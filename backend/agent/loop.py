"""Ajan döngüsü.

SDK'nın `tool_runner`'ı yerine elle döngü var, çünkü üç şeye ihtiyacımız var
ve runner üçünü de vermiyor: bir partideki eylemlerin ilk hatada durması,
her adımda acil durdurma kontrolü, ve eski ekran görüntülerinin bağlamdan
budanması.

## Eylemden sonra doğrulama

Bir tıklamanın ya da yazının başarılı olup olmadığını `ToolOutcome`'un
kendisi bilmiyor: işleyiciler koşulsuz "OK" dönüyor. Modelin "tıkladım"
sözüne güvenmek bileşik hata üretiyor — tutmayan tıklamanın ardından gelen
yazı yanlış pencereye gidiyor. Bu yüzden döngü her eylemin **öncesinde ve
sonrasında** ön plan penceresini ve odak denetimini okuyup karşılaştırıyor
(`_durum_izi`) ve sonucu adım kaydına işliyor. Uydurma yok: `dogrulandi`
yalnızca gerçekten gözlenen bir değişiklikte; gözlem değişiklik
göstermediğinde `varsayildi`, okuma düştüğünde `dogrulanamadi` yazılıyor. Doğrulama bir emniyet kilidi değil — tutmayan
eylem turu durdurmuyor, sonuç "Not verified" notuyla ajana dönüyor ki bir
sonraki adımda ekran görüntüsü alıp baksın.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import anthropic

from .. import config
from ..computer import uia
from ..computer import windows as win
from ..computer.capture import ScreenCapture
from ..computer.displays import DisplayMap
from ..safety.killswitch import Aborted, KillSwitch
from . import rapor as rapor_mod
from .akankod import AkanKod
from .kayit import Kayit, oneri_notu, tekrar_bul
from .dispatch import Dispatcher, ToolError, ToolOutcome
from .prompts import build_system
from .tools import CUSTOM_TOOLS

COMPUTER_TOOLSET = "computer"

#: Bağlamda tutulacak ekran görüntüsü sayısı. Her kare ~1000-1800 token, ve
#: istek başına 20 görsel sınırı var. Model bir önceki birkaç adımı görsün
#: yeter — daha eskisi neredeyse hiç işe yaramıyor ama tokeni yiyor.
KEEP_IMAGES = 4

#: Budama eşiği. Her turda budamak prompt cache'ini her turda geçersiz kılar;
#: birikmesini bekleyip toplu budamak çok daha ucuz.
PRUNE_AT = 12

PRUNED_PLACEHOLDER = "[an old screenshot was pruned from the context]"


def _ozet(icerik) -> str:
    """Araç sonucunun kayda giren kısa hâli.

    Görsel bloklar metne çevrilmiyor: base64 bir kareyi denetim kaydına
    yazmak dosyayı megabaytlara çıkarır ve hiçbir şey anlatmaz.
    """
    if isinstance(icerik, list):
        return "[image]"
    return str(icerik)


#: Dünyayı doğrudan değiştiren ve doğrulaması anlamlı olan eylemler.
#: Bakma araçları (`screenshot`, `read_ui_tree`…) değişiklik beklemedikleri
#: için listede değil; şerh yiyen bir `screenshot` yanlış alarm olurdu.
EYLEM_ARACLARI = frozenset({
    "left_click", "right_click", "middle_click", "double_click",
    "triple_click", "mouse_move", "left_click_drag", "left_mouse_down",
    "left_mouse_up", "scroll", "type", "key", "hold_key",
})


def _durum_izi() -> dict[str, Any] | None:
    """Eylem öncesi/sonrası karşılaştırılan durum özeti. Okunamazsa `None`.

    Kullanılan her şey mevcut primitifler: ön plan penceresinin başlığı ve
    süreci (`windows.py`) ile odaktaki denetim (`uia.py`). Yeni bir alt
    sistem yok; iki ucuz okuma, eylem başına bir kez.

    Hata fırlatmıyor ama yutmayı da gizlemiyor: tamamı okunamadıysa `None`
    dönüyor ve `dogrulandi` **üretilmiyor** — okunamayan bir dünya
    doğrulanmış sayılamaz. Kısmi kayıp (`odak=None`) `tamam` alanıyla
    anlatılıyor; karar mercii `_dogrulama_sonucu`: okunabilen bileşenlerin
    gerçek farkı kanıttır, okunamayan bir bileşen ne kanıt ne de "değişmedi".
    """
    try:
        baslik = win.foreground_title()
        surec = win.foreground_process()
        odak = uia.odak_ozeti()
        return {
            "baslik": baslik,
            "surec": surec,
            "odak": odak,
            "tamam": bool(baslik or surec) and odak is not None,
        }
    except Exception:
        return None


def _dogrulama_sonucu(
    once: dict[str, Any] | None, sonra: dict[str, Any] | None
) -> tuple[str, str]:
    """`(durum, ayrinti)` — durum: dogrulandi / varsayildi / dogrulanamadi.

    Üç yol var ve ayrım pazarlık dışı:

    - **dogrulandi** yalnızca okunabilen bir bileşen gerçekten değiştiğinde.
      Okunamayan bir bileşen (`None`) "değişmedi" sayılmıyor — okunamamış
      bir dünya kanıt üretemez; kısmi okumadaki gerçek bir fark ise kanıttır
      ve başlık/süreç uyuşmazlığı odak okunamasa bile sayılır.
    - **varsayildi** okunabilen kısımda fark yoksa: varsayım bu.
    - **dogrulanamadi** hiçbir şey okunamadıysa.

    Uydurulmuş bir "dogrulandi" zincirleme hatayı gizler; şerhli bir
    "varsayildi" yalnızca dikkat çeker. Yanlış tarafa düşmesi gereken yer
    burası.
    """
    if once is None or sonra is None:
        return "dogrulanamadi", "the screen state could not be read around the action"
    if _bos(once) or _bos(sonra):
        # Hiçbir şey okunamadı — masaüstünün kendisi odakta olabilir.
        # "Kısmen okundu" demek burada yalan olurdu.
        return "dogrulanamadi", (
            "nothing about the screen could be read around the action"
        )

    fark = _fark_anlat(once, sonra)
    if fark:
        return "dogrulandi", f"the screen changed after the action — {fark}"
    if once.get("tamam") and sonra.get("tamam"):
        return "varsayildi", "no visible change after the action"
    return "varsayildi", (
        "the screen could only be read in part, and no change showed in "
        "the readable part"
    )


def _bos(iz: dict[str, Any]) -> bool:
    """İzdeki her alan boş mu — hiçbir şey okunamamış mı."""
    return not (iz.get("baslik") or iz.get("surec") or iz.get("odak"))


def _fark_anlat(once: dict[str, Any], sonra: dict[str, Any]) -> str:
    """Okunabilen bileşenlerdeki gerçek farkların kısa anlatımı.

    Odak iki tarafta da okunabildiyse karşılaştırılıyor; bir tarafı
    okunamayan bir karşılaştırma fark sayılmaz, çünkü taraf tutar:
    `None -> ("Edit", ...)` bir değişiklik değil, bir okuma hatasıdır.
    """
    parcalar: list[str] = []
    if once.get("baslik") != sonra.get("baslik"):
        parcalar.append(
            f"window {once.get('baslik')!r} -> {sonra.get('baslik')!r}"
        )
    if once.get("surec") != sonra.get("surec"):
        parcalar.append(
            f"process {once.get('surec')!r} -> {sonra.get('surec')!r}"
        )
    o, s = once.get("odak"), sonra.get("odak")
    if o is not None and s is not None and o != s:
        parcalar.append(f"focus {_odak_anlat(o)} -> {_odak_anlat(s)}")
    return "; ".join(parcalar)


def _odak_anlat(odak: tuple[str, str, str] | None) -> str:
    if odak is None:
        return "(focus unreadable)"
    tur, ad, deger = odak
    if deger:
        return f"{tur} {ad!r} = {deger!r}"
    return f"{tur} {ad!r}"


def _dogrulama_notu(durum: str, ayrinti: str) -> str:
    """Sonuca eklenen İngilizce not.

    İngilizce, çünkü not modele gidiyor ve sızması serbest. Ayrım pazarlık
    dışı: gerçekleşen değişiklik gözlenen kanıttır ve ajana "bu adım oldu,
    üstüne kur" yetkisi verir; gerçekleşmeyen ise varsayımdır ve bir
    sonraki adımı onun üstüne kurmaması açıkça söylenir. Uydurulmuş bir
    doğrulama, zincirleme hatayı **gizler**; şerhli bir varsayım yalnızca
    dikkat çeker.
    """
    if durum == "dogrulandi":
        return (
            f"\n\n[Verified: {ayrinti}. This is an observed change, not a "
            f"claim — carry on.]"
        )
    return (
        f"\n\n[Not verified: {ayrinti}. Do not assume this worked; take a "
        f"screenshot or read the UI tree before the next step.]"
    )


@dataclass
class Turn:
    """Bir tur boyunca dışarıya bildirilenler — arayüz buraya bağlanacak."""

    on_text: Callable[[str], None] = lambda _t: None
    on_thinking: Callable[[str], None] = lambda _t: None
    on_action: Callable[[str, dict[str, Any]], None] = lambda _n, _i: None
    on_result: Callable[[str, ToolOutcome], None] = lambda _n, _o: None
    #: Araya sıkıştırılan cümle ajana ulaştığında.
    on_interjection: Callable[[str], None] = lambda _t: None
    #: Modelden herhangi bir parça düştü — metin ya da düşünce. Arayüzdeki
    #: gösterge bununla ilerliyor: hareket, gerçekten bir şeyin geldiği
    #: anlamına gelmeli. Sabit hızda dönen bir çark bunu söylemiyor.
    on_pulse: Callable[[], None] = lambda: None
    #: Ajanın cevabında kayıtta karşılığı olmayan iddia varsa, o satır.
    #: Boş dizeyle çağrılmıyor — arayüz yalnızca söyleyecek bir şey
    #: olduğunda haber alıyor.
    on_rapor: Callable[[str], None] = lambda _t: None
    #: Model bir dosya yazarken: (araç, yol, o ana kadarki metin, bitti mi).
    #: Dosya diske hâlâ tek seferde yazılıyor; canlı olan modelin
    #: üretimi ve gösterilen de tam olarak o.
    on_kod: Callable[[str, str, str, bool], None] = lambda _a, _y, _m, _b: None
    #: Bir eylemden sonra doğrulama: (araç, durum). Durum `dogrulandi`,
    #: `varsayildi` ya da `dogrulanamadi`. Adım kaydı zaten `ToolOutcome`
    #: üzerinde duruyor (`dogrulama` alanı); bu kanca onu turun dışına,
    #: arayüze ve denetim kaydının sahibine taşıyan kanal.
    on_dogrulama: Callable[[str, str], None] = lambda _n, _d: None


#: Reddedilme mesajı. Computer-use çağrılarında Anthropic bir güvenlik
#: sınıflandırıcısı çalıştırıyor ve bu sınıflandırıcı **ekran görüntüsünün
#: içeriğine** de bakıyor. Ekranda doğrulama kodu, bankacılık ekranı ya da
#: kimlik bilgisi varken reddedilen şey çoğu zaman kullanıcının isteği değil,
#: karenin içeriği oluyor.
#:
#: Eski hâli yalnızca "Model bu isteği reddetti." diyordu: ne reddedildiğini,
#: neden reddedildiğini ve ne yapılacağını söylemiyor, üstelik modelin kendi
#: açıklamasını da çöpe atıyordu.
REFUSAL_HINT = (
    "The request was refused. This is usually not about what you wrote "
    "but about what was on screen: a frame showing a verification code, "
    "a banking screen or a password field trips a safety check.\n\n"
    "Close that window or switch to another display and try again."
)


def _refusal_text(model_text: str) -> str:
    """Modelin kendi açıklaması varsa o kaybolmuyor."""
    said = model_text.strip()
    return f"{said}\n\n{REFUSAL_HINT}" if said else REFUSAL_HINT


#: Aynı araç aynı hatayla kaç kez düşerse pes edilir.
#:
#: Bir tur maliyetli: model çağrısı, düşünce, ekran görüntüsü. Aynı çağrının
#: aynı hatayı vermesi ajanın kendini düzeltemediği anlamına geliyor ve
#: devam etmek yalnızca para yakıyor. Ölçüldü: bir kod hatası yüzünden dört
#: `remote_*` çağrısı üst üste aynı `TypeError` ile düştü, ajan her seferinde
#: yeniden denedi.
#:
#: İkinci tekrarda modele "bu yol kapalı, başka bir şey dene" deniyor;
#: üçüncüde tur durduruluyor.
#: Nabız sinyalleri arasındaki en kısa süre, saniye. 20 Hz gözün ayırt
#: edebildiği üst sınırın üstünde; daha sıkı göndermek boşa iş.
PULSE_MIN_GAP = 0.05

SAME_ERROR_HINT = 2
SAME_ERROR_LIMIT = 3


def _error_key(name: str, outcome: ToolOutcome) -> str:
    """Aynı hatayı tanımak için imza. Değişken kısımlar atılıyor: dosya
    yolu ve satır numarası farklı olsa da hata aynı hatadır."""
    import re

    text = outcome.content if isinstance(outcome.content, str) else ""
    text = re.sub(r"\d+", "#", text[:200])
    return f"{name}|{text}"


def _new_lock():
    import threading

    return threading.Lock()


@dataclass
class Agent:
    displays: DisplayMap
    capture: ScreenCapture
    kill: KillSwitch
    client: anthropic.Anthropic
    approve: Callable[[str, str, str], bool] | None = None
    dispatcher: Dispatcher = field(init=False)
    messages: list[dict[str, Any]] = field(default_factory=list)
    #: Ajan çalışırken araya sıkıştırılan cümleler. Kilitli, çünkü arayüz
    #: thread'inden yazılıp ajan thread'inden okunuyor.
    _pending: list[str] = field(default_factory=list, repr=False)
    _pending_lock: Any = field(default_factory=_new_lock, repr=False)
    #: Denetim kaydı. Ajanın ne yaptığının diskteki karşılığı; hem
    #: doğrulanmış rapor hem de tekrar tespiti buna dayanıyor.
    kayit: Kayit = field(default_factory=Kayit)
    #: Oturum boyunca başarıyla çalışmış araçlar. Bir iddia bu turda
    #: desteklenmiyorsa buraya bakılıyor: "az önce yazdığım dosya" meşru
    #: bir cümle ve her turda sıfırlansaydı yanlış alarm verirdi.
    _oturum_araclari: set[str] = field(default_factory=set, repr=False)

    def __post_init__(self) -> None:
        self.dispatcher = Dispatcher(
            self.displays, self.capture, self.kill, approve=self.approve
        )
        # Açık MCP sunucuları arka planda bağlanıyor. Beklenmiyor: bir
        # `npx` indirmesi dakikalar sürebiliyor ve o süre boyunca ajanın
        # açılmaması kabul edilemez. Araçlar hazır olunca listeye
        # giriyor; liste zaten her model çağrısında yeniden kuruluyor.
        self.dispatcher.mcp.basla()

    @classmethod
    def create(cls, cfg: config.Config, displays: DisplayMap, capture: ScreenCapture,
               kill: KillSwitch, approve=None) -> Agent:
        return cls(
            displays=displays,
            capture=capture,
            kill=kill,
            client=anthropic.Anthropic(api_key=cfg.anthropic_api_key),
            approve=approve,
        )

    @property
    def tools(self) -> list[dict[str, Any]]:
        """Araç listesi her model çağrısında yeniden kuruluyor.

        Sabit bir liste, ajanın az önce yazdığı yeteneği aynı turda
        çağırmasını imkânsız kılardı — yetenek ancak uygulama yeniden
        başlatılınca görünürdü ve "yaz, hemen dene" döngüsü kapanmazdı.

        Önbellek noktası **son statik aracın** üstünde, computer araç
        setinin değil. Bir önbellek noktası kendisine kadar olan her şeyi
        kapsıyor; nokta ilk sırada olduğunda arkasındaki 28 özel araç
        (~3700 token) her istekte yeniden işleniyordu. Nokta sona alınınca
        hepsi önbellekten geliyor, yetenekler ise ondan sonra kaldığı için
        yeni yetenek yazmak önbelleği bozmuyor.
        """
        static = [
            {"type": "computer_toolset_20260801"},
            *CUSTOM_TOOLS[:-1],
            {**CUSTOM_TOOLS[-1], "cache_control": {"type": "ephemeral"}},
        ]
        return [*static, *self.dispatcher.skills.tools(),
                *self.dispatcher.mcp.tools()]

    def interject(self, text: str) -> None:
        """Ajan çalışırken araya bir cümle sıkıştırır.

        Ajan bir sonraki adıma geçerken bunu görüyor. Turu kesmiyor —
        yarım kalmış bir tıklama dizisini ortasından bölmek, ekranı
        beklenmedik bir durumda bırakırdı. Bir sonraki karar noktasında
        okunuyor ve oradan itibaren geçerli oluyor.
        """
        with self._pending_lock:
            self._pending.append(text)

    def take_pending(self) -> list[str]:
        """Bekleyenleri alır ve kuyruğu boşaltır."""
        with self._pending_lock:
            bekleyen, self._pending = self._pending, []
        return bekleyen

    def run(self, instruction: str, turn: Turn | None = None,
            max_steps: int = 60) -> str:
        """Bir talimatı ajan bitene kadar sürer. Son metni döndürür.

        Asıl döngü `_sur`; buradaki sarmalayıcının tek işi turu her
        çıkışta kayda kapatmak. `_sur`'ün beş ayrı çıkışı var (reddedilme,
        araçsız cevap, tıkanma, adım sınırı, iptal) ve her birine ayrı ayrı
        kapanış yazmak, birini unutmanın kesin yolu olurdu.
        """
        turn = turn or Turn()
        metin = ""
        try:
            metin = self._sur(instruction, turn, max_steps)
            return metin
        finally:
            # Koşu bitti: kayıt sürüyorsa burada duruyor. Ajan
            # `record_stop` demeyi unutabilir, tur bir hatayla ya da
            # Esc x3 ile kesilmiş olabilir — her üç yolda da arkada
            # ffmpeg kalmamalı ve dosya oynatılabilir olmalı. `kapat`
            # hata yutuyor: kapanış yolundaki bir istisna, raporun hiç
            # yazılmamasına yol açardı.
            self.dispatcher.ekran_kaydi.kapat()
            eksik = self._raporu_kapat(metin)
            if eksik:
                turn.on_rapor(rapor_mod.not_metni(eksik))

    def _raporu_kapat(self, metin: str) -> list[str]:
        """Turu kayda kapatır ve desteksiz iddiaları döndürür."""
        bu_tur = self.kayit.tur_araclari()
        self._oturum_araclari |= bu_tur
        eksik = rapor_mod.desteksiz(
            metin, bu_tur, self._oturum_araclari - bu_tur
        )
        self.kayit.tur_bitti(metin, eksik)
        return eksik

    def _sur(self, instruction: str, turn: Turn, max_steps: int) -> str:
        self.kill.reset()
        # Yarım kalmış araç çağrıları kapatılıyor. Bir tur durdurulunca
        # (Esc, durdur düğmesi, çökme) `tool_use` içeren asistan mesajı
        # geçmişte kalıyor ama sonuçları hiç eklenmiyor. API her
        # `tool_use` için hemen sonraki mesajda bir `tool_result`
        # istiyor; olmayınca **bütün sohbet** reddediliyor ve uygulamayı
        # yeniden başlatmadan bir daha konuşamıyorsun.
        self._close_open_tools("Durduruldu.")

        self.kayit.tur_basladi(instruction, self.dispatcher.kuru)
        # Akış kaydı tamponu da burada sıfırlanıyor: `workflow_save`
        # "bu turda ne yaptın" diyor ve tampon turlar arası taşınsaydı
        # iki turluk bir dizi tek akış olarak kaydedilirdi.
        self.dispatcher.tur_basladi(instruction)
        # Tekrarlanan iş varsa talimatın sonuna not düşüyor. Bunu sistem
        # promptuna yazmak eskiden denendi ve çalışmadı: model otuz
        # adımlık bir turun sonunda "bunu üçüncü kez yapıyorum" demiyor.
        # Sayan taraf artık kod.
        istek = instruction + oneri_notu(tekrar_bul(self.kayit.satirlar()))
        self.messages.append({"role": "user", "content": istek})

        final_text = ""
        stuck = False
        # Aynı hata imzası kaç kez görüldü. Tur boyunca yaşıyor: ajan iki
        # adım sonra aynı duvara toslarsa bu sayılıyor.
        seen_errors: dict[str, int] = {}
        for step in range(max_steps):
            self.kill.check()
            response = self._call_model(turn, effort=_effort_for(step, stuck))

            final_text = "".join(
                block.text for block in response.content if block.type == "text"
            )
            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "refusal":
                # Son ekran görüntüsünü geçmişten düşür. Kalırsa bir sonraki
                # istek de aynı kareyi taşıyor ve aynı yerde reddediliyor —
                # kullanıcı "neden hiçbir şey çalışmıyor" diye kalıyor.
                self._drop_last_images()
                return _refusal_text(final_text)
            if response.stop_reason != "tool_use":
                return final_text

            try:
                results = self._run_batch(response.content, turn, seen_errors)
            except Aborted:
                # Geçmişi hemen onar. Bir sonraki tura bırakmak, arada
                # başka bir şey yazılırsa o mesajı da bozardı.
                self._close_open_tools("Durduruldu.")
                raise
            stuck = any(r.get("is_error") for r in results)
            tekrar = max(seen_errors.values(), default=0)
            if tekrar >= SAME_ERROR_LIMIT:
                self.messages.append({"role": "user", "content": results})
                worst = max(seen_errors, key=lambda k: seen_errors[k])
                return (
                    f"{worst.split('|')[0]} failed {tekrar} times with the same error, "
                    f"so I stopped — carrying on would just cost money.\n\n"
                    f"{final_text}".strip()
                )
            # Araya sıkıştırılan cümleler araç sonuçlarıyla aynı mesaja
            # ekleniyor. Sıra önemli: API tool_result bloklarının kullanıcı
            # turunun **başında** olmasını istiyor, metin sonra geliyor.
            araya = self.take_pending()
            if araya:
                results = results + [
                    {"type": "text", "text": f"[the user cut in] {metin}"}
                    for metin in araya
                ]
                for metin in araya:
                    turn.on_interjection(metin)
            self.messages.append({"role": "user", "content": results})
            self._prune_images()

        return final_text or f"It did not finish in {max_steps} steps, so I stopped."

    def _close_open_tools(self, reason: str) -> str | None:
        """Sonucu yazılmamış araç çağrılarını kapatır.

        Geçmişin sonundaki asistan mesajında `tool_use` varsa ve peşinden
        `tool_result` gelmiyorsa, her biri için hata sonucu ekliyor.
        Kapatılan varsa araçların adını döndürüyor.
        """
        if not self.messages or self.messages[-1].get("role") != "assistant":
            return None
        acik = [b for b in _blocks(self.messages[-1])
                if getattr(b, "type", None) == "tool_use"
                or (isinstance(b, dict) and b.get("type") == "tool_use")]
        if not acik:
            return None

        sonuclar = []
        adlar = []
        for blok in acik:
            kimlik = getattr(blok, "id", None) or blok.get("id")
            ad = getattr(blok, "name", None) or blok.get("name", "")
            adlar.append(ad)
            sonuc = {
                "type": "tool_result",
                "tool_use_id": kimlik,
                "content": reason,
                "is_error": True,
            }
            toolset = getattr(blok, "toolset_name", None)
            if toolset:
                sonuc["toolset_name"] = toolset
            sonuclar.append(sonuc)
        self.messages.append({"role": "user", "content": sonuclar})
        return ", ".join(a for a in adlar if a)

    def _drop_last_images(self) -> None:
        """Geçmişteki görselleri metin yer tutucuyla değiştirir."""
        for message in self.messages:
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "image":
                    block.clear()
                    block.update({
                        "type": "text",
                        "text": "(the screenshot was removed)",
                    })

    # --- model çağrısı ----------------------------------------------------

    def _call_model(self, turn: Turn, effort: str = config.EFFORT):
        """Modeli akışla çağırır ve tam mesajı döndürür.

        Akış zorunlu: SDK, 10 dakikayı aşabilecek isteklerde bloke çağrıyı
        reddediyor ve yüksek `max_tokens` bu eşiği tetikliyor. İşe yarıyor
        da — metin ve düşünce özeti tur bitmeden görünüyor.
        """
        thinking_buffer: list[str] = []
        akan = AkanKod()

        with self.client.messages.stream(
            model=config.MODEL,
            max_tokens=config.MAX_TOKENS,
            system=self._system_blocks(),
            tools=self.tools,
            messages=self.messages,
            thinking={"type": "adaptive", "display": "summarized"},
            output_config={"effort": effort},
        ) as stream:
            # Nabız kısılıyor: saniyede yüzlerce parça geliyor ve her
            # birini arayüze taşımak, çizilenden çok sinyal göndermek olurdu.
            son_nabiz = 0.0
            for event in stream:
                if event.type == "content_block_start":
                    blok = getattr(event, "content_block", None)
                    if getattr(blok, "type", "") == "tool_use":
                        akan.basla(getattr(blok, "name", ""))
                elif event.type == "content_block_delta":
                    delta = event.delta
                    simdi = time.monotonic()
                    if simdi - son_nabiz > PULSE_MIN_GAP:
                        son_nabiz = simdi
                        turn.on_pulse()
                    if delta.type == "text_delta":
                        turn.on_text(delta.text)
                    elif delta.type == "thinking_delta":
                        thinking_buffer.append(delta.thinking)
                    elif delta.type == "input_json_delta":
                        # Araç girdisi de akıyor. `write_file`'ın içeriği
                        # buradan geçiyor ve arayüz onu yazılırken
                        # gösterebiliyor; eskiden dosya araç çalıştıktan
                        # sonra bir anda beliriyordu.
                        if akan.besle(delta.partial_json):
                            turn.on_kod(akan.arac, akan.yol, akan.metin,
                                        False)
                elif event.type == "content_block_stop":
                    if akan.etkin:
                        turn.on_kod(akan.arac, akan.yol, akan.metin, True)
                        akan.dur()
                    if thinking_buffer:
                        # Düşünce parça parça geliyor; bloğu tamamlanınca
                        # tek seferde bildiriyoruz, yoksa arayüz kelime
                        # kelime titrer.
                        turn.on_thinking("".join(thinking_buffer))
                        thinking_buffer.clear()

            return stream.get_final_message()

    def _system_blocks(self) -> list[dict[str, Any]]:
        """Sistem promptu önbelleğe alınabilir blok olarak.

        Düz metin olarak gönderildiğinde ~2450 token her istekte yeniden
        işleniyordu. Prompt uzadıkça (yetenek sözleşmesi, panel sözleşmesi,
        uzak makine bölümü) bu maliyet büyüyor ve her adıma biniyor.
        """
        return [
            {
                "type": "text",
                "text": build_system(self.displays,
                                     self.dispatcher.active_index,
                                     self.dispatcher.kuru),
                "cache_control": {"type": "ephemeral"},
            }
        ]

    # --- araç partisi -----------------------------------------------------

    def _run_batch(self, content, turn: Turn,
                   seen_errors: dict[str, int] | None = None) -> list[dict[str, Any]]:
        """Bir turdaki tüm araç çağrılarını sırayla çalıştırır.

        Model tek yanıtta birkaç eylem gönderebiliyor ("tıkla, yaz, görüntü
        al"). Bunlar birbirini varsayar: tıklama başarısızsa yazma yanlış
        yere gider. Bu yüzden ilk hatadan sonrakiler çalıştırılmıyor,
        modele de neden çalıştırılmadığı söyleniyor.

        Eylem araçlarından sonra makinenin durumu **yeniden okunuyor**
        (`_dogrula`): işleyici "OK" derken bir tıklamanın tutup tutmadığını
        bilmiyor. Doğrulama bir hata yolu değil — tutmayan eylem turu
        durdurmuyor, yalnızca işaretleniyor; kural tek: söylenen şey görülen
        şey olsun.
        """
        results: list[dict[str, Any]] = []
        failed = False

        for block in content:
            if block.type != "tool_use":
                continue

            payload = dict(block.input or {})
            if failed:
                results.append(
                    self._result_block(
                        block,
                        ToolOutcome(
                            content="Not executed: an earlier computer action "
                                    "in this turn failed.",
                            is_error=True,
                        ),
                    )
                )
                continue

            turn.on_action(block.name, payload)
            # Doğrulama izi eylemden **önce** okunuyor ve yalnızca eylem
            # araçlarında: bir `screenshot`ın doğrulanacak bir iddiası yok,
            # ona fazladan iki okuma binmemeli. "Doğrulanacak mı" kararı
            # araç adından; `once`un `None` olması okumanın düştüğü anlamına
            # gelir ve o durumda da doğrulanır — `dogrulanamadi` damgasıyla.
            #
            # Kuru koşuda doğrulama yok: eylem hiç çalışmadı, yani
            # doğrulanacak bir iddia da yok. Şerh eklenirse kuru koşunun
            # kendi talimatıyla ("Assume it would have worked and carry on
            # planning") açıkça çelişirdi.
            dogrula = (
                block.name in EYLEM_ARACLARI and not self.dispatcher.kuru
            )
            once = _durum_izi() if dogrula else None
            try:
                outcome = self.dispatcher.run(block.name, payload)
            except Aborted:
                raise
            except ToolError as exc:
                outcome = ToolOutcome(content=str(exc), is_error=True)
                failed = True
            except Exception as exc:  # beklenmeyen: modele söyle, çökme
                outcome = ToolOutcome(
                    content=f"{type(exc).__name__}: {exc}", is_error=True
                )
                failed = True
            else:
                if dogrula:
                    self._dogrula(block.name, outcome, once, turn)

            if outcome.is_error and seen_errors is not None:
                key = _error_key(block.name, outcome)
                seen_errors[key] = seen_errors.get(key, 0) + 1
                if seen_errors[key] >= SAME_ERROR_HINT:
                    outcome = ToolOutcome(
                        content=(
                            f"{outcome.content}\n\n"
                            f"[This call returned the same error {seen_errors[key]} times. "
                            f"Do not retry it — either pick another route or tell the user "
                            f"what is not working.]"
                        ),
                        is_error=True,
                        # Şerh, doğrulama damgasını silmemeli.
                        dogrulama=outcome.dogrulama,
                    )

            self.kayit.eylem(
                block.name, dict(payload), outcome.is_error,
                _ozet(outcome.content),
            )
            turn.on_result(block.name, outcome)
            results.append(self._result_block(block, outcome))

        return results

    def _dogrula(self, name: str, outcome: ToolOutcome, once, turn: Turn) -> None:
        """Eylemden sonra durumu yeniden okur ve adımı damgalar.

        Yalnızca başarılı araçlarda çağrılıyor: hata zaten modele dönüyor.
        Damga `ToolOutcome`u **yerinde** değiştiriyor — `turn.on_result` de
        aynı nesneyi gördüğü için arayüz ve kayıt aynı şeyi okumak zorunda
        kalıyor, ikinci bir kopya yok.

        Şerh `content`e buradan, `_result_block` çalışmadan önce ekleniyor:
        modelin gördüğü metin tek yol üzerinden geçsin ve şerh ne kayıtta ne
        sonuç bloğunda ikinci kez çoğalmasın.
        """
        sonra = _durum_izi()
        durum, ayrinti = _dogrulama_sonucu(once, sonra)
        outcome.dogrulama = durum
        outcome.content = str(outcome.content) + _dogrulama_notu(durum, ayrinti)
        turn.on_dogrulama(name, durum)

    def _result_block(self, block, outcome: ToolOutcome) -> dict[str, Any]:
        result: dict[str, Any] = {
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": outcome.content,
        }
        # Üye araçların sonucu hangi toolset'e ait olduğunu söylemek zorunda;
        # `switch_display` bizim kendi aracımız, onda bu alan olmamalı.
        toolset = getattr(block, "toolset_name", None)
        if toolset:
            result["toolset_name"] = toolset
        if outcome.is_error:
            result["is_error"] = True
        return result

    # --- bağlam -----------------------------------------------------------

    def _prune_images(self) -> None:
        """Eski ekran görüntülerini metin yer tutucusuyla değiştirir."""
        positions = [
            (mi, ci)
            for mi, message in enumerate(self.messages)
            for ci, block in enumerate(_blocks(message))
            if _is_image_result(block)
        ]
        if len(positions) <= PRUNE_AT:
            return

        for mi, ci in positions[:-KEEP_IMAGES]:
            self.messages[mi]["content"][ci]["content"] = PRUNED_PLACEHOLDER


def _blocks(message: dict[str, Any]) -> list[Any]:
    content = message.get("content")
    return content if isinstance(content, list) else []


def _is_image_result(block: Any) -> bool:
    return (
        isinstance(block, dict)
        and block.get("type") == "tool_result"
        and isinstance(block.get("content"), list)
        and any(
            isinstance(part, dict) and part.get("type") == "image"
            for part in block["content"]
        )
    )


def _effort_for(step: int, stuck: bool) -> str:
    """Adıma göre düşünme bütçesi.

    İlk adım pahalı olmalı: yaklaşımı orada seçiyor ve yanlış yaklaşım
    sonraki on adımı çöpe atıyor. Ondan sonrası çoğunlukla mekanik —
    "düğmeye tıkla, sonucu doğrula" — ve `medium` yetiyor.

    Bir eylem hata verdiyse ajan tıkanmış demektir; orada tekrar `high`e
    çıkıyoruz. Aynı hatayı `medium` ile tekrarlamak en pahalı yol.
    """
    if step == 0 or stuck:
        return "high"
    return "medium"
