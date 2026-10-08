"""Ajanın masaüstünün canlı görüntüsü.

`side_capture` tek bir pencereyi, tek bir anda, modele göndermek için
yakalıyor. Bu modül başka bir soruyu cevaplıyor: **o masaüstünde şu anda ne
oluyor.** Bütün pencereler, yerleriyle, üst üste binme sıralarıyla ve
ajanın imlecinin nerede olduğuyla birlikte.

İkisi ayrı kalmak zorunda. Modele giden kare pahalı ve seyrek: her biri
~1500 görsel token ve ajan zaten nereye tıkladığını biliyor. Buradaki
kare bedava (tokenı yok) ve sık: saniyede sekiz kez, çünkü onu okuyan
insan ve insan "bir şey oluyor mu" sorusunu sürekli soruyor.

## Neden istemci alanı kırpılıyor

`PrintWindow` pencerenin tamamını veriyor, Windows'un başlık çubuğu dahil.
O kare Mint görünümlü bir çerçeveye konunca iki başlık üst üste geliyor.
İstemci alanı kırpılınca içeride yalnızca uygulamanın kendi arayüzü
kalıyor ve çerçeveyi biz çiziyoruz.

## Ölçüldü

1100x760 bir Chrome penceresi: kare başına 54 ms, yani tek pencerede
~18 fps. `pencereler()` 0.14 ms — sayılmayacak kadar ucuz. Arayüz sekiz
kareye ayarlı; kalan pay bilerek bırakıldı, çünkü bu iş ajanın kendi
çalışmasıyla aynı makinede dönüyor.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .masaustu import Calisma, istemci_kutusu, pencere_bilgisi

#: Bir karede en fazla kaç pencere yakalanıyor. Chromium tek sekme için
#: bir düzine yardımcı pencere açıyor; büyüklük süzgeci çoğunu eliyor ama
#: bir üst sınır olmadan kare bütçesi bir uygulamanın eline kalıyor.
SINIR = 4


@dataclass(frozen=True)
class PencereKaresi:
    """Bir pencerenin o andaki içeriği ve masaüstündeki yeri."""

    hwnd: int
    baslik: str
    sinif: str
    #: İstemci alanının masaüstü koordinatındaki yeri.
    x: int
    y: int
    en: int
    boy: int
    #: RGB888, `en * boy * 3` bayt. Qt'ye ham veriliyor: PNG'ye çevirmek
    #: saniyede sekiz kez sıkıştırma demek ve gösterilecek yer zaten aynı
    #: makinedeki bir pencere.
    ham: bytes


@dataclass(frozen=True)
class MasaKaresi:
    """Masaüstünün tamamı: pencereler, imleç, iz."""

    #: Arkadan öne sıralı. En sondaki en üstte.
    pencereler: list[PencereKaresi] = field(default_factory=list)
    imlec: tuple[int, int] = (0, 0)
    iz: list[tuple[int, int]] = field(default_factory=list)
    tik: bool = False
    #: Masaüstünün mantıksal boyutu — pencereler bunun içine yerleşiyor.
    alan: tuple[int, int] = (1920, 1080)
    #: Ajanın en son dokunduğu pencere. Bakan kişinin ilk sorusu bu.
    etkin: int = 0

    @property
    def bos(self) -> bool:
        return not self.pencereler


def masayi_oku(calisma: Calisma | None, girdi=None, alan=(1920, 1080),
               etkin: int = 0, sinir: int = SINIR) -> MasaKaresi:
    """Masaüstünün o anki hâlini okur.

    Hiçbir hata yukarı çıkmıyor ve bu bilinçli: bu döngü saniyede sekiz kez
    dönüyor ve ajan tam o sırada `side_close` çağırıp masaüstünü kapatabilir.
    O yarışta kaybeden pencere kareden düşüyor, sonraki karede zaten yok.
    Canlı bir görüntünün bir kare kaçırması olağan; uygulamayı düşürmesi
    değil.
    """
    if calisma is None:
        return MasaKaresi(alan=alan)
    try:
        pencereler = calisma.pencereler()
    except Exception:
        return MasaKaresi(alan=alan)

    # Arka ucun kendi okuma metotları tercih ediliyor: X11'de
    # `istemci_kutusu` (0,0,en,boy) ve pencere bilgisi hedef ekranı
    # bilmek zorunda (çağrı `DISPLAY=:n` ile gidiyor); Windows'ta
    # metotlar modül fonksiyonlarına devrediyor, davranış aynı.
    kutu_oku = getattr(calisma, "istemci_kutusu", None) or istemci_kutusu
    bilgi_oku = getattr(calisma, "pencere_bilgisi", None) or pencere_bilgisi

    kareler: list[PencereKaresi] = []
    # `EnumDesktopWindows` üstten alta veriyor; çizim alttan üste olacak.
    for p in reversed(pencereler[:sinir]):
        try:
            dx, dy, en, boy = kutu_oku(p.hwnd)
            if en <= 0 or boy <= 0:
                continue
            kare = calisma.yakala(p.hwnd)
            gorsel = kare.image.crop((dx, dy, dx + en, dy + boy))
            taze = bilgi_oku(p.hwnd)
            kareler.append(PencereKaresi(
                hwnd=p.hwnd, baslik=taze.baslik, sinif=taze.sinif,
                x=taze.x + dx, y=taze.y + dy, en=en, boy=boy,
                ham=gorsel.tobytes(),
            ))
        except Exception:
            continue

    imlec = (0, 0)
    iz: list[tuple[int, int]] = []
    tik = False
    if girdi is not None:
        imlec = (girdi.imlec.x, girdi.imlec.y)
        iz = list(girdi.iz)
        tik = bool(girdi.son_tik)
    return MasaKaresi(pencereler=kareler, imlec=imlec, iz=iz, tik=tik,
                      alan=alan, etkin=etkin)
