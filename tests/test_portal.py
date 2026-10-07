"""Portal/Wayland yolu — sahte taşıyıcıyla, gerçek D-Bus'a dokunmadan.

Bu dosyanın bütün konusu tek bir cümle: **çağrı yolu ve sınırları doğru mu.**
Gerçek portal diyaloğu, gerçek PipeWire, gerçek kompozitör yok — bunların
hiçbiri bu makinede (Windows) koşulamaz ve mış gibi yapmak bu deponun
dürüstlük kurallarına aykırı. Sınanan şey: imzalar, akış sırası, zaman aşımı
ve ret davranışı, hazır-ama-uygulanmamış sınırının **açık** hata vermesi.

Sahte taşıyıcı kuyruğu elle sürülüyor (`bekle_yanit` programlanıyor), yani
"kullanıcı reddetti", "kullanıcı hiç cevap vermedi" ve "izin verdi" yolları
ayrı ayrı sınanıyor.
"""

from __future__ import annotations

import pytest

from backend.computer import portal_ekran, portal_girdi, portal_oturum, portal_tasiyici
from backend.computer.portal_tasiyici import (
    PortalHatasi,
    PortalZamanAsimi,
    SecenekDegeri,
)


class SahteTasiyici:
    """Kaydeden, programlanabilir D-Bus vekili.

    Onay yanıtları bir **kuyruk**: portal akışındaki her adım (CreateSession,
    SelectDevices/SelectSources, Start) bir yanıt tüketiyor ve kuyruk boşsa
    `PortalZamanAsimi` geliyor — "kullanıcı cevap vermedi" hâli. Kuyruk,
    istek yolu yerine sırayla çalışıyor çünkü gerçek akış da portalın
    döndürdüğü yolu bekliyor; yolun kendisi `test_istek_yolu_kurali`'nde
    ayrıca sınanıyor. Her `cagir` olduğu gibi kaydediliyor ki testler
    imzayı ve akış sırasını doğrulayabilsin.
    """

    def __init__(self, ozellikler=None, hata_verenler=()):
        self.cagrilar: list[tuple] = []
        self.yanit_kuyrugu: list[tuple[int, dict]] = []
        self.ozellikler = ozellikler or {}
        self.hata_verenler = set(hata_verenler)
        self.ad_kumesi = {portal_tasiyici.PORTAL_ADI}
        self._sira = 0

    # --- çağrı ------------------------------------------------------------

    def cagir(self, hedef, yol, arayuz, uye, imza, govde, zaman_asimi=10.0):
        self.cagrilar.append((hedef, yol, arayuz, uye, imza, govde, zaman_asimi))
        if uye in self.hata_verenler:
            raise PortalHatasi(f"programlanmış hata: {uye}")
        if uye == "Get":
            # Gerçek taşıyıcı `v` sarmalını açıyor; vekil de açık döner.
            anahtar = tuple(govde)
            if anahtar in self.ozellikler:
                return "v", [self.ozellikler[anahtar]], []
            raise PortalHatasi("no such property")
        if uye == "NameHasOwner":
            return "b", [govde[0] in self.ad_kumesi], []
        if uye == "ListNames":
            return "as", [sorted(self.ad_kumesi)], []
        if uye == "ListActivatableNames":
            return "as", [sorted(self.ad_kumesi)], []
        if uye == "OpenPipeWireRemote":
            return "h", [7], []
        # Her anahtarlı çağrı kendi istek yolunu döndürüyor.
        self._sira += 1
        return "o", [f"/org/freedesktop/portal/desktop/request/1_1/istek{self._sira}"], []

    # --- yanıt ------------------------------------------------------------

    def bekle_yanit(self, istek_yolu, zaman_asimi):
        if not self.yanit_kuyrugu:
            raise PortalZamanAsimi(
                f"sahte: {istek_yolu!r} için cevap yok (kullanıcı sustu)"
            )
        return self.yanit_kuyrugu.pop(0)

    def benzersiz_ad(self):
        return ":1.1"

    def adlar(self):
        return sorted(self.ad_kumesi)

    def ad_sahipli_mi(self, ad):
        return ad in self.ad_kumesi

    def etkinlestirilebilir_adlar(self):
        return []

    def kapat(self):
        pass


