from __future__ import annotations

from pathlib import Path

from mcmahon_dispatch.services.settings_service import SettingsService
from mcmahon_dispatch.ui.theme.theme_manager import ACCENT_PALETTES, ThemeManager


def test_accent_palette_codes_are_unique() -> None:
    codes = [palette.code for palette in ACCENT_PALETTES]
    assert len(codes) == len(set(codes))
    assert "classic" in codes
    assert "safety" in codes


def test_palette_replaces_brand_tokens() -> None:
    palette = next(item for item in ACCENT_PALETTES if item.code == "copper")
    result = ThemeManager._apply_palette(
        "#F97316 #FB923C #EA580C #FFEDD5",
        palette,
    )
    assert palette.primary in result
    assert palette.hover in result
    assert palette.pressed in result
    assert palette.soft in result


def test_settings_set_many_is_atomic_from_caller_perspective(tmp_path: Path) -> None:
    service = SettingsService(tmp_path / "settings.json")
    service.set_many(
        {
            "appearance.theme": "light",
            "appearance.accent": "burnt",
            "appearance.font_scale": 110,
        }
    )
    reloaded = SettingsService(tmp_path / "settings.json")
    assert reloaded.get("appearance.theme") == "light"
    assert reloaded.get("appearance.accent") == "burnt"
    assert reloaded.get("appearance.font_scale") == 110
