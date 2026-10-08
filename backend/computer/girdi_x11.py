"""Linux girdi sürücüleri — xdotool (XTEST) ve ydotool (uinput).

## Neden alt süreç, neden python-xlib değil

İki yol var: `python-xlib` süreç içinde X protokolünü konuşur (yeni bir
Python bağımlılığı), ya da `xdotool` alt süreç olarak çağrılır (yeni
bağımlılık sıfır, çağrı başına ~10-20 ms). Alt süreç seçildi: yeni bir
çalışma zamanı bağımlılığı getirmiyor ve xdotool zaten XTEST'in üstünde
duruyor — yani aynı çekirdek mekanizma, sadece süreç sınırının öbür
yanından. Bedeli her fare hareketinde bir süreç doğurma maliyeti; ölçülene
kadar bu bilinçli kabul.

## xdotool ve Wayland

XTEST yalnızca gerçek X11 oturumunda anlamlı. Wayland'de (XWayland
üzerinden bir `DISPLAY` görünse bile) xdotool imleci oynatır ama tıklama
yerel pencereye ulaşmaz — sessiz yarı-çalışma. Seçim o yüzden
`erisim.girdi_sec`'te: Wayland'de xdotool hiç denenmez.

## ydotool

Çekirdek uinput'a yazar; X11'de de Wayland'de de çalışır. Erişim için
udev kuralı gerekir — paketlemeye ait, burada hatırlatma:
`KERNEL=="uinput", GROUP="input", MODE="0660"` ve kullanıcı `input`
grubunda olmalı; daemon (ydotool.service) soketi
`/run/user/<uid>/ydotool.sock`.

**Sürüm farkı açıkça yazılıyor:** buradaki ydotool komut kurgusu 1.x CLI'si
için (`mousemove --absolute -x/-y`, `click --repeat`, `key ...:1`).
0.1.8'in `mousedown`/`mouseup`/`wheel` alt komutları 1.x'te yok; karşılığı
olmayan işler sessizce yanlış yapılmıyor, `Desteklenmiyor` ile söyleniyor.
Komut kurguları tek yerde ve tek tek test edilmiş; farklı sürümde düzeltme
ilgili `_argv_*` fonksiyonunda.
"""

from __future__ import annotations

import time
from collections.abc import Mapping

from . import komut

#: Karakterler arası bekleme; Windows tarafındaki ölçümün (12 ms) aynısı.
TYPE_DELAY = 0.012


class Desteklenmiyor(RuntimeError):
    """Bu sürücüde karşılığı olmayan bir iş istendi."""


#: Ad -> (xdotool keysym adı, ydotool KEY_* adı).
#: `input.py`'deki isim sözlüğünün Linux karşılığı; ikisi ayrı kalır çünkü
#: biri sanal tuş kodu, öteki keysym üretiyor.
ADLAR: dict[str, tuple[str, str]] = {
    "backspace": ("BackSpace", "KEY_BACKSPACE"),
    "tab": ("Tab", "KEY_TAB"),
    "return": ("Return", "KEY_ENTER"),
    "enter": ("Return", "KEY_ENTER"),
    "shift": ("shift", "KEY_LEFTSHIFT"),
    "ctrl": ("ctrl", "KEY_LEFTCTRL"),
    "control": ("ctrl", "KEY_LEFTCTRL"),
    "alt": ("alt", "KEY_LEFTALT"),
    "pause": ("Pause", "KEY_PAUSE"),
    "caps_lock": ("Caps_Lock", "KEY_CAPSLOCK"),
    "escape": ("Escape", "KEY_ESC"),
    "esc": ("Escape", "KEY_ESC"),
    "space": ("space", "KEY_SPACE"),
    "page_up": ("Prior", "KEY_PAGEUP"),
    "page_down": ("Next", "KEY_PAGEDOWN"),
    "end": ("End", "KEY_END"),
    "home": ("Home", "KEY_HOME"),
    "left": ("Left", "KEY_LEFT"),
    "up": ("Up", "KEY_UP"),
    "right": ("Right", "KEY_RIGHT"),
    "down": ("Down", "KEY_DOWN"),
    "print": ("Print", "KEY_SYSRQ"),
    "insert": ("Insert", "KEY_INSERT"),
    "delete": ("Delete", "KEY_DELETE"),
    "super": ("super", "KEY_LEFTMETA"),
    "win": ("super", "KEY_LEFTMETA"),
    "menu": ("Menu", "KEY_MENU"),
    "num_lock": ("Num_Lock", "KEY_NUMLOCK"),
    "scroll_lock": ("Scroll_Lock", "KEY_SCROLLLOCK"),
}
ADLAR.update({f"f{i}": (f"F{i}", f"KEY_F{i}") for i in range(1, 25)})
ADLAR.update({str(d): (str(d), f"KEY_{d}") for d in range(10)})
ADLAR.update(
    {chr(c).lower(): (chr(c).lower(), f"KEY_{chr(c)}")
     for c in range(ord("A"), ord("Z") + 1)}
)

