"""Model uzayı — gönderilen karenin ölçeği ve koordinat çevirisi.

Bu dosyanın varlık sebebi bir iddianın kayda geçmesi: "kare küçültülmez,
modelin verdiği piksel doğrudan tıklanabilir pikseldir". İddia yanlıştı —
modelin kabul ettiği kare iki sınıra birden uymak zorunda (uzun kenar
<= 2576 px **ve** görsel token <= 4784) ve eski kod yalnızca kenara bakıp
ölçeği hiçbir yerde uygulamıyordu. 2560x1600 bir kare kenarın altında ama
5336 token, yani ya API onu kendisi küçültüyor (koordinatlar kayıyor) ya da
computer araç setindeki gibi isteği reddediyor.

Burada doğrulanan şey iki parçalı:

1. `model_kare_boyutu` modelin uygulayacağı boyutun aynısını hesaplıyor —
   Anthropic vision dokümanındaki referans algoritmanın çevirisi, dokümanın
   kendi örnekleriyle sabitlenmiş.
2. Ölçek **tek yerden** okunuyor: `Display.to_virtual` (model→ekran),
   `Display.from_virtual` (ekran→model, tersi), `Frame.model_gorsel`
   (gönderilen görüntü) ve `Frame.crop` (zoom bölgesi). Dördü de aynı
   fonksiyonun cevabını kullanıyor; ikinci bir kopya yok.

Testler tamamen çevrimdışı: görüntüler bellekte (PIL), yakalama yok, Windows
API'ye dokunulmuyor.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from backend.computer.capture import Frame
from backend.computer.displays import (
    MAX_LONG_EDGE_PX,
    MAX_VISUAL_TOKENS,
    Display,
    DisplayMap,
    _token_sayisi,
    gercek_noktayi_kucult,
    model_kare_boyutu,
    model_noktasini_buyut,
)

#: Dokümandaki standart katman: `claude-opus-5` yüksek katmanda ama
#: referans algoritmanın sınırları parametrik olduğunu buradan belli.
STANDART_EDGE, STANDART_TOKEN = 1568, 1568


def _bkz(w: int, h: int, max_edge=MAX_LONG_EDGE_PX,
         max_tokens=MAX_VISUAL_TOKENS) -> tuple[int, int]:
    return model_kare_boyutu(w, h, max_edge, max_tokens)


class TestSinirlar:
    def test_bu_makinenin_kareleri_kucultulmuyor(self):
        # 1920x1080 = 2691 token. İki sınırın da altında; iddianın doğru
        # olduğu tek durum bu ve monitör başına yakalamanın gerekçesi.
        assert _bkz(1920, 1080) == (1920, 1080)

    def test_kenar_sinirinda_tam_sigiyor(self):
        # 2576x1456 = 4784 token, tam ikisinin kesişimi. Sığıyor.
        assert _bkz(2576, 1456) == (2576, 1456)

    def test_bir_piksel_fazlasi_kucultuluyor(self):
        # Kenardan değil tokendan: 2576x1457 = 4876 token.
        assert _bkz(2576, 1457) == (2575, 1456)

    def test_token_butcesi_tek_basina_kucultuyor(self):
        # 2560x1600 kenarın altında (2560 < 2576) ama 5336 token.
        # Eski kod bunu sınır içinde sanıyordu.
        assert _bkz(2560, 1600) == (2420, 1512)
        assert _token_sayisi(2560, 1600) == 5336
        assert _token_sayisi(2420, 1512) == 4698

    def test_sanal_masaustu_tamami_sigmaz(self):
        assert _bkz(3840, 1080) == (2576, 724)

    def test_dikey_karede_uzun_kenar_yukseklik(self):
        assert _bkz(1080, 3840) == (724, 2576)

    def test_4k_ekran_hesaplanmis_olcege_duser(self):
        assert _bkz(3840, 2160) == (2576, 1449)

    def test_cikti_her_zaman_sinirlarin_icinde(self):
        # Fuzz yerine tablo: her çıktı iki sınırı da tutmalı.
        for w, h in ((3840, 2160), (2560, 1600), (2600, 100), (1080, 3840),
                     (5000, 5000), (2577, 1440), (200, 9000)):
            en, boy = _bkz(w, h)
            assert _token_sayisi(en, boy) <= MAX_VISUAL_TOKENS
            assert max(en, boy) <= MAX_LONG_EDGE_PX

    def test_kucultme_asla_buyutmuyor(self):
        for w, h in ((3840, 2160), (2560, 1600), (1080, 3840)):
            en, boy = _bkz(w, h)
            assert en <= w and boy <= h

    def test_sonuc_idempotent(self):
        # İki kez uygulamak bir şey değiştirmemeli; `Frame` değişmezi
        # `model_kare_boyutu(width, height) == (width, height)` buna dayanıyor.
        for w, h in ((3840, 2160), (2560, 1600), (1080, 3840), (2600, 100)):
            kare = _bkz(w, h)
            assert _bkz(*kare) == kare

    def test_dejenere_boyut_oldugu_gibi_doner(self):
        assert _bkz(0, 100) == (0, 100)


class TestDokumanOrnekleri:
    """Referans algoritmanın dokümandaki kendi örnekleri.

    Rakamlar Anthropic vision dokümanının "Coordinates and bounding boxes"
    bölümündeki örnek tablodan; hesaplamanın doğruluğu bu sabitlere bağlı.
    """

    def test_standart_katman_1075x1520(self):
        assert _bkz(1075, 1520, STANDART_EDGE, STANDART_TOKEN) == (924, 1307)

    def test_standart_katman_1920x1080(self):
        # Standart katmanda 1920x1080 küçülür — çalışma notundaki
        # "1568 px / 1.15 MP eşiği" tam olarak bu.
        assert _bkz(1920, 1080, STANDART_EDGE, STANDART_TOKEN) == (1456, 819)

    def test_yuksek_katman_3840x2160(self):
        assert _bkz(3840, 2160) == (2576, 1449)

    def test_yuksek_katman_1920x1080_degismez(self):
        assert _bkz(1920, 1080, 2576, 4784) == (1920, 1080)


class TestNoktaCevirisi:
    def test_kucultme_yoksa_aynen_doner(self):
        assert model_noktasini_buyut(100, 200, 1920, 1080) == (100, 200)
        assert gercek_noktayi_kucult(100, 200, 1920, 1080) == (100, 200)

    def test_kucultulmus_karede_buyutulur(self):
        # 2560x1600 -> 2420x1512 (oran 1.05785...). Merkez iki yönde de
        # orta kalmalı: (1210, 756) tam merkez.
        assert model_noktasini_buyut(1210, 756, 2560, 1600) == (1280, 800)

    def test_son_model_pikseli_son_gercek_piksele(self):
        assert model_noktasini_buyut(2419, 1511, 2560, 1600) == (2559, 1599)

    def test_gidis_donus_model_uzayinda_kimildamaz(self):
        # Model→gerçek→model aynı noktaya dönmeli: ajanın gördüğü kare ile
        # tıkladığı piksel arasındaki fark burada kapanıyor.
        for w, h in ((2560, 1600), (3840, 1080), (3840, 2160), (1080, 3840)):
            en, boy = _bkz(w, h)
            for x in (0, 1, en // 3, en // 2, en - 1):
                for y in (0, 1, boy // 3, boy // 2, boy - 1):
                    gx, gy = model_noktasini_buyut(x, y, w, h)
                    assert gercek_noktayi_kucult(gx, gy, w, h) == (x, y)


class TestDisplayCevirisi:
    def test_1080p_tam_1_1(self):
        d = Display(0, 0, 0, 1920, 1080, True)
        assert d.to_virtual(100, 200) == (100, 200)
        assert d.from_virtual(100, 200) == (100, 200)

    def test_kucultme_gerektiren_ekranda_tiklama_dogru_piksele(self):
        # Model 2420x1512 kare görüyor, biz 2560x1600 ekrana tıklıyoruz.
        d = Display(0, 0, 0, 2560, 1600, True)
        assert d.needs_downscale
        assert d.to_virtual(1210, 756) == (1280, 800)

    def test_ofset_kucultmeden_sonra_ekleniyor(self):
        d = Display(1, 1920, 0, 2560, 1600, False)
        assert d.to_virtual(1210, 756) == (3200, 800)

    def test_from_virtual_tersi(self):
        d = Display(0, 0, 0, 2560, 1600, True)
        assert d.from_virtual(1280, 800) == (1210, 756)
        assert d.from_virtual(*d.to_virtual(700, 900)) == (700, 900)

    def test_sinir_disi_hala_reddediliyor(self):
        # Model uzayında geçerli ama fiziksel olarak dışarı taşan bir nokta.
        d = Display(0, 0, 0, 2560, 1600, True)
        with pytest.raises(ValueError, match="outside"):
            d.to_virtual(2500, 1511)

    def test_sinir_disi_karari_fiziksel_noktada_veriliyor(self):
        # 2560x1600'de model uzayının son sütunu (2419) fiziksel 2559'a
        # gidiyor; kabul edilmeli. Ham karşılaştırma yapılsaydı bu nokta
        # "içeride" ama komşusu "dışarıda" gibi tutarsız olurdu.
        d = Display(0, 0, 0, 2560, 1600, True)
        assert d.to_virtual(2419, 1511) == (2559, 1599)


class TestDescribe:
    def test_1080p_sade_yaziliyor(self):
        m = DisplayMap([Display(0, 0, 0, 1920, 1080, True)])
        assert m.describe() == "  0: 1920x1080 (primary)"

    def test_kucultme_gereken_ekranda_kare_boyutu_da_yaziliyor(self):
        # Model monitörün 2560x1600 olduğunu okuyup 2420x1512 kare görürse
        # hangi uzayda konuştuğunu bilemez; cümle bunu söylüyor.
        m = DisplayMap([Display(0, 0, 0, 2560, 1600, True)])
        assert m.describe() == "  0: 2560x1600 (primary), shown as 2420x1512"


class TestFrame:
    def test_sigan_kare_kucultulmuyor(self):
        f = Frame.from_capture(0, Image.new("RGB", (1920, 1080)))
        assert (f.width, f.height) == (1920, 1080)
        assert f.model_gorsel() is f.image  # kopya yok

    def test_sigmayan_kare_model_uzayinda(self):
        f = Frame.from_capture(0, Image.new("RGB", (2560, 1600)))
        assert (f.width, f.height) == (2420, 1512)
        assert f.model_gorsel().size == (2420, 1512)

    def test_gonderilen_kare_her_zaman_sinirin_icinde(self):
        f = Frame.from_capture(0, Image.new("RGB", (3840, 2160)))
        gorsel = f.model_gorsel()
        assert (gorsel.width, gorsel.height) == (f.width, f.height)
        assert _token_sayisi(f.width, f.height) <= MAX_VISUAL_TOKENS

    def test_encode_model_uzayini_gonderiyor(self):
        f = Frame.from_capture(0, Image.new("RGB", (2560, 1600)))
        data, mime = f.encode()
        assert mime == "image/webp"
        assert Image.open(io.BytesIO(data)).size == (2420, 1512)

    def test_png_fiziksel_kaliyor(self):
        # PNG modele gitmiyor, Berkay bakıyor; küçültülmüş önizleme okunmaz.
        f = Frame.from_capture(0, Image.new("RGB", (2560, 1600)))
        assert f.to_png()[:8] == b"\x89PNG\r\n\x1a\n"
        assert Image.open(io.BytesIO(f.to_png())).size == (2560, 1600)

    def test_crop_model_uzayinda(self):
        # Zoom bölgesi modelin gördüğü kareden seçiliyor, fizikselden değil.
        # Fiziksel (1260..1300, 780..820) işaretli; 2420/2560 ölçeğinde model
        # uzayında o kare (1191..1229, 737..775) demek. Model bölgesi onu
        # içeriyor; aynı sayılar fiziksel kareden kırpılsa beyaz çıkardı —
        # iki sonucun farkı testin ölçtüğü şey.
        gorsel = Image.new("RGB", (2560, 1600), (255, 255, 255))
        gorsel.paste((255, 0, 0), (1260, 780, 1300, 820))
        f = Frame.from_capture(0, gorsel)

        kirpik = f.crop((1200, 746, 1220, 766))
        assert kirpik.size == (20, 20)
        assert kirpik.getpixel((10, 10)) == (255, 0, 0)
        assert gorsel.crop((1200, 746, 1220, 766)).getpixel((10, 10)) == (
            255, 255, 255
        )

    def test_crop_model_sinirinin_disinda_reddediliyor(self):
        f = Frame.from_capture(0, Image.new("RGB", (2560, 1600)))
        with pytest.raises(ValueError):
            f.crop((0, 0, 2420, 1513))


class _SahtePencere:
    def __init__(self, hwnd=7, x=100, y=200, en=2600, boy=1600):
        self.hwnd, self.x, self.y, self.en, self.boy = hwnd, x, y, en, boy
        self.baslik, self.sinif = "pencere", "S"


class _SahteCalisma:
    """Yan masanın yerine geçen en küçük şey."""

    def __init__(self, pencere):
        self._pencere = pencere

    def pencereler(self):
        return [self._pencere]

    def yakala(self, hwnd, **_):
        return Frame.from_capture(-1, Image.new("RGB", (self._pencere.en,
                                                         self._pencere.boy)))


class _SahteGirdi:
    """Tıklamayı kaydediyor, hiçbir ileti göndermiyor."""

    def __init__(self):
        self.tiklamalar: list[tuple[int, int]] = []
        self.imlec = type("I", (), {"x": 0, "y": 0})()
        self.iz: list[tuple[int, int]] = []
        self.son_tik = False

    def tikla(self, hwnd, x, y, sag=False, cift=False):
        self.tiklamalar.append((x, y))

    def kaydir(self, hwnd, x, y, adim):
        self.tiklamalar.append((x, y))

    def yaz(self, metin, hwnd=None):
        pass

    def tus(self, ad, hwnd=None):
        pass


class TestYanMasaTiklamasi:
    """Yan masadaki pencere karesi de küçültülebilir.

    2600x1600 bir pencere 2576 px kenarını aşıyor; kare 2457x1512 gidiyor.
    Model pencereye göre koordinat veriyor ve o koordinatlar **gönderilen**
    karenin uzayında — tıklama fiziksel piksele büyütülmeden yapılırsa
    her tıklama biraz kayar.
    """

    def _d(self, monkeypatch, pencere):
        from backend.agent import dispatch as mod

        monkeypatch.setattr(mod, "pencere_bilgisi", lambda hwnd: pencere)
        d = mod.Dispatcher.__new__(mod.Dispatcher)
        d.side = _SahteCalisma(pencere)
        d.side_input = _SahteGirdi()
        d.last_side_hwnd = 0
        return d

    def test_kucultulmus_pencerede_tiklama_buyutuluyor(self, monkeypatch):
        pencere = _SahtePencere(en=2600, boy=1600)
        d = self._d(monkeypatch, pencere)
        # Model 2457x1512 kare görüyor; merkez (1210, 756) fiziksel
        # (1280, 800), pencere ofseti (100, 200) ile (1380, 1000).
        d._do_side_act({"action": "click", "coordinate": [1210, 756], "hwnd": 7})
        assert d.side_input.tiklamalar == [(1380, 1000)]

    def test_sigan_pencerede_tiklama_aynen(self, monkeypatch):
        pencere = _SahtePencere(en=1920, boy=1080)
        d = self._d(monkeypatch, pencere)
        d._do_side_act({"action": "click", "coordinate": [500, 300], "hwnd": 7})
        assert d.side_input.tiklamalar == [(600, 500)]

    def test_koordinatsiz_tiklama_hata(self, monkeypatch):
        from backend.agent.dispatch import ToolError

        d = self._d(monkeypatch, _SahtePencere())
        with pytest.raises(ToolError, match="coordinate"):
            d._do_side_act({"action": "click", "hwnd": 7})


class TestTekKaynak:
    """Ölçek matematiğinin ikinci bir kopyası yok.

    Bu görevin en kolay yanlış çözümü aynı ölçeği iki yere yazmaktı; iki
    kopya zamanla ayrışır ve ayrıştıkları gün tıklama yine kayar. Testler
    bunu kaynakta tutuyor: boyutlandırma tek dosyada, sınır tek sabitte.
    """

    @staticmethod
    def _kaynaklar():
        from pathlib import Path

        kok = Path(__file__).resolve().parent.parent
        return kok, [p for p in (kok / "backend").rglob("*.py")]

    def test_resize_tek_yerde(self):
        # Yeniden örnekleme yalnızca `capture.Frame.model_gorsel` içinde.
        kok, dosyalar = self._kaynaklar()
        yerler = [
            p.relative_to(kok).as_posix()
            for p in dosyalar
            if ".resize(" in p.read_text(encoding="utf-8")
        ]
        assert yerler == ["backend/computer/capture.py"]

    def test_kenar_siniri_tek_literal(self):
        # `2576` bir yorumda geçebilir; sayı olarak yalnızca sabitte olmalı.
        import tokenize

        kok, dosyalar = self._kaynaklar()
        bulunan = []
        for p in dosyalar:
            with p.open(encoding="utf-8") as f:
                for tok in tokenize.generate_tokens(f.readline):
                    if tok.type == tokenize.NUMBER and tok.string in ("2576", "4784"):
                        bulunan.append(p.relative_to(kok).as_posix())
        assert bulunan == ["backend/computer/displays.py"] * 2