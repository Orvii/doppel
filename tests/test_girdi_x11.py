"""Linux girdi/yakalama yolu — sahtelenmiş alt süreçlerle.

Hiçbir test gerçek X sunucusuna, xdotool'a, xrandr'a ya da Windows
API'sine dokunmuyor: alt süreç katmanı (`komut.calistir`) ve yoklamalar
sahteleniyor, doğrulanan şey sahteye **ne verildiği** — argv'ler,
dönüş ayrıştırma, seçim sırası. Bu dosya Windows'ta da Linux'ta da
aynı şekilde koşar: platform yalnızca `sys.platform` sahtelenerek
değiştiriliyor, gerçek API çağrılmıyor.

Gerçek X sunucusunda ölçüm ayrı iş: CI'daki xvfb ayağı (port-ci).
"""

from __future__ import annotations

import io
import sys

import pytest
from PIL import Image

from backend.computer import erisim, komut
from backend.computer.displays import Display, DisplayMap


class SahteKomut:
    """`komut.calistir` yerine geçen kayıtçı. Kayıtlı argv listeleri döndürür."""

    def __init__(self, sonuclar: list[komut.KomutSonuc] | None = None):
        self.cagrilar: list[tuple[list[str], dict]] = []
        self._sonuclar = list(sonuclar or [])

    def __call__(self, argv, env_ek=None, zaman_asimi=5.0):
        self.cagrilar.append((argv, {"env_ek": env_ek, "zaman_asimi": zaman_asimi}))
        if self._sonuclar:
            return self._sonuclar.pop(0)
        return komut.KomutSonuc(0, "", "")

    @property
    def argvler(self) -> list[list[str]]:
        return [argv for argv, _ in self.cagrilar]


class SahteSarici:
    """`komut.var_mi` yerine geçer."""

    def __init__(self, kurulu: set[str]):
        self.kurulu = kurulu

    def __call__(self, ad: str):
        return f"/usr/bin/{ad}" if ad in self.kurulu else None