#: Fare tuşu adı -> xdotool düğme numarası.
_XDOTOOL_DUGME = {"left": 1, "middle": 2, "right": 3}
#: xdotool tekerlek düğmeleri 4/5 dikey, 6/7 yatay.
_XDOTOOL_TEKERLEK = {"up": 4, "down": 5, "left": 6, "right": 7}
#: ydotool click kodları — 0xC0 sınıfı basma+bırakma birleşik biçim.
_YDOTOOL_DUGME = {"left": "0xC0", "middle": "0xC2", "right": "0xC1"}


def _combo_adlari(combo: str, sutun: int) -> list[str]:
    """`"ctrl+shift+s"` -> sürücü sözlüğündeki karşılıklar."""
    adlar = []
    for parca in combo.split("+"):
        ad = parca.strip().lower()
        if not ad:
            raise ValueError(f"Empty key name: {combo!r}")
        if ad not in ADLAR:
            raise ValueError(f"Unknown key: {parca!r} (in {combo!r})")
        adlar.append(ADLAR[ad][sutun])
    return adlar


class _Surucu:
    """İki sürücünün ortak gövdesi: ortam, ortak işler."""

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        self.env = dict(env or {})

    # Alt sınıflar doldurur.
    def _calistir(self, argv: list[str], zaman_asimi: float | None = 5.0) -> komut.KomutSonuc:
        raise NotImplementedError

    def move_to(self, vx: int, vy: int) -> None:
        raise NotImplementedError

    def cursor_position(self) -> tuple[int, int]:
        raise NotImplementedError

    def click(self, vx: int, vy: int, button: str = "left", count: int = 1) -> None:
        raise NotImplementedError

    def mouse_down(self, button: str = "left") -> None:
        raise NotImplementedError

    def mouse_up(self, button: str = "left") -> None:
        raise NotImplementedError

    def scroll(self, direction: str, amount: int) -> None:
        raise NotImplementedError

    def press(self, combo: str, repeat: int = 1) -> None:
        raise NotImplementedError

    def type_text(self, text: str, delay: float | None = None) -> None:
        raise NotImplementedError

    def tus_adlari_bas(self, adlar: list[str]) -> None:
        raise NotImplementedError

    def tus_adlari_birak(self, adlar: list[str]) -> None:
        raise NotImplementedError


class XdotoolSurucu(_Surucu):
    """XTEST yolu — xreal X11 oturumu."""

    def _calistir(self, argv: list[str], zaman_asimi: float | None = 5.0) -> komut.KomutSonuc:
        return komut.calistir(argv, env_ek=self.env, zaman_asimi=zaman_asimi)

    def move_to(self, vx: int, vy: int) -> None:
        self._calistir(["xdotool", "mousemove", str(vx), str(vy)])

    def cursor_position(self) -> tuple[int, int]:
        sonuc = self._calistir(["xdotool", "getmouselocation", "--shell"])
        degerler: dict[str, int] = {}
        for satir in sonuc.cikti.splitlines():
            anahtar, _, deger = satir.partition("=")
            if anahtar in ("X", "Y"):
                try:
                    degerler[anahtar] = int(deger)
                except ValueError:
                    raise komut.KomutHatasi(
                        f"xdotool getmouselocation returned {satir!r}"
                    ) from None
        if "X" not in degerler or "Y" not in degerler:
            raise komut.KomutHatasi(
                f"xdotool getmouselocation gave no position: {sonuc.cikti!r}"
            )
        return degerler["X"], degerler["Y"]

    def click(self, vx: int, vy: int, button: str = "left", count: int = 1) -> None:
        if button not in _XDOTOOL_DUGME:
            raise ValueError(f"Unknown mouse button: {button}")
        self.move_to(vx, vy)
        argv = ["xdotool", "click", "--delay", "60"]
        if count > 1:
            argv += ["--repeat", str(count)]
        argv.append(str(_XDOTOOL_DUGME[button]))
        self._calistir(argv)

    def mouse_down(self, button: str = "left") -> None:
        if button not in _XDOTOOL_DUGME:
            raise ValueError(f"Unknown mouse button: {button}")
        self._calistir(["xdotool", "mousedown", str(_XDOTOOL_DUGME[button])])

    def mouse_up(self, button: str = "left") -> None:
        if button not in _XDOTOOL_DUGME:
            raise ValueError(f"Unknown mouse button: {button}")
        self._calistir(["xdotool", "mouseup", str(_XDOTOOL_DUGME[button])])

    def scroll(self, direction: str, amount: int) -> None:
        if direction not in _XDOTOOL_TEKERLEK:
            raise ValueError(f"Unknown scroll direction: {direction}")
        argv = ["xdotool", "click", "--delay", "20"]
        if amount > 1:
            argv += ["--repeat", str(amount)]
        argv.append(str(_XDOTOOL_TEKERLEK[direction]))
        self._calistir(argv)

    def press(self, combo: str, repeat: int = 1) -> None:
        tus = "+".join(_combo_adlari(combo, 0))
        for _ in range(max(1, repeat)):
            self._calistir(["xdotool", "key", "--delay", "10", tus])
            time.sleep(0.01)

    def type_text(self, text: str, delay: float | None = None) -> None:
        """`xdotool type` — tek alt süreç, karakter başına değil.

        Windows'taki "karakter başına bir çağrı" sözleşmesi burada geçerli
        değil: orada sorun SendInput'un mesaj kuyruğunu boğmasıydı; xdotool
        zamanlamayı kendi içinde (`--delay`) tutuyor. Metin tek `argv`
        öğesi olarak gidiyor, kabuk yok.
        """
        ms = round((TYPE_DELAY if delay is None else delay) * 1000)
        argv = ["xdotool", "type", "--delay", str(ms)]
        if text.startswith("-"):
            # xdotool seçenek sanmasın.
            argv.append("--")
        argv.append(text)
        # Uzun metinde süre metinle büyür; sabit sınır uzun yazmayı keserdi.
        self._calistir(argv, zaman_asimi=None)

    def tus_adlari_bas(self, adlar: list[str]) -> None:
        self._calistir(["xdotool", "keydown", *[ADLAR[a][0] for a in adlar]])

    def tus_adlari_birak(self, adlar: list[str]) -> None:
        self._calistir(["xdotool", "keyup", *[ADLAR[a][0] for a in reversed(adlar)]])


