"""Ajanın yaptığı işin çizimi.

Bir adım listesi "Tıklıyor · Kaydediyor · Yazıyor" diye metinle akarken hepsi
birbirine benziyor ve göz nerede olduğunu kaybediyor. Her iş ailesinin kendi
çizimi olduğunda liste okunmadan taranabiliyor: kabuk komutlarının nerede
yoğunlaştığı, hangi adımda dosyaya dokunulduğu bir bakışta görünüyor.

Simge yazı tipi kullanılmıyor. Fluent'in kendi çizim dili burada: 1.6 piksel
kalınlık, yuvarlatılmış uçlar, 24 birimlik ızgara. Her çizimde tek bir öge
vurgu rengiyle boyanıyor — asıl eylemi yapan öge. Tıklamada halka, yazmada
imleç, tabloda değişen hücre. Gerisi çerçeve rengiyle geride duruyor.

Bir hazır simge setini indirip yapıştırmak daha kolaydı ama o setler genel
amaçlı: "dosya" simgesi var, "hücreye formül yazıldı" simgesi yok. Bu
uygulamanın gösterdiği şey tam olarak o ikincisi.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from .fluent import RADIUS_CONTROL, Tokens

#: Çizimler bu ızgarada tanımlı, sonra istenen boyuta ölçekleniyor.
GRID = 24.0

STROKE = 1.7


def _pen(colour: str, width: float = STROKE) -> QPen:
    pen = QPen(QColor(colour), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


# --- tek tek çizimler -----------------------------------------------------
# Her biri 24x24 ızgaraya çiziyor. `ana` vurgu rengi, `sap` çerçeve rengi.


def _goz(p: QPainter, ana: str, sap: str) -> None:
    """Ekrana bakmak: vizör köşeleri ve ortada odak."""
    p.setPen(_pen(sap))
    for x1, y1, x2, y2, x3, y3 in (
        (4, 9, 4, 5, 8, 5), (16, 5, 20, 5, 20, 9),
        (20, 15, 20, 19, 16, 19), (8, 19, 4, 19, 4, 15),
    ):
        path = QPainterPath(QPointF(x1, y1))
        path.lineTo(x2, y2)
        path.lineTo(x3, y3)
        p.drawPath(path)
    p.setPen(_pen(ana))
    p.drawEllipse(QPointF(12, 12), 3.0, 3.0)


def _mercek(p: QPainter, ana: str, sap: str) -> None:
    """Yakınlaştırma: mercek ve içinde büyütülen bölge.

    İçeride eksi işareti vardı ve "uzaklaştır" gibi okunuyordu; bu araç
    bir bölgeyi kırpıp büyütüyor, bölgenin kendisi çiziliyor.
    """
    p.setPen(_pen(sap))
    p.drawLine(QPointF(15.5, 15.5), QPointF(20, 20))
    p.setPen(_pen(ana))
    p.drawEllipse(QPointF(10.5, 10.5), 6.5, 6.5)
    p.drawRect(QRectF(7.5, 7.5, 6, 6))


def _imlec(p: QPainter, ana: str, sap: str) -> None:
    """Tıklama: artı nişan ve yayılan halka."""
    p.setPen(_pen(sap))
    p.drawLine(QPointF(12, 3), QPointF(12, 7))
    p.drawLine(QPointF(12, 17), QPointF(12, 21))
    p.drawLine(QPointF(3, 12), QPointF(7, 12))
    p.drawLine(QPointF(17, 12), QPointF(21, 12))
    p.setPen(_pen(ana))
    p.drawEllipse(QPointF(12, 12), 4.5, 4.5)
    p.setBrush(QColor(ana))
    p.drawEllipse(QPointF(12, 12), 1.5, 1.5)
    p.setBrush(Qt.BrushStyle.NoBrush)


def _surukle(p: QPainter, ana: str, sap: str) -> None:
    """Sürükleme: başlangıç noktası ve ok."""
    p.setPen(_pen(sap))
    p.drawEllipse(QPointF(6, 18), 2.5, 2.5)
    p.setPen(_pen(ana))
    p.drawLine(QPointF(8, 16), QPointF(18, 7))
    path = QPainterPath(QPointF(13, 6))
    path.lineTo(19, 6)
    path.lineTo(19, 12)
    p.drawPath(path)


def _klavye(p: QPainter, ana: str, sap: str) -> None:
    """Yazmak: metin tabanı ve yanıp sönen imleç."""
    p.setPen(_pen(sap))
    p.drawLine(QPointF(4, 9), QPointF(13, 9))
    p.drawLine(QPointF(4, 14), QPointF(10, 14))
    p.drawLine(QPointF(4, 19), QPointF(16, 19))
    p.setPen(_pen(ana, 2.2))
    p.drawLine(QPointF(16, 4), QPointF(16, 15))


def _tus(p: QPainter, ana: str, sap: str) -> None:
    """Tuş kombinasyonu: iki tuş kapağı."""
    p.setPen(_pen(sap))
    p.drawRoundedRect(QRectF(3.5, 7.5, 9, 9), 2, 2)
    p.setPen(_pen(ana))
    p.drawRoundedRect(QRectF(11.5, 11.5, 9, 9), 2, 2)


def _kaydir(p: QPainter, ana: str, sap: str) -> None:
    """Kaydırma: üstte sönük, altta vurgulu çift ok."""
    p.setPen(_pen(sap))
    path = QPainterPath(QPointF(8, 9))
    path.lineTo(12, 5)
    path.lineTo(16, 9)
    p.drawPath(path)
    p.setPen(_pen(ana))
    path = QPainterPath(QPointF(8, 15))
    path.lineTo(12, 19)
    path.lineTo(16, 15)
    p.drawPath(path)


def _pencere(p: QPainter, ana: str, sap: str) -> None:
    """Uygulama açmak: başlık çubuklu pencere."""
    p.setPen(_pen(sap))
    p.drawRoundedRect(QRectF(3.5, 5.5, 17, 14), 2, 2)
    p.drawLine(QPointF(3.5, 10), QPointF(20.5, 10))
    p.setPen(_pen(ana, 2.2))
    p.drawPoint(QPointF(6.5, 7.8))
    p.setPen(_pen(ana))
    p.drawEllipse(QPointF(6.5, 7.8), 1.0, 1.0)


def _kabuk(p: QPainter, ana: str, sap: str) -> None:
    """Komut: istem işareti ve alt çizgi."""
    p.setPen(_pen(sap))
    p.drawRoundedRect(QRectF(3.5, 5.5, 17, 13), 2, 2)
    p.setPen(_pen(ana))
    path = QPainterPath(QPointF(7, 9))
    path.lineTo(10, 12)
    path.lineTo(7, 15)
    p.drawPath(path)
    p.drawLine(QPointF(12.5, 15), QPointF(17, 15))


def _agac(p: QPainter, ana: str, sap: str) -> None:
    """Pencereyi okumak: erişilebilirlik ağacı."""
    p.setPen(_pen(sap))
    p.drawLine(QPointF(7, 6), QPointF(7, 18))
    p.drawLine(QPointF(7, 12), QPointF(12, 12))
    p.drawLine(QPointF(7, 18), QPointF(12, 18))
    p.setPen(_pen(ana))
    p.drawEllipse(QPointF(7, 5), 2.0, 2.0)
    p.drawRoundedRect(QRectF(13, 9.5, 7, 5), 1.5, 1.5)
    p.setPen(_pen(sap))
    p.drawRoundedRect(QRectF(13, 15.5, 7, 5), 1.5, 1.5)


def _sayfa(p: QPainter, ana: str, sap: str) -> None:
    """Dosya: köşesi kıvrık sayfa."""
    p.setPen(_pen(sap))
    path = QPainterPath(QPointF(6, 3.5))
    path.lineTo(14, 3.5)
    path.lineTo(18.5, 8)
    path.lineTo(18.5, 20.5)
    path.lineTo(6, 20.5)
    path.closeSubpath()
    p.drawPath(path)
    path = QPainterPath(QPointF(14, 3.5))
    path.lineTo(14, 8)
    path.lineTo(18.5, 8)
    p.drawPath(path)
    p.setPen(_pen(ana))
    p.drawLine(QPointF(9, 13), QPointF(15.5, 13))
    p.drawLine(QPointF(9, 16.5), QPointF(13, 16.5))


def _klasor(p: QPainter, ana: str, sap: str) -> None:
    p.setPen(_pen(sap))
    path = QPainterPath(QPointF(3.5, 18.5))
    path.lineTo(3.5, 6.5)
    path.lineTo(9, 6.5)
    path.lineTo(11, 9)
    path.lineTo(20.5, 9)
    path.lineTo(20.5, 18.5)
    path.closeSubpath()
    p.drawPath(path)
    p.setPen(_pen(ana))
    p.drawLine(QPointF(3.5, 12.5), QPointF(20.5, 12.5))


def _tablo(p: QPainter, ana: str, sap: str) -> None:
    """Hesap tablosu: başlık satırı ve değişen tek hücre.

    Önce 3x3 ızgaraydı; 38 pikselde hücreler 4 piksele düşüyor ve dolu
    hücre ızgaranın içinde kayboluyordu. İki bölme, dolu hücreyi görünür
    kılacak kadar büyük tutuyor.
    """
    p.setPen(_pen(sap))
    p.drawRoundedRect(QRectF(3.5, 4.5, 17, 15), 2, 2)
    p.drawLine(QPointF(3.5, 9.5), QPointF(20.5, 9.5))
    p.drawLine(QPointF(12, 9.5), QPointF(12, 19.5))
    p.setBrush(QColor(ana))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRect(QRectF(12.6, 10.1, 7.3, 8.8))
    p.setBrush(Qt.BrushStyle.NoBrush)


def _yazi(p: QPainter, ana: str, sap: str) -> None:
    """Metin belgesi: paragraflar, biri vurgulu."""
    p.setPen(_pen(sap))
    p.drawLine(QPointF(4, 6), QPointF(20, 6))
    p.drawLine(QPointF(4, 10), QPointF(17, 10))
    p.drawLine(QPointF(4, 18), QPointF(20, 18))
    p.setPen(_pen(ana, 2.4))
    p.drawLine(QPointF(4, 14), QPointF(14, 14))


def _kaydet(p: QPainter, ana: str, sap: str) -> None:
    """Kaydetmek: aşağı ok ve zemin."""
    p.setPen(_pen(sap))
    p.drawLine(QPointF(5, 19.5), QPointF(19, 19.5))
    p.setPen(_pen(ana))
    p.drawLine(QPointF(12, 4), QPointF(12, 15))
    path = QPainterPath(QPointF(7.5, 10.5))
    path.lineTo(12, 15)
    path.lineTo(16.5, 10.5)
    p.drawPath(path)


def _defter(p: QPainter, ana: str, sap: str) -> None:
    """Değişiklik geçmişi: zaman çizgisi."""
    p.setPen(_pen(sap))
    p.drawLine(QPointF(7, 4), QPointF(7, 20))
    for y in (7, 17):
        p.drawEllipse(QPointF(7, y), 2.0, 2.0)
        p.drawLine(QPointF(11, y), QPointF(19, y))
    p.setPen(_pen(ana))
    p.setBrush(QColor(ana))
    p.drawEllipse(QPointF(7, 12), 2.4, 2.4)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawLine(QPointF(11, 12), QPointF(19, 12))


def _yetenek(p: QPainter, ana: str, sap: str) -> None:
    """Ajanın kendine yazdığı yetenek: kıvılcım.

    Bu çizim bilerek diğerlerinden farklı — ajanın *kendi* eklediği bir şey
    olduğu listeye bakarken anlaşılmalı.
    """
    p.setPen(_pen(sap))
    p.drawRoundedRect(QRectF(3.5, 3.5, 17, 17), 3, 3)
    p.setPen(_pen(ana, 1.9))
    path = QPainterPath(QPointF(12, 6))
    path.lineTo(13.6, 10.4)
    path.lineTo(18, 12)
    path.lineTo(13.6, 13.6)
    path.lineTo(12, 18)
    path.lineTo(10.4, 13.6)
    path.lineTo(6, 12)
    path.lineTo(10.4, 10.4)
    path.closeSubpath()
    p.drawPath(path)


def _bekle(p: QPainter, ana: str, sap: str) -> None:
    p.setPen(_pen(sap))
    p.drawEllipse(QPointF(12, 12), 8.0, 8.0)
    p.setPen(_pen(ana, 2.0))
    p.drawLine(QPointF(12, 12), QPointF(12, 7.5))
    p.drawLine(QPointF(12, 12), QPointF(15.5, 13.5))


def _yukari(p: QPainter, ana: str, sap: str) -> None:
    """Üst klasöre çık."""
    p.setPen(_pen(sap))
    p.drawLine(QPointF(12, 20), QPointF(12, 6))
    p.setPen(_pen(ana))
    path = QPainterPath(QPointF(6, 12))
    path.lineTo(12, 6)
    path.lineTo(18, 12)
    p.drawPath(path)


def _yenile(p: QPainter, ana: str, sap: str) -> None:
    """Yeniden oku. Neredeyse tam bir çember ve bir ok ucu; kapalı çember
    dönmeyi değil beklemeyi anlatırdı."""
    p.setPen(_pen(ana))
    path = QPainterPath()
    path.arcMoveTo(QRectF(4.5, 4.5, 15, 15), 60)
    path.arcTo(QRectF(4.5, 4.5, 15, 15), 60, 300)
    p.drawPath(path)
    p.setPen(_pen(sap))
    uc = QPainterPath(QPointF(11.5, 3.5))
    uc.lineTo(16.2, 6.2)
    uc.lineTo(13.4, 10.6)
    p.drawPath(uc)


def _sunucu(p: QPainter, ana: str, sap: str) -> None:
    """Uzak makine: üst üste iki raf ve durum ışığı."""
    p.setPen(_pen(sap))
    p.drawRoundedRect(QRectF(3.5, 4.5, 17, 6), 1.5, 1.5)
    p.drawRoundedRect(QRectF(3.5, 13.5, 17, 6), 1.5, 1.5)
    p.setPen(_pen(ana))
    p.setBrush(QColor(ana))
    p.drawEllipse(QPointF(7, 7.5), 1.3, 1.3)
    p.drawEllipse(QPointF(7, 16.5), 1.3, 1.3)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawLine(QPointF(11, 7.5), QPointF(17, 7.5))
    p.drawLine(QPointF(11, 16.5), QPointF(17, 16.5))


def _sen(p: QPainter, ana: str, sap: str) -> None:
    """Berkay'ın yazdığı satır: konuşma balonu."""
    p.setPen(_pen(ana))
    path = QPainterPath(QPointF(6, 19))
    path.lineTo(6, 20.5)
    path.lineTo(9.5, 17.5)
    p.drawPath(path)
    p.drawRoundedRect(QRectF(3.5, 4.5, 17, 13), 3, 3)
    p.setPen(_pen(sap))
    p.drawLine(QPointF(7, 9), QPointF(17, 9))
    p.drawLine(QPointF(7, 13), QPointF(13, 13))


