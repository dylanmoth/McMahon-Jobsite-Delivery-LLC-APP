from pathlib import Path

import pytest

from mcmahon_dispatch.services.update_service import UpdateError, UpdateService


def test_version_comparison() -> None:
    assert UpdateService._version_tuple("v1.3.0") == (1, 3, 0)
    assert UpdateService._version_tuple("1.2.9") < UpdateService._version_tuple("1.3.0")


def test_invalid_version_rejected() -> None:
    with pytest.raises(UpdateError):
        UpdateService._version_tuple("1.3")


def test_update_urls_require_https(tmp_path: Path) -> None:
    service = UpdateService(cache_directory=tmp_path)
    with pytest.raises(UpdateError):
        service._request("http://github.com/example")
