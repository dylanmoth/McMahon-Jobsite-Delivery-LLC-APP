from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy.orm import Session, sessionmaker

from mcmahon_dispatch.core.config import AppConfig
from mcmahon_dispatch.core.enums import UserStatus
from mcmahon_dispatch.core.exceptions import AuthenticationError, ValidationError
from mcmahon_dispatch.database.models import AuditEvent, User
from mcmahon_dispatch.repositories.user_repository import UserRepository


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    id: str
    organization_id: str
    username: str
    display_name: str
    permissions: frozenset[str]

    def can(self, permission: str) -> bool:
        return permission in self.permissions


class AuthenticationService:
    MAX_FAILED_ATTEMPTS = 5
    LOCK_MINUTES = 15

    def __init__(self, factory: sessionmaker[Session], config: AppConfig) -> None:
        self.factory = factory
        self.config = config
        self.hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16)

    def has_any_user(self) -> bool:
        with self.factory() as session:
            return UserRepository(session).count() > 0

    def create_initial_admin(self, username: str, display_name: str, email: str, password: str) -> AuthenticatedUser:
        username = username.strip()
        display_name = display_name.strip()
        email = email.strip().lower()
        self._validate_credentials(username, display_name, password)
        with self.factory.begin() as session:
            repo = UserRepository(session)
            if repo.count() != 0:
                raise ValidationError("The initial administrator already exists.")
            if repo.by_username(username):
                raise ValidationError("That username is already in use.")
            user = repo.create_admin(username, display_name, email or None, self.hasher.hash(password))
            session.flush()
            permissions = repo.permission_codes(user.id)
            self._audit(session, user, "auth.initial_admin_created")
            return AuthenticatedUser(user.id, user.organization_id, user.username, user.display_name, frozenset(permissions))

    def authenticate(self, username: str, password: str) -> AuthenticatedUser:
        now = datetime.now(UTC)
        with self.factory.begin() as session:
            repo = UserRepository(session)
            user = repo.by_username(username.strip())
            if user is None:
                self._audit(session, None, "auth.login_failed", {"username": username.strip(), "reason": "unknown_user"})
                raise AuthenticationError("The username or password is incorrect.")
            if user.status == UserStatus.DISABLED.value:
                self._audit(session, user, "auth.login_blocked", {"reason": "disabled"})
                raise AuthenticationError("This account has been disabled. Contact an administrator.")
            if user.locked_until and user.locked_until > now:
                self._audit(session, user, "auth.login_blocked", {"reason": "locked"})
                raise AuthenticationError(f"This account is temporarily locked until {user.locked_until.astimezone().strftime('%I:%M %p')}.")
            try:
                self.hasher.verify(user.password_hash, password)
            except VerifyMismatchError as exc:
                user.failed_login_count += 1
                if user.failed_login_count >= self.MAX_FAILED_ATTEMPTS:
                    user.locked_until = now + timedelta(minutes=self.LOCK_MINUTES)
                    user.failed_login_count = 0
                self._audit(session, user, "auth.login_failed", {"reason": "invalid_password"})
                raise AuthenticationError("The username or password is incorrect.") from exc
            if self.hasher.check_needs_rehash(user.password_hash):
                user.password_hash = self.hasher.hash(password)
            user.failed_login_count = 0
            user.locked_until = None
            user.last_login_at = now
            permissions = repo.permission_codes(user.id)
            self._audit(session, user, "auth.login_succeeded")
            return AuthenticatedUser(user.id, user.organization_id, user.username, user.display_name, frozenset(permissions))

    @staticmethod
    def _validate_credentials(username: str, display_name: str, password: str) -> None:
        if len(username) < 3 or len(username) > 80:
            raise ValidationError("Username must be between 3 and 80 characters.")
        if not display_name:
            raise ValidationError("Display name is required.")
        if len(password) < 12:
            raise ValidationError("Password must contain at least 12 characters.")
        if not any(c.isupper() for c in password) or not any(c.islower() for c in password) or not any(c.isdigit() for c in password):
            raise ValidationError("Password must contain uppercase, lowercase, and numeric characters.")

    @staticmethod
    def _audit(session: Session, user: User | None, event_type: str, details: dict[str, str] | None = None) -> None:
        session.add(AuditEvent(
            organization_id=user.organization_id if user else None,
            user_id=user.id if user else None,
            event_type=event_type,
            entity_type="user" if user else None,
            entity_id=user.id if user else None,
            details_json=details or {},
        ))