def _soru(p: QPainter, ana: str, sap: str) -> None:
    p.setPen(_pen(sap))
    p.drawEllipse(QPointF(12, 12), 8.0, 8.0)
    p.setPen(_pen(ana, 2.0))
    path = QPainterPath(QPointF(9.5, 9.5))
    path.cubicTo(9.5, 6.5, 14.5, 6.5, 14.5, 9.8)
    path.cubicTo(14.5, 12.2, 12, 12.2, 12, 14.5)
    p.drawPath(path)
    p.drawPoint(QPointF(12, 17.5))
    p.drawEllipse(QPointF(12, 17.6), 0.7, 0.7)


def _gecmis(p: QPainter, ana: str, sap: str) -> None:
    """Geçmiş: saat kadranı ve geriye dönen ok.

    Kadran çerçeve rengiyle, akrep-yelkovan vurguyla: geçmişte aranan şey
    "ne zaman"dan çok "hangi an" oluyor.
    """
    p.setPen(_pen(sap))
    yay = QPainterPath()
    # Ok için üstte bir boşluk bırakılıyor; tam daire çizip üstüne ok
    # koymak iki çizgiyi üst üste bindiriyor ve leke yapıyor.
    yay.arcMoveTo(QRectF(4, 4, 16, 16), 110)
    yay.arcTo(QRectF(4, 4, 16, 16), 110, -320)
    p.drawPath(yay)
    ok = QPainterPath(QPointF(5.6, 4.6))
    ok.lineTo(6.9, 8.2)
    ok.lineTo(10.5, 6.9)
    p.drawPath(ok)
    p.setPen(_pen(ana))
    p.drawLine(QPointF(12, 8.5), QPointF(12, 12))
    p.drawLine(QPointF(12, 12), QPointF(15, 13.6))


