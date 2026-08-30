"""Yan masanın ekran kaydı.

Dosya adı `test_kayit.py` değil: o ad denetim kaydının testlerinde ve
iki ayrı `kayit` modülü var — biri `backend/agent` (denetim kaydı), biri
`backend/computer` (ekran kaydı). Var olan dosyanın üstüne yazmak
otuz testi silmek olurdu.

Burada **gerçek ffmpeg çalıştırılmıyor**. Testler dış sürece, ağa ve
Windows API'sine dokunmuyor; süreç sahteleniyor ve doğrulanan şey
sahteye ne verildiği: komut satırı, `lpDesktop`, durdurma sırası.

Gerçek ffmpeg ile ölçüm ayrı bir yerde: `scripts/dogrula_kayit.py`.
Onun sonucu `backend/computer/kayit.py` docstring'inde yazılı.
"""

from __future__ import annotations

import ctypes
from pathlib import Path

import pytest

from backend.computer import kayit as kayit_mod
from backend.computer.kayit import (
    EkranKaydi,
    KayitHatasi,
    STARTF_USESTDHANDLES,
    _startupinfo,
    ffmpeg_komutu,
    ffmpeg_yolu,
    varsayilan_hedef,
)

MASA = "ajan-calisma"


class SahteSurec:
    """ffmpeg'in yerine geçen sahte. Ne çağrıldığını sırasıyla tutuyor.

    `yasar` ile ne zaman öleceği ayarlanıyor: `basla` açılışta ölen bir
    ffmpeg'i yakalamak için bekliyor, `durdur` ise `q`'dan sonra
    ölmesini bekliyor. İkisi de aynı `bekle` çağrısı, farkı yalnızca
    zamanı.
    """

    def __init__(self, acilista_olur: bool = False,
                 qya_cevap_verir: bool = True, gunluk: str = "") -> None:
        self._acilista_olur = acilista_olur
        self._qya_cevap_verir = qya_cevap_verir
        self.gunluk = gunluk
        self.pid = 4242
        self.izler: list[str] = []
        self._q_yazildi = False

    def bekle(self, _saniye: float) -> bool:
        self.izler.append("bekle")
        if not self._q_yazildi:
            return self._acilista_olur
        return self._qya_cevap_verir

    def dur_iste(self) -> None:
        self.izler.append("dur_iste")
        self._q_yazildi = True

    def oldur(self) -> None:
        self.izler.append("oldur")

    def kapat(self) -> None:
        self.izler.append("kapat")


@pytest.fixture
def ffmpeg_var(monkeypatch):
    """ffmpeg'i PATH'te varmış gibi gösterir.

    Gerçek `shutil.which`'e bırakılsaydı testler makinede ffmpeg kurulu
    olup olmamasına göre farklı davranırdı — yani bir gün ffmpeg'i olan
    makinede geçip olmayanda kırılırdı.
    """
    monkeypatch.setattr(
        kayit_mod.shutil, "which", lambda ad: r"C:\bin\ffmpeg.exe")


def kur(surec: SahteSurec) -> tuple[EkranKaydi, list[tuple[str, str]]]:
    """Sahte süreç doğuran bir kaydedici ve doğurma çağrılarının listesi."""
    cagrilar: list[tuple[str, str]] = []

    def dogur(komut: str, masaustu: str):
        cagrilar.append((komut, masaustu))
        return surec

    return EkranKaydi(MASA, dogurucu=dogur), cagrilar


