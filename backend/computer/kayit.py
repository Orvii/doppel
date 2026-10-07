"""Yan masanın ekran kaydı — ffmpeg, ama doğru masaüstünde.

Ekran görüntüsü ajanın ne yaptığını anlatmıyor, yalnızca nerede
durduğunu söylüyor. Videoyu isteyen sebep bu: sırayı, tereddüdü ve
yanlış tıklamayı yalnızca hareket gösteriyor.

## Neden `subprocess` değil

`ffmpeg -f gdigrab -i desktop` **çağıran sürecin masaüstünü** çekiyor:
`gdigrab` `GetDC(NULL)` ile başlıyor ve o DC iş parçacığının bağlı
olduğu masaüstüne ait. Uygulamamız ana masaüstünde çalışıyor, yani
`subprocess.Popen("ffmpeg …")` Berkay'ın ekranını kaydeder — istenenin
tam tersi, üstelik sessizce doğru görünen bir dosya üreterek.

Python'un `subprocess.STARTUPINFO`'su `lpDesktop` alanını hiç açmıyor.
Bu yüzden süreç burada `CreateProcessW` ile elle doğuruluyor,
`masaustu.py`'nin `baslat`'ıyla aynı yoldan: `STARTUPINFOW.lpDesktop`
yan masaüstünün adı.

## Neden `-i desktop` değil, `-i hwnd=…`

Bu ölçüldü, varsayılmadı. Yan masaüstünde `charmap.exe` açıkken üç
girdi denendi (`scripts/dogrula_kayit.py`):

    -i desktop        ffmpeg saniyesinde ölüyor:
                      "Failed to capture image (error 5)" — ACCESS_DENIED
    -i hwnd=<hwnd>    43 kare, 474x398, karede gerçek charmap içeriği
    -i title="…"      aynı, birebir aynı boyutta dosya

Sebep `masaustu.py`'nin zaten yazdığı şey: Windows yalnızca **girdi
masaüstünü** oluşturuyor. Etkin olmayan bir masaüstünün ekran yüzeyi
yok, dolayısıyla masaüstü DC'sinden `BitBlt` okunacak bir şey bulamıyor.
Aynı gerekçeyle `capture.py` değil `PrintWindow` kullanılıyor.

Bedeli: kayıt **tek pencere**. Ajan kayıt sürerken başka bir pencereye
geçerse video ilk pencerede kalıyor. Bunu gizlemiyoruz — `record_start`
aracının tanımı modele bunu söylüyor, çünkü alternatifi yok: bütün
masaüstünü çeken bir yol Windows tarafından kapalı.

## Neden `Calisma.baslat` kullanılmıyor

`Calisma` başlattığı her süreci `KILL_ON_JOB_CLOSE` bayraklı bir iş
nesnesine bağlıyor ve `kapat()` hepsini `TerminateProcess` ile
öldürüyor. ffmpeg için bu tam olarak yapılmaması gereken şey: sert
öldürülen ffmpeg `moov` atomunu yazamadan gidiyor ve geriye açılmayan
bir mp4 kalıyor. Kaydın süreç yönetimi bu yüzden ayrı: durdurma
stdin'e `q` yazıp bekliyor, öldürmek yalnızca son çare.

## Ölçülen ayrıntılar

- **`CREATE_NO_WINDOW` şart.** Konsol penceresi yan masaüstünde açılıyor
  ve orada açılan her pencere gibi **kaydın içine giriyor**. Kaydın ilk
  karesinde ffmpeg'in kendi konsolunu görmek istemiyoruz.
- **`-draw_mouse 0`.** Yan masaüstünde fiziksel imleç yok — ajanın
  imleci `mesaj.py` içinde bir değişken. `gdigrab` yine de sistemin
  okunu çiziyor ve o ok hiç kıpırdamıyor; kaydın ortasında donmuş bir
  imleç, bakan kişiye "takıldı mı" dedirtiyor.
- **Çift sayıya kırpma.** `yuv420p` tek sayılı genişlik/yükseklik kabul
  etmiyor ve ffmpeg orada başlamadan ölüyor. Pencere boyutu keyfî.
- **stderr borusu boşaltılıyor.** Boşaltılmazsa boru dolduğunda ffmpeg
  yazma sırasında bloke oluyor ve kayıt sessizce donuyor.
"""

from __future__ import annotations

import ctypes
import shutil
import threading
import time
from ctypes import wintypes
from pathlib import Path

from ..config import REPO_ROOT
from .masaustu import _PROCESS_INFORMATION, _STARTUPINFOW

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)

# `ctypes` bildirilmemiş bir dönüş tipini `int`, yani 32 bit sayıyor ve
# 64 bitlik bir tutamacı sessizce kırpıyor. Kırpılmış tutamaç geçersiz
# bir tutamaç: ffmpeg stdout'a yazamıyor ve hata mesajı "invalid
# handle" olmuyor, hiç olmuyor.
_k32.CreateFileW.restype = wintypes.HANDLE

