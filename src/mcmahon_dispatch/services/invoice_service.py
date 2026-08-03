from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Iterable

from sqlalchemy.orm import Session, sessionmaker

from mcmahon_dispatch.core.enums import InvoiceStatus
from mcmahon_dispatch.core.exceptions import ValidationError
from mcmahon_dispatch.database.models import Document, DocumentLink, Invoice
from mcmahon_dispatch.repositories.invoice_repository import (
    BillingReport,
    CustomerChoice,
    InvoiceRepository,
    InvoiceSummary,
    PaymentSummary,
)
from mcmahon_dispatch.services.invoice_pdf import InvoicePdfWriter


CENT = Decimal("0.01")


def cents(value: Decimal | str | float | int) -> int:
    return int((Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP) * 100).to_integral_value())


@dataclass(frozen=True, slots=True)
class InvoiceLineRequest:
    description: str
    quantity: Decimal
    unit_rate_cents: int
    taxable: bool = False
    charge_code: str | None = None
    adjustment_reason: str | None = None

    @property
    def line_total_cents(self) -> int:
        return int((self.quantity * Decimal(self.unit_rate_cents)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@dataclass(frozen=True, slots=True)
class InvoiceSaveRequest:
    customer_id: str
    issued_on: date | None
    due_on: date | None
    terms_days: int
    purchase_order_number: str | None
    customer_reference: str | None
    discount_cents: int
    tax_cents: int
    customer_notes: str
    internal_notes: str
    lines: tuple[InvoiceLineRequest, ...]
    issue_now: bool = False


@dataclass(frozen=True, slots=True)
class PaymentAllocationRequest:
    invoice_id: str
    amount_cents: int


@dataclass(frozen=True, slots=True)
class PaymentSaveRequest:
    customer_id: str
    payment_method: str
    received_at: datetime
    gross_amount_cents: int
    processing_fee_cents: int
    external_reference: str | None
    notes: str
    allocations: tuple[PaymentAllocationRequest, ...]


@dataclass(frozen=True, slots=True)
class StatementResult:
    path: Path
    customer_name: str
    opening_balance_cents: int
    invoice_cents: int
    payment_cents: int
    closing_balance_cents: int


class InvoiceService:
    def __init__(
        self,
        factory: sessionmaker[Session],
        organization_id: str,
        user_id: str | None,
        documents_root: Path,
        logo_path: Path,
        *,
        can_write: bool,
    ) -> None:
        self.factory = factory
        self.organization_id = organization_id
        self.user_id = user_id
        self.documents_root = documents_root
        self.logo_path = logo_path
        self.can_write = can_write
        self.pdf = InvoicePdfWriter(logo_path)

    def _ensure_write(self) -> None:
        if not self.can_write:
            raise ValidationError("Your account has read-only billing access.")

    def customer_choices(self) -> list[CustomerChoice]:
        with self.factory() as session:
            return InvoiceRepository(session, self.organization_id).customer_choices()

    def invoices(
        self,
        *,
        query: str = "",
        statuses: Iterable[str] | None = None,
        customer_id: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        outstanding_only: bool = False,
    ) -> list[InvoiceSummary]:
        with self.factory.begin() as session:
            repo = InvoiceRepository(session, self.organization_id)
            self._refresh_overdue(repo, datetime.now(UTC))
            return repo.search_invoices(
                query=query,
                statuses=statuses,
                customer_id=customer_id,
                date_from=date_from,
                date_to=date_to,
                outstanding_only=outstanding_only,
            )

    def invoice(self, invoice_id: str) -> Invoice:
        with self.factory() as session:
            invoice = InvoiceRepository(session, self.organization_id).get_invoice(invoice_id)
            if invoice is None:
                raise ValidationError("Invoice not found.")
            _ = invoice.customer
            _ = tuple(invoice.lines)
            session.expunge_all()
            return invoice

    def save_invoice(self, request: InvoiceSaveRequest, invoice_id: str | None = None) -> str:
        self._ensure_write()
        self._validate_invoice(request)
        with self.factory.begin() as session:
            repo = InvoiceRepository(session, self.organization_id)
            customer = repo.customer(request.customer_id)
            if customer is None:
                raise ValidationError("Select an available customer.")
            invoice = repo.get_invoice(invoice_id) if invoice_id else None
            if invoice_id and invoice is None:
                raise ValidationError("Invoice not found.")
            if invoice is None:
                invoice = repo.create_invoice(customer, self.user_id)
            if invoice.status in (InvoiceStatus.PAID.value, InvoiceStatus.VOID.value, InvoiceStatus.WRITTEN_OFF.value):
                raise ValidationError("Paid, void, and written-off invoices cannot be edited.")

            line_values = tuple(
                (
                    line.charge_code,
                    line.description.strip(),
                    line.quantity,
                    line.unit_rate_cents,
                    line.line_total_cents,
                    line.taxable,
                    line.adjustment_reason,
                )
                for line in request.lines
            )
            repo.replace_lines(invoice, line_values, self.user_id)
            subtotal = sum(line.line_total_cents for line in request.lines)
            total = max(0, subtotal - request.discount_cents + request.tax_cents)
            if total < invoice.paid_cents:
                raise ValidationError("Invoice total cannot be less than payments already applied.")
            invoice.customer_id = customer.id
            invoice.terms_days = request.terms_days
            invoice.purchase_order_number = self._clean_optional(request.purchase_order_number)
            invoice.customer_reference = self._clean_optional(request.customer_reference)
            invoice.subtotal_cents = subtotal
            invoice.discount_cents = request.discount_cents
            invoice.tax_cents = request.tax_cents
            invoice.total_cents = total
            invoice.balance_cents = total - invoice.paid_cents
            invoice.customer_notes = request.customer_notes.strip()
            invoice.internal_notes = request.internal_notes.strip()
            invoice.updated_by_id = self.user_id

            if request.issue_now:
                issued_on = request.issued_on or datetime.now(UTC).date()
                due_on = request.due_on or issued_on + timedelta(days=request.terms_days)
                invoice.issued_at = datetime.combine(issued_on, datetime.min.time(), tzinfo=UTC)
                invoice.due_at = datetime.combine(due_on, datetime.max.time(), tzinfo=UTC)
                invoice.status = InvoiceStatus.ISSUED.value if invoice.balance_cents else InvoiceStatus.PAID.value
            elif request.issued_on:
                invoice.issued_at = datetime.combine(request.issued_on, datetime.min.time(), tzinfo=UTC)
                invoice.due_at = datetime.combine(
                    request.due_on or request.issued_on + timedelta(days=request.terms_days),
                    datetime.max.time(),
                    tzinfo=UTC,
                )
            repo.audit(
                "invoice.saved",
                "invoice",
                invoice.id,
                self.user_id,
                details={"invoice_number": invoice.invoice_number, "total_cents": total, "status": invoice.status},
            )
            session.flush()
            return invoice.id

    def issue_invoice(self, invoice_id: str, issued_on: date | None = None) -> None:
        self._ensure_write()
        now_date = issued_on or datetime.now(UTC).date()
        with self.factory.begin() as session:
            repo = InvoiceRepository(session, self.organization_id)
            invoice = repo.get_invoice(invoice_id)
            if invoice is None:
                raise ValidationError("Invoice not found.")
            if not invoice.lines or invoice.total_cents <= 0:
                raise ValidationError("Add at least one charge before issuing the invoice.")
            if invoice.status not in (InvoiceStatus.DRAFT.value, InvoiceStatus.ISSUED.value):
                raise ValidationError("Only draft or issued invoices can be issued.")
            invoice.issued_at = datetime.combine(now_date, datetime.min.time(), tzinfo=UTC)
            invoice.due_at = datetime.combine(now_date + timedelta(days=invoice.terms_days), datetime.max.time(), tzinfo=UTC)
            invoice.status = InvoiceStatus.ISSUED.value
            invoice.updated_by_id = self.user_id
            repo.audit("invoice.issued", "invoice", invoice.id, self.user_id)

    def void_invoice(self, invoice_id: str, reason: str) -> None:
        self._ensure_write()
        clean_reason = reason.strip()
        if not clean_reason:
            raise ValidationError("Enter a reason for voiding the invoice.")
        with self.factory.begin() as session:
            repo = InvoiceRepository(session, self.organization_id)
            invoice = repo.get_invoice(invoice_id)
            if invoice is None:
                raise ValidationError("Invoice not found.")
            if invoice.paid_cents:
                raise ValidationError("An invoice with payments cannot be voided. Reverse or reallocate the payment first.")
            if invoice.status == InvoiceStatus.PAID.value:
                raise ValidationError("Paid invoices cannot be voided.")
            invoice.status = InvoiceStatus.VOID.value
            invoice.balance_cents = 0
            invoice.void_reason = clean_reason
            invoice.updated_by_id = self.user_id
            repo.audit("invoice.voided", "invoice", invoice.id, self.user_id, reason=clean_reason)

    def apply_late_fee(self, invoice_id: str, amount_cents: int, reason: str) -> None:
        self._ensure_write()
        if amount_cents <= 0:
            raise ValidationError("Late fee must be greater than zero.")
        clean_reason = reason.strip()
        if not clean_reason:
            raise ValidationError("Enter the late-fee reason or policy reference.")
        with self.factory.begin() as session:
            repo = InvoiceRepository(session, self.organization_id)
            invoice = repo.get_invoice(invoice_id)
            if invoice is None:
                raise ValidationError("Invoice not found.")
            if invoice.status in (InvoiceStatus.DRAFT.value, InvoiceStatus.PAID.value, InvoiceStatus.VOID.value, InvoiceStatus.WRITTEN_OFF.value):
                raise ValidationError("Late fees apply only to open issued invoices.")
            if not invoice.due_at or self._as_utc(invoice.due_at) >= datetime.now(UTC):
                raise ValidationError("This invoice is not yet past due.")
            invoice.lines.append(
                self._late_fee_line(invoice, amount_cents, clean_reason)
            )
            invoice.subtotal_cents += amount_cents
            invoice.total_cents += amount_cents
            invoice.balance_cents += amount_cents
            invoice.status = InvoiceStatus.OVERDUE.value
            invoice.updated_by_id = self.user_id
            repo.audit("invoice.late_fee_added", "invoice", invoice.id, self.user_id, reason=clean_reason, details={"amount_cents": amount_cents})

    def _late_fee_line(self, invoice: Invoice, amount_cents: int, reason: str):
        from mcmahon_dispatch.database.models import InvoiceLine

        return InvoiceLine(
            organization_id=self.organization_id,
            sequence=max((line.sequence for line in invoice.lines), default=0) + 1,
            charge_code="LATE_FEE",
            description="Late fee",
            quantity=Decimal("1"),
            unit_rate_cents=amount_cents,
            line_total_cents=amount_cents,
            taxable=False,
            adjustment_reason=reason,
            created_by_id=self.user_id,
            updated_by_id=self.user_id,
        )

    def payments(
        self,
        *,
        query: str = "",
        customer_id: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[PaymentSummary]:
        with self.factory() as session:
            return InvoiceRepository(session, self.organization_id).search_payments(
                query=query, customer_id=customer_id, date_from=date_from, date_to=date_to
            )

    def customer_open_invoices(self, customer_id: str) -> list[InvoiceSummary]:
        with self.factory() as session:
            repo = InvoiceRepository(session, self.organization_id)
            customer = repo.customer(customer_id)
            invoices = repo.customer_open_invoices(customer_id)
            customer_name = customer.company_name if customer else "Customer"
            return [
                InvoiceSummary(
                    id=invoice.id,
                    invoice_number=invoice.invoice_number,
                    customer_id=invoice.customer_id,
                    customer_name=customer_name,
                    status=invoice.status,
                    issued_at=invoice.issued_at,
                    due_at=invoice.due_at,
                    total_cents=invoice.total_cents,
                    paid_cents=invoice.paid_cents,
                    balance_cents=invoice.balance_cents,
                    purchase_order_number=invoice.purchase_order_number,
                    updated_at=invoice.updated_at,
                )
                for invoice in invoices
            ]

    def record_payment(self, request: PaymentSaveRequest) -> str:
        self._ensure_write()
        if not request.customer_id:
            raise ValidationError("Select a customer.")
        if request.gross_amount_cents <= 0:
            raise ValidationError("Payment amount must be greater than zero.")
        if request.processing_fee_cents < 0 or request.processing_fee_cents > request.gross_amount_cents:
            raise ValidationError("Processing fee must be between zero and the payment amount.")
        if not request.payment_method.strip():
            raise ValidationError("Select a payment method.")
        allocated_total = sum(item.amount_cents for item in request.allocations)
        if allocated_total != request.gross_amount_cents:
            raise ValidationError("Payment allocations must equal the full payment amount.")

        with self.factory.begin() as session:
            repo = InvoiceRepository(session, self.organization_id)
            customer = repo.customer(request.customer_id)
            if customer is None:
                raise ValidationError("Customer not found.")
            allocations: list[tuple[Invoice, int]] = []
            seen: set[str] = set()
            for allocation in request.allocations:
                if allocation.invoice_id in seen:
                    raise ValidationError("Each invoice can be allocated only once per payment.")
                seen.add(allocation.invoice_id)
                invoice = repo.get_invoice(allocation.invoice_id)
                if invoice is None or invoice.customer_id != customer.id:
                    raise ValidationError("A selected invoice is unavailable for this customer.")
                if allocation.amount_cents <= 0 or allocation.amount_cents > invoice.balance_cents:
                    raise ValidationError(f"Allocation for {invoice.invoice_number} exceeds its open balance.")
                allocations.append((invoice, allocation.amount_cents))
            payment = repo.create_payment(
                customer_id=customer.id,
                payment_method=request.payment_method.strip().lower().replace(" ", "_"),
                received_at=request.received_at,
                gross_amount_cents=request.gross_amount_cents,
                processing_fee_cents=request.processing_fee_cents,
                external_reference=self._clean_optional(request.external_reference),
                notes=request.notes.strip(),
                allocations=allocations,
                user_id=self.user_id,
            )
            for invoice, amount in allocations:
                invoice.paid_cents += amount
                invoice.balance_cents = max(0, invoice.total_cents - invoice.paid_cents)
                invoice.status = InvoiceStatus.PAID.value if invoice.balance_cents == 0 else InvoiceStatus.PARTIALLY_PAID.value
                invoice.updated_by_id = self.user_id
            repo.audit(
                "payment.recorded",
                "payment",
                payment.id,
                self.user_id,
                details={"payment_number": payment.payment_number, "gross_amount_cents": payment.gross_amount_cents},
            )
            session.flush()
            return payment.id

    def report(self, date_from: date, date_to: date) -> BillingReport:
        if date_to < date_from:
            raise ValidationError("Report end date cannot be before the start date.")
        with self.factory.begin() as session:
            repo = InvoiceRepository(session, self.organization_id)
            self._refresh_overdue(repo, datetime.now(UTC))
            return repo.report(date_from, date_to)

    def generate_invoice_pdf(self, invoice_id: str) -> Path:
        with self.factory.begin() as session:
            repo = InvoiceRepository(session, self.organization_id)
            invoice = repo.get_invoice(invoice_id)
            if invoice is None:
                raise ValidationError("Invoice not found.")
            organization = repo.organization()
            customer = invoice.customer
            if customer is None:
                raise ValidationError("Invoice has no customer.")
            folder = self.documents_root / "Invoices" / self._safe_name(customer.company_name)
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{self._safe_name(invoice.invoice_number)}.pdf"
            self.pdf.write_invoice(path, organization, customer, invoice)
            self._register_document(session, invoice, path, "invoice_pdf")
            repo.audit("invoice.pdf_generated", "invoice", invoice.id, self.user_id, details={"path": str(path)})
            return path

    def generate_statement_pdf(self, customer_id: str, date_from: date, date_to: date) -> StatementResult:
        if date_to < date_from:
            raise ValidationError("Statement end date cannot be before the start date.")
        with self.factory.begin() as session:
            repo = InvoiceRepository(session, self.organization_id)
            organization = repo.organization()
            customer, invoices, payments = repo.customer_statement_rows(customer_id, date_from, date_to)
            valid_invoices = [invoice for invoice in invoices if invoice.status not in (InvoiceStatus.VOID.value, InvoiceStatus.WRITTEN_OFF.value)]
            prior_charges = sum(invoice.total_cents for invoice in valid_invoices if (invoice.issued_at or invoice.created_at).date() < date_from)
            prior_payments = sum(payment.gross_amount_cents for payment in payments if payment.received_at.date() < date_from)
            opening_balance = max(0, prior_charges - prior_payments)
            period_invoices = [invoice for invoice in valid_invoices if date_from <= (invoice.issued_at or invoice.created_at).date() <= date_to]
            period_payments = [payment for payment in payments if date_from <= payment.received_at.date() <= date_to]
            invoice_cents = sum(invoice.total_cents for invoice in period_invoices)
            payment_cents = sum(payment.gross_amount_cents for payment in period_payments)
            closing_balance = max(0, opening_balance + invoice_cents - payment_cents)
            folder = self.documents_root / "Statements" / self._safe_name(customer.company_name)
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"Statement-{date_from.isoformat()}-to-{date_to.isoformat()}.pdf"
            self.pdf.write_statement(
                path,
                organization,
                customer,
                date_from,
                date_to,
                opening_balance,
                period_invoices,
                period_payments,
                closing_balance,
            )
            repo.audit("customer_statement.generated", "customer", customer.id, self.user_id, details={"path": str(path), "date_from": str(date_from), "date_to": str(date_to)})
            return StatementResult(path, customer.company_name, opening_balance, invoice_cents, payment_cents, closing_balance)

    def _register_document(self, session: Session, invoice: Invoice, path: Path, document_type: str) -> None:
        payload = path.read_bytes()
        checksum = hashlib.sha256(payload).hexdigest()
        existing = next((link.document for link in getattr(invoice, "document_links", []) if link.document.storage_key == str(path)), None)
        if existing is not None:
            return
        document = Document(
            organization_id=self.organization_id,
            document_type=document_type,
            title=f"Invoice {invoice.invoice_number}",
            file_name=path.name,
            storage_provider="local",
            storage_key=str(path),
            mime_type="application/pdf",
            size_bytes=len(payload),
            checksum_sha256=checksum,
            retention_class="financial",
            uploader_user_id=self.user_id,
            created_by_id=self.user_id,
            updated_by_id=self.user_id,
        )
        session.add(document)
        session.flush()
        session.add(
            DocumentLink(
                organization_id=self.organization_id,
                document_id=document.id,
                entity_type="invoice",
                entity_id=invoice.id,
                relationship_type="generated_pdf",
                created_by_id=self.user_id,
                updated_by_id=self.user_id,
            )
        )

    def _refresh_overdue(self, repo: InvoiceRepository, now: datetime) -> None:
        for summary in repo.search_invoices(statuses=(InvoiceStatus.ISSUED.value, InvoiceStatus.SENT.value, InvoiceStatus.VIEWED.value, InvoiceStatus.PARTIALLY_PAID.value), outstanding_only=True):
            if summary.due_at and self._as_utc(summary.due_at) < now:
                invoice = repo.get_invoice(summary.id)
                if invoice is not None:
                    invoice.status = InvoiceStatus.OVERDUE.value
                    invoice.updated_by_id = self.user_id

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

    @staticmethod
    def _validate_invoice(request: InvoiceSaveRequest) -> None:
        if not request.customer_id:
            raise ValidationError("Select a customer.")
        if request.terms_days < 0:
            raise ValidationError("Payment terms cannot be negative.")
        if request.discount_cents < 0 or request.tax_cents < 0:
            raise ValidationError("Discount and tax cannot be negative.")
        if not request.lines:
            raise ValidationError("Add at least one invoice line.")
        for line in request.lines:
            if not line.description.strip():
                raise ValidationError("Every invoice line needs a description.")
            if line.quantity <= 0:
                raise ValidationError("Invoice quantities must be greater than zero.")
            if line.unit_rate_cents < 0:
                raise ValidationError("Invoice rates cannot be negative.")
        if request.due_on and request.issued_on and request.due_on < request.issued_on:
            raise ValidationError("Due date cannot be before the issue date.")

    @staticmethod
    def _clean_optional(value: str | None) -> str | None:
        cleaned = (value or "").strip()
        return cleaned or None

    @staticmethod
    def _safe_name(value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-.")
        return cleaned[:100] or "Document"
