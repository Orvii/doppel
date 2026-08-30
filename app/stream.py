"""Akış göstergeleri: koşu halkası ve akan metin.

**Halka bir bekleme çarkı değil, turun şekli.** Biten her adım halkada
kalıcı bir dilim bırakıyor; başarısız olan kırmızı. Tur bitince halkaya
bakıp "dokuz adım sürdü, biri patladı" diyebiliyorsun. Klasik bekleme
çarkı bunu yapmıyor: sabit hızda döner, sen bekliyor musun yoksa iş mi
yapıyor ayırt edemezsin, ve bittiğinde ardında hiçbir şey bırakmaz.

**Yalnızca gerçekten bir şey geldiğinde ilerliyor.** Modelden bir parça
düştüğünde ya da bir araç sonuç verdiğinde. Model takılırsa halka da
takılıyor — bu bilgi, arıza değil: "neden bekliyor" sorusunun cevabı.
`MicDot` da aynı görüşte, halkası sen sustuğunda duruyor.

**Yay dilimin sonuna asla varmıyor.** Bir adımın bittiğini, bitmeden önce
iddia edemez. Yüzde 92'de durup gerçek sonucu bekliyor.

Metin tarafında `AkanMetin` var: model yazarken harfler geldikçe düşüyor
ve sonunda bir imleç yanıp sönüyor. İmleçsiz akan metin, bitmiş bir cevap
gibi okunuyordu.
"""

from __future__ import annotations

import math
import re
import time

from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QKeySequence,
    QPainter,
    QPen,
    QTextLayout,
    QTextOption,
)
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from .fluent import Tokens, _blend
from .glyphs import glyph_for, paint_glyph
from .motion import (
    Ripple, Shake, Spring, Tween, clock, ease_out_back, ease_out_expo,
)
from .kafa import AjanKafasi


def _yuz(t: Tokens, size: int):
    """Halkanın içindeki yüz.

    Sıra: kendi SVG'miz, sonra kodla çizilen yüz. İkisi de aynı arayüzü
    sunuyor.

    Arada bir üçüncü katman vardı — hazır GIF karelerinden oynayan bir
    maskot. Kaldırıldı: 1180 kare 8.8 MB tutuyordu, tema bilmiyordu,
    gözbebeğini oynatamıyordu, ve kareler başkasının çizimlerinden
    ayrılmıştı. SVG varlıkları depoda duruyor; yoksa `svg_yap.py` onları
    yeniden üretiyor.
    """
    yuz = _svg_yuz(t, size)
    return yuz if yuz is not None else AjanKafasi(t, size)


def _svg_yuz(t: Tokens, size: int):
    try:
        from .svgyuz import SvgYuz, varlik_var

        return SvgYuz(t, size) if varlik_var() else None
    except Exception:
        return None


#: Kare aralığı. 30 fps: 44 pikselik bir çizimde 60 fps'in farkı
#: görünmüyor, işlemci farkı görünüyor.
FRAME_MS = 33

#: Yayın dilim sonuna yaklaşırken durduğu yer. 1.0 olsaydı adım bitmeden
#: bittiğini söylerdi.
ARC_CEILING = 0.92

#: Bir parça geldiğinde yayın ilerlediği miktar.
ARC_STEP = 0.035

#: Halka en az bu kadar dilime bölünüyor. Tek adımlık bir turda tam
#: çember çizmek, turun bittiğini söylerdi.
MIN_SLOTS = 6

#: İzin kalınlığı, sol kenardan uzaklığı ve uçlardaki pay.
TRACK_W, TRACK_X, TRACK_PAD = 3.0, 5.0, 6.0

#: Yüzün üstten uzaklığı.
FACE_Y = 2.0

#: Bu kadar süre hiçbir şey gelmezse yayın ucu soluyor.
STALL_AFTER = 0.9

#: Akıştaki bir adım satırının yüksekliği. 26'ydı; yedi satırlık bir
#: dökümde 28 piksel fazladan yer kaplıyordu ve satırlar zaten 12 punto.
ROW_H = 22

#: Düşen adımın işareti bu kadar kalınlaşıyor.
#:
#: Renk tek başına yetmiyor: bu temada `accent` #e7babd ve `critical`
#: #ff99a4 — ikisi de soluk pembe ve ince bir işarette aynı görünüyor.
#: Ölçtüm. Biçim renge bağlı değil: düşen adım kalınlaşıyor ve temayı
#: değiştirsen de görünür kalıyor.
FAIL_WIDTH = 2.0


