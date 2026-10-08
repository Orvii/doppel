"""X11 yan masa: kendi X ekranı, kendi pencereleri, kendi imleci.

Windows'ta yan masa bir masaüstü nesnesiydi (`CreateDesktopW`). X11'de
karşılığı **ayrı bir X sunucusu**: `Xvfb :99` görünmez, `Xephyr :99`
kullanıcının ekranında iç içe bir pencere (yaşam döngüsü `ekran_x11`de).
Uygulamalar `DISPLAY=:99` ile oraya doğuyor; pencere listesi, odak
zinciri ve imleç ana oturumdan tamamen bağımsız.

**Ana oturumun türü hiç sorulmuyor.** Yan masa bizim Xvfb'imiz; makinenin
kendi oturumu Wayland de olsa, hiç ekran da olmasa (headless) çalışır.
Arka uç seçimi `erisim.masa_sec`'te: Windows masaüstü nesnesi, diğer her
yerde bu modül.

## Pencereler nasıl bulunuyor: `xdotool search --onlyvisible --name .`

Pencere listesi EWMH'e (`_NET_CLIENT_LIST`) **dayanmıyor**. O liste
pencere yöneticisinin tuttuğu bir kayıt ve Xvfb'de WM yok; WM'siz bir
ekranda EWMH listesi boş kalır ve yan masa hiç pencere göremezdi.
`xdotool search` bunun yerine pencere ağacını yürüyor ve WM'siz bir
Xvfb'de de görünür üst düzey pencereleri buluyor. Süzgeç
`masaustu_ortak.ASGARI_EN/BOY`: aynı uygulama iki platformda aynı listede
görünsün diye.

## Yakalama: mss, `display=":99"`

`mss.mss(display=...)` Linux'ta `XOpenDisplay`e geçiyor (10.1.0'da
doğrulandı) — yani mss'ye hangi ekranı okuyacağı söylenebiliyor. Oturum
ilk yakalamada açılıp yan masa boyunca yaşıyor; kare başına yeni bir X
bağlantısı açmak saniyede sekiz karelik canlı görüntüde bağlantı
biriktirirdi. Oturum tek ve bir kilit altında: Xlib bağlantısı iş
parçacığı güvenli değil, yakalamayı iki thread istiyor (arayüzün canlı
görüntüsü ve ajanın `side_capture`ı). Sunucu kapanırken oturum önce
kapatılıyor (`kapat` içindeki sıra: kayıt → girdi oturumu → süreçler →
sunucu).

## Tuşlar ve `type`: odak PointerRoot'tur

Xvfb'de pencere yöneticisi yok; X sunucusunun varsayılan odağı
**PointerRoot** — yani tuşlar imlecin altındaki pencereye gider. Ajanın
imleci son tıkladığı yerdedir; `mesaj.py`nin X11 dalı bu yüzden yazma ve
tuş göndermeden **önce imleci ajanın konumuna taşıyor**: tuşun hangi
pencereye gideceği böylece "en son tıklanan pencere" oluyor — Windows'un
`self._odak` sözleşmesinin aynısı. Kalıcı risk: uygulama kendisi
`XSetInputFocus` çağırırsa odak değişir ve tuş başka yere gidebilir;
`ctrl+w` gibi yıkıcı bir kombinasyonun model tarafından bilinçsizce
gönderilmesini bu modül engelleyemiyor (Windows'ta da engellemiyordu —
orada da tuş kombinasyonu uygulamanın odakladığı denetime gidiyor).

## headless gerçeği: Chromium bayrakları

Xvfb'nin altında GPU ve compositor yok; Chromium ailesi (`--no-sandbox`,
`--disable-gpu` olmadan) yan ekranda ya açılmıyor ya boş geliyor. Bu iki
bayrak **yalnızca `baslat`tan geçen, yani yan masaya doğan** komutlara
ekleniyor (ve yalnızca Chromium ailesi için); kullanıcının kendi
masaüstündeki uygulamalara hiçbir yoldan bulaşmıyor.

## Kayıt bütün ekranı çeker

`side_act`/`side_capture` pencereyle konuşur ama kayıt (`kayit.py`)
x11grab ile **yan ekranın tamamını** çeker; pencere seçimi kaydı
daraltmıyor (sebebi ve bedeli `kayit.py` başlığında). Yani kayıt sürerken
ajan başka pencereye geçerse video onu da gösterir — Windows'ta bu
mümkün değildi, burada mümkün ve daha doğrusu.
"""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import threading
from collections.abc import Callable, Mapping, Sequence