class TestKomutSatiri:
    """ffmpeg'e ne söylendiği. Yanlış bir bayrak, sessizce yanlış bir
    video demek — dosya yine oluşuyor."""

    def test_yan_pencereyi_cekiyor(self, ffmpeg_var):
        komut = ffmpeg_komutu(Path(r"C:\r\a.mp4"), hwnd=0x20039C)
        assert "-f gdigrab" in komut
        # Asıl mesele bu: `-i desktop` ana masaüstünü çekerdi ve yan
        # masaüstünde zaten çalışmıyor (modül docstring'i, ölçüm).
        assert f"-i hwnd={0x20039C}" in komut
        assert "-i desktop" not in komut

    def test_sistem_imleci_cizilmiyor(self, ffmpeg_var):
        # Yan masaüstünde fiziksel imleç yok; çizilen ok hiç kıpırdamıyor.
        assert "-draw_mouse 0" in ffmpeg_komutu(Path("a.mp4"), hwnd=1)

    def test_yollar_tirnakli(self, ffmpeg_var):
        hedef = Path(r"C:\Users\bir kisi\runs\a.mp4")
        komut = ffmpeg_komutu(hedef, hwnd=1)
        assert f'"{hedef}"' in komut
        assert '"C:\\bin\\ffmpeg.exe"' in komut

    def test_oynatilabilir_mp4(self, ffmpeg_var):
        komut = ffmpeg_komutu(Path("a.mp4"), hwnd=1)
        # yuv420p tek sayılı boyut kabul etmiyor, pencere boyutu keyfî.
        assert "crop=trunc(iw/2)*2:trunc(ih/2)*2" in komut
        assert "-pix_fmt yuv420p" in komut
        assert "-movflags +faststart" in komut

    def test_kare_hizi_ayarlanabiliyor(self, ffmpeg_var):
        assert "-framerate 4" in ffmpeg_komutu(Path("a.mp4"), 1, kare_hizi=4)


class TestMasaustu:
    """Kaydın doğru ekranı çekmesinin tek şartı `lpDesktop`."""

    def test_lpdesktop_yan_masaustu(self):
        si = _startupinfo(MASA)
        assert si.lpDesktop == MASA

    def test_stdin_devredilebilsin_diye_bayrak_var(self):
        # Bayrak olmadan `hStdInput` yok sayılıyor ve ffmpeg'e `q`
        # yazacak bir boru kalmıyor — yani temiz durdurma imkânsız.
        si = _startupinfo(MASA, stdin=None, stdout=None, stderr=None)
        assert si.dwFlags & STARTF_USESTDHANDLES
        assert si.cb == ctypes.sizeof(si)

    def test_surec_yan_masaustunde_doguruluyor(self, ffmpeg_var, tmp_path):
        kayit, cagrilar = kur(SahteSurec())
        kayit.basla(tmp_path / "a.mp4", hwnd=7)
        assert [masa for _komut, masa in cagrilar] == [MASA]


class TestBasla:
    def test_hedefi_ve_klasoru_kuruyor(self, ffmpeg_var, tmp_path):
        kayit, _ = kur(SahteSurec())
        hedef = tmp_path / "kosu" / "kosu.mp4"
        assert kayit.basla(hedef, hwnd=7) == hedef
        assert hedef.parent.is_dir()
        assert kayit.suruyor

    def test_pencere_yoksa_reddediyor(self, ffmpeg_var, tmp_path):
        kayit, cagrilar = kur(SahteSurec())
        with pytest.raises(KayitHatasi, match="window handle"):
            kayit.basla(tmp_path / "a.mp4", hwnd=0)
        assert cagrilar == []

    def test_ikinci_kayit_reddediliyor(self, ffmpeg_var, tmp_path):
        kayit, cagrilar = kur(SahteSurec())
        kayit.basla(tmp_path / "a.mp4", hwnd=7)
        with pytest.raises(KayitHatasi, match="already running"):
            kayit.basla(tmp_path / "b.mp4", hwnd=7)
        # İkinci ffmpeg hiç doğmadı: iki süreç aynı pencereyi çekerse
        # ikisi de kare düşürür.
        assert len(cagrilar) == 1

    def test_acilista_olen_ffmpeg_hemen_bildiriliyor(self, ffmpeg_var, tmp_path):
        surec = SahteSurec(acilista_olur=True, gunluk="Failed to capture image")
        kayit, _ = kur(surec)
        with pytest.raises(KayitHatasi, match="Failed to capture image"):
            kayit.basla(tmp_path / "a.mp4", hwnd=7)
        assert not kayit.suruyor
        assert "kapat" in surec.izler


