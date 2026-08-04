from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from mcmahon_dispatch.database.models import (
    Customer,
    Document,
    DocumentLink,
    NumberSequence,
    PricingVersion,
    QuickCallNote,
    Quote,
    QuoteCharge,
    QuoteIntake,
    QuoteLoad,
    QuoteRevision,
    QuoteStop,
)


@dataclass(frozen=True, slots=True)
class CustomerChoice:
    id: str
    company_name: str
    customer_number: str
    primary_phone: str
    primary_email: str
    delay_level: int


@dataclass(frozen=True, slots=True)
class QuoteSummary:
    id: str
    quote_number: str
    customer_name: str
    status: str
    total_cents: int
    confidence: str
    updated_at: datetime


class QuoteRepository:
    def __init__(self, session: Session, organization_id: str) -> None:
        self.session = session
        self.organization_id = organization_id

    def customer_choices(self) -> list[CustomerChoice]:
        rows = self.session.execute(
            select(
                Customer.id,
                Customer.company_name,
                Customer.customer_number,
                Customer.primary_phone,
                Customer.primary_email,
                Customer.delay_level,
            )
            .where(
                Customer.organization_id == self.organization_id,
                Customer.deleted_at.is_(None),
                Customer.status.not_in(("archived", "do_not_serve")),
            )
            .order_by(Customer.company_name.asc())
        ).all()
        return [
            CustomerChoice(
                id=str(row.id),
                company_name=str(row.company_name),
                customer_number=str(row.customer_number),
                primary_phone=str(row.primary_phone or ""),
                primary_email=str(row.primary_email or ""),
                delay_level=int(row.delay_level or 0),
            )
            for row in rows
        ]

    def list_quotes(self, query: str = "", limit: int = 250) -> list[QuoteSummary]:
        stmt = (
            select(Quote, Customer.company_name)
            .outerjoin(Customer, Customer.id == Quote.customer_id)
            .where(
                Quote.organization_id == self.organization_id,
                Quote.deleted_at.is_(None),
            )
            .order_by(Quote.updated_at.desc())
            .limit(limit)
        )
        normalized = query.strip()
        if normalized:
            like = f"%{normalized}%"
            stmt = stmt.where(
                (Quote.quote_number.ilike(like)) | (Customer.company_name.ilike(like))
            )
        return [
            QuoteSummary(
                id=quote.id,
                quote_number=quote.quote_number,
                customer_name=company_name or "Unassigned customer",
                status=quote.status,
                total_cents=quote.total_cents,
                confidence=quote.confidence,
                updated_at=quote.updated_at,
            )
            for quote, company_name in self.session.execute(stmt).all()
        ]

    def get(self, quote_id: str) -> Quote | None:
        return self.session.scalar(
            select(Quote)
            .where(
                Quote.id == quote_id,
                Quote.organization_id == self.organization_id,
                Quote.deleted_at.is_(None),
            )
            .options(
                selectinload(Quote.customer),
                selectinload(Quote.intake),
                selectinload(Quote.revisions).selectinload(QuoteRevision.charges),
                selectinload(Quote.revisions).selectinload(QuoteRevision.stops),
                selectinload(Quote.revisions).selectinload(QuoteRevision.loads),
            )
        )

    def customer(self, customer_id: str | None) -> Customer | None:
        if not customer_id:
            return None
        return self.session.scalar(
            select(Customer).where(
                Customer.id == customer_id,
                Customer.organization_id == self.organization_id,
                Customer.deleted_at.is_(None),
            )
        )

    def active_pricing(self) -> PricingVersion:
        pricing = self.session.scalar(
            select(PricingVersion)
            .where(
                PricingVersion.organization_id == self.organization_id,
                PricingVersion.active.is_(True),
                PricingVersion.effective_from <= datetime.now(UTC),
            )
            .order_by(PricingVersion.effective_from.desc())
            .limit(1)
        )
        if pricing is None:
            raise RuntimeError("No active pricing version is configured.")
        return pricing

    def next_quote_number(self, company_name: str) -> str:
        sequence = self.session.scalar(
            select(NumberSequence)
            .where(
                NumberSequence.organization_id == self.organization_id,
                NumberSequence.sequence_code == "quote",
            )
            .with_for_update()
        )
        if sequence is None:
            sequence = NumberSequence(
                organization_id=self.organization_id,
                sequence_code="quote",
                prefix="MJD-",
                next_value=1,
                padding=4,
            )
            self.session.add(sequence)
            self.session.flush()
        value = sequence.next_value
        sequence.next_value += 1
        company_slug = re.sub(r"[^A-Za-z0-9]+", "-", company_name.strip()).strip("-")
        company_slug = company_slug[:45] or "Customer"
        return f"{sequence.prefix}{value:0{sequence.padding}d}-{company_slug}"

    def current_revision(self, quote: Quote) -> QuoteRevision | None:
        return next(
            (
                revision
                for revision in quote.revisions
                if revision.revision_number == quote.current_revision_number
            ),
            None,
        )

    def clear_revision_detail(self, revision: QuoteRevision) -> None:
        self.session.execute(
            delete(QuoteCharge).where(QuoteCharge.quote_revision_id == revision.id)
        )
        self.session.execute(delete(QuoteStop).where(QuoteStop.quote_revision_id == revision.id))
        self.session.execute(delete(QuoteLoad).where(QuoteLoad.quote_revision_id == revision.id))
        revision.charges.clear()
        revision.stops.clear()
        revision.loads.clear()

    def save_quick_note(self, note: QuickCallNote) -> str:
        self.session.add(note)
        self.session.flush()
        return note.id

    def quick_note(self, note_id: str) -> QuickCallNote | None:
        return self.session.scalar(
            select(QuickCallNote).where(
                QuickCallNote.id == note_id,
                QuickCallNote.organization_id == self.organization_id,
                QuickCallNote.deleted_at.is_(None),
            )
        )

    def create_lead(self, company_name: str, phone: str, email: str) -> Customer:
        numbers = self.session.scalars(
            select(Customer.customer_number).where(Customer.organization_id == self.organization_id)
        ).all()
        highest = 0
        for number in numbers:
            digits = "".join(character for character in number if character.isdigit())
            if digits:
                highest = max(highest, int(digits))
        customer = Customer(
            organization_id=self.organization_id,
            customer_number=f"MJD-CUST-{highest + 1:04d}",
            company_name=company_name,
            status="lead",
            primary_phone=phone.strip() or None,
            primary_email=email.strip().lower() or None,
        )
        self.session.add(customer)
        self.session.flush()
        return customer

    def add_document(
        self,
        *,
        title: str,
        file_name: str,
        storage_key: str,
        mime_type: str,
        size_bytes: int,
        checksum_sha256: str,
        uploader_user_id: str,
        quote_id: str,
        metadata: dict[str, object],
    ) -> Document:
        document = Document(
            organization_id=self.organization_id,
            document_type="quote_pdf",
            title=title,
            file_name=file_name,
            storage_provider="local",
            storage_key=storage_key,
            mime_type=mime_type,
            size_bytes=size_bytes,
            checksum_sha256=checksum_sha256,
            retention_class="financial",
            uploader_user_id=uploader_user_id,
            metadata_json=metadata,
        )
        self.session.add(document)
        self.session.flush()
        self.session.add(
            DocumentLink(
                organization_id=self.organization_id,
                document_id=document.id,
                entity_type="quote",
                entity_id=quote_id,
                relationship_type="generated_quote",
            )
        )
        return document

    def count_documents_for_quote(self, quote_id: str) -> int:
        return int(
            self.session.scalar(
                select(func.count(DocumentLink.id)).where(
                    DocumentLink.organization_id == self.organization_id,
                    DocumentLink.entity_type == "quote",
                    DocumentLink.entity_id == quote_id,
                )
            )
            or 0
        )