class RunRing(QWidget):
    """Turun şeklini biriktiren iz, üstünde ajanın yüzü.

    Önce bir daireydi ve yüz ortasındaydı. Maskotun eline nesne verince
    çalışmaz oldu: nesne çemberi kesiyor, koşu kaydı okunmaz hâle
    geliyordu. Daireyi büyütmek de olmazdı — figür küçülür, ifade
    kaybolurdu.

    Şimdi **dikey bir iz**, sütunun sol kenarında. Adımlar yukarıdan
    aşağı diziliyor, yani dökümle aynı yönde okunuyor ve figürün üstünden
    hiç geçmiyor. Çember hiç kırılmıyor çünkü çember yok.
    """

    def __init__(self, t: Tokens, size: int = 52) -> None:
        super().__init__()
        self.t = t
        self.setFixedSize(size, size)
        self._done: list[bool] = []      # her biten adım: hata mı?
        # Halkanın içindeki yüz. Ayrı bir widget olarak üst üste koymak
        # iki ortayı hizalamak demekti; yüz kendi çizimini buraya boyuyor.
        #
        # Hazır kareler varsa maskot, yoksa çizilen yüz. İkisi aynı
        # arayüzü sunuyor; halka hangisi olduğunu bilmiyor. Varlıksız bir
        # kopyada uygulama yüzsüz kalmamalı.
        self.face = _yuz(t, size)
        self.face.setParent(self)
        #: Yüzü halka çiziyor. Bir dönem sahne çiziyordu — maskotun
        #: elinde nesne varken sıra önemliydi — ama nesneler kalktı.
        self.yuzu_ciz = True
        self.face.hide()
        self.face.on_change = self.update
        self._glyph = "goz"
        self._prev_glyph = ""
        self._fade = 1.0
        self._arc_target = 0.0
        # Yay: yolun ortasında hedef değişirse hız korunuyor. Süreli bir
        # geçiş orada sıfırlanıp zıplardı ve akış sırasında hedef saniyede
        # yirmi kez değişiyor.
        self._arc_spring = Spring(0.0, stiffness=150.0)
        # İniş: yeni biten dilim yerine oturarak geliyor, birden
        # belirmiyor. Turun tek yazılı anı bu.
        self._land = Spring(1.0, stiffness=210.0, damping=17.0)
        self._ripple = Ripple(0.5)
        self._shake = Shake()
        self._live = False
        self._last = 0.0
        self._abone = False

    # --- olaylar ----------------------------------------------------------

    def begin(self) -> None:
        """Yeni tur. Önceki turun şekli siliniyor."""
        self._done.clear()
        self._arc_target = 0.0
        self._arc_spring.jump(0.0)
        self._land.jump(1.0)
        self._live = True
        self.face.set_live(True)
        self.face.set_state("dusunuyor")
        self._mark()
        self._dinle(True)
        self.update()

    def step(self, tool: str) -> None:
        """Yeni bir araç çağrısı başladı."""
        self.face.set_tool(tool)
        self.face.bump()
        yeni = glyph_for(tool)
        if yeni != self._glyph:
            self._prev_glyph = self._glyph
            self._glyph = yeni
            self._fade = 0.0
        self._arc_spring.jump(0.0)
        self._arc_target = 0.08
        self._mark()
        self._dinle(True)

    def settle(self, is_error: bool) -> None:
        """Adım bitti — halkada kalıcı bir dilim bırakıyor."""
        self._done.append(bool(is_error))
        self.face.bump()
        # İniş: dilim sıfırdan tam boyuna yayla açılıyor ve halkadan bir
        # dalga çıkıyor. Adımın **bittiği** an, adımın sürdüğü andan
        # başka görünmeli.
        self._land.jump(0.0)
        self._land.to(1.0)
        self._ripple.hit()
        if is_error:
            self.face.set_state("hata")
            self._shake.hit(1.0)
        self._arc_target = 0.0
        self._arc_spring.jump(0.0)
        self._mark()
        self._dinle(True)

    def pulse(self) -> None:
        """Modelden bir parça düştü."""
        self._arc_target = min(ARC_CEILING, self._arc_target + ARC_STEP)
        self.face.bump()
        self._mark()

    def finish(self) -> None:
        """Tur bitti. Şekil ekranda kalıyor, hareket duruyor."""
        self._live = False
        self.face.set_state("bitti")
        self.face.look_forward()
        self.face.set_live(False)
        self._arc_target = 0.0
        self._arc_spring.to(0.0)
        self.update()

    def _mark(self) -> None:
        self._last = time.monotonic()

    def _dinle(self, ac: bool) -> None:
        if ac and not self._abone:
            clock().subscribe(self._tick)
            self._abone = True
        elif not ac and self._abone:
            clock().unsubscribe(self._tick)
            self._abone = False

    def hideEvent(self, event) -> None:
        # Görünmeyen bir şeyi canlandırmak boşa iş.
        self._dinle(False)
        super().hideEvent(event)

    def showEvent(self, event) -> None:
        # Yüz görünür olduğu sürece nefes alıyor: bekleme animasyonu tur
        # bitince de sürüyor.
        super().showEvent(event)
        self._dinle(True)

    # --- kare -------------------------------------------------------------

    def _tick(self, dt: float) -> None:
        # Yüz gizli bir çocuk widget: kendi saatine abone olamıyor,
        # halka onu buradan sürüyor.
        adim = getattr(self.face, "step", None)
        if adim is not None:
            adim(dt)
        self._arc_spring.to(self._arc_target)
        self._arc_spring.step(dt)
        self._land.step(dt)
        self._ripple.step(dt)
        self._shake.step(dt)
        if self._fade < 1.0:
            self._fade = min(1.0, self._fade + dt / 0.22)
        self.update()
        # Yüz görünür olduğu sürece devam: bekleme animasyonu duruyorsa
        # halka ölü bir rozete dönüyor.

    @property
    def _arc(self) -> float:
        return max(0.0, self._arc_spring.value)

    # --- çizim ------------------------------------------------------------

    def _slots(self) -> int:
        return max(MIN_SLOTS, len(self._done) + 1)

    def paintEvent(self, _event) -> None:
        t = self.t
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Hata titremesi izi sarsıyor: kırmızı bir dilim okunmayı bekler,
        # kımıldayan bir şey gözü kendine çeker.
        sars = self._shake.amount and self._shake.step(0.0) or 0.0
        self._izi_ciz(painter, sars)
        self._paint_glyph(painter)
        painter.end()

    def _izi_ciz(self, painter: QPainter, sars: float) -> None:
        t = self.t
        x = TRACK_X + sars * 2.0
        ust, alt = TRACK_PAD, self.height() - TRACK_PAD
        boy = max(1.0, alt - ust)

        # Ray: bütün iz, sönük. Nereye kadar gidileceğini gösteriyor.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(t.divider))
        painter.drawRoundedRect(
            QRectF(x - TRACK_W / 2, ust, TRACK_W, boy), TRACK_W / 2, TRACK_W / 2
        )

        yuva = max(MIN_SLOTS, len(self._done) + 1)
        dilim = boy / yuva
        bosluk = min(3.0, dilim * 0.22)

        # Biten adımlar. Düşen adım hem kırmızı hem de sıradan dışarı
        # taşıyor: bu temada iki renk küçük bir işarette ayırt edilmiyor.
        son = len(self._done) - 1
        for i, hata in enumerate(self._done):
            oran = (ease_out_back(min(1.0, max(0.0, self._land.value)))
                    if i == son else 1.0)
            uzunluk = max(0.0, (dilim - bosluk) * oran)
            en = TRACK_W * (FAIL_WIDTH if hata else 1.0)
            painter.setBrush(QColor(t.critical if hata else t.accent))
            painter.drawRoundedRect(
                QRectF(x - en / 2, ust + i * dilim, en, uzunluk),
                en / 2, en / 2,
            )

        # Süren adım: dilimin içinde büyüyen parça, sonuna varmıyor.
        if self._arc > 0.004:
            durdu = self._live and (time.monotonic() - self._last) > STALL_AFTER
            renk = QColor(t.text_tertiary if durdu else t.text_secondary)
            painter.setBrush(renk)
            uzunluk = (dilim - bosluk) * self._arc
            bas_y = ust + len(self._done) * dilim
            painter.drawRoundedRect(
                QRectF(x - TRACK_W / 2, bas_y, TRACK_W, max(0.0, uzunluk)),
                TRACK_W / 2, TRACK_W / 2,
            )
            self._paint_head(painter, x, bas_y + uzunluk, renk)

        # Biten adımın dalgası: izin ucundan dışarı yayılıp sönüyor.
        if self._ripple.alive:
            hale = QColor(t.accent)
            hale.setAlphaF(0.30 * self._ripple.alpha)
            painter.setPen(QPen(hale, 1.4))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            r = 4.0 + self._ripple.radius * 9.0
            merkez_y = ust + min(len(self._done), yuva) * dilim
            painter.drawEllipse(QPointF(x, merkez_y), r, r)
            painter.setPen(Qt.PenStyle.NoPen)

    def _paint_head(self, painter: QPainter, x: float, y: float,
                    renk: QColor) -> None:
        """İzin ucundaki nokta: "buradayız".

        Çizgi tek başına nerede bittiğini yeterince söylemiyor — bitmiş
        dilimlerle aynı kalınlıkta ve durağan bir karede ikisi birbirine
        karışıyor.
        """
        painter.setBrush(renk)
        painter.drawEllipse(QPointF(x, y), 2.4, 2.4)

    def _paint_glyph(self, painter: QPainter) -> None:
        """Ortadaki yüz.

        Eskiden burada aracın çizimi vardı; o çizimler artık dökümde, her
        adımın kendi satırında. Burada tek bir şey olmalı ve o da ajanın
        kendisi: hangi araçta olduğunu satırdan okuyorsun, ne durumda
        olduğunu yüzden.
        """
        if not self.yuzu_ciz:
            return
        kutu = self.yuz_kutusu()
        self.face.paint(painter, kutu.width(), kutu.topLeft())

    def yuz_kutusu(self) -> QRectF:
        """Yüzün gerçekten çizildiği kare.

        Dışarıya açık, çünkü maskotun elindeki nesneyi yerleştiren
        `sahne.py` yüzün nerede olduğunu bilmek zorunda. Eskiden bilmiyordu
        ve kendi hesabını yapıyordu: sütunun ortası. Halka sütundan dar
        olduğu için yüz merkezi 30'da, nesne merkezi 43'te kalıyordu —
        ölçtüm. Ekranda maskot bir yana, elindeki nesne öbür yana
        düşüyordu ve hiçbir şeyi tuttuğu okunmuyordu.

        Aynı sayıyı iki yerde hesaplamanın bedeli buydu. Artık tek yer
        burası.

        Yüz izin sağında ve üstte; ortalanmıyor çünkü altta nesne var.
        """
        alan = self.width() - TRACK_X - TRACK_W
        boyut = alan * getattr(self.face, "fill", 0.56)
        return QRectF(
            TRACK_X + TRACK_W + (alan - boyut) / 2, FACE_Y, boyut, boyut
        )


