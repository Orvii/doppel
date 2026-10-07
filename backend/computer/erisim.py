"""Erişilebilirlik ağacından model okunur metin — platformdan bağımsız çekirdek.

Windows arka ucu UIA'dır (`uia.py`), Linux arka ucu AT-SPI2'dir
(`uia_linux.py`). İkisi de AYNI disiplini kullanmak zorunda: ilgi çeken
denetim türleri (`INTERESTING`), derinlik ve düğüm tavanı, gizli ya da
daraltılmış denetimin atlanması, ekran dışı süzgeci ve "ince ağaç" eşiği.
Bu disiplini iki dosyaya kopyalasaydık biri güncellenip öteki unutulurdu;
bu depoda yanlış ikizlenmiş mantık birkaç kez gerçek hata üretti. O yüzden
gezinme ve biçimlendirme burada TEK kez yazılı; arka uçlar yalnızca aşağıdaki
`Dugum` arayüzünü uyarlar.

Çıktı dikdörtgen değil **merkez noktası** veriyor. Modelin istediği şey "bu
düğme nerede" değil, "nereye tıklayayım"; erişilebilirlik katmanı denetimin
dikdörtgenini zaten biliyor, ölçüm tahminden iyidir.

`Etiket` güvenlik kapısının gördüğü cevaptır ve iki durumu birbirinden
ayırır: okunabilen bir etiket (boş bile olsa "burada etiket yok" demektir)
ile hiç okunamayan bir etiket (`okunabilir=False`). Bu ayrım kaybolursa kapı
"okuyamadım"ı "riskli değil" sayar — sessiz SAFE tam olarak budur.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

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


@dataclass(frozen=True)
class Etiket:
    """Güvenlik kapısına giden etiket cevabı.

    `metin` okunan etiket (boş olabilir: denetim var, adı yok).
    `okunabilir=False` ise erişilebilirlik katmanı hiç cevap veremedi —
    bu "etiket yok" DEĞİL, "soru sorulamadı" demektir; kapı bu ayrımı
    korumak zorunda, yoksa okunamayan bir hedefe tıklama onaysız geçer.
    """

    metin: str = ""
    okunabilir: bool = True


@runtime_checkable
class Dugum(Protocol):
    """Bir erişilebilirlik düğümü — arka uçların uyarladığı tek arayüz."""

    @property
    def tur(self) -> str:
        """INTERESTING'deki tür adı; boşsa düğüm kapsayıcı sayılır."""
        ...

    @property
    def ad(self) -> str:
        """Denetimin adı; yoksa boş dize."""
        ...

    @property
    def etkin(self) -> bool:
        """Denetim kullanılabilir mi — pasifse çıktıya damga konuyor."""
        ...

    @property
    def kutu(self) -> tuple[int, int, int, int] | None:
        """(sol, üst, sağ, alt) sanal masaüstünde; okunamazsa None."""
        ...

    @property
    def deger(self) -> str:
        """Metin kutularının içeriği — "yazdım mı" sorusunun kanıtı."""
        ...

    def cocuklar(self) -> list["Dugum"]:
        """Alt düğümler; uyarlama hataları yutulur, boş liste döner."""
        ...


def agac_metni(
    kok: Dugum,
    display: Display,
    baslik: str,
    *,
    max_depth: int = MAX_DEPTH,
    max_nodes: int = MAX_NODES,
) -> SnapshotResult:
    """Kökün çocuklarından metin anlık görüntüsü üretir.

    Kökün KENDİSİ yazılmaz; pencere başlığı üst satırda. Windows ve Linux
    arka uçları bu fonksiyonu paylaşıyor ki iki platformun çıktısı aynı
    kurallarla üretilsin.
    """
    lines: list[str] = []
    state = {"count": 0, "truncated": False}

    gez(kok, display, 0, max_depth, max_nodes, lines, state)

    if state["truncated"]:
        lines.append(f"... truncated at {max_nodes} nodes")

    header = f"Window: {baslik!r} (display {display.index})"
    body = "\n".join(lines) if lines else "(no readable controls)"
    return SnapshotResult(
        text=f"{header}\n{body}", node_count=state["count"], window_title=baslik
    )


def gez(dugum: Dugum, display: Display, depth: int, max_depth: int, max_nodes: int,
        lines: list[str], state: dict) -> None:
    """Özyinelemeli gezinti — indentation yalnızca satır yazıldığında artar."""
    if depth > max_depth:
        return
    if state["count"] >= max_nodes:
        state["truncated"] = True
        return

    try:
        cocuklar = dugum.cocuklar()
    except Exception:
        # Bir denetim gezilirken kapanabilir; ağacın kalanını kaybetme.
        cocuklar = []

    for cocuk in cocuklar:
        if state["count"] >= max_nodes:
            state["truncated"] = True
            return

        line = satir(cocuk, display)
        if line is not None:
            lines.append("  " * depth + line)
            state["count"] += 1
            gez(cocuk, display, depth + 1, max_depth, max_nodes, lines, state)
        else:
            # İlgisiz kapsayıcı: kendisini yazma ama içine bak, girintiyi artırma.
            gez(cocuk, display, depth, max_depth, max_nodes, lines, state)


def satir(dugum: Dugum, display: Display) -> str | None:
    """Tek bir düğümün çıktı satırı; gösterilmeyecekse None."""
    try:
        tur = dugum.tur
        kutu = dugum.kutu
        ad = dugum.ad.strip()
        etkin = dugum.etkin
    except Exception:
        return None

    if tur not in INTERESTING:
        return None

    if kutu is None:
        return None
    left, top, right, bottom = kutu
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        return None  # gizli ya da daraltılmış

    vx, vy = (left + right) // 2, (top + bottom) // 2
    if not display.contains_virtual(vx, vy):
        return None  # başka ekranda ya da ekran dışında

    x, y = display.from_virtual(vx, vy)
    label = f'"{ad[:70]}"' if ad else "(unnamed)"
    suffix = "" if etkin else " [pasif]"

    try:
        value = dugum.deger
    except Exception:
        value = ""
    if value:
        label += f" = {value[:60]!r}"

    return f"{tur} {label} [{x},{y}]{suffix}"


#: Odak özetindeki alanların sınırı. Her eylemden önce ve sonra okunuyor;
#: büyük bir belgenin tamamını iki kez okumak adım başına sınırsız maliyet
#: olurdu. 200 karakter yazılanı görmeye yetiyor; ötesindeki bir değişiklik
#: görülmezse sonuç "dogrulanamadi" değil "değişmedi" olur — modeli
#: ekran görüntüsü almaya iten uyarı yine çıkıyor.
ODAK_SINIRI = 200


def odak_ozeti_metni(dugum: Dugum) -> tuple[str, str, str]:
    """Odaktaki düğümün (tür, ad, değer) özeti.

    Alan sınırları Windows'taki özgün davranışla birebir: tür 40, ad 80,
    değer `ODAK_SINIRI`. Ad burada KIRPILMIYOR (satır biçimlendirmesinden
    farkı bu ve bilinçli: özet eşitlik karşılaştırması için okunuyor).
    """
    return (
        dugum.tur[:40],
        dugum.ad[:80],
        dugum.deger[:ODAK_SINIRI],
    )