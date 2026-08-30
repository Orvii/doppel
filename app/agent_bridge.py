"""Ajan çekirdeği ile arayüz arasındaki köprü.

Ajan döngüsü bloke çalışıyor: model çağrısı, araç çalıştırma, tekrar model
çağrısı. Bunu doğrudan arayüz thread'inde çağırmak pencereyi donduruyor —
ve donmuş bir pencerede acil durdurma düğmesine basılamıyor, ki bu tam da
basılması gereken an.

Bu yüzden döngü ayrı bir thread'de. `Turn` geri çağırmaları o thread'den
geliyor ve Qt sinyallerine çevriliyor; Qt sinyalleri thread sınırını
kuyruğa alarak geçtiği için arayüz güvenle güncelleniyor.

Onay istemi ters yönde çalışıyor: çalışan thread duruyor, arayüzde soru
çıkıyor, cevap gelince thread devam ediyor. `threading.Event` bunu yapan
en basit şey.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal


@dataclass
class ApprovalRequest:
    tool: str
    detail: str
    reason: str
    event: threading.Event
    approved: bool = False


class AgentBridge(QObject):
    """Ajan döngüsünü ayrı thread'de sürer, olayları sinyal olarak yayar."""

    said = Signal(str)           # ajanın konuştuğu metin (parça parça)
    thought = Signal(str)        # düşünce özeti
    acted = Signal(str, dict)    # araç adı, girdi
    result = Signal(str, str, bool, bytes)  # araç, metin, hata mı, kare
    approval = Signal(object)    # ApprovalRequest
    finished = Signal(str)       # tur bitti, son metin
    failed = Signal(str)
    ready = Signal(bool, str)    # ajan kuruldu mu, kurulamadıysa neden
    document = Signal(object)    # DocSnapshot — ajan bir belge açtı ya da değiştirdi
    panel = Signal(str, object)  # yetenek adı, panel tanımı
    wrote = Signal(list)         # ajanın az önce yazdığı dosya yolları
    queued = Signal(str)         # araya sıkıştırılan cümle sıraya alındı
    landed = Signal(str)         # ajan o cümleyi gördü
    rapor = Signal(str)          # ajanın iddiasının kayıtta karşılığı yok
    pulse = Signal()             # modelden bir parça düştü
    #: Model bir dosya yazıyor: araç, yol, o ana kadarki metin, bitti mi.
    kod = Signal(str, str, str, bool)

    def __init__(self) -> None:
        super().__init__()
        self._thread: QThread | None = None
        self._worker: _Worker | None = None
        self._agent = None
        self._kill = None
        self._capture = None
        self._busy = False
        #: Kuru koşu. Ajan henüz kurulmamış olabilir ve anahtar o zaman da
        #: çevrilebiliyor; değer burada bekliyor ve ajan gelince
        #: uygulanıyor. Beklemeseydi açılışta çevrilen anahtar sessizce
        #: yok sayılırdı.
        self._kuru = False

    @property
    def busy(self) -> bool:
        return self._busy

    def start(self) -> None:
        """Ajanı kurar. Anahtar yoksa sessizce yarım kalmıyor, söylüyor."""
        try:
            from backend import config
            from backend.computer.capture import ScreenCapture
            from backend.computer.displays import enumerate_displays
            from backend.safety.killswitch import KillSwitch
            from backend.agent.loop import Agent

            cfg = config.Config.load()
            displays = enumerate_displays()
            self._capture = ScreenCapture(displays)
            self._kill = KillSwitch().start()
            self._agent = Agent.create(
                cfg, displays, self._capture, self._kill, approve=self._ask_approval
            )
            self._agent.dispatcher.kuru = self._kuru
            # Esc x3 kaydı da durdursun. Turun çözülmesini beklemek
            # yeterli değil: ajan model cevabını beklerken durdurulursa
            # ffmpeg saniyelerce daha kaydetmeye devam ederdi.
            self._kill.ayrica_cagir(self._agent.dispatcher.ekran_kaydi.kapat)
        except Exception as exc:
            self.ready.emit(False, str(exc))
            return
        self.ready.emit(True, "")

    def set_kuru(self, kuru: bool) -> None:
        """Kuru koşuyu açar ya da kapatır."""
        self._kuru = kuru
        if self._agent is not None:
            self._agent.dispatcher.kuru = kuru

    @property
    def kuru(self) -> bool:
        return self._kuru

    def expand_command(self, line: str) -> str | None:
        """`/ad` kısayolunu hazır talimata çevirir."""
        if self._agent is None:
            return None
        try:
            return self._agent.dispatcher.skills.expand(line)
        except Exception:
            return None

    def dispatcher(self):
        """Ajanın araç çalıştırıcısı — yan masaüstü onun elinde.

        Canlı görüntü buradan okuyor. Ajan kurulamamışsa `None` dönüyor ve
        masa penceresi boş masayı gösteriyor; kurulum hatası yüzünden
        pencerenin hiç açılmaması, hatanın kendisinden daha kafa
        karıştırıcı olurdu.
        """
        return None if self._agent is None else self._agent.dispatcher

    def mcp_durumlari(self) -> list:
        """MCP sunucularının hâli.

        Ajan kurulmadan da çalışıyor: yapılandırma diskte duruyor ve
        API anahtarı olmadan da sunucu eklenip düzenlenebilmeli. O
        durumda hepsi "kapalı" görünüyor, ki doğrusu da bu — bağlanan
        bir şey yok.
        """
        if self._agent is not None:
            return self._agent.dispatcher.mcp.durumlar()
        from backend.mcp import ayar as ayar_mod
        from backend.mcp.istemci import Baglanti

        return [Baglanti(sunucu=s) for s in ayar_mod.oku()]

    def mcp_yenile(self) -> None:
        """Yapılandırma değişti — açılanları bağla, kapananları kapat."""
        if self._agent is not None:
            self._agent.dispatcher.mcp.yenile()

    def akislar(self):
        """Akış deposu. Ajan kurulamadıysa da çalışıyor: kayıtlı akışlar
        diskte duruyor ve API anahtarı olmadan da listelenebilmeli."""
        if self._agent is not None:
            return self._agent.dispatcher.akislar
        from backend.workflows.depo import AkisDeposu

        return AkisDeposu()

    def oynat(self, ad: str) -> None:
        """Kaydedilmiş akışı oynatır — modele hiç uğramadan.

        Ayrı bir thread'de, çünkü oynatma tıklıyor, yazıyor ve bekliyor;
        arayüz thread'inde çalışsaydı pencere donar ve donmuş bir
        pencerede durdurma düğmesine basılamazdı.

        Sinyaller gerçek koşuyla aynı: akış sayfası, halka ve çubuk
        oynatmayı da bir koşu gibi gösteriyor. Ayrı bir yol açmak, aynı
        arayüzü ikinci kez yazmak olurdu.
        """
        if self._agent is None or self._busy:
            return
        akis = self._agent.dispatcher.akislar.al(ad)
        if akis is None:
            self.failed.emit(f"There is no workflow called {ad!r}.")
            return
        self._busy = True
        self._kill.reset()
        self._thread = QThread()
        self._worker = _OynatIscisi(self._agent, akis, self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_done)
        self._thread.start()

    # --- ekran kaydı ------------------------------------------------------

    def kayit_hedefi(self) -> str:
        """Şu an kaydedilen dosya. Kayıt yoksa boş dize."""
        if self._agent is None:
            return ""
        hedef = self._agent.dispatcher.ekran_kaydi.hedef
        return str(hedef) if hedef else ""

    def kaydi_durdur(self) -> str:
        """Arayüzdeki 'Stop recording' düğmesi. Sonucu tek satır olarak
        döndürüyor.

        Arayüz thread'inden çağrılıyor ve ajan o sırada çalışıyor
        olabilir; `EkranKaydi` kendi kilidini tutuyor, ffmpeg'e `q`
        yazmak yarım saniye sürüyor ve o kadarlık bir donma, kaydı
        durduramamaktan iyi.
        """
        if self._agent is None:
            return ""
        kayit = self._agent.dispatcher.ekran_kaydi
        if not kayit.suruyor:
            return ""
        try:
            hedef = kayit.durdur()
        except Exception as exc:
            return str(exc)
        return f"Recording saved: {hedef} ({kayit.sure:.1f}s)."

    def remote_session(self):
        """Ajanın bağlı olduğu sunucu — yoksa None."""
        if self._agent is None:
            return None
        return self._agent.dispatcher.remote

    def adopt_remote(self, session) -> None:
        """Berkay elle bağlandığında ajan da aynı oturumu kullansın.

        İki ayrı bağlantı tutmak, panelde bir yeri gezerken ajana başka bir
        yerden bahsetmek demekti.
        """
        if self._agent is not None:
            self._agent.dispatcher.remote = session

    def button_store(self):
        """Düğme deposu. Ajan kurulamadıysa da çalışıyor: düğmeler tercih,
        API anahtarına bağlı olmamalı."""
        from backend.skills.shortcuts import ShortcutStore

        if self._agent is not None:
            return self._agent.dispatcher.buttons
        return ShortcutStore()

    def commands(self) -> list[tuple[str, str]]:
        if self._agent is None:
            return []
        registry = self._agent.dispatcher.skills
        registry.refresh()
        return [(c.name, c.description) for c in registry.commands.values()]

    def stop(self) -> None:
        if self._kill is not None:
            self._kill.trigger()

    def shutdown(self) -> None:
        if self._kill is not None:
            self._kill.stop()
        if self._agent is not None:
            self._agent.dispatcher.shutdown()
        if self._capture is not None:
            self._capture.close()

    # --- onay -------------------------------------------------------------

    def _ask_approval(self, tool: str, detail: str, reason: str) -> bool:
        """Çalışan thread'den çağrılıyor; arayüz cevaplayana kadar bekliyor."""
        request = ApprovalRequest(tool, detail, reason, threading.Event())
        self.approval.emit(request)
        # Süresiz bekleme yok: arayüz çökerse ya da pencere kapanırsa
        # eylem kendiliğinden reddedilmiş sayılır, asılı kalmaz.
        if not request.event.wait(timeout=300):
            return False
        return request.approved

    # --- koşu -------------------------------------------------------------

    def run(self, instruction: str) -> None:
        """Yeni bir tur başlatır ya da çalışan tura cümleyi ekler.

        Eskiden çalışırken gelen mesaj **sessizce düşüyordu**: yazıyordun,
        Enter'a basıyordun, hiçbir şey olmuyordu. Artık kuyruğa giriyor ve
        ajan bir sonraki adımda görüyor.
        """
        if self._agent is None:
            return
        if self._busy:
            self._agent.interject(instruction)
            self.queued.emit(instruction)
            return
        self._busy = True
        self._kill.reset()

        self._thread = QThread()
        self._worker = _Worker(self._agent, instruction, self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_done)
        self._thread.start()

    def _on_done(self, text: str, error: str) -> None:
        self._busy = False
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(2000)
            self._thread = None
        if error:
            self.failed.emit(error)
        else:
            self.finished.emit(text)

        # Tur biterken kuyrukta kalan varsa yeni bir tur olarak sürüyor.
        # Son adımdan sonra yazılan bir cümle yoksa kaybolurdu.
        kalan = self._agent.take_pending() if self._agent else []
        if kalan:
            self.run("\n".join(kalan))


