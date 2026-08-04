from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer


class DebouncedCall(QObject):
    """Collapse repeated UI events into one callback on the Qt event loop."""

    def __init__(
        self,
        callback: Callable[[], None],
        delay_ms: int = 250,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._callback = callback
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay_ms)
        self._timer.timeout.connect(callback)

    def schedule(self) -> None:
        self._timer.start()

    def cancel(self) -> None:
        self._timer.stop()
