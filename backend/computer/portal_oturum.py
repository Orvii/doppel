"""Portal oturum akışı — istek/yol matematiği ve onay semantiği.

ScreenCast ve RemoteDesktop aynı üç adımlı akışı paylaşıyor:

    CreateSession → SelectSources/SelectDevices → Start

Üçünün de dönüşü bir **istek yolu** (`handle`); gerçek sonuç o nesnenin
`Request::Response` sinyalinde geliyor. Onay diyaloğu da burada açılıyor —
yani portal çağrılarının hepsi kullanıcı cevap verene kadar **bekleyebilir**
ve **reddedilebilir**.

## Yarış: sinyal, çağrıdan önce mi sonra mı

İstek yolu bizim `handle_token`'ımızdan ve bağlantının tekil adından
türetiliyor:

    /org/freedesktop/portal/desktop/request/<tekil_ad>/<handle_token>

Tekil adı portal tarafından atanıyor ve **ilk bağlantıda** boş olabiliyor;
bu yüzden yolu çağrıdan önce **hesaplıyoruz** ama çağrıdan sonra, dönen
`handle` ile karşılaştırıyoruz. Uyuşursa kuyruk zaten doğru yolda; uyuşmazsa
(eski portal sürümü) dönen yolu kullanıyoruz. Eski sürümlerde sinyal,
abonelik kurulmadan gelebilir; bu pencere kapatılamıyor ve gerçek portal
kadar eski bir yarış — akış süre aşımına düşer, asılı kalmaz.

## Onay bir güvenlik özelliği, engel değil

Kullanıcı diyaloğu **görüyor ve ne istendiğini biliyor**; biz istemeden
ekran paylaşılmıyor. Karşılığında her bekleyişin bir tavanı var:
`Onay` nesnesi zaman aşımını `PortalZamanAsimi`'ne çevirir. "Henüz cevap
yok" ile "evet" asla karıştırılmaz — kapının `True` gördüğü tek şey
`response == 0`.

Zaman aşımı varsayılanı cömert (120 s): diyalog bir **insan hızında**
cevaplanıyor, otomatik bir sistem değil. Ama sınırsız değil.
"""

from __future__ import annotations

import secrets

from .portal_tasiyici import (
    PORTAL_ADI,
    PORTAL_YOLU,
    PortalHatasi,
    PortalZamanAsimi,
    SecenekDegeri,
    Tasiyici,
)

#: Onay diyaloğunun başında beklenen varsayılan süre (saniye).
VARSAYILAN_ONAY_ZAMANI = 120.0

#: Hızlı çağrılar (onturum adımları, Notify* girdileri) için tavan.
HIZLI_ZAMANI = 10.0

#: Request::Response kodları. Ayrıştırma tek yerde; akışlar metne çevirir.
YANIT_BASARILI = 0
YANIT_VAZGECILDI = 1
YANIT_BASKA_TURLU = 2

#: Portal arayüzleri, adları tek yerde.
ARAYUZ_OTURUM = "org.freedesktop.portal.Session"
ARAYUZ_ISTEK = "org.freedesktop.portal.Request"
ARAYUZ_EKRAN = "org.freedesktop.portal.ScreenCast"
ARAYUZ_GIRDI = "org.freedesktop.portal.RemoteDesktop"


def jeton(onek: str = "doppel") -> str:
    """İstek yolu öğesi: her çağrıda taze, tahmin edilemez.

    Portal dokümanı istiyor (tahmin edilemezlik); ayrıca sabit jetonla aynı
    akışta ikinci bir çağrı, ilk isteğin yolunu yeniden kurardı.
    """
    return f"{onek}_{secrets.token_hex(8)}"


def istek_yolu(tasiyici: Tasiyici, jet: str) -> str:
    """Çağrıdan önce hesaplanmış istek yolu.

    Portal dokümanındaki kural: tekil addaki `:` düşüyor, `.` `_` oluyor.
    """
    ad = tasiyici.benzersiz_ad().lstrip(":").replace(".", "_")
    return f"/org/freedesktop/portal/desktop/request/{ad}/{jet}"