#: Modelin yazdığı kalın vurgu. Yıldızlar **ekranda görünmemeli** —
#: `**Reacher**` diye basılan bir cevap, biçimlendirmeyi çizmek yerine
#: kaynağını gösteriyor demektir.
_KALIN = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)

#: Ters tırnak içindeki kod. Yıldızla aynı gerekçe.
_KOD = re.compile(r"`([^`\n]+)`")


def bicimle(ham: str) -> tuple[str, list[tuple[int, int]], list[tuple[int, int]]]:
    """Markdown işaretlerini metinden çıkarır, yerlerini geri verir.

    Dönen şey: temizlenmiş metin, kalın aralıklar, kod aralıkları. Aralıklar
    **temizlenmiş metnin** koordinatında; tek bir koordinat sistemi olması
    seçimi ve imleci de doğru tutuyor.

    İşaretler saklanmak yerine silinip yeniden çizilebilirdi ama o zaman
    kopyaladığın metinde yıldızlar kalırdı. Burada kopyalanan da temiz.

    Akış sırasında yarım kalan bir `**` kendiliğinden çözülüyor: her parça
    geldiğinde bütün ham metinden yeniden hesaplanıyor, yani kapanmayan bir
    işaret eşleşmiyor ve olduğu gibi duruyor — sonra kapanınca kayboluyor.
    """
    temiz: list[str] = []
    kalin: list[tuple[int, int]] = []
    kod: list[tuple[int, int]] = []
    i = 0
    while i < len(ham):
        for desen, hedef in ((_KALIN, kalin), (_KOD, kod)):
            m = desen.match(ham, i)
            if m:
                govde = m.group(1)
                bas = sum(len(p) for p in temiz)
                temiz.append(govde)
                hedef.append((bas, len(govde)))
                i = m.end()
                break
        else:
            temiz.append(ham[i])
            i += 1
    return "".join(temiz), kalin, kod