def _cagri_ozeti(tasiyici, uye):
    for hedef, yol, arayuz, ad, imza, govde, zaman in tasiyici.cagrilar:
        if ad == uye:
            return imza, govde
    return None


def _yanit_programla(tasiyici, adim_sonucu, basarili=True, ek=None):
    """Onay kuyruğuna bir yanıt ekler: ret ya da sonuç sözlüğü.

    Her anahtarlı adım (CreateSession, SelectSources/SelectDevices, Start)
    bir yanıt tüketiyor — akış sırası kadar yanıt programlanmalı.
    """
    sonuc = dict(adim_sonucu)
    if ek:
        sonuc.update(ek)
    kod = portal_oturum.YANIT_BASARILI if basarili else portal_oturum.YANIT_VAZGECILDI
    tasiyici.yanit_kuyrugu.append((kod, sonuc))
    return tasiyici


#: Kullanıcı onayladığında ScreenCast akışının üç yanıtı.
def _ekran_yanitlari(tasiyici, akinlar=None):
    _yanit_programla(tasiyici, {"session_handle": "/session/1"})
    _yanit_programla(tasiyici, {})  # SelectSources onayı
    _yanit_programla(tasiyici, {}, ek={"streams": akinlar if akinlar is not None else []})
    return tasiyici


#: Kullanıcı onayladığında RemoteDesktop akışının üç yanıtı.
def _girdi_yanitlari(tasiyici, cihazlar, akinlar=None):
    _yanit_programla(tasiyici, {"session_handle": "/s"})
    _yanit_programla(tasiyici, {})  # SelectDevices onayı
    _yanit_programla(
        tasiyici,
        {"devices": cihazlar, "streams": akinlar if akinlar is not None else []},
    )
    return tasiyici


# --- imza ve sözlük kurulumu ----------------------------------------------


class TestSozluk:
    def test_duz_deger_turunden_sarilir(self):
        secenek = portal_oturum.secenekler(handle_token="x", multiple=True, types=1)
        assert secenek["handle_token"] == SecenekDegeri("s", "x")
        assert secenek["multiple"] == SecenekDegeri("b", True)
        assert secenek["types"] == SecenekDegeri("u", 1)

    def test_acik_tur_korunur(self):
        secenek = portal_oturum.secenekler(types=SecenekDegeri("u", 1))
        assert secenek["types"].imza == "u"

    def test_desteklenmeyen_deger_acik_hata(self):
        with pytest.raises(PortalHatasi, match="Unsupported option"):
            portal_oturum.secenekler(zaman=1.5)

    def test_jeton_taze(self):
        assert portal_oturum.jeton() != portal_oturum.jeton()

    def test_istek_yolu_kurali(self):
        """Portal dokümanı: ':' düşer, '.' '_' olur."""
        tasiyici = SahteTasiyici()
        yol = portal_oturum.istek_yolu(tasiyici, "abc")
        assert yol == "/org/freedesktop/portal/desktop/request/1_1/abc"


class TestVaryant:
    def test_yapisal_sarmal_acilir(self):
        class Vekil:
            signature = "u"
            value = 3

        assert portal_tasiyici.varyanti_ac({"a": Vekil(), "b": [Vekil()]}) == {
            "a": 3,
            "b": [3],
        }

    def test_sozluk_ozyinelemeli(self):
        assert portal_tasiyici.varyanti_ac({"x": {"y": 1}}) == {"x": {"y": 1}}


# --- uygunluk sınaması -----------------------------------------------------


