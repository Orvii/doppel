"""Dikiş sürücüleri — port-temel'in `erisim` kayıt yüzüne portalı bağlar.

port-temel'in sözleşmesi (`backend/computer/erisim.py`, port/temel):

    surucu_kaydet(ad, sinif, musait, tur)
    tur: "girdi" | "goruntu" | "ekran"
    sınıflar lazily, `sinif(env)` ile kuruluyor; env Wayland'de {}.

Bu dosya o sınıfları üretiyor. Kural: **sınıf kurulurken portal oturumu
AÇILMAZ** — oturum açmak onay diyaloğu demek ve `musait()` sınaması diyalog
açmamalı. Oturum ilk gerçek kullanımda kuruluyor.

## Hangi yol kaydediliyor, hangisi kaydedilmiyor

  girdi (girdi)  → `GirdiSurucusu` — kaydedilmeye hazır
  görüntü        → `EkranSurucusu` — **kaydedilmiyor**, aşağıya bak
  ekran          → `MonitorSurucusu` — kaydedilmiyor, gerekçesi aşağıda

## Ekran yakalama neden kaydedilmiyor

`EkranSurucusu.grab` kare üretemiyor (PipeWire dönüşümü bu yapıda yok,
ayrıntısı `portal_ekran` docstring'inde). Dikişe **kaydetmek**, seçimin bu
sürücüyü kazanması demek olurdu; o zaman Wayland'de ekran görüntüsü isteyen
her çağrı, çalışan bir yol varsa bile düşen yola giderdi. Kaydetmemek
dürüst olan: dikiş "görüntü" için sürücü bulamaz, hatası net olur, ve yolu
açmak isteyen tek yeri (`grab`) bilir. Kayıt açıldığında tek satır:

    surucu_kaydet("portal", EkranSurucusu, portal_musait_mi, tur="goruntu")

## Monitör listesi neden kaydedilmiyor

Wayland'de monitör envanteri (konum/boyut) yalnızca **onaylanmış** bir
ScreenCast oturumunun akışlarında geliyor; portal bunu diyalog açmadan
vermiyor. `monitorler()` dikişten çağrıldığında yapılabilecek iki şey var:
boş bir `DisplayMap` uydurmak (ajan "hiç monitör yok" sanır) ya da açık
hata vermek. İkincisi seçildi; sürücü sınıfı duruyor ki sözleşme ve
gerekçe aynı yerde okunsun, kayıt bilinçli bir kararla açılsın.
"""

from __future__ import annotations

from . import portal_ekran, portal_girdi
from .portal_tasiyici import PortalHatasi, portal_musait


def portal_musait_mi() -> bool:
    """ScreenCast/RemoteDesktop portalı + bir masaüstü ucu var mı.

    Onay diyaloğu açmaz; yalnızca bus'ta isim sorar. Dikişin `musait`
    geri çağrısı bu.
    """
    return portal_musait()


def _tasiyici_kur():
    """Gerçek taşıyıcıyı kurar. `dbus_next` yoksa `PortalHatasi`."""
    from .portal_tasiyici import DbusNextTasiyici

    return DbusNextTasiyici()


