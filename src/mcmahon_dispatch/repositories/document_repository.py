from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from mcmahon_dispatch.database.models import Document, DocumentLink


@dataclass(frozen=True, slots=True)
class DocumentSummary:
    id: str
    title: str
    document_type: str
    file_name: str
    mime_type: str
    size_bytes: int
    status: str
    storage_key: str
    created_at: datetime
    link_count: int
    linked_records: str


class DocumentRepository:
    """Database access for stored business documents and entity links."""

    def __init__(self, session: Session, organization_id: str) -> None:
        self.session = session
        self.organization_id = organization_id

    def documents(
        self,
        query: str = "",
        document_type: str | None = None,
        status: str | None = "active",
    ) -> list[DocumentSummary]:
        statement = (
            select(Document)
            .where(
                Document.organization_id == self.organization_id,
                Document.deleted_at.is_(None),
            )
            .options(selectinload(Document.links))
            .order_by(Document.created_at.desc())
        )
        if document_type:
            statement = statement.where(Document.document_type == document_type)
        if status:
            statement = statement.where(Document.status == status)
        cleaned = query.strip()
        if cleaned:
            like = f"%{cleaned}%"
            statement = statement.where(
                or_(
                    Document.title.ilike(like),
                    Document.file_name.ilike(like),
                    Document.document_type.ilike(like),
                    Document.metadata_json.cast(str).ilike(like),
                )
            )
        results = []
        for document in self.session.scalars(statement).unique():
            links = ", ".join(
                sorted(
                    {
                        f"{link.entity_type.replace('_', ' ').title()} {link.entity_id[:8]}"
                        for link in document.links
                    }
                )
            )
            results.append(
                DocumentSummary(
                    id=document.id,
                    title=document.title,
                    document_type=document.document_type,
                    file_name=document.file_name,
                    mime_type=document.mime_type,
                    size_bytes=document.size_bytes,
                    status=document.status,
                    storage_key=document.storage_key,
                    created_at=document.created_at,
                    link_count=len(document.links),
                    linked_records=links,
                )
            )
        return results

    def document(self, document_id: str) -> Document | None:
        return self.session.scalar(
            select(Document)
            .where(
                Document.id == document_id,
                Document.organization_id == self.organization_id,
                Document.deleted_at.is_(None),
            )
            .options(selectinload(Document.links))
        )

    def types(self) -> list[str]:
        return list(
            self.session.scalars(
                select(Document.document_type)
                .where(
                    Document.organization_id == self.organization_id,
                    Document.deleted_at.is_(None),
                )
                .distinct()
                .order_by(Document.document_type)
            )
        )

    def duplicate_checksum(self, checksum: str, storage_key: str) -> bool:
        return bool(
            self.session.scalar(
                select(func.count(Document.id)).where(
                    Document.organization_id == self.organization_id,
                    Document.checksum_sha256 == checksum,
                    Document.storage_key == storage_key,
                    Document.deleted_at.is_(None),
                )
            )
            or 0
        )