class TestUygunluk:
    def test_portal_yoksa_false(self):
        tasiyici = SahteTasiyici()
        tasiyici.ad_kumesi = {"org.freedesktop.DBus"}  # portal yok
        assert portal_tasiyici.portal_musait(tasiyici) is False

    def test_portal_var_arka_uc_yoksa_false(self):
        """Portal tek başına yetmiyor — uç yoksa ilk istekte patlar."""
        tasiyici = SahteTasiyici()
        assert portal_tasiyici.portal_musait(tasiyici) is False

    def test_portal_ve_gnome_ucu_varsa_true(self):
        tasiyici = SahteTasiyici()
        tasiyici.ad_kumesi = {
            portal_tasiyici.PORTAL_ADI,
            "org.freedesktop.impl.portal.desktop.gnome",
        }
        assert portal_tasiyici.portal_musait(tasiyici) is True

    def test_wlr_ucu_da_kabul(self):
        tasiyici = SahteTasiyici()
        tasiyici.ad_kumesi = {
            portal_tasiyici.PORTAL_ADI,
            "org.freedesktop.impl.portal.desktop.wlr",
        }
        assert portal_tasiyici.portal_musait(tasiyici) is True

    def test_hata_verirse_false(self):
        """Sınama kapı değil soru: cevap veremeyen taşıyıcı 'hayır' sayılır."""
        tasiyici = SahteTasiyici(hata_verenler={"NameHasOwner"})
        assert portal_tasiyici.portal_musait(tasiyici) is False

    def test_paket_yoksa_yan_etkisiz(self):
        assert portal_tasiyici.dbus_yaninda_mi() in (True, False)


# --- ekran yakalama akışı --------------------------------------------------


