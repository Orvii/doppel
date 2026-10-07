"""Ajanın kendi masaüstü — ikinci bir imleç, ayrı bir çalışma alanı.

Berkay'ın istediği şey şuydu: ajan iş yaparken onun faresi ve klavyesi
serbest kalsın, ikisi aynı anda çalışabilsin. `SendInput` bunu asla
veremez — tek bir fiziksel imleç var ve ajan onu her oynattığında
kullanıcının elinden alıyor.

Windows'un buna hazır bir cevabı var: **masaüstü nesnesi**. Bir pencere
istasyonu birden çok masaüstü barındırabilir ve her birinin kendi
pencere listesi, kendi odak zinciri, kendi imleç konumu vardır.
`CreateDesktopW` ile ikinci bir masaüstü açılıyor, uygulamalar
`STARTUPINFOW.lpDesktop` ile oraya doğuruluyor, ve orada olan biten
Berkay'ın ekranında **görünmüyor**. Ne pencereleri kayıyor, ne odağı
gidiyor, ne imleci sıçrıyor.

Bedeli şu: `SendInput` girdiyi **çağıran iş parçacığının** masaüstüne
gönderir ve oraya geçemeyiz — geçersek kendi Qt penceremiz görünmez
olur. Bu yüzden girdi `mesaj.py` üzerinden, pencerelere doğrudan
gönderilen mesajlarla veriliyor. Ajanın imleci bir donanım değil, bir
değişken.

## Neyin çalıştığı ölçüldü

Klasik Win32 (`charmap.exe`) ve Chromium (Chrome) üzerinde:

    yazma      WM_CHAR      -> WM_GETTEXT ile geri okundu, birebir
    tıklama    WM_LBUTTON*  -> açılır liste 0->1; sayfa kırmızıdan yeşile
    yakalama   PrintWindow  -> 1100x800, 25 ayrık renk (gerçek içerik)
    imleç      hiç dokunulmadı — SendInput tek satır bile çağrılmıyor

## Neyin çalışmadığı

- **Paketlenmiş uygulamalar** (Win11'in `notepad.exe`'si, Store
  uygulamaları) bu masaüstünde pencere açmıyor. Görev başlatıcı onları
  kendi oturum bağlamında doğuruyor ve `lpDesktop` yolda kayboluyor.
  Klasik `.exe`'ler ve Chromium sorunsuz.
- **Sürükle-bırak** ve OLE, mesajla taklit edilemiyor.
- Masaüstünde **kabuk yok** — görev çubuğu, masaüstü simgeleri,
  bildirim alanı yok. Uygulamayı biz başlatıyoruz.
"""

from __future__ import annotations

import ctypes
import os
import threading
from collections.abc import Sequence
from ctypes import wintypes
from dataclasses import dataclass

from PIL import Image, ImageDraw

from .capture import Frame

#: Ajanın imleci — maskotun rengi. Windows'un okunu taklit etmiyoruz
#: kasıtlı olarak: karede iki ok görünürse hangisinin kimin olduğu
#: karışır. Bu ok ajanın rengini taşıyor, yani bakan kişi bir an bile
#: tereddüt etmiyor.
IMLEC_RENK = (231, 186, 189)
IMLEC_OYUK = (28, 28, 28)
#: Okun boyu. 22 idi ve yetmiyordu: kare arayüzde küçültülerek
#: gösteriliyor ve üçte bir ölçekte 22 piksellik ok yedi piksele
#: düşüp kayboluyor. 28, küçültülmüş karede de okunuyor.
IMLEC_BOY = 28

_u32 = ctypes.WinDLL("user32", use_last_error=True)
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_g32 = ctypes.WinDLL("gdi32", use_last_error=True)

GENERIC_ALL = 0x10000000

#: `PrintWindow` bayrağı. İstemci alanını da render etmesini söylüyor;
#: bu bayrak olmadan Chromium boş bir kare veriyor.
PW_RENDERFULLCONTENT = 0x00000002

