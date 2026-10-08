"""Girdi — RemoteDesktop portalı üzerinden fare ve klavye.

## İki yol var, biz D-Bus yolunu seçtik

Portal dokümanı iki girdi yolu sunuyor: `ConnectToEIS` (libei, "önerilen") ve
`Notify*` D-Bus yöntemleri. Doküman birincisini öneriyor çünkü EIS olay
akışını toplu ve düşük gecikmeli taşıyor. Ama libei bir C kitaplığı ve
Python'dan kullanmak EI protokolünü kendimiz konuşmak demek — bu deponun
kuralı dışında (yeni sistem bağımlılığı, test edilemez yol). `Notify*`
yöntemleri saf D-Bus: mock'lanabilir, imzaları dokümanda sabit. Seçim bu
yüzden `Notify*`.

Dokümandan çıkan sert bir kural: **EIS bağlantısı kurulduysa `Notify*`
kullanılmamalı.** Biz EIS'e hiç bağlanmıyoruz, yani bu koşul hiç doğmuyor.

## Mutlak konum, akış uzayında

`NotifyPointerMotionAbsolute` koordinatı **akışın mantıksal uzayında** ve
hedef akışın düğüm kimliğiyle birlikte istiyor. Yani her monitör ayrı bir
akış. Akışın `position`/`size` özellikleri tam olarak bir monitörün
yerleşimi: `Display(left, top, width, height)` ile aynı şekil. Sanal masaüstü
koordinatı bu yüzden `(x - position.x, y - position.y)` ile akış uzayına
çevriliyor — tek çeviri noktası `GirdiAkini.yerel`.

## Eksik: konum okuma

`Notify*` yolu **imlecin nerede olduğunu söylemiyor**; portal böyle bir okuma
sunmuyor. `cursor_position()` bu yüzden açık bir `KonumYokHatasi` yükseltiyor —
(0, 0) döndürmek, "tıklamayı imlecin durduğu yere yap" aracını sessizce
sol üst köşeye gönderirdi. Gerçek çözüm EIS/libei tarafında ve o da bu
depoda yok.

## Onay ve cihaz maskesi

`Start` kullanıcıya "hangi cihazlar" diyaloğu gösteriyor ve sonuçta
**verilen** cihazların bit maskesi dönüyor. Kullanıcı klavyeyi reddedip
fareyi verebilir. Bu yüzden maske saklanıyor ve her yöntem önce izni
sınıyor: izin yoksa çağrı hiç yapılmıyor, açık hata dönüyor. Portal zaten
reddederdi; ama hatayı portalın ağzından değil bizim cümlemizle söylemek,
modele "kullanıcı klavyeyi vermedi" dedirtmenin tek yolu.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field

from .portal_oturum import (
    ARAYUZ_GIRDI,
    HIZLI_ZAMANI,
    VARSAYILAN_ONAY_ZAMANI,
    cagir_ve_bekle,
    jeton,
    oturum_kapat,
    secenekler,
    yanit_bekle,
)
from .portal_tasiyici import (
    PORTAL_ADI,
    PORTAL_YOLU,
    PortalHatasi,
    SecenekDegeri,
    Tasiyici,
)

#: `AvailableDeviceTypes`: 1 KEYBOARD, 2 POINTER, 4 TOUCHSCREEN.
CIHAZ_KLAVYE = 1
CIHAZ_FARE = 2
CIHAZ_DOKUNMATIK = 4

#: Evdev düğme kodları (linux/include/uapi/linux/input-event-codes.h).
#: Portal dokümanı "Linux Evdev düğme kodları" diyor: BTN_LEFT 0x110,
#: BTN_RIGHT 0x111, BTN_MIDDLE 0x112.
DUGME_KODLARI = {
    "left": 0x110,
    "right": 0x111,
    "middle": 0x112,
}

BASILDI = 1
BIRAKILDI = 0

#: `NotifyPointerAxisDiscrete` eksenleri: 0 dikey, 1 yatay.
EKSEN_DIKEY = 0
EKSEN_YATAY = 1

#: Kaydırma yönü işareti. **Varsayım**: dikey eksende pozitif adım aşağı
#: kaydırıyor (evdev/tablet geleneği). Gerçek masaüstünde doğrulanmadı; tek
#: yerde duruyor ki yanlışsa bir satırda çevrilsin.
YON_ISARETI = {"up": -1, "down": 1, "left": -1, "right": 1}

#: X11 keysym sabitleri (xorgproto keysymdef.h). Değiştiriciler sol varyant.
KEYSYM = {
    "backspace": 0xFF08,
    "tab": 0xFF09,
    "return": 0xFF0D,
    "enter": 0xFF0D,
    "shift": 0xFFE1,
    "ctrl": 0xFFE3,
    "control": 0xFFE3,
    "alt": 0xFFE9,
    "pause": 0xFF13,
    "caps_lock": 0xFFE5,
    "escape": 0xFF1B,
    "esc": 0xFF1B,
    "space": 0x0020,
    "page_up": 0xFF55,
    "page_down": 0xFF56,
    "end": 0xFF57,
    "home": 0xFF50,
    "left": 0xFF51,
    "up": 0xFF52,
    "right": 0xFF53,
    "down": 0xFF54,
    "print": 0xFF61,
    "insert": 0xFF63,
    "delete": 0xFFFF,
    "super": 0xFFEB,
    "win": 0xFFEB,
    "menu": 0xFF67,
    "num_lock": 0xFF7F,
    "scroll_lock": 0xFF14,
}
KEYSYM.update({f"f{i}": 0xFFBE + i - 1 for i in range(1, 25)})  # F1=0xFFBE, F24=0xFFD5
KEYSYM.update({str(d): 0x30 + d for d in range(10)})
KEYSYM.update(
    {chr(kod): kod for kod in range(0x41, 0x5B)}  # 'A'-'Z'
)
KEYSYM.update({chr(kod).lower(): kod for kod in range(0x41, 0x5B)})

#: Metin yazarken karakter arası bekleme. Windows tarafındaki ölçüm
#: (`input.TYPE_DELAY` = 12 ms) buradan devralınıyor: aynı hedef
#: uygulamalar aynı hızda olay bekliyor, iki ayrı sayı tutmanın sebebi yok.
TYPE_DELAY = 0.012

#: Sürüklemede ara adım sayısı ve aralığı (`input.drag` ile aynı gerekçe:
#: tek sıçrayışta uygulamalar sürüklemeyi algılamıyor).
DRAG_ADIM = 24
DRAG_ARALIK = 0.008


class KonumYokHatasi(PortalHatasi):
    """İmleç konumu okunamıyor. `Notify*` yolu böyle bir okuma sunmuyor."""


class IzinYokHatasi(PortalHatasi):
    """İstenen cihaz türü kullanıcı tarafından verilmedi."""


def keysym_bul(ad: str) -> int:
    """`"ctrl"`, `"F4"`, `"a"` gibi tuş adını X11 keysym'ine çevirir."""
    anahtar = ad.strip().lower()
    if not anahtar:
        raise PortalHatasi(f"Empty key name: {ad!r}")
    if anahtar in KEYSYM:
        return KEYSYM[anahtar]
    raise PortalHatasi(f"Unknown key: {ad!r}")


