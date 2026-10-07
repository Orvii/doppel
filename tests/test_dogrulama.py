"""Eylemden sonra doğrulama — "yaptım" iddiasının gerçek karşılığı.

Sorun somut: tıklama ve klavye işleyicileri koşulsuz "OK" dönüyor ve
döngü o "OK"u olduğu gibi modele taşıyordu. Modelin "tıkladım" sözüne
güvenmek bileşik hata üretiyor — tutmayan tıklamanın ardından gelen yazı
yanlış pencereye gidiyor. Artık döngü her eylemin öncesinde ve sonrasında
ön plan penceresini ve odak denetimini okuyup karşılaştırıyor; sonuç adım
kaydına üç değerden biriyle işleniyor: `dogrulandi` (okunabilen bir şey
gerçekten değişti), `varsayildi` (değişiklik görünmedi),
`dogrulanamadi` (okuma düştü).

Bu dosyadaki testler **gerçek Windows API'sine dokunmuyor**: klavye ve
fare sahteleri SendInput'a hiç inmiyor, `_durum_izi` saf mantık olarak
ayrı test ediliyor, döngü tarafı ise sahte bir iz kaynağıyla koşuyor.
Gerçek UIA okuması ayrı bir doğrulama işi ve burada iddia edilmiyor.
"""

from __future__ import annotations

import pytest

#: Sahte izlerde kullanılan tam-okunabilir hâller.
TAM_A = {"baslik": "Notepad", "surec": "notepad.exe",
         "odak": ("Edit", "Metin", ""), "tamam": True}
TAM_B = {"baslik": "Notepad", "surec": "notepad.exe",
         "odak": ("Edit", "Metin", "merhaba"), "tamam": True}
TAM_PENCERE = {"baslik": "Hesap Makinesi", "surec": "calc.exe",
               "odak": ("Edit", "Metin", ""), "tamam": True}
EKSIK = {"baslik": "Notepad", "surec": "notepad.exe",
         "odak": None, "tamam": False}
BOS = {"baslik": "", "surec": "", "odak": None, "tamam": False}


class SahteIz:
    """`_durum_izi`nin yerine geçen sıralı sahte.

    Her çağrı sıradaki izi verir; liste bitince son iz tekrarlanır —
    böylece "iki okuma da aynı" senaryosu tek elemanla kurulur.
    """

    def __init__(self, izler):
        self.izler = list(izler)
        self.cagri = 0

    def __call__(self):
        iz = self.izler[min(self.cagri, len(self.izler) - 1)]
        self.cagri += 1
        return iz


class SahteKill:
    def reset(self):
        pass

    def check(self):
        pass


class TestDogrulamaSonucu:
    """Saf mantık: iz çiftinden karar.

    Kural tek cümleyle: **doğrulanamayan şey varsayılmış sayılır,
    doğrulanmış değil.** Buradaki her test o cümlenin bir kenarını tutuyor.
    """

    def _karar(self, once, sonra):
        from backend.agent.loop import _dogrulama_sonucu

        return _dogrulama_sonucu(once, sonra)

    def test_odak_degisti_dogrulandi(self):
        durum, ayrinti = self._karar(TAM_A, TAM_B)
        assert durum == "dogrulandi"
        assert "'merhaba'" in ayrinti

    def test_pencere_degisti_dogrulandi(self):
        durum, ayrinti = self._karar(TAM_A, TAM_PENCERE)
        assert durum == "dogrulandi"
        assert "Hesap Makinesi" in ayrinti

    def test_hicbir_sey_degismedi_varsayildi(self):
        durum, ayrinti = self._karar(TAM_A, TAM_A)
        assert durum == "varsayildi"
        assert "no visible change" in ayrinti

    def test_okuma_dustu_dogrulanamadi(self):
        durum, _ = self._karar(None, TAM_A)
        assert durum == "dogrulanamadi"
        durum, _ = self._karar(TAM_A, None)
        assert durum == "dogrulanamadi"

    def test_hicbir_sey_okunamadi_dogrulanamadi(self):
        # Masaüstünün kendisi odakta: pencere de odak da yok. "Kısmen
        # okundu" demek bile fazla iddia olurdu.
        durum, ayrinti = self._karar(BOS, BOS)
        assert durum == "dogrulanamadi"
        assert "nothing" in ayrinti

    def test_odak_okunamadi_varsayildi(self):
        # Pencere okundu, odak okunamadı: karşılaştırmanın bir tarafı kör.
        # Değişiklik yoksa bu bir varsayım — doğrulama değil.
        durum, ayrinti = self._karar(EKSIK, EKSIK)
        assert durum == "varsayildi"
        assert "in part" in ayrinti

    def test_yarim_okuma_degisiklik_sayilmaz(self):
        # Odak okunamayan taraf ile okunabilir taraf arasındaki fark bir
        # **okuma hatası**, değişiklik değil. Bunu "dogrulandi" saymak
        # tam da uydurma olurdu.
        durum, _ = self._karar(EKSIK, TAM_A)
        assert durum != "dogrulandi"

    def test_yarim_okumada_pencere_farki_yine_kanittir(self):
        # Başlık/süreç gerçekten değiştiyse bu gözlenmiş bir kanıttır;
        # odak okunamıyor olması onu geçersiz kılmaz.
        durum, ayrinti = self._karar(EKSIK, TAM_PENCERE)
        assert durum == "dogrulandi"
        assert "Hesap Makinesi" in ayrinti