from . import komut
from .capture import Frame
from .ekran_x11 import VARSAYILAN_OLCU
from .ekran_x11 import baslat as _sunucu_baslat
from .imlec import imlec_ciz
from .masaustu_ortak import (
    ASGARI_BOY,
    ASGARI_EN,
    GIZLI_EKRAN,
    YAN_AD,
    MasaustuHatasi,
    Pencere,
    yan_birak,
    yan_kaydet,
    yan_ortam,
)

#: Chromium ailesi + Electron kabukları. Xvfb altında bu ikisi olmadan
#: pencere gelmiyor (modül başlığı, "headless gerçeği").
YAN_BAYRAKLAR = ("--no-sandbox", "--disable-gpu")

SAYILAN_UYGULAMALAR = frozenset({
    "chrome", "google-chrome", "google-chrome-stable", "chromium",
    "chromium-browser", "chromium-freeworld", "msedge", "microsoft-edge",
    "brave", "brave-browser", "vivaldi", "electron",
})

#: Süreç ağacını durdurma sırası: SIGTERM → bu kadar bekle → SIGKILL.
#: `ekran_x11.Ekran.durdur` ile aynı disiplin; Windows'taki iş nesnesinin
#: (`KILL_ON_JOB_CLOSE`) karşılığı süreç grubudur: Chrome kendi işini
#: onlarca çocuğa bölüyor ve çocuklar ana süreç ölünce sağ kalıyor —
#: görünmez ekranda biriken görünmez Chrome, bir sonraki açılışta profil
#: kilidiyle devralıyor ve tıklamalar hiçbir yere ulaşmıyordu.
KAPANIS_BEKLEME = 3.0

#: Sert durdurma sinyali. Windows'ta `SIGKILL` **yok**; modül orada da
#: içe aktarılıyor (Linux güvenlik testleri her modülü içe aktarıyor) ve
#: `_surec_durdur` orada çağrılırsa `None` görüp `kill()` yoluna düşüyor.
#: Gerçek kullanım Linux'ta; bu yalnızca modülün taşınabilir kalması.
_SIGKILL = getattr(signal, "SIGKILL", None)


def tarayici_bayraklari(komut_metni: str) -> list[str]:
    """Yan masaya doğacak Chromium ailesi uygulamaların zorunlu bayrakları.

    Xvfb'nin altında GPU ve compositor yok: Chromium ailesi hem
    `--no-sandbox` hem `--disable-gpu` istiyor, yoksa pencere hiç
    açılmıyor ya da boş geliyor. Bayraklar **yalnızca yan masaya** doğan
    çocuğa eklenir (tek çağırıcı `Calisma.baslat`); kullanıcının kendi
    masaüstündeki uygulamalara asla bulaşmaz.
    """
    try:
        parcalar = shlex.split(komut_metni)
    except ValueError:
        return []
    if not parcalar:
        return []
    ad = os.path.basename(parcalar[0]).casefold()
    if ad.endswith(".exe"):
        ad = ad[:-4]
    return list(YAN_BAYRAKLAR) if ad in SAYILAN_UYGULAMALAR else []


def kirp(x: int, y: int, en: int, boy: int,
         monitor: Mapping) -> tuple[int, int, int, int] | None:
    """Pencere dikdörtgenini mss monitörünün içine kırpar.

    X11'de ölçek diye bir şey yok: xdotool ve mss **aynı** X sunucusunun
    aynı piksellerini okuyor (mss X11'de ham piksel veriyor; Windows'taki
    DPI ölçeklemesi burada yok). Yani pencere dikdörtgeni doğrudan kare
    kutusu — tek bir koordinat dili var, karışma ihtimali de yok.

    Kırpma yine de şart: taşan bir `grab` hata verir ve pencere canlı
    görüntüden sessizce düşerdi. Tamamen dışındaysa `None`.
    """
    sol = max(int(monitor["left"]), int(x))
    ust = max(int(monitor["top"]), int(y))
    sag = min(int(monitor["left"]) + int(monitor["width"]), int(x + en))
    alt = min(int(monitor["top"]) + int(monitor["height"]), int(y + boy))
    if sag <= sol or alt <= ust:
        return None
    return sol, ust, sag - sol, alt - ust


