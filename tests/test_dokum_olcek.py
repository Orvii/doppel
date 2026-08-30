"""Uzun bir turdan sonra dökümde yukarı kaydırınca donma.

Şikâyet: "uzun bir turdan sonra yukarıdaki mesajları okumak için
kaydırınca arayüz donuyor." Önce ölçüldü, sonra düzeltildi.

## Ölçüm — düzeltmeden önce

`Akis`e satır ekleyip her satırda `heightForWidth` sormak (uygulamada
`CommandBar._fit_reply` tam olarak bunu yapıyor):

    n=  20   ekleme 169 ms   satır başı  8.5 ms   hFW  1.9 ms
    n= 200   ekleme 1123 ms  satır başı  5.6 ms   hFW  7.0 ms
    n=1000   ekleme 22919 ms satır başı 22.9 ms   hFW 39.1 ms

Ve asıl şikâyet, tekerlek adımı başına düşen süre:

    n=  20    0.33 ms/adım
    n= 200    2.71 ms/adım
    n=1000   32.99 ms/adım      ← iki kare; donma olarak görülüyor

## Nedenin hangisi olduğu

Üç şüphe vardı; ölçüm ikisini doğruladı, birini çürüttü.

**Kaydırma maliyeti çocuk widget sayısından geliyor, içerik boyundan
değil.** Aynı 22000 pikselde:

    1000 çocuk            81.3 ms/adım
      20 çocuk (dolgu)     3.9 ms/adım
    1000 çocuk, 950 gizli 17.9 ms/adım

Yani `Akis`te satır sayısının üst sınırının olmaması **asıl sebep**.
`heightForWidth`in O(n) olması ikinci sebep: `_fit_reply` her satırda
sorduğu için satır eklemek kareselleşiyordu.

**Saat abonesi sızıntısı yok** — bu şüphe çürüdü. 500 satır eklendikten
sonra abone 500 görünüyor ama giriş animasyonu bitince 1.2 saniyede
sıfıra iniyor. (Budanan satırlar ayrı bir konu; aşağıda.)

## Düzeltme

1. `NotSatiri.heightForWidth` genişlik başına önbellekleniyor (0.13 ms
   → ~0). Metin kurulduktan sonra değişmiyor.
2. `Akis.heightForWidth` genişlik başına önbellekleniyor; düzen
   isteğinde ve akan metin uzadığında geçersiz kılınıyor.
3. `Akis.EN_COK_SATIR` = 240. Aşan en eski satırlar düşüyor.
4. Budanan satır saatten elle düşürülüyor: hiç görünmemiş bir satır
   `setParent(None)` ile gizlenme olayı almıyordu ve abone kalıyordu —
   600 satır sonrası 240 satırlık dökümde 600 abone ölçtüm, ve
   `Clock.subscribe` her abonelikte listeyi baştan taradığı için bu tek
   başına kareseldi.

## Ölçüm — düzeltmeden sonra

    n=  20   ekleme   45 ms  satır başı 2.3 ms   hFW 0.002 ms
    n= 200   ekleme  352 ms  satır başı 1.8 ms   hFW 0.002 ms
    n=1000   ekleme 2810 ms  satır başı 2.8 ms   hFW 0.002 ms

    kaydırma:  n=20  0.57 ms/adım
               n=200 0.98 ms/adım
               n=1000 7.03 ms/adım   ← bir karenin altında

Satır başı süre artık n ile büyümüyor: kareselden doğrusala indi.

## Buradaki testler süre ölçmüyor

Süreye bakan bir test, yüklü bir makinede rastgele kırılır. Bunun
yerine süreyi yaratan **sayılar** ölçülüyor: kaç çocuk kalıyor, kaç
çocuk ölçülüyor, kaç abone duruyor. Rakamlar yukarıda, güvence burada.
"""

from __future__ import annotations

import pytest


@pytest.fixture()
def t():
    from app import fluent

    return fluent.tokens()


