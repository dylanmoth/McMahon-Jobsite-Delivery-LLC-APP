from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from threading import RLock
from typing import Any


class SettingsService:
    DEFAULTS: dict[str, Any] = {
        "appearance.theme": "dark",
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

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return dict(self.DEFAULTS)
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            return {**self.DEFAULTS, **loaded} if isinstance(loaded, dict) else dict(self.DEFAULTS)
        except (OSError, json.JSONDecodeError):
            return dict(self.DEFAULTS)

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._values.get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._values[key] = value
            self._write_atomic()

    def _write_atomic(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix="settings-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self._values, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
