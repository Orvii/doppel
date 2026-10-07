"""Windows API'ye dokunmadan test edilebilen saf mantık.

Ekranı gerçekten süren kısımlar `scripts/check_phase1.py` ile elle
doğrulanıyor — burada yalnızca koordinat matematiği ve tuş çözümlemesi var,
çünkü ajanın sessizce yanlış yere tıkladığı hatalar hep buradan çıkıyor.
"""

import re

import pytest

from backend.computer.displays import Display, DisplayMap
from backend.computer.input import normalize_absolute, parse_combo


PRIMARY = Display(index=0, left=0, top=0, width=1920, height=1080, primary=True)
SECONDARY = Display(index=1, left=1920, top=0, width=1920, height=1080, primary=False)


class _McpYok:
    """MCP bağlı değilken yönetici böyle davranıyor."""

    @staticmethod
    def tools():
        return []


class TestDisplay:
    def test_primary_koordinati_degismez(self):
        assert PRIMARY.to_virtual(100, 200) == (100, 200)

    def test_ikinci_ekran_ofsetlenir(self):
        assert SECONDARY.to_virtual(100, 200) == (2020, 200)

    def test_gidis_donus(self):
        assert SECONDARY.from_virtual(*SECONDARY.to_virtual(640, 480)) == (640, 480)

    def test_son_piksel_gecerli(self):
        assert SECONDARY.to_virtual(1919, 1079) == (3839, 1079)

    def test_disari_tasan_koordinat_reddedilir(self):
        with pytest.raises(ValueError, match="outside"):
            PRIMARY.to_virtual(1920, 0)

    def test_1080p_kucultme_gerektirmez(self):
        assert not PRIMARY.needs_downscale

    def test_sanal_masaustu_genisligi_siniri_asar(self):
        # Bu, monitör başına yakalama kararının gerekçesi.
        birlesik = Display(0, 0, 0, 3840, 1080, True)
        assert birlesik.needs_downscale


class TestDisplayMap:
    def setup_method(self):
        self.map = DisplayMap([PRIMARY, SECONDARY])

    def test_koordinatin_ekranini_bulur(self):
        assert self.map.locate_virtual(2500, 500) is SECONDARY
        assert self.map.locate_virtual(500, 500) is PRIMARY

    def test_bosluktaki_koordinat_none(self):
        assert self.map.locate_virtual(0, 5000) is None

    def test_olmayan_ekran_anlasilir_hata(self):
        with pytest.raises(IndexError, match="has 2"):
            self.map[7]

    def test_bos_harita_reddedilir(self):
        with pytest.raises(ValueError):
            DisplayMap([])


class TestNormalizeAbsolute:
    RECT = (0, 0, 3840, 1080)

    def test_sol_ust_kose_sifir(self):
        assert normalize_absolute(0, 0, self.RECT) == (0, 0)

    def test_sag_alt_kose_tam_deger(self):
        assert normalize_absolute(3839, 1079, self.RECT) == (65535, 65535)

    def test_orta_nokta(self):
        nx, _ = normalize_absolute(1919, 0, self.RECT)
        assert 32700 < nx < 32800

    def test_negatif_ofsetli_masaustu(self):
        # İkinci monitör solda konumlandırılmışsa sanal masaüstü x<0'dan başlar.
        assert normalize_absolute(-1920, 0, (-1920, 0, 3840, 1080)) == (0, 0)

    def test_sinir_disi_kirpilir(self):
        assert normalize_absolute(99999, 0, self.RECT)[0] == 65535

    def test_dejenere_masaustu_reddedilir(self):
        with pytest.raises(ValueError):
            normalize_absolute(0, 0, (0, 0, 1, 1))


class TestParseCombo:
    def test_tek_tus(self):
        assert parse_combo("Return") == [0x0D]

    def test_degistirici_once(self):
        assert parse_combo("ctrl+s") == [0x11, 0x53]

    def test_uclu_kombinasyon(self):
        assert parse_combo("ctrl+shift+Escape") == [0x11, 0x10, 0x1B]

    def test_fonksiyon_tuslari(self):
        assert parse_combo("F1") == [0x70]
        assert parse_combo("alt+F4") == [0x12, 0x73]

    def test_bosluk_toleransi(self):
        assert parse_combo("ctrl + a") == [0x11, 0x41]

    def test_bilinmeyen_tus_adlandirilir(self):
        with pytest.raises(ValueError, match="hyperspace"):
            parse_combo("ctrl+hyperspace")


class TestTypeText:
    """Toplu gönderim regresyonu.

    İlk sürüm 24 karakteri tek SendInput çağrısında topluyordu ve 55
    karakterlik bir metin hedefe 39 karakter olarak düşüyordu. Zamanlamayı
    test edemeyiz, ama "karakter başına bir çağrı" sözleşmesini edebiliriz.
    """

    def _capture(self, monkeypatch):
        from backend.computer import input as kb

        calls: list[int] = []
        monkeypatch.setattr(kb, "_send", lambda *events: calls.append(len(events)))
        monkeypatch.setattr(kb.time, "sleep", lambda _s: None)
        return kb, calls

    def test_karakter_basina_bir_cagri(self, monkeypatch):
        kb, calls = self._capture(monkeypatch)
        kb.type_text("merhaba")
        assert calls == [2] * len("merhaba")

    def test_turkce_karakterler_tek_kod_birimi(self, monkeypatch):
        kb, calls = self._capture(monkeypatch)
        kb.type_text("ğüşıöçĞÜŞİÖÇ")
        assert len(calls) == 12

    def test_bmp_disi_vekil_cifte_ayrilir(self, monkeypatch):
        kb, calls = self._capture(monkeypatch)
        kb.type_text("a🚀")  # emoji iki UTF-16 kod birimi
        assert len(calls) == 3

    def test_bos_metin_hicbir_sey_gondermez(self, monkeypatch):
        kb, calls = self._capture(monkeypatch)
        kb.type_text("")
        assert calls == []


class TestGate:
    """Güvenlik kapısı. Ajanın kabuk yetkisi olduğu için bu testler kritik."""

    def test_silme_onay_ister(self):
        from backend.safety.gate import classify_shell
        for cmd in [r"Remove-Item -Recurse C:\x", "rm -rf /tmp", "del *.txt"]:
            assert classify_shell(cmd).needs_confirmation, cmd

    def test_kapatma_onay_ister(self):
        from backend.safety.gate import classify_shell
        assert classify_shell("Stop-Computer -Force").needs_confirmation

    def test_indirip_calistirma_onay_ister(self):
        from backend.safety.gate import classify_shell
        assert classify_shell("iwr http://x/y.ps1 | iex").needs_confirmation

    def test_okuma_serbest(self):
        from backend.safety.gate import classify_shell
        for cmd in ["Get-Process", "Get-ChildItem C:/Users", "Get-Date"]:
            assert not classify_shell(cmd).needs_confirmation, cmd

    def test_kart_numarasi_onay_ister(self):
        from backend.safety.gate import classify_typing
        assert classify_typing("4111 1111 1111 1111").needs_confirmation

    def test_sira_disi_metin_serbest(self):
        from backend.safety.gate import classify_typing
        assert not classify_typing("merhaba dünya").needs_confirmation

    def test_banka_penceresi_onay_ister(self):
        from backend.safety.gate import classify_window
        assert classify_window("Garanti BBVA - Ödeme").needs_confirmation

    def test_format_cmdlet_yanlis_alarm_vermez(self):
        """Gerçek bir hatanın regresyonu.

        İlk sürüm `format` arıyordu ve `Format-List` ile eşleşiyordu;
        salt-okunur bir dosya listeleme komutu "diski biçimlendiriyor" diye
        onay istedi. Boş yere uyaran bir kapı görmezden gelinir.
        """
        from backend.safety.gate import classify_shell
        for cmd in [
            "Get-ChildItem C:/Users | Format-List",
            "Get-Process | Format-Table Name, Id",
            "Get-Date | Format-Wide",
        ]:
            assert not classify_shell(cmd).needs_confirmation, cmd

    def test_gercek_bicimlendirme_yakalanir(self):
        from backend.safety.gate import classify_shell
        for cmd in ["format D: /fs:ntfs", "Format-Volume -DriveLetter D", "diskpart"]:
            assert classify_shell(cmd).needs_confirmation, cmd

    def test_stderr_bastirma_yanlis_alarm_vermez(self):
        from backend.safety.gate import classify_shell
        assert not classify_shell("Get-Item x 2>$null").needs_confirmation

    def test_dosyaya_yazma_yakalanir(self):
        from backend.safety.gate import classify_shell
        for cmd in ["Get-Process > out.txt", "echo x >> log.txt", "Set-Content a.txt b"]:
            assert classify_shell(cmd).needs_confirmation, cmd

    def test_gerekce_bos_degil(self):
        # Onay istemi kullanıcıya *neden* sorulduğunu söylemeli.
        from backend.safety.gate import classify_shell
        assert classify_shell("Remove-Item x").reason


class TestKillSwitch:
    def test_tetiklenince_hata_firlatir(self):
        from backend.safety.killswitch import Aborted, KillSwitch
        k = KillSwitch()
        k.check()          # temizken sessiz
        k.trigger()
        with pytest.raises(Aborted):
            k.check()

    def test_reset_temizler(self):
        from backend.safety.killswitch import KillSwitch
        k = KillSwitch()
        k.trigger()
        k.reset()
        k.check()

    def test_geri_cagirma_bir_kez_calisir(self):
        from backend.safety.killswitch import KillSwitch
        calls = []
        k = KillSwitch(on_trigger=lambda: calls.append(1))
        k.trigger()
        k.trigger()
        assert len(calls) == 1


class TestEffort:
    def test_ilk_adim_pahali(self):
        from backend.agent.loop import _effort_for
        assert _effort_for(0, stuck=False) == "high"

    def test_rutin_adim_ucuz(self):
        from backend.agent.loop import _effort_for
        assert _effort_for(3, stuck=False) == "medium"

    def test_hata_sonrasi_pahali(self):
        from backend.agent.loop import _effort_for
        assert _effort_for(7, stuck=True) == "high"


class TestDispatcherGate:
    """Onay kancasının gerçekten eylemi durdurup durdurmadığı.

    Sınıflandırıcının doğru olması yetmez — kapının kapalı olduğunda
    komutun *çalışmadığını* da doğrulamak gerek.
    """

    def _dispatcher(self, approve):
        from backend.agent.dispatch import Dispatcher
        from backend.safety.killswitch import KillSwitch
        return Dispatcher(
            DisplayMap([PRIMARY]), capture=None, kill=KillSwitch(), approve=approve
        )

    def test_red_komutu_calistirmaz(self, monkeypatch):
        import subprocess
        from backend.agent.dispatch import Denied

        ran = []
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: ran.append(a))
        d = self._dispatcher(approve=lambda *_a: False)
        with pytest.raises(Denied):
            d.run("run_shell", {"command": "Remove-Item x"})
        assert ran == []

    def test_onay_komutu_calistirir(self, monkeypatch):
        import subprocess

        class Done:
            returncode, stdout, stderr = 0, "silindi", ""

        monkeypatch.setattr(subprocess, "run", lambda *a, **k: Done())
        d = self._dispatcher(approve=lambda *_a: True)
        outcome = d.run("run_shell", {"command": "Remove-Item x"})
        assert "silindi" in outcome.content

    def test_onay_kancasi_yoksa_varsayilan_red(self, monkeypatch):
        """Kancayı bağlamayı unutan bir çağıran kapıyı sessizce açmamalı."""
        import subprocess
        from backend.agent.dispatch import Denied

        ran = []
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: ran.append(a))
        d = self._dispatcher(approve=None)
        with pytest.raises(Denied):
            d.run("run_shell", {"command": "Remove-Item x"})
        assert ran == []

    def test_zararsiz_komut_onay_istemez(self, monkeypatch):
        import subprocess

        class Done:
            returncode, stdout, stderr = 0, "cikti", ""

        monkeypatch.setattr(subprocess, "run", lambda *a, **k: Done())
        asked = []
        d = self._dispatcher(approve=lambda *a: asked.append(a) or True)
        d.run("run_shell", {"command": "Get-Process | Format-List"})
        assert asked == []

    # --- tıklanan denetimin etiketi ---------------------------------------

    def _tiklamayi_izle(self, monkeypatch, baslik="Notepad"):
        """Fareyi gerçekten oynatmadan tıklamayı ve başlığı sahteler."""
        import backend.agent.dispatch as dispatch_mod
        from backend.computer import input as kb

        monkeypatch.setattr(dispatch_mod.win, "foreground_title", lambda: baslik)
        tiklanan = []
        monkeypatch.setattr(
            kb, "click",
            lambda vx, vy, button="left", count=1: tiklanan.append((vx, vy, button)),
        )
        return tiklanan

    def test_gonder_etiketli_tik_durduruluyor(self, monkeypatch):
        """Etiket "Gönder" ama pencere sıradan. Eskiden kapı bunu görmezdi."""
        import backend.agent.dispatch as dispatch_mod
        from backend.agent.dispatch import Denied
        from backend.workflows.imza import Imza

        tiklanan = self._tiklamayi_izle(monkeypatch)
        monkeypatch.setattr(
            dispatch_mod, "imza_noktada", lambda vx, vy: Imza("ButtonControl", "Gönder")
        )
        asked = []
        d = self._dispatcher(approve=lambda *a: asked.append(a) or False)
        with pytest.raises(Denied):
            d.run("left_click", {"coordinate": [10, 10]})
        assert tiklanan == [], "reddedilen tıklama yine de yapıldı"
        assert asked and "send" in asked[0][2]

    def test_iyi_huylu_etiket_sormuyor(self, monkeypatch):
        import backend.agent.dispatch as dispatch_mod
        from backend.workflows.imza import Imza

        tiklanan = self._tiklamayi_izle(monkeypatch)
        monkeypatch.setattr(
            dispatch_mod, "imza_noktada", lambda vx, vy: Imza("ButtonControl", "Kaydet")
        )
        asked = []
        d = self._dispatcher(approve=lambda *a: asked.append(a) or True)
        d.run("left_click", {"coordinate": [10, 10]})
        assert asked == []
        assert tiklanan == [(10, 10, "left")]

    def test_etiket_okunamayinca_tiklama_sormuyor(self, monkeypatch):
        """Erişim reddi (oyun, tuval): etiketsiz karar kapıyı düşürmemeli.

        Orada her tıklamayı onaya düşürmek onay yorgunluğu üretir; pencere
        başlığı süzgeci o yerlerde yine çalışıyor.
        """
        import backend.agent.dispatch as dispatch_mod

        def patla(_vx, _vy):
            raise RuntimeError("E_ACCESSDENIED")

        tiklanan = self._tiklamayi_izle(monkeypatch)
        monkeypatch.setattr(dispatch_mod, "imza_noktada", patla)
        asked = []
        d = self._dispatcher(approve=lambda *a: asked.append(a) or True)
        d.run("left_click", {"coordinate": [10, 10]})
        assert asked == []
        assert tiklanan == [(10, 10, "left")]

    def test_etiket_okunamasa_da_baslik_yetiyor(self, monkeypatch):
        import backend.agent.dispatch as dispatch_mod
        from backend.agent.dispatch import Denied

        tiklanan = self._tiklamayi_izle(monkeypatch, baslik="Garanti BBVA - Ödeme")
        monkeypatch.setattr(dispatch_mod, "imza_noktada", lambda vx, vy: None)
        d = self._dispatcher(approve=lambda *_a: False)
        with pytest.raises(Denied):
            d.run("left_click", {"coordinate": [10, 10]})
        assert tiklanan == []

    def test_sag_tik_baglam_menusu_durduruluyor(self, monkeypatch):
        """Sağ tık da bir düğmeyi çalıştırabiliyor; süzülen kümeye yeni girdi."""
        import backend.agent.dispatch as dispatch_mod
        from backend.agent.dispatch import Denied
        from backend.workflows.imza import Imza

        tiklanan = self._tiklamayi_izle(monkeypatch)
        monkeypatch.setattr(
            dispatch_mod, "imza_noktada", lambda vx, vy: Imza("MenuItemControl", "Remove")
        )
        d = self._dispatcher(approve=lambda *_a: False)
        with pytest.raises(Denied):
            d.run("right_click", {"coordinate": [10, 10]})
        assert tiklanan == []

    def test_yeni_isleyici_varsayilan_olarak_kapidan_geciyor(self, monkeypatch):
        """Depoya `_do_*` eklenip kapı listesine yazılmazsa eskiden sorgusuz
        geçerdi. Açık liste sayesinde artık varsayılan onay: yeni aracın
        kapısız kaldığını ancak bir şeyi bozunca fark etmek olurdu."""
        import backend.agent.dispatch as dispatch_mod
        from backend.agent.dispatch import Denied, Dispatcher, ToolOutcome

        monkeypatch.setattr(dispatch_mod.win, "foreground_title", lambda: "Notepad")
        monkeypatch.setattr(
            Dispatcher, "_do_gelecek_arac",
            lambda self, payload: ToolOutcome(content="çalıştı"), raising=False,
        )
        d = self._dispatcher(approve=lambda *_a: False)
        with pytest.raises(Denied):
            d.run("gelecek_arac", {})

    def test_office_save_uzerine_yazma_durduruluyor(self, monkeypatch, tmp_path):
        import backend.agent.dispatch as dispatch_mod
        from backend.agent.dispatch import Denied
        from backend.computer import files
        from backend.office.text import TextDocument

        monkeypatch.setattr(dispatch_mod.win, "foreground_title", lambda: "Word")

        kaynak = tmp_path / "belge.docx"
        TextDocument.create(str(kaynak)).save()
        hedef = tmp_path / "rapor.docx"
        files.write(str(hedef), "eski içerik")

        d = self._dispatcher(approve=lambda *_a: False)
        d.office.open("belge", str(kaynak))
        with pytest.raises(Denied):
            d.run("office_save", {"name": "belge", "path": str(hedef)})
        assert hedef.read_bytes() == b"eski i\xc3\xa7erik"


class TestFiles:
    def test_yaz_ve_oku_utf8(self, tmp_path):
        from backend.computer import files
        target = tmp_path / "alt" / "not.txt"
        files.write(str(target), "ğüşıöç ĞÜŞİÖÇ — tamam")
        assert files.read(str(target)) == "ğüşıöç ĞÜŞİÖÇ — tamam"

    def test_klasor_otomatik_olusur(self, tmp_path):
        from backend.computer import files
        files.write(str(tmp_path / "a" / "b" / "c.txt"), "x")
        assert (tmp_path / "a" / "b" / "c.txt").exists()

    def test_ekleme_veri_kaybetmez(self, tmp_path):
        from backend.computer import files
        p = tmp_path / "log.txt"
        files.write(str(p), "bir\n")
        files.write(str(p), "iki\n", append=True)
        assert files.read(str(p)) == "bir\niki\n"

    def test_duzenleme_esssiz_esleme_ister(self, tmp_path):
        from backend.computer import files
        p = tmp_path / "k.py"
        files.write(str(p), "x = 1\ny = 1\n")
        with pytest.raises(files.FileError, match="2 times"):
            files.edit(str(p), "= 1", "= 2")
        # Başarısız düzenleme dosyaya dokunmamalı.
        assert files.read(str(p)) == "x = 1\ny = 1\n"

    def test_duzenleme_bulunamazsa_yazmaz(self, tmp_path):
        from backend.computer import files
        p = tmp_path / "k.py"
        files.write(str(p), "x = 1\n")
        with pytest.raises(files.FileError, match="was not found"):
            files.edit(str(p), "z = 9", "z = 8")
        assert files.read(str(p)) == "x = 1\n"

    def test_duzenleme_calisir(self, tmp_path):
        from backend.computer import files
        p = tmp_path / "k.py"
        files.write(str(p), "x = 1\ny = 2\n")
        files.edit(str(p), "y = 2", "y = 42")
        assert files.read(str(p)) == "x = 1\ny = 42\n"

    def test_olmayan_dosya_anlasilir_hata(self, tmp_path):
        from backend.computer import files
        with pytest.raises(files.FileError, match="does not exist"):
            files.read(str(tmp_path / "yok.txt"))

    def test_hassas_yol_isaretlenir(self):
        from backend.computer import files
        assert files.is_sensitive(files.resolve(r"C:\Windows\System32\drivers\etc\hosts"))
        assert files.is_sensitive(files.resolve("~/.ssh/id_ed25519"))
        assert not files.is_sensitive(files.resolve("~/Desktop/notlar.txt"))


