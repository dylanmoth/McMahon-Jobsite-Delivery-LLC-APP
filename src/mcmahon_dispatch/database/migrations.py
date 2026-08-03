from __future__ import annotations

from pathlib import Path
import sys

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect


class MigrationError(RuntimeError):
    pass


def project_root() -> Path:
    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root is not None:
        return Path(str(bundled_root))
    return Path(__file__).resolve().parents[3]


def alembic_config(database_url: str) -> Config:
    root = project_root()
    config_path = root / "alembic.ini"
    migrations_path = root / "migrations"
    if not config_path.is_file() or not migrations_path.is_dir():
        raise MigrationError(
            "Alembic migration resources are missing. Reinstall McMahon Dispatch before continuing."
        )
    config = Config(str(config_path))
    config.set_main_option("script_location", str(migrations_path))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def upgrade_database(database_url: str, revision: str = "head") -> None:
    try:
        command.upgrade(alembic_config(database_url), revision)
    except Exception as exc:  # Alembic exposes backend-specific exception types.
        raise MigrationError(f"Database migration failed: {exc}") from exc


def current_revision(engine: Engine) -> str | None:
    inspector = inspect(engine)
    if "alembic_version" not in inspector.get_table_names():
        return None
    with engine.connect() as connection:
        value = connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one_or_none()
        return str(value) if value is not None else None