class TestDogrulamaNotu:
    """Şerh metinleri. İngilizce — modele gidiyor ve sızması serbest."""

    def test_dogrulandi_notu_iddia_degil_gozlem_der(self):
        from backend.agent.loop import _dogrulama_notu

        not_ = _dogrulama_notu("dogrulandi", "focus changed")
        assert "Verified" in not_
        assert "observed change" in not_

    def test_varsayildi_notu_ekran_goruntusu_yonlendirir(self):
        from backend.agent.loop import _dogrulama_notu

        not_ = _dogrulama_notu("varsayildi", "no visible change")
        assert "Not verified" in not_
        assert "screenshot" in not_

    def test_dogrulanamadi_notu_da_uyarir(self):
        from backend.agent.loop import _dogrulama_notu

        not_ = _dogrulama_notu("dogrulanamadi", "read failed")
        assert "Not verified" in not_


class TestDurumIzi:
    """`_durum_izi`nin sözleşmesi — yalnızca dikiş noktaları sahtelenir."""

    def test_tam_okuma(self, monkeypatch):
        from backend.agent import loop

        monkeypatch.setattr(loop.win, "foreground_title", lambda: "Notepad")
        monkeypatch.setattr(loop.win, "foreground_process", lambda: "notepad.exe")
        monkeypatch.setattr(loop.uia, "odak_ozeti", lambda: ("Edit", "x", "y"))
        iz = loop._durum_izi()
        assert iz["tamam"] and iz["baslik"] == "Notepad"
        assert iz["odak"] == ("Edit", "x", "y")

    def test_hata_yutulmaz_none_doner(self, monkeypatch):
        from backend.agent import loop

        def patlat():
            raise OSError("pencere yok")

        monkeypatch.setattr(loop.win, "foreground_title", patlat)
        assert loop._durum_izi() is None

    def test_odak_yoksa_tamam_degil(self, monkeypatch):
        from backend.agent import loop

        monkeypatch.setattr(loop.win, "foreground_title", lambda: "Notepad")
        monkeypatch.setattr(loop.win, "foreground_process", lambda: "n.exe")
        monkeypatch.setattr(loop.uia, "odak_ozeti", lambda: None)
        iz = loop._durum_izi()
        assert iz is not None and not iz["tamam"] and iz["odak"] is None


@pytest.fixture
def sahte_klavye(monkeypatch):
    """SendInput'a inmeyen klavye/fare sahtesi.

    İşleyiciler gerçek; yalnızca `input` modülünün sistem çağrıları
    sahteleniyor — testlerin gerçek girdi göndermesi yasak.
    """

    class SahteKb:
        def __init__(self):
            self.yazilan: list[str] = []
            self.tiklamalar: list[tuple[int, int]] = []
            self.tuslar: list[str] = []

        def type_text(self, metin):
            self.yazilan.append(str(metin))

        def click(self, x, y, button="left", count=1):
            self.tiklamalar.append((int(x), int(y)))

        def move_to(self, x, y):
            pass

        def press(self, combo, repeat=1):
            self.tuslar.append(str(combo))

    from backend.agent import dispatch as dispatch_mod

    kb = SahteKb()
    monkeypatch.setattr(dispatch_mod.kb, "type_text", kb.type_text)
    monkeypatch.setattr(dispatch_mod.kb, "click", kb.click)
    monkeypatch.setattr(dispatch_mod.kb, "move_to", kb.move_to)
    monkeypatch.setattr(dispatch_mod.kb, "press", kb.press)
    return kb