class TestWriteGate:
    def test_yeni_dosya_onay_istemez(self, tmp_path):
        from backend.safety.gate import classify
        v = classify("write_file", {"path": str(tmp_path / "yeni.txt"), "content": "x"})
        assert not v.needs_confirmation

    def test_uzerine_yazma_onay_ister(self, tmp_path):
        from backend.computer import files
        from backend.safety.gate import classify
        p = tmp_path / "var.txt"
        files.write(str(p), "eski")
        v = classify("write_file", {"path": str(p), "content": "yeni"})
        assert v.needs_confirmation
        assert "var.txt" in v.reason

    def test_ekleme_onay_istemez(self, tmp_path):
        from backend.computer import files
        from backend.safety.gate import classify
        p = tmp_path / "log.txt"
        files.write(str(p), "eski")
        v = classify("write_file", {"path": str(p), "content": "x", "append": True})
        assert not v.needs_confirmation

    def test_terminale_yazilan_komut_da_suzgecten_gecer(self):
        from backend.safety.gate import classify
        assert classify("terminal_send", {"name": "t", "text": "Remove-Item -Recurse x"}).needs_confirmation
        assert not classify("terminal_send", {"name": "t", "text": "git status"}).needs_confirmation

    def test_tus_gonderme_onay_istemez(self):
        from backend.safety.gate import classify
        assert not classify("terminal_send", {"name": "t", "key": "enter"}).needs_confirmation


class TestClickGate:
    """Tıklanan denetimin etiketi. Kapının yalnızca pencere başlığına
    baktığı sürümde bir "Gönder" ya da "Ödeme Yap" düğmesi sıradan bir
    pencerenin içinde sorgusuz çalışıyordu — tıklamanın kendisi geri
    alınamaz olduğu için bu, kapının en pahalı açığıydı.
    """

    def test_gonder_dugmesi_onay_ister(self):
        from backend.safety.gate import classify
        for etiket in ("Gönder", "GÖNDER", "Send", "Submit", "Paylaş", "Ödeme Yap",
                       "Satın Al", "Sil", "SİL", "Delete", "Kaldır", "Yayınla"):
            v = classify("left_click", {"coordinate": [10, 10]}, label=etiket)
            assert v.needs_confirmation, etiket
            assert v.reason

    def test_kaydet_dugmesi_sormuyor(self):
        """Kaydetme geri alınabilir; onu da sormak sürekli yanlış alarm olurdu.

        Kapı bu dosyada bir kez `format`/`Format-List` yüzünden aynı hataya
        düştü: boş yere uyaran kapı görmezden gelinir.
        """
        from backend.safety.gate import classify
        for etiket in ("Kaydet", "Save", "Save As", "Gönderen", "Silgi",
                       "İptal", "Cancel", "Kaydet ve Kapat"):
            v = classify("left_click", {"coordinate": [10, 10]},
                         window_title="belge.docx - Word", label=etiket)
            assert not v.needs_confirmation, etiket

    def test_etiket_okunamazsa_sormuyor(self):
        # Oyun, tuval, yükseltilmiş pencere: UIA susuyor ve orada her
        # tıklamaya sormak onay yorgunluğu üretir. Başlık süzgeci o
        # yerlerde yine devrede.
        from backend.safety.gate import classify
        assert not classify("left_click", {"coordinate": [10, 10]},
                            window_title="Notepad", label="").needs_confirmation

    def test_baslik_etiketi_ezebiliyor(self):
        # Etiket "Kaydet" olsa bile banka penceresinde sormaya devam: başlık
        # riskli bir bağlam söylüyorsa etiketin iyi huylu olması yetmiyor.
        from backend.safety.gate import classify
        v = classify("left_click", {"coordinate": [10, 10]},
                     window_title="Garanti BBVA - Ödeme", label="Kaydet")
        assert v.needs_confirmation

    def test_sag_ve_orta_tik_da_suzuluyor(self):
        # İkisi de bir düğmeyi, bağlam menüsündeki "Sil"i çalıştırabiliyor.
        from backend.safety.gate import classify
        for ad in ("right_click", "middle_click", "triple_click"):
            assert classify(ad, {"coordinate": [1, 1]},
                            window_title="X - Ödeme").needs_confirmation, ad
            assert classify(ad, {"coordinate": [1, 1]},
                            label="Sil").needs_confirmation, ad
            assert not classify(ad, {"coordinate": [1, 1]},
                                label="Kaydet").needs_confirmation, ad


class TestUnknownToolGate:
    #: Desenlerle süzülen araçlar: SAFE_TOOLS'ta olmamaları doğru, çünkü
    #: kararı payload'a ve pencereye göre değişiyor.
    SUZULEN = {
        "run_shell", "write_file", "edit_file", "terminal_send", "type",
        "key", "left_click", "right_click", "middle_click", "double_click",
        "triple_click", "left_click_drag", "office_save", "side_launch",
        "side_act",
    }

    def test_her_isleyici_kapida_hesapli(self):
        """Her `_do_*` ya süzülüyor ya açık listede olacak.

        Bu, bu görevin kapattığı asıl delik: yeni bir araç eklenip kapıya
        yazılmadığında eskiden sessizce sorgusuz geçiyordu. Artık böyle
        bir aracın testte de görünmesi gerek — süzülecek mi, açık listeye
        mi girecek, kararı vermeden depo yeşile dönmüyor.
        """
        from backend.agent.dispatch import Dispatcher
        from backend.agent.tools import CUSTOM_TOOL_NAMES
        from backend.safety import gate

        isleyiciler = {m[4:] for m in dir(Dispatcher) if m.startswith("_do_")}
        cozulmemis = isleyiciler - self.SUZULEN - gate.SAFE_TOOLS
        assert cozulmemis == set(), cozulmemis
        # Modelin görebildiği araç kümesi de aynı hesabı verecek.
        cozulmemis_ozel = set(CUSTOM_TOOL_NAMES) - self.SUZULEN - gate.SAFE_TOOLS
        assert cozulmemis_ozel == set(), cozulmemis_ozel

    def test_taninmayan_arac_onay_ister(self):
        # Açık liste: `SAFE_TOOLS`'a yazılmayan her ad soruyor. Depoya araç
        # eklenip listeye yazılmadığında yeni araç sessizce kapısız kalmaz.
        from backend.safety.gate import classify
        v = classify("gelecek_arac", {})
        assert v.needs_confirmation
        assert "gelecek_arac" in v.reason

    def test_bilinen_araclar_onay_istemiyor(self):
        # Kendi içinde onay isteyenler dâhil: ikinci soru yorgunluk olurdu.
        from backend.safety.gate import classify
        for ad, girdi in [
            ("wait", {}), ("screenshot", {}), ("read_file", {}),
            ("write_files", {"files": []}), ("skill_write", {}),
            ("side_act", {"action": "click"}), ("workflow_remove", {"name": "x"}),
            ("workflow_run", {"name": "x"}), ("heads_up", {}),
        ]:
            assert not classify(ad, girdi).needs_confirmation, ad


class TestOfficeSaveGate:
    def test_kendi_dosyasina_kaydetme_sormuyor(self):
        # Yolsuz kaydetme, belgenin açıldığı dosyaya gidiyor: kullanıcının
        # ajanı yönlendirdiği dosya. Buna her seferinde sormak — ilk
        # kayıttan sonra dosya artık var olduğu için her kayıtta sormak —
        # ofis akışını onay yorgunluğuna çevirirdi. Riskli olan,
        # kaydetmenin kullanıcının hiç söz etmediği BAŞKA bir dosyaya
        # yönlendirilmesi; süzülen taraf o.
        from backend.safety.gate import classify
        assert not classify("office_save", {"name": "butce"}).needs_confirmation

    def test_yeni_yola_kaydetme_sormuyor(self, tmp_path):
        from backend.safety.gate import classify
        hedef = tmp_path / "yeni.docx"
        assert not classify(
            "office_save", {"name": "butce", "path": str(hedef)}
        ).needs_confirmation

    def test_var_olan_dosyanin_uzerine_kaydetme_onay_ister(self, tmp_path):
        # Başka ada kaydetme üzerine yazıyorsa `write_file`la aynı risk:
        # var olan dosyanın içeriği gider.
        from backend.computer import files
        from backend.safety.gate import classify
        hedef = tmp_path / "rapor.docx"
        files.write(str(hedef), "eski")
        v = classify("office_save", {"name": "butce", "path": str(hedef)})
        assert v.needs_confirmation
        assert "rapor.docx" in v.reason


class TestTerminalKeys:
    def test_bilinen_tuslar_dizi_dondurur(self):
        from backend.computer.terminal import KEYS
        assert KEYS["enter"] == "\r"
        assert KEYS["ctrl+c"] == "\x03"
        assert KEYS["up"] == "\x1b[A"

    def test_bilinmeyen_tus_secenekleri_listeler(self):
        from backend.computer.terminal import TerminalError, TerminalSession
        import pyte
        s = TerminalSession.__new__(TerminalSession)
        with pytest.raises(TerminalError, match="enter"):
            TerminalSession.send_key(s, "hyperspace")


class _SahteSurec:
    """PTY yerine geçen sahte süreç. Gerçek fd, gerçek sinyal yok."""

    def __init__(self):
        self.cagrilar = []
        self.canli = True

    def isalive(self):
        return self.canli

    def read(self, size=4096):
        raise EOFError("bitti")

    def write(self, metin):
        self.cagrilar.append(("write", metin))

    def setwinsize(self, cols, rows):
        self.cagrilar.append(("size", cols, rows))

    def terminate(self, force=False):
        self.cagrilar.append(("terminate", force))

    def stop(self):
        self.cagrilar.append(("stop",))
        self.canli = False


class TestTerminalLinux:
    """Linux portunun saf kısmı — Windows'ta koşuyor, ama hesap platform
    bağımsız: aynı fonksiyonlar Linux'ta aynı girdiyle aynı sonucu verir.
    Buraya dosya sistemi, sinyal ve fd girmez; onları test etmek Linux
    gerektirir ve dürüstçe "doğrulanmadı" diye işaretlendi."""

    def test_kabuk_shell_degiskenini_izler(self):
        from backend.computer.terminal import kabuk_argv
        assert kabuk_argv({"SHELL": "/usr/bin/fish"}, lambda y: True) == ["/usr/bin/fish"]

    def test_kabuk_bayat_shell_yolundan_asar(self):
        # $SHELL artık var olmayabilir; sıradaki adaya düşülmeli.
        from backend.computer.terminal import kabuk_argv
        var = lambda y: y == "/bin/bash"
        assert kabuk_argv({"SHELL": "/usr/bin/yok"}, var) == ["/bin/bash"]

    def test_kabuk_zsh_a_sabitlenmiyor(self):
        # zsh daima /bin/bash'e düşülüyor; zsh hiçbir Linux'ta garanti değil.
        from backend.computer.terminal import kabuk_argv
        var = lambda y: y in ("/bin/sh",)
        assert kabuk_argv({}, var) == ["/bin/sh"]

    def test_kabuk_bulunamazsa_acik_hata(self):
        from backend.computer.terminal import TerminalError, kabuk_argv
        with pytest.raises(TerminalError, match="no usable shell"):
            kabuk_argv({"SHELL": "/yok/1"}, lambda y: False)

    def test_ortam_term_i_sabitler_girdiyi_bozmadan(self):
        from backend.computer.terminal import oturum_ortami
        girdi = {"PATH": "/usr/bin", "TERM": "dumb"}
        yeni = oturum_ortami(girdi)
        assert yeni["TERM"] == "xterm-256color"
        assert yeni["PATH"] == "/usr/bin"
        assert girdi["TERM"] == "dumb"  # çağıranın sözlüğü değişmedi

    def test_pencere_verisi_satir_once_sutun_sonra(self):
        import struct
        from backend.computer.terminal import pencere_verisi
        veri = pencere_verisi(120, 40)
        assert len(veri) == 8  # dört 16 bit alan
        assert struct.unpack("HHHH", veri) == (40, 120, 0, 0)

    def test_acilis_plani_komutu_posix_kurallariyla_boler(self):
        from backend.computer.terminal import acilis_plani
        argv, cwd, ortam = acilis_plani("python -c 'print(1)'", cwd="/tmp",
                                        var_mi=lambda y: True)
        assert argv == ["python", "-c", "print(1)"]
        assert cwd == "/tmp"
        assert ortam["TERM"] == "xterm-256color"

    def test_acilis_plani_bos_komutta_kabuk_acar(self):
        from backend.computer.terminal import acilis_plani
        argv, _, _ = acilis_plani("  ", ortam={"SHELL": "/bin/bash"},
                                  var_mi=lambda y: True)
        assert argv == ["/bin/bash"]

    def test_acilis_plani_bozuk_tirnakta_hata_verir(self):
        from backend.computer.terminal import TerminalError, acilis_plani
        with pytest.raises(TerminalError, match="could not parse"):
            acilis_plani("python 'kapanmamis")

    def test_kapatma_once_yumusak_sinyal(self):
        from backend.computer.terminal import surec_kapat
        sinyaller = []
        sonuc = surec_kapat(lambda: False, sinyaller.append,
                            sinyaller=(15, 9), bekle=lambda s: None)
        assert sonuc is False and sinyaller == [15]

    def test_kapatma_dinlemeyen_sureci_sert_oldurur(self):
        import time
        from backend.computer.terminal import surec_kapat
        sinyaller = []
        sonuc = surec_kapat(lambda: True, sinyaller.append,
                            sinyaller=(15, 9), bekle=lambda s: time.sleep(0.001),
                            sure=0.05)
        assert sonuc is True and sinyaller == [15, 9]

    def test_kapatma_iki_sinyal_arasinda_oleni_bildirir(self):
        from backend.computer.terminal import surec_kapat
        sinyaller = []
        durum = {"kez": 0}

        def sag_mi():
            durum["kez"] += 1
            return durum["kez"] < 2  # ilk yoklamada yaşıyor, sonra öldü

        sonuc = surec_kapat(sag_mi, sinyaller.append, sinyaller=(15, 9),
                            bekle=lambda s: None)
        assert sonuc is False and sinyaller == [15]

    def test_arka_uc_secimi_tek_yerde(self):
        import os
        from backend.computer import terminal as t
        if os.name == "nt":
            assert t.arka_uc_sinifi() is t._WinptyArkaUcu
        else:
            assert t.arka_uc_sinifi() is t._PtyArkaUcu

    def test_ithalat_koruma_yayilari_dogru(self):
        # Dikilen kural: Windows yolu pywinpty'yi, Linux yolu
        # fcntl/termios'u koşullu ithal ediyor; biri diğerinin platformda
        # modülü kırıyor olamaz. Bu test iki platformda da koşar.
        import os
        from backend.computer import terminal as t
        if os.name == "nt":
            assert t.winpty is not None
            assert not hasattr(t, "fcntl")
            assert not hasattr(t, "termios")
        else:
            assert t.winpty is None
            assert hasattr(t, "fcntl") and hasattr(t, "termios")

    def test_winpty_arka_ucu_spawn_argumanlari_aynen_gecirir(self):
        from backend.computer import terminal as t
        kayit = {}

        class SahtePtyProcess:
            @staticmethod
            def spawn(argv, cwd=None, env=None, dimensions=None, backend=None):
                kayit.update(argv=argv, cwd=cwd, dimensions=dimensions,
                             backend=backend)
                return _SahteSurec()

        class SahteWinpty:
            PtyProcess = SahtePtyProcess

            class Backend:
                ConPTY = "conpty-nisani"

        t.winpty_yedek = t.winpty
        t.winpty = SahteWinpty
        try:
            uc = t._WinptyArkaUcu.spawn(None, cwd="D:/x", cols=100, rows=30)
        finally:
            t.winpty = t.winpty_yedek
            del t.winpty_yedek
        assert kayit["argv"] == "powershell.exe -NoLogo -NoProfile"
        assert kayit["cwd"] == "D:/x"
        assert kayit["dimensions"] == (30, 100)  # winpty: (satır, sütun)
        assert kayit["backend"] == "conpty-nisani"
        assert isinstance(uc, t._WinptyArkaUcu)

    def test_winpty_arka_ucu_baslatamazsa_terminal_hatasi(self):
        from backend.computer import terminal as t

        class Patlayan:
            @staticmethod
            def spawn(*a, **k):
                raise OSError("conpty yok")

        class SahteWinpty:
            PtyProcess = Patlayan

            class Backend:
                ConPTY = "x"

        t.winpty_yedek = t.winpty
        t.winpty = SahteWinpty
        try:
            with pytest.raises(t.TerminalError, match="could not start"):
                t._WinptyArkaUcu.spawn("cmd.exe", cwd=None)
        finally:
            t.winpty = t.winpty_yedek
            del t.winpty_yedek

    def test_winpty_arka_ucu_boyutu_satir_once_gonderir(self):
        from backend.computer.terminal import _WinptyArkaUcu
        sahte = _SahteSurec()
        _WinptyArkaUcu(sahte).setwinsize(120, 40)
        assert sahte.cagrilar == [("size", 40, 120)]

    def test_winpty_arka_ucu_kapatmada_zorlar(self):
        from backend.computer.terminal import _WinptyArkaUcu
        sahte = _SahteSurec()
        _WinptyArkaUcu(sahte).stop()
        assert sahte.cagrilar == [("terminate", True)]

    def test_linux_arka_ucu_olmayan_komutu_acilista_reddeder(self):
        # Kontrol fork'tan önce: Windows'ta da koşar, gerçek pty açılmaz.
        from backend.computer.terminal import TerminalError, _PtyArkaUcu
        with pytest.raises(TerminalError, match="not found"):
            _PtyArkaUcu.spawn("kesinlikle-yok-boyle-bir-program-xyz")

    def test_linux_arka_ucu_olmayan_dizini_acilista_reddeder(self):
        import sys
        from backend.computer.terminal import TerminalError, _PtyArkaUcu
        # Windows yolunu POSIX kuralları ters eğik çizgileri yiyor
        # (`shlex.split("C:\\x")` -> "C:x"), o yüzden tırnaklı veriliyor:
        # Linux'ta sys.executable tek jeton, davranış aynı.
        argv = f'"{sys.executable}"'
        with pytest.raises(TerminalError, match="working directory"):
            _PtyArkaUcu.spawn(argv, cwd="/boyle-bir-dizin-yok-xyz")


class TestTerminalSession:
    """Oturumun iskeleti sahte arka uçla — gerçek PTY yok."""

    def _oturum(self):
        import pyte
        from backend.computer.terminal import TerminalSession
        sahte = _SahteSurec()
        ekran = pyte.Screen(80, 24)
        oturum = TerminalSession(name="t", cwd="", process=sahte,
                                 screen=ekran, stream=pyte.Stream(ekran))
        return oturum, sahte, ekran

    def test_resize_hem_pty_ye_hem_ekrana_isler(self):
        oturum, sahte, ekran = self._oturum()
        oturum.resize(100, 30)
        assert sahte.cagrilar == [("size", 100, 30)]
        assert ekran.columns == 100 and ekran.lines == 30

    def test_kapali_oturumda_resize_hata_verir(self):
        from backend.computer.terminal import TerminalError
        oturum, _, _ = self._oturum()
        oturum._closed.set()
        with pytest.raises(TerminalError, match="closed"):
            oturum.resize(100, 30)

    def test_tus_dizisi_arka_uca_yaziliyor(self):
        oturum, sahte, _ = self._oturum()
        oturum.send_key("up")
        oturum.send("merhaba")
        assert sahte.cagrilar == [("write", "\x1b[A"), ("write", "merhaba")]

    def test_kapali_oturuma_gonderim_hata_verir(self):
        from backend.computer.terminal import TerminalError
        oturum, _, _ = self._oturum()
        oturum._closed.set()
        with pytest.raises(TerminalError, match="closed"):
            oturum.send("x")

    def test_olu_surecte_canlilik_yanlis(self):
        oturum, sahte, _ = self._oturum()
        assert oturum.alive
        sahte.canli = False
        assert not oturum.alive

    def test_close_arka_ucu_durdurur(self):
        oturum, sahte, _ = self._oturum()
        oturum.close()
        assert sahte.cagrilar == [("stop",)]
        assert not oturum.alive


class _SahteOturum:
    """Kayıt defteri testleri için: PTY'siz oturum."""

    def __init__(self, canli=True):
        self.canli = canli
        self.kapandi = False

    @property
    def alive(self):
        return self.canli

    def close(self):
        self.kapandi = True


