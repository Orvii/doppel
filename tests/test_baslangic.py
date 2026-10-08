"""Açılışta başlama — gerçek kayıt defterine ya da gerçek `autostart`'a
dokunmadan.

Windows dalı: `winreg` modülünün yerine sözlükle çalışan bir sahte konuyor.
Bir testin makinenin açılış ayarını değiştirmesi, testi çalıştıran kişinin
bilgisayarını değiştirmesi demek olurdu.

Linux dalı: `XDG_CONFIG_HOME` `tmp_path`'e çevrilip dizin sahteleniyor —
gerçek `~/.config/autostart`'a hiç dokunulmuyor. Linux bu makinede
çalışmadığı için sınanan şey içerik üretimi ve temizlik mantığı; gerçek
masaüstünün girdiyi okuyup okumadığı **doğrulanmadı**.

Ağırlık üç yerde: komutun **tırnaklanması** (kullanıcı adında boşluk
varsa tırnaksız komut sessizce hiçbir şey başlatmıyor), yazılan yolun
gerçekten doğru yorumlayıcıyı + betiği göstermesi, ve aç/kapat döngüsünün
`acik()` ile tutarlı kalması — artı ad değişiminden kalan eski girdinin
temizlenmesi, başkalarının girdilerine dokunmadan.
"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

import pytest

from app import baslangic, isletim


class SahteAnahtar:
    """Açılmış bir kayıt defteri anahtarı — arkasında bir sözlük var."""

    def __init__(self, degerler: dict[str, str]) -> None:
        self.degerler = degerler
        self.kapali = False


class SahteWinreg:
    """`winreg`in kullanılan yüzeyi. Yol yanlışsa `FileNotFoundError`.

    Gerçek `winreg` var olmayan anahtar ve değerde `FileNotFoundError`
    (bir `OSError`) atıyor; sahte de atıyor, yoksa modülün "yoksa kapalı
    demektir" dalları hiç sınanmamış olurdu.
    """

    HKEY_CURRENT_USER = "HKCU"
    KEY_READ = 1
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self) -> None:
        #: {anahtar_yolu: {deger_adi: veri}}
        self.kovan: dict[str, dict[str, str]] = {}
        self.acik_kalan = 0

    def OpenKey(self, kok, yol, ayrilmis=0, erisim=0):
        assert kok == self.HKEY_CURRENT_USER, "HKCU dışına yazılıyor"
        if yol not in self.kovan:
            raise FileNotFoundError(2, "anahtar yok", yol)
        self.acik_kalan += 1
        return SahteAnahtar(self.kovan[yol])

    def CreateKeyEx(self, kok, yol, ayrilmis=0, erisim=0):
        assert kok == self.HKEY_CURRENT_USER, "HKCU dışına yazılıyor"
        self.acik_kalan += 1
        return SahteAnahtar(self.kovan.setdefault(yol, {}))

    def QueryValueEx(self, anahtar, ad):
        if ad not in anahtar.degerler:
            raise FileNotFoundError(2, "değer yok", ad)
        return anahtar.degerler[ad], self.REG_SZ

    def SetValueEx(self, anahtar, ad, ayrilmis, tur, veri):
        assert tur == self.REG_SZ
        anahtar.degerler[ad] = veri

    def DeleteValue(self, anahtar, ad):
        if ad not in anahtar.degerler:
            raise FileNotFoundError(2, "değer yok", ad)
        del anahtar.degerler[ad]

    def CloseKey(self, anahtar):
        anahtar.kapali = True
        self.acik_kalan -= 1


@pytest.fixture()
def kayit(monkeypatch):
    # Windows dalı **gerçekten** Windows varsayılıyor: aksi hâlde Linux'ta
    # `acik()`/`ac()`/`kapat()` XDG dalına gider ve bu testler kayıt
    # defterini hiç sınamamış olurdu. Sabitlemek, hangi dalın ölçüldüğünü
    # koşulan makineye bırakmıyor.
    monkeypatch.setattr(isletim, "WINDOWS", True)
    sahte = SahteWinreg()
    monkeypatch.setattr(baslangic, "winreg", sahte)
    return sahte


def _yazilan(sahte: SahteWinreg) -> str | None:
    return sahte.kovan.get(baslangic.ANAHTAR, {}).get(baslangic.DEGER)


class TestKomut:
    def test_iki_parca_da_tirnakli(self):
        # Kullanıcı adında boşluk olabiliyor; tırnaksız komutu Windows
        # ilk boşluktan bölüyor ve hiçbir şey başlamıyor.
        k = baslangic.komut()
        assert k.count('"') == 4
        assert k.startswith('"') and k.endswith('"')
        assert '" "' in k

    def test_bosluklu_kullanici_adi_bolunmuyor(self, monkeypatch):
        bosluklu = Path(r"C:\Users\Ada Lovelace\.venv\Scripts\pythonw.exe")
        monkeypatch.setattr(baslangic, "_pythonw", lambda: bosluklu)
        k = baslangic.komut()
        assert f'"{bosluklu}"' in k
        # Tırnaklar sökülünce iki parça kalmalı, dört değil.
        import shlex

        parcalar = shlex.split(k, posix=False)
        assert len(parcalar) == 2

    def test_pythonw_ve_doppel_yollari(self):
        k = baslangic.komut()
        if isletim.WINDOWS:
            # Konsolsuz başlatma Windows'a özgü; komut Linux'ta hiç
            # yazılmıyor (XDG girdisi `Doppel.sh` gösteriyor), o yüzden
            # bu iddia yalnızca Windows'ta anlamlı.
            assert "pythonw.exe" in k.lower()
        betik = Path(__file__).resolve().parent.parent / "doppel.py"
        assert betik.exists(), "doppel.py deponun kökünde değil"
        assert str(betik) in k

    def test_yollar_mutlak(self):
        import shlex

        for parca in shlex.split(baslangic.komut(), posix=False):
            assert Path(parca.strip('"')).is_absolute()

    def test_pythonw_yoksa_calisan_yorumlayici(self, monkeypatch):
        # Konsollu başlamak, hiç başlamamaktan iyi.
        import sys

        monkeypatch.setattr(Path, "exists", lambda self: False)
        assert baslangic._pythonw() == Path(sys.executable)


class TestAcKapat:
    def test_hicbir_sey_yokken_kapali(self, kayit):
        assert not baslangic.acik()

    def test_ac_kapat_dongusu(self, kayit):
        assert not baslangic.acik()
        baslangic.ac()
        assert baslangic.acik()
        assert _yazilan(kayit) == baslangic.komut()
        baslangic.kapat()
        assert not baslangic.acik()
        assert _yazilan(kayit) is None

    def test_dogru_anahtara_yaziliyor(self, kayit):
        baslangic.ac()
        assert list(kayit.kovan) == [
            r"Software\Microsoft\Windows\CurrentVersion\Run"
        ]
        assert list(kayit.kovan[baslangic.ANAHTAR]) == [baslangic.DEGER]

    def test_iki_kez_acmak_tek_deger_birakiyor(self, kayit):
        baslangic.ac()
        baslangic.ac()
        assert len(kayit.kovan[baslangic.ANAHTAR]) == 1

    def test_iki_kez_kapatmak_patlamiyor(self, kayit):
        baslangic.ac()
        baslangic.kapat()
        baslangic.kapat()
        assert not baslangic.acik()

    def test_hic_acilmadan_kapatmak_patlamiyor(self, kayit):
        baslangic.kapat()
        assert not baslangic.acik()

    def test_anahtar_kapatiliyor(self, kayit):
        baslangic.ac()
        baslangic.acik()
        baslangic.kapat()
        assert kayit.acik_kalan == 0, "kayıt defteri tutamacı sızdırılıyor"


class TestBayatKayit:
    def test_baska_bir_kopyayi_gosteren_kayit_acik_sayilmiyor(self, kayit):
        # Depo taşındıysa satır duruyor ama hiçbir şey başlatmıyor;
        # işaretli bir kutu göstermek yalan olurdu.
        kayit.kovan[baslangic.ANAHTAR] = {
            baslangic.DEGER: r'"C:\eski\pythonw.exe" "D:\eski\doppel.py"'
        }
        assert not baslangic.acik()

    def test_bayat_kaydin_uzerine_yaziliyor(self, kayit):
        kayit.kovan[baslangic.ANAHTAR] = {baslangic.DEGER: "eski"}
        baslangic.ac()
        assert _yazilan(kayit) == baslangic.komut()
        assert baslangic.acik()

    def test_buyuk_kucuk_harf_onemsiz(self, kayit):
        # Windows yolları harfe duyarsız; kayıt büyük harfle yazılmışsa
        # kutu işaretsiz görünmemeli.
        kayit.kovan[baslangic.ANAHTAR] = {
            baslangic.DEGER: baslangic.komut().upper()
        }
        assert baslangic.acik()

    def test_yorumlayici_degisse_de_acik(self, kayit):
        # `python.exe` → `pythonw.exe` farkı kutuyu işaretsiz yapmamalı;
        # bakılan şey hangi betiğin başlatıldığı.
        betik = baslangic._betik()
        kayit.kovan[baslangic.ANAHTAR] = {
            baslangic.DEGER: f'"C:\\baska\\python.exe" "{betik}"'
        }
        assert baslangic.acik()

    def test_baska_degerler_korunuyor(self, kayit):
        # Aynı anahtarın altında başka uygulamaların girdileri var.
        kayit.kovan[baslangic.ANAHTAR] = {"BaskaUygulama": "x.exe"}
        baslangic.ac()
        baslangic.kapat()
        assert kayit.kovan[baslangic.ANAHTAR] == {"BaskaUygulama": "x.exe"}

    def test_eski_adli_deger_acik_saymiyor(self, kayit):
        # Ürünün eski adıyla yazılmış satır hâlâ `yanmasa.py`'yi gösteriyor
        # ve o dosya artık yok; işaretli bir kutu yalan olurdu.
        kayit.kovan[baslangic.ANAHTAR] = {
            baslangic.ESKI_DEGER: r'"C:\eski\pythonw.exe" "C:\eski\yanmasa.py"'
        }
        assert not baslangic.acik()

    def test_eski_adli_deger_acarken_siliniyor(self, kayit):
        # Bırakılsaydı her oturum açılışında var olmayan bir betiği
        # başlatmayı denerdi.
        kayit.kovan[baslangic.ANAHTAR] = {baslangic.ESKI_DEGER: "eski"}
        baslangic.ac()
        assert baslangic.ESKI_DEGER not in kayit.kovan[baslangic.ANAHTAR]
        assert _yazilan(kayit) == baslangic.komut()

    def test_eski_adli_deger_kapatirken_siliniyor(self, kayit):
        kayit.kovan[baslangic.ANAHTAR] = {baslangic.ESKI_DEGER: "eski"}
        baslangic.kapat()
        assert baslangic.ESKI_DEGER not in kayit.kovan[baslangic.ANAHTAR]

    def test_eski_deger_yokken_eskiyi_silmek_patlamiyor(self, kayit):
        baslangic.ac()
        assert baslangic.acik()


@pytest.fixture()
def xdg(tmp_path, monkeypatch):
    """Linux dalı: gerçek `~/.config` yerine `tmp_path`.

    `XDG_CONFIG_HOME` çevriliyor — modülün kendi okuduğu değişken bu, yolu
    hesaplayan fonksiyonu sahtelemek gerçek davranışı gizlerdi.
    """
    monkeypatch.setattr(isletim, "WINDOWS", False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    return tmp_path / "config" / "autostart"


class TestXdgIcerik:
    """Yazılan `.desktop` dosyası — birebir beklenen içerik.

    `Exec` **mutlak depo yolunu** gösteriyor ve tırnaklı: depo yolu boşluk
    içerebiliyor ve masaüstü ortamı `Exec` değerini boşluktan bölüyor.
    Sanal ortamı çözen şey `Doppel.sh`; buradan `python3 .../doppel.py`
    yazmak o çözümü atlardı.

    İçerik testlerinde `_baslatici()` sabit bir yola çevriliyor: gerçek
    depo yoluna göre yazılan golden, testin koştuğu klasöre göre
    değişirdi ve taşınan bir depoda sessizce yanlış olurdu. Gerçek yolun
    doğruluğu ayrı testte, hesaplanarak sınanıyor.
    """

    #: Sahte depo: düz bir POSIX yolu. `PurePosixPath` bilinçli — bu
    #: testler Linux dalını sınıyor ve Windows'ta `Path("/opt/x")`
    #: ayırıcıları çevirip golden'ı platforma bağlardı.
    DEPO = PurePosixPath("/opt/doppel")

    @pytest.fixture(autouse=True)
    def _sabit_depo(self, monkeypatch):
        monkeypatch.setattr(baslangic, "_baslatici",
                            lambda: self.DEPO / "Doppel.sh")

    def test_tam_icerik_birebir(self, xdg):
        assert baslangic.xdg_metni() == (
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Doppel\n"
            "Comment=Launch Doppel when you sign in\n"
            'Exec="/opt/doppel/Doppel.sh"\n'
            "Terminal=false\n"
            "X-GNOME-Autostart-enabled=true\n"
            "X-Doppel-Autostart=true\n"
        )

    def test_bosluklu_yol_tirnakli(self, xdg, monkeypatch):
        # `~/My Projects/doppel` altında kurulum: tırnak olmadan masaüstü
        # ortamı `Exec` değerini ilk boşluktan bölüyor.
        monkeypatch.setattr(
            baslangic, "_baslatici",
            lambda: PurePosixPath("/opt/My Projects/doppel/Doppel.sh"),
        )
        assert 'Exec="/opt/My Projects/doppel/Doppel.sh"\n' in baslangic.xdg_metni()

    def test_ters_bolu_ve_tirnak_kacisli(self, xdg, monkeypatch):
        # Kaçışsız bir `\` ya da `"` değeri bozardı; masaüstü girdisi
        # sözdizimi ikisini de kaçışlı bekliyor.
        monkeypatch.setattr(
            baslangic, "_baslatici",
            lambda: PurePosixPath('/opt/do"ppel\\x/Doppel.sh'),
        )
        assert 'Exec="/opt/do\\"ppel\\\\x/Doppel.sh"\n' in baslangic.xdg_metni()

    def test_imlec_satiri_var(self, xdg):
        # Temizlik bize ait dosyaları bu satırdan tanıyor.
        assert f"{baslangic.XDG_ISARET}=true" in baslangic.xdg_metni()

    def test_dosya_adi(self, xdg):
        assert baslangic._xdg_yolu().name == "doppel.desktop"
        assert baslangic._xdg_yolu().parent.name == "autostart"

    def test_xdg_config_home_yoksa_home(self, xdg, monkeypatch):
        # `XDG_CONFIG_HOME=` diye boş bırakan bir kabuk, girdileri geçerli
        # dizinin altına yazdırırdı; boş dize "tanımsız" sayılıyor.
        monkeypatch.setenv("XDG_CONFIG_HOME", "")
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/ev")))
        assert baslangic._xdg_yolu() == Path("/ev/.config/autostart/doppel.desktop")


class TestGercekYol:
    """Sabitlenmiş golden'ın yanında gerçek hesap: `_baslatici` bu deponun
    kökünü göstermeli ve yazılan `Exec` aynı yola geri çözülmeli."""

    def test_gidis_donus(self, xdg):
        depo = Path(__file__).resolve().parent.parent
        assert baslangic._baslatici() == depo / "Doppel.sh"

        baslangic.ac()
        assert baslangic.acik()
        assert baslangic._exec_ayikla(
            baslangic._xdg_yolu().read_text(encoding="utf-8")
        ) == str(depo / "Doppel.sh")
        assert os.path.isabs(baslangic._exec_ayikla(baslangic.xdg_metni()))


class TestXdgAcKapat:
    def test_hicbir_sey_yokken_kapali(self, xdg):
        assert not baslangic.acik()

    def test_ac_kapat_dongusu(self, xdg):
        assert not baslangic.acik()
        baslangic.ac()
        assert baslangic.acik()
        assert baslangic._xdg_yolu().read_text(encoding="utf-8") == baslangic.xdg_metni()
        baslangic.kapat()
        assert not baslangic.acik()
        assert not baslangic._xdg_yolu().exists()

    def test_iki_kez_acmak_tek_dosya_birakiyor(self, xdg):
        baslangic.ac()
        baslangic.ac()
        assert [p.name for p in xdg.glob("*.desktop")] == ["doppel.desktop"]

    def test_iki_kez_kapatmak_patlamiyor(self, xdg):
        baslangic.ac()
        baslangic.kapat()
        baslangic.kapat()
        assert not baslangic.acik()

    def test_hic_acilmadan_kapatmak_patlamiyor(self, xdg):
        baslangic.kapat()
        assert not baslangic.acik()

    def test_yazma_gecici_dosya_birakmiyor(self, xdg):
        baslangic.ac()
        assert not list(xdg.glob("*.yeni"))
        assert [p.name for p in xdg.iterdir()] == ["doppel.desktop"]

    def test_yarim_yazilmis_girdi_acik_saymiyor(self, xdg):
        # `os.replace` şart: yarıda kalan bir yazma bozuk bir girdi
        # bırakırdı ve o hâli "açık" göstermek en kötüsü olurdu.
        xdg.mkdir(parents=True)
        (xdg / "doppel.desktop").write_text("Exec=", encoding="utf-8")
        assert not baslangic.acik()


class TestXdgBayatKayit:
    def test_baska_bir_kopyayi_gosteren_girdi_kapali(self, xdg):
        # Depo taşındıysa eski girdi duruyor ama hiçbir şey başlatmıyor.
        xdg.mkdir(parents=True)
        (xdg / "doppel.desktop").write_text(
            'Exec="/eski/yer/Doppel.sh"\n', encoding="utf-8")
        assert not baslangic.acik()

    def test_bayat_girdinin_uzerine_yaziliyor(self, xdg):
        xdg.mkdir(parents=True)
        (xdg / "doppel.desktop").write_text("Exec=/eski/Doppel.sh\n",
                                            encoding="utf-8")
        baslangic.ac()
        assert baslangic.acik()
        assert baslangic._xdg_yolu().read_text(encoding="utf-8") == baslangic.xdg_metni()

    def test_eski_adli_dosya_acik_saymiyor(self, xdg):
        # Ürünün eski adıyla yazılmış girdi artık var olmayan bir betik
        # gösteriyor; işaretli bir kutu yalan olurdu.
        xdg.mkdir(parents=True)
        (xdg / "yanmasa.desktop").write_text(
            "Exec=/eski/yanmasa.py\n", encoding="utf-8")
        assert not baslangic.acik()

    def test_acarken_eski_girdi_siliniyor(self, xdg):
        # Bırakılsaydı her oturum açılışında var olmayan bir betik
        # başlatılmaya çalışılırdı — ve aynı uygulama iki kez açılırdı.
        xdg.mkdir(parents=True)
        (xdg / "yanmasa.desktop").write_text(
            "Exec=/eski/yanmasa.py\n", encoding="utf-8")
        baslangic.ac()
        assert [p.name for p in xdg.glob("*.desktop")] == ["doppel.desktop"]
        assert baslangic.acik()

    def test_kapatirken_eski_girdi_siliniyor(self, xdg):
        xdg.mkdir(parents=True)
        (xdg / "yanmasa.desktop").write_text(
            "Exec=/eski/yanmasa.py\n", encoding="utf-8")
        (xdg / "doppel.desktop").write_text(baslangic.xdg_metni(),
                                            encoding="utf-8")
        baslangic.kapat()
        assert list(xdg.glob("*.desktop")) == []

    def test_eski_ad_YAMLIS_yazilmis_girdi_de_silinir(self, xdg):
        # Ad değişse bile imleç satırımız kalmış: dosya adı `doppel.desktop`
        # olmayan ama bize ait bir girdi de temizlenmeli.
        xdg.mkdir(parents=True)
        (xdg / "eski-doppel.desktop").write_text(
            "[Desktop Entry]\n"
            f"{baslangic.XDG_ISARET}=true\n"
            'Exec="/eski/yer/Doppel.sh"\n',
            encoding="utf-8",
        )
        baslangic.ac()
        assert [p.name for p in xdg.glob("*.desktop")] == ["doppel.desktop"]

    def test_baskalarinin_girdilerine_dokunulmuyor(self, xdg):
        # Oturum açılış klasöründe başka uygulamaların girdileri var ve
        # onları silmek, kullanıcının kurduğu bir şeyin sebebi görünmeden
        # kaybolması demek olurdu.
        xdg.mkdir(parents=True)
        yabanci = {
            "slack.desktop": "[Desktop Entry]\nName=Slack\nExec=/usr/bin/slack\n",
            "notdoppel.desktop": "[Desktop Entry]\nName=x\nExec=/x/notdoppel.py\n",
            "yanmasa-klonu.desktop": "[Desktop Entry]\nName=y\nExec=/x/yanmasa.py.bak\n",
        }
        for ad, icerik in yabanci.items():
            (xdg / ad).write_text(icerik, encoding="utf-8")
        baslangic.ac()
        baslangic.kapat()
        kalan = {p.name for p in xdg.glob("*.desktop")}
        assert kalan == set(yabanci), kalan

    def test_dizin_yokken_kapatmak_patlamiyor(self, xdg):
        assert not xdg.exists()
        baslangic.kapat()  # patlamamalı
