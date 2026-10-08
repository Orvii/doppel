"""İkinci imleç — pencerelere doğrudan gönderilen girdi.

`input.py` fiziksel donanımı sürüyor: `SendInput` çağırdığı anda
Berkay'ın imleci sıçrar, odağı değişir, yazdığı cümlenin ortasına ajanın
harfleri düşer. Bu modül onun **tam tersi**: hiçbir donanıma dokunmuyor.
Girdi doğrudan hedef pencerenin ileti kuyruğuna bırakılıyor.

Bunun sonucu, Berkay'ın istediği şey: ajanın kendi imleci var. Bir
koordinat değişkeni — `Imlec` — ve tıklamalar o koordinattan gidiyor.
Fiziksel fare olduğu yerde duruyor. İkisi aynı anda çalışabiliyor.

## Neyin çalıştığı, neyin çalışmadığı

`PostMessage` ile gönderilen girdi gerçek girdi değil; uygulama sorarsa
farkı görebilir. Ölçülen sınırlar:

- **Tıklama ve yazma çalışıyor** — hem klasik Win32'de hem Chromium'da
  doğrulandı (`masaustu.py` başlığındaki ölçüm tablosu).
- **Değiştirici tuşlar güvenilmez.** `Ctrl+S` göndermek için `Ctrl`'ün
  basılı *durumda* olması gerekir; uygulamalar bunu `GetKeyState` ile
  sorar ve o durum iş parçacığı başına tutulur. Biz hedefin iş
  parçacığı değiliz, dolayısıyla `Ctrl` hiçbir zaman basılı görünmez.
  `tus()` bu yüzden düz tuşlarla sınırlı; kombinasyon istendiğinde
  sessizce yanlış iş yapmak yerine `DesteklenmiyorHatasi` atıyor.
  Uygulamanın menüsüne tıklamak, kısayolu taklit etmeye çalışmaktan
  daha sağlam.
- **Sürükle-bırak** yok. Kaynak ve hedef arasındaki OLE el sıkışması
  ileti taklidiyle kurulmuyor.

Bu dürüst sınır listesi kasıtlı: mesajla girdi "çoğu zaman çalışan" bir
şey ve nerede çalışmadığını bilmeden kullanmak, ajanın sessizce yanlış
yere tıklaması demek.
"""

from __future__ import annotations

import ctypes
import time
from collections import deque
from dataclasses import dataclass

from .win32_kabuk import WinDLL, wintypes

_u32 = WinDLL("user32", use_last_error=True)

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0201, 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONDOWN, WM_RBUTTONUP = 0x0204, 0x0205
WM_MOUSEWHEEL = 0x020A
WM_KEYDOWN, WM_KEYUP, WM_CHAR = 0x0100, 0x0101, 0x0102
WM_SETFOCUS = 0x0007

MK_LBUTTON, MK_RBUTTON = 0x0001, 0x0002
WHEEL_DELTA = 120

CWP_SKIPINVISIBLE = 0x0001
CWP_SKIPTRANSPARENT = 0x0004

#: Basma ile bırakma arası. Sıfır olduğunda Chromium ikisini tek olay
#: sayıp tıklamayı yutuyor — ölçülerek bulundu, tahmin değil.
TIK_SURESI = 0.04

#: Harfler arası. Chromium'un giriş kuyruğu ardışık `WM_CHAR`'ları
#: birleştirebiliyor; bu aralık metnin sırasını koruyor.
HARF_ARASI = 0.012

#: Düz tuşlar. Değiştirici gerektirenler kasıtlı olarak yok — neden
#: olmadığı modül başlığında.
TUSLAR = {
    "enter": 0x0D, "return": 0x0D, "tab": 0x09, "escape": 0x1B, "esc": 0x1B,
    "backspace": 0x08, "delete": 0x2E, "space": 0x20,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "insert": 0x2D,
    **{f"f{i}": 0x6F + i for i in range(1, 13)},
}


class DesteklenmiyorHatasi(RuntimeError):
    """İleti taklidiyle yapılamayan bir girdi istendi."""


def _lp(x: int, y: int) -> int:
    """Fare iletilerinin lParam'ı: yüksek word y, düşük word x."""
    return ((y & 0xFFFF) << 16) | (x & 0xFFFF)


def _derin_cocuk(hwnd: int, x: int, y: int) -> tuple[int, int, int]:
    """Verilen masaüstü noktasındaki en derin alt pencere ve yerel nokta.

    Fare iletileri **istemci koordinatı** taşır ve doğru alıcı üst düzey
    pencere değil, o noktadaki denetim. Chromium'da bu
    `Chrome_RenderWidgetHostHWND`; üst pencereye gönderilen tıklama
    sayfaya hiç ulaşmıyor.
    """
    nokta = wintypes.POINT(x, y)
    hedef = hwnd
    for _ in range(16):  # iç içe geçme derinliği; sonsuz döngü olmasın
        yerel = wintypes.POINT(nokta.x, nokta.y)
        _u32.ScreenToClient(hedef, ctypes.byref(yerel))
        alt = _u32.ChildWindowFromPointEx(
            hedef, yerel, CWP_SKIPINVISIBLE | CWP_SKIPTRANSPARENT
        )
        if not alt or alt == hedef:
            return hedef, yerel.x, yerel.y
        hedef = alt
    return hedef, nokta.x, nokta.y