class TestTerminalRegistry:
    """Açık oturumların defteri: aynı isim, sınır, yeniden kullanım."""

    @pytest.fixture(autouse=True)
    def _sahte_acilis(self, monkeypatch):
        from backend.computer import terminal as t
        self.acilanlar = []

        def sahte_open(name, command=None, cwd=None):
            self.acilanlar.append((name, command, cwd))
            return _SahteOturum()

        monkeypatch.setattr(t.TerminalSession, "open", sahte_open)

    def test_acilan_oturum_ismiyle_bulunuyor(self):
        from backend.computer.terminal import TerminalRegistry
        r = TerminalRegistry()
        oturum = r.open("bir", command="python")
        assert r.get("bir") is oturum
        assert r.names() == ["bir"]
        assert self.acilanlar == [("bir", "python", None)]

    def test_ayni_isim_ikinci_kez_acilamaz(self):
        from backend.computer.terminal import TerminalError, TerminalRegistry
        r = TerminalRegistry()
        r.open("bir")
        with pytest.raises(TerminalError, match="already open"):
            r.open("bir")

    def test_olen_oturumun_ismi_yeniden_kullanilabilir(self):
        # Aynı ismi açıkça kapatmadan da ölü oturumun yerine geçilebilir;
        # dispatch bunu bir oturum "kapandı" sandığında istiyor.
        from backend.computer.terminal import TerminalRegistry
        r = TerminalRegistry()
        eski = r.open("bir")
        eski.canli = False
        yeni = r.open("bir")
        assert r.get("bir") is yeni

    def test_olmayan_oturum_acik_hata_verir(self):
        from backend.computer.terminal import TerminalError, TerminalRegistry
        r = TerminalRegistry()
        with pytest.raises(TerminalError, match="There is no session"):
            r.get("yok")

    def test_kapatma_defterden_dusurur(self):
        from backend.computer.terminal import TerminalError, TerminalRegistry
        r = TerminalRegistry()
        oturum = r.open("bir")
        r.close("bir")
        assert oturum.kapandi and r.names() == []
        with pytest.raises(TerminalError, match="no session"):
            r.close("bir")

    def test_sinir_asilinca_olu_oturum_toplanir(self):
        from backend.computer.terminal import TerminalRegistry
        r = TerminalRegistry()
        for i in range(TerminalRegistry.MAX_SESSIONS):
            s = r.open(f"o{i}")
            if i == 0:
                s.canli = False  # biri ölmüş: yer açılmalı
        yeni = r.open("yeni")
        assert yeni in r._sessions.values()
        assert "o0" not in r.names()

    def test_sinir_asilinca_acik_hata(self):
        from backend.computer.terminal import TerminalError, TerminalRegistry
        r = TerminalRegistry()
        for i in range(TerminalRegistry.MAX_SESSIONS):
            r.open(f"o{i}")
        with pytest.raises(TerminalError, match="At most"):
            r.open("fazla")

    def test_close_all_hepsini_kapatir(self):
        from backend.computer.terminal import TerminalRegistry
        r = TerminalRegistry()
        acilanlar = [r.open(f"o{i}") for i in range(3)]
        r.close_all()
        assert all(o.kapandi for o in acilanlar)
        assert r.names() == []


class TestLedger:
    """Gerekçe defteri — bu ofisin ayırt edici parçası."""

    def test_gerekcesiz_degisiklik_reddedilir(self):
        from backend.office.model import Ledger
        with pytest.raises(ValueError, match="no reason given"):
            Ledger().record("A1", None, 5, "")

    def test_bosluk_gerekce_sayilmaz(self):
        from backend.office.model import Ledger
        with pytest.raises(ValueError):
            Ledger().record("A1", None, 5, "   ")

    def test_onceki_deger_saklanir(self):
        from backend.office.model import Ledger
        led = Ledger()
        c = led.record("Sayfa1!A1", "eski", "yeni", "kaynak CSV 3. sütun")
        assert c.before == "eski" and c.after == "yeni"
        assert "CSV" in c.describe()

    def test_kaydedilmemis_sayaci(self):
        from backend.office.model import Ledger
        led = Ledger()
        led.record("A1", None, 1, "x")
        assert led.dirty and led.unsaved_count == 1
        led.mark_saved()
        assert not led.dirty


class TestWorkbook:
    def test_yaz_oku_kaydet(self, tmp_path):
        from backend.office.sheet import Workbook
        wb = Workbook.create(str(tmp_path / "t.xlsx"))
        wb.write("A1", [["Kalem", "Tutar"], ["Kira", 12000]], why="bütçe tablosu kuruluyor")
        wb.save()
        assert (tmp_path / "t.xlsx").exists()
        assert "Kira" in Workbook.open(str(tmp_path / "t.xlsx")).read("A1:B2")

    def test_her_hucre_ayri_kaydedilir(self, tmp_path):
        from backend.office.sheet import Workbook
        wb = Workbook.create(str(tmp_path / "t.xlsx"))
        wb.write("A1", [["a", "b"], ["c", "d"]], why="test")
        assert len(wb.ledger) == 4

    def test_ayni_deger_kayit_uretmez(self, tmp_path):
        from backend.office.sheet import Workbook
        wb = Workbook.create(str(tmp_path / "t.xlsx"))
        wb.write("A1", [["x"]], why="ilk")
        wb.write("A1", [["x"]], why="ikinci")
        assert len(wb.ledger) == 1

    def test_geri_alma_onceki_degeri_koyar(self, tmp_path):
        from backend.office.sheet import Workbook
        wb = Workbook.create(str(tmp_path / "t.xlsx"))
        wb.write("A1", [["ilk"]], why="a")
        wb.write("A1", [["ikinci"]], why="b")
        wb.undo(1)
        assert wb.book.active["A1"].value == "ilk"
        assert len(wb.ledger) == 1

    def test_formul_sonucu_okumada_gorunur(self, tmp_path):
        # Gerileme testi: ajan bir kez formülün sonucunu kafadan toplayıp
        # 21.290 dedi, doğrusu 20.990'dı. Sonuç okumada yazılı olmalı ki
        # tahmin etmeye kalkmasın.
        from backend.office.sheet import Workbook
        wb = Workbook.create(str(tmp_path / "t.xlsx"))
        wb.write("B1", [[12000], [1850], [640], [4200], [2300]], why="kalemler")
        wb.write("B6", [["=SUM(B1:B5)"]], why="toplam")
        out = wb.read("B1:B6")
        assert "20990" in out
        assert "21290" not in out

    def test_hesaplanamayan_formul_uyari_verir(self, tmp_path):
        # Sessizce geçmek, modelin sonucu bildiğini sanmasına yol açar.
        from backend.office import sheet as sheet_mod
        from backend.office.sheet import CalcError, Workbook

        wb = Workbook.create(str(tmp_path / "t.xlsx"))
        wb.write("B5", [["=SUM(B2:B4)"]], why="toplam")

        def patla(*_args, **_kwargs):
            raise CalcError("motor yok")

        original = sheet_mod.evaluate
        sheet_mod.evaluate = patla
        try:
            assert "could not be evaluated" in wb.read("B5")
        finally:
            sheet_mod.evaluate = original

    def test_formul_yoksa_motor_calismaz(self, tmp_path):
        # Hesaplama saniyeler sürüyor; formülsüz tabloda ödenmemeli.
        from backend.office import sheet as sheet_mod
        from backend.office.sheet import Workbook

        wb = Workbook.create(str(tmp_path / "t.xlsx"))
        wb.write("A1", [["metin", 5]], why="veri")
        calls = []
        original = sheet_mod.evaluate
        sheet_mod.evaluate = lambda *a, **k: calls.append(1) or {}
        try:
            wb.read("A1:B1")
        finally:
            sheet_mod.evaluate = original
        assert calls == []

    def test_gecersiz_aralik_ornekle_reddedilir(self, tmp_path):
        from backend.office.sheet import SheetError, Workbook
        wb = Workbook.create(str(tmp_path / "t.xlsx"))
        with pytest.raises(SheetError, match="A1"):
            wb.read("saçmalık")

    def test_olmayan_sayfa_secenekleri_listeler(self, tmp_path):
        from backend.office.sheet import SheetError, Workbook
        wb = Workbook.create(str(tmp_path / "t.xlsx"))
        with pytest.raises(SheetError, match="Sheet1"):
            wb.read("A1", sheet="Yok")


class TestTextDocument:
    def test_ekle_oku_kaydet(self, tmp_path):
        from backend.office.text import TextDocument
        d = TextDocument.create(str(tmp_path / "r.docx"))
        d.append("Ajan Raporu", why="başlık", style="Title")
        d.append("ğüşıöç ĞÜŞİÖÇ", why="Türkçe testi")
        d.save()
        assert "ĞÜŞİÖÇ" in TextDocument.open(str(tmp_path / "r.docx")).read()

    def test_degistirme_geri_alinabilir(self, tmp_path):
        from backend.office.text import TextDocument
        d = TextDocument.create(str(tmp_path / "r.docx"))
        d.append("ilk hali", why="taslak")
        d.replace(0, "yeni hali", why="düzeltme")
        assert "yeni hali" in d.read()
        d.undo(1)
        assert "ilk hali" in d.read()

    def test_olmayan_stil_secenekleri_listeler(self, tmp_path):
        from backend.office.text import TextDocument, TextError
        d = TextDocument.create(str(tmp_path / "r.docx"))
        with pytest.raises(TextError, match="Heading 1"):
            d.append("x", why="y", style="Uydurma Stil")

    def test_olmayan_paragraf_sayi_verir(self, tmp_path):
        from backend.office.text import TextDocument, TextError
        d = TextDocument.create(str(tmp_path / "r.docx"))
        with pytest.raises(TextError, match="the document has 0"):
            d.replace(9, "x", why="y")


class TestOfficeStore:
    def test_kaydedilmemis_belge_kapanmaz(self, tmp_path):
        from backend.office.store import OfficeError, OfficeStore
        st = OfficeStore()
        wb = st.open("b", str(tmp_path / "a.xlsx"))
        wb.write("A1", [["x"]], why="test")
        with pytest.raises(OfficeError, match="unsaved changes"):
            st.close("b")

    def test_discard_ile_kapanir(self, tmp_path):
        from backend.office.store import OfficeStore
        st = OfficeStore()
        st.open("b", str(tmp_path / "a.xlsx")).write("A1", [["x"]], why="test")
        assert "discarded" in st.discard("b")
        assert st.names() == []

    def test_desteklenmeyen_uzanti_yol_gosterir(self, tmp_path):
        from backend.office.store import OfficeError, OfficeStore
        with pytest.raises(OfficeError, match=".xlsx"):
            OfficeStore().open("b", str(tmp_path / "a.pdf"))

    def test_ayni_ad_iki_kez_acilmaz(self, tmp_path):
        from backend.office.store import OfficeError, OfficeStore
        st = OfficeStore()
        st.open("b", str(tmp_path / "a.xlsx"))
        with pytest.raises(OfficeError, match="is already open"):
            st.open("b", str(tmp_path / "c.xlsx"))


class TestSkills:
    """Ajanın kendine yazdığı yetenekler."""

    def _registry(self, tmp_path, reserved=frozenset()):
        from backend.skills.registry import SkillRegistry
        return SkillRegistry(directory=tmp_path / "yetenekler", reserved=reserved)

    IYI = (
        'ARAC = {\n'
        '    "ad": "topla",\n'
        '    "aciklama": "Iki sayiyi toplar.",\n'
        '    "girdi": {"a": {"type": "number"}, "b": {"type": "number"}},\n'
        '}\n'
        'def calistir(girdi, ortam):\n'
        '    return girdi["a"] + girdi["b"]\n'
    )

    def test_yazilan_yetenek_hemen_cagirilabilir(self, tmp_path):
        # Asıl mesele bu: yaz, aynı turda dene, düzelt.
        r = self._registry(tmp_path)
        skill = r.write("topla", self.IYI)
        assert skill.run({"a": 2, "b": 3}, None) == 5
        assert [t["name"] for t in r.tools()] == ["topla"]

    def test_sozdizimi_hatasi_dosya_birakmaz(self, tmp_path):
        from backend.skills.registry import SkillError
        r = self._registry(tmp_path)
        with pytest.raises(SkillError, match="syntax error"):
            r.write("bozuk", "def calistir(:")
        assert not (r.directory / "bozuk.py").exists()

    def test_basarisiz_duzeltme_eskisini_geri_koyar(self, tmp_path):
        # Yarım bir yetenek bırakmak, çalışan yeteneği de kaybettirirdi.
        from backend.skills.registry import SkillError
        r = self._registry(tmp_path)
        r.write("topla", self.IYI)
        with pytest.raises(SkillError):
            r.write("topla", "ARAC = 5\ndef calistir(g, o): return 1")
        assert r.get("topla").run({"a": 1, "b": 1}, None) == 2

    def test_yerlesik_arac_adi_ele_gecirilemez(self, tmp_path):
        from backend.skills.registry import SkillError
        r = self._registry(tmp_path, reserved=frozenset({"run_shell"}))
        kod = self.IYI.replace('"ad": "topla"', '"ad": "run_shell"')
        with pytest.raises(SkillError, match="built-in tool name"):
            r.write("sinsi", kod)

    def test_bozuk_dosya_sessizce_atlanmaz(self, tmp_path):
        r = self._registry(tmp_path)
        r.directory.mkdir(parents=True)
        (r.directory / "yarim.py").write_text("ARAC = {}", encoding="utf-8")
        r.refresh(force=True)
        assert [b.name for b in r.broken] == ["yarim"]
        assert "yarim.py" in r.report()

    def test_disaridan_duzeltilen_dosya_yeniden_yuklenir(self, tmp_path):
        # Berkay dosyayı Not Defteri'nde açıp düzeltebilmeli.
        import time
        r = self._registry(tmp_path)
        r.write("topla", self.IYI)
        time.sleep(0.01)
        (r.directory / "topla.py").write_text(
            self.IYI.replace('girdi["a"] + girdi["b"]', 'girdi["a"] * girdi["b"]'),
            encoding="utf-8",
        )
        assert r.get("topla").run({"a": 3, "b": 4}, None) == 12

    def test_komut_talimata_acilir(self, tmp_path):
        r = self._registry(tmp_path)
        kod = self.IYI + (
            'KOMUT = {"ad": "top", "aciklama": "toplama", "talimat": "Sunlari topla:"}\n'
        )
        r.write("topla", kod)
        assert r.expand("/top 2 ve 3") == "Sunlari topla:\n\n2 ve 3"
        assert r.expand("/top") == "Sunlari topla:"

    def test_bilinmeyen_egik_cizgi_metin_olarak_kalir(self, tmp_path):
        # Aksi hâlde `/mnt/c/...` gibi bir yol yazmak imkânsız olurdu.
        r = self._registry(tmp_path)
        assert r.expand("/olmayan bir sey") is None
        assert r.expand("dosyayi /tmp/x.txt icine yaz") is None


class TestSkillDispatch:
    """Yetenek çağrısı kapıdan ve hata yolundan nasıl geçiyor."""

    def _dispatcher(self, tmp_path, approve=None):
        from backend.agent.dispatch import Dispatcher
        from backend.computer.displays import Display, DisplayMap
        from backend.safety.killswitch import KillSwitch
        d = Dispatcher(
            DisplayMap([Display(0, 0, 0, 1920, 1080, True)]),
            capture=None, kill=KillSwitch(), approve=approve,
        )
        d.skills.directory = tmp_path / "yetenekler"
        return d

    def test_yetenek_hatasi_ajani_dusurmez(self, tmp_path):
        from backend.agent.dispatch import ToolError
        d = self._dispatcher(tmp_path)
        d.skills.write(
            "patla",
            'ARAC = {"ad": "patla", "aciklama": "hep patlar", "girdi": {}}\n'
            'def calistir(girdi, ortam):\n'
            '    raise ValueError("olmadi")\n',
        )
        with pytest.raises(ToolError, match="olmadi"):
            d.run("patla", {})

    def test_skill_write_onaysiz_yazmaz(self, tmp_path):
        from backend.agent.dispatch import Denied
        d = self._dispatcher(tmp_path, approve=lambda *_: False)
        with pytest.raises(Denied):
            d.run("skill_write", {"name": "x", "code": "ARAC={}", "why": "deneme"})
        assert not (d.skills.directory / "x.py").exists()

    def test_onay_ekraninda_kodun_tamami_gosterilir(self, tmp_path):
        # Ne kurulduğunu görmeden onaylamak, onay olmamasıyla aynı şey.
        gorulen = {}

        def approve(name, detail, reason):
            gorulen["detail"] = detail
            return False

        d = self._dispatcher(tmp_path, approve=approve)
        kod = 'ARAC = {"ad": "x", "aciklama": "a", "girdi": {}}'
        with pytest.raises(Exception):
            d.run("skill_write", {"name": "x", "code": kod, "why": "deneme"})
        assert kod in gorulen["detail"]

    def test_onay_isteyen_yetenek_reddedilince_calismaz(self, tmp_path):
        from backend.agent.dispatch import Denied
        calisti = []
        d = self._dispatcher(tmp_path, approve=lambda *_: False)
        d.skills.write(
            "riskli",
            'ARAC = {"ad": "riskli", "aciklama": "a", "girdi": {}, "onay": True}\n'
            'import pathlib\n'
            'def calistir(girdi, ortam):\n'
            '    pathlib.Path(girdi.get("iz", "")).touch()\n'
            '    return "calisti"\n',
        )
        iz = tmp_path / "iz.txt"
        with pytest.raises(Denied):
            d.run("riskli", {"iz": str(iz)})
        assert not iz.exists()


class TestSystemPrompt:
    def _displays(self):
        from backend.computer.displays import Display, DisplayMap
        return DisplayMap([Display(0, 0, 0, 1920, 1080, True)])

    def test_kod_ornekli_prompt_kurulur(self):
        # Gerileme testi: prompt `str.format` ile kuruluyordu ve içindeki
        # örnek kodun süslü parantezleri yer tutucu sanılıyordu. Ajan hiç
        # başlayamadan `KeyError: '\n    "ad"'` veriyordu.
        from backend.agent.prompts import build_system
        out = build_system(self._displays(), 0)
        assert '"ad": "gun_farki"' in out
        assert "{displays}" not in out
        assert "{active}" not in out

    def test_suslu_parantez_eklemek_prompti_kirmaz(self):
        from backend.agent import prompts
        original = prompts.SYSTEM
        prompts.SYSTEM = original + '\nornek = {"a": 1, "b": {"c": 2}}\n'
        try:
            out = prompts.build_system(self._displays(), 1)
        finally:
            prompts.SYSTEM = original
        assert '{"a": 1, "b": {"c": 2}}' in out


class TestShortcuts:
    """Çubuktaki düğmeler."""

    def _store(self, tmp_path):
        from backend.skills.shortcuts import ShortcutStore
        return ShortcutStore(tmp_path / "dugmeler.json")

    def _one(self, **kw):
        from backend.skills.shortcuts import Shortcut
        data = dict(name="rapor", label="Haftalik rapor",
                    instruction="Raporu hazirla", glyph="tablo")
        data.update(kw)
        return Shortcut(**data)

    def test_kaydedilen_dugme_geri_okunur(self, tmp_path):
        store = self._store(tmp_path)
        store.save(self._one())
        assert [s.label for s in store.all()] == ["Haftalik rapor"]
        assert store.get("rapor").instruction == "Raporu hazirla"

    def test_ayni_ad_ustune_yazilir_kopyalanmaz(self, tmp_path):
        store = self._store(tmp_path)
        store.save(self._one())
        store.save(self._one(label="Aylik rapor"))
        assert [s.label for s in store.all()] == ["Aylik rapor"]

    def test_bozuk_dosya_uygulamayi_acmaktan_alikoymaz(self, tmp_path):
        # Bir düğme yüzünden uygulamanın açılmaması kabul edilemez.
        store = self._store(tmp_path)
        store.path.write_text("{bu json degil", encoding="utf-8")
        assert store.all() == []

    def test_eksik_alanli_kayit_atlanir_digerleri_kalir(self, tmp_path):
        import json
        store = self._store(tmp_path)
        store.path.write_text(
            json.dumps([
                {"ad": "iyi", "etiket": "Iyi", "talimat": "calis"},
                {"ad": "yarim"},
            ]),
            encoding="utf-8",
        )
        assert [s.name for s in store.all()] == ["iyi"]

    def test_talimatsiz_dugme_reddedilir(self, tmp_path):
        from backend.skills.shortcuts import ShortcutError
        store = self._store(tmp_path)
        with pytest.raises(ShortcutError, match="instruction cannot be empty"):
            store.save(self._one(instruction="   "))

    def test_uzun_etiket_reddedilir(self, tmp_path):
        from backend.skills.shortcuts import ShortcutError
        store = self._store(tmp_path)
        with pytest.raises(ShortcutError, match="22"):
            store.save(self._one(label="B" * 40))

    def test_etiketten_uretilen_ad_turkce_harf_barindirmaz(self):
        from app.buttons import _slug
        assert _slug("Günlük Özet Çıkar") == "gunluk_ozet_cikar"
        assert _slug("3 gün")[0].isalpha()
        assert _slug("!!!") == "dugme"


