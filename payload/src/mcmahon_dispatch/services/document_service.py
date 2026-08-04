from __future__ import annotations

import hashlib
import mimetypes
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from mcmahon_dispatch.core.exceptions import ValidationError
from mcmahon_dispatch.database.base import utc_now
from mcmahon_dispatch.database.models import AuditEvent, Document, DocumentLink
from mcmahon_dispatch.repositories.document_repository import (
    DocumentRepository,
    DocumentSummary,
)


@dataclass(frozen=True, slots=True)
class DocumentUploadRequest:
    source_path: Path
    title: str
    document_type: str
    retention_class: str = "business"
    entity_type: str | None = None
    entity_id: str | None = None
    relationship_type: str = "attachment"
    notes: str = ""


@dataclass(frozen=True, slots=True)
class DocumentDetails:
    id: str
    title: str
    document_type: str
    file_name: str
    storage_path: Path
    mime_type: str
    size_bytes: int
    checksum_sha256: str
    retention_class: str
    status: str
    created_at: datetime
    metadata: dict[str, Any]
    links: tuple[tuple[str, str, str], ...]


class DocumentService:
    """Secure local document storage, metadata, linking, and lifecycle management."""

    MAX_FILE_BYTES = 250 * 1024 * 1024

    def __init__(
        self,
        factory: sessionmaker[Session],
        organization_id: str,
        actor_user_id: str,
        documents_root: Path,
        *,
        can_write: bool,
    ) -> None:
        self.factory = factory
        self.organization_id = organization_id
        self.actor_user_id = actor_user_id
        self.documents_root = documents_root / "managed"
        self.documents_root.mkdir(parents=True, exist_ok=True)
        self.can_write = can_write

    def documents(
        self,
        query: str = "",
        document_type: str | None = None,
        status: str | None = "active",
    ) -> list[DocumentSummary]:
        with self.factory() as session:
            return DocumentRepository(session, self.organization_id).documents(
                query, document_type, status
            )

    def document_types(self) -> list[str]:
        with self.factory() as session:
            return DocumentRepository(session, self.organization_id).types()

    def document(self, document_id: str) -> DocumentDetails:
        with self.factory() as session:
            document = DocumentRepository(session, self.organization_id).document(document_id)
            if document is None:
                raise ValidationError("The selected document no longer exists.")
            return self._details(document)

    def upload(self, request: DocumentUploadRequest) -> str:
        self._require_write()
        source = request.source_path.expanduser().resolve()
        if not source.is_file():
            raise ValidationError("Select a valid file.")
        size = source.stat().st_size
        if size > self.MAX_FILE_BYTES:
            raise ValidationError("Files larger than 250 MB are not supported.")
        title = request.title.strip() or source.stem
        document_type = request.document_type.strip().lower().replace(" ", "_")
        if not document_type:
            raise ValidationError("Document type is required.")

        checksum = self._checksum(source)
        destination_dir = self.documents_root / datetime.now().strftime("%Y/%m")
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / f"{uuid4().hex}_{source.name}"
        shutil.copy2(source, destination)
        relative_key = destination.relative_to(self.documents_root.parent).as_posix()
        mime_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"

        try:
            with self.factory.begin() as session:
                document = Document(
                    organization_id=self.organization_id,
                    document_type=document_type,
                    title=title,
                    file_name=source.name,
                    storage_provider="local",
                    storage_key=relative_key,
                    mime_type=mime_type,
                    size_bytes=size,
                    checksum_sha256=checksum,
                    retention_class=request.retention_class.strip() or "business",
                    status="active",
                    uploader_user_id=self.actor_user_id,
                    metadata_json={"notes": request.notes.strip()},
                    created_by_id=self.actor_user_id,
                    updated_by_id=self.actor_user_id,
                )
                session.add(document)
                session.flush()
                if request.entity_type and request.entity_id:
                    session.add(
                        DocumentLink(
                            organization_id=self.organization_id,
                            document_id=document.id,
                            entity_type=request.entity_type,
                            entity_id=request.entity_id,
                            relationship_type=request.relationship_type,
                            created_by_id=self.actor_user_id,
                            updated_by_id=self.actor_user_id,
                        )
                    )
                self._audit(
                    session,
                    "documents.uploaded",
                    document.id,
                    details={"file_name": source.name, "size_bytes": size},
                )
                return document.id
        except Exception:
            destination.unlink(missing_ok=True)
            raise

    def update_metadata(
        self,
        document_id: str,
        *,
        title: str,
        document_type: str,
        retention_class: str,
        notes: str,
    ) -> None:
        self._require_write()
        title = title.strip()
        if not title:
            raise ValidationError("Document title is required.")
        with self.factory.begin() as session:
            document = DocumentRepository(session, self.organization_id).document(document_id)
            if document is None:
                raise ValidationError("The selected document no longer exists.")
            document.title = title
            document.document_type = document_type.strip().lower().replace(" ", "_")
            document.retention_class = retention_class.strip() or "business"
            document.metadata_json = {**(document.metadata_json or {}), "notes": notes.strip()}
            document.updated_by_id = self.actor_user_id
            self._audit(session, "documents.updated", document.id)

    def add_link(
        self,
        document_id: str,
        entity_type: str,
        entity_id: str,
        relationship_type: str = "attachment",
    ) -> None:
        self._require_write()
        if not entity_type.strip() or not entity_id.strip():
            raise ValidationError("Record type and record ID are required.")
        with self.factory.begin() as session:
            document = DocumentRepository(session, self.organization_id).document(document_id)
            if document is None:
                raise ValidationError("The selected document no longer exists.")
            duplicate = any(
                link.entity_type == entity_type
                and link.entity_id == entity_id
                and link.relationship_type == relationship_type
                for link in document.links
            )
            if duplicate:
                raise ValidationError("That document link already exists.")
            session.add(
                DocumentLink(
                    organization_id=self.organization_id,
                    document_id=document.id,
                    entity_type=entity_type.strip(),
                    entity_id=entity_id.strip(),
                    relationship_type=relationship_type.strip() or "attachment",
                    created_by_id=self.actor_user_id,
                    updated_by_id=self.actor_user_id,
                )
            )
            self._audit(
                session,
                "documents.linked",
                document.id,
                details={"entity_type": entity_type, "entity_id": entity_id},
            )

    def set_status(self, document_id: str, status: str) -> None:
        self._require_write()
        if status not in {"active", "archived", "quarantined"}:
            raise ValidationError("Select a valid document status.")
        with self.factory.begin() as session:
            document = DocumentRepository(session, self.organization_id).document(document_id)
            if document is None:
                raise ValidationError("The selected document no longer exists.")
            document.status = status
            document.updated_by_id = self.actor_user_id
            self._audit(
                session,
                "documents.status_changed",
                document.id,
                details={"status": status},
            )

    def delete(self, document_id: str) -> None:
        self._require_write()
        with self.factory.begin() as session:
            document = DocumentRepository(session, self.organization_id).document(document_id)
            if document is None:
                raise ValidationError("The selected document no longer exists.")
            document.deleted_at = utc_now()
            document.status = "archived"
            document.updated_by_id = self.actor_user_id
            self._audit(session, "documents.deleted", document.id)

    def storage_path(self, storage_key: str) -> Path:
        path = (self.documents_root.parent / storage_key).resolve()
        root = self.documents_root.parent.resolve()
        if root not in path.parents and path != root:
            raise ValidationError("The document path is invalid.")
        return path

    def _details(self, document: Document) -> DocumentDetails:
        return DocumentDetails(
            id=document.id,
            title=document.title,
            document_type=document.document_type,
            file_name=document.file_name,
            storage_path=self.storage_path(document.storage_key),
            mime_type=document.mime_type,
            size_bytes=document.size_bytes,
            checksum_sha256=document.checksum_sha256,
            retention_class=document.retention_class,
            status=document.status,
            created_at=document.created_at,
            metadata=dict(document.metadata_json or {}),
            links=tuple(
                (link.entity_type, link.entity_id, link.relationship_type)
                for link in document.links
            ),
        )

    @staticmethod
    def _checksum(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _require_write(self) -> None:
        if not self.can_write:
            raise ValidationError("You do not have permission to change documents.")

    def _audit(
        self,
        session: Session,
        event_type: str,
        document_id: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        session.add(
            AuditEvent(
                organization_id=self.organization_id,
                user_id=self.actor_user_id,
                event_type=event_type,
                entity_type="document",
                entity_id=document_id,
                occurred_at=datetime.now(UTC),
                details_json=details or {},
            )
        )