class TestEkranAkisi:
    def _akin_yaniti(self):
        return [[4, {"position": [1920, 0], "size": [1920, 1080], "pipewire-serial": 99}]]

    def test_happy_path_dort_adim(self):
        tasiyici = SahteTasiyici(ozellikler={("org.freedesktop.portal.ScreenCast", "AvailableCursorModes"): 2})
        _ekran_yanitlari(tasiyici, self._akin_yaniti())
        oturum = portal_ekran.EkranOturumu.ac(tasiyici)

        adlar = [c[3] for c in tasiyici.cagrilar]
        assert adlar[0] == "CreateSession"
        assert "SelectSources" in adlar
        assert "Start" in adlar
        assert "OpenPipeWireRemote" in adlar
        assert oturum.hazir is True
        assert oturum.pipewire_fd == 7
        assert len(oturum.akinlar) == 1
        assert oturum.akinlar[0].dugum == 4
        assert oturum.akinlar[0].boyut == (1920, 1080)
        assert oturum.akinlar[0].seri == 99

    def test_select_sources_monitor_ve_coklu(self):
        tasiyici = SahteTasiyici(ozellikler={("org.freedesktop.portal.ScreenCast", "AvailableCursorModes"): 2})
        _ekran_yanitlari(tasiyici, self._akin_yaniti())
        portal_ekran.EkranOturumu.ac(tasiyici)

        _, govde = _cagri_ozeti(tasiyici, "SelectSources")
        secenek = govde[1]
        assert secenek["types"].deger == portal_ekran.KAYNAK_MONITOR
        assert secenek["multiple"].deger is True

    def test_create_session_reddi_acik_hata(self):
        tasiyici = SahteTasiyici()
        _yanit_programla(tasiyici, {"session_handle": "/s"}, basarili=False)
        with pytest.raises(PortalHatasi, match="denied"):
            portal_ekran.EkranOturumu.ac(tasiyici)

    def test_sonradan_ret_oturumu_kapatir(self):
        """Start'ta ret: oturum zaten açılmıştı, portalda sızıntı kalmamalı."""
        tasiyici = SahteTasiyici()
        _yanit_programla(tasiyici, {"session_handle": "/s"})
        _yanit_programla(tasiyici, {})  # SelectSources onayı
        _yanit_programla(tasiyici, {}, basarili=False)  # Start reddedildi
        with pytest.raises(PortalHatasi, match="denied"):
            portal_ekran.EkranOturumu.ac(tasiyici)
        adlar = [c[3] for c in tasiyici.cagrilar]
        assert "Close" in adlar
        assert adlar.index("Close") > adlar.index("CreateSession")

    def test_onay_susarsa_zaman_asimi(self):
        """Programlanmamış istek = kullanıcı hiç cevap vermedi."""
        tasiyici = SahteTasiyici()
        with pytest.raises(PortalZamanAsimi):
            portal_ekran.EkranOturumu.ac(tasiyici, zaman_asimi=0.01)

    def test_fd_sozluk_yerine_gercek_fd(self):
        """Taşıyıcı `h`'yi fd'ye çevirdiğinde oturum onu tutmalı."""
        tasiyici = SahteTasiyici(ozellikler={("org.freedesktop.portal.ScreenCast", "AvailableCursorModes"): 2})
        _ekran_yanitlari(tasiyici, self._akin_yaniti())
        oturum = portal_ekran.EkranOturumu.ac(tasiyici)
        assert isinstance(oturum.pipewire_fd, int) and oturum.pipewire_fd >= 0

    def test_kare_alma_uygulanmadi_diye_durustce_hata(self):
        """Sınırın sözü: oturum hazır ama kare yok, ve hata bunu SÖYLÜYOR."""
        tasiyici = SahteTasiyici(ozellikler={("org.freedesktop.portal.ScreenCast", "AvailableCursorModes"): 2})
        _ekran_yanitlari(tasiyici, self._akin_yaniti())
        oturum = portal_ekran.EkranOturumu.ac(tasiyici)

        with pytest.raises(portal_ekran.YakalamaYokHatasi) as exc:
            oturum.grab(0)
        metin = str(exc.value)
        assert "not implemented" in metin
        assert "pipewire_fd=yes" in metin  # ne olduğunu tam söylüyor

    def test_akis_konumu_cozulur(self):
        akinlar = portal_ekran.akinlari_coz({"streams": self._akin_yaniti()})
        assert akinlar[0].konum == (1920, 0)

    def test_bos_akis_listesi_bos_doner(self):
        assert portal_ekran.akinlari_coz({}) == []

    def test_imlec_kipi_desteklenmiyorsa_dusurulur(self):
        """Doküman: desteklenmeyen kip oturumu KAPATIR — sormadan istemiyoruz."""
        tasiyici = SahteTasiyici(ozellikler={("org.freedesktop.portal.ScreenCast", "AvailableCursorModes"): portal_ekran.IMLEC_GIZLI})
        assert portal_ekran.imlec_kipi_sec(tasiyici, portal_ekran.IMLEC_GOMULU) == portal_ekran.IMLEC_GIZLI

    def test_imlec_kipi_ozellik_yoksa_istenen(self):
        tasiyici = SahteTasiyici()
        assert portal_ekran.imlec_kipi_sec(tasiyici, portal_ekran.IMLEC_GOMULU) == portal_ekran.IMLEC_GOMULU


# --- girdi akışı -----------------------------------------------------------


class TestKlavyeCevirisi:
    def test_ascii_kendi_kod_noktasi(self):
        assert portal_girdi.character_keysym("a") == 0x61
        assert portal_girdi.character_keysym(" ") == 0x20

    def test_unicode_kod_noktasi_ofseti(self):
        """keysymdef.h kuralı: 0x01000000 + kod noktası."""
        assert portal_girdi.character_keysym("ğ") == 0x01000000 + 0x011F
        assert portal_girdi.character_keysym("ı") == 0x01000000 + 0x0131
        assert portal_girdi.character_keysym("é") == 0x01000000 + 0x00E9

    def test_isimli_tuslar(self):
        assert portal_girdi.keysym_coz("ctrl") == 0xFFE3
        assert portal_girdi.keysym_coz("F4") == 0xFFC1
        assert portal_girdi.keysym_coz("A") == 0x41

    def test_bilinmeyen_tus_acik_hata(self):
        with pytest.raises(PortalHatasi, match="Unknown key"):
            portal_girdi.keysym_coz("hiper")

    def test_kombo_degistirici_once(self):
        assert portal_girdi.komboyu_coz("ctrl+s") == [0xFFE3, 0x73]

    def test_bos_parca_reddedilir(self):
        with pytest.raises(PortalHatasi, match="Empty key name"):
            portal_girdi.komboyu_coz("ctrl+")

    def test_bolme_isareti_kurar(self):
        assert portal_girdi.keysym_bul("super") == 0xFFEB