@pytest.fixture
def linux(monkeypatch):
    """platform=linux + sahte ortam; gerçek API'lere dokunulmaz."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("YDOTOOL_SOCKET", raising=False)
    # Windows'ta os.getuid yok; sahte soket yolu env'den gelecek.
    monkeypatch.setattr(erisim, "_ydotool_varsayilan_soket", lambda: None)
    yield monkeypatch


class TestOturum:
    def test_windows_gercek_platform(self):
        # Bu makinede (windows) oturum türü windows olmalı.
        if sys.platform == "win32":
            assert erisim.oturum().tur == "windows"

    def test_x11(self, linux, monkeypatch):
        monkeypatch.setenv("DISPLAY", ":0")
        o = erisim.oturum()
        assert o.tur == "x11"
        assert o.x_goster == ":0"

    def test_wayland_once_gelir(self, linux, monkeypatch):
        # XWayland yüzünden DISPLAY doludur ama oturum Wayland'dir.
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        assert erisim.oturum().tur == "wayland"

    def test_tamamen_bas_kesik(self, linux):
        o = erisim.oturum()
        assert o.tur == "headless"
        assert not o.x_var


class TestGirdiSecimi:
    def test_headless_anlasilir_hata(self, linux):
        secim = erisim.girdi_sec()
        assert secim.ad is None
        assert "DISPLAY" in secim.hata

    def test_x11_xdotool_sec(self, linux, monkeypatch):
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.setattr(erisim.komut, "var_mi", SahteSarici({"xdotool"}))
        monkeypatch.setattr(
            erisim.komut, "calistir", SahteKomut([komut.KomutSonuc(0, "1920 1080", "")])
        )
        secim = erisim.girdi_sec()
        assert secim.ad == "xdotool"
        assert secim.env["DISPLAY"] == ":0"

    def test_x11_yoklama_dusunce_ydotool_a_gecer(self, linux, monkeypatch):
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
        monkeypatch.setenv("YDOTOOL_SOCKET", "/run/user/1000/ydotool.sock")
        monkeypatch.setattr(erisim.komut, "var_mi", SahteSarici({"xdotool", "ydotool"}))
        # xdotool kurulu ama ölü ekran: yoklama hata veriyor.
        monkeypatch.setattr(erisim.komut, "calistir", SahteKomut([komut.KomutSonuc(1, "", "x")]))
        monkeypatch.setattr(erisim.os.path, "exists", lambda _y: True)
        secim = erisim.girdi_sec()
        assert secim.ad == "ydotool"

    def test_wayland_xdotool_hic_denenmez(self, linux, monkeypatch):
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        monkeypatch.setenv("YDOTOOL_SOCKET", "/tmp/y.sock")
        monkeypatch.setattr(erisim.komut, "var_mi", SahteSarici({"xdotool", "ydotool"}))
        called = []
        monkeypatch.setattr(erisim, "xdotool_calisir", lambda *a, **k: called.append(1) or True)
        monkeypatch.setattr(erisim.os.path, "exists", lambda _y: True)
        secim = erisim.girdi_sec()
        assert secim.ad == "ydotool"
        assert called == [], "Wayland'de xdotool yoklanmamalı"

    def test_wayland_ydotool_yoksa_soyler(self, linux, monkeypatch):
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        monkeypatch.setattr(erisim.komut, "var_mi", SahteSarici(set()))
        secim = erisim.girdi_sec()
        assert secim.ad is None
        assert "ydotool" in secim.hata

    def test_kayitli_arka_uc_son_care(self, linux, monkeypatch):
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.setattr(erisim.komut, "var_mi", SahteSarici(set()))

        class SahtePortali:
            def __init__(self, env):
                self.env = env

        erisim.surucu_kaydet("portaltest", SahtePortali, lambda: True, tur="girdi")
        try:
            secim = erisim.girdi_sec()
            assert secim.ad == "portaltest"
            assert secim.sinif is SahtePortali
        finally:
            erisim._suruculer.pop("portaltest", None)

    def test_kurulu_ama_cevapsiz_xdotool_metni(self, linux, monkeypatch):
        # xdotool kurulu ama getdisplaygeometry ölü: hata bunu söylemeli,
        # "kurulu değil" dememeli.
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.setattr(erisim.komut, "var_mi", SahteSarici({"xdotool"}))
        monkeypatch.setattr(erisim.komut, "calistir", SahteKomut([komut.KomutSonuc(1, "", "x")]))
        secim = erisim.girdi_sec()
        assert "probe failed" in secim.hata

    def test_x_goster_verilince_headless_de_x_yolu(self, linux, monkeypatch):
        """Yan masa sözleşmesi: ana oturum yokken açık DISPLAY ile XTEST.

        port-ortam'ın Xvfb/Xephyr ekranı böyle çağrılacak — ortamda
        DISPLAY olmasa bile `x_goster` vermek X yolunu açar.
        """
        monkeypatch.setattr(erisim.komut, "var_mi", SahteSarici({"xdotool"}))
        monkeypatch.setattr(
            erisim.komut, "calistir", SahteKomut([komut.KomutSonuc(0, "1920 1080", "")])
        )
        secim = erisim.girdi_sec(x_goster=":99")
        assert secim.ad == "xdotool"
        assert secim.env["DISPLAY"] == ":99"

    def test_x_goster_olmadan_headless_hata(self, linux, monkeypatch):
        monkeypatch.setattr(erisim.komut, "var_mi", SahteSarici({"xdotool"}))
        assert erisim.girdi_sec().ad is None


class TestGoruntuSecimi:
    def test_x11_mss(self, linux, monkeypatch):
        monkeypatch.setenv("DISPLAY", ":0")
        assert erisim.goruntu_sec().ad == "mss"

    def test_headless_hata(self, linux):
        assert erisim.goruntu_sec().hata

    def test_wayland_kayitli_arka_uc(self, linux, monkeypatch):
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")

        class SahtePortal:
            def __init__(self, env):
                self.env = env

        erisim.surucu_kaydet("portalgoruntu", SahtePortal, lambda: True, tur="goruntu")
        try:
            secim = erisim.goruntu_sec()
            assert secim.ad == "portalgoruntu"
        finally:
            erisim._suruculer.pop("portalgoruntu", None)

    def test_wayland_kayit_yoksa_hata(self, linux, monkeypatch):
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        secim = erisim.goruntu_sec()
        assert secim.ad is None
        assert "portal" in secim.hata


class TestXdotoolKomutlari:
    def _surucu(self, monkeypatch, cevaplar=None):
        from backend.computer.girdi_x11 import XdotoolSurucu

        sahte = SahteKomut(cevaplar)
        monkeypatch.setattr(komut, "calistir", sahte)
        return XdotoolSurucu({"DISPLAY": ":0"}), sahte

    def test_move_to(self, monkeypatch):
        s, sahte = self._surucu(monkeypatch)
        s.move_to(100, 250)
        assert sahte.argvler == [["xdotool", "mousemove", "100", "250"]]
        assert sahte.cagrilar[0][1]["env_ek"] == {"DISPLAY": ":0"}

    def test_cursor_position_ayristirir(self, monkeypatch):
        s, _ = self._surucu(monkeypatch, [komut.KomutSonuc(0, "X=12\nY=34\nSCREEN=0\n", "")])
        assert s.cursor_position() == (12, 34)

    def test_cursor_position_beklenmeyen_cikti(self, monkeypatch):
        s, _ = self._surucu(monkeypatch, [komut.KomutSonuc(0, "çöp", "")])
        with pytest.raises(komut.KomutHatasi):
            s.cursor_position()

    def test_click_numara_ve_tekrar(self, monkeypatch):
        s, sahte = self._surucu(monkeypatch)
        s.click(5, 6, "right", count=2)
        assert sahte.argvler == [
            ["xdotool", "mousemove", "5", "6"],
            ["xdotool", "click", "--delay", "60", "--repeat", "2", "3"],
        ]

    def test_click_bilinmeyen_dugme(self, monkeypatch):
        s, _ = self._surucu(monkeypatch)
        with pytest.raises(ValueError, match="button"):
            s.click(0, 0, "pinky")

    def test_down_up(self, monkeypatch):
        s, sahte = self._surucu(monkeypatch)
        s.mouse_down("middle")
        s.mouse_up("middle")
        assert sahte.argvler == [["xdotool", "mousedown", "2"], ["xdotool", "mouseup", "2"]]

    def test_scroll_tekerlek_dugmeleri(self, monkeypatch):
        s, sahte = self._surucu(monkeypatch)
        s.scroll("down", 3)
        assert sahte.argvler == [["xdotool", "click", "--delay", "20", "--repeat", "3", "5"]]

    def test_press_keysym(self, monkeypatch):
        s, sahte = self._surucu(monkeypatch)
        s.press("ctrl+shift+Escape")
        assert sahte.argvler == [["xdotool", "key", "--delay", "10", "ctrl+shift+Escape"]]

    def test_press_bilinmeyen_tus(self, monkeypatch):
        s, _ = self._surucu(monkeypatch)
        with pytest.raises(ValueError, match="hyperspace"):
            s.press("ctrl+hyperspace")

    def test_type_text_delay_ve_kabuk_yok(self, monkeypatch):
        s, sahte = self._surucu(monkeypatch)
        s.type_text("ğüşıöç — merhaba")
        argv, kw = sahte.cagrilar[0]
        assert argv[:3] == ["xdotool", "type", "--delay"]
        assert argv[-1] == "ğüşıöç — merhaba"
        assert kw["zaman_asimi"] is None  # uzun metin keyfî kesilmesin

    def test_type_text_tire_ile_baslarsa_korunur(self, monkeypatch):
        s, sahte = self._surucu(monkeypatch)
        s.type_text("-s -f")
        assert sahte.argvler[0][-2:] == ["--", "-s -f"]

    def test_tus_adlari_bas_birak(self, monkeypatch):
        s, sahte = self._surucu(monkeypatch)
        s.tus_adlari_bas(["ctrl", "shift"])
        s.tus_adlari_birak(["ctrl", "shift"])
        assert sahte.argvler == [
            ["xdotool", "keydown", "ctrl", "shift"],
            ["xdotool", "keyup", "shift", "ctrl"],
        ]


class TestYdotoolKomutlari:
    def _surucu(self, monkeypatch):
        from backend.computer.girdi_x11 import YdotoolSurucu

        sahte = SahteKomut()
        monkeypatch.setattr(komut, "calistir", sahte)
        return YdotoolSurucu({}), sahte

    def test_move_to_absolute(self, monkeypatch):
        s, sahte = self._surucu(monkeypatch)
        s.move_to(10, 20)
        assert sahte.argvler == [["ydotool", "mousemove", "--absolute", "-x", "10", "-y", "20"]]

    def test_click_repeat(self, monkeypatch):
        s, sahte = self._surucu(monkeypatch)
        s.click(1, 2, "left", count=2)
        assert sahte.argvler[-1] == ["ydotool", "click", "--repeat", "2", "0xC0"]

    def test_press_kernel_adlari(self, monkeypatch):
        s, sahte = self._surucu(monkeypatch)
        s.press("ctrl+s")
        assert sahte.argvler == [["ydotool", "key", "-d", "10", "KEY_LEFTCTRL+KEY_S"]]

    def test_tus_tutma_bicimi(self, monkeypatch):
        s, sahte = self._surucu(monkeypatch)
        s.tus_adlari_bas(["ctrl"])
        s.tus_adlari_birak(["ctrl"])
        assert sahte.argvler == [
            ["ydotool", "key", "-d", "0", "KEY_LEFTCTRL:1"],
            ["ydotool", "key", "-d", "0", "KEY_LEFTCTRL:0"],
        ]

    def test_type_text(self, monkeypatch):
        s, sahte = self._surucu(monkeypatch)
        s.type_text("abc", delay=0.02)
        assert sahte.argvler == [["ydotool", "type", "-d", "20", "abc"]]

    @pytest.mark.parametrize("islem", ["mouse_down", "mouse_up"])
    def test_surukle_yok_soylenir(self, monkeypatch, islem):
        from backend.computer.girdi_x11 import Desteklenmiyor

        s, _ = self._surucu(monkeypatch)
        with pytest.raises(Desteklenmiyor, match="xdotool"):
            getattr(s, islem)("left")

    def test_scroll_yok_soylenir(self, monkeypatch):
        from backend.computer.girdi_x11 import Desteklenmiyor

        s, _ = self._surucu(monkeypatch)
        with pytest.raises(Desteklenmiyor):
            s.scroll("down", 1)

    def test_cursor_position_yok_soylenir(self, monkeypatch):
        from backend.computer.girdi_x11 import Desteklenmiyor

        s, _ = self._surucu(monkeypatch)
        with pytest.raises(Desteklenmiyor):
            s.cursor_position()


class TestKomut:
    def test_env_birlesir_ve_kabuk_yok(self, monkeypatch):
        kayit = {}

        class Sonuc:
            returncode, stdout, stderr = 0, "ok", ""

        def sahte_run(argv, **kw):
            kayit["argv"] = argv
            kayit["kw"] = kw
            return Sonuc()

        monkeypatch.setattr(komut.subprocess, "run", sahte_run)
        sonuc = komut.calistir(["xdotool", "type", "a"], env_ek={"DISPLAY": ":9"})
        assert sonuc.cikti == "ok"
        assert kayit["kw"]["env"]["DISPLAY"] == ":9"
        assert "shell" not in kayit["kw"]

    def test_yoksa_anlasilir_hata(self, monkeypatch):
        def patla(*_a, **_k):
            raise FileNotFoundError()

        monkeypatch.setattr(komut.subprocess, "run", patla)
        with pytest.raises(komut.KomutYokHatasi, match="ghosttool"):
            komut.calistir(["ghosttool"])


class TestGenelGirdiDevri:
    """`input.py` genel API'sinin sürücüye ne geçirdiği."""

    class Kayitci:
        def __init__(self):
            self.cagrilar = []

        def __getattr__(self, ad):
            def kaydet(*args, **kwargs):
                self.cagrilar.append((ad, args))
            return kaydet

    def _bagla(self, monkeypatch):
        from backend.computer import input as kb

        kayitci = self.Kayitci()
        monkeypatch.setattr(kb, "_surucu", lambda _g=None: kayitci)
        return kb, kayitci

    def test_click_gecirir(self, monkeypatch):
        kb, k = self._bagla(monkeypatch)
        kb.click(10, 20, "right", 2)
        assert k.cagrilar == [("click", (10, 20, "right", 2))]

    def test_modifiers_held_basli_tutar_ve_birakir(self, monkeypatch):
        kb, k = self._bagla(monkeypatch)
        with kb.modifiers_held("shift"):
            k.cagrilar.append(("ici", ()))
        assert [ad for ad, _ in k.cagrilar] == ["tus_adlari_bas", "ici", "tus_adlari_birak"]
        assert k.cagrilar[0][1] == (["shift"],)
        assert k.cagrilar[2][1] == (["shift"],)

    def test_modifiers_hata_olsa_da_birakir(self, monkeypatch):
        kb, k = self._bagla(monkeypatch)
        with pytest.raises(RuntimeError):
            with kb.modifiers_held("ctrl"):
                raise RuntimeError("içeride patladı")
        assert k.cagrilar[-1][0] == "tus_adlari_birak"

    def test_modifiers_bos_combo_dokunmaz(self, monkeypatch):
        kb, k = self._bagla(monkeypatch)
        with kb.modifiers_held(None):
            pass
        assert k.cagrilar == []

    def test_hold_her_halde_birakir(self, monkeypatch):
        kb, k = self._bagla(monkeypatch)
        monkeypatch.setattr(kb.time, "sleep", lambda _s: None)
        kb.hold("alt", 0.01)
        assert [ad for ad, _ in k.cagrilar] == ["tus_adlari_bas", "tus_adlari_birak"]

    def test_drag_bas_birak_cifti(self, monkeypatch):
        kb, k = self._bagla(monkeypatch)
        monkeypatch.setattr(kb.time, "sleep", lambda _s: None)
        kb.drag((0, 0), (10, 10), steps=2)
        adlar = [ad for ad, _ in k.cagrilar]
        assert adlar[0] == "move_to"
        assert adlar[1] == "mouse_down"
        assert adlar[-1] == "mouse_up"

    def test_bilinmeyen_tus_ortak_dogrulama(self, monkeypatch):
        kb, _ = self._bagla(monkeypatch)
        with pytest.raises(ValueError, match="hyperspace"):
            with kb.modifiers_held("hyperspace"):
                pass

    def test_surucu_secilemezse_acik_hata(self, monkeypatch, linux):
        from backend.computer import input as kb

        monkeypatch.setenv("DISPLAY", ":0")
        kb.secimi_sifirla()
        monkeypatch.setattr(erisim.komut, "var_mi", SahteSarici(set()))
        try:
            with pytest.raises(RuntimeError, match="No input backend"):
                kb.click(0, 0)
        finally:
            kb.secimi_sifirla()


