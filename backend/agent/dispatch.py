"""Araç çağrısı -> gerçek eylem.

`computer_toolset_20260801` üye araçlarını Windows eylemlerine çeviriyor.
Koordinatlar modelden ekran görüntüsü uzayında gelir; buradan çıkarken aktif
ekranın ofsetiyle sanal masaüstü uzayına dönüşürler. Çeviri tek noktada
kalsın diye başka hiçbir modül `to_virtual` çağırmıyor.
"""

from __future__ import annotations

import base64
import io
import os
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..mcp.istemci import McpHatasi, McpYonetici
from ..computer import apps
from ..computer import files
from ..computer import input as kb
from ..computer import uia
from ..computer import windows as win
from ..computer.capture import ScreenCapture
from ..computer.displays import DisplayMap, model_noktasini_buyut
from ..computer.kayit import EkranKaydi, KayitHatasi
from ..computer.masaustu import Calisma, MasaustuHatasi, pencere_bilgisi
from ..computer.mesaj import DesteklenmiyorHatasi, Girdi
from ..computer.terminal import TerminalError, TerminalRegistry
from ..office.sheet import SheetError, Workbook
from ..office.store import OfficeError, OfficeStore
from ..office.text import TextError
from . import kuru as kuru_mod
from ..safety import gate
from ..safety.killswitch import KillSwitch
from ..remote.ssh import RemoteError, SshHost, SshSession
from ..skills.api import Ortam
from ..skills.panel import PanelError, normalise, to_text
from ..skills.registry import SkillError, SkillRegistry
from ..skills.shortcuts import Shortcut, ShortcutError, ShortcutStore
from ..workflows.depo import Adim, Akis, AkisDeposu, AkisHatasi, kaydedilir
from ..workflows.imza import noktada as imza_noktada
from ..workflows.oynatici import KOORDINATLI, oynat

#: Ekran görüntüsü döndüren üyeler — sonuçları metin değil görsel bloktur.
VISUAL_MEMBERS = {"screenshot", "zoom"}

_CLICK_COUNTS = {"left_click": 1, "double_click": 2, "triple_click": 3}
_CLICK_BUTTONS = {"left_click": "left", "right_click": "right", "middle_click": "middle"}


class ToolError(RuntimeError):
    """Araç çalıştırılamadı — modele `is_error` olarak döner."""


class Denied(ToolError):
    """Berkay eylemi reddetti. Modele hata olarak döner ki başka yol denesin."""


@dataclass
class ToolOutcome:
    """Bir araç çağrısının sonucu."""

    content: str | list[dict[str, Any]]
    is_error: bool = False
    #: Eylem **sonrası** doğrulamanın sonucu: `dogrulandi` / `varsayildi` /
    #: `dogrulanamadi`, ya da doğrulanmayan araçta `None`.
    #:
    #: Buraya `Dispatcher` yazmıyor — işleyiciler sonuçlarını ancak "çağrı
    #: patlamadı" düzeyinde biliyor; tutan bir tıklamayla tutmayanı ayıran
    #: şey makinenin durumu ve onu okuyup yazan taraf döngü (`loop.py`).
    #: Sayısal iş doğrulamada değil, doğru tarafta: burası yalnızca kayıt.
    dogrulama: str | None = None


def _image_block(data: bytes, media_type: str) -> list[dict[str, Any]]:
    return [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.standard_b64encode(data).decode("ascii"),
            },
        }
    ]


