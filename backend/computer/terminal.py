"""Kalıcı terminal oturumları — ajanın TUI uygulamaları kullanabilmesi için.

`run_shell` tek atışlık ve etkileşimsiz: komutu çalıştırır, çıktıyı verir,
biter. Claude Code, opencode, `git rebase -i`, bir Python REPL — hiçbiri
orada çalışmaz, girdi bekleyip zaman aşımına düşerler.

Buradaki yaklaşım: gerçek bir sahte terminal aç, çıktısını bir terminal
emülatöründen (`pyte`) geçir ve ajana **ekranın metin hali**ni ver. Ajan
Claude Code'un TUI'sini ekran görüntüsü almadan, koordinat tahmin etmeden,
düz metin olarak okur. Bir kare ~1500 token; aynı terminalin metni ~600
token ve içindeki her karakter kesin.

Ham çıktıyı biriktirip vermek işe yaramaz: TUI'ler ekranı imleç hareketleri
ve silme dizileriyle yeniden çizer, yani ham akış aynı satırın onlarca
sürümünü içerir. Emülatör bu akışı ekranın *son hali*ne indiriyor — insanın
gördüğü şeye.

## Platform: tek dikiş

Windows ConPTY'yi `pywinpty` ile kullanıyor; ConPTY Windows çekirdeğinde
olduğu için Linux'ta pywinpty **yok ve olamaz**. Linux tarafı stdlib `pty`
ailesiyle açılıyor. İki taraf da aynı protokolü uyguluyor (`PtyArkaUcu`:
isalive/read/write/setwinsize/stop); `TerminalSession` hangi arka uçta
koştuğunu bilmiyor, platform kararı tek yerde: `arka_uc_sinifi()`.

Linux'ta `os.forkpty()` kullanılıyor — `pty.openpty()` + `subprocess.Popen`
değil. Sebep kontrol terminali: `Popen(..., start_new_session=True)` yalnızca
`setsid` yapar, slave fd çocuğa ana süreçte açılmış olarak miras kalır ama
çekirdek kontrol terminalini yalnızca "oturum lideri bir tty'yi açarken"
atar — miras kalan fd bu koşulu sağlamaz. Kontrol terminali olmayınca
kabuğun iş denetimi yok olur ve line discipline'in ürettiği sinyaller
(^C, ^Z) gidecek ön plan grubu bulamaz; ajanın `ctrl+c` tuşu sessizce
yutulur. `forkpty` fork + setsid + TIOCSCTTY'i tek adımda çekirdekte
yapıyor. Boyut değişikliğinin SIGWINCH üretmesi de aynı yüzden buna bağlı:
ioctl master'a yazılıyor, çekirdek slave'in ön plan grubuna yolluyor.

PTY görüntü sunucusu istemiyor: bu modül X11, Wayland ve masaüstüsüz
(SSH/headless) oturumlarda aynı çalışır — oturum türünden bağımsız.
"""

from __future__ import annotations

import codecs
import errno
import os
import shlex
import shutil
import signal
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Mapping, Protocol

import pyte

if os.name == "nt":  # pragma: no cover - platforma bağlı dal
    import winpty
else:                # pragma: no cover - platforma bağlı dal
    import fcntl
    import termios

    winpty = None  # pywinpty yalnızca Windows'ta var; adı yoksa çağrı da yok

DEFAULT_COLS = 120
DEFAULT_ROWS = 40

#: Ekranın "durulmuş" sayılması için geçmesi gereken sessizlik.
IDLE_SECONDS = 0.4

#: Kapanış sırası: SIGTERM'den sonra süreç grubuna bu kadar süre veriliyor.
#: Yetmezse SIGKILL — `kayit.py`'nin ffmpeg'i `q` → bekle → öldür sırasının
#: sinyalli hali: önce kibarca, olmazsa sert.
STOP_GRACE_SECONDS = 2.0

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


