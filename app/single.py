"""Tek örnek koruması.

Uygulama iki kez açıldığında iki ajan penceresi ve iki komut çubuğu oluyor.
Bu yalnızca dağınık değil, tehlikeli: iki ajan aynı fareyi ve klavyeyi
sürüyor, birinin tıklaması diğerinin ekran görüntüsünü geçersizleştiriyor
ve Esc×3 acil durdurma yalnızca birini kesiyor.

**Kilit platformun kendi çekirdek kilidi; yuva değil.** Yuva yalnızca
uyandırma kanalı (`_wake_existing`), "ilk örneğim" iddiası değil — ikisi
ayrı işler ve ayrı olmaları bilinçli.

Windows'ta önceki sürüm `QLocalServer` ile kilitlemeye çalışıyordu ve bu
**çalışmıyor**: `QLocalServer` adlandırılmış boru kullanıyor, Windows aynı
adlı borunun birden çok örneğine izin veriyor, yani `listen()` herkese
başarı dönüyor. Ölçtüm — aynı anda başlatılan altı örnekten dördü birden
"ilk örneğim" dedi. `CreateMutexW` bunu çekirdek düzeyinde atomik
yapıyor: adı ilk alan alır, sonrakiler `ERROR_ALREADY_EXISTS` görür.

Linux'ta Unix alan adlı yuva **kilitleniyor** ama bayat bir dosya
kaldığında `listen()` ile canlı/bayat ayrımı yeniden yazmayı gerektiriyor;
kilit ayrı bir dosyada `flock` ile tutuluyor. Sözleşme Windows'takiyle
birebir aynı: süreç çökerse çekirdek kilidi kendisi bırakıyor, yani ölü
kilit diye bir şey yok — eski sürümün `removeServer` ile temizlemeye
çalıştığı sorun iki platformda da ortadan kalkıyor.

Kilit dosyasının adı `SOCKET`'ten türetiliyor; testler yuvayı kendi
etiketleriyle değiştirdiğinde kilidin de izole olması bedava geliyor.
Linux'ta dosya adı kullanıcı kimliğini taşıyor: Windows'taki `Local\\`
önekinin eşi — aynı makinede başka bir hesap kendi örneğini açabilsin.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from . import isletim

if isletim.WINDOWS:
    import ctypes
    from ctypes import wintypes
else:  # Linux: `wintypes` yok; dallar da çalışmıyor
    import fcntl

    ctypes = None  # type: ignore[assignment]
    wintypes = None  # type: ignore[assignment]

#: Kullanıcıya özel: `Local\` öneki adı oturumla sınırlıyor, aynı makinede
#: başka bir hesap kendi örneğini açabilsin.
MUTEX = r"Local\doppel-tek-ornek"

#: Var olan örneği öne getirmek için kullanılan yuva.
SOCKET = "doppel-tek-ornek"

#: Var olan örneğe "kendini göster" demek için gönderilen işaret.
WAKE = b"uyan\n"

ERROR_ALREADY_EXISTS = 183


def _create_mutex(name: str):
    """Adlandırılmış mutex kurar. `(tutamac, zaten_vardi)` döndürür.

    Windows dışında ya da API çağrısı düşerse `(None, False)`: koruma
    olmadan da uygulama açılmalı, kilit bir kolaylık, önkoşul değil.
    """
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    except (AttributeError, OSError):
        return None, False
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    tutamac = kernel32.CreateMutexW(None, False, name)
    vardi = ctypes.get_last_error() == ERROR_ALREADY_EXISTS
    if not tutamac:
        return None, False
    return tutamac, vardi


def _close_handle(tutamac) -> None:
    if tutamac:
        ctypes.WinDLL("kernel32").CloseHandle(wintypes.HANDLE(tutamac))


def kilit_dosyasi() -> Path:
    """Linux'taki kilit dosyasının yolu.

    `XDG_RUNTIME_DIR` varsa o; yoksa sistemin geçici klasörü. Ad
    kullanıcı kimliğini ve yuva adını taşıyor: ikisi de izolasyon için —
    hesaplar birbirinden, testler de kendi aralarında ayrı kalsın.
    """
    taban = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    try:
        kimlik = os.getuid()
    except AttributeError:  # pragma: no cover - Windows'ta buraya gelinmiyor
        kimlik = "x"
    ad = SOCKET.replace("/", "_").replace("\\", "_")
    return Path(taban) / f"{ad}-{kimlik}.lock"


def _kilit_al():
    """Linux kilidi. `(dosya, zaten_vardi)` döndürür.

    `flock` bloklamadan deneniyor: alınamazsa başka bir örnek tutuyor.
    Dosya tanıtıcısı süreç boyunca açık kalmalı — kapatan kilit bırakır.
    """
    yol = kilit_dosyasi()
    try:
        tanitici = os.open(yol, os.O_CREAT | os.O_RDWR, 0o600)
    except OSError:
        return None, False
    try:
        fcntl.flock(tanitici, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(tanitici)
        return None, True
    return tanitici, False


def _kilit_birak(tanitici) -> None:
    if tanitici is None:
        return
    try:
        fcntl.flock(tanitici, fcntl.LOCK_UN)
    except OSError:
        pass
    os.close(tanitici)


class InstanceGuard(QObject):
    """İkinci bir örnek başlatıldığında yayılır."""

    woken = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._server: QLocalServer | None = None
        self._mutex = None
        #: Linux'ta tutulan `flock` tanıtıcısı; Windows'ta `None`.
        self._kilit = None

    def claim(self, timeout_ms: int = 400) -> bool:
        """İlk örnek isek `True`. Değilsek var olanı uyandırıp `False`."""
        if isletim.WINDOWS:
            self._mutex, vardi = _create_mutex(MUTEX)
        else:
            self._kilit, vardi = _kilit_al()
        if vardi:
            self._wake_existing(timeout_ms)
            _close_handle(self._mutex)
            self._mutex = None
            _kilit_birak(self._kilit)
            self._kilit = None
            return False

        # Kilit bizde. Yuva yalnızca uyandırma kanalı; ölü bir yuva
        # kalmışsa temizlemek artık güvenli, çünkü canlı bir örnek olsaydı
        # kilidi zaten o tutuyor olurdu. Linux'ta Unix alan adlı yuva
        # dosyası bayat da olsa `listen()` `AddressInUse` veriyor ve
        # `removeServer` bunun için var.
        QLocalServer.removeServer(SOCKET)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_connection)
        self._server.listen(SOCKET)
        return True

    def _wake_existing(self, timeout_ms: int) -> None:
        probe = QLocalSocket()
        probe.connectToServer(SOCKET)
        if probe.waitForConnected(timeout_ms):
            probe.write(WAKE)
            probe.waitForBytesWritten(timeout_ms)
            probe.disconnectFromServer()

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            QLocalServer.removeServer(SOCKET)
            self._server = None
        _close_handle(self._mutex)
        self._mutex = None
        _kilit_birak(self._kilit)
        self._kilit = None

    def _on_connection(self) -> None:
        connection = self._server.nextPendingConnection()
        if connection is None:
            return
        connection.disconnected.connect(connection.deleteLater)
        self.woken.emit()