class Dispatcher:
    """Aktif ekranı ve yakalayıcıyı tutan araç çalıştırıcısı."""

    def __init__(
        self,
        displays: DisplayMap,
        capture: ScreenCapture,
        kill: KillSwitch,
        approve: Callable[[str, str, str], bool] | None = None,
        active_index: int = 0,
    ) -> None:
        self.displays = displays
        self.capture = capture
        self.kill = kill
        # Onay isteyici verilmezse her riskli eylem reddedilir. Varsayılan
        # "izin ver" olsaydı, onay kancasını bağlamayı unutan bir çağıran
        # kapıyı sessizce kapatmış olurdu.
        self.approve = approve or (lambda _n, _d, _r: False)
        self.active_index = active_index
        #: Kuru koşu. Açıkken dünyayı değiştiren her araç çalışmadan
        #: geri dönüyor; salt okunur olanlar çalışıyor ki plan gerçek
        #: duruma bakarak yapılsın.
        self.kuru = False
        self.terminals = TerminalRegistry()
        self.office = OfficeStore()
        # Yerleşik araç adları rezerve: bir yetenek `run_shell` adını alıp
        # kabuk çağrılarını sessizce ele geçiremesin.
        from .tools import CUSTOM_TOOL_NAMES

        builtin = {m[4:] for m in dir(self) if m.startswith("_do_")}
        self.skills = SkillRegistry(reserved=frozenset(builtin | CUSTOM_TOOL_NAMES))
        self.buttons = ShortcutStore()
        self.remote: SshSession | None = None
        #: Yan çalışma alanı — ilk kullanımda açılıyor. Masaüstü nesnesi
        #: ucuz değil ve ajanların çoğu oturumu ona hiç dokunmadan bitiyor.
        self.side: Calisma | None = None
        self.side_input = Girdi()
        #: Ajanın en son dokunduğu yan pencere. Canlı görüntü bunu
        #: işaretliyor: bakan kişinin ilk sorusu "şu an nerede".
        self.last_side_hwnd = 0
        #: Yan alanın son karesi, arayüz için. Modele gitmiyor — her
        #: eylemde kare göndermek tur başına ~1500 görsel token ve
        #: model zaten nereye tıkladığını biliyor. Berkay bilmiyor.
        self.last_side_frame: bytes | None = None
        #: Yan masanın ekran kaydı. ffmpeg süreci ancak `record_start`
        #: çağrılınca doğuyor; nesnenin kendisi bedava.
        self.ekran_kaydi = EkranKaydi()
        #: (yetenek adı, panel) — arayüzün alıp çizeceği son panel.
        self.last_panel: tuple[str, dict] | None = None
        #: Son yazılan dosyalar — arayüz kod panelini bunlardan açıyor.
        self.last_files: list[str] = []
        self.akislar = AkisDeposu()
        #: Dış MCP sunucuları. Kurulmuş oluyor ama **başlatılmıyor**:
        #: `Agent` başlatıyor, çünkü bir MCP sunucusu senin makinende
        #: senin haklarınla çalışan bir süreç ve testlerde bir
        #: `Dispatcher` kurmanın yan etkisi olmamalı.
        self.mcp = McpYonetici()
        #: Bu turda dünyayı değiştiren adımlar. `workflow_save` bunu
        #: kaydediyor. Denetim kaydı bu iş için kullanılamıyor: oradaki
        #: girdiler 200 karakterde kırpılıyor ve kırpılmış bir komutu
        #: oynatmak, komutun yarısını çalıştırmak olurdu.
        self._tur_adimlari: list[Adim] = []
        #: Akış oynatılırken açık. Oynanan adımların yeniden
        #: kaydedilmesini engelliyor.
        self._oynatiyor = False
        self._tur_talimati = ""

    def shutdown(self) -> None:
        """Açık PTY'leri kapatır. Yoksa süreçler ajan bittikten sonra yaşar."""
        # Kayıt ilk sırada: ffmpeg'e `q` yazıp beklemek mp4'ü
        # oynatılabilir bırakıyor, sonraki adımlar masaüstünü kapatıp
        # kaydedilen pencereyi altından çekiyor.
        self.ekran_kaydi.kapat()
        self.terminals.close_all()
        # MCP sunucuları da süreç: kapatılmazlarsa uygulama kapandıktan
        # sonra arkada `node` süreçleri kalıyor.
        self.mcp.durdur()
        if self.side is not None:
            # Yan alandaki süreçler görünmez; kapatılmazlarsa hiç kimsenin
            # fark etmediği bir Chrome bellekte yaşamaya devam ediyor.
            self.side.kapat()
            self.side = None

    @property
    def active(self):
        return self.displays[self.active_index]

    def _virtual(self, coordinate: Any) -> tuple[int, int]:
        if not (isinstance(coordinate, (list, tuple)) and len(coordinate) == 2):
            raise ToolError(f"coordinate must be [x, y], got: {coordinate!r}")
        x, y = int(coordinate[0]), int(coordinate[1])
        try:
            return self.active.to_virtual(x, y)
        except ValueError as exc:
            raise ToolError(str(exc)) from None

    def run(self, name: str, payload: dict[str, Any]) -> ToolOutcome:
        """Tek bir araç çağrısını çalıştırır."""
        self.kill.check()
        if self.kuru and not kuru_mod.serbest(name):
            # Kesme noktası burası, `_do_*` içleri değil: her aracın
            # başına bir kontrol koymak, bir tanesini unutmanın kesin
            # yolu olurdu. Yetenekler de buradan geçiyor.
            return ToolOutcome(content=kuru_mod.not_metni(name, payload))
        handler = getattr(self, f"_do_{name}", None)
        if handler is None:
            skill = self.skills.get(name)
            if skill is not None:
                sonuc = self._run_skill(skill, payload)
                self._adimi_kaydet(name, payload, None, sonuc)
                return sonuc
            if self.mcp.bilir(name):
                sonuc = self._run_mcp(name, payload)
                self._adimi_kaydet(name, payload, None, sonuc)
                return sonuc
            raise ToolError(f"Unknown tool: {name}")

        self._gate(name, payload)
        # İmza eylemden **önce** alınıyor: tıklamadan sonra ekran değişmiş
        # oluyor ve o noktadaki denetim artık başka bir şey.
        imza = self._imza(name, payload)
        sonuc = handler(payload)
        self._adimi_kaydet(name, payload, imza, sonuc)
        return sonuc

    # --- akış kaydı -------------------------------------------------------

    def tur_basladi(self, talimat: str = "") -> None:
        """Yeni tur: kayıt tamponu boşalıyor.

        `workflow_save` "bu turda ne yaptın" diyor; tampon turlar arası
        taşınsaydı iki turluk bir dizi tek akış olarak kaydedilirdi.

        Talimat da saklanıyor: kaydedilen akışın hangi cümleden doğduğunu
        bilmek, aylar sonra listeye bakınca onu tanımanın tek yolu.
        """
        self._tur_adimlari = []
        self._tur_talimati = talimat

    @property
    def son_adimlar(self) -> list[Adim]:
        return list(self._tur_adimlari)

    def _imza(self, name: str, payload: dict[str, Any]):
        """Tıklanan denetimin kimliği. Alınamıyorsa `None`.

        Yalnızca koordinatlı araçlarda ve yalnızca kayıt açıkken. Ölçüldü:
        `ControlFromPoint` normal bir pencerede ~6 ms, oyunda ve
        yükseltilmiş pencerede erişim reddiyle düşüyor.
        """
        if self.kuru or self._oynatiyor or name not in KOORDINATLI:
            return None
        nokta = payload.get("coordinate")
        if not isinstance(nokta, (list, tuple)) or len(nokta) != 2:
            return None
        try:
            return imza_noktada(*self._virtual(nokta))
        except Exception:
            return None

    def _adimi_kaydet(self, name: str, payload: dict[str, Any], imza,
                      sonuc: ToolOutcome) -> None:
        if self.kuru or self._oynatiyor or sonuc.is_error:
            return
        # Bakan araçlar kaydedilmiyor: oynatmada karar veren yok ve
        # yirmi ekran görüntüsü almak hem yavaş hem anlamsız olurdu.
        if not kaydedilir(name):
            return
        if len(self._tur_adimlari) < 500:
            self._tur_adimlari.append(
                Adim(arac=name, girdi=dict(payload), imza=imza)
            )

    def _run_skill(self, skill, payload: dict[str, Any]) -> ToolOutcome:
        """Yeteneği çalıştırır.

        Yeteneğin fırlattığı istisna ajanı düşürmüyor; modele hata olarak
        dönüyor ki ajan kendi yazdığı kodu düzeltebilsin. Bu, yeteneklerin
        yararlı olmasının asıl yolu: ilk deneme tutmaz, ikinci tutar.
        """
        if skill.needs_approval and not self.approve(
            skill.name, str(payload)[:400], f"the {skill.name} skill is asking for approval"
        ):
            raise Denied(f"The user rejected the {skill.name} skill.")
        try:
            result = skill.run(dict(payload), Ortam(self))
        except Denied:
            raise
        except Exception as exc:
            raise ToolError(
                f"{skill.name} raised while running — {type(exc).__name__}: {exc}. "
                f"The code is at {skill.path}. You can fix it with skill_write."
            ) from None
        # Yetenek panel döndürebiliyor: `{"panel": {...}}`. Panel arayüze
        # gidiyor, metin karşılığı modele. İkisi ayrılmazsa ajan kullanıcıya
        # gösterdiği şeyi bilmiyor ve bir sonraki cümlesinde çelişiyor.
        try:
            panel = normalise(result)
        except PanelError as exc:
            raise ToolError(
                f"{skill.name} returned an invalid panel: {exc}. "
                f"Fix it with skill_write."
            ) from None
        if panel is not None:
            self.last_panel = (skill.name, panel)
            metin = str(result.get("metin") or "").strip()
            return ToolOutcome(content=metin or to_text(panel))
        return ToolOutcome(content=str(result) if result is not None else "OK")

    def _hedef_etiketi(self, name: str, payload: dict[str, Any]) -> str:
        """Tıklanacak denetimin UIA etiketi. Okunamıyorsa boş dize.

        Okunamadığında güvenli taraf SAFE: UIA'nın sustuğu yerde (oyun,
        tuval, yükseltilmiş pencere) her tıklamaya onay sormak, sıradan
        bir tıklamayı sürekli onaya düşürür ve yorgunluk kapıyı işlevsiz
        kılar; pencere başlığı süzgeci o yerlerde yine çalışıyor.
        """
        if name not in gate.CLICK_TOOLS:
            return ""
        nokta = payload.get("coordinate")
        try:
            if nokta is None:
                # Koordinatsız tıklama imlecin durduğu yere gidiyor;
                # etiket oradan okunuyor.
                vx, vy = kb.cursor_position()
            elif isinstance(nokta, (list, tuple)) and len(nokta) == 2:
                vx, vy = self._virtual(nokta)
            else:
                return ""
            imza = imza_noktada(vx, vy)
        except Exception:
            # Ölü COM, erişim reddi, kırpılmış koordinat: hepsi normal,
            # etiketsiz karar kapıyı düşürmemeli. Koordinat gerçekten
            # bozuksa işleyici kendi hatasını zaten verecek.
            return ""
        return imza.ad if imza is not None else ""

    def _gate(self, name: str, payload: dict[str, Any]) -> None:
        """Riskli eylemde onay ister. Onay yoksa eylem hiç çalışmaz."""
        verdict = gate.classify(
            name,
            payload,
            window_title=win.foreground_title(),
            label=self._hedef_etiketi(name, payload),
        )
        if not verdict.needs_confirmation:
            return

        detail = payload.get("command") or payload.get("text") or str(payload)
        if not self.approve(name, str(detail)[:400], verdict.reason):
            raise Denied(f"The user declined ({verdict.reason}). This action was not run.")




    def _do_heads_up(self, payload: dict[str, Any]) -> ToolOutcome:
        """Kullanıcıya not. Makinede hiçbir şey yapmıyor.

        Notun kendisi arayüze `on_action` üzerinden gidiyor — girdi
        eylemden **önce** yayılıyor ve bir uyarının uyardığı işten sonra
        görünmesi anlamsız olurdu. Burada yapılan tek şey modele notun
        yerine ulaştığını söylemek.
        """
        _require(payload, "note")
        return ToolOutcome(
            content="The note is on the user's screen. Carry on."
        )

    # --- MCP --------------------------------------------------------------

    def _run_mcp(self, name: str, payload: dict[str, Any]) -> ToolOutcome:
        """Bir MCP aracını çalıştırır — **her çağrıda onay isteyerek**.

        Berkay böyle seçti ve gerekçesi sağlam: MCP sunucusu üçüncü
        tarafın kodu, araç tanımı modelin promptuna giriyor ve taranan
        sunucuların üçte birinde kritik açık bulundu. Yerleşik araçlarda
        kapı yalnızca riskli görünen çağrılarda açılıyor; burada her
        çağrıda.

        Bedeli onay yorgunluğu ve o gerçek bir risk: bir noktada okumadan
        onaylanır. Buna karşı onay metni **bilgilendirici**: hangi
        sunucu, aracın kendi tanımı, ve tanımda talimat gibi duran bir
        şey varsa uyarısı.
        """
        gerekce = self.mcp.anlat(name)
        uyarilar = self.mcp.uyarilar(name)
        if uyarilar:
            gerekce += "  [warning: " + "; ".join(uyarilar) + "]"
        if not self.approve(name, str(payload)[:400], gerekce):
            raise Denied(f"The user did not approve {name}.")
        try:
            icerik, hatali = self.mcp.cagir(name, payload)
        except McpHatasi as exc:
            raise ToolError(str(exc)) from None
        return ToolOutcome(content=icerik, is_error=hatali)

    # --- akışlar ----------------------------------------------------------

    def _do_workflow_save(self, payload: dict[str, Any]) -> ToolOutcome:
        _require(payload, "name", "label")
        adimlar = self.son_adimlar
        try:
            akis = self.akislar.kaydet(Akis(
                ad=str(payload["name"]),
                etiket=str(payload["label"]),
                talimat=self._tur_talimati,
                adimlar=adimlar,
            ))
        except AkisHatasi as exc:
            raise ToolError(str(exc)) from None
        return ToolOutcome(
            content=(
                f"Saved {akis.etiket!r} as {akis.ad} with "
                f"{akis.adim_sayisi} steps. Replay it with "
                f"workflow_run(name={akis.ad!r}) — it costs nothing."
            )
        )

    def _do_workflow_list(self, _payload: dict[str, Any]) -> ToolOutcome:
        akislar = self.akislar.hepsi()
        if not akislar:
            return ToolOutcome(
                content="No workflows are saved yet."
            )
        satirlar = [
            f"{a.ad}  {a.etiket!r}  {a.adim_sayisi} steps"
            for a in akislar
        ]
        return ToolOutcome(content="\n".join(satirlar))

    def _do_workflow_remove(self, payload: dict[str, Any]) -> ToolOutcome:
        _require(payload, "name")
        ad = str(payload["name"])
        if not self.akislar.sil(ad):
            raise ToolError(f"There is no workflow called {ad!r}.")
        return ToolOutcome(content=f"The {ad} workflow was removed.")

    def _do_workflow_run(self, payload: dict[str, Any]) -> ToolOutcome:
        _require(payload, "name")
        ad = str(payload["name"])
        akis = self.akislar.al(ad)
        if akis is None:
            raise ToolError(
                f"There is no workflow called {ad!r}. "
                f"workflow_list shows the saved ones."
            )
        sonuc = self.calistir(akis)
        if not sonuc.basarili:
            # Hata olarak dönüyor: ajan kaldığı yerden elle devam
            # edebilsin. Başarı gibi dönseydi yarım kalan işi bitmiş
            # sanardı.
            raise ToolError(sonuc.anlat())
        return ToolOutcome(content=sonuc.anlat())

    def calistir(self, akis: Akis, on_step=None, on_result=None):
        """Akışı oynatır. Arayüz de buradan çağırıyor — modele uğramadan."""
        self._oynatiyor = True
        try:
            return oynat(akis, self, on_step, on_result)
        finally:
            self._oynatiyor = False

    # --- yetenekler -------------------------------------------------------

    def _do_skill_list(self, payload: dict[str, Any]) -> ToolOutcome:
        name = payload.get("name")
        if name:
            try:
                return ToolOutcome(content=self.skills.read(str(name)))
            except SkillError as exc:
                raise ToolError(str(exc)) from None
        return ToolOutcome(content=self.skills.report())

    def _do_skill_write(self, payload: dict[str, Any]) -> ToolOutcome:
        _require(payload, "name", "code", "why")
        name, code = str(payload["name"]), str(payload["code"])
        # Onay ekranında kodun tamamı görünüyor: neyin kurulduğunu görmeden
        # onaylamak, onay olmamasıyla aynı şey.
        detail = f"{name}.py\n\n{code}"
        if not self.approve("skill_write", detail, str(payload["why"])):
            raise Denied(f"The user did not approve the {name} skill.")
        try:
            skill = self.skills.write(name, code)
        except SkillError as exc:
            raise ToolError(f"Could not install the skill: {exc}") from None
        return ToolOutcome(
            content=f"{skill.name} installed and loaded — {skill.path}. "
            f"You can call it on the next step."
        )

    def _do_skill_remove(self, payload: dict[str, Any]) -> ToolOutcome:
        _require(payload, "name", "why")
        name = str(payload["name"])
        if not self.approve("skill_remove", f"{name}.py siliniyor", str(payload["why"])):
            raise Denied(f"The user did not approve removing the {name} skill.")
        try:
            path = self.skills.remove(name)
        except SkillError as exc:
            raise ToolError(str(exc)) from None
        return ToolOutcome(content=f"{path.name} silindi.")

    def _do_button_write(self, payload: dict[str, Any]) -> ToolOutcome:
        _require(payload, "name", "label", "instruction", "why")
        shortcut = Shortcut(
            name=str(payload["name"]),
            label=str(payload["label"]),
            instruction=str(payload["instruction"]),
            glyph=str(payload.get("glyph") or "yetenek"),
        )
        # Düğme Berkay'ın arayüzünü değiştiriyor; sessizce eklenmemeli.
        detail = f"{shortcut.label} -> {shortcut.instruction}"
        if not self.approve("button_write", detail, str(payload["why"])):
            raise Denied(f"The user did not approve the {shortcut.name} button.")
        try:
            self.buttons.save(shortcut)
        except ShortcutError as exc:
            raise ToolError(str(exc)) from None
        return ToolOutcome(
            content=f"The {shortcut.label!r} button is on the bar. The user can edit or delete it."
        )

    def _do_button_remove(self, payload: dict[str, Any]) -> ToolOutcome:
        _require(payload, "name", "why")
        name = str(payload["name"])
        if not self.approve("button_remove", f"removing the {name} button", str(payload["why"])):
            raise Denied(f"The user did not approve removing the {name} button.")
        try:
            self.buttons.remove(name)
        except ShortcutError as exc:
            raise ToolError(str(exc)) from None
        return ToolOutcome(content=f"The {name} button was removed.")

    # --- uzak makine ------------------------------------------------------

    def _remote_session(self) -> SshSession:
        """Bağlı sunucu.

        Adı `_session` idi ve sınıfta terminal oturumu için zaten bir
        `_session` vardı; sonra tanımlanan öncekini eziyordu ve bütün
        `remote_*` araçları "missing 1 required positional argument"
        hatasıyla düşüyordu. Python bu çakışmayı sessizce kabul ediyor.
        """
        if self.remote is None or not self.remote.connected:
            raise ToolError(
                "You are not connected to a server. Call remote_connect first "
                "(for the user's own server, alias=\"brky\")."
            )
        return self.remote

    def _do_remote_connect(self, payload: dict[str, Any]) -> ToolOutcome:
        host = SshHost(
            alias=str(payload.get("alias", "")).strip(),
            host=str(payload.get("host", "")).strip(),
            user=str(payload.get("user", "") or "root").strip(),
            port=int(payload.get("port") or 22),
        )
        if not host.alias and not host.host:
            raise ToolError("alias ya da host gerekli")
        session = SshSession(host)
        try:
            banner = session.connect()
        except RemoteError as exc:
            raise ToolError(str(exc)) from None
        self.remote = session
        return ToolOutcome(
            content=f"Connected: {banner}\nWorking directory: {session.cwd}"
        )

    def _do_remote_list(self, payload: dict[str, Any]) -> ToolOutcome:
        session = self._remote_session()
        path = str(payload.get("path") or session.cwd)
        try:
            entries = session.enter(path)
        except RemoteError as exc:
            raise ToolError(str(exc)) from None
        if not entries:
            return ToolOutcome(content=f"{path} is empty.")
        lines = [f"{path}:"]
        for entry in entries:
            kind = "d" if entry.is_dir else "-"
            lines.append(
                f"  {kind} {entry.mode} {entry.size_label:>9} "
                f"{entry.modified}  {entry.name}"
            )
        return ToolOutcome(content="\n".join(lines))

    def _do_remote_read(self, payload: dict[str, Any]) -> ToolOutcome:
        _require(payload, "path")
        try:
            return ToolOutcome(content=self._remote_session().read(str(payload["path"])))
        except RemoteError as exc:
            raise ToolError(str(exc)) from None

    def _do_remote_write(self, payload: dict[str, Any]) -> ToolOutcome:
        _require(payload, "path", "content", "why")
        session = self._remote_session()
        path, content = str(payload["path"]), str(payload["content"])
        # Uzak yazma her zaman soruluyor ve onay ekranında hangi sunucu
        # olduğu yazıyor: iki sunucuya bağlıyken hangisine yazdığını
        # bilmemek, yanlış makineyi bozmanın en kolay yolu.
        detail = f"{session.host.label}:{path}\n\n{content[:2000]}"
        if not self.approve("remote_write", detail, str(payload["why"])):
            raise Denied(f"The user rejected writing {path}.")
        try:
            return ToolOutcome(content=session.write(path, content))
        except RemoteError as exc:
            raise ToolError(str(exc)) from None

    def _do_remote_run(self, payload: dict[str, Any]) -> ToolOutcome:
        _require(payload, "command")
        session = self._remote_session()
        command = str(payload["command"])
        verdict = gate.classify_remote(command)
        if verdict.needs_confirmation and not self.approve(
            "remote_run", f"{session.host.label}$ {command}", verdict.reason
        ):
            raise Denied(f"Berkay reddetti ({verdict.reason}).")
        try:
            out = session.run(command, timeout=int(payload.get("timeout") or 60))
        except RemoteError as exc:
            raise ToolError(str(exc)) from None
        return ToolOutcome(content=out.strip() or "(no output)")

    # --- görsel -----------------------------------------------------------

    # --- yan çalışma alanı ------------------------------------------------

    def _side(self) -> Calisma:
        if self.side is None:
            self.side = Calisma()
            self.side.ac()
        return self.side

    def _side_pencere(self, payload: dict[str, Any]):
        """Modelin verdiği hwnd'yi doğrular.

        Doğrulamanın nedeni: hwnd bir tamsayı ve model uydurabilir. Yan
        alanda olmayan bir tutamaca ileti göndermek, kötü ihtimalle
        Berkay'ın gerçek penceresine tıklamak demek — kaçınılan şeyin
        tam olarak kendisi.
        """
        try:
            hwnd = int(payload.get("hwnd"))
        except (TypeError, ValueError):
            raise ToolError("hwnd must be an integer; get it from side_windows.") from None
        if hwnd not in {p.hwnd for p in self._side().pencereler()}:
            raise ToolError(
                f"{hwnd} is not in the side workspace. Get a fresh list "
                "with side_windows."
            )
        self.last_side_hwnd = hwnd
        return pencere_bilgisi(hwnd)

    def _do_side_launch(self, payload: dict[str, Any]) -> ToolOutcome:
        _require(payload, "command")
        try:
            pid = self._side().baslat(str(payload["command"]))
        except MasaustuHatasi as exc:
            raise ToolError(str(exc)) from None
        return ToolOutcome(
            content=f"Launched in the side desk, pid {pid}. The window can take a "
            "couple of seconds; check with side_windows."
        )

    def _do_side_windows(self, _payload: dict[str, Any]) -> ToolOutcome:
        pencereler = self._side().pencereler()
        if not pencereler:
            return ToolOutcome(
                content="No windows in the side desk. If you just launched one, wait "
                "a second or two; Store apps never open a window here."
            )
        satirlar = [
            f"{p.hwnd}  {p.en}x{p.boy}  [{p.sinif}]  {p.baslik or '(untitled)'}"
            for p in pencereler
        ]
        return ToolOutcome(content="\n".join(satirlar))

    def _side_kare(self, hwnd: int):
        """Yan alandan imleci çizilmiş bir kare."""
        girdi = self.side_input
        return self._side().yakala(
            hwnd,
            imlec=(girdi.imlec.x, girdi.imlec.y),
            iz=list(girdi.iz)[:-1],  # son nokta okun kendisi; iki kez çizme
            tik=girdi.son_tik,
        )

    def _do_side_capture(self, payload: dict[str, Any]) -> ToolOutcome:
        pencere = self._side_pencere(payload)
        try:
            frame = self._side_kare(pencere.hwnd)
        except MasaustuHatasi as exc:
            raise ToolError(str(exc)) from None
        self.last_side_frame = frame.to_png()
        return ToolOutcome(content=_image_block(*frame.encode()))

    def _do_side_act(self, payload: dict[str, Any]) -> ToolOutcome:
        pencere = self._side_pencere(payload)
        action = str(payload.get("action") or "").strip()
        girdi = self.side_input

        def nokta() -> tuple[int, int]:
            c = payload.get("coordinate")
            if not (isinstance(c, (list, tuple)) and len(c) == 2):
                raise ToolError(f"{action} needs coordinate [x, y].")
            # Model pencereye göre konuşuyor **ve** pencere karesi küçültme
            # gerektirmiş olabilir (2576 px kenarı ya da token bütçesini
            # aşan bir pencere). Önce model uzayından fiziksel piksele,
            # sonra masaüstü uzayına. Dönüşüm monitör yoluyla aynı
            # fonksiyondan: `model_noktasini_buyut`.
            gercek_x, gercek_y = model_noktasini_buyut(
                int(c[0]), int(c[1]), pencere.en, pencere.boy
            )
            return pencere.x + gercek_x, pencere.y + gercek_y

        try:
            if action in ("click", "right_click", "double_click"):
                x, y = nokta()
                girdi.tikla(pencere.hwnd, x, y,
                            sag=action == "right_click",
                            cift=action == "double_click")
                return ToolOutcome(content=f"OK — ajan imleci ({x}, {y})")
            if action == "type":
                metin = payload.get("text")
                if not metin:
                    raise ToolError("type needs text.")
                girdi.yaz(str(metin))
                return ToolOutcome(content="OK")
            if action == "key":
                girdi.tus(str(payload.get("text") or ""))
                return ToolOutcome(content="OK")
            if action == "scroll":
                x, y = nokta()
                girdi.kaydir(pencere.hwnd, x, y, int(payload.get("amount") or -3))
                return ToolOutcome(content="OK")
        except DesteklenmiyorHatasi as exc:
            raise ToolError(str(exc)) from None
        finally:
            # Eylem başarısız olsa da kare çekiliyor: hata anındaki
            # ekran, hatanın kendisinden daha çok şey anlatıyor.
            self._side_kare_yenile(pencere.hwnd)
        raise ToolError(f"Unknown action: {action!r}")

    def _side_kare_yenile(self, hwnd: int) -> None:
        """Arayüzün göreceği kareyi tazeler. Hata yutuluyor.

        Yakalama, ajanın işini bozacak bir şey değil — sadece görüntü.
        Pencere o arada kapandıysa eylem sonucu yine de dönmeli.
        """
        try:
            self.last_side_frame = self._side_kare(hwnd).to_png()
        except Exception:
            self.last_side_frame = None

    # --- ekran kaydı ------------------------------------------------------

    def _do_record_start(self, payload: dict[str, Any]) -> ToolOutcome:
        """Yan masadaki bir pencerenin kaydını başlatır.

        `hwnd` verilmezse ajanın en son dokunduğu pencere kullanılıyor.
        Hiç dokunmadıysa ve yan masada tek pencere varsa o. İkisi de yoksa
        hata: bir pencere seçmek modelin işi, tahmin etmek yanlış işi
        kaydetmenin en kolay yolu.
        """
        hwnd = payload.get("hwnd") or self.last_side_hwnd
        if not hwnd:
            pencereler = self._side().pencereler()
            if len(pencereler) == 1:
                hwnd = pencereler[0].hwnd
        if not hwnd:
            raise ToolError(
                "Nothing to record yet. Launch something with side_launch, "
                "then pick a window with side_windows."
            )
        try:
            hedef = self.ekran_kaydi.basla(hwnd=int(hwnd))
        except KayitHatasi as exc:
            raise ToolError(str(exc)) from None
        self.last_side_hwnd = int(hwnd)
        return ToolOutcome(
            content=f"Recording window {int(hwnd)} to {hedef}. "
            "Call record_stop when the job is done."
        )

    def _do_record_stop(self, _payload: dict[str, Any]) -> ToolOutcome:
        try:
            hedef = self.ekran_kaydi.durdur()
        except KayitHatasi as exc:
            raise ToolError(str(exc)) from None
        if hedef is None:
            return ToolOutcome(content="Nothing was being recorded.")
        return ToolOutcome(
            content=f"Recording saved: {hedef} ({self.ekran_kaydi.sure:.1f}s)."
        )

    def _do_side_close(self, _payload: dict[str, Any]) -> ToolOutcome:
        # Kayıt önce duruyor: masaüstü kapanınca kaydedilen pencere de
        # gidiyor ve o noktada ffmpeg'in yazacağı bir şey kalmıyor.
        self.ekran_kaydi.kapat()
        if self.side is None:
            return ToolOutcome(content="The side desk is already closed.")
        self.side.kapat()
        self.side = None
        self.side_input = Girdi()
        return ToolOutcome(content="Side desk closed, its processes were terminated.")

    # --- ekran görüntüsü ---------------------------------------------------

    def _do_screenshot(self, _payload: dict[str, Any]) -> ToolOutcome:
        frame = self.capture.grab(self.active)
        return ToolOutcome(content=_image_block(*frame.encode()))

    def _do_zoom(self, payload: dict[str, Any]) -> ToolOutcome:
        region = payload.get("region")
        if not (isinstance(region, (list, tuple)) and len(region) == 4):
            raise ToolError(f"region must be [x0, y0, x1, y1], got: {region!r}")

        # Taze yakalama: model bölgeyi büyütmek istediğinde ilgilendiği şey
        # ekranın şu anki hali. Eski kareden kırpmak, aradan geçen sürede
        # değişmiş bir arayüzü değişmemiş gibi göstermek olurdu.
        frame = self.capture.grab(self.active)
        try:
            crop = frame.crop(tuple(int(v) for v in region))
        except ValueError as exc:
            raise ToolError(str(exc)) from None

        buffer = io.BytesIO()
        crop.save(buffer, format="WEBP", lossless=True, method=0)
        return ToolOutcome(content=_image_block(buffer.getvalue(), "image/webp"))

    # --- fare -------------------------------------------------------------

    def _click(self, name: str, payload: dict[str, Any]) -> ToolOutcome:
        coordinate = payload.get("coordinate")
        with kb.modifiers_held(payload.get("text")):
            if coordinate is None:
                vx, vy = kb.cursor_position()
            else:
                vx, vy = self._virtual(coordinate)
            kb.click(vx, vy, button=_CLICK_BUTTONS.get(name, "left"),
                     count=_CLICK_COUNTS.get(name, 1))
        return ToolOutcome(content="OK")

    def _do_left_click(self, payload): return self._click("left_click", payload)
    def _do_right_click(self, payload): return self._click("right_click", payload)
    def _do_middle_click(self, payload): return self._click("middle_click", payload)
    def _do_double_click(self, payload): return self._click("double_click", payload)
    def _do_triple_click(self, payload): return self._click("triple_click", payload)

    def _do_mouse_move(self, payload: dict[str, Any]) -> ToolOutcome:
        kb.move_to(*self._virtual(payload.get("coordinate")))
        return ToolOutcome(content="OK")

    def _do_left_mouse_down(self, _payload) -> ToolOutcome:
        kb.mouse_down("left")
        return ToolOutcome(content="OK")

    def _do_left_mouse_up(self, _payload) -> ToolOutcome:
        kb.mouse_up("left")
        return ToolOutcome(content="OK")

    def _do_cursor_position(self, _payload) -> ToolOutcome:
        vx, vy = kb.cursor_position()
        display = self.displays.locate_virtual(vx, vy)
        if display is None:
            return ToolOutcome(content="The cursor is not over any display")
        x, y = display.from_virtual(vx, vy)
        return ToolOutcome(content=f"[{x}, {y}] (ekran {display.index})")

    def _do_left_click_drag(self, payload: dict[str, Any]) -> ToolOutcome:
        start = payload.get("start_coordinate")
        end = payload.get("coordinate")
        if start is None or end is None:
            raise ToolError("left_click_drag hem start_coordinate hem coordinate ister")
        with kb.modifiers_held(payload.get("text")):
            kb.drag(self._virtual(start), self._virtual(end))
        return ToolOutcome(content="OK")

    def _do_scroll(self, payload: dict[str, Any]) -> ToolOutcome:
        direction = payload.get("scroll_direction")
        amount = int(payload.get("scroll_amount", 3))
        coordinate = payload.get("coordinate")
        at = self._virtual(coordinate) if coordinate is not None else None
        with kb.modifiers_held(payload.get("text")):
            try:
                kb.scroll(direction, amount, at=at)
            except ValueError as exc:
                raise ToolError(str(exc)) from None
        return ToolOutcome(content="OK")

    # --- klavye ve zamanlama ----------------------------------------------

    def _do_type(self, payload: dict[str, Any]) -> ToolOutcome:
        text = payload.get("text")
        if not isinstance(text, str):
            raise ToolError(f"type needs text, got: {text!r}")
        kb.type_text(text)
        return ToolOutcome(content="OK")

    def _do_key(self, payload: dict[str, Any]) -> ToolOutcome:
        combo = payload.get("text")
        if not isinstance(combo, str) or not combo.strip():
            # Eksik alanda ham bir AttributeError dönüyordu; modele de
            # yeteneğe de neyin eksik olduğunu söylemiyordu.
            raise ToolError(
                f"key needs a key — put a combination like 'ctrl+k' in the "
                f"kombinasyon yaz. Gelen: {combo!r}"
            )
        repeat = int(payload.get("repeat", 1))
        try:
            kb.press(combo, repeat=repeat)
        except ValueError as exc:
            raise ToolError(str(exc)) from None
        return ToolOutcome(content="OK")

    def _do_hold_key(self, payload: dict[str, Any]) -> ToolOutcome:
        duration = _duration(payload.get("duration"))
        try:
            kb.hold(payload.get("text"), duration)
        except ValueError as exc:
            raise ToolError(str(exc)) from None
        return ToolOutcome(content="OK")

    def _do_wait(self, payload: dict[str, Any]) -> ToolOutcome:
        duration = _duration(payload.get("duration"))
        # Beklerken de acil durdurmaya cevap vermeli — 300 saniyelik bir
        # `sleep` Esc'yi 5 dakika sağır eder.
        _interruptible_sleep(duration, self.kill)
        return ToolOutcome(content="OK")

    # --- özel araçlar -----------------------------------------------------

    def _do_read_ui_tree(self, _payload: dict[str, Any]) -> ToolOutcome:
        result = uia.snapshot(self.active)
        if result.thin:
            return ToolOutcome(
                content=(
                    f"{result.text}\n\n"
                    "The tree is shallow — this window exposes no accessibility "
                    "information. Take a screenshot."
                )
            )
        return ToolOutcome(content=result.text)

    def _do_launch_app(self, payload: dict[str, Any]) -> ToolOutcome:
        target = str(payload.get("target", "")).strip()
        if not target:
            raise ToolError("launch_app needs target")
        arguments = str(payload.get("arguments", "")).strip()

        before = win.foreground_title()
        try:
            if target.startswith(("http://", "https://")):
                os.startfile(target)
                expect = None
            else:
                # Önce PATH, sonra kurulu uygulamalar kataloğu. Windows'ta
                # uygulamaların çoğu PATH'te değil: on yedi yaygın
                # uygulamadan on ikisi yalnızca `which` ile bulunamıyordu.
                yol = shutil.which(target)
                app = None
                if yol is None and not os.path.exists(target):
                    app = apps.resolve(target)
                    if app is None:
                        yakin = apps.suggest(target, limit=5)
                        oneri = (
                            " Did you mean: "
                            + ", ".join(a.name for a in yakin)
                            if yakin else
                            " Use `list_apps` to see the installed apps."
                        )
                        raise ToolError(f"There is no app called {target!r}.{oneri}")

                if app is not None:
                    argv = apps.launch_argv(app)
                    subprocess.Popen(
                        argv + ([arguments] if arguments else []),
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    # Kısayol ve mağaza girdileri explorer üzerinden
                    # açılıyor; öne gelecek pencere explorer değil, o yüzden
                    # süreç adına göre bekleme yapılamıyor.
                    expect = None
                else:
                    resolved = yol or target
                    subprocess.Popen(
                        f'"{resolved}" {arguments}'.strip(),
                        shell=True,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    expect = os.path.basename(resolved)
        except OSError as exc:
            raise ToolError(f"Could not launch {target}: {exc}") from None

        # Öne gelmesini bekle. Gelmezse modele söyle — sessizce devam edip
        # yanlış pencereye yazmak Faz 1'de tam olarak bu şekilde patlamıştı.
        appeared = self._wait_for_new_foreground(before, expect)
        now = win.foreground_title()
        if not appeared:
            return ToolOutcome(
                content=(
                    f"{target} launched but did not come to the front. {now!r} has focus. "
                    "Take a screenshot and verify before typing."
                )
            )
        return ToolOutcome(content=f"{target} opened, in the foreground: {now!r}")

    def _wait_for_new_foreground(
        self, before: str, expect: str | None, timeout: float = 10.0
    ) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.kill.check()
            if expect and win.matches_foreground(expect, None):
                return True
            title = win.foreground_title()
            if title and title != before:
                return True
            time.sleep(0.15)
        return False

    def _do_list_apps(self, payload: dict[str, Any]) -> ToolOutcome:
        query = str(payload.get("query", "")).strip()
        found = apps.search(query, limit=30) if query else apps.catalog()
        if not found:
            return ToolOutcome(
                content=f"No app matches {query!r}. Call it without a query to see "
                        f"the whole list."
            )
        lines = [f"{len(found)} uygulama:"]
        lines += [f"  {a.describe()}" for a in found[:60]]
        if len(found) > 60:
            lines.append(f"  … +{len(found) - 60} tane daha, daha dar ara.")
        return ToolOutcome(content="\n".join(lines))

    def _do_run_shell(self, payload: dict[str, Any]) -> ToolOutcome:
        command = str(payload.get("command", "")).strip()
        if not command:
            raise ToolError("run_shell needs command")
        timeout = min(int(payload.get("timeout", 30)), 300)

        try:
            completed = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True,
                timeout=timeout,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except subprocess.TimeoutExpired:
            raise ToolError(
                f"The command did not finish in {timeout} s and was stopped. It may be waiting for input."
            ) from None

        output = (completed.stdout or "").strip()
        errors = (completed.stderr or "").strip()
        if len(output) > 8000:
            output = output[:8000] + f"\n... ({len(output)} karakterden kesildi)"

        parts = [f"cikis_kodu={completed.returncode}"]
        if output:
            parts.append(output)
        if errors:
            parts.append(f"stderr:\n{errors[:2000]}")
        return ToolOutcome(
            content="\n".join(parts), is_error=completed.returncode != 0
        )

    # --- dosyalar ---------------------------------------------------------

    def _do_write_file(self, payload: dict[str, Any]) -> ToolOutcome:
        path = str(payload.get("path", ""))
        try:
            sonuc = files.write(
                path,
                str(payload.get("content", "")),
                append=bool(payload.get("append", False)),
            )
        except files.FileError as exc:
            raise ToolError(str(exc)) from None
        # Arayüz yazılan dosyayı kod paneli olarak açıyor. Yalnızca başarılı
        # yazımda: olmayan bir dosyayı göstermeye çalışmak boş panel demek.
        self.last_files = [path]
        return ToolOutcome(content=sonuc)

    def _do_write_files(self, payload: dict[str, Any]) -> ToolOutcome:
        _require(payload, "files")
        items = payload["files"]
        if not isinstance(items, list) or not items:
            raise ToolError("files cannot be empty; a list of {path, content} is expected")

        hazir: list[tuple[str, str]] = []
        for index, item in enumerate(items):
            if not isinstance(item, dict) or "path" not in item or "content" not in item:
                raise ToolError(f"files[{index}] must be {{path, content}}")
            hazir.append((str(item["path"]), str(item["content"])))

        # Üzerine yazılacaklar tek seferde soruluyor. Dosya başına ayrı onay,
        # on dosyalık bir projede on kere sormak demek ve o noktada kimse
        # okumadan onaylıyor.
        ustune = [p for p, _c in hazir if gate.classify_write(p).needs_confirmation]
        if ustune:
            detay = "Will be overwritten:\n" + "\n".join(f"  {p}" for p in ustune)
            if not self.approve(
                "write_files", detay,
                str(payload.get("why") or "overwrites existing files"),
            ):
                raise Denied("The user declined the overwrite. No file was written.")

        yazilan: list[str] = []
        try:
            for path, content in hazir:
                files.write(path, content)
                yazilan.append(path)
        except (OSError, ValueError) as exc:
            # Yarım kalan yazımı gizlemek, ajanın projeyi tamamlandı
            # sanmasına yol açar.
            raise ToolError(
                f"Stopped after writing {len(yazilan)}/{len(hazir)} files: "
                f"{exc}. Written: {', '.join(yazilan) or 'none'}"
            ) from None

        self.last_files = yazilan
        toplam = sum(len(c) for _p, c in hazir)
        return ToolOutcome(
            content=f"{len(yazilan)} files written ({toplam} characters):\n"
            + "\n".join(f"  {p}" for p in yazilan)
        )

    def _do_read_file(self, payload: dict[str, Any]) -> ToolOutcome:
        try:
            return ToolOutcome(content=files.read(str(payload.get("path", ""))))
        except files.FileError as exc:
            raise ToolError(str(exc)) from None

    def _do_edit_file(self, payload: dict[str, Any]) -> ToolOutcome:
        try:
            return ToolOutcome(
                content=files.edit(
                    str(payload.get("path", "")),
                    str(payload.get("old", "")),
                    str(payload.get("new", "")),
                )
            )
        except files.FileError as exc:
            raise ToolError(str(exc)) from None

    def _do_list_dir(self, payload: dict[str, Any]) -> ToolOutcome:
        try:
            return ToolOutcome(content=files.list_dir(str(payload.get("path", ""))))
        except files.FileError as exc:
            raise ToolError(str(exc)) from None

    # --- terminaller ------------------------------------------------------

    def _do_terminal_open(self, payload: dict[str, Any]) -> ToolOutcome:
        name = str(payload.get("name", "")).strip()
        if not name:
            raise ToolError("terminal_open needs name")
        try:
            session = self.terminals.open(
                name,
                command=(payload.get("command") or None),
                cwd=(payload.get("cwd") or None),
            )
        except TerminalError as exc:
            raise ToolError(str(exc)) from None

        settled = session.wait_idle(timeout=20)
        return ToolOutcome(content=self._screen(session, settled))

    def _do_terminal_send(self, payload: dict[str, Any]) -> ToolOutcome:
        session = self._session(payload)
        text = payload.get("text")
        key = payload.get("key")
        if text is None and key is None:
            raise ToolError("terminal_send needs text or key")

        try:
            if text is not None:
                session.send(str(text))
                if payload.get("submit", True):
                    session.send_key("enter")
            if key is not None:
                session.send_key(str(key))
        except TerminalError as exc:
            raise ToolError(str(exc)) from None

        wait = min(float(payload.get("wait", 15)), 120.0)
        settled = session.wait_idle(timeout=wait)
        return ToolOutcome(content=self._screen(session, settled))

    def _do_terminal_read(self, payload: dict[str, Any]) -> ToolOutcome:
        session = self._session(payload)
        wait = float(payload.get("wait", 0))
        settled = session.wait_idle(timeout=wait) if wait > 0 else True
        return ToolOutcome(content=self._screen(session, settled))

    def _do_terminal_close(self, payload: dict[str, Any]) -> ToolOutcome:
        name = str(payload.get("name", ""))
        try:
            self.terminals.close(name)
        except TerminalError as exc:
            raise ToolError(str(exc)) from None
        return ToolOutcome(content=f"Session {name!r} was closed.")

    def _session(self, payload: dict[str, Any]):
        try:
            return self.terminals.get(str(payload.get("name", "")))
        except TerminalError as exc:
            raise ToolError(str(exc)) from None

    def _screen(self, session, settled: bool) -> str:
        text = session.screen_text()
        if not settled:
            # Durmadıysa bunu söylemek şart: model ekranı bitmiş sanıp yarım
            # çizilmiş bir arayüze göre karar verirse yanlış tuşa basar.
            text += "\n[still producing output — read again with terminal_read]"
        if not session.alive:
            text += "\n[the process in this session exited]"
        return text

    # --- ofis -------------------------------------------------------------

    def _do_office_open(self, payload: dict[str, Any]) -> ToolOutcome:
        try:
            document = self.office.open(
                str(payload.get("name", "")), str(payload.get("path", ""))
            )
        except OfficeError as exc:
            raise ToolError(str(exc)) from None
        return ToolOutcome(content=document.summary())

    def _do_office_read(self, payload: dict[str, Any]) -> ToolOutcome:
        document = self._document(payload)
        try:
            if isinstance(document, Workbook):
                return ToolOutcome(
                    content=document.read(
                        ref=payload.get("ref"), sheet=payload.get("sheet")
                    )
                )
            return ToolOutcome(content=document.read(start=int(payload.get("start", 0))))
        except (SheetError, TextError) as exc:
            raise ToolError(str(exc)) from None

    def _do_office_edit(self, payload: dict[str, Any]) -> ToolOutcome:
        document = self._document(payload)
        operation = str(payload.get("operation", ""))
        why = str(payload.get("why", ""))

        try:
            if operation == "write":
                _require(payload, "ref", "values")
                return ToolOutcome(
                    content=document.write(
                        str(payload["ref"]), payload["values"], why,
                        sheet=payload.get("sheet"),
                    )
                )
            if operation == "add_sheet":
                _require(payload, "sheet")
                return ToolOutcome(content=document.add_sheet(str(payload["sheet"]), why))
            if operation == "append":
                _require(payload, "text")
                return ToolOutcome(
                    content=document.append(
                        str(payload["text"]), why, style=payload.get("style")
                    )
                )
            if operation == "replace":
                _require(payload, "index", "text")
                return ToolOutcome(
                    content=document.replace(int(payload["index"]), str(payload["text"]), why)
                )
            if operation == "add_table":
                _require(payload, "values")
                return ToolOutcome(content=document.add_table(payload["values"], why))
        except AttributeError:
            raise ToolError(
                f"{operation!r} does not exist for this document type. {document.path} is a "
                f"{document.kind} document."
            ) from None
        except ValueError as exc:
            raise ToolError(str(exc)) from None
        except (SheetError, TextError) as exc:
            raise ToolError(str(exc)) from None

        raise ToolError(f"Unknown operation: {operation!r}")

    def _do_office_save(self, payload: dict[str, Any]) -> ToolOutcome:
        document = self._document(payload)
        try:
            return ToolOutcome(content=document.save(payload.get("path")))
        except (SheetError, TextError) as exc:
            raise ToolError(str(exc)) from None

    def _do_office_history(self, payload: dict[str, Any]) -> ToolOutcome:
        document = self._document(payload)
        undo = int(payload.get("undo", 0))
        if undo > 0:
            result = document.undo(undo)
            return ToolOutcome(content=f"{result}\n\n{document.ledger.report()}")
        return ToolOutcome(content=document.ledger.report())

    def _do_office_close(self, payload: dict[str, Any]) -> ToolOutcome:
        name = str(payload.get("name", ""))
        try:
            if payload.get("discard"):
                return ToolOutcome(content=self.office.discard(name))
            return ToolOutcome(content=self.office.close(name))
        except OfficeError as exc:
            raise ToolError(str(exc)) from None

    def _document(self, payload: dict[str, Any]):
        try:
            return self.office.get(str(payload.get("name", "")))
        except OfficeError as exc:
            raise ToolError(str(exc)) from None

    def _do_switch_display(self, payload: dict[str, Any]) -> ToolOutcome:
        try:
            index = int(payload["index"])
            display = self.displays[index]
        except (KeyError, ValueError, TypeError) as exc:
            raise ToolError(f"Invalid display index: {exc}") from None
        except IndexError as exc:
            raise ToolError(str(exc)) from None

        self.active_index = index
        return ToolOutcome(
            content=f"Ekran {index} ({display.width}x{display.height}) aktif."
        )


def _require(payload: dict[str, Any], *keys: str) -> None:
    missing = [k for k in keys if payload.get(k) is None]
    if missing:
        raise ToolError(
            f"Bu islem icin eksik alan: {', '.join(missing)}"
        )


def _duration(value: Any) -> float:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        raise ToolError(f"The duration must be a number, got: {value!r}") from None
    if not 0 <= seconds <= 300:
        raise ToolError(f"The duration must be between 0 and 300 seconds, got: {seconds}")
    return seconds


def _interruptible_sleep(seconds: float, kill: KillSwitch, step: float = 0.1) -> None:
    import time

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        kill.check()
        time.sleep(min(step, max(0.0, deadline - time.monotonic())))
