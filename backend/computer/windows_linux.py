"""Ön plandaki pencere — EWMH (xprop/wmctrl) ile Linux karşılığı.

`windows.py`'nin Linux'taki eşi: aynı genel API (foreground_title,
foreground_process, find_window, force_foreground, activate, window_rect,
wait_for_foreground, matches_foreground). Alt süreç çağrılarının hepsi
`komut` kapısından geçiyor; hiçbir çağrı zaman aşımı olmadan yapılmıyor
(asılı kalma, yanlış veriden de kötüdür).

## Wayland'de yok — ve bu dürüstçe söyleniyor

Wayland'da bir uygulamanın başka uygulamaların pencerelerini görmesinin
ya da öne getirmesinin taşınabilir bir yolu yok; XWayland da değiştirmiyor
(yalnızca kendi X istemcilerini gösterir, oradan okunan `_NET_ACTIVE_WINDOW`
gerçek ön planı değil **başka bir istemciyi** anlatır — sessizce yarım
çalışan yol). O yüzden Wayland/ekransız oturumda her işlem
`PencereYonetimiYokHatasi` ile, sebebi söyleyen tek cümleyle düşüyor;
uydurma başlık, uydurma dikdörtgen, "aktive edildi" yalanı yok.

## Oturum kararı `erisim`de

"Bu makinede X11 mi" sorusu burada cevaplanmıyor; `erisim.oturum()`a
soruluyor — `DISPLAY` dolu olsa bile Wayland'ı Wayland sayan tek yer orası.
Bu modül yalnızca "X11 ise hangi araç, hangi komut" bilgisini taşıyor.
"""

from __future__ import annotations

import os
import subprocess
import time

from . import erisim, komut

#: Okuma çağrılarının sınırı. xprop takılı kalan bir X sunucusunda asılı
#: kalırsa çağrı burada kesiliyor — araç yoksa da hata açık.
OKUMA_SINIRI = 2.0

#: `wmctrl -i -a` WM'e bir istek bırakıyor; WM kabul etmeyebilir. Bu yüzden
#: sonuç varsayılmıyor, `activate` ön plan kimliği değişene kadar bekliyor.
AKTIF_SINIRI = 3.0


class PencereYonetimiYokHatasi(RuntimeError):
    """Bu oturumda pencere yönetimi yok: Wayland, ekransız ya da araç eksik.

    WindowsGerekli'nin Linux karşılığı: içe aktarma patlamıyor, çağrı
    anında ne olduğunu söyleyen açık bir hata var.
    """


def musait() -> bool:
    """X11 oturumu + xprop var mı. Ağaç gezmez, ucuz yoklama."""
    return _sebep() == ""


def yokluk_sebebi() -> str:
    """Pencere yönetimi neden yok — insan okunur tek cümle, ya da boş dize."""
    return _sebep()


def _sebep() -> str:
    oturum_ = erisim.oturum()
    if oturum_.tur == "windows":
        return "this session is Windows; the Win32 path is in use"
    if oturum_.tur == "wayland":
        return (
            "this is a Wayland session — reading or raising other "
            "applications' windows is not possible on Wayland"
        )
    if oturum_.tur == "headless":
        return "there is no X display in this session"
    if komut.var_mi("xprop") is None:
        return "xprop is not installed (install x11-utils)"
    return ""


def _x_env() -> dict[str, str]:
    """Alt süreçlere geçirilecek DISPLAY: oturumun kendi ekranı."""
    goster = erisim.oturum().x_goster
    return {"DISPLAY": goster} if goster else {}


def _calistir(argv: list[str], zaman_asimi: float = OKUMA_SINIRI) -> komut.KomutSonuc:
    """`komut.calistir` + bu modülün hata sözlüğü.

    Zaman aşımı ve eksik araç `KomutYokHatasi`/`TimeoutExpired` olarak
    sızarsa çağıran "neden" sorusunun cevabını bulamaz; ikisi de burada
    tek açık hataya çevriliyor.
    """
    if komut.var_mi(argv[0]) is None:
        raise PencereYonetimiYokHatasi(
            f"window management requires {argv[0]}, which is not installed"
        )
    try:
        return komut.calistir(argv, env_ek=_x_env(), zaman_asimi=zaman_asimi)
    except komut.KomutYokHatasi:  # varlık yarışı: PATH'ten tam yol kayboldu
        raise PencereYonetimiYokHatasi(
            f"window management requires {argv[0]}, which is not installed"
        ) from None
    except subprocess.TimeoutExpired:
        raise PencereYonetimiYokHatasi(
            f"{argv[0]} did not answer within {zaman_asimi}s"
        ) from None


def _gerekli() -> None:
    sebep = _sebep()
    if sebep:
        raise PencereYonetimiYokHatasi(f"window management is unavailable: {sebep}")