# --- Linux planı: saf fonksiyonlar --------------------------------------
#
# Hepsi Windows'ta da koşuyor (testler orada): dosya sistemine dokunan tek
# şey `kabuk_argv`nin varsayılanı, o da `var_mi` ile enjekte edilebiliyor.


def _calistirilabilir(yol: str) -> bool:
    return os.path.exists(yol) and os.access(yol, os.X_OK)


def kabuk_argv(ortam: Mapping[str, str] | None = None,
               var_mi: Callable[[str], bool] | None = None) -> list[str]:
    """Linux'ta açılacak kabuk: `$SHELL` → `/bin/bash` → `/bin/sh`.

    zsh'a sabitlenmiyor: zsh her Linux'ta kurulu değil ve `$SHELL`
    kullanıcının kendi seçimi (fish, bash, zsh...). `$SHELL` bayat bir
    yola işaret ediyorsa da sıradaki adaya düşülüyor.
    """
    kaynak = os.environ if ortam is None else ortam
    kontrol = _calistirilabilir if var_mi is None else var_mi
    for yol in (kaynak.get("SHELL", ""), "/bin/bash", "/bin/sh"):
        if yol and kontrol(yol):
            return [yol]
    raise TerminalError(
        "no usable shell found: $SHELL, /bin/bash and /bin/sh are all "
        "missing or not executable")


def oturum_ortami(ortam: Mapping[str, str] | None = None) -> dict[str, str]:
    """Çocuğa verilecek ortam; `TERM` burada sabitleniyor.

    Uygulama GUI'den başladığında `TERM` hiç olmayabiliyor ya da "dumb"
    oluyor; TUI'ler ikisinde de çizmiyor. Buradaki ekran gerçekten 256
    renk çiziyor (pyte), yani xterm-256color doğru beyan — abartı değil.
    Girdi sözlüğü değiştirilmiyor, kopyası dönüyor.
    """
    yeni = dict(os.environ if ortam is None else ortam)
    yeni["TERM"] = "xterm-256color"
    return yeni


def pencere_verisi(cols: int, rows: int) -> bytes:
    """`struct winsize`: satır, sütun, x piksel, y piksel — dördü de 16 bit.

    Alan sırası ters görünüyor ama ioctl böyle istiyor; satır/sütun
    karışması burada sessizce yanlış çizilmiş bir ekran demek, o yüzden
    paketleme tek yerde ve testli.
    """
    return struct.pack("HHHH", rows, cols, 0, 0)


def acilis_plani(komut: str | None,
                 cwd: str | None = None,
                 ortam: Mapping[str, str] | None = None,
                 var_mi: Callable[[str], bool] | None = None
                 ) -> tuple[list[str], str | None, dict[str, str]]:
    """Linux oturumunun planı: `(argv, cwd, ortam)`. Hepsi saf.

    `komut` Windows'taki gibi tek satır bir komut ("python", "git rebase
    -i"); POSIX kurallarıyla (`shlex`) ayrılıyor — winpty de aynı işi
    yapıyor, yani iki platform aynı girdiyi aynı yürütülebilir dosyaya
    çeviriyor. Boş komut kabuğu açar.
    """
    if komut and komut.strip():
        try:
            argv = shlex.split(komut)
        except ValueError as exc:  # kapanmamış tırnak
            raise TerminalError(
                f"could not parse command {komut!r}: {exc}") from None
    else:
        argv = kabuk_argv(ortam, var_mi)
    return argv, cwd, oturum_ortami(ortam)


def surec_kapat(sag_mi: Callable[[], bool],
                sinyal_gonder: Callable[[int], None],
                sinyaller: tuple[int, int] | None = None,
                bekle: Callable[[float], None] = time.sleep,
                adim: float = 0.05,
                sure: float = STOP_GRACE_SECONDS) -> bool:
    """Grubu kapatır: önce yumuşak sinyal, süre dolarsa sert.

    Hepsi parametre — burada gerçek sinyal, gerçek bekleme yok; testler
    sahte bir süreçle ("öldü mü?" sorusuna cevap veren) tam sırayı
    ölçüyor. Zorla öldürmek gerektiyse `True` döner.
    """
    yumusak, sert = sinyaller or (signal.SIGTERM, signal.SIGKILL)
    sinyal_gonder(yumusak)
    son = time.monotonic() + sure
    while time.monotonic() < son:
        if not sag_mi():
            return False
        bekle(adim)
    if not sag_mi():
        return False
    sinyal_gonder(sert)
    return True