#: Kayıtların kökü. `runs/` `.gitignore` içinde; video da denetim kaydı
#: gibi depoya girmemeli.
DIZIN = REPO_ROOT / "runs"

#: Kare hızı. Ajan saniyede otuz kare üretmiyor — bir tıklama, bir
#: bekleme, bir tıklama. 10 kare hem hareketi taşıyor hem dosyayı
#: paylaşılabilir boyutta tutuyor.
KARE_HIZI = 10

#: Durdurma sırası: `q`'dan sonra ffmpeg'e bu kadar süre veriliyor.
#: Yetmezse öldürülüyor ve dosyanın bozuk olabileceği söyleniyor.
KAPANIS_SANIYE = 10.0

#: ffmpeg başlar başlamaz ölüyor mu — bu kadar beklenip bakılıyor.
#: Çözünürlük, kodek ya da dolu disk yüzünden ölen ffmpeg'i durdurma
#: anında fark etmek, elde boş bir dosyayla kalmak demek.
ACILIS_SANIYE = 0.6

STARTF_USESTDHANDLES = 0x00000100
CREATE_NO_WINDOW = 0x08000000
HANDLE_FLAG_INHERIT = 0x00000001
GENERIC_WRITE = 0x40000000
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
WAIT_OBJECT_0 = 0x00000000
STILL_ACTIVE = 259


class KayitHatasi(RuntimeError):
    """Kayıt başlatılamadı ya da temiz durdurulamadı."""


class _SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wintypes.BOOL),
    ]


def ffmpeg_yolu() -> str:
    """ffmpeg'in tam yolu. Yoksa **açık** bir hata.

    Sessizce geçmiyor: kayıt yapılmadığını koşunun sonunda video dosyası
    aramaya kalkınca öğrenmek, hiç kayıt yapmamaktan daha kötü.
    """
    yol = shutil.which("ffmpeg")
    if not yol:
        raise KayitHatasi(
            "ffmpeg was not found on PATH, so nothing can be recorded. "
            "Install it (winget install Gyan.FFmpeg) and restart the app."
        )
    return yol


def kosu_kimligi(an: float | None = None) -> str:
    """Bu koşunun kimliği. Saniye çözünürlüğü yeterli — iki kayıt aynı
    saniyede başlamıyor, ikinci kayıt zaten reddediliyor."""
    return time.strftime("%Y%m%d-%H%M%S", time.localtime(an or time.time()))


def varsayilan_hedef(kosu: str | None = None, dizin: Path | None = None) -> Path:
    """`runs/<koşu>/<koşu>.mp4`.

    Klasör koşu başına: video tek başına kalmıyor, denetim kaydının ve
    ileride eklenecek her şeyin yanında duruyor. Dosya adı da koşu
    kimliği, çünkü paylaşılan şey dosyanın kendisi ve `kayit.mp4` adıyla
    indirilen üç dosya birbirinden ayırt edilemiyor.
    """
    kosu = kosu or kosu_kimligi()
    return (dizin or DIZIN) / kosu / f"{kosu}.mp4"


def ffmpeg_komutu(hedef: Path, hwnd: int, kare_hizi: int = KARE_HIZI,
                  ffmpeg: str | None = None) -> str:
    """Komut satırını kurar. `CreateProcessW` tek bir dize istiyor.

    Yollar tırnak içinde: `runs` depo kökünün altında ve depo kökü
    boşluk taşıyan bir yerde olabilir.
    """
    return (
        f'"{ffmpeg or ffmpeg_yolu()}"'
        " -hide_banner -loglevel error -y"
        f" -f gdigrab -framerate {kare_hizi} -draw_mouse 0 -i hwnd={int(hwnd)}"
        ' -vf "crop=trunc(iw/2)*2:trunc(ih/2)*2"'
        " -c:v libx264 -preset veryfast -crf 26 -pix_fmt yuv420p"
        " -movflags +faststart"
        f' "{hedef}"'
    )


def _startupinfo(masaustu: str, stdin=None, stdout=None,
                 stderr=None) -> _STARTUPINFOW:
    """Süreci **yan masaüstünde** doğuracak `STARTUPINFOW`.

    Ayrı bir fonksiyon, çünkü testi gerçek bir süreç doğurmadan
    yazılabilsin: `lpDesktop`'ın doğru adı taşıması kaydın doğru ekranı
    çekmesinin tek şartı ve karelere bakmadan gözle doğrulanamıyor.
    """
    si = _STARTUPINFOW()
    si.cb = ctypes.sizeof(si)
    si.lpDesktop = masaustu
    si.dwFlags = STARTF_USESTDHANDLES
    si.hStdInput = stdin
    si.hStdOutput = stdout
    si.hStdError = stderr
    return si


