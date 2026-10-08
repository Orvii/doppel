"""Ön plandaki pencere — girdi göndermeden önceki emniyet kilidi.

Bu modül Faz 1 doğrulaması sırasında bir kazadan doğdu: Notepad açılması
beklenirken öne gelmedi ve yazılan metin o an odakta olan başka bir pencereye,
bir sohbet kutusuna gitti; ardından gelen Return mesajı gönderdi.

Ders: `type_text` ve `press` hedefsizdir — nereye gittiklerini bilmezler,
odakta ne varsa oraya yazarlar. Ajan döngüsünde her klavye eylemi önce
`assert_foreground` ile hangi pencereye yazdığını doğrulamalı. Ekran
görüntüsündeki pencere ile odaktaki pencere aynı olmayabilir; arada geçen
saniyede kullanıcı sekme değiştirmiş olabilir.

## Port notu: seçim `erisim`den, gövde değişmedi

Linux'ta aynı sözleşmeyi EWMH arka ucu (`windows_linux.py`) veriyor;
seçim çağrı anında `erisim.oturum()`a soruluyor — başka yerde platform
dalı yok. `ctypes.wintypes` toleranslı içe aktarılıyor (`win32_kabuk`):
Linux'ta bu ad yok ve modülün içe aktarılması patlamamalı, yoksa ajanın
kendisi Linux'ta açılmazdı. Windows gövdesi birebir korundu.
"""

from __future__ import annotations

import ctypes
import time

from .win32_kabuk import wintypes
#: Linux arka ucunun "bu oturumda pencere yönetimi yok" hatası — burada da
#: adı var ki çağıranlar platforma göre import etmesin. Windows'ta hiç
#: fırlatılmaz; `win32_kabuk.WindowsGerekli` ile aynı desen.
from .windows_linux import PencereYonetimiYokHatasi  # noqa: F401


def _linux_arka_uc():
    """Bu oturum Linux mu? Öyleyse EWMH modülü, değilse None.

    `erisim` içe aktarılamazsa (beklenmez) Windows yolu korunuyor —
    oturum sorusunun tek kaynağı orası, yedek dar ve bilinçli.
    """
    try:
        from . import erisim

        if erisim.oturum().tur == "windows":
            return None
        from . import windows_linux

        return windows_linux
    except ImportError:  # pragma: no cover - erisim varken olmaz
        return None


class FocusError(RuntimeError):
    """Beklenen pencere odakta değil — girdi gönderilmedi."""


def foreground_title() -> str:
    """Ön plandaki pencerenin başlığı. Pencere yoksa boş dize."""
    linux = _linux_arka_uc()
    if linux is not None:
        return linux.foreground_title()
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def foreground_process() -> str:
    """Ön plandaki pencerenin çalıştırılabilir dosya adı, örn. `notepad.exe`."""
    linux = _linux_arka_uc()
    if linux is not None:
        return linux.foreground_process()
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""

    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(260)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(
            handle, 0, buffer, ctypes.byref(size)
        ):
            return ""
        return buffer.value.rsplit("\\", 1)[-1]
    finally:
        kernel32.CloseHandle(handle)


def wait_for_foreground(
    process: str | None = None,
    title_contains: str | None = None,
    timeout: float = 5.0,
    poll: float = 0.1,
) -> bool:
    """Beklenen pencere öne gelene kadar bekler. Geldiyse True."""
    if process is None and title_contains is None:
        raise ValueError("process ya da title_contains verilmeli")

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if matches_foreground(process, title_contains):
            return True
        time.sleep(poll)
    return False


def matches_foreground(process: str | None, title_contains: str | None) -> bool:
    if process is not None and foreground_process().lower() != process.lower():
        return False
    if title_contains is not None and title_contains.lower() not in foreground_title().lower():
        return False
    return True


def assert_foreground(
    process: str | None = None, title_contains: str | None = None
) -> None:
    """Beklenen pencere odakta değilse hata fırlatır — klavye eylemi öncesi kilit."""
    if not matches_foreground(process, title_contains):
        expected = process or f"a window with {title_contains!r} in its title"
        raise FocusError(
            f"{expected} was expected, but the foreground is "
            f"{foreground_process() or '<none>'} / {foreground_title()!r}. "
            f"No input was sent."
        )