class AkanMetin(QWidget):
    """Model yazarken harflerin düştüğü alan, sonunda yanıp sönen imleç.

    `QLabel` yerine kendi düzenini kuruyor çünkü imlecin **son harfin tam
    yanında** durması gerekiyor ve `QLabel` satır kırılımlarını nereye
    koyduğunu söylemiyor. `QTextLayout` bunu söylüyor.

    Fare ile seçme de burada: ajanın cevabını kopyalayabilmek gerekiyor ve
    kendi düzenini kuran bir widget bunu kendi eklemezse kaybediyor.

    ## Paragraf başına bir düzen

    Tek bir `QTextLayout` bütün metni alıyordu ve `QTextLayout` satır
    sonunu bilmiyor: `\\n` sıradan bir karakter, satır kırılımını yalnızca
    sarma üretiyor. Sonuç ekranda görüldü — "…(lightest).One caveat" gibi
    iki paragraf birbirine yapışıyordu. Ölçtüm: iki paragraflı bir metin
    tek satıra iniyor, `\\n\\n` yutuluyor.

    Artık `\\n` başına bir düzen var ve boş satır tam satır değil daha
    küçük bir boşluk bırakıyor: yüzen çubukta yer pahalı, paragraf arası
    tam satır olsa cevabın yarısı boşluk olurdu.
    """

    PAD_X = 14
    PAD_TOP = 3
    PAD_BOTTOM = 3
    #: Satır yüksekliği çarpanı. 13 piksel gövdede 1.0 sıkışık okunuyor.
    LEADING = 1.34
    #: Paragraf arası boşluk, satır yüksekliğinin katı olarak.
    PARA_ARA = 0.5

    def __init__(self, t: Tokens, font_px: int = 13) -> None:
        super().__init__()
        self.t = t
        self._ham = ""
        self._text = ""
        self._kalin: list[tuple[int, int]] = []
        self._kod: list[tuple[int, int]] = []
        self._live = False
        self._caret_on = True
        self._bloklar: list[tuple[QTextLayout, int, float]] = []
        self._width = 0
        self._text_height = 0.0
        self._sel = (0, 0)
        self._anchor: int | None = None

        self._font = QFont(t.font_ui)
        self._font.setPixelSize(font_px)
        self._font_kalin = QFont(self._font)
        self._font_kalin.setWeight(QFont.Weight.DemiBold)
        self._font_kod = QFont(t.font_mono)
        self._font_kod.setPixelSize(font_px - 1)

        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        # Düzen yüksekliği `sizeHint`ten alıyor ve genişliğe bağlı
        # yükseklik ancak politika söylerse dikkate alınıyor. Bu satır
        # olmadan metin satırları 0 yükseklik alıp adımların üstüne
        # biniyordu — ölçtüm, ekranda üst üste çıktılar.
        politika = QSizePolicy(QSizePolicy.Policy.Preferred,
                               QSizePolicy.Policy.Minimum)
        politika.setHeightForWidth(True)
        self.setSizePolicy(politika)

        # İmleç yanıp sönmesi Windows'un kendi hızında: sistemle uyumsuz
        # bir imleç, ekrandaki tek yanlış ritim olurdu.
        self._blink = QTimer(self)
        self._blink.timeout.connect(self._flip)
        self._interval = max(400, QGuiApplication.styleHints().cursorFlashTime() // 2)

    # --- içerik -----------------------------------------------------------

    def text(self) -> str:
        """Ekranda duran metin — markdown işaretleri çıkarılmış hâli.

        Kopyalanan da bu. Yıldızları saklayıp yalnızca çizimde gizlemek,
        panoya yıldızlı metin koymak olurdu.
        """
        return self._text

    def set_text(self, text: str) -> None:
        if text == self._ham:
            return
        self._ham = text
        self._sel = (0, 0)
        self._yenile()

    def append(self, parca: str) -> None:
        if not parca:
            return
        self._ham += parca
        self._yenile()

    def _yenile(self) -> None:
        self._text, self._kalin, self._kod = bicimle(self._ham)
        self._bloklar = []
        self._resize_to_text()
        self.update()

    def set_live(self, live: bool) -> None:
        """Akış sürüyor mu — imleç yalnızca sürerken yanıp sönüyor."""
        if self._live == live:
            return
        self._live = live
        self._caret_on = True
        if live:
            self._blink.start(self._interval)
        else:
            self._blink.stop()
        self.update()

    def _flip(self) -> None:
        self._caret_on = not self._caret_on
        self.update()

    # --- düzen ------------------------------------------------------------

    def _bicimler(self, bas: int, boy: int) -> list[QTextLayout.FormatRange]:
        """Bir bloğa düşen kalın ve kod aralıkları, blok koordinatında."""
        cikti = []
        for araliklar, font in ((self._kalin, self._font_kalin),
                                (self._kod, self._font_kod)):
            for a_bas, a_boy in araliklar:
                kesisim_bas = max(bas, a_bas)
                kesisim_son = min(bas + boy, a_bas + a_boy)
                if kesisim_son <= kesisim_bas:
                    continue
                r = QTextLayout.FormatRange()
                r.start = kesisim_bas - bas
                r.length = kesisim_son - kesisim_bas
                r.format.setFont(font)
                if font is self._font_kod:
                    r.format.setForeground(QColor(self.t.accent_text))
                cikti.append(r)
        return cikti

    def _build(self, width: int) -> list[tuple[QTextLayout, int, float]]:
        """Paragraf başına bir düzen. Dönen: (düzen, metindeki başı, y)."""
        if self._bloklar and self._width == width:
            return self._bloklar
        secenek = QTextOption()
        secenek.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        kullanilir = max(1, width - self.PAD_X * 2)

        bloklar: list[tuple[QTextLayout, int, float]] = []
        y = 0.0
        yer = 0
        satir_boy = 0.0
        for parca in self._text.split("\n"):
            if not parca.strip():
                # Boş satır: tam satır değil, paragraf boşluğu. Yüzen
                # çubukta yer pahalı.
                y += (satir_boy or self._font.pixelSize()) * self.PARA_ARA
                yer += len(parca) + 1
                continue
            duzen = QTextLayout(parca, self._font)
            duzen.setTextOption(secenek)
            duzen.setFormats(self._bicimler(yer, len(parca)))
            duzen.beginLayout()
            ic_y = 0.0
            while True:
                satir = duzen.createLine()
                if not satir.isValid():
                    break
                satir.setLineWidth(kullanilir)
                satir.setPosition(QPointF(0, ic_y))
                satir_boy = satir.height()
                ic_y += satir.height() * self.LEADING
            duzen.endLayout()
            bloklar.append((duzen, yer, y))
            y += ic_y
            yer += len(parca) + 1

        self._bloklar = bloklar
        self._width = width
        self._text_height = y
        return bloklar

    def heightForWidth(self, width: int) -> int:
        if not self._text:
            return 0
        self._build(width)
        return int(math.ceil(self._text_height)) + self.PAD_TOP + self.PAD_BOTTOM

    def hasHeightForWidth(self) -> bool:
        return True

    def sizeHint(self) -> QSize:
        genislik = self.width() or 320
        return QSize(genislik, self.heightForWidth(genislik))

    def minimumSizeHint(self) -> QSize:
        """Genişlikte alt sınır **yok**.

        `sizeHint`i olduğu gibi döndürüyordum ve o genişliği en küçük
        genişlik sayılıyordu: kaydırma alanı içeriği viewport'a
        sığdıramıyor, döküm 640 piksele şişip metin sağdan kırpılıyordu.
        Ölçtüm — viewport 340, içerik 640.
        """
        return QSize(0, self.heightForWidth(self.width() or 320))

    def _resize_to_text(self) -> None:
        if self.width() > 0:
            self.setMinimumHeight(self.heightForWidth(self.width()))
        self.updateGeometry()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._bloklar = []
        self._resize_to_text()

    # --- seçim ------------------------------------------------------------

    def _cursor_at(self, point) -> int:
        bloklar = self._build(self.width())
        if not bloklar:
            return 0
        yerel = QPointF(point.x() - self.PAD_X, point.y() - self.PAD_TOP)
        for blok_i, (duzen, yer, blok_y) in enumerate(bloklar):
            son_blok = blok_i == len(bloklar) - 1
            for i in range(duzen.lineCount()):
                satir = duzen.lineAt(i)
                alt = blok_y + satir.y() + satir.height() * self.LEADING
                son_satir = son_blok and i == duzen.lineCount() - 1
                if yerel.y() < alt or son_satir:
                    return yer + satir.xToCursor(yerel.x())
        return len(self._text)

    def focusOutEvent(self, event) -> None:
        """Odak gidince seçim kalkıyor.

        Kalmıyordu ve sekiz satırlık bir cevabın tamamı vurgulu duruyordu:
        çubuğa yazmak için Ctrl+A'ya basmak dökümü seçiyor, sonra seçim
        sonsuza kadar ekranda kalıyor. Kalıcı bir vurgu okumayı bozuyor.
        """
        self._sel = (0, 0)
        self.update()
        super().focusOutEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._text:
            self._anchor = self._cursor_at(event.position())
            self._sel = (self._anchor, self._anchor)
            self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._anchor is not None:
            simdi = self._cursor_at(event.position())
            self._sel = (min(self._anchor, simdi), max(self._anchor, simdi))
            self.update()

    def mouseReleaseEvent(self, _event) -> None:
        self._anchor = None

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.StandardKey.Copy):
            bas, son = self._sel
            if son > bas:
                QGuiApplication.clipboard().setText(self._text[bas:son])
            return
        if event.matches(QKeySequence.StandardKey.SelectAll):
            self._sel = (0, len(self._text))
            self.update()
            return
        super().keyPressEvent(event)

    # --- çizim ------------------------------------------------------------

    def paintEvent(self, _event) -> None:
        if not self._text:
            return
        bloklar = self._build(self.width())
        if not bloklar:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QColor(self.t.text))

        bas, son = self._sel
        for duzen, yer, blok_y in bloklar:
            secimler = []
            if son > bas:
                kesisim_bas = max(bas, yer)
                kesisim_son = min(son, yer + len(duzen.text()))
                if kesisim_son > kesisim_bas:
                    aralik = QTextLayout.FormatRange()
                    aralik.start = kesisim_bas - yer
                    aralik.length = kesisim_son - kesisim_bas
                    # Vurgu dolu vurgu rengiyle çiziliyordu ve seçili bir
                    # cevap okunmaz bir pembe tabaka oluyordu. Yıkama
                    # yeterli: seçildiğini söylüyor, yazıyı ezmiyor.
                    aralik.format.setBackground(
                        QColor(_blend(self.t.accent, 0.30, self.t.layer))
                    )
                    aralik.format.setForeground(QColor(self.t.text))
                    secimler.append(aralik)
            duzen.draw(painter, QPointF(self.PAD_X, self.PAD_TOP + blok_y),
                       secimler)

        if self._live and self._caret_on:
            duzen, yer, blok_y = bloklar[-1]
            if duzen.lineCount():
                self._paint_caret(painter, duzen,
                                  QPointF(self.PAD_X, self.PAD_TOP + blok_y),
                                  len(duzen.text()))
        painter.end()

    def _paint_caret(self, painter: QPainter, duzen: QTextLayout,
                     koken: QPointF, son: int) -> None:
        """Son harfin yanındaki imleç. Blok değil ince bir çubuk: metnin
        altını kapatan bir blok, gelen son kelimeyi okunmaz yapıyordu."""
        satir = duzen.lineAt(duzen.lineCount() - 1)
        x = satir.cursorToX(son)[0]
        yukseklik = satir.height() * 0.82
        ust = satir.y() + (satir.height() - yukseklik) / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self.t.accent))
        painter.drawRoundedRect(
            QRectF(koken.x() + x + 1, koken.y() + ust, 2.0, yukseklik), 1.0, 1.0
        )


