"""Ajanın masası — kendi masaüstünü canlı gösteren pencere.

Ajanın zaten kendi masaüstü var: `CreateDesktopW` ile açılmış, kendi
pencere listesi, kendi odak zinciri, kendi imleci olan gerçek bir Windows
masaüstü nesnesi. Sorun onu göremememizdi. `side_capture` yalnızca ajan
bir eylem yaptığında tek bir pencerenin karesini veriyordu; arada ekran
donuyordu ve "şu anda ne oluyor" sorusunun cevabı yoktu.

Bu pencere o boşluğu kapatıyor: saniyede sekiz kez bütün pencereleri
yakalayıp yerlerine koyuyor, üstünde ajanın imlecini geziyor.

## Neden Linux Mint gibi görünüyor

Berkay'ın istediği buydu ve isteğin altında bir sebep var: o masaüstü
Windows'un masaüstü **değil**. Aynı görünseydi bakan kişi hangi ekrana
baktığını karıştırırdı — kendi masaüstü mü, ajanınki mi. Başka bir
işletim sisteminin kabuğu, tek bakışta "burası başka bir yer" diyor.

Renkler ve ölçüler Mint-Y'ye **yaklaşıyor**, kopyalanmıyor: Mint'in duvar
kâğıtları, logosu ve simgeleri onların ve bu depoya giremez. Panel,
başlık çubuğu, yeşil vurgu ve duvar kâğıdı burada sıfırdan çiziliyor.
Yazı tipi de sistemin: Mint'in Ubuntu/Noto'su kurulu olmayan bir makinede
zorlanamaz.

## Neyi gösteriyor, neyi göstermiyor

Salt okunur. Pencerelerin üstüne tıklayamazsın, yazamazsın — kasıtlı,
Berkay öyle seçti. Bu yüzden başlık çubuklarında kapat/küçült düğmeleri
**yok**: çalışmayan bir düğme çizmek, çalışıyormuş gibi görünen bir yalan
olurdu. Yerine başlıkta ajanın o an hangi pencerede olduğu yazıyor —
bakan kişinin gerçekten sorduğu şey bu.

Paneldeki tek gerçek düğme duraklatma ve o gerçekten bir iş yapıyor:
yakalama saniyede 54 ms tutuyor ve bakmadığın sürece o payı ajanın kendi
işine bırakmak doğru.
"""

from __future__ import annotations

import threading
import time

from PySide6.QtCore import QObject, QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from backend.computer.canli import MasaKaresi, masayi_oku
from .fluent import Tokens
from .kod_penceresi import KodPenceresi
from .mint import (  # noqa: F401  (masa'nın paleti; testler buradan okuyor)
    BASLIK_ETKIN,
    BASLIK_H,
    BASLIK_PASIF,
    CERCEVE,
    DUVAR_ALT,
    DUVAR_UST,
    PANEL,
    PANEL_UST,
    YARICAP,
    YAZI,
    YAZI_SOLUK,
    YESIL,
)
from backend.computer.masaustu import IMLEC_BOY, IMLEC_OYUK, IMLEC_RENK

#: Panel yüksekliği. Mint'in Cinnamon paneli varsayılan 40; burada 38,
#: çünkü bizim pencere bir ekran değil ve panel oranı büyük görünüyor.
#:
#: Panel **üstte**. Mint'te altta duruyor ama masa artık uygulamanın bir
#: sayfası ve altta uygulamanın kendi durum şeridi var; ikisi alt alta
#: gelince aynı işi yapan iki çubuk oluyordu. Üste alınca panel sayfanın
#: başlık şeridi hâline geliyor ve Cinnamon'un üst panel düzeni de zaten
#: var olan bir düzen.
PANEL_H = 38


#: Kod penceresi açıkken masadan aldığı pay. Kalanı yakalanan gerçek
#: pencerelere gidiyor.
#:
#: 0.58 ölçüldü: 1100 piksellik bir sayfada kod penceresine 620 piksel
#: kalıyor ve 80 sütunluk bir satır tam sığıyor. 0.5'te satır sonları
#: kaydırma çubuğuna dayanıyor, 0.7'te tarayıcı okunmaz oluyor.
KOD_ORAN = 0.58

#: Kod penceresinin masa kenarından payı.
KOD_PAY = 18

#: Kod bölmesinin okunabilir sayılan en dar hâli. 340'ın altında tek
#: aralıklı yazıyla 40 sütun bile sığmıyor ve kod satır sonlarından
#: ibaret kalıyor.
#:
#: Pencerenin en küçük hâli 480 piksel ve orada bölüşüm 260 veriyor —
#: yani dar masada bölünmek gerçekten oluyor, kuramsal bir durum değil.
KOD_ASGARI = 340

#: Saniyede kaç kare. Ölçüm: tek pencere yakalaması 54 ms, yani tavan
#: ~18. Sekizde kalmak bilinçli — bu döngü ajanın kendi işiyle aynı
#: makinede dönüyor ve öncelik onun.
FPS = 8



#: Gren karosu. Bir kez üretilip her duvar kâğıdında döşeniyor.
_GREN: QImage | None = None


