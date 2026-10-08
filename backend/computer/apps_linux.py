"""Kurulu uygulamaların kataloğu — Linux'ta XDG `.desktop` girdileri.

`apps.py`'nin Linux eşi: aynı genel API (catalog, search, suggest,
resolve, launch_argv, App) ama kaynak Windows'un Başlat menüsü değil,
masaüstü girdisi standardı. İki dizin okunuyor:

1. `XDG_DATA_HOME` (yoksa `~/.local/share`) `/applications` — kullanıcı
2. `XDG_DATA_DIRS` (yoksa `/usr/local/share:/usr/share`) `/applications`

## Exec alan kodları

`Exec=` değeri bir kabuk komutu değil, alan kodlu bir argv şablonu:
`%f`, `%F`, `%u`, `%U`, `%i`, `%c`, `%k`. Bunlar temizlenmeden çalıştırmak
uygulamaya boktan bir yol argümanı göndermek demek (`firefox %u` vaat
edilmiş bir URL olmadan). Kodlar atılıyor, `%%` tek `%` oluyor. `%i`
iki argümana açıldığı için o da atılıyor — bütünüyle.

Temizleme sonrası argv boş kalırsa (kalan yalnızca alan koduysa) komut
kırık sayılıp `gtk-launch <dosya>` yedeğine düşülüyor: dosya adını XDG
dizinlerine kendisi soran araç, kırık bir Exec'i yeniden yorumlamaktan
daha güvenilir.

## NoDisplay ve Hidden

`NoDisplay=true` girdiler katalogda **yok**: kullanıcı uygulama
menüsünde görmüyorsa ajanın da görmemesi doğru (kaldırma yardımcıları,
arka plan servisleri). `Hidden=true` zaten kullanıcının kaldırdığı bir
girdi — üzerine yazılmış sayılıyor. `Type=Application` olmayan girdiler
(Link, Directory) hiç okunmuyor.
"""

from __future__ import annotations

import os
import shlex
import time
from pathlib import Path

#: Windows tarafındakiyle aynı önbellek süresi ve aynı gerekçe: uygulama
#: kurmak seyrek bir iş, her `launch_app` çağrısında yüzlerce dosyayı
#: taramanın anlamı yok.
from .apps import CACHE_SECONDS, App, _tokens

#: `XDG_DATA_DIRS` set değilse standardın kendi varsayılanı.
_XDG_VARSAYILAN_DATA = "/usr/local/share:/usr/share"


def _veri_dizinleri(ortam: dict[str, str] | None = None) -> list[Path]:
    """Uygulama girdilerinin aranacağı `applications` dizinleri, öncelik sırasıyla.

    Sıra XDG'nin kendi kuralı: kullanıcı `XDG_DATA_HOME`, sonra
    `XDG_DATA_DIRS` soldan sağa. Aynı ada sahip girdide önce gelen
    kazanıyor (masaüstü ortamlarının da kuralı).
    """
    ortam = os.environ if ortam is None else ortam
    kokler: list[str] = []
    ev = ortam.get("HOME", "")
    veri_evi = ortam.get("XDG_DATA_HOME") or (str(Path(ev) / ".local/share") if ev else "")
    if veri_evi:
        kokler.append(veri_evi)
    # Ayırıcı `os.pathsep`: gerçek Linux'ta bu zaten ":" (XDG standardı),
    # ama Windows'ta simülasyon koşarken test yolları `C:\...` içeriyor ve
    # sabit ":" sürücü harfini ortadan bölüyordu (`['C', '\\Users\\...']`).
    # Platform kendi ayırıcısını söyler; Linux davranışı bit-bit aynı kalır.
    kokler += (ortam.get("XDG_DATA_DIRS") or _XDG_VARSAYILAN_DATA).split(os.pathsep)

    gorulen: set[Path] = set()
    out: list[Path] = []
    for kok in kokler:
        kok = kok.strip()
        if not kok:
            continue
        yol = Path(kok) / "applications"
        if yol not in gorulen:
            gorulen.add(yol)
            out.append(yol)
    return out