@pytest.fixture
def sahte_agent():
    """Gerçek işleyiciler, sahte girdi: kayıt yolundan geçen bir döngü.

    `screenshot` işleyicisi dışındaki her şey gerçek `dispatch` kodu —
    doğrulamanın eylemin üstüne bindiği yeri test ediyoruz, işleyiciyi
    taklit ederek değil.
    """
    from backend.agent.dispatch import Dispatcher, ToolOutcome
    from backend.agent.loop import Agent, _new_lock
    from backend.computer.displays import Display, DisplayMap
    from backend.safety.killswitch import KillSwitch

    agent = Agent.__new__(Agent)
    agent.messages = []
    agent._pending = []
    agent._pending_lock = _new_lock()
    agent.kill = SahteKill()

    class SahteKayit:
        def eylem(self, *_a, **_k):
            pass

    agent.kayit = SahteKayit()
    agent._oturum_araclari = set()
    agent.dispatcher = Dispatcher(
        DisplayMap([Display(0, 0, 0, 1920, 1080, True)]),
        capture=None, kill=KillSwitch(),
    )
    # Gerçek `screenshot` bir `ScreenCapture` istiyor; görüntü bloğu yerine
    # metin dönmesi bu testlerin ilgilendiği şeyi değiştirmiyor.
    agent.dispatcher._do_screenshot = lambda _p: ToolOutcome(content="[image]")
    return agent


class SahteBlok:
    def __init__(self, ad, girdi):
        self.type = "tool_use"
        self.name = ad
        self.id = f"t_{ad}"
        self.input = girdi
        self.toolset_name = None


class TestDonguDogrulama:
    """`_run_batch` sözleşmesi: eylem araçlarında iki okuma, sonuca damga."""

    def _tek(self, agent, monkeypatch, ad, girdi, izler):
        from backend.agent import loop

        sahte = SahteIz(izler)
        monkeypatch.setattr(loop, "_durum_izi", sahte)
        sonuclar = agent._run_batch([SahteBlok(ad, girdi)], loop.Turn(), {})
        return sonuclar[0], sahte

    def test_degisen_durum_dogrulandi_damgasi_alir(
        self, sahte_agent, sahte_klavye, monkeypatch
    ):
        sonuc, sahte = self._tek(
            sahte_agent, monkeypatch, "type", {"text": "merhaba"},
            [TAM_A, TAM_B],
        )
        assert sahte.cagri == 2, "eylemden önce ve sonra birer okuma"
        assert "Verified" in sonuc["content"]
        assert "Not verified" not in sonuc["content"]

    def test_degismeyen_durum_varsayildi_damgasi_alir(
        self, sahte_agent, sahte_klavye, monkeypatch
    ):
        sonuc, _ = self._tek(
            sahte_agent, monkeypatch, "type", {"text": "merhaba"},
            [TAM_A, TAM_A],
        )
        assert "Not verified" in sonuc["content"]
        assert "screenshot" in sonuc["content"]

    def test_okuma_dustu_dogrulanamadi(
        self, sahte_agent, sahte_klavye, monkeypatch
    ):
        sonuc, sahte = self._tek(
            sahte_agent, monkeypatch, "left_click",
            {"coordinate": [10, 10]}, [None, None],
        )
        assert sahte.cagri == 2
        assert "Not verified" in sonuc["content"]

    def test_bakma_araci_hic_okumaz(self, sahte_agent, monkeypatch):
        # `screenshot`ın doğrulanacak bir iddiası yok; ona fazladan iki
        # okuma binerse her ekran görüntüsü adımı yavaşlar.
        sonuc, sahte = self._tek(
            sahte_agent, monkeypatch, "screenshot", {}, [TAM_A]
        )
        assert sahte.cagri == 0
        assert "Verified" not in sonuc["content"]
        assert "Not verified" not in sonuc["content"]

    def test_verilen_not_uzerine_yazmaz(
        self, sahte_agent, sahte_klavye, monkeypatch
    ):
        # Normal sonuç sapasağlam kalmalı: şerh metnin sonuna eklenir.
        sonuc, _ = self._tek(
            sahte_agent, monkeypatch, "type", {"text": "x"}, [TAM_A, TAM_B],
        )
        assert sonuc["content"].startswith("OK")

    def test_hata_yolu_dogrulanmaz(self, sahte_agent, monkeypatch):
        # Hata zaten modele dönüyor; ikinci bir okuma ve şerh anlamsız.
        from backend.agent import loop
        from backend.agent.dispatch import ToolError

        def patlat(_p):
            raise ToolError("hedef yok")

        sahte_agent.dispatcher._do_type = patlat
        sahte = SahteIz([TAM_A, TAM_B])
        monkeypatch.setattr(loop, "_durum_izi", sahte)
        sonuclar = sahte_agent._run_batch(
            [SahteBlok("type", {"text": "x"})], loop.Turn(), {}
        )
        assert sonuclar[0].get("is_error") is True
        assert sahte.cagri == 1, "yalnızca öncesinde okunmuştu"

    def test_kuru_kosuda_dogrulanmaz(self, sahte_agent, monkeypatch):
        # Kuru koşuda eylem hiç çalışmıyor; "Not verified" şerhi dipsiz
        # bir çelişki olurdu — kuru koşunun kendi notu zaten "olmuş gibi
        # varsay" diyor.
        from backend.agent import loop

        sahte_agent.dispatcher.kuru = True
        sahte = SahteIz([TAM_A, TAM_B])
        monkeypatch.setattr(loop, "_durum_izi", sahte)
        sonuclar = sahte_agent._run_batch(
            [SahteBlok("left_click", {"coordinate": [5, 5]})], loop.Turn(), {}
        )
        assert sahte.cagri == 0, "kuru koşuda hiç okuma yapılmamalı"
        assert "Not verified" not in sonuclar[0]["content"]
        assert "dry run" in sonuclar[0]["content"]

    def test_turn_kancasi_durumu_bildirir(
        self, sahte_agent, sahte_klavye, monkeypatch
    ):
        from backend.agent import loop

        gorulen: list[tuple[str, str]] = []
        monkeypatch.setattr(loop, "_durum_izi", SahteIz([TAM_A, TAM_B]))
        sahte_agent._run_batch(
            [SahteBlok("type", {"text": "x"})],
            loop.Turn(on_dogrulama=lambda n, d: gorulen.append((n, d))),
            {},
        )
        assert gorulen == [("type", "dogrulandi")]

    def test_damga_outcome_uzerinde_kalici(
        self, sahte_agent, sahte_klavye, monkeypatch
    ):
        # Adım kaydı `ToolOutcome` üzerinde: kayıt tüketicileri sonradan
        # bakabilsin diye turluk değil, nesne ömürlü.
        from backend.agent import loop

        monkeypatch.setattr(loop, "_durum_izi", SahteIz([TAM_A, TAM_B]))
        gorulen = []
        sahte_agent._run_batch(
            [SahteBlok("type", {"text": "x"})],
            loop.Turn(on_result=lambda _n, o: gorulen.append(o.dogrulama)),
            {},
        )
        assert gorulen == ["dogrulandi"]


