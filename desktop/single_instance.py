"""One running Prompta per user: a second launch asks the first to come forward and quits.

Both copies would otherwise write the same history database and settings. The first launch listens on a
local socket named per user; a later launch connects to it, says "show" and exits.
"""

from __future__ import annotations

import getpass

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket


def default_name() -> str:
    return f"prompta-{getpass.getuser()}"


class SingleInstance(QObject):
    activated = pyqtSignal()  # another launch asked this copy to show its window

    def __init__(self, name: str | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.name = name or default_name()
        self.server: QLocalServer | None = None

    def claim(self) -> bool:
        """True: this is the first copy (now listening). False: another copy runs and was asked to show."""
        socket = QLocalSocket()
        socket.connectToServer(self.name)
        if socket.waitForConnected(500):
            socket.write(b"show")
            socket.flush()
            socket.waitForBytesWritten(500)
            socket.disconnectFromServer()
            return False
        QLocalServer.removeServer(self.name)  # a socket file left by a copy that crashed
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._on_connection)
        return self.server.listen(self.name)

    def _on_connection(self) -> None:
        while self.server is not None and (connection := self.server.nextPendingConnection()):
            connection.disconnected.connect(connection.deleteLater)
            self.activated.emit()


def bring_forward(window) -> None:
    window.showNormal() if window.isMinimized() else window.show()
    window.raise_()
    window.activateWindow()
