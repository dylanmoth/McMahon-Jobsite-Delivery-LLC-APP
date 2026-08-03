from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from mcmahon_dispatch.core.config import AppConfig
from mcmahon_dispatch.core.logging import configure_logging, get_logger
from mcmahon_dispatch.database.engine import Database
from mcmahon_dispatch.database.seed import seed_foundation_data
from mcmahon_dispatch.services.auth_service import AuthenticationService
from mcmahon_dispatch.services.dashboard_service import DashboardService
from mcmahon_dispatch.services.dispatch_service import DispatchService
from mcmahon_dispatch.services.fleet_service import FleetService
from mcmahon_dispatch.services.invoice_service import InvoiceService
from mcmahon_dispatch.services.reporting_service import ReportingService
from mcmahon_dispatch.services.customer_service import CustomerService
from mcmahon_dispatch.services.settings_service import SettingsService
from mcmahon_dispatch.services.quote_service import QuoteService
from mcmahon_dispatch.ui.auth.first_run_dialog import FirstRunAdminDialog
from mcmahon_dispatch.ui.auth.login_dialog import LoginDialog
from mcmahon_dispatch.ui.main_window import MainWindow
from mcmahon_dispatch.ui.theme.theme_manager import ThemeManager


def run_desktop() -> int:
    config = AppConfig.load()
    config.paths.ensure()
    configure_logging(config)
    log = get_logger(__name__)
    log.info("Starting McMahon Dispatch", extra={"app_version": config.app_version})

    app = QApplication(sys.argv)
    app.setApplicationName(config.app_name)
    app.setOrganizationName(config.organization_name)
    app.setApplicationVersion(config.app_version)
    icon = QIcon(str(Path(__file__).parent / "assets" / "icons" / "mcmahon_dispatch.ico"))
    app.setWindowIcon(icon)

    database = Database(config.database_url)
    database.initialize()
    seed_foundation_data(database.session_factory)

    settings = SettingsService(config.paths.settings_file)
    ThemeManager(app, settings).apply_saved_theme()
    auth = AuthenticationService(database.session_factory, config)

    if not auth.has_any_user():
        setup = FirstRunAdminDialog(auth)
        if setup.exec() != setup.DialogCode.Accepted:
            return 0

    login = LoginDialog(auth)
    if login.exec() != login.DialogCode.Accepted or login.authenticated_user is None:
        return 0

    dashboard = DashboardService(database.session_factory)
    customers = CustomerService(database.session_factory, login.authenticated_user.organization_id, login.authenticated_user.id)
    quotes = QuoteService(
        database.session_factory,
        login.authenticated_user.organization_id,
        login.authenticated_user.id,
        config.paths.documents,
        Path(__file__).parent / "assets" / "images" / "mcmahon_dispatch_logo.png",
        can_override_price=login.authenticated_user.can("quotes.override_price"),
        can_write=login.authenticated_user.can("quotes.write"),
    )
    dispatch = DispatchService(
        database.session_factory,
        login.authenticated_user.organization_id,
        login.authenticated_user.id,
        can_manage=login.authenticated_user.can("dispatch.manage"),
        can_view_financials=login.authenticated_user.can("reports.financial"),
    )
    fleet = FleetService(
        database.session_factory,
        login.authenticated_user.organization_id,
        login.authenticated_user.id,
        can_write=login.authenticated_user.can("fleet.write"),
    )
    invoices = InvoiceService(
        database.session_factory,
        login.authenticated_user.organization_id,
        login.authenticated_user.id,
        config.paths.documents,
        Path(__file__).parent / "assets" / "images" / "mcmahon_dispatch_logo.png",
        can_write=login.authenticated_user.can("billing.write"),
    )
    reporting = ReportingService(database.session_factory, login.authenticated_user.organization_id, config.paths.documents)
    window = MainWindow(
        config,
        settings,
        auth,
        dashboard,
        customers,
        quotes,
        dispatch,
        fleet,
        invoices,
        reporting,
        login.authenticated_user,
    )
    window.show()
    return app.exec()