class TestGirdiAkini:
    def test_yerel_ceviri(self):
        akin = portal_girdi.GirdiAkini(dugum=4, sol=1920, ust=0, genislik=1920, yukseklik=1080)
        assert akin.yerel(2020, 100) == (100.0, 100.0)

    def test_akis_dugum_uzayi(self):
        """Gösterilen ad: tüketici `virtual_to_stream` diyecek."""
        akin = portal_girdi.GirdiAkini(dugum=4, sol=100, ust=50, genislik=800, yukseklik=600)
        assert akin.icinde_mi(500, 300) is True
        assert akin.icinde_mi(99, 300) is False

    def test_disari_tasin_reddedilir(self):
        akin = portal_girdi.GirdiAkini(dugum=0, sol=0, ust=0, genislik=1920, yukseklik=1080)
        with pytest.raises(PortalHatasi, match="outside"):
            akin.yerel(1920, 0)

    def test_yerlesimsiz_akis_atlanir(self):
        ham = [[3, {"position": [0, 0], "size": [800, 600]}], [9, {"foo": 1}]]
        akinlar = portal_girdi.akinlardan(ham)
        assert [a.dugum for a in akinlar] == [3]


class TestGirdiOturumu:
    def _ac(self, cihazlar=portal_girdi.CIHAZ_KLAVYE | portal_girdi.CIHAZ_FARE, basarili=True):
        tasiyici = SahteTasiyici()
        _girdi_yanitlari(
            tasiyici,
            cihazlar,
            akinlar=[[4, {"position": [0, 0], "size": [1920, 1080]}]],
        )
        if not basarili:
            tasiyici.yanit_kuyrugu[-1] = (portal_oturum.YANIT_VAZGECILDI, {})
        oturum = portal_girdi.GirdiOturumu.ac(tasiyici)
        return tasiyici, oturum

    def test_happy_path_izin_ve_akis(self):
        tasiyici, oturum = self._ac()
        adlar = [c[3] for c in tasiyici.cagrilar]
        assert adlar[0] == "CreateSession"
        assert "SelectDevices" in adlar
        assert "Start" in adlar
        assert oturum.izinli == (portal_girdi.CIHAZ_KLAVYE | portal_girdi.CIHAZ_FARE)
        assert len(oturum.akinlar) == 1

    def test_tasinma_mutlak_akis_uzayinda(self):
        tasiyici, oturum = self._ac()
        oturum.move_to(300, 200)
        _, govde = _cagri_ozeti(tasiyici, "NotifyPointerMotionAbsolute")
        assert govde[2] == 4  # akış düğümü
        assert (govde[3], govde[4]) == (300.0, 200.0)

    def test_tiklama_once_tasir_sonra_dugme(self):
        tasiyici, oturum = self._ac()
        oturum.click(300, 200)
        adlar = [c[3] for c in tasiyici.cagrilar]
        i_tasi = adlar.index("NotifyPointerMotionAbsolute")
        i_dugme = adlar.index("NotifyPointerButton")
        assert i_tasi < i_dugme
        _, govde = _cagri_ozeti(tasiyici, "NotifyPointerButton")
        assert govde[2] == portal_girdi.DUGME_KODLARI["left"]
        assert govde[3] == portal_girdi.BASILDI
        assert adlar.count("NotifyPointerButton") == 2  # bas + bırak

    def test_cift_tiklama_iki_kez(self):
        tasiyici, oturum = self._ac()
        oturum.click(10, 10, count=2)
        assert [c[3] for c in tasiyici.cagrilar].count("NotifyPointerButton") == 4

    def test_klavye_verilmeyince_acik_hata(self):
        """Kullanıcı klavyeyi reddetti; çağrı hiç yapılmamalı."""
        tasiyici, oturum = self._ac(cihazlar=portal_girdi.CIHAZ_FARE)
        with pytest.raises(portal_girdi.IzinYokHatasi, match="keyboard"):
            oturum.press("ctrl+s")
        assert _cagri_ozeti(tasiyici, "NotifyKeyboardKeysym") is None

    def test_fare_verilmeyince_acik_hata(self):
        _, oturum = self._ac(cihazlar=portal_girdi.CIHAZ_KLAVYE)
        with pytest.raises(portal_girdi.IzinYokHatasi, match="pointer"):
            oturum.move_to(1, 1)

    def test_konum_okunamaz_durustce_hata(self):
        """(0, 0) döndürmek 'imlecin oraya tıkla' aracını sol üste atardı."""
        _, oturum = self._ac()
        with pytest.raises(portal_girdi.KonumYokHatasi, match="does not expose"):
            oturum.cursor_position()

    def test_reddedilen_onay_acik_hata(self):
        with pytest.raises(PortalHatasi, match="denied"):
            self._ac(basarili=False)

    def test_susan_kullanici_zaman_asimi(self):
        tasiyici = SahteTasiyici()
        with pytest.raises(PortalZamanAsimi):
            portal_girdi.GirdiOturumu.ac(tasiyici, zaman_asimi=0.01)

    def test_surukleme_bas_birak_temiz(self):
        tasiyici, oturum = self._ac()
        oturum.drag((10, 10), (100, 100), steps=3)
        adlar = [c[3] for c in tasiyici.cagrilar]
        assert adlar.count("NotifyPointerButton") == 2
        bas, _ = _cagri_ozeti(tasiyici, "NotifyPointerButton")
        assert adlar[adlar.index("NotifyPointerButton")] == "NotifyPointerButton"

    def test_kaydirma_yonu_ve_ekseni(self):
        tasiyici, oturum = self._ac()
        oturum.scroll("down", 3, at=(50, 50))
        _, govde = _cagri_ozeti(tasiyici, "NotifyPointerAxisDiscrete")
        assert govde[2] == portal_girdi.EKSEN_DIKEY
        assert govde[3] == 3

    def test_yatay_kaydirma_ekseni(self):
        tasiyici, oturum = self._ac()
        oturum.scroll("right", 1)
        _, govde = _cagri_ozeti(tasiyici, "NotifyPointerAxisDiscrete")
        assert govde[2] == portal_girdi.EKSEN_YATAY

    def test_metin_yazimi_unicode_dogru(self):
        tasiyici, oturum = self._ac()
        oturum.type_text("ğ", delay=0)
        _, govde = _cagri_ozeti(tasiyici, "NotifyKeyboardKeysym")
        assert govde[2] == 0x01000000 + 0x011F

    def test_modifier_hatada_birakilir(self):
        tasiyici, oturum = self._ac()
        with pytest.raises(RuntimeError):
            with oturum.modifiers_held("ctrl"):
                raise RuntimeError("içeride patladı")
        durumlar = [c[5][3] for c in tasiyici.cagrilar if c[3] == "NotifyKeyboardKeysym"]
        assert durumlar[0] == portal_girdi.BASILDI
        assert durumlar[-1] == portal_girdi.BIRAKILDI

    def test_akis_yoksa_mutlak_konum_hata(self):
        tasiyici = SahteTasiyici()
        _girdi_yanitlari(tasiyici, portal_girdi.CIHAZ_FARE)  # akış yok
        oturum = portal_girdi.GirdiOturumu.ac(tasiyici)
        with pytest.raises(PortalHatasi, match="no screen cast streams"):
            oturum.move_to(1, 1)

    def test_akis_disi_nokta_hata(self):
        _, oturum = self._ac()
        with pytest.raises(PortalHatasi, match="not inside any shared stream"):
            oturum.move_to(5000, 5000)


