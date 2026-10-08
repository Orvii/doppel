"""XDG portal taşıyıcısı — D-Bus katmanının tek darboğazı ve var olma sınaması.

Masaüstü portalı konuşmasının tamamı bu arayüzden geçiyor: oturum akışları
(`portal_oturum`), ekran yakalama (`portal_ekran`) ve girdi (`portal_girdi`)
yalnızca `Tasiyici` protokolünü bilir. Tek gerçek uygulama `DbusNextTasiyici`;
testler kendi sahte taşıyıcısını enjekte eder, yani testler hiçbir koşulda
gerçek D-Bus'a dokunmaz (depo kuralı: testler işletim sistemi API'sine
dokunmuyor).

## D-Bus istemcisi kararı: dbus-next

Üç seçenek ölçütlendi:

  gdbus (alt süreç) — **fd yüzünden elendi.** ScreenCast akışı PipeWire
      dosya tanımlayıcısını D-Bus `h` (UNIX_FD) türü olarak veriyor.
      gdbus-tool kaynağında doğrulandı (`gio/gdbus-tool.c`): çağrı gerçekten
      fd listesiyle yapılıyor — `g_dbus_connection_call_with_unix_fd_list_sync`
      — ama yanıt `g_variant_print` ile **metne** çevrilip basılıyor, fd
      listesi süreç çıkarken bırakılıyor (`g_clear_object (&fd_list)`).
      Yani fd alt süreçle birlikte ölüyor, bize ulaşmıyor. İkinci sebep:
      onay akışı bir sinyal beklemek (`Request::Response`); her bekleyişi
      ayrı bir alt sürece yıkmak ya yarışa girer ya süreç başına gecikme
      demektir.
  dasbus — PyGObject istiyor (sistem `python3-gi`, C/GLib); "tek yeni saf
      Python bağımlılığı" hedefiyle çelişiyor. Elendi.
  dbus-next — saf Python, sıfır çalışma zamanı bağımlılığı (PyPI
      `requires_dist` boş), MIT. fd'leri `SCM_RIGHTS` ile `recvmsg`'den
      gerçek fd olarak alıp `Message.unix_fds`'te veriyor (0.2.3 kaynağında
      doğrulandı). Bedeli açık: son sürüm 0.2.3 (Temmuz 2021) ve PyPI'da
      "Development Status :: 3 - Alpha" — üst akış yavaş. Bu yüzden sürüm
      **çivili** (`==0.2.3`) ve `dbus_next` yalnızca bu dosyanın içinde,
      çalışma zamanında, tembel import ediliyor: testler ve Windows
      kurulumu paketi hiç görmez. Python 3.12'de import edildiği bu makinede
      sınandı (0.2.3, cp312).

Sonuç: belki bir gün gdbus fd'leri taşıyabilir; bugün taşımıyor.

## Eşzamanlılık

dbus-next asyncio tabanlı; kendi özel döngü thread'inde yaşıyor ve dışarıya
**eşzamanlı** (bloklayan, zaman aşımlı) bir yüz veriyor. Sebep: depodaki
girdi/yakalama API'lerinin tamamı eşzamanlı ve çağıran katman (port-temel
dikişi) bir olay döngüsü yönetmek zorunda kalmamalı.

## Dürüstlük sınırı

Bu yol gerçek bir Wayland masaüstünde **koşulmadı**; yalnızca sahte
taşıyıcıyla sınandı ve UNVERIFIED. Burada sınanan şey D-Bus konuşmasının
kendisi (imzalar, akış, zaman aşımları); portalın gerçekten cevap verdiği
değil.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import queue
import threading
from dataclasses import dataclass
from typing import Any, Protocol

#: Portal servisinin iyi bilinen adı ve nesne yolu.
PORTAL_ADI = "org.freedesktop.portal.Desktop"
PORTAL_YOLU = "/org/freedesktop/portal/desktop"

#: Portalın arkasındaki masaüstü uçları. Portal tek başına yetmiyor:
#: istekleri seçili masaüstüne göre bu uçlardan birine devrediyor.
ARKA_UC_ADLARI = (
    "org.freedesktop.impl.portal.desktop.gnome",
    "org.freedesktop.impl.portal.desktop.kde",
    "org.freedesktop.impl.portal.desktop.wlr",
)

#: Uygunluk sınamasının kendi D-Bus çağrıları için ölçülü bir tavan (saniye).
SINAMA_ZAMANI = 2.0


class PortalHatasi(RuntimeError):
    """Portal konuşmasının genel hatası. Mesajlar İngilizce (araca dönüyor)."""


class PortalZamanAsimi(PortalHatasi):
    """Onay beklenirken ya da çağrı sırasında süre doldu.

    Ayrı bir tür, çünkü kapı bunu **başarısızlık** saymak zorunda: "kullanıcı
    henüz cevap vermedi" asla "tamam" değil.
    """


@dataclass(frozen=True)
class SecenekDegeri:
    """`a{sv}` sözlüğündeki tek bir değer: imzası ve ham değeri.

    Akış katmanı düz Python değerleri yazamıyor çünkü D-Bus `v` alanlarında
    türü istiyor (`types` u, `multiple` b, `handle_token` s...). dbus-next'in
    `Variant`'ını akışa sızdırmak da olmaz: o zaman sahte taşıyıcılı testler
    paketi kurmak zorunda kalırdı. Aradaki bu küçük taşıyıcı türü akış
    tarafında açık tutuyor, dönüşümü gerçek taşıyıcı yapıyor.
    """

    imza: str
    deger: Any


class Tasiyici(Protocol):
    """Portal akışlarının gördüğü tek yüz. Sahtesi testlerdedir."""

    def cagir(
        self,
        hedef: str,
        yol: str,
        arayuz: str,
        uye: str,
        imza: str,
        govde: list,
        zaman_asimi: float = 10.0,
    ) -> tuple[str, list, list[int]]:
        """Yöntem çağrısı: (dönüş imzası, gövde, unix fd listesi).

        Gövde sadeleştirilmiş gelir (Variant açılmış, top-level `h` gerçek
        fd'ye çevrilmiş). Süre dolunca `PortalZamanAsimi`, D-Bus hatasında
        `PortalHatasi` yükselir.
        """
        ...

    def bekle_yanit(self, istek_yolu: str, zaman_asimi: float) -> tuple[int, dict]:
        """`Request::Response` sinyalini bekler: (kod, sonuçlar).

        Kod: 0 başarı, 1 kullanıcı vazgeçti, 2 başka şekilde bitti. Sinyal
        süre içinde gelmezse `PortalZamanAsimi` yükselir — bekleyen akış onu
        başarı saymaz.
        """
        ...

    def benzersiz_ad(self) -> str:
        """Bağlantının tekil adı (`:1.42`). İstek yolu bundan türetiliyor."""
        ...

    def adlar(self) -> list[str]:
        """Busta sahipli adlar."""
        ...

    def ad_sahipli_mi(self, ad: str) -> bool:
        """Tek bir ad sahipli mi (ucuz isim sınaması)."""
        ...

    def etkinlestirilebilir_adlar(self) -> list[str]:
        """D-Bus tarafından istek üzerine başlatılabilen servis adları."""
        ...

    def kapat(self) -> None:
        ...


def dbus_yaninda_mi() -> bool:
    """`dbus_next` import edilebiliyor mu. Yan etkisiz, hata yükseltmez."""
    try:
        import dbus_next  # noqa: F401
    except ImportError:
        return False
    return True


def varyanti_ac(deger: Any) -> Any:
    """dbus-next `Variant` sarmalını yapısal olarak açar.

    Yapısal bakılıyor (isimle değil, `signature`+`value` alanlarıyla) ki
    test, paketi kurmadan vekil bir sarmalla bu yolu sınayabilsin. Sözlük ve
    listeler özyinelemeli sadeleştirilir; `a{sv}` sonuçlarının değerleri de
    sarmal geliyor.
    """
    if hasattr(deger, "signature") and hasattr(deger, "value"):
        return varyanti_ac(deger.value)
    if isinstance(deger, dict):
        return {anahtar: varyanti_ac(kira) for anahtar, kira in deger.items()}
    if isinstance(deger, tuple):
        return tuple(varyanti_ac(ogee) for ogee in deger)
    if isinstance(deger, list):
        return [varyanti_ac(ogee) for ogee in deger]
    return deger


def portal_musait(tasiyici: Tasiyici | None = None, zaman_asimi: float = SINAMA_ZAMANI) -> bool:
    """Portal bu makinede kullanılabilir mi. port-temel dikişinin sınaması.

    İki koşul birlikte aranıyor: **xdg-desktop-portal** çalışıyor **ve** en az
    bir masaüstü ucu (gnome/kde/wlr) sahipli ya da etkinleştirilebilir. Portal
    tek başına yetmiyor — uç yoksa çağrılar ilk istekte hata verir.

    Sınır, dürüstçe: uç sahipli olması, portalın **bu masaüstü** için doğru
    ucu seçeceği anlamına gelmiyor; eşleşmeyi portal `XDG_CURRENT_DESKTOP` ve
    `*-portals.conf` üzerinden yapıyor. Sınama bu yüzden "portal altyapısı
    var" sorusunu cevaplıyor, "senin masaüstün için yapılandırılmış" sorusunu
    değil. Onay diyaloğu açmaz, hiçbir şeyi değiştirmez; yalnızca isim sorar.

    Taşıyıcı verilmezse kısa ömürlü bir gerçek taşıyıcı kurulur; dbus_next
    yoksa ya da oturum bus'ı yoksa sessizce False döner.
    """
    kurulan: Tasiyici | None = None
    try:
        if tasiyici is None:
            kurulan = DbusNextTasiyici(zaman_asimi=zaman_asimi)
            tasiyici = kurulan
        if not tasiyici.ad_sahipli_mi(PORTAL_ADI):
            return False
        bilinen = set(tasiyici.adlar()) | set(tasiyici.etkinlestirilebilir_adlar())
        return any(ad in bilinen for ad in ARKA_UC_ADLARI)
    except Exception:
        # Sınama bir kapı değil, bir soru: cevap veremiyorsa cevap "hayır".
        return False
    finally:
        if kurulan is not None:
            kurulan.kapat()


def _varyantla(deger: Any, Variant: Any) -> Any:
    """`SecenekDegeri`'ni (özyinelemeli) dbus-next `Variant`'ına çevirir."""
    if isinstance(deger, SecenekDegeri):
        return Variant(deger.imza, _varyantla(deger.deger, Variant))
    if isinstance(deger, dict):
        return {anahtar: _varyantla(kira, Variant) for anahtar, kira in deger.items()}
    if isinstance(deger, tuple):
        return tuple(_varyantla(ogee, Variant) for ogee in deger)
    if isinstance(deger, list):
        return [_varyantla(ogee, Variant) for ogee in deger]
    return deger


class DbusNextTasiyici:
    """Gerçek D-Bus taşıyıcısı. Özel bir döngü thread'inde yaşar.

    `dbus_next` tembel import ediliyor (modül üstünde değil): bu dosyanın
    testlerde ve Windows'ta paketsiz içe aktarılabilmesi gerekiyor.
    """

    def __init__(self, zaman_asimi: float = 10.0) -> None:
        try:
            from dbus_next.aio import MessageBus  # noqa: F401
        except ImportError as exc:
            raise PortalHatasi(
                "The dbus-next package is required for portal sessions; "
                "install it with: pip install dbus-next==0.2.3"
            ) from exc

        self._kilit = threading.Lock()
        self._kuyruklar: dict[str, queue.Queue] = {}
        self._benzersiz_ad = ""
        self._hazir = threading.Event()
        self._kurulum_hatasi: BaseException | None = None

        self._dongu = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._donguyu_kos, daemon=True)
        self._thread.start()
        if not self._hazir.wait(timeout=max(zaman_asimi, 5.0)):
            raise PortalZamanAsimi("Timed out while connecting to the session bus")
        if self._kurulum_hatasi is not None:
            raise PortalHatasi(
                f"Could not connect to the session bus: {self._kurulum_hatasi}"
            )

    def _donguyu_kos(self) -> None:
        """Özel döngü: bus'ı bağlar, sinyal kancasını takar, sonsuza dek döner."""
        from dbus_next.aio import MessageBus
        from dbus_next.constants import BusType

        asyncio.set_event_loop(self._dongu)

        async def baglan() -> None:
            self._bus = await MessageBus(
                bus_type=BusType.SESSION, negotiate_unix_fd=True
            ).connect()
            self._benzersiz_ad = self._bus.unique_name or ""
            self._bus.add_message_handler(self._sinyal_kancasi)

        try:
            self._dongu.run_until_complete(baglan())
        except BaseException as exc:  # bus yok, kimlik doğrulama reddi...
            self._kurulum_hatasi = exc
            self._hazir.set()
            return
        self._hazir.set()
        self._dongu.run_forever()

    def _sinyal_kancasi(self, msg: Any) -> None:
        """`Request::Response` sinyallerini istek yolu başına kuyruğa yazar.

        Sinyal, bekleyen taraf kuyruğu kurmadan da gelebilir; o yüzden kuyruk
        burada, sinyal anında kuruluyor ve bekleyen taraf var olan kuyruğu
        alıyor. Aksi hâlde hızlı cevaplanan bir onay yarışa girerdi.
        """
        from dbus_next.constants import MessageType

        if msg.message_type != MessageType.SIGNAL:
            return
        if msg.interface != "org.freedesktop.portal.Request" or msg.member != "Response":
            return
        kod = int(msg.body[0])
        sonuclar = varyanti_ac(msg.body[1]) if len(msg.body) > 1 else {}
        with self._kilit:
            kuyruk = self._kuyruklar.setdefault(msg.path, queue.Queue())
        kuyruk.put((kod, sonuclar))

    def _kos(self, bekleme: Any, isim: str, zaman_asimi: float) -> Any:
        """Döngü thread'inde bir coroutine koşturur, dıştan süre çitler."""
        gelecek = asyncio.run_coroutine_threadsafe(bekleme, self._dongu)
        try:
            return gelecek.result(timeout=zaman_asimi)
        except concurrent.futures.TimeoutError:
            gelecek.cancel()
            raise PortalZamanAsimi(
                f"The portal call {isim!r} did not answer within {zaman_asimi:g} s"
            ) from None

    def cagir(
        self,
        hedef: str,
        yol: str,
        arayuz: str,
        uye: str,
        imza: str,
        govde: list,
        zaman_asimi: float = 10.0,
    ) -> tuple[str, list, list[int]]:
        from dbus_next import Message, Variant
        from dbus_next.constants import MessageType
        from dbus_next.errors import DBusError

        mesaj = Message(
            destination=hedef,
            path=yol,
            interface=arayuz,
            member=uye,
            signature=imza,
            body=_varyantla(govde, Variant),
        )
        try:
            yanit = self._kos(self._bus.call(mesaj), uye, zaman_asimi)
        except DBusError as hata:
            raise PortalHatasi(f"{arayuz}.{uye}: {hata.type}: {hata.text}") from None
        if yanit is None:
            raise PortalHatasi(f"{arayuz}.{uye}: no reply")
        if yanit.message_type == MessageType.ERROR:
            ayrinti = yanit.body[0] if yanit.body else ""
            raise PortalHatasi(f"{arayuz}.{uye}: {yanit.error_name}: {ayrinti}")

        govde_donus = varyanti_ac(list(yanit.body))
        unix_fds = list(yanit.unix_fds or [])
        # Tek fd sonucumuz OpenPipeWireRemote'un top-level `h` imzası; D-Bus
        # `h`'yi tel üzerinde fd listesine indeks olarak taşıyor (aşağıdaki
        # arabellek gerçek fd'yi oradan çeviriyor). `a{sv}` içine gömülü `h`
        # şu an tüketilmiyor: dbus-next'in `replace_idx_with_fds` yardımcısı
        # özyinelemeli hâliyle orada; gerekirse çağrılacak yer burasıdır.
        if yanit.signature == "h" and govde_donus and unix_fds:
            indeks = govde_donus[0]
            if isinstance(indeks, int) and 0 <= indeks < len(unix_fds):
                govde_donus[0] = unix_fds[indeks]
        return yanit.signature, govde_donus, unix_fds

    def bekle_yanit(self, istek_yolu: str, zaman_asimi: float) -> tuple[int, dict]:
        with self._kilit:
            kuyruk = self._kuyruklar.setdefault(istek_yolu, queue.Queue())
        try:
            kod, sonuclar = kuyruk.get(timeout=zaman_asimi)
        except queue.Empty:
            raise PortalZamanAsimi(
                f"The portal request {istek_yolu!r} got no answer within "
                f"{zaman_asimi:g} s — the consent dialog may still be open, "
                "and an unanswered dialog is not a yes"
            ) from None
        with self._kilit:
            self._kuyruklar.pop(istek_yolu, None)
        return kod, sonuclar

    def benzersiz_ad(self) -> str:
        return self._benzersiz_ad

    def _isim_sorusu(self, uye: str, imza: str = "", govde: list | None = None):
        return self.cagir(
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            uye,
            imza,
            govde or [],
            zaman_asimi=SINAMA_ZAMANI,
        )

    def adlar(self) -> list[str]:
        _, govde, _ = self._isim_sorusu("ListNames")
        return list(govde[0]) if govde else []

    def ad_sahipli_mi(self, ad: str) -> bool:
        _, govde, _ = self._isim_sorusu("NameHasOwner", imza="s", govde=[ad])
        return bool(govde[0]) if govde else False

    def etkinlestirilebilir_adlar(self) -> list[str]:
        _, govde, _ = self._isim_sorusu("ListActivatableNames")
        return list(govde[0]) if govde else []

    def kapat(self) -> None:
        try:
            self._dongu.call_soon_threadsafe(self._dongu.stop)
        except Exception:
            pass
        self._thread.join(timeout=2.0)