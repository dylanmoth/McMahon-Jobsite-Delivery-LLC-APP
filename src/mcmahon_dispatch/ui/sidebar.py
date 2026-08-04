from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

from mcmahon_dispatch.services.auth_service import AuthenticatedUser
from mcmahon_dispatch.ui.navigation import NAVIGATION, NavigationItem

__all__ = ["NAVIGATION", "NavigationItem", "Sidebar"]


class Sidebar(QFrame):
    """Permission-aware primary navigation with a compact display mode."""

    route_requested = Signal(str)

    EXPANDED_WIDTH = 240
    COLLAPSED_WIDTH = 78

    def __init__(self, user: AuthenticatedUser) -> None:
        super().__init__()
        self.setObjectName("sidebar")
        self.setMinimumWidth(self.COLLAPSED_WIDTH)
        self.setMaximumWidth(260)

        self._buttons: dict[str, QPushButton] = {}
        self._items = {item.key: item for item in NAVIGATION}
        self._collapsed = False
        self._active_route: str | None = None

        self.brand = QLabel("McMahon\nDispatch")
        self.brand.setObjectName("brandTitle")
        self.brand.setAccessibleName("McMahon Dispatch")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 18, 12, 12)
        layout.setSpacing(4)
        layout.addWidget(self.brand)
        layout.addSpacing(14)

        for item in NAVIGATION:
            if not user.can(item.permission):
                continue
            button = self._create_button(item)
            self._buttons[item.key] = button
            layout.addWidget(button)

        layout.addStretch(1)
        self.user_label = QLabel(user.display_name)
        self.user_label.setObjectName("sidebarUser")
        self.user_label.setToolTip(user.display_name)
        layout.addWidget(self.user_label)

    @property
    def is_collapsed(self) -> bool:
        return self._collapsed

    def set_active(self, key: str) -> None:
        if key == self._active_route:
            return
        self._active_route = key
        for route, button in self._buttons.items():
            active = route == key
            if bool(button.property("active")) == active:
                continue
            button.setProperty("active", active)
            button.style().unpolish(button)
            button.style().polish(button)

    def set_collapsed(self, collapsed: bool) -> None:
        if collapsed == self._collapsed and self.width() in {
            self.COLLAPSED_WIDTH,
            self.EXPANDED_WIDTH,
        }:
            return

        self._collapsed = collapsed
        self.setFixedWidth(self.COLLAPSED_WIDTH if collapsed else self.EXPANDED_WIDTH)
        self.brand.setText("MD" if collapsed else "McMahon\nDispatch")
        self.brand.setAlignment(
            Qt.AlignmentFlag.AlignLeft if not collapsed else Qt.AlignmentFlag.AlignHCenter
        )

        for key, button in self._buttons.items():
            item = self._items[key]
            button.setText(item.compact_label if collapsed else item.label)
            button.setToolTip(item.label if collapsed else "")
            button.setAccessibleName(item.label)

        self.user_label.setVisible(not collapsed)

    def _create_button(self, item: NavigationItem) -> QPushButton:
        button = QPushButton(item.label)
        button.setObjectName("navButton")
        button.setProperty("active", False)
        button.setCheckable(False)
        button.setAccessibleName(item.label)
        button.clicked.connect(
            lambda _checked=False, route=item.key: self.route_requested.emit(route)
        )
        return button
