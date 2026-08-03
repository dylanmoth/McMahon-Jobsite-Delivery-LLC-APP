from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mcmahon_dispatch.database.models import Organization, Role, User, UserRole


class UserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def count(self) -> int:
        return int(self.session.scalar(select(func.count()).select_from(User)) or 0)

    def by_username(self, username: str) -> User | None:
        return self.session.scalar(select(User).where(func.lower(User.username) == username.lower()))

    def create_admin(self, username: str, display_name: str, email: str | None, password_hash: str) -> User:
        organization = self.session.scalar(select(Organization).limit(1))
        admin_role = self.session.scalar(select(Role).where(Role.code == "admin"))
        if organization is None or admin_role is None:
            raise RuntimeError("Foundation data has not been seeded")
        user = User(
            organization_id=organization.id,
            username=username,
            display_name=display_name,
            email=email or None,
            password_hash=password_hash,
        )
        self.session.add(user)
        self.session.flush()
        self.session.add(UserRole(user_id=user.id, role_id=admin_role.id))
        return user

    def permission_codes(self, user_id: str) -> set[str]:
        user = self.session.get(User, user_id)
        if user is None:
            return set()
        return {rp.permission.code for ur in user.roles for rp in ur.role.permissions}
