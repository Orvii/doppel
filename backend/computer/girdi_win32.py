"""Windows girdi sürücüsü — doğrudan Win32 SendInput.

`input.py`'nin genel arayüzünün arkasındaki Windows uygulaması. Buraya
taşınmasının sebebi port: `ctypes.wintypes` Linux'ta içe aktarılamıyor, bu
yüzden Windows'a özgü her şey tek bir modülde toplandı ve yalnızca oturum
Windows'tayken yükleniyor (`input._win()`).

Yaklaşım aynen korundu: fare için MOUSEEVENTF_VIRTUALDESK ile sanal
masaüstüne normalize mutlak koordinat, klavye için KEYEVENTF_UNICODE ile
ham kod noktası. İkincisi klavye düzeninden tamamen bağımsız — pyautogui
Türkçe karakterleri İngilizce düzende düşürüyordu.
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

from .displays import virtual_screen_rect
from .input import VK_NAMES, normalize_absolute, parse_combo

ULONG_PTR = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

WHEEL_DELTA = 120

# Fare tuşu adı -> (basma bayrağı, bırakma bayrağı)
_BUTTONS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def _send(*events: _INPUT) -> None:
    array = (_INPUT * len(events))(*events)
    sent = ctypes.windll.user32.SendInput(
        len(events), ctypes.byref(array), ctypes.sizeof(_INPUT)
    )
    if sent != len(events):
        raise OSError(
            f"SendInput sent {sent} of {len(events)} events "
            f"(GetLastError={ctypes.get_last_error()})"
        )


# Genişletilmiş bayrak gereken tuşlar — yoksa numpad eşdeğerleri olarak gider.
_EXTENDED = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B, 0x5D, 0x90}


def _key_event(vk: int, up: bool) -> _INPUT:
    flags = KEYEVENTF_KEYUP if up else 0
    if vk in _EXTENDED:
        flags |= KEYEVENTF_EXTENDEDKEY
    return _INPUT(type=INPUT_KEYBOARD, ki=_KEYBDINPUT(vk, 0, flags, 0, 0))


def move_to(vx: int, vy: int) -> None:
    """İmleci sanal masaüstü koordinatına taşır."""
    nx, ny = normalize_absolute(vx, vy, virtual_screen_rect())
    _send(
        _INPUT(
            type=INPUT_MOUSE,
            mi=_MOUSEINPUT(
                dx=nx,
                dy=ny,
                mouseData=0,
                dwFlags=MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
                time=0,
                dwExtraInfo=0,
            ),
        )
    )


def cursor_position() -> tuple[int, int]:
    point = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def click(vx: int, vy: int, button: str = "left", count: int = 1) -> None:
    """Verilen noktaya tıklar. count=2 çift, count=3 üçlü tıklama."""
    if button not in _BUTTONS:
        raise ValueError(f"Unknown mouse button: {button}")
    down, up = _BUTTONS[button]
    move_to(vx, vy)
    for i in range(count):
        if i:
            # Windows'un çift tıklama eşiği varsayılan 500 ms; 60 ms güvenli.
            time.sleep(0.06)
        _send(
            _INPUT(type=INPUT_MOUSE, mi=_MOUSEINPUT(0, 0, 0, down, 0, 0)),
            _INPUT(type=INPUT_MOUSE, mi=_MOUSEINPUT(0, 0, 0, up, 0, 0)),
        )


def mouse_down(button: str = "left") -> None:
    _send(_INPUT(type=INPUT_MOUSE, mi=_MOUSEINPUT(0, 0, 0, _BUTTONS[button][0], 0, 0)))


def mouse_up(button: str = "left") -> None:
    _send(_INPUT(type=INPUT_MOUSE, mi=_MOUSEINPUT(0, 0, 0, _BUTTONS[button][1], 0, 0)))


def scroll(direction: str, amount: int) -> None:
    """Tekerlek kaydırma. amount, tık sayısı. Konum çağıranın işi."""
    axis = {"up": (MOUSEEVENTF_WHEEL, 1), "down": (MOUSEEVENTF_WHEEL, -1),
            "right": (MOUSEEVENTF_HWHEEL, 1), "left": (MOUSEEVENTF_HWHEEL, -1)}
    if direction not in axis:
        raise ValueError(f"Unknown scroll direction: {direction}")
    flag, sign = axis[direction]
    delta = ctypes.c_long(sign * WHEEL_DELTA * amount).value & 0xFFFFFFFF
    _send(_INPUT(type=INPUT_MOUSE, mi=_MOUSEINPUT(0, 0, delta, flag, 0, 0)))


def press(combo: str, repeat: int = 1) -> None:
    """Tuş ya da kombinasyon basar: `"Return"`, `"ctrl+s"`, `"alt+F4"`."""
    codes = parse_combo(combo)
    for _ in range(repeat):
        _send(*[_key_event(vk, up=False) for vk in codes])
        _send(*[_key_event(vk, up=True) for vk in reversed(codes)])
        time.sleep(0.01)


#: Karakterler arası bekleme. Ölçülerek bulundu — aşağıdaki nota bakın.
TYPE_DELAY = 0.012


def type_text(text: str, delay: float = TYPE_DELAY) -> None:
    """Metni harfi harfine yazar, klavye düzeninden bağımsız.

    KEYEVENTF_UNICODE her karakteri ham kod noktası olarak gönderir, yani
    `ğüşıöç` ve `İ` Türkçe Q düzeni kurulu olmasa da doğru düşer. BMP dışı
    karakterler (emoji) UTF-16 vekil çiftine ayrılıyor.

    **Karakter başına bir SendInput çağrısı, arada bekleme ile.** İlk sürüm
    24 karakteri tek çağrıda toplu gönderiyordu; ölçümde 55 karakterlik bir
    metin Notepad'e 39 karakter olarak düştü — olaylar hedefin mesaj
    kuyruğunun tükettiğinden hızlı geliyordu ve arada kalanlar bozuluyordu.
    Kısa dizelerde sorun görünmüyordu, bu yüzden ancak tam metinle test
    edilince ortaya çıktı. Toplu gönderim bu iş için yanlış optimizasyon.

    Uzun metinlerde bu yavaş (~12 ms/karakter). Panoya yazıp Ctrl+V ile
    yapıştırmak çok daha hızlı ama kullanıcının panosunu eziyor ve her alanda
    çalışmıyor; o yol Faz 2'de ayrı bir fonksiyon olarak, yalnızca uzun
    metinler için eklenecek.
    """
    raw = text.encode("utf-16-le")
    units = [int.from_bytes(raw[i:i + 2], "little") for i in range(0, len(raw), 2)]

    for unit in units:
        _send(
            _INPUT(type=INPUT_KEYBOARD, ki=_KEYBDINPUT(0, unit, KEYEVENTF_UNICODE, 0, 0)),
            _INPUT(
                type=INPUT_KEYBOARD,
                ki=_KEYBDINPUT(0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, 0),
            ),
        )
        time.sleep(delay)


# Adlar burada çözülüyor: `input.py` kombinasyonu adlara ayırıyor, sanal tuş
# koduna çevirmek Windows sürücüsünün işi.
def _adlari_koda(adlar: list[str]) -> list[int]:
    kodlar = []
    for ad in adlar:
        if ad not in VK_NAMES:
            raise ValueError(f"Unknown key: {ad!r}")
        kodlar.append(VK_NAMES[ad])
    return kodlar


def tus_adlari_bas(adlar: list[str]) -> None:
    _send(*[_key_event(vk, up=False) for vk in _adlari_koda(adlar)])


def tus_adlari_birak(adlar: list[str]) -> None:
    _send(*[_key_event(vk, up=True) for vk in reversed(_adlari_koda(adlar))])