"""Platform ayrımı — Linux dalı Windows'ta sahtelerle sınanıyor.

Bu makinede Linux **çalıştırılamıyor**; buradaki testlerin hiçbiri Linux
çekirdeğine, gerçek bestecisine ya da gerçek masaüstüne dokunmuyor. Sınanan
şey karar mantığı: `isletim.WINDOWS` çevrildiğinde dalların doğru yola
girmesi, ve modüllerin Linux'ta **içe aktarılabilir** olması.

İçe aktarma testi ayrı bir süreçte koşuyor: `sys.platform` bu süreçte
sahtelenirse PySide6'nın kendi eklenti seçimi de etkilenirdi. Alt süreç
önce Qt'yi gerçek platformla kuruyor, sonra platformu değiştirip
`winreg`'i **engelliyor**. Guard kaldırılırsa çocuk süreç `ImportError`
ile ölüyor ve test bunu görüyor — dosya toplama aşamasında patlayan bir
`import winreg`, CI'da tam olarak böyle davranıyor.

Spek: `ctypes.wintypes` Linux'ta zaten içe aktarılabiliyor (VARIANT_BOOL
girdisi `#ifdef MS_WIN32` dışında). Kırılan şey `ctypes.WinDLL`/
`ctypes.windll` ve `winreg`; guard'lar onların üzerinde.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app import isletim


class TestMetinler:
    def test_etiket_platforma_gore(self, monkeypatch):
        monkeypatch.setattr(isletim, "WINDOWS", False)
        assert isletim.acilis_etiketi() == "Start at login"
        monkeypatch.setattr(isletim, "WINDOWS", True)
        assert isletim.acilis_etiketi() == "Start with Windows"

    def test_ipucu_platforma_gore(self, monkeypatch):
        monkeypatch.setattr(isletim, "WINDOWS", True)
        assert isletim.anahtar_ipucu().startswith("C:")
        monkeypatch.setattr(isletim, "WINDOWS", False)
        assert isletim.anahtar_ipucu() == "~/.ssh/id_ed25519"

    def test_yazi_tipi_windows_marka(self, monkeypatch):
        monkeypatch.setattr(isletim, "WINDOWS", True)
        assert isletim.yazi_tipi() == "Segoe UI Variable Text"
        assert isletim.mono_yazi_tipi() == "Cascadia Mono"


class TestQtTema:
    """Qt'ye sorulan şeyler — offscreen altında da cevap veriyor."""

    def test_koyu_tema_uc_degerli(self, qt_app):
        # Qt burada masaüstünün gerçek tercihini veriyor olabilir (offscreen
        # eklentisi Windows'ta yine okuyor); üç değerden biri olmalı ve
        # "kapalı" diye bir dördüncüsü olmamalı.
        cevap = isletim.qt_koyu_tema()
        assert cevap in (True, False, None)

    def test_koyu_tema_uygulama_yoksa_bilmiyorum(self, monkeypatch):
        # `QGuiApplication.instance()` yokken cevap uydurulmuyor.
        from PySide6.QtGui import QGuiApplication

        monkeypatch.setattr(QGuiApplication, "instance", staticmethod(lambda: None))
        assert isletim.qt_koyu_tema() is None
        assert isletim.qt_vurgu_rengi() is None

    def test_vurgu_rengi_ya_dogru_bicim_ya_yok(self, qt_app):
        renk = isletim.qt_vurgu_rengi()
        assert renk is None or (
            renk.startswith("#") and len(renk) == 7
        ), f"geçersiz renk: {renk!r}"

    def test_yazi_tipi_linux_sistemden(self, qt_app, monkeypatch):
        # Linux dalı uygulamanın yüzünü okuyor: kendi koyduğumuz bir yüz
        # aynen dönmeli. Sabit bir yüze "eşit değil" demek sıraya bağlı
        # kırılıyordu — oturumdaki QApplication'ı daha önce koşan bir test
        # `fluent.apply` ile kurmuş olabiliyor ve okunan yüz o zaman
        # Windows'un yüzü oluyor. Ölçülen şey okuma yolunun kendisi.
        from PySide6.QtGui import QFont

        monkeypatch.setattr(isletim, "WINDOWS", False)
        onceki = qt_app.font()
        qt_app.setFont(QFont("Test Sans", 10))
        try:
            assert isletim.yazi_tipi() == "Test Sans"
        finally:
            qt_app.setFont(onceki)
        assert isletim.mono_yazi_tipi() != "Cascadia Mono"


