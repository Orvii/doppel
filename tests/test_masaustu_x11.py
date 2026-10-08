"""X11 yan masa — saf mantık testleri.

Gerçek X sunucusu, gerçek Xvfb, gerçek xdotool, gerçek ffmpeg YOK: hepsi
sahteleniyor (argv kayıtçısı, sahte süreç, sahte mss oturumu). Doğrulanan
şey sözleşme: hangi argv, hangi ortam, kapanış sırası, hangi hata.

Gerçek Xvfb'de ölçüm CI'nın xvfb ayağında; burada olmayan şey orada.
Bu dosya Windows'ta da Linux'ta da aynı şekilde koşar.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from backend.computer import ekran_x11, komut, masaustu_ortak
from backend.computer import masaustu_x11 as mx
from backend.computer.masaustu_ortak import Pencere


class SahteKomut:
    """`komut.calistir` yerine geçen kayıtçı."""

    def __init__(self, sonuclar=None):
        self.cagrilar: list[tuple[list[str], dict]] = []
        self._sonuclar = list(sonuclar or [])

    def __call__(self, argv, env_ek=None, zaman_asimi=5.0):
        self.cagrilar.append((argv, {"env_ek": env_ek,
                                     "zaman_asimi": zaman_asimi}))
        if self._sonuclar:
            return self._sonuclar.pop(0)
        return komut.KomutSonuc(0, "", "")

    @property
    def argvler(self):
        return [argv for argv, _ in self.cagrilar]


class SahteSurec:
    """Doğurulmuş süreç — `Popen`un kullanılan yüzeyi."""

    def __init__(self, pid=4242, olur=False):
        self.pid = pid
        self._olur = olur
        self.sinyaller: list[int] = []
        self.cagrilar: list[str] = []
        self.beklemeler: list[float | None] = []

    def poll(self):
        return 0 if self._olur else None

    def wait(self, timeout=None, **_k):
        self.beklemeler.append(timeout)
        if self._olur:
            return 0
        raise subprocess.TimeoutExpired(cmd="sahte", timeout=timeout or 0)

    def kill(self):
        self.cagrilar.append("kill")

    def terminate(self):
        self.cagrilar.append("terminate")

    def send_signal(self, isaret):
        self.sinyaller.append(isaret)


class SahteEkran:
    """`ekran_x11.Ekran`in yerine geçen en küçük şey."""

    def __init__(self, gosterge=":99"):
        self.gosterge = gosterge
        self.tur = "xvfb"
        self.surec = SahteSurec()
        self.durduruldu = 0

    def durdur(self, _bekleme=3.0):
        self.durduruldu += 1


class SahteMonitor:
    def __init__(self, en=1920, boy=1080, sol=0, ust=0):
        self._kutu = {"left": sol, "top": ust, "width": en, "height": boy}

    def __getitem__(self, anahtar):
        return self._kutu[anahtar]


class HamKare:
    def __init__(self, en, boy):
        self.size = (en, boy)
        self.bgra = bytes(en * boy * 4)


class SahteMss:
    """`mss.mss(display=...)` yerine geçen sahte oturum."""

    def __init__(self, en=1920, boy=1080):
        self.monitors = [SahteMonitor(en, boy)]
        self.grablar: list[dict] = []
        self.kapandi = False

    def grab(self, kutu):
        self.grablar.append(dict(kutu))
        return HamKare(kutu["width"], kutu["height"])

    def close(self):
        self.kapandi = True


def _calisma(**ayarlar):
    """(Calisma, ekran, sahte komut, sahte oturum) — hiçbir şeye dokunmaz."""
    ekran = ayarlar.pop("ekran", None) or SahteEkran()
    sahte = ayarlar.pop("komut", None) or SahteKomut()
    oturum = ayarlar.pop("oturum", None) or SahteMss()
    ac_sayaci = ayarlar.pop("ac_sayaci", None)
    dogurucu = ayarlar.pop("dogurucu", None)

    def ac(_olcu):
        if ac_sayaci is not None:
            ac_sayaci.append(1)
        return ekran

    c = mx.Calisma(ac=ac, calistir=sahte, oturum_ac=lambda _g: oturum,
                   dogurucu=dogurucu, **ayarlar)
    return c, ekran, sahte, oturum


def _geo(x, y, en, boy):
    return komut.KomutSonuc(0, f"X={x}\nY={y}\nWIDTH={en}\nHEIGHT={boy}\n", "")


def _pencere_sonuclari(*satirlar):
    """`pencere_listesi`nin beklediği sıra: search, sonra pencere başına
    geometri + ad + sınıf."""
    sonuclar = [komut.KomutSonuc(0, "\n".join(str(s[0]) for s in satirlar), "")]
    for _hwnd, x, y, en, boy, ad in satirlar:
        sonuclar.append(_geo(x, y, en, boy))
        sonuclar.append(komut.KomutSonuc(0, ad, ""))
        sonuclar.append(komut.KomutSonuc(1, "", ""))  # xprop yok
    return sonuclar


@pytest.fixture(autouse=True)
def _kayit_temizle():
    """Gösterge kaydı süreç geneli — her testten önce/sonra temiz."""
    masaustu_ortak.yan_birak()
    yield
    masaustu_ortak.yan_birak()


class TestYasamDongusu:
    def test_ac_sunucuyu_ve_kaydi_kuruyor(self):
        c, _, _, _ = _calisma()
        c.ac()
        assert c.gosterge == ":99"
        assert masaustu_ortak.aktif_gosterge() == ":99"

    def test_ac_idempotent(self):
        sayac: list[int] = []
        c, _, _, _ = _calisma(ac_sayaci=sayac)
        c.ac()
        c.ac()
        assert len(sayac) == 1

    def test_kapat_kaydi_birakiyor(self):
        c, ekran, _, _ = _calisma()
        c.ac()
        c.kapat()
        assert ekran.durduruldu == 1
        assert masaustu_ortak.aktif_gosterge() is None

    def test_kapat_oturumu_sunucudan_once_kapatiyor(self):
        """X bağlantısı, ölü ekrana grab denemeden kapanmalı."""
        sira: list[str] = []
        c, ekran, _, oturum = _calisma()
        oturum.close = lambda: sira.append("oturum")
        ekran.durdur = lambda _b=3.0: sira.append("sunucu")
        c.ac()
        c._oturum = oturum  # yakalama yapılmış gibi
        c.kapat()
        assert sira == ["oturum", "sunucu"]

    def test_context_manager(self):
        c, ekran, _, _ = _calisma()
        with c:
            assert c.gosterge == ":99"
        assert ekran.durduruldu == 1


class TestPencereler:
    def test_geometri_baslik_ve_hedef_ekran(self):
        c, _, sahte, _ = _calisma()
        sahte._sonuclar = _pencere_sonuclari((123, 10, 20, 800, 600, "Chrome"))
        c.ac()
        ps = c.pencereler()
        assert ps == [Pencere(hwnd=123, baslik="Chrome", sinif="",
                              x=10, y=20, en=800, boy=600)]
        # Her çağrı hedef ekranı taşıyor.
        assert all(kw["env_ek"]["DISPLAY"] == ":99"
                   for _argv, kw in sahte.cagrilar)
        # EWMH değil ağaç yürüyüşü: `search --onlyvisible`.
        assert sahte.argvler[0][:3] == ["xdotool", "search", "--onlyvisible"]

    def test_kucuk_pencereler_suzuluyor(self):
        c, _, sahte, _ = _calisma()
        sahte._sonuclar = _pencere_sonuclari(
            (1, 0, 0, 100, 50, "araç"),        # küçük — düşer
            (2, 0, 0, 800, 600, "gerçek"),
        )
        c.ac()
        assert [p.hwnd for p in c.pencereler()] == [2]

    def test_kutu_kapaliyken_bos_liste(self):
        c, _, _, _ = _calisma()
        assert c.pencereler() == []

    def test_pencere_bul_baslikla(self):
        c, _, sahte, _ = _calisma()
        sahte._sonuclar = _pencere_sonuclari((1, 0, 0, 800, 600, "Posta - Chromium"))
        c.ac()
        assert c.pencere_bul("posta").hwnd == 1

    def test_xdotool_olurse_konusuyor(self):
        c, _, sahte, _ = _calisma()
        sahte._sonuclar = [komut.KomutSonuc(1, "", "cannot open display")]
        c.ac()
        with pytest.raises(masaustu_ortak.MasaustuHatasi, match="display"):
            c.pencereler()

    def test_geometrisi_okunamayan_pencere_dusuyor(self):
        c, _, sahte, _ = _calisma()
        sahte._sonuclar = [
            komut.KomutSonuc(0, "1\n2\n", ""),
            komut.KomutSonuc(0, "çöp çıktı", ""),          # geometri bozuk
            _geo(0, 0, 800, 600),                          # 2 sağlam
            komut.KomutSonuc(0, "B", ""),
            komut.KomutSonuc(1, "", ""),
        ]
        c.ac()
        assert [p.hwnd for p in c.pencereler()] == [2]


class TestBaslat:
    def test_argv_ve_ortam_yalitimi(self):
        yakalanan = {}

        def dogurucu(argv, secenekler):
            yakalanan["argv"] = argv
            yakalanan["sec"] = secenekler
            return SahteSurec()

        c, _, _, _ = _calisma(dogurucu=dogurucu)
        c.ac()
        pid = c.baslat("firefox -new-window https://example.com")
        assert pid == 4242
        assert yakalanan["argv"] == ["firefox", "-new-window",
                                     "https://example.com"]
        assert yakalanan["sec"]["env"]["DISPLAY"] == ":99"

    def test_tirnakli_yol_argv_de_kaliyor(self):
        yakalanan = {}
        c, _, _, _ = _calisma(
            dogurucu=lambda argv, sec: yakalanan.update(argv=argv) or SahteSurec()
        )
        c.ac()
        c.baslat('"/opt/my apps/editor" --new')
        assert yakalanan["argv"] == ["/opt/my apps/editor", "--new"]

    def test_wayland_isareti_cocuga_gecmiyor(self, monkeypatch):
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        yakalanan = {}
        c, _, _, _ = _calisma(
            dogurucu=lambda argv, sec: yakalanan.update(sec=sec) or SahteSurec()
        )
        c.ac()
        c.baslat("xterm")
        assert "WAYLAND_DISPLAY" not in yakalanan["sec"]["env"]

    def test_bulunamayan_ikili_acik_hata(self):
        def dogurucu(_argv, _sec):
            raise FileNotFoundError(2, "No such file or directory: 'hayalet'")

        c, _, _, _ = _calisma(dogurucu=dogurucu)
        c.ac()
        with pytest.raises(masaustu_ortak.MasaustuHatasi, match="hayalet"):
            c.baslat("hayalet --arg")

    def test_bos_komut_reddediliyor(self):
        c, _, _, _ = _calisma()
        c.ac()
        with pytest.raises(masaustu_ortak.MasaustuHatasi, match="empty"):
            c.baslat("   ")


class TestTarayiciBayraklari:
    """Xvfb altında Chromium ailesi GPU'suz çalışsın — yalnızca yan masada."""

    @pytest.mark.parametrize("ad", [
        "google-chrome", "google-chrome-stable", "chromium",
        "chromium-browser", "brave-browser", "/usr/bin/google-chrome",
        "msedge", "electron",
    ])
    def test_tarayici_ailesi_bayrak_alir(self, ad):
        assert mx.tarayici_bayraklari(f"{ad} https://a") == list(mx.YAN_BAYRAKLAR)

    @pytest.mark.parametrize("metin", [
        "firefox https://a", "xterm", "gimp", "code --new-window",
        "/opt/chrome-ish/thing",  # benziyor ama değil
        "chrome-beta",            # sonek adı sayılmaz
    ])
    def test_digerleri_dokunulmaz(self, metin):
        assert mx.tarayici_bayraklari(metin) == []

    def test_baslat_bayragi_yalnizca_tarayiciya_ekliyor(self):
        argvler = []

        def dogurucu(argv, _sec):
            argvler.append(argv)
            return SahteSurec()

        c, _, _, _ = _calisma(dogurucu=dogurucu)
        c.ac()
        c.baslat("chromium https://a")
        c.baslat("firefox https://a")
        assert argvler[0] == ["chromium", "https://a", "--no-sandbox",
                              "--disable-gpu"]
        assert argvler[1] == ["firefox", "https://a"]


