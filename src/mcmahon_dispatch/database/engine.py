from __future__ import annotations

from sqlalchemy import Engine, create_engine, event, inspect
from sqlalchemy.orm import Session, sessionmaker

from mcmahon_dispatch.database import models  # noqa: F401
from mcmahon_dispatch.database.legacy_upgrade import (
    archive_legacy_database,
    restore_legacy_identity,
    snapshot_legacy_database,
    sqlite_database_path,
)
from mcmahon_dispatch.database.migrations import upgrade_database


class Database:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        connect_args = (
            {"check_same_thread": False, "timeout": 30}
            if database_url.startswith("sqlite")
            else {}
        )
        self.engine: Engine = create_engine(
            database_url,
            future=True,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
        if database_url.startswith("sqlite"):
            event.listen(self.engine, "connect", self._configure_sqlite)
        self.session_factory = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
            class_=Session,
        )

    @staticmethod
    def _configure_sqlite(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    def initialize(self) -> None:
        table_names = set(inspect(self.engine).get_table_names())
        database_path = sqlite_database_path(self.database_url)
        if table_names and "alembic_version" not in table_names and database_path is not None:
            snapshot = snapshot_legacy_database(database_path)
            self.engine.dispose()
            archive_legacy_database(database_path)
            upgrade_database(self.database_url)
            restore_legacy_identity(snapshot, self.session_factory)
            return
        upgrade_database(self.database_url)

    def dispose(self) -> None:
        self.engine.dispose()
