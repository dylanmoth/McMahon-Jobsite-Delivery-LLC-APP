from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from mcmahon_dispatch.database.models import (
    AuditEvent,
    Device,
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
)


class UserManagementRepository:
    """Persistence operations for users, roles, permissions, devices, and audit events."""

    def __init__(self, session: Session, organization_id: str) -> None:
        self.session = session
        self.organization_id = organization_id

    def users(self, query: str = "", status: str | None = None) -> list[User]:
        statement = (
            select(User)
            .where(User.organization_id == self.organization_id, User.deleted_at.is_(None))
            .options(
                selectinload(User.roles).selectinload(UserRole.role),
                selectinload(User.devices),
            )
            .order_by(func.lower(User.display_name), func.lower(User.username))
        )
        if query.strip():
            pattern = f"%{query.strip().lower()}%"
            statement = statement.where(
                or_(
                    func.lower(User.username).like(pattern),
                    func.lower(User.display_name).like(pattern),
                    func.lower(func.coalesce(User.email, "")).like(pattern),
                    func.lower(func.coalesce(User.phone, "")).like(pattern),
                )
            )
        if status:
            statement = statement.where(User.status == status)
        return list(self.session.scalars(statement).unique())

    def user(self, user_id: str) -> User | None:
        return self.session.scalar(
            select(User)
            .where(
                User.id == user_id,
                User.organization_id == self.organization_id,
                User.deleted_at.is_(None),
            )
            .options(
                selectinload(User.roles)
                .selectinload(UserRole.role)
                .selectinload(Role.permissions)
                .selectinload(RolePermission.permission),
                selectinload(User.devices),
            )
        )

    def username_exists(self, username: str, exclude_user_id: str | None = None) -> bool:
        statement = select(func.count()).select_from(User).where(
            User.organization_id == self.organization_id,
            func.lower(User.username) == username.lower(),
            User.deleted_at.is_(None),
        )
        if exclude_user_id:
            statement = statement.where(User.id != exclude_user_id)
        return bool(self.session.scalar(statement))

    def email_exists(self, email: str, exclude_user_id: str | None = None) -> bool:
        statement = select(func.count()).select_from(User).where(
            User.organization_id == self.organization_id,
            func.lower(User.email) == email.lower(),
            User.deleted_at.is_(None),
        )
        if exclude_user_id:
            statement = statement.where(User.id != exclude_user_id)
        return bool(self.session.scalar(statement))

    def roles(self, active_only: bool = False) -> list[Role]:
        statement = (
            select(Role)
            .where(Role.organization_id == self.organization_id)
            .options(
                selectinload(Role.permissions).selectinload(RolePermission.permission),
                selectinload(Role.users),
            )
            .order_by(func.lower(Role.name))
        )
        if active_only:
            statement = statement.where(Role.active.is_(True))
        return list(self.session.scalars(statement).unique())

    def role(self, role_id: str) -> Role | None:
        return self.session.scalar(
            select(Role)
            .where(Role.id == role_id, Role.organization_id == self.organization_id)
            .options(
                selectinload(Role.permissions).selectinload(RolePermission.permission),
                selectinload(Role.users),
            )
        )

    def role_by_code(self, code: str) -> Role | None:
        return self.session.scalar(
            select(Role).where(
                Role.organization_id == self.organization_id,
                Role.code == code,
            )
        )

    def permissions(self) -> list[Permission]:
        return list(
            self.session.scalars(
                select(Permission).order_by(Permission.category, func.lower(Permission.name))
            )
        )

    def set_user_roles(self, user: User, role_ids: set[str]) -> None:
        valid_ids = set(
            self.session.scalars(
                select(Role.id).where(
                    Role.organization_id == self.organization_id,
                    Role.id.in_(role_ids) if role_ids else False,
                    Role.active.is_(True),
                )
            )
        )
        existing = {link.role_id: link for link in user.roles}
        for role_id, link in list(existing.items()):
            if role_id not in valid_ids:
                self.session.delete(link)
        for role_id in valid_ids - set(existing):
            self.session.add(UserRole(user_id=user.id, role_id=role_id))

    def set_role_permissions(self, role: Role, permission_ids: set[str]) -> None:
        valid_ids = set(
            self.session.scalars(
                select(Permission.id).where(Permission.id.in_(permission_ids) if permission_ids else False)
            )
        )
        existing = {link.permission_id: link for link in role.permissions}
        for permission_id, link in list(existing.items()):
            if permission_id not in valid_ids:
                self.session.delete(link)
        for permission_id in valid_ids - set(existing):
            self.session.add(RolePermission(role_id=role.id, permission_id=permission_id))

    def active_admin_count(self, excluding_user_id: str | None = None) -> int:
        statement = (
            select(func.count(func.distinct(User.id)))
            .select_from(User)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(
                User.organization_id == self.organization_id,
                User.status == "active",
                User.deleted_at.is_(None),
                Role.code == "admin",
            )
        )
        if excluding_user_id:
            statement = statement.where(User.id != excluding_user_id)
        return int(self.session.scalar(statement) or 0)

    def audit_events(
        self,
        query: str = "",
        event_type: str | None = None,
        limit: int = 500,
    ) -> list[tuple[AuditEvent, str | None]]:
        statement = (
            select(AuditEvent, User.display_name)
            .outerjoin(User, User.id == AuditEvent.user_id)
            .where(AuditEvent.organization_id == self.organization_id)
            .order_by(AuditEvent.occurred_at.desc())
            .limit(max(1, min(limit, 2000)))
        )
        if query.strip():
            pattern = f"%{query.strip().lower()}%"
            statement = statement.where(
                or_(
                    func.lower(AuditEvent.event_type).like(pattern),
                    func.lower(func.coalesce(AuditEvent.entity_type, "")).like(pattern),
                    func.lower(func.coalesce(AuditEvent.reason, "")).like(pattern),
                    func.lower(func.coalesce(User.display_name, "")).like(pattern),
                )
            )
        if event_type:
            statement = statement.where(AuditEvent.event_type == event_type)
        return list(self.session.execute(statement).all())

    def audit_event_types(self) -> list[str]:
        return list(
            self.session.scalars(
                select(AuditEvent.event_type)
                .where(AuditEvent.organization_id == self.organization_id)
                .distinct()
                .order_by(AuditEvent.event_type)
            )
        )

    def revoke_devices(self, user_id: str) -> int:
        devices = list(
            self.session.scalars(
                select(Device).where(
                    Device.organization_id == self.organization_id,
                    Device.user_id == user_id,
                    Device.revoked_at.is_(None),
                )
            )
        )
        now = datetime.now(UTC)
        for device in devices:
            device.revoked_at = now
            device.refresh_token_hash = None
        return len(devices)