# --- Ayrıştırıcılar (saf; örnek çıktılarla test edilir) -----------------------


def aktif_id_ayristir(cikti: str) -> int | None:
    """`xprop -root _NET_ACTIVE_WINDOW` çıktısından pencere kimliği.

    Beklenen satır: `_NET_ACTIVE_WINDOW(WINDOW): window id # 0x3400007`.
    Pencere yoksa X `0x0` der; o da None (Windows'ta GetForegroundWindow'ın
    0 dönmesiyle aynı anlam).
    """
    for satir in cikti.splitlines():
        if "_NET_ACTIVE_WINDOW" not in satir:
            continue
        _, _, kuyruk = satir.partition("#")
        ham = kuyruk.strip().split()[0] if kuyruk.strip() else ""
        try:
            kimlik = int(ham, 0)
        except ValueError:
            return None
        return kimlik or None
    return None


def baslik_ayristir(cikti: str) -> str:
    """`xprop -id <id> _NET_WM_NAME WM_NAME` çıktısından başlık.

    `_NET_WM_NAME` tercih ediliyor (UTF-8); yoksa `WM_NAME`. Değer çift
    tırnak içinde; kaçışlı tırnak (`\\"`) ve kaçışsız ters bölü düzgün
    çözülüyor.
    """
    sonuc = ""
    for satir in cikti.splitlines():
        if "WM_NAME" not in satir or "=" not in satir:
            continue
        _, _, deger = satir.partition("=")
        cozulen = _tirnak_coz(deger.strip())
        if satir.lstrip().startswith("_NET_WM_NAME"):
            return cozulen  # UTF-8 sürümü her zaman kazanır
        sonuc = cozulen
    return sonuc


def _tirnak_coz(deger: str) -> str:
    if not deger.startswith('"'):
        return ""
    govde = deger[1:]
    # Sondaki tırnak stdout'a innerler; kaçışlı tırnak içeride kalabilir.
    if govde.endswith('"') and not govde.endswith('\\"'):
        govde = govde[:-1]
    out: list[str] = []
    kacisli = False
    for ch in govde:
        if kacisli:
            out.append(ch)
            kacisli = False
        elif ch == "\\":
            kacisli = True
        else:
            out.append(ch)
    return "".join(out)


def pid_ayristir(cikti: str) -> int | None:
    """`xprop -id <id> _NET_WM_PID` çıktısından süreç kimliği."""
    for satir in cikti.splitlines():
        if "_NET_WM_PID" not in satir or "=" not in satir:
            continue
        _, _, deger = satir.partition("=")
        try:
            return int(deger.strip())
        except ValueError:
            return None
    return None


def wmctrl_satirlari_ayristir(cikti: str) -> list[tuple[int, str]]:
    """`wmctrl -l` çıktısı -> [(kimlik, başlık)]. Biçim:

    `0x03e00003  0 myhost Firefox — bir şeyler`. Sunucu adı boşluk
    içerebilir; başlık son alan olduğu için `split(maxsplit=3)` doğru.
    """
    out: list[tuple[int, str]] = []
    for satir in cikti.splitlines():
        parcalar = satir.split(maxsplit=3)
        if len(parcalar) < 4:
            continue
        try:
            kimlik = int(parcalar[0], 0)
        except ValueError:
            continue
        out.append((kimlik, parcalar[3]))
    return out


def wmctrl_geometri_ayristir(cikti: str) -> list[tuple[int, int, int, int, int, str]]:
    """`wmctrl -lG` çıktısı -> [(kimlik, sol, üst, genişlik, yükseklik, başlık)].

    Biçim: `0x03e00003  0 100 50 800 600 myhost başlık` — sunucu adı ve
    başlık son iki alan, ikisi birlikte `split(maxsplit=7)` ile ayrılıyor.
    """
    out: list[tuple[int, int, int, int, int, str]] = []
    for satir in cikti.splitlines():
        parcalar = satir.split(maxsplit=7)
        if len(parcalar) < 8:
            continue
        try:
            kimlik = int(parcalar[0], 0)
            x, y, en, boy = (int(p) for p in parcalar[2:6])
        except ValueError:
            continue
        out.append((kimlik, x, y, en, boy, parcalar[7]))
    return out


# --- Genel API — `windows.py` ile birebir imzalar -----------------------------


def foreground_id() -> int | None:
    """`_NET_ACTIVE_WINDOW` kimliği; pencere yoksa None."""
    _gerekli()
    sonuc = _calistir(["xprop", "-root", "_NET_ACTIVE_WINDOW"])
    return aktif_id_ayristir(sonuc.cikti)


