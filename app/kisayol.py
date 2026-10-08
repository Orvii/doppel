"""Global kısayol — uygulama arkadayken ajanı çağırmak.

Komut çubuğu ekranın köşesinde yüzüyor ama bir tarayıcı ya da bir kod
düzenleyici tam ekrandayken altında kalıyor. Ona ulaşmanın yolu şimdiye
kadar pencereleri karıştırmaktı; bir kısayol tuşu bunu bir basışa
indiriyor.

## Neden ayrı bir thread

`RegisterHotKey` pencere tutamacı verilmediğinde `WM_HOTKEY`'i **thread'in
mesaj kuyruğuna** yolluyor. Bunu Qt'nin ana döngüsünden `nativeEventFilter`
ile yakalamak mümkün ama iki şeye bağlı: Qt'nin thread mesajlarını
süzgeçlere iletmesine ve ana döngünün tıkanmamasına. Ajan tam da ana
thread'i meşgul eden şey.

Bu yüzden kendi thread'i ve kendi `GetMessageW` döngüsü var. Bu döngü
`GetMessageW` dışında hiçbir şey yapmıyor, yani bloklanacak bir yeri de
yok. `killswitch.py` aynı gerekçeyle yoklama yapıyor: acil olan şeyin
başka hiçbir şeye bağlı olmaması gerekiyor.

## Kayıt tutmazsa

`RegisterHotKey` başka bir uygulama aynı kombinasyonu almışsa `0`
döndürüyor. Bu yutulmuyor: `hata` alanına yazılıyor ve arayüz onu durum
satırında söylüyor. Sessizce çalışmayan bir kısayol, bozuk bir klavye gibi
hissettiriyor.

## Linux'ta kısayol yok — ve bu dürüstçe söyleniyor

`RegisterHotKey` bir Win32 kavramı; Linux'ta karşılığı X11 tuş yakalama
(`XGrabKey`) ya da `org.freedesktop.portal.GlobalShortcuts` portalı ve
ikisi de masaüstüne/oturum türüne göre değişiyor: X11'de portal çoğu
zaman kurulu değil, Wayland'de X11 yakalama diye bir şey yok. Burada
uydurma bir yakalama denenmiyor.

Bunun yerine `kur()` Windows dışında **kayıtlı olmayan** bir nesne
döndürüyor, `hata` alanında da sebebini yazıyor: arayüz zaten bu alanı
durum satırına basıyor, yani kullanıcı "kısayol var ama çalışmıyor"
durumunda kalmıyor, "burada kısayol yok" cümlesini okuyor. Kısayolun
sunduğu şeyin (arkadaki ajanı öne getirmek) Linux'ta başka yolları var:
tepsi menüsündeki "Show the command bar", ve uygulamayı ikinci kez
başlatmak. İkincisi `single.py` yüzünden zaten var olanı öne getiriyor.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal

from . import isletim

if isletim.WINDOWS:
    import ctypes
    from ctypes import wintypes
else:  # Linux: `wintypes` yok; dallar da çalışmıyor
    ctypes = None  # type: ignore[assignment]
    wintypes = None  # type: ignore[assignment]

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
#: Tuş basılı tutulunca tekrar tetiklenmesin.
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

VK_SPACE = 0x20

#: Sırayla denenen kombinasyonlar; ilk boş olan alınıyor.
#:
#: Tek bir sabit kombinasyon yetmiyor: bu makinede Ctrl+Alt+Space ve
#: Win+Shift+Space **başka uygulamalarda** çıktı — ölçtüm. Global bir
#: kısayolun boş olup olmadığı makineye göre değişiyor ve tek adayla
#: gelen bir uygulama o makinelerde kısayolsuz kalıyor.
#:
#: Ctrl+Shift+Space listede yok: boş görünüyor ama birçok düzenleyicide
#: parametre ipucu o tuşta ve global bir kayıt onu uygulamanın elinden
#: alıyor. Bir kısayol kazanmak için başka bir kısayolu bozmak, kazanç
#: değil.
ADAYLAR = (
    (MOD_CONTROL | MOD_ALT, VK_SPACE, "Ctrl+Alt+Space"),
    (MOD_CONTROL | MOD_ALT, 0x59, "Ctrl+Alt+Y"),
    (MOD_CONTROL | MOD_SHIFT, 0x59, "Ctrl+Shift+Y"),
    (MOD_CONTROL | MOD_ALT, 0x4D, "Ctrl+Alt+M"),
)

VARSAYILAN_MOD, VARSAYILAN_TUS, VARSAYILAN_AD = ADAYLAR[0]

#: `RegisterHotKey` bu hatayı kombinasyon başkasındayken veriyor.
ERROR_HOTKEY_ALREADY_REGISTERED = 1409

KIMLIK = 0xB001


class GlobalKisayol(QObject):
    """Windows'a bir kısayol kaydeder, basılınca `basildi` yayar.

    Sinyal kendi thread'inden yayılıyor; alıcılar ana thread'de olduğu
    için Qt bağlantıyı kendiliğinden kuyruğa alıyor.
    """

    basildi = Signal()

    def __init__(self, mod: int = VARSAYILAN_MOD, tus: int = VARSAYILAN_TUS,
                 ad: str = VARSAYILAN_AD) -> None:
        super().__init__()
        self.mod, self.tus, self.ad = mod, tus, ad
        #: Kayıt tutmadıysa sebebi. Tuttuysa boş.
        self.hata = ""
        self._thread: threading.Thread | None = None
        self._tid = 0
        self._hazir = threading.Event()

    @property
    def kayitli(self) -> bool:
        return self._thread is not None and not self.hata

    def start(self, timeout: float = 2.0) -> bool:
        """Kısayolu kaydeder. Tuttuysa `True`.

        Linux'ta kaydetmiyor ve iş parçacığı da açmıyor: denenip
        başarısız olan bir kayıt, sebebi olmayan bir hatayı andırırdı.
        `hata` alanına yazılan cümle arayüzde durum satırında görünüyor.
        """
        if not isletim.WINDOWS:
            self.hata = (
                "global shortcuts are not available on this desktop — "
                "use the tray menu or start Doppel again to bring the "
                "command bar up"
            )
            return False
        if self._thread is not None:
            return self.kayitli
        self.hata = ""
        self._hazir.clear()
        self._thread = threading.Thread(
            target=self._dongu, daemon=True, name="global-kisayol"
        )
        self._thread.start()
        if not self._hazir.wait(timeout):
            # Thread'in kurulumu bu kadar sürmez; sürdüyse elde bir şey
            # yok demektir ve bunu "çalışıyor" diye göstermek yanlış olur.
            self.hata = "the shortcut thread did not start"
        return self.kayitli

    def stop(self) -> None:
        if self._thread is None:
            return
        if self._tid:
            ctypes.windll.user32.PostThreadMessageW(
                self._tid, WM_QUIT, 0, 0
            )
        self._thread.join(timeout=1.0)
        self._thread = None
        self._tid = 0

    # --- thread ------------------------------------------------------------

    def _dongu(self) -> None:
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            kernel32 = ctypes.WinDLL("kernel32")
        except (AttributeError, OSError) as exc:
            self.hata = f"could not reach the Windows API: {exc}"
            self._hazir.set()
            return

        self._tid = kernel32.GetCurrentThreadId()
        ok = user32.RegisterHotKey(
            None, KIMLIK, self.mod | MOD_NOREPEAT, self.tus
        )
        if not ok:
            kod = ctypes.get_last_error()
            self.hata = (
                f"{self.ad} is already taken by another app"
                if kod == ERROR_HOTKEY_ALREADY_REGISTERED
                else f"{self.ad} could not be registered (error {kod})"
            )
            self._hazir.set()
            return
        self._hazir.set()

        mesaj = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(mesaj), None, 0, 0) > 0:
                if mesaj.message == WM_HOTKEY:
                    self.basildi.emit()
        finally:
            user32.UnregisterHotKey(None, KIMLIK)


def kur(adaylar=ADAYLAR, timeout: float = 2.0) -> GlobalKisayol:
    """İlk boş kombinasyonu kaydeder.

    Hepsi doluysa dönen nesnenin `kayitli`'sı `False` ve `hata`'sı
    denenenlerin hepsini sayıyor. Arayüz bunu olduğu gibi söylüyor:
    çalışmayan bir kısayolun sessizce yok sayılması, bozuk bir klavye
    gibi hissettiriyor.
    """
    if not isletim.WINDOWS:
        # Adayları denemek burada anlamsız: hiçbiri kaydedilemiyor. Tek
        # bir nesne, tek bir sebep — "hepsi dolu" cümlesi yanlış olurdu.
        bos = GlobalKisayol()
        bos.start()
        return bos
    son: GlobalKisayol | None = None
    for mod, tus, ad in adaylar:
        aday = GlobalKisayol(mod, tus, ad)
        if aday.start(timeout):
            return aday
        aday.stop()
        son = aday
    kalan = son or GlobalKisayol()
    kalan.hata = (
        "no global shortcut is free — tried "
        + ", ".join(ad for _m, _t, ad in adaylar)
    )
    return kalan
