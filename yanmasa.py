"""Yan Masa — Windows masaüstü uygulaması.

    .venv/Scripts/pythonw.exe yanmasa.py

Yerel bir Qt uygulaması: web katmanı, tarayıcı motoru ve HTTP köprüsü yok.
Görsel dil Windows 11 Fluent; renkler ve tema sistemden okunuyor.

Ajanla konuşulan yer ana pencere değil, ekranın köşesinde yüzen komut
çubuğu: mikrofon, yazı alanı ve yapılan işin önizleme karesi bir arada.
Ana pencere belgeleri tutuyor.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app import fluent
from app.agent_bridge import AgentBridge
from app.commandbar import CommandBar, Operation
from app.etiketler import TOOL_LABEL, hedef
from app.single import InstanceGuard
from app.window import MainWindow


def _describe(tool: str, payload: dict) -> Operation:
    """Araç çağrısını önizleme karesinin anlayacağı hâle getirir."""
    target = hedef(payload)

    # `why` zorunlu bir alan olduğu için ofis işlerinde gerekçe hazır;
    # diğerlerinde araç çağrısının kendisi anlatıyor.
    detail = str(payload.get("why") or payload.get("text") or payload.get("command") or "")
    if len(detail) > 140:
        detail = detail[:137] + "…"

    # Detay boşsa boş kalıyor. Eskiden araç adına düşüyordu ve satır
    # "Bekliyor  wait" gibi kendini tekrar ediyordu; çizim zaten hangi
    # iş olduğunu söylüyor.
    return Operation(
        tool=TOOL_LABEL.get(tool, tool),
        target=target,
        detail=detail,
        key=tool,
    )


def _ortak_klasor(paths: list[str]) -> str:
    """Yazılan dosyaların ortak üst klasörü — kod ağacının kökü.

    Tek dosya yazıldıysa onun klasörü. Farklı sürücülere yazıldıysa
    (`commonpath` orada hata veriyor) ilk dosyanın klasörü.
    """
    klasorler = [str(Path(p).resolve().parent) for p in paths]
    if len(set(klasorler)) == 1:
        return klasorler[0]
    try:
        return os.path.commonpath(klasorler)
    except ValueError:
        return klasorler[0]


def _panel_for(shot, tokens):
    """Anlık görüntüden panel içeriği üretir."""
    if shot.kind == "sheet":
        from app.sheet_view import Cell, SheetView

        rows = [
            [Cell(value=v, formula=f, why=w, result=r) for v, f, w, r in row]
            for row in shot.rows
        ]
        return SheetView(rows, tokens, shot.sheets or ["Sheet1"], shot.path)

    from app.panels import DocPanel, Para

    return DocPanel([
        Para(text=text, style=style, why=why)
        for text, style, why in shot.paragraphs
    ])


def main() -> int:
    # Süreç DPI farkındalığına alınmalı: ajan aynı süreçten ekran yakalayıp
    # koordinat hesaplıyor ve Qt'nin ölçeklemesi araya girerse tıklama
    # yanlış piksele gider.
    from backend.computer.displays import set_dpi_awareness

    set_dpi_awareness()

    app = QApplication(sys.argv)
    app.setApplicationName("Yan Masa")
    # Fusion, Windows stilinin yok saydığı QSS kurallarını uyguluyor.
    app.setStyle("Fusion")
    tokens = fluent.apply(app)

    # İki ajan aynı fareyi süremez: ikinci örnek açılmıyor, var olanı
    # öne getiriyor.
    guard = InstanceGuard()
    if not guard.claim():
        return 0
    app.aboutToQuit.connect(guard.release)

    window = MainWindow(tokens)
    window.show()

    bar = CommandBar(tokens)
    window.attach_bar(bar)
    # Ses motoru henüz bağlı değil ve bu gizlenmiyor: mikrofon sönük durur,
    # yazı alanı tek çalışan giriş yolu olarak öne çıkar.
    bar.set_voice_available(False)
    bar.show()

    def on_woken() -> None:
        """Biri uygulamayı tekrar açmaya çalıştı."""
        window.showNormal()
        window.raise_()
        window.activateWindow()
        bar.show()
        bar.raise_()
        bar.set_status("Yan Masa is already open.")

    guard.woken.connect(on_woken)

    bridge = AgentBridge()

    def on_ready(ok: bool, why: str) -> None:
        if ok:
            bar.attach_buttons(bridge.button_store(), bridge.commands)
            bar.set_status("Type something and press Enter.")
        else:
            bar.set_status(f"Agent could not start: {why}")
            bar.field.setEnabled(False)

    def on_submit(text: str) -> None:
        # `/ad` bir komutsa hazır talimata açılıyor. Eşleşme yoksa metin
        # olduğu gibi gidiyor: eğik çizgiyle başlayan bir yol yazmak
        # engellenmemeli.
        expanded = bridge.expand_command(text)
        window.activity.add_step("You", "", text, "__sen__")
        # Araya cümle sıkıştırırken cevabı silme: süren turun anlatımı
        # ekranda kalmalı, yeni bir tur başlıyorsa temizlenmeli.
        if not bar.busy:
            bar.clear_run()
            bar.show_operation(None)
        bar.add_user(text)
        bar.set_busy(True)
        bar.set_status("Working…")
        bar.sona_kaydir()
        kod_gosterildi["tur"] = False
        window.run_instruction(text)
        bridge.run(expanded or text)

    steps = {"n": 0}
    unsaved: dict[str, int] = {}
    ide: dict = {"view": None}

    def open_remote(session, title_suffix: str = "") -> None:
        """Sunucu panelini açar ya da öne getirir."""
        from app.remote_view import RemoteView

        view = RemoteView(tokens, session)
        view.show_path(session.cwd)
        window.open_panel("__uzak__", f"{session.host.label} · server", view,
                          glyph="sunucu", label=session.host.label)

    def connect_remote() -> None:
        """Berkay 'Sunucu' düğmesine bastı."""
        from PySide6.QtWidgets import QDialog
        from app.remote_view import ConnectDialog
        from backend.remote.ssh import RemoteError, SshSession

        dialog = ConnectDialog(tokens, window)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        session = SshSession(dialog.result_host())
        bar.set_status(f"connecting to {session.host.label}…")
        try:
            banner = session.connect()
        except RemoteError as exc:
            # Bağlanamamak sessizce geçilmiyor; sebebi olduğu gibi yazılıyor.
            bar.set_status(str(exc))
            window.status.set_line(str(exc))
            return
        bridge.adopt_remote(session)
        open_remote(session)
        bar.set_status("")
        window.status.set_line(f"Connected: {banner}")

    window.status.connect_remote.clicked.connect(connect_remote)

    # Masa sabit bir sayfa: ajan yan alanı hiç kullanmasa da rayda duruyor
    # ve boş masayı gösteriyor. Yakalama yalnızca sayfa görünürken dönüyor,
    # yani bakılmayan bir masa hiç işlemci yemiyor.
    from app.masa import MasaPenceresi, masa_kaynagi

    masa_gorunumu = MasaPenceresi(masa_kaynagi(bridge.dispatcher), tokens)
    # Masa başlıksız: kendi paneli zaten bir başlık şeridi ve ikisini üst
    # üste koymak aynı işi yapan iki çubuk demekti.
    window.add_fixed_page("masa", "Desk", "pencere", masa_gorunumu,
                          basliksiz=True)

    def show_desk() -> None:
        window.show_page("masa")

    kod_gosterildi = {"tur": False}

    def kod_akiyor(arac: str, yol: str, metin: str, bitti: bool) -> None:
        """Model bir dosya yazıyor — masadaki Code penceresine düşüyor.

        Tur başına bir kez masaya geçiliyor. Her parçada geçmek, başka
        bir sayfaya bakarken sürekli geri fırlatılmak olurdu.
        """
        masa_gorunumu.kod_akiyor(arac, yol, metin, bitti)
        if not kod_gosterildi["tur"]:
            kod_gosterildi["tur"] = True
            show_desk()

    bridge.kod.connect(kod_akiyor)

    # Geçmiş de sabit bir sayfa. Diskteki kayıt uygulamadan uzun yaşıyor
    # ve ona bakmanın tek yolu şimdiye kadar dosyayı elle açmaktı.
    from app.gecmis import GecmisGorunumu

    gecmis = GecmisGorunumu(tokens)
    window.add_fixed_page("gecmis", "History", "gecmis", gecmis,
                          basliksiz=True)

    # Akışlar da sabit sayfa: kaydedilmiş bir işi çalıştırmak için ajanı
    # uyandırmak, ücretsiz olanı ücretli yapmak olurdu.
    from app.akislar import AkisGorunumu

    akis_gorunumu = AkisGorunumu(tokens, bridge.akislar)
    akis_gorunumu.oynat.connect(bridge.oynat)
    window.add_fixed_page("akislar", "Workflows", "akis", akis_gorunumu,
                          basliksiz=True)

    # MCP sayfası: dış sunucular ve getirdikleri araçlar. Ajan
    # kurulmadan da açılıyor — sunucu eklemek API anahtarı istemiyor.
    from app.mcp_view import McpGorunumu

    mcp_gorunumu = McpGorunumu(tokens, bridge.mcp_durumlari)
    mcp_gorunumu.degisti.connect(bridge.mcp_yenile)
    window.add_fixed_page("mcp", "MCP", "fis", mcp_gorunumu, basliksiz=True)

    def sayfa_degisti(anahtar: str) -> None:
        # Geçmiş açıldığında tazeleniyor: kayda ajan çalışırken saniyede
        # birkaç satır düşüyor ve bakılmayan bir sayfa için sürekli
        # yeniden kurmak boşa iş.
        if anahtar == "gecmis":
            gecmis.yenile()
        elif anahtar == "akislar":
            akis_gorunumu.yenile()
        elif anahtar == "mcp":
            mcp_gorunumu.yenile()

    window.ray.secildi.connect(sayfa_degisti)

    def on_panel(skill: str, panel: dict) -> None:
        """Bir yetenek panel üretti — arayüzde yeni bir özellik."""
        from app.panel_view import SkillPanel

        window.open_panel(f"__yetenek__{skill}", panel["baslik"],
                          SkillPanel(tokens, panel),
                          glyph="yetenek", label=skill)

    def on_wrote(paths: list) -> None:
        """Ajan dosya yazdı — kodu göster.

        "yazıldı" demek yetmiyor: ajan diske kod koyuyor ve görmeden ona
        güvenmen gerekiyor.

        Dosya başına bir panel açmak eskiden ekranı sekmelerle dolduruyordu
        ve dosyalar arasındaki ilişkiyi göstermiyordu. Tek bir kod paneli
        var: solda projenin ağacı, sağda sekmeler.
        """
        gecerli = [p for p in paths if Path(p).is_file()]
        if not gecerli:
            return
        masa_gorunumu.kod.dosyalari_ekle(gecerli)
        kok = _ortak_klasor(gecerli)
        if ide["view"] is None:
            from app.ide import IdeView

            ide["view"] = IdeView(tokens, kok)
        else:
            ide["view"].set_root(kok)
            ide["view"].reload()
        window.open_panel("__kod__", f"Code · {Path(kok).name}", ide["view"],
                          glyph="sayfa", label="Code")
        for path in gecerli[-3:]:
            ide["view"].open_file(path)

    def on_document(shot) -> None:
        """Ajan bir belge açtığında ya da değiştirdiğinde panel belirir."""
        unsaved[shot.name] = shot.unsaved
        title = f"{shot.name} · {shot.kind}"
        if shot.unsaved:
            title += f"  ({shot.unsaved} unsaved)"
        window.open_panel(shot.name, title, _panel_for(shot, tokens),
                          glyph="tablo" if shot.kind == "sheet" else "yazi",
                          label=shot.name)
        window.set_counters(steps["n"], sum(unsaved.values()), 0)

    def _bakis(payload: dict) -> None:
        """Gözler gerçekten tıklanacak yere bakıyor.

        Koordinat zaten elimizde ve yakalanan ekran 1920x1080; merkeze
        göre -1..1 aralığına çeviriyoruz. Rastgele kıpırdayan bir maskot
        süs olurdu — buradaki her hareket gibi bu da bir veriyi taşıyor.
        """
        nokta = payload.get("coordinate")
        if isinstance(nokta, (list, tuple)) and len(nokta) == 2:
            try:
                x, y = float(nokta[0]), float(nokta[1])
            except (TypeError, ValueError):
                return
            bar.ring.face.look_at(x / 960.0 - 1.0, y / 540.0 - 1.0)
        else:
            # Koordinat yoksa bakış baloncuğa dönüyor: maskot kendi
            # söylediğine bakıyor. Körü körüne öne çevirmek, konuşurken
            # başka yere bakmak olurdu.
            bar.bakisi_tazele()

    def on_said(parca: str) -> None:
        """Model yazarken harfler düşüyor.

        Akış zaten çekirdekte vardı ama arayüz onu hiç dinlemiyordu: cevap
        yalnızca tur bitince, tek seferde beliriyordu.
        """
        bar.stream(parca)

    def on_action(tool: str, payload: dict) -> None:
        # Ajan yan masaüstüne dokundu: orada olan bitenin görünmesi bu
        # aracın bütün gerekçesi. Pencereyi elle açmayı beklemek, ilk
        # koşuda kimsenin bakmadığı bir çalışma alanı demek.
        if tool.startswith("side_"):
            show_desk()
            if tool == "side_launch":
                masa_gorunumu.masa_acildi()
        if tool == "edit_file":
            # `old` ve `new` eylem anında elimizde; sonucu beklemeye
            # gerek yok ve beklemek değişikliği iş bittikten sonra
            # göstermek olurdu.
            masa_gorunumu.kod.degisiklik(
                str(payload.get("path") or ""),
                str(payload.get("old") or ""),
                str(payload.get("new") or ""),
            )
        if tool == "heads_up":
            # Not bir adım değil: ne yaptığını değil, neyin ters
            # gidebileceğini söylüyor. Adım satırı gibi çizilseydi otuz
            # satırlık bir dökümün içinde kaybolurdu.
            notu = str(payload.get("note") or "").strip()
            hakkinda = str(payload.get("about") or "").strip()
            if notu:
                bar.add_note(notu, hakkinda)
                window.activity.add_note(notu, hakkinda)
                bar.set_tool("A note", hakkinda or notu[:60])
            bar.ring.step(tool)
            return

        op = _describe(tool, payload)
        bar.ring.step(tool)
        bar.set_tool(op.tool, op.target or op.detail)
        _bakis(payload)
        bar.add_step(tool, op.tool, op.target or op.detail)
        bar.show_operation(op)
        window.activity.add_step(op.tool, op.target, op.detail, tool)
        steps["n"] += 1
        window.set_counters(steps["n"], 0, 0)

    def on_result(tool: str, text: str, is_error: bool, png: bytes) -> None:
        # Adım bitti: halkada kalıcı bir dilim bırakıyor, hata kırmızı.
        bar.ring.settle(is_error)
        bar.settle_step(is_error)
        # Ajan bir düğme kurduysa çubuk hemen göstersin; yeniden başlatmak
        # gerekmesin.
        if tool.startswith("terminal_") and not is_error and text:
            # Kodun yanında çalıştığını görmek: `pip install`,
            # `python bot.py`, hata izleri.
            masa_gorunumu.kod.terminal_ciktisi("terminal", text)
        if tool == "side_close" and not is_error:
            masa_gorunumu.masa_kapandi()
        # Kayıt rozeti: kırmızı nokta ve süre, durum şeridinde. Kaydın
        # açık kaldığı süre dakikalarla ölçülüyor ve bu sürenin görünür
        # olmaması, sonunda kimsenin istemediği bir video demek.
        if tool == "record_start" and not is_error:
            window.kayit_basladi(bridge.kayit_hedefi())
        if tool == "record_stop":
            window.kayit_bitti(text if not is_error else "")
        if tool.startswith("workflow_") and not is_error:
            akis_gorunumu.yenile()
        if tool.startswith("button_") and not is_error:
            bar.buttons.reload()
            bar._grow()
        # Ajan bir sunucuya bağlandıysa ya da orada gezindiyse panel de
        # oraya gitsin: iki ayrı yerde durmaları kafa karıştırıyor.
        if tool in ("remote_connect", "remote_list") and not is_error:
            session = bridge.remote_session()
            if session is not None and session.connected:
                open_remote(session)
        if png:
            window.activity.frame_last(png)
        elif is_error:
            window.activity.annotate_last(text[:600], error=True, tool=tool)
        elif text and text != "OK":
            window.activity.annotate_last(text[:900], tool=tool)
        if is_error:
            bar.set_status(f"{tool}: {text[:120]}")

    def on_finished(text: str) -> None:
        # Koşu biterken çekirdek kaydı zaten kapatıyor; rozet de
        # kapanmalı, yoksa şeritte durmayan bir kayıt görünür.
        window.kayit_bitti()
        bar.set_busy(False)
        bar.show_operation(None)
        bar.set_status("")
        # Metin akarken zaten yazıldı; burada tekrar koymak turun ilk
        # adımlarındaki anlatımı silerdi. Yalnızca hiç akmadıysa yazılıyor.
        if bar.reply.text().strip():
            bar.end_stream()
        else:
            bar.say(text or "Bitti.")
        bar._fit_reply()
        window.set_phase("bitti")
        window.status.set_line(text[:120] if text else "Bitti.")
        if bar.kuru:
            # Kuru koşunun sonunda "peki şimdi nasıl yapacağım" sorusu
            # cevapsız kalmasın.
            bar.set_status(
                "Dry run finished — nothing was done. Turn DRY off and "
                "send it again to actually run it."
            )
        bildir("Dry run finished" if bar.kuru else "Done",
               text or "The turn finished.")

    def on_rapor(satir: str) -> None:
        """Ajan bir iş yaptığını söyledi ama denetim kaydında yok.

        Durum satırına yazılıyor, cevabın içine değil: cevap ajanın
        sözü, bu ise ona dair bir gözlem. İkisini aynı baloncuğa koymak,
        ajanı kendi hakkında konuşuyor gibi gösterirdi.
        """
        window.status.set_line(satir)

    def on_failed(why: str) -> None:
        window.kayit_bitti()
        bar.set_busy(False)
        bar.show_operation(None)
        bar.set_status("")
        bar.say(why)
        window.set_phase("durduruldu")
        bildir("Stopped", why, hata=True)

    def on_approval(request) -> None:
        bar.ask_approval(request.tool, request.detail, request.reason)
        window.set_phase("onay")
        # Onay bekleyen bir ajan hiçbir şey yapmıyor demek; bunun fark
        # edilmemesi turun sessizce beş dakika durması anlamına geliyor.
        bildir("Approval needed", f"{request.tool} — {request.reason}")

        def answer(approved: bool) -> None:
            request.approved = approved
            request.event.set()
            bar.clear_approval()
            window.set_phase("kosuyor")
            try:
                bar.approval.answered.disconnect(answer)
            except (RuntimeError, TypeError):
                pass

        bar.approval.answered.connect(answer)

    bridge.ready.connect(on_ready)
    bridge.said.connect(on_said)
    bridge.pulse.connect(bar.ring.pulse)
    bridge.acted.connect(on_action)
    bridge.result.connect(on_result)
    bridge.document.connect(on_document)
    bridge.panel.connect(on_panel)
    bridge.wrote.connect(on_wrote)
    bridge.rapor.connect(on_rapor)
    bridge.finished.connect(on_finished)
    bridge.failed.connect(on_failed)
    bridge.approval.connect(on_approval)
    bar.submitted.connect(on_submit)

    def kuru_degisti(acik: bool) -> None:
        bridge.set_kuru(acik)
        window.status.set_line(
            "Dry run — it plans and reads; clicks, typing, commands and "
            "files are blocked."
            if acik else "Dry run off — actions will really run."
        )

    bar.kuru_degisti.connect(kuru_degisti)
    gecmis.tekrarla.connect(bar.submit_text)
    bar.set_commands(bridge.commands)
    def kaydi_durdur() -> None:
        satir = bridge.kaydi_durdur()
        window.kayit_bitti(satir or "Recording stopped.")

    window.status.kayit.stop_requested.connect(kaydi_durdur)
    window.stop_requested.connect(bridge.stop)
    bar.stop_requested.connect(bridge.stop)
    app.aboutToQuit.connect(bridge.shutdown)

    # --- tepsi ve global kısayol ------------------------------------------
    #
    # İkisi de aynı boşluğu dolduruyor: ajan çalışırken bakılan şey ajan
    # penceresi değil, işin yapıldığı uygulama. Tepsi simgesi durumu
    # oradan söylüyor, kısayol çubuğu oradan çağırıyor.
    from app import kisayol as kisayol_mod
    from app.tepsi import Tepsi

    tepsi = None
    if Tepsi.kullanilabilir():
        tepsi = Tepsi(tokens, app)
        tepsi.pencere_istendi.connect(on_woken)
        tepsi.cubuk_istendi.connect(bar.claim_focus)
        tepsi.durdur_istendi.connect(window.stop)
        tepsi.cikis_istendi.connect(app.quit)
        window.phase_changed.connect(tepsi.set_phase)
        tepsi.goster()
        # Pencere kapanınca uygulama ölmesin: tepsiden geri çağrılabiliyor.
        # Tepsi yoksa bu ayarı yapmak uygulamayı kapatılamaz hâle
        # getirirdi — kapatmanın başka bir yolu kalmazdı.
        app.setQuitOnLastWindowClosed(False)
        app.aboutToQuit.connect(tepsi.gizle)

    def bildir(baslik: str, metin: str, hata: bool = False) -> None:
        """Ajan penceresi öndeyken bildirim göstermiyoruz: bakılan şeyi
        ikinci kez söylemek olurdu."""
        if tepsi is None or window.isActiveWindow():
            return
        tepsi.bildir(baslik, metin, hata)

    kisayol = kisayol_mod.kur()
    if kisayol.kayitli:
        kisayol.basildi.connect(bar.claim_focus)
        bar.set_status(f"Press {kisayol.ad} from anywhere to come here.")
    elif kisayol.hata:
        # Sessizce çalışmayan bir kısayol bozuk bir klavye gibi
        # hissettiriyor; sebebi yazılıyor.
        window.status.set_line(kisayol.hata)
    app.aboutToQuit.connect(kisayol.stop)

    bridge.start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