#: Yakalamaya değer bulunan en küçük pencere. Chromium tek sekme için
#: bir düzine minik yardımcı pencere açıyor ve onlar listede gürültüden
#: başka bir şey değil.
ASGARI_EN, ASGARI_BOY = 200, 120

#: `Frame.display_index` bu değerdeyse kare fiziksel bir monitörden
#: değil, ajanın kendi masaüstünden geliyor.
GIZLI_EKRAN = -1

_u32.CreateDesktopW.restype = wintypes.HANDLE
_u32.CreateDesktopW.argtypes = [
    wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p,
    wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
]

_EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


class MasaustuHatasi(RuntimeError):
    """Masaüstü açılamadı ya da içine süreç doğurulamadı."""


class _STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.c_void_p), ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE),
    ]


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD),
    ]


CREATE_SUSPENDED = 0x00000004
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JobObjectExtendedLimitInformation = 9


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [(ad, ctypes.c_ulonglong) for ad in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
        ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.POINTER(ctypes.c_ulong)),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


@dataclass(frozen=True)
class Pencere:
    """Gizli masaüstündeki bir üst düzey pencere."""

    hwnd: int
    baslik: str
    sinif: str
    x: int
    y: int
    en: int
    boy: int

    @property
    def dikdortgen(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.x + self.en, self.y + self.boy)


def pencere_bilgisi(hwnd: int) -> Pencere:
    """Bir HWND'yi başlığı, sınıfı ve dikdörtgeniyle okur."""
    n = _u32.GetWindowTextLengthW(hwnd)
    tampon = ctypes.create_unicode_buffer(n + 1)
    _u32.GetWindowTextW(hwnd, tampon, n + 1)
    sinif = ctypes.create_unicode_buffer(256)
    _u32.GetClassNameW(hwnd, sinif, 256)
    r = wintypes.RECT()
    _u32.GetWindowRect(hwnd, ctypes.byref(r))
    return Pencere(
        hwnd=hwnd, baslik=tampon.value, sinif=sinif.value,
        x=r.left, y=r.top, en=r.right - r.left, boy=r.bottom - r.top,
    )


def istemci_kutusu(hwnd: int) -> tuple[int, int, int, int]:
    """İstemci alanının pencere karesindeki yeri: (dx, dy, en, boy).

    Canlı görüntü için gerekiyor. `PrintWindow` pencerenin tamamını —
    Windows'un kendi başlık çubuğu ve kenarlığı dahil — veriyor. O kareyi
    Mint görünümlü bir çerçevenin içine koyunca iki başlık çubuğu üst üste
    geliyor: biri Windows'un, biri bizim. İstemci alanı kırpılınca yalnızca
    uygulamanın kendi içeriği kalıyor ve çerçeve bizim oluyor.

    Chrome gibi kendi başlığını istemci alanına çizen uygulamalarda sekme
    şeridi içeride kalıyor; doğru olan bu, o şerit uygulamanın kendi
    arayüzü.
    """
    istemci = wintypes.RECT()
    _u32.GetClientRect(hwnd, ctypes.byref(istemci))
    kose = wintypes.POINT(0, 0)
    _u32.ClientToScreen(hwnd, ctypes.byref(kose))
    pencere = wintypes.RECT()
    _u32.GetWindowRect(hwnd, ctypes.byref(pencere))
    return (
        kose.x - pencere.left,
        kose.y - pencere.top,
        istemci.right - istemci.left,
        istemci.bottom - istemci.top,
    )


