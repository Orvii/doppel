"""Ajanın imleci — karenin üstüne çizilen ok. Saf PIL, platform yok.

Buradaki tek karar imlecin **görünüşü** ve o da platformdan bağımsız:
ok ajanın rengini taşıyor, koyu bir kılıf içinde ve arkasında iz
bırakıyor. Nedenleri `imlec_ciz`in docstring'inde, ölçümleriyle.

Modül `masaustu.py`'den ayrıldı çünkü artık iki arka uç var (Win32
masaüstü nesnesi ve X11 yan ekranı) ve ikisi de aynı oku çiziyor.
Çizim kopyalansaydı iki arka ucun kareleri bir süre sonra birbirinden
ayrı görünürdü — kullanıcı için tek bir ajan var, tek bir imleç olmalı.

`GIZLI_EKRAN` bilerek burada değil: o karenin nereden geldiğinin
işareti ve `capture.Frame`in kavramı.
"""

from __future__ import annotations

from collections.abc import Sequence

from PIL import Image, ImageDraw

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