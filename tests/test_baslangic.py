"""Açılışta başlama — gerçek kayıt defterine dokunmadan.

Buradaki testlerin hiçbiri `HKEY_CURRENT_USER` altına yazmıyor: `winreg`
modülünün yerine sözlükle çalışan bir sahte konuyor. Bir testin makinenin
açılış ayarını değiştirmesi, testi çalıştıran kişinin bilgisayarını
değiştirmesi demek olurdu.

Ağırlık üç yerde: komutun **tırnaklanması** (kullanıcı adında boşluk
varsa tırnaksız komut sessizce hiçbir şey başlatmıyor), yazılan yolun
gerçekten `pythonw.exe` + `doppel.py` olması, ve aç/kapat döngüsünün
`acik()` ile tutarlı kalması.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app import baslangic


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