def find_window(title_contains: str) -> int:
    """Başlığında verilen metin geçen ilk görünür pencerenin tutamağı.

    Yalnızca görünür ve başlıklı pencereler: Windows'ta her uygulamanın
    arka planda başlıksız yardımcı pencereleri oluyor ve onlardan birini
    öne getirmek hiçbir şey yapmıyor gibi görünüyor.
    """
    linux = _linux_arka_uc()
    if linux is not None:
        return linux.find_window(title_contains)
    hedef = title_contains.lower()
    bulunan: list[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def _gez(hwnd, _param):
        if not ctypes.windll.user32.IsWindowVisible(hwnd):
            return True
        uzunluk = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if uzunluk == 0:
            return True
        tampon = ctypes.create_unicode_buffer(uzunluk + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, tampon, uzunluk + 1)
        if hedef in tampon.value.lower():
            bulunan.append(hwnd)
            return False
        return True

    ctypes.windll.user32.EnumWindows(_gez, None)
    return bulunan[0] if bulunan else 0


def force_foreground(hwnd: int) -> None:
    """Bir pencereyi ön plana zorlar.

    Windows ön plan hırsızlığını engelliyor: `SetForegroundWindow` yalnızca
    çağıran süreç zaten ön plandaysa ya da yakın zamanda kullanıcı girdisi
    aldıysa çalışıyor. Kural şu: iki thread girdi kuyruğunu paylaşıyorsa
    biri diğerinin penceresini öne getirebiliyor. Ön plandaki thread'e
    geçici olarak bağlanıp izni alıyoruz.

    Sonucu doğrulamıyor — çağıran doğrulasın. Bu yalnızca çağrının
    yapılabilecek en iyi hâli.
    """
    linux = _linux_arka_uc()
    if linux is not None:
        return linux.force_foreground(hwnd)
    user32 = ctypes.windll.user32
    hedef_thread = user32.GetWindowThreadProcessId(hwnd, None)
    on_hwnd = user32.GetForegroundWindow()
    on_thread = user32.GetWindowThreadProcessId(on_hwnd, None) if on_hwnd else 0
    bizim_thread = ctypes.windll.kernel32.GetCurrentThreadId()

    bagli = []
    for thread in {on_thread, hedef_thread} - {0, bizim_thread}:
        if user32.AttachThreadInput(bizim_thread, thread, True):
            bagli.append(thread)
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetActiveWindow(hwnd)
    finally:
        for thread in bagli:
            user32.AttachThreadInput(bizim_thread, thread, False)


def activate(title_contains: str, timeout: float = 3.0) -> bool:
    """Pencereyi öne getirir. Getiremezse `False` — yalan söylemiyor.

    `SetForegroundWindow` Windows'ta her zaman çalışmıyor: başka bir süreç
    ön plandaysa ve bizim sürecimiz yakın zamanda girdi almadıysa sistem
    çağrıyı sessizce yok sayıp yalnızca görev çubuğunu yakıp söndürüyor.
    Bu yüzden sonuç varsayılmıyor, ön plana geçtiği **doğrulanıyor**.
    """
    linux = _linux_arka_uc()
    if linux is not None:
        return linux.activate(title_contains, timeout)
    hwnd = find_window(title_contains)
    if not hwnd:
        return False

    user32 = ctypes.windll.user32
    SW_RESTORE = 9
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)

    force_foreground(hwnd)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if title_contains.lower() in foreground_title().lower():
            return True
        time.sleep(0.05)
    return False


def window_rect(title_contains: str) -> tuple[int, int, int, int] | None:
    """Pencerenin sanal masaüstündeki dikdörtgeni: (sol, üst, sağ, alt)."""
    linux = _linux_arka_uc()
    if linux is not None:
        return linux.window_rect(title_contains)
    hwnd = find_window(title_contains)
    if not hwnd:
        return None
    rect = wintypes.RECT()
    if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return (rect.left, rect.top, rect.right, rect.bottom)