def ayristir_shell(cikti: str) -> dict[str, str]:
    """`xdotool ... --shell` çıktısını sözlüğe çevirir (`X=12` satırları)."""
    degerler: dict[str, str] = {}
    for satir in cikti.splitlines():
        anahtar, _, deger = satir.partition("=")
        if anahtar and deger:
            degerler[anahtar.strip()] = deger.strip()
    return degerler


def sinif_coz(cikti: str) -> str:
    """`xprop WM_CLASS` çıktısından ikinci (sınıf) adı çıkarır.

    Biçim: `WM_CLASS(STRING) = "chromium", "Chromium"`. İkinci ad
    uygulamanın kimliği; ilki örnek adı ve pencerenin başlığıyla birlikte
    değişebiliyor. Çıktı beklenenden farklıysa (boş, tek parça) elde ne
    varsa o dönüyor — hata değil, sınıfsız pencere.
    """
    _, _, kuyruk = cikti.partition("=")
    parcalar = [p.strip().strip('"') for p in kuyruk.split(",") if p.strip()]
    if not parcalar:
        return ""
    return parcalar[1] if len(parcalar) >= 2 else parcalar[0]


# --- pencere taraması ----------------------------------------------------


def _geometri(cal: Callable, hwnd: int, env: Mapping[str, str]) -> Pencere | None:
    """Bir pencere kimliğini okuyup `Pencere`ye çevirir. Okunamazsa `None`."""
    try:
        geo = cal(["xdotool", "getwindowgeometry", "--shell", str(int(hwnd))],
                  env_ek=dict(env), zaman_asimi=5.0)
        if geo.donus != 0:
            return None
        degerler = ayristir_shell(geo.cikti)
        x, y = int(degerler["X"]), int(degerler["Y"])
        en, boy = int(degerler["WIDTH"]), int(degerler["HEIGHT"])
    except (KeyError, ValueError, komut.KomutHatasi, komut.KomutYokHatasi):
        return None

    try:
        ad_sonuc = cal(["xdotool", "getwindowname", str(int(hwnd))],
                       env_ek=dict(env), zaman_asimi=5.0)
        baslik = ad_sonuc.cikti.strip() if ad_sonuc.donus == 0 else ""
    except (komut.KomutHatasi, komut.KomutYokHatasi):
        baslik = ""

    # xprop ayrı bir araç (x11-utils); yokluğu pencereyi düşürmemeli.
    try:
        sinif_sonuc = cal(["xprop", "-id", str(int(hwnd)), "WM_CLASS"],
                          env_ek=dict(env), zaman_asimi=5.0)
        sinif = sinif_coz(sinif_sonuc.cikti) if sinif_sonuc.donus == 0 else ""
    except (komut.KomutHatasi, komut.KomutYokHatasi):
        sinif = ""

    return Pencere(hwnd=int(hwnd), baslik=baslik, sinif=sinif,
                   x=x, y=y, en=en, boy=boy)


def pencere_listesi(env: Mapping[str, str] | None = None,
                    calistir: Callable | None = None,
                    asgari: tuple[int, int] = (ASGARI_EN, ASGARI_BOY)
                    ) -> list[Pencere]:
    """Yan ekrandaki görünür, kayda değer pencereler.

    `xdotool search --onlyvisible --name .` çıktısı kimlik listesi; her
    kimliğin geometrisi ayrı bir çağrıda okunuyor (xdotool tek çağrıda
    hepsini vermiyor). `env` hedef ekranı taşımak zorunda: buradan
    geçmeyen bir `DISPLAY` kullanıcının ekranına sorardı.
    """
    cal = calistir or komut.calistir
    cevre = dict(env or {})
    try:
        sonuc = cal(["xdotool", "search", "--onlyvisible", "--name", "."],
                    env_ek=cevre, zaman_asimi=5.0)
    except (komut.KomutHatasi, komut.KomutYokHatasi) as exc:
        raise MasaustuHatasi(f"could not list the side desk windows: {exc}") from None
    if sonuc.donus != 0:
        raise MasaustuHatasi(
            "could not list the side desk windows: "
            f"xdotool search failed ({sonuc.hata.strip()[:200] or 'no output'})"
        )
    bulunan: list[Pencere] = []
    for satir in sonuc.cikti.splitlines():
        satir = satir.strip()
        if not satir.isdigit():
            continue
        p = _geometri(cal, int(satir), cevre)
        if p is not None and p.en >= asgari[0] and p.boy >= asgari[1]:
            bulunan.append(p)
    return bulunan


