"""AT-SPI arka ucu — sahte ağaçlarla, gerçek D-Bus'a dokunmadan.

pyatspi bu makinede (Windows'ta ya da pyatspi'siz Linux'ta) kurulu
değil; testler modülün `pyatspi` adını sahte bir modülle değiştirip
gezinti, süzgeç ve etiket mantığını ölçüyor. Doğrulanan şey AT-SPI
istemcisi değil, **bizim sözleşmemiz**: hangi rollerin yazıldığı,
çıktının biçimi, `okunabilir` ayrımı ve platform seçiminin nereye
gittiği.

`Gönder`/`Send` gibi literal beklentiler bilinçli: güvenlik kapısının
girdisi tam bu metin ve kapı Türkçe/İngilizce kalıplarla eşleşiyor.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from backend.computer import uia, uia_linux
from backend.computer.displays import Display


# --- sahte AT-SPI yüzeyi ------------------------------------------------------


class SahteDurum:
    def __init__(self, durumlar):
        self._durumlar = set(durumlar)

    def contains(self, bayrak):
        return bayrak in self._durumlar


class SahteBilesen:
    def __init__(self, kutu):
        self._kutu = kutu

    def getExtents(self, _kordinat):  # noqa: N802 - AT-SPI adı
        return self._kutu


class SahteMetin:
    def __init__(self, deger):
        self._deger = deger

    def getText(self, _bas, _son):  # noqa: N802 - AT-SPI adı
        return self._deger


class SahteDugum:
    """Tek bir AT-SPI düğümü. `kutu=None` bileşen arayüzü olmayan düğüm.

    `kutu` gerçek AT-SPI sözleşmesinde: `getExtents` (x, y, **genişlik**,
    **yükseklik**) döndürür — (sol, üst, sağ, alt) DEĞİL. Sahte de bunu
    birebir veriyor ki modülün çevirisi gerçek istemcide de doğru olsun.
    """

    def __init__(self, rol, ad="", kutu=None, cocuklar=(), deger="",
                 etkin=True, odakli=False, aktif=False, gorunur=True):
        self._rol = rol
        self.name = ad
        self._kutu = kutu
        self._cocuklar = list(cocuklar)
        self._deger = deger
        durumlar = set()
        if etkin:
            durumlar.add(8)   # STATE_ENABLED
        if odakli:
            durumlar.add(4)   # STATE_FOCUSED
        if aktif:
            durumlar.add(1)   # STATE_ACTIVE
        if gorunur:
            durumlar.add(2)   # STATE_SHOWING
        self._durum = SahteDurum(durumlar)

    def getRoleName(self):  # noqa: N802 - AT-SPI adı
        return self._rol

    def getChildCount(self):  # noqa: N802 - AT-SPI adı
        return len(self._cocuklar)

    def getChildAtIndex(self, i):  # noqa: N802 - AT-SPI adı
        return self._cocuklar[i]

    def getState(self):  # noqa: N802 - AT-SPI adı
        return self._durum

    def queryComponent(self):  # noqa: N802 - AT-SPI adı
        if self._kutu is None:
            raise RuntimeError("no component interface")
        return SahteBilesen(self._kutu)

    def queryEditableText(self):  # noqa: N802 - AT-SPI adı
        if self._deger == "":
            raise RuntimeError("not editable")
        return SahteMetin(self._deger)


def sahte_pyatspi(masaustu=None):
    def _getDesktop(_i):  # noqa: N802 - AT-SPI adı
        if masaustu is None:
            raise RuntimeError("no session bus")
        return masaustu

    return SimpleNamespace(
        Registry=SimpleNamespace(getDesktop=_getDesktop),
        DESKTOP_COORDS=0,
        STATE_ACTIVE=1,
        STATE_SHOWING=2,
        STATE_FOCUSED=4,
        STATE_ENABLED=8,
    )


@pytest.fixture
def atspi(monkeypatch):
    """pyatspi'yi sahteyle değiştirir; kurulan masaüstü sonda veriliyor."""

    def kur(masaustu):
        monkeypatch.setattr(uia_linux, "pyatspi", sahte_pyatspi(masaustu))
        return masaustu

    return kur


PENCERE = SahteDugum("frame", "Notepad", (0, 0, 800, 600))


class TestMusait:
    def test_pyatspi_yoksa_hayir(self, monkeypatch):
        monkeypatch.setattr(uia_linux, "pyatspi", None)
        assert uia_linux.musait() is False

    def test_veri_yolu_yoksa_hayir(self, monkeypatch):
        # pyatspi var ama oturum veri yolu yok: masaüstü alınamıyor.
        monkeypatch.setattr(uia_linux, "pyatspi", sahte_pyatspi(None))
        assert uia_linux.musait() is False

    def test_veri_yolu_varsa_evet(self, atspi):
        atspi(SahteDugum("application", "masa", (0, 0, 1, 1)))
        assert uia_linux.musait() is True