class TestXrandrAyristirma:
    LISTE = (
        "Monitors: 3\n"
        " 0: +*DP-1 1920/527x1080/296+0+0  DP-1\n"
        " 1: +HDMI-1 1920/527x1080/296+1920+0  HDMI-1\n"
        " 2: +DP-2 2560/600x1440/340-2560+0  DP-2\n"
    )

    SORGU = (
        "Screen 0: minimum 320 x 200, current 3840 x 1080, maximum 16384 x 16384\n"
        "DP-1 connected primary 1920x1080+0+0 (normal left inverted right x axis y axis) 527mm x 296mm\n"
        "HDMI-1 connected 1920x1080+1920+0 (normal left inverted right x axis y axis) 527mm x 296mm\n"
        "DP-2 disconnected (normal left inverted right x axis y axis)\n"
    )

    def test_listmonitors_birincil_once_negatif_ofset(self):
        from backend.computer.goruntu_x11 import xrandr_monitorleri_coz

        ds = xrandr_monitorleri_coz(self.LISTE)
        assert [d.index for d in ds] == [0, 1, 2]
        assert ds[0].primary and ds[0].left == 0
        # Birincil önce, sonra soldan sağa: negatif ofsetli monitör (-2560)
        # 1920'den önce gelir.
        assert ds[1].left == -2560 and ds[1].width == 2560
        assert ds[2].left == 1920
        assert not ds[1].primary

    def test_sorgu_connected_satirlari(self):
        from backend.computer.goruntu_x11 import xrandr_sorgusunu_coz

        ds = xrandr_sorgusunu_coz(self.SORGU)
        assert len(ds) == 2  # disconnected atlandı
        assert ds[0].primary and ds[1].left == 1920

    def test_cop_girdi_bos_doner(self):
        from backend.computer.goruntu_x11 import (
            xrandr_monitorleri_coz,
            xrandr_sorgusunu_coz,
        )

        assert xrandr_monitorleri_coz("hiçbir şey") == []
        assert xrandr_sorgusunu_coz("hiçbir şey") == []

    def test_monitorler_listeden_sorguya_duser(self, monkeypatch):
        from backend.computer import goruntu_x11

        sahte = SahteKomut(
            [
                komut.KomutSonuc(1, "", "listmonitors desteklenmiyor"),
                komut.KomutSonuc(0, self.SORGU, ""),
            ]
        )
        monkeypatch.setattr(komut, "calistir", sahte)
        m = goruntu_x11.monitorler()
        assert len(m) == 2
        assert [argv[1] for argv, _ in sahte.cagrilar] == ["--listmonitors", "--query"]

    def test_monitorler_ikisi_de_copse_hata(self, monkeypatch):
        from backend.computer import goruntu_x11

        sahte = SahteKomut(
            [komut.KomutSonuc(0, "boş", ""), komut.KomutSonuc(1, "", "ekran yok")]
        )
        monkeypatch.setattr(komut, "calistir", sahte)
        with pytest.raises(RuntimeError, match="xrandr"):
            goruntu_x11.monitorler()

    def test_sanal_dikdortgen(self):
        from backend.computer.goruntu_x11 import sanal_dikdortgen

        ds = [
            Display(0, 0, 0, 1920, 1080, True),
            Display(1, -2560, 0, 2560, 1440, False),
        ]
        assert sanal_dikdortgen(ds) == (-2560, 0, 4480, 1440)


