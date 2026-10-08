"""XDG uygulama kataloğu — dosya düzeninde, gerçek `.desktop` içerikleriyle.

Testler geçici bir dizin ağacına gerçek dosyalar yazıp `XDG_DATA_HOME` /
`XDG_DATA_DIRS`ı oraya çeviriyor: `.desktop` ayrıştırma, NoDisplay/Hidden
süzgeci, alan kodu temizliği ve Exec çözümü gerçek dosya üzerinden
ölçülüyor. Hiçbir test gerçek `/usr/share`e dokunmuyor ve hiçbir uygulama
başlatılmıyor.
"""

from __future__ import annotations

import sys

import pytest

from backend.computer import apps, apps_linux


@pytest.fixture
def xdg(tmp_path, monkeypatch):
    """Geçici XDG ağacı; `.desktop` yazıp katalog okunabiliyor."""
    ev = tmp_path / "ev"
    ev.mkdir()
    paylasim = tmp_path / "usr-share"
    (paylasim / "applications").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(ev))
    monkeypatch.setenv("XDG_DATA_HOME", str(ev / ".local/share"))
    monkeypatch.setenv("XDG_DATA_DIRS", str(paylasim))
    monkeypatch.delenv("LANGUAGE", raising=False)
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.setenv("LANG", "tr_TR.UTF-8")
    # Oturum Linux'a çevriliyor: `apps.catalog` çağrısı bu arka uca gitsin
    # (yoksa Windows'ta koşarken Windows kaynağı okunur ve test anlamsızlaşır).
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    apps_linux._cache = None
    yield paylasim / "applications"
    apps_linux._cache = None


def yaz(dizin, ad: str, metin: str) -> str:
    yol = dizin / ad
    yol.parent.mkdir(parents=True, exist_ok=True)
    yol.write_text(metin, encoding="utf-8")
    return str(yol)


class TestAyristirma:
    def test_ilk_bolum_okunur(self):
        veri = apps_linux.girdi_ayristir(
            "[Desktop Entry]\nName=Firefox\nExec=firefox %u\n\n"
            "[Desktop Action new-window]\nName=Yeni Pencere\n"
        )
        assert veri["Name"] == "Firefox"
        assert veri["Exec"] == "firefox %u"
        assert "Yeni Pencere" not in veri.values()

    def test_yorum_ve_bos_satir_atlanir(self):
        veri = apps_linux.girdi_ayristir(
            "# yorum\n[Desktop Entry]\n\nName=Satranç\n"
        )
        assert veri == {"Name": "Satranç"}

    def test_bolum_disindaki_satir_yok_sayilir(self):
        veri = apps_linux.girdi_ayristir("Name=Kayip\n[Desktop Entry]\nName=Var\n")
        assert veri == {"Name": "Var"}


class TestAlanKodalari:
    def test_tek_kodlar_atilir(self):
        assert apps_linux.alan_kodlarini_temizle(["firefox", "%u"]) == ["firefox"]
        assert apps_linux.alan_kodlarini_temizle(
            ["gimp", "%f", "%F", "%i", "%c", "%k"]
        ) == ["gimp"]

    def test_gomulu_kod_silinir(self):
        assert apps_linux.alan_kodlarini_temizle(["--profile=%f"]) == ["--profile="]

    def test_ikili_yuzde_tek_olur(self):
        assert apps_linux.alan_kodlarini_temizle(["yuzde%%", "calis"]) == [
            "yuzde%", "calis",
        ]

    def test_bilinmeyen_yuzde_kodu_da_duser(self):
        # Bilinmeyen kodu korumak, uygulamaya ham `%z` göndermek olurdu;
        # kod çifti düşüyor, kalan harfler (`zz`) argümanda kalıyor.
        assert apps_linux.alan_kodlarini_temizle(["x%zzz"]) == ["xzz"]

    def test_yalniz_kod_kalirsa_bos_argv(self):
        assert apps_linux.exec_argv("%u") == []

    def test_tirnakli_exec_cozulur(self):
        assert apps_linux.exec_argv('"/opt/My App/run" --flag %F') == [
            "/opt/My App/run", "--flag",
        ]

    def test_kapanmamis_tirnak_bos_doner(self):
        assert apps_linux.exec_argv('"eksik tırnak --x') == []


