from __future__ import annotations

from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from mcmahon_dispatch.core.config import AppConfig
from mcmahon_dispatch.services.auth_service import AuthenticatedUser, AuthenticationService
from mcmahon_dispatch.services.dashboard_service import DashboardService
from mcmahon_dispatch.services.dispatch_service import DispatchService
from mcmahon_dispatch.services.fleet_service import FleetService
from mcmahon_dispatch.services.invoice_service import InvoiceService
from mcmahon_dispatch.services.customer_service import CustomerService
from mcmahon_dispatch.services.settings_service import SettingsService
from mcmahon_dispatch.services.quote_service import QuoteService
from mcmahon_dispatch.ui.pages.dashboard_page import DashboardPage
from mcmahon_dispatch.ui.pages.dispatch_page import DispatchPage
from mcmahon_dispatch.ui.pages.fleet_page import FleetPage
from mcmahon_dispatch.ui.pages.invoice_page import InvoicePage
from mcmahon_dispatch.ui.pages.customer_page import CustomerPage
from mcmahon_dispatch.ui.pages.module_page import ModulePage
from mcmahon_dispatch.ui.pages.quote_page import QuotePage
from mcmahon_dispatch.ui.sidebar import NAVIGATION, Sidebar


class MainWindow(QMainWindow):
    def __init__(
        self,
        config: AppConfig,
        settings: SettingsService,
        auth: AuthenticationService,
        dashboard: DashboardService,
        customers: CustomerService,
        quotes: QuoteService,
        dispatch: DispatchService,
        fleet: FleetService,
        invoices: InvoiceService,
        user: AuthenticatedUser,
    ) -> None:
        super().__init__()
        self.config=config; self.settings=settings; self.auth=auth; self.user=user
        self.setWindowTitle("McMahon Dispatch")
        self.resize(int(settings.get("window.width", 1440)), int(settings.get("window.height", 900)))
        self.sidebar = Sidebar(user)
        self.stack = QStackedWidget()
        dashboard_page = DashboardPage(
            dashboard,
            user,
            int(settings.get("dashboard.refresh_seconds", config.dashboard_refresh_seconds)),
        )
        dashboard_page.drilldown_requested.connect(self.navigate)
        dashboard_page.quick_action_requested.connect(self._handle_quick_action)
        self.pages: dict[str, QWidget] = {"dashboard": dashboard_page}
        if user.can("quotes.read"):
            self.pages["quotes"] = QuotePage(quotes)
        if user.can("customers.read"):
            self.pages["customers"] = CustomerPage(customers)
        if user.can("dispatch.read"):
            self.pages["dispatch"] = DispatchPage(dispatch)
        if user.can("fleet.read"):
            self.pages["fleet"] = FleetPage(fleet)
        if user.can("billing.read"):
            self.pages["invoices"] = InvoicePage(invoices)
        for item in NAVIGATION:
            if item.key not in {"dashboard", "quotes", "customers", "dispatch", "calendar", "fleet", "invoices"} and user.can(item.permission):
                self.pages[item.key] = ModulePage(item.key)
        for page in self.pages.values():
            self.stack.addWidget(page)
        self.sidebar.route_requested.connect(self.navigate)

        self.navigation_toggle = QPushButton("☰")
        self.navigation_toggle.setObjectName("navigationToggle")
        self.navigation_toggle.setToolTip("Show or hide navigation (Ctrl+B)")
        self.navigation_toggle.setAccessibleName("Show or hide navigation")
        self.navigation_toggle.setFixedSize(42, 38)
        self.navigation_toggle.clicked.connect(self._toggle_sidebar)

        self.section_title = QLabel("Home")
        self.section_title.setObjectName("sectionTitle")

        top_bar = QFrame()
        top_bar.setObjectName("topNavigationBar")
        top_bar_layout = QHBoxLayout(top_bar)
        top_bar_layout.setContentsMargins(10, 7, 14, 7)
        top_bar_layout.setSpacing(10)
        top_bar_layout.addWidget(self.navigation_toggle)
        top_bar_layout.addWidget(self.section_title)
        top_bar_layout.addStretch()

        content = QWidget()
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(self.sidebar)
        content_layout.addWidget(self.stack, 1)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        body_layout.addWidget(top_bar)
        body_layout.addWidget(content, 1)
        self.setCentralWidget(body)

        self.toggle_navigation_shortcut = QShortcut(QKeySequence("Ctrl+B"), self)
        self.toggle_navigation_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.toggle_navigation_shortcut.activated.connect(self._toggle_sidebar)

        status = QStatusBar()
        self.setStatusBar(status)
        status.showMessage("Local database ready • Offline-capable foundation")
        self.sidebar.set_collapsed(bool(settings.get("appearance.sidebar_collapsed", False)))
        self._inactive_seconds = 0
        self._activity_timer = QTimer(self); self._activity_timer.timeout.connect(self._tick_inactivity); self._activity_timer.start(1000)
        self.installEventFilter(self)
        start = str(settings.get("appearance.start_page", "dashboard"))
        valid_start = start in self.pages or start == "calendar"
        self.navigate(start if valid_start else "dashboard")

    def navigate(self, key: str) -> None:
        page_key = "dispatch" if key == "calendar" else key
        page = self.pages.get(page_key)
        if page is None:
            return
        self.stack.setCurrentWidget(page)
        if isinstance(page, DispatchPage):
            page.set_view(key)
        activation_handler = getattr(page, "on_activated", None)
        if callable(activation_handler):
            activation_handler()
        self.sidebar.set_active(key)
        labels = {item.key: item.label for item in NAVIGATION}
        self.section_title.setText(labels.get(key, "McMahon Dispatch"))
        self.settings.set("appearance.start_page", key)


    def _handle_quick_action(self, action: str) -> None:
        route_by_action = {
            "new_quote": "quotes",
            "new_job": "dispatch",
            "new_customer": "customers",
            "record_payment": "invoices",
        }
        route = route_by_action.get(action)
        if route is not None:
            self.navigate(route)
            if action == "new_quote":
                page = self.pages.get("quotes")
                if isinstance(page, QuotePage):
                    page.new_quote()
            elif action == "new_job":
                page = self.pages.get("dispatch")
                if isinstance(page, DispatchPage):
                    page.new_job()
            elif action == "record_payment":
                page = self.pages.get("invoices")
                if isinstance(page, InvoicePage):
                    page.record_payment()

    def _toggle_sidebar(self) -> None:
        collapsed = not self.sidebar.is_collapsed
        self.settings.set("appearance.sidebar_collapsed", collapsed)
        self.sidebar.set_collapsed(collapsed)

    def eventFilter(self, watched, event):  # type: ignore[no-untyped-def]
        if event.type() in {QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress, QEvent.Type.Wheel}:
            self._inactive_seconds = 0
        return super().eventFilter(watched, event)

    def _tick_inactivity(self) -> None:
        self._inactive_seconds += 1
        limit = int(self.settings.get("security.inactivity_lock_minutes", self.config.inactivity_lock_minutes)) * 60
        if self._inactive_seconds >= limit:
            self._activity_timer.stop(); QMessageBox.information(self, "Session locked", "McMahon Dispatch locked after inactivity. Unsaved screen state remains open."); self.close()

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        self.sidebar.set_collapsed(self.width() < 1100 or bool(self.settings.get("appearance.sidebar_collapsed", False)))

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self.settings.set("window.width", self.width()); self.settings.set("window.height", self.height()); super().closeEvent(event)
