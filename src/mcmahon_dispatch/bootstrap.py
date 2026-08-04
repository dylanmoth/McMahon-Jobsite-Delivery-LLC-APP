from __future__ import annotations

import sys
from pathlib import Path
from types import TracebackType

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from mcmahon_dispatch.application.services import build_services
from mcmahon_dispatch.core.config import AppConfig
from mcmahon_dispatch.core.logging import configure_logging, get_logger
from mcmahon_dispatch.database.engine import Database
from mcmahon_dispatch.database.seed import seed_foundation_data
from mcmahon_dispatch.services.auth_service import AuthenticatedUser, AuthenticationService
from mcmahon_dispatch.services.settings_service import SettingsService
from mcmahon_dispatch.ui.auth.first_run_dialog import FirstRunAdminDialog
from mcmahon_dispatch.ui.auth.login_dialog import LoginDialog
from mcmahon_dispatch.ui.main_window import MainWindow
from mcmahon_dispatch.ui.theme.theme_manager import ThemeManager


def run_desktop() -> int:
    """Compose infrastructure, authenticate the user, and start the Qt event loop."""

    config = AppConfig.load()
    config.paths.ensure()
    configure_logging(config)
    log = get_logger(__name__)
    log.info("Starting McMahon Dispatch", extra={"app_version": config.app_version})

    app = _create_application(config)
    _install_exception_handler(app)

    database = Database(config.database_url)
    database.initialize()
    seed_foundation_data(database.session_factory)

    settings = SettingsService(config.paths.settings_file)
    theme_manager = ThemeManager(app, settings)
    theme_manager.apply_saved_theme()

    auth = AuthenticationService(database.session_factory, config)
    user = _authenticate(auth)
    if user is None:
        return 0

    services = build_services(
        database.session_factory,
        config,
        settings,
        auth,
        user,
    )
    window = MainWindow(config, services, theme_manager, user)
    window.show()
    return app.exec()


def _create_application(config: AppConfig) -> QApplication:
    app = QApplication(sys.argv)
    app.setApplicationName(config.app_name)
    app.setOrganizationName(config.organization_name)
    app.setApplicationVersion(config.app_version)
    app.setStyle("Fusion")

    icon_path = Path(__file__).parent / "assets" / "icons" / "mcmahon_dispatch.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    return app


def _authenticate(auth: AuthenticationService) -> AuthenticatedUser | None:
    if not auth.has_any_user():
        setup = FirstRunAdminDialog(auth)
        if setup.exec() != setup.DialogCode.Accepted:
            return None

    remembered_user = auth.resume_remembered_session()
    if remembered_user is not None:
        return remembered_user

    login = LoginDialog(auth)
    if login.exec() != login.DialogCode.Accepted:
        return None
    return login.authenticated_user


def _install_exception_handler(app: QApplication) -> None:
    log = get_logger("mcmahon_dispatch.unhandled")

    def handle_exception(
        exception_type: type[BaseException],
        exception: BaseException,
        traceback: TracebackType | None,
    ) -> None:
        if issubclass(exception_type, KeyboardInterrupt):
            sys.__excepthook__(exception_type, exception, traceback)
            return

        log.exception(
            "Unhandled application error",
            exc_info=(exception_type, exception, traceback),
        )
        QMessageBox.critical(
            app.activeWindow(),
            "McMahon Dispatch encountered a problem",
            "The action could not be completed. Your saved data remains intact.\n\n"
            f"Technical details: {exception}",
        )

    sys.excepthook = handle_exception