class AdimSatiri(QWidget):
    """Akıştaki tek bir adım: işin çizimi, ne yaptığı, nerede yaptığı.

    Çizim araca göre değişiyor — bakmak, okumak, tıklamak, yazmak, kabuk,
    dosya, sunucu, yetenek. Aynı simgeyi her adıma koymak, akışı okunmaz
    bir liste yapardı: hangi adımın ne olduğunu ancak metni okuyarak
    anlardın.
    """

    def __init__(self, t: Tokens, tool: str, baslik: str, detay: str) -> None:
        super().__init__()
        self.t = t
        self._tone = "normal"
        self._key = glyph_for(tool)
        self._baslik = baslik
        self._detay = detay
        self._giris: Giris | None = None
        self._shake = Shake()
        self.setFixedHeight(ROW_H)

    def sizeHint(self) -> QSize:
        # `setFixedHeight` en/boy sınırlarını koyuyor ama `sizeHint`i
        # değiştirmiyor: düz bir `QWidget` geçersiz (-1) ipucu veriyor ve
        # düzen satırı hiç saymıyordu. Ölçtüm — dört adım toplamda sıfır
        # yükseklik sayılıyor, son satır kırpılıyordu.
        return QSize(160, ROW_H)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def set_tone(self, tone: str) -> None:
        """`normal` ya da `hata`. Düşen adım kırmızıya dönüyor ve bir kez
        titriyor: kırmızı bir yazı okunmayı bekler, kımıldayan bir şey
        gözü kendine çeker."""
        self._tone = tone
        if tone == "hata":
            self._shake.hit(1.0)
            clock().subscribe(self._tick)
        self.update()

    def anime_et(self) -> None:
        """Satır aşağıdan kayarak geliyor. Birden beliren bir satır,
        akış hâlindeki bir dökümde gözün yerini kaybettiriyor."""
        self._giris = Giris()
        clock().subscribe(self._tick)

    def _tick(self, dt: float) -> None:
        if self._giris is not None:
            self._giris.step(dt)
            if self._giris.done:
                self._giris = None
        self._shake.step(dt)
        self.update()
        if self._giris is None and self._shake.resting:
            clock().unsubscribe(self._tick)

    def hideEvent(self, event) -> None:
        clock().unsubscribe(self._tick)
        super().hideEvent(event)

    def paintEvent(self, _event) -> None:
        t = self.t
        hata = self._tone == "hata"
        ana = t.critical if hata else t.accent
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._giris is not None:
            painter.setOpacity(self._giris.opacity)
            painter.translate(0, self._giris.offset)
        sars = self._shake.amount
        if sars:
            painter.translate(self._shake.step(0.0) * 3.0, 0)

        paint_glyph(painter, self._key, 16, ana,
                    t.critical if hata else t.text_tertiary, QPointF(14, 5))

        font = QFont(t.font_ui)
        font.setPixelSize(12)
        painter.setFont(font)
        olcu = painter.fontMetrics()
        x = 38
        painter.setPen(QColor(t.critical if hata else t.text_secondary))
        painter.drawText(x, 0, olcu.horizontalAdvance(self._baslik), self.height(),
                         int(Qt.AlignmentFlag.AlignVCenter), self._baslik)

        if self._detay:
            x += olcu.horizontalAdvance(self._baslik) + 8
            kalan = self.width() - x - 14
            if kalan > 24:
                painter.setPen(QColor(t.text_tertiary))
                painter.drawText(
                    x, 0, kalan, self.height(),
                    int(Qt.AlignmentFlag.AlignVCenter),
                    olcu.elidedText(self._detay, Qt.TextElideMode.ElideRight, kalan),
                )
        painter.end()