class _Worker(QObject):
    done = Signal(str, str)

    def __init__(self, agent, instruction: str, bridge: AgentBridge) -> None:
        super().__init__()
        self._agent = agent
        self._instruction = instruction
        self._bridge = bridge

    def _on_result(self, name: str, outcome) -> None:
        # Yan alan eylemleri modele kare göndermiyor ama arayüz görmeli:
        # "çalışma alanı görülecek zaten" — orada olan biten görünmezse
        # ikinci imleç bir kara kutu olurdu.
        kare = _as_png(outcome.content)
        yan = getattr(self._agent.dispatcher, "last_side_frame", None)
        if yan and not kare:
            kare = yan
        if yan:
            self._agent.dispatcher.last_side_frame = None
        self._bridge.result.emit(
            name, _as_text(outcome.content), outcome.is_error, kare,
        )
        # Belge anlık görüntüsü burada, ajanın kendi thread'inde çıkıyor:
        # arayüz `openpyxl` nesnesine hiç dokunmuyor.
        if name.startswith("office_") and not outcome.is_error:
            self._emit_documents()
        son = getattr(self._agent.dispatcher, "last_panel", None)
        if son is not None:
            self._agent.dispatcher.last_panel = None
            self._bridge.panel.emit(son[0], son[1])
        yazilan = getattr(self._agent.dispatcher, "last_files", None)
        if yazilan:
            self._agent.dispatcher.last_files = []
            self._bridge.wrote.emit(list(yazilan))

    def _emit_documents(self) -> None:
        from .snapshot import snapshot

        store = getattr(self._agent.dispatcher, "office", None)
        if store is None:
            return
        for doc_name in store.names():
            try:
                shot = snapshot(doc_name, store.get(doc_name))
            except Exception:
                continue
            if shot is not None:
                self._bridge.document.emit(shot)

    def run(self) -> None:
        from backend.agent.loop import Turn
        from backend.safety.killswitch import Aborted

        turn = Turn(
            on_text=self._bridge.said.emit,
            on_thinking=self._bridge.thought.emit,
            on_action=lambda name, payload: self._bridge.acted.emit(name, dict(payload)),
            on_result=self._on_result,
            on_interjection=self._bridge.landed.emit,
            on_pulse=self._bridge.pulse.emit,
            on_rapor=self._bridge.rapor.emit,
            on_kod=self._bridge.kod.emit,
        )
        try:
            text = self._agent.run(self._instruction, turn)
            self.done.emit(text, "")
        except Aborted as exc:
            self.done.emit("", str(exc))
        except Exception as exc:
            self.done.emit("", f"{type(exc).__name__}: {exc}")