class TestSaydamlik:
    def test_windows_her_zaman_besteli(self, monkeypatch):
        monkeypatch.setattr(isletim, "WINDOWS", True)
        assert isletim.saydam_zemin_destekli() is True

    def test_wayland_besteliyor(self, monkeypatch):
        monkeypatch.setattr(isletim, "WINDOWS", False)
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        assert isletim.saydam_zemin_destekli() is True

    def test_bilinmeyen_platform_saydam_degil(self, qt_app, monkeypatch):
        # offscreen: besteci yok ve sorulamıyor. "Var" demek yarı saydam
        # bir pencereyi siyah kutu yapardı.
        monkeypatch.setattr(isletim, "WINDOWS", False)
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        assert isletim.saydam_zemin_destekli() is False

    def test_bestecisiz_cubuk_sade_zemine_dusuyor(self, qt_app, monkeypatch):
        """Besteci yoksa çubuğun çevresi siyah değil, uygulamanın zemini.

        Karar tek başına yetmiyor: `WA_TranslucentBackground` konmayınca
        pencerenin boyanmayan payını Qt siyah bırakıyordu — karar doğru,
        sonuç yine siyah kutu olurdu. Boyanan piksele bakılıyor.
        """
        from PySide6.QtWidgets import QApplication

        from app.commandbar import CommandBar
        from app.fluent import Tokens

        monkeypatch.setattr(isletim, "saydam_zemin_destekli", lambda: False)
        t = Tokens(
            dark=True, background="#202020", background_secondary="#1c1c1c",
            layer="#2a2a2a", card="#2b2b2b", card_hover="#2f2f2f",
            control="#2d2d2d", control_hover="#2f2f2f",
            control_pressed="#282828", subtle_hover="#2d2d2d",
            stroke="#313131", divider="#353535", control_stroke="#313131",
            text="#ffffff", text_secondary="#c8c8c8", text_tertiary="#8a8a8a",
            text_disabled="#5c5c5c", accent="#4cc2ff", accent_hover="#0091f8",
            accent_text="#4cc2ff", on_accent="#000000", critical="#ff99a4",
            caution="#fce100", success="#6ccb5f",
        )
        bar = CommandBar(t)
        bar.show()
        QApplication.processEvents()
        try:
            resim = bar.grab().toImage()
            kose = resim.pixelColor(0, 0)
            assert kose.alpha() == 255, "çubuğun payı boyanmıyor"
            assert kose.name() != "#000000", "siyah kutu: pay boyanmadı"
        finally:
            bar.close()