class TestSurecDurdurma:
    """SIGTERM → bekle → SIGKILL, grup hâlinde. kayit.py disiplini."""

    @pytest.mark.skipif(mx._SIGKILL is None,
                        reason="Windows'ta SIGKILL yok; sınanan Linux disiplini")
    def test_once_sigterm_sonra_sigkill(self, monkeypatch):
        isaretler: list[int] = []
        monkeypatch.setattr(mx, "_grup_sinyal",
                            lambda surec, isaret: isaretler.append(isaret))
        surec = SahteSurec()  # poll None, wait timeout → SIGKILL yolu
        mx._surec_durdur(surec, bekleme=0.01)
        assert isaretler == [mx.signal.SIGTERM, mx._SIGKILL]

    def test_sigkill_yoksa_kill_yoluna_duser(self, monkeypatch):
        """Windows'ta SIGKILL yok; modül orada patlamamalı, `kill()`e düşmeli."""
        isaretler: list[int] = []
        monkeypatch.setattr(mx, "_grup_sinyal",
                            lambda surec, isaret: isaretler.append(isaret))
        monkeypatch.setattr(mx, "_SIGKILL", None)
        surec = SahteSurec()
        mx._surec_durdur(surec, bekleme=0.01)
        assert isaretler == [mx.signal.SIGTERM]
        assert surec.cagrilar == ["kill"]

    def test_nazik_cevapta_oldurmuyor(self, monkeypatch):
        isaretler: list[int] = []
        monkeypatch.setattr(mx, "_grup_sinyal",
                            lambda surec, isaret: isaretler.append(isaret))
        surec = SahteSurec()
        surec.wait = lambda timeout=None, **_k: 0  # ilk beklemede öldü
        mx._surec_durdur(surec, bekleme=0.01)
        assert isaretler == [mx.signal.SIGTERM]

    def test_olen_surece_sinyal_yok(self, monkeypatch):
        isaretler: list[int] = []
        monkeypatch.setattr(mx, "_grup_sinyal",
                            lambda surec, isaret: isaretler.append(isaret))
        mx._surec_durdur(SahteSurec(olur=True))
        assert isaretler == []

    def test_kapat_surecleri_durduruyor(self, monkeypatch):
        durdurulanlar = []
        monkeypatch.setattr(mx, "_surec_durdur",
                            lambda s, bekleme=3.0: durdurulanlar.append(s))
        c, _, _, _ = _calisma()
        c.ac()
        c._surecler.extend([SahteSurec(1), SahteSurec(2)])
        c.kapat()
        assert [s.pid for s in durdurulanlar] == [1, 2]

    def test_sonlandir_pid_ile(self, monkeypatch):
        durdurulanlar = []
        monkeypatch.setattr(mx, "_surec_durdur",
                            lambda s, bekleme=3.0: durdurulanlar.append(s))
        c, _, _, _ = _calisma()
        c.ac()
        c._surecler.append(SahteSurec(pid=7))
        assert c.sonlandir(7) is True
        assert [s.pid for s in durdurulanlar] == [7]
        assert c.sonlandir(7) is False