def pencere_bilgisi(hwnd: int, env: Mapping[str, str] | None = None,
                    calistir: Callable | None = None) -> Pencere:
    """Tek pencereyi oku. Okunamazsa açık hata — boş kayıt değil."""
    p = _geometri(calistir or komut.calistir, int(hwnd), dict(env or {}))
    if p is None:
        raise MasaustuHatasi(f"could not read window {hwnd} on the side desk")
    return p


# --- süreç grubu ---------------------------------------------------------


def _varsayilan_ac(olcu: str):
    return _sunucu_baslat(olcu=olcu)


def _popen(argv: list[str], secenekler: Mapping) -> subprocess.Popen:
    """Varsayılan doğurucu — testler bunu sahteliyor.

    `stdout/stderr` yutuluyor (uygulama kendi günlüğünü tutar;
    `side_launch` çıktısını kimse okumuyor) ve `start_new_session=True`
    ile her çocuk kendi süreç grubuna giriyor — `_surec_durdur` grubu
    topluca vuruyor (KAPANIS_BEKLEME notu).
    """
    return subprocess.Popen(
        argv,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        **secenekler,
    )


def _oturum_ac(gosterge: str):
    """Yan ekrana bağlı bir mss oturumu (tembel içe aktarma: mss yalnızca
    gerçekten yakalanacağı anda yükleniyor)."""
    import mss  # noqa: PLC0415 - bilinçli tembel: yakalama yoksa paket gerekmiyor

    return mss.mss(display=gosterge)