def keysym_coz(ad: str) -> int:
    """Tuş adı ya da tek karakter: keysym."""
    if len(ad) == 1:
        return character_keysym(ad)
    return keysym_bul(ad)


def character_keysym(karakter: str) -> int:
    """Tek karakterin X11 keysym'i.

    kuralı (xorgproto keysymdef.h): Latin-1'deki her karakterin keysym'i
    kendi kod noktası; dışındaki her şey `0x01000000 + kod noktası`.
    Böylece `ğüşıöç` ve emoji Türkçe Q düzeni kurulu olmasa da doğru gidiyor
    — `input.type_text`'in KEYEVENTF_UNICODE kararının Linux karşılığı.
    """
    kod = ord(karakter)
    if kod > 0x10FFFF:
        raise PortalHatasi(f"Not a character: {karakter!r}")
    if 0x20 <= kod <= 0x7E:
        return kod
    return 0x01000000 + kod


def komboyu_coz(kombo: str) -> list[int]:
    """`"ctrl+shift+s"` → keysym listesi, değiştiriciler önce (`parse_combo`)."""
    parcalar = [parca.strip() for parca in kombo.split("+")]
    if not all(parcalar):
        raise PortalHatasi(f"Empty key name: {kombo!r}")
    return [keysym_coz(parca) for parca in parcalar]


