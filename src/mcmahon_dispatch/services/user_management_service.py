from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy.orm import Session, sessionmaker

from mcmahon_dispatch.core.exceptions import AuthenticationError, ValidationError
from mcmahon_dispatch.database.models import AuditEvent, Role, User
from mcmahon_dispatch.repositories.user_management_repository import (
    UserManagementRepository,
)


@dataclass(frozen=True, slots=True)
class RoleChoice:
    id: str
    code: str
    name: str
    description: str
    active: bool
    is_system: bool
    user_count: int
    permission_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class PermissionChoice:
    id: str
    code: str
    name: str
    description: str
    category: str


@dataclass(frozen=True, slots=True)
class UserRow:
    id: str
    username: str
    display_name: str
    email: str
    phone: str
    status: str
    roles: tuple[str, ...]
    last_login_at: datetime | None
    active_devices: int
    must_change_password: bool


@dataclass(frozen=True, slots=True)
class UserDetails:
    id: str
    username: str
    display_name: str
    first_name: str
    last_name: str
    email: str
    phone: str
    status: str
    role_ids: frozenset[str]
    must_change_password: bool
    last_login_at: datetime | None


@dataclass(frozen=True, slots=True)
class AuditRow:
    occurred_at: datetime
    user_name: str
    event_type: str
    entity_type: str
    entity_id: str
    reason: str
    details: dict[str, Any]


