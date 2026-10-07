"""Erişim katmanı — hangi oturumdayız ve hangi araçlar gerçekten çalışıyor.

Tüm platform dallanması burada. `input.py`, `displays.py`, `capture.py` ve
`killswitch.py` yalnızca buraya sorar; `if sys.platform` başka hiçbir dosyada
yaşamaz. Tek istisna bu modülün kendisi.

## Neden yetenek, platform değil

"Linux'ta XTEST vardır" yanlış bir cümle. Wayland oturumunda XWayland
üzerinden gelen bir `DISPLAY` de var — ve `xdotool` orada **sessizce yarım
çalışır**: imleci oynatır, tıklama yerel (Wayland) pencereye hiç ulaşmaz.
Bu depoda sessizce yanlış iş yapan yol, çalışmayan yoldan kötüdür. Bu yüzden
seçim sırayla soruyor: hangi oturum, araç PATH'te mi, araç o oturumda
gerçekten cevap veriyor mu.

Seçim sırası (girdi):

1. `xdotool` — yalnızca X11 oturumunda ve `getdisplaygeometry` cevap
   verdikten sonra. XTEST kısıtı yalnızca Wayland içindir.
2. `ydotool` — çekirdek uinput; X11'de de Wayland'de de çalışır. İkili
   dosya **ve** daemon soketi bekliyor. Udev kuralı (paketleme/README'ye
   ait, burada yalnızca hatırlatma): `KERNEL=="uinput", GROUP="input",
   MODE="0660"` ve kullanıcı `input` grubunda olmalı — yoksa ydotool
   bağlanır ama olay gönderemez.
3. Kayıtlı sürücüler — `surucu_kaydet()` ile gelenler. XDG portal arka
   ucu (port/wayland) buraya `musait()` fonksiyonu + sınıfıyla kaydolur;
   bu modül portal dosyalarını hiç bilmez.

Wayland oturumunda `xdotool` **hiç denenmez** (yukarıdaki sessiz yarım
çalışma yüzünden), yalnızca ydotool ve kayıtlı sürücüler kalır.

Ekransız (ne DISPLAY ne WAYLAND_DISPLAY) Linux: içe aktarma patlamaz,
çağrı anında açık bir hata verir — `GirdiSecimi.hata`. Ajanın çalışması
mümkün olmayan bir makinede dürüst davranış budur.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from . import komut


@dataclass(frozen=True)
class Oturum:
    """Nerede çalıştığımızın tek kaynağı."""

    tur: str  # "windows" | "x11" | "wayland" | "headless"
    x_goster: str | None
    wayland_goster: str | None
    ydotool_soket: str | None

    @property
    def x_var(self) -> bool:
        return self.x_goster is not None


def _ydotool_varsayilan_soket() -> str | None:
    """ydotool'un systemd kullanıcı soketi. uid okunamazsa None."""
    try:
        return f"/run/user/{os.getuid()}/ydotool.sock"
    except AttributeError:  # Windows
        return None


def oturum(ortam: Mapping[str, str] | None = None) -> Oturum:
    """Oturum türünü ortam değişkenlerinden okur. Hiçbir şeyi çalıştırmaz.

    Wayland + DISPLAY birlikte görülürse tür "wayland" olur: XWayland
    yüzünden `DISPLAY` dolu olsa bile yerel pencereler X istemcisi değil.
    """
    ortam = os.environ if ortam is None else ortam
    soket = ortam.get("YDOTOOL_SOCKET") or _ydotool_varsayilan_soket()
    if sys.platform == "win32":
        return Oturum("windows", None, None, soket)
    x = ortam.get("DISPLAY") or None
    w = ortam.get("WAYLAND_DISPLAY") or None
    if w:
        return Oturum("wayland", x, w, soket)
    if x:
        return Oturum("x11", x, None, soket)
    return Oturum("headless", None, None, soket)


# --- Araç yoklaması -----------------------------------------------------------

#: Kayıtlı sürücüler: ad -> (tür, sınıf, musait_fonksiyonu).
#: port/wayland buraya kaydolur; bu modül onların içini hiç görmez.
_suruculer: dict[str, tuple[str, type, Callable[[], bool]]] = {}


def surucu_kaydet(
    ad: str,
    sinif: type,
    musait: Callable[[], bool],
    tur: str = "girdi",
) -> None:
    """Yeni bir arka uç kaydeder. `musait` True derse seçim onu da sayar."""
    _suruculer[ad] = (tur, sinif, musait)