def _bos_aygit():
    """`NUL`'a yazan, miras alınabilir bir tutamaç.

    `STARTF_USESTDHANDLES` üç akışın üçünü de istiyor; stdout boş
    kalırsa ffmpeg geçersiz bir tutamaca yazmaya çalışıyor.
    """
    sa = _SECURITY_ATTRIBUTES()
    sa.nLength = ctypes.sizeof(sa)
    sa.bInheritHandle = True
    return _k32.CreateFileW(
        "NUL", GENERIC_WRITE, FILE_SHARE_WRITE, ctypes.byref(sa),
        OPEN_EXISTING, 0, None,
    )


class _Surec:
    """Doğurulmuş ffmpeg. Testlerdeki sahtenin taklit ettiği yüzey bu."""

    def __init__(self, pi: _PROCESS_INFORMATION, stdin_yaz: int,
                 stderr_oku: int) -> None:
        self._pi = pi
        self._stdin = stdin_yaz
        self._stderr = stderr_oku
        self.pid = pi.dwProcessId
        self._gunluk: list[str] = []
        self._okuyucu = threading.Thread(
            target=self._stderr_bosalt, daemon=True, name="ffmpeg-stderr")
        self._okuyucu.start()

    def _stderr_bosalt(self) -> None:
        tampon = ctypes.create_string_buffer(4096)
        okunan = wintypes.DWORD()
        while _k32.ReadFile(self._stderr, tampon, 4096,
                            ctypes.byref(okunan), None) and okunan.value:
            self._gunluk.append(
                tampon.raw[:okunan.value].decode("utf-8", "replace"))
        _k32.CloseHandle(self._stderr)

    @property
    def gunluk(self) -> str:
        return "".join(self._gunluk).strip()

    def dur_iste(self) -> None:
        """stdin'e `q`. ffmpeg bunu görünce başlığı yazıp temiz çıkıyor."""
        yazilan = wintypes.DWORD()
        _k32.WriteFile(self._stdin, b"q", 1, ctypes.byref(yazilan), None)
        _k32.FlushFileBuffers(self._stdin)
        _k32.CloseHandle(self._stdin)
        self._stdin = 0

    def bekle(self, saniye: float) -> bool:
        """Süreç bitene kadar bekler. Bittiyse `True`."""
        return _k32.WaitForSingleObject(
            self._pi.hProcess, int(saniye * 1000)) == WAIT_OBJECT_0

    def oldur(self) -> None:
        _k32.TerminateProcess(self._pi.hProcess, 1)
        _k32.WaitForSingleObject(self._pi.hProcess, 2000)

    def kapat(self) -> None:
        if self._stdin:
            _k32.CloseHandle(self._stdin)
            self._stdin = 0
        _k32.CloseHandle(self._pi.hProcess)
        _k32.CloseHandle(self._pi.hThread)


def dogur(komut: str, masaustu: str) -> _Surec:
    """Komutu yan masaüstünde, stdin'i bize bağlı olarak başlatır."""
    sa = _SECURITY_ATTRIBUTES()
    sa.nLength = ctypes.sizeof(sa)
    sa.bInheritHandle = True

    giris_oku, giris_yaz = wintypes.HANDLE(), wintypes.HANDLE()
    if not _k32.CreatePipe(ctypes.byref(giris_oku), ctypes.byref(giris_yaz),
                           ctypes.byref(sa), 0):
        raise KayitHatasi("could not create the pipe for ffmpeg's input")
    # Yazma ucu miras alınmamalı: alınırsa ffmpeg kendi stdin'inin yazma
    # ucunu da tutar ve boruyu kapatmamız EOF üretmez.
    _k32.SetHandleInformation(giris_yaz, HANDLE_FLAG_INHERIT, 0)

    hata_oku, hata_yaz = wintypes.HANDLE(), wintypes.HANDLE()
    if not _k32.CreatePipe(ctypes.byref(hata_oku), ctypes.byref(hata_yaz),
                           ctypes.byref(sa), 0):
        _k32.CloseHandle(giris_oku)
        _k32.CloseHandle(giris_yaz)
        raise KayitHatasi("could not create the pipe for ffmpeg's output")
    _k32.SetHandleInformation(hata_oku, HANDLE_FLAG_INHERIT, 0)

    si = _startupinfo(masaustu, giris_oku, _bos_aygit(), hata_yaz)
    pi = _PROCESS_INFORMATION()
    ok = _k32.CreateProcessW(
        None, ctypes.create_unicode_buffer(komut), None, None, True,
        CREATE_NO_WINDOW, None, str(REPO_ROOT), ctypes.byref(si),
        ctypes.byref(pi),
    )
    # Çocuğa devredilen uçlar bizde kalmamalı; kalırsa ffmpeg çıksa bile
    # stderr borusu hiç EOF vermez ve okuyucu iş parçacığı asılı kalır.
    _k32.CloseHandle(giris_oku)
    _k32.CloseHandle(hata_yaz)
    _k32.CloseHandle(si.hStdOutput)
    if not ok:
        _k32.CloseHandle(giris_yaz)
        _k32.CloseHandle(hata_oku)
        raise KayitHatasi(
            f"could not start ffmpeg (error {ctypes.get_last_error()})")
    return _Surec(pi, giris_yaz, hata_oku)