def imlec_ciz(gorsel: Image.Image, x: int, y: int,
              iz: Sequence[tuple[int, int]] = (), tik: bool = False) -> None:
    """Ajanın imlecini karenin üstüne çizer. Görseli yerinde değiştirir.

    **İz kasıtlı.** Yalnızca oku çizmek "şu an neredeyim" der ve orada
    kalır; iz "nereden geldim" der. Ajan yanlış yere tıkladığında tek
    kareye bakıp yolu görebiliyorsun — üç kare geri sarmadan. Aynı
    fikrin küçük hâli: koşu şeridi, tek karede.

    Tıklama anında ok bir halkanın içine giriyor. Halka çizmek yerine
    oku büyütmek de olurdu ama büyüyen ok konumu bozar; halka okun
    kendisine dokunmuyor.
    """
    kat = Image.new("RGBA", gorsel.size, (0, 0, 0, 0))
    firca = ImageDraw.Draw(kat)

    # İz bağlı bir çizgi, nokta dizisi değil. Noktalarla çizip baktım:
    # açık zeminde toz gibi duruyor ve yol olduğu okunmuyor. Çizgi
    # sonlanma yönü taşıyor, yani nereden gelindiği bir bakışta belli.
    yol = list(iz) + [(x, y)]
    for i in range(len(yol) - 1):
        oran = (i + 1) / len(yol)
        # İz okun kendisinden baskın çıkmamalı: bakılacak yer şu anki
        # konum, geçmiş yalnızca bağlam.
        firca.line([yol[i], yol[i + 1]],
                   fill=IMLEC_OYUK + (int(45 * oran),), width=4)
        firca.line([yol[i], yol[i + 1]],
                   fill=IMLEC_RENK + (int(140 * oran),), width=2)

    if tik:
        r = IMLEC_BOY * 0.8
        firca.ellipse((x - r, y - r, x + r, y + r),
                      outline=IMLEC_OYUK + (170,), width=5)
        firca.ellipse((x - r, y - r, x + r, y + r),
                      outline=IMLEC_RENK + (255,), width=3)

    # Ok: klasik imleç siluetinin dolu hâli, koyu bir kılıf içinde.
    #
    # Maskotun dili kontursuz — ama o dil bizim yüzeylerimiz için. Bu ok
    # başkasının uygulamasının üstüne düşüyor ve zeminin ne olacağını
    # bilmiyoruz. Tek renk ok, açık zeminde 1.2:1 kontrastla kayboluyor;
    # ölçtüm, ekranda gerçekten görünmüyordu. Koyu kılıf hem açık hem
    # koyu zeminde okunmayı garanti ediyor. Windows'un oku da tam bu
    # nedenle beyaz gövde + siyah kontur.
    b = IMLEC_BOY
    silüet = [
        (x, y), (x, y + b), (x + b * 0.28, y + b * 0.72),
        (x + b * 0.46, y + b * 1.02), (x + b * 0.60, y + b * 0.94),
        (x + b * 0.42, y + b * 0.66), (x + b * 0.68, y + b * 0.64),
    ]
    # Kılıf: aynı çokgen sekiz yöne kaydırılıp koyu çiziliyor. Pillow'un
    # `width` desteği sürüme göre değişiyor; bu her yerde aynı sonucu
    # veriyor.
    for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2),
                   (-1, -1), (1, -1), (-1, 1), (1, 1)):
        firca.polygon([(px + dx, py + dy) for px, py in silüet],
                      fill=IMLEC_OYUK + (255,))
    firca.polygon(silüet, fill=IMLEC_RENK + (255,))

    gorsel.paste(Image.alpha_composite(gorsel.convert("RGBA"), kat).convert("RGB"),
                 (0, 0))