def kayitli(tur: str) -> list[tuple[str, type]]:
    """Verilen türde, o an müsait olan kayıtlı sürücüler (kayıt sırasıyla)."""
    return [
        (ad, sinif)
        for ad, (t, sinif, musait) in _suruculer.items()
        if t == tur and musait()
    ]


def _x_env(oturum_: Oturum, x_goster: str | None) -> dict[str, str]:
    """Alt süreçlere geçirilecek X ortamı.

    `x_goster` açıkça verilmişse kazanır — yan masa (port-ortam) yan
    ekranına `DISPLAY=:n` ile konuşacak.
    """
    env: dict[str, str] = {}
    if x_goster:
        env["DISPLAY"] = x_goster
    elif oturum_.x_goster:
        env["DISPLAY"] = oturum_.x_goster
    return env


def xdotool_calisir(
    oturum_: Oturum, otam: Mapping[str, str] | None = None, x_goster: str | None = None
) -> bool:
    """xdotool PATH'te **ve** bu X ekranında cevap veriyor mu.

    Varlık yetmiyor: ölü bir DISPLAY'de xdotool kurulu olabilir ama
    `getdisplaygeometry` hata verir. Ölçülen şey cevap, kurulum değil.
    """
    if oturum_.tur not in ("x11",) and x_goster is None:
        return False
    if komut.var_mi("xdotool") is None:
        return False
    env = _x_env(oturum_, x_goster)
    if not env.get("DISPLAY"):
        return False
    try:
        sonuc = komut.calistir(
            ["xdotool", "getdisplaygeometry"], env_ek=env, zaman_asimi=2.0
        )
    except komut.KomutYokHatasi:
        return False
    return sonuc.donus == 0


def ydotool_calisir(oturum_: Oturum) -> bool:
    """ydotool: ikili dosya **ve** daemon soketi birlikte olmalı.

    Yalnızca ikiliye bakmak yetmiyordu: daemon kapalıysa ydotool bağlanma
    hatası verir ve o an sıradaki adaya geçmek gerekir. Soket varsa
    udev/izin sorunu çağrı anına ertelenmiş olur; orada hata sesli olur
    (`KomutHatasi`), sessiz yanlış davranış olmaz.
    """
    if komut.var_mi("ydotool") is None:
        return False
    if not oturum_.ydotool_soket:
        return False
    return os.path.exists(oturum_.ydotool_soket)


# --- Seçim --------------------------------------------------------------------


@dataclass(frozen=True)
class GirdiSecimi:
    """Seçilen girdi sürücüsü. `hata` dolusa seçim başarısız."""

    ad: str | None
    sinif: type | None
    env: dict[str, str]
    hata: str | None = None


def girdi_sec(
    ortam: Mapping[str, str] | None = None, x_goster: str | None = None
) -> GirdiSecimi:
    """Girdi sürücüsünü yetenek sırasına göre seçer.

    `x_goster` açıkça verilmişse oturum Wayland/headless olsa bile X
    yoklaması yapılır: çağıran "şu X ekranına konuş" diyorsa orada gerçek
    bir X sunucusu var demektir (port-ortam'ın Xvfb/Xephyr yan masası
    böyle) ve XTEST orada çalışır. Belirtilmemişken Wayland kuralı aynen
    sürer: oturumun kendi XWayland'ine xdotool ile dokunulmaz.
    """
    oturum_ = oturum(ortam)
    if oturum_.tur == "windows":
        return GirdiSecimi("win32", None, {}, None)
    if oturum_.tur == "headless" and x_goster is None:
        return GirdiSecimi(
            None,
            None,
            {},
            "No display found: set DISPLAY (X11/Xvfb) or WAYLAND_DISPLAY "
            "to give the agent a screen to work on.",
        )

    env = _x_env(oturum_, x_goster)
    x_yolu = oturum_.tur == "x11" or x_goster is not None
    if x_yolu and xdotool_calisir(oturum_, ortam, x_goster):
        return GirdiSecimi("xdotool", None, env, None)
    if ydotool_calisir(oturum_):
        return GirdiSecimi("ydotool", None, env, None)
    for ad, sinif in kayitli("girdi"):
        return GirdiSecimi(ad, sinif, env, None)
    # xdotool kurulu ve X oturumu var ama yoklama düşürdüyse hata metni
    # bunu saklamasın: "kurulu değil" ile "cevap vermiyor" farklı işler.
    if x_yolu:
        ayrinti = (
            "xdotool is installed but its probe failed and ydotool is unavailable"
            if komut.var_mi("xdotool")
            else "install xdotool (XTEST) or ydotool (uinput)"
        )
    else:
        ayrinti = "install ydotool (uinput) or a registered portal backend"
    return GirdiSecimi(None, None, env, f"No input backend available: {ayrinti}")