class EkranKaydi:
    """Yan masaüstünün ekran kaydı. Aynı anda tek kayıt.

    İkinci bir kayıt reddediliyor, sessizce ilkinin üstüne yazılmıyor:
    aynı ekranı iki ffmpeg çekerse ikisi de kare düşürüyor ve hangisinin
    hangi dosyayı yazdığı belirsiz kalıyor.
    """

    def __init__(self, masaustu_adi: str = "ajan-calisma",
                 dogurucu=dogur) -> None:
        self.masaustu_adi = masaustu_adi
        self._dogur = dogurucu
        self._surec = None
        self._hedef: Path | None = None
        #: Kaydedilen pencere. Arayüz bunu gösteriyor: "kayıt var" ile
        #: "neyin kaydı var" farklı sorular.
        self._hwnd = 0
        self._basladi = 0.0
        self._sure = 0.0
        self._kilit = threading.RLock()

    # -- durum ------------------------------------------------------

    @property
    def suruyor(self) -> bool:
        return self._surec is not None

    @property
    def hedef(self) -> Path | None:
        return self._hedef

    @property
    def hwnd(self) -> int:
        return self._hwnd

    @property
    def sure(self) -> float:
        """Kayıt sürerken geçen süre, bittiyse toplam süre. Saniye."""
        if self._surec is not None:
            return time.time() - self._basladi
        return self._sure

    # -- yaşam döngüsü ----------------------------------------------

    def basla(self, hedef: Path | None = None, hwnd: int = 0) -> Path:
        """Kaydı başlatır ve yazılacak dosyayı döndürür.

        `hwnd` yan masaüstündeki bir pencere. Sıfır olamaz: bütün
        masaüstünü çekmenin yolu yok (modül docstring'i) ve varsayılan
        bir pencere uydurmak, yanlış pencereyi sessizce kaydetmek olurdu.
        """
        with self._kilit:
            if self._surec is not None:
                raise KayitHatasi(
                    f"a recording is already running, writing to {self._hedef}. "
                    "Stop it first."
                )
            if not hwnd:
                raise KayitHatasi(
                    "recording needs a window handle from the side desk; "
                    "get one with side_windows."
                )
            hedef = Path(hedef) if hedef else varsayilan_hedef()
            try:
                hedef.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise KayitHatasi(
                    f"could not create {hedef.parent}: {exc}") from None
            komut = ffmpeg_komutu(hedef, hwnd)
            surec = self._dogur(komut, self.masaustu_adi)
            if surec.bekle(ACILIS_SANIYE):
                gunluk = surec.gunluk or "it exited immediately"
                surec.kapat()
                raise KayitHatasi(f"ffmpeg could not start recording: {gunluk}")
            self._surec = surec
            self._hedef = hedef
            self._hwnd = hwnd
            self._basladi = time.time()
            self._sure = 0.0
            return hedef

    def durdur(self) -> Path | None:
        """Kaydı temiz durdurur ve dosyayı döndürür. Kayıt yoksa `None`.

        `q` yazıp bekliyor. Öldürmek yalnızca ffmpeg cevap vermezse ve o
        durumda hata fırlatılıyor — bozuk olabilecek bir dosyayı sağlam
        diye geri vermek, kaydın hiç olmamasından kötü.
        """
        with self._kilit:
            surec, hedef = self._surec, self._hedef
            if surec is None:
                return None
            self._sure = time.time() - self._basladi
            self._surec = None
            try:
                surec.dur_iste()
                if not surec.bekle(KAPANIS_SANIYE):
                    surec.oldur()
                    raise KayitHatasi(
                        f"ffmpeg did not stop within {KAPANIS_SANIYE:.0f}s and "
                        f"had to be killed; {hedef} may be unplayable."
                    )
            finally:
                surec.kapat()
            return hedef

    def kapat(self) -> None:
        """Uygulama ya da koşu biterken çağrılıyor: arkada ffmpeg kalmasın.

        `durdur`'dan farkı hata yutması. Kapanış yolunda bir istisna,
        ondan sonraki temizliği de iptal ederdi.
        """
        try:
            self.durdur()
        except KayitHatasi:
            pass