class Calisma:
    """Ajanın yan ekranı ve orada başlattığı süreçler.

    `masaustu.Calisma` (Windows) ile aynı yüzey: `ac/kapat/baslat/
    pencereler/pencere_bul/yakala/istemci_kutusu/pencere_bilgisi`. Tek
    örnek olarak kullanılmak üzere yazıldı: gösterge kaydı tek bir yan
    masaya izin veriyor (`masaustu_ortak` başlığı).
    """

    def __init__(self, ad: str = YAN_AD, olcu: str = VARSAYILAN_OLCU,
                 ac: Callable[[str], object] | None = None,
                 calistir: Callable | None = None,
                 oturum_ac: Callable[[str], object] | None = None,
                 dogurucu: Callable[[list[str], dict], object] | None = None
                 ) -> None:
        self.ad = ad
        self._olcu = olcu
        self._ac = ac or _varsayilan_ac
        self._cal = calistir or komut.calistir
        self._oturum_ac = oturum_ac or _oturum_ac
        self._dogur = dogurucu or _popen
        self._ekran = None
        self._oturum = None
        self._surecler: list = []
        self._kilit = threading.RLock()

    # -- yaşam döngüsü ----------------------------------------------

    def ac(self) -> None:
        """Boş bir gösterge numarasına X sunucusunu başlatır."""
        if self._ekran is not None:
            return
        ekran = self._ac(self._olcu)
        self._ekran = ekran
        # Gösterge kaydı: `mesaj.Girdi` ve `kayit.EkranKaydi` hedef ekranı
        # çağrı ANINDA buradan okuyor (masaustu_ortak başlığı).
        yan_kaydet(ekran.gosterge)

    def kapat(self) -> None:
        """Kayıt oturumu, süreçler ve sunucu — sırayla ve hepsi.

        Sıra bilinçli: X oturumu (mss) sunucudan önce kapanmalı, yoksa
        kapanmış bir ekrana grab denemesi olur. Süreçler sunucudan önce
        duruyor: Xvfb son istemci gidince sıfırlanıyor (`-noreset` bunu
        engelliyor) ve pencere listesi tutarsız kalırdı.
        """
        with self._kilit:
            oturum, self._oturum = self._oturum, None
            if oturum is not None:
                try:
                    oturum.close()
                except Exception:
                    pass
            surecler, self._surecler = self._surecler, []
            for surec in surecler:
                _surec_durdur(surec)
            ekran, self._ekran = self._ekran, None
        if ekran is not None:
            ekran.durdur()
        yan_birak()

    def __enter__(self) -> "Calisma":
        self.ac()
        return self

    def __exit__(self, *_hata) -> None:
        self.kapat()

    # -- süreç ------------------------------------------------------

    def baslat(self, komut_metni: str, calisma_dizini: str | None = None) -> int:
        """Komutu **yan ekranda** başlatır, PID döndürür.

        Kabuk yok: `shlex.split` ile argv'ye çevriliyor (tırnaklı yollar
        çalışır, `>`/`|` çalışmaz — Windows'taki `CreateProcessW` gibi).
        Ortam `yan_ortam`dan: `DISPLAY=:n` yazılı, `WAYLAND_DISPLAY`
        silinmiş. Chromium ailesine headless bayrakları eklenir.
        """
        self.ac()
        cevre = self._ortam()
        try:
            argv = shlex.split(komut_metni)
        except ValueError as exc:
            raise MasaustuHatasi(f"could not parse the command: {exc}") from None
        if not argv:
            raise MasaustuHatasi("empty command")
        argv += tarayici_bayraklari(komut_metni)
        try:
            surec = self._dogur(argv, {
                "cwd": calisma_dizini or os.getcwd(),
                "env": cevre,
            })
        except OSError as exc:
            raise MasaustuHatasi(
                f"could not start the process ({exc}): {komut_metni}") from None
        with self._kilit:
            self._surecler.append(surec)
        return surec.pid

    def sonlandir(self, pid: int) -> bool:
        """Bu yan ekranda başlatılmış bir süreci durdurur."""
        with self._kilit:
            for surec in list(self._surecler):
                if surec.pid != int(pid):
                    continue
                self._surecler.remove(surec)
                _surec_durdur(surec)
                return True
        return False

    # -- pencereler -------------------------------------------------

    @property
    def gosterge(self) -> str | None:
        return self._ekran.gosterge if self._ekran is not None else None

    def pencereler(self) -> list[Pencere]:
        """Yan ekrandaki görünür ve kayda değer pencereler.

        Kutu açılmadan boş liste — Windows'taki davranışın aynısı:
        `side_windows` masa kapalıyken hata değil, boş liste diyor.
        """
        if self._ekran is None:
            return []
        return pencere_listesi(self._ortam(), calistir=self._cal)

    def pencere_bul(self, parca: str) -> Pencere | None:
        """Başlığında `parca` geçen ilk pencere. Büyük/küçük harf umursamaz."""
        aranan = parca.casefold()
        for p in self.pencereler():
            if aranan in p.baslik.casefold():
                return p
        return None

    def pencere_bilgisi(self, hwnd: int) -> Pencere:
        """Tek pencereyi **yan ekrandan** okur (canli.py bu metodu arıyor)."""
        return pencere_bilgisi(hwnd, self._ortam(), calistir=self._cal)

    def istemci_kutusu(self, hwnd: int) -> tuple[int, int, int, int]:
        """İstemci alanı X11'de pencerenin kendisidir: (0, 0, en, boy).

        Windows'ta `PrintWindow` başlık çubuğunu da verir ve kırpma
        gerekir; Xvfb'de pencere yöneticisi yok, çerçeve çizen yok —
        pencere kimliğinin geometrisi zaten istemci alanı. Canlı görüntü
        (`canli.py`) bu yüzden X11'de hiç kırpmıyor.
        """
        p = self.pencere_bilgisi(hwnd)
        return 0, 0, p.en, p.boy

    # -- yakalama ---------------------------------------------------

    def yakala(self, hwnd: int, imlec: tuple[int, int] | None = None,
               iz: Sequence[tuple[int, int]] = (), tik: bool = False) -> Frame:
        """Bir pencereyi yan ekrandan yakalar.

        `PrintWindow` yok; ama gerek de yok: yan ekran gerçek bir X
        sunucusu ve `mss(display=:n)` oradan okuyabiliyor (modül
        başlığı). Kare `GIZLI_EKRAN` işaretiyle dönüyor — canlı görüntü
        ve model aynı sözleşmeyi görsün diye.
        """
        with self._kilit:
            if self._ekran is None:
                raise MasaustuHatasi("the side desk is not open")
            p = pencere_bilgisi(hwnd, self._ortam(), calistir=self._cal)
            if p.en <= 0 or p.boy <= 0:
                raise MasaustuHatasi(f"invalid window size: {p.en}x{p.boy}")
            oturum = self._oturum_ver()
            monitor = oturum.monitors[0]
            kutu = kirp(p.x, p.y, p.en, p.boy, monitor)
            if kutu is None:
                raise MasaustuHatasi(
                    f"window {hwnd} is outside the side screen "
                    f"({p.x},{p.y} {p.en}x{p.boy})"
                )
            # `kutu` ekran koordinatında; mss'nin kutusu da ekran
            # koordinatı (monitor["left"]/["top"] zaten 0, yine de
            # monitör ofseti ekleniyor — çok monitörlü bir X'te doğru
            # olan bu).
            ham = oturum.grab({
                "left": kutu[0],
                "top": kutu[1],
                "width": kutu[2],
                "height": kutu[3],
            })
        from PIL import Image  # noqa: PLC0415 - yakalama yolunda tek yerde

        gorsel = Image.frombytes("RGB", ham.size, ham.bgra, "raw", "BGRX")
        if imlec is not None:
            # İmleç ve iz pencerenin dışında da doğru yerde kalsın diye
            # kırpma yok (Windows'taki gerekçenin aynısı): Pillow taşan
            # çizimi kesiyor. Tıklama ile aynı dil: ikisi de X pikseli.
            def yerel(n: tuple[int, int]) -> tuple[int, int]:
                return (int(n[0]) - kutu[0], int(n[1]) - kutu[1])

            imlec_ciz(gorsel, *yerel(imlec), [yerel(n) for n in iz], tik)
        return Frame.from_capture(GIZLI_EKRAN, gorsel)

    def _oturum_ver(self):
        if self._oturum is None:
            self._oturum = self._oturum_ac(self._ekran.gosterge)
        return self._oturum

    def _ortam(self) -> dict[str, str]:
        if self._ekran is None:
            raise MasaustuHatasi("the side desk is not open")
        return yan_ortam(self._ekran.gosterge)


