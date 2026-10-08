"""Yan masanın iki arka ucunun paylaştığı zemin.

Windows arka ucu masaüstü nesnesi (`CreateDesktopW`), X11 arka ucu ikinci
bir X ekranı (`Xvfb`/`Xephyr`). İkisi de birer "yan masa" ve dışarıdan
bakan için tek bir ajan var; o yüzden pencere kaydı, hata türü ve yan
masanın orada olduğunun işareti tek yerde duruyor.

Arka uç seçimi de burada: `yan_masa_kur`. Kararı `erisim.masa_sec`
veriyor (platform dallanması yalnızca orada yaşar); buradaki fabrika
kararı somut sınıfa çeviriyor ve içe aktarmaları tembel tutuyor —
Linux'ta Win32 modülünün kurulmasına gerek yok.

## Gösterge kaydı neden var

`mesaj.py` ve `kayit.py` çağıranları masaüstünü hiç bilmiyor: girdi
`Girdi()` ile kuruluyor, kayıt `EkranKaydi()` ile — ikisi de yan masa
açılmadan önce, hatta (kayıt) süreç başında. Windows'ta sorun değil:
hedef her zaman bir HWND ve masaüstü çağrı anında seçiliyor. X11'de
hedef ekran `DISPLAY=:n`, yani **yan masa açılırken** belirlenen bir
şey ve input/kayıt katmanının onu bir yerden öğrenmesi gerekiyor.

Kayıt bu yüzden var: yan masayı açan tek bir örnek var (`Calisma`,
`masaustu.py` başlığındaki tek örnek kararı) ve açılışta göstergeyi
buraya yazıyor. Girdi ve kayıt çağrı anında buradan okuyor. Alternatif
`Girdi(x_goster=...)` diye parametre taşımak olurdu, ama `dispatch.py`
`Girdi()` kuruyor ve masaüstü açılışından önce kuruyor — enum'u herkese
taşımak yerine tek bir kayıt noktası daha dürüst.

## Ortam yalıtımı

Yan masaya doğurulan her süreç `DISPLAY=:n` alıyor ve
`WAYLAND_DISPLAY` **siliniyor** (varsa). Sebep ölçülmüş bir sınıf hata:
Wayland oturumunda ana oturumdan miras kalan `WAYLAND_DISPLAY`,
Chromium'un X11 yerine Wayland'ı seçmesine yetiyor — uygulama yan
ekranda açılacakken kullanıcının kendi oturumuna bağlanıyor. Miras
tesadüf değil, seçim olmalı: yan masaya giden çocuk sadece yan masayı
görüyor.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Mapping
from dataclasses import dataclass

#: `Frame.display_index` bu değerdeyse kare fiziksel bir monitörden
#: değil, ajanın kendi masasından geliyor.
GIZLI_EKRAN = -1

#: Yakalamaya değer bulunan en küçük pencere. Chromium tek sekme için
#: bir düzine minik yardımcı pencere açıyor ve onlar listede gürültüden
#: başka bir şey değil. İki arka uçta da aynı süzgeç: farklı olsaydı
#: aynı uygulama iki platformda farklı pencere listesi verirdi.
ASGARI_EN, ASGARI_BOY = 200, 120


class MasaustuHatasi(RuntimeError):
    """Yan masa açılamadı ya da içine süreç doğurulamadı."""


@dataclass(frozen=True)
class Pencere:
    """Yan masadaki bir üst düzey pencere.

    `hwnd` adı Windows'tan geliyor; X11'de içi bir X pencere kimliği
    (`Window`). Modelin gördüğü sözleşme aynı kalsın diye ad değişmedi —
    `side_windows` çıktısı ve `side_act`in beklediği alan iki platformda
    da `hwnd`.
    """

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


# --- gösterge kaydı -----------------------------------------------------

_kilit = threading.Lock()
_gosterge: str | None = None
_oturum: object | None = None


def yan_kaydet(gosterge: str, oturum: object | None = None) -> None:
    """Yan masanın açıldığını ve hangi ekranda olduğunu kaydeder.

    `oturum`, X11 arka ucunun ekran bağlantısı; Windows `None` geçiyor
    (orada ekran diye bir şey yok). Tip `object`: bu modül X11'in
    tiplerini hiç bilmiyor, taşıyor.
    """
    global _gosterge, _oturum
    with _kilit:
        _gosterge, _oturum = gosterge, oturum


def yan_birak() -> None:
    """Yan masa kapandı. Girdi ve kayıt artık hedefsiz."""
    global _gosterge, _oturum
    with _kilit:
        _gosterge, _oturum = None, None


def aktif_gosterge() -> str | None:
    """Açık yan masanın ekran adı (`":99"`), açık masa yoksa `None`."""
    with _kilit:
        return _gosterge


def aktif_oturum() -> object | None:
    """Açık yan masanın X11 ekran bağlantısı, yoksa `None`."""
    with _kilit:
        return _oturum


def yan_ortam(gosterge: str, temel: Mapping[str, str] | None = None) -> dict[str, str]:
    """Yan masaya giden çocuk süreçlerin ortamı.

    `DISPLAY` yazılıyor ve `WAYLAND_DISPLAY` siliniyor — neden, modül
    başlığında: ana oturumdan miras kalan Wayland işareti, çocuğun yan
    ekranı değil kullanıcının oturumunu seçmesine yetiyordu.
    """
    ortam = dict(os.environ if temel is None else temel)
    ortam["DISPLAY"] = gosterge
    ortam.pop("WAYLAND_DISPLAY", None)
    return ortam


# --- arka uç seçimi -----------------------------------------------------

#: Ajanın yan masaüstünün adı (Windows'ta `CreateDesktopW` adı).
YAN_AD = "ajan-calisma"


def _masaustu_sinifi():
    """Windows arka ucu. Yalnızca gerçekten Windows'ta içe aktarılır."""
    from .masaustu import Calisma

    return Calisma


def _yan_sinifi():
    """X11 arka ucu — her Linux'ta, oturum türünden bağımsız."""
    from .masaustu_x11 import Calisma as YanCalisma

    return YanCalisma


def yan_masa_kur(ortam: Mapping[str, str] | None = None) -> object:
    """Yan masa arka ucunu seçip kurar. `Calisma` sözleşmesi: `ac` +
    `kapat` + `pencereler` + `yakala` + `baslat`."""
    from . import erisim

    secim = erisim.masa_sec(ortam)
    if secim.ad == "win32":
        return _masaustu_sinifi()(YAN_AD)
    return _yan_sinifi()(YAN_AD)