def _akis(p: QPainter, ana: str, sap: str) -> None:
    """Kaydedilmiş dizi: birbirine bağlı üç adım, ilki vurgulu.

    "Tekrar" oku değil: tekrar zaten `yenile`nin işi ve akışın anlattığı
    şey tekrar etmek değil, **sıra**.
    """
    p.setPen(_pen(sap))
    p.drawLine(QPointF(7, 6.5), QPointF(17, 6.5))
    p.drawLine(QPointF(7, 12), QPointF(17, 12))
    p.drawLine(QPointF(7, 17.5), QPointF(14, 17.5))
    p.setPen(_pen(ana))
    p.setBrush(QColor(ana))
    for y in (6.5, 12.0, 17.5):
        p.drawEllipse(QPointF(4, y), 1.5, 1.5)
    p.setBrush(Qt.BrushStyle.NoBrush)


def _fis(p: QPainter, ana: str, sap: str) -> None:
    """Dış sunucu: fiş. İki uç, gövde, ve aşağı inen kablo.

    Vurgu uçlarda: bağlantıyı yapan şey onlar ve bu çizimin anlattığı
    şey de bağlanmak — aracın ne yaptığı değil, **nereden geldiği**.
    """
    p.setPen(_pen(ana))
    p.drawLine(QPointF(9, 3.5), QPointF(9, 8))
    p.drawLine(QPointF(15, 3.5), QPointF(15, 8))
    p.setPen(_pen(sap))
    p.drawRoundedRect(QRectF(6.5, 8, 11, 7), 2, 2)
    yol = QPainterPath(QPointF(12, 15))
    yol.lineTo(12, 17.5)
    yol.cubicTo(12, 20.5, 8.5, 19.5, 8.5, 21.5)
    p.drawPath(yol)