class TestButtonTools:
    def _dispatcher(self, tmp_path, approve):
        from backend.agent.dispatch import Dispatcher
        from backend.computer.displays import Display, DisplayMap
        from backend.safety.killswitch import KillSwitch
        from backend.skills.shortcuts import ShortcutStore
        d = Dispatcher(
            DisplayMap([Display(0, 0, 0, 1920, 1080, True)]),
            capture=None, kill=KillSwitch(), approve=approve,
        )
        d.buttons = ShortcutStore(tmp_path / "dugmeler.json")
        return d

    def test_ajan_dugme_kurar(self, tmp_path):
        d = self._dispatcher(tmp_path, approve=lambda *_: True)
        d.run("button_write", {
            "name": "disk", "label": "Disk durumu",
            "instruction": "C: surucusunu kontrol et", "glyph": "kabuk",
            "why": "Haftada uc kez soruyorsun",
        })
        assert d.buttons.get("disk").glyph == "kabuk"

    def test_onaysiz_dugme_kurulmaz(self, tmp_path):
        # Düğme Berkay'ın arayüzünü değiştiriyor; sessizce eklenmemeli.
        from backend.agent.dispatch import Denied
        d = self._dispatcher(tmp_path, approve=lambda *_: False)
        with pytest.raises(Denied):
            d.run("button_write", {
                "name": "x", "label": "X", "instruction": "y", "why": "z",
            })
        assert d.buttons.all() == []


class TestCommandNames:
    def test_kisa_komut_kabul_edilir(self, tmp_path):
        # Gerileme testi: komut adı, araç adı kuralına tabiydi ve en az üç
        # harf istiyordu. `/oz` reddediliyordu — kısayolun kısa olmasını
        # engelleyen bir kural.
        from backend.skills.registry import SkillRegistry
        r = SkillRegistry(directory=tmp_path / "y")
        r.write("ozet", (
            'ARAC = {"ad": "ozet", "aciklama": "a", "girdi": {}}\n'
            'KOMUT = {"ad": "oz", "aciklama": "Ozet", "talimat": "Bugunu ozetle"}\n'
            'def calistir(g, o): return "ok"\n'
        ))
        assert r.expand("/oz") == "Bugunu ozetle"

    def test_gecersiz_komut_adi_yine_reddedilir(self, tmp_path):
        from backend.skills.registry import SkillError, SkillRegistry
        r = SkillRegistry(directory=tmp_path / "y")
        with pytest.raises(SkillError, match="valid command name"):
            r.write("kotu", (
                'ARAC = {"ad": "kotu", "aciklama": "a", "girdi": {}}\n'
                'KOMUT = {"ad": "3 gun", "aciklama": "a", "talimat": "b"}\n'
                'def calistir(g, o): return "ok"\n'
            ))


class TestRefusal:
    """Reddedilme nasıl anlatılıyor."""

    def test_modelin_kendi_aciklamasi_kaybolmaz(self):
        # Eski hâli modelin metnini atıp yerine tek cümlelik bir kalıp
        # koyuyordu; kullanıcı neyin reddedildiğini öğrenemiyordu.
        from backend.agent.loop import _refusal_text
        out = _refusal_text("Ekranda doğrulama kodu var, ona dokunmadım.")
        assert "doğrulama kodu var, ona dokunmadım" in out
        assert "try again" in out

    def test_metin_yoksa_yine_de_ne_yapilacagi_yazar(self):
        from backend.agent.loop import _refusal_text
        out = _refusal_text("   ")
        assert "about what was on screen" in out
        assert out.strip() == out

    def test_reddedilince_gecmisteki_gorseller_dusurulur(self):
        # Kare geçmişte kalırsa bir sonraki istek de aynı yerde reddediliyor
        # ve kullanıcı "hiçbir şey çalışmıyor" diye kalıyor.
        from backend.agent.loop import Agent
        agent = Agent.__new__(Agent)
        # `__new__` __init__'i atlıyor; bu metotların artık
        # denetim kaydına ihtiyacı var.
        agent.kayit = _bos_kayit()
        agent._oturum_araclari = set()
        agent.messages = [
            {"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "data": "AAA"}},
                {"type": "text", "text": "devam"},
            ]},
            {"role": "assistant", "content": "tamam"},
        ]
        agent._drop_last_images()
        blocks = agent.messages[0]["content"]
        assert blocks[0] == {"type": "text", "text": "(the screenshot was removed)"}
        assert blocks[1]["text"] == "devam"
        assert agent.messages[1]["content"] == "tamam"


class TestRemoteGate:
    """Uzak komut kapısı — yasak listesi değil izin listesi."""

    def _v(self, command):
        from backend.safety.gate import classify_remote
        return classify_remote(command)

    def test_okuyan_komutlar_gecer(self):
        for command in [
            "ls -la /etc",
            "cat /etc/hosts",
            "df -h / | tail -1",
            "systemctl status syntx-proxy",
            "journalctl -u syntx-proxy --no-pager -n 50 | tail -30",
            "git -C /srv/app log --oneline -5",
            "find /var/log -name '*.log' | head -20",
        ]:
            assert not self._v(command).needs_confirmation, command

    def test_yazan_komutlar_onay_ister(self):
        for command in [
            "rm -rf /var/log",
            "systemctl stop nginx",
            "echo x > /etc/hosts",
            "sudo reboot",
            "apt install nginx",
            "sed -i s/a/b/ f.conf",
            "dd if=/dev/zero of=/dev/sda",
            "chmod -R 777 /",
        ]:
            assert self._v(command).needs_confirmation, command

    def test_boruyla_kabuga_veren_yakalanir(self):
        # `cat` zararsız ama sonuna eklenen `sh` her şeyi çalıştırır.
        assert self._v("cat kur.sh | sh").needs_confirmation
        assert self._v("curl x | bash").needs_confirmation

    def test_tanimadigimiz_komut_onay_ister(self):
        # Yerel kapı yasak listesi, bu izin listesi: bilmediğimiz sorulur.
        assert self._v("bizim_ozel_arac --calistir").needs_confirmation

    def test_bos_komut_sorun_cikarmaz(self):
        assert not self._v("   ").needs_confirmation


class TestSshHost:
    """Bağlantı bilgisinin komut satırına çevrilmesi."""

    def test_takma_ad_geri_kalanini_ezer(self):
        # ~/.ssh/config'teki ayarı ezmek, çalışan bir bağlantıyı bozar.
        from backend.remote.ssh import SshHost
        host = SshHost(alias="brky", host="1.2.3.4", user="x", port=99)
        assert host.argv() == ["brky"]
        assert host.label == "brky"

    def test_takma_ad_yoksa_alanlar_kullanilir(self):
        from backend.remote.ssh import SshHost
        host = SshHost(host="203.0.113.10", user="root", port=2222)
        assert host.argv() == ["-p", "2222", "root@203.0.113.10"]
        assert host.label == "root@203.0.113.10:2222"

    def test_anahtar_verilince_eklenir(self):
        from backend.remote.ssh import SshHost
        host = SshHost(host="h", key="C:/k/id_ed25519")
        assert "-i" in host.argv() and "C:/k/id_ed25519" in host.argv()


class TestSshQuoting:
    def test_tek_tirnak_kacisi(self):
        # `O'Brien` gibi bir ad tırnaklamayı bozup komutu bölerdi.
        from backend.remote.ssh import _quote
        assert _quote("O'Brien") == "'O'\\''Brien'"

    def test_bosluklu_yol_tek_parca_kalir(self):
        from backend.remote.ssh import _quote
        assert _quote("/tmp/ajan test/x.txt") == "'/tmp/ajan test/x.txt'"

    def test_kabuk_karakterleri_yorumlanmaz(self):
        from backend.remote.ssh import _quote
        out = _quote("$HOME; rm -rf /")
        assert out.startswith("'") and out.endswith("'")
        assert "$HOME; rm -rf /" in out


class TestEntry:
    def _entry(self, **kw):
        from backend.remote.ssh import Entry
        data = dict(name="x", is_dir=False, size=0, modified="2026-01-01 00:00",
                    mode="-rw-r--r--", parent="/tmp")
        data.update(kw)
        return Entry(**data)

    def test_klasorde_boyut_yazilmaz(self):
        assert self._entry(is_dir=True, size=4096).size_label == ""

    def test_boyut_okunur_birime_cevrilir(self):
        assert self._entry(size=7).size_label == "7 B"
        assert self._entry(size=3277).size_label == "3.2 KB"
        assert self._entry(size=5 * 1024 * 1024).size_label == "5.0 MB"

    def test_yol_ust_dizinle_birlestirilir(self):
        assert self._entry(name="a b.txt").path == "/tmp/a b.txt"
        assert self._entry(parent="/").path == "/x"


class TestUygulamaKurulumu:
    """Uygulamanın kendisi ayağa kalkıyor mu.

    Bu sınıf bir hatadan sonra yazıldı: `window.connect_remote` diye var
    olmayan bir alana bağlanıldı ve 127 testin hepsi geçtiği hâlde uygulama
    açılmadı. Testler modülleri tek tek doğruluyordu, hiçbiri onları
    birbirine bağlayan kodu çalıştırmıyordu.
    """

    def _app(self):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        return QApplication.instance() or QApplication([])

    def test_pencere_ve_cubuk_kurulur(self):
        app = self._app()
        from app import fluent
        from app.commandbar import CommandBar
        from app.window import MainWindow

        tokens = fluent.apply(app)
        window = MainWindow(tokens)
        bar = CommandBar(tokens)
        window.attach_bar(bar)
        # Ana döngünün dokunduğu her alan gerçekten var mı.
        assert window.status.connect_remote is not None
        assert window.activity is not None
        assert bar.buttons is not None
        window.close()
        bar.close()

    def test_ana_dongunun_bagladigi_alanlar_var(self):
        # `doppel.py` içinde `window.<x>` ve `bar.<x>` diye erişilen her alan
        # gerçekten tanımlı mı — eksikse uygulama açılmıyor.
        import re
        from pathlib import Path

        source = Path(__file__).resolve().parent.parent / "doppel.py"
        text = source.read_text(encoding="utf-8")

        app = self._app()
        from app import fluent
        from app.commandbar import CommandBar
        from app.window import MainWindow

        tokens = fluent.apply(app)
        nesneler = {"window": MainWindow(tokens), "bar": CommandBar(tokens)}
        eksik = []
        for ad, nesne in nesneler.items():
            # Büyük harf de dâhil: `activateWindow` küçük harfle sınırlı bir
            # desende `activate` diye kesiliyor ve olmayan bir alan uyduruyor.
            for alan in set(re.findall(rf"\b{ad}\.([A-Za-z_][A-Za-z0-9_]*)", text)):
                if not hasattr(nesne, alan):
                    eksik.append(f"{ad}.{alan}")
        assert not eksik, f"doppel.py olmayan alanlara bağlanıyor: {eksik}"
        for nesne in nesneler.values():
            nesne.close()


class TestTekrarlayanHata:
    """Aynı hataya takılıp token yakmayı durdurma.

    Gerçek bir koşuda bir kod hatası yüzünden dört `remote_*` çağrısı üst
    üste aynı `TypeError` ile düştü ve ajan her seferinde yeniden denedi.
    Her deneme bir model çağrısı, yani gerçek para.
    """

    def _outcome(self, text):
        from backend.agent.loop import ToolOutcome
        return ToolOutcome(content=text, is_error=True)

    def test_ayni_hata_ayni_imzayi_verir(self):
        from backend.agent.loop import _error_key
        a = self._outcome("TypeError: _session() missing 1 argument at line 12")
        b = self._outcome("TypeError: _session() missing 1 argument at line 99")
        assert _error_key("remote_list", a) == _error_key("remote_list", b)

    def test_farkli_arac_farkli_imza(self):
        from backend.agent.loop import _error_key
        o = self._outcome("aynı hata")
        assert _error_key("remote_list", o) != _error_key("remote_read", o)

    def test_farkli_hata_farkli_imza(self):
        from backend.agent.loop import _error_key
        assert _error_key("x", self._outcome("dosya yok")) != _error_key(
            "x", self._outcome("izin reddedildi")
        )

    def test_ikinci_tekrarda_modele_uyari_eklenir(self):
        from backend.agent.loop import Agent, Turn, ToolOutcome
        from backend.agent.dispatch import ToolError

        agent = Agent.__new__(Agent)
        # `__new__` __init__'i atlıyor; bu metotların artık
        # denetim kaydına ihtiyacı var.
        agent.kayit = _bos_kayit()
        agent._oturum_araclari = set()

        class SahteDispatcher:
            def run(self, name, payload):
                raise ToolError("hep aynı hata")

        agent.dispatcher = SahteDispatcher()

        class Blok:
            type = "tool_use"
            name = "remote_list"
            id = "t1"
            input = {}
            toolset_name = None

        seen = {}
        son = None
        for _ in range(2):
            sonuclar = agent._run_batch([Blok()], Turn(), seen)
            son = sonuclar[-1]
        metin = str(son)
        assert "Do not retry it" in metin, metin
        assert max(seen.values()) == 2


class TestAdCakismasi:
    """Aynı sınıfta iki kez tanımlanan metot.

    `_session` hem terminal hem SSH için tanımlanmıştı; sonra gelen öncekini
    sessizce ezdi ve bütün `remote_*` araçları "missing 1 required positional
    argument" hatasıyla düştü. Python bunu ne hata ne uyarı sayıyor.
    """

    def _duplicates(self, path):
        import ast
        from collections import Counter
        from pathlib import Path

        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
        found = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            names = Counter(
                child.name for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            )
            tekrar = [n for n, adet in names.items() if adet > 1]
            if tekrar:
                found[node.name] = tekrar
        return found

    def test_hicbir_sinifta_tekrarlayan_metot_yok(self):
        from pathlib import Path

        kok = Path(__file__).resolve().parent.parent
        sorunlu = {}
        for path in list(kok.glob("backend/**/*.py")) + list(kok.glob("app/*.py")):
            found = self._duplicates(path)
            if found:
                sorunlu[path.name] = found
        assert not sorunlu, f"aynı sınıfta iki kez tanımlanan metot: {sorunlu}"


class TestSonucGorunumu:
    """Sonuç türüne göre görünüm."""

    def test_yigin_izinden_okunabilir_satir(self):
        from app.results import _short_error
        yigin = (
            "Traceback (most recent call last):\n"
            "  File \"dispatch.py\", line 130, in run\n"
            "    return handler(payload)\n"
            "TypeError: _session() missing 1 required positional argument"
        )
        assert _short_error(yigin) == (
            "TypeError: _session() missing 1 required positional argument"
        )

    def test_tek_satirlik_hata_oldugu_gibi_kalir(self):
        from app.results import _short_error
        assert _short_error("brky: Permission denied") == "brky: Permission denied"

    def test_dizin_satiri_ayristirilir(self):
        from app.results import _ENTRY
        m = _ENTRY.match("  d drwxr-xr-x           2026-08-16 17:54  ai-news")
        assert m and m.group("name") == "ai-news" and m.group("kind") == "d"

    def test_bosluklu_dosya_adi_bozulmaz(self):
        from app.results import _ENTRY
        m = _ENTRY.match("  - -rw-r--r--     3.2 KB 2026-08-14 19:03  bir dosya.txt")
        assert m and m.group("name") == "bir dosya.txt"
        assert m.group("size").strip() == "3.2 KB"

    def test_dizin_olmayan_cikti_eslesmez(self):
        from app.results import _ENTRY
        assert _ENTRY.match(" 15:36:19 up 12 days,  2 users") is None


class TestYetenekPaneli:
    """Ajanın kurduğu arayüz özelliği."""

    def _panel(self, **kw):
        base = {
            "baslik": "Sunucu",
            "bolumler": [
                {"tur": "olcu", "ogeler": [{"etiket": "Disk", "deger": "%68"}]}
            ],
        }
        base.update(kw)
        return {"panel": base}

    def test_gecerli_panel_normallesir(self):
        from backend.skills.panel import normalise
        out = normalise(self._panel())
        assert out["baslik"] == "Sunucu"
        assert out["bolumler"][0]["ogeler"][0]["durum"] == "notr"

    def test_panel_olmayan_sonuc_none(self):
        from backend.skills.panel import normalise
        assert normalise("düz metin") is None
        assert normalise({"sonuc": 5}) is None

    def test_bilinmeyen_bolum_turu_reddedilir(self):
        # Sessizce atlamak, ajanın panelinin görünmediğini fark etmemesine
        # yol açardı.
        from backend.skills.panel import PanelError, normalise
        with pytest.raises(PanelError, match="grafik"):
            normalise(self._panel(bolumler=[{"tur": "grafik", "ogeler": []}]))

    def test_bilinmeyen_durum_reddedilir(self):
        from backend.skills.panel import PanelError, normalise
        with pytest.raises(PanelError, match="mor"):
            normalise(self._panel(bolumler=[
                {"tur": "olcu", "ogeler": [{"deger": "1", "durum": "mor"}]}
            ]))

    def test_bassiz_panel_reddedilir(self):
        from backend.skills.panel import PanelError, normalise
        with pytest.raises(PanelError, match="baslik"):
            normalise(self._panel(baslik="  "))

    def test_eksik_alan_hangi_bolum_oldugunu_soyler(self):
        from backend.skills.panel import PanelError, normalise
        with pytest.raises(PanelError, match="section 1"):
            normalise(self._panel(bolumler=[
                {"tur": "metin", "icerik": "a"},
                {"tur": "tablo"},
            ]))

    def test_panel_metne_cevrilir(self):
        # Ajan kullanıcıya ne gösterdiğini bilmeli; yoksa bir sonraki
        # cümlesinde panelde yazanla çelişiyor.
        from backend.skills.panel import normalise, to_text
        out = to_text(normalise(self._panel(bolumler=[
            {"tur": "olcu", "ogeler": [{"etiket": "Disk", "deger": "%68"}]},
            {"tur": "tablo", "basliklar": ["Ad"], "satirlar": [["/var/log"]]},
        ])))
        assert "Disk: %68" in out and "/var/log" in out

    def test_yetenek_panel_dondurunce_yakalanir(self, tmp_path):
        from backend.agent.dispatch import Dispatcher
        from backend.computer.displays import Display, DisplayMap
        from backend.safety.killswitch import KillSwitch

        d = Dispatcher(
            DisplayMap([Display(0, 0, 0, 1920, 1080, True)]),
            capture=None, kill=KillSwitch(), approve=lambda *_: True,
        )
        d.skills.directory = tmp_path / "y"
        d.skills.write("gosterge", (
            'ARAC = {"ad": "gosterge", "aciklama": "panel", "girdi": {}}\n'
            'def calistir(girdi, ortam):\n'
            '    return {"panel": {"baslik": "Test", "bolumler": ['
            '        {"tur": "metin", "icerik": "merhaba"}]}}\n'
        ))
        out = d.run("gosterge", {})
        assert d.last_panel is not None
        assert d.last_panel[0] == "gosterge"
        # Model de aynı şeyi metin olarak görüyor.
        assert "merhaba" in out.content

    def test_bozuk_panel_ajana_hata_olarak_doner(self, tmp_path):
        from backend.agent.dispatch import Dispatcher, ToolError
        from backend.computer.displays import Display, DisplayMap
        from backend.safety.killswitch import KillSwitch

        d = Dispatcher(
            DisplayMap([Display(0, 0, 0, 1920, 1080, True)]),
            capture=None, kill=KillSwitch(), approve=lambda *_: True,
        )
        d.skills.directory = tmp_path / "y"
        d.skills.write("bozuk", (
            'ARAC = {"ad": "bozuk", "aciklama": "panel", "girdi": {}}\n'
            'def calistir(girdi, ortam):\n'
            '    return {"panel": {"baslik": "X", "bolumler": ['
            '        {"tur": "pasta_grafigi"}]}}\n'
        ))
        with pytest.raises(ToolError, match="Fix it with skill_write"):
            d.run("bozuk", {})