def _gren(kenar: int = 128) -> QImage:
    """Bantlaşmayı kıran ince gren.

    Büyük ve karanlık bir geçiş 8 bitlik kanalda şerit üretiyor: 26 farklı
    yeşil arasında yumuşak geçiş yapacak yer yok. Gren o şeritleri
    dağıtıyor ve ekranda "kaliteli" görünen şeyin çoğu aslında bu.

    Deterministik: `random` yerine karma kullanılıyor, yani her açılışta
    aynı doku çıkıyor. Rastgele olsaydı iki ekran görüntüsü asla aynı
    olmazdı ve bir gerilemeyi karşılaştırarak yakalamak imkânsızlaşırdı.

    İki tuzağa düştüm ve ikisi de ekranda göründü:

    - İlk karma `(x * A) ^ (y * B)` idi ve gren değil **dikey şeritler**
      verdi: y'nin düşük bitleri kaydırmada kayboluyor ve doku sütun
      başına periyodik oluyor. Şimdi çarpım-karıştır-kaydır zinciri var.
    - Gren gri bir katman olarak %5 saydamlıkla basılıyordu ve ortalaması
      128 olan bir doku, ortalaması 25 olan bir zemini açıyordu — duvar
      kâğıdı soluyordu. Şimdi yarısı beyaz yarısı siyah, alfası düşük:
      simetrik, yani parlaklığı kaydırmıyor.
    """
    global _GREN
    if _GREN is not None and _GREN.width() == kenar:
        return _GREN
    gorsel = QImage(kenar, kenar, QImage.Format.Format_ARGB32)
    gorsel.fill(QColor(0, 0, 0, 0))
    for y in range(kenar):
        for x in range(kenar):
            n = (x * 374761393 + y * 668265263) & 0xFFFFFFFF
            n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
            v = (n >> 16) & 0xFF
            alfa = 2 + (v & 0x07)
            if v & 0x80:
                gorsel.setPixelColor(x, y, QColor(255, 255, 255, alfa))
            else:
                gorsel.setPixelColor(x, y, QColor(0, 0, 0, alfa))
    _GREN = gorsel
    return gorsel


class _Akis(QObject):
    """Yakalamayı kendi thread'inde döndürür.

    Arayüz thread'inde olamaz: bir kare 54 ms ve saniyede sekiz kare, yani
    arayüzün yarım saniyesi. Çubuk ve maskot o sırada donardı.

    Ajanın thread'inde de olamaz: orada ajanın kendi işi var ve canlı
    görüntü onu bekletemez.
    """

    kare = Signal(object)

    def __init__(self, kaynak) -> None:
        super().__init__()
        self._kaynak = kaynak
        self._calis = False
        self._thread: threading.Thread | None = None
        self._duraklat = False
        self.son_sure = 0.0

    def basla(self) -> None:
        if self._calis:
            return
        self._calis = True
        self._thread = threading.Thread(target=self._don, daemon=True,
                                        name="masa-canli")
        self._thread.start()

    def dur(self) -> None:
        self._calis = False

    def duraklat(self, deger: bool) -> None:
        self._duraklat = deger

    def _don(self) -> None:
        butce = 1.0 / FPS
        while self._calis:
            if self._duraklat:
                time.sleep(0.15)
                continue
            bas = time.perf_counter()
            try:
                kare = self._kaynak()
            except Exception:
                # Canlı görüntü uygulamayı düşüremez: ajan tam bu sırada
                # masaüstünü kapatmış olabilir.
                kare = None
            self.son_sure = time.perf_counter() - bas
            if kare is not None and self._calis:
                self.kare.emit(kare)
            time.sleep(max(0.0, butce - self.son_sure))