class TestTurAkilDegismedi:
    """Durdurma davranışı: doğrulama turu **kesmez**."""

    def test_tutmayan_eylem_turu_durdurmuyor(
        self, sahte_agent, sahte_klavye, monkeypatch
    ):
        from backend.agent import loop

        monkeypatch.setattr(loop, "_durum_izi", SahteIz([TAM_A, TAM_A]))
        sonuc = sahte_agent._run_batch(
            [SahteBlok("type", {"text": "x"}),
             SahteBlok("screenshot", {})],
            loop.Turn(), {},
        )
        assert len(sonuc) == 2, "varsayılan adım turu kesmemeli"
        assert not any(s.get("is_error") for s in sonuc)


class TestEylemAraclari:
    def test_tikla_ve_yaz_listede(self):
        from backend.agent.loop import EYLEM_ARACLARI

        for ad in ("left_click", "double_click", "type", "key", "scroll"):
            assert ad in EYLEM_ARACLARI

    def test_bakma_araci_listede_degil(self):
        from backend.agent.loop import EYLEM_ARACLARI

        for ad in ("screenshot", "read_ui_tree", "cursor_position", "wait"):
            assert ad not in EYLEM_ARACLARI


class TestGercekYuzeyGercektenCalisiyor:
    """Uçtan uca: gerçek `type` işleyicisi + gerçek döngü kodu.

    Kasten sahte işleyici kullanılmıyor; sahtelenen tek şey `input`
    modülünün SendInput çağrıları. Böylece metnin gerçekten işleyiciden
    geçtiği ve damganın aynı çağrıda oluştuğu kanıtlanıyor.
    """

    def test_yazilan_metin_gercekten_gonderiliyor(
        self, sahte_agent, sahte_klavye, monkeypatch
    ):
        from backend.agent import loop

        monkeypatch.setattr(loop, "_durum_izi", SahteIz([TAM_A, TAM_B]))
        sonuc = sahte_agent._run_batch(
            [SahteBlok("type", {"text": "merhaba"})], loop.Turn(), {}
        )
        assert sahte_klavye.yazilan == ["merhaba"]
        assert "Verified" in sonuc[0]["content"]

    def test_tiklama_gercekten_gonderiliyor(
        self, sahte_agent, sahte_klavye, monkeypatch
    ):
        from backend.agent import loop

        monkeypatch.setattr(loop, "_durum_izi", SahteIz([TAM_A, TAM_A]))
        sonuc = sahte_agent._run_batch(
            [SahteBlok("left_click", {"coordinate": [100, 200]})],
            loop.Turn(), {},
        )
        assert sahte_klavye.tiklamalar == [(100, 200)]
        assert "Not verified" in sonuc[0]["content"]