from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtGui import QCloseEvent, QKeySequence, QResizeEvent, QShortcut
from PySide6.QtWidgets import (
    QApplication,
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

from mcmahon_dispatch.application.services import ServiceContainer
from mcmahon_dispatch.core.config import AppConfig
from mcmahon_dispatch.services.auth_service import AuthenticatedUser
from mcmahon_dispatch.ui.navigation import NAVIGATION, NAVIGATION_LABELS, page_key_for_route
from mcmahon_dispatch.ui.pages.customer_page import CustomerPage
from mcmahon_dispatch.ui.pages.dashboard_page import DashboardPage
from mcmahon_dispatch.ui.pages.dispatch_page import DispatchPage
from mcmahon_dispatch.ui.pages.fleet_page import FleetPage
from mcmahon_dispatch.ui.pages.invoice_page import InvoicePage
from mcmahon_dispatch.ui.pages.module_page import ModulePage
from mcmahon_dispatch.ui.pages.quote_page import QuotePage
from mcmahon_dispatch.ui.pages.reporting_page import ReportingPage
from mcmahon_dispatch.ui.pages.supplier_page import SupplierPage
from mcmahon_dispatch.ui.pages.document_page import DocumentPage
from mcmahon_dispatch.ui.pages.user_management_page import ProfilePage, UserManagementPage
from mcmahon_dispatch.ui.sidebar import Sidebar
from mcmahon_dispatch.ui.theme.theme_manager import ThemeManager

PageFactory = Callable[[], QWidget]


class MainWindow(QMainWindow):
    """Desktop shell that lazily creates feature pages as they are first opened."""

    RESPONSIVE_SIDEBAR_WIDTH = 1050

    def __init__(
        self,
        config: AppConfig,
        services: ServiceContainer,
        theme_manager: ThemeManager,
        user: AuthenticatedUser,
    ) -> None:
        super().__init__()
        self.config = config
        self.services = services
        self.settings = services.settings
        self.auth = services.auth
        self.user = user
        self.theme_manager = theme_manager

        self._inactive_seconds = 0
        self._current_route = "dashboard"
        self._sidebar_manually_toggled = False
        self._sidebar_preference = bool(self.settings.get("appearance.sidebar_collapsed", False))

        self.setWindowTitle("McMahon Dispatch")
        self.setMinimumSize(900, 620)
        self._restore_window_size()

        self.sidebar = Sidebar(user)
        self.stack = QStackedWidget()
        self.stack.setObjectName("pageStack")
        self.pages: dict[str, QWidget] = {}
        self._page_factories = self._build_page_factories()

        self.navigation_toggle = QPushButton("☰")
        self.navigation_toggle.setObjectName("navigationToggle")
        self.navigation_toggle.setToolTip("Show or hide navigation (Ctrl+B)")
        self.navigation_toggle.setAccessibleName("Show or hide navigation")
        self.navigation_toggle.setFixedSize(42, 38)
        self.navigation_toggle.clicked.connect(self._toggle_sidebar)

        self.section_title = QLabel("Home")
        self.section_title.setObjectName("sectionTitle")

        self.user_badge = QLabel(user.display_name)
        self.user_badge.setObjectName("topbarUser")
        self.user_badge.setToolTip(f"Signed in as {user.display_name}")

        self._build_shell()
        self._connect_shortcuts()
        self._configure_inactivity_lock()

        self.sidebar.route_requested.connect(self.navigate)
        self._apply_responsive_sidebar()

        start_route = str(self.settings.get("appearance.start_page", "dashboard"))
        self.navigate(start_route if self._route_available(start_route) else "dashboard")

    def navigate(self, route: str) -> None:
        """Open a route, creating its owning page only when first needed."""

        page_key = page_key_for_route(route)
        page = self._ensure_page(page_key)
        if page is None:
            return

        self.stack.setCurrentWidget(page)
        self._configure_page_view(page, route)
        self._activate_page(page)

        self._current_route = route
        self.sidebar.set_active(route)
        self.section_title.setText(NAVIGATION_LABELS.get(route, "McMahon Dispatch"))
        self.settings.set("appearance.start_page", route)

    def _build_page_factories(self) -> dict[str, PageFactory]:
        factories: dict[str, PageFactory] = {
            "dashboard": self._create_dashboard_page,
            "profile": lambda: ProfilePage(
                self.services.user_management,
                self.services.auth,
            ),
        }

        if self.user.can("quotes.read"):
            factories["quotes"] = lambda: QuotePage(self.services.quotes)
        if self.user.can("customers.read"):
            factories["customers"] = lambda: CustomerPage(self.services.customers)
        if self.user.can("dispatch.read"):
            factories["dispatch"] = lambda: DispatchPage(self.services.dispatch)
        if self.user.can("fleet.read"):
            factories["fleet"] = lambda: FleetPage(self.services.fleet)
        if self.user.can("customers.read"):
            factories["suppliers"] = lambda: SupplierPage(self.services.suppliers)
            factories["documents"] = lambda: DocumentPage(self.services.documents)
        if self.user.can("billing.read"):
            factories["invoices"] = lambda: InvoicePage(self.services.invoices)
        if self.user.can("reports.financial"):
            factories["reports"] = lambda: ReportingPage(self.services.reporting)
        if self.user.can("users.manage"):
            factories["users"] = lambda: UserManagementPage(
                self.services.user_management,
                self.settings,
                self.theme_manager,
            )

        implemented = {
            "dashboard",
            "quotes",
            "customers",
            "dispatch",
            "calendar",
            "fleet",
            "invoices",
            "reports",
            "users",
            "profile",
            "settings",
            "suppliers",
            "documents",
        }
        for item in NAVIGATION:
            if item.key not in implemented and self.user.can(item.permission):
                factories[item.key] = lambda key=item.key: ModulePage(key)

        return factories

    def _create_dashboard_page(self) -> DashboardPage:
        page = DashboardPage(
            self.services.dashboard,
            self.user,
            int(
                self.settings.get(
                    "dashboard.refresh_seconds",
                    self.config.dashboard_refresh_seconds,
                )
            ),
        )
        page.drilldown_requested.connect(self.navigate)
        page.quick_action_requested.connect(self._handle_quick_action)
        return page

    def _ensure_page(self, page_key: str) -> QWidget | None:
        existing = self.pages.get(page_key)
        if existing is not None:
            return existing

        factory = self._page_factories.get(page_key)
        if factory is None:
            return None

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            page = factory()
            page.setObjectName(page.objectName() or f"{page_key}Page")
            self.pages[page_key] = page
            self.stack.addWidget(page)
            return page
        except Exception as exc:  # UI boundary: present a safe message and keep the shell alive.
            QMessageBox.critical(
                self,
                "Unable to open page",
                f"McMahon Dispatch could not open {NAVIGATION_LABELS.get(page_key, page_key)}.\n\n{exc}",
            )
            return None
        finally:
            QApplication.restoreOverrideCursor()

    @staticmethod
    def _configure_page_view(page: QWidget, route: str) -> None:
        set_view = getattr(page, "set_view", None)
        if callable(set_view):
            set_view(route)

    @staticmethod
    def _activate_page(page: QWidget) -> None:
        on_activated = getattr(page, "on_activated", None)
        if callable(on_activated):
            on_activated()

    def _handle_quick_action(self, action: str) -> None:
        routes = {
            "new_quote": "quotes",
            "new_job": "dispatch",
            "new_customer": "customers",
            "record_payment": "invoices",
        }
        route = routes.get(action)
        if route is None:
            return

        self.navigate(route)
        page = self.pages.get(page_key_for_route(route))
        handlers = {
            "new_quote": "new_quote",
            "new_job": "new_job",
            "record_payment": "record_payment",
        }
        handler_name = handlers.get(action)
        handler = getattr(page, handler_name, None) if handler_name else None
        if callable(handler):
            handler()

    def _build_shell(self) -> None:
        top_bar = QFrame()
        top_bar.setObjectName("topNavigationBar")
        top_bar_layout = QHBoxLayout(top_bar)
        top_bar_layout.setContentsMargins(10, 7, 14, 7)
        top_bar_layout.setSpacing(10)
        top_bar_layout.addWidget(self.navigation_toggle)
        top_bar_layout.addWidget(self.section_title)
        top_bar_layout.addStretch(1)
        top_bar_layout.addWidget(self.user_badge)

        content = QWidget()
        content.setObjectName("contentArea")
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(self.sidebar)
        content_layout.addWidget(self.stack, 1)

        shell = QWidget()
        shell.setObjectName("appShell")
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        shell_layout.addWidget(top_bar)
        shell_layout.addWidget(content, 1)
        self.setCentralWidget(shell)

        status_bar = QStatusBar()
        self.setStatusBar(status_bar)
        status_bar.showMessage("Local database ready • Offline capable")

    def _connect_shortcuts(self) -> None:
        self.toggle_navigation_shortcut = QShortcut(QKeySequence("Ctrl+B"), self)
        self.toggle_navigation_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.toggle_navigation_shortcut.activated.connect(self._toggle_sidebar)

    def _configure_inactivity_lock(self) -> None:
        self._activity_timer = QTimer(self)
        self._activity_timer.setInterval(1000)
        self._activity_timer.timeout.connect(self._tick_inactivity)
        self._activity_timer.start()

        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def _toggle_sidebar(self) -> None:
        self._sidebar_manually_toggled = True
        collapsed = not self.sidebar.is_collapsed
        self._sidebar_preference = collapsed
        self.settings.set("appearance.sidebar_collapsed", collapsed)
        self.sidebar.set_collapsed(collapsed)

    def _apply_responsive_sidebar(self) -> None:
        auto_collapse = (
            self.width() < self.RESPONSIVE_SIDEBAR_WIDTH and not self._sidebar_manually_toggled
        )
        self.sidebar.set_collapsed(self._sidebar_preference or auto_collapse)

    def _route_available(self, route: str) -> bool:
        return page_key_for_route(route) in self._page_factories

    def _restore_window_size(self) -> None:
        width = max(900, int(self.settings.get("window.width", 1440)))
        height = max(620, int(self.settings.get("window.height", 900)))
        screen = QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            width = min(width, max(900, available.width()))
            height = min(height, max(620, available.height()))
        self.resize(width, height)

    def eventFilter(self, watched: object, event: QEvent) -> bool:  # type: ignore[override]
        if event.type() in {
            QEvent.Type.MouseMove,
            QEvent.Type.MouseButtonPress,
            QEvent.Type.KeyPress,
            QEvent.Type.Wheel,
            QEvent.Type.TouchBegin,
        }:
            self._inactive_seconds = 0
        return super().eventFilter(watched, event)

    def _tick_inactivity(self) -> None:
        self._inactive_seconds += 1
        limit_minutes = int(
            self.settings.get(
                "security.inactivity_lock_minutes",
                self.config.inactivity_lock_minutes,
            )
        )
        if self._inactive_seconds < limit_minutes * 60:
            return

        self._activity_timer.stop()
        QMessageBox.information(
            self,
            "Session locked",
            "McMahon Dispatch locked after inactivity. Unsaved screen state remains open.",
        )
        self.close()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._apply_responsive_sidebar()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.settings.set_many(
            {
                "window.width": self.width(),
                "window.height": self.height(),
            }
        )
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        super().closeEvent(event)
