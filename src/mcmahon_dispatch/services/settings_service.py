from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from threading import RLock
from typing import Any


class SettingsService:
    """Thread-safe JSON settings with atomic persistence.

    The service avoids disk writes when values do not change. That matters because
    navigation, resize, and appearance events can fire frequently in a desktop UI.
    """

    DEFAULTS: dict[str, Any] = {
        "appearance.theme": "dark",
        "appearance.accent": "classic",
        "appearance.density": "comfortable",
        "appearance.font_scale": 100,
        "appearance.sidebar_collapsed": False,
        "appearance.start_page": "dashboard",
        "window.width": 1440,
        "window.height": 900,
        "dashboard.refresh_seconds": 60,
        "security.inactivity_lock_minutes": 15,
    }

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = RLock()
        self._values = self._read()

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._values.get(key, default)

    def snapshot(self) -> dict[str, Any]:
        """Return an isolated copy suitable for diagnostics or previews."""

        with self._lock:
            return dict(self._values)

    def set(self, key: str, value: Any) -> bool:
        """Persist one value and report whether anything changed."""

        with self._lock:
            if self._values.get(key) == value:
                return False
            self._values[key] = value
            self._write_atomic()
            return True

    def set_many(self, values: dict[str, Any]) -> bool:
        """Persist a related group of settings with a single atomic write."""

        with self._lock:
            changed = {
                key: value for key, value in values.items() if self._values.get(key) != value
            }
            if not changed:
                return False
            self._values.update(changed)
            self._write_atomic()
            return True

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return dict(self.DEFAULTS)

        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return dict(self.DEFAULTS)

        if not isinstance(loaded, dict):
            return dict(self.DEFAULTS)

        return {**self.DEFAULTS, **loaded}

    def _write_atomic(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        file_descriptor, temp_name = tempfile.mkstemp(
            prefix="settings-",
            suffix=".json",
            dir=self.path.parent,
        )
        try:
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
                json.dump(self._values, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