class TestYakalamaThread:
    """Ekran yakalama ajanın thread'inden çalışıyor mu.

    Gerçek bir hata: yakalayıcı arayüz thread'inde kuruluyor, ajan ayrı bir
    thread'de çalışıyor ve mss cihaz bağlamını `threading.local()` içinde
    tuttuğu için her ekran görüntüsü

        AttributeError: '_thread._local' object has no attribute 'srcdc'

    ile düşüyordu. Fren devreye girip "3 kez düştü, durdum" dedi — yani
    ajan hiç ekran göremiyordu.
    """

    def test_baska_threadden_yakalama_calisir(self):
        import threading

        from backend.computer.capture import ScreenCapture
        from backend.computer.displays import enumerate_displays

        displays = enumerate_displays()
        capture = ScreenCapture(displays)
        try:
            # Ana thread'de kur (uygulamada arayüz thread'i yapıyor).
            ana = capture.grab(0)
            sonuc = {}

            def isci():
                try:
                    kare = capture.grab(0)
                    sonuc["boyut"] = (kare.width, kare.height)
                except Exception as exc:
                    sonuc["hata"] = f"{type(exc).__name__}: {exc}"

            thread = threading.Thread(target=isci)
            thread.start()
            thread.join(timeout=20)

            assert "hata" not in sonuc, sonuc["hata"]
            assert sonuc["boyut"] == (ana.width, ana.height)
        finally:
            capture.close()

    def test_kapanis_iki_kez_cagrilabilir(self):
        from backend.computer.capture import ScreenCapture
        from backend.computer.displays import enumerate_displays

        capture = ScreenCapture(enumerate_displays())
        capture.grab(0)
        capture.close()
        capture.close()  # uygulama kapanırken iki kez gelebiliyor


class TestPencereEkrani:
    """Bir pencerenin hangi monitörde olduğu.

    Gerçek hata: Discord penceresi sol=1912'de başlıyordu ve 1920'de
    başlayan ikinci ekranda olmasına rağmen "sol kenarı içeren ekran"
    mantığıyla birinci ekranda sayıldı. Ekran görüntüsü yanlış monitörden
    alınıp ajan Discord'u hiç göremedi.
    """

    def setup_method(self):
        self.map = DisplayMap([PRIMARY, SECONDARY])

    def test_kenardan_tasan_pencere_dogru_ekranda(self):
        # 8 piksel birinciye taşıyor ama neredeyse tamamı ikincide.
        assert self.map.locate_rect(1912, -8, 3848, 1040) is SECONDARY

    def test_tamamen_birincideki_pencere(self):
        assert self.map.locate_rect(100, 100, 900, 700) is PRIMARY

    def test_tam_ortada_bolunmus_pencere_daha_cok_olana_gider(self):
        # 1500..2500: birincide 420, ikincide 580 piksel genişlik.
        assert self.map.locate_rect(1500, 0, 2500, 1080) is SECONDARY

    def test_hicbir_ekranla_kesismeyen_pencere_cokmez(self):
        # Ekran çıkarılmış olabiliyor; en azından bir cevap dönmeli.
        assert self.map.locate_rect(-5000, -5000, -4000, -4000) in (PRIMARY, SECONDARY)


class TestKeyAraci:
    def test_eksik_tus_anlasilir_hata(self):
        # Ham AttributeError dönüyordu; ne eksik olduğunu söylemiyordu.
        from backend.agent.dispatch import Dispatcher, ToolError
        from backend.safety.killswitch import KillSwitch

        d = Dispatcher(DisplayMap([PRIMARY]), capture=None, kill=KillSwitch())
        with pytest.raises(ToolError, match=re.escape("ctrl+k")):
            d.run("key", {})


class TestDiscordEklentisi:
    """Klavyeyle Discord — yan etkisiz korumalar."""

    def _skill(self, tmp_path):
        from pathlib import Path

        from backend.skills.registry import SkillRegistry

        kok = Path(__file__).resolve().parent.parent
        r = SkillRegistry(directory=tmp_path / "y")
        return r.write("discord", (kok / "eklentiler" / "discord.py").read_text(
            encoding="utf-8"
        ))

    class Ortam:
        def __init__(self, odak=True, gecebilir=True):
            self.odak, self.gecebilir = odak, gecebilir
            self.cagrilar, self.onaylar = [], []

        def arac(self, ad, **g):
            self.cagrilar.append((ad, g))
            return "OK"

        def bekle(self, saniye):
            pass

        def on_pencere(self):
            return "Discord" if self.odak else "Mozilla Firefox"

        def pencereye_gec(self, baslik, timeout=3.0):
            return self.gecebilir

        def pencerenin_ekrani(self, baslik):
            return 1

        def onay(self, baslik, ayrinti, sebep):
            self.onaylar.append(baslik)
            return False

    def _tuslar(self, ortam):
        return [g for ad, g in ortam.cagrilar if ad in ("key", "type")]

    def test_odak_yoksa_tus_gonderilmez(self, tmp_path):
        # Yanlış pencereye giden tuş, başkasının sohbetine yazmak demek.
        skill = self._skill(tmp_path)
        o = self.Ortam(odak=False, gecebilir=False)
        out = skill.run({"islem": "git", "hedef": "genel"}, o)
        assert "no key was sent" in out
        assert self._tuslar(o) == []

    def test_yaz_gondermiyor(self, tmp_path):
        skill = self._skill(tmp_path)
        o = self.Ortam()
        out = skill.run({"islem": "yaz", "metin": "merhaba"}, o)
        assert "NOT SENT" in out
        assert not any(g.get("text") == "Return" for g in self._tuslar(o))

    def test_satir_sonlu_metin_reddedilir(self, tmp_path):
        # Discord'da Enter mesajı gönderir; satır sonu erken gönderim olurdu.
        skill = self._skill(tmp_path)
        o = self.Ortam()
        out = skill.run({"islem": "yaz", "metin": "bir\niki"}, o)
        assert "line break" in out
        assert self._tuslar(o) == []

    def test_gonder_onaysiz_calismaz(self, tmp_path):
        skill = self._skill(tmp_path)
        o = self.Ortam()
        out = skill.run({"islem": "gonder"}, o)
        assert "declined sending" in out
        assert o.onaylar == ["discord gonder"]
        assert self._tuslar(o) == []

    def test_git_arama_sonrasi_bekliyor(self, tmp_path):
        # Erken Enter önceki sonuca gider — yanlış kişiye yazmanın yolu.
        skill = self._skill(tmp_path)
        o = self.Ortam()
        skill.run({"islem": "git", "hedef": "genel"}, o)
        sira = [(ad, g) for ad, g in o.cagrilar if ad in ("key", "type")]
        assert sira[0][1]["text"] == "ctrl+k"
        assert sira[1][1]["text"] == "genel"
        assert sira[2][1]["text"] == "Return"

    def test_ac_dogru_ekrana_geciyor(self, tmp_path):
        # Ajan yanlış monitöre bakarsa Discord'u hiç göremiyor.
        skill = self._skill(tmp_path)
        o = self.Ortam()
        out = skill.run({"islem": "ac"}, o)
        assert ("switch_display", {"index": 1}) in o.cagrilar
        assert "display is now 1" in out


class TestHiz:
    """Hız kararlarının gerilemesini engelleyen testler."""

    def test_kare_webp_kayipsiz(self):
        # PNG'nin 2-6 katı küçük ve kayıpsız; kayıplı bir biçim küçük
        # yazıyı bozar ve yanlış okunan etiket yanlış tıklama demek.
        from backend.computer.capture import ScreenCapture
        from backend.computer.displays import enumerate_displays

        capture = ScreenCapture(enumerate_displays())
        try:
            data, mime = capture.grab(0).encode()
        finally:
            capture.close()
        assert mime == "image/webp"
        assert data[:4] == b"RIFF" and data[8:12] == b"WEBP"

    def test_onbellek_noktasi_son_statik_aracta(self):
        """Nokta ilk sıradayken arkasındaki 28 özel araç (~3700 token) her
        istekte yeniden işleniyordu."""
        from backend.agent.loop import Agent
        from backend.agent.tools import CUSTOM_TOOLS

        agent = Agent.__new__(Agent)
        # `__new__` __init__'i atlıyor; bu metotların artık
        # denetim kaydına ihtiyacı var.
        agent.kayit = _bos_kayit()
        agent._oturum_araclari = set()

        class SahteKayit:
            def tools(self):
                return [{"name": "yetenek", "description": "", "input_schema": {}}]

        class SahteDispatcher:
            skills = SahteKayit()
            active_index = 0
            kuru = False
            mcp = _McpYok()

        agent.dispatcher = SahteDispatcher()
        tools = agent.tools

        assert "cache_control" not in tools[0], "computer araç setinde olmamalı"
        isaretli = [i for i, t in enumerate(tools) if "cache_control" in t]
        assert len(isaretli) == 1
        # Nokta bütün statik araçlardan sonra, yeteneklerden önce.
        assert isaretli[0] == len(CUSTOM_TOOLS)
        assert tools[-1]["name"] == "yetenek"
        assert "cache_control" not in tools[-1]

    def test_yetenek_eklemek_onbellegi_bozmuyor(self):
        # Yetenek listesi noktadan sonra: yeni yetenek yazmak statik
        # bölümün önbelleğini geçersiz kılmamalı.
        from backend.agent.loop import Agent

        agent = Agent.__new__(Agent)
        # `__new__` __init__'i atlıyor; bu metotların artık
        # denetim kaydına ihtiyacı var.
        agent.kayit = _bos_kayit()
        agent._oturum_araclari = set()

        class SahteKayit:
            def __init__(self):
                self.adet = 1

            def tools(self):
                return [
                    {"name": f"y{i}", "description": "", "input_schema": {}}
                    for i in range(self.adet)
                ]

        class SahteDispatcher:
            active_index = 0
            kuru = False
            mcp = _McpYok()

        d = SahteDispatcher()
        d.skills = SahteKayit()
        agent.dispatcher = d

        once = agent.tools
        d.skills.adet = 3
        sonra = agent.tools
        statik = len(once) - 1
        assert once[:statik] == sonra[:statik]

    def test_sistem_promptu_onbelleklenebilir_blok(self):
        from backend.agent.loop import Agent
        from backend.computer.displays import Display, DisplayMap

        agent = Agent.__new__(Agent)
        # `__new__` __init__'i atlıyor; bu metotların artık
        # denetim kaydına ihtiyacı var.
        agent.kayit = _bos_kayit()
        agent._oturum_araclari = set()
        agent.displays = DisplayMap([Display(0, 0, 0, 1920, 1080, True)])

        class SahteDispatcher:
            active_index = 0
            kuru = False
            mcp = _McpYok()

        agent.dispatcher = SahteDispatcher()
        blocks = agent._system_blocks()
        assert len(blocks) == 1
        assert blocks[0]["cache_control"] == {"type": "ephemeral"}
        assert len(blocks[0]["text"]) > 1000


class TestPencereOneGetirme:
    def test_olmayan_pencere_hizli_false_doner(self):
        # Zaman aşımını beklemek bir aracın saniyelerce donması demek.
        import time

        from backend.computer import windows as win

        basla = time.monotonic()
        assert win.activate("boyle-bir-pencere-yok-12345", timeout=5.0) is False
        assert time.monotonic() - basla < 1.0

    def test_olmayan_pencerenin_dikdortgeni_none(self):
        from backend.computer import windows as win

        assert win.window_rect("boyle-bir-pencere-yok-12345") is None


class TestUygulamaKatalogu:
    """Kurulu uygulamaları bulmak.

    `launch_app` yalnızca PATH'e bakıyordu ve on yedi yaygın uygulamadan
    on ikisi bulunamıyordu.
    """

    def test_katalog_dolu(self):
        from backend.computer import apps
        assert len(apps.catalog()) > 20

    def test_onbellek_ikinci_taramayi_atliyor(self):
        import time

        from backend.computer import apps

        apps.catalog(refresh=True)
        basla = time.monotonic()
        apps.catalog()
        assert time.monotonic() - basla < 0.05

    def test_turkce_harf_duyarsiz_arama(self):
        from backend.computer.apps import normalise
        assert normalise("Görüntü Düzenleyici") == "goruntu duzenleyici"
        assert normalise("İŞLEM") == "islem"

    def test_tam_ad_ilk_sirada(self):
        # "chrome" araması "Chrome Remote Desktop"u önce getirmemeli.
        from backend.computer import apps
        found = apps.search("chrome")
        if found:
            assert apps.normalise(found[0].name) in ("chrome", "google chrome")

    def test_kaldirma_kisayollari_katalogda_yok(self):
        # Ajanın açması istenen son şey "Uninstall".
        from backend.computer import apps
        for app in apps.catalog():
            assert "uninstall" not in app.name.lower()

    def test_yazim_hatasi_oneri_veriyor(self):
        # Sessizce başka uygulamaya çözmek tehlikeli; öneri vermek değil.
        from backend.computer import apps
        if apps.resolve("discord"):
            assert apps.resolve("discrod") is None
            assert any("discord" in a.name.lower() for a in apps.suggest("discrod"))

    def test_bos_sorgu_hicbir_sey_bulmuyor(self):
        from backend.computer import apps
        assert apps.search("  ") == []

    def test_magaza_uygulamasi_appsfolder_ile_aciliyor(self):
        from backend.computer.apps import App, launch_argv
        argv = launch_argv(App("Not Defteri", "magaza", "Microsoft.Notepad_8we!App"))
        assert argv[0] == "explorer.exe"
        assert argv[1].startswith("shell:AppsFolder\\")

    def test_kisayol_explorer_ile_aciliyor(self):
        from backend.computer.apps import App, launch_argv
        assert launch_argv(App("X", "kisayol", "C:/x.lnk")) == ["explorer.exe", "C:/x.lnk"]


class TestTopluYazma:
    def _dispatcher(self, approve):
        from backend.agent.dispatch import Dispatcher
        from backend.safety.killswitch import KillSwitch
        return Dispatcher(DisplayMap([PRIMARY]), capture=None,
                          kill=KillSwitch(), approve=approve)

    def test_tek_cagrida_cok_dosya(self, tmp_path):
        d = self._dispatcher(lambda *_: False)
        kok = tmp_path / "proje"
        out = d.run("write_files", {"files": [
            {"path": str(kok / "main.py"), "content": "print(1)\n"},
            {"path": str(kok / "alt" / "ayar.json"), "content": "{}\n"},
        ]})
        assert (kok / "main.py").exists()
        # Klasör kendiliğinden açılmalı, yoksa ajan önce mkdir turu harcıyor.
        assert (kok / "alt" / "ayar.json").exists()
        assert "2 files written" in out.content

    def test_ustune_yazma_tek_seferde_soruluyor(self, tmp_path):
        # Dosya başına ayrı onay, on dosyada okumadan onaylamaya yol açar.
        sorulan = []

        def approve(name, detail, reason):
            sorulan.append(detail)
            return False

        d = self._dispatcher(approve)
        for ad in ("a.txt", "b.txt"):
            (tmp_path / ad).write_text("eski", encoding="utf-8")

        from backend.agent.dispatch import Denied

        with pytest.raises(Denied):
            d.run("write_files", {"files": [
                {"path": str(tmp_path / "a.txt"), "content": "yeni"},
                {"path": str(tmp_path / "b.txt"), "content": "yeni"},
            ]})
        assert len(sorulan) == 1
        assert "a.txt" in sorulan[0] and "b.txt" in sorulan[0]
        # Reddedilince hiçbiri yazılmamalı.
        assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "eski"

    def test_yeni_dosya_onay_istemiyor(self, tmp_path):
        d = self._dispatcher(lambda *_: pytest.fail("yeni dosya sormamalı"))
        d.run("write_files", {"files": [
            {"path": str(tmp_path / "yeni.txt"), "content": "x"},
        ]})
        assert (tmp_path / "yeni.txt").exists()

    def test_bozuk_girdi_anlasilir_hata(self, tmp_path):
        from backend.agent.dispatch import ToolError
        d = self._dispatcher(lambda *_: True)
        with pytest.raises(ToolError, match=r"files\[1\]"):
            d.run("write_files", {"files": [
                {"path": str(tmp_path / "a"), "content": "x"},
                {"yol": "eksik"},
            ]})


class TestKodGorunumu:
    """Renklendirme artık `pygments` ile. Elle yazılmış düzenli ifadeler
    çok satırlı metinlerde yanılıyordu."""

    def _lex(self, path, text):
        from pygments.lexers import get_lexer_for_filename
        return get_lexer_for_filename(path, text)

    def test_uzantiya_gore_dil(self):
        assert self._lex("a.py", "x=1").name == "Python"
        # Eski düzenli ifade sürümü .tsx'i "c" sanıyordu.
        assert self._lex("b.tsx", "const x = 1").name == "TSX"
        assert self._lex("c.sh", "echo hi").name == "Bash"

    def test_belirtec_rengi_en_ozgul_esleseni_seciyor(self):
        # `Name.Function` tanımlıysa `Name.Function.Magic` de onu almalı,
        # daha genel `Name`e düşmemeli.
        from pygments.token import Name
        from app.ide import _format_for
        renkler = {"Name": "#111111", "Name.Function": "#222222"}
        assert _format_for(Name.Function.Magic, renkler).foreground().color().name() == "#222222"
        assert _format_for(Name.Variable, renkler).foreground().color().name() == "#111111"

    def test_tanimsiz_belirtec_bicimsiz_kaliyor(self):
        from pygments.token import Whitespace
        from app.ide import _format_for
        assert _format_for(Whitespace, {"Keyword": "#fff"}) is None

    def test_cok_satirli_metin_dogru_bitiyor(self):
        # Eski düzenli ifade sürümünün yanıldığı yer: üç tırnaklı bir
        # metinden sonraki kod hâlâ metin sanılıyordu.
        kaynak = '''x = """
bir
iki
"""
def f(): pass
'''
        from pygments.token import Keyword, String
        turler = [t for _, t, v in self._lex("a.py", kaynak).get_tokens_unprocessed(kaynak)
                  if v.strip()]
        assert any(t in String for t in turler)
        assert Keyword in turler  # `def` metnin içinde kalmadı

    def test_buyuk_dosya_renklendirilmiyor(self):
        # `pygments` bir megabaytta saniyeler harcıyor; o dosyaya zaten
        # kimse göz atmıyor.
        from app.ide import MAX_HIGHLIGHT
        assert MAX_HIGHLIGHT < 1_000_000


def _bos_kayit():
    """Diske yazmayan denetim kaydı.

    Testler `Agent.__new__` ile yarım nesne kuruyor ve o nesnelerin de
    artık bir kaydı olmalı. Geçici dizin yerine yazmayan bir kayıt:
    testin ilgilendiği şey kaydın içeriği değil, varlığı.
    """
    import pathlib
    import tempfile
    from backend.agent.kayit import Kayit

    return Kayit(pathlib.Path(tempfile.mkdtemp()))