class GirdiSurucusu:
    """Dikişin "girdi" sürücüsü. Oturumu ilk gerçek çağrıda tembel açar.

    Yöntem adları port-temel'in sözleşmesiyle birebir (`input.py` yüzü);
    portal nesnesi `key_press` istiyor, bu sınıf `tus_adlari_bas/_birak`
    sunuyor — aradaki farkı bu sınıf kapatıyor.
    """

    def __init__(self, env: dict | None = None) -> None:
        self._env = env or {}
        self._oturum: portal_girdi.GirdiOturumu | None = None
        self._basili: list[int] = []

    @property
    def oturum(self) -> portal_girdi.GirdiOturumu:
        """Oturumu tembel açar. Onay diyaloğu ilk çağrıda görünür."""
        if self._oturum is None:
            self._oturum = portal_girdi.GirdiOturumu.ac(_tasiyici_kur())
        return self._oturum

    # --- dikiş sözleşmesi -------------------------------------------------

    def move_to(self, vx: int, vy: int) -> None:
        self.oturum.move_to(vx, vy)

    def cursor_position(self) -> tuple[int, int]:
        """Portal `Notify*` yolu konumu okumuyor — açık hata (portal_girdi)."""
        return self.oturum.cursor_position()

    def click(self, vx: int, vy: int, button: str = "left", count: int = 1) -> None:
        self.oturum.click(vx, vy, button=button, count=count)

    def mouse_down(self, button: str = "left") -> None:
        self.oturum.mouse_down(button)

    def mouse_up(self, button: str = "left") -> None:
        self.oturum.mouse_up(button)

    def drag(self, from_xy: tuple[int, int], to_xy: tuple[int, int]) -> None:
        self.oturum.drag(from_xy, to_xy)

    def scroll(self, direction: str, amount: int) -> None:
        self.oturum.scroll(direction, amount)

    def press(self, combo: str, repeat: int = 1) -> None:
        self.oturum.press(combo, repeat)

    def type_text(self, text: str, delay: float | None = None) -> None:
        if delay is None:
            self.oturum.type_text(text)
        else:
            self.oturum.type_text(text, delay)

    def tus_adlari_bas(self, adlar: list[str]) -> None:
        """Değiştiricileri basılı tutar; liste sırası korunur."""
        if not adlar:
            return
        keysymler = [portal_girdi.keysym_coz(ad) for ad in adlar]
        for keysym in keysymler:
            self.oturum.key_press(keysym, portal_girdi.BASILDI)
        self._basili.extend(keysymler)

    def tus_adlari_birak(self, adlar: list[str]) -> None:
        """Bırakır; dikiş aynı sırayı geçiriyor, ters çevirme burada.

        Ters sıra Windows'taki `modifiers_held` ile aynı gerekçe: son basılan
        ilk bırakılır (`ctrl+shift` basıldıysa önce shift).
        """
        for ad in reversed(adlar):
            try:
                keysym = portal_girdi.keysym_coz(ad)
            except PortalHatasi:
                continue
            self.oturum.key_press(keysym, portal_girdi.BIRAKILDI)
            if keysym in self._basili:
                self._basili.remove(keysym)

    def kapat(self) -> None:
        """Önce basılı kalan değiştiriciler bırakılır, sonra oturum kapanır.

        Bir hata yolunda ctrl basılı kalırsa kullanıcının klavyesi
        kullanılamaz hâle gelir — Windows tarafındaki gerekçenin aynısı.
        """
        if self._oturum is None:
            return
        for keysym in reversed(self._basili):
            try:
                self._oturum.key_press(keysym, portal_girdi.BIRAKILDI)
            except PortalHatasi:
                pass
        self._basili = []
        self._oturum.kapat()
        self._oturum = None


class EkranSurucusu:
    """Dikişin "görüntü" sürücüsü — bilerek düşen sürücü.

    `grab` çağrısı `YakalamaYokHatasi` yükseltiyor (PipeWire dönüşümü yok).
    Sınıf burada duruyor çünkü kaydın doğru biçimi bu ve hatanın metni tam
    olarak neyin eksik olduğunu söylüyor; bugünkü kayıtsızlık bilinçli
    (modül docstring'inde).
    """

    def __init__(self, env: dict | None = None) -> None:
        self._env = env or {}
        self._oturum: portal_ekran.EkranOturumu | None = None

    def grab(self, display=None):
        if self._oturum is None:
            self._oturum = portal_ekran.EkranOturumu.ac(_tasiyici_kur())
        return self._oturum.grab(display)

    def close(self) -> None:
        if self._oturum is not None:
            self._oturum.kapat()
            self._oturum = None


class MonitorSurucusu:
    """Dikişin "ekran" sürücüsü — envanteri veremiyor, açık hata veriyor.

    Gerekçe modül docstring'inde: Wayland'de monitör listesi onaylanmış bir
    ScreenCast oturumunda yaşıyor. Oturum açıp akışları çözmek isteyen
    çağıran, `EkranOturumu.ac(...).akinlar`'ı doğrudan kullanmalı —
    buradan sahte bir `DisplayMap` uydurmak yanlış olurdu.
    """

    def __init__(self, env: dict | None = None) -> None:
        self._env = env or {}

    def monitorler(self):
        raise PortalHatasi(
            "Monitor enumeration on Wayland is only available inside a "
            "consented screen cast session: the portal reveals stream "
            "positions and sizes to SelectSources/Start, not before. Open "
            "an EkranOturumu and build the map from its streams; returning "
            "an empty display map here would make the agent believe there "
            "are no monitors."
        )