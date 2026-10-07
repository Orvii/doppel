"""Oturum açılışında kendiliğinden başlama — her platformda bir kayıt.

Windows'ta üç yol var ve ikisi **yönetici hakkı istiyor**:
`HKLM\\...\\Run` altına yazmak da, Zamanlanmış Görev oluşturmak da UAC
penceresi açtırıyor. Bir kutucuğu işaretlemenin bedeli yükseltme istemi
olamaz; kalan tek yol `HKEY_CURRENT_USER`:

    HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run

Kullanıcıya özel, yükseltme istemiyor, oturum açıldığında çalışıyor.

Linux'ta masaüstünden bağımsız tek yol XDG oturum açılış girdisi:

    ~/.config/autostart/doppel.desktop

GNOME, KDE, XFCE ve geri kalanı bu klasörü okuyor; systemd kullanıcı
servisi ya da dağıtıma özel bir şey yazmak, "her Linux'ta çalışır"
iddiasını masaüstü sayısı kadar kırılım hâline getirirdi.

## Komut satırı tırnaklanıyor

Windows'a yazılan şey `"...\\pythonw.exe" "...\\doppel.py"`. Tırnak süs
değil: kullanıcı adında boşluk olabiliyor (`C:\\Users\\Ada Lovelace\\...`)
ve tırnaksız bir komutu Windows ilk boşluktan bölüp `C:\\Users\\Ada.exe`
aramaya çıkıyor. Sessizce başlamayan bir uygulamanın sebebi de
görünmüyor. `python.exe` değil `pythonw.exe`: her açılışta bir konsol
penceresinin açılıp kalması, açılışta başlamanın bütün anlamını
götürürdü.

Linux'a yazılan şey `Exec="<depo kökü>/Doppel.sh"` — yine tırnaklı, aynı
gerekçeyle: depo yolu boşluk içerebiliyor ve `Exec` değerini masaüstü
ortamı boşluktan bölüyor. Sanal ortamı çözen şeyin kendisi zaten
`Doppel.sh`; buradan `python3 .../doppel.py` yazmak o çözümü atlardı.
Kurulum modeli "klasörü istediğin yere kopyala" olduğu için değişmeyen
kimlik depo yoludur; `Doppel.sh` girdi yazılırken var mı diye
bakılmıyor — bakan bir kontrol, kopyalama sonrası yalan söylerdi.

## "Açık" ne demek

`acik()` yalnızca kaydın var olmasına bakmıyor, komutun **bu** kurulumu
gösterdiğine bakıyor. Depo taşındıysa eski satır hâlâ duruyor ama hiçbir
şey başlatmıyor; orada işaretli bir kutu göstermek yalan olurdu.
İşaretsiz görünüyor, işaretlenince doğru yolla üzerine yazılıyor.

## Ürünün adı değişti

Ürün 2026-10-07'de Yan Masa'dan Doppel'e geçti; Windows'ta değerin adı
`Doppel`, Linux'ta dosyanın adı `doppel.desktop` oldu. Eski adla yazılmış
kayıt `acik()` tarafından zaten açık sayılmıyor (gösterdiği `yanmasa.py`
artık yok), ama sağlam durmasının sebebi bu değil: açarken ve kapatırken
eski kayıt da siliniyor. Bırakılsaydı her oturum açılışında var olmayan
bir betik başlatılmaya çalışılırdı.

Silme işi yalnızca **bize ait olduğu kanıtlanan** girdilere dokunuyor:
eski ad, imleç satırımız (`X-Doppel-Autostart`) ya da bizim betik
adlarımız. Oturum açılış klasöründe başka uygulamaların girdileri var ve
onları silmek, kullanıcının kurduğu hiçbir şeyin sebebi görünmeden
kaybolması demek olurdu.

Tek platform bağımlılığı `winreg`: yalnızca Windows'ta var, o yüzden
yalnızca Windows'ta içe aktarılıyor. Dalağın geri kalanı `app/isletim.py`
üzerinden bakıyor.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from . import isletim

if isletim.WINDOWS:
    import winreg
else:  # Linux: modül içe aktarılabilsin, ad var ama kullanılmıyor
    winreg = None  # type: ignore[assignment]

#: Windows'un oturum açılışında çalıştırdığı, kullanıcıya özel anahtar.
#: `HKEY_LOCAL_MACHINE` altındaki eşi yönetici hakkı istiyor.
ANAHTAR = r"Software\Microsoft\Windows\CurrentVersion\Run"

#: Değerin adı. Kayıt defterini elle açan biri bunu görüp ne olduğunu
#: anlayabilmeli; `doppel` değil, uygulamanın adı.
DEGER = "Doppel"

#: Ürünün eski adıyla yazılmış değer. Ad değişince siliniyor: bırakılsaydı
#: artık var olmayan `yanmasa.py`'yi her oturum açılışında başlatmayı
#: denerdi. `acik()` bunu **açık saymaz** — gösterdiği betik yok, yani
#: hiçbir şey başlatmıyor; işaretsiz görünmesi doğru.
ESKI_DEGER = "Yan Masa"

#: Linux'ta yazılan girdi dosyası ve ürünün eski adıyla yazılmış eşi.
XDG_DOSYA = "doppel.desktop"
ESKI_XDG_DOSYA = "yanmasa.desktop"

#: Bize ait bir girdiyi tanıyan imleç satırı. Ad değişse de kalıyor;
#: temizlik bu satıra, bilinen dosya adlarına ve betik adlarımıza bakıyor.
XDG_ISARET = "X-Doppel-Autostart"

#: Eski girdileri tanıyan betik adları — `yanmasa.py` ürünün ilk adından,
#: `doppel.py` bu dosyanın eski Linux sürümünden (sanal ortamı atlayan
#: `python3 .../doppel.py` girdisi).
_ESKI_BETIKLER = ("yanmasa.py", "doppel.py")


def _pythonw() -> Path:
    """Uygulamayı çalıştıracak yorumlayıcı.

    `sys.executable` geliştirirken `python.exe` oluyor; açılışta konsol
    istemediğimiz için yanındaki `pythonw.exe` tercih ediliyor. Yoksa
    (gömülü ya da alışılmadık bir kurulum) çalışan yorumlayıcı yazılıyor:
    konsollu başlamak, hiç başlamamaktan iyi.
    """
    calisan = Path(sys.executable)
    yanindaki = calisan.with_name("pythonw.exe")
    return yanindaki if yanindaki.exists() else calisan


def _betik() -> Path:
    """`doppel.py`'nin mutlak yolu — bu modülün bir üst klasöründe."""
    return Path(__file__).resolve().parent.parent / "doppel.py"