def _uyari(p: QPainter, ana: str, sap: str) -> None:
    """Dikkat notu: üçgen ve ünlem.

    Ünlem vurgu renginde, üçgen çerçeve renginde. Tersi denendi ve
    yanlıştı: dolu kırmızı bir üçgen "bir şey bozuldu" diyor, oysa bu
    satır bir hata değil, ajanın kendi uyarısı.
    """
    p.setPen(_pen(sap))
    yol = QPainterPath(QPointF(12, 4.2))
    yol.lineTo(21, 19.4)
    yol.lineTo(3, 19.4)
    yol.closeSubpath()
    p.drawPath(yol)
    p.setPen(_pen(ana, 2.0))
    p.drawLine(QPointF(12, 10), QPointF(12, 14.4))
    p.setBrush(QColor(ana))
    p.drawEllipse(QPointF(12, 17.2), 0.9, 0.9)
    p.setBrush(Qt.BrushStyle.NoBrush)


#: Araç adı -> çizim. Aile bazında, araç bazında değil: on yedi tıklama
#: aracının hepsi aynı işi yapıyor ve on yedi ayrı çizim gürültü olurdu.
def _kayit(p: QPainter, ana: str, sap: str) -> None:
    """Kayıt. Dolu bir daire ve çevresinde bir halka.

    Kamera çizmek daha anlatıcı olurdu ama 24 pikselde kamera bir kutuya
    dönüyor ve `pencere` çiziminden ayırt edilemiyor. Dolu daire kayıt
    düğmesinin evrensel dili; halka onu `imlec`in ucundan ve durum
    ışığından ayırıyor.
    """
    p.setPen(_pen(sap))
    p.drawEllipse(QPointF(12, 12), 8.0, 8.0)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(ana))
    p.drawEllipse(QPointF(12, 12), 4.2, 4.2)
    p.setBrush(Qt.BrushStyle.NoBrush)


