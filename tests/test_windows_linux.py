"""EWMH pencere arka ucu — fabrikasyon xprop/wmctrl çıktılarıyla.

Gerçek X sunucusuna, gerçek pencereye dokunulmuyor: `komut.calistir` ve
`komut.var_mi` sahteleniyor, doğrulanan şey **ayrıştırma ve karar**:
`_NET_ACTIVE_WINDOW` → kimlik, `_NET_WM_NAME` → başlık, `wmctrl -lG` →
dikdörtgen, ve oynanmış çıktıların (boş, çöp, pencere yok) dürüst
sonuçları. Wayland/ekransız oturumun **açık yokluğu** da burada pinli.
"""

from __future__ import annotations

import sys

import pytest

from backend.computer import komut, uia_linux, windows, windows_linux

#: Gerçek `xprop -root _NET_ACTIVE_WINDOW` satırı. Kimlik bilinçli olarak
#: `WMCTRL`nin ilk penceresiyle aynı: "firefox aktif" senaryosu bütün testte
#: tutarlı olsun.
AKTIF_SATIR = "_NET_ACTIVE_WINDOW(WINDOW): window id # 0x3e00003\n"
#: Pencere yokken X'in verdiği cevap.
AKTIF_YOK = "_NET_ACTIVE_WINDOW(WINDOW): window id # 0x0\n"
WM_NAME = '_NET_WM_NAME(UTF8_STRING) = "belge.txt - Not Defteri"\n'
WM_NAME_DUZ = 'WM_NAME(STRING) = "Duz Ad"\n'
PID_SATIR = "_NET_WM_PID(CARDINAL) = 1234\n"
WMCTRL = (
    "0x03e00003  0 host adli pencere - Firefox\n"
    "0x01600007  0 host ikinci pencere\n"
)
WMCTRL_G = (
    "0x03e00003  0 100 50 800 600 host adli pencere - Firefox\n"
    "0x01600007  0 0 0 1920 1080 host ikinci pencere\n"
)


class SahteKomut:
    """`komut.calistir` yerine geçen kayıtçı; argv'ye göre cevap verir."""

    def __init__(self, cevaplar: dict[str, komut.KomutSonuc] | None = None,
                 varsayilan: komut.KomutSonuc | None = None):
        self.cagrilar: list[list[str]] = []
        self._cevaplar = cevaplar or {}
        self._varsayilan = varsayilan or komut.KomutSonuc(0, "", "")

    def __call__(self, argv, env_ek=None, zaman_asimi=5.0):
        self.cagrilar.append(list(argv))
        anahtar = " ".join(argv)
        for kalip, sonuc in self._cevaplar.items():
            if kalip in anahtar:
                return sonuc
        return self._varsayilan