def goruntu_sec(ortam: Mapping[str, str] | None = None) -> GirdiSecimi:
    """Ekran yakalama arka ucunu seçer. Wayland yolu port/wayland'in kaydı."""
    oturum_ = oturum(ortam)
    if oturum_.tur == "windows":
        return GirdiSecimi("win32", None, {}, None)
    if oturum_.tur == "x11":
        return GirdiSecimi("mss", None, _x_env(oturum_, None), None)
    for ad, sinif in kayitli("goruntu"):
        return GirdiSecimi(ad, sinif, {}, None)
    return GirdiSecimi(
        None,
        None,
        {},
        "No screen capture backend for this session: on Wayland a portal "
        "backend must be registered; headless has no screen at all.",
    )


def ekran_sec(ortam: Mapping[str, str] | None = None) -> GirdiSecimi:
    """Monitör envanteri arka ucunu seçer ("ekran" türü).

    Wayland'de xrandr **bilinçli olarak kullanılmaz**: XWayland üzerinden
    cevap verir ama o cevap gerçek çıktı düzeni olmayabiliyor — yarım
    doğru bir monitör listesi, yanlış ekrandan yakalanan kareden farksız.
    Orada portal arka ucu (port/wayland kaydı) konuşur; kayıt yoksa hata
    açıkça söylenir.
    """
    oturum_ = oturum(ortam)
    if oturum_.tur == "windows":
        return GirdiSecimi("win32", None, {}, None)
    if oturum_.tur == "x11":
        return GirdiSecimi("xrandr", None, _x_env(oturum_, None), None)
    for ad, sinif in kayitli("ekran"):
        return GirdiSecimi(ad, sinif, {}, None)
    return GirdiSecimi(
        None,
        None,
        {},
        "No display enumeration backend for this session: on Wayland a "
        "portal backend must be registered (xrandr would only describe "
        "XWayland, not the real outputs).",
    )


# --- Acil durdurmanın Esc okuyucusu -------------------------------------------


def esc_okuyucu() -> Callable[[], bool] | None:
    """Esc'in o an basılı olup olmadığını söyleyen bir çağrılabilir.

    Windows: `GetAsyncKeyState` (mevcut davranış aynen).
    X11/Wayland: `Xlib` kuruluysa `XQueryKeymap` — süreç içinde, ayrıcalık
    istemiyor, XTEST kısıtından etkilenmiyor. Kurulu değilse None döner ve
    killswitch yalnızca UI durdur düğmesi + SIGINT/SIGTERM ile çalışır:
    bunu bir bağımlılık uğruna zorlamak yerine sınırı dürüstçe söylüyoruz.
    """
    tur = oturum().tur
    if tur == "windows":
        return _win_esc_okuyucu()
    if tur in ("x11", "wayland"):
        return _xlib_esc_okuyucu()
    return None


def _win_esc_okuyucu() -> Callable[[], bool]:
    import ctypes

    def oku() -> bool:
        return bool(ctypes.windll.user32.GetAsyncKeyState(0x1B) & 0x8000)

    return oku


def _xlib_esc_okuyucu() -> Callable[[], bool] | None:
    """XQueryKeymap tabanlı okuyucu — python-xlib yoksa None.

    Geçici içe aktarma: port/wayland'in portal arka ucu kurulunca buraya
    D-Bus tabanlı bir okuma eklemek mümkün ama portal global tuş durumu
    vermiyor; o yüzden şimdilik Xlib ya da hiç.
    """
    try:
        from Xlib import display as xdisplay  # type: ignore[import-not-found]
        from Xlib import XK  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        baglanti = xdisplay.Display()
        kod = baglanti.keysym_to_keycode(XK.string_to_keysym("Escape"))
    except Exception:
        return None

    def oku() -> bool:
        try:
            izgara = baglanti.query_keymap()
            return bool(izgara[kod // 8] & (1 << (kod % 8)))
        except Exception:
            # Bağlantı koptuysa acil durdurmayı düşürme: En az bir kez
            # False dönmek, kullanıcının Esc'ini yok etmez.
            return False

    return oku