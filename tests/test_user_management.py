from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from mcmahon_dispatch.core.exceptions import AuthenticationError, ValidationError
from mcmahon_dispatch.database.models import AuditEvent, Device, Role, User
from mcmahon_dispatch.services.auth_service import AuthenticationService
from mcmahon_dispatch.services.user_management_service import UserManagementService


def _admin(database, config):
    auth = AuthenticationService(database.session_factory, config)
    admin = auth.create_initial_admin(
        "owner",
        "Dylan McMahon",
        "owner@example.com",
        "StrongPassword123",
    )
    service = UserManagementService(
        database.session_factory,
        admin.organization_id,
        admin.id,
        can_manage_users=True,
        can_read_audit=True,
        can_manage_settings=True,
    )
    return auth, admin, service


def test_create_dispatcher_hashes_password_and_assigns_role(database, config):
    _auth, _admin_user, service = _admin(database, config)
    dispatcher = next(role for role in service.roles() if role.code == "dispatcher")
    user_id = service.create_user(
        username="dispatcher1",
        display_name="Dispatcher One",
        first_name="Dispatcher",
        last_name="One",
        email="dispatcher@example.com",
        phone="772-555-0100",
        password="AnotherStrong123",
        role_ids={dispatcher.id},
        must_change_password=True,
    )
    with database.session_factory() as session:
        user = session.get(User, user_id)
        assert user is not None
        assert user.password_hash != "AnotherStrong123"
        assert user.must_change_password is True
        assert {link.role.code for link in user.roles} == {"dispatcher"}


def test_cannot_disable_last_active_admin(database, config):
    _auth, admin, service = _admin(database, config)
    details = service.user(admin.id)
    with pytest.raises(ValidationError, match="active administrator"):
        service.update_user(
            admin.id,
            display_name=details.display_name,
            first_name=details.first_name,
            last_name=details.last_name,
            email=details.email,
            phone=details.phone,
            status="disabled",
            role_ids=set(details.role_ids),
            must_change_password=False,
        )


def test_password_change_verifies_current_password(database, config):
    _auth, _admin_user, service = _admin(database, config)
    with pytest.raises(AuthenticationError):
        service.change_password("WrongPassword123", "ReplacementPassword123")
    service.change_password("StrongPassword123", "ReplacementPassword123")
    auth = AuthenticationService(database.session_factory, config)
    assert auth.authenticate("owner", "ReplacementPassword123").username == "owner"


def test_reset_password_revokes_devices_and_audits(database, config):
    _auth, admin, service = _admin(database, config)
    with database.session_factory.begin() as session:
        session.add(
            Device(
                organization_id=admin.organization_id,
                user_id=admin.id,
                device_name="Office PC",
                device_fingerprint="fingerprint",
                platform="Windows",
                app_version="0.9.0",
                refresh_token_hash="hash",
            )
        )
    service.reset_password(admin.id, "ReplacementPassword123", True)
    with database.session_factory() as session:
        device = session.scalar(select(Device).where(Device.user_id == admin.id))
        assert device is not None and device.revoked_at is not None
        event = session.scalar(
            select(AuditEvent).where(AuditEvent.event_type == "users.password_reset")
        )
        assert event is not None
        assert event.details_json["sessions_revoked"] == 1


def test_role_permission_changes_are_persisted(database, config):
    _auth, _admin_user, service = _admin(database, config)
    driver = next(role for role in service.roles() if role.code == "driver")
    permissions = service.permissions()
    selected = {p.id for p in permissions if p.code in {"dashboard.view", "dispatch.read"}}
    service.set_role_permissions(driver.id, selected)
    refreshed = next(role for role in service.roles() if role.code == "driver")
    assert refreshed.permission_ids == frozenset(selected)


def test_audit_log_returns_user_management_events(database, config):
    _auth, admin, service = _admin(database, config)
    service.update_profile(
        display_name="Dylan M.",
        first_name="Dylan",
        last_name="McMahon",
        email="owner@example.com",
        phone="772-555-0101",
    )
    rows = service.audit_events(event_type="profile.updated")
    assert rows
    assert rows[0].user_name == "Dylan M."