# --- kombine oturum (girdi + ekran, tek diyalog) ---------------------------


class TestKombineOturum:
    def test_ekran_da_true_secenekleri_ayni_oturumda(self):
        tasiyici = SahteTasiyici(ozellikler={("org.freedesktop.portal.ScreenCast", "AvailableCursorModes"): 2})
        _yanit_programla(tasiyici, {"session_handle": "/s"})
        _yanit_programla(tasiyici, {})  # SelectDevices
        _yanit_programla(tasiyici, {})  # SelectSources (aynı oturum)
        _yanit_programla(
            tasiyici,
            {
                "devices": portal_girdi.CIHAZ_FARE,
                "streams": [[4, {"position": [0, 0], "size": [800, 600]}]],
            },
        )
        oturum = portal_girdi.GirdiOturumu.ac(tasiyici, ekran_da=True)

        # SelectSources aynı oturum yoluyla çağrılmalı — portal dokümanı
        # "cross-portal" için bunu şart koşuyor.
        _, govde = _cagri_ozeti(tasiyici, "SelectSources")
        assert govde[0] == oturum.oturum_yolu
        assert oturum.pipewire_fd is not None

    def test_ekran_da_false_pipewire_sormaz(self):
        tasiyici = SahteTasiyici()
        _girdi_yanitlari(tasiyici, portal_girdi.CIHAZ_FARE)
        portal_girdi.GirdiOturumu.ac(tasiyici, ekran_da=False)
        assert _cagri_ozeti(tasiyici, "OpenPipeWireRemote") is None