class Calisma:
    """Ajanın kendi masaüstü ve içinde başlattığı süreçler.

    Tek örnek olarak kullanılmak üzere yazıldı: masaüstü adı sabit ve
    ikinci bir `Calisma` yenisini yaratmıyor, var olana bağlanıyor —
    `CreateDesktopW` zaten var olan bir ada çağrıldığında var olanı
    döndürüyor, yani bu davranış Windows'un kendisinden geliyor.
    """

    def __init__(self, ad: str = "ajan-calisma") -> None:
        self.ad = ad
        self._masa: int | None = None
        self._is: int | None = None
        self._surecler: list[_PROCESS_INFORMATION] = []
        self._kilit = threading.Lock()

    # -- yaşam döngüsü ----------------------------------------------

    def ac(self) -> None:
        """Masaüstünü yaratır. Zaten varsa ona bağlanır."""
        if self._masa:
            return
        kol = _u32.CreateDesktopW(self.ad, None, None, 0, GENERIC_ALL, None)
        if not kol:
            hata = ctypes.get_last_error()
            raise MasaustuHatasi(f"could not create the desktop (error {hata})")
        self._masa = kol
        self._is = self._is_nesnesi()

    @staticmethod
    def _is_nesnesi() -> int:
        """Süreç ağacını topluca öldürecek iş nesnesi.

        Bu, ölçülerek bulunmuş bir hatanın karşılığı. `TerminateProcess`
        yalnızca başlattığımız süreci öldürüyor; Chrome kendi işini
        onlarca çocuk sürece bölüyor ve onlar hayatta kalıyor. Sonucu iki
        katmanlı: görünmez bir masaüstünde görünmez Chrome süreçleri
        birikiyor, ve profil dizinindeki kilit ayakta kaldığı için bir
        sonraki açılış eski örneğe devrediyor — pencere geliyor ama
        tıklama hiçbir yere ulaşmıyor. Bir çalıştırmada tam olarak bu
        oldu.

        `KILL_ON_JOB_CLOSE` bunu Windows'a yaptırıyor: iş nesnesinin son
        tutamacı kapandığında ağacın tamamı gidiyor. Süreç çökse bile.
        """
        kol = _k32.CreateJobObjectW(None, None)
        if not kol:
            return 0
        bilgi = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        bilgi.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        _k32.SetInformationJobObject(
            kol, _JobObjectExtendedLimitInformation,
            ctypes.byref(bilgi), ctypes.sizeof(bilgi),
        )
        return kol

    def kapat(self) -> None:
        """Başlatılan her süreci sonlandırır ve masaüstünü bırakır.

        Süreçler önce kapanmalı: masaüstünde pencere kaldığı sürece
        `CloseDesktop` nesneyi yok etmiyor, yalnızca tutamacı bırakıyor,
        ve arkada görünmez pencereler yaşamaya devam ediyor.
        """
        with self._kilit:
            for pi in self._surecler:
                _k32.TerminateProcess(pi.hProcess, 0)
                _k32.CloseHandle(pi.hProcess)
                _k32.CloseHandle(pi.hThread)
            self._surecler.clear()
        if self._is:
            # Ağacın kalanı burada gidiyor: Chrome'un render süreçleri
            # ana sürecin ölümünden sağ çıkıyor, iş nesnesinin kapanışından
            # çıkmıyor.
            _k32.CloseHandle(self._is)
            self._is = None
        if self._masa:
            _u32.CloseDesktop(self._masa)
            self._masa = None

    def __enter__(self) -> "Calisma":
        self.ac()
        return self

    def __exit__(self, *_hata) -> None:
        self.kapat()

    # -- süreç ------------------------------------------------------

    def baslat(self, komut: str, calisma_dizini: str | None = None) -> int:
        """Komutu **gizli masaüstünde** başlatır, PID döndürür.

        Paketlenmiş uygulamalar (Win11 `notepad.exe`) burada pencere
        açmıyor — ölçüldü. Klasik bir `.exe` yolu ver.
        """
        self.ac()
        si = _STARTUPINFOW()
        si.cb = ctypes.sizeof(si)
        si.lpDesktop = self.ad
        pi = _PROCESS_INFORMATION()
        # Askıya alınmış başlıyor: iş nesnesine atanmadan önce çalışırsa
        # o aradaki milisaniyede doğurduğu çocuklar ağacın dışında kalır.
        ok = _k32.CreateProcessW(
            None, ctypes.create_unicode_buffer(komut), None, None, False,
            CREATE_SUSPENDED, None, calisma_dizini or os.getcwd(),
            ctypes.byref(si), ctypes.byref(pi),
        )
        if not ok:
            hata = ctypes.get_last_error()
            raise MasaustuHatasi(f"could not start the process (error {hata}): {komut}")
        if self._is:
            _k32.AssignProcessToJobObject(self._is, pi.hProcess)
        _k32.ResumeThread(pi.hThread)
        with self._kilit:
            self._surecler.append(pi)
        return pi.dwProcessId

    def sonlandir(self, pid: int) -> bool:
        """Bu masaüstünde başlatılmış bir süreci kapatır."""
        with self._kilit:
            for pi in list(self._surecler):
                if pi.dwProcessId != pid:
                    continue
                _k32.TerminateProcess(pi.hProcess, 0)
                _k32.CloseHandle(pi.hProcess)
                _k32.CloseHandle(pi.hThread)
                self._surecler.remove(pi)
                return True
        return False

    # -- pencereler -------------------------------------------------

    def pencereler(self) -> list[Pencere]:
        """Gizli masaüstündeki görünür ve kayda değer pencereler."""
        if not self._masa:
            return []
        bulunan: list[Pencere] = []

        def topla(hwnd, _lp):
            if not _u32.IsWindowVisible(hwnd):
                return True
            p = pencere_bilgisi(hwnd)
            if p.en >= ASGARI_EN and p.boy >= ASGARI_BOY:
                bulunan.append(p)
            return True

        _u32.EnumDesktopWindows(self._masa, _EnumProc(topla), 0)
        return bulunan

    def pencere_bul(self, parca: str) -> Pencere | None:
        """Başlığında `parca` geçen ilk pencere. Büyük/küçük harf umursamaz."""
        aranan = parca.casefold()
        for p in self.pencereler():
            if aranan in p.baslik.casefold():
                return p
        return None

    # -- yakalama ---------------------------------------------------

    def yakala(self, hwnd: int, imlec: tuple[int, int] | None = None,
               iz: Sequence[tuple[int, int]] = (), tik: bool = False) -> Frame:
        """Bir pencereyi `PrintWindow` ile yakalar.

        `PrintWindow` seçildi çünkü pencere görünür bir ekranda değil —
        `BitBlt` ekran DC'sinden okur ve orada okuyacak bir şey yok.
        `PW_RENDERFULLCONTENT` olmadan Chromium boş kare veriyor.
        """
        p = pencere_bilgisi(hwnd)
        if p.en <= 0 or p.boy <= 0:
            raise MasaustuHatasi(f"invalid window size: {p.en}x{p.boy}")

        dc = _u32.GetWindowDC(hwnd)
        bellek = _g32.CreateCompatibleDC(dc)
        bitmap = _g32.CreateCompatibleBitmap(dc, p.en, p.boy)
        eski = _g32.SelectObject(bellek, bitmap)
        try:
            _u32.PrintWindow(hwnd, bellek, PW_RENDERFULLCONTENT)
            bi = _BITMAPINFOHEADER()
            bi.biSize = ctypes.sizeof(bi)
            bi.biWidth, bi.biHeight = p.en, -p.boy  # negatif: yukarıdan aşağı
            bi.biPlanes, bi.biBitCount = 1, 32
            ham = ctypes.create_string_buffer(p.en * p.boy * 4)
            _g32.GetDIBits(bellek, bitmap, 0, p.boy, ham, ctypes.byref(bi), 0)
        finally:
            _g32.SelectObject(bellek, eski)
            _g32.DeleteObject(bitmap)
            _g32.DeleteDC(bellek)
            _u32.ReleaseDC(hwnd, dc)

        # GetDIBits BGRA veriyor; alfa kanalı GDI'da anlamsız, atılıyor.
        gorsel = Image.frombuffer(
            "RGBA", (p.en, p.boy), ham.raw, "raw", "BGRA", 0, 1
        ).convert("RGB")
        if imlec is not None:
            # Masaüstü koordinatı pencereye göreliye dönüyor: imleç
            # pencerelerin dışındayken de doğru yerde kalsın diye kırpma
            # yok, Pillow zaten taşan çizimi kesiyor.
            imlec_ciz(
                gorsel, imlec[0] - p.x, imlec[1] - p.y,
                [(ix - p.x, iy - p.y) for ix, iy in iz], tik,
            )
        # Küçültme kararı monitör yolundakiyle aynı fonksiyondan geçiyor:
        # penceresi 2576 px'i ya da token bütçesini aşan bir kare
        # küçültülmeden gönderilirse API onu reddeder.
        return Frame.from_capture(GIZLI_EKRAN, gorsel)