class TestYakalamaKapisi:
    def _map(self):
        return DisplayMap([Display(0, 0, 0, 640, 480, True)])

    def test_secim_yoksa_kurulum_aninda_hata(self, monkeypatch):
        from backend.computer import capture

        monkeypatch.setattr(
            capture.erisim, "goruntu_sec", lambda *_a, **_k: erisim.GirdiSecimi(None, None, {}, "yok")
        )
        with pytest.raises(RuntimeError, match="yok"):
            capture.ScreenCapture(self._map())

    def test_kayitli_arka_uc_grab_ve_frame(self, monkeypatch):
        from backend.computer import capture

        class SahteYakalayici:
            def __init__(self, env):
                self.gorulen = None

            def grab(self, display):
                self.gorulen = display
                return Image.new("RGB", (640, 480), "red")

        monkeypatch.setattr(
            capture.erisim,
            "goruntu_sec",
            lambda *_a, **_k: erisim.GirdiSecimi("pyntest", SahteYakalayici, {}, None),
        )
        cap = capture.ScreenCapture(self._map())
        kare = cap.grab(0)
        assert kare.display_index == 0
        assert (kare.width, kare.height) == (640, 480)  # iki sınırın da altında
        cap.close()

    def test_arka_uc_kucultme_karari_burada_kalir(self, monkeypatch):
        """Arka uç ham piksel verir; küçültme Frame.from_capture'ın işi."""
        from backend.computer import capture

        class SahteYakalayici:
            def __init__(self, env):
                pass

            def grab(self, display):
                return Image.new("RGB", (5000, 100), "red")

        monkeypatch.setattr(
            capture.erisim,
            "goruntu_sec",
            lambda *_a, **_k: erisim.GirdiSecimi("pyntest", SahteYakalayici, {}, None),
        )
        cap = capture.ScreenCapture(DisplayMap([Display(0, 0, 0, 5000, 100, True)]))
        kare = cap.grab(0)
        assert kare.width < 5000  # modele gideceği boyuta indirildi
        cap.close()