class UserManagementService:
    """Application service for account administration and self-service profile changes."""

    REQUIRED_ADMIN_PERMISSIONS = {"users.manage", "settings.manage", "audit.read"}

    def __init__(
        self,
        factory: sessionmaker[Session],
        organization_id: str,
        actor_user_id: str,
        *,
        can_manage_users: bool,
        can_read_audit: bool,
        can_manage_settings: bool,
    ) -> None:
        self.factory = factory
        self.organization_id = organization_id
        self.actor_user_id = actor_user_id
        self.can_manage_users = can_manage_users
        self.can_read_audit = can_read_audit
        self.can_manage_settings = can_manage_settings
        self.hasher = PasswordHasher(
            time_cost=3,
            memory_cost=65536,
            parallelism=4,
            hash_len=32,
            salt_len=16,
        )

    def users(self, query: str = "", status: str | None = None) -> list[UserRow]:
        self._require_manage()
        with self.factory() as session:
            users = UserManagementRepository(session, self.organization_id).users(query, status)
            return [self._user_row(user) for user in users]

    def user(self, user_id: str) -> UserDetails:
        self._require_manage()
        with self.factory() as session:
            user = UserManagementRepository(session, self.organization_id).user(user_id)
            if user is None:
                raise ValidationError("The selected user no longer exists.")
            return self._details(user)

    def roles(self) -> list[RoleChoice]:
        self._require_manage()
        with self.factory() as session:
            roles = UserManagementRepository(session, self.organization_id).roles()
            return [self._role_choice(role) for role in roles]

    def permissions(self) -> list[PermissionChoice]:
        self._require_manage()
        with self.factory() as session:
            permissions = UserManagementRepository(session, self.organization_id).permissions()
            return [
                PermissionChoice(
                    permission.id,
                    permission.code,
                    permission.name,
                    permission.description,
                    permission.category,
                )
                for permission in permissions
            ]

    def create_user(
        self,
        *,
        username: str,
        display_name: str,
        first_name: str,
        last_name: str,
        email: str,
        phone: str,
        password: str,
        role_ids: set[str],
        must_change_password: bool,
    ) -> str:
        self._require_manage()

        username = username.strip()
        display_name = display_name.strip()
        email = email.strip().lower()

        self._validate_identity(username, display_name, email)
        self._validate_password(password)

        if not role_ids:
            raise ValidationError("Select at least one role.")

        with self.factory.begin() as session:
            repo = UserManagementRepository(session, self.organization_id)

            if repo.username_exists(username):
                raise ValidationError("That username is already in use.")

            if email and repo.email_exists(email):
                raise ValidationError("That email address is already assigned to another user.")

            user = User(
                organization_id=self.organization_id,
                username=username,
                display_name=display_name,
                first_name=first_name.strip() or None,
                last_name=last_name.strip() or None,
                email=email or None,
                phone=phone.strip() or None,
                password_hash=self.hasher.hash(password),
                password_changed_at=datetime.now(UTC),
                must_change_password=must_change_password,
                created_by_id=self.actor_user_id,
                updated_by_id=self.actor_user_id,
            )

            session.add(user)
            session.flush()

            repo.set_user_roles(user, role_ids)
            self._audit(
                session,
                "users.created",
                "user",
                user.id,
                details={"username": username},
            )
            return user.id

    def update_user(
        self,
        user_id: str,
        *,
        display_name: str,
        first_name: str,
        last_name: str,
        email: str,
        phone: str,
        status: str,
        role_ids: set[str],
        must_change_password: bool,
    ) -> None:
        self._require_manage()

        display_name = display_name.strip()
        email = email.strip().lower()

        if not display_name:
            raise ValidationError("Display name is required.")

        if email and "@" not in email:
            raise ValidationError("Enter a valid email address.")

        if status not in {"active", "disabled", "locked"}:
            raise ValidationError("Select a valid account status.")

        if not role_ids:
            raise ValidationError("Select at least one role.")

        with self.factory.begin() as session:
            repo = UserManagementRepository(session, self.organization_id)
            user = repo.user(user_id)

            if user is None:
                raise ValidationError("The selected user no longer exists.")

            if email and repo.email_exists(email, user.id):
                raise ValidationError("That email address is already assigned to another user.")

            admin_role = repo.role_by_code("admin")
            is_currently_admin = admin_role is not None and any(
                link.role_id == admin_role.id for link in user.roles
            )
            removing_admin = (
                is_currently_admin and admin_role is not None and admin_role.id not in role_ids
            )
            disabling_admin = status != "active" and is_currently_admin

            if (removing_admin or disabling_admin) and repo.active_admin_count(user.id) == 0:
                raise ValidationError("At least one active administrator must remain.")

            if user.id == self.actor_user_id and status != "active":
                raise ValidationError("You cannot disable or lock your own account.")

            user.display_name = display_name
            user.first_name = first_name.strip() or None
            user.last_name = last_name.strip() or None
            user.email = email or None
            user.phone = phone.strip() or None
            user.status = status
            user.must_change_password = must_change_password
            user.updated_by_id = self.actor_user_id

            if status == "active":
                user.locked_until = None
                user.failed_login_count = 0

            repo.set_user_roles(user, role_ids)

            self._audit(
                session,
                "users.updated",
                "user",
                user.id,
                details={"status": status, "roles": sorted(role_ids)},
            )

    def reset_password(
        self,
        user_id: str,
        password: str,
        require_change: bool = True,
    ) -> None:
        self._require_manage()
        self._validate_password(password)

        with self.factory.begin() as session:
            repo = UserManagementRepository(session, self.organization_id)
            user = repo.user(user_id)

            if user is None:
                raise ValidationError("The selected user no longer exists.")

            user.password_hash = self.hasher.hash(password)
            user.password_changed_at = datetime.now(UTC)
            user.must_change_password = require_change
            user.failed_login_count = 0
            user.locked_until = None
            user.updated_by_id = self.actor_user_id

            revoked = repo.revoke_devices(user.id)

            self._audit(
                session,
                "users.password_reset",
                "user",
                user.id,
                details={
                    "sessions_revoked": revoked,
                    "must_change": require_change,
                },
            )

    def revoke_sessions(self, user_id: str) -> int:
        self._require_manage()

        with self.factory.begin() as session:
            repo = UserManagementRepository(session, self.organization_id)
            user = repo.user(user_id)

            if user is None:
                raise ValidationError("The selected user no longer exists.")

            count = repo.revoke_devices(user.id)

            self._audit(
                session,
                "users.sessions_revoked",
                "user",
                user.id,
                details={"count": count},
            )
            return count

    def set_role_permissions(
        self,
        role_id: str,
        permission_ids: set[str],
    ) -> None:
        self._require_manage()

        with self.factory.begin() as session:
            repo = UserManagementRepository(session, self.organization_id)
            role = repo.role(role_id)

            if role is None:
                raise ValidationError("The selected role no longer exists.")

            if role.code == "admin":
                permission_by_id = {
                    permission.id: permission.code for permission in repo.permissions()
                }
                selected_codes = {
                    permission_by_id[permission_id]
                    for permission_id in permission_ids
                    if permission_id in permission_by_id
                }
                missing = self.REQUIRED_ADMIN_PERMISSIONS - selected_codes

                if missing:
                    raise ValidationError(
                        "The Admin role must retain user, settings, and audit permissions."
                    )

            repo.set_role_permissions(role, permission_ids)
            role.updated_by_id = self.actor_user_id

            self._audit(
                session,
                "roles.permissions_updated",
                "role",
                role.id,
                details={"permission_count": len(permission_ids)},
            )

    def audit_events(
        self,
        query: str = "",
        event_type: str | None = None,
        limit: int = 500,
    ) -> list[AuditRow]:
        if not self.can_read_audit:
            raise ValidationError("You do not have permission to view the audit log.")

        with self.factory() as session:
            rows = UserManagementRepository(session, self.organization_id).audit_events(
                query, event_type, limit
            )

            results: list[AuditRow] = []

            for event, display_name in rows:
                results.append(
                    AuditRow(
                        event.occurred_at,
                        display_name or "System",
                        event.event_type,
                        event.entity_type or "",
                        event.entity_id or "",
                        event.reason or "",
                        self._normalize_audit_details(event.details_json),
                    )
                )

            return results

    def audit_event_types(self) -> list[str]:
        if not self.can_read_audit:
            return []

        with self.factory() as session:
            return UserManagementRepository(session, self.organization_id).audit_event_types()

    def profile(self) -> UserDetails:
        with self.factory() as session:
            user = UserManagementRepository(session, self.organization_id).user(self.actor_user_id)

            if user is None:
                raise ValidationError("Your account no longer exists.")

            return self._details(user)

    def update_profile(
        self,
        *,
        display_name: str,
        first_name: str,
        last_name: str,
        email: str,
        phone: str,
    ) -> None:
        display_name = display_name.strip()
        email = email.strip().lower()

        if not display_name:
            raise ValidationError("Display name is required.")

        if email and "@" not in email:
            raise ValidationError("Enter a valid email address.")

        with self.factory.begin() as session:
            repo = UserManagementRepository(session, self.organization_id)
            user = repo.user(self.actor_user_id)

            if user is None:
                raise ValidationError("Your account no longer exists.")

            if email and repo.email_exists(email, user.id):
                raise ValidationError("That email address is already assigned to another user.")

            user.display_name = display_name
            user.first_name = first_name.strip() or None
            user.last_name = last_name.strip() or None
            user.email = email or None
            user.phone = phone.strip() or None
            user.updated_by_id = self.actor_user_id

            self._audit(session, "profile.updated", "user", user.id)

    def change_password(
        self,
        current_password: str,
        new_password: str,
    ) -> None:
        self._validate_password(new_password)

        with self.factory.begin() as session:
            repo = UserManagementRepository(session, self.organization_id)
            user = repo.user(self.actor_user_id)

            if user is None:
                raise ValidationError("Your account no longer exists.")

            try:
                self.hasher.verify(user.password_hash, current_password)
            except VerifyMismatchError as exc:
                raise AuthenticationError("Your current password is incorrect.") from exc

            user.password_hash = self.hasher.hash(new_password)
            user.password_changed_at = datetime.now(UTC)
            user.must_change_password = False
            user.updated_by_id = self.actor_user_id

            revoked = repo.revoke_devices(user.id)

            self._audit(
                session,
                "profile.password_changed",
                "user",
                user.id,
                details={"other_sessions_revoked": revoked},
            )

    def _require_manage(self) -> None:
        if not self.can_manage_users:
            raise ValidationError("You do not have permission to manage users.")

    @staticmethod
    def _validate_identity(
        username: str,
        display_name: str,
        email: str,
    ) -> None:
        if len(username) < 3 or len(username) > 80:
            raise ValidationError("Username must be between 3 and 80 characters.")

        if not display_name:
            raise ValidationError("Display name is required.")

        if email and "@" not in email:
            raise ValidationError("Enter a valid email address.")

    @staticmethod
    def _validate_password(password: str) -> None:
        if len(password) < 12:
            raise ValidationError("Password must contain at least 12 characters.")

        if not any(character.isupper() for character in password):
            raise ValidationError("Password must include an uppercase letter.")

        if not any(character.islower() for character in password):
            raise ValidationError("Password must include a lowercase letter.")

        if not any(character.isdigit() for character in password):
            raise ValidationError("Password must include a number.")

    def _audit(
        self,
        session: Session,
        event_type: str,
        entity_type: str,
        entity_id: str,
        *,
        reason: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        session.add(
            AuditEvent(
                organization_id=self.organization_id,
                user_id=self.actor_user_id,
                event_type=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                reason=reason,
                details_json=details or {},
            )
        )

    @staticmethod
    def _normalize_audit_details(value: Any) -> dict[str, Any]:
        if value is None:
            return {}

        if isinstance(value, dict):
            return value

        if isinstance(value, str):
            stripped = value.strip()

            if not stripped:
                return {}

            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                return {"value": value}

            if isinstance(parsed, dict):
                return parsed

            return {"value": parsed}

        if isinstance(value, (list, tuple, set)):
            return {"value": list(value)}

        return {"value": value}

    @staticmethod
    def _user_row(user: User) -> UserRow:
        roles = tuple(sorted(link.role.name for link in user.roles))
        active_devices = sum(1 for device in user.devices if device.revoked_at is None)

        return UserRow(
            user.id,
            user.username,
            user.display_name,
            user.email or "",
            user.phone or "",
            user.status,
            roles,
            user.last_login_at,
            active_devices,
            user.must_change_password,
        )

    @staticmethod
    def _details(user: User) -> UserDetails:
        return UserDetails(
            user.id,
            user.username,
            user.display_name,
            user.first_name or "",
            user.last_name or "",
            user.email or "",
            user.phone or "",
            user.status,
            frozenset(link.role_id for link in user.roles),
            user.must_change_password,
            user.last_login_at,
        )

    @staticmethod
    def _role_choice(role: Role) -> RoleChoice:
        return RoleChoice(
            role.id,
            role.code,
            role.name,
            role.description,
            role.active,
            role.is_system,
            len(role.users),
            frozenset(link.permission_id for link in role.permissions),
        )
