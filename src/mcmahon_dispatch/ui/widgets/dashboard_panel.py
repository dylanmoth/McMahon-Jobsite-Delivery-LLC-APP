from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


class ClickableFrame(QFrame):
    activated = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit()

    def keyPressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space}:
            self.activated.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class DashboardPanel(QFrame):
    def __init__(self, title: str, subtitle: str = "", action: QWidget | None = None) -> None:
        super().__init__()
        self.setObjectName("dashboardPanel")
        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(0)

        title_label = QLabel(title)
        title_label.setObjectName("panelTitle")
        header = QHBoxLayout()
        header.setContentsMargins(18, 16, 18, 10)
        header.addWidget(title_label)
        header.addStretch()
        if action is not None:
            header.addWidget(action)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(header)
        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setObjectName("panelSubtitle")
            subtitle_label.setWordWrap(True)
            subtitle_label.setContentsMargins(18, 0, 18, 12)
            layout.addWidget(subtitle_label)
        layout.addLayout(self.body, 1)
