from pathlib import Path

from mcmahon_dispatch.services.document_service import DocumentService


def test_document_storage_path_stays_inside_root(tmp_path: Path) -> None:
    service = object.__new__(DocumentService)
    service.documents_root = tmp_path / "managed"
    service.documents_root.mkdir()
    result = service.storage_path("managed/test.pdf")
    assert result == (tmp_path / "managed/test.pdf").resolve()
