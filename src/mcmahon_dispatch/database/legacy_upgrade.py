from __future__ import annotations

import json
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from mcmahon_dispatch.database.models import (
    Organization,
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
)

def parse_datetime(value):
    if value is None:
        return datetime.now(UTC)

    if isinstance(value, datetime):
        return value

    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass

        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S.%f")
        except ValueError:
            pass

        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass

    return datetime.now(UTC)



@dataclass(frozen=True, slots=True)
class LegacySnapshot:
    organizations: list[dict[str, Any]]
    permissions: list[dict[str, Any]]
    roles: list[dict[str, Any]]
    role_permissions: list[dict[str, Any]]
    users: list[dict[str, Any]]
    user_roles: list[dict[str, Any]]


def sqlite_database_path(database_url: str) -> Path | None:
    url = make_url(database_url)
    if url.drivername not in {"sqlite", "sqlite+pysqlite"} or not url.database:
        return None
    if url.database == ":memory:":
        return None
    return Path(url.database).expanduser().resolve()


def snapshot_legacy_database(path: Path) -> LegacySnapshot:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        tables = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }

        def rows(table: str) -> list[dict[str, Any]]:
            if table not in tables:
                return []
            return [dict(row) for row in connection.execute(f'SELECT * FROM "{table}"')]

        return LegacySnapshot(
            organizations=rows("organizations"),
            permissions=rows("permissions"),
            roles=rows("roles"),
            role_permissions=rows("role_permissions"),
            users=rows("users"),
            user_roles=rows("user_roles"),
        )
    finally:
        connection.close()


def archive_legacy_database(path: Path) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.stem}.pre_database_v0_2.{timestamp}{path.suffix}.bak")
    shutil.move(path, backup)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{path}{suffix}")
        if sidecar.exists():
            sidecar.unlink()
    return backup


def restore_legacy_identity(snapshot: LegacySnapshot, factory: sessionmaker[Session]) -> None:
    with factory.begin() as session:
        organization_ids: set[str] = set()
        for row in snapshot.organizations:
            organization_id = str(row["id"])
            session.add(
                Organization(
                    id=organization_id,
                    legal_name=str(row.get("legal_name") or "McMahon Jobsite Delivery LLC"),
                    display_name=str(row.get("display_name") or "McMahon Jobsite Delivery"),
                    timezone=str(row.get("timezone") or "America/New_York"),
                    currency=str(row.get("currency") or "USD"),
                    active=bool(row.get("active", 1)),
                    created_at=parse_datetime(row.get("created_at")),
                    updated_at=parse_datetime(row.get("updated_at")),
                    version=int(row.get("version") or 1),
                    created_by_id=row.get("created_by_id"),
                    updated_by_id=row.get("updated_by_id"),
                )
            )
            organization_ids.add(organization_id)

        if not organization_ids:
            return
        default_org_id = next(iter(organization_ids))

        permission_ids: set[str] = set()
        for row in snapshot.permissions:
            permission_id = str(row["id"])
            code = str(row.get("code") or "")
            if not code:
                continue
            session.add(
                Permission(
                    id=permission_id,
                    code=code,
                    name=code.replace(".", " ").replace("_", " ").title(),
                    description=str(row.get("description") or ""),
                    category=code.partition(".")[0] or "general",
                    is_system=True,
                    created_at=parse_datetime(row.get("created_at")),
                    updated_at=parse_datetime(row.get("updated_at")),
                    version=int(row.get("version") or 1),
                    created_by_id=row.get("created_by_id"),
                    updated_by_id=row.get("updated_by_id"),
                )
            )
            permission_ids.add(permission_id)

        role_ids: set[str] = set()
        for row in snapshot.roles:
            role_id = str(row["id"])
            code = str(row.get("code") or "")
            if not code:
                continue
            session.add(
                Role(
                    id=role_id,
                    organization_id=default_org_id,
                    code=code,
                    name=str(row.get("name") or code.title()),
                    description=str(row.get("description") or ""),
                    is_system=True,
                    active=True,
                    created_at=parse_datetime(row.get("created_at")),
                    updated_at=parse_datetime(row.get("updated_at")),
                    version=int(row.get("version") or 1),
                    created_by_id=row.get("created_by_id"),
                    updated_by_id=row.get("updated_by_id"),
                )
            )
            role_ids.add(role_id)

        user_ids: set[str] = set()
        for row in snapshot.users:
            organization_id = str(row.get("organization_id") or default_org_id)
            if organization_id not in organization_ids:
                organization_id = default_org_id
            user_id = str(row["id"])
            session.add(
                User(
                    id=user_id,
                    organization_id=organization_id,
                    username=str(row["username"]),
                    display_name=str(row.get("display_name") or row["username"]),
                    email=row.get("email"),
                    password_hash=str(row["password_hash"]),
                    status=str(row.get("status") or "active"),
                    failed_login_count=int(row.get("failed_login_count") or 0),
                    locked_until=row.get("locked_until"),
                    last_login_at=row.get("last_login_at"),
                    must_change_password=bool(row.get("must_change_password", 0)),
                    mfa_enabled=bool(row.get("mfa_enabled", 0)),
                    notification_preferences_json={},
                    created_at=parse_datetime(row.get("created_at")),
                    updated_at=parse_datetime(row.get("updated_at")),
                    version=int(row.get("version") or 1),
                    created_by_id=row.get("created_by_id"),
                    updated_by_id=row.get("updated_by_id"),
                )
            )
            user_ids.add(user_id)

        session.flush()

        for row in snapshot.role_permissions:
            role_id = str(row.get("role_id") or "")
            permission_id = str(row.get("permission_id") or "")
            if role_id in role_ids and permission_id in permission_ids:
                session.add(
                    RolePermission(
                        id=str(row["id"]),
                        role_id=role_id,
                        permission_id=permission_id,
                        created_at=parse_datetime(row.get("created_at")),
                        updated_at=parse_datetime(row.get("updated_at")),
                        version=int(row.get("version") or 1),
                    )
                )

        for row in snapshot.user_roles:
            user_id = str(row.get("user_id") or "")
            role_id = str(row.get("role_id") or "")
            if user_id in user_ids and role_id in role_ids:
                session.add(
                    UserRole(
                        id=str(row["id"]),
                        user_id=user_id,
                        role_id=role_id,
                        created_at=parse_datetime(row.get("created_at")),
                        updated_at=parse_datetime(row.get("updated_at")),
                        version=int(row.get("version") or 1),
                    )
                )