# --- zaman aşımı sözü ------------------------------------------------------


class TestZamanAsimiSozu:
    def test_hizli_zaman_asimi_cagriya_geciyor(self):
        """Notify* çağrıları diyalog beklemiyor ama asılı da kalmamalı."""
        tasiyici = SahteTasiyici()
        _girdi_yanitlari(
            tasiyici,
            portal_girdi.CIHAZ_FARE,
            akinlar=[[4, {"position": [0, 0], "size": [10, 10]}]],
        )
        oturum = portal_girdi.GirdiOturumu.ac(tasiyici)
        oturum.move_to(5, 5)
        _, _, _, uye, _, _, zaman = tasiyici.cagrilar[-1]
        assert uye == "NotifyPointerMotionAbsolute"
        assert zaman == portal_girdi.HIZLI_ZAMANI

    def test_vazgecilen_yanit_reddedildi_metni_basari_degil(self):
        yanit = portal_oturum.Onay(portal_oturum.YANIT_VAZGECILDI, {})
        assert yanit.basarili is False
        with pytest.raises(PortalHatasi, match="denied"):
            yanit.dogrula("x")

    def test_beklenmedik_kod_ayri_metin(self):
        yanit = portal_oturum.Onay(portal_oturum.YANIT_BASKA_TURLU, {})
        with pytest.raises(PortalHatasi, match="unexpected way"):
            yanit.dogrula("x")

    def test_sifir_basari(self):
        assert portal_oturum.Onay(0, {"a": 1}).dogrula("x") == {"a": 1}


# --- uçtan uca: iki akış da aynı vekilden geçiyor ---------------------------


def test_akis_cagrilari_sira_ve_imza_tam():
    """Bir cümlede: imzalar portal dokümanıyla birebir mi."""
    tasiyici = SahteTasiyici()
    _girdi_yanitlari(
        tasiyici,
        3,
        akinlar=[[4, {"position": [0, 0], "size": [800, 600]}]],
    )
    oturum = portal_girdi.GirdiOturumu.ac(tasiyici)

    beklenen = {
        "CreateSession": ("a{sv}",),
        "SelectDevices": ("oa{sv}",),
        "Start": ("osa{sv}",),
    }
    for uye, (imza,) in beklenen.items():
        bulunan = _cagri_ozeti(tasiyici, uye)
        assert bulunan is not None, f"{uye} çağrılmadı"
        assert bulunan[0] == imza, f"{uye} imzası yanlış"

    oturum.press("ctrl+s")
    assert _cagri_ozeti(tasiyici, "NotifyKeyboardKeysym")[0] == "oa{sv}iu"
    oturum.mouse_down("right")
    assert _cagri_ozeti(tasiyici, "NotifyPointerButton")[0] == "oa{sv}iu"

