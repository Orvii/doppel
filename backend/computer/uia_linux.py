"""AT-SPI2 erişilebilirlik ağacı — Linux'un UIA karşılığı.

Windows arka ucu `uia.py`; bu dosya aynı sözleşmenin AT-SPI2 (D-Bus)
karşılığı: `anlik_gorunum` modelin okuduğu metin anlık görüntüsünü,
`odak_ozeti` eylem öncesi/sonrası karşılaştırmayı, `etiket_noktada`
güvenlik kapısının tıklanan denetim etiketini üretir.

pyatspi toleranslı içe aktarılır (pip'ten kurulamıyor; apt paketi
`python3-pyatspi` + oturum veri yolu). Kurulu değilse modül yine içe
aktarılabilir kalır, ama çağrı anında `AtsPiyokHatasi` ile AÇIK hata
verir — sessizce boş ağaç döndürmek, "erişilebilirlik yok"u "pencere
boş" gibi gösterirdi.

Maliyet farkı UIA'ya göre temel: UIA süreç içi COM (~6 ms ölçüldü).
AT-SPI'de her özellik okuması D-Bus üzerinden hedef uygulamaya gidip
dönüyor ve cevap vermeyen bir uygulama turu blokluyor; bu yüzden
derinlik/düğüm tavanı `uia.py` ile aynı disiplinde, her düğüm okuması
kendi `try`ında ve bir düğümün ölümcül hatası ağacın kalanını almıyor.
"""

from __future__ import annotations

from dataclasses import dataclass

from .displays import Display

try:  # pyatspi pip'ten kurulamıyor; apt paketi ya da hiç yok
    import pyatspi  # type: ignore[import-not-found]
except ImportError:  # Windows'ta ve pyatspi'siz Linux'ta: yok say
    pyatspi = None  # type: ignore[assignment]


class AtsPiyokHatasi(RuntimeError):
    """AT-SPI (pyatspi ya da oturum veri yolu) bu makinede kullanılamıyor."""


#: Tıklanabilir ya da okunmaya değer denetim türleri — `uia.py`'deki
#: INTERESTING ile aynı sözlük. Modele iki platformda aynı kelimeler
#: görünsün diye AT-SPI rollerı aşağıdaki tabloyla bunlara çevriliyor.
ILGINC_TURLER = {
    "Button", "CheckBox", "ComboBox", "Edit", "Document", "Hyperlink",
    "ListItem", "MenuItem", "RadioButton", "Slider", "SplitButton", "Tab",
    "TabItem", "Text", "TreeItem", "ToolBar", "Window", "Spinner",
}

#: AT-SPI rol adı -> UIA türü. Karşılığı olmayan rol (panel, filler,
#: table...) kapsayıcı sayılıyor: kendisi yazılmıyor, yalnızca içi
#: geziliyor — yoksa çıktının yarısı yapısal gürültü oluyor.
ROLLER = {
    "push button": "Button",
    "toggle button": "Button",
    "check box": "CheckBox",
    "combo box": "ComboBox",
    "entry": "Edit",
    "text": "Text",
    "label": "Text",
    "link": "Hyperlink",
    "list item": "ListItem",
    "menu item": "MenuItem",
    "check menu item": "MenuItem",
    "radio menu item": "MenuItem",
    "radio button": "RadioButton",
    "slider": "Slider",
    "spin button": "Spinner",
    "page tab": "TabItem",
    "page tab list": "Tab",
    "tree item": "TreeItem",
    "tool bar": "ToolBar",
    "frame": "Window",
    "dialog": "Window",
    "document frame": "Document",
    "document text": "Document",
}

MAX_DERINLIK = 12
MAX_DUGUM = 220

#: Bu sayının altında düğüm çıkarsa ağaç güvenilmez sayılıp modele
#: "ekran görüntüsü al" denecek (`uia.py` ile aynı eşik).
INCE_ALTI = 4

#: odak ve etiket aramalarının ayrı tavanları: ikisi de tek bir soru için
#: tüm ağacı gezmemeli (her düğüm en az bir D-Bus turu demek).
MAX_ARAMA_DERINLIK = 24
MAX_ODAK_DUGUM = 400
MAX_ETIKET_DUGUM = 600

#: Masaüstü taramasının sınırları: kaç uygulama, uygulama başına kaç çocuk.
MAX_UYGULAMA = 64
MAX_PENCERE = 16

#: Odak özetindeki değer alanının sınırı — `uia.py`'deki ODAK_SINIRI ile
#: aynı sayı ve aynı gerekçe (eylem başına iki okuma, sınırsız olamaz).
ODAK_SINIRI = 200