@dataclass
class Imlec:
    """Ajanın imleci. Donanım değil, iki sayı.

    Konum **masaüstü** koordinatında tutuluyor, pencereye göre değil:
    ajan pencereler arası geçtiğinde imleç yerinde kalsın diye.
    """

    x: int = 0
    y: int = 0

    def tasi(self, x: int, y: int) -> None:
        self.x, self.y = int(x), int(y)


class Girdi:
    """Bir gizli masaüstündeki pencerelere ileti gönderen girdi kanalı.

    Odak takibi burada: son tıklanan denetim hatırlanıyor ve klavye
    oraya gidiyor. `GetFocus` kullanılamıyor çünkü hedefin iş parçacığına
    `AttachThreadInput` ile bağlanmak gerekirdi ve o bağlanma, kaçındığımız
    şeyin ta kendisi — girdi durumunu paylaşmak.
    """

    #: İzde tutulan geçmiş konum sayısı. Sekiz, bir pencere genişliğinde
    #: yolu anlatmaya yetiyor; daha uzunu kareyi noktalarla dolduruyor.
    IZ_UZUNLUK = 8

    def __init__(self) -> None:
        self.imlec = Imlec()
        self.iz: deque[tuple[int, int]] = deque(maxlen=self.IZ_UZUNLUK)
        #: Son eylem tıklama mıydı — karede halka çizilsin diye.
        self.son_tik = False
        self._odak: int | None = None

    def _isaretle(self, tikladi: bool) -> None:
        self.iz.append((self.imlec.x, self.imlec.y))
        self.son_tik = tikladi

    # -- fare -------------------------------------------------------

    def tasi(self, x: int, y: int, hwnd: int | None = None) -> None:
        """İmleci taşır ve varsa altındaki pencereye üzerinde-gezinme bildirir."""
        self.imlec.tasi(x, y)
        self._isaretle(False)
        if hwnd:
            alici, cx, cy = _derin_cocuk(hwnd, x, y)
            _u32.PostMessageW(alici, WM_MOUSEMOVE, 0, _lp(cx, cy))

    def tikla(self, hwnd: int, x: int, y: int, sag: bool = False,
              cift: bool = False) -> None:
        """İmleci noktaya taşıyıp tıklar. Fiziksel fare kıpırdamaz."""
        self.imlec.tasi(x, y)
        alici, cx, cy = _derin_cocuk(hwnd, x, y)
        p = _lp(cx, cy)
        bas, birak, tus = (
            (WM_RBUTTONDOWN, WM_RBUTTONUP, MK_RBUTTON) if sag
            else (WM_LBUTTONDOWN, WM_LBUTTONUP, MK_LBUTTON)
        )
        # Gezinme iletisi önce: birçok denetim tıklamayı ancak fare
        # üzerine geldikten sonra kabul ediyor.
        _u32.PostMessageW(alici, WM_MOUSEMOVE, 0, p)
        _u32.PostMessageW(alici, bas, tus, p)
        time.sleep(TIK_SURESI)
        _u32.PostMessageW(alici, birak, 0, p)
        if cift:
            time.sleep(TIK_SURESI)
            _u32.PostMessageW(alici, WM_LBUTTONDBLCLK, tus, p)
            time.sleep(TIK_SURESI)
            _u32.PostMessageW(alici, birak, 0, p)
        self._isaretle(True)
        self._odak = alici

    def kaydir(self, hwnd: int, x: int, y: int, adim: int) -> None:
        """Tekerlek. `adim` pozitifse yukarı.

        `WM_MOUSEWHEEL`'in lParam'ı istemci değil **ekran** koordinatı
        taşır — diğer bütün fare iletilerinin tersi. Windows'un
        tutarsızlığı, bizim hatamız değil.
        """
        self.imlec.tasi(x, y)
        self._isaretle(False)
        alici, _, _ = _derin_cocuk(hwnd, x, y)
        wp = (int(adim) * WHEEL_DELTA) << 16
        _u32.PostMessageW(alici, WM_MOUSEWHEEL, wp, _lp(x, y))

    # -- klavye -----------------------------------------------------

    def yaz(self, metin: str, hwnd: int | None = None) -> None:
        """Metni harf harf yazar. Türkçe karakterler dahil.

        `WM_CHAR` kod noktası taşıyor, tarama kodu değil — yani klavye
        düzeninden bağımsız. `ğüşıöç` İngilizce düzende de doğru düşüyor.
        """
        alici = hwnd or self._odak
        if not alici:
            raise DesteklenmiyorHatasi("click somewhere first — the focus is unknown")
        for harf in metin:
            _u32.PostMessageW(alici, WM_CHAR, ord(harf), 1)
            time.sleep(HARF_ARASI)

    def tus(self, ad: str, hwnd: int | None = None) -> None:
        """Düz bir tuşa basar. Kombinasyonlar desteklenmiyor — modül başlığı."""
        anahtar = ad.strip().casefold()
        if "+" in anahtar:
            raise DesteklenmiyorHatasi(
                f"'{ad}': a posted message cannot hold a modifier key down. "
                "Click the app's menu instead of using a shortcut."
            )
        vk = TUSLAR.get(anahtar)
        if vk is None:
            raise DesteklenmiyorHatasi(f"unknown key: {ad}")
        alici = hwnd or self._odak
        if not alici:
            raise DesteklenmiyorHatasi("click somewhere first — the focus is unknown")
        _u32.PostMessageW(alici, WM_KEYDOWN, vk, 1)
        time.sleep(HARF_ARASI)
        _u32.PostMessageW(alici, WM_KEYUP, vk, 1)
