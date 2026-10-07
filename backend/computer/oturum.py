"""Platform ve oturum türü — tek soru: hangi yetenekler var.

Doppel artık iki platformda çalışıyor ve yetenekler platformla değil
**oturum türüyle** değişiyor: Linux'ta X11 oturumunda EWMH ile başka
uygulamaların pencereleri kontrol edilebiliyor, Wayland oturumunda ise
edilemiyor — Wayland'da bir uygulamanın başka uygulamaların pencerelerini
görmesinin ya da öne getirmesinin taşınabilir bir yolu yok, XWayland de
bunu değiştirmiyor (XWayland yalnızca kendi X istemcilerini gösterir).

Bu yüzden her modül `sys.platform` bakmıyor; **buradan** soruyor. Aynı
soruyu on üç ayrı yerde sormak, bir gün birinin `DISPLAY` varken Wayland'ı
fark etmemesi demek olurdu — `DISPLAY` XWayland yüzünden Wayland
oturumunda da dolu.

Erişilebilirlik (AT-SPI) bu ayrımın dışında: D-Bus üzerinden çalışıyor ve
**iki oturum türünde de** aynı şekilde erişilebiliyor. Orada tek soru
arılık yolunun (bus) açık olup olmadığı; `uia_linux.py` kendisi bakıyor.
"""

from __future__ import annotations

import os
import shutil
import sys

#: İşletim sistemi. Windows'ta `os.name == "nt"` tek doğru işaret.
WINDOWS = os.name == "nt"

#: Linux. Windows'ta `sys.platform == "win32"` olduğu için ayrı bayrak.
LINUX = sys.platform.startswith("linux")


def arac(ad: str) -> bool:
    """Sistem aracı PATH'te mi. `xprop`, `wmctrl`, `xdotool` gibi."""
    return shutil.which(ad) is not None


def x11_oturumu() -> bool:
    """Gerçek bir X11 oturumu mu — Wayland süpürmesi dâhil.

    `DISPLAY` set olması yetmiyor: Wayland oturumunda XWayland `DISPLAY`
    tanımlıyor ve oradan yalnızca **X11 istemcileri** görünüyor. Native
    Wayland pencereleri görünmez, öne getirilemez. Raporlarken X11 sanmak,
    "aktive edildi" yalanını üretmenin en kolay yolu.

    Kural: `WAYLAND_DISPLAY` doluysa ya da oturum türü wayland ise X11
    değil. Aksi hâlde `DISPLAY` dolu ve `xprop` kurulu olmalı — araç
    olmadan pencere yönetimi denemesi de sahte bir sonuç üretirdi.
    """
    if not LINUX:
        return False
    if os.environ.get("WAYLAND_DISPLAY"):
        return False
    if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
        return False
    if not os.environ.get("DISPLAY"):
        return False
    return arac("xprop")


def x11_yokluk_sebebi() -> tuple[bool, str]:
    """X11 pencere yönetimi neden yok — insan okunur tek cümle.

    Modüller bunu hata mesajlarına koyuyor: "neden çalışmadı" sorusunun
    cevabı her çağrı yerinde yeniden kurulmasın. Wayland ile X11 eksikliği
    farklı cümleler çünkü çözümleri farklı: biri oturum değiştirmek, öteki
    paket kurmak.
    """
    if x11_oturumu():
        return True, ""
    if WINDOWS:
        return False, "this session is Windows; the X11 backend is not in use"
    if os.environ.get("WAYLAND_DISPLAY") or (
        os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
    ):
        return False, (
            "this is a Wayland session — controlling other applications' "
            "windows is not possible on Wayland"
        )
    if not os.environ.get("DISPLAY"):
        return False, "there is no X display in this session"
    return False, "xprop is not installed (install x11-utils)"