class TestDosyaAc:
    def test_windows_startfile(self, monkeypatch, tmp_path):
        import os as os_mod

        monkeypatch.setattr(isletim, "WINDOWS", True)
        cagri: list = []
        monkeypatch.setattr(os_mod, "startfile", lambda y: cagri.append(y),
                            raising=False)
        isletim.dosya_ac(tmp_path / "a.txt")
        assert cagri == [str(tmp_path / "a.txt")]

    def test_windows_startfile_duserse_defter(self, monkeypatch, tmp_path):
        import os as os_mod
        import subprocess as sp

        def patla(_y):
            raise OSError("yok")

        monkeypatch.setattr(isletim, "WINDOWS", True)
        monkeypatch.setattr(os_mod, "startfile", patla, raising=False)
        gelen: list = []
        monkeypatch.setattr(sp, "Popen", lambda a: gelen.append(a))
        isletim.dosya_ac(tmp_path / "a.txt")
        assert gelen and gelen[0][0] == "notepad.exe"

    def test_linux_xdg_open_once_denenir(self, monkeypatch, tmp_path):
        import subprocess as sp

        monkeypatch.setattr(isletim, "WINDOWS", False)
        gelen: list = []
        monkeypatch.setattr(sp, "Popen", lambda a: gelen.append(a))
        isletim.dosya_ac(tmp_path / "a.txt")
        assert gelen == [["xdg-open", str(tmp_path / "a.txt")]]

    def test_linux_xdg_yoksa_gio(self, monkeypatch, tmp_path):
        # xdg-open her masaüstünde yok; gio'ya düşülmeli.
        import subprocess as sp

        monkeypatch.setattr(isletim, "WINDOWS", False)
        gelen: list = []

        def p(parcalar):
            gelen.append(parcalar)
            if parcalar[0] == "xdg-open":
                raise FileNotFoundError("xdg-open yok")

        monkeypatch.setattr(sp, "Popen", p)
        isletim.dosya_ac(tmp_path / "a.txt")
        assert gelen == [
            ["xdg-open", str(tmp_path / "a.txt")],
            ["gio", "open", str(tmp_path / "a.txt")],
        ]

    def test_hicbiri_yoksa_sessiz_kalmiyor(self, monkeypatch, tmp_path):
        # Sessiz kalmak düğmeyi bozuk gösterir; çağıran uyarı çıkarıyor.
        import subprocess as sp

        monkeypatch.setattr(isletim, "WINDOWS", False)
        monkeypatch.setattr(sp, "Popen",
                            lambda a: (_ for _ in ()).throw(OSError("yok")))
        with pytest.raises(OSError):
            isletim.dosya_ac(tmp_path / "a.txt")


class TestLinuxIceAktarma:
    """Linux'ta modüller içe aktarılabilmeli — dosya toplaması buna bakıyor.

    Alt süreç, gerçek Linux'un yaptığını taklit ediyor: `sys.platform`
    değişiyor, `winreg` engelleniyor. Guard kalkarsa çocuk ölüyor.
    """

    KOD = '''
import sys, types
sys.path.insert(0, {kok!r})

# Qt'yi gerçek platformla kur: eklenti seçimi sys.platform'a bakıyor ve
# sahtelemeden önce kurulması gerekiyor.
from PySide6.QtWidgets import QApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket  # noqa: F401
app = QApplication([])

sys.platform = "linux"
sys.modules["winreg"] = None          # `import winreg` -> ImportError
sys.modules["fcntl"] = types.ModuleType("fcntl")

import os
os.environ["XDG_CONFIG_HOME"] = {xdg!r}

from app import isletim, baslangic, fluent, single, kisayol
assert isletim.WINDOWS is False, "platform anahtarı Linux'a geçmedi"
assert baslangic.winreg is None and fluent.winreg is None
assert single.ctypes is None and kisayol.ctypes is None

# Arayüz gerçekten kurulabiliyor mu — offscreen, X11'e dokunmadan.
from app.tepsi import Tepsi
t = fluent.tokens()
tepsi = Tepsi(t)
adlar = [a.text() for a in tepsi._menu.actions() if not a.isSeparator()]
assert adlar[2] == "Start at login", adlar
assert len(adlar) == 5, adlar

from app.commandbar import CommandBar
bar = CommandBar(t)

from app.window import MainWindow
w = MainWindow(t)
w.attach_bar(bar)

ks = kisayol.kur()
assert not ks.kayitli and "not available" in ks.hata
print("OK", flush=True)
'''

    def test_linux_dali_ice_aktarilir_ve_kurulur(self, tmp_path):
        import subprocess

        kok = Path(__file__).resolve().parent.parent
        xdg = tmp_path / "config"
        xdg.mkdir()
        kod = tmp_path / "cocuk.py"
        kod.write_text(self.KOD.format(kok=str(kok), xdg=str(xdg)),
                       encoding="utf-8")
        ortam = {**__import__("os").environ, "QT_QPA_PLATFORM": "offscreen"}
        sonuc = subprocess.run(
            [sys.executable, str(kod)], capture_output=True, text=True,
            timeout=120, env=ortam,
        )
        assert sonuc.returncode == 0, sonuc.stderr[-2000:]
        assert "OK" in sonuc.stdout