class TestTemizDurdurma:
    """`q` yazılıp beklenmeden öldürülen ffmpeg bozuk mp4 bırakıyor."""

    def test_once_q_sonra_bekleme(self, ffmpeg_var, tmp_path):
        surec = SahteSurec()
        kayit, _ = kur(surec)
        hedef = kayit.basla(tmp_path / "a.mp4", hwnd=7)
        assert kayit.durdur() == hedef
        # Açılış kontrolündeki `bekle` ilk sırada; asıl olan sonrası.
        assert surec.izler == ["bekle", "dur_iste", "bekle", "kapat"]
        assert "oldur" not in surec.izler
        assert not kayit.suruyor

    def test_cevap_vermeyen_ffmpeg_olduruluyor_ve_soyleniyor(
            self, ffmpeg_var, tmp_path):
        surec = SahteSurec(qya_cevap_verir=False)
        kayit, _ = kur(surec)
        kayit.basla(tmp_path / "a.mp4", hwnd=7)
        # Sessizce sağlam bir yol döndürmüyor: dosya oynatılmayabilir ve
        # bunu ancak paylaşmaya kalkınca öğrenmek en kötüsü.
        with pytest.raises(KayitHatasi, match="may be unplayable"):
            kayit.durdur()
        assert "oldur" in surec.izler
        assert "kapat" in surec.izler
        assert not kayit.suruyor

    def test_kayit_yoksa_none(self, ffmpeg_var):
        kayit, _ = kur(SahteSurec())
        assert kayit.durdur() is None

    def test_kapat_hatayi_yutuyor(self, ffmpeg_var, tmp_path):
        # Kapanış yolundaki bir istisna, ondan sonraki temizliği de
        # iptal ederdi.
        surec = SahteSurec(qya_cevap_verir=False)
        kayit, _ = kur(surec)
        kayit.basla(tmp_path / "a.mp4", hwnd=7)
        kayit.kapat()
        assert not kayit.suruyor
        assert "oldur" in surec.izler

    def test_sure_durdurulunca_donuyor(self, ffmpeg_var, tmp_path):
        kayit, _ = kur(SahteSurec())
        assert kayit.sure == 0.0
        kayit.basla(tmp_path / "a.mp4", hwnd=7)
        assert kayit.sure >= 0.0
        kayit.durdur()
        assert kayit.sure >= 0.0


class TestFfmpegYok:
    def test_acik_hata(self, monkeypatch):
        monkeypatch.setattr(kayit_mod.shutil, "which", lambda _ad: None)
        with pytest.raises(KayitHatasi) as hata:
            ffmpeg_yolu()
        metin = str(hata.value)
        # Hata ne olduğunu ve ne yapılacağını söylüyor; "None" demiyor.
        assert "ffmpeg" in metin
        assert "PATH" in metin
        assert "winget" in metin

    def test_basla_sessizce_gecmiyor(self, monkeypatch, tmp_path):
        monkeypatch.setattr(kayit_mod.shutil, "which", lambda _ad: None)
        kayit, cagrilar = kur(SahteSurec())
        with pytest.raises(KayitHatasi, match="ffmpeg was not found"):
            kayit.basla(tmp_path / "a.mp4", hwnd=7)
        assert not kayit.suruyor
        assert cagrilar == []


class TestHedefYolu:
    def test_kosu_klasoru_ve_kosu_adi(self, tmp_path):
        yol = varsayilan_hedef("20260830-141500", dizin=tmp_path)
        assert yol == tmp_path / "20260830-141500" / "20260830-141500.mp4"

    def test_varsayilan_dizin_runs(self):
        assert varsayilan_hedef("x").parent.parent.name == "runs"


class TestKuruKosu:
    """Kayıt dosya yazıyor — kuru koşuda engelli kalmalı."""

    def test_izin_listesinde_degil(self):
        from backend.agent import kuru

        assert not kuru.serbest("record_start")
        assert not kuru.serbest("record_stop")

    def test_kuru_kosuda_ffmpeg_dogmuyor(self, ffmpeg_var, tmp_path):
        from backend.agent.dispatch import Dispatcher
        from backend.computer.displays import Display, DisplayMap
        from backend.safety.killswitch import KillSwitch

        d = Dispatcher(DisplayMap([Display(0, 0, 0, 1920, 1080, True)]),
                       capture=None, kill=KillSwitch())
        surec = SahteSurec()
        kayit, cagrilar = kur(surec)
        d.ekran_kaydi = kayit
        d.kuru = True
        d.last_side_hwnd = 7
        sonuc = d.run("record_start", {})
        assert "[dry run]" in sonuc.content
        assert cagrilar == []
        assert not kayit.suruyor


class TestAkisaKaydedilmiyor:
    def test_record_araclari_akisa_girmiyor(self):
        from backend.workflows.depo import kaydedilir

        # Oynatılan bir akışın sessizce ffmpeg başlatması, kimsenin
        # istemediği bir video bırakırdı.
        assert not kaydedilir("record_start")
        assert not kaydedilir("record_stop")


