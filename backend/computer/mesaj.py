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

## X11 dalı: mesaj yok, ama donanım da yok

X11'de postalanmış ileti diye bir şey yok — ve olması da gerekmiyor.
Yan masa artık **ayrı bir X ekranı** (`masaustu_x11`): orada XTEST'in
vuruşları kullanıcının imlecine değil, o ekranın imlecine gidiyor.
Windows'ta ileti taklidi, kullanıcının masaüstündeki fiziksel imleci
oynatmamak için bir zorunluluktu; X11'de ayrı ekran bu zorunluluğu
kaldırıyor: ajan kendi ekranında gerçek bir fare/klavye sürüyor, ilki
kimsenin göremediği ikinci bir imleç.

- **Fiziksel donanıma yine dokunulmuyor**: `input.py`'nin aksine burada
  doğrudan xdotool sürücüsü kullanılıyor ve hedef açıkça yan ekran
  (`erisim.girdi_sec(x_goster=...)`). `Girdi()`nin geri kalanı aynı.
- **Tuş kombinasyonu burada çalışıyor**: Windows'ta `Ctrl+S` gönderilemez
  çünkü tuş *durumunu* hedefin iş parçacığında tutmak gerekir; X11'de tuş
  basma/bırakma gerçek olaylar, kombinasyon da gerçek. `tus()` burada
  `ctrl+s` kabul ediyor — sınır artık yok, uydurma bir sınır koymak
  ajanı gereksiz yere menü tıklamaya mahkûm ederdi.
- **Odak PointerRoot**: Xvfb'de pencere yöneticisi yok, X sunucusu
  tuşları **imlecin altındaki** pencereye veriyor. `yaz()`/`tus()` bu
  yüzden tuştan önce imleci ajanın konumuna taşıyor (mekanik nedenleri
  `masaustu_x11` başlığında). Kalıcı sınır: uygulama kendisi odağı
  değiştirirse tuş başka pencereye gidebilir; `ctrl+w` gibi yıkıcı bir
  kombinasyonun modele verilmemesi `side_act` tanımının işi.
- **Koordinat uzayı tek**: çağıran pencere ofsetini ekleyip **X pikseli**
  veriyor; xdotool ve mss aynı sunucunun aynı piksellerini okuyor, araya
  ölçek girmiyor (`masaustu_x11` başlığında nedeni). Windows'ta da aynı
  sözleşme: masaüstü koordinatı gelir, işletim sistemi kendi
  dönüşümünü yapar.