def _kayit_dur(p: QPainter, ana: str, sap: str) -> None:
    """Kaydı durdur. Aynı halka, içinde daire yerine kare.

    Kayıt ve durdurma yan yana bir dökümde okunuyor; ikisi de daire
    olsaydı satırlar birbirinin aynısı görünürdü.
    """
    p.setPen(_pen(sap))
    p.drawEllipse(QPointF(12, 12), 8.0, 8.0)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(ana))
    p.drawRect(QRectF(8.6, 8.6, 6.8, 6.8))
    p.setBrush(Qt.BrushStyle.NoBrush)


GLYPHS = {
    "kayit": _kayit, "kayit_dur": _kayit_dur,
    "goz": _goz, "mercek": _mercek, "imlec": _imlec, "surukle": _surukle,
    "klavye": _klavye, "tus": _tus, "kaydir": _kaydir, "pencere": _pencere,
    "kabuk": _kabuk, "agac": _agac, "sayfa": _sayfa, "klasor": _klasor,
    "tablo": _tablo, "yazi": _yazi, "kaydet": _kaydet, "defter": _defter,
    "yetenek": _yetenek, "bekle": _bekle, "sen": _sen, "soru": _soru,
    "yukari": _yukari, "yenile": _yenile, "sunucu": _sunucu,
    "gecmis": _gecmis, "akis": _akis, "fis": _fis,
    "uyari": _uyari,
}

