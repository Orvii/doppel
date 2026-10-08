"""Ekran yakalama — ScreenCast portalı, PipeWire akışları ve DURAN SINIR.

## Akış

`CreateSession → SelectSources → Start → OpenPipeWireRemote`. Sonuçta elimizde
portal oturumu, seçilen akışların listesi (düğüm kimliği + konum/boyut
özellikleri) ve PipeWire remote'unun dosya tanımlayıcısı oluyor.

## Nerede duruyoruz ve neden

**Kare alma uygulanmadı.** Bu bilinçli: `OpenPipeWireRemote`'un verdiği fd
`pw_context_connect_fd` ile bir `pw_core` kurmak için; kareye çevirmek
GStreamer (`pipewiresrc`) ya da ham libpipewire bağlayıcısı istiyor. İkisi de
saf Python değil, ve bu deponun kuralı yeni bir sistem bağımlılığını sessizce
içeri almamak. Ayrıca bu iş **Linux'ta koşulmadan** doğrulanamaz — burada
uydurulmuş bir kare yolu, çalıştığı iddiası dışında bir şey üretmez.

Bu yüzden sınır dürüst çiziliyor: oturum kurulur, akışlar çözülür, fd alınır
(dördü de mock'la sınanmış), ve kare isteyen her yol
`YakalamaYokHatasi` yükseltir. Bu bir hata değil **belgelenmiş bir eksik**:
mesajı ne eksik olduğunu ve seçenekleri söylüyor. Sahte kare üretilmiyor.

Eksik parçayı kapatmanın en kısa yolu, fd'yi `pass_fds` ile bir
`gst-launch-1.0 pipewiresrc fd=N path=M num-buffers=1 ! videoconvert !
pngenc ! filesink` alt sürecine vermek; bu ayrı bir iş olarak listelendi,
çünkü fd'nin alt sürece geçmesi ve `path` yerine `pipewire-serial` kullanımı
(portal v6+) kendi başına sınanması gereken bir yığın.

## Kombine oturum

Girdi ile yakalamanın aynı onay diyaloğunu paylaşması için portal şunu
öneriyor: oturumu `RemoteDesktop.CreateSession` ile aç, `SelectDevices`,
sonra **aynı oturum** üzerinde `ScreenCast.SelectSources`, ve başlatmayı
`RemoteDesktop.Start` ile yap. `portal_girdi.GirdiOturumu(ekran_da=True)` bu
yolu kuruyor; bu dosyadaki `kaynaklari_sec` ve `pipewire_fd_al` o yolun
kullanacağı iki adım. Tek oturum, tek diyalog, tek "izin ver".
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .portal_oturum import (
    ARAYUZ_EKRAN,
    HIZLI_ZAMANI,
    VARSAYILAN_ONAY_ZAMANI,
    cagir_ve_bekle,
    istek_yolu,
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

#: `AvailableSourceTypes`: 1 MONITOR, 2 WINDOW, 4 VIRTUAL. Monitör istiyoruz:
#: ajan model uzayı monitör başına kuruluyor (bkz. displays.py).
KAYNAK_MONITOR = 1

#: `AvailableCursorModes`: 1 Hidden, 2 Embedded, 4 Metadata.
IMLEC_GIZLI = 1
IMLEC_GOMULU = 2
IMLEC_USTVERI = 4


class YakalamaYokHatasi(PortalHatasi):
    """Oturum hazır ama kare alma uygulanmadı.

    Ayrı tür, çünkü çağıranın ayırt etmesi gerekiyor: burada **izin sorunu
    yok**, portal akışı da sağlam; yalnızca son dönüştürme adımı (PipeWire
    akışından kare) bu depoda yok. Kullanıcıya "Wayland'de ekran
    görüntüsü alınamadı" demek ile "portal reddedildi" demek farklı şeyler.
    """


@dataclass(frozen=True)
class Akin:
    """`Start` sonucundaki tek PipeWire akışı.

    `dugum`: Portal'ın verdiği PipeWire düğüm kimliği. Portal v6'dan beri
    izleme için **önerilmiyor** (düğüm kimlikleri yeniden kullanılabiliyor);
    `seri` (object.serial) tercih edilen kimlik. İkisi de tutuluyor ki
    tüketici hangisini destekliyorsa onunla hedefleyebilsin.
    """

    dugum: int
    ozellikler: dict[str, object] = field(default_factory=dict)

    @property
    def seri(self) -> int | None:
        return self.ozellikler.get("pipewire-serial")

    @property
    def konum(self) -> tuple[int, int] | None:
        return _ikili(self.ozellikler.get("position"))

    @property
    def boyut(self) -> tuple[int, int] | None:
        return _ikili(self.ozellikler.get("size"))

    @property
    def eşleme(self) -> str | None:
        """`mapping_id`: mutlak libei bölgelerini eşleştirmek için (v5+)."""
        return self.ozellikler.get("mapping_id")


def _ikili(deger) -> tuple[int, int] | None:
    """(ii) alanını iki tam sayıya çevirir; yoksa/bozuksa None."""
    if isinstance(deger, (list, tuple)) and len(deger) == 2:
        try:
            return int(deger[0]), int(deger[1])
        except (TypeError, ValueError):
            return None
    return None


def akinlari_coz(sonuclar: dict) -> list[Akin]:
    """`Start` sonucundaki `streams` alanını `Akin` listesine çevirir.

    Alan yoksa boş liste: `multiple=False` ile tek akış, `multiple=True` ile
    bir ya da daha çok akış dönüyor. Kullanıcı hiçbir monitör seçmezse
    `streams` hiç gelmeyebiliyor — bu bir çözümleme hatası değil, çağıranın
    kararı (devam etmenin anlamı yok).
    """
    ham = sonuclar.get("streams") or []
    akinlar: list[Akin] = []
    for oge in ham:
        if not isinstance(oge, (list, tuple)) or len(oge) < 2:
            continue
        try:
            akinlar.append(Akin(dugum=int(oge[0]), ozellikler=dict(oge[1] or {})))
        except (TypeError, ValueError):
            continue
    return akinlar


def imlec_kipi_sec(tasiyici: Tasiyici, istenen: int = IMLEC_GOMULU) -> int:
    """`AvailableCursorModes`'a bakıp desteklenen en iyi imleç kipini seçer.

    Gerekçe somut: doküman "desteklenmeyen bir kip istemek oturumu
    kapatır" diyor. Sabit `2` istemek, yalnızca `1` (Hidden) duyuran bir
    arka uçta oturumu sessizce düşürürdü. Sorup seçmek tek güvenli yol;
    hiçbiri okunamazsa `istenen` döner — çağrı yine de portalın kendi
    doğrulamasına kalır.
    """
    try:
        _, govde, _ = tasiyici.cagir(
            PORTAL_ADI,
            PORTAL_YOLU,
            "org.freedesktop.DBus.Properties",
            "Get",
            "ss",
            [ARAYUZ_EKRAN, "AvailableCursorModes"],
            zaman_asimi=HIZLI_ZAMANI,
        )
    except PortalHatasi:
        return istenen
    if not govde:
        return istenen
    kullanilabilir = govde[0]
    if not isinstance(kullanilabilir, int):
        return istenen
    if kullanilabilir & istenen:
        return istenen
    for aday in (IMLEC_GOMULU, IMLEC_USTVERI, IMLEC_GIZLI):
        if kullanilabilir & aday:
            return aday
    return istenen


def oturum_ac(tasiyici: Tasiyici, zaman_asimi: float = VARSAYILAN_ONAY_ZAMANI) -> str:
    """`CreateSession` — oturum yolunu döner. Onay diyaloğu açmaz."""
    jet = jeton("oturum")
    onay = cagir_ve_bekle(
        tasiyici,
        ARAYUZ_EKRAN,
        "CreateSession",
        [secenekler(handle_token=jet, session_handle_token=jeton("s"))],
        "screen capture session",
        zaman_asimi=zaman_asimi,
    )
    sonuclar = onay.dogrula("screen capture session")
    oturum = sonuclar.get("session_handle")
    if not oturum:
        raise PortalHatasi("CreateSession returned no session_handle")
    return oturum


def kaynaklari_sec(
    tasiyici: Tasiyici,
    oturum: str,
    imlec_kipi: int = IMLEC_GOMULU,
    zaman_asimi: float = VARSAYILAN_ONAY_ZAMANI,
) -> None:
    """`SelectSources` — monitörleri ister.

    `multiple=True`: kullanıcı birden çok monitör seçebilsin. Hangi
    monitörlerin seçildiği akışların `position`/`size` özelliklerinden
    çözülüyor; index eşlemesi yapılmıyor çünkü portal monitör numarası
    diye bir şey vermiyor.
    """
    jet = jeton("kaynak")
    onay = cagir_ve_bekle(
        tasiyici,
        ARAYUZ_EKRAN,
        "SelectSources",
        [
            oturum,
            secenekler(
                handle_token=jet,
                types=SecenekDegeri("u", KAYNAK_MONITOR),
                multiple=True,
                cursor_mode=SecenekDegeri("u", imlec_kipi),
            ),
        ],
        "screen capture sources",
        imza="oa{sv}",
        zaman_asimi=zaman_asimi,
    )
    onay.dogrula("screen capture sources")


def pipewire_fd_al(tasiyici: Tasiyici, oturum: str) -> int:
    """`OpenPipeWireRemote` — yerel fd'yi döner.

    Dönen fd bu sürece ait: `kapat()` kapanışında `os.close` ile
    bırakılıyor. (dbus-next'te fd sızıntısı bildirilmiş; bizim tarafımızda
    tek fd var, kapanışta tek yerde bırakılıyor.)
    """
    _, govde, _ = tasiyici.cagir(
        PORTAL_ADI,
        PORTAL_YOLU,
        ARAYUZ_EKRAN,
        "OpenPipeWireRemote",
        "oa{sv}",
        [oturum, {}],
        zaman_asimi=HIZLI_ZAMANI,
    )
    if not govde or not isinstance(govde[0], int) or govde[0] < 0:
        raise PortalHatasi("OpenPipeWireRemote returned no usable file descriptor")
    return govde[0]


@dataclass
class EkranOturumu:
    """Tek başına ScreenCast oturumu: izin → akışlar → PipeWire fd.

    Ardından **kare alınamıyor** — bkz. `YakalamaYokHatasi`. Nesne bu yüzden
    "hazır" durumunu ve fd'yi taşıyor, görüntüyü değil.
    """

    tasiyici: Tasiyici
    oturum_yolu: str = ""
    akinlar: list[Akin] = field(default_factory=list)
    pipewire_fd: int | None = None
    imlec_kipi: int = IMLEC_GOMULU

    @classmethod
    def ac(
        cls,
        tasiyici: Tasiyici,
        zaman_asimi: float = VARSAYILAN_ONAY_ZAMANI,
        imlec_istenen: int = IMLEC_GOMULU,
    ) -> "EkranOturumu":
        """Dört adımı sırayla koşturur. Her adımda ret/süre aşımı yükselir."""
        oturum = cls(tasiyici=tasiyici)

        oturum.oturum_yolu = oturum_ac(tasiyici, zaman_asimi)
        try:
            oturum.imlec_kipi = imlec_kipi_sec(tasiyici, imlec_istenen)
            kaynaklari_sec(tasiyici, oturum.oturum_yolu, oturum.imlec_kipi, zaman_asimi)
            jet = jeton("baslat")
            beklenen = istek_yolu(tasiyici, jet)
            _, govde, _ = tasiyici.cagir(
                PORTAL_ADI,
                PORTAL_YOLU,
                ARAYUZ_EKRAN,
                "Start",
                "osa{sv}",
                [oturum.oturum_yolu, "", secenekler(handle_token=jet)],
                zaman_asimi=HIZLI_ZAMANI,
            )
            istek = govde[0] if govde else beklenen
            onay = yanit_bekle(tasiyici, istek, "screen capture start", zaman_asimi)
            sonuclar = onay.dogrula("screen capture start")
            oturum.akinlar = akinlari_coz(sonuclar)
            oturum.pipewire_fd = pipewire_fd_al(tasiyici, oturum.oturum_yolu)
        except Exception:
            oturum.kapat()
            raise
        return oturum

    @property
    def hazir(self) -> bool:
        """Oturum kuruldu ve fd alındı mı. Kare alınabilir demek DEĞİL."""
        return bool(self.oturum_yolu) and self.pipewire_fd is not None

    def grab(self, display=None):
        """`ScreenCapture.grab` sözleşmesini taşır, ama uygulanmadı.

        Bilerek bu isim: dikiş ekran yakalamayı buradan istiyor ve hata
        mesajı tam olarak nerede durduğumuzu söylüyor.
        """
        raise YakalamaYokHatasi(
            "The portal screen cast session is prepared "
            f"(session={self.oturum_yolu!r}, streams={len(self.akinlar)}, "
            f"pipewire_fd={'yes' if self.pipewire_fd is not None else 'no'}) "
            "but converting PipeWire frames into images is not implemented "
            "in this build. Screen capture on Wayland is unavailable; use an "
            "X11 session for full screen control, or the window-scoped "
            "capture path if the desktop exposes one."
        )

    def kapat(self) -> None:
        """Oturumu ve fd'yi bırakır. Sıra önemli: önce portal, sonra fd."""
        if self.oturum_yolu:
            oturum_kapat(self.tasiyici, self.oturum_yolu)
            self.oturum_yolu = ""
        if self.pipewire_fd is not None:
            try:
                os.close(self.pipewire_fd)
            except OSError:
                pass
            self.pipewire_fd = None
        self.akinlar = []