class YdotoolSurucu(_Surucu):
    """uinput yolu — Wayland'de de çalışır, udev izni ister.

    1.x CLI'si varsayıldı (bkz. modül docstring'i). Karşılığı olmayan
    işler sessizce değil, yüksek sesle reddedilir.
    """

    def _calistir(self, argv: list[str], zaman_asimi: float | None = 5.0) -> komut.KomutSonuc:
        # DISPLAY ydotool'u ilgilendirmez; soket YDOTOOL_SOCKET ile seçilir.
        return komut.calistir(argv, env_ek=self.env or None, zaman_asimi=zaman_asimi)

    def move_to(self, vx: int, vy: int) -> None:
        self._calistir(
            ["ydotool", "mousemove", "--absolute", "-x", str(vx), "-y", str(vy)]
        )

    def cursor_position(self) -> tuple[int, int]:
        raise Desteklenmiyor(
            "ydotool cannot read the pointer position; use an xdotool session "
            "or ask the compositor"
        )

    def click(self, vx: int, vy: int, button: str = "left", count: int = 1) -> None:
        if button not in _YDOTOOL_DUGME:
            raise ValueError(f"Unknown mouse button: {button}")
        self.move_to(vx, vy)
        self._calistir(
            ["ydotool", "click", "--repeat", str(max(1, count)), _YDOTOOL_DUGME[button]]
        )

    def mouse_down(self, button: str = "left") -> None:
        raise Desteklenmiyor(
            "ydotool 1.x has no separate mousedown; drag is xdotool-only"
        )

    def mouse_up(self, button: str = "left") -> None:
        raise Desteklenmiyor(
            "ydotool 1.x has no separate mouseup; drag is xdotool-only"
        )

    def scroll(self, direction: str, amount: int) -> None:
        raise Desteklenmiyor(
            "ydotool 1.x has no wheel command; scrolling is xdotool-only"
        )

    def press(self, combo: str, repeat: int = 1) -> None:
        tuslar = _combo_adlari(combo, 1)
        for _ in range(max(1, repeat)):
            self._calistir(["ydotool", "key", "-d", "10", "+".join(tuslar)])
            time.sleep(0.01)

    def type_text(self, text: str, delay: float | None = None) -> None:
        ms = round((TYPE_DELAY if delay is None else delay) * 1000)
        self._calistir(["ydotool", "type", "-d", str(ms), text], zaman_asimi=None)

    def tus_adlari_bas(self, adlar: list[str]) -> None:
        # `KEY_A:1` — ydotool'un basılı tutma biçimi.
        self._calistir(
            ["ydotool", "key", "-d", "0", *[f"{ADLAR[a][1]}:1" for a in adlar]]
        )

    def tus_adlari_birak(self, adlar: list[str]) -> None:
        self._calistir(
            ["ydotool", "key", "-d", "0", *[f"{ADLAR[a][1]}:0" for a in reversed(adlar)]]
        )


def surucu_sec(secim) -> _Surucu:
    """`erisim.GirdiSecimi` cevabını somut sürücüye çevirir."""
    if secim.ad == "xdotool":
        return XdotoolSurucu(secim.env)
    if secim.ad == "ydotool":
        return YdotoolSurucu(secim.env)
    raise ValueError(f"Not an X11 input backend: {secim.ad!r}")