def _surec_durdur(surec, bekleme: float = KAPANIS_BEKLEME) -> None:
    """Süreç **grubunu** nazikçe durdurur; cevap vermezse öldürür.

    `terminate` yalnızca ana süreci vurur; Chrome'un çocukları ayrı
    süreçler ve sağ kalırlar (modül başındaki KAPANIS_BEKLEME notu).
    `start_new_session=True` her çocuğu kendi grubuna koyduğu için grup
    sinyali ana süreçle birlikte ağacın tamamını kapsıyor. Grup yoksa
    (süreç çoktan ölmüş) tek süreç sinyaline düşülüyor.
    """
    if surec.poll() is not None:
        return
    if _SIGKILL is None:  # Windows: grup sinyali yok, süreç ağacı yok
        _grup_sinyal(surec, signal.SIGTERM)
        try:
            surec.wait(timeout=bekleme)
        except (subprocess.TimeoutExpired, OSError):
            try:
                surec.kill()
                surec.wait(timeout=bekleme)
            except (subprocess.TimeoutExpired, OSError, AttributeError):
                pass
        return
    _grup_sinyal(surec, signal.SIGTERM)
    try:
        surec.wait(timeout=bekleme)
        return
    except subprocess.TimeoutExpired:
        pass
    _grup_sinyal(surec, _SIGKILL)
    try:
        surec.wait(timeout=bekleme)
    except subprocess.TimeoutExpired:
        # Buraya düşen süreç canlı kalıyor; kapanış yolunda daha fazla
        # beklemek kapanışı geciktirmekten başka bir şey yapmaz.
        pass


def _grup_sinyal(surec: subprocess.Popen, isaret: int) -> None:
    try:
        os.killpg(os.getpgid(surec.pid), isaret)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            surec.send_signal(isaret)
        except (ProcessLookupError, OSError):
            pass