X11 dalı **çağrı anında** seçiliyor (`aktif_gosterge()`): yan masa
açılmadan önce kurulan bir `Girdi` bile açıldıktan sonra doğru ekrana
konuşuyor. Yan masa hiç açılmamışsa Windows dalı çalışır ve Linux'ta
`WindowsGerekli` ile yüksek sesle düşer — sessizce yanlış yere yazmaz.
"""

from __future__ import annotations

import ctypes
import threading
import time
from collections import deque
from dataclasses import dataclass

from . import komut
from .girdi_x11 import ADLAR, Desteklenmiyor
from .masaustu_ortak import aktif_gosterge
from .win32_kabuk import WinDLL, wintypes

_u32 = WinDLL("user32", use_last_error=True)

#: Yan ekranın X11 girdi kanalı: (gösterge, sürücü). `Girdi` örnekleri
#: yan masa açılmadan kuruluyor (dispatch.py), hedef ekran ise açılışta
#: belirleniyor — o yüzden kanal çağrı anında kuruluyor ve gösterge
#: değişmedikçe yaşıyor.
#:
#: Kilit iki iş yapıyor: kanal kurulumu (sürücü seçimi bir alt süreç
#: doğurabiliyor) ve eylem sırası. İkincisi görünüşte gereksiz ("her
#: eylem bir alt süreç zaten sıralı") ama değil: fare eylemi iki adımdır
#: (taşı + tıkla) ve iki thread araya girerse A'nın taşımasından sonra
#: B'nin tıklaması A'nın noktasına giderdi.
_x_kilit = threading.RLock()
_x_kanal: tuple[str, object] | None = None


def kanali_sifirla() -> None:
    """Kanalı unutturur. Kapanış ve test temizliği için."""
    global _x_kanal
    with _x_kilit:
        _x_kanal = None


def _x11_dal() -> tuple[str, object] | None:
    """Yan ekran açıksa (gösterge, sürücü) çifti, açık değilse `None`.

    Sürücü seçimi `erisim.girdi_sec(x_goster=...)` üzerinden: yetenek
    kararı tek yerde (`erisim.py`) kalıyor, burası kararı uygulamıyor.
    Seçim başarısızsa `DesteklenmiyorHatasi` — çağıran sessizce Windows
    dalına düşmez (o dal Linux'ta `WindowsGerekli` ile patlardı ve asıl
    sebebi saklardı).
    """
    global _x_kanal
    gosterge = aktif_gosterge()
    if not gosterge:
        kanali_sifirla()
        return None
    with _x_kilit:
        if _x_kanal is not None and _x_kanal[0] == gosterge:
            return _x_kanal
        from . import erisim  # noqa: PLC0415 - döngü kırmak için burada
        from .girdi_x11 import XdotoolSurucu, YdotoolSurucu  # noqa: PLC0415

        secim = erisim.girdi_sec(x_goster=gosterge)
        if secim.ad == "xdotool":
            surucu = XdotoolSurucu(secim.env)
        elif secim.ad == "ydotool":
            # ydotool uinput'a yazar; ekransız da tuş üretir ama imleç
            # konumunu okuyamaz. Yan masada yedek: tıklama ve yazma
            # çalışsın, imleç izi yanlış olmasın diye konum uydurmuyoruz
            # (tasi yalnızca durum tutuyor).
            surucu = YdotoolSurucu(secim.env)
        else:
            raise DesteklenmiyorHatasi(
                f"no input backend for the side display {gosterge}: "
                f"{secim.hata or 'nothing usable was found'}"
            )
        _x_kanal = (gosterge, surucu)
        return _x_kanal


def _x_dene(fn):
    """X11 sürücüsü çağrısını yapıp hatalarını `DesteklenmiyorHatasi`na çevirir.

    Dispatcher yalnızca bu istisnayı modele görünür bir araç hatasına
    çeviriyor (`dispatch.py`); başka bir tür yukarı sızarsa model
    "beklenmeyen hata" görür ve asıl sebebi (ölü xdotool, desteklenmeyen
    işlem) öğrenemez.
    """
    try:
        return fn()
    except Desteklenmiyor as exc:
        raise DesteklenmiyorHatasi(
            f"the side display's driver cannot do this: {exc}") from None
    except (komut.KomutYokHatasi, komut.KomutHatasi, ValueError) as exc:
        raise DesteklenmiyorHatasi(str(exc)) from None


def _x_keysym(ad: str) -> str:
    """Kullanıcı tuş adını xdotool keysym'ine çevirir.

    `ADLAR` (`girdi_x11`) zaten tam ters eşlemeyi taşıyor: `enter` ->
    `Return`, `f5` -> `F5`. Burada aynı sözlük soruluyor — ikinci bir
    isim listesi yazmak, iki listenin bir gün ayrışması demek.
    """
    anahtar = ad.strip().casefold()
    giris = ADLAR.get(anahtar)
    if giris is None:
        raise DesteklenmiyorHatasi(f"unknown key: {ad}")
    return giris[0]  # xdotool keysym adı

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

    # -- X11 dalı ---------------------------------------------------
    #
    # Ortak kural: her eylemden sonra `_isaretle` çağrılıyor. Canlı
    # görüntü (`canli.py`) imleci bu değişkenden çiziyor — gerçek X imleci
    # okunmuyor, çünkü Windows'ta da okunmuyordu ve okunsaydı ajanın
    # olmadığı anlarda (X sunucusunun kendi konumu) yalan söylerdi.

    def _x_tasi(self, surucu, x: int, y: int) -> None:
        _x_dene(lambda: surucu.move_to(x, y))
        self.imlec.tasi(x, y)
        self._isaretle(False)

    def _x_tikla(self, surucu, x: int, y: int, sag: bool = False,
                 cift: bool = False) -> None:
        dugme = "right" if sag else "left"
        sayi = 2 if cift else 1
        self._x_tasi(surucu, x, y)
        _x_dene(lambda: surucu.click(x, y, dugme, sayi))
        self._isaretle(True)

    def _x_kaydir(self, surucu, x: int, y: int, adim: int) -> None:
        # `adim` `mesaj.py` sözleşmesi: pozitif yukarı. Tekerlek "tık"ı
        # ayrı bir sayı değil, aynı büyüklüğün xdotool karşılığı.
        yon = "up" if adim > 0 else "down"
        miktar = max(1, abs(int(adim)))
        self._x_tasi(surucu, x, y)
        _x_dene(lambda: surucu.scroll(yon, miktar))
        self._isaretle(False)

    def _x_odakla(self, surucu) -> None:
        """İmleci ajanın son bilinen konumuna taşır — odak PointerRoot'tur.

        Xvfb'de pencere yöneticisi yok; tuşlar imlecin altındaki pencereye
        gidiyor. İmleci son tıklanan noktaya koymak, Windows'taki
        `self._odak` sözleşmesinin X11 karşılığı (tam gerekçe
        `masaustu_x11` başlığında).
        """
        _x_dene(lambda: surucu.move_to(self.imlec.x, self.imlec.y))

    def _x_yaz(self, surucu, metin: str) -> None:
        self._x_odakla(surucu)
        _x_dene(lambda: surucu.type_text(metin))
        self._isaretle(False)

    def _x_tus(self, surucu, ad: str) -> None:
        self._x_odakla(surucu)
        if "+" in ad:  # kombinasyon: XTEST gerçek basış üretir, sınır yok
            _x_dene(lambda: surucu.press(ad))
        else:
            # Önce doğrula: bilinmeyen tuş xdotool'a hiç gitmesin. Sürücü
            # sözlüğü (`ADLAR`) tek isim kaynağı; `press` kendi doğruluyor,
            # düz tuş yolu burada aynı sözlükten geçiyor.
            _x_keysym(ad)
            adlar = [ad.strip().casefold()]
            _x_dene(lambda: surucu.tus_adlari_bas(adlar))
            _x_dene(lambda: surucu.tus_adlari_birak(adlar))
        self._isaretle(False)

    # -- fare -------------------------------------------------------

    def tasi(self, x: int, y: int, hwnd: int | None = None) -> None:
        """İmleci taşır ve varsa altındaki pencereye üzerinde-gezinme bildirir."""
        dal = _x11_dal()
        if dal is not None:
            _, surucu = dal
            with _x_kilit:
                self._x_tasi(surucu, x, y)
            return
        self.imlec.tasi(x, y)
        self._isaretle(False)
        if hwnd:
            alici, cx, cy = _derin_cocuk(hwnd, x, y)
            _u32.PostMessageW(alici, WM_MOUSEMOVE, 0, _lp(cx, cy))

    def tikla(self, hwnd: int, x: int, y: int, sag: bool = False,
              cift: bool = False) -> None:
        """İmleci noktaya taşıyıp tıklar. Fiziksel fare kıpırdamaz."""
        dal = _x11_dal()
        if dal is not None:
            _, surucu = dal
            with _x_kilit:
                self._x_tikla(surucu, x, y, sag, cift)
            return
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
        dal = _x11_dal()
        if dal is not None:
            _, surucu = dal
            with _x_kilit:
                self._x_kaydir(surucu, x, y, adim)
            return
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
        dal = _x11_dal()
        if dal is not None:
            _, surucu = dal
            with _x_kilit:
                self._x_yaz(surucu, metin)
            return
        alici = hwnd or self._odak
        if not alici:
            raise DesteklenmiyorHatasi("click somewhere first — the focus is unknown")
        for harf in metin:
            _u32.PostMessageW(alici, WM_CHAR, ord(harf), 1)
            time.sleep(HARF_ARASI)

    def tus(self, ad: str, hwnd: int | None = None) -> None:
        """Bir tuşa (X11'de kombinasyona da) basar.

        Windows: düz tuşlar; kombinasyon reddedilir — modül başlığı.
        X11: kombinasyon gerçek basışlarla gidiyor, sınır yok.
        """
        dal = _x11_dal()
        if dal is not None:
            _, surucu = dal
            with _x_kilit:
                self._x_tus(surucu, ad)
            return
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