def komut() -> str:
    """Kayıt defterine yazılan komut satırı, iki parçası da tırnaklı."""
    return f'"{_pythonw()}" "{_betik()}"'


# --- Windows ---------------------------------------------------------------


def _yazili() -> str:
    """Kayıtlı değer; yoksa boş dize.

    Anahtar ya da değer yoksa bu bir hata değil, "kapalı" demek.
    """
    try:
        anahtar = winreg.OpenKey(winreg.HKEY_CURRENT_USER, ANAHTAR, 0,
                                 winreg.KEY_READ)
    except OSError:
        return ""
    try:
        deger, _tur = winreg.QueryValueEx(anahtar, DEGER)
    except OSError:
        return ""
    finally:
        winreg.CloseKey(anahtar)
    return str(deger)


def _acik_win() -> bool:
    """Açılışta **bu** kurulum başlıyor mu.

    Karşılaştırma betik yoluyla yapılıyor, komutun tamamıyla değil:
    sanal ortam `python.exe`'den `pythonw.exe`'ye geçmiş olabilir ve o
    fark kutuyu işaretsiz göstermeyi hak etmiyor. Yollar Windows'ta
    büyük/küçük harfe duyarsız.
    """
    yazili = _yazili()
    return bool(yazili) and str(_betik()).casefold() in yazili.casefold()


def _sil(anahtar, ad: str) -> None:
    """Bir değeri siler; yoksa sessizce çıkıyor. İstenen sonuç zaten o.

    İki ad ayrı ayrı siliniyor ki biri yokken diğeri atlanmasın: eski adlı
    satır, yeni ad hiç yazılmamış olsa da temizlenmeli.
    """
    try:
        winreg.DeleteValue(anahtar, ad)
    except OSError:
        pass


