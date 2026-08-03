from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from mcmahon_dispatch.services.settings_service import SettingsService


@dataclass(frozen=True, slots=True)
class AccentPalette:
    code: str
    label: str
    primary: str
    hover: str
    pressed: str
    soft: str


ACCENT_PALETTES: tuple[AccentPalette, ...] = (
    AccentPalette("classic", "McMahon Classic", "#F97316", "#FB923C", "#EA580C", "#FFEDD5"),
    AccentPalette("burnt", "Burnt Orange", "#C65D12", "#D97706", "#9A3412", "#FCE7D6"),
    AccentPalette("copper", "Copper Orange", "#B8673B", "#C97B4F", "#8A4B2A", "#F5E5DC"),
    AccentPalette("sunset", "Sunset Orange", "#F28C4B", "#F6A46B", "#D96A2B", "#FFE9DC"),
    AccentPalette("safety", "Safety Orange", "#FF6B00", "#FF8A1F", "#E85D00", "#FFE3CC"),
    AccentPalette("slate", "Slate Orange", "#D66A2C", "#E17D42", "#B6531F", "#F4E3DA"),
    AccentPalette("high_contrast", "High Contrast Orange", "#FF7A00", "#FF9A33", "#E65F00", "#FFE0C2"),
)

_ACCENTS = {palette.code: palette for palette in ACCENT_PALETTES}
_DENSITY_PADDING = {"compact": 5, "comfortable": 8, "spacious": 11}
_FONT_SCALES = {90: 9.0, 100: 10.0, 110: 11.0, 125: 12.5, 150: 15.0}


class ThemeManager(QObject):
    """Applies application-wide appearance settings without rebuilding open windows."""

    theme_changed = Signal(str, str)

    def __init__(self, app: QApplication, settings: SettingsService) -> None:
        super().__init__(app)
        self.app = app
        self.settings = settings
        self.theme_dir = Path(__file__).parent
        self._system_signal_connected = False
        self._connect_system_theme_signal()

    @property
    def accent_options(self) -> tuple[AccentPalette, ...]:
        return ACCENT_PALETTES

    def apply_saved_theme(self) -> None:
        self.apply(
            mode=str(self.settings.get("appearance.theme", "dark")),
            accent=str(self.settings.get("appearance.accent", "classic")),
            density=str(self.settings.get("appearance.density", "comfortable")),
            font_scale=int(self.settings.get("appearance.font_scale", 100)),
            persist=False,
        )

    def apply(
        self,
        mode: str,
        accent: str = "classic",
        density: str = "comfortable",
        font_scale: int = 100,
        *,
        persist: bool = False,
    ) -> None:
        selected_mode = mode if mode in {"dark", "light", "system"} else "dark"
        selected_accent = accent if accent in _ACCENTS else "classic"
        selected_density = density if density in _DENSITY_PADDING else "comfortable"
        selected_scale = font_scale if font_scale in _FONT_SCALES else 100
        resolved_mode = self._resolved_mode(selected_mode)

        template = (self.theme_dir / f"{resolved_mode}.qss").read_text(encoding="utf-8")
        palette = _ACCENTS[selected_accent]
        stylesheet = self._apply_palette(template, palette)
        stylesheet += self._appearance_overrides(selected_density, selected_scale, palette)
        self.app.setStyleSheet(stylesheet)

        if persist:
            self.settings.set_many(
                {
                    "appearance.theme": selected_mode,
                    "appearance.accent": selected_accent,
                    "appearance.density": selected_density,
                    "appearance.font_scale": selected_scale,
                }
            )

        self.theme_changed.emit(resolved_mode, selected_accent)

    def preview(self, mode: str, accent: str, density: str, font_scale: int) -> None:
        self.apply(mode, accent, density, font_scale, persist=False)

    def _connect_system_theme_signal(self) -> None:
        style_hints = QGuiApplication.styleHints()
        signal = getattr(style_hints, "colorSchemeChanged", None)
        if signal is not None:
            signal.connect(self._system_theme_changed)
            self._system_signal_connected = True

    def _system_theme_changed(self, _scheme: object) -> None:
        if str(self.settings.get("appearance.theme", "dark")) == "system":
            self.apply_saved_theme()

    @staticmethod
    def _apply_palette(template: str, palette: AccentPalette) -> str:
        replacements = {
            "#F97316": palette.primary,
            "#f97316": palette.primary,
            "#FB923C": palette.hover,
            "#fb923c": palette.hover,
            "#EA580C": palette.pressed,
            "#ea580c": palette.pressed,
            "#FFEDD5": palette.soft,
            "#ffedd5": palette.soft,
        }
        result = template
        for source, target in replacements.items():
            result = result.replace(source, target)
        return result

    @staticmethod
    def _appearance_overrides(
        density: str,
        font_scale: int,
        palette: AccentPalette,
    ) -> str:
        padding = _DENSITY_PADDING[density]
        font_size = _FONT_SCALES[font_scale]
        row_padding = max(3, padding - 1)
        return f"""

/* Runtime appearance overrides v1.1 */
QWidget {{ font-size: {font_size:g}pt; }}
QPushButton, QToolButton {{ padding: {padding}px {padding + 4}px; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QDateTimeEdit {{
    padding: {padding}px;
}}
QHeaderView::section {{ padding: {row_padding + 1}px; }}
QTableWidget::item, QTableView::item {{ padding: {row_padding}px; }}
QAbstractItemView::item:selected {{ border-left: 3px solid {palette.primary}; }}
QWidget:focus {{ outline: none; }}
"""

    @staticmethod
    def _resolved_mode(mode: str) -> str:
        if mode != "system":
            return mode
        style_hints = QGuiApplication.styleHints()
        color_scheme = getattr(style_hints, "colorScheme", lambda: None)()
        light_scheme = getattr(Qt.ColorScheme, "Light", None)
        return "light" if color_scheme == light_scheme else "dark"
