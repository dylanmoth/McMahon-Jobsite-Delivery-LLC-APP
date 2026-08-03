from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout


class MetricCard(QFrame):
    activated = Signal(str)

    def __init__(
        self,
        key: str,
        label: str,
        value: str = "0",
        *,
        accent: str = "orange",
        helper: str = "",
    ) -> None:
        super().__init__()
        self.key = key
        self.setObjectName("metricCard")
        self.setProperty("accent", accent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(label)

        self.accent_bar = QFrame()
        self.accent_bar.setObjectName("metricAccent")
        self.accent_bar.setProperty("accent", accent)
        self.accent_bar.setFixedWidth(4)

        self.value_label = QLabel(value)
        self.value_label.setObjectName("metricValue")
        self.label_widget = QLabel(label)
        self.label_widget.setObjectName("metricLabel")
        self.label_widget.setWordWrap(True)
        self.helper_label = QLabel(helper)
        self.helper_label.setObjectName("metricHelper")
        self.helper_label.setWordWrap(True)
        self.helper_label.setVisible(bool(helper))

        text = QVBoxLayout()
        text.setContentsMargins(14, 14, 16, 14)
        text.setSpacing(5)
        text.addWidget(self.label_widget)
        text.addWidget(self.value_label)
        text.addWidget(self.helper_label)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.accent_bar)
        layout.addLayout(text, 1)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)

    def set_helper(self, helper: str) -> None:
        self.helper_label.setText(helper)
        self.helper_label.setVisible(bool(helper))

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self.key)

    def keyPressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space}:
            self.activated.emit(self.key)
            event.accept()
            return
        super().keyPressEvent(event)
