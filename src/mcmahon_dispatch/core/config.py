from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import PlatformDirs


@dataclass(frozen=True, slots=True)
class AppPaths:
    root: Path
    data: Path
    logs: Path
    documents: Path
    cache: Path
    backups: Path
    settings_file: Path
    database_file: Path

    @classmethod
    def discover(cls) -> "AppPaths":
        dirs = PlatformDirs("McMahon Dispatch", "McMahon Jobsite Delivery LLC", roaming=False)
        root = Path(dirs.user_data_dir)
        return cls(
            root=root,
            data=root / "data",
            logs=Path(dirs.user_log_dir),
            documents=root / "documents",
            cache=Path(dirs.user_cache_dir),
            backups=root / "backups",
            settings_file=root / "settings.json",
            database_file=root / "data" / "mcmahon_dispatch.sqlite3",
        )

    def ensure(self) -> None:
        for path in (self.root, self.data, self.logs, self.documents, self.cache, self.backups):
            path.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True, slots=True)
class AppConfig:
    app_name: str
    app_version: str
    organization_name: str
    environment: str
    log_level: str
    database_url: str
    dashboard_refresh_seconds: int
    inactivity_lock_minutes: int
    paths: AppPaths

    @classmethod
    def load(cls) -> "AppConfig":
        paths = AppPaths.discover()
        db_url = os.getenv("MCMAHON_DATABASE_URL") or f"sqlite:///{paths.database_file.as_posix()}"
        return cls(
            app_name="McMahon Dispatch",
            app_version="1.0.0",
            organization_name="McMahon Jobsite Delivery LLC",
            environment=os.getenv("MCMAHON_ENVIRONMENT", "production").strip().lower(),
            log_level=os.getenv("MCMAHON_LOG_LEVEL", "INFO").strip().upper(),
            database_url=db_url,
            dashboard_refresh_seconds=max(15, int(os.getenv("MCMAHON_DASHBOARD_REFRESH_SECONDS", "60"))),
            inactivity_lock_minutes=max(1, int(os.getenv("MCMAHON_INACTIVITY_LOCK_MINUTES", "15"))),
            paths=paths,
        )
