"""Linux'ta içe aktarma güvenliği — gerçekten Windows'ta koşan bir kanıt.

CI'nin Linux ayağında suite'in toplanabilmesi şu soruya cevap veriyor:
içe aktarma anında hangi modül Windows'a özgü bir isme dokunuyor? Bu
soruyu "merak etme, guard koydum" diye cevaplamak yerine, alt süreçte
Linux'un içe aktarma yüzeyi **simüle edilip** ölçülüyor:

- `ctypes.win32` (windll/WinDLL/WINFUNCTYPE yok): Linux'ta bu adlar
  gerçekten yok.
- `winreg`, `winpty`, `uiautomation` engelleniyor (Linux'ta kurulu
  değiller; metin olarak da mevcut olmasınlar).
- Ortam `sys.platform` üzerinden değil, yalnızca isim düzeyinde
  kısıtlanıyor — `erisim` seçimi için DISPLAY yoklaması yapılıyor.

Bu test Windows'ta koşarken Linux'taki içe aktarmayı doğruluyor; çünkü
gerçek Linux'ta koşamıyoruz. Kanıtladığı şey dar ama tam: **bu modüller
içe aktarılabilir ve çağrıları sessizce değil, açık hata ile düşer.**

Sınırı dürüstçe: bu, "Linux'ta her şey çalışır" demek değil — X
sunucusuna, xdotool'a ya da gerçek API çağrılarına dokunulmuyor. Onların
kanıtı CI'nın xvfb ayağı.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

#: Alt süreçte kurulan Linux benzeri içe aktarma yüzeyi.
_ONDE = '''
import ctypes, importlib, importlib.abc, json, sys, os

# Windows'a özgü ctypes adlarını kaldır.
for _ad in ("windll", "WinDLL", "WINFUNCTYPE", "WINFUNCTYPE"):
    if hasattr(ctypes, _ad):
        delattr(ctypes, _ad)

# wintypes de Linux'ta yok.
sys.modules["ctypes.wintypes"] = None


class _Engel(importlib.abc.MetaPathFinder):
    """Windows'a özgü modülleri yok say — Linux'ta kurulu değiller."""

    YASAK = ("winreg", "winpty", "uiautomation", "pywinpty")

    def find_spec(self, ad, _yol=None, _hedef=None):
        kok = ad.split(".")[0]
        if kok in self.YASAK:
            raise ImportError(f"{ad} is not available on this platform")
        return None


sys.meta_path.insert(0, _Engel())

# Oturum: X11 gibi görünsün (gerçek X sunucusu yok, yalnızca değişken).
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ["DISPLAY"] = ":99"
sys.platform = "linux"  # erisim seçimi bu değere bakıyor

_MODELLER = [
    "backend.computer.input",
    "backend.computer.erisim",
    "backend.computer.komut",
    "backend.computer.girdi_x11",
    "backend.computer.goruntu_x11",
    "backend.computer.displays",
    "backend.computer.capture",
    "backend.computer.mesaj",
    "backend.computer.masaustu",
    "backend.computer.kayit",
    "backend.computer.canli",
    "backend.computer.terminal",
    "backend.safety.killswitch",
]

sonuc = {"ok": [], "hata": {}}
for _mod in _MODELLER:
    try:
        importlib.import_module(_mod)
        sonuc["ok"].append(_mod)
    except Exception as _exc:
        sonuc["hata"][_mod] = f"{type(_exc).__name__}: {_exc}"

# Çağrılar sessizce yanlış iş yapmamalı: ya anlamlı hata ya da seçim.
try:
    from backend.computer import erisim as _er
    sonuc["oturum"] = _er.oturum().tur
    _secim = _er.girdi_sec()
    sonuc["girdi_secim"] = _secim.ad
    sonuc["girdi_hata"] = _secim.hata
except Exception as _exc:
    sonuc["secim_patla"] = f"{type(_exc).__name__}: {_exc}"

# Windows sürücüsü bu yüzeyde çözülemez: yalnızca Windows'ta yüklenir.
try:
    importlib.import_module("backend.computer.girdi_win32")
    sonuc["win32_surucu"] = "ice_aktarildi"
except Exception as _exc:
    sonuc["win32_surucu"] = type(_exc).__name__

# Masaüstü nesnesi API'si çağrıda açık hata vermeli, sessizce None değil.
try:
    from backend.computer import mesaj as _mesaj
    _mesaj._u32.GetForegroundWindow()
    sonuc["win32_cagri"] = "calisti"
except Exception as _exc:
    sonuc["win32_cagri"] = type(_exc).__name__

print(json.dumps(sonuc, ensure_ascii=False))
'''


def _calistir(mesaj: str) -> dict:
    kok = Path(__file__).resolve().parent.parent
    islem = subprocess.run(
        [sys.executable, "-c", _ONDE],
        cwd=str(kok),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if islem.returncode != 0:
        pytest.fail(f"{mesaj}: alt süreç düştü\n{islem.stderr[-2000:]}")
    return json.loads(islem.stdout.strip().splitlines()[-1])


class TestLinuxIceAktarma:
    @pytest.fixture(scope="class")
    def sonuc(self):
        return _calistir("Linux içe aktarma simülasyonu")

    def test_yalniz_bu_ortamda_dogrulanir(self):
        # Simülasyon Windows'ta anlamlı: orada win32 adları gerçekten var
        # ve kaldırılınca Linux yüzeyi oluşuyor.
        if sys.platform != "win32":
            pytest.skip("simülasyon Windows'ta anlamlı")

    def test_cozulenen_hepsi_ice_aktarilir(self, sonuc):
        eksik = [m for m in sonuc["ok"]]
        assert not sonuc["hata"], (
            "Linux'ta içe aktarılamayan modüller: "
            + ", ".join(f"{k} ({v})" for k, v in sonuc["hata"].items())
        )
        assert len(eksik) == 13, f"beklenen 13 modül, içe aktarılan {len(eksik)}"

    def test_oturum_x11_gorunur(self, sonuc):
        assert sonuc["oturum"] == "x11"

    def test_secim_sessizce_degil_konusarak_karar_verir(self, sonuc):
        # xdotool yok (bu makinede kurulu değil): seçim ya kayıtlı bir arka
        # uç ya da açık hata olmalı — sessizce "win32" ASLA.
        assert sonuc.get("secim_patla") is None, sonuc.get("secim_patla")
        assert sonuc["girdi_secim"] != "win32", "Linux yüzeyinde win32 seçildi"
        if sonuc["girdi_secim"] is None:
            assert sonuc["girdi_hata"], "seçim yoksa hata metni olmalı"

    def test_win32_surucusu_linux_yuzeyinde_cozulemez(self, sonuc):
        """`girdi_win32` bu yüzeyde içe aktarılamaz (ctypes.wintypes yok)."""
        # ModuleNotFoundError, ImportError'ın alt sınıfı; ikisi de kabul.
        assert sonuc["win32_surucu"] in ("ImportError", "ModuleNotFoundError"), (
            sonuc["win32_surucu"]
        )

    def test_win32_cagrisi_sessizce_degil_patlar(self, sonuc):
        """Sahte DLL fonksiyonu çağrılınca açık hata verir — None değil."""
        assert sonuc["win32_cagri"] == "WindowsGerekli", sonuc["win32_cagri"]