class TestAnlikGorunum:
    def test_pyatspi_yoksa_acik_hata(self, monkeypatch):
        monkeypatch.setattr(uia_linux, "pyatspi", None)
        with pytest.raises(uia_linux.AtsPiyokHatasi):
            uia_linux.anlik_gorunum()

    def test_veri_yolu_yoksa_acik_hata(self, monkeypatch):
        monkeypatch.setattr(uia_linux, "pyatspi", sahte_pyatspi(None))
        with pytest.raises(uia_linux.AtsPiyokHatasi):
            uia_linux.anlik_gorunum()

    def test_pencere_yoksa_durust_cevap(self, atspi):
        atspi(SahteDugum("application", "masa"))
        sonuc = uia_linux.anlik_gorunum()
        assert sonuc.node_count == 0
        assert sonuc.text == "There is no foreground window."
        assert sonuc.thin

    def test_gonder_dugmesi_literal_yazilir(self, atspi):
        dugme = SahteDugum("push button", "Gönder", (10, 20, 40, 20))
        atspi(SahteDugum("application", "masa", cocuklar=[
            SahteDugum("frame", "Notepad", (0, 0, 800, 600), cocuklar=[dugme]),
        ]))
        sonuc = uia_linux.anlik_gorunum()
        assert sonuc.window_title == "Notepad"
        assert sonuc.text == "Window: 'Notepad'\nButton \"Gönder\" [30,30]"
        assert sonuc.node_count == 1

    def test_kapsayici_yazilmaz_ama_cocugu_yazilir(self, atspi):
        dugme = SahteDugum("push button", "Send", (10, 20, 40, 20))
        panel = SahteDugum("panel", "Panel", (0, 0, 800, 600), cocuklar=[dugme])
        atspi(SahteDugum("application", "masa", cocuklar=[
            SahteDugum("frame", "Notepad", (0, 0, 800, 600), cocuklar=[panel]),
        ]))
        sonuc = uia_linux.anlik_gorunum()
        # Panel yazılmadı ve girinti artmadı: satır sıfır girintide.
        assert sonuc.text == "Window: 'Notepad'\nButton \"Send\" [30,30]"

    def test_pasif_ve_isimsiz_damgalanir(self, atspi):
        dugmeler = [
            SahteDugum("push button", "Sil", (0, 0, 100, 40), etkin=False),
            SahteDugum("push button", "", (0, 50, 100, 40)),
        ]
        atspi(SahteDugum("application", "masa", cocuklar=[
            SahteDugum("frame", "Notepad", (0, 0, 800, 600), cocuklar=dugmeler),
        ]))
        sonuc = uia_linux.anlik_gorunum()
        assert 'Button "Sil" [50,20] [pasif]' in sonuc.text
        assert "Button (unnamed) [50,70]" in sonuc.text
        assert sonuc.node_count == 2

    def test_metin_kutusunun_degeri_yazilir(self, atspi):
        duzenle = SahteDugum("entry", "Ad", (0, 0, 100, 40), deger="merhaba")
        atspi(SahteDugum("application", "masa", cocuklar=[
            SahteDugum("frame", "Notepad", (0, 0, 800, 600), cocuklar=[duzenle]),
        ]))
        sonuc = uia_linux.anlik_gorunum()
        assert "Edit \"Ad\" = 'merhaba' [50,20]" in sonuc.text

    def test_uzun_ad_kirpilir(self, atspi):
        dugme = SahteDugum("push button", "A" * 80, (0, 0, 100, 40))
        atspi(SahteDugum("application", "masa", cocuklar=[
            SahteDugum("frame", "Notepad", (0, 0, 800, 600), cocuklar=[dugme]),
        ]))
        sonuc = uia_linux.anlik_gorunum()
        assert f'Button "{"A" * 70}"' in sonuc.text
        assert "A" * 71 not in sonuc.text

    def test_dugum_tavani_kesme_satiri_yazar(self, atspi):
        dugmeler = [
            SahteDugum("push button", f"B{i}", (0, i * 40, 100, 30))
            for i in range(5)
        ]
        atspi(SahteDugum("application", "masa", cocuklar=[
            SahteDugum("frame", "Notepad", (0, 0, 800, 600), cocuklar=dugmeler),
        ]))
        sonuc = uia_linux.anlik_gorunum(maks_dugum=2)
        assert sonuc.node_count == 2
        assert "... truncated at 2 nodes" in sonuc.text

    def test_ekran_verilirse_model_uzayina_cevrilir(self, atspi):
        ekran = Display(index=0, left=100, top=50, width=1920, height=1080,
                        primary=True)
        dugme = SahteDugum("push button", "Tamam", (210, 150, 40, 20))
        atspi(SahteDugum("application", "masa", cocuklar=[
            SahteDugum("frame", "Notepad", (100, 50, 1800, 1000), cocuklar=[dugme]),
        ]))
        sonuc = uia_linux.anlik_gorunum(ekran=ekran)
        # Merkez sanal (230, 160) -> ekran içi (130, 110); ölçek 1.
        assert "Button \"Tamam\" [130,110]" in sonuc.text
        assert "(display 0)" in sonuc.text

    def test_baska_ekrandaki_dugum_atlanir(self, atspi):
        ekran = Display(index=0, left=0, top=0, width=800, height=600,
                        primary=True)
        dugme = SahteDugum("push button", "Uzak", (2000, 100, 100, 40))
        atspi(SahteDugum("application", "masa", cocuklar=[
            SahteDugum("frame", "Notepad", (0, 0, 800, 600), cocuklar=[dugme]),
        ]))
        sonuc = uia_linux.anlik_gorunum(ekran=ekran)
        assert sonuc.node_count == 0

    def test_aktif_pencere_once_gezilir(self, atspi):
        olu = SahteDugum("frame", "Arka", (0, 0, 10, 10), gorunur=False)
        canli = SahteDugum("frame", "Ön", (0, 0, 800, 600), aktif=True)
        atspi(SahteDugum("application", "masa", cocuklar=[olu, canli]))
        sonuc = uia_linux.anlik_gorunum()
        assert sonuc.window_title == "Ön"


