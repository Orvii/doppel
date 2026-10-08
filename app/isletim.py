"""Platform ayrımının **tek** anahtarı — ve neden tek olduğu.

Uygulama Windows 11 için yazılmıştı; artık her Linux'ta da çalışmak
zorunda. Platforma bağlı her karar bu modülden geçiyor: başka hiçbir
dosya `sys.platform` okumuyor, hepsi buradaki `WINDOWS` değerine bakıyor.
Ölçülmüş bir hata değil bu, tekrar eden bir kalıp: dağınık `if windows`
kontrolleri zamanla birbirinden ayrışıyor ve "Linux'ta da çalışıyor"
iddiası sınanabilir olmaktan çıkıyor. Testler bu anahtarı çevirip Linux
yolunu Windows'ta sahtelerle sınıyor.

Platforma özel **işler** kendi modüllerinde kalıyor; burada yalnızca iki
platformda da cevaplanabilen sorular var:

- `app/baslangic.py` — açılışta başlatma: kayıt defteri / XDG girdisi
- `app/fluent.py` — tema: kayıt defteri / Qt'nin renk şeması
- `app/single.py` — tek örnek: adlandırılmış mutex / `flock`
- `app/kisayol.py` — global kısayol: `RegisterHotKey` / kurulmuyor,
  ama sebebiyle

Buradakiler Qt'ye sorulabilen şeyler (koyu tema, vurgu rengi, besteci var
mı), dosya açma, ve kullanıcının gördüğü iki metin. Qt bağımlılıkları
fonksiyon içinde import ediliyor: etiket ve ipucu gibi metinler Qt
penceresi kurulmadan da çağrılabilsin, ve modülün içe aktarılması
`QApplication` istemesin.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

#: Tek anahtar. `sys.platform`'a başka hiçbir app/ modülü bakmıyor.
WINDOWS = sys.platform == "win32"

#: Platformun kendi "şunu aç" komutu. Windows'ta kabuk yok.
_ACICI = ("xdg-open", "gio open")


def qt_koyu_tema() -> bool | None:
    """Qt'nin bildiği renk şeması: koyuysa `True`, açıksa `False`.

    Qt 6.5+ `styleHints().colorScheme()` masaüstünün tercihini veriyor
    (Wayland'de `org.freedesktop.appearance`, X11'de Qt'nin kendi
    sezgisi). Uygulama yoksa ya da platform bilmiyorsa `None`: çağıran
    taraf kendi varsayılanına düşüyor, yani uydurma bir "açık" cevabı
    verilmiyor.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance()
    if app is None:
        return None
    sema = app.styleHints().colorScheme()
    if sema == Qt.ColorScheme.Dark:
        return True
    if sema == Qt.ColorScheme.Light:
        return False
    return None


def qt_vurgu_rengi() -> str | None:
    """Sistemin vurgu rengi, `#rrggbb`. Okunamıyorsa `None`.

    `QPalette.ColorRole.Accent` Qt 6.6'da standart bir rol oldu ve
    masaüstünün vurgusunu taşıyor. `None` dönmesi hata değil: Linux'ta
    vurgu diye bir kavram olmayan masaüstleri var ve o zaman çağıran
    kendi bilinen varsayılanına düşüyor.
    """
    from PySide6.QtGui import QGuiApplication, QPalette

    app = QGuiApplication.instance()
    if app is None:
        return None
    renk = app.palette().color(QPalette.ColorRole.Accent)
    return renk.name() if renk.isValid() else None


