from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
)

from mcmahon_dispatch.core.config import AppConfig
from mcmahon_dispatch.services.settings_service import SettingsService
from mcmahon_dispatch.services.update_service import (
    UpdateError,
    UpdateInfo,
    UpdateService,
)


class _UpdateWorker(QObject):
    checked = Signal(object)
    downloaded = Signal(object)
    progress = Signal(int, int)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        service: UpdateService,
        action: str,
        update: UpdateInfo | None = None,
    ) -> None:
        super().__init__()
        self.service = service
        self.action = action
        self.update = update

    def run(self) -> None:
        try:
            if self.action == "check":
                self.checked.emit(self.service.check())
            elif self.action == "download" and self.update is not None:
                path = self.service.download(
                    self.update,
                    lambda current, total: self.progress.emit(current, total),
                )
                self.downloaded.emit(path)
        except UpdateError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # Prevent background exceptions from terminating Qt.
            self.failed.emit(f"Unexpected updater error: {exc}")
        finally:
            self.finished.emit()


class UpdateController(QObject):
    """Coordinates background update checks and user-approved installation."""

    CHECK_INTERVAL = timedelta(hours=24)

    def __init__(
        self,
        window: QMainWindow,
        config: AppConfig,
        settings: SettingsService,
    ) -> None:
        super().__init__(window)
        self.window = window
        self.config = config
        self.settings = settings
        self.service = UpdateService(
            current_version=config.app_version,
            releases_api_url=config.update_api_url,
            cache_directory=config.paths.cache / "updates",
        )
        self._thread: QThread | None = None
        self._progress: QProgressDialog | None = None
        self._manual_check = False

    def schedule_automatic_check(self) -> None:
        if not bool(self.settings.get("updates.auto_check", True)):
            return
        if self.config.environment != "production":
            return
        last_value = str(self.settings.get("updates.last_checked_at", ""))
        if last_value:
            try:
                last = datetime.fromisoformat(last_value)
                if datetime.now(UTC) - last < self.CHECK_INTERVAL:
                    return
            except ValueError:
                pass
        QTimer.singleShot(5000, lambda: self.check(manual=False))

    def check(self, *, manual: bool = True) -> None:
        if self._thread is not None:
            if manual:
                QMessageBox.information(
                    self.window,
                    "Updates",
                    "An update operation is already running.",
                )
            return
        self._manual_check = manual
        self._start_worker(_UpdateWorker(self.service, "check"))

    def _start_worker(self, worker: _UpdateWorker) -> None:
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.checked.connect(self._checked)
        worker.downloaded.connect(self._downloaded)
        worker.progress.connect(self._download_progress)
        worker.failed.connect(self._failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._thread_finished)
        self._thread = thread
        thread.start()

    def _checked(self, update: object) -> None:
        self.settings.set("updates.last_checked_at", datetime.now(UTC).isoformat())
        if update is None:
            if self._manual_check:
                QMessageBox.information(
                    self.window,
                    "McMahon Dispatch is up to date",
                    f"You are running version {self.config.app_version}.",
                )
            return
        assert isinstance(update, UpdateInfo)
        message = (
            f"{update.release_name} is available.\n\n"
            f"Installed version: {self.config.app_version}\n"
            f"Available version: {update.version}\n\n"
            "Download the verified installer now?"
        )
        if update.notes:
            message += f"\n\nRelease notes:\n{update.notes[:1500]}"
        if (
            QMessageBox.question(
                self.window,
                "Update available",
                message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        ):
            QTimer.singleShot(0, lambda: self._download(update))

    def _download(self, update: UpdateInfo) -> None:
        if self._thread is not None:
            QTimer.singleShot(150, lambda: self._download(update))
            return
        self._progress = QProgressDialog(
            "Downloading the verified update…",
            "Hide",
            0,
            max(1, update.installer.size_bytes),
            self.window,
        )
        self._progress.setWindowTitle("McMahon Dispatch Update")
        self._progress.setAutoClose(False)
        self._progress.setAutoReset(False)
        self._progress.show()
        self._start_worker(_UpdateWorker(self.service, "download", update))

    def _download_progress(self, current: int, total: int) -> None:
        if self._progress is None:
            return
        self._progress.setMaximum(max(1, total))
        self._progress.setValue(min(current, total))

    def _downloaded(self, path: object) -> None:
        installer = Path(str(path))
        if self._progress is not None:
            self._progress.close()
            self._progress = None
        if (
            QMessageBox.question(
                self.window,
                "Update ready",
                "The update was downloaded and verified.\n\n"
                "Install it now? McMahon Dispatch will close while the installer updates the application.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            self.service.launch_installer(installer)
        except UpdateError as exc:
            QMessageBox.critical(self.window, "Update failed", str(exc))
            return
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _failed(self, message: str) -> None:
        if self._progress is not None:
            self._progress.close()
            self._progress = None
        if self._manual_check:
            QMessageBox.warning(self.window, "Unable to check for updates", message)

    def _thread_finished(self) -> None:
        self._thread = None