class TestArayaGirme:
    """Ajan çalışırken araya bir cümle sıkıştırmak.

    Eskiden çalışırken yazdığın mesaj **sessizce düşüyordu**: yazıyordun,
    Enter'a basıyordun, hiçbir şey olmuyordu.
    """

    def _agent(self):
        from backend.agent.loop import Agent, _new_lock

        agent = Agent.__new__(Agent)
        # `__new__` __init__'i atlıyor; bu metotların artık
        # denetim kaydına ihtiyacı var.
        agent.kayit = _bos_kayit()
        agent._oturum_araclari = set()
        agent._pending = []
        agent._pending_lock = _new_lock()
        agent.messages = []
        return agent

    def test_kuyruk_sirayla_bosaliyor(self):
        a = self._agent()
        a.interject("bir")
        a.interject("iki")
        assert a.take_pending() == ["bir", "iki"]
        assert a.take_pending() == []

    def test_kuyruk_kilitli(self):
        # İki thread: arayüz yazıyor, ajan okuyor. Kayıp cümle olmamalı.
        import threading

        a = self._agent()
        yazanlar = [
            threading.Thread(target=lambda i=i: a.interject(str(i)))
            for i in range(50)
        ]
        for t in yazanlar:
            t.start()
        for t in yazanlar:
            t.join()
        assert sorted(int(x) for x in a.take_pending()) == list(range(50))

    def _kosu(self, araya_yaz):
        """Tek araç çağrısı, sonra bitiş — arada bir cümle sıkışıyor."""
        from backend.agent.loop import Agent, ToolOutcome, Turn

        agent = self._agent()

        class SahteKill:
            def reset(self): pass
            def check(self): pass

        class SahteEkranKaydi:
            """Tur biterken `Agent.run` kaydı kapatıyor — sahtenin de
            kapanabilmesi gerekiyor."""

            def __init__(self):
                self.kapandi = False

            def kapat(self):
                self.kapandi = True

        class SahteDispatcher:
            kuru = False
            ekran_kaydi = SahteEkranKaydi()

            def tur_basladi(self, talimat=""):
                pass

            def run(self, name, payload):
                araya_yaz(agent)
                return ToolOutcome(content="OK", is_error=False)

        agent.kill = SahteKill()
        agent.dispatcher = SahteDispatcher()

        class Blok:
            type = "tool_use"
            name = "screenshot"
            id = "t1"
            input = {}
            toolset_name = "computer"

        class Yanit:
            def __init__(self, content, stop):
                self.content = content
                self.stop_reason = stop

        yanitlar = [Yanit([Blok()], "tool_use"), Yanit([], "end_turn")]
        agent._call_model = lambda turn, effort=None: yanitlar.pop(0)
        agent._prune_images = lambda: None

        gorulen = []
        agent.run("bir iş yap", Turn(on_interjection=gorulen.append))
        return agent, gorulen

    def test_cumle_arac_sonuclarindan_sonra_geliyor(self):
        # API tool_result bloklarının kullanıcı turunun başında olmasını
        # istiyor; metin bloğu araya girerse istek reddediliyor.
        agent, gorulen = self._kosu(lambda a: a.interject("bir de şunu ekle"))
        kullanici = [m for m in agent.messages if m["role"] == "user"][-1]
        turler = [b["type"] if isinstance(b, dict) else b.type
                  for b in kullanici["content"]]
        assert turler[0] == "tool_result"
        assert turler[-1] == "text"
        assert "bir de şunu ekle" in kullanici["content"][-1]["text"]

    def test_arayuze_haber_veriliyor(self):
        _, gorulen = self._kosu(lambda a: a.interject("şunu da yap"))
        assert gorulen == ["şunu da yap"]

    def test_hicbir_sey_yazilmazsa_mesaj_degismiyor(self):
        agent, gorulen = self._kosu(lambda a: None)
        kullanici = [m for m in agent.messages if m["role"] == "user"][-1]
        assert all(b["type"] == "tool_result" for b in kullanici["content"])
        assert gorulen == []

    def test_calisirken_yazilan_dusmuyor(self):
        # Köprü: meşgulken gelen talimat sessizce atılmıyor, kuyruğa giriyor.
        import inspect
        from app import agent_bridge

        kaynak = inspect.getsource(agent_bridge.AgentBridge.run)
        assert "interject" in kaynak
        assert "self._busy: return" not in kaynak.replace("\n", " ")

    def test_yazi_alani_mesgulken_kapanmiyor(self):
        # Kapalı bir alana yazamazsın; araya girmenin tek yolu o alan.
        import inspect
        from app import commandbar

        kaynak = inspect.getsource(commandbar.CommandBar.set_busy)
        assert "field.setEnabled" not in kaynak


class TestIdeGorunumu:
    """Ajanın yazdığı kodu gösteren panel."""

    def test_ortak_klasor_tek_dosyada_kendi_klasoru(self, tmp_path):
        import doppel as ajan
        (tmp_path / "a.py").write_text("x")
        assert ajan._ortak_klasor([str(tmp_path / "a.py")]) == str(tmp_path.resolve())

    def test_ortak_klasor_alt_klasorleri_topluyor(self, tmp_path):
        import doppel as ajan
        (tmp_path / "src").mkdir()
        (tmp_path / "tests").mkdir()
        kok = ajan._ortak_klasor([
            str(tmp_path / "src" / "a.py"), str(tmp_path / "tests" / "b.py"),
        ])
        assert kok == str(tmp_path.resolve())

    def test_ortak_klasor_farkli_surucude_patlamiyor(self):
        # `commonpath` farklı sürücülerde ValueError atıyor; panel bu
        # yüzden hiç açılmamamalı değil.
        import doppel as ajan
        assert ajan._ortak_klasor([r"C:\a\x.py", r"D:\b\y.py"]).startswith("C:")

    def test_agac_gurultuyu_atliyor(self, tmp_path, qt_app):
        # __pycache__ içinde ajanın yazdığı kodu aramak istemiyorsun.
        from app import fluent
        from app.ide import IdeView

        (tmp_path / "__pycache__").mkdir()
        (tmp_path / ".git").mkdir()
        (tmp_path / "gercek.py").write_text("x = 1", encoding="utf-8")
        ide = IdeView(fluent.tokens(), str(tmp_path))
        agac = ide.tree
        adlar = {agac.topLevelItem(i).text(0) for i in range(agac.topLevelItemCount())}
        assert adlar == {"gercek.py"}

    def test_ayni_dosya_iki_sekme_acmiyor(self, tmp_path, qt_app):
        from app import fluent
        from app.ide import IdeView

        yol = tmp_path / "a.py"
        yol.write_text("print(1)", encoding="utf-8")
        ide = IdeView(fluent.tokens(), str(tmp_path))
        ide.open_file(str(yol))
        ide.open_file(str(yol))
        assert ide.tabs.count() == 1

    def test_sekme_kapaninca_esleme_kayiyor(self, tmp_path, qt_app):
        # Indeksler kaydığında eski eşleme yanlış sekmeyi gösteriyordu.
        from app import fluent
        from app.ide import IdeView

        yollar = []
        for ad in ("a.py", "b.py", "c.py"):
            p = tmp_path / ad
            p.write_text(f"# {ad}", encoding="utf-8")
            yollar.append(str(p))
        ide = IdeView(fluent.tokens(), str(tmp_path))
        for y in yollar:
            ide.open_file(y)
        ide._close(0)
        ide.open_file(yollar[2])
        assert ide.tabs.count() == 2
        assert ide.tabs.tabText(ide.tabs.currentIndex()) == "c.py"

    def test_okunamayan_dosya_panelde_soyluyor(self, tmp_path, qt_app):
        from app import fluent
        from app.ide import IdeView

        ide = IdeView(fluent.tokens(), str(tmp_path))
        ide.open_file(str(tmp_path / "yok.py"))
        assert "Could not read" in ide.tabs.currentWidget().editor.toPlainText()

    def test_arama_buyuk_kucuk_harf_ayirmiyor(self, tmp_path, qt_app):
        from app import fluent
        from app.ide import CodePane

        pane = CodePane(fluent.tokens(), "a.py", "Path = 1\npath = 2\n")
        assert pane.editor.search("PATH") == 2

    def test_cetvel_basamak_sayisina_gore_genisliyor(self, qt_app):
        from app import fluent
        from app.ide import Editor

        dar = Editor(fluent.tokens(), "a.py", "x\n" * 5)
        genis = Editor(fluent.tokens(), "a.py", "x\n" * 500)
        assert genis.gutter_width() > dar.gutter_width()

    def test_ayni_dosya_yeniden_yazilinca_tazeleniyor(self, tmp_path, qt_app):
        # Sekmeyi sadece öne getirmek, diskteki koddan farklı bir şey
        # gösterirdi — kodu görmenin bütün amacı bu.
        from app import fluent
        from app.ide import IdeView

        yol = tmp_path / "a.py"
        yol.write_text("x = 1", encoding="utf-8")
        ide = IdeView(fluent.tokens(), str(tmp_path))
        ide.open_file(str(yol))
        yol.write_text("x = 2", encoding="utf-8")
        ide.open_file(str(yol))
        assert ide.tabs.count() == 1
        assert "x = 2" in ide.tabs.currentWidget().editor.toPlainText()


class TestTekOrnek:
    """İki ajan aynı fareyi süremez.

    Eski koruma `QLocalServer` ile kilitliyordu ve Windows'ta çalışmıyordu:
    `QLocalServer` adlandırılmış boru kullanıyor, Windows aynı adlı borunun
    birden çok örneğine izin veriyor, yani `listen()` herkese başarı
    dönüyor. Ölçüldü: aynı anda başlatılan altı örnekten dördü birden "ilk
    örneğim" dedi. Gerçekten iki pencere açıldı.
    """

    KOD = '''
import sys, time, glob, os.path
sys.path.insert(0, {kok!r})
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from app import single

# Kendi kilit adı: testin sonucu Ajan'ın o an açık olup olmamasına
# bağlı olmamalı.
single.MUTEX = r"Local\ajan-test-" + sys.argv[3]
single.SOCKET = "ajan-test-" + sys.argv[3]

app = QApplication([])
g = single.InstanceGuard()
# Bariyer: PySide6 içe aktarımı ~1 sn sürüyor ve o jitter süreçlerin
# claim()'e aynı anda girmesini engelliyordu — yarış hiç oluşmuyordu.
hazir = sys.argv[1] + ".hazir"
open(hazir, "w").close()
kalip = os.path.join(os.path.dirname(hazir), "*.hazir")
while len(glob.glob(kalip)) < int(sys.argv[2]):
    time.sleep(0.005)
sonuc = g.claim()
open(sys.argv[1], "w").write("1" if sonuc else "0")
if sonuc:
    QTimer.singleShot(2500, app.quit)   # kilidi tut ki rakipler görsün
    app.exec()
'''

    def test_es_zamanli_baslatmada_tek_kazanan(self, tmp_path):
        import subprocess, sys as _sys
        from pathlib import Path as _Path

        kok = _Path(__file__).resolve().parent.parent
        kod = tmp_path / "cocuk.py"
        kod.write_text(self.KOD.format(kok=str(kok)), encoding="utf-8")

        N = 4
        etiket = tmp_path.name
        ciktilar = [tmp_path / f"{i}.txt" for i in range(N)]
        surecler = [
            subprocess.Popen([_sys.executable, str(kod), str(o), str(N), etiket])
            for o in ciktilar
        ]
        for p in surecler:
            p.wait(timeout=90)
        kazanan = sum(1 for o in ciktilar if o.exists() and o.read_text() == "1")
        assert kazanan == 1, f"{N} eş zamanlı başlatmada {kazanan} kazanan"

    def test_coken_ornekten_sonra_acilabiliyor(self, tmp_path):
        # Mutex'in tutamacını çekirdek bırakıyor; ölü kilit diye bir şey yok.
        import subprocess, sys as _sys, time
        from pathlib import Path as _Path

        kok = _Path(__file__).resolve().parent.parent
        kod = tmp_path / "tut.py"
        kod.write_text('''
import sys, time
sys.path.insert(0, {kok!r})
from PySide6.QtWidgets import QApplication
from app import single
single.MUTEX = r"Local\ajan-test-" + {etiket!r}
single.SOCKET = "ajan-test-" + {etiket!r}
app = QApplication([])
g = single.InstanceGuard()
print("EVET" if g.claim() else "HAYIR", flush=True)
time.sleep(60)
'''.format(kok=str(kok), etiket=tmp_path.name), encoding="utf-8")

        def baslat():
            return subprocess.Popen(
                [_sys.executable, str(kod)], stdout=subprocess.PIPE, text=True
            )

        ilk = baslat()
        try:
            assert ilk.stdout.readline().strip() == "EVET"
            ikinci = baslat()
            try:
                assert ikinci.stdout.readline().strip() == "HAYIR"
            finally:
                ikinci.kill()
        finally:
            ilk.kill()
            ilk.wait()

        time.sleep(0.5)
        ucuncu = baslat()
        try:
            assert ucuncu.stdout.readline().strip() == "EVET"
        finally:
            ucuncu.kill()


class TestKosuHalkasi:
    """Halka turun şeklini taşıyor; yanlış taşırsa yokluğundan kötü."""

    def _ring(self, qt_app):
        from app import fluent
        from app.stream import RunRing
        return RunRing(fluent.tokens())

    def test_yay_dilim_sonuna_varmiyor(self, qt_app):
        # Bir adımın bittiğini, bitmeden önce iddia edemez.
        from app.stream import ARC_CEILING
        r = self._ring(qt_app)
        r.begin()
        r.step("screenshot")
        for _ in range(500):
            r.pulse()
        assert r._arc_target <= ARC_CEILING < 1.0

    def test_biten_adim_kalici_dilim_birakiyor(self, qt_app):
        r = self._ring(qt_app)
        r.begin()
        for arac, hata in (("screenshot", False), ("run_shell", True)):
            r.step(arac)
            r.settle(hata)
        assert r._done == [False, True]

    def test_yeni_tur_onceki_sekli_siliyor(self, qt_app):
        r = self._ring(qt_app)
        r.begin()
        r.step("type")
        r.settle(False)
        r.begin()
        assert r._done == []

    def test_gizlenince_hareket_duruyor(self, qt_app):
        # Halka görünür olduğu sürece nefes alıyor — bekleme animasyonu
        # tur bitince de sürüyor. Ama görünmeyeni canlandırmak boşa iş:
        # gizlenince saatten iniyor.
        from PySide6.QtCore import Qt
        r = self._ring(qt_app)
        r.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        r.show()
        r.begin()
        assert r._abone
        r.hide()
        assert not r._abone

    def test_dusen_adim_renkten_bagimsiz_ayirt_ediliyor(self):
        # Bu temada accent #e7babd, critical #ff99a4 — ince bir işarette
        # ikisi aynı görünüyor. Ayrım biçimde olmak zorunda: düşen adımın
        # işareti kalınlaşıyor.
        from app.stream import FAIL_WIDTH
        assert FAIL_WIDTH > 1.0

    def test_her_aracin_kendi_cizimi_var(self):
        # "Yaptığı işe göre görsel" — jenerik kıvılcıma düşen araç kalmasın.
        from backend.agent.tools import CUSTOM_TOOLS
        from app.glyphs import TOOL_GLYPH
        eksik = [t["name"] for t in CUSTOM_TOOLS if t["name"] not in TOOL_GLYPH]
        assert eksik == [], eksik


class TestAkanMetin:
    def _m(self, qt_app, metin=""):
        from app import fluent
        from app.stream import AkanMetin
        w = AkanMetin(fluent.tokens())
        w.resize(320, 100)
        if metin:
            w.set_text(metin)
        return w

    def test_parcalar_birikiyor(self, qt_app):
        w = self._m(qt_app)
        for p in ("Mer", "haba ", "dünya"):
            w.append(p)
        assert w.text() == "Merhaba dünya"

    def test_imlec_yalnizca_akarken(self, qt_app):
        # İmleçsiz akan metin bitmiş cevap gibi okunuyordu; bitmiş cevapta
        # yanıp sönen imleç de "hâlâ yazıyor" diye yalan söyler.
        w = self._m(qt_app, "bir şey")
        assert not w._blink.isActive()
        w.set_live(True)
        assert w._blink.isActive()
        w.set_live(False)
        assert not w._blink.isActive()

    def test_uzun_metin_daha_yuksek(self, qt_app):
        kisa = self._m(qt_app, "tek satır")
        uzun = self._m(qt_app, "uzun bir cümle " * 30)
        assert uzun.heightForWidth(320) > kisa.heightForWidth(320)

    def test_bos_metin_yer_kaplamiyor(self, qt_app):
        assert self._m(qt_app).heightForWidth(320) == 0

    def test_secim_kopyalanabiliyor(self, qt_app):
        # Kendi düzenini kuran bir widget, seçmeyi kendi eklemezse kaybeder.
        from PySide6.QtGui import QGuiApplication
        w = self._m(qt_app, "kopyalanacak metin")
        w._sel = (0, 12)
        w.keyPressEvent(_copy_event())
        assert QGuiApplication.clipboard().text() == "kopyalanacak"

    def test_paragraf_yapismiyor(self, qt_app):
        # Ekranda görüldü: "…(lightest).One caveat" — iki paragraf
        # birbirine yapışmış. Tek bir `QTextLayout` satır sonunu bilmiyor,
        # `\n` sıradan bir karakter ve satır kırılımını yalnızca sarma
        # üretiyor. Ölçtüm: iki paragraflı metin tek satıra iniyordu.
        w = self._m(qt_app, "Birinci bitti.\n\nİkinci başladı.")
        bloklar = w._build(320)
        assert len(bloklar) == 2
        assert bloklar[0][0].text() == "Birinci bitti."
        assert bloklar[1][0].text() == "İkinci başladı."
        # İkinci blok birincinin altında, üstünde değil.
        assert bloklar[1][2] > bloklar[0][2]

    def test_paragraf_bosluk_biraktiriyor(self, qt_app):
        tek = self._m(qt_app, "Birinci bitti. İkinci başladı.")
        cift = self._m(qt_app, "Birinci bitti.\n\nİkinci başladı.")
        assert cift.heightForWidth(320) > tek.heightForWidth(320)

    def test_yildizlar_ekranda_yok(self, qt_app):
        # `**Reacher**` diye basılan bir cevap, biçimlendirmeyi çizmek
        # yerine kaynağını gösteriyor demektir.
        w = self._m(qt_app, "en iyisi **Reacher** ve `notlar.md`")
        assert w.text() == "en iyisi Reacher ve notlar.md"
        assert w._kalin == [(9, 7)]
        assert w._kod == [(20, 9)]

    def test_yarim_isaret_oldugu_gibi_duruyor(self, qt_app):
        # Akış sırasında `**` yarım geliyor. Kapanmayan bir işaret
        # eşleşmiyor ve olduğu gibi duruyor; kapanınca kayboluyor.
        w = self._m(qt_app)
        w.append("yarım **kal")
        assert w.text() == "yarım **kal"
        w.append("ın** bitti")
        assert w.text() == "yarım kalın bitti"

    def test_kopyalanan_metinde_isaret_yok(self, qt_app):
        from PySide6.QtGui import QGuiApplication
        w = self._m(qt_app, "**hepsi** kalın")
        w._sel = (0, len(w.text()))
        w.keyPressEvent(_copy_event())
        assert QGuiApplication.clipboard().text() == "hepsi kalın"

    def test_odak_gidince_secim_kalkiyor(self, qt_app):
        # Kalmıyordu: çubuğa yazmak için Ctrl+A'ya basmak dökümü seçiyor
        # ve sekiz satırlık cevap sonsuza kadar vurgulu kalıyordu.
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QFocusEvent
        w = self._m(qt_app, "seçili kalmasın")
        w._sel = (0, 6)
        w.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut))
        assert w._sel == (0, 0)

    def test_tikladigin_yer_dogru_paragrafta(self, qt_app):
        w = self._m(qt_app, "Birinci bitti.\n\nİkinci başladı.")
        bloklar = w._build(320)
        from PySide6.QtCore import QPointF
        _, yer, blok_y = bloklar[1]
        nokta = QPointF(w.PAD_X + 2, w.PAD_TOP + blok_y + 4)
        assert w._cursor_at(nokta) >= yer


def _copy_event():
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent
    return QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_C,
                     Qt.KeyboardModifier.ControlModifier, "c")


class TestAkisBaglantisi:
    """Akış çekirdekte vardı ama arayüz onu dinlemiyordu."""

    def test_arayuz_akisi_dinliyor(self):
        import inspect
        import doppel as ajan
        kaynak = inspect.getsource(ajan.main)
        assert "bridge.said.connect" in kaynak
        assert "bridge.pulse.connect" in kaynak

    def test_nabiz_kisiliyor(self):
        # Saniyede yüzlerce parça geliyor; her birini arayüze taşımak
        # çizilenden çok sinyal göndermek olurdu.
        from backend.agent.loop import PULSE_MIN_GAP
        assert 0.02 <= PULSE_MIN_GAP <= 0.2

    def test_bitis_akan_metni_silmiyor(self):
        # Tur bitince say() çağırmak, ilk adımların anlatımını siler.
        import inspect
        import doppel as ajan
        kaynak = inspect.getsource(ajan.main)
        govde = kaynak[kaynak.index("def on_finished"):]
        govde = govde[:govde.index("def on_failed")]
        assert "end_stream" in govde