def _as_png(content: Any) -> bytes:
    """Araç sonucundaki ekran görüntüsünü çıkarır.

    Model bunu base64 olarak alıyor; arayüz de aynı kareyi görmeli.
    Ajanın gördüğünü göstermek yerine temsilî bir simge koymak, "ne
    gördü" sorusunu cevapsız bırakırdı.
    """
    import base64

    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "image":
                data = part.get("source", {}).get("data")
                if data:
                    try:
                        return base64.b64decode(data)
                    except ValueError:
                        return b""
    return b""


def _as_text(content: Any) -> str:
    """Araç sonucu görsel blok olabilir; arayüze metin gidiyor."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        if any(isinstance(p, dict) and p.get("type") == "image" for p in content):
            return "(screenshot)"
        return " ".join(str(p) for p in content)
    return str(content)


class _OynatIscisi(QObject):
    """Akış oynatmayı ajan thread'inde süren işçi."""

    done = Signal(str, str)

    def __init__(self, agent, akis, bridge: AgentBridge) -> None:
        super().__init__()
        self._agent = agent
        self._akis = akis
        self._bridge = bridge

    def run(self) -> None:
        kayit = self._agent.kayit
        # Oynatma da denetim kaydına giriyor: geçmişte "bu iş bugün
        # yapıldı" demek, onu kimin başlattığından bağımsız.
        kayit.tur_basladi(f"workflow: {self._akis.etiket}")

        def adim(ad: str, girdi: dict) -> None:
            self._bridge.acted.emit(ad, dict(girdi))

        def sonuc(ad: str, cikti) -> None:
            metin = cikti.content if isinstance(cikti.content, str) else "(image)"
            kayit.eylem(ad, {}, cikti.is_error, metin)
            self._bridge.result.emit(ad, metin, cikti.is_error, b"")

        try:
            rapor = self._agent.dispatcher.calistir(self._akis, adim, sonuc)
        except Exception as exc:
            kayit.tur_bitti(f"{type(exc).__name__}: {exc}")
            self.done.emit("", f"{type(exc).__name__}: {exc}")
            return
        kayit.tur_bitti(rapor.anlat())
        if rapor.basarili:
            self.done.emit(rapor.anlat(), "")
        else:
            self.done.emit("", rapor.anlat())