def saydam_zemin_destekli() -> bool:
    """Yarı saydam bir pencere çizebilir miyiz.

    Windows'ta DWM her zaman besteliyor, cevap kesin `True`. Linux'ta
    cevap masaüstüne bağlı: Wayland her zaman besteliyor, X11'de besteci
    (picom, KWin, Mutter) çoğu zaman var ama garanti değil — besteci
    yokken yarı saydam pencere **siyah bir kutu** olarak çiziliyor.
    Qt platform eklentisi xcb ise besteciye `QX11Application` üzerinden
    soruluyor; sorulamıyorsa "yok" cevabı veriliyor, çünkü siyah kutu
    bozuk, düz zemin ise sadece sade.
    """
    if WINDOWS or sys.platform == "darwin":  # pragma: no cover - macOS kapsam dışı
        return True
    # Wayland oturumu: besteci tanım gereği çalışıyor. `platformName`
    # yeterli değil — Qt xcb ile XWayland üzerinden de açılabiliyor ve o
    # zaman X sunucusunda besteci seçimi görünmüyor; oturumun kendisi
    # daha güvenilir bir işaret.
    if os.environ.get("WAYLAND_DISPLAY"):
        return True
    try:
        from PySide6.QtGui import QGuiApplication, QNativeInterface

        app = QGuiApplication.instance()
        if app is None:
            return False
        if app.platformName() in ("wayland", "wayland-egl"):
            return True
        if app.platformName() != "xcb":
            # offscreen/vnc gibi başsız platformlar: saydamlığın bir
            # anlamı yok ama yanlış cevap da vermiyoruz.
            return False
        return bool(QNativeInterface.QX11Application(app).isCompositingManagerRunning())
    except (AttributeError, ImportError, TypeError):
        return False


def yazi_tipi() -> str:
    """Arayüzün metin yüzü.

    Windows'ta Fluent'in kendi yazı tipi (Segoe UI Variable). Linux'ta
    sistemin Qt'ye bildirdiği yüz: "Segoe UI Variable" orada yok ve Qt'yi
    kendi genel `sans-serif`ına düşürmek, uygulamayı diğerlerinden
    gereksiz yere ayırmak olurdu.
    """
    if WINDOWS:
        return "Segoe UI Variable Text"
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance()
    if app is None:
        return "sans-serif"
    return app.font().family() or "sans-serif"


def mono_yazi_tipi() -> str:
    """Kod görünümünün eşaralıklı yüzü.

    Windows'ta Cascadia Mono. Linux'ta sistemin sabit genişlikli yazı
    tipi — Cascadia orada kurulu değil ve olmayan bir yazı tipi adı Qt'yi
    sessizce varsayılana düşürüyor.
    """
    if WINDOWS:
        return "Cascadia Mono"
    from PySide6.QtGui import QFontDatabase

    return (
        QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()
        or "monospace"
    )


def anahtar_ipucu() -> str:
    """SSH anahtarı alanının yer tutucusu — platformun kendi yol biçimi."""
    return r"C:\Users\...\.ssh\id_ed25519" if WINDOWS else "~/.ssh/id_ed25519"


def acilis_etiketi() -> str:
    """Açılışta başlatma kutusunun menüdeki adı.

    İki platformda da sorulan şey aynı — oturum açıldığında başlasın mı —
    ama "Start with Windows" Linux'ta yanlış bir cümle; yanlış olduğu
    yerde duran bir ayar, çalışmayan bir düğmeden kötüdür.
    """
    return "Start with Windows" if WINDOWS else "Start at login"


def dosya_ac(yol: Path) -> None:
    """Dosyayı sistemin görüntüleyicisiyle açar.

    Windows'ta `os.startfile` (kabuk yok), o düşerse Not Defteri. Linux'ta
    `xdg-open`, o yoksa `gio open`: xdg-open çoğu masaüstünde var ama
    minimal kurulumlarda eksik olabiliyor. İkisi de yoksa `OSError`
    yükseliyor — sessizce hiçbir şey yapmamak, düğmenin bozuk olduğunu
    düşündürürdü.
    """
    if WINDOWS:
        try:
            os.startfile(str(yol))  # noqa: S606  (kullanıcının kendi dosyası)
            return
        except OSError:
            subprocess.Popen(["notepad.exe", str(yol)])
            return
    son: OSError | None = None
    for komut in _ACICI:
        try:
            subprocess.Popen([*komut.split(), str(yol)])
            return
        except OSError as exc:
            son = exc
    raise son