@pytest.fixture()
def akis(qt_app, t):
    from app.stream import Akis

    w = Akis(t)
    yield w
    w.setParent(None)
    w.deleteLater()


def _doldur(akis, adet: int) -> None:
    for i in range(adet):
        if i % 5 == 4:
            akis.add_note(f"dikkat {i} " * 6, "kabuk")
        else:
            akis.add_step("run_shell", f"Step {i}", "detay")


class TestSatirTavani:
    def test_tavani_asmiyor(self, akis):
        from app.stream import Akis

        _doldur(akis, Akis.EN_COK_SATIR * 3)
        assert akis._kutu.count() == Akis.EN_COK_SATIR

    def test_tavanin_altinda_hicbir_sey_dusmuyor(self, akis):
        from app.stream import Akis

        _doldur(akis, Akis.EN_COK_SATIR - 1)
        assert akis._kutu.count() == Akis.EN_COK_SATIR - 1

    def test_dusen_en_eski_satir(self, akis):
        from app.stream import Akis

        akis.add_step("run_shell", "ILK", "detay")
        _doldur(akis, Akis.EN_COK_SATIR + 5)
        basliklar = [
            akis._kutu.itemAt(i).widget()._baslik
            for i in range(akis._kutu.count())
            if hasattr(akis._kutu.itemAt(i).widget(), "_baslik")
        ]
        assert "ILK" not in basliklar

    def test_budanan_satir_saatten_dusuyor(self, akis):
        from app.motion import clock
        from app.stream import Akis

        clock()._aboneler.clear()
        _doldur(akis, Akis.EN_COK_SATIR * 2)
        # Giriş animasyonu her satırı abone ediyor; budanan satırlar
        # abone kalsaydı sayı eklenen satır sayısına yakın olurdu.
        assert len(clock()._aboneler) <= Akis.EN_COK_SATIR

    def test_budanan_akan_metin_unutuluyor(self, akis):
        # Canlı anlatım budanırsa `_son_metin` ona işaret etmeye devam
        # edemez: silinmiş bir Qt nesnesine dokunmak süreci düşürür.
        from app.stream import Akis

        akis.stream("merhaba")
        _doldur(akis, Akis.EN_COK_SATIR + 2)
        assert akis._son_metin is None
        akis.stream("yeniden")  # patlamamalı
        assert akis._son_metin is not None

    def test_budanan_adim_unutuluyor(self, akis):
        from app.stream import Akis

        _doldur(akis, Akis.EN_COK_SATIR + 2)
        # `_son_adim` hâlâ dökümde duran bir satır olmalı.
        if akis._son_adim is not None:
            duran = [akis._kutu.itemAt(i).widget()
                     for i in range(akis._kutu.count())]
            assert akis._son_adim in duran


class TestYukseklikOnbellegi:
    def test_ayni_genislik_cocuklari_tekrar_olcmuyor(self, akis, monkeypatch):
        from app.stream import AdimSatiri

        _doldur(akis, 30)
        sayac = {"n": 0}
        gercek = AdimSatiri.sizeHint

        def sayan(self):
            sayac["n"] += 1
            return gercek(self)

        monkeypatch.setattr(AdimSatiri, "sizeHint", sayan)
        akis.heightForWidth(360)
        ilk = sayac["n"]
        assert ilk > 0
        for _ in range(10):
            akis.heightForWidth(360)
        assert sayac["n"] == ilk

    def test_satir_eklenince_gecersiz(self, akis):
        _doldur(akis, 10)
        once = akis.heightForWidth(360)
        akis.add_step("run_shell", "bir daha", "detay")
        assert akis.heightForWidth(360) > once

    def test_akan_metin_uzayinca_gecersiz(self, akis):
        akis.stream("kısa")
        once = akis.heightForWidth(360)
        akis.stream("uzun bir cümle daha, sarması için yeterince. " * 8)
        assert akis.heightForWidth(360) > once

    def test_temizleyince_sifir(self, akis):
        _doldur(akis, 10)
        assert akis.heightForWidth(360) > 0
        akis.clear()
        assert akis.heightForWidth(360) == 0

    def test_genislik_basina_ayri(self, akis):
        akis.add_note("uzunca bir not, sarması gerekiyor ki fark çıksın. " * 4)
        assert akis.heightForWidth(200) > akis.heightForWidth(600)