# --- Arka uçlar ----------------------------------------------------------


class PtyArkaUcu(Protocol):
    """Oturumun gördüğü tek sözleşme. Platform bunun arkasında saklı."""

    def isalive(self) -> bool: ...
    def read(self, size: int = 4096) -> str: ...
    def write(self, metin: str) -> None: ...
    def setwinsize(self, cols: int, rows: int) -> None: ...
    def stop(self) -> None: ...


class _WinptyArkaUcu:
    """Windows: pywinpty/ConPTY. Çağrılar eskisiyle birebir aynı."""

    def __init__(self, process) -> None:
        self._process = process

    @classmethod
    def spawn(cls, komut: str | None, cwd: str | None = None,
              cols: int = DEFAULT_COLS, rows: int = DEFAULT_ROWS):
        argv = komut or "powershell.exe -NoLogo -NoProfile"
        if winpty is None:  # normalde olmaz; kurulmamışsa sessiz ölme
            raise TerminalError(
                "pywinpty is not installed, so no terminal can be opened")
        try:
            process = winpty.PtyProcess.spawn(
                argv, cwd=cwd, dimensions=(rows, cols), backend=winpty.Backend.ConPTY
            )
        except Exception as exc:
            raise TerminalError(f"could not start {argv!r}: {exc}") from None
        return cls(process)

    def isalive(self) -> bool:
        return self._process.isalive()

    def read(self, size: int = 4096) -> str:
        return self._process.read(size)

    def write(self, metin: str) -> None:
        self._process.write(metin)

    def setwinsize(self, cols: int, rows: int) -> None:
        # winpty önce satır istiyor; ortak arayüz sütunu önce veriyor.
        self._process.setwinsize(rows, cols)

    def stop(self) -> None:
        self._process.terminate(force=True)


