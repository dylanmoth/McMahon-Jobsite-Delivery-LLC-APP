from __future__ import annotations

import hashlib
import json
import platform
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from mcmahon_dispatch.core.config import AppConfig
from mcmahon_dispatch.core.enums import UserStatus
from mcmahon_dispatch.core.exceptions import AuthenticationError, ValidationError
from mcmahon_dispatch.database.models import AuditEvent, Device, User
from mcmahon_dispatch.repositories.user_repository import UserRepository

try:
    import keyring
    from keyring.errors import KeyringError
except ImportError:  # pragma: no cover - dependency is installed in production
    keyring = None  # type: ignore[assignment]

    class KeyringError(Exception):
        pass


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    id: str
    organization_id: str
    username: str
    display_name: str
    permissions: frozenset[str]
    role_codes: tuple[str, ...] = ()

    def can(self, permission: str) -> bool:
        return permission in self.permissions


class AuthenticationService:
    MAX_FAILED_ATTEMPTS = 5
    LOCK_MINUTES = 15
    KEYRING_SERVICE = "McMahon Dispatch"
    KEYRING_ACCOUNT = "remembered-session"

    def __init__(self, factory: sessionmaker[Session], config: AppConfig) -> None:
        self.factory = factory
        self.config = config
        self.hasher = PasswordHasher(
            time_cost=3,
            memory_cost=65536,
            parallelism=4,
            hash_len=32,
            salt_len=16,
        )

    def has_any_user(self) -> bool:
        with self.factory() as session:
            return UserRepository(session).count() > 0

    def create_initial_admin(
        self,
        username: str,
        display_name: str,
        email: str,
        password: str,
    ) -> AuthenticatedUser:
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
            user = repo.create_admin(
                username,
                display_name,
                email or None,
                self.hasher.hash(password),
            )
            user.password_changed_at = datetime.now(UTC)
            session.flush()
            authenticated = self._authenticated_user(repo, user)
            self._audit(session, user, "auth.initial_admin_created")
            return authenticated

    def authenticate(
        self,
        username: str,
        password: str,
        *,
        remember_login: bool = False,
    ) -> AuthenticatedUser:
        now = datetime.now(UTC)
        remembered_payload: dict[str, str] | None = None
        with self.factory.begin() as session:
            repo = UserRepository(session)
            user = repo.by_username(username.strip())
            if user is None:
                self._audit(
                    session,
                    None,
                    "auth.login_failed",
                    {"username": username.strip(), "reason": "unknown_user"},
                )
                raise AuthenticationError("The username or password is incorrect.")
            self._ensure_login_allowed(session, user, now)
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
            authenticated = self._authenticated_user(repo, user)
            if remember_login:
                remembered_payload = self._issue_remembered_session(session, user)
            else:
                self._delete_remembered_credential()
            self._audit(
                session,
                user,
                "auth.login_succeeded",
                {"remembered": remember_login},
            )
        if remembered_payload is not None:
            self._write_remembered_credential(remembered_payload)
        return authenticated

    def resume_remembered_session(self) -> AuthenticatedUser | None:
        payload = self._read_remembered_credential()
        if payload is None:
            return None
        user_id = payload.get("user_id", "")
        device_id = payload.get("device_id", "")
        token = payload.get("token", "")
        if not user_id or not device_id or not token:
            self.forget_remembered_login()
            return None
        token_hash = self._token_hash(token)
        now = datetime.now(UTC)
        with self.factory.begin() as session:
            repo = UserRepository(session)
            user = session.get(User, user_id)
            device = session.get(Device, device_id)
            if (
                user is None
                or device is None
                or user.organization_id != device.organization_id
                or device.user_id != user.id
                or device.revoked_at is not None
                or device.refresh_token_hash != token_hash
                or device.device_fingerprint != self._device_fingerprint()
            ):
                self._delete_remembered_credential()
                return None
            try:
                self._ensure_login_allowed(session, user, now)
            except AuthenticationError:
                self._delete_remembered_credential()
                return None
            device.last_seen_at = now
            device.app_version = self.config.app_version
            user.last_login_at = now
            authenticated = self._authenticated_user(repo, user)
            self._audit(session, user, "auth.remembered_login_succeeded", {"device_id": device.id})
            return authenticated

    def remembered_username(self) -> str:
        payload = self._read_remembered_credential()
        return payload.get("username", "") if payload else ""

    def forget_remembered_login(self) -> None:
        payload = self._read_remembered_credential()
        if payload:
            device_id = payload.get("device_id")
            if device_id:
                with self.factory.begin() as session:
                    device = session.get(Device, device_id)
                    if device is not None:
                        device.revoked_at = datetime.now(UTC)
                        device.refresh_token_hash = None
        self._delete_remembered_credential()

    def remembered_login_available(self) -> bool:
        return keyring is not None

    def _issue_remembered_session(self, session: Session, user: User) -> dict[str, str]:
        fingerprint = self._device_fingerprint()
        device = session.scalar(
            select(Device).where(
                Device.organization_id == user.organization_id,
                Device.device_fingerprint == fingerprint,
            )
        )
        token = secrets.token_urlsafe(48)
        now = datetime.now(UTC)
        if device is None:
            device = Device(
                organization_id=user.organization_id,
                user_id=user.id,
                device_name=platform.node() or "Windows PC",
                device_fingerprint=fingerprint,
                platform=platform.platform(),
                app_version=self.config.app_version,
                last_seen_at=now,
            )
            session.add(device)
            session.flush()
        else:
            device.user_id = user.id
            device.device_name = platform.node() or "Windows PC"
            device.platform = platform.platform()
            device.app_version = self.config.app_version
            device.last_seen_at = now
            device.revoked_at = None
        device.refresh_token_hash = self._token_hash(token)
        return {
            "user_id": user.id,
            "device_id": device.id,
            "token": token,
            "username": user.username,
        }

    def _read_remembered_credential(self) -> dict[str, str] | None:
        if keyring is None:
            return None
        try:
            value = keyring.get_password(self.KEYRING_SERVICE, self.KEYRING_ACCOUNT)
        except KeyringError:
            return None
        if not value:
            return None
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def _write_remembered_credential(self, payload: dict[str, str]) -> None:
        if keyring is None:
            return
        try:
            keyring.set_password(
                self.KEYRING_SERVICE,
                self.KEYRING_ACCOUNT,
                json.dumps(payload, separators=(",", ":")),
            )
        except KeyringError:
            return

    def _delete_remembered_credential(self) -> None:
        if keyring is None:
            return
        try:
            keyring.delete_password(self.KEYRING_SERVICE, self.KEYRING_ACCOUNT)
        except (KeyringError, Exception):
            # Some backends raise a backend-specific "not found" exception.
            return

    def _device_fingerprint(self) -> str:
        material = "|".join(
            [
                str(uuid.getnode()),
                platform.node(),
                platform.system(),
                platform.machine(),
                self.config.organization_name,
            ]
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _authenticated_user(self, repo: UserRepository, user: User) -> AuthenticatedUser:
        permissions = repo.permission_codes(user.id)
        role_codes = tuple(sorted(link.role.code for link in user.roles))
        return AuthenticatedUser(
            user.id,
            user.organization_id,
            user.username,
            user.display_name,
            frozenset(permissions),
            role_codes,
        )

    @staticmethod
    def _ensure_login_allowed(session: Session, user: User, now: datetime) -> None:
        if user.status == UserStatus.DISABLED.value:
            AuthenticationService._audit(session, user, "auth.login_blocked", {"reason": "disabled"})
            raise AuthenticationError("This account has been disabled. Contact an administrator.")
        if user.locked_until and user.locked_until > now:
            AuthenticationService._audit(session, user, "auth.login_blocked", {"reason": "locked"})
            raise AuthenticationError(
                f"This account is temporarily locked until "
                f"{user.locked_until.astimezone().strftime('%I:%M %p')}."
            )

    @staticmethod
    def _validate_credentials(username: str, display_name: str, password: str) -> None:
        if len(username) < 3 or len(username) > 80:
            raise ValidationError("Username must be between 3 and 80 characters.")
        if not display_name:
            raise ValidationError("Display name is required.")
        if len(password) < 12:
            raise ValidationError("Password must contain at least 12 characters.")
        if (
            not any(c.isupper() for c in password)
            or not any(c.islower() for c in password)
            or not any(c.isdigit() for c in password)
        ):
            raise ValidationError(
                "Password must contain uppercase, lowercase, and numeric characters."
            )

    @staticmethod
    def _audit(
        session: Session,
        user: User | None,
        event_type: str,
        details: dict[str, object] | None = None,
    ) -> None:
        session.add(
            AuditEvent(
                organization_id=user.organization_id if user else None,
                user_id=user.id if user else None,
                event_type=event_type,
                entity_type="user" if user else None,
                entity_id=user.id if user else None,
                details_json=details or {},
            )
        )