class NotSatiri(QWidget):
    """Ajanın "buna dikkat" notu.

    Adım satırından ayrı bir şey ve ayrı görünüyor: adım *ne yaptığını*
    söylüyor, not *neyin ters gidebileceğini*. İkisini aynı biçimde
    çizmek, notu otuz adımlık bir listenin içinde kaybetmek olurdu.

    Sabit yükseklikli değil. Bir not bir cümle de olabilir üç de; tek
    satıra sıkıştırılan bir uyarı, okunmadan geçilen bir uyarı.

    Ton **uyarı**, hata değil. Kırmızı bir satır "bir şey bozuldu"
    diyor; oysa burada hiçbir şey bozulmadı, ajan bozulabilecek bir şeyi
    söylüyor.
    """

    #: İç boşluklar ve metnin başladığı yer — adım satırıyla hizalı.
    PAY_Y = 7
    METIN_X = 38
    SAG_PAY = 14
    #: `about` verildiğinde üstteki küçük etiketin yüksekliği.
    ETIKET_H = 13

    def __init__(self, t: Tokens, notu: str, hakkinda: str = "") -> None:
        super().__init__()
        self.t = t
        self._not = (notu or "").strip()
        self._hakkinda = (hakkinda or "").strip()
        self._giris: Giris | None = None
        # Genişlik başına yükseklik. Metin kurulduktan sonra değişmiyor,
        # yani önbellek hiç geçersiz kalmıyor. Ölçtüm: önbelleksiz her
        # çağrı 0.13 ms (genişlik değişince 0.39 ms) ve `Akis` bunu her
        # satır eklendiğinde bütün notlar için yeniden ödüyordu.
        self._boy_onbellek: dict[int, int] = {}
        self.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Minimum)

    # --- ölçü -------------------------------------------------------------

    def _yazi(self) -> QFont:
        font = QFont(self.t.font_ui)
        font.setPixelSize(12)
        return font

    def _etiket_yazisi(self) -> QFont:
        font = QFont(self.t.font_ui)
        font.setPixelSize(9)
        font.setWeight(QFont.Weight.DemiBold)
        font.setCapitalization(QFont.Capitalization.AllUppercase)
        return font

    def _metin_kutusu(self, width: int) -> QRect:
        kalan = max(40, width - self.METIN_X - self.SAG_PAY)
        return QRect(0, 0, kalan, 10000)

    def heightForWidth(self, width: int) -> int:
        onbellekli = self._boy_onbellek.get(width)
        if onbellekli is not None:
            return onbellekli
        olcu = QFontMetrics(self._yazi())
        kutu = olcu.boundingRect(
            self._metin_kutusu(width),
            int(Qt.TextFlag.TextWordWrap), self._not,
        )
        yukseklik = kutu.height() + self.PAY_Y * 2
        if self._hakkinda:
            yukseklik += self.ETIKET_H
        sonuc = max(ROW_H + 6, yukseklik)
        self._boy_onbellek[width] = sonuc
        return sonuc

    def hasHeightForWidth(self) -> bool:
        return True

    def sizeHint(self) -> QSize:
        return QSize(220, self.heightForWidth(max(220, self.width())))

    def minimumSizeHint(self) -> QSize:
        return QSize(160, ROW_H + 6)

    # --- animasyon ---------------------------------------------------------

    def anime_et(self) -> None:
        self._giris = Giris()
        clock().subscribe(self._tick)

    def _tick(self, dt: float) -> None:
        if self._giris is not None:
            self._giris.step(dt)
            if self._giris.done:
                self._giris = None
                clock().unsubscribe(self._tick)
        self.update()

    def hideEvent(self, event) -> None:
        clock().unsubscribe(self._tick)
        super().hideEvent(event)

    # --- çizim -------------------------------------------------------------

    def paintEvent(self, _event) -> None:
        t = self.t
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._giris is not None:
            p.setOpacity(self._giris.opacity)
            p.translate(0, self._giris.offset)

        # Zemin: uyarı renginin çok kısılmış hâli. Dolu bir sarı şerit
        # notu okunur değil bağırır yapardı.
        zemin = QRectF(8, 1, max(0, self.width() - 16), self.height() - 2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(_blend(t.caution, 0.10, t.card)))
        p.drawRoundedRect(zemin, 5, 5)
        p.setBrush(QColor(t.caution))
        p.drawRoundedRect(QRectF(8, 1, 2.5, self.height() - 2), 1.2, 1.2)

        paint_glyph(p, "uyari", 15, t.caution, t.text_tertiary,
                    QPointF(16, self.PAY_Y))

        y = self.PAY_Y
        if self._hakkinda:
            p.setFont(self._etiket_yazisi())
            p.setPen(QColor(t.caution))
            p.drawText(
                QRect(self.METIN_X, y - 1,
                      self.width() - self.METIN_X - self.SAG_PAY,
                      self.ETIKET_H),
                int(Qt.AlignmentFlag.AlignVCenter), self._hakkinda,
            )
            y += self.ETIKET_H

        p.setFont(self._yazi())
        p.setPen(QColor(t.text_secondary))
        p.drawText(
            QRect(self.METIN_X, y,
                  max(40, self.width() - self.METIN_X - self.SAG_PAY),
                  self.height() - y - self.PAY_Y),
            int(Qt.TextFlag.TextWordWrap) | int(Qt.AlignmentFlag.AlignTop),
            self._not,
        )
        p.end()


