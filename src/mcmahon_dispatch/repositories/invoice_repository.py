from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Iterable

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, selectinload

from mcmahon_dispatch.core.enums import InvoiceStatus, PaymentStatus
from mcmahon_dispatch.database.models import (
    AuditEvent,
    Customer,
    Invoice,
    InvoiceLine,
    NumberSequence,
    Organization,
    Payment,
    PaymentAllocation,
)


@dataclass(frozen=True, slots=True)
class CustomerChoice:
    id: str
    number: str
    company_name: str
    billing_email: str | None
    terms_days: int
    preferred_payment_method: str | None


@dataclass(frozen=True, slots=True)
class InvoiceSummary:
    id: str
    invoice_number: str
    customer_id: str | None
    customer_name: str
    status: str
    issued_at: datetime | None
    due_at: datetime | None
    total_cents: int
    paid_cents: int
    balance_cents: int
    purchase_order_number: str | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class PaymentSummary:
    id: str
    payment_number: str
    customer_id: str | None
    customer_name: str
    status: str
    payment_method: str
    received_at: datetime
    gross_amount_cents: int
    processing_fee_cents: int
    net_deposit_cents: int
    external_reference: str | None
    allocated_cents: int


@dataclass(frozen=True, slots=True)
class AgingBucket:
    label: str
    invoice_count: int
    balance_cents: int


@dataclass(frozen=True, slots=True)
class BillingReport:
    invoiced_cents: int
    collected_cents: int
    outstanding_cents: int
    overdue_cents: int
    invoice_count: int
    paid_invoice_count: int
    average_invoice_cents: int
    collection_rate: Decimal
    aging: tuple[AgingBucket, ...]
    payment_methods: tuple[tuple[str, int, int], ...]