@pytest.fixture
def ewmh(monkeypatch):
    """Linux X11 oturumu; araçlar ve alt süreçler sahte."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("XDG_SESSION_TYPE", raising=False)
    monkeypatch.setattr(komut, "var_mi", lambda ad: f"/usr/bin/{ad}")
    return monkeypatch


def kur(monkeypatch, **kwargs) -> SahteKomut:
    sahte = SahteKomut(**kwargs)
    monkeypatch.setattr(komut, "calistir", sahte)
    return sahte


class TestAyristiricilar:
    def test_aktif_id(self):
        assert windows_linux.aktif_id_ayristir(AKTIF_SATIR) == 0x03E00003

    def test_aktif_id_pencere_yokken_none(self):
        assert windows_linux.aktif_id_ayristir(AKTIF_YOK) is None

    def test_aktif_id_bos_cikti(self):
        assert windows_linux.aktif_id_ayristir("") is None

    def test_baslik_utf8_kazanir(self):
        assert windows_linux.baslik_ayristir(WM_NAME_DUZ + WM_NAME) == \
            "belge.txt - Not Defteri"

    def test_baslik_wm_name_yedegi(self):
        assert windows_linux.baslik_ayristir(WM_NAME_DUZ) == "Duz Ad"

    def test_baslik_kacisli_tirnak(self):
        satir = '_NET_WM_NAME(UTF8_STRING) = "de\\"gil"\n'
        assert windows_linux.baslik_ayristir(satir) == 'de"gil'

    def test_baslik_tirnaksiz_deger(self):
        assert windows_linux.baslik_ayristir("WM_NAME(STRING) = yok\n") == ""

    def test_pid(self):
        assert windows_linux.pid_ayristir(PID_SATIR) == 1234

    def test_pid_yoksa_none(self):
        assert windows_linux.pid_ayristir("") is None

    def test_wmctrl_satirlari(self):
        assert windows_linux.wmctrl_satirlari_ayristir(WMCTRL) == [
            (0x03E00003, "adli pencere - Firefox"),
            (0x01600007, "ikinci pencere"),
        ]

    def test_wmctrl_bos_satirlari_atlar(self):
        assert windows_linux.wmctrl_satirlari_ayristir("\nbozuk\n") == []

    def test_wmctrl_geometri(self):
        assert windows_linux.wmctrl_geometri_ayristir(WMCTRL_G) == [
            (0x03E00003, 100, 50, 800, 600, "adli pencere - Firefox"),
            (0x01600007, 0, 0, 1920, 1080, "ikinci pencere"),
        ]


class TestForeground:
    def test_baslik_tam_zincir(self, ewmh):
        kur(ewmh, cevaplar={
            "-root _NET_ACTIVE_WINDOW": komut.KomutSonuc(0, AKTIF_SATIR, ""),
            "_NET_WM_NAME WM_NAME": komut.KomutSonuc(0, WM_NAME, ""),
        })
        assert windows.foreground_title() == "belge.txt - Not Defteri"

    def test_pencere_yoksa_bos_dize(self, ewmh):
        kur(ewmh, cevaplar={
            "-root _NET_ACTIVE_WINDOW": komut.KomutSonuc(0, AKTIF_YOK, ""),
        })
        assert windows.foreground_title() == ""
        assert windows.foreground_process() == ""

    def test_surec_proc_commdan_okunur(self, ewmh, monkeypatch):
        kur(ewmh, cevaplar={
            "-root _NET_ACTIVE_WINDOW": komut.KomutSonuc(0, AKTIF_SATIR, ""),
            "_NET_WM_PID": komut.KomutSonuc(0, PID_SATIR, ""),
        })
        monkeypatch.setattr(
            windows_linux, "_proc_comm", lambda pid: "firefox" if pid == 1234 else ""
        )
        assert windows.foreground_process() == "firefox"

    def test_pid_yayimlanmazsa_bos_dize(self, ewmh, monkeypatch):
        kur(ewmh, cevaplar={
            "-root _NET_ACTIVE_WINDOW": komut.KomutSonuc(0, AKTIF_SATIR, ""),
            "_NET_WM_PID": komut.KomutSonuc(0, "_NET_WM_PID(CARDINAL) = yok\n", ""),
        })
        assert windows.foreground_process() == ""


class TestPencere:
    def test_baslikla_bulma(self, ewmh):
        kur(ewmh, cevaplar={"wmctrl -l": komut.KomutSonuc(0, WMCTRL, "")})
        assert windows.find_window("firefox") == 0x03E00003
        assert windows.find_window("boyle-bir-sey-yok") == 0

    def test_dikdortgen(self, ewmh):
        kur(ewmh, cevaplar={"wmctrl -lG": komut.KomutSonuc(0, WMCTRL_G, "")})
        assert windows.window_rect("firefox") == (100, 50, 900, 650)

    def test_dikdortgen_bulunamazsa_none(self, ewmh):
        kur(ewmh, cevaplar={"wmctrl -lG": komut.KomutSonuc(0, WMCTRL_G, "")})
        assert windows.window_rect("yok-boyle-sey") is None

    def test_activate_kimlikle_dogrular(self, ewmh):
        sahte = kur(ewmh, cevaplar={
            "wmctrl -l": komut.KomutSonuc(0, WMCTRL, ""),
            "-i -a": komut.KomutSonuc(0, "", ""),
            "-root _NET_ACTIVE_WINDOW": komut.KomutSonuc(0, AKTIF_SATIR, ""),
        })
        assert windows.activate("firefox", timeout=0.5) is True
        assert any("-i" in argv and "-a" in argv for argv in sahte.cagrilar)

    def test_activate_wm_kabul_etmezse_false(self, ewmh):
        # `wmctrl -a` bir istek bırakır; WM kabul etmezse kimlik değişmez.
        kur(ewmh, cevaplar={
            "wmctrl -l": komut.KomutSonuc(0, WMCTRL, ""),
            "-i -a": komut.KomutSonuc(0, "", ""),
            "-root _NET_ACTIVE_WINDOW": komut.KomutSonuc(0, ACTIVE_BASKA, ""),
        })
        assert windows.activate("firefox", timeout=0.3) is False

    def test_activate_pencere_yoksa_false(self, ewmh):
        kur(ewmh, cevaplar={"wmctrl -l": komut.KomutSonuc(0, WMCTRL, "")})
        assert windows.activate("yok") is False

    def test_matches_foreground(self, ewmh):
        kur(ewmh, cevaplar={
            "-root _NET_ACTIVE_WINDOW": komut.KomutSonuc(0, AKTIF_SATIR, ""),
            "_NET_WM_NAME WM_NAME": komut.KomutSonuc(0, WM_NAME, ""),
        })
        assert windows.matches_foreground(None, "not defteri")
        assert not windows.matches_foreground(None, "firefox")


#: Başka bir pencere aktifken.
ACTIVE_BASKA = "_NET_ACTIVE_WINDOW(WINDOW): window id # 0x1111111\n"


class TestYokluk:
    def test_wayland_oturumunda_acik_yokluk(self, ewmh):
        ewmh.setenv("WAYLAND_DISPLAY", "wayland-0")
        with pytest.raises(windows_linux.PencereYonetimiYokHatasi) as exc:
            windows.foreground_title()
        assert "Wayland" in str(exc.value)

    def test_ekransiz_oturumda_acik_yokluk(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        with pytest.raises(windows_linux.PencereYonetimiYokHatasi):
            windows.foreground_title()

    def test_xprop_yoksa_acik_yokluk(self, ewmh, monkeypatch):
        monkeypatch.setattr(komut, "var_mi", lambda ad: None)
        assert not windows_linux.musait()
        with pytest.raises(windows_linux.PencereYonetimiYokHatasi) as exc:
            windows.foreground_title()
        assert "xprop" in str(exc.value)

    def test_wmctrl_yoksa_bulma_acik_hata(self, ewmh, monkeypatch):
        monkeypatch.setattr(
            komut, "var_mi", lambda ad: "/usr/bin/xprop" if ad == "xprop" else None
        )
        with pytest.raises(windows_linux.PencereYonetimiYokHatasi) as exc:
            windows.find_window("x")
        assert "wmctrl" in str(exc.value)

    def test_zaman_asimi_durust_hata(self, ewmh, monkeypatch):
        import subprocess

        def patla(argv, env_ek=None, zaman_asimi=5.0):
            raise subprocess.TimeoutExpired(argv[0], zaman_asimi)

        monkeypatch.setattr(komut, "calistir", patla)
        with pytest.raises(windows_linux.PencereYonetimiYokHatasi) as exc:
            windows.foreground_title()
        assert "did not answer" in str(exc.value)

    def test_yokluk_sebebi_wayland_der(self, ewmh):
        ewmh.setenv("WAYLAND_DISPLAY", "wayland-0")
        assert "Wayland" in windows_linux.yokluk_sebebi()

    def test_x11de_sebep_bos(self, ewmh):
        assert windows_linux.yokluk_sebebi() == ""
        assert windows_linux.musait()


class TestSecim:
    def test_linux_oturumunda_ewmh(self, ewmh):
        assert windows._linux_arka_uc() is windows_linux

    def test_windows_oturumunda_windows_yolu(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        assert windows._linux_arka_uc() is None

    def test_hata_adi_windows_modulunde_de_var(self):
        # Çağıranlar platforma göre import etmesin: ad `windows`da duruyor.
        assert windows.PencereYonetimiYokHatasi is \
            windows_linux.PencereYonetimiYokHatasi

    def test_gate_wayland_yoklugunda_dusmez(self, monkeypatch):
        """Wayland'de kapı çalışmaya devam etmeli; başlık süzgeci düşerken
        (okunamıyor) etiket süzgeci kalır — okunamayan pencere başlığı kapıyı
        çökertemez ve riskli etiket yine durdurur."""
        import backend.agent.dispatch as dispatch_mod

        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.setattr(
            dispatch_mod.uia, "etiket_noktada",
            lambda vx, vy: uia_linux.Etiket("Gönder", True),
        )
        from backend.agent.dispatch import Dispatcher, Denied
        from backend.computer.displays import Display, DisplayMap
        from backend.safety.killswitch import KillSwitch

        d = Dispatcher(
            DisplayMap([Display(0, 0, 0, 800, 600, True)]),
            capture=None, kill=KillSwitch(), approve=lambda *a: False,
        )
        # Tıklama işleyicisi gerçek girdi sürücüsü istiyor; burada kanıtlanan
        # şey kapının **tıklamadan önce** durdurması — işleyiciye hiç
        # varılmamalı.
        d._do_left_click = lambda payload: pytest.fail("tıklama kapıya rağmen çalıştı")
        with pytest.raises(Denied):
            d.run("left_click", {"coordinate": [10, 10]})

    def test_gate_wayland_basligi_okuyamasa_da_calisir(self, monkeypatch):
        """Etiket iyi huyluysa Wayland'de kapı soru sormaz, işleyici çalışır."""
        import backend.agent.dispatch as dispatch_mod

        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.setattr(
            dispatch_mod.uia, "etiket_noktada",
            lambda vx, vy: uia_linux.Etiket("Kaydet", True),
        )
        from backend.agent.dispatch import Dispatcher, ToolOutcome
        from backend.computer.displays import Display, DisplayMap
        from backend.safety.killswitch import KillSwitch

        d = Dispatcher(
            DisplayMap([Display(0, 0, 0, 800, 600, True)]),
            capture=None, kill=KillSwitch(), approve=lambda *a: False,
        )
        cagrildi = []
        d._do_left_click = lambda payload: (
            cagrildi.append(1) or ToolOutcome(content="tıklandı")
        )
        d.run("left_click", {"coordinate": [10, 10]})
        assert cagrildi == [1]