def alan_kodlarini_temizle(argv: list[str]) -> list[str]:
    """Exec argv'sinden alan kodlarını atar. `%%` tek `%` olur.

    Kodlar argümanın içine gömülü olabiliyor (`--profile %f` değil,
    `--profile=%f`): token içinde geçen her `%x` siliniyor. Sonuçta argv
    boşalırsa çağıran `gtk-launch` yedeğine düşüyor.
    """
    out: list[str] = []
    for parca in argv:
        temiz = []
        i = 0
        while i < len(parca):
            ch = parca[i]
            if ch != "%":
                temiz.append(ch)
                i += 1
                continue
            if i + 1 < len(parca) and parca[i + 1] == "%":
                temiz.append("%")
                i += 2
                continue
            # Tek yüzde + kod harfi: ikisi de düşüyor. Tanımadığımız `%x`
            # de düşüyor — bilinmeyen kodu korumak, uygulamaya ham `%x`
            # göndermek olurdu.
            i += 2
        sonuc = "".join(temiz)
        if sonuc:
            out.append(sonuc)
    return out


def exec_argv(exec_satiri: str) -> list[str]:
    """`Exec=` değerini argv'ye çevirir: shlex + alan kodu temizliği.

    Masaüstü standardının alıntılama kuralları shlex'in kuralıyla
    örtüşüyor (çift tırnak, ters bölü kaçışı). shlex'in kendisi patlarsa
    (kapanmamış tırnak) kırık Exec sayılıp boş liste dönüyor.
    """
    try:
        parcalar = shlex.split(exec_satiri)
    except ValueError:
        return []
    return alan_kodlarini_temizle(parcalar)


def girdi_ayristir(metin: str) -> dict[str, str]:
    """Bir `.desktop` dosyasını `[Desktop Entry]` anahtar/değer sözlüğüne çevirir.

    Yalnızca ilk bölüm okunuyor; `[Desktop Action ...]` bölümleri ayrı
    girdiler ve kataloğa karışmamalı. Aynı anahtar ikinci kez görülürse
    **son** değer kazanıyor: masaüstlerinin fiilî referansı GLib'in
    GKeyFile'i böyle yapıyor ve oradan farklı davranmak, aynı dosyada iki
    uygulamanın iki farklı `Exec` görmesi demek olurdu.
    """
    veri: dict[str, str] = {}
    bolum = ""
    for satir in metin.splitlines():
        satir = satir.strip()
        if not satir or satir.startswith("#"):
            continue
        if satir.startswith("[") and satir.endswith("]"):
            bolum = satir[1:-1]
            continue
        if bolum != "Desktop Entry" or "=" not in satir:
            continue
        anahtar, _, deger = satir.partition("=")
        veri[anahtar.strip()] = deger.strip()
    return veri


def girdiden_app(yol: Path, ortam: dict[str, str] | None = None) -> App | None:
    """Bir `.desktop` dosyasından `App`; atlanacaksa None.

    Ad seçimi: önce yerelleştirilmiş `Name[tr]` (kullanıcının kendi dili),
    yoksa `Name`. Sanal ad olarak GenericName saklanıyor — arayüz
    İngilizce ama `Name` birçok dağıtımda zaten yerelleştirilmiş geliyor;
    ikisini birden arayabilmek "tarayıcı" ile "Firefox"u aynı sonuçta
    buluşturuyor.
    """
    ortam = os.environ if ortam is None else ortam
    deneme = _yerel_ad_anahtarlari(ortam)
    try:
        metin = yol.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    veri = girdi_ayristir(metin)

    if veri.get("Type", "Application") != "Application":
        return None
    if _dogru_mu(veri.get("NoDisplay")) or _dogru_mu(veri.get("Hidden")):
        return None

    ad = next((veri[k] for k in deneme if veri.get(k)), "") or veri.get("Name", "")
    if not ad:
        return None
    # Kaldırma/yardım girdileri uygulama değil; Windows tarafındaki
    # `_start_menu` ile aynı süzgeç ve aynı gerekçe: ajanın "uninstall"
    # açması istenen son şey. Ölçüt ad ve GenericName birlikte — bazı
    # dağıtımlar bunu Name değil GenericName'e yazıyor.
    if _tokens(ad) & _KALDIRMA_SOZLERI or _tokens(veri.get("GenericName", "")) & _KALDIRMA_SOZLERI:
        return None
    # GenericName arama için ayrı taşınıyor (`App.alias`); Windows
    # girdileri bu alanı hiç doldurmuyor, orada davranış değişmiyor.
    return App(ad, "xdg", str(yol), veri.get("GenericName", ""))


