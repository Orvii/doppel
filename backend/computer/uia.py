"""UI Automation ağacı -> metin anlık görüntüsü.

Bir ekran görüntüsü ~1500 token ve modelin piksellerden koordinat tahmin
etmesini gerektiriyor. Aynı pencerenin erişilebilirlik ağacı birkaç yüz token
ve koordinatları **tahmin değil, ölçüm**: Windows her denetimin dikdörtgenini
zaten biliyor.

Bu yüzden çıktı dikdörtgen değil **merkez noktası** veriyor. Modelin istediği
şey "bu düğme nerede" değil, "nereye tıklayayım".

Her yerde çalışmıyor: tuval çizen uygulamalar, oyunlar, video, uzak masaüstü
ve erişilebilirliği kapalı bazı Electron uygulamaları boş ya da yüzeysel ağaç
verir. O durumda ekran görüntüsüne dönmek gerekiyor — `snapshot` bunu
`SnapshotResult.thin` ile bildiriyor.

## Port notu: platform seçimi `erisim`den

Linux'ta aynı sözleşmeyi AT-SPI arka ucu (`uia_linux.py`) veriyor; seçim
çağrı anında `erisim.oturum()`a soruluyor — başka yerde platform dalı yok.
`uiautomation` toleranslı içe aktarılıyor: Linux'ta paket yok ve olamaz,
modül yine de içe aktarılabilir kalmalı (yoksa ajanın kendisi Linux'ta
açılmazdı); Windows yolu yanlış oturumda çağrılırsa `AttributeError` değil,
ne olduğunu söyleyen bir hata veriyor.
"""

from __future__ import annotations

from dataclasses import dataclass

try:  # uiautomation yalnızca Windows'ta; Linux'ta yok
    import uiautomation as auto
except ImportError:
    auto = None  # type: ignore[assignment]

from .displays import Display

#: Tıklanabilir ya da okunmaya değer denetim türleri. Bunun dışındakiler
#: (Pane, Group, Custom) yalnızca çocukları için geziliyor, kendileri
#: yazılmıyor — yoksa çıktının yarısı yapısal gürültü oluyor.
INTERESTING = {
    "Button", "CheckBox", "ComboBox", "Edit", "Document", "Hyperlink",
    "ListItem", "MenuItem", "RadioButton", "Slider", "SplitButton", "Tab",
    "TabItem", "Text", "TreeItem", "ToolBar", "Window", "Spinner",
}

MAX_DEPTH = 12
MAX_NODES = 220

#: Bu sayının altında düğüm çıkarsa ağaç güvenilmez sayılıp modele
#: "ekran görüntüsü al" denecek.
THIN_BELOW = 4


@dataclass
class SnapshotResult:
    text: str
    node_count: int
    window_title: str

    @property
    def thin(self) -> bool:
        return self.node_count < THIN_BELOW


def _auto():
    """Windows UIA kökü; bu oturumda yoksa açık hata.

    Windows dışında `uiautomation` içe aktarılmıyor ve ona dokunan her
    çağrı `None` üzerinden `AttributeError` verirdi — "erişilebilirlik
    yok" ile "yanlış arka uç seçildi" karışmasın diye tek kapı burası.
    """
    if auto is None:
        raise RuntimeError(
            "UI Automation is not available on this platform (uiautomation "
            "is Windows-only). On Linux the AT-SPI backend (uia_linux.py) "
            "serves the same interface."
        )
    return auto


def _linux_arka_uc():
    """Bu oturum Linux mu? Öyleyse AT-SPI modülü, değilse None.

    `erisim` içe aktarılamazsa (beklenmez) Windows yolu korunuyor —
    oturum sorusunun tek kaynağı orası, yedek dar ve bilinçli.
    """
    try:
        from . import erisim

        return None if erisim.oturum().tur == "windows" else _atspi()
    except ImportError:  # pragma: no cover - erisim varken olmaz
        return None


def _atspi():
    from . import uia_linux

    return uia_linux


def snapshot(
    display: Display,
    max_depth: int = MAX_DEPTH,
    max_nodes: int = MAX_NODES,
) -> SnapshotResult:
    """Ön plandaki pencerenin ağacını verilen ekranın koordinatlarında döndürür."""
    linux = _linux_arka_uc()
    if linux is not None:
        # Linux'ta `display` aktif monitör; AT-SPI koordinatı ya ham yazılsın
        # (ekran verilmezse) ya da Windows'taki gibi model uzayına çevrilsin.
        return linux.anlik_gorunum(
            maks_derinlik=max_depth, maks_dugum=max_nodes, ekran=display
        )

    window = _auto().GetForegroundControl()
    if window is None:
        return SnapshotResult(text="There is no foreground window.", node_count=0, window_title="")

    title = str(window.Name or "")
    lines: list[str] = []
    state = {"count": 0, "truncated": False}

    _walk(window, display, depth=0, max_depth=max_depth, max_nodes=max_nodes,
          lines=lines, state=state)

    if state["truncated"]:
        lines.append(f"... truncated at {max_nodes} nodes")

    header = f"Window: {title!r} (display {display.index})"
    body = "\n".join(lines) if lines else "(no readable controls)"
    return SnapshotResult(
        text=f"{header}\n{body}", node_count=state["count"], window_title=title
    )


