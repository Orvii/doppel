"""Monitör envanteri ve koordinat çevirisi.

Modelin gördüğü her ekran görüntüsü tek bir monitöre ait ve sol üst köşesi
(0, 0). Windows'un imleç API'si ise sanal masaüstü koordinatlarını bekliyor —
ikinci monitör burada x=1920'den başlıyor. Bu modül iki uzayı birbirine
çevirir; burada "model uzayı" modele gönderilen karenin piksel uzayıdır.

## Sınır iki sayı, tek sayı değil

Modelin kabul ettiği bir kare iki koşula birden uymak zorunda: uzun kenar en
çok 2576 piksel **ve** görsel token sayısı en çok 4784 (28x28 piksel bir
token). İkisinden biri aşılırsa API kareyi kendisi küçültür; computer araç
setine dönen karelerde ise küçültmek yerine isteği reddeder. Her iki hâlde de
modelin gördüğü uzay elimizdeki kareden farklı olur ve tıklama yanlış yere
gider — kare küçültülmüşken koordinatları ham sayan ajan sessizce kayar.

Eski hâlde yalnızca kenara bakılıyordu ve o bakışın tükettiği tek yer bir
uyarı satırıydı; ölçeği uygulayan hiçbir kod yoktu. 2560x1600 kare kenar
sınırının altında ama 5336 token ediyor, yani küçültülüyordu ve bunu gören
yoktu. Artık iki sınır da `model_kare_boyutu`'nda: gönderilen kare
(`capture.Frame.model_gorsel`), bölge kırpma (`capture.Frame.crop`) ve tıklama
çevirisi (`Display.to_virtual`) aynı fonksiyonun cevabını kullanır. Ölçek
matematiğinin ikinci bir kopyası yok.

Sınırlar Anthropic vision dokümanından ("Resolution and token cost",
"Coordinates and bounding boxes"): yüksek çözünürlük katmanı (Claude 4.7 ve
sonrası; bu projede `claude-opus-5`) 2576 px / 4784 token, standart katman
1568 / 1568. Aşağıdaki boyut fonksiyonu dokümandaki referans uygulamanın
aynısıdır ve dokümanın kendi örnekleriyle test edilir.

Sanal masaüstünün tamamını (3840x1080) tek kare olarak göndermek yine iyi
bir fikir değil: 5382 token ediyor, küçültme giriyor. Monitör başına
yakalayınca 1920x1080 iki sınırın da altında kalıyor ve bu makinede ölçek
tam olarak 1 — koordinatlar 1:1.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass

#: Modelin görsel token ızgarası: bir token 28x28 piksel.
MODEL_TOKEN_PX = 28

#: Yüksek çözünürlük katmanının sınırları (Claude 4.7 ve sonrası).
#: Standart katman 1568 / 1568; `claude-opus-5` yüksek katmanda.
MAX_LONG_EDGE_PX = 2576
MAX_VISUAL_TOKENS = 4784


def _token_sayisi(genislik: int, yukseklik: int) -> int:
    """Kareyi oluşturan 28x28'lik görsel token sayısı."""
    return (
        (genislik + MODEL_TOKEN_PX - 1) // MODEL_TOKEN_PX
    ) * ((yukseklik + MODEL_TOKEN_PX - 1) // MODEL_TOKEN_PX)


def model_kare_boyutu(
    genislik: int,
    yukseklik: int,
    max_edge: int = MAX_LONG_EDGE_PX,
    max_tokens: int = MAX_VISUAL_TOKENS,
) -> tuple[int, int]:
    """Kareyi modele göndermek için küçültmek gerekiyorsa hedef boyutu.

    Sığdıysa `(genislik, yukseklik)` aynen döner. Sığmadıysa modelin
    uygulayacağı boyutun **aynısı** hesaplanır: oran korunur, iki sınırdan
    (kenar ve token) hangisi darsa ona uyulur. Anthropic vision
    dokümanındaki referans uygulamanın birebir çevirisi; dokümanın kendi
    örnekleri testlerde sabitlenmiştir.

    Gerekçe: API, sınırı aşan bir kareyi ya kendisi küçültür (koordinatlar
    sessizce kayar) ya da computer araç setine dönen karelerde olduğu gibi
    isteği reddeder. İkisinde de tek çıkış, kareyi bizim küçültüp hangi
    uzayı gönderdiğimizi bilmektir.
    """
    if genislik < 1 or yukseklik < 1:
        return genislik, yukseklik

    def sigiyor(mu_en: int, mu_boy: int) -> bool:
        # Kare 28'in katına **yukarı** yastıklanıyor ve sınır o yastıklı
        # boyuta bakıyor: 2576 sınırında 2575 hâlâ 2576'ya yuvarlanıyor.
        return (
            -(-mu_en // MODEL_TOKEN_PX) * MODEL_TOKEN_PX <= max_edge
            and -(-mu_boy // MODEL_TOKEN_PX) * MODEL_TOKEN_PX <= max_edge
            and _token_sayisi(mu_en, mu_boy) <= max_tokens
        )

    if sigiyor(genislik, yukseklik):
        return genislik, yukseklik
    if yukseklik > genislik:
        # Dikey karede uzun kenar yükseklik; aynı arama takas edilerek.
        dikey_en, dikey_boy = model_kare_boyutu(
            yukseklik, genislik, max_edge, max_tokens
        )
        return dikey_boy, dikey_en

    oran = genislik / yukseklik
    alt, ust = 1, genislik  # alt her zaman sığar, üst asla
    while alt + 1 < ust:
        orta = (alt + ust) // 2
        if sigiyor(orta, max(round(orta / oran), 1)):
            alt = orta
        else:
            ust = orta
    return alt, max(round(alt / oran), 1)


def model_noktasini_buyut(
    x: int, y: int, genislik: int, yukseklik: int
) -> tuple[int, int]:
    """Model uzayındaki bir noktayı yüzeyin gerçek piksel koordinatına çevirir.

    `genislik`/`yukseklik` yüzeyin **gerçek** boyutu. Küçültme yoksa
    koordinat aynen döner. Tek çeviri noktası: monitör tıklamaları,
    yan masa penceresi ve bölge kırpma hep buradan geçer.
    """
    mu_en, mu_boy = model_kare_boyutu(genislik, yukseklik)
    if mu_en == genislik and mu_boy == yukseklik:
        return x, y
    return round(x * genislik / mu_en), round(y * yukseklik / mu_boy)


def gercek_noktayi_kucult(
    x: int, y: int, genislik: int, yukseklik: int
) -> tuple[int, int]:
    """Gerçek piksel koordinatını model uzayına çevirir.

    Model uzayı; `model_noktasini_buyut`'in tersi. Gidip gelmeli: giden bir
    koordinat geri döndüğünde aynı olmalı.
    """
    mu_en, mu_boy = model_kare_boyutu(genislik, yukseklik)
    if mu_en == genislik and mu_boy == yukseklik:
        return x, y
    return round(x * mu_en / genislik), round(y * mu_boy / yukseklik)


@dataclass(frozen=True)
class Display:
    """Sanal masaüstü üzerinde bir monitör."""

    index: int
    left: int
    top: int
    width: int
    height: int
    primary: bool

    @property
    def long_edge(self) -> int:
        return max(self.width, self.height)

    @property
    def needs_downscale(self) -> bool:
        """Kare olduğu gibi gönderilemez mi.

        İki sınırdan biri yetiyor: kenar **ya da** token bütçesi. Eski hâl
        yalnızca kenara bakıyordu ve 2560x1600'ü (5336 token) sınır içinde
        sanıyordu.
        """
        return model_kare_boyutu(self.width, self.height) != (self.width, self.height)

    def to_virtual(self, x: int, y: int) -> tuple[int, int]:
        """Model koordinatını sanal masaüstü pikseline çevirir.

        Gelen koordinat **gönderilen karenin** uzayında; kare küçültülmüşse
        önce gerçek piksele büyütülür. Model→ekran yolundaki tek çeviri
        noktası burasıdır.
        """
        gercek_x, gercek_y = model_noktasini_buyut(
            x, y, self.width, self.height
        )
        if not (0 <= gercek_x < self.width and 0 <= gercek_y < self.height):
            raise ValueError(
                f"({x}, {y}) is outside display {self.index}, which is "
                f"{self.width}x{self.height}"
            )
        return self.left + gercek_x, self.top + gercek_y

    def from_virtual(self, vx: int, vy: int) -> tuple[int, int]:
        """Sanal masaüstü pikselini **model uzayına** çevirir.

        `to_virtual`'in tersi; `cursor_position` ve UIA tıklama noktaları
        buradan geçiyor, yani modele verilen her koordinat onun gördüğü
        karenin uzayında oluyor.
        """
        return gercek_noktayi_kucult(
            vx - self.left, vy - self.top, self.width, self.height
        )

    def contains_virtual(self, vx: int, vy: int) -> bool:
        return (
            self.left <= vx < self.left + self.width
            and self.top <= vy < self.top + self.height
        )


class DisplayMap:
    """Sıralı monitör listesi. Birincil ekran her zaman 0. indekste."""

    def __init__(self, displays: list[Display]) -> None:
        if not displays:
            raise ValueError("At least one monitor is required")
        self._displays = displays

    def __len__(self) -> int:
        return len(self._displays)

    def __iter__(self):
        return iter(self._displays)

    def __getitem__(self, index: int) -> Display:
        try:
            return self._displays[index]
        except IndexError:
            raise IndexError(
                f"There is no display {index} — this machine has {len(self._displays)}"
            ) from None

    def locate_virtual(self, vx: int, vy: int) -> Display | None:
        """Verilen sanal koordinatı içeren monitörü döndürür."""
        for display in self._displays:
            if display.contains_virtual(vx, vy):
                return display
        return None

    def locate_rect(self, left: int, top: int, right: int, bottom: int) -> Display:
        """Bir pencerenin **çoğunlukla** hangi monitörde olduğunu söyler.

        Sol üst köşeye bakmak yetmiyor: Windows'ta ekranı kaplayan bir
        pencere kenarlığı yüzünden birkaç piksel komşu monitöre taşıyor.
        Discord'un penceresi sol=1912 ile başlıyordu ve 1920'de başlayan
        ikinci ekranda olmasına rağmen birinci ekranda sayılıyordu — o
        yüzden ekran görüntüsü yanlış monitörden alınıyor ve ajan
        Discord'u hiç göremiyordu.

        Örtüşme alanı en büyük olan monitör kazanıyor.
        """
        en_iyi, en_buyuk = self._displays[0], -1
        for display in self._displays:
            genislik = min(right, display.left + display.width) - max(left, display.left)
            yukseklik = min(bottom, display.top + display.height) - max(top, display.top)
            alan = max(0, genislik) * max(0, yukseklik)
            if alan > en_buyuk:
                en_iyi, en_buyuk = display, alan
        return en_iyi

    def describe(self) -> str:
        """Sistem promptuna gömülecek insan okunur özet.

        Küçültme gereken ekranda kare boyutu da yazılıyor: model monitörün
        2560x1600 olduğunu okuyup 2420x1512 bir kare görürse hangi uzayda
        konuştuğunu bilemez. Koordinatlar her hâlükârda gördüğü karenin
        uzayında ve çeviri bizde — ama söylenmiş olması bir belirsizlik
        bırakmıyor.
        """
        lines = []
        for d in self._displays:
            tag = " (primary)" if d.primary else ""
            kare_en, kare_boy = model_kare_boyutu(d.width, d.height)
            if (kare_en, kare_boy) != (d.width, d.height):
                lines.append(
                    f"  {d.index}: {d.width}x{d.height}{tag}, "
                    f"shown as {kare_en}x{kare_boy}"
                )
            else:
                lines.append(f"  {d.index}: {d.width}x{d.height}{tag}")
        return "\n".join(lines)


# --- Windows'tan gerçek monitörleri okuma -------------------------------------

_MONITORINFOF_PRIMARY = 0x1


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("rcMonitor", _RECT),
        ("rcWork", _RECT),
        ("dwFlags", ctypes.c_ulong),
    ]


def enumerate_displays() -> DisplayMap:
    """Bağlı monitörleri Windows'tan okur. Birincil ekran başa alınır."""
    user32 = ctypes.windll.user32
    found: list[tuple[_RECT, bool]] = []

    proc_type = ctypes.WINFUNCTYPE(
        ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(_RECT), ctypes.c_double
    )

    def _callback(hmonitor, _hdc, _rect_ptr, _data):
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            found.append((info.rcMonitor, bool(info.dwFlags & _MONITORINFOF_PRIMARY)))
        return 1

    if not user32.EnumDisplayMonitors(None, None, proc_type(_callback), 0):
        raise OSError("EnumDisplayMonitors failed")

    # Birincil önce, sonra soldan sağa.
    found.sort(key=lambda item: (not item[1], item[0].left, item[0].top))

    return DisplayMap(
        [
            Display(
                index=i,
                left=rect.left,
                top=rect.top,
                width=rect.right - rect.left,
                height=rect.bottom - rect.top,
                primary=primary,
            )
            for i, (rect, primary) in enumerate(found)
        ]
    )


def virtual_screen_rect() -> tuple[int, int, int, int]:
    """Sanal masaüstünün (left, top, width, height) değeri.

    SendInput'un mutlak fare koordinatlarını normalize etmek için gerekli.
    """
    user32 = ctypes.windll.user32
    SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
    SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79
    return (
        user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_CXVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_CYVIRTUALSCREEN),
    )


def set_dpi_awareness() -> None:
    """Süreci monitör başına DPI farkındalığına alır.

    Bu çağrı olmadan Windows koordinatları ölçekler ve yakaladığımız kare ile
    tıkladığımız nokta birbirini tutmaz. Süreç başlangıcında, pencere
    oluşturulmadan önce çağrılmalı.
    """
    DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(
            DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        )
    except (AttributeError, OSError):
        # Windows 8.1–10 1607 öncesi: eski API.
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
