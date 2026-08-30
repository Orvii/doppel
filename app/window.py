"""Ajan penceresi — Windows 11 Fluent.

Uygulama Dosya Gezgini ve Ayarlar'ın yanında durduğunda oradan gelmiş gibi
görünmeli. Kendi tasarım dilimizi uydurmuyoruz; Fluent'in kendi kurallarına
uyuyoruz: Segoe UI Variable, 8 piksel kart yarıçapı, sistem vurgu rengi,
sistem teması.

Mikrofon burada değil. O her şeyden bağımsız, kendi penceresinde, ekranın
köşesinde duruyor (`mic.py`) — Berkay ajan penceresine bakmadan da basıp
konuşabilsin diye.

Pencere solda bir ray, sağda sayfalardan ibaret. Önce her şey
`QDockWidget`'tı ve ajan üç belge açtığında ekranda ne olduğunu kimse
söyleyemiyordu: dock'lar birbiriyle sekmeleniyor, yüzüyor, pencere kendi
kendine yeniden düzenleniyordu. Gerekçe `ray.py` içinde, kaybedilenle
birlikte.
"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import panels
from .fluent import GAP, RADIUS_CARD, RADIUS_CONTROL, Tokens
from .activity import ActivityView
from .ray import Oge, Ray, Sayfa

PHASE_LABEL = {
    "bos": "Ready",
    "dinleniyor": "Listening",
    "diziliyor": "Transcribing",
    "kosuyor": "Working",
    "onay": "Waiting for approval",
    "bitti": "Done",
    "durduruldu": "Stopped",
}


class StatusDot(QWidget):
    """Durum ışığı. Unicode karakteri değil, çizilmiş bir daire —
    bir glifin ağırlığı yazı tipine bağlıdır ve hiçbir zaman hizalanmaz."""

    def __init__(self, t: Tokens) -> None:
        super().__init__()
        self.setFixedSize(10, 10)
        self._colour = t.text_tertiary

    def set_colour(self, colour: str) -> None:
        self._colour = colour
        self.update()

    def paintEvent(self, _event) -> None:
        from PySide6.QtGui import QColor, QPainter

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._colour))
        painter.drawEllipse(1, 1, 8, 8)
        painter.end()


class KayitRozeti(QWidget):
    """Kayıt sürerken görünen kırmızı nokta, süre ve durdurma.

    Durum şeridinde duruyor, komut çubuğunda değil. Çubuk ajanın söz
    söylediği yer ve orada yazılan her şey bir sonraki cümlenin altında
    kalıyor; kaydın "hâlâ açık" demesi gereken süre ise dakikalar.
    Şerit ise pencere açıkken hep aynı yerde ve hiç kaymıyor.

    Nokta yanıp sönüyor. Sabit kırmızı bir daire durum ışığından
    ayırt edilemiyordu — şeritte zaten bir tane var ve ikisi yan yana
    "iki durum mu var" sorusunu doğuruyor. Yanıp sönen nokta her
    kayıt cihazının dili; kimseye açıklamak gerekmiyor.
    """

    stop_requested = Signal()

    #: Yanıp sönme periyodu. Bir saniye, saniye sayacıyla aynı ritimde:
    #: iki farklı hızda kıpırdayan iki şey, tek bir şeyden daha çok
    #: dikkat çekiyor ve dikkat burada kayda değil işe ait.
    ARALIK_MS = 1000

    def __init__(self, t: Tokens) -> None:
        super().__init__()
        self.t = t
        layout = QHBoxLayout(self)
        layout.setContentsMargins(GAP * 2, 0, GAP * 2, 0)
        layout.setSpacing(GAP)

        self._dot = StatusDot(t)
        self._dot.set_colour(t.critical)
        layout.addWidget(self._dot)

        self._label = QLabel("REC 0:00")
        self._label.setStyleSheet(
            f"color: {t.critical}; font-weight: 600; letter-spacing: 0.4px;"
        )
        layout.addWidget(self._label)

        self._stop = QPushButton("Stop recording")
        self._stop.setToolTip("Stop the recording and keep the video")
        self._stop.setFixedHeight(32)
        self._stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self._stop.clicked.connect(self.stop_requested.emit)
        layout.addWidget(self._stop)

        self._timer = QTimer(self)
        self._timer.setInterval(self.ARALIK_MS)
        self._timer.timeout.connect(self._tik)
        self._acik = True
        self._basladi = 0.0
        self.hide()

    def basladi(self) -> None:
        self._basladi = time.monotonic()
        self._acik = True
        self._dot.set_colour(self.t.critical)
        self._label.setText("REC 0:00")
        self._timer.start()
        self.show()

    def bitti(self) -> None:
        self._timer.stop()
        self.hide()

    def _tik(self) -> None:
        self._acik = not self._acik
        self._dot.set_colour(self.t.critical if self._acik else self.t.divider)
        gecen = int(time.monotonic() - self._basladi)
        self._label.setText(f"REC {gecen // 60}:{gecen % 60:02d}")


class Counter(QWidget):
    """Durum şeridindeki canlı sayaç."""

    def __init__(self, t: Tokens, label: str, warn: bool = False) -> None:
        super().__init__()
        self.t, self._warn = t, warn
        layout = QVBoxLayout(self)
        layout.setContentsMargins(GAP * 3, GAP * 2, GAP * 3, GAP * 2)
        layout.setSpacing(0)

        self._value = QLabel("0")
        self._value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._value)

        caption = QLabel(label)
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        caption.setProperty("role", "tertiary")
        layout.addWidget(caption)
        self.set_value(0)

    def set_value(self, value: int) -> None:
        colour = self.t.critical if (self._warn and value > 0) else self.t.text
        self._value.setText(str(value))
        self._value.setStyleSheet(
            f"font-family: '{self.t.font_display}', '{self.t.font_ui}';"
            f" font-size: 20px; font-weight: 600; color: {colour};"
        )


class StatusBar(QWidget):
    """Durum ve sayaçlar. Durdurma her zaman burada, hep etkin."""

    stop_requested = Signal()

    def __init__(self, t: Tokens) -> None:
        super().__init__()
        self.t = t
        self.setFixedHeight(56)
        self.setStyleSheet(
            f"background: {t.background}; border-top: 1px solid {t.divider};"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(GAP * 4, 0, GAP * 3, 0)
        layout.setSpacing(GAP * 2)

        self._dot = StatusDot(t)
        layout.addWidget(self._dot)

        self._phase = QLabel()
        self._phase.setProperty("role", "strong")
        layout.addWidget(self._phase)

        self._line = QLabel()
        self._line.setProperty("role", "caption")
        layout.addWidget(self._line, 1)

        #: Kayıt rozeti sayaçların solunda: sayaçlar hep orada duruyor ve
        #: rozet göründüğünde onları kaydırmıyor, aralarına girmiyor.
        self.kayit = KayitRozeti(t)
        layout.addWidget(self.kayit)

        self.steps = Counter(t, "steps")
        self.unsaved = Counter(t, "unsaved", warn=True)
        self.terminals = Counter(t, "terminals")
        for counter in (self.steps, self.unsaved, self.terminals):
            layout.addWidget(counter)

        self.connect_remote = QPushButton("Server")
        self.connect_remote.setToolTip("Connect to a server over SSH")
        self.connect_remote.setFixedHeight(32)
        self.connect_remote.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self.connect_remote)

        stop = QPushButton("Stop")
        stop.setToolTip("Stop the agent — Esc ×3 works from anywhere")
        stop.setFixedHeight(32)
        stop.setCursor(Qt.CursorShape.PointingHandCursor)
        stop.clicked.connect(self.stop_requested.emit)
        layout.addWidget(stop)

        self.set_phase("bos")
        self.set_line("Type or talk from the bar in the corner.")

    def set_phase(self, phase: str) -> None:
        active = phase in {"dinleniyor", "diziliyor", "kosuyor"}
        alert = phase in {"onay", "durduruldu"}
        colour = self.t.critical if alert else (self.t.accent if active else self.t.text_tertiary)
        self._dot.set_colour(colour)
        self._phase.setText(PHASE_LABEL.get(phase, phase))

    def set_line(self, text: str) -> None:
        self._line.setText(text)


def _kisa_etiket(baslik: str) -> str:
    """Ray etiketi başlığın ilk parçası.

    Başlıklar `butce.xlsx · sheet  (1 unsaved)` gibi geliyor ve 76
    piksellik bir raya sığmıyor. İlk parça neredeyse her zaman doğru adı
    taşıyor; tamamı sayfanın kendi başlığında duruyor.
    """
    return baslik.split("·")[0].strip() or baslik


#: Sayfa anahtarından çizim. Ajanın açtığı her sayfa türü kendi işaretini
#: alıyor; hepsi aynı simgeyle gelseydi ray okunmaz bir liste olurdu.
CIZIMLER = {
    "__uzak__": "sunucu",
    "__kod__": "sayfa",
    "__terminal__": "kabuk",
}


def _cizim(key: str) -> str:
    if key in CIZIMLER:
        return CIZIMLER[key]
    if key.startswith("__yetenek__"):
        return "yetenek"
    if key.endswith(".xlsx") or key.endswith(".csv"):
        return "tablo"
    if key.endswith(".docx") or key.endswith(".md"):
        return "yazi"
    return "sayfa"


class MainWindow(QMainWindow):
    stop_requested = Signal()
    #: Durum değişti. Tepsi simgesi buna bağlı: pencereye bakmadan da
    #: ajanın ne yaptığı görünmeli.
    phase_changed = Signal(str)

    def __init__(self, t: Tokens) -> None:
        super().__init__()
        self.t = t
        panels.set_tokens(t)

        self.setWindowTitle("Yan Masa")
        self.resize(1500, 940)

        self._phase = "bos"
        self._bar = None
        self._esc_hits: list[float] = []

        # Solda ray, sağda sayfalar. Önce her şey `QDockWidget`'tı ve ajan
        # üç belge açtığında ekranda ne olduğunu kimse söyleyemiyordu:
        # dock'lar birbiriyle sekmeleniyor, yüzüyor, kendi kendine yeniden
        # düzenleniyordu. Sayfa hep aynı yerde ve hep tam genişlikte.
        self.ray = Ray(t)
        self.ray.secildi.connect(self.show_page)
        self.stack = QStackedWidget()
        self._pages: dict[str, Sayfa] = {}

        merkez = QWidget()
        yatay = QHBoxLayout(merkez)
        yatay.setContentsMargins(0, 0, 0, 0)
        yatay.setSpacing(0)
        yatay.addWidget(self.ray)
        yatay.addWidget(self.stack, 1)
        self.setCentralWidget(merkez)

        # Akış her zaman ilk sayfa: ajanın ne yaptığı asıl içerik, belgeler
        # onun sonucu.
        self.activity = ActivityView(t)
        self.add_fixed_page("akis", "Activity", "defter", self.activity,
                            "Every step the agent takes")

        self.status = StatusBar(t)
        self.status.stop_requested.connect(self.stop)
        self.setStatusBar(self._status_host())

        self._wire_shortcuts()
        self.set_counters(0, 0, 0)

    # --- komut çubuğu bağlantısı -----------------------------------------

    def attach_bar(self, bar) -> None:
        """Köşedeki komut çubuğunu bağlar.

        Çubuk ana pencereye ait değil; pencere kapansa da yaşamaya devam
        etmeli. Bu yüzden pencere çubuğu sahiplenmiyor, yalnızca ona
        yazıyor.
        """
        self._bar = bar

    def run_instruction(self, text: str) -> None:
        """Çubuktan gelen yazılı komut."""
        self.set_phase("kosuyor")
        self.status.set_line(text)
        if self._bar is not None:
            self._bar.set_status(f"Working: {text}")

    def show_operation(self, op) -> None:
        """Ajanın o an yaptığı iş çubuktaki önizleme karesine düşer."""
        if self._bar is not None:
            self._bar.show_operation(op)

    def _status_host(self):
        from PySide6.QtWidgets import QStatusBar

        bar = QStatusBar()
        bar.setSizeGripEnabled(False)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setStyleSheet("QStatusBar::item { border: none; }")
        bar.addPermanentWidget(self.status, 1)
        return bar

    # --- paneller ---------------------------------------------------------

    def add_fixed_page(self, key: str, label: str, glyph: str,
                       body: QWidget, title: str = "",
                       basliksiz: bool = False) -> None:
        """Kapatılamayan sayfa — akış ve masa.

        Ajanın açtıklarından ayrı tutuluyorlar: onlar gelip gidiyor,
        bunlar hep orada. Ray ikisinin arasına bir ayraç çiziyor.
        """
        self._sayfa_kur(key, label, glyph, title or label, body,
                        kapatilabilir=False, basliksiz=basliksiz)

    def open_panel(self, key: str, title: str, body: QWidget,
                   glyph: str = "", label: str = "") -> None:
        """Ajan bir belge, terminal ya da panel açtığında sayfa belirir.

        Uygulama açılışta yalnızca akış ve masa ile geliyor: ortada hiç
        dosya yokken bir tablo sayfası göstermek, ajanın tablo üstünde
        çalıştığını sanmana yol açardı.
        """
        self._sayfa_kur(key, label or _kisa_etiket(title), glyph or _cizim(key),
                        title, body, kapatilabilir=True)
        self.show_page(key)

    def _sayfa_kur(self, key: str, label: str, glyph: str, title: str,
                   body: QWidget, kapatilabilir: bool,
                   basliksiz: bool = False) -> None:
        var = self._pages.get(key)
        if var is not None:
            # Aynı gövde tekrar geliyorsa dokunma: yerinden alıp geri
            # koymak kod sayfasında kaydırma konumunu başa döndürüyordu.
            var.set_govde(body)
            if var.baslik is not None:
                var.baslik.set_baslik(title)
            self.ray.etiketle(key, label)
            return
        sayfa = Sayfa(self.t, title, body, kapatilabilir, basliksiz)
        if kapatilabilir and sayfa.baslik is not None:
            sayfa.baslik.kapatildi.connect(
                lambda k=key: self.close_panel(k)
            )
        self.stack.addWidget(sayfa)
        self._pages[key] = sayfa
        self.ray.ekle(Oge(key, label, glyph, kapatilabilir))
        if len(self._pages) == 1:
            self.show_page(key)

    def show_page(self, key: str) -> None:
        sayfa = self._pages.get(key)
        if sayfa is None:
            return
        self.stack.setCurrentWidget(sayfa)
        self.ray.sec(key)

    def close_panel(self, key: str) -> None:
        sayfa = self._pages.pop(key, None)
        if sayfa is None:
            return
        komsu = self.ray.anahtarlar()
        self.stack.removeWidget(sayfa)
        sayfa.deleteLater()
        self.ray.cikar(key)
        if self.ray.etkin == key:
            # Kapanan sayfadan sonra boş bir yığın kalmamalı: bir önceki
            # sayfaya düşülüyor, o da yoksa akışa.
            i = komsu.index(key) if key in komsu else 0
            kalan = self.ray.anahtarlar()
            hedef = kalan[min(max(0, i - 1), len(kalan) - 1)] if kalan else ""
            if hedef:
                self.show_page(hedef)

    # --- kısayollar -------------------------------------------------------

    def _wire_shortcuts(self) -> None:
        stop = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        stop.setAutoRepeat(False)
        stop.activated.connect(self._escape_hit)

    def _escape_hit(self) -> None:
        now = time.monotonic()
        self._esc_hits = [t for t in self._esc_hits if now - t < 0.8] + [now]
        if len(self._esc_hits) >= 3:
            self._esc_hits.clear()
            self.stop()

    # --- ajan durumu ------------------------------------------------------

    def set_phase(self, phase: str) -> None:
        self._phase = phase
        self.status.set_phase(phase)
        self.phase_changed.emit(phase)

    def start_listening(self) -> None:
        self.set_phase("dinleniyor")
        self.status.set_line("Listening — it starts working when you let go.")

    def stop_listening(self) -> None:
        if self._phase != "dinleniyor":
            return
        self.set_phase("bos")
        # Ses motoru bağlı değil ve bu gizlenmiyor.
        self.status.set_line(
            "No voice engine — type into the bar in the corner instead."
        )

    def stop(self) -> None:
        self.set_phase("durduruldu")
        self.status.set_line("Stopped. Pending actions were cancelled.")
        self.stop_requested.emit()
        if self._bar is not None:
            self._bar.set_busy(False)
            self._bar.clear_approval()

    # --- ekran kaydı ------------------------------------------------------

    def kayit_basladi(self, yol: str) -> None:
        self.status.kayit.basladi()
        self.status.set_line(f"Recording to {yol}")

    def kayit_bitti(self, satir: str = "") -> None:
        self.status.kayit.bitti()
        if satir:
            self.status.set_line(satir)

    # --- değişiklikler ----------------------------------------------------

    def set_counters(self, steps: int, unsaved: int, terminals: int) -> None:
        self.status.steps.set_value(steps)
        self.status.unsaved.set_value(unsaved)
        self.status.terminals.set_value(terminals)