class TestYakalama:
    def test_kirpma(self):
        m = SahteMonitor(1920, 1080)
        assert mx.kirp(10, 20, 800, 600, m) == (10, 20, 800, 600)
        assert mx.kirp(1500, 0, 800, 600, m) == (1500, 0, 420, 600)
        assert mx.kirp(2000, 0, 100, 100, m) is None
        assert mx.kirp(-40, -40, 100, 100, m) == (0, 0, 60, 60)

    def _tek_pencere(self, c, sahte, x=30, y=40, en=400, boy=300):
        sahte._sonuclar = [
            _geo(x, y, en, boy),
            komut.KomutSonuc(0, "B", ""),
            komut.KomutSonuc(1, "", ""),
        ]

    def test_yakala_pencere_kutusunu_grab_ediyor(self):
        c, _, sahte, oturum = _calisma()
        c.ac()
        self._tek_pencere(c, sahte)
        kare = c.yakala(5)
        assert oturum.grablar == [{"left": 30, "top": 40, "width": 400,
                                   "height": 300}]
        assert kare.image.size == (400, 300)
        assert kare.display_index == masaustu_ortak.GIZLI_EKRAN

    def test_kapali_kutu_yakalayamaz(self):
        c, _, _, _ = _calisma()
        with pytest.raises(masaustu_ortak.MasaustuHatasi, match="not open"):
            c.yakala(1)

    def test_imlec_ve_iz_ciziliyor(self):
        c, _, sahte, _ = _calisma()
        c.ac()
        self._tek_pencere(c, sahte, x=0, y=0)  # ofset yok: imleç koord
        kare = c.yakala(1, imlec=(100, 100), iz=[(90, 90)], tik=True)
        # Okun silueti imleç noktasının **altına** düşüyor (imlec.py
        # geometrisi): orada zemin rengi değişmiş olmalı. İz çizgisi de
        # (90,90)-(100,100) arasında görünür.
        assert kare.image.getpixel((100, 105)) != (0, 0, 0)
        assert kare.image.getpixel((95, 95)) != (0, 0, 0)

    def test_istemci_kutusu_pencerenin_kendisi(self):
        c, _, sahte, _ = _calisma()
        c.ac()
        sahte._sonuclar = [
            _geo(0, 0, 800, 600),
            komut.KomutSonuc(0, "B", ""),
            komut.KomutSonuc(1, "", ""),
        ]
        assert c.istemci_kutusu(1) == (0, 0, 800, 600)

    def test_ekranin_disindaki_pencere_soyleniyor(self):
        c, _, sahte, _ = _calisma()
        c.ac()
        self._tek_pencere(c, sahte, x=5000, y=0, en=400, boy=300)
        with pytest.raises(masaustu_ortak.MasaustuHatasi, match="outside"):
            c.yakala(1)