class TestKatalog:
    def test_desktop_girdisi_bulunur(self, xdg):
        yaz(xdg, "firefox.desktop", "[Desktop Entry]\nType=Application\n"
            "Name=Firefox\nGenericName=Web Browser\nExec=firefox %u\n")
        bulunan = apps_linux.katalog(refresh=True)
        assert [a.name for a in bulunan] == ["Firefox"]
        assert bulunan[0].kind == "xdg"
        assert bulunan[0].alias == "Web Browser"
        assert bulunan[0].target.endswith("firefox.desktop")

    def test_yerel_ad_tercih_edilir(self, xdg):
        yaz(xdg, "tarayici.desktop", "[Desktop Entry]\nType=Application\n"
            "Name=Firefox\nName[tr]=Ateş Tilkisi\nExec=firefox\n")
        assert apps_linux.katalog(refresh=True)[0].name == "Ateş Tilkisi"

    def test_nodisplay_katalogda_yok(self, xdg):
        yaz(xdg, "arsiv.desktop", "[Desktop Entry]\nType=Application\n"
            "Name=Arşivleyici\nExec=ark\nNoDisplay=true\n")
        assert apps_linux.katalog(refresh=True) == []

    def test_hidden_katalogda_yok(self, xdg):
        yaz(xdg, "kaldirilmis.desktop", "[Desktop Entry]\nType=Application\n"
            "Name=Eski\nExec=eski\nHidden=true\n")
        assert apps_linux.katalog(refresh=True) == []

    def test_link_turu_atlanir(self, xdg):
        yaz(xdg, "baglanti.desktop", "[Desktop Entry]\nType=Link\nName=Site\nURL=https://x\n")
        assert apps_linux.katalog(refresh=True) == []

    def test_adsiz_girdi_atlanir(self, xdg):
        yaz(xdg, "adsiz.desktop", "[Desktop Entry]\nType=Application\nExec=hicbir\n")
        assert apps_linux.katalog(refresh=True) == []

    def test_kullanici_dizini_one_gecer(self, xdg, tmp_path, monkeypatch):
        ev_kok = tmp_path / "ev/.local/share/applications"
        yaz(ev_kok, "chrome.desktop", "[Desktop Entry]\nType=Application\n"
            "Name=Chrome Kişisel\nExec=chrome-kisisel\n")
        yaz(xdg, "chrome.desktop", "[Desktop Entry]\nType=Application\n"
            "Name=Chrome Sistem\nExec=chrome-sistem\n")
        bulunan = apps_linux.katalog(refresh=True)
        assert [a.name for a in bulunan] == ["Chrome Kişisel"]

    def test_bozuk_dosya_katalogu_dusurmez(self, xdg):
        (xdg / "bozuk.desktop").write_bytes(b"\xff\xfe bozuk metin")
        yaz(xdg, "saglam.desktop", "[Desktop Entry]\nType=Application\n"
            "Name=Saglam\nExec=saglam\n")
        assert [a.name for a in apps_linux.katalog(refresh=True)] == ["Saglam"]

    def test_onbellek_ikinci_taramayi_atlar(self, xdg):
        yaz(xdg, "bir.desktop", "[Desktop Entry]\nType=Application\n"
            "Name=Bir\nExec=bir\n")
        apps_linux.katalog(refresh=True)
        (xdg / "iki.desktop").write_text(
            "[Desktop Entry]\nType=Application\nName=Iki\nExec=iki\n",
            encoding="utf-8",
        )
        assert [a.name for a in apps_linux.katalog()] == ["Bir"]
        assert [a.name for a in apps_linux.katalog(refresh=True)] == ["Bir", "Iki"]


