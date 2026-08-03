from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QWidget

from mcmahon_dispatch.services.auth_service import AuthenticatedUser


@dataclass(frozen=True, slots=True)
class NavigationItem:
    key: str
    label: str
    permission: str


NAVIGATION = (
    NavigationItem("dashboard", "Home", "dashboard.view"),
    NavigationItem("quotes", "Quotes", "quotes.read"),
    NavigationItem("dispatch", "Dispatch", "dispatch.read"),
    NavigationItem("calendar", "Calendar", "dispatch.read"),
    NavigationItem("customers", "Customers", "customers.read"),
    NavigationItem("suppliers", "Suppliers", "customers.read"),
    NavigationItem("fleet", "Fleet Management", "fleet.read"),
    NavigationItem("invoices", "Invoices", "billing.read"),
    NavigationItem("reports", "Reports", "reports.financial"),
    NavigationItem("users", "Users & Access", "users.manage"),
    NavigationItem("profile", "My Profile", "dashboard.view"),
    NavigationItem("documents", "Documents", "customers.read"),
    NavigationItem("settings", "Settings", "settings.manage"),
)


class Sidebar(QFrame):
    route_requested = Signal(str)

    def __init__(self, user: AuthenticatedUser) -> None:
        super().__init__()
        self.setObjectName("sidebar")
        self.setMinimumWidth(220); self.setMaximumWidth(260)
        self._buttons: dict[str, QPushButton] = {}
        self._collapsed = False
        brand = QLabel("McMahon\nDispatch"); brand.setObjectName("brandTitle")
        layout = QVBoxLayout(self); layout.setContentsMargins(12, 18, 12, 12); layout.addWidget(brand); layout.addSpacing(16)
        for item in NAVIGATION:
            if user.can(item.permission):
                button = QPushButton(item.label); button.setObjectName("navButton"); button.setProperty("active", False); button.clicked.connect(lambda _checked=False, key=item.key: self.route_requested.emit(key))
                self._buttons[item.key] = button; layout.addWidget(button)
        layout.addStretch()
        self.user_label = QLabel(user.display_name); self.user_label.setObjectName("muted"); layout.addWidget(self.user_label)

    @property
    def is_collapsed(self) -> bool:
        return self._collapsed

    def set_active(self, key: str) -> None:
        for route, button in self._buttons.items():
            button.setProperty("active", route == key); button.style().unpolish(button); button.style().polish(button)

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        self.setFixedWidth(78 if collapsed else 240)
        for item in NAVIGATION:
            button = self._buttons.get(item.key)
            if button:
                button.setText(item.label[:1] if collapsed else item.label); button.setToolTip(item.label if collapsed else "")
        self.user_label.setVisible(not collapsed)