@dataclass
class GorunumSonucu:
    """`uia.SnapshotResult` ile aynı alanlar — çağıran ikisini ayırt etmiyor."""

    text: str
    node_count: int
    window_title: str

    @property
    def thin(self) -> bool:
        return self.node_count < INCE_ALTI


@dataclass(frozen=True)
class Etiket:
    """Güvenlik kapısına giden cevap; iki hâli AYRI tutar.

    `metin` okunan etiket (boş olabilir: denetim var, adı yok).
    `okunabilir=False` ise erişilebilirlik katmanı soruya hiç cevap
    veremedi — bu "etiket yok" DEĞİL, "soru sorulamadı" demektir. Kapı bu
    ayrımı korumak zorunda, yoksa okunamayan bir hedefe tıklama sessizce
    SAFE sayılır.
    """

    metin: str = ""
    okunabilir: bool = True


def musait() -> bool:
    """AT-SPI bu oturumda kullanılabilir mi — veri yoluna sorar, ağacı gezmez.

    Yalnızca ucuz yoklama: pyatspi içe aktarılabilir VE masaüstü nesnesi
    alınabiliyor (oturum veri yolu açık). Ne uygulama sayısına ne pencere
    varlığına bakıyor: erişilebilirlik açık ama hiç pencere yoksa cevap
    yine True, "pencere yok" ayrı bir bilgi.
    """
    if pyatspi is None:
        return False
    try:
        return pyatspi.Registry.getDesktop(0) is not None
    except Exception:
        return False


def anlik_gorunum(
    maks_derinlik: int = MAX_DERINLIK,
    maks_dugum: int = MAX_DUGUM,
    ekran: Display | None = None,
) -> GorunumSonucu:
    """Ön plandaki pencerenin AT-SPI ağacını metne çevirir.

    `ekran` verilirse koordinatlar `uia.py` ile tam aynı sözleşmeden
    geçiyor: ekran dışı düğüm atılıyor, merkez **model uzayına** çevriliyor.
    Verilmezse ham AT-SPI masaüstü koordinatı yazılıyor (tüm X ekranı) —
    tek monitörlü kurulumda ikisi aynı sayı.

    pyatspi yoksa ya da veri yolu cevap vermiyorsa `AtsPiyokHatasi`: boş
    ağaç döndürmek, kurulum eksikliğini "pencere boş" gibi gösterirdi.
    """
    _gerekli()
    try:
        pencere = _aktif_pencere()
    except Exception:
        raise AtsPiyokHatasi(
            "there is no accessibility bus in this session — AT-SPI needs a "
            "session bus (run under dbus-run-session) and a desktop that "
            "exports AT-SPI"
        ) from None

    if pencere is None:
        return GorunumSonucu(
            text="There is no foreground window.", node_count=0, window_title=""
        )

    baslik = str(_ad(pencere))
    satirlar: list[str] = []
    durum = {"sayi": 0, "kesildi": False}
    _gez(pencere, ekran, 0, maks_derinlik, maks_dugum, satirlar, durum)

    if durum["kesildi"]:
        satirlar.append(f"... truncated at {maks_dugum} nodes")

    bas = f"Window: {baslik!r} (display {ekran.index})" if ekran else f"Window: {baslik!r}"
    govde = "\n".join(satirlar) if satirlar else "(no readable controls)"
    return GorunumSonucu(
        text=f"{bas}\n{govde}", node_count=durum["sayi"], window_title=baslik
    )


def odak_ozeti() -> tuple[str, str, str] | None:
    """Odaktaki denetimin (tür, ad, değer) özeti — okunamazsa `None`.

    `uia.py` ile aynı sözleşme ve aynı "None" anlamı: "değişiklik yok"
    değil, "bu bileşen karşılaştırılamadı". pyatspi yokluğu da buraya
    düşüyor — döngü zaten `None`u okunamama sayıp doğrulama üretmiyor,
    bu yüzden ayrı bir istisna türü burada fayda değil gürültü olurdu.
    """
    if pyatspi is None:
        return None
    try:
        butce = [MAX_ODAK_DUGUM]
        for pencere in _pencereler():
            dugum = _odak_ara(pencere, butce, 0)
            if dugum is None:
                continue
            tur = _uia_turu(dugum) or _ham_rol(dugum)
            return (tur[:40], str(_ad(dugum))[:80], _deger_oku(dugum, tur)[:ODAK_SINIRI])
        return None
    except Exception:
        return None