class TestKillswitchOkumaSecimi:
    def test_sozlesme_none_ya_da_sifir_argumanli(self, linux):
        """`esc_okuyucu` ya None ya da () -> bool bir çağrılabilir döner."""
        okuyucu = erisim.esc_okuyucu()
        if okuyucu is not None:
            assert callable(okuyucu)
            assert isinstance(okuyucu(), bool)

    def test_xlib_yokken_x11_none_doner(self, monkeypatch):
        """Xlib yokken X11'de okuma None — belgelenen geri çekilme yolu.

        Xlib kuruluysa sınanamaz (orada sözleşme "kurulur ve cevap verir")
        ve test atlanır; Xlib'siz ortamda — bu makine ve CI — gerçekten
        koşar, yani atlama bir şey gizlemiyor.
        """
        try:
            import Xlib  # noqa: F401
        except ImportError:
            pass
        else:
            pytest.skip("Xlib kurulu; None yolu sınanamaz")

        class SahteOturum:
            tur = "x11"

        monkeypatch.setattr(erisim, "oturum", lambda *_a, **_k: SahteOturum())
        assert erisim.esc_okuyucu() is None

    def test_okuma_yoksa_sinyaller_baglanir(self, linux, monkeypatch):
        import signal

        import backend.safety.killswitch as ks

        monkeypatch.setattr(erisim, "esc_okuyucu", lambda: None)
        baglanan = []
        monkeypatch.setattr(
            ks.signal, "signal", lambda isaret, isleyici: baglanan.append(isaret)
        )
        k = ks.KillSwitch()
        try:
            k.start()
            k.stop()
        except Exception:
            k.stop()
            raise
        assert set(baglanan) >= {signal.SIGINT, signal.SIGTERM}

    def test_uclu_basista_tetikler(self, monkeypatch):
        import backend.safety.killswitch as ks

        k = ks.KillSwitch()

        class Saat:
            simdi = 100.0

            @staticmethod
            def monotonic():
                return 100.0

            @staticmethod
            def sleep(_s):
                pass

        monkeypatch.setattr(ks, "time", Saat)
        okumalar = [False, True, False, True, False, True]

        def oku():
            deger = okumalar.pop(0) if okumalar else False
            if not okumalar:
                k._stop.set()  # döngüyü kapat
            return deger

        k._okuyucu = oku
        k._stop.clear()
        k._watch()
        assert k.triggered

    def test_pencereden_uzak_basista_tetiklemez(self, monkeypatch):
        import backend.safety.killswitch as ks

        k = ks.KillSwitch()

        class Saat:
            an = 0.0

            @classmethod
            def monotonic(cls):
                cls.an += 1.0  # her okuma bir saniye ileri: 3 basış 2 sn'ye yayılıyor
                return cls.an

            @staticmethod
            def sleep(_s):
                pass

        monkeypatch.setattr(ks, "time", Saat)
        okumalar = [True, False, True, False, True, False]

        def oku():
            if not okumalar:
                k._stop.set()
                return False
            return okumalar.pop(0)

        k._okuyucu = oku
        k._stop.clear()
        k._watch()
        assert not k.triggered