# --- dikiş sürücüleri (port-temel'in `erisim` yüzü) ------------------------


class TestDikisSurucileri:
    """Sürücüler dikiş sözleşmesini taşıyor mu ve uygunluk sınaması sessiz mi.

    Türler ve yöntem adları port-temel'in sözleşmesinden kopyalanmış liste:
    bunlar tutmazsa dikiş sürücüyü seçemez ve hata üretim zamanında çıkar.
    """

    def test_girdi_yuzu_tam(self):
        from backend.computer import portal_surucu

        gerekli = [
            "move_to", "cursor_position", "click", "mouse_down", "mouse_up",
            "scroll", "press", "type_text", "tus_adlari_bas", "tus_adlari_birak",
        ]
        eksik = [ad for ad in gerekli if not callable(getattr(portal_surucu.GirdiSurucusu, ad, None))]
        assert eksik == []

    def test_girdi_kurulurken_oturum_acilmaz(self):
        """musait()/kurulum diyalog açmamalı: kur, ama bağlanma."""
        from backend.computer import portal_surucu

        surucu = portal_surucu.GirdiSurucusu({})
        assert surucu._oturum is None

    def test_ekran_ve_monitor_siniflari_var(self):
        from backend.computer import portal_surucu

        assert callable(getattr(portal_surucu.EkranSurucusu, "grab"))
        assert callable(getattr(portal_surucu.EkranSurucusu, "close"))
        assert callable(getattr(portal_surucu.MonitorSurucusu, "monitorler"))

    def test_monitor_listesi_sahte_bos_liste_degil(self):
        """Boş liste ajanı 'monitör yok' sanısına düşürürdü."""
        from backend.computer import portal_surucu

        with pytest.raises(PortalHatasi, match="consented screen cast session"):
            portal_surucu.MonitorSurucusu({}).monitorler()

    def test_uygunluk_sinamasi_diyalog_acmaz(self, monkeypatch):
        """`portal_musait_mi` yalnızca isim sorar; taşıyıcıyı kurup kapatır."""
        from backend.computer import portal_surucu

        kurulan = []

        class Vekil:
            def __init__(self, zaman_asimi=10.0):
                kurulan.append(1)

            def ad_sahipli_mi(self, ad):
                return False

            def adlar(self):
                return []

            def etkinlestirilebilir_adlar(self):
                return []

            def kapat(self):
                pass

        monkeypatch.setattr(portal_tasiyici, "DbusNextTasiyici", Vekil)
        assert portal_surucu.portal_musait_mi() is False
        assert kurulan == [1]

    def test_tus_birak_ters_sira(self):
        """`ctrl+shift` basıldıysa önce shift bırakılmalı."""
        from backend.computer import portal_surucu

        surucu = portal_surucu.GirdiSurucusu({})
        birakilanlar: list[tuple[int, int]] = []

        class SahteOturum:
            def key_press(self, keysym, durum):
                birakilanlar.append((keysym, durum))

        surucu._oturum = SahteOturum()  # type: ignore[assignment]
        surucu.tus_adlari_bas(["ctrl", "shift"])
        surucu.tus_adlari_birak(["ctrl", "shift"])
        basilanlar = [k for k, d in birakilanlar if d == portal_girdi.BASILDI]
        birakilan = [k for k, d in birakilanlar if d == portal_girdi.BIRAKILDI]
        assert basilanlar == [0xFFE3, 0xFFE1]
        assert birakilan == [0xFFE1, 0xFFE3]  # ters sıra