#: Kataloğa alınmayan ad parçaları — Windows `_start_menu`ndeki kaldırma
#: süzgeciyle **birebir aynı küme**. Fark olsaydı iki platform aynı ada
#: farklı karar verir ve bu sessiz bir ayrışma olurdu; `remove` gibi fazladan
#: bir kelime meşru bir uygulamayı (ör. "Remove Background") eleyebilirdi.
_KALDIRMA_SOZLERI = {
    "uninstall", "kaldir", "help", "yardim", "readme", "website",
    "documentation",
}


def _yerel_ad_anahtarlari(ortam: dict[str, str]) -> list[str]:
    dil = ortam.get("LANGUAGE", "") or ortam.get("LC_ALL", "") or ortam.get("LANG", "")
    anahtarlar = ["Name"]
    if dil:
        kisa = dil.split(".")[0].split("@")[0]
        if kisa:
            anahtar = f"Name[{kisa}]"
            if anahtar != "Name":
                anahtarlar.insert(0, anahtar)
            temel = kisa.split("_")[0]
            if temel and temel != kisa:
                anahtarlar.insert(0, f"Name[{temel}]")
    return anahtarlar


def _dogru_mu(deger: str | None) -> bool:
    return (deger or "").strip().lower() == "true"


_cache: tuple[float, list[App]] | None = None


def katalog(refresh: bool = False) -> list[App]:
    """Tüm `.desktop` girdileri: kullanıcı dizini önce, çift ad ayıklanıyor.

    Önbellek `apps.py` ile aynı gerekçeyle ve aynı süreyle: her
    `launch_app` çağrısında yüzlerce dosyayı yeniden taramanın anlamı yok.
    """
    global _cache
    if not refresh and _cache and time.monotonic() - _cache[0] < CACHE_SECONDS:
        return _cache[1]

    bulunan: list[App] = []
    gorulen: set[str] = set()
    for dizin in _veri_dizinleri():
        if not dizin.exists():
            continue
        try:
            yollar = sorted(dizin.rglob("*.desktop"))
        except OSError:
            continue
        for yol in yollar:
            # Çift ayıklama masaüstü standardındaki gibi **dosya kimliğiyle**
            # (dizine göre relatif yol), adla değil: aynı `chrome.desktop`u
            # iki dizinde iki farklı `Name` ile yazan bir dağıtımda ada göre
            # ayıklamak ikisini birden gösterirdi.
            try:
                kimlik = yol.relative_to(dizin).as_posix()
            except ValueError:  # pragma: no cover - rglob her zaman içeride
                kimlik = yol.name
            if kimlik in gorulen:
                continue
            app = girdiden_app(yol)
            if app is None:
                continue
            gorulen.add(kimlik)
            bulunan.append(app)
    bulunan.sort(key=lambda a: a.name.lower())
    _cache = (time.monotonic(), bulunan)
    return bulunan


def launch_argv(app: App) -> list[str]:
    """Uygulamayı açacak komut — `apps.py` ile aynı sözleşme.

    Yol `xdg` girdisinde `.desktop` dosyasının kendisi; Exec'i kendimiz
    temizledik. Exec kırıksa (temizlik sonrası boş) `gtk-launch` yedeği:
    dosya adını XDG dizinlerine kendisi soran araç, kırık bir Exec'i
    yeniden yorumlamaktan daha güvenilir.
    """
    if app.kind == "gtk":
        return ["gtk-launch", app.target]
    if app.kind == "xdg":
        try:
            metin = Path(app.target).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ["gtk-launch", Path(app.target).stem]
        argv = exec_argv(girdi_ayristir(metin).get("Exec", ""))
        if argv and _calistirilabilir(argv[0]):
            return argv
        # Exec kırık ya da program PATH'te yok: gtk-launch dosya adını XDG
        # dizinlerine kendisi sorar.
        return ["gtk-launch", Path(app.target).stem]
    return [app.target]


def _calistirilabilir(ad: str) -> bool:
    """Program çalıştırılabilir mi: mutlak/relatif yol varsa dosya, yoksa PATH."""
    from .komut import var_mi

    if os.sep in ad or (os.altsep and os.altsep in ad):
        return os.path.isfile(ad) and os.access(ad, os.X_OK)
    return var_mi(ad) is not None