class TestAraclar:
    def test_ikisi_de_tanimli(self):
        from backend.agent.tools import CUSTOM_TOOL_NAMES

        assert {"record_start", "record_stop"} <= CUSTOM_TOOL_NAMES

    def _dispatcher(self, kayit):
        from backend.agent.dispatch import Dispatcher
        from backend.computer.displays import Display, DisplayMap
        from backend.safety.killswitch import KillSwitch

        d = Dispatcher(DisplayMap([Display(0, 0, 0, 1920, 1080, True)]),
                       capture=None, kill=KillSwitch())
        d.ekran_kaydi = kayit
        return d

    def test_son_dokunulan_pencereyi_kaydediyor(self, ffmpeg_var, tmp_path,
                                                monkeypatch):
        monkeypatch.setattr(kayit_mod, "DIZIN", tmp_path)
        kayit, cagrilar = kur(SahteSurec())
        d = self._dispatcher(kayit)
        d.last_side_hwnd = 0x1234
        sonuc = d.run("record_start", {})
        assert not sonuc.is_error
        assert f"-i hwnd={0x1234}" in cagrilar[0][0]

    def test_verilen_hwnd_onceligi_aliyor(self, ffmpeg_var, tmp_path,
                                          monkeypatch):
        monkeypatch.setattr(kayit_mod, "DIZIN", tmp_path)
        kayit, cagrilar = kur(SahteSurec())
        d = self._dispatcher(kayit)
        d.last_side_hwnd = 0x1234
        d.run("record_start", {"hwnd": 0x99})
        assert f"-i hwnd={0x99}" in cagrilar[0][0]

    def test_pencere_yoksa_arac_hatasi(self, ffmpeg_var, monkeypatch):
        from backend.agent.dispatch import ToolError

        kayit, _ = kur(SahteSurec())
        d = self._dispatcher(kayit)
        # Yan masa hiç açılmasın: `pencereler()` boş liste veriyor.
        monkeypatch.setattr(type(d), "_side",
                            lambda _self: _BosMasa(), raising=True)
        with pytest.raises(ToolError, match="side_launch"):
            d.run("record_start", {})

    def test_durdurma_yolu_ve_sureyi_soyluyor(self, ffmpeg_var, tmp_path,
                                              monkeypatch):
        monkeypatch.setattr(kayit_mod, "DIZIN", tmp_path)
        kayit, _ = kur(SahteSurec())
        d = self._dispatcher(kayit)
        d.last_side_hwnd = 7
        d.run("record_start", {})
        sonuc = d.run("record_stop", {})
        assert str(kayit.hedef) in sonuc.content
        assert "s)." in sonuc.content

    def test_kayit_yokken_durdurma_hata_degil(self, ffmpeg_var):
        kayit, _ = kur(SahteSurec())
        d = self._dispatcher(kayit)
        sonuc = d.run("record_stop", {})
        assert not sonuc.is_error
        assert "Nothing was being recorded" in sonuc.content


class _BosMasa:
    def pencereler(self):
        return []


class TestKosuBitince:
    """Arkada ffmpeg kalmamalı — koşu nasıl biterse bitsin."""

    def test_shutdown_kaydi_durduruyor(self, ffmpeg_var, tmp_path):
        from backend.agent.dispatch import Dispatcher
        from backend.computer.displays import Display, DisplayMap
        from backend.safety.killswitch import KillSwitch

        d = Dispatcher(DisplayMap([Display(0, 0, 0, 1920, 1080, True)]),
                       capture=None, kill=KillSwitch())
        surec = SahteSurec()
        kayit, _ = kur(surec)
        d.ekran_kaydi = kayit
        kayit.basla(tmp_path / "a.mp4", hwnd=7)
        d.shutdown()
        assert not kayit.suruyor
        assert "dur_iste" in surec.izler

    def test_side_close_once_kaydi_durduruyor(self, ffmpeg_var, tmp_path):
        from backend.agent.dispatch import Dispatcher
        from backend.computer.displays import Display, DisplayMap
        from backend.safety.killswitch import KillSwitch

        d = Dispatcher(DisplayMap([Display(0, 0, 0, 1920, 1080, True)]),
                       capture=None, kill=KillSwitch())
        surec = SahteSurec()
        kayit, _ = kur(surec)
        d.ekran_kaydi = kayit
        kayit.basla(tmp_path / "a.mp4", hwnd=7)
        d.run("side_close", {})
        assert not kayit.suruyor
        assert "dur_iste" in surec.izler