class TestAkisDokumu:
    """Çubuktaki döküm: senin cümlen, adımlar, ajanın anlattıkları."""

    def _akis(self, qt_app):
        from app import fluent
        from app.stream import Akis
        a = Akis(fluent.tokens())
        a.resize(398, 200)
        return a

    def test_her_adim_kendi_cizimini_aliyor(self, qt_app):
        # "Olaya göre farklı görsel" — hepsine aynı simgeyi koymak, akışı
        # ancak metni okuyarak anlaşılır bir liste yapardı.
        from app.glyphs import glyph_for
        a = self._akis(qt_app)
        for arac in ("screenshot", "type", "run_shell", "write_file", "remote_run"):
            a.add_step(arac, "iş", "hedef")
        cizimler = [
            a._kutu.itemAt(i).widget()._key for i in range(a._kutu.count())
        ]
        assert cizimler == [glyph_for(x) for x in
                            ("screenshot", "type", "run_shell", "write_file", "remote_run")]
        assert len(set(cizimler)) == 5, "beş farklı iş, beş farklı çizim"

    def test_satirlar_yukseklik_bildiriyor(self, qt_app):
        # `setFixedHeight` `sizeHint`i değiştirmiyor: düz bir QWidget
        # geçersiz (-1) ipucu veriyor ve düzen satırı hiç saymıyordu —
        # dört adım sıfır sayılıp son satır kırpılıyordu.
        from app.stream import AdimSatiri, ROW_H
        from app import fluent
        satir = AdimSatiri(fluent.tokens(), "screenshot", "Bakıyor", "Ekran 2")
        assert satir.sizeHint().height() == ROW_H

    def test_yukseklik_butun_satirlari_topluyor(self, qt_app):
        a = self._akis(qt_app)
        bos = a.heightForWidth(398)
        a.add_user("bir iş yap")
        tek = a.heightForWidth(398)
        for _ in range(4):
            a.add_step("screenshot", "Bakıyor", "Ekran 1")
        cok = a.heightForWidth(398)
        from app.stream import ROW_H
        assert bos == 0 < tek < cok
        assert cok - tek >= 4 * ROW_H

    def test_dusen_adim_kirmiziya_donuyor(self, qt_app):
        a = self._akis(qt_app)
        a.add_step("run_shell", "Komut", "curl")
        a.mark_last(True)
        assert a._son_adim._tone == "hata"

    def test_tek_imlec(self, qt_app):
        # İki yerde birden yanıp sönen imleç, ikisinin de yazıldığını
        # söylerdi.
        from app.stream import AkanMetin
        a = self._akis(qt_app)
        a.stream("birinci")
        a.add_step("screenshot", "Bakıyor", "")
        a.stream("ikinci")
        canli = [a._kutu.itemAt(i).widget() for i in range(a._kutu.count())]
        canli = [w for w in canli if isinstance(w, AkanMetin) and w._live]
        assert len(canli) == 1

    def test_yeni_tur_dokumu_siliyor(self, qt_app):
        a = self._akis(qt_app)
        a.add_user("iş")
        a.add_step("type", "Yazıyor", "")
        a.clear()
        assert a.is_empty() and a.heightForWidth(398) == 0

    def test_cubuk_dokumu_gosteriyor(self, qt_app):
        # Çubuk zaten gözünün olduğu yer; adımları görmek için ana
        # pencereye bakmak gerekmemeli.
        import inspect
        import doppel as ajan
        kaynak = inspect.getsource(ajan.main)
        assert "bar.add_step(" in kaynak
        assert "bar.add_user(" in kaynak
        assert "bar.settle_step(" in kaynak


class TestAjanKafasi:
    """Yüz. Hareketi süs değil, ajanın ne yaptığı."""

    def _k(self, qt_app):
        from app import fluent
        from app.kafa import AjanKafasi
        return AjanKafasi(fluent.tokens())

    def test_arac_yuze_donusuyor(self):
        from app.kafa import face_for
        assert face_for("screenshot") == "bakiyor"
        assert face_for("left_click") == "tikliyor"
        assert face_for("type") == "yaziyor"
        assert face_for("write_file") == "yaziyor"

    def test_tanimadigi_arac_dusunuyor(self):
        # Uydurma bir ifade koymaktansa nötr kalmak dürüst.
        from app.kafa import face_for
        assert face_for("hic_boyle_bir_arac_yok") == "dusunuyor"

    def test_bakis_sinirlanmis(self, qt_app):
        # Gözbebeği kafanın dışına çıkamaz.
        k = self._k(qt_app)
        k.look_at(9.0, -9.0)
        assert k._gaze_hedef.x() == 1.0 and k._gaze_hedef.y() == -1.0

    def test_bakis_gercek_koordinattan(self):
        # Rastgele kıpırdayan bir maskot süs olurdu; bakış tıklanacak yeri
        # gösteriyor.
        import inspect
        import doppel as ajan
        kaynak = inspect.getsource(ajan.main)
        assert "look_at" in kaynak and "coordinate" in kaynak

    def test_bostayken_hareket_yok(self, qt_app):
        # Boşta kırpan bir yüz, bir şey oluyormuş gibi görünürdü.
        k = self._k(qt_app)
        assert not k._abone
        k.set_live(True)
        assert k._abone
        k.set_live(False)
        assert not k._abone

    def test_hata_hem_renk_hem_bicim(self, qt_app):
        # Bu temada kırmızı ile vurgu rengi birbirine yakın; hatayı renk
        # tek başına taşıyamaz. Yarıklar içeri dönüyor.
        k = self._k(qt_app)
        k.set_state("bosta")
        notr = k._slit_angle(1)
        k.set_state("hata")
        assert k._slit_angle(1) != notr
        assert k._slit_angle(1) * k._slit_angle(-1) < 0, "iki yarık ters dönmeli"

    def test_yariklar_paralel(self, qt_app):
        # Aynalı eğimde yüz sürekli hafif asık duruyordu: içe bakan iki
        # çizgi çatık kaş okunuyor. Kızgınlık yalnızca hataya ait.
        k = self._k(qt_app)
        k.set_state("bosta")
        assert k._slit_angle(1) == k._slit_angle(-1)

    def test_ezilme_sinirli(self, qt_app):
        # Kareler arasında biriken itkiler kafayı krep yapıyordu.
        from app.kafa import SQUASH_MAX
        k = self._k(qt_app)
        k.set_live(True)
        for _ in range(200):
            k.bump()
            k._tick()
        assert abs(k._squash) <= SQUASH_MAX

    def test_acilirken_goz_kirpmiyor(self, qt_app):
        # `_blink_at` sıfırdan başlıyordu: yüz açılır açılmaz gözünü
        # kırpıyor ve kısa turda ömrünü gözü kapalı geçiriyordu.
        k = self._k(qt_app)
        assert k._blink == 0 and k._blink_at > 10

    def test_halka_yuzun_durumunu_suruyor(self, qt_app):
        from app import fluent
        from app.stream import RunRing
        r = RunRing(fluent.tokens())
        r.begin()
        r.step("left_click")
        calisan = getattr(r.face, "_anim", r.face._state)
        r.settle(True)
        hatali = getattr(r.face, "_anim", r.face._state)
        r.finish()
        biten = getattr(r.face, "_anim", r.face._state)
        assert len({calisan, hatali, biten}) == 3, (calisan, hatali, biten)


class TestYuzSecimi:
    """Halkanın içindeki yüz iki kademeli: SVG, sonra kodla çizilen yüz."""

    def test_varlik_yoksa_cizilen_yuze_dusuyor(self, qt_app, monkeypatch):
        from app import fluent, stream, svgyuz
        from app.kafa import AjanKafasi
        monkeypatch.setattr(svgyuz, "varlik_var", lambda: False)
        assert isinstance(stream._yuz(fluent.tokens(), 52), AjanKafasi)

    def test_once_svg_seciliyor(self, qt_app):
        # SVG bizim: temaya uyuyor ve gerçek veriye sürekli tepki
        # verebiliyor.
        from app import fluent, stream
        from app.svgyuz import SvgYuz, varlik_var
        if not varlik_var():
            import pytest as _p
            _p.skip("svg yok")
        assert isinstance(stream._yuz(fluent.tokens(), 52), SvgYuz)

    def test_iki_yuz_ayni_arayuzu_sunuyor(self, qt_app):
        # Halka hangisini kullandığını bilmemeli.
        from app.kafa import AjanKafasi
        from app.svgyuz import SvgYuz
        gerekli = ("set_live", "set_state", "set_tool", "look_at",
                   "look_forward", "bump", "paint", "fill")
        for sinif in (SvgYuz, AjanKafasi):
            eksik = [a for a in gerekli if not hasattr(sinif, a)]
            assert eksik == [], f"{sinif.__name__}: {eksik}"


class TestHareketMotoru:
    """Hareket zamana bağlı olmalı, kare sayısına değil."""

    def test_yay_kare_hizindan_bagimsiz(self):
        # Eski kod `x += (hedef-x)*0.18` yapıyordu: 30 fps'te ve 120 fps'te
        # aynı hedefe **farklı sürelerde** varıyordu. Yani animasyonun
        # süresi donanıma bağlıydı.
        from app.motion import Spring

        def surede_nerede(fps, saniye):
            y = Spring(0.0, stiffness=180.0)
            y.to(1.0)
            dt = 1.0 / fps
            for _ in range(int(saniye * fps)):
                y.step(dt)
            return y.value

        a = surede_nerede(30, 0.5)
        b = surede_nerede(120, 0.5)
        c = surede_nerede(240, 0.5)
        assert abs(a - b) < 0.02, f"30 fps {a:.4f} vs 120 fps {b:.4f}"
        assert abs(b - c) < 0.01

    def test_eski_yontem_gercekten_bagimliydi(self):
        # Karşılaştırma: düzeltilen hatanın var olduğunu gösteriyor.
        def kare_basina(fps, saniye, k=0.18):
            x = 0.0
            for _ in range(int(saniye * fps)):
                x += (1.0 - x) * k
            return x
        assert kare_basina(30, 0.5) < 0.95 < kare_basina(120, 0.5)

    def test_kritik_sonum_hedefi_asmiyor(self):
        from app.motion import Spring
        y = Spring(0.0, stiffness=200.0)   # varsayılan sönüm kritik
        y.to(1.0)
        for _ in range(400):
            y.step(1 / 240)
        assert y.value <= 1.0005, y.value

    def test_yay_dinlenmeye_geciyor(self):
        from app.motion import Spring
        y = Spring(0.0, stiffness=180.0)
        y.to(1.0)
        assert not y.resting
        for _ in range(600):
            y.step(1 / 120)
        assert y.resting and abs(y.value - 1.0) < 0.002

    def test_buyuk_duraksama_firlatmiyor(self):
        # Pencere sürüklenirken ya da ağır bir araç çalışırken `dt` yarım
        # saniye geliyor; sınırsız bırakılsa yay tek karede fırlıyordu.
        from app.motion import MAX_DT, Spring
        y = Spring(0.0, stiffness=400.0)
        y.to(1.0)
        for _ in range(30):
            y.step(MAX_DT)
        assert -0.5 < y.value < 1.5

    def test_saat_abonesiz_duruyor(self, qt_app):
        # Boşta dönen zamanlayıcı dizüstünde pil yer.
        from app.motion import Clock
        s = Clock()
        assert not s.running
        f = lambda dt: None
        s.subscribe(f)
        assert s.running
        s.unsubscribe(f)
        assert not s.running

    def test_saat_ayni_aboneyi_iki_kez_almiyor(self, qt_app):
        from app.motion import Clock
        s = Clock()
        f = lambda dt: None
        s.subscribe(f); s.subscribe(f)
        assert len(s._aboneler) == 1

    def test_gecis_suresi_tutuyor(self):
        from app.motion import Tween
        g = Tween(0.3)
        for _ in range(int(0.3 * 240)):
            g.step(1 / 240)
        assert g.done and g.value > 0.99

    def test_titreme_soniyor(self):
        from app.motion import Shake
        s = Shake()
        s.hit()
        ilk = max(abs(s.step(1 / 120)) for _ in range(10))
        for _ in range(240):
            s.step(1 / 120)
        assert s.resting and ilk > 0.1

    def test_dalga_bir_kez(self):
        from app.motion import Ripple
        d = Ripple(0.4)
        assert not d.alive
        d.hit()
        assert d.alive and d.alpha > 0.9
        for _ in range(int(0.4 * 240) + 2):
            d.step(1 / 240)
        assert not d.alive and d.alpha == 0.0

    def test_ease_out_back_asip_donuyor(self):
        from app.motion import ease_out_back
        assert max(ease_out_back(i / 100) for i in range(101)) > 1.0
        assert abs(ease_out_back(1.0) - 1.0) < 1e-6
        assert abs(ease_out_back(0.0)) < 1e-6


class TestSvgYuz:
    """Poz değiştiren gövde, kendi başına bakan gözler."""

    def _y(self, qt_app):
        from app import fluent
        from app.svgyuz import SvgYuz, varlik_var
        if not varlik_var():
            import pytest as _p
            _p.skip("svg yok")
        return SvgYuz(fluent.tokens(), 64)

    def test_butun_pozlar_ayni_nokta_sayisinda(self):
        # Kritik: sayılar farklı olsaydı iki şekil arasında geçiş yol
        # eşleştirme problemi olurdu ve ara karelerde şekil bozulurdu.
        from app.svgyuz import ANIMASYON, _poz_noktalari, varlik_var
        if not varlik_var():
            import pytest as _p
            _p.skip("svg yok")
        adlar = {p for a in ANIMASYON.values() for p in a[:2]}
        sayilar = {len(_poz_noktalari(ad)) for ad in adlar}
        assert len(sayilar) == 1 and sayilar.pop() > 100

    def test_gozler_svg_parcali(self):
        from PySide6.QtCore import QByteArray
        from PySide6.QtSvg import QSvgRenderer
        from app.svgyuz import SVG_DIZIN, varlik_var
        if not varlik_var():
            import pytest as _p
            _p.skip("svg yok")
        r = QSvgRenderer(QByteArray((SVG_DIZIN / "gozler.svg").read_bytes()))
        assert r.isValid()
        for ad in ("goz-normal-sol", "goz-genis-sag", "goz-kapali-sol",
                   "goz-kizgin-sag", "goz-gulen-sol"):
            assert r.elementExists(ad), ad

    def test_her_is_kendi_animasyonunu_aliyor(self, qt_app):
        # İstenen buydu: bekleme, iş ve ofis ayrı görünmeli.
        y = self._y(qt_app)
        y.set_state("bosta")
        bosta = y._anim
        y.set_tool("left_click")
        is_ = y._anim
        y.set_tool("office_edit")
        ofis = y._anim
        y.set_state("dusunuyor")
        dusun = y._anim
        assert len({bosta, is_, ofis, dusun}) == 4, (bosta, is_, ofis, dusun)

    def test_ofis_araclarinin_hepsi_ofis(self, qt_app):
        y = self._y(qt_app)
        for arac in ("office_open", "office_read", "office_edit",
                     "office_save", "office_close", "office_history"):
            y.set_tool(arac)
            assert y._anim == "ofis", arac

    def test_animasyonlar_farkli_hizda(self):
        # Bekleme ağır, iş çabuk. Aynı hızda olsalar karakterleri olmazdı.
        from app.svgyuz import ANIMASYON
        assert ANIMASYON["is"][2] < ANIMASYON["ofis"][2] < ANIMASYON["bosta"][2]

    def test_govde_poz_arasinda_geciyor(self, qt_app):
        y = self._y(qt_app)
        y.set_state("bosta")
        y._faz = 0.0
        bas = y._govde_yolu().elementAt(3)
        y._faz = 1.0
        son = y._govde_yolu().elementAt(3)
        assert (bas.x, bas.y) != (son.x, son.y)

    def test_faz_ileri_geri_gidiyor(self, qt_app):
        y = self._y(qt_app)
        y.set_state("bosta")
        for _ in range(2000):
            y.step(1 / 60)
            assert 0.0 <= y._faz <= 1.0

    def test_renk_temadan_geliyor(self, qt_app):
        from app import fluent
        from app.svgyuz import YER_OYUK, _gozler_renkli
        metin = bytes(_gozler_renkli(fluent.tokens())).decode("utf-8")
        assert YER_OYUK not in metin

    def test_govde_halkanin_rengiyle_ayni_degil(self, qt_app):
        # İkisi de vurgu rengi olsaydı yüz koşu kaydının önünü kapatırdı.
        y = self._y(qt_app)
        y._hata = False
        assert y._govde_rengi().lower() != y.t.accent.lower()

    def test_bakis_saga_sola_gidiyor(self, qt_app):
        # Açıkça istenen: sağa sola baksın.
        y = self._y(qt_app)
        y.look_at(-1.0, 0.0)
        for _ in range(200):
            y.step(1 / 120)
        sol = y._gaze_x.value
        y.look_at(1.0, 0.0)
        for _ in range(200):
            y.step(1 / 120)
        assert sol < -0.9 and y._gaze_x.value > 0.9

    def test_bostayken_bakis_geziniyor(self, qt_app):
        # Boştaki tek uydurma hareket. Çalışırken devreye girmemeli.
        y = self._y(qt_app)
        y.set_live(False)
        y._takip = False
        hedefler = set()
        for _ in range(4000):
            y.step(1 / 60)
            hedefler.add(round(y._gaze_x.target, 3))
        assert len(hedefler) > 2

    def test_calisirken_gezinme_yok(self, qt_app):
        y = self._y(qt_app)
        y.look_at(0.5, 0.0)
        for _ in range(4000):
            y.step(1 / 60)
        assert y._gaze_x.target == 0.5

    def test_ezilme_sinirli(self, qt_app):
        from app.svgyuz import SQUASH_MAX
        y = self._y(qt_app)
        for _ in range(300):
            y.bump()
            y.step(1 / 120)
        assert abs(y._squash.value) <= SQUASH_MAX + 1e-9

    def test_halka_yuzu_suruyor(self, qt_app):
        # Yüz halkanın içinde gizli bir çocuk widget: kendi `showEvent`i
        # gelmiyor, kendi başına saate abone olamıyor. Halka sürmezse
        # yüz hiç kıpırdamaz.
        from app import fluent
        from app.stream import RunRing
        r = RunRing(fluent.tokens())
        if not hasattr(r.face, "step"):
            import pytest as _p
            _p.skip("svg yüz değil")
        once = r.face._gecen
        r._tick(1 / 60)
        assert r.face._gecen > once

    def test_uretici_ayni_ciktiyi_veriyor(self):
        # Varlık elle düzenlenmiş olmamalı: betik neyse dosya o.
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
        import svg_yap
        from app.svgyuz import SVG_DIZIN, varlik_var
        if not varlik_var():
            import pytest as _p
            _p.skip("svg yok")
        for ad in svg_yap.POZLAR:
            yol = SVG_DIZIN / f"poz-{ad}.svg"
            assert yol.read_text("utf-8") == svg_yap.poz_svg(ad), ad
        assert (SVG_DIZIN / "gozler.svg").read_text("utf-8") == svg_yap.gozler_svg()


class TestSatirGirisi:
    def test_giris_bitiyor(self):
        from app.stream import Giris
        g = Giris()
        assert g.opacity < 0.5 and g.offset > 1
        for _ in range(int(Giris.SURE * 240) + 4):
            g.step(1 / 240)
        assert g.done and g.opacity > 0.99 and g.offset < 0.05

    def test_hata_satiri_titriyor(self, qt_app):
        from app import fluent
        from app.stream import AdimSatiri
        s = AdimSatiri(fluent.tokens(), "run_shell", "Komut", "curl")
        assert s._shake.resting
        s.set_tone("hata")
        assert not s._shake.resting
        for _ in range(400):
            s._tick(1 / 120)
        assert s._shake.resting


class TestSaatSizintisi:
    """Saat aboneyi hayatta tutmamalı ve ölmüş aboneyi çağırmamalı."""

    def test_abone_serbest_birakiliyor(self, qt_app):
        # Güçlü referans widget'ı kapandıktan sonra da yaşatıyordu; Qt
        # nesnesi C++ tarafında silinince geriye sarkan çağrı kalıp
        # süreci çökertiyordu — ölçüldü, segfault.
        import gc, weakref
        from app.motion import Clock

        class Sahte:
            def tik(self, dt):
                pass

        s = Clock()
        o = Sahte()
        z = weakref.ref(o)
        s.subscribe(o.tik)
        assert s.running
        del o
        gc.collect()
        assert z() is None, "saat aboneyi hayatta tutuyor"

    def test_olen_abone_cagrilmiyor_ve_saat_duruyor(self, qt_app):
        import gc
        from app.motion import Clock

        class Sahte:
            def __init__(self):
                self.n = 0

            def tik(self, dt):
                self.n += 1

        s = Clock()
        yasayan, olecek = Sahte(), Sahte()
        s.subscribe(yasayan.tik)
        s.subscribe(olecek.tik)
        del olecek
        gc.collect()
        s._tick()
        assert yasayan.n == 1
        assert len(s._aboneler) == 1

    def test_ayni_abone_iki_kez_eklenmiyor(self, qt_app):
        from app.motion import Clock

        class Sahte:
            def tik(self, dt):
                pass

        s = Clock()
        o = Sahte()
        s.subscribe(o.tik)
        s.subscribe(o.tik)
        assert len(s._aboneler) == 1
        s.unsubscribe(o.tik)
        assert not s.running