def _walk(control, display: Display, depth: int, max_depth: int, max_nodes: int,
          lines: list[str], state: dict) -> None:
    if depth > max_depth:
        return
    if state["count"] >= max_nodes:
        state["truncated"] = True
        return

    try:
        children = control.GetChildren()
    except Exception:
        # Bir denetim gezilirken kapanabilir; ağacın kalanını kaybetme.
        children = []

    for child in children:
        if state["count"] >= max_nodes:
            state["truncated"] = True
            return

        line = _describe(child, display)
        if line is not None:
            lines.append("  " * depth + line)
            state["count"] += 1
            _walk(child, display, depth + 1, max_depth, max_nodes, lines, state)
        else:
            # İlgisiz kapsayıcı: kendisini yazma ama içine bak, girintiyi artırma.
            _walk(child, display, depth, max_depth, max_nodes, lines, state)


def _describe(control, display: Display) -> str | None:
    try:
        kind = control.ControlTypeName.removesuffix("Control")
        rect = control.BoundingRectangle
        name = str(control.Name or "").strip()
        enabled = control.IsEnabled
    except Exception:
        return None

    if kind not in INTERESTING:
        return None

    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return None  # gizli ya da daraltılmış

    vx, vy = (rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2
    if not display.contains_virtual(vx, vy):
        return None  # başka ekranda ya da ekran dışında

    x, y = display.from_virtual(vx, vy)
    label = f'"{name[:70]}"' if name else "(unnamed)"
    suffix = "" if enabled else " [pasif]"

    value = _value_of(control)
    if value:
        label += f" = {value[:60]!r}"

    return f"{kind} {label} [{x},{y}]{suffix}"


def _value_of(control) -> str:
    """Metin kutularının içeriği — ajanın "yazdım mı" sorusunun cevabı."""
    try:
        if control.ControlTypeName == "EditControl":
            return str(control.GetValuePattern().Value or "")
    except Exception:
        pass
    return ""


def _imza_oku(vx: int, vy: int):
    """Windows: noktadaki denetimin imzası (`workflows.imza.noktada`).

    Ayrı bir fonksiyon: imza modülü `uiautomation`ı yalnızca çağrı anında
    içe aktarıyor ve bu sarmalayıcı aynı zamanda testlerin sahteleme
    noktası — kapı etiketinin kaynağı burada net görünsün.
    """
    from ..workflows.imza import noktada

    return noktada(vx, vy)


def etiket_noktada(vx: int, vy: int):
    """Bir noktadaki denetimin etiketi — güvenlik kapısının girdisi.

    Cevap `uia_linux.Etiket`tir ve iki hâli ayrı tutar: "noktada adı olan
    denetim yok" (okunabilir, boş metin) ile "erişilebilirlik katmanı soruya
    cevap veremedi" (okunamadı). Kapı bu ayrımı görmek zorunda; yoksa
    okunamayan bir hedefe tıklama sessizce SAFE sayılır.

    Windows'ta sözleşme bilinçli olarak eskisi gibi: noktada denetim
    bulunamadığında (oyun, tuval, yükseltilmiş pencere) boş ama okunabilir
    cevap dönüyor — o pencerelerde her tıklamaya onay sormak onay
    yorgunluğu üretirdi ve pencere başlığı süzgeci orada yine çalışıyor.
    """
    linux = _linux_arka_uc()
    if linux is not None:
        return linux.etiket_noktada(vx, vy)
    from .uia_linux import Etiket

    try:
        imza = _imza_oku(vx, vy)
    except Exception:
        imza = None
    return Etiket(imza.ad if imza is not None else "", True)


#: Odak özetindeki alanların sınırı. Her eylemden önce ve sonra okunuyor;
#: büyük bir belgenin tamamını iki kez okumak adım başına sınırsız maliyet
#: olurdu. 200 karakter yazılanı görmeye yetiyor; ötesindeki bir değişiklik
#: görülmezse sonuç "dogrulanamadi" değil "değişmedi" olur — modeli
#: ekran görüntüsü almaya iten uyarı yine çıkıyor.
ODAK_SINIRI = 200


def odak_ozeti() -> tuple[str, str, str] | None:
    """Odaktaki denetimin (tür, ad, değer) özeti — okunamazsa `None`.

    Kimin için: ajan döngüsü bir eylemden **önce ve sonra** bunu iki kez
    okuyup karşılaştırıyor. Tıklama sonrası pencere başlığı değişmese de
    odak başka denetime geçer; `type` sonrası ise odak aynı kalıp
    `EditControl`'ün değeri değişir — "yazdım" iddiasının tek ucuz kanıtı
    orası. Bu yüzden değer de özete giriyor.

    Okunamaması olağan: yükseltilmiş pencereler erişim reddi veriyor ve
    COM çağrısı her an düşebiliyor. `None` "değişiklik yok" demek değil,
    "bu bileşen karşılaştırılamadı" demek — ayrımı çağıran koruyor.
    Linux'ta AT-SPI arka ucu aynı sözleşmeyi veriyor; pyatspi yokluğu da
    buraya `None` olarak düşüyor — döngü zaten okunamazlık sayıyor ve
    doğrulama üretmiyor.
    """
    linux = _linux_arka_uc()
    if linux is not None:
        return linux.odak_ozeti()
    try:
        control = _auto().GetFocusedControl()
        if control is None:
            return None
        tur = control.ControlTypeName.removesuffix("Control")[:40]
        ad = str(control.Name or "")[:80]
        return (tur, ad, _value_of(control)[:ODAK_SINIRI])
    except Exception:
        return None