def _grup_sinyal(pid: int, sig: int) -> None:
    """Grubun tamamına sinyal. pgid == pid, çünkü forkpty çocuğu oturum
    lideri yapıyor; `getpgid` kullanılmıyor: lider öldükten sonra o sorgu
    başarısız olur ama grup hâlâ yaşıyor olabilir."""
    try:
        os.killpg(pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def _cocuk_hazirla(cwd: str | None) -> None:
    """fork sonrası, exec'ten önce — çocukta yalnızca sistem çağrıları.

    fd taraması şu yüzden: başka oturumların master'ları fork'ta bu çocuğa
    miras kalıyor ve exec onları kapatmazsa çocuk onları tutar. Ayrıca
    Python SIGPIPE'ı SIG_IGN yapıyor ve yok sayılan sinyaller exec'i de
    atlatıyor; bunu devralan programlar (`git log | head`) boru arkadaşı
    ölünce gereksiz hata basıyor, o yüzden varsayılana çevriliyor.
    """
    try:
        for fd_adi in os.listdir("/proc/self/fd"):
            fd = int(fd_adi)
            if fd > 2:
                try:
                    os.close(fd)
                except OSError:
                    pass
    except (OSError, ValueError):
        os.closerange(3, 256)
    try:
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (OSError, ValueError, AttributeError):
        pass
    if cwd:
        os.chdir(cwd)


def _yurutulebilir(ad: str) -> bool:
    """Komutun program kısmı bulunabiliyor mu — Windows'taki spawn hatasını
    Linux'ta da açılış anında verebilmek için (yoksa oturum doğar doğmaz
    ölür ve hata yalnızca ekranda görünürdü)."""
    if os.sep in ad:
        return _calistirilabilir(ad)
    return shutil.which(ad) is not None


class _PtyArkaUcu:
    """Linux: stdlib `pty` (`os.forkpty`) — fork+setsid+TIOCSCTTY tek adımda.

    Çocuğun gerçek bir oturum lideri ve slave'in onun kontrol terminali
    olması, iş denetiminin (dolayısıyla ^C ve SIGWINCH'in) tek şartı;
    gerekçenin tamamı modül docstring'inde. Kapanışta da grubun tamamı
    hedefleniyor: kabuğun çocukları (bir dev sunucusu, bir TUI'nin yardımcı
    süreçleri) aynı grupta ve yalnızca lideri öldürmek onları sahipsiz
    bırakırdı.
    """

    def __init__(self, pid: int, master: int) -> None:
        self._pid = pid
        self._master: int | None = master
        self._bitti = False
        # Okuma sınırı UTF-8 dizisini ortadan bölebiliyor (Türkçe karakter
        # iki bayt); artımlı çözücü parçayı biriktirip ekranda çöp
        # çıkmasını önlüyor.
        self._cozucu = codecs.getincrementaldecoder("utf-8")("replace")

    @classmethod
    def spawn(cls, komut: str | None, cwd: str | None = None,
              cols: int = DEFAULT_COLS, rows: int = DEFAULT_ROWS):
        argv, cwd, ortam = acilis_plani(komut, cwd)
        if not _yurutulebilir(argv[0]):
            raise TerminalError(
                f"could not start {argv[0]!r}: not found on PATH")
        if cwd and not os.path.isdir(cwd):
            raise TerminalError(f"working directory does not exist: {cwd}")
        try:
            pid, master = os.forkpty()
        except OSError as exc:
            raise TerminalError(f"could not start {argv!r}: {exc}") from None
        if pid == 0:  # çocuk dalı — buradan aşağısı yalnızca ebeveynde
            # BaseException: fork sonrası her hata burada bitmek zorunda.
            # Kaçan bir istisna `spawn`dan çocuğun içinde yukarı çıkar ve
            # çocuk exec etmeden dönüp uygulamanın ikinci kopyası olurdu.
            try:
                _cocuk_hazirla(cwd)
                os.execvpe(argv[0], argv, ortam)
            except BaseException as exc:
                # exec olmadıysa hata pty'nin ekranına yazılıyor; ajan
                # ekranı okuyunca neden başlamadığını görüyor.
                try:
                    os.write(2, f"could not start {argv[0]!r}: {exc}\n"
                             .encode("utf-8", "replace"))
                except OSError:
                    pass
                os._exit(127)
        os.set_inheritable(master, False)
        # Taze bir pty'nin boyutu 0x0; boyut verilmezse TUI'ler sıfır
        # sütunlu bir ekran sanıyor. Windows'ta bu iş spawn'ın
        # `dimensions` argümanı; burada ioctl.
        try:
            fcntl.ioctl(master, termios.TIOCSWINSZ, pencere_verisi(cols, rows))
        except OSError:
            pass
        return cls(pid, master)

    @property
    def _grup_sagliyor(self) -> bool:
        """Kapatma kararının gördüğü "yaşıyor": lider bitmiş olsa da
        grubun kalanı `killpg(pid, 0)` yoklamasıyla sayılıyor."""
        if self.isalive():
            return True
        try:
            os.killpg(self._pid, 0)  # sin 0: yalnızca var mı diye bakıyor
        except (ProcessLookupError, PermissionError):
            return False
        return True

    def isalive(self) -> bool:
        """Çocuk yaşıyor mu — aynı zamanda zombiyi topluyor."""
        if self._bitti:
            return False
        try:
            pid, _ = os.waitpid(self._pid, os.WNOHANG)
        except ChildProcessError:
            self._bitti = True
            return False
        if pid == 0:
            return True
        self._bitti = True
        return False

    def read(self, size: int = 4096) -> str:
        master = self._master
        if master is None:
            raise EOFError("pty closed")
        try:
            veri = os.read(master, size)
        except OSError as exc:
            if exc.errno == errno.EIO:
                # Son slave de kapandı; master'ın okuyucusu burada biter.
                raise EOFError("pty closed") from None
            raise
        if not veri:
            raise EOFError("pty closed")
        return self._cozucu.decode(veri)

    def write(self, metin: str) -> None:
        veri = metin.encode("utf-8")
        while veri:
            master = self._master
            if master is None:
                raise OSError("pty closed")
            veri = veri[os.write(master, veri):]

    def setwinsize(self, cols: int, rows: int) -> None:
        """`TIOCSWINSZ` master'a yazılıyor; çekirdek yeni boyutu doğrudan
        slave'e işliyor ve **ön plan grubuna SIGWINCH yolluyor** — TUI'ler
        yeniden çizme emrini böyle alıyor. SIGWINCH'in gidecek bir ön plan
        grubu olması çocuğun gerçek oturum lideri olmasına bağlı;
        `forkpty` bunu garanti ettiği için burada ek bir iş yok."""
        fcntl.ioctl(self._master, termios.TIOCSWINSZ, pencere_verisi(cols, rows))

    def stop(self) -> None:
        """Süreç grubunu kapatır, ardından master fd'sini bırakır."""
        try:
            surec_kapat(lambda: self._grup_sagliyor,
                        lambda sig: _grup_sinyal(self._pid, sig),
                        sinyaller=(signal.SIGTERM, signal.SIGKILL))
        finally:
            self._kapat()

    def _kapat(self) -> None:
        self._bitti = True
        if self._master is not None:
            try:
                os.close(self._master)
            except OSError:
                pass
            self._master = None


def arka_uc_sinifi():
    """Platform seçimi: tek yer. Başka hiçbir yerde platform `if`i yok."""
    if os.name == "nt":
        return _WinptyArkaUcu
    return _PtyArkaUcu


# --- Oturum --------------------------------------------------------------


@dataclass
class TerminalSession:
    """Bir PTY ve onun ekranı."""

    name: str
    cwd: str
    process: PtyArkaUcu
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
        process = arka_uc_sinifi().spawn(command, cwd=cwd, cols=cols, rows=rows)

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
        """Terminal yetenek sorgularını cevaplar.

        ConPTY açılışta `ESC[c` (cihaz öznitelikleri) gönderip **cevap
        bekliyor**. Cevaplamazsan hiçbir zaman prompt yazmıyor; oturum canlı
        görünüyor ama ekran sonsuza kadar boş kalıyor. İlk sürüm tam olarak
        böyle sessizce takıldı. Linux'ta ConPTY yok ama soran program yine
        olabiliyor ve cevapsız kalmanın bedeli aynı sınıf sessiz takılma;
        cevap her yerde geçerli bir VT100 beyanı, o yüzden yol ortak.

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

    def resize(self, cols: int, rows: int) -> None:
        """Hem gerçek pty'ye hem pyte ekranına yeni boyutu verir.

        Sıra önemli: önce pty (uygulama SIGWINCH'i alıp yeniden çiziyor),
        sonra yerel ekran. `awaiting` işaretleniyor çünkü TUI yeniden
        çiziyor — `wait_idle` yeniden çizilmiş ekranı beklesin diye.
        """
        if not self.alive:
            raise TerminalError(f"session {self.name!r} is closed")
        with self._lock:
            self.process.setwinsize(cols, rows)
            self.screen.resize(lines=rows, columns=cols)
            self._awaiting = True
            self._last_output = time.monotonic()

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
            self.process.stop()
        except Exception:
            pass


class TerminalRegistry:
    """Açık oturumlar. Ajan bunlara isimle erişiyor.

    Kapanış garantisi oturumun kendisinde: `close` süreç **grubunu**
    kapatıyor (`_PtyArkaUcu.stop`), yalnızca lideri değil.
    """

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