class TestAcilDurdurma:
    """Esc x3 kaydı da durdurmalı."""

    def test_kanca_tetiklenince_calisiyor(self):
        from backend.safety.killswitch import KillSwitch

        cagrildi: list[str] = []
        kill = KillSwitch()
        kill.ayrica_cagir(lambda: cagrildi.append("kayit"))
        kill.trigger()
        assert cagrildi == ["kayit"]

    def test_patlayan_kanca_digerlerini_engellemiyor(self):
        from backend.safety.killswitch import KillSwitch

        cagrildi: list[str] = []

        def patlar():
            raise RuntimeError("olmadi")

        kill = KillSwitch()
        kill.ayrica_cagir(patlar)
        kill.ayrica_cagir(lambda: cagrildi.append("ikinci"))
        kill.trigger()
        assert kill.triggered
        assert cagrildi == ["ikinci"]

    def test_kurucudaki_kanca_hala_calisiyor(self):
        from backend.safety.killswitch import KillSwitch

        cagrildi: list[str] = []
        KillSwitch(on_trigger=lambda: cagrildi.append("kurucu")).trigger()
        assert cagrildi == ["kurucu"]

    def test_ikinci_tetikleme_kancalari_tekrar_calistirmiyor(self):
        from backend.safety.killswitch import KillSwitch

        sayac: list[int] = []
        kill = KillSwitch()
        kill.ayrica_cagir(lambda: sayac.append(1))
        kill.trigger()
        kill.trigger()
        assert sayac == [1]


@pytest.fixture()
def t():
    from app import fluent

    return fluent.tokens()


class TestRozet:
    """Kayıt sürerken arayüzde görünen kırmızı nokta ve durdurma yolu.

    Kayıt görünmezse en kötü sonuç sessiz: ajan işini bitirir, kimse
    kaydın hâlâ açık olduğunu fark etmez ve elde saatlik bir video
    kalır.
    """

    def test_bastan_gizli(self, qt_app, t):
        from app.window import KayitRozeti

        rozet = KayitRozeti(t)
        assert rozet.isHidden()

    def test_basladiginda_gorunuyor(self, qt_app, t):
        from app.window import KayitRozeti

        rozet = KayitRozeti(t)
        rozet.basladi()
        assert not rozet.isHidden()
        assert rozet._timer.isActive()

    def test_bitince_gizleniyor_ve_saat_duruyor(self, qt_app, t):
        from app.window import KayitRozeti

        rozet = KayitRozeti(t)
        rozet.basladi()
        rozet.bitti()
        assert rozet.isHidden()
        # Saat durmazsa gizli bir widget saniyede bir kendini boyar.
        assert not rozet._timer.isActive()

    def test_durdurma_yolu_var(self, qt_app, t):
        from app.window import KayitRozeti

        rozet = KayitRozeti(t)
        rozet.basladi()
        yakalanan: list[int] = []
        rozet.stop_requested.connect(lambda: yakalanan.append(1))
        rozet._stop.click()
        assert yakalanan == [1]

    def test_sure_sayiyor(self, qt_app, t):
        from app.window import KayitRozeti

        rozet = KayitRozeti(t)
        rozet.basladi()
        rozet._basladi -= 75  # 1:15 önce başlamış gibi
        rozet._tik()
        assert rozet._label.text() == "REC 1:15"

    def test_nokta_yanip_sonuyor(self, qt_app, t):
        from app.window import KayitRozeti

        rozet = KayitRozeti(t)
        rozet.basladi()
        renkler = []
        for _ in range(2):
            rozet._tik()
            renkler.append(rozet._dot._colour)
        # Sabit kırmızı bir daire, şeritteki durum ışığından ayırt
        # edilemiyordu.
        assert renkler[0] != renkler[1]
        assert t.critical in renkler

    def test_durum_seridinde_duruyor(self, qt_app, t):
        from app.window import StatusBar

        cubuk = StatusBar(t)
        assert cubuk.kayit.isHidden()
        cubuk.kayit.basladi()
        assert cubuk.kayit.parent() is cubuk
        assert not cubuk.kayit.isHidden()
