"""Xvfb/Xephyr yaşam döngüsü — yan ekranın kendisi.

Yan masa X11'de ikinci bir X ekranıdır: `Xvfb :99` (görünmez) ya da
`Xephyr :99` (kullanıcının ekranında iç içe bir pencere). Uygulamalar
`DISPLAY=:99` ile oraya doğar ve orada olan biten ana oturumda görünmez.

## Neden bu, "Linux'ta masaüstü nesnesi"nin karşılığı

Windows'ta `CreateDesktopW` işletim sisteminin kendi masaüstü nesnesini
kullanıyordu. X11'de karşılığı **ayrı bir X sunucusu**: pencere listesi,
odak zinciri ve imleci ana oturumdan tamamen bağımsız. Bu seçim
oturum türünü hiç sormuyor — Xvfb bir süreç, makinenin kendi oturumu
Wayland de olsa, hiç ekran olmasa da (headless) çalışır. Yani yan masa
X11'in kurulu olduğu bir host şartı değil; yan ekran **bizim** ve X11
olması tasarımın kendisi.

## Bağımlılık kararı (tek satır)

Yeni Python bağımlılığı yok: Xvfb/Xephyr alt süreç, yakalama mevcut
`mss`in `display=:` parametresiyle. Doğrulandı — mss 10.1.0'da `display`
kwarg'ı yalnızca Linux'ta anlamlı ve `XOpenDisplay`e geçiyor.

## Ekran numarası dağıtımı

`gosterge_sec` 99'dan başlayıp ilk boş numarayı veriyor. Dolu sayılma
ölçütü soket (`/tmp/.X11-unix/Xn`) **veya** kilit dosyası (`/tmp/.Xn-lock`)
varlığı: sert öldürülmüş bir sunucu geride kilit bırakabiliyor ve o
numarayı yeniden kullanmak "açıldı ama bağlanamıyorum" hata sınıfını
doğuruyor. Yanlış tarafa düşen hata, numara atlamaktır; ucuz.

## Kimlik doğrulama

Sunucu `-auth` olmadan başlıyor; o durumda boş yetkilendirme kabul
ediliyor ve ana oturumun `XAUTHORITY` dosyasında `:99` girdisi olmadığı
için istemciler yetkilendirmesiz bağlanıyor. `-ac` (erişim denetimini
tamamen kapat) bilerek konmadı: yan ekran başka kullanıcılara da açık
kalırdı ve buna gerek yok.

## Ölçülmedi

Bu modül Windows'ta yazıldı; Linux koşusu CI'da (ubuntu + Xvfb) yeşile
dönerken ölçülecek. Burada doğrulanan şey saf mantık: argv, numara
dağıtımı, hata yolları.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass

from .masaustu_ortak import MasaustuHatasi

#: Varsayılan ekran ölçüsü. Derinlik 24: mss'nin okuduğu ZPIXMAP yolu ve
#: ffmpeg x11grab uçları 24 bit varsayıyor.
VARSAYILAN_OLCU = "1920x1080x24"

#: Numara aralığı. 99, `xvfb-run`un ve CI alışkanlıklarının başladığı yer;
#: gerçek oturumlar genelde :0–:2'de ve onlara çarpmıyoruz.
ILK_GOSTERGE = 99
SON_GOSTERGE = 199

#: Sunucunun soketi bırakması için beklenecek süre. Xvfb normalde
#: yüz milisaniyeler içinde hazır oluyor; 8 saniye yavaş makineler için
#: cömert bir sınır, takılı kalmaya karşı da üst sınır.
HAZIR_SANIYE = 8.0

SOKET_DIZIN = "/tmp/.X11-unix"

#: Tur adı -> eksik olduğunda söylenecek paket. Hata metni kullanıcıya
#: "ne kuracağım?" sorusunun cevabını vermek zorunda; "bulunamadı"
#: tek başına eyleme dönüşmüyor.
KURULUM = {
    "xvfb": "apt install xvfb (or your distro's xvfb package)",
    "xephyr": "apt install xserver-xephyr (or your distro's xephyr package)",
}


def komut_kur(tur: str, gosterge: str, olcu: str = VARSAYILAN_OLCU) -> list[str]:
    """Sunucunun argv'si. Saf: hiçbir şey çalıştırmaz, test edilebilir.

    `-noreset` kasıtlı: son istemci ayrıldığında sunucu sıfırlanıp
    pencereleri düşürürdü; yan masada tek pencereyle çalışan bir ajanın
    başka pencere açtığında masayı boş bulması sürpriz olurdu.
    `-nolisten tcp` yan ekranı ağa açmıyor.
    """
    if tur == "xvfb":
        return ["Xvfb", gosterge, "-screen", "0", olcu, "-noreset",
                "-nolisten", "tcp"]
    if tur == "xephyr":
        # Xephyr ana oturumun içine yerleşiyor; üst ekran `DISPLAY`ten
        # miras alınıyor (ana süreçte değiştirilmiyor, yalnızca bu
        # çocuğa geçiyor). Görünür yan ekran isteyen kullanıcı için.
        return ["Xephyr", gosterge, "-screen", olcu, "-noreset",
                "-nolisten", "tcp"]
    raise MasaustuHatasi(f"unknown X server kind: {tur!r}")


def soket_yolu(gosterge: str) -> str:
    """`":99"` -> `"/tmp/.X11-unix/X99"`."""
    return f"{SOKET_DIZIN}/X{gosterge.lstrip(':')}"


def kilit_yolu(gosterge: str) -> str:
    return f"/tmp/.X{gosterge.lstrip(':')}-lock"


def mesgul_gosterge(gosterge: str, var: Callable[[str], bool] = os.path.exists) -> bool:
    """Bu numarada çalışan bir sunucu var mı.

    Soket ya da kilit dosyasından biri yeterli. `var` enjekte edilebilir:
    testler dosya sistemine dokunmadan bu kararı sürebilsin diye.
    """
    return var(soket_yolu(gosterge)) or var(kilit_yolu(gosterge))


def gosterge_sec(mesgul: Callable[[str], bool] = mesgul_gosterge,
                 baslangic: int = ILK_GOSTERGE,
                 son: int = SON_GOSTERGE) -> str:
    """İlk boş ekran numarası, `":n"` olarak. Doluysa sonrakine geçer."""
    for n in range(baslangic, son + 1):
        gosterge = f":{n}"
        if not mesgul(gosterge):
            return gosterge
    raise MasaustuHatasi(
        f"every display from :{baslangic} to :{son} is taken; close some X "
        "servers or raise the range."
    )


def bulucu_var(tur: str, bulucu: Callable[[str], object]) -> bool:
    return bulucu("Xvfb" if tur == "xvfb" else "Xephyr") is not None


def tur_sec(bulucu: Callable[[str], object] = shutil.which) -> str:
    """Xvfb varsa o, yoksa Xephyr, ikisi de yoksa açık hata.

    Sıra bu: Xvfb headless makinelerde de çalışır, Xephyr ise ana
    oturumda bir X ekranı şart koşar (içine yerleşecek bir pencere
    sistemi yoksa açılamaz). Yani Xephyr ancak Xvfb yokken bir kazanç;
    asıl taşıyıcı Xvfb.
    """
    if bulucu_var("xvfb", bulucu):
        return "xvfb"
    if bulucu_var("xephyr", bulucu):
        return "xephyr"
    raise MasaustuHatasi(
        "Neither Xvfb nor Xephyr was found on PATH; the side desk needs its "
        "own X display. Install one: " + " or ".join(KURULUM.values()) + "."
    )


@dataclass
class Ekran:
    """Çalışan bir X sunucusu. `surec` testlerde sahtelenebilir bir yüzey."""

    gosterge: str
    tur: str
    surec: object

    def durdur(self, bekleme: float = 3.0) -> None:
        """Sunucuyu nazikçe durdurur; cevap vermezse öldürür."""
        if self.surec.poll() is not None:
            return
        self.surec.terminate()
        try:
            self.surec.wait(timeout=bekleme)
        except subprocess.TimeoutExpired:
            self.surec.kill()
            try:
                self.surec.wait(timeout=bekleme)
            except subprocess.TimeoutExpired:
                # Buraya düşen sunucu canlı kalıyor; yan masayı kapatma
                # yolunda daha fazla beklemek kapanışı geciktirmekten
                # başka bir şey yapmaz.
                pass


def _varsayilan_dogurucu(argv: list[str]):
    """Sunucuyu başlatır. Çıktı yutuluyor: Xvfb stderr'e konuşuyor.

    Ortam **burada değiştirilmiyor** (Xephyr üst `DISPLAY`i ister);
    yan ekranın ortamı yalnızca o ekrana doğan çocuklara veriliyor —
    `masaustu_x11` başlığındaki yalıtım kuralı.
    """
    return subprocess.Popen(
        argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        start_new_session=True,
    )


def hazir_bekle(gosterge: str, surec, zaman_asimi: float = HAZIR_SANIYE,
                uyku: Callable[[float], None] = time.sleep,
                saat: Callable[[], float] = time.monotonic,
                var: Callable[[str], bool] = os.path.exists) -> None:
    """Soket görünene kadar bekler. Ölen ya da takılan sunucu hata verir.

    Beklerken süreç ölürse stderr'in son satırları hataya konuyor;
    "açılmadı" demek, nedenini söylememek olurdu.
    """
    son = saat() + zaman_asimi
    while saat() < son:
        if surec.poll() is not None:
            raise MasaustuHatasi(
                f"{gosterge}: the X server exited while starting up"
                + _stderr_kuyrugu(surec)
            )
        if var(soket_yolu(gosterge)):
            return
        uyku(0.05)
    raise MasaustuHatasi(
        f"{gosterge}: the X server did not come up within {zaman_asimi:.0f}s"
        + _stderr_kuyrugu(surec)
    )


def _stderr_kuyrugu(surec) -> str:
    akis = getattr(surec, "stderr", None)
    if akis is None:
        return ""
    try:
        ham = akis.read() or b""
    except Exception:
        return ""
    metin = ham.decode("utf-8", "replace").strip()
    return f": {metin[-300:]}" if metin else ""


def baslat(tur: str | None = None, olcu: str = VARSAYILAN_OLCU,
           mesgul: Callable[[str], bool] | None = None,
           bulucu: Callable[[str], object] = shutil.which,
           dogurucu: Callable[[list[str]], object] | None = None,
           hazir: Callable[[str, object], None] | None = None) -> Ekran:
    """Boş numaraya bir X sunucusu açar. Hata yolunda yarım sunucu kalmaz.

    Dört enjeksiyon noktası var — `bulucu`, `mesgul`, `dogurucu`, `hazir` —
    ve hepsi testler için: gerçek X sunucusuna, PATH'e ve dosya sistemine
    dokunmadan yaşam döngüsünün tamamı koşturulabilsin diye.
    """
    tur = tur or tur_sec(bulucu)
    gosterge = gosterge_sec(mesgul or mesgul_gosterge)
    argv = komut_kur(tur, gosterge, olcu)
    surec = (dogurucu or _varsayilan_dogurucu)(argv)
    bekle = hazir or (lambda g, s: hazir_bekle(g, s))
    try:
        bekle(gosterge, surec)
    except MasaustuHatasi:
        # Yarım açılmış sunucu arkada kalmamalı: sayı kullanılmış, soket
        # belki yazılmış — temizleyip hatayı olduğu gibi yukarı veriyoruz.
        try:
            Ekran(gosterge, tur, surec).durdur()
        except Exception:
            pass
        raise
    return Ekran(gosterge=gosterge, tur=tur, surec=surec)