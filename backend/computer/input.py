"""Fare ve klavye — tek arayüz, altında seçilen platform sürücüsü.

Bu modül genel API'yi ve platformdan bağımsız çalışan parçaları tutar
(isim çözümlemesi, normalize_absolute, sürücü seçimi). Gerçek girdiyi
üreten kod ayrı: `girdi_win32.py` (SendInput) ve `girdi_x11.py`
(xdotool/ydotool). Buradaki fonksiyonlar çağrı anında sürücüyü seçip
ona devrediyor; platform dalı yalnızca `erisim.py`'de yaşıyor.

Neden bu ayrım: pyautogui yerine ham SendInput kullanılıyordu, iki
nedenle — pyautogui Türkçe karakterleri aktif klavye düzenine bağlı
olarak yazıyor (İngilizce düzende `ğüşıöç` düşüyor) ve fareyi sanal
masaüstü yerine birincil ekrana göre konumlandırıyor. Windows'taki bu
davranış aynen korundu; Linux tarafı aynı sözleşmeyi xdotool/ydotool ile
veriyor ve seçim yetenek yoklamasıyla yapılıyor (bkz. `erisim.py`).

Windows'ta modül içe aktarma yolu değişmedi: `girdi_win32` yalnızca
çağrı anında, oturum Windows'sa yükleniyor — Linux'ta bu modül
`ctypes.wintypes` görmeden içe aktarılabilir.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from types import ModuleType

from . import erisim

# --- Platformdan bağımsız: isim çözümlemesi ve mutlak normalizasyon -----------

#: Modelin kullandığı X11 tarzı tuş adları -> Windows sanal tuş kodları.
#: Linux sürücüleri kendi karşılıklarını (`girdi_x11.ADLAR`) kullanır; bu
#: sözlük Windows kodları ürettiği için burada kalır — ad çözümlemesi
#: iki platformda da aynı hataları vermeli (`Unknown key: ...`).
VK_NAMES: dict[str, int] = {
    "backspace": 0x08, "tab": 0x09, "return": 0x0D, "enter": 0x0D,
    "shift": 0x10, "ctrl": 0x11, "control": 0x11, "alt": 0x12,
    "pause": 0x13, "caps_lock": 0x14, "escape": 0x1B, "esc": 0x1B,
    "space": 0x20, "page_up": 0x21, "page_down": 0x22,
    "end": 0x23, "home": 0x24,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "print": 0x2C, "insert": 0x2D, "delete": 0x2E,
    "super": 0x5B, "win": 0x5B, "menu": 0x5D,
    "num_lock": 0x90, "scroll_lock": 0x91,
}
VK_NAMES.update({f"f{i}": 0x6F + i for i in range(1, 25)})  # F1=0x70
VK_NAMES.update({str(d): 0x30 + d for d in range(10)})
VK_NAMES.update({chr(c): c for c in range(ord("A"), ord("Z") + 1)})
VK_NAMES.update({chr(c).lower(): c for c in range(ord("A"), ord("Z") + 1)})


def normalize_absolute(vx: int, vy: int, rect: tuple[int, int, int, int]) -> tuple[int, int]:
    """Sanal masaüstü pikselini SendInput'un 0–65535 mutlak uzayına çevirir.

    Windows bu değeri `piksel = deger * genislik / 65536` ile geri çeviriyor,
    yani (genislik - 1) ile ölçekleyip yuvarlamak son sütuna/satıra da
    ulaşmayı garantiliyor. Linux sürücüleri piksel uzayında konuştuğu için
    orada kullanılmıyor; Windows'ta sözleşme aynen sürüyor.
    """
    left, top, width, height = rect
    if width <= 1 or height <= 1:
        raise ValueError(f"Invalid virtual desktop size: {width}x{height}")
    nx = round((vx - left) * 65535 / (width - 1))
    ny = round((vy - top) * 65535 / (height - 1))
    return max(0, min(65535, nx)), max(0, min(65535, ny))


def parse_combo(combo: str) -> list[int]:
    """`"ctrl+shift+s"` -> sanal tuş kodu listesi, değiştiriciler önce."""
    codes = []
    for part in combo.split("+"):
        name = part.strip().lower()
        if not name:
            raise ValueError(f"Empty key name: {combo!r}")
        if name not in VK_NAMES:
            raise ValueError(f"Unknown key: {part!r} (in {combo!r})")
        codes.append(VK_NAMES[name])
    return codes


# --- Sürücü seçimi ------------------------------------------------------------

#: Yerleşik sürücüler. x_goster verilmişse (yan masa) o ekran kazanır.
_suruculer: dict[str, object] = {}


def _surucu(x_goster: str | None = None):
    """Çağrı anında sürücüyü seçer; seçilemezse açık hata yükseltir.

    Seçim sürücü **kurulurken** yoklanıyor ve sonucu burada tutuluyor:
    yoklama bir alt süreç (`xdotool getdisplaygeometry`) ve onu her fare
    hareketinde tekrarlamak sürüklemeyi (24 adım) iki katına çıkarırdı.
    Ortam değişirse (`secimi_sifirla`) yeniden seçilir; ekran ortamı süreç
    içinde değişebiliyor çünkü yan masa `DISPLAY=:n` ile konuşuyor.
    """
    anahtar = x_goster or ""
    if anahtar in _suruculer:
        return _suruculer[anahtar]
    secim = erisim.girdi_sec(x_goster=x_goster)
    if secim.hata:
        raise RuntimeError(secim.hata)
    if secim.ad == "win32":
        from . import girdi_win32

        modul = girdi_win32
    elif secim.ad in ("xdotool", "ydotool"):
        from . import girdi_x11

        modul = girdi_x11.surucu_sec(secim)
    elif secim.sinif is not None:
        # Kayıtlı arka uç (ör. XDG portal): sınıf `env` ile kuruluyor ve
        # modülün kamu API'sini (aşağıdaki fonksiyon adları) uygulamak
        # zorunda. Ayrıntı: `erisim.surucu_kaydet`.
        modul = secim.sinif(secim.env)
    else:
        raise RuntimeError(f"Unknown input backend: {secim.ad!r}")
    _suruculer[anahtar] = modul
    return modul


def secimi_sifirla() -> None:
    """Sürücü seçimini bayatlatır — ekran ortamı değişince ya da testte."""
    _suruculer.clear()


# --- Genel API — imzalar Windows hâliyle birebir ------------------------------


def move_to(vx: int, vy: int, x_goster: str | None = None) -> None:
    """İmleci sanal masaüstü koordinatına taşır."""
    _surucu(x_goster).move_to(vx, vy)


def cursor_position(x_goster: str | None = None) -> tuple[int, int]:
    return _surucu(x_goster).cursor_position()


def click(vx: int, vy: int, button: str = "left", count: int = 1,
          x_goster: str | None = None) -> None:
    """Verilen noktaya tıklar. count=2 çift, count=3 üçlü tıklama."""
    _surucu(x_goster).click(vx, vy, button, count)


def mouse_down(button: str = "left", x_goster: str | None = None) -> None:
    _surucu(x_goster).mouse_down(button)


def mouse_up(button: str = "left", x_goster: str | None = None) -> None:
    _surucu(x_goster).mouse_up(button)


def drag(from_xy: tuple[int, int], to_xy: tuple[int, int], steps: int = 24,
         x_goster: str | None = None) -> None:
    """Basılı tutarak sürükler.

    Ara adımlar şart: tek sıçrayışta çoğu uygulama sürüklemeyi algılamıyor,
    çünkü taşıma olaylarının akışını görmüyorlar.
    """
    surucu = _surucu(x_goster)
    surucu.move_to(*from_xy)
    surucu.mouse_down("left")
    try:
        x0, y0 = from_xy
        x1, y1 = to_xy
        for i in range(1, steps + 1):
            t = i / steps
            surucu.move_to(round(x0 + (x1 - x0) * t), round(y0 + (y1 - y0) * t))
            time.sleep(0.008)
    finally:
        surucu.mouse_up("left")


def scroll(direction: str, amount: int, at: tuple[int, int] | None = None,
           x_goster: str | None = None) -> None:
    """Tekerlek kaydırma. amount, tık sayısı."""
    surucu = _surucu(x_goster)
    if at is not None:
        surucu.move_to(*at)
    surucu.scroll(direction, amount)


def press(combo: str, repeat: int = 1, x_goster: str | None = None) -> None:
    """Tuş ya da kombinasyon basar: `"Return"`, `"ctrl+s"`, `"alt+F4"`."""
    _surucu(x_goster).press(combo, repeat)


def type_text(text: str, delay: float | None = None, x_goster: str | None = None) -> None:
    """Metni harfi harfine yazar, klavye düzeninden bağımsız.

    Sürücü başına zamanlama farkı bilinçli: Windows karakter başına ayrı
    SendInput çağrısı yapar (ölçülmüş bir bozulma regresyonu), Linux
    sürücüleri tek alt süreçte `--delay` ile yazar. Ortak sözleşme yalnızca
    "metin hedefe birebir düşer" — zamanlama değil.
    """
    _surucu(x_goster).type_text(text, delay)


@contextmanager
def modifiers_held(combo: str | None, x_goster: str | None = None):
    """Değiştirici tuşları basılı tutarken içerideki eylemi çalıştırır.

    Model tıklama ve kaydırma aksiyonlarında `text` alanıyla değiştirici
    gönderebiliyor: `left_click` + `"shift"` = shift'li tıklama. Bırakma
    `finally` içinde, çünkü ortada bir hata olursa ctrl basılı kalırsa
    kullanıcının klavyesi kullanılamaz hale gelir.
    """
    if not combo:
        yield
        return

    surucu = _surucu(x_goster)
    adlar = _combo_adlari(combo)
    surucu.tus_adlari_bas(adlar)
    try:
        yield
    finally:
        surucu.tus_adlari_birak(adlar)


def hold(combo: str, duration: float, x_goster: str | None = None) -> None:
    """Tuşu belirtilen saniye boyunca basılı tutar."""
    surucu = _surucu(x_goster)
    adlar = _combo_adlari(combo)
    surucu.tus_adlari_bas(adlar)
    try:
        time.sleep(duration)
    finally:
        surucu.tus_adlari_birak(adlar)


def _combo_adlari(combo: str) -> list[str]:
    """Kombinasyonu sürücüye göre adlara ayırır; bilinmeyen ad burada patlar.

    Windows sürücüsüne sanal tuş kodu mu, X adı mı gideceği sürücünün
    işi; ortak doğrulama ise burada — kullanıcı hangi platformda olursa
    olsun aynı hatayı görmeli.
    """
    adlar = []
    for parca in combo.split("+"):
        ad = parca.strip().lower()
        if not ad:
            raise ValueError(f"Empty key name: {combo!r}")
        if ad not in VK_NAMES:
            raise ValueError(f"Unknown key: {parca!r} (in {combo!r})")
        adlar.append(ad)
    return adlar