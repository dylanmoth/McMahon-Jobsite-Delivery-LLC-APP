import pytest

from mcmahon_dispatch.core.exceptions import AuthenticationError
from mcmahon_dispatch.services.auth_service import AuthenticationService


def test_first_admin_and_login(database, config) -> None:
    auth = AuthenticationService(database.session_factory, config)
    created = auth.create_initial_admin("owner", "Owner", "owner@example.com", "StrongPassword123")
    assert created.can("settings.manage")
    logged_in = auth.authenticate("OWNER", "StrongPassword123")
    assert logged_in.id == created.id


def test_invalid_password_is_rejected(database, config) -> None:
    auth = AuthenticationService(database.session_factory, config)
    auth.create_initial_admin("owner", "Owner", "owner@example.com", "StrongPassword123")
    with pytest.raises(AuthenticationError):
        auth.authenticate("owner", "wrong")