def secenekler(**anahtarlar: SecenekDegeri | str | int | bool) -> dict:
    """`a{sv}` sözlüğü kurar; düz değerler türünden çıkarılarak sarılır.

    Kolaylık yüzünden: `handle_token="x"` yazmak, elle `SecenekDegeri("s",
    "x")` yazmaktan okunur. Açıkça tür isteyen çağrılar `SecenekDegeri`
    verir (örneğin bit maskeleri: `types=SecenekDegeri("u", 1)`).
    """
    sozluk: dict[str, SecenekDegeri] = {}
    for anahtar, deger in anahtarlar.items():
        if isinstance(deger, SecenekDegeri):
            sozluk[anahtar] = deger
        elif isinstance(deger, bool):
            sozluk[anahtar] = SecenekDegeri("b", deger)
        elif isinstance(deger, int):
            sozluk[anahtar] = SecenekDegeri("u", deger)
        elif isinstance(deger, str):
            sozluk[anahtar] = SecenekDegeri("s", deger)
        else:
            raise PortalHatasi(f"Unsupported option value for {anahtar!r}: {deger!r}")
    return sozluk


class Onay:
    """`Request::Response` sonucunu insan-okur bir karara çevirir.

    Tek yerde: kod 0 dışındaki her şey başarısızlık ve hangisi olduğunu
    söyleyen ayrı mesajlar var. "Vazgeçildi" ile "cevapsız kaldı" farklı
    şeyler — biri bilinçli bir ret, diğeri sorunun kendisi; aracı okuyan
    insan da modeli de bunu ayırt edebilmeli.
    """

    def __init__(self, kod: int, sonuclar: dict) -> None:
        self.kod = kod
        self.sonuclar = sonuclar

    @property
    def basarili(self) -> bool:
        return self.kod == YANIT_BASARILI

    def dogrula(self, ne: str) -> dict:
        """Başarılıysa sonuçları döner; değilse açık hata yükseltir."""
        if self.kod == YANIT_BASARILI:
            return self.sonuclar
        if self.kod == YANIT_VAZGECILDI:
            raise PortalHatasi(
                f"The user denied the portal request for {ne} (consent dialog "
                "was declined)"
            )
        raise PortalHatasi(
            f"The portal request for {ne} ended in an unexpected way "
            f"(response code {self.kod})"
        )


def yanit_bekle(
    tasiyici: Tasiyici, istek: str, ne: str, zaman_asimi: float = VARSAYILAN_ONAY_ZAMANI
) -> Onay:
    """İsteğin sinyalini bekler ve `Onay`'a çevirir.

    Zaman aşımı burada da açık hata: diyalog hâlâ açıkken akış devam edemez.
    """
    try:
        kod, sonuclar = tasiyici.bekle_yanit(istek, zaman_asimi)
    except PortalZamanAsimi as hata:
        raise PortalZamanAsimi(
            f"Timed out waiting for the consent dialog of {ne}: {hata}"
        ) from None
    return Onay(kod, sonuclar)


def cagir_ve_bekle(
    tasiyici: Tasiyici,
    arayuz: str,
    uye: str,
    govde: list,
    ne: str,
    imza: str = "a{sv}",
    zaman_asimi: float = VARSAYILAN_ONAY_ZAMANI,
) -> Onay:
    """Anahtarlı portal çağrısı: dönen isteği doğrular, sonucunu bekler.

    Kısayol; CreateSession/SelectSources/SelectDevices/Start hep bu şekli
    kullanıyor. Çağrı dönüşü `o` (istek yolu) — beklenen yolla karşılaştırma
    `istek_yolu` dokümantasyonundaki gerekçeyle burada yapılıyor.
    """
    _, govde_donus, _ = tasiyici.cagir(
        PORTAL_ADI, PORTAL_YOLU, arayuz, uye, imza, govde, zaman_asimi=HIZLI_ZAMANI
    )
    if not govde_donus:
        raise PortalHatasi(f"{arayuz}.{uye} returned no request handle")
    istek = govde_donus[0]
    return yanit_bekle(tasiyici, istek, ne, zaman_asimi)


def oturum_kapat(tasiyici: Tasiyici, oturum_yolu: str) -> None:
    """Oturumu kapatır. Hata yutuluyor: kapanış çabası akışı düşürmemeli.

    Portal oturumu zaten kapanmışsa `Close` çağrısı hata veriyor; bu, temizlik
    yolunda anlamlı bir bilgi değil.
    """
    try:
        tasiyici.cagir(
            PORTAL_ADI, oturum_yolu, ARAYUZ_OTURUM, "Close", "", [], zaman_asimi=HIZLI_ZAMANI
        )
    except PortalHatasi:
        pass