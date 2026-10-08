"""Kurulu uygulamaların kataloğu.

`launch_app` yalnızca PATH'e bakıyordu ve Windows'ta uygulamaların çoğu
PATH'te değil. Ölçüldü: on yedi yaygın uygulamadan **on ikisi**
bulunamıyordu — Discord, Chrome, Spotify, Telegram, Steam, VLC, Firefox…
Ajan bunları açmak için ya tam yolu bilmek ya da Başlat menüsünde
tıklayarak gezinmek zorundaydı; ikincisi dört beş ekran görüntüsü demek.

Katalog üç kaynaktan geliyor, hepsi Windows'un kendi kayıtları:

1. **Başlat menüsü kısayolları** — makine ve kullanıcı için, iç içe
   klasörler dâhil. Windows Arama'nın baktığı yer burası.
2. **`App Paths` kayıt defteri anahtarı** — `chrome.exe` gibi adları
   yükleyicilerin kaydettiği yer.
3. **Mağaza uygulamaları** — `Get-StartApps`. Bunlar bir exe değil, bir
   AppID; `shell:AppsFolder` ile açılıyorlar.

Kısayolun hedefi çözülmüyor: `.lnk` dosyası doğrudan başlatılıyor. Windows
zaten çözüyor ve çalışma dizini, argümanlar, simge — hepsi kısayolun içinde.
Hedefi elle çıkarmak, o ayarları kaybetmek olurdu.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

try:  # winreg yalnızca Windows'ta; Linux'ta yok
    import winreg
except ImportError:
    winreg = None  # type: ignore[assignment]

#: Katalog bu kadar saniye taze sayılıyor. Uygulama kurmak seyrek bir iş;
#: her `launch_app` çağrısında 146 kısayolu taramanın anlamı yok.
CACHE_SECONDS = 300

#: Mağaza uygulamaları PowerShell ile geliyor ve ~1 saniye sürüyor. Diğer
#: kaynaklar yeterse ona hiç gidilmiyor.
STORE_TIMEOUT = 8

#: Türkçe harfleri karşılıklarına indiren tablo. "Görüntü" yazan bir
#: kısayolu "goruntu" diye arayabilmek için.
_ASCII = str.maketrans("çğıiöşüÇĞİIÖŞÜ", "cgiiosuCGIIOSU")

#: Kısayol adlarındaki gürültü. "Google Chrome" ile "Chrome" eşleşmeli.
_NOISE = {
    "app", "uygulama", "launcher", "baslat", "start", "run", "calistir",
    "x64", "x86", "64", "32", "bit", "desktop", "masaustu",
}


@dataclass(frozen=True)
class App:
    name: str
    #: `kisayol`, `exe`, `magaza` (Windows) ya da `xdg` (Linux).
    kind: str
    target: str
    #: Aramada adın yanında sayılan ikinci ad. Linux'ta `.desktop`un
    #: GenericName'i ("Web Browser"); Windows kaynakları doldurmuyor.
    alias: str = field(default="")

    def describe(self) -> str:
        return f"{self.name}  [{self.kind}]"


def normalise(text: str) -> str:
    ascii_text = text.translate(_ASCII).lower()
    return "".join(ch if ch.isalnum() else " " for ch in ascii_text).strip()


def _tokens(text: str) -> set[str]:
    return {t for t in normalise(text).split() if t and t not in _NOISE}


# --- kaynaklar -------------------------------------------------------------


def _start_menu() -> list[App]:
    roots = [
        Path(os.environ.get("ProgramData", "")) / "Microsoft/Windows/Start Menu/Programs",
        Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
    ]
    out: list[App] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.lnk"):
            # Kaldırma ve yardım kısayolları uygulama değil; ajanın
            # "uninstall" açması istenen son şey.
            if _tokens(path.stem) & {"uninstall", "kaldir", "help", "yardim",
                                     "readme", "website", "documentation"}:
                continue
            out.append(App(path.stem, "kisayol", str(path)))
    return out


def _app_paths() -> list[App]:
    if winreg is None:  # Linux: bu kaynak yok, katalog boş dönüyor
        return []
    out: list[App] = []
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            key = winreg.OpenKey(
                hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
            )
        except OSError:
            continue
        with key:
            for index in range(winreg.QueryInfoKey(key)[0]):
                try:
                    name = winreg.EnumKey(key, index)
                    with winreg.OpenKey(key, name) as sub:
                        target = winreg.QueryValueEx(sub, "")[0]
                except OSError:
                    continue
                if target and os.path.exists(target):
                    out.append(App(Path(name).stem, "exe", target))
    return out


def _store_apps() -> list[App]:
    """Mağaza uygulamaları. Başarısız olursa boş liste — katalog yine çalışır."""
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Get-StartApps | ForEach-Object { $_.Name + '|' + $_.AppID }"],
            capture_output=True, timeout=STORE_TIMEOUT,
            encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    out: list[App] = []
    for line in (done.stdout or "").splitlines():
        name, _, app_id = line.partition("|")
        # Klasik uygulamalar zaten kısayol olarak geliyor; buradan yalnızca
        # exe'si olmayan mağaza girdileri alınıyor.
        if name.strip() and "!" in app_id:
            out.append(App(name.strip(), "magaza", app_id.strip()))
    return out


# --- katalog ---------------------------------------------------------------

_cache: tuple[float, list[App]] | None = None


def _linux_arka_uc():
    """Bu oturum Linux mu? Öyleyse XDG modülü, değilse None.

    `erisim` içe aktarılamazsa (beklenmez) Windows yolu korunuyor —
    oturum sorusunun tek kaynağı orası.
    """
    try:
        from . import erisim

        if erisim.oturum().tur == "windows":
            return None
        from . import apps_linux

        return apps_linux
    except ImportError:  # pragma: no cover - erisim varken olmaz
        return None


def catalog(refresh: bool = False) -> list[App]:
    linux = _linux_arka_uc()
    if linux is not None:
        return linux.katalog(refresh)
    global _cache
    if not refresh and _cache and time.monotonic() - _cache[0] < CACHE_SECONDS:
        return _cache[1]

    apps: list[App] = []
    seen: set[str] = set()
    # Sıra önemli: aynı ada sahip iki girdide kısayol kazanıyor, çünkü
    # çalışma dizini ve argümanları taşıyor.
    for source in (_start_menu, _app_paths, _store_apps):
        try:
            found = source()
        except Exception:
            found = []
        for app in found:
            key = normalise(app.name)
            if key and key not in seen:
                seen.add(key)
                apps.append(app)
    apps.sort(key=lambda a: a.name.lower())
    _cache = (time.monotonic(), apps)
    return apps


def search(query: str, limit: int = 8) -> list[App]:
    """Sorguya en uygun uygulamalar, iyiden kötüye.

    Sıralama kasıtlı: tam ad > adın başı > kelime eşleşmesi > içinde geçme.
    "chrome" araması "Google Chrome"u "Chrome Remote Desktop"tan önce
    getirmeli, yoksa ajan yanlış uygulamayı açıyor.
    """
    hedef = normalise(query)
    if not hedef:
        return []
    kelimeler = _tokens(query)

    puanli: list[tuple[int, int, App]] = []
    for app in catalog():
        ad = normalise(app.name)
        tam = ad
        # Windows girdilerinde alan boş; Linux'ta GenericName ("Web Browser")
        # ikinci ad olarak daha zayıf bir puanla katılıyor — "tarayıcı"
        # araması Firefox'u "Firefox Web Browser"tan önce görmeli.
        takma = normalise(app.alias) if app.alias else ""
        if ad == hedef:
            puan = 0
        elif ad.startswith(hedef):
            puan = 1
        elif kelimeler and kelimeler <= _tokens(app.name):
            puan = 2
        elif takma and (takma == hedef or takma.startswith(hedef)
                        or hedef in takma):
            puan = 3
            tam = takma
        elif hedef in ad:
            puan = 4
        else:
            continue
        puanli.append((puan, len(tam), app))

    puanli.sort(key=lambda x: (x[0], x[1], x[2].name.lower()))
    return [app for _p, _l, app in puanli[:limit]]


def suggest(query: str, limit: int = 5) -> list[App]:
    """Öneri listesi — yazım hatalarını da yakalıyor.

    `search` kesin kurallarla çalışıyor ve doğru olan bu: bir yazım
    hatasını sessizce başka bir uygulamaya çözmek, ajanın istenmeyen bir
    programı açması demek. Ama *öneri* vermek zararsız ve asıl işe yarayacağı
    yer tam da yazım hatası: "spotfy" yazıldığında "Spotify" görünmeli.
    """
    import difflib

    kesin = search(query, limit=limit)
    if kesin:
        return kesin
    hedef = normalise(query)
    adlar = {normalise(a.name): a for a in catalog()}
    yakin = difflib.get_close_matches(hedef, adlar.keys(), n=limit, cutoff=0.6)
    return [adlar[ad] for ad in yakin]


def resolve(query: str) -> App | None:
    """Tek bir en iyi eşleşme, yoksa `None`."""
    found = search(query, limit=1)
    return found[0] if found else None


def launch_argv(app: App) -> list[str]:
    """Uygulamayı açacak komut.

    Kısayol ve mağaza girdileri `explorer.exe` üzerinden açılıyor: `.lnk`
    çözümünü ve `shell:AppsFolder` protokolünü bilen o.

    Linux `xdg` girdisi buraya hiç gelmiyor — `catalog` orada zaten
    `apps_linux`e devrediyor ve Exec çözümü orada kalıyor; bu fonksiyonun
    Linux dalı yalnızca elle kurulmuş bir `App` için emniyet kemeri.
    """
    if app.kind == "xdg":
        from . import apps_linux

        return apps_linux.launch_argv(app)
    if app.kind == "magaza":
        return ["explorer.exe", f"shell:AppsFolder\\{app.target}"]
    if app.kind == "kisayol":
        return ["explorer.exe", app.target]
    return [app.target]
