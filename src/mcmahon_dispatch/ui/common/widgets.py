from __future__ import annotations

from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QBoxLayout, QFrame, QLabel, QVBoxLayout, QWidget


class PageHeader(QFrame):
    """Consistent, responsive title area used at the top of application pages."""

    COMPACT_WIDTH = 760

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        actions: QWidget | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("pageHeader")
        self._actions = actions

        self.title = QLabel(title)
        self.title.setObjectName("pageTitle")
        self.subtitle = QLabel(subtitle)
        self.subtitle.setObjectName("muted")
        self.subtitle.setWordWrap(True)
        self.subtitle.setVisible(bool(subtitle))

        text = QWidget()
        text_layout = QVBoxLayout(text)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(3)
        text_layout.addWidget(self.title)
        text_layout.addWidget(self.subtitle)

        self._layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(16)
        self._layout.addWidget(text, 1)
        if actions is not None:
            self._layout.addWidget(actions)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        compact = event.size().width() < self.COMPACT_WIDTH
        direction = (
            QBoxLayout.Direction.TopToBottom if compact else QBoxLayout.Direction.LeftToRight
        )
        if self._layout.direction() == direction:
            return
        self._layout.setDirection(direction)
        self._layout.setSpacing(10 if compact else 16)


class SectionCard(QFrame):
    """A styled content surface with an optional heading."""

    def __init__(
        self,
        title: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("sectionCard")
        self.content_layout = QVBoxLayout(self)
        self.content_layout.setContentsMargins(16, 16, 16, 16)
        self.content_layout.setSpacing(12)
        if title:
            label = QLabel(title)
            label.setObjectName("cardTitle")
            self.content_layout.addWidget(label)