class TestArama:
    def test_genericname_ile_aramada_bulunur(self, xdg):
        yaz(xdg, "firefox.desktop", "[Desktop Entry]\nType=Application\n"
            "Name=Firefox\nGenericName=Web Browser\nExec=firefox\n")
        bulunan = apps.search("web browser")
        assert [a.name for a in bulunan] == ["Firefox"]

    def test_tam_ad_once_gelir(self, xdg):
        yaz(xdg, "bir.desktop", "[Desktop Entry]\nType=Application\n"
            "Name=Chrome Remote Desktop\nExec=a\n")
        yaz(xdg, "iki.desktop", "[Desktop Entry]\nType=Application\n"
            "Name=Chrome\nExec=b\n")
        bulunan = apps.search("chrome")
        assert bulunan[0].name == "Chrome"

    def test_turkce_harfle_aramada_bulunur(self, xdg):
        yaz(xdg, "editor.desktop", "[Desktop Entry]\nType=Application\n"
            "Name=Görüntü Düzenleyici\nExec=editor\n")
        assert apps.search("goruntu")[0].name == "Görüntü Düzenleyici"


class TestBaslatma:
    def test_exec_argv_degerlendirilir(self, xdg, monkeypatch):
        yol = yaz(xdg, "sahte.desktop", "[Desktop Entry]\nType=Application\n"
                  "Name=Sahte\nExec=sahte-uygulama --yeni %U\n")
        from backend.computer import komut

        # Program "PATH'te" sayılsın: gerçek dosya aramıyoruz.
        monkeypatch.setattr(komut, "var_mi", lambda ad: f"/usr/bin/{ad}")
        app = apps.App("Sahte", "xdg", yol)
        assert apps_linux.launch_argv(app) == ["sahte-uygulama", "--yeni"]

    def test_program_yoksa_gtk_launch_yedegi(self, xdg, monkeypatch):
        yol = yaz(xdg, "kirik.desktop", "[Desktop Entry]\nType=Application\n"
                  "Name=Kirik\nExec=olmayan-program %u\n")
        from backend.computer import komut

        monkeypatch.setattr(komut, "var_mi", lambda ad: None)
        app = apps.App("Kirik", "xdg", yol)
        assert apps_linux.launch_argv(app) == ["gtk-launch", "kirik"]

    def test_exec_tamamen_kiriksa_gtk_launch(self, xdg):
        yol = yaz(xdg, "bos.desktop", "[Desktop Entry]\nType=Application\n"
                  "Name=Bos\nExec=%U\n")
        app = apps.App("Bos", "xdg", yol)
        assert apps_linux.launch_argv(app) == ["gtk-launch", "bos"]

    def test_okunamayan_dosya_gtk_launcha_duser(self, tmp_path):
        app = apps.App("Yok", "xdg", str(tmp_path / "yok.desktop"))
        assert apps_linux.launch_argv(app) == ["gtk-launch", "yok"]


class TestSecim:
    def test_linux_oturumunda_xdg_arka_ucu(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setenv("DISPLAY", ":99")
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        assert apps._linux_arka_uc() is apps_linux

    def test_windows_oturumunda_windows_yolu(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        assert apps._linux_arka_uc() is None

    def test_katalog_linux_devreder(self, xdg, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setenv("DISPLAY", ":99")
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        yaz(xdg, "devredilen.desktop", "[Desktop Entry]\nType=Application\n"
            "Name=Devredilen\nExec=devredilen\n")
        assert [a.name for a in apps.catalog(refresh=True)] == ["Devredilen"]

    def test_launch_argv_xdg_icin_linuxa_gider(self, xdg):
        yol = yaz(xdg, "kopru.desktop", "[Desktop Entry]\nType=Application\n"
                  "Name=Kopru\nExec=%u\n")
        app = apps.App("Kopru", "xdg", yol)
        assert apps.launch_argv(app) == ["gtk-launch", "kopru"]