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


@dataclass(frozen=True, slots=True)
class AppearanceSpec:
    mode: str
    accent: str
    density: str
    font_scale: int


ACCENT_PALETTES: tuple[AccentPalette, ...] = (
    AccentPalette("classic", "McMahon Classic", "#F97316", "#FB923C", "#EA580C", "#FFEDD5"),
    AccentPalette("burnt", "Burnt Orange", "#C65D12", "#D97706", "#9A3412", "#FCE7D6"),
    AccentPalette("copper", "Copper Orange", "#B8673B", "#C97B4F", "#8A4B2A", "#F5E5DC"),
    AccentPalette("sunset", "Sunset Orange", "#F28C4B", "#F6A46B", "#D96A2B", "#FFE9DC"),
    AccentPalette("safety", "Safety Orange", "#FF6B00", "#FF8A1F", "#E85D00", "#FFE3CC"),
    AccentPalette("slate", "Slate Orange", "#D66A2C", "#E17D42", "#B6531F", "#F4E3DA"),
    AccentPalette(
        "high_contrast",
        "High Contrast Orange",
        "#FF7A00",
        "#FF9A33",
        "#E65F00",
        "#FFE0C2",
    ),
)

_ACCENTS = {palette.code: palette for palette in ACCENT_PALETTES}
_DENSITY_PADDING = {"compact": 5, "comfortable": 8, "spacious": 11}
_FONT_SCALES = {90: 9.0, 100: 10.0, 110: 11.0, 125: 12.5, 150: 15.0}


class ThemeManager(QObject):
    """Apply and preview application appearance without rebuilding open windows."""

    theme_changed = Signal(str, str)

    def __init__(self, app: QApplication, settings: SettingsService) -> None:
        super().__init__(app)
        self.app = app
        self.settings = settings
        self.theme_dir = Path(__file__).parent
        self._template_cache: dict[str, str] = {}
        self._last_spec: AppearanceSpec | None = None
        self._last_resolved_mode: str | None = None
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
        spec = self._normalize_spec(mode, accent, density, font_scale)
        resolved_mode = self._resolved_mode(spec.mode)

        if spec == self._last_spec and resolved_mode == self._last_resolved_mode:
            if persist:
                self._persist(spec)
            return

        template = self._load_template(resolved_mode)
        palette = _ACCENTS[spec.accent]
        stylesheet = self._apply_palette(template, palette)
        stylesheet += self._appearance_overrides(spec.density, spec.font_scale, palette)
        self.app.setStyleSheet(stylesheet)

        if persist:
            self._persist(spec)

        self._last_spec = spec
        self._last_resolved_mode = resolved_mode
        self.theme_changed.emit(resolved_mode, spec.accent)

    def preview(self, mode: str, accent: str, density: str, font_scale: int) -> None:
        self.apply(mode, accent, density, font_scale, persist=False)

    def clear_cache(self) -> None:
        """Force stylesheet files to be read again during development."""

        self._template_cache.clear()
        self._last_spec = None
        self._last_resolved_mode = None

    def _persist(self, spec: AppearanceSpec) -> None:
        self.settings.set_many(
            {
                "appearance.theme": spec.mode,
                "appearance.accent": spec.accent,
                "appearance.density": spec.density,
                "appearance.font_scale": spec.font_scale,
            }
        )

    def _load_template(self, resolved_mode: str) -> str:
        cached = self._template_cache.get(resolved_mode)
        if cached is not None:
            return cached

        mode_path = self.theme_dir / f"{resolved_mode}.qss"
        base_path = self.theme_dir / "base.qss"
        base = base_path.read_text(encoding="utf-8") if base_path.exists() else ""
        mode = mode_path.read_text(encoding="utf-8")
        template = f"{mode}\n\n{base}"
        self._template_cache[resolved_mode] = template
        return template

    def _connect_system_theme_signal(self) -> None:
        signal = getattr(QGuiApplication.styleHints(), "colorSchemeChanged", None)
        if signal is not None:
            signal.connect(self._system_theme_changed)

    def _system_theme_changed(self, _scheme: object) -> None:
        if str(self.settings.get("appearance.theme", "dark")) == "system":
            self._last_spec = None
            self.apply_saved_theme()

    @staticmethod
    def _normalize_spec(
        mode: str,
        accent: str,
        density: str,
        font_scale: int,
    ) -> AppearanceSpec:
        return AppearanceSpec(
            mode=mode if mode in {"dark", "light", "system"} else "dark",
            accent=accent if accent in _ACCENTS else "classic",
            density=density if density in _DENSITY_PADDING else "comfortable",
            font_scale=font_scale if font_scale in _FONT_SCALES else 100,
        )

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

/* Runtime appearance overrides */
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
        color_scheme = getattr(QGuiApplication.styleHints(), "colorScheme", lambda: None)()
        light_scheme = getattr(Qt.ColorScheme, "Light", None)
        return "light" if color_scheme == light_scheme else "dark"