class TestOdakOzeti:
    def test_pyatspi_yoksa_none(self, monkeypatch):
        monkeypatch.setattr(uia_linux, "pyatspi", None)
        assert uia_linux.odak_ozeti() is None

    def test_odakli_dugme_ozeti(self, atspi):
        duzenle = SahteDugum("entry", "Ad", (0, 0, 100, 40), deger="ali",
                             odakli=True)
        atspi(SahteDugum("application", "masa", cocuklar=[
            SahteDugum("frame", "Notepad", (0, 0, 800, 600), cocuklar=[duzenle]),
        ]))
        assert uia_linux.odak_ozeti() == ("Edit", "Ad", "ali")

    def test_odak_yoksa_none(self, atspi):
        atspi(SahteDugum("application", "masa", cocuklar=[
            SahteDugum("frame", "Notepad", (0, 0, 800, 600), cocuklar=[
                SahteDugum("push button", "Tamam", (0, 0, 40, 40)),
            ]),
        ]))
        assert uia_linux.odak_ozeti() is None

    def test_okunamayan_deger_bos_doner_ama_ozet_dogar(self, atspi):
        # Text kutunun değeri okunamıyorsa özet yine gelir; ad ve tür kanıt.
        duzenle = SahteDugum("entry", "Ad", kutu=None, odakli=True)
        atspi(SahteDugum("application", "masa", cocuklar=[
            SahteDugum("frame", "Notepad", (0, 0, 800, 600), cocuklar=[duzenle]),
        ]))
        assert uia_linux.odak_ozeti() == ("Edit", "Ad", "")