@dataclass
class GirdiAkini:
    """Girdiye dönük akış bilgisi: kimlik + monitör yerleşimi.

    `portal_ekran.Akin` yakalamanın gördüğü zengin nesne; buradaki daha dar
    çünkü girdi için yalnızca konum, boyut ve düğüm kimliği anlamlı.
    """

    dugum: int
    sol: int
    ust: int
    genislik: int
    yukseklik: int

    def icinde_mi(self, vx: int, vy: int) -> bool:
        return self.sol <= vx < self.sol + self.genislik and self.ust <= vy < self.ust + self.yukseklik

    def yerel(self, vx: int, vy: int) -> tuple[float, float]:
        """Sanal masaüstü noktasını akışın mantıksal uzayına çevirir.

        Tek çeviri noktası; taşıma/kaydırma/sürükleme hep buradan geçiyor.
        Sınır dışı nokta kırpılmıyor, hata veriyor: sessizce kırpmak,
        ikinci monitöre yapılan bir tıklamayı birincinin kenarına
        göndermek demekti.
        """
        if not self.icinde_mi(vx, vy):
            raise PortalHatasi(
                f"({vx}, {vy}) is outside the portal stream {self.dugum} "
                f"({self.genislik}x{self.yukseklik} at {self.sol},{self.ust})"
            )
        return float(vx - self.sol), float(vy - self.ust)


def akinlardan(ham_liste) -> list[GirdiAkini]:
    """Portal `streams` listesinden girdi akışlarını çıkarır.

    Yerleşim bilgisi olmayan akış atlanıyor: `position`/`size` monitör
    akışlarında opsiyonel ve ikisi olmadan mutlak konum çevrilemez.
    """
    akinlar: list[GirdiAkini] = []
    for oge in ham_liste or []:
        if not isinstance(oge, (list, tuple)) or len(oge) < 2:
            continue
        ozellikler = dict(oge[1] or {})
        konum = ozellikler.get("position")
        boyut = ozellikler.get("size")
        if not (
            isinstance(konum, (list, tuple))
            and isinstance(boyut, (list, tuple))
            and len(konum) == 2
            and len(boyut) == 2
        ):
            continue
        try:
            akinlar.append(
                GirdiAkini(
                    dugum=int(oge[0]),
                    sol=int(konum[0]),
                    ust=int(konum[1]),
                    genislik=int(boyut[0]),
                    yukseklik=int(boyut[1]),
                )
            )
        except (TypeError, ValueError):
            continue
    return akinlar