TOOL_GLYPH = {
    "screenshot": "goz", "zoom": "mercek", "cursor_position": "imlec",
    "left_click": "imlec", "right_click": "imlec", "middle_click": "imlec",
    "double_click": "imlec", "triple_click": "imlec", "mouse_move": "imlec",
    "left_mouse_down": "imlec", "left_mouse_up": "imlec",
    "left_click_drag": "surukle",
    "type": "klavye", "key": "tus", "hold_key": "tus", "scroll": "kaydir",
    "wait": "bekle",
    "read_ui_tree": "agac", "switch_display": "goz",
    "launch_app": "pencere", "run_shell": "kabuk",
    "terminal_open": "kabuk", "terminal_send": "kabuk",
    "terminal_read": "kabuk", "terminal_close": "kabuk",
    "write_file": "sayfa", "read_file": "sayfa", "edit_file": "sayfa",
    "list_dir": "klasor",
    "office_open": "tablo", "office_read": "tablo", "office_edit": "tablo",
    "office_close": "tablo",
    "office_save": "kaydet", "office_history": "defter",
    "skill_list": "yetenek", "skill_write": "yetenek", "skill_remove": "yetenek",
    "remote_connect": "sunucu", "remote_list": "sunucu",
    "remote_read": "sunucu", "remote_write": "sunucu", "remote_run": "sunucu",
    "write_files": "klasor", "list_apps": "pencere",
    "button_write": "yetenek", "button_remove": "yetenek",
    "side_launch": "pencere", "side_windows": "pencere",
    "side_capture": "mercek", "side_act": "imlec", "side_close": "pencere",
    "record_start": "kayit", "record_stop": "kayit_dur",
    "workflow_save": "akis", "workflow_list": "akis",
    "workflow_remove": "akis", "workflow_run": "yenile",
    "heads_up": "uyari",
    "__sen__": "sen", "__onay__": "soru",
}


def glyph_for(tool: str) -> str:
    """Bilinmeyen araç — yetenekler dâhil — kıvılcımla gösteriliyor."""
    if tool.startswith("mcp__"):
        # Dış sunucudan gelen araç: fiş çizimi. Yeteneklerle aynı
        # görünseydi ajanın kendi yazdığı kodla üçüncü tarafın kodu
        # akışta ayırt edilemezdi.
        return "fis"
    return TOOL_GLYPH.get(tool, "yetenek")