def foreground_title() -> str:
    """Ön plandaki pencerenin başlığı. Pencere yoksa boş dize."""
    _gerekli()
    kimlik = foreground_id()
    if kimlik is None:
        return ""
    sonuc = _calistir(
        ["xprop", "-id", hex(kimlik), "_NET_WM_NAME", "WM_NAME"]
    )
    return baslik_ayristir(sonuc.cikti)


def foreground_process() -> str:
    """Ön plandaki pencerenin süreç adı, örn. `firefox`.

    `_NET_WM_PID` → `/proc/<pid>/comm`. Uygulama PID'i yayımlamıyorsa
    (bazı GTK uygulamaları yayımlamıyor) boş dize: "bilinmiyor", uydurma
    değil.
    """
    _gerekli()
    kimlik = foreground_id()
    if kimlik is None:
        return ""
    sonuc = _calistir(["xprop", "-id", hex(kimlik), "_NET_WM_PID"])
    pid = pid_ayristir(sonuc.cikti)
    if pid is None:
        return ""
    try:
        with open(f"/proc/{pid}/comm", encoding="utf-8") as dosya:
            return dosya.read().strip()
    except OSError:
        return ""


def find_window(title_contains: str) -> int:
    """Başlığında verilen metin geçen ilk pencerenin kimliği; yoksa 0.

    `windows.py` sözleşmesiyle aynı: 0 "bulunamadı" demek. Yalnızca
    `wmctrl -l`nin listelediği pencereler — istemci listesi tutmayan bir
    WM'de (nadir) bu liste boş kalır ve cevap dürüstçe 0 olur.
    """
    _gerekli()
    if komut.var_mi("wmctrl") is None:
        raise PencereYonetimiYokHatasi(
            "finding windows by title requires wmctrl, which is not installed"
        )
    hedef = title_contains.lower()
    sonuc = _calistir(["wmctrl", "-l"])
    for kimlik, baslik in wmctrl_satirlari_ayristir(sonuc.cikti):
        if hedef in baslik.lower():
            return kimlik
    return 0


def force_foreground(wid: int) -> None:
    """Bir pencereyi öne getirmeyi ister. Sonuç doğrulanmaz — çağıran doğrulasın.

    `wmctrl -i -a` WM'e `_NET_ACTIVE_WINDOW` istemci mesajı bırakır;
    Windows'ta olduğu gibi WM bunu reddedebilir. Bu yüzden "aktive ettim"
    denmiyor, yalnızca isteniyor.
    """
    _gerekli()
    _calistir(["wmctrl", "-i", "-a", hex(wid)])


def activate(title_contains: str, timeout: float = AKTIF_SINIRI) -> bool:
    """Pencereyi öne getirir. Getiremezse `False` — yalan söylemiyor.

    Doğrulama başlıkla değil **kimlikle**: başlıklar kaydetme sırasında
    değişiyor (`*` gidiyor), kimlik değişmiyor.
    """
    wid = find_window(title_contains)
    if not wid:
        return False
    force_foreground(wid)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if foreground_id() == wid:
            return True
        time.sleep(0.1)
    return False


def window_rect(title_contains: str) -> tuple[int, int, int, int] | None:
    """Pencerenin dikdörtgeni: (sol, üst, sağ, alt); yoksa None.

    `wmctrl -lG`nin verdiği istemci geometrisi; Windows'taki
    GetWindowRect'e en yakın EWMH karşılığı.
    """
    _gerekli()
    if komut.var_mi("wmctrl") is None:
        raise PencereYonetimiYokHatasi(
            "reading window rectangles requires wmctrl, which is not installed"
        )
    hedef = title_contains.lower()
    sonuc = _calistir(["wmctrl", "-lG"])
    for _kimlik, x, y, en, boy, baslik in wmctrl_geometri_ayristir(sonuc.cikti):
        if hedef in baslik.lower():
            return (x, y, x + en, y + boy)
    return None


def matches_foreground(process: str | None, title_contains: str | None) -> bool:
    """Beklenen pencere odakta mı. `windows.py` ile aynı karşılaştırma."""
    if process is not None and foreground_process().lower() != process.lower():
        return False
    if title_contains is not None and title_contains.lower() not in foreground_title().lower():
        return False
    return True


def wait_for_foreground(
    process: str | None = None,
    title_contains: str | None = None,
    timeout: float = 5.0,
    poll: float = 0.1,
) -> bool:
    """Beklenen pencere öne gelene kadar bekler. Geldiyse True.

    Zaman aşımı sınırlı ve sabit: sonsuz bir bekleme, ajanı sağır
    bırakmanın en kolay yolu olurdu.
    """
    if process is None and title_contains is None:
        raise ValueError("process ya da title_contains verilmeli")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if matches_foreground(process, title_contains):
            return True
        time.sleep(poll)
    return False