class InvoiceRepository:
    def __init__(self, session: Session, organization_id: str) -> None:
        self.session = session
        self.organization_id = organization_id

    def organization(self) -> Organization:
        organization = self.session.get(Organization, self.organization_id)
        if organization is None:
            raise RuntimeError("Organization was not found.")
        return organization

    def customer_choices(self) -> list[CustomerChoice]:
        customers = self.session.scalars(
            select(Customer)
            .where(
                Customer.organization_id == self.organization_id,
                Customer.deleted_at.is_(None),
                Customer.status.not_in(("archived", "do_not_serve")),
            )
            .order_by(Customer.company_name.asc())
        ).all()
        return [
            CustomerChoice(
                id=customer.id,
                number=customer.customer_number,
                company_name=customer.company_name,
                billing_email=customer.billing_email or customer.primary_email,
                terms_days=customer.payment_terms_days,
                preferred_payment_method=customer.preferred_payment_method,
            )
            for customer in customers
        ]

    def customer(self, customer_id: str) -> Customer | None:
        return self.session.scalar(
            select(Customer).where(
                Customer.id == customer_id,
                Customer.organization_id == self.organization_id,
                Customer.deleted_at.is_(None),
            )
        )

    def search_invoices(
        self,
        *,
        query: str = "",
        statuses: Iterable[str] | None = None,
        customer_id: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        outstanding_only: bool = False,
        limit: int = 1000,
    ) -> list[InvoiceSummary]:
        stmt = (
            select(Invoice, Customer.company_name)
            .outerjoin(Customer, Customer.id == Invoice.customer_id)
            .where(
                Invoice.organization_id == self.organization_id,
                Invoice.deleted_at.is_(None),
            )
            .order_by(Invoice.created_at.desc())
            .limit(limit)
        )
        normalized = query.strip()
        if normalized:
            like = f"%{normalized}%"
            stmt = stmt.where(
                or_(
                    Invoice.invoice_number.ilike(like),
                    Invoice.purchase_order_number.ilike(like),
                    Invoice.customer_reference.ilike(like),
                    Invoice.customer_notes.ilike(like),
                    Customer.company_name.ilike(like),
                    Customer.customer_number.ilike(like),
                    Customer.primary_email.ilike(like),
                    Customer.billing_email.ilike(like),
                )
            )
        status_values = tuple(statuses or ())
        if status_values:
            stmt = stmt.where(Invoice.status.in_(status_values))
        if customer_id:
            stmt = stmt.where(Invoice.customer_id == customer_id)
        if date_from:
            stmt = stmt.where(
                func.date(func.coalesce(Invoice.issued_at, Invoice.created_at)) >= date_from
            )
        if date_to:
            stmt = stmt.where(
                func.date(func.coalesce(Invoice.issued_at, Invoice.created_at)) <= date_to
            )
        if outstanding_only:
            stmt = stmt.where(Invoice.balance_cents > 0)
        rows = self.session.execute(stmt).all()
        return [
            InvoiceSummary(
                id=invoice.id,
                invoice_number=invoice.invoice_number,
                customer_id=invoice.customer_id,
                customer_name=company_name or "Unassigned customer",
                status=invoice.status,
                issued_at=invoice.issued_at,
                due_at=invoice.due_at,
                total_cents=invoice.total_cents,
                paid_cents=invoice.paid_cents,
                balance_cents=invoice.balance_cents,
                purchase_order_number=invoice.purchase_order_number,
                updated_at=invoice.updated_at,
            )
            for invoice, company_name in rows
        ]

    def get_invoice(self, invoice_id: str) -> Invoice | None:
        return self.session.scalar(
            select(Invoice)
            .where(
                Invoice.id == invoice_id,
                Invoice.organization_id == self.organization_id,
                Invoice.deleted_at.is_(None),
            )
            .options(
                selectinload(Invoice.customer),
                selectinload(Invoice.lines),
                selectinload(Invoice.payments).selectinload(PaymentAllocation.payment),
            )
        )

    def next_number(self, code: str, default_prefix: str) -> str:
        sequence = self.session.scalar(
            select(NumberSequence)
            .where(
                NumberSequence.organization_id == self.organization_id,
                NumberSequence.sequence_code == code,
            )
            .with_for_update()
        )
        if sequence is None:
            sequence = NumberSequence(
                organization_id=self.organization_id,
                sequence_code=code,
                prefix=default_prefix,
                next_value=1,
                padding=4,
            )
            self.session.add(sequence)
            self.session.flush()
        value = sequence.next_value
        sequence.next_value += 1
        return f"{sequence.prefix}{value:0{sequence.padding}d}"

    def create_invoice(self, customer: Customer, user_id: str | None) -> Invoice:
        invoice = Invoice(
            organization_id=self.organization_id,
            customer_id=customer.id,
            invoice_number=self.next_number("invoice", "MJD-INV-"),
            status=InvoiceStatus.DRAFT.value,
            terms_days=customer.payment_terms_days,
            created_by_id=user_id,
            updated_by_id=user_id,
        )
        self.session.add(invoice)
        self.session.flush()
        return invoice

    def replace_lines(
        self,
        invoice: Invoice,
        lines: Iterable[tuple[str | None, str, Decimal, int, int, bool, str | None]],
        user_id: str | None,
    ) -> None:
        invoice.lines.clear()
        for sequence, (
            charge_code,
            description,
            quantity,
            unit_rate_cents,
            line_total_cents,
            taxable,
            reason,
        ) in enumerate(lines, start=1):
            invoice.lines.append(
                InvoiceLine(
                    organization_id=self.organization_id,
                    sequence=sequence,
                    charge_code=charge_code,
                    description=description,
                    quantity=quantity,
                    unit_rate_cents=unit_rate_cents,
                    line_total_cents=line_total_cents,
                    taxable=taxable,
                    adjustment_reason=reason,
                    created_by_id=user_id,
                    updated_by_id=user_id,
                )
            )

    def search_payments(
        self,
        *,
        query: str = "",
        customer_id: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int = 1000,
    ) -> list[PaymentSummary]:
        allocated = (
            select(
                PaymentAllocation.payment_id.label("payment_id"),
                func.coalesce(func.sum(PaymentAllocation.amount_cents), 0).label("allocated_cents"),
            )
            .group_by(PaymentAllocation.payment_id)
            .subquery()
        )
        stmt = (
            select(Payment, Customer.company_name, func.coalesce(allocated.c.allocated_cents, 0))
            .outerjoin(Customer, Customer.id == Payment.customer_id)
            .outerjoin(allocated, allocated.c.payment_id == Payment.id)
            .where(Payment.organization_id == self.organization_id)
            .order_by(Payment.received_at.desc())
            .limit(limit)
        )
        normalized = query.strip()
        if normalized:
            like = f"%{normalized}%"
            stmt = stmt.where(
                or_(
                    Payment.payment_number.ilike(like),
                    Payment.external_reference.ilike(like),
                    Payment.provider_transaction_id.ilike(like),
                    Customer.company_name.ilike(like),
                    Customer.customer_number.ilike(like),
                )
            )
        if customer_id:
            stmt = stmt.where(Payment.customer_id == customer_id)
        if date_from:
            stmt = stmt.where(func.date(Payment.received_at) >= date_from)
        if date_to:
            stmt = stmt.where(func.date(Payment.received_at) <= date_to)
        rows = self.session.execute(stmt).all()
        return [
            PaymentSummary(
                id=payment.id,
                payment_number=payment.payment_number,
                customer_id=payment.customer_id,
                customer_name=company_name or "Unassigned customer",
                status=payment.status,
                payment_method=payment.payment_method,
                received_at=payment.received_at,
                gross_amount_cents=payment.gross_amount_cents,
                processing_fee_cents=payment.processing_fee_cents,
                net_deposit_cents=payment.net_deposit_cents,
                external_reference=payment.external_reference,
                allocated_cents=int(allocated_cents or 0),
            )
            for payment, company_name, allocated_cents in rows
        ]

    def create_payment(
        self,
        *,
        customer_id: str,
        payment_method: str,
        received_at: datetime,
        gross_amount_cents: int,
        processing_fee_cents: int,
        external_reference: str | None,
        notes: str,
        allocations: Iterable[tuple[Invoice, int]],
        user_id: str | None,
    ) -> Payment:
        payment = Payment(
            organization_id=self.organization_id,
            customer_id=customer_id,
            payment_number=self.next_number("payment", "MJD-PAY-"),
            status=PaymentStatus.SUCCEEDED.value,
            payment_method=payment_method,
            received_at=received_at,
            gross_amount_cents=gross_amount_cents,
            processing_fee_cents=processing_fee_cents,
            net_deposit_cents=gross_amount_cents - processing_fee_cents,
            external_reference=external_reference,
            notes=notes,
            created_by_id=user_id,
            updated_by_id=user_id,
        )
        self.session.add(payment)
        self.session.flush()
        for invoice, amount_cents in allocations:
            self.session.add(
                PaymentAllocation(
                    payment_id=payment.id,
                    invoice_id=invoice.id,
                    amount_cents=amount_cents,
                    created_by_id=user_id,
                    updated_by_id=user_id,
                )
            )
        return payment

    def customer_open_invoices(self, customer_id: str) -> list[Invoice]:
        return list(
            self.session.scalars(
                select(Invoice)
                .where(
                    Invoice.organization_id == self.organization_id,
                    Invoice.customer_id == customer_id,
                    Invoice.deleted_at.is_(None),
                    Invoice.balance_cents > 0,
                    Invoice.status.not_in(
                        (InvoiceStatus.VOID.value, InvoiceStatus.WRITTEN_OFF.value)
                    ),
                )
                .options(selectinload(Invoice.lines))
                .order_by(Invoice.due_at.asc().nulls_last(), Invoice.created_at.asc())
            )
        )

    def customer_statement_rows(
        self, customer_id: str, date_from: date, date_to: date
    ) -> tuple[Customer, list[Invoice], list[Payment]]:
        customer = self.customer(customer_id)
        if customer is None:
            raise LookupError("Customer not found.")
        invoices = list(
            self.session.scalars(
                select(Invoice)
                .where(
                    Invoice.organization_id == self.organization_id,
                    Invoice.customer_id == customer_id,
                    Invoice.deleted_at.is_(None),
                    func.date(func.coalesce(Invoice.issued_at, Invoice.created_at)) <= date_to,
                )
                .options(selectinload(Invoice.lines), selectinload(Invoice.payments))
                .order_by(func.coalesce(Invoice.issued_at, Invoice.created_at).asc())
            )
        )
        payments = list(
            self.session.scalars(
                select(Payment)
                .where(
                    Payment.organization_id == self.organization_id,
                    Payment.customer_id == customer_id,
                    func.date(Payment.received_at) <= date_to,
                    Payment.status == PaymentStatus.SUCCEEDED.value,
                )
                .options(selectinload(Payment.allocations))
                .order_by(Payment.received_at.asc())
            )
        )
        return customer, invoices, payments

    def report(self, date_from: date, date_to: date) -> BillingReport:
        invoice_filter = (
            Invoice.organization_id == self.organization_id,
            Invoice.deleted_at.is_(None),
            func.date(func.coalesce(Invoice.issued_at, Invoice.created_at)) >= date_from,
            func.date(func.coalesce(Invoice.issued_at, Invoice.created_at)) <= date_to,
            Invoice.status.not_in((InvoiceStatus.VOID.value, InvoiceStatus.WRITTEN_OFF.value)),
        )
        aggregate = self.session.execute(
            select(
                func.coalesce(func.sum(Invoice.total_cents), 0),
                func.coalesce(func.sum(Invoice.paid_cents), 0),
                func.coalesce(func.sum(Invoice.balance_cents), 0),
                func.count(Invoice.id),
                func.sum(case((Invoice.status == InvoiceStatus.PAID.value, 1), else_=0)),
            ).where(*invoice_filter)
        ).one()
        aggregate = tuple(value or 0 for value in aggregate)
        invoiced, collected, outstanding, count, paid_count = map(int, aggregate)
        today = datetime.now(UTC).date()
        overdue_cents = int(
            self.session.scalar(
                select(func.coalesce(func.sum(Invoice.balance_cents), 0)).where(
                    Invoice.organization_id == self.organization_id,
                    Invoice.deleted_at.is_(None),
                    Invoice.balance_cents > 0,
                    Invoice.due_at.is_not(None),
                    func.date(Invoice.due_at) < today,
                    Invoice.status.not_in(
                        (InvoiceStatus.VOID.value, InvoiceStatus.WRITTEN_OFF.value)
                    ),
                )
            )
            or 0
        )
        age_expr = func.julianday(func.current_date()) - func.julianday(Invoice.due_at)
        bucket_specs = (
            ("Current", age_expr <= 0),
            ("1-30 days", age_expr.between(1, 30)),
            ("31-60 days", age_expr.between(31, 60)),
            ("61-90 days", age_expr.between(61, 90)),
            ("90+ days", age_expr > 90),
        )
        aging: list[AgingBucket] = []
        for label, condition in bucket_specs:
            row = self.session.execute(
                select(
                    func.count(Invoice.id), func.coalesce(func.sum(Invoice.balance_cents), 0)
                ).where(
                    Invoice.organization_id == self.organization_id,
                    Invoice.deleted_at.is_(None),
                    Invoice.balance_cents > 0,
                    condition,
                    Invoice.status.not_in(
                        (InvoiceStatus.VOID.value, InvoiceStatus.WRITTEN_OFF.value)
                    ),
                )
            ).one()
            aging.append(AgingBucket(label, int(row[0]), int(row[1])))
        method_rows = self.session.execute(
            select(
                Payment.payment_method,
                func.count(Payment.id),
                func.coalesce(func.sum(Payment.gross_amount_cents), 0),
            )
            .where(
                Payment.organization_id == self.organization_id,
                Payment.status == PaymentStatus.SUCCEEDED.value,
                func.date(Payment.received_at) >= date_from,
                func.date(Payment.received_at) <= date_to,
            )
            .group_by(Payment.payment_method)
            .order_by(func.sum(Payment.gross_amount_cents).desc())
        ).all()
        return BillingReport(
            invoiced_cents=invoiced,
            collected_cents=collected,
            outstanding_cents=outstanding,
            overdue_cents=overdue_cents,
            invoice_count=count,
            paid_invoice_count=paid_count,
            average_invoice_cents=round(invoiced / count) if count else 0,
            collection_rate=(
                (Decimal(collected) / Decimal(invoiced) * 100).quantize(Decimal("0.01"))
                if invoiced
                else Decimal("0")
            ),
            aging=tuple(aging),
            payment_methods=tuple(
                (str(method), int(method_count), int(amount))
                for method, method_count, amount in method_rows
            ),
        )

    def audit(
        self,
        event_type: str,
        entity_type: str,
        entity_id: str,
        user_id: str | None,
        reason: str | None = None,
        details: dict | None = None,
    ) -> None:
        self.session.add(
            AuditEvent(
                organization_id=self.organization_id,
                user_id=user_id,
                event_type=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                reason=reason,
                details_json=details or {},
            )
        )