def etiket_noktada(vx: int, vy: int) -> Etiket:
    """(Sanal) noktadaki denetimin etiketi — güvenlik kapısının girdisi.

    Erişilebilirlik katmanı cevap veremediğinde `okunabilir=False` dönüyor
    ve kapı bunu SAFE sayamaz; "noktada adı olan denetim yok" ise boş ama
    okunabilir bir cevap. Pencere çerçevesinin kendi başlığı etiket
    sayılmıyor: başlık kapıya ayrı bir alan olarak zaten gidiyor.
    """
    if pyatspi is None:
        return Etiket("", False)
    try:
        pencereler = _pencereler()
    except Exception:
        return Etiket("", False)
    if not pencereler:
        return Etiket("", False)

    durum: dict = {"kalan": MAX_ETIKET_DUGUM, "kutu_okunur": False,
                   "en_iyi": None, "alan": None}
    for pencere in pencereler:
        _etiket_gez(pencere, int(vx), int(vy), 0, durum)
        if durum["kalan"] <= 0:
            break

    if durum["en_iyi"] is None:
        # Kutu hiç okunamadıysa soru cevaplanamadı; okunduysa cevap
        # "burada adı olan denetim yok".
        return Etiket("", bool(durum["kutu_okunur"]))
    return Etiket(str(durum["en_iyi"])[:120], True)


# --- AT-SPI ağacına ince sarmalayıcılar ---------------------------------------
#
# Hepsi tek bir düğümün okunması ve hepsi kendi hatasını yutuyor: bir
# uygulama gezinme sırasında kapanabiliyor ve o düğüm yüzünden ağacın
# kalanını kaybetmek, `uia.py`'nin ilk sürümünde zaten bir kez pahalıya
# mal oldu.


def _gerekli() -> None:
    if pyatspi is None:
        raise AtsPiyokHatasi(
            "AT-SPI is not available: pyatspi is not installed. Install "
            "python3-pyatspi (at-spi2-core), and run the agent inside a "
            "session bus (dbus-run-session)."
        )


def _ad(dugum) -> str:
    try:
        return str(dugum.name or "")
    except Exception:
        return ""


def _ham_rol(dugum) -> str:
    try:
        return str(dugum.getRoleName() or "").strip().lower()
    except Exception:
        return ""


def _uia_turu(dugum) -> str:
    return ROLLER.get(_ham_rol(dugum), "")


def _durum_var(dugum, bayrak) -> bool:
    try:
        return bool(dugum.getState().contains(bayrak))
    except Exception:
        return False


def _cocuklar(dugum, sinir: int) -> list:
    """Alt düğümler; okunamayan çocuk atlanıyor, liste asla patlamıyor."""
    out: list = []
    try:
        sayi = int(dugum.getChildCount())
    except Exception:
        return out
    for i in range(min(sayi, sinir)):
        try:
            cocuk = dugum.getChildAtIndex(i)
        except Exception:
            continue
        if cocuk is not None:
            out.append(cocuk)
    return out


def _kutu(dugum) -> tuple[int, int, int, int] | None:
    """(sol, üst, sağ, alt) AT-SPI masaüstü koordinatında; yoksa None.

    Component arayüzü olmayan düğüm (saf metin parçası) ve gizli/daraltılmış
    denetim (sıfır boyut) None dönüyor — ikisi de yazılmaz.
    """
    if pyatspi is None:
        return None
    try:
        ham = dugum.queryComponent().getExtents(pyatspi.DESKTOP_COORDS)
        x, y, en, boy = int(ham[0]), int(ham[1]), int(ham[2]), int(ham[3])
    except Exception:
        return None
    if en <= 0 or boy <= 0:
        return None
    return (x, y, x + en, y + boy)


def _deger_oku(dugum, tur: str) -> str:
    """Metin kutularının içeriği — modele "yazdım mı" kanıtı (`uia.py` gibi
    yalnızca Edit türünde okunuyor; diğer türlerde değer kavramı yok)."""
    if tur != "Edit":
        return ""
    for sorgu in ("queryEditableText", "queryText"):
        try:
            arayuz = getattr(dugum, sorgu)()
            return str(arayuz.getText(0, -1) or "")
        except Exception:
            continue
    return ""


def _pencereler() -> list:
    """Masaüstündeki üst düzey pencereler; aktif olan başta.

    Önce ön plandaki pencere yazılıyor: model "şu an ekranda ne var"
    sorusunun cevabını istiyor. Sıra aktif > görünür > gerisi; eşitlikte
    keşif sırası korunuyor (sıralama kararlı).
    """
    masaustu = pyatspi.Registry.getDesktop(0)
    pencereler: list = []
    for uygulama in _cocuklar(masaustu, MAX_UYGULAMA):
        if _ham_rol(uygulama) in ("frame", "dialog"):
            # Bazı uygulamalar pencereyi doğrudan masaüstüne veriyor.
            pencereler.append(uygulama)
            continue
        for cocuk in _cocuklar(uygulama, MAX_PENCERE):
            if _ham_rol(cocuk) in ("frame", "dialog"):
                pencereler.append(cocuk)

    def sira(pencere) -> int:
        if _durum_var(pencere, pyatspi.STATE_ACTIVE):
            return 0
        if _durum_var(pencere, pyatspi.STATE_SHOWING):
            return 1
        return 2

    return sorted(pencereler, key=sira)


