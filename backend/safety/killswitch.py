"""Acil durdurma — Esc'ye üç kez arka arkaya basınca ajan durur.

Ayrı bir thread'de tuş durumunu yokluyor. Düşük seviyeli klavye kancası
(Windows'ta WH_KEYBOARD_LL) daha zarif olurdu ama bir mesaj döngüsü
gerektiriyor ve o döngü bloklanırsa acil durdurma da bloklanır. Yoklama
aptal ama hiçbir şeye bağlı değil — ajan döngüsü ne yaparsa yapsın çalışır.

Esc tek başına değil üç kere, çünkü tek Esc çok uygulamada anlamlı bir tuş;
ajan bir diyalog kapatırken kendi kendini durdurmamalı.

## Port: Esc okuma platformdan bağımsız hâle geldi

Tuş durumunu okuma işi `erisim.esc_okuyucu()`'nun cevabına devredildi.
Windows'ta yine `GetAsyncKeyState`; X11'de (Xlib kuruluysa) `XQueryKeymap`
— süreç içinde, ayrıcalık istemiyor. Xlib kurulu değilse okuma **yok** ve
o durumda acil durdurma yalnızca arayüzdeki durdur düğmesi ve SIGINT/
SIGTERM ile çalışır (`start()` bu sinyalleri bağlıyor). X11'de global tuş
grab'ı masaüstünü kilitlediği için bilinçli olarak yok; `/dev/input`
okumak ise ayrıcalık istiyor. Yani Linux'ta Esc "elinden gelenin en iyisi":
zorlamak yerine sınır yüksek sesle yazıldı.
"""

from __future__ import annotations

import signal
import threading
import time
from collections import deque

from ..computer import erisim

#: Windows sanal tuş kodu — eski adla uyumluluk için duruyor.
VK_ESCAPE = 0x1B

#: Kaç basış, kaç saniye içinde.
REQUIRED_PRESSES = 3
WINDOW_SECONDS = 0.8
POLL_SECONDS = 0.02


class KillSwitch:
    """`triggered` bir kez True olduktan sonra `reset()` çağrılana dek öyle kalır."""

    def __init__(
        self,
        required: int = REQUIRED_PRESSES,
        window: float = WINDOW_SECONDS,
        on_trigger=None,
    ) -> None:
        self._required = required
        self._window = window
        self._kancalar = [on_trigger] if on_trigger else []
        self._event = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        #: Yoklama başlarken kurulur. Kurulum anında yoklamak, her
        #: `KillSwitch()` kuran testte bir X bağlantısı açardı; burada
        #: bilinçli olarak None ve `start()` dolduruyor.
        self._okuyucu = None
        self._eski_sinyaller: list[tuple[int, object]] = []

    @property
    def triggered(self) -> bool:
        return self._event.is_set()

    def reset(self) -> None:
        self._event.clear()

    def ayrica_cagir(self, geri) -> None:
        """Tetiklenince çağrılacak bir kanca daha ekler.

        Kurucudaki tek kanca yetmiyordu: acil durdurmanın kapatması
        gereken şeyler birden fazla ve hepsi `KillSwitch` kurulduktan
        **sonra** var oluyor. Ekran kaydı bunun somut hâli — Esc x3'te
        ffmpeg'e `q` yazılmazsa arkada süreç kalıyor ve elde oynatılmayan
        bir dosya oluyor.
        """
        self._kancalar.append(geri)

    def trigger(self) -> None:
        """Elle tetikleme — arayüzdeki durdur düğmesi buraya bağlanacak."""
        if self._event.is_set():
            return
        self._event.set()
        for kanca in self._kancalar:
            # Bir kancanın patlaması diğerlerini engellememeli: acil
            # durdurmanın yarısının çalışması, hiç çalışmamasından
            # yalnızca biraz iyi.
            try:
                kanca()
            except Exception:
                pass

    def check(self) -> None:
        """Tetiklendiyse hata fırlatır. Ajan döngüsünde her adımda çağrılır."""
        if self._event.is_set():
            raise Aborted(
                f"Acil durdurma: Esc x{self._required}. Bekleyen eylemler iptal edildi."
            )

    def start(self) -> KillSwitch:
        """Yoklama thread'ini başlatır ve sinyal kancalarını bağlar.

        Windows'ta Esc okuyucusu her zaman var. Linux'ta Xlib kuruluysa
        XQueryKeymap ile, değilse okuma yok — o durumda SIGINT/SIGTERM
        bağlanır ki `xdotool`/`ytdotoool` fark etmeksizin bir terminal
        oturumundan çalıştırıldığında Ctrl-C acil durdurma sayılsın.
        Sinyal kancaları yalnızca ana thread'den bağlanabilir; başka bir
        thread'den çağrılırsa sessizce atlanır (`ValueError`).
        """
        if self._thread is not None:
            raise RuntimeError("the KillSwitch is already running")
        self._okuyucu = erisim.esc_okuyucu()
        if self._okuyucu is None:
            self._sinyalleri_bagla()
        self._thread = threading.Thread(target=self._watch, daemon=True, name="killswitch")
        self._thread.start()
        return self

    def _sinyalleri_bagla(self) -> None:
        eski: list[tuple[int, object]] = []
        for isaret in (signal.SIGINT, signal.SIGTERM):
            try:
                eski.append(
                    (isaret, signal.signal(isaret, lambda *_a: self.trigger()))
                )
            except ValueError:
                # Ana thread değil — sinyal bağlanamaz, Esc de yok.
                # Yüksek sesle söyle, sessizce yutma.
                print(
                    "killswitch: no Esc reader and signals unbound (not the main thread)",
                )
                return
        self._eski_sinyaller = eski

    def _sinyalleri_birak(self) -> None:
        for isaret, eski in self._eski_sinyaller:
            try:
                signal.signal(isaret, eski)
            except ValueError:
                pass
        self._eski_sinyaller = []

    def stop(self) -> None:
        self._sinyalleri_birak()
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def __enter__(self) -> KillSwitch:
        return self.start()

    def __exit__(self, *_exc) -> None:
        self.stop()

    def _watch(self) -> None:
        """Yoklama döngüsü. `_okuyucu` yoksa (Linux + Xlib yok) hemen biter.

        Thread yine de kurulur: `stop()` sözleşmesi her platformda aynı
        kalsın (join edilecek bir şey olsun) ve "başlatıldı ama çalışmıyor"
        durumu yalnızca `esc_okuyucu()`'nun None dönmesiyle anlaşılsın —
        orada docstring'inde yazdığı gibi.
        """
        get_state = self._okuyucu
        if get_state is None:
            return
        presses: deque[float] = deque(maxlen=self._required)
        was_down = False

        while not self._stop.is_set():
            # En anlamlı bit tuşun o an basılı olduğunu söyler.
            is_down = bool(get_state())
            if is_down and not was_down:
                now = time.monotonic()
                presses.append(now)
                if (
                    len(presses) == self._required
                    and now - presses[0] <= self._window
                ):
                    presses.clear()
                    self.trigger()
            was_down = is_down
            time.sleep(POLL_SECONDS)


class Aborted(RuntimeError):
    """Kullanıcı ajanı durdurdu."""