def paint_glyph(painter: QPainter, key: str, size: float,
                ana: str, sap: str, origin: QPointF | None = None) -> None:
    """Çizimi istenen boyutta boyar. Ölçek 24 birimlik ızgaradan."""
    draw = GLYPHS.get(key) or _yetenek
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    if origin is not None:
        painter.translate(origin)
    factor = size / GRID
    painter.scale(factor, factor)
    # Kalınlık ölçekle birlikte incelmesin: 12 pikselde 0.85 piksel çizgi
    # yarı saydam bir hayalet olarak çıkıyor.
    painter.setPen(_pen(sap, STROKE / factor if factor < 1 else STROKE))
    draw(painter, ana, sap)
    painter.restore()


def glyph_icon(key: str, size: int, ana: str, sap: str) -> QIcon:
    """Çizimi liste ve açılır kutularda kullanılabilir bir simgeye çevirir."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    paint_glyph(painter, key, size, ana, sap, QPointF(0, 0))
    painter.end()
    return QIcon(pixmap)


class WorkGlyph(QWidget):
    """Bir adımın çizimi, yuvarlatılmış bir karonun içinde."""

    def __init__(self, t: Tokens, tool: str = "screenshot", size: int = 38) -> None:
        super().__init__()
        self.t = t
        self._key = glyph_for(tool)
        self._tone = "normal"
        self.setFixedSize(size, size)

    def set_tool(self, tool: str) -> None:
        self._key = glyph_for(tool)
        self.update()

    def set_tone(self, tone: str) -> None:
        """`normal`, `hata`, `onay`. Hata kırmızıya döner — bir adımın
        başarısız olduğu, metni okumadan görünmeli."""
        self._tone = tone
        self.update()

    def paintEvent(self, _event) -> None:
        t = self.t
        ana = {"hata": t.critical, "onay": t.caution}.get(self._tone, t.accent)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        wash = QColor(ana)
        wash.setAlpha(30)
        painter.setBrush(wash)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(
            QRectF(0.5, 0.5, self.width() - 1, self.height() - 1),
            RADIUS_CONTROL + 2, RADIUS_CONTROL + 2,
        )

        inset = self.width() * 0.21
        paint_glyph(
            painter, self._key, self.width() - inset * 2,
            ana, t.text_secondary, QPointF(inset, inset),
        )
        painter.end()


class PreviewFrame(QWidget):
    """Komut çubuğundaki önizleme karesi.

    Ekran görüntüsü varsa o görünüyor. Yoksa — dosya yazmak, formül
    hesaplamak, yetenek kurmak gibi ekranda karşılığı olmayan işlerde — o
    işin çizimi görünüyor. Önceki hâli "görüntü yok" yazıyordu: dürüsttü ama
    bakacak bir şey vermiyordu ve işlerin çoğunda ekran görüntüsü yok.
    """

    def __init__(self, t: Tokens, width: int = 84, height: int = 52) -> None:
        super().__init__()
        self.t = t
        self._pixmap = None
        self._key = "goz"
        self._tone = "normal"
        self.setFixedSize(width, height)

    def show_tool(self, tool: str, pixmap=None, tone: str = "normal") -> None:
        self._key = glyph_for(tool)
        self._pixmap = pixmap
        self._tone = tone
        self.update()

    def clear(self) -> None:
        self._pixmap = None
        self.update()

    def paintEvent(self, _event) -> None:
        t = self.t
        ana = {"hata": t.critical, "onay": t.caution}.get(self._tone, t.accent)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        frame = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)

        path = QPainterPath()
        path.addRoundedRect(frame, RADIUS_CONTROL, RADIUS_CONTROL)
        painter.setClipPath(path)

        if self._pixmap is not None and not self._pixmap.isNull():
            scaled = self._pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(
                (self.width() - scaled.width()) // 2,
                (self.height() - scaled.height()) // 2,
                scaled,
            )
        else:
            wash = QColor(ana)
            wash.setAlpha(26)
            painter.fillRect(frame, wash)
            size = min(self.width(), self.height()) * 0.62
            paint_glyph(
                painter, self._key, size, ana, t.text_secondary,
                QPointF((self.width() - size) / 2, (self.height() - size) / 2),
            )

        painter.setClipping(False)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(t.stroke), 1))
        painter.drawRoundedRect(frame, RADIUS_CONTROL, RADIUS_CONTROL)
        painter.end()