def _aktif_pencere():
    pencereler = _pencereler()
    return pencereler[0] if pencereler else None


def _gez(dugum, ekran: Display | None, derinlik: int, maks_derinlik: int,
         maks_dugum: int, satirlar: list[str], durum: dict) -> None:
    """`uia.py::_walk` ile aynı disiplin: sayaç yalnızca yazılan satırı
    sayar, kapsayıcı düğüm kendini yazmaz ama girintiyi de artırmaz."""
    if derinlik > maks_derinlik:
        return
    if durum["sayi"] >= maks_dugum:
        durum["kesildi"] = True
        return

    for cocuk in _cocuklar(dugum, maks_dugum):
        if durum["sayi"] >= maks_dugum:
            durum["kesildi"] = True
            return
        satir = _satir(cocuk, ekran)
        if satir is not None:
            satirlar.append("  " * derinlik + satir)
            durum["sayi"] += 1
            _gez(cocuk, ekran, derinlik + 1, maks_derinlik, maks_dugum,
                 satirlar, durum)
        else:
            _gez(cocuk, ekran, derinlik, maks_derinlik, maks_dugum,
                 satirlar, durum)


def _satir(dugum, ekran: Display | None) -> str | None:
    """Tek düğümün çıktı satırı; gösterilmeyecekse None (`uia.py::_describe`)."""
    tur = _uia_turu(dugum)
    if tur not in ILGINC_TURLER:
        return None

    kutu = _kutu(dugum)
    if kutu is None:
        return None

    ad = _ad(dugum).strip()
    left, top, right, bottom = kutu
    vx, vy = (left + right) // 2, (top + bottom) // 2
    if ekran is not None:
        if not ekran.contains_virtual(vx, vy):
            return None  # başka ekranda ya da ekran dışında
        x, y = ekran.from_virtual(vx, vy)
    else:
        x, y = vx, vy

    try:
        etkin = bool(dugum.getState().contains(pyatspi.STATE_ENABLED))
    except Exception:
        # Durum okunamadıysa [pasif] damgası vurulmuyor: yanlış "pasif"
        # demek, damgayı görmezden gelinir hâle getirirdi.
        etkin = True

    etiket = f'"{ad[:70]}"' if ad else "(unnamed)"
    son_ek = "" if etkin else " [pasif]"

    deger = _deger_oku(dugum, tur)
    if deger:
        etiket += f" = {deger[:60]!r}"

    return f"{tur} {etiket} [{x},{y}]{son_ek}"


def _odak_ara(dugum, butce: list[int], derinlik: int):
    """En derindeki odaklı düğüm. Bütçe düğüm sayısı, tavan derinlik.

    Derinlik önce: odaklı bir kapsayıcı varsa (bazı toolkit'ler işaretler)
    asıl odaklanan onun çocuğudur ve özet onu göstermeli.
    """
    if butce[0] <= 0 or derinlik > MAX_ARAMA_DERINLIK:
        return None
    butce[0] -= 1
    for cocuk in _cocuklar(dugum, MAX_DUGUM):
        derin = _odak_ara(cocuk, butce, derinlik + 1)
        if derin is not None:
            return derin
        if butce[0] <= 0:
            return None
    if _durum_var(dugum, pyatspi.STATE_FOCUSED):
        return dugum
    return None


def _etiket_gez(dugum, vx: int, vy: int, derinlik: int, durum: dict) -> None:
    """Noktayı içeren en küçük adlı düğümü arar; pencere çerçevesi sayılmaz."""
    if durum["kalan"] <= 0 or derinlik > MAX_ARAMA_DERINLIK:
        return
    durum["kalan"] -= 1

    kutu = _kutu(dugum)
    if kutu is not None:
        durum["kutu_okunur"] = True
        left, top, right, bottom = kutu
        if left <= vx < right and top <= vy < bottom and _uia_turu(dugum) != "Window":
            alan = (right - left) * (bottom - top)
            ad = _ad(dugum).strip()
            if ad and (durum["alan"] is None or alan < durum["alan"]):
                durum["en_iyi"], durum["alan"] = ad, alan

    for cocuk in _cocuklar(dugum, MAX_DUGUM):
        if durum["kalan"] <= 0:
            return
        _etiket_gez(cocuk, vx, vy, derinlik + 1, durum)