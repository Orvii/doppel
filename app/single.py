"""Tek örnek koruması.

Uygulama iki kez açıldığında iki ajan penceresi ve iki komut çubuğu oluyor.
Bu yalnızca dağınık değil, tehlikeli: iki ajan aynı fareyi ve klavyeyi
sürüyor, birinin tıklaması diğerinin ekran görüntüsünü geçersizleştiriyor
ve Esc×3 acil durdurma yalnızca birini kesiyor.

**Kilit adlandırılmış bir mutex, yuva değil.** Önceki sürüm `QLocalServer`
ile kilitlemeye çalışıyordu ve bu Windows'ta çalışmıyor: `QLocalServer`
adlandırılmış boru kullanıyor, Windows aynı adlı borunun birden çok
örneğine izin veriyor, yani `listen()` herkese başarı dönüyor. Ölçtüm —
aynı anda başlatılan altı örnekten dördü birden "ilk örneğim" dedi.

`CreateMutexW` bunu çekirdek düzeyinde atomik yapıyor: adı ilk alan alır,
sonrakiler `ERROR_ALREADY_EXISTS` görür. Süreç çökerse çekirdek tutamacı
kendisi bırakıyor, yani ölü kilit diye bir şey kalmıyor — eski sürümün
`removeServer` ile temizlemeye çalıştığı sorun ortadan kalkıyor.

Yuva hâlâ var ama başka bir iş için: ikinci örnek sessizce kapanmıyor,
çift tıklayan kişi bir şey olmasını bekliyor. Yuvaya "uyan" yazıp var olan
pencereyi öne getiriyor ve çıkıyor.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

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


class InstanceGuard(QObject):
    """İkinci bir örnek başlatıldığında yayılır."""

    woken = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._server: QLocalServer | None = None
        self._mutex = None

    def claim(self, timeout_ms: int = 400) -> bool:
        """İlk örnek isek `True`. Değilsek var olanı uyandırıp `False`."""
        self._mutex, vardi = _create_mutex(MUTEX)
        if vardi:
            self._wake_existing(timeout_ms)
            _close_handle(self._mutex)
            self._mutex = None
            return False

        # Kilit bizde. Yuva yalnızca uyandırma kanalı; ölü bir yuva
        # kalmışsa temizlemek artık güvenli, çünkü canlı bir örnek olsaydı
        # mutex'i zaten o tutuyor olurdu.
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

    def _on_connection(self) -> None:
        connection = self._server.nextPendingConnection()
        if connection is None:
            return
        connection.disconnected.connect(connection.deleteLater)
        self.woken.emit()
