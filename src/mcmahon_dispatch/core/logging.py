from __future__ import annotations

import json
import logging
import logging.handlers
from datetime import UTC, datetime
from typing import Any

from mcmahon_dispatch.core.config import AppConfig

_RESERVED = set(logging.makeLogRecord({}).__dict__)
_SENSITIVE = {"password", "password_hash", "token", "secret", "authorization", "refresh_token"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and key.lower() not in _SENSITIVE:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(config: AppConfig) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(config.log_level)
    formatter = JsonFormatter()

    file_handler = logging.handlers.RotatingFileHandler(
        config.paths.logs / "mcmahon_dispatch.log",
        maxBytes=5_000_000,
        backupCount=10,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    if config.environment == "development":
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        root.addHandler(console)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
