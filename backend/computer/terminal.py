"""Kalıcı terminal oturumları — ajanın TUI uygulamaları kullanabilmesi için.

`run_shell` tek atışlık ve etkileşimsiz: komutu çalıştırır, çıktıyı verir,
biter. Claude Code, opencode, `git rebase -i`, bir Python REPL — hiçbiri
orada çalışmaz, girdi bekleyip zaman aşımına düşerler.

Buradaki yaklaşım: ConPTY ile gerçek bir sahte terminal aç, çıktısını bir
terminal emülatöründen (`pyte`) geçir ve ajana **ekranın metin hali**ni ver.
Ajan Claude Code'un TUI'sini ekran görüntüsü almadan, koordinat tahmin
etmeden, düz metin olarak okur. Bir kare ~1500 token; aynı terminalin metni
~600 token ve içindeki her karakter kesin.

Ham çıktıyı biriktirip vermek işe yaramaz: TUI'ler ekranı imleç hareketleri
ve silme dizileriyle yeniden çizer, yani ham akış aynı satırın onlarca
sürümünü içerir. Emülatör bu akışı ekranın *son hali*ne indiriyor — insanın
gördüğü şeye.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

import pyte

try:
    import winpty
except ImportError:  # Linux: ConPTY yok — modül içe aktarılabilir kalsın
    winpty = None  # type: ignore[assignment]

DEFAULT_COLS = 120
DEFAULT_ROWS = 40

#: Ekranın "durulmuş" sayılması için geçmesi gereken sessizlik.
IDLE_SECONDS = 0.4

#: Tuş adı -> terminale gönderilecek dizi. TUI'lerde gezinmek için gerekli;
#: `type_text` ile ok tuşu gönderemezsin.
KEYS = {
    "enter": "\r",
    "tab": "\t",
    "escape": "\x1b",
    "backspace": "\x7f",
    "up": "\x1b[A",
    "down": "\x1b[B",
    "right": "\x1b[C",
    "left": "\x1b[D",
    "home": "\x1b[H",
    "end": "\x1b[F",
    "page_up": "\x1b[5~",
    "page_down": "\x1b[6~",
    "ctrl+c": "\x03",
    "ctrl+d": "\x04",
    "ctrl+z": "\x1a",
    "ctrl+l": "\x0c",
    "ctrl+u": "\x15",
    "shift+tab": "\x1b[Z",
}


class TerminalError(RuntimeError):
    """Oturum açılamadı ya da bulunamadı."""


@dataclass
class TerminalSession:
    """Bir PTY ve onun ekranı."""

    name: str
    cwd: str
    process: winpty.PtyProcess
    screen: pyte.Screen
    stream: pyte.Stream
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _last_output: float = field(default_factory=time.monotonic)
    _awaiting: bool = True
    _reader: threading.Thread | None = None
    _closed: threading.Event = field(default_factory=threading.Event)

    @classmethod
    def open(
        cls,
        name: str,
        command: str | None = None,
        cwd: str | None = None,
        cols: int = DEFAULT_COLS,
        rows: int = DEFAULT_ROWS,
    ) -> TerminalSession:
        if winpty is None:
            raise TerminalError(
                "The terminal needs Windows ConPTY (pywinpty); it is not "
                "available on this platform."
            )
        argv = command or "powershell.exe -NoLogo -NoProfile"
        try:
            process = winpty.PtyProcess.spawn(
                argv, cwd=cwd, dimensions=(rows, cols), backend=winpty.Backend.ConPTY
            )
        except Exception as exc:
            raise TerminalError(f"could not start {argv!r}: {exc}") from None

        screen = pyte.Screen(cols, rows)
        session = cls(
            name=name,
            cwd=cwd or "",
            process=process,
            screen=screen,
            stream=pyte.Stream(screen),
        )
        session._start_reader()
        return session

    def _start_reader(self) -> None:
        def pump() -> None:
            while not self._closed.is_set():
                try:
                    data = self.process.read(4096)
                except (EOFError, OSError):
                    break
                if not data:
                    time.sleep(0.02)
                    continue
                self._answer_queries(data)
                with self._lock:
                    self.stream.feed(data)
                    self._last_output = time.monotonic()
                    self._awaiting = False

        self._reader = threading.Thread(target=pump, daemon=True,
                                        name=f"pty-{self.name}")
        self._reader.start()

    def _answer_queries(self, data: str) -> None:
        """ConPTY'nin terminal yetenek sorgularını cevaplar.

        ConPTY açılışta `ESC[c` (cihaz öznitelikleri) gönderip **cevap
        bekliyor**. Cevaplamazsan hiçbir zaman prompt yazmıyor; oturum canlı
        görünüyor ama ekran sonsuza kadar boş kalıyor. İlk sürüm tam olarak
        böyle sessizce takıldı.

        Yalnızca gerçek sorgular cevaplanır. `ESC[1t` bir sorgu değil,
        terminale verilen bir komut (pencereyi geri yükle) — ona cevap
        yazmak, cevabı kabuğa yazılmış bir tuş dizisi olarak gönderiyor ve
        komut satırına `[8;40;120t` diye düşüyor. İlk denemede öyle oldu.
        """
        try:
            if "\x1b[c" in data:
                self.process.write("\x1b[?1;0c")  # VT100, seçenek yok
        except OSError:
            pass  # süreç kapanmış; okuyucu bir sonraki turda zaten çıkacak

    @property
    def alive(self) -> bool:
        return self.process.isalive() and not self._closed.is_set()

    def send(self, text: str) -> None:
        if not self.alive:
            raise TerminalError(f"session {self.name!r} is closed")
        with self._lock:
            self._awaiting = True
            self._last_output = time.monotonic()
        self.process.write(text)

    def send_key(self, key: str) -> None:
        sequence = KEYS.get(key.strip().lower())
        if sequence is None:
            raise TerminalError(
                f"Unknown key: {key!r}. The valid ones are: {', '.join(sorted(KEYS))}"
            )
        self.send(sequence)

    def wait_idle(self, timeout: float = 10.0, idle: float = IDLE_SECONDS) -> bool:
        """Çıktı durana kadar bekler. Durduysa True, zaman aşımında False.

        TUI'ler kademeli çiziyor; ilk baytı görür görmez ekranı okumak yarım
        çizilmiş bir arayüz döndürür. "Bir süredir yeni bayt yok" pratikte
        "çizim bitti" demek.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                quiet = time.monotonic() - self._last_output
                awaiting = self._awaiting
            # `awaiting` olmadan bu döngü hiç çıktı gelmeden "duruldu" der ve
            # ajana boş bir ekran döndürür.
            if not awaiting and quiet >= idle:
                return True
            time.sleep(0.05)
        return False

    def screen_text(self, trim: bool = True) -> str:
        """Ekranın şu anki hali. TUI'lerde imleç konumu da eklenir."""
        with self._lock:
            lines = list(self.screen.display)
            cursor = (self.screen.cursor.y, self.screen.cursor.x)

        if trim:
            lines = [line.rstrip() for line in lines]
            while lines and not lines[-1]:
                lines.pop()

        body = "\n".join(lines) if lines else "(the screen is empty)"
        return f"{body}\n[cursor: row {cursor[0]}, column {cursor[1]}]"

    def close(self) -> None:
        self._closed.set()
        try:
            self.process.terminate(force=True)
        except Exception:
            pass


