"""MCP sayfası — bağlı dış sunucular ve getirdikleri araçlar.

Bu sayfanın işi listelemek değil, **okunur yapmak**. Bir MCP sunucusu
senin makinende senin haklarınla çalışan üçüncü tarafın kodu ve
araçlarının tanımı doğrudan modelin promptuna giriyor. O tanımları hiç
görmediğin bir yerde tutmak, ajana kimin ne söylediğini bilmemek demek.

Üç şey kasıtlı:

- **Hiçbir sunucu kendiliğinden açık değil.** Yapılandırmaya bir sunucu
  yazmak onu çalıştırmaya izin vermek değil; açma ayrı bir hareket.
- **Araç tanımları olduğu gibi görünüyor.** Kırpılıyor ama gizlenmiyor.
  "Tool poisoning" denen saldırı tam olarak burada yaşıyor: tanımın
  içine ajana verilmiş bir talimat konuyor.
- **Şüpheli tanım işaretleniyor, engellenmiyor.** Tarayıcıların yanlış
  pozitif oranı yüksek; engelleyen bir tarama, çalışan bir sunucuyu
  sebepsiz kapatır. Kararı okuyan veriyor.

`env` değerleri **hiç** gösterilmiyor — yalnızca hangi anahtarların
tanımlı olduğu. Bir anahtarın ekranda durması, ekran görüntüsüyle
paylaşılması demek.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from backend.mcp import ayar as ayar_mod
from backend.mcp.istemci import Baglanti

from . import isletim
from .fluent import RADIUS_CARD, RADIUS_CONTROL, Tokens, _blend, sarmali
from .glyphs import WorkGlyph

#: Kartta gösterilen en fazla araç. Playwright otuzdan fazla araç
#: veriyor ve hepsini birden çizmek sayfayı okunmaz yapıyor.
EN_COK_ARAC = 12

DURUM_ETIKET = {
    "kapali": "off",
    "baglaniyor": "connecting…",
    "hazir": "connected",
    "hata": "failed",
}


def _durum_rengi(t: Tokens, durum: str) -> str:
    return {
        "hazir": t.success,
        "hata": t.critical,
        "baglaniyor": t.caution,
    }.get(durum, t.text_tertiary)


def _rozet(t: Tokens, metin: str, renk: str) -> QLabel:
    etiket = QLabel(metin)
    etiket.setStyleSheet(
        f"color: {renk}; background: {_blend(renk, 0.12, t.background)};"
        f" border-radius: {RADIUS_CONTROL}px; padding: 2px 8px;"
        f" font-size: 11px; font-weight: 600;"
    )
    return etiket


class _SunucuKarti(QWidget):
    """Bir sunucu: durumu, araçları, uyarıları."""

    degisti = Signal()

    def __init__(self, t: Tokens, baglanti: Baglanti) -> None:
        super().__init__()
        self.t, self.baglanti = t, baglanti
        sunucu = baglanti.sunucu
        self.setObjectName("mcpKart")
        self.setStyleSheet(
            f"QWidget#mcpKart {{ background: {t.card};"
            f" border: 1px solid {t.stroke};"
            f" border-radius: {RADIUS_CARD}px; }}"
        )
        duzen = QVBoxLayout(self)
        duzen.setContentsMargins(16, 14, 14, 14)
        duzen.setSpacing(8)

        ust = QHBoxLayout()
        ust.setSpacing(10)
        ust.addWidget(WorkGlyph(t, "mcp__x__y", 34), 0,
                      Qt.AlignmentFlag.AlignTop)

        sol = QVBoxLayout()
        sol.setSpacing(3)
        ad = QLabel(sunucu.ad)
        ad.setStyleSheet(
            f"color: {t.text}; font-size: 14px; font-weight: 600;"
            f" border: none;"
        )
        sol.addWidget(ad)
        komut = QLabel(sunucu.anlat)
        komut.setStyleSheet(
            f"color: {t.text_tertiary}; font-size: 11.5px; border: none;"
            f" font-family: '{t.font_mono}';"
        )
        sol.addWidget(komut)
        if sunucu.ortam:
            # Değerler değil, yalnızca adlar. Bir anahtarın ekranda
            # durması, ekran görüntüsüyle paylaşılması demek.
            anahtarlar = QLabel("env: " + ", ".join(sorted(sunucu.ortam)))
            anahtarlar.setStyleSheet(
                f"color: {t.text_disabled}; font-size: 11px; border: none;"
            )
            sol.addWidget(anahtarlar)
        ust.addLayout(sol, 1)

        rozetler = QVBoxLayout()
        rozetler.setSpacing(6)
        rozetler.addWidget(
            _rozet(t, DURUM_ETIKET.get(baglanti.durum, baglanti.durum),
                   _durum_rengi(t, baglanti.durum)),
            0, Qt.AlignmentFlag.AlignRight,
        )
        if baglanti.hazir:
            rozetler.addWidget(
                _rozet(t, f"{len(baglanti.araclar)} tools", t.text_secondary),
                0, Qt.AlignmentFlag.AlignRight,
            )
        ust.addLayout(rozetler)

        dugmeler = QVBoxLayout()
        dugmeler.setSpacing(6)
        self._ac_kapa = QPushButton("Disable" if sunucu.acik else "Enable")
        self._ac_kapa.setFixedSize(84, 28)
        self._ac_kapa.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ac_kapa.setToolTip(
            "Stops the server process."
            if sunucu.acik else
            "Starts the server as a process on this machine, with your "
            "permissions."
        )
        self._ac_kapa.clicked.connect(self._cevir)
        dugmeler.addWidget(self._ac_kapa)

        kaldir = QPushButton("Remove")
        kaldir.setFixedSize(84, 26)
        kaldir.setCursor(Qt.CursorShape.PointingHandCursor)
        kaldir.clicked.connect(self._sil)
        dugmeler.addWidget(kaldir)
        dugmeler.addStretch(1)
        ust.addLayout(dugmeler)
        duzen.addLayout(ust)

        if baglanti.hata:
            duzen.addWidget(self._serit(baglanti.hata, t.critical))
        if baglanti.degisti:
            # Halı çekme: onayladığın araçlar artık başka araçlar.
            duzen.addWidget(self._serit(
                "This server's tool definitions changed since it was last "
                "connected. Read them again before approving a call.",
                t.caution,
            ))

        for tanim in baglanti.araclar[:EN_COK_ARAC]:
            duzen.addWidget(self._arac(tanim))
        kalan = len(baglanti.araclar) - EN_COK_ARAC
        if kalan > 0:
            fazla = QLabel(f"and {kalan} more tools")
            fazla.setStyleSheet(
                f"color: {t.text_tertiary}; font-size: 11.5px;"
                f" border: none; padding-left: 44px;"
            )
            duzen.addWidget(fazla)

    def _serit(self, metin: str, renk: str) -> QWidget:
        t = self.t
        kutu = QLabel(metin)
        kutu.setWordWrap(True)
        kutu.setStyleSheet(
            f"color: {renk}; background: {_blend(renk, 0.10, t.card)};"
            f" border: none; border-radius: {RADIUS_CONTROL}px;"
            f" padding: 8px 10px; font-size: 12px;"
        )
        return kutu

    def _arac(self, tanim: dict) -> QWidget:
        t = self.t
        kutu = QWidget()
        duzen = QVBoxLayout(kutu)
        duzen.setContentsMargins(44, 2, 4, 2)
        duzen.setSpacing(1)

        kisa = tanim["name"].split("__", 2)[-1]
        ad = QLabel(kisa)
        ad.setStyleSheet(
            f"color: {t.text_secondary}; font-size: 12px; border: none;"
            f" font-family: '{t.font_mono}';"
        )
        duzen.addWidget(ad)

        aciklama = (tanim.get("description") or "").strip()
        if aciklama:
            metin = QLabel(aciklama[:240]
                           + ("…" if len(aciklama) > 240 else ""))
            metin.setWordWrap(True)
            metin.setStyleSheet(
                f"color: {t.text_tertiary}; font-size: 11.5px; border: none;"
            )
            duzen.addWidget(metin)

        uyarilar = self.baglanti.uyarilar.get(tanim["name"], [])
        if uyarilar:
            uyari = QLabel("⚠  " + "; ".join(uyarilar))
            uyari.setWordWrap(True)
            uyari.setStyleSheet(
                f"color: {t.caution}; font-size: 11.5px; border: none;"
            )
            duzen.addWidget(uyari)
        return kutu

    def _cevir(self) -> None:
        sunucu = self.baglanti.sunucu
        if not sunucu.acik:
            cevap = QMessageBox.question(
                self, "Start the server",
                f"{sunucu.ad} runs as a process on this machine with your "
                f"permissions:\n\n{sunucu.anlat}\n\n"
                f"Its tool descriptions go into the model's prompt. Start "
                f"it?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if cevap != QMessageBox.StandardButton.Yes:
                return
        ayar_mod.ac_kapa(sunucu.ad, not sunucu.acik)
        self.degisti.emit()

    def _sil(self) -> None:
        ad = self.baglanti.sunucu.ad
        cevap = QMessageBox.question(
            self, "Remove the server",
            f"Remove {ad} from mcp.json?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if cevap == QMessageBox.StandardButton.Yes:
            ayar_mod.sil(ad)
            self.degisti.emit()


class McpGorunumu(QWidget):
    """MCP sayfası."""

    #: Ayar değişti — köprü sunucuları yeniden bağlamalı.
    degisti = Signal()

    def __init__(self, t: Tokens, durum_ver) -> None:
        super().__init__()
        self.t = t
        #: Bağlantı durumlarını veren çağrılabilir. Sayfa uygulama
        #: açılırken kuruluyor, ajan saniyeler sonra; o an alınıp
        #: saklansaydı sayfa ömrü boyunca boş kalırdı.
        self._durum_ver = durum_ver
        self._son_imza = ""

        dis = QVBoxLayout(self)
        dis.setContentsMargins(0, 0, 0, 0)
        dis.setSpacing(0)
        dis.addWidget(self._baslik_seridi())

        self._kaydirma = QScrollArea()
        self._kaydirma.setWidgetResizable(True)
        self._kaydirma.setFrameShape(QScrollArea.Shape.NoFrame)
        self._kaydirma.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._govde = QWidget()
        self._duzen = QVBoxLayout(self._govde)
        self._duzen.setContentsMargins(20, 18, 20, 24)
        self._duzen.setSpacing(10)
        self._duzen.addStretch(1)
        self._kaydirma.setWidget(self._govde)
        dis.addWidget(self._kaydirma, 1)

        # Bağlanma arka planda ve dakikalar sürebiliyor (`npx` paket
        # indiriyor). Sayfa açıkken kendini tazeliyor, yoksa "connecting…"
        # yazısı elle yenilenene kadar orada kalırdı.
        self._zamanlayici = QTimer(self)
        self._zamanlayici.timeout.connect(self._sessiz_tazele)
        self.yenile()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.yenile()
        self._zamanlayici.start(2000)

    def hideEvent(self, event) -> None:
        self._zamanlayici.stop()
        super().hideEvent(event)

    def _sessiz_tazele(self) -> None:
        """Yalnızca bir şey değiştiyse yeniden çiziyor.

        İki saniyede bir bütün kartları yıkıp kurmak, sayfaya bakan
        birinin kaydırma konumunu sürekli sıfırlardı.
        """
        imza = self._imza()
        if imza != self._son_imza:
            self.yenile()

    def _baslik_seridi(self) -> QWidget:
        t = self.t
        serit = QWidget()
        serit.setObjectName("mcpBaslik")
        serit.setFixedHeight(52)
        serit.setStyleSheet(
            f"QWidget#mcpBaslik {{ background: {t.background};"
            f" border-bottom: 1px solid {t.divider}; }}"
        )
        duzen = QHBoxLayout(serit)
        duzen.setContentsMargins(20, 0, 16, 0)
        duzen.setSpacing(10)

        baslik = QLabel("MCP")
        baslik.setStyleSheet(
            f"color: {t.text}; font-size: 15px; font-weight: 600;"
            f" font-family: '{t.font_display}', '{t.font_ui}'; border: none;"
        )
        duzen.addWidget(baslik)

        self._sayac = QLabel()
        self._sayac.setStyleSheet(
            f"color: {t.text_tertiary}; font-size: 12px; border: none;"
        )
        duzen.addWidget(self._sayac)
        duzen.addStretch(1)

        for etiket, kanca, ipucu in (
            ("Import from Claude", self._aktar,
             "Copies the servers from Claude Desktop's config. They come "
             "in disabled."),
            ("Open mcp.json", self._dosyayi_ac,
             "Opens the config file in your editor."),
            ("Reconnect", self._tekrar_bagla,
             "Re-reads the config and reconnects the enabled servers."),
        ):
            dugme = QPushButton(etiket)
            dugme.setFixedHeight(30)
            dugme.setCursor(Qt.CursorShape.PointingHandCursor)
            dugme.setToolTip(ipucu)
            dugme.clicked.connect(kanca)
            duzen.addWidget(dugme)
        return serit

    # --- eylemler ----------------------------------------------------------

    def _aktar(self) -> None:
        eklenen = ayar_mod.claude_desktop_aktar()
        if eklenen:
            self.degisti.emit()
            self.yenile()
            QMessageBox.information(
                self, "Imported",
                "Added, all disabled:\n\n" + "\n".join(eklenen),
            )
        else:
            QMessageBox.information(
                self, "Nothing to import",
                f"No new servers in {ayar_mod.CLAUDE_DESKTOP}.",
            )

    def _dosyayi_ac(self) -> None:
        """Örnek yapılandırmayı sistemin görüntüleyicisinde açar.

        Açıcı platforma göre (`app/isletim.py`). Hiçbiri yoksa
        patlamıyor: kullanıcıya yolu söyleyen bir uyarı çıkıyor —
        sessiz kalmak düğmeyi bozuk gösterirdi, patlamak daha kötüsü.
        """
        yol = ayar_mod.ornek_yaz()
        try:
            isletim.dosya_ac(yol)
        except OSError:
            QMessageBox.information(
                self, "Could not open the file",
                f"No file opener is available.\n\nThe example config is at:\n{yol}",
            )

    def _tekrar_bagla(self) -> None:
        self.degisti.emit()
        self.yenile()

    # --- veri --------------------------------------------------------------

    def _imza(self) -> str:
        """Ekranda görüneni belirleyen her şey. Değişmediyse çizim yok."""
        return "|".join(
            f"{b.sunucu.ad}:{b.durum}:{len(b.araclar)}:{b.izler}:{b.hata[:40]}"
            for b in (self._durum_ver() or [])
        )

    def yenile(self) -> None:
        self._son_imza = self._imza()
        while self._duzen.count() > 1:
            oge = self._duzen.takeAt(0)
            if oge.widget() is not None:
                oge.widget().deleteLater()

        durumlar = self._durum_ver() or []
        hazir = [b for b in durumlar if b.hazir]
        arac_sayisi = sum(len(b.araclar) for b in hazir)
        self._sayac.setText(
            f"{len(hazir)}/{len(durumlar)} connected · {arac_sayisi} tools"
            if durumlar else "no servers configured"
        )
        if not durumlar:
            self._duzen.insertWidget(0, self._bos_durum())
            return
        for sira, baglanti in enumerate(durumlar):
            kart = _SunucuKarti(self.t, baglanti)
            kart.degisti.connect(self._degisti)
            self._duzen.insertWidget(sira, kart)

    def _degisti(self) -> None:
        self.degisti.emit()
        self.yenile()

    def _bos_durum(self) -> QWidget:
        t = self.t
        kutu = QWidget()
        duzen = QVBoxLayout(kutu)
        duzen.setContentsMargins(20, 40, 20, 20)
        duzen.setSpacing(12)

        baslik = QLabel("No MCP servers yet")
        baslik.setStyleSheet(
            f"color: {t.text}; font-size: 22px; font-weight: 600;"
            f" font-family: '{t.font_display}', '{t.font_ui}';"
        )
        duzen.addWidget(baslik)

        govde = QLabel(
            "MCP servers lend the agent tools this app does not have — a "
            "structured browser, a GitHub client, a web fetcher. They are "
            "declared in ~/.ajan/mcp.json in the standard format, so a "
            "config you already have for another app can be pasted in "
            "whole.\n\n"
            "Nothing starts on its own. A server is a process running on "
            "this machine with your permissions, and its tool "
            "descriptions go straight into the model's prompt — so "
            "enabling one is a separate, deliberate click, and every "
            "call it makes is approved by you.\n\n"
            "Open mcp.json to see an example with Playwright, fetch and "
            "GitHub already written out."
        )
        govde.setStyleSheet(
            f"color: {t.text_secondary}; font-size: 13.5px; line-height: 155%;"
        )
        duzen.addWidget(sarmali(govde, 580))
        duzen.addStretch(1)
        return kutu
