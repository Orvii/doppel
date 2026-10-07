"""Tek örnek kilidi — Linux dalı, Windows'ta sahtelerle.

Gerçek çok süreçli yarış testi `test_computer.py::TestTekOrnek` içinde ve
o Windows mutex'ini ölçüyor; Linux bu makinede çalışmadığı için buradaki
testler `flock`u sahteliyor. Sınanan şey **karar mantığı**: kilidi
alamayan örnek "ilk örnek" demiyor, uyandırma deniyor, ve kilidi
bırakmak tanıtıcıyı gerçekten kapatıyor.

`fcntl` Windows'ta yok; sahte modül konuyor. Kilit dosyasının yolu
`XDG_RUNTIME_DIR` ile `tmp_path`'e çevriliyor — testin gerçek
`/run/user` dizinine dokunması, testi çalıştıran kişinin oturumunu
kilitleyebilirdi.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app import isletim, single


class SahteFcntl:
    """`flock`un kullanılan yüzeyi.

    Kilit **dosya başına** tutuluyor, tanıtıcı başına değil: gerçek
    `flock` böyle çalışıyor ve tanıtıcıya göre tutan bir sahte, aynı
    dosyanın iki ayrı `os.open`'ını ayrı kilit sayar — o zaman ikinci
    örneğin kaybetmesi gereken yer hiç sınanmamış olurdu. Yolu görmek
    için `os.open` sarmalanıyor.
    """

    LOCK_EX = 2
    LOCK_NB = 4
    LOCK_UN = 8

    def __init__(self) -> None:
        self.tutulan: set[str] = set()
        self.cagrilar: list[tuple[str, int]] = []
        #: {tanıtıcı: yol} — `os.open` sarmalaması dolduruyor.
        self.yollar: dict[int, str] = {}

    def flock(self, tanitici: int, islem: int) -> None:
        yol = self.yollar.get(tanitici, f"?#{tanitici}")
        self.cagrilar.append((yol, islem))
        if islem == self.LOCK_UN:
            self.tutulan.discard(yol)
            return
        if yol in self.tutulan:
            raise BlockingIOError(11, "kilit başkasında")
        self.tutulan.add(yol)


@pytest.fixture()
def linux(monkeypatch, tmp_path):
    """Linux dalı: sahte `fcntl` ve `tmp_path`'e çevrilmiş kilit dizini."""
    sahte = SahteFcntl()
    monkeypatch.setattr(isletim, "WINDOWS", False)
    # Windows'ta `fcntl` hiç import edilmiyor (guard'lı dal), o yüzden
    # `raising=False`: sahte yine de kuruluyor.
    monkeypatch.setattr(single, "fcntl", sahte, raising=False)
    monkeypatch.setattr(single, "ctypes", None)

    gercek_open = os.open

    def kaydeden_open(yol, *a, **k):
        tanitici = gercek_open(yol, *a, **k)
        sahte.yollar[tanitici] = str(yol)
        return tanitici

    monkeypatch.setattr(single.os, "open", kaydeden_open, raising=False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    # Yuva adı da izole: testin sonucu o an Ajan açık mı sorusuna
    # bağlı olmamalı.
    monkeypatch.setattr(single, "SOCKET", f"doppel-test-{tmp_path.name}")
    return sahte


class TestKilit:
    def test_ilk_ornek_kilidi_aliyor(self, linux, qt_app):
        g = single.InstanceGuard()
        try:
            assert g.claim()
            assert linux.tutulan, "flock hiç çağrılmadı"
            # Kilidi tutan tanıtıcı saklanmalı; kapanan tanıtıcı kilidi
            # bırakır ve o zaman ikinci örnek de "ilk örnek" derdi.
            assert g._kilit is not None
        finally:
            g.release()

    def test_bloklamayan_kilit_isteniyor(self, linux, qt_app):
        # `LOCK_NB` olmadan ikinci örnek, birincinin çıkmasını bekleyip
        # asılı kalırdı — çift tıklayan kişi için "hiç açılmadı".
        g = single.InstanceGuard()
        try:
            g.claim()
            islem = linux.cagrilar[0][1]
            assert islem & linux.LOCK_EX
            assert islem & linux.LOCK_NB
        finally:
            g.release()

    def test_birakma_kilidi_gercekten_birakiyor(self, linux, qt_app):
        ilk = single.InstanceGuard()
        assert ilk.claim()
        ilk.release()
        assert not linux.tutulan, "kilit bırakılmasına rağmen tutuluyor"
        # Ve yeniden alınabiliyor.
        ikinci = single.InstanceGuard()
        try:
            assert ikinci.claim()
        finally:
            ikinci.release()

    def test_iki_kez_birakmak_patlamiyor(self, linux, qt_app):
        g = single.InstanceGuard()
        g.claim()
        g.release()
        g.release()

    def test_kilit_dosyasi_soketten_turetiliyor(self, linux, tmp_path, qt_app):
        # Testler yuvayı kendi etiketiyle değiştiriyor; kilidin de izole
        # olması bundan bedava geliyor.
        yol = single.kilit_dosyasi()
        assert yol.parent == tmp_path
        assert single.SOCKET in yol.name
        assert yol.name.endswith(".lock")

    def test_kilit_dosyasi_kullaniciya_ozel(self, linux, qt_app):
        # Windows'taki `Local\\` önekinin eşi: aynı makinede başka bir
        # hesap kendi örneğini açabilmeli. Linux'ta ad, kimliği taşıyor;
        # Windows'ta `getuid` yok ve modül "x"e düşüyor — o da sınanıyor.
        beklenen = str(getattr(os, "getuid", lambda: "x")())
        assert beklenen in single.kilit_dosyasi().name

    def test_xdg_runtime_yoksa_gecici_dizine_duser(self, monkeypatch, tmp_path):
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
        monkeypatch.setattr(single, "SOCKET", "doppel-test-tmp")
        import tempfile

        yol = single.kilit_dosyasi()
        assert yol.parent == Path(tempfile.gettempdir())
        assert "/" not in yol.name and "\\" not in yol.name


class TestKaybedenOrnek:
    def test_kaybeden_uyandirmayi_deniyor(self, linux, qt_app, monkeypatch):
        # İkinci örnek sessizce kapanmıyor: çift tıklayan kişi bir şey
        # olmasını bekliyor. Var olanı öne getirme denemesi bu yüzden
        # şart ve burada kaydediliyor.
        g = single.InstanceGuard()
        assert g.claim()
        try:
            denenen: list[int] = []
            # Sınıf düzeyinde: uyandırmayı yapan **kaybeden** nesne ve o
            # burada sonradan kuruluyor.
            monkeypatch.setattr(single.InstanceGuard, "_wake_existing",
                                lambda self, ms: denenen.append(ms))
            ikinci = single.InstanceGuard()
            assert not ikinci.claim()
            assert denenen == [400]
            assert ikinci._kilit is None, "kaybeden kilidi tutuyor"
        finally:
            g.release()

    def test_kaybeden_kilit_birakiyor_dosya_kalmiyor(self, linux, qt_app,
                                                     monkeypatch):
        g = single.InstanceGuard()
        assert g.claim()
        try:
            monkeypatch.setattr(g, "_wake_existing", lambda ms: None)
            ikinci = single.InstanceGuard()
            assert not ikinci.claim()
            # Kaybeden `flock`u tutmamalı: tutsaydı birincinin kilit
            # bırakmasını engeller ve bir sonraki açılış "ilk örnek"
            # olamazdı.
            assert len(linux.tutulan) == 1
        finally:
            g.release()

    def test_kilit_dosyasi_acilamazsa_koruma_yok_ama_patlamiyor(
        self, linux, qt_app, monkeypatch, tmp_path
    ):
        # Kilit bir kolaylık, önkoşul değil: kilit dosyası açılamıyorsa
        # (salt-okunur dizin) uygulama yine açılmalı.
        # Dizin yerine dosya: `os.open` `ENOTDIR` ile düşüyor.
        engel = tmp_path / "engel"
        engel.write_text("", encoding="utf-8")
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(engel))
        g = single.InstanceGuard()
        try:
            assert g.claim(), "kilit alınamayınca uygulama açılmıyor"
            assert g._kilit is None
        finally:
            g.release()

    def test_sahte_fcntl_ile_ikinci_ornek_kaybediyor(self, linux, qt_app):
        # Uçtan uca karar: aynı süreçte iki koruma nesnesi, ikincisi
        # kaybetmeli. `flock` sahtesi kilitli tanıtıcıları gerçekten
        # tutuyor, yani bu iddia bayrağa değil kilit durumuna bakıyor.
        ilk = single.InstanceGuard()
        assert ilk.claim()
        try:
            ikinci = single.InstanceGuard()
            assert not ikinci.claim()
        finally:
            ilk.release()