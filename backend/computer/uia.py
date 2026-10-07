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
"""

from __future__ import annotations

from dataclasses import dataclass

import uiautomation as auto

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


def snapshot(
    display: Display,
    max_depth: int = MAX_DEPTH,
    max_nodes: int = MAX_NODES,
) -> SnapshotResult:
    """Ön plandaki pencerenin ağacını verilen ekranın koordinatlarında döndürür."""
    window = auto.GetForegroundControl()
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
    """
    try:
        control = auto.GetFocusedControl()
        if control is None:
            return None
        tur = control.ControlTypeName.removesuffix("Control")[:40]
        ad = str(control.Name or "")[:80]
        return (tur, ad, _value_of(control)[:ODAK_SINIRI])
    except Exception:
        return None