class TestEtiketNoktada:
    def test_pyatspi_yoksa_okunamadi(self, monkeypatch):
        monkeypatch.setattr(uia_linux, "pyatspi", None)
        etiket = uia_linux.etiket_noktada(50, 30)
        assert etiket.metin == ""
        assert etiket.okunabilir is False

    def test_veri_yolu_yoksa_okunamadi(self, monkeypatch):
        monkeypatch.setattr(uia_linux, "pyatspi", sahte_pyatspi(None))
        assert uia_linux.etiket_noktada(50, 30).okunabilir is False

    def test_gonder_dugmesi_literal_doner(self, atspi):
        dugme = SahteDugum("push button", "Gönder", (10, 10, 90, 40))
        atspi(SahteDugum("application", "masa", cocuklar=[
            SahteDugum("frame", "Notepad", (0, 0, 800, 600), cocuklar=[dugme]),
        ]))
        etiket = uia_linux.etiket_noktada(50, 30)
        assert etiket.metin == "Gönder"
        assert etiket.okunabilir is True

    def test_en_kucuk_alanli_dugum_kazanir(self, atspi):
        dugme = SahteDugum("push button", "Sil", (10, 10, 90, 40))
        panel = SahteDugum("panel", "Panel", (0, 0, 800, 600), cocuklar=[dugme])
        atspi(SahteDugum("application", "masa", cocuklar=[
            SahteDugum("frame", "Notepad", (0, 0, 800, 600), cocuklar=[panel]),
        ]))
        assert uia_linux.etiket_noktada(50, 30).metin == "Sil"

    def test_pencere_cercevesi_etiket_sayilmaz(self, atspi):
        atspi(SahteDugum("application", "masa", cocuklar=[
            SahteDugum("frame", "Notepad", (0, 0, 800, 600)),
        ]))
        etiket = uia_linux.etiket_noktada(50, 30)
        assert etiket.metin == ""
        assert etiket.okunabilir is True  # kutu okundu, nokta pencerede

    def test_nokta_kutu_okunamadiysa_okunamadi(self, atspi):
        # Bileşen arayüzü hiç yok: kutu sorulamadı, "etiket yok" denemez.
        kok = SahteDugum("application", "masa", cocuklar=[
            SahteDugum("frame", "Notepad"),
        ])
        atspi(kok)
        assert uia_linux.etiket_noktada(50, 30).okunabilir is False

    def test_nokta_pencerede_degilse_okunabilir_bos(self, atspi):
        dugme = SahteDugum("push button", "Gönder", (10, 10, 90, 40))
        atspi(SahteDugum("application", "masa", cocuklar=[
            SahteDugum("frame", "Notepad", (0, 0, 800, 600), cocuklar=[dugme]),
        ]))
        etiket = uia_linux.etiket_noktada(2000, 2000)
        assert etiket.metin == ""
        assert etiket.okunabilir is True


class TestSecim:
    """`uia.py` çağrıları Linux'ta AT-SPI'ye, Windows'ta Windows yoluna."""

    def test_linux_oturumunda_atspi_secbrlir(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setenv("DISPLAY", ":99")
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        assert uia._linux_arka_uc() is uia_linux

    def test_windows_oturumunda_windows_yolu(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        assert uia._linux_arka_uc() is None

    def test_snapshot_linux_devreder(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setenv("DISPLAY", ":99")
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        cagri = {}

        def sahte_gorunum(maks_derinlik, maks_dugum, ekran):
            cagri["ekran"] = ekran
            return uia_linux.GorunumSonucu("sahte", 1, "T")

        monkeypatch.setattr(uia_linux, "anlik_gorunum", sahte_gorunum)

        def patla():
            raise AssertionError("Windows yolu Linux oturumunda çağrıldı")

        monkeypatch.setattr(uia, "_auto", patla)
        ekran = Display(index=0, left=0, top=0, width=800, height=600,
                        primary=True)
        sonuc = uia.snapshot(ekran)
        assert sonuc.text == "sahte"
        assert cagri["ekran"] is ekran

    def test_odak_ozeti_linux_devreder(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setenv("DISPLAY", ":99")
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        monkeypatch.setattr(uia_linux, "odak_ozeti", lambda: ("Edit", "a", "b"))
        assert uia.odak_ozeti() == ("Edit", "a", "b")

    def test_etiket_noktada_linux_devreder(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setenv("DISPLAY", ":99")
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        monkeypatch.setattr(
            uia_linux, "etiket_noktada",
            lambda vx, vy: uia_linux.Etiket("Gönder", True),
        )
        etiket = uia.etiket_noktada(10, 10)
        assert etiket.metin == "Gönder"

    def test_windows_etiketi_imza_okunamasa_da_okunabilir(self, monkeypatch):
        """Windows'ta eski sözleşme: denetim bulunamazsa boş ama okunabilir."""
        monkeypatch.setattr(sys, "platform", "win32")

        def patla(_vx, _vy):
            raise RuntimeError("E_ACCESSDENIED")

        monkeypatch.setattr(uia, "_imza_oku", patla)
        etiket = uia.etiket_noktada(10, 10)
        assert etiket.metin == ""
        assert etiket.okunabilir is True


class TestUiauDegismedi:
    """Windows uia.py'nin dışa vurduğu işaretler duruyor."""

    def test_icerikler_aynen(self):
        for ad in ("Button", "Edit", "MenuItem", "TreeItem"):
            assert ad in uia.INTERESTING
        assert uia.MAX_DEPTH == 12
        assert uia.MAX_NODES == 220

    def test_iki_backend_ayni_rolleri_kullaniyor(self):
        # uia_linux'un çevirdiği rollerin hepsi INTERESTING'de olmalı;
        # olmayan bir rol sessizce yazılmaz olurdu.
        for uia_turu in uia_linux.ROLLER.values():
            assert uia_turu in uia.INTERESTING
        assert uia_linux.MAX_DERINLIK == uia.MAX_DEPTH
        assert uia_linux.MAX_DUGUM == uia.MAX_NODES
        assert uia_linux.INCE_ALTI == uia.THIN_BELOW