@dataclass
class GirdiOturumu:
    """RemoteDesktop oturumu; istenirse aynı oturumda ekran paylaşımı da.

    `ekran_da=True` seçildiğinde portal dokümanının "cross-portal" önerisi
    uygulanıyor: oturum RemoteDesktop'ta açılıyor, `SelectDevices`'ten sonra
    **aynı oturum** üzerinde `ScreenCast.SelectSources` çağrılıyor ve
    başlatma yine `RemoteDesktop.Start`. Tek diyalog, tek izin: kullanıcı
    hem ekranı hem girdiyi bir kez onaylıyor. Ayrı iki oturum açmak iki
    diyalog ve iki "izin ver" demekti.
    """

    tasiyici: Tasiyici
    oturum_yolu: str = ""
    izinli: int = 0
    akinlar: list[GirdiAkini] = field(default_factory=list)
    pipewire_fd: int | None = None

    # --- kurulum ----------------------------------------------------------

    @classmethod
    def ac(
        cls,
        tasiyici: Tasiyici,
        cihazlar: int = CIHAZ_KLAVYE | CIHAZ_FARE,
        ekran_da: bool = False,
        kaynak_turu: int = 0,
        imlec_kipi: int = 0,
        zaman_asimi: float = VARSAYILAN_ONAY_ZAMANI,
    ) -> "GirdiOturumu":
        """CreateSession → SelectDevices → [SelectSources] → Start."""
        oturum = cls(tasiyici=tasiyici)
        oturum.oturum_yolu = cls._oturum_ac(tasiyici, zaman_asimi)
        try:
            cls._cihazlari_sec(tasiyici, oturum.oturum_yolu, cihazlar, zaman_asimi)
            if ekran_da:
                # Geç import: ekran modülü ekran oturumunu de kuruyor, ama
                # bu yol yalnızca iki adımını ödünç alıyor.
                from . import portal_ekran

                portal_ekran.kaynaklari_sec(
                    tasiyici,
                    oturum.oturum_yolu,
                    imlec_kipi or portal_ekran.IMLEC_GOMULU,
                    zaman_asimi,
                )
            sonuclar = cls._basla(
                tasiyici, oturum.oturum_yolu, zaman_asimi, ekran_da=ekran_da
            )
            oturum.izinli = int(sonuclar.get("devices", 0) or 0)
            oturum.akinlar = akinlardan(sonuclar.get("streams"))
            if ekran_da:
                oturum.pipewire_fd = portal_ekran.pipewire_fd_al(tasiyici, oturum.oturum_yolu)
        except Exception:
            oturum.kapat()
            raise
        return oturum

    @staticmethod
    def _oturum_ac(tasiyici: Tasiyici, zaman_asimi: float) -> str:
        jet = jeton("girdi")
        onay = cagir_ve_bekle(
            tasiyici,
            ARAYUZ_GIRDI,
            "CreateSession",
            [secenekler(handle_token=jet, session_handle_token=jeton("s"))],
            "remote desktop session",
            zaman_asimi=zaman_asimi,
        )
        sonuclar = onay.dogrula("remote desktop session")
        oturum = sonuclar.get("session_handle")
        if not oturum:
            raise PortalHatasi("CreateSession returned no session_handle")
        return oturum

    @staticmethod
    def _cihazlari_sec(tasiyici: Tasiyici, oturum: str, cihazlar: int, zaman_asimi: float) -> None:
        onay = cagir_ve_bekle(
            tasiyici,
            ARAYUZ_GIRDI,
            "SelectDevices",
            [oturum, secenekler(handle_token=jeton("cihaz"), types=SecenekDegeri("u", cihazlar))],
            "input devices",
            imza="oa{sv}",
            zaman_asimi=zaman_asimi,
        )
        onay.dogrula("input devices")

    @staticmethod
    def _basla(
        tasiyici: Tasiyici, oturum: str, zaman_asimi: float, ekran_da: bool = False
    ) -> dict:
        """`Start` — onay diyaloğu burada. Verilen cihaz maskesi döner."""
        from .portal_oturum import istek_yolu

        jet = jeton("basla")
        beklenen = istek_yolu(tasiyici, jet)
        _, govde, _ = tasiyici.cagir(
            PORTAL_ADI,
            PORTAL_YOLU,
            ARAYUZ_GIRDI,
            "Start",
            "osa{sv}",
            [oturum, "", secenekler(handle_token=jet)],
            zaman_asimi=HIZLI_ZAMANI,
        )
        istek = govde[0] if govde else beklenen
        ne = "remote desktop session"
        onay = yanit_bekle(tasiyici, istek, ne, zaman_asimi)
        return onay.dogrula(ne)

    # --- izin sınaması ----------------------------------------------------

    def _izin_dogrula(self, cihaz: int, ne: str) -> None:
        if not self.izinli & cihaz:
            raise IzinYokHatasi(
                f"The user did not grant {ne} access to this session (granted "
                f"device mask: {self.izinli}); the portal consent dialog "
                "decides this and the agent cannot bypass it"
            )

    def _akinlar_gerekli(self) -> list[GirdiAkini]:
        if not self.akinlar:
            raise PortalHatasi(
                "This session has no screen cast streams, so absolute pointer "
                "motion cannot be translated; open the session with screen "
                "sharing enabled"
            )
        return self.akinlar

    def _gonder(self, arayuz: str, uye: str, imza: str, govde: list) -> None:
        """`Notify*` çağrısı. Hepsi hızlı zaman aşımıyla çitli.

        Bekleme diyaloğu açmıyorlar; ama portal tıkanırsa asılı kalmak
        yerine hata vermeli. Ajan döngüsünde asılı bir çağrı, ajanın
        durduğu anlamına gelir ve bunu kimse göremez.
        """
        self.tasiyici.cagir(
            PORTAL_ADI, PORTAL_YOLU, arayuz, uye, imza, govde, zaman_asimi=HIZLI_ZAMANI
        )

    def _akis_ve_nokta(self, vx: int, vy: int) -> tuple[int, float, float]:
        for akin in self._akinlar_gerekli():
            if akin.icinde_mi(vx, vy):
                x, y = akin.yerel(vx, vy)
                return akin.dugum, x, y
        raise PortalHatasi(
            f"({vx}, {vy}) is not inside any shared stream; the user only "
            "gave access to some monitors"
        )

    # --- fare (`input.py` sözleşmesi) -------------------------------------

    def move_to(self, vx: int, vy: int) -> None:
        """`NotifyPointerMotionAbsolute` — akış uzayında mutlak konum."""
        self._izin_dogrula(CIHAZ_FARE, "pointer")
        dugum, x, y = self._akis_ve_nokta(vx, vy)
        self._gonder(
            ARAYUZ_GIRDI,
            "NotifyPointerMotionAbsolute",
            "oa{sv}udd",
            [self.oturum_yolu, {}, dugum, x, y],
        )

    def cursor_position(self) -> tuple[int, int]:
        raise KonumYokHatasi(
            "The RemoteDesktop portal does not expose the pointer position "
            "over its D-Bus Notify API; reading it needs an EIS/libei "
            "connection, which this build does not make. Callers that need "
            "the position must be given coordinates explicitly."
        )

    def click(self, vx: int, vy: int, button: str = "left", count: int = 1) -> None:
        """Tıklama = mutlak taşıma + düğme bas/bırak.

        Portal'da "şu noktaya tıkla" yok; düğme olayı imlecin durduğu yere
        gidiyor. Bu yüzden önce taşınıyor.
        """
        if button not in DUGME_KODLARI:
            raise PortalHatasi(f"Unknown mouse button: {button}")
        self.move_to(vx, vy)
        for sira in range(count):
            if sira:
                # Windows çift tıklama eşiğinin altında kalma; `input.click`
                # ile aynı 60 ms.
                time.sleep(0.06)
            self.mouse_down(button)
            self.mouse_up(button)

    def mouse_down(self, button: str = "left") -> None:
        self._dugme(button, BASILDI)

    def mouse_up(self, button: str = "left") -> None:
        self._dugme(button, BIRAKILDI)

    def _dugme(self, button: str, durum: int) -> None:
        self._izin_dogrula(CIHAZ_FARE, "pointer")
        if button not in DUGME_KODLARI:
            raise PortalHatasi(f"Unknown mouse button: {button}")
        self._gonder(
            ARAYUZ_GIRDI,
            "NotifyPointerButton",
            "oa{sv}iu",
            [self.oturum_yolu, {}, DUGME_KODLARI[button], durum],
        )

    def drag(self, from_xy: tuple[int, int], to_xy: tuple[int, int], steps: int = DRAG_ADIM) -> None:
        """Basılı tutarak sürükler; ara adımlar `input.drag` ile aynı sebeple."""
        self.move_to(*from_xy)
        self.mouse_down("left")
        try:
            x0, y0 = from_xy
            x1, y1 = to_xy
            for i in range(1, steps + 1):
                t = i / steps
                self.move_to(round(x0 + (x1 - x0) * t), round(y0 + (y1 - y0) * t))
                time.sleep(DRAG_ARALIK)
        finally:
            self.mouse_up("left")

    def scroll(self, direction: str, amount: int, at: tuple[int, int] | None = None) -> None:
        """`NotifyPointerAxisDiscrete` — ayrık tekerlek adımları."""
        self._izin_dogrula(CIHAZ_FARE, "pointer")
        if direction not in YON_ISARETI:
            raise PortalHatasi(f"Unknown scroll direction: {direction}")
        if at is not None:
            self.move_to(*at)
        eksen = EKSEN_DIKEY if direction in ("up", "down") else EKSEN_YATAY
        self._gonder(
            ARAYUZ_GIRDI,
            "NotifyPointerAxisDiscrete",
            "oa{sv}ui",
            [self.oturum_yolu, {}, eksen, YON_ISARETI[direction] * amount],
        )

    # --- klavye -----------------------------------------------------------

    def key_press(self, keysym: int, durum: int) -> None:
        """Tek keysym bas/bırak. Toplu yazımın altındaki yapı taşı."""
        self._izin_dogrula(CIHAZ_KLAVYE, "keyboard")
        self._gonder(
            ARAYUZ_GIRDI,
            "NotifyKeyboardKeysym",
            "oa{sv}iu",
            [self.oturum_yolu, {}, keysym, durum],
        )

    def press(self, combo: str, repeat: int = 1) -> None:
        """Tuş ya da kombinasyon: `"Return"`, `"ctrl+s"`, `"alt+F4"`.

        Kombinasyon keysym'lerle gönderiliyor: değiştiriciler basılı tutulup
        asıl tuş basılıyor, sonra ters sırayla bırakılıyor. (EIS olsaydı
        tuş kodları daha kesin olurdu; `NotifyKeyboardKeysym` yolu
        kompozitörün kendi tuş haritasından geçiyor — gerçek masaüstünde
        doğrulanması gereken yer burası, UNVERIFIED.)
        """
        kodlar = komboyu_coz(combo)
        for _ in range(repeat):
            for keysym in kodlar:
                self.key_press(keysym, BASILDI)
            for keysym in reversed(kodlar):
                self.key_press(keysym, BIRAKILDI)
            time.sleep(0.01)

    @contextmanager
    def modifiers_held(self, combo: str | None):
        """Değiştiricileri basılı tutarken içerideki eylemi çalıştırır.

        Bırakma `finally` içinde — `input.modifiers_held` ile aynı gerekçe:
        ortada hata olursa ctrl basılı kalırsa kullanıcının klavyesi
        kullanılamaz hâle gelir.
        """
        if not combo:
            yield
            return
        kodlar = komboyu_coz(combo)
        for keysym in kodlar:
            self.key_press(keysym, BASILDI)
        try:
            yield
        finally:
            for keysym in reversed(kodlar):
                self.key_press(keysym, BIRAKILDI)

    def type_text(self, text: str, delay: float = TYPE_DELAY) -> None:
        """Metni harfi harfine yazar.

        Her karakter için bas/bırak, aralarında bekleme. Sebep Windows
        tarafında ölçülmüştü (`input.type_text`): olaylar hedefin mesaj
        kuyruğunun tükettiğinden hızlı gelirse karakterler düşüyor.
        Buradaki kuyruk D-Bus ve portal olduğu için aynı sayı birebir
        geçerli değil; devralınan değer, gerçek masaüstünde yeniden
        ölçülmesi gereken bir varsayım (UNVERIFIED).
        """
        self._izin_dogrula(CIHAZ_KLAVYE, "keyboard")
        for karakter in text:
            keysym = character_keysym(karakter)
            self.key_press(keysym, BASILDI)
            self.key_press(keysym, BIRAKILDI)
            if delay:
                time.sleep(delay)

    def hold(self, combo: str, duration: float) -> None:
        kodlar = komboyu_coz(combo)
        for keysym in kodlar:
            self.key_press(keysym, BASILDI)
        try:
            time.sleep(duration)
        finally:
            for keysym in reversed(kodlar):
                self.key_press(keysym, BIRAKILDI)

    # --- kapanış ----------------------------------------------------------

    def kapat(self) -> None:
        if self.oturum_yolu:
            oturum_kapat(self.tasiyici, self.oturum_yolu)
            self.oturum_yolu = ""
        if self.pipewire_fd is not None:
            try:
                import os

                os.close(self.pipewire_fd)
            except OSError:
                pass
            self.pipewire_fd = None
        self.akinlar = []