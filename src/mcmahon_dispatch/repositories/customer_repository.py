from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Iterable

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, selectinload

from mcmahon_dispatch.database.models import (
    Address,
    Contact,
    Customer,
    CustomerAddress,
    CustomerContact,
    CustomerNote,
    CustomerPreferredSupplier,
    Document,
    DocumentLink,
    Invoice,
    Job,
    Quote,
    Supplier,
)


@dataclass(frozen=True, slots=True)
class CustomerStatistics:
    quote_count: int
    accepted_quote_count: int
    invoice_count: int
    job_count: int
    quoted_revenue_cents: int
    invoiced_revenue_cents: int
    paid_revenue_cents: int
    outstanding_cents: int
    actual_profit_cents: int
    average_invoice_cents: int


class CustomerRepository:
    def __init__(self, session: Session, organization_id: str) -> None:
        self.session = session
        self.organization_id = organization_id

    def search(
        self,
        query: str = "",
        statuses: Iterable[str] | None = None,
        payment_method: str | None = None,
        has_outstanding: bool | None = None,
        limit: int = 500,
    ) -> list[Customer]:
        stmt = (
            select(Customer)
            .where(
                Customer.organization_id == self.organization_id,
                Customer.deleted_at.is_(None),
            )
            .options(
                selectinload(Customer.contacts).selectinload(CustomerContact.contact),
                selectinload(Customer.addresses).selectinload(CustomerAddress.address),
            )
            .order_by(Customer.company_name.asc())
            .limit(limit)
        )
        normalized = query.strip()
        if normalized:
            like = f"%{normalized}%"
            customer_ids_by_contact = select(CustomerContact.customer_id).join(Contact).where(
                Contact.organization_id == self.organization_id,
                Contact.deleted_at.is_(None),
                or_(
                    Contact.first_name.ilike(like),
                    Contact.last_name.ilike(like),
                    Contact.phone.ilike(like),
                    Contact.mobile.ilike(like),
                    Contact.email.ilike(like),
                ),
            )
            customer_ids_by_address = select(CustomerAddress.customer_id).join(Address).where(
                Address.organization_id == self.organization_id,
                Address.deleted_at.is_(None),
                or_(
                    Address.entered_address.ilike(like),
                    Address.normalized_address.ilike(like),
                    Address.city.ilike(like),
                    Address.postal_code.ilike(like),
                ),
            )
            customer_ids_by_quote = select(Quote.customer_id).where(
                Quote.organization_id == self.organization_id,
                Quote.quote_number.ilike(like),
            )
            customer_ids_by_invoice = select(Invoice.customer_id).where(
                Invoice.organization_id == self.organization_id,
                Invoice.invoice_number.ilike(like),
            )
            stmt = stmt.where(
                or_(
                    Customer.customer_number.ilike(like),
                    Customer.company_name.ilike(like),
                    Customer.legal_name.ilike(like),
                    Customer.id.in_(customer_ids_by_contact),
                    Customer.id.in_(customer_ids_by_address),
                    Customer.id.in_(customer_ids_by_quote),
                    Customer.id.in_(customer_ids_by_invoice),
                )
            )
        status_values = tuple(statuses or ())
        if status_values:
            stmt = stmt.where(Customer.status.in_(status_values))
        if payment_method:
            stmt = stmt.where(Customer.preferred_payment_method == payment_method)
        if has_outstanding is not None:
            outstanding_exists = select(Invoice.id).where(
                Invoice.customer_id == Customer.id,
                Invoice.balance_cents > 0,
                Invoice.deleted_at.is_(None),
            ).exists()
            stmt = stmt.where(outstanding_exists if has_outstanding else ~outstanding_exists)
        return list(self.session.scalars(stmt).unique())

    def get(self, customer_id: str) -> Customer | None:
        return self.session.scalar(
            select(Customer)
            .where(
                Customer.id == customer_id,
                Customer.organization_id == self.organization_id,
                Customer.deleted_at.is_(None),
            )
            .options(
                selectinload(Customer.contacts).selectinload(CustomerContact.contact),
                selectinload(Customer.addresses).selectinload(CustomerAddress.address),
                selectinload(Customer.notes),
                selectinload(Customer.preferred_suppliers).selectinload(CustomerPreferredSupplier.supplier),
            )
        )

    def next_customer_number(self) -> str:
        numbers = self.session.scalars(
            select(Customer.customer_number).where(Customer.organization_id == self.organization_id)
        ).all()
        highest = 0
        for number in numbers:
            digits = "".join(ch for ch in number if ch.isdigit())
            if digits:
                highest = max(highest, int(digits))
        return f"MJD-CUST-{highest + 1:04d}"

    def create(self, *, company_name: str, legal_name: str | None, status: str) -> Customer:
        customer = Customer(
            organization_id=self.organization_id,
            customer_number=self.next_customer_number(),
            company_name=company_name,
            legal_name=legal_name,
            status=status,
        )
        self.session.add(customer)
        self.session.flush()
        return customer

    def soft_delete(self, customer: Customer, user_id: str) -> None:
        customer.deleted_at = datetime.now(UTC)
        customer.deleted_by_id = user_id
        customer.status = "archived"

    def quotes(self, customer_id: str) -> list[Quote]:
        return list(self.session.scalars(
            select(Quote)
            .where(Quote.customer_id == customer_id, Quote.deleted_at.is_(None))
            .order_by(Quote.created_at.desc())
        ))

    def invoices(self, customer_id: str) -> list[Invoice]:
        return list(self.session.scalars(
            select(Invoice)
            .where(Invoice.customer_id == customer_id, Invoice.deleted_at.is_(None))
            .order_by(Invoice.created_at.desc())
        ))

    def jobs(self, customer_id: str) -> list[Job]:
        return list(self.session.scalars(
            select(Job)
            .where(Job.customer_id == customer_id, Job.deleted_at.is_(None))
            .order_by(Job.created_at.desc())
        ))

    def documents(self, customer_id: str) -> list[Document]:
        return list(self.session.scalars(
            select(Document)
            .join(DocumentLink, DocumentLink.document_id == Document.id)
            .where(
                Document.organization_id == self.organization_id,
                Document.deleted_at.is_(None),
                DocumentLink.entity_type == "customer",
                DocumentLink.entity_id == customer_id,
            )
            .order_by(Document.created_at.desc())
        ))

    def statistics(self, customer_id: str) -> CustomerStatistics:
        quote = self.session.execute(
            select(
                func.count(Quote.id),
                func.sum(case((Quote.status.in_(("accepted", "converted")), 1), else_=0)),
                func.coalesce(func.sum(Quote.total_cents), 0),
            ).where(Quote.customer_id == customer_id, Quote.deleted_at.is_(None))
        ).one()
        invoice = self.session.execute(
            select(
                func.count(Invoice.id),
                func.coalesce(func.sum(Invoice.total_cents), 0),
                func.coalesce(func.sum(Invoice.paid_cents), 0),
                func.coalesce(func.sum(Invoice.balance_cents), 0),
                func.coalesce(func.avg(Invoice.total_cents), 0),
            ).where(Invoice.customer_id == customer_id, Invoice.deleted_at.is_(None))
        ).one()
        job = self.session.execute(
            select(
                func.count(Job.id),
                func.coalesce(func.sum(Job.actual_profit_cents), 0),
            ).where(Job.customer_id == customer_id, Job.deleted_at.is_(None))
        ).one()
        return CustomerStatistics(
            quote_count=int(quote[0] or 0),
            accepted_quote_count=int(quote[1] or 0),
            invoice_count=int(invoice[0] or 0),
            job_count=int(job[0] or 0),
            quoted_revenue_cents=int(quote[2] or 0),
            invoiced_revenue_cents=int(invoice[1] or 0),
            paid_revenue_cents=int(invoice[2] or 0),
            outstanding_cents=int(invoice[3] or 0),
            actual_profit_cents=int(job[1] or 0),
            average_invoice_cents=int(Decimal(invoice[4] or 0)),
        )

    def suppliers(self) -> list[Supplier]:
        return list(self.session.scalars(
            select(Supplier).where(
                Supplier.organization_id == self.organization_id,
                Supplier.deleted_at.is_(None),
                Supplier.active.is_(True),
            ).order_by(Supplier.name)
        ))
