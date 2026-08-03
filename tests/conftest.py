from pathlib import Path

import pytest

from mcmahon_dispatch.core.config import AppConfig, AppPaths
from mcmahon_dispatch.database.engine import Database
from mcmahon_dispatch.database.seed import seed_foundation_data


@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    paths = AppPaths(tmp_path, tmp_path / "data", tmp_path / "logs", tmp_path / "documents", tmp_path / "cache", tmp_path / "backups", tmp_path / "settings.json", tmp_path / "data" / "test.sqlite3")
    paths.ensure()
    return AppConfig("McMahon Dispatch", "0.1.0", "McMahon Jobsite Delivery LLC", "development", "DEBUG", f"sqlite:///{paths.database_file.as_posix()}", 60, 15, paths)


@pytest.fixture
def database(config: AppConfig) -> Database:
    db = Database(config.database_url); db.initialize(); seed_foundation_data(db.session_factory); return db