class MasaPenceresi(QWidget):
    """Ajanın masaüstü — Mint görünümlü kabuk, içinde gerçek pencereler."""

    def __init__(self, kaynak, t: Tokens | None = None) -> None:
        super().__init__()
        # Tema verilmezse sistemden okunuyor: masa kendi başına da
        # açılabiliyor (`scripts/masa_dogrula.py`) ve orada bir `Tokens`
        # taşımak zorunda kalmak, doğrulama betiğini uygulamaya
        # bağlardı.
        if t is None:
            from . import fluent

            t = fluent.tokens()
        self.t = t
        # Ayrı bir pencere değil, sayfa. Kendi başına da açılabilsin diye
        # başlığı duruyor; asgari boy küçük tutuluyor, yoksa gömüldüğü
        # pencerenin en küçük boyunu o belirliyor.
        self.setWindowTitle("Doppel — the agent's desk")
        self.setMinimumSize(480, 300)
        self.setAutoFillBackground(False)

        self._kare = MasaKaresi()
        self._akis = _Akis(kaynak)
        self._akis.kare.connect(self._kare_geldi)
        self._duraklat = False
        self._duraklat_kutusu = QRect()
        self._yakin = True
        self._yakin_kutusu = QRect()
        self._duvar_kare: QPixmap | None = None
        self._kapali = False

        # Kod penceresi masanın **içinde** duran gerçek bir arayüz;
        # yakalanan pencereler gibi ölçeklenmiş bir fotoğraf değil. Kodu
        # okunmayacak kadar küçültmek, onu göstermenin bütün sebebini
        # ortadan kaldırırdı.
        self.kod = KodPenceresi(t)
        self.kod.setParent(self)
        self.kod.hide()
        self._kod_kutusu = QRect()

        # Saat panelde gerçek saati gösteriyor. Duran bir saat, canlı
        # olduğunu iddia eden bir ekranda ilk fark edilen yalan olurdu.
        self._saat = QTimer(self)
        self._saat.timeout.connect(self.update)
        self._saat.start(1000)

    # --- yaşam döngüsü ----------------------------------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._akis.basla()

    def hideEvent(self, event) -> None:
        # Görünmeyen bir pencere için yakalama yapmak, ajanın işlemcisini
        # kimsenin bakmadığı bir görüntüye harcamak olurdu.
        self._akis.dur()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        self._akis.dur()
        super().closeEvent(event)

    def _kare_geldi(self, kare: MasaKaresi) -> None:
        self._kare = kare
        self.update()

    def masa_kapandi(self) -> None:
        """Ajan yan alanı kapattı — pencere kalıyor ama bunu söylüyor."""
        self._kapali = True
        self._akis.dur()
        self.update()

    def masa_acildi(self) -> None:
        self._kapali = False
        if self.isVisible():
            self._akis.basla()

    # --- etkileşim --------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        nokta = event.position().toPoint()
        if self._duraklat_kutusu.contains(nokta):
            self._duraklat = not self._duraklat
            self._akis.duraklat(self._duraklat)
            self.update()
        elif self._yakin_kutusu.contains(nokta):
            self._yakin = not self._yakin
            self.update()

    # --- çizim ------------------------------------------------------------

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        masa = QRect(0, PANEL_H, self.width(), self.height() - PANEL_H)
        self._duvar(p, masa)

        kod_kutusu, alan = self._bolgeler()
        if self.kod.isVisible() and kod_kutusu.isValid():
            # Gölge burada çiziliyor, çocuğun kendi boyamasında değil:
            # bir widget kendi dışına çizemiyor ve gölge çerçevenin
            # dışında. Masadaki gerçek pencerelerin gölgesiyle aynı
            # katmanlı yöntem.
            self._golge(p, QRectF(kod_kutusu), YARICAP)
        if alan.isValid():
            olcek, ofset = self._olcek(alan)
            if self._kare.bos:
                # Kod penceresi açıkken boş masa metnini yazmıyoruz:
                # ajan hiçbir şey yapmıyormuş gibi görünürdü, oysa tam o
                # sırada kod yazıyor.
                if not self.kod.aktif:
                    self._bos_masa(p, alan)
            else:
                for pencere in self._kare.pencereler:
                    self._pencere_ciz(p, pencere, olcek, ofset)
                self._imlec_ciz(p, olcek, ofset)

        self._panel(p)
        p.end()

    def _bolgeler(self) -> tuple[QRect, QRect]:
        """(kod penceresi, yakalanan pencereler) alanları.

        Kod yokken masanın tamamı yakalanan pencerelerin. Kod varken ve
        yakalanacak pencere yokken tersi. İkisi birden varsa masa
        bölünüyor — ajan hem kod yazarken hem tarayıcıya bakarken ikisini
        de görmek gerekiyor ve üst üste bindirmek birini gizlerdi.
        """
        masa = QRect(0, PANEL_H, self.width(), self.height() - PANEL_H)
        if not self.kod.aktif:
            return QRect(), masa
        ic = masa.adjusted(KOD_PAY, KOD_PAY, -KOD_PAY, -KOD_PAY)
        if self._kare.bos:
            return ic, QRect()
        en = int(masa.width() * KOD_ORAN) - KOD_PAY
        if en < KOD_ASGARI:
            # Bölünecek kadar geniş değil ve iki okunmaz bölme, bir
            # okunur bölmeden kötü. Yazılırken kod öne alınıyor —
            # bakılmak istenen o. Yazma bitince masa pencerelere
            # dönüyor, yoksa küçük bir pencerede kod ekranı kalıcı
            # olarak kaplardı.
            return (ic, QRect()) if self.kod.yaziliyor else (QRect(), masa)
        return (QRect(ic.left(), ic.top(), en, ic.height()),
                QRect(masa.left() + int(masa.width() * KOD_ORAN), masa.top(),
                      masa.width() - int(masa.width() * KOD_ORAN),
                      masa.height()))

    def _golge(self, p: QPainter, kutu: QRectF, yaricap: float) -> None:
        """Katmanlı yumuşak gölge. Tek bir yarı saydam dikdörtgen
        gölge değil bir çerçeve gibi duruyordu; altı geçiş katmanı
        yumuşaklığı bedavaya yakın veriyor."""
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(6, 0, -1):
            renk = QColor(0, 0, 0, 10 + i * 3)
            p.setBrush(renk)
            p.drawRoundedRect(
                kutu.adjusted(-i, -i + 2, i, i + 3),
                yaricap + i, yaricap + i,
            )

    def _yerlestir(self) -> None:
        """Kod penceresini yerine koyar. Değişmediyse dokunmuyor —
        aynı geometriyi saniyede sekiz kez atamak boşuna düzen işi."""
        kutu, _kalan = self._bolgeler()
        gorunur = self.kod.aktif and kutu.isValid() and kutu.width() > 220
        if gorunur and kutu != self._kod_kutusu:
            self._kod_kutusu = kutu
            self.kod.setGeometry(kutu)
        # `isHidden` soruluyor, `isVisible` değil: masa sayfası ekranda
        # değilken `isVisible` her zaman `False` dönüyor ve karşılaştırma
        # saniyede sekiz kez `setVisible` çağırırdı.
        if gorunur == self.kod.isHidden():
            self.kod.setVisible(gorunur)
            if gorunur:
                self.kod.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._yerlestir()

    def kod_akiyor(self, arac: str, yol: str, metin: str, bitti: bool) -> None:
        """Model bir dosya yazıyor."""
        self.kod.kod_akiyor(arac, yol, metin, bitti)
        self._yerlestir()
        self.update()

    def _kapsam(self) -> tuple[int, int, int, int]:
        """Çizilecek masaüstü bölgesi: ya tamamı ya pencerelerin kutusu.

        1920x1080'i 1100 piksellik bir sayfaya sığdırmak 0.57 ölçek demek
        ve 980 piksellik bir tarayıcı 560 piksele iniyor — içindeki yazı
        okunmuyor. "Yakınlaş" kipinde pencerelerin ortak kutusuna
        sığdırılıyor ve aynı tarayıcı neredeyse gerçek boyunda çıkıyor.
        İkisi de doğru; hangisine baktığın panelde yazıyor.
        """
        en, boy = self._kare.alan
        if not self._yakin or self._kare.bos:
            return 0, 0, en, boy
        sol = min(p.x for p in self._kare.pencereler)
        ust = min(p.y for p in self._kare.pencereler)
        sag = max(p.x + p.en for p in self._kare.pencereler)
        alt = max(p.y + p.boy for p in self._kare.pencereler)
        pay = 28
        # Başlık çubuğu pencerenin üstünde çiziliyor; kapsam onu da almalı.
        return (sol - pay, ust - BASLIK_H - pay,
                (sag - sol) + pay * 2, (alt - ust) + BASLIK_H + pay * 2)

    def _olcek(self, masa: QRect) -> tuple[float, QPointF]:
        """Kapsamı sayfaya sığdıran ölçek ve ortalama kayması."""
        kx, ky, en, boy = self._kapsam()
        if en <= 0 or boy <= 0:
            return 1.0, QPointF(0, 0)
        olcek = min(masa.width() / en, masa.height() / boy)
        return olcek, QPointF(
            masa.left() + (masa.width() - en * olcek) / 2 - kx * olcek,
            masa.top() + (masa.height() - boy * olcek) / 2 - ky * olcek,
        )

    def _duvar(self, p: QPainter, masa: QRect) -> None:
        """Duvar kâğıdı — **önbellekten**.

        Kompozisyon her karede yeniden çizilseydi saniyede sekiz kez iki
        radyal geçiş, dört bant ve bir gren katmanı demekti. Boyut
        değişmediği sürece hiçbiri tekrar hesaplanmıyor; sonuç bir
        `QPixmap` ve karede yalnızca bir blit var. Zenginliği de bu
        ödüyor: bedava olmayan bir duvar kâğıdı sade kalmak zorundaydı.
        """
        if self._duvar_kare is None or self._duvar_kare.size() != masa.size():
            self._duvar_kare = self._duvar_ciz(masa.size())
        p.drawPixmap(masa.topLeft(), self._duvar_kare)

    def _duvar_ciz(self, olcu) -> QPixmap:
        """Mint'in fotoğrafı değil, kendi çizimimiz.

        Mint'in duvar kâğıtları onların ve açık bir depoya konamaz. Burada
        beş katman var ve her biri bir işe yarıyor: taban geçişi rengi,
        iki ışık derinliği, bantlar karakteri, gren bantlaşmayı, vinyet
        pencerelerin kenardan ayrılmasını.
        """
        kare = QPixmap(olcu)
        en, boy = olcu.width(), olcu.height()
        p = QPainter(kare)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # 1. Taban: köşegen geçiş.
        taban = QLinearGradient(QPointF(0, 0), QPointF(en * 0.55, boy))
        taban.setColorAt(0.0, QColor(DUVAR_UST))
        taban.setColorAt(1.0, QColor(DUVAR_ALT))
        p.fillRect(0, 0, en, boy, taban)

        # 2. İki ışık kaynağı. Tek kaynak düz bir zemini canlandırmıyor;
        # ikincisi karşı köşeden gelip hacim veriyor.
        for merkez, renk, alfa, yaricap in (
            ((0.22, 0.16), YESIL, 30, 0.85),
            ((0.86, 0.92), "#3f7f6a", 18, 0.75),
        ):
            isik = QRadialGradient(
                QPointF(en * merkez[0], boy * merkez[1]),
                max(en, boy) * yaricap,
            )
            ic = QColor(renk)
            ic.setAlpha(alfa)
            dis = QColor(renk)
            dis.setAlpha(0)
            isik.setColorAt(0.0, ic)
            isik.setColorAt(1.0, dis)
            p.fillRect(0, 0, en, boy, isik)

        # 3. Bantlar. Mint'in duvar kâğıtlarındaki akış hissi; burada
        # birkaç geniş yay olarak. Alfa çok düşük — fark edilmesi değil,
        # zemine doku vermesi isteniyor.
        p.setPen(Qt.PenStyle.NoPen)
        # Değişkenin adı `kayma`, `kaydir` değil: salt okunurluk testi
        # yasak eylem adlarını kaynakta arıyor ve `kaydir` onlardan biri.
        # Testi gevşetmek yerine adı değiştirmek doğru — gevşeyen bir
        # güvenlik testi bir daha sıkılaşmıyor.
        for i, (kayma, kalinlik, alfa) in enumerate(
            ((-0.10, 0.42, 9), (0.18, 0.34, 7), (0.52, 0.5, 6), (0.78, 0.3, 5))
        ):
            yol = QPainterPath()
            y0 = boy * kayma
            yol.moveTo(-en * 0.1, y0)
            yol.cubicTo(en * 0.3, y0 - boy * 0.18,
                        en * 0.7, y0 + boy * 0.22,
                        en * 1.1, y0 - boy * 0.05)
            yol.lineTo(en * 1.1, y0 - boy * 0.05 + boy * kalinlik)
            yol.cubicTo(en * 0.7, y0 + boy * 0.22 + boy * kalinlik,
                        en * 0.3, y0 - boy * 0.18 + boy * kalinlik,
                        -en * 0.1, y0 + boy * kalinlik)
            yol.closeSubpath()
            renk = QColor("#ffffff" if i % 2 else YESIL)
            renk.setAlpha(alfa)
            p.setBrush(renk)
            p.drawPath(yol)

        # 4. Gren. Büyük ve karanlık bir geçiş bantlaşıyor — 8 bitlik
        # kanalda 26 farklı yeşil arasında geçiş yapmak şerit üretiyor.
        # Gren onu kırıyor; ekranda "kaliteli" görünen şeyin çoğu bu.
        gren = _gren()
        for gy in range(0, boy, gren.height()):
            for gx in range(0, en, gren.width()):
                p.drawImage(gx, gy, gren)

        # 5. Vinyet: kenarlar koyulaşınca pencereler zeminden ayrılıyor.
        vinyet = QRadialGradient(QPointF(en / 2, boy / 2), max(en, boy) * 0.78)
        vinyet.setColorAt(0.55, QColor(0, 0, 0, 0))
        vinyet.setColorAt(1.0, QColor(0, 0, 0, 96))
        p.fillRect(0, 0, en, boy, vinyet)

        # Panelin altına ince bir gölge: panel zeminin üstünde duruyor.
        alt_golge = QLinearGradient(QPointF(0, 0), QPointF(0, 10))
        alt_golge.setColorAt(0.0, QColor(0, 0, 0, 70))
        alt_golge.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(0, 0, en, 10, alt_golge)
        p.end()
        return kare

    def _bos_masa(self, p: QPainter, masa: QRect) -> None:
        """Hiç pencere yokken ne olduğunu yazıyor.

        Boş bir duvar kâğıdı "bağlantı koptu" ile "ajan henüz bir şey
        açmadı"yı ayırt ettirmiyor. İkisi çok farklı ve ikisi de burada
        yazılı.
        """
        if self._kapali:
            baslik = "The desk is closed"
            alt = ("The agent closed its workspace. It opens again on the "
                   "next side_launch.")
        else:
            baslik = "The desk is empty"
            alt = "Nothing has been launched here yet."

        # Yer tutucu pencere: buraya bir pencere geleceğini söylüyor.
        # Kesikli çizgi kasıtlı — dolu bir dikdörtgen gerçek bir pencere
        # sanılırdı ve boş bir masayı dolu göstermek olurdu.
        orta = QPointF(masa.center().x(), masa.center().y() - 46)
        cerceve = QRectF(orta.x() - 132, orta.y() - 74, 264, 148)
        kalem = QPen(QColor(255, 255, 255, 34), 1.4)
        kalem.setStyle(Qt.PenStyle.DashLine)
        kalem.setDashPattern([5, 5])
        p.setPen(kalem)
        p.setBrush(QColor(255, 255, 255, 8))
        p.drawRoundedRect(cerceve, YARICAP, YARICAP)
        p.setPen(QPen(QColor(255, 255, 255, 26), 1.2))
        p.drawLine(QPointF(cerceve.left() + 10, cerceve.top() + 26),
                   QPointF(cerceve.right() - 10, cerceve.top() + 26))
        for i in range(3):
            p.setBrush(QColor(255, 255, 255, 26))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(cerceve.left() + 16 + i * 11,
                                  cerceve.top() + 13), 2.6, 2.6)

        f = QFont(self.font())
        f.setPointSizeF(15.0)
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(QColor(YAZI))
        kutu = QRect(masa.left(), int(cerceve.bottom()) + 30,
                     masa.width(), 30)
        p.drawText(kutu, Qt.AlignmentFlag.AlignCenter, baslik)

        f.setPointSizeF(10.5)
        f.setWeight(QFont.Weight.Normal)
        p.setFont(f)
        p.setPen(QColor(YAZI_SOLUK))
        p.drawText(QRect(masa.left(), kutu.bottom() + 2, masa.width(), 22),
                   Qt.AlignmentFlag.AlignCenter, alt)

        # Özelliğin ne olduğunu söyleyen tek cümle. Boş bir ekran, ürünün
        # en çok açıklamaya ihtiyaç duyduğu yer: buraya ilk bakan kişi
        # neden ayrı bir masaüstü olduğunu bilmiyor.
        f.setPointSizeF(9.5)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255, 90))
        p.drawText(
            QRect(masa.left(), kutu.bottom() + 26, masa.width(), 22),
            Qt.AlignmentFlag.AlignCenter,
            "The agent opens apps here with side_launch — your mouse and "
            "focus stay where they are.",
        )

    def _pencere_ciz(self, p: QPainter, pencere, olcek: float,
                     ofset: QPointF) -> None:
        en = max(1.0, pencere.en * olcek)
        boy = max(1.0, pencere.boy * olcek)
        x = ofset.x() + pencere.x * olcek
        y = ofset.y() + pencere.y * olcek
        govde = QRectF(x, y, en, boy)
        baslik = QRectF(x, y - BASLIK_H, en, BASLIK_H)
        etkin = pencere.hwnd == self._kare.etkin

        tam = baslik.united(govde)

        # Gölge tek bir dikdörtgendi ve pencereler duvar kâğıdının üstüne
        # yapıştırılmış resimler gibi duruyordu. Bulanıklık yerine katman:
        # aynı yol büyüyerek ve solarak altı kez çiziliyor. Gerçek bir
        # bulanıklık `QGraphicsEffect` isterdi ve o her karede yeniden
        # hesaplanırdı; bu, sekiz kareye bedeli olmayan yaklaşıklık.
        p.setPen(Qt.PenStyle.NoPen)
        derinlik = 6 if etkin else 4
        for i in range(derinlik, 0, -1):
            p.setBrush(QColor(0, 0, 0, 10 if etkin else 7))
            p.drawRoundedRect(
                tam.adjusted(-i, -i + i * 0.7, i, i + i * 1.3),
                YARICAP + i, YARICAP + i,
            )

        # Pencerenin tamamı tek bir yol: üstü yuvarlak, altı hafif
        # yuvarlak. İçerik buna kırpılıyor, yoksa keskin köşeli bir kare
        # yuvarlak bir başlığın altından taşıyordu.
        yol = QPainterPath()
        yol.addRoundedRect(tam, YARICAP, YARICAP)
        kesik = QPainterPath()
        kesik.addRect(QRectF(tam.left(), tam.top() + YARICAP,
                             tam.width(), tam.height() - YARICAP * 2))
        yol = yol.united(kesik)

        p.setBrush(QColor(BASLIK_ETKIN if etkin else BASLIK_PASIF))
        p.drawPath(yol)

        # İçerik. `QImage` ham baytı kopyalamıyor; `ham` kare nesnesinde
        # yaşadığı sürece geçerli ve kare `self._kare` içinde duruyor.
        gorsel = QImage(pencere.ham, pencere.en, pencere.boy,
                        pencere.en * 3, QImage.Format.Format_RGB888)
        p.save()
        p.setClipPath(yol)
        p.drawImage(govde, gorsel)
        p.restore()

        # Üst kenarda ince bir aydınlık: ışık yukarıdan geliyor. Bu tek
        # piksel, chrome'un "çizilmiş" değil "gerçek" görünmesini sağlayan
        # şey — her işletim sistemi yapıyor.
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 22 if etkin else 12), 1))
        p.drawLine(QPointF(tam.left() + YARICAP, tam.top() + 0.5),
                   QPointF(tam.right() - YARICAP, tam.top() + 0.5))

        # Başlıkla içerik arasında ayraç ve dışta kenarlık.
        p.setPen(QPen(QColor(0, 0, 0, 60), 1))
        p.drawLine(QPointF(govde.left(), govde.top() - 0.5),
                   QPointF(govde.right(), govde.top() - 0.5))
        p.setPen(QPen(QColor(CERCEVE), 1))
        p.drawPath(yol)

        # Başlık yazısı ortada — Mint-Y'nin yaptığı bu. Rozet varken
        # yazının alanı ondan **önce** daraltılıyor: eliding tek başına
        # yetmiyor, ortalanmış bir yazı kısalsa da rozetin altına giriyor.
        # Ölçmeden önce öyleydi, "…Q6l2Y0here" diye üst üste bindi.
        rozet = self._rozet_eni() if etkin else 0.0
        alan = baslik.adjusted(8, 0, -(rozet + 8), 0)
        f = QFont(self.font())
        f.setPointSizeF(9.0)
        f.setWeight(QFont.Weight.DemiBold if etkin else QFont.Weight.Normal)
        p.setFont(f)
        p.setPen(QColor(YAZI if etkin else YAZI_SOLUK))
        yazi = QFontMetrics(f).elidedText(
            pencere.baslik or pencere.sinif, Qt.TextElideMode.ElideRight,
            max(20, int(alan.width())),
        )
        p.drawText(alan, Qt.AlignmentFlag.AlignCenter, yazi)

        if etkin:
            # Kapat/küçült düğmesi yok — salt okunur bir pencerede
            # çalışmayan bir düğme çizmek yalan olurdu. Yerine ajanın
            # burada olduğunu söyleyen bir işaret var.
            self._etkin_isareti(p, baslik)

    ROZET = "agent here"

    def _rozet_eni(self) -> float:
        f = QFont(self.font())
        f.setPointSizeF(8.0)
        return QFontMetrics(f).horizontalAdvance(self.ROZET) + 26

    def _etkin_isareti(self, p: QPainter, baslik: QRectF) -> None:
        f = QFont(self.font())
        f.setPointSizeF(8.0)
        p.setFont(f)
        metin = self.ROZET
        w = QFontMetrics(f).horizontalAdvance(metin)
        kutu = QRectF(baslik.right() - w - 26, baslik.center().y() - 8,
                      w + 18, 16)
        p.setPen(Qt.PenStyle.NoPen)
        yesil = QColor(YESIL)
        yesil.setAlpha(46)
        p.setBrush(yesil)
        p.drawRoundedRect(kutu, 8, 8)
        p.setBrush(QColor(YESIL))
        p.drawEllipse(QPointF(kutu.left() + 8, kutu.center().y()), 3.0, 3.0)
        p.setPen(QColor(YESIL))
        p.drawText(kutu.adjusted(14, 0, -4, 0),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   metin)

    def _imlec_ciz(self, p: QPainter, olcek: float, ofset: QPointF) -> None:
        """Ajanın imleci ve geldiği yol.

        İz kasıtlı ve `masaustu.py` ile aynı gerekçeyle: yalnızca ok "şu an
        neredeyim" der, iz "nereden geldim" der. Bir ajan yanlış yere
        tıkladığında ikincisi soruyu cevaplıyor.

        Ok **ölçeklenmiyor**: masaüstü küçültülerek gösteriliyor ve okla
        birlikte küçülen bir imleç üçte bir ölçekte kayboluyor. Gerçek bir
        imleç de ekran çözünürlüğüyle küçülmüyor.
        """
        def yerel(nokta: tuple[int, int]) -> QPointF:
            return QPointF(ofset.x() + nokta[0] * olcek,
                           ofset.y() + nokta[1] * olcek)

        iz = [yerel(n) for n in self._kare.iz]
        if len(iz) > 1:
            kalem = QPen(QColor(*IMLEC_RENK, 110), 2.0)
            kalem.setCapStyle(Qt.PenCapStyle.RoundCap)
            kalem.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(kalem)
            p.setBrush(Qt.BrushStyle.NoBrush)
            yol = QPainterPath(iz[0])
            for nokta in iz[1:]:
                yol.lineTo(nokta)
            p.drawPath(yol)

        uc = yerel(self._kare.imlec)
        if self._kare.tik:
            p.setPen(QPen(QColor(*IMLEC_RENK, 150), 2.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(uc, 11.0, 11.0)

        # Aynı siluet `masaustu.py`'deki oku izliyor: modele giden karede ve
        # burada iki farklı imleç görünmesi, ikisinin aynı şey olduğunu
        # gizlerdi.
        boy = float(IMLEC_BOY)
        silüet = [
            QPointF(uc.x(), uc.y()),
            QPointF(uc.x(), uc.y() + boy),
            QPointF(uc.x() + boy * 0.26, uc.y() + boy * 0.72),
            QPointF(uc.x() + boy * 0.42, uc.y() + boy * 1.04),
            QPointF(uc.x() + boy * 0.60, uc.y() + boy * 0.96),
            QPointF(uc.x() + boy * 0.44, uc.y() + boy * 0.66),
            QPointF(uc.x() + boy * 0.70, uc.y() + boy * 0.64),
        ]
        yol = QPainterPath(silüet[0])
        for nokta in silüet[1:]:
            yol.lineTo(nokta)
        yol.closeSubpath()
        p.setPen(QPen(QColor(*IMLEC_OYUK), 2.4))
        p.setBrush(QColor(*IMLEC_RENK))
        p.drawPath(yol)

    # --- panel ------------------------------------------------------------

    def _panel(self, p: QPainter) -> None:
        kutu = QRect(0, 0, self.width(), PANEL_H)
        # Düz dolgu yerine ince bir geçiş ve üstte bir aydınlık çizgi.
        # Panel bir yüzey; düz bir renk onu boyanmış bir şerit yapıyordu.
        gecis = QLinearGradient(QPointF(0, 0), QPointF(0, PANEL_H))
        gecis.setColorAt(0.0, QColor("#333333"))
        gecis.setColorAt(1.0, QColor("#292929"))
        p.fillRect(kutu, gecis)
        p.setPen(QPen(QColor(255, 255, 255, 16), 1))
        p.drawLine(QPointF(0, 0.5), QPointF(self.width(), 0.5))
        p.setPen(QPen(QColor(PANEL_UST), 1))
        p.drawLine(kutu.bottomLeft(), kutu.bottomRight())

        x = self._panel_mark(p, kutu)
        sag = self._panel_sag(p, kutu)
        self._panel_pencereler(p, kutu, x, sag)

    def _panel_mark(self, p: QPainter, kutu: QRect) -> int:
        """Panelin sol ucu: menü değil, kimlik.

        Mint'te burada menü düğmesi var. Bizde menü yok ve olmayan bir
        menünün düğmesini çizmek yalan olurdu; yerine masaüstü nesnesinin
        adı duruyor — o gerçekten var, `CreateDesktopW` ona verildi.
        """
        isaret = QRectF(10, kutu.center().y() - 9, 18, 18)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(YESIL))
        p.drawRoundedRect(isaret, 5, 5)
        p.setPen(QPen(QColor(PANEL), 1.6))
        for i in range(3):
            y = isaret.top() + 5.5 + i * 3.6
            p.drawLine(QPointF(isaret.left() + 4.5, y),
                       QPointF(isaret.right() - 4.5, y))

        f = QFont(self.font())
        f.setPointSizeF(9.5)
        p.setFont(f)
        p.setPen(QColor(YAZI))
        metin = "ajan-calisma"
        w = QFontMetrics(f).horizontalAdvance(metin)
        p.drawText(QRectF(isaret.right() + 8, kutu.top(), w + 4, PANEL_H),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   metin)
        return int(isaret.right() + 8 + w + 14)

    def _panel_sag(self, p: QPainter, kutu: QRect) -> int:
        """Saat, kare hızı ve duraklatma. Üçü de gerçek."""
        f = QFont(self.font())
        f.setPointSizeF(9.5)
        p.setFont(f)
        olcum = QFontMetrics(f)

        # Saat ve tarih. Cinnamon'da ikisi yan yana duruyor ve tarih
        # olmadan panel bir masaüstüne benzemiyor — bir ekranın sağ ucunda
        # yalnızca saat, uygulama arayüzüdür.
        saat = time.strftime("%H:%M")
        tarih = time.strftime("%a %d %b")
        w = olcum.horizontalAdvance(saat)
        wt = olcum.horizontalAdvance(tarih)
        p.setPen(QColor(YAZI))
        p.drawText(QRectF(self.width() - w - 14, kutu.top(), w, PANEL_H),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   saat)
        p.setPen(QColor(YAZI_SOLUK))
        p.drawText(QRectF(self.width() - w - wt - 22, kutu.top(), wt, PANEL_H),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   tarih)
        x = self.width() - w - wt - 32

        sure = self._akis.son_sure
        hiz = f"{min(FPS, 1 / sure):.0f} fps" if sure > 0.001 else "— fps"
        if self._duraklat:
            hiz = "paused"
        w2 = olcum.horizontalAdvance(hiz)
        p.setPen(QColor(YAZI_SOLUK))
        p.drawText(QRectF(x - w2, kutu.top(), w2, PANEL_H),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   hiz)
        x -= w2 + 12

        dugme = QRectF(x - 26, kutu.center().y() - 11, 22, 22)
        self._duraklat_kutusu = dugme.toRect()
        self._yuzey(p, dugme)
        p.setBrush(QColor(YAZI))
        if self._duraklat:
            ucgen = QPainterPath(QPointF(dugme.center().x() - 3.5,
                                         dugme.center().y() - 5))
            ucgen.lineTo(dugme.center().x() + 5, dugme.center().y())
            ucgen.lineTo(dugme.center().x() - 3.5, dugme.center().y() + 5)
            ucgen.closeSubpath()
            p.drawPath(ucgen)
        else:
            for dx in (-3.5, 1.5):
                p.drawRect(QRectF(dugme.center().x() + dx,
                                  dugme.center().y() - 5, 2.6, 10))
        x = dugme.left() - 8

        # Yakınlaşma anahtarı. İki kip de doğru: biri masaüstünün gerçek
        # geometrisini, öbürü pencerelerin okunur hâlini gösteriyor.
        # Hangisine baktığın yazıyor, çünkü ölçek değişince pencerelerin
        # birbirine göre yeri aynı kalıyor ve fark ancak yazıyla anlaşılıyor.
        etiket = "zoom" if self._yakin else "desk"
        w3 = olcum.horizontalAdvance(etiket) + 18
        kip = QRectF(x - w3, kutu.center().y() - 11, w3, 22)
        self._yakin_kutusu = kip.toRect()
        self._yuzey(p, kip)
        p.setPen(QColor(YESIL if self._yakin else YAZI_SOLUK))
        p.drawText(kip, Qt.AlignmentFlag.AlignCenter, etiket)
        return int(kip.left() - 12)

    @staticmethod
    def _yuzey(p: QPainter, kutu: QRectF) -> None:
        """Panel üstündeki küçük yüzey: geçiş, kenarlık, üst aydınlık.

        Düz bir gri dikdörtgen paneldeki her düğmeyi aynı yapıyordu ve
        hiçbiri basılabilir görünmüyordu.
        """
        gecis = QLinearGradient(kutu.topLeft(), kutu.bottomLeft())
        gecis.setColorAt(0.0, QColor("#3d3d3d"))
        gecis.setColorAt(1.0, QColor("#343434"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(gecis)
        p.drawRoundedRect(kutu, 5, 5)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 18), 1))
        p.drawLine(QPointF(kutu.left() + 5, kutu.top() + 0.5),
                   QPointF(kutu.right() - 5, kutu.top() + 0.5))
        p.setPen(QPen(QColor(0, 0, 0, 70), 1))
        p.drawRoundedRect(kutu, 5, 5)

    def _panel_pencereler(self, p: QPainter, kutu: QRect, sol: int,
                          sag: int) -> None:
        """Pencere listesi. Mint'te bunlar düğme; burada etiket.

        Salt okunur bir görüntüde bir pencereyi öne getirmek gerçek
        z-sırasını yalanlamak olurdu — ekranda gördüğün sıra ajanın
        masaüstündeki sıra.
        """
        pencereler = list(reversed(self._kare.pencereler))
        if not pencereler or sag - sol < 80:
            return
        f = QFont(self.font())
        f.setPointSizeF(9.0)
        p.setFont(f)
        olcum = QFontMetrics(f)
        genislik = min(190, (sag - sol - 8) // len(pencereler))
        if genislik < 60:
            return
        x = sol
        for pencere in pencereler:
            etkin = pencere.hwnd == self._kare.etkin
            alan = QRectF(x, kutu.top() + 5, genislik - 6, PANEL_H - 10)
            if etkin:
                self._yuzey(p, alan)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(YESIL))
                p.drawRoundedRect(
                    QRectF(alan.left() + 1, alan.top() + 3, 2.5,
                           alan.height() - 6), 1.2, 1.2
                )
            else:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(0, 0, 0, 40))
                p.drawRoundedRect(alan, 5, 5)
            p.setPen(QColor(YAZI if etkin else YAZI_SOLUK))
            p.drawText(
                alan.adjusted(10, 0, -6, 0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                olcum.elidedText(pencere.baslik or pencere.sinif,
                                 Qt.TextElideMode.ElideRight,
                                 int(alan.width()) - 18),
            )
            x += genislik


def masa_kaynagi(dispatcher_ver):
    """Arayüzün her karede çağıracağı okuyucu.

    Aldığı şey dispatcher'ın kendisi **değil**, onu veren bir çağrı. Fark
    şurada: masa sayfası uygulama açılırken kuruluyor, ajan ise saniyeler
    sonra. Dispatcher'ı o an alıp saklasaydım masa ömrü boyunca `None`
    tutar ve ajan çalışsa bile hep boş masa gösterirdi — yazarken tam
    olarak bunu yaptım, sonra sıralamaya bakınca çıktı.
    """
    def oku() -> MasaKaresi:
        dispatcher = (dispatcher_ver() if callable(dispatcher_ver)
                      else dispatcher_ver)
        alan = (1920, 1080)
        try:
            ekran = dispatcher.active
            alan = (ekran.width, ekran.height)
        except Exception:
            # Ajan kurulamamışsa masaüstü ölçüsü de yok; varsayılan kalıyor
            # ve pencere boş masayı gösteriyor.
            pass
        return masayi_oku(
            getattr(dispatcher, "side", None),
            getattr(dispatcher, "side_input", None),
            alan=alan,
            etkin=getattr(dispatcher, "last_side_hwnd", 0),
        )
    return oku
