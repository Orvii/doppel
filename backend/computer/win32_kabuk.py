"""Windows kabuğu — modül düzeyindeki Win32 kurulumunun Linux karşılığı.

`masaustu`, `mesaj` ve `kayit` modül gövdesinde `ctypes.WinDLL(...)` çağırıp
`restype`/`argtypes` kuruyor. Bu satırlar Linux'ta modülün **içe
aktarılmasını** patlatıyordu; oysa Windows'a özgü sınıfların (STRUCT'lar)
tanımı ile gerçek API çağrısı ayrı şeyler. Kabuk ikisini ayırıyor:

- Windows'ta hiçbir şey değişmiyor: aynı `ctypes.WinDLL`, aynı `wintypes`.
- Linux'ta `WinDLL` sahte bir kutu döndürüyor. Kutunun fonksiyonları
  **çağrıldığında** `WindowsGerekli` fırlatıyor — sessizce None dönmek,
  yanlış veriyi doğru sanmak demek olurdu. `restype`/`argtypes` atamaları
  kutuya yazılabiliyor, yani modül gövdesi aynen çalışıyor.
- `wintypes` yedeği gerçek ctypes türleriyle kuruluyor (`DWORD` -> c_ulong
  vb.), böylece `ctypes.Structure` alt sınıfları Linux'ta da tanımlanıyor;
  boyut farkları önemsiz çünkü bu yapılar orada hiç örneklenmiyor.
"""

from __future__ import annotations

import ctypes
import sys

try:  # Windows: gerçek modül ve gerçek API'ler
    from ctypes import wintypes
    from ctypes import WinDLL, WINFUNCTYPE

    _GERCEK = True
except (ImportError, AttributeError):  # Linux: adlar yok
    _GERCEK = False


class WindowsGerekli(RuntimeError):
    """Windows API'si yalnızca Windows'ta çağrılabilir.

    İki platformda da tanımlı: içe aktaran taraf koşullu bakmak zorunda
    kalmasın. Windows'ta hiç fırlatılmaz.
    """


if _GERCEK:  # pragma: no cover - Windows'ta gerçek modül
    pass
else:

    class _SahteIslev:
        """Sahte DLL fonksiyonu: atama kabul eder, çağrıda açıkça patlar."""

        restype = None
        argtypes = None

        def __init__(self, ad: str):
            self._ad = ad

        def __call__(self, *_a, **_k):
            raise WindowsGerekli(
                f"{self._ad} is a Windows API call; this process is on "
                f"{sys.platform}"
            )

    class _SahteDll:
        def __init__(self, ad: str):
            self._ad = ad
            self._islevler: dict[str, _SahteIslev] = {}

        def __getattr__(self, ad: str) -> _SahteIslev:
            islev = self._islevler.get(ad)
            if islev is None:
                islev = _SahteIslev(f"{self._ad}.{ad}")
                self._islevler[ad] = islev
            return islev

    def WinDLL(ad: str, **_k):  # noqa: N802 - Windows adıyla birebir
        return _SahteDll(ad)

    WINFUNCTYPE = ctypes.CFUNCTYPE  # imza aynı: (restype, *argtypes)

    class _Yedekwintypes:
        """Gerçek ctypes karşılıkları — STRUCT tanımları Linux'ta da kurulsun."""

        BOOL = ctypes.c_long
        DWORD = ctypes.c_ulong
        HANDLE = ctypes.c_void_p
        HWND = ctypes.c_void_p
        LARGE_INTEGER = ctypes.c_longlong
        LONG = ctypes.c_long
        LPARAM = ctypes.c_ssize_t
        LPCWSTR = ctypes.c_wchar_p
        LPWSTR = ctypes.c_wchar_p
        WORD = ctypes.c_ushort
        BYTE = ctypes.c_ubyte

        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

    wintypes = _Yedekwintypes  # type: ignore[assignment]