class TestSafYardimcilar:
    def test_shell_cikti_ayristirma(self):
        d = mx.ayristir_shell("WINDOW=123\nX=4\nY=5\nWIDTH=6\nHEIGHT=7\n")
        assert d == {"WINDOW": "123", "X": "4", "Y": "5",
                     "WIDTH": "6", "HEIGHT": "7"}

    def test_sinif_coz_ikinci_ad(self):
        assert mx.sinif_coz(
            'WM_CLASS(STRING) = "chrome", "Chromium"') == "Chromium"
        assert mx.sinif_coz('WM_CLASS(STRING) = "tek"') == "tek"
        assert mx.sinif_coz("") == ""

    def test_yan_masa_kur_linux_x11(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        c = masaustu_ortak.yan_masa_kur()
        assert type(c).__module__ == "backend.computer.masaustu_x11"

    def test_yan_masa_kur_windows_masaustu(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        c = masaustu_ortak.yan_masa_kur()
        assert type(c).__module__ == "backend.computer.masaustu"


class _Kayitci:
    """Sürücü yerine geçen kayıtçı: her metot çağrısını yazıyor."""

    def __init__(self):
        self.cagrilar: list[tuple[str, tuple]] = []

    def __getattr__(self, ad):
        def kaydet(*args, **_kw):
            self.cagrilar.append((ad, args))
        return kaydet


class TestMesajX11Dali:
    """`mesaj.Girdi` yan ekran açıkken xdotool sürücüsüne konuşuyor."""

    def _girdi(self, monkeypatch, gosterge=":99"):
        from backend.computer import erisim, mesaj

        monkeypatch.setattr(mesaj, "aktif_gosterge", lambda: gosterge)
        monkeypatch.setattr(
            erisim, "girdi_sec",
            lambda *_a, **_k: erisim.GirdiSecimi(
                "xdotool", None, {"DISPLAY": gosterge}, None),
        )
        kayitci = _Kayitci()
        monkeypatch.setattr(
            "backend.computer.girdi_x11.XdotoolSurucu",
            lambda env: kayitci,
        )
        mesaj.kanali_sifirla()
        girdi = mesaj.Girdi()
        girdi._kayitci = kayitci
        return girdi

    def test_tikla_tasi_ve_tikla(self, monkeypatch):
        girdi = self._girdi(monkeypatch)
        girdi.tikla(1, 2, 3)
        assert [c[0] for c in girdi._kayitci.cagrilar] == ["move_to", "click"]
        assert girdi._kayitci.cagrilar[1][1] == (2, 3, "left", 1)
        assert (girdi.imlec.x, girdi.imlec.y) == (2, 3)
        assert girdi.son_tik

    def test_sag_ve_cift_tiklama(self, monkeypatch):
        girdi = self._girdi(monkeypatch)
        girdi.tikla(1, 5, 5, sag=True, cift=True)
        assert girdi._kayitci.cagrilar[1] == ("click", (5, 5, "right", 2))

    def test_kaydir_yon_ve_miktar(self, monkeypatch):
        girdi = self._girdi(monkeypatch)
        girdi.kaydir(1, 0, 0, -3)
        assert girdi._kayitci.cagrilar[-1] == ("scroll", ("down", 3))

    def test_yaz_once_odaklanip_yaziyor(self, monkeypatch):
        girdi = self._girdi(monkeypatch)
        girdi.imlec.tasi(10, 20)
        girdi.yaz("merhaba")
        assert [c[0] for c in girdi._kayitci.cagrilar] == ["move_to",
                                                           "type_text"]
        assert girdi._kayitci.cagrilar[0][1] == (10, 20)

    def test_tus_kombinasyon_x11_de_gercek(self, monkeypatch):
        # Windows dalında bu DesteklenmiyorHatasi; X11'de gerçek basış.
        girdi = self._girdi(monkeypatch)
        girdi.tus("ctrl+s")
        assert girdi._kayitci.cagrilar[-1] == ("press", ("ctrl+s",))

    def test_duz_tus_bas_birak(self, monkeypatch):
        girdi = self._girdi(monkeypatch)
        girdi.tus("enter")
        adlar = [c[0] for c in girdi._kayitci.cagrilar]
        assert "tus_adlari_bas" in adlar and "tus_adlari_birak" in adlar

    def test_bilinmeyen_tus_reddediliyor(self, monkeypatch):
        from backend.computer.mesaj import DesteklenmiyorHatasi

        girdi = self._girdi(monkeypatch)
        with pytest.raises(DesteklenmiyorHatasi, match="unknown key"):
            girdi.tus("hyperspace")

    def test_kanal_gosterge_degisince_yenileniyor(self, monkeypatch):
        from backend.computer import mesaj

        girdi1 = self._girdi(monkeypatch, ":99")
        girdi1.tikla(1, 1, 1)
        girdi2 = self._girdi(monkeypatch, ":100")
        girdi2.tikla(1, 2, 2)
        ilk = girdi1._kayitci
        ikinci = girdi2._kayitci
        assert ilk is not ikinci
        assert ilk.cagrilar and ikinci.cagrilar

    def test_yan_masa_kapaliyken_x_dali_yok(self, monkeypatch):
        from backend.computer import mesaj

        monkeypatch.setattr(mesaj, "aktif_gosterge", lambda: None)
        mesaj.kanali_sifirla()
        assert mesaj._x11_dal() is None
        # Windows dalındaki gibi: odak yokken yazma sessizce yanlış iş
        # yapmıyor. (Buraya kadar hiçbir Win32 çağrısı yapılmıyor.)
        with pytest.raises(mesaj.DesteklenmiyorHatasi, match="focus"):
            mesaj.Girdi().yaz("merhaba")


class TestKayitX11Dali:
    """`kayit.py`nin x11grab dalı — argv ve süreç sözleşmesi."""

    class SahteX11Surec:
        """`_SurecX11` yüzeyi: bekle/dur_iste/oldur/kapat."""

        def __init__(self, qya_cevap_verir=True):
            self.izler: list[str] = []
            self._q = False
            self._cevap = qya_cevap_verir

        def bekle(self, _s):
            self.izler.append("bekle")
            return self._cevap if self._q else False

        def dur_iste(self):
            self.izler.append("dur_iste")
            self._q = True

        def oldur(self):
            self.izler.append("oldur")

        def kapat(self):
            self.izler.append("kapat")

    def test_x11_komutu_beklenen_bayraklarla(self, tmp_path):
        from backend.computer.kayit import ffmpeg_komutu_x11

        hedef = tmp_path / "a.mp4"
        metin = ffmpeg_komutu_x11(hedef, ":99", (1920, 1080),
                                  ffmpeg="/usr/bin/ffmpeg")
        assert "-f x11grab" in metin
        assert "-video_size 1920x1080" in metin
        assert "-i :99" in metin
        assert "crop=trunc(iw/2)*2:trunc(ih/2)*2" in metin
        # X11'de ajanın imleci gerçek; çizilmesin demek bilgi kaybı olur.
        assert "-draw_mouse" not in metin
        assert f'"{hedef}"' in metin

    def test_basla_durdur_x11_yan_ekrana_yaziyor(self, monkeypatch, tmp_path):
        from backend.computer import kayit as km

        monkeypatch.setattr(km.shutil, "which", lambda _a: "/usr/bin/ffmpeg")
        monkeypatch.setattr(km, "aktif_gosterge", lambda: ":99")
        sahte = self.SahteX11Surec()
        cagrilar = []

        def win32_patla(*_a):
            raise AssertionError("X11 yolunda Windows doğurucusu çağrıldı")

        kayit = km.EkranKaydi(
            dogurucu=win32_patla,
            dogurucu_x11=lambda k, g: cagrilar.append((k, g)) or sahte,
        )
        hedef = kayit.basla(tmp_path / "a.mp4", hwnd=7)
        assert cagrilar and cagrilar[0][1] == ":99"
        assert "-f x11grab" in cagrilar[0][0]
        assert kayit.suruyor
        assert kayit.durdur() == hedef
        assert sahte.izler == ["bekle", "dur_iste", "bekle", "kapat"]

    def test_gosterge_yoksa_windows_dali(self, monkeypatch, tmp_path):
        from backend.computer import kayit as km

        monkeypatch.setattr(km.shutil, "which", lambda _a: "/usr/bin/ffmpeg")
        monkeypatch.setattr(km, "aktif_gosterge", lambda: None)
        sahte = self.SahteX11Surec()
        cagrilar = []

        def x11_patla(*_a):
            raise AssertionError("gösterge yokken X11 doğurucusu çağrıldı")

        kayit = km.EkranKaydi(
            dogurucu=lambda k, masa: cagrilar.append((k, masa)) or sahte,
            dogurucu_x11=x11_patla,
        )
        kayit.basla(tmp_path / "a.mp4", hwnd=7)
        assert "gdigrab" in cagrilar[0][0]

class TestXSunucuYasamDongusu:
    """`ekran_x11` — numara dağıtımı, argv, hata yolları, durdurma.

    Hiçbir gerçek süreç, PATH ve dosya sistemi yok: dört enjeksiyon
    noktası (`bulucu`, `mesgul`, `dogurucu`, `hazir`) sahteleniyor.
    """

    def test_komut_kur_argv(self):
        argv = ekran_x11.komut_kur("xvfb", ":99")
        assert argv[0] == "Xvfb" and argv[1] == ":99"
        assert "-screen" in argv and "1920x1080x24" in argv
        assert "-noreset" in argv and "-nolisten" in argv
        argv = ekran_x11.komut_kur("xephyr", ":100")
        assert argv[0] == "Xephyr"

    def test_bilinmeyen_tur_reddediliyor(self):
        with pytest.raises(masaustu_ortak.MasaustuHatasi, match="kind"):
            ekran_x11.komut_kur("wayland", ":99")

    def test_soket_ve_kilit_yolu(self):
        assert ekran_x11.soket_yolu(":99") == "/tmp/.X11-unix/X99"
        assert ekran_x11.kilit_yolu(":99") == "/tmp/.X99-lock"

    def test_gosterge_sec_bos_verir(self):
        assert ekran_x11.gosterge_sec(mesgul=lambda _g: False) == ":99"

    def test_dolu_gosterge_sonrakine_gecer(self):
        dolu = {":99", ":100"}
        assert ekran_x11.gosterge_sec(
            mesgul=lambda g: g in dolu) == ":101"

    def test_aralik_tukenirse_acik_hata(self):
        with pytest.raises(masaustu_ortak.MasaustuHatasi, match="taken"):
            ekran_x11.gosterge_sec(mesgul=lambda _g: True,
                                   baslangic=99, son=100)

    def test_tur_sec_xvfb_once(self):
        assert ekran_x11.tur_sec(bulucu=lambda ad: ad) == "xvfb"

    def test_tur_sec_xephyr_yedek(self):
        assert ekran_x11.tur_sec(
            bulucu=lambda ad: ad if ad == "Xephyr" else None) == "xephyr"

    def test_iki_ikili_de_yoksa_paket_adi_soyluyor(self):
        with pytest.raises(masaustu_ortak.MasaustuHatasi) as hata:
            ekran_x11.tur_sec(bulucu=lambda _ad: None)
        assert "xvfb" in str(hata.value) and "xephyr" in str(hata.value)

    def test_hazir_bekle_soketi_bekliyor(self):
        ekran_x11.hazir_bekle(":99", SahteSurec(),
                              uyku=lambda _s: None, var=lambda _y: True)

    def test_hazir_bekle_olen_sunucu_stderr_ile(self):
        surec = SahteSurec(olur=True)
        surec.stderr = __import__("io").BytesIO(b"Fatal: no screen")
        with pytest.raises(masaustu_ortak.MasaustuHatasi, match="exited"):
            ekran_x11.hazir_bekle(":99", surec, uyku=lambda _s: None,
                                  var=lambda _y: False)

    def test_baslat_hata_yolunda_yarim_sunucu_birakmiyor(self, monkeypatch):
        surec = SahteSurec()
        durdurulanlar = []
        monkeypatch.setattr(ekran_x11.Ekran, "durdur",
                            lambda self, bekleme=3.0: durdurulanlar.append(1))
        with pytest.raises(masaustu_ortak.MasaustuHatasi):
            ekran_x11.baslat(
                tur="xvfb",
                mesgul=lambda _g: False,
                dogurucu=lambda _argv: surec,
                hazir=lambda _g, _s: (_ for _ in ()).throw(
                    masaustu_ortak.MasaustuHatasi("açılmadı")),
            )
        assert durdurulanlar == [1]

    def test_baslat_basarili_yol(self):
        surec = SahteSurec()
        ekran = ekran_x11.baslat(
            tur="xvfb",
            mesgul=lambda _g: False,
            dogurucu=lambda _argv: surec,
            hazir=lambda _g, _s: None,
        )
        assert ekran.gosterge == ":99" and ekran.tur == "xvfb"

    def test_ekran_durdur_sigterm_sonra_kill(self):
        surec = SahteSurec()

        def wait(timeout=None, **_k):
            if "terminate" in surec.cagrilar:
                raise subprocess.TimeoutExpired(cmd="x", timeout=timeout or 0)
            return 0

        surec.wait = wait
        ekran_x11.Ekran(":99", "xvfb", surec).durdur(bekleme=0.01)
        assert surec.cagrilar == ["terminate", "kill"]

    def test_ekran_durdur_olen_surece_dokunmuyor(self):
        surec = SahteSurec(olur=True)
        ekran_x11.Ekran(":99", "xvfb", surec).durdur(bekleme=0.01)
        assert surec.cagrilar == []
