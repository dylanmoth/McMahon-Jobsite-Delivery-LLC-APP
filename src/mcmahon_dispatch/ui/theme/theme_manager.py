from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication

from mcmahon_dispatch.services.settings_service import SettingsService


class ThemeManager:
    def __init__(self, app: QApplication, settings: SettingsService) -> None:
        self.app = app
        self.settings = settings
        self.theme_dir = Path(__file__).parent

    def apply_saved_theme(self) -> None:
        self.apply(str(self.settings.get("appearance.theme", "dark")))

    def apply(self, theme: str) -> None:
        selected = theme if theme in {"dark", "light"} else "dark"
        self.app.setStyleSheet((self.theme_dir / f"{selected}.qss").read_text(encoding="utf-8"))
        self.settings.set("appearance.theme", selected)