class Giris:
    """Bir satırın geliş animasyonu.

    Satır aşağıdan hafifçe kayıp beliriyor. Amaç süs değil: dökümde
    satırlar akış hâlinde ekleniyor ve birden beliren bir satır, gözün
    yerini kaybetmesine yol açıyor. Kayarak gelen satır nereden geldiğini
    söylüyor.

    Gecikme yok: satırlar teker teker geliyor, kademelendirilecek bir
    grup yok. Olmayan bir gruba gecikme uydurmak, her satırı boşuna
    bekletmek olurdu.
    """

    SURE = 0.28
    KAYMA = 9.0

    def __init__(self) -> None:
        self._t = Tween(self.SURE, ease_out_expo)

    def step(self, dt: float) -> None:
        self._t.step(dt)

    @property
    def done(self) -> bool:
        return self._t.done

    @property
    def opacity(self) -> float:
        return self._t.value

    @property
    def offset(self) -> float:
        return (1.0 - self._t.value) * self.KAYMA


class Akis(QWidget):
    """Turun dökümü: senin cümlen, ajanın anlattıkları, attığı adımlar.

    Önceden burada yalnızca son cevap duruyordu; ne yaptığını görmek için
    ana pencereye bakman gerekiyordu. Oysa çubuk zaten gözünün olduğu yer.
    Adımlar buraya, her biri kendi çizimiyle düşüyor.

    ## Satır sayısının bir tavanı var, çünkü olmayınca donuyordu

    Uzun bir turdan sonra yukarı kaydırmak tutukluyordu. Ölçtüm:
    kaydırma maliyeti **çocuk widget sayısıyla** artıyor, içerik boyuyla
    değil — aynı 22000 pikselde 1000 çocukla tekerlek adımı 81 ms,
    20 çocukla 3.9 ms. Gerçek dökümde tekerlek adımı 1000 satırda 33 ms,
    yani iki kare.

    İkinci sebep `heightForWidth`in O(n) olması: `CommandBar._fit_reply`
    onu **her satırda** soruyor, yani satır eklemek kareselleşiyordu.

    Önce / sonra (satır ekleme + her satırda `heightForWidth`):

        n     ekleme          satır başı        tekerlek adımı
        20    170 → 45 ms     8.5 → 2.3 ms      0.33 → 0.57 ms
        200   1123 → 352 ms   5.6 → 1.8 ms      2.71 → 0.98 ms
        1000  22919 → 2810 ms 22.9 → 2.8 ms    32.99 → 7.03 ms

    Satır başı süre artık n ile büyümüyor. Düşen satırlar kaybolmuyor:
    tur geçmişi ayrı tutuluyor, düşen yalnızca yüzen çubuğun kopyası.
    Ölçümün tamamı `tests/test_dokum_olcek.py` docstring'inde.
    """

    #: Dökümde tutulan en çok satır. Sınırsızdı; ölçtüğüm donma buydu.
    #:
    #: Kaydırma maliyeti **çocuk widget sayısıyla** artıyor, içerik
    #: boyuyla değil: aynı 22000 pikselde 1000 çocukla tekerlek adımı
    #: 81 ms, 20 çocukla 3.9 ms. 1000 satırlık gerçek bir dökümde adım
    #: 33 ms — iki kare, yani yukarı kaydırma tutukluk olarak görülüyor.
    #: 240 satırda adım 4 ms'in altında kalıyor ve tavanı
    #: (`REPLY_MAX_HEIGHT`) çok aşan bir geçmiş zaten çubukta değil
    #: geçmiş panelinde okunuyor.
    EN_COK_SATIR = 240

    def __init__(self, t: Tokens) -> None:
        super().__init__()
        self.t = t
        self._son_metin: AkanMetin | None = None
        self._son_adim: AdimSatiri | None = None
        # Genişlik başına toplam yükseklik. `heightForWidth` bütün
        # çocukları dolaşıyor ve `_fit_reply` onu her satırda çağırıyor:
        # önbelleksiz satır eklemek kareselleşiyordu — 1000 satır 22.9
        # saniye. Geçersiz kılma `event()` içinde, düzen isteğinde.
        self._boy_onbellek: dict[int, int] = {}
        self._kutu = QVBoxLayout(self)
        self._kutu.setContentsMargins(0, 10, 0, 6)
        self._kutu.setSpacing(2)

    # --- içerik -----------------------------------------------------------

    def clear(self) -> None:
        while self._kutu.count():
            oge = self._kutu.takeAt(0).widget()
            if oge is not None:
                oge.setParent(None)
                oge.deleteLater()
        self._son_metin = None
        self._son_adim = None
        self._boy_onbellek.clear()
        self.updateGeometry()

    def is_empty(self) -> bool:
        return self._kutu.count() == 0

    def add_user(self, metin: str) -> None:
        # Önceki anlatımın imleci sönüyor: iki yerde birden yanıp
        # sönen imleç, ikisinin de yazıldığını söylerdi.
        self.end_stream()
        self._son_metin = None
        self._ekle(AdimSatiri(self.t, "__sen__", "You", metin))

    def add_step(self, tool: str, baslik: str, detay: str) -> None:
        # Önceki anlatımın imleci sönüyor: iki yerde birden yanıp
        # sönen imleç, ikisinin de yazıldığını söylerdi.
        self.end_stream()
        self._son_metin = None
        self._son_adim = AdimSatiri(self.t, tool, baslik, detay)
        self._ekle(self._son_adim)

    def add_note(self, notu: str, hakkinda: str = "") -> None:
        """Ajanın "buna dikkat" notu.

        `_son_adim` güncellenmiyor: not bir adım değil ve bir sonraki
        hata onu kırmızıya çevirmemeli.

        Boş not hiç çizilmiyor: boş bir uyarı şeridi, bakılacak bir şey
        varmış gibi durur. Denetim burada, çağıranda değil — bir gün
        başka bir çağıran eklendiğinde aynı kusur yeniden doğmasın.
        """
        if not (notu or "").strip():
            return
        self.end_stream()
        self._son_metin = None
        self._ekle(NotSatiri(self.t, notu, hakkinda))

    def mark_last(self, is_error: bool) -> None:
        if self._son_adim is not None and is_error:
            self._son_adim.set_tone("hata")

    def stream(self, parca: str) -> None:
        if self._son_metin is None:
            self._son_metin = AkanMetin(self.t)
            self._son_metin.set_live(True)
            self._ekle(self._son_metin)
        self._son_metin.append(parca)
        # Elle geçersiz kılınıyor: çocuğun `updateGeometry` çağrısı düzen
        # isteğini **kuyruğa** koyuyor, çağıran ise `heightForWidth`i
        # hemen soruyor. Olay işlenene kadar bayat boy dönerdi.
        self._boy_onbellek.clear()
        self.updateGeometry()

    def say(self, metin: str) -> None:
        """Akış olmadan tek parça cevap — hata mesajları böyle geliyor."""
        # Önceki anlatımın imleci sönüyor: iki yerde birden yanıp
        # sönen imleç, ikisinin de yazıldığını söylerdi.
        self.end_stream()
        self._son_metin = None
        w = AkanMetin(self.t)
        w.set_text(metin)
        self._ekle(w)

    def end_stream(self) -> None:
        if self._son_metin is not None:
            self._son_metin.set_live(False)

    def text(self) -> str:
        return self._son_metin.text() if self._son_metin else ""

    def _ekle(self, w: QWidget) -> None:
        if hasattr(w, "anime_et"):
            w.anime_et()
        self._kutu.addWidget(w)
        self._buda()
        self._boy_onbellek.clear()
        self.updateGeometry()

    def _buda(self) -> None:
        """Sınırı aşan en eski satırları düşürür.

        Düşürülen satır **kaybolmuyor**: tur geçmişi ayrı tutuluyor ve
        panelde tamamı duruyor. Burada düşen yalnızca yüzen çubuğun
        kendi kopyası. Sessizce kırpmak yerine sınırı burada, tek yerde
        tutuyorum ki neyin neden düştüğü okunabilsin.
        """
        while self._kutu.count() > self.EN_COK_SATIR:
            oge = self._kutu.takeAt(0).widget()
            if oge is None:
                continue
            if oge is self._son_metin:
                self._son_metin = None
            if oge is self._son_adim:
                self._son_adim = None
            # Saatten elle düşürülüyor. `hideEvent`e güvenmek yetmiyor:
            # hiç görünmemiş bir satır `setParent(None)` ile gizlenme
            # olayı almıyor ve abone olarak kalıyordu. Ölçtüm — 600
            # satır eklendikten sonra 240 satırlık dökümde 600 abone
            # duruyordu, ve `Clock.subscribe` her abonelikte listeyi
            # baştan tarıyor: budanmış satırlar aboneliği kareselleştirir.
            tik = getattr(oge, "_tick", None)
            if tik is not None:
                clock().unsubscribe(tik)
            oge.setParent(None)
            oge.deleteLater()

    def event(self, olay) -> bool:
        # Bir çocuk kendi boyunu değiştirdiğinde Qt buraya düzen isteği
        # yolluyor: önbelleği tam orada bırakmak, akan metnin uzadığını
        # görmemek olurdu.
        if olay.type() == QEvent.Type.LayoutRequest:
            self._boy_onbellek.clear()
        return super().event(olay)

    def heightForWidth(self, width: int) -> int:
        if self.is_empty():
            return 0
        onbellekli = self._boy_onbellek.get(width)
        if onbellekli is not None:
            return onbellekli
        toplam = self._kutu.contentsMargins().top() + self._kutu.contentsMargins().bottom()
        for i in range(self._kutu.count()):
            w = self._kutu.itemAt(i).widget()
            if w is None:
                continue
            h = (w.heightForWidth(width) if w.hasHeightForWidth()
                 else w.sizeHint().height())
            toplam += max(h, w.minimumHeight())
            if i:
                toplam += self._kutu.spacing()
        self._boy_onbellek[width] = toplam
        return toplam

    def hasHeightForWidth(self) -> bool:
        return True