class TestBloubKaynagi:
    """Siluet kaynak SVG'den geliyor, uydurulmuyor."""

    def _k(self):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
        import bloub_kaynak
        if not bloub_kaynak.KAYNAK.is_file():
            import pytest as _p
            _p.skip("kaynak yok")
        return bloub_kaynak

    def test_kaynak_yolu_okunuyor(self):
        k = self._k()
        assert k._govde_yolu().startswith("M91.51")
        assert k._govde_yolu().count("C") == 64

    def test_noktalar_esit_aralikli(self, qt_app):
        # Ham düğüm noktaları eşit aralık vermezdi ve pozlar arası
        # geçişte şekil dalgalanırdı.
        import statistics
        k = self._k()
        n = k.taban_noktalari(160)
        assert len(n) == 160
        araliklar = [
            ((n[i][0] - n[i - 1][0]) ** 2 + (n[i][1] - n[i - 1][1]) ** 2) ** 0.5
            for i in range(1, len(n))
        ]
        ort = statistics.mean(araliklar)
        assert statistics.pstdev(araliklar) / ort < 0.25, "aralıklar eşit değil"

    def test_poz_siluetin_disina_cikmiyor(self, qt_app):
        # Bütün pozlar aynı yaratık olmalı: alan çok değişirse başka bir
        # şeye dönüşmüş demektir.
        k = self._k()
        taban = k.taban_noktalari()

        def alan(p):
            return abs(sum(p[i][0] * p[i - 1][1] - p[i - 1][0] * p[i][1]
                           for i in range(len(p)))) / 2

        temel = alan(taban)
        for ad, kw in k.POZLAR.items():
            oran = alan(k.poz(taban, **kw)) / temel
            assert 0.85 < oran < 1.2, f"{ad}: alan oranı {oran:.2f}"

    def test_butun_pozlar_ayni_nokta_sayisinda(self, qt_app):
        k = self._k()
        taban = k.taban_noktalari()
        assert {len(k.poz(taban, **kw)) for kw in k.POZLAR.values()} == {len(taban)}

    def test_goz_olculeri_kaynaktan(self):
        # Uydurma değil: kaynaktaki matrislerden çevrildi.
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
        import svg_yap
        from bloub_kaynak import KAYNAK
        if not KAYNAK.is_file():
            import pytest as _p
            _p.skip("kaynak yok")
        assert len(svg_yap.GOZ_KONUM) == 2
        sol, sag = svg_yap.GOZ_KONUM
        # Yatay kapsül: en boydan büyük.
        assert svg_yap.GOZ_W > svg_yap.GOZ_H
        # İkisi tam ayna değil — elle çizilmiş olmasının izi.
        assert abs(sol[2]) != abs(sag[2])


class TestBaloncuk:
    """Maskot ne yaptığını çizmiyor, **yazıyor**.

    Elinde nesne tutan bir maskot vardı ve altı tur uğraştıktan sonra
    kaldırıldı: 78 pikselde bir kol iki piksel ediyor ve hiçbir ayar bunu
    çözmüyor. Yerine baloncuk.
    """

    def _b(self, qt_app):
        from app import fluent
        from app.baloncuk import Baloncuk

        return Baloncuk(fluent.tokens())

    def test_yazi_harf_harf_akiyor(self, qt_app):
        b = self._b(qt_app)
        b.soyle("Dosya yazıyor: notlar.md")
        assert b.akiyor
        b._tick(10.0)
        assert not b.akiyor, "on saniyede yazı bitmeliydi"

    def test_ortak_on_ek_korunuyor(self, qt_app):
        # "Dosya yazıyor: a.md" ile "Dosya yazıyor: b.md" arasında
        # baloncuk boşalıp yeniden dolsaydı, gözün takip ettiği şey iş
        # değil animasyon olurdu.
        b = self._b(qt_app)
        b.soyle("Dosya yazıyor: a.md")
        b._tick(10.0)
        b.soyle("Dosya yazıyor: b.md")
        assert b._gorunen >= len("Dosya yazıyor: ")

    def test_ayni_metin_akisi_sifirlamiyor(self, qt_app):
        b = self._b(qt_app)
        b.soyle("Ekran görüntüsü alıyor")
        b._tick(10.0)
        b.soyle("Ekran görüntüsü alıyor")
        assert not b.akiyor

    def test_bos_metin_kapatiyor(self, qt_app):
        b = self._b(qt_app)
        b.soyle("Bir şey")
        b.soyle("")
        assert b._giris.target == 0.0

    def test_temizle_her_seyi_siliyor(self, qt_app):
        b = self._b(qt_app)
        b.soyle("Bir şey")
        b.temizle()
        assert b._tam == "" and not b.isVisible()

    def test_govde_yaziya_yapisiyor(self, qt_app):
        # Sütunun tamamını kaplayan bir baloncuk konuşma gibi durmuyor,
        # devre dışı bir metin alanı gibi duruyor.
        b = self._b(qt_app)
        b.resize(400, 40)
        b.soyle("Klasöre bakıyor")
        kisa = b._govde(b._duzen(b._ic_en(), b._gosterim())).width()
        b.soyle("Komut çalıştırıyor: python -m pytest tests/ -q --tb=short")
        uzun = b._govde(b._duzen(b._ic_en(), b._gosterim())).width()
        assert kisa < uzun <= 400

    def test_sigmayan_yazi_uc_noktayla_kesiliyor(self, qt_app):
        # `QTextLayout` iki satırdan fazlasını sessizce düşürüyordu:
        # imleç ikinci satırın sonunda yanıp söner, baloncuk yazının
        # bittiğini söyler, oysa yolun ortasında kesilmiştir.
        b = self._b(qt_app)
        b.resize(180, 40)
        b.soyle("Komut çalıştırıyor: " + "uzun-bir-argument " * 20)
        gosterim = b._gosterim()
        assert gosterim.endswith("…")
        assert len(gosterim) < len(b._tam)
        b._tick(60.0)
        assert not b.akiyor, "kesilen yazı da bir yerde bitmeli"

    def test_sigan_yazi_kesilmiyor(self, qt_app):
        b = self._b(qt_app)
        b.resize(400, 40)
        b.soyle("Tabloyu açıyor: butce.xlsx")
        assert b._gosterim() == b._tam

    def test_saat_olu_widgetlari_dusuruyor(self, qt_app):
        # Zayıf başvuru yetmiyor: Qt bir widget'ın C++ tarafını silip
        # Python sarmalayıcıyı ayakta bırakabiliyor. O durumda çağrı
        # yapılıyor ve ölü nesneye dokunulduğu anda süreç düşüyor.
        from app.motion import _canli, clock

        b = self._b(qt_app)
        b.soyle("Bir şey")
        assert _canli(b._tick), "canlı widget düşürülmemeli"
        # `deleteLater` yetmiyor: sahipsiz ve hiç gösterilmemiş bir
        # widget'ı Qt hemen silmiyor. `shiboken6.delete` C++ tarafını
        # kesin olarak yok ediyor ve testin taklit etmek istediği durum
        # tam bu — Python sarmalayıcı yaşıyor, C++ nesnesi yok.
        from shiboken6 import delete

        delete(b)
        assert not _canli(b._tick), "C++ tarafı silinen widget düşmeli"
        clock()._tick()  # patlamamalı


class TestYarimKalanArac:
    """Durdurulan turdan sonra sohbet bozulmamalı.

    Gerçek hata: `messages.10: tool_use ids were found without
    tool_result blocks immediately after`. Bir tur durdurulunca
    `tool_use` içeren asistan mesajı geçmişte kalıyor ama sonuçları hiç
    eklenmiyor; sonraki her istek reddediliyor ve uygulamayı yeniden
    başlatmadan bir daha konuşamıyorsun.
    """

    class Blok:
        type = "tool_use"
        name = "screenshot"
        id = "toolu_test"
        input: dict = {}
        toolset_name = "computer"

    def _agent(self, mesajlar):
        from backend.agent.loop import Agent, _new_lock
        a = Agent.__new__(Agent)
        a.messages = mesajlar
        a._pending = []
        a._pending_lock = _new_lock()
        return a

    def _gecerli(self, mesajlar) -> bool:
        """API kuralı: her `tool_use`u hemen sonraki mesajda bir
        `tool_result` izlemeli."""
        for i, m in enumerate(mesajlar):
            kullanilan = [
                b for b in (m.get("content") or [])
                if (getattr(b, "type", None) == "tool_use"
                    or (isinstance(b, dict) and b.get("type") == "tool_use"))
            ]
            if not kullanilan:
                continue
            sonraki = mesajlar[i + 1] if i + 1 < len(mesajlar) else None
            if sonraki is None:
                return False
            doner = {
                b.get("tool_use_id")
                for b in (sonraki.get("content") or [])
                if isinstance(b, dict) and b.get("type") == "tool_result"
            }
            for b in kullanilan:
                kimlik = getattr(b, "id", None) or b.get("id")
                if kimlik not in doner:
                    return False
        return True

    def test_yarim_kalan_gecmis_gercekten_gecersiz(self):
        # Önce hatanın var olduğunu göster.
        yarim = [
            {"role": "user", "content": "bir iş yap"},
            {"role": "assistant", "content": [self.Blok()]},
            {"role": "user", "content": "bir şey daha"},
        ]
        assert not self._gecerli(yarim)

    def test_kapatinca_gecerli_oluyor(self):
        a = self._agent([
            {"role": "user", "content": "bir iş yap"},
            {"role": "assistant", "content": [self.Blok()]},
        ])
        assert a._close_open_tools("Durduruldu.") == "screenshot"
        a.messages.append({"role": "user", "content": "bir şey daha"})
        assert self._gecerli(a.messages)

    def test_sonuc_hata_olarak_isaretli(self):
        # Modele "bu adım olmadı" demek gerekiyor; sessiz bir boşluk
        # bıraksaydık ajan onu yapılmış sanardı.
        a = self._agent([
            {"role": "user", "content": "x"},
            {"role": "assistant", "content": [self.Blok()]},
        ])
        a._close_open_tools("Durduruldu.")
        sonuc = a.messages[-1]["content"][0]
        assert sonuc["is_error"] is True
        assert sonuc["tool_use_id"] == "toolu_test"
        assert sonuc["toolset_name"] == "computer"

    def test_kapatacak_bir_sey_yoksa_dokunmuyor(self):
        for gecmis in (
            [],
            [{"role": "user", "content": "x"}],
            [{"role": "assistant", "content": [{"type": "text", "text": "bitti"}]}],
        ):
            a = self._agent(list(gecmis))
            assert a._close_open_tools("Durduruldu.") is None
            assert a.messages == gecmis

    def test_tur_baslarken_onariliyor(self):
        # Durdurmadan sonra yazılan ilk mesaj geçmişi bozmamalı.
        import inspect
        from backend.agent.loop import Agent
        kaynak = inspect.getsource(Agent._sur)
        onarim = kaynak.index("_close_open_tools")
        ekleme = kaynak.index('"role": "user", "content": istek')
        assert onarim < ekleme, "onarım, yeni mesajı eklemeden önce olmalı"

    def test_durdurmada_hemen_kapatiliyor(self):
        # Bir sonraki tura bırakmak, arada başka bir şey yazılırsa o
        # mesajı da bozardı.
        import inspect
        from backend.agent.loop import Agent
        kaynak = inspect.getsource(Agent._sur)
        assert "except Aborted:" in kaynak
        blok = kaynak[kaynak.index("except Aborted:"):]
        assert "_close_open_tools" in blok[:400]


class TestDurdurma:
    """Çalışan turu durdurmak."""

    def _bar(self, qt_app):
        from app import fluent
        from app.commandbar import CommandBar
        return CommandBar(fluent.tokens())

    def test_dugme_yalnizca_calisirken(self, qt_app):
        # Boşta duran kırmızı bir düğme, basılacak bir şey varmış gibi
        # duruyor.
        bar = self._bar(qt_app)
        assert not bar.stop.isVisible()
        bar.set_busy(True)
        bar.show()
        assert bar.stop.isVisibleTo(bar)
        bar.set_busy(False)
        assert not bar.stop.isVisibleTo(bar)

    def test_dugme_sinyal_yayiyor(self, qt_app):
        bar = self._bar(qt_app)
        gelen = []
        bar.stop_requested.connect(lambda: gelen.append(1))
        bar.stop.clicked.emit()
        assert gelen == [1]

    def test_cubuk_durdurmaya_bagli(self):
        # Ana pencerede bir düğme vardı ama insan çubuğa bakıyor.
        import inspect
        import doppel as ajan
        kaynak = inspect.getsource(ajan.main)
        assert "bar.stop_requested.connect(bridge.stop)" in kaynak


class TestCubukBoyu:
    """Çubuk sessizce büyümesin.

    Ölçüldü: yedi adımlık bir turda 291 piksele çıkmıştı ve maskot
    sütununun yarısı boştu. Bu testler eşiği tutuyor.
    """

    def _dolu(self, qt_app):
        from app import fluent
        from app.commandbar import CommandBar
        from PySide6.QtWidgets import QApplication
        t = fluent.tokens()
        bar = CommandBar(t)
        bar.set_voice_available(False)
        bar.show()
        bar.clear_run()
        bar.add_user("Bütçeyi güncelle ve rapor et")
        bar.set_busy(True)
        bar.stream("Tamam, tabloyu açıyorum.")
        for a, b, d in (("screenshot", "Ekrana bakıyor", "Ekran 2"),
                        ("office_open", "Tabloyu açıyor", "butce.xlsx"),
                        ("office_edit", "Hücre yazıyor", "B12 = 4200"),
                        ("office_save", "Kaydediyor", "butce.xlsx")):
            bar.ring.step(a)
            bar.set_tool(a)
            bar.add_step(a, b, d)
            bar.settle_step(False)
        bar.stream("Bütçe güncellendi.")
        QApplication.processEvents()
        return bar

    def test_dolu_cubuk_kucuk_kaliyor(self, qt_app):
        # Eşik mutlak, ekranın oranı değil: ekran boyutu ortama göre
        # değişiyor ve test bir koşuda 1032, ötekinde 800 görüyordu.
        # Önemli olan çubuğun kendi boyu — ölçüldüğünde 291'di.
        bar = self._dolu(qt_app)
        assert bar.height() <= 280, bar.height()

    def test_bos_cubuk_kucuk(self, qt_app):
        from app import fluent
        from app.commandbar import CommandBar
        from PySide6.QtWidgets import QApplication
        bar = CommandBar(fluent.tokens())
        bar.show()
        QApplication.processEvents()
        assert bar.height() <= 130, bar.height()

    def test_maskot_cevabin_yerini_yemiyor(self, qt_app):
        # Maskot artık yalnızca halka: nesne yok, kol yok. Korunması
        # gereken tek şey cevabın okunabilir kalması.
        from app.commandbar import BAR_WIDTH
        bar = self._dolu(qt_app)
        dokum = BAR_WIDTH - 28 - 20 - bar.ring.width()
        assert dokum >= 380, f"cevap alanı {dokum} piksele düştü"


class TestArayuzKusurlari:
    """Ekran görüntüsünde görülen kusurlar. Hepsi ölçülerek bulundu."""

    def test_her_aracin_turkce_adi_var(self):
        # "wait wait" diye görünüyordu: 25 aracın etiketi yoktu ve ham
        # İngilizce adı iki kez yazılıyordu.
        import doppel as ajan
        from backend.agent.tools import CUSTOM_TOOLS
        computer = [
            "screenshot", "zoom", "cursor_position", "left_click",
            "right_click", "middle_click", "double_click", "triple_click",
            "mouse_move", "left_mouse_down", "left_mouse_up",
            "left_click_drag", "type", "key", "hold_key", "scroll", "wait",
        ]
        hepsi = computer + [t["name"] for t in CUSTOM_TOOLS]
        eksik = [a for a in hepsi if a not in ajan.TOOL_LABEL]
        assert eksik == [], eksik

    def test_detay_arac_adini_tekrar_etmiyor(self):
        import doppel as ajan
        op = ajan._describe("wait", {"duration": 2})
        assert op.tool == "Waiting"
        assert op.detail == ""

    def test_dokum_kaydirma_alanina_sigiyor(self, qt_app):
        # Ölçüldü: viewport 340, içerik 640 — metin sağdan kırpılıyordu.
        # Sebep, metin widget'ının en küçük boyut ipucunun genişliğe alt
        # sınır koyması.
        from PySide6.QtWidgets import QApplication
        from app import fluent
        from app.commandbar import CommandBar
        bar = CommandBar(fluent.tokens())
        bar.set_voice_available(False)
        bar.show()
        bar.clear_run()
        bar.set_busy(True)
        bar.stream("Çok uzun bir cümle " * 12)
        QApplication.processEvents()
        assert bar.reply.width() <= bar._reply_scroll.viewport().width()

    def test_metin_genislige_alt_sinir_koymuyor(self, qt_app):
        from app import fluent
        from app.stream import AkanMetin
        w = AkanMetin(fluent.tokens())
        w.resize(320, 40)
        w.set_text("uzun bir metin " * 20)
        assert w.minimumSizeHint().width() == 0

    def test_dugme_satiri_tasmiyor(self, qt_app):
        # "Butce ozetini goster y" diye kesiliyordu.
        from PySide6.QtWidgets import QApplication
        from app import fluent
        from app.buttons import ButtonStrip

        def komutlar():
            return [
                ("goster", "Bütçe özetini göster ve raporu maile ekle"),
                ("discord", "Discord'u aç ve ekrana getir"),
                ("genislet", "Sayfayı farklı genişliklerde test et"),
            ]

        strip = ButtonStrip(fluent.tokens())
        strip.setFixedWidth(412)
        strip.attach(None, komutlar)
        strip.show()
        QApplication.processEvents()
        for i in range(strip._rows.count()):
            w = strip._rows.itemAt(i).widget()
            if w is not None:
                assert w.x() + w.width() <= strip.width(), w.toolTip()

    def test_uzun_etiket_uc_noktayla_bitiyor(self, qt_app):
        # Kırpılmış bir yazı kesildiğini söylemiyor.
        from app import fluent
        from app.buttons import CHIP_MAX, ShortcutChip
        chip = ShortcutChip(
            fluent.tokens(), "x",
            "Bütçe özetini göster ve raporu maile ekle", "yetenek",
        )
        assert chip.text().endswith("…")
        assert chip.sizeHint().width() <= CHIP_MAX
        assert chip.toolTip().endswith("ekle"), "tam etiket ipucunda kalmalı"

    def test_akan_duzen_tek_yerde(self):
        # İki kopya, iki ayrı davranış demekti.
        import inspect
        from app import buttons, panel_view
        from app.flow import FlowLayout
        assert panel_view.FlowLayout is FlowLayout
        assert buttons.FlowLayout is FlowLayout
        assert "class FlowLayout" not in inspect.getsource(panel_view)


class TestAdimIzi:
    """Koşu kaydı artık daire değil, dikey iz."""

    def _r(self, qt_app):
        from app import fluent
        from app.commandbar import RING_SIZE
        from app.stream import RunRing
        r = RunRing(fluent.tokens(), RING_SIZE)
        r.resize(RING_SIZE, RING_SIZE)
        return r

    def test_iz_yuzun_solunda_kaliyor(self, qt_app):
        # Daire yerine dikey iz: adımlar yukarıdan aşağı diziliyor ve
        # figürün üstünden geçmiyor.
        from app.stream import TRACK_W, TRACK_X
        r = self._r(qt_app)
        assert r.yuz_kutusu().left() >= TRACK_X + TRACK_W

    def test_yuz_izin_saginda(self, qt_app):
        from app.stream import TRACK_W, TRACK_X
        r = self._r(qt_app)
        alan = r.width() - TRACK_X - TRACK_W
        boyut = alan * getattr(r.face, "fill", 0.56)
        sol = TRACK_X + TRACK_W + (alan - boyut) / 2
        assert sol >= TRACK_X + TRACK_W

    def test_adimlar_hala_birikiyor(self, qt_app):
        r = self._r(qt_app)
        r.begin()
        for arac, hata in (("screenshot", False), ("run_shell", True)):
            r.step(arac)
            r.settle(hata)
        assert r._done == [False, True]


class TestOnizlemeKaresi:
    def test_kare_yoksa_kutu_yok(self, qt_app):
        # Kare yokken işin çizimini gösteriyordu ve o çizim dökümde
        # zaten var: aynı satır iki kez, biri 72 piksellik kutuda.
        from app import fluent
        from app.commandbar import CommandBar, Operation
        bar = CommandBar(fluent.tokens())
        bar.show()
        bar.show_operation(Operation(tool="Yakınlaştırıyor", target="", detail="",
                                     thumbnail=None, key="zoom"))
        assert not bar.preview.isVisibleTo(bar)

    def test_kare_varsa_kutu_var(self, qt_app):
        from PySide6.QtGui import QPixmap
        from app import fluent
        from app.commandbar import CommandBar, Operation
        bar = CommandBar(fluent.tokens())
        bar.show()
        kare = QPixmap(40, 24)
        kare.fill()
        bar.show_operation(Operation(tool="Ekrana bakıyor", target="", detail="",
                                     thumbnail=kare, key="screenshot"))
        assert bar.preview.isVisibleTo(bar)