def _ac_win() -> None:
    """Değeri yazar. Zaten varsa üzerine yazılıyor — eski yol bayatsa
    düzeltmenin yolu bu."""
    anahtar = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, ANAHTAR, 0,
                                 winreg.KEY_SET_VALUE)
    try:
        winreg.SetValueEx(anahtar, DEGER, 0, winreg.REG_SZ, komut())
        _sil(anahtar, ESKI_DEGER)
    finally:
        winreg.CloseKey(anahtar)


def _kapat_win() -> None:
    """Değeri siler. Yoksa sessizce çıkıyor: istenen sonuç zaten bu."""
    try:
        anahtar = winreg.OpenKey(winreg.HKEY_CURRENT_USER, ANAHTAR, 0,
                                 winreg.KEY_SET_VALUE)
    except OSError:
        return
    try:
        _sil(anahtar, DEGER)
        _sil(anahtar, ESKI_DEGER)
    finally:
        winreg.CloseKey(anahtar)


# --- Linux (XDG oturum açılışı) --------------------------------------------


def _xdg_dizini() -> Path:
    """Oturum açılış klasörü. `XDG_CONFIG_HOME` varsa o, yoksa `~/.config`.

    Boş dize "tanımsız" sayılıyor: `XDG_CONFIG_HOME=` diye bırakan bir
    kabuk, girdileri geçerli dizinin altına yazdırırdı.
    """
    taban = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(taban) / "autostart"


def _xdg_yolu() -> Path:
    """Yazdığımız girdi dosyasının tam yolu."""
    return _xdg_dizini() / XDG_DOSYA


def _baslatici() -> Path:
    """`Doppel.sh`'nin mutlak yolu — `doppel.py` ile aynı klasörde."""
    return _betik().with_name("Doppel.sh")


def _xdg_kacis(yol: Path) -> str:
    """`Exec` değeri için tırnaklar ve kaçışlar.

    Masaüstü girdisi sözdiziminde çift tırnak içindeki `\\` ve `"` kaçış
    istiyor; yol boşluk içerebildiği için tırnak da şart.
    """
    metin = str(yol).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{metin}"'


def xdg_metni() -> str:
    """Yazılan `.desktop` dosyasının tam içeriği.

    `X-GNOME-Autostart-enabled` GNOME'un klasik anahtarı; diğer masaüstleri
    yok sayıyor, GNOME ise onsuz da açıyor ama açıkça yazmak niyeti
    belgeliyor. `X-Doppel-Autostart` bizim imlecimiz: temizlik bize ait
    dosyaları bu satırdan tanıyor ve başka uygulamaların girdilerine
    dokunmuyor.
    """
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Doppel\n"
        "Comment=Launch Doppel when you sign in\n"
        f"Exec={_xdg_kacis(_baslatici())}\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
        f"{XDG_ISARET}=true\n"
    )


def _exec_ayikla(metin: str) -> str:
    """Girdideki `Exec` değerinden ilk yol parçasını çıkarır.

    Ayıklama asgari: tırnaklıysa tırnak sökülüyor, kaçışlar çözülüyor,
    tırnak dışındaki ilk boşlukta kesiliyor. Tam bir masaüstü girdisi
    ayrıştırıcısı yazmak, tek satır okumak için koca bir sözdizimi
    olurdu.
    """
    for satir in metin.splitlines():
        if not satir.startswith("Exec="):
            continue
        deger = satir[len("Exec="):].strip()
        if deger.startswith('"'):
            son = 1
            parca = []
            while son < len(deger):
                if deger[son] == "\\" and son + 1 < len(deger):
                    parca.append(deger[son + 1])
                    son += 2
                    continue
                if deger[son] == '"':
                    break
                parca.append(deger[son])
                son += 1
            return "".join(parca)
        return deger.split(" ", 1)[0]
    return ""


#: Betik adlarımız, iki yandan sınırlı. `notdoppel.py` bize ait değil
#: (öndeki harf), `yanmasa.py.bak` de değil (arkadaki nokta): aksi hâlde
#: bir yedeği ya da adı benzeyen başka bir uygulamayı silerdik.
_BETIK_KALIBI = re.compile(
    r"(?<![\w.-])(?:"
    + "|".join(re.escape(b[:-3]) for b in _ESKI_BETIKLER)
    + r")\.py(?=$|[\s\"'])"
)