class TestNotSatiriOnbellegi:
    def _not(self, t):
        from app.stream import NotSatiri

        return NotSatiri(t, "sarması gereken uzunca bir not. " * 4, "kabuk")

    def test_ayni_genislik_yeniden_olcmuyor(self, qt_app, t, monkeypatch):
        import app.stream as stream

        satir = self._not(t)
        satir.heightForWidth(360)
        sayac = {"n": 0}
        gercek = stream.QFontMetrics

        def sayan(*a, **k):
            sayac["n"] += 1
            return gercek(*a, **k)

        monkeypatch.setattr(stream, "QFontMetrics", sayan)
        for _ in range(20):
            satir.heightForWidth(360)
        assert sayac["n"] == 0
        satir.deleteLater()

    def test_onbellek_boyu_degistirmiyor(self, qt_app, t):
        satir = self._not(t)
        boylar = {satir.heightForWidth(g) for g in (200, 360, 600)}
        for _ in range(3):
            assert {satir.heightForWidth(g) for g in (200, 360, 600)} == boylar
        satir.deleteLater()


class TestGorunusDegismiyor:
    """Hız için ödenen bedel görünüş olmamalı."""

    def test_giris_animasyonu_duruyor(self, akis):
        from app.stream import AdimSatiri

        akis.add_step("run_shell", "Step", "detay")
        satir = akis._kutu.itemAt(0).widget()
        assert isinstance(satir, AdimSatiri)
        assert satir._giris is not None

    def test_satir_yukseklikleri_ayni(self, qt_app, t):
        # Önbellek, ölçünün kendisini değiştirmemeli.
        from app.stream import NotSatiri, ROW_H

        satir = NotSatiri(t, "tek satırlık kısa not")
        assert satir.heightForWidth(360) >= ROW_H + 6
        satir.deleteLater()

    def test_cizilebiliyor(self, qt_app, t):
        from PySide6.QtGui import QImage
        from app.stream import Akis

        w = Akis(t)
        _doldur(w, 12)
        w.resize(360, w.heightForWidth(360))
        w.render(QImage(w.size(), QImage.Format.Format_ARGB32))
        w.setParent(None)
        w.deleteLater()


class TestKaydirmaTakibi:
    """`TAKIP_PAYI` davranışı budamadan sonra da duruyor."""

    @pytest.fixture()
    def bar(self, qt_app, t):
        from app.commandbar import CommandBar

        w = CommandBar(t)
        w.show()
        qt_app.processEvents()
        yield w
        w.close()
        w.deleteLater()

    def test_yukari_kaydirinca_orada_kaliyor(self, bar, qt_app):
        for i in range(60):
            bar.add_step("screenshot", "Looking at the screen", f"adım {i}")
        qt_app.processEvents()
        cubuk = bar._reply_scroll.verticalScrollBar()
        assert cubuk.maximum() > 0
        cubuk.setValue(0)
        bar.add_step("screenshot", "Looking at the screen", "yeni")
        qt_app.processEvents()
        assert cubuk.value() == 0

    def test_sondaysan_takip_ediyor(self, bar, qt_app):
        for i in range(60):
            bar.add_step("screenshot", "Looking at the screen", f"adım {i}")
        qt_app.processEvents()
        cubuk = bar._reply_scroll.verticalScrollBar()
        cubuk.setValue(cubuk.maximum())
        bar.add_step("screenshot", "Looking at the screen", "yeni")
        qt_app.processEvents()
        assert cubuk.value() == cubuk.maximum()