class TerminalRegistry:
    """Açık oturumlar. Ajan bunlara isimle erişiyor."""

    MAX_SESSIONS = 6

    def __init__(self) -> None:
        self._sessions: dict[str, TerminalSession] = {}

    def open(self, name: str, command: str | None = None,
             cwd: str | None = None) -> TerminalSession:
        if name in self._sessions and self._sessions[name].alive:
            raise TerminalError(
                f"A session named {name!r} is already open. You can write to it or "
                f"close it and open it again."
            )
        if len(self._sessions) >= self.MAX_SESSIONS:
            self._reap()
        if len(self._sessions) >= self.MAX_SESSIONS:
            raise TerminalError(
                f"At most {self.MAX_SESSIONS} sessions can be open. "
                f"Close one you are not using."
            )

        session = TerminalSession.open(name, command=command, cwd=cwd)
        self._sessions[name] = session
        return session

    def get(self, name: str) -> TerminalSession:
        session = self._sessions.get(name)
        if session is None:
            known = ", ".join(sorted(self._sessions)) or "none"
            raise TerminalError(f"There is no session {name!r}. Open sessions: {known}")
        return session

    def close(self, name: str) -> None:
        session = self._sessions.pop(name, None)
        if session is None:
            raise TerminalError(f"there is no session {name!r}")
        session.close()

    def close_all(self) -> None:
        for session in self._sessions.values():
            session.close()
        self._sessions.clear()

    def names(self) -> list[str]:
        return sorted(self._sessions)

    def _reap(self) -> None:
        for name in [n for n, s in self._sessions.items() if not s.alive]:
            self._sessions.pop(name).close()
