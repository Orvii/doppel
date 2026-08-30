"""Acil durdurma — Esc'ye üç kez arka arkaya basınca ajan durur.

Ayrı bir thread'de `GetAsyncKeyState` ile yoklama yapıyor. Düşük seviyeli
klavye kancası (WH_KEYBOARD_LL) daha zarif olurdu ama bir mesaj döngüsü
gerektiriyor ve o döngü bloklanırsa acil durdurma da bloklanır. Yoklama
aptal ama hiçbir şeye bağlı değil — ajan döngüsü ne yaparsa yapsın çalışır.

Esc tek başına değil üç kere, çünkü tek Esc çoğu uygulamada anlamlı bir tuş;
ajan bir diyalog kapatırken kendi kendini durdurmamalı.
"""

from __future__ import annotations

import ctypes
import threading
import time
from collections import deque

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
        if self._thread is not None:
            raise RuntimeError("the KillSwitch is already running")
        self._thread = threading.Thread(target=self._watch, daemon=True, name="killswitch")
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def __enter__(self) -> KillSwitch:
        return self.start()

    def __exit__(self, *_exc) -> None:
        self.stop()

    def _watch(self) -> None:
        get_state = ctypes.windll.user32.GetAsyncKeyState
        presses: deque[float] = deque(maxlen=self._required)
        was_down = False

        while not self._stop.is_set():
            # En anlamlı bit tuşun o an basılı olduğunu söyler.
            is_down = bool(get_state(VK_ESCAPE) & 0x8000)
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