def _bizim_icerik(metin: str) -> bool:
    """Bu içerik bize mi ait. Silmeden önce soruluyor.

    Ölçüt bilinçli olarak dar: imleç satırımız ya da betik adlarımız.
    `Name=Doppel` gibi bir ada bakmak, adı benzeyen başka bir girdiyi
    silme riski taşırdı; ad benzerliği kanıt değil.
    """
    return XDG_ISARET in metin or bool(_BETIK_KALIBI.search(metin))


#: Bizim girdilerimizin bilinen dosya adları; ad değişse de eskiler burada
#: kalıyor ki taşınma sonrası temizlenebilsinler.
_BILINEN_ADLAR = {XDG_DOSYA.casefold(), ESKI_XDG_DOSYA.casefold()}


def _bizimki_mi(yol: Path) -> bool:
    """Dosya bize mi ait — silmeden önce soruluyor.

    Ölçüt bilinçli olarak dar: bilinen dosya adımız **ya da** içerikte
    imleç satırımız/betik adlarımız. Ada değil, kanıta bakılıyor:
    oturum açılış klasöründe başka uygulamaların girdileri var ve onları
    silmek, kullanıcının kurduğu hiçbir şeyin sebebi görünmeden
    kaybolması demek olurdu.
    """
    if yol.name.casefold() in _BILINEN_ADLAR:
        return True
    try:
        return _bizim_icerik(yol.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return False


def _eski_girdileri_sil(haric: Path | None = None) -> list[Path]:
    """Bizim eski girdilerimizi siler, başkalarınınkine dokunmaz.

    `haric` yeni yazdığımız dosya: o kalıyor. Silinenler listeleniyor ki
    test ne yapıldığını görebilsin.
    """
    silinen: list[Path] = []
    dizin = _xdg_dizini()
    try:
        adaylar = sorted(dizin.glob("*.desktop"))
    except OSError:
        return silinen
    for aday in adaylar:
        if haric is not None and aday == haric:
            continue
        if not _bizimki_mi(aday):
            continue
        try:
            aday.unlink()
            silinen.append(aday)
        except OSError:
            pass
    return silinen


def _acik_xdg() -> bool:
    """Açılışta **bu** kurulum başlıyor mu.

    Varlığa değil, `Exec`'in bu depodaki `Doppel.sh`'yi gösterdiğine
    bakılıyor — Windows tarafındaki betik yolu karşılaştırmasının eşi.
    Depo taşındıysa eski girdi hiçbir şey başlatmıyor ve işaretsiz
    görünmesi doğru.
    """
    yol = _xdg_yolu()
    try:
        metin = yol.read_text(encoding="utf-8")
    except OSError:
        return False
    return _exec_ayikla(metin) == str(_baslatici())


def _ac_xdg() -> None:
    """Girdiyi yazar, eski bizim girdilerimizi siler.

    Yazma önce geçici dosyaya, sonra `os.replace`: yarıda kalan bir
    yazma, hiçbir şey başlatmayan bozuk bir girdi bırakırdı ve o hâli
    "açık" gibi göstermek en kötüsü olurdu.
    """
    hedef = _xdg_yolu()
    hedef.parent.mkdir(parents=True, exist_ok=True)
    gecici = hedef.with_name(hedef.name + ".yeni")
    gecici.write_text(xdg_metni(), encoding="utf-8")
    os.replace(gecici, hedef)
    _eski_girdileri_sil(haric=hedef)


def _kapat_xdg() -> None:
    """Girdiyi ve bizim eski girdilerimizi siler; başkasına dokunmaz."""
    _eski_girdileri_sil()
    try:
        _xdg_yolu().unlink()
    except OSError:
        pass


# --- ortak yüz -------------------------------------------------------------


def acik() -> bool:
    """Oturum açılışında **bu** kurulum başlıyor mu."""
    return _acik_win() if isletim.WINDOWS else _acik_xdg()


def ac() -> None:
    """Kaydı yazar; eski bizim kayıtları temizler.

    Üzerine yazma bilinçli: eski yol bayatsa düzeltmenin yolu bu.
    """
    _ac_win() if isletim.WINDOWS else _ac_xdg()


def kapat() -> None:
    """Kaydı siler. Yoksa sessizce çıkıyor: istenen sonuç zaten bu."""
    _kapat_win() if isletim.WINDOWS else _kapat_xdg()