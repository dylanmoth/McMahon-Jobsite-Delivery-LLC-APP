from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from mcmahon_dispatch.services.auth_service import AuthenticationService
from mcmahon_dispatch.services.customer_service import CustomerSaveRequest, CustomerService
from mcmahon_dispatch.services.invoice_service import (
    InvoiceLineRequest,
    InvoiceSaveRequest,
    InvoiceService,
    PaymentAllocationRequest,
    PaymentSaveRequest,
)


def _setup(database, config):
    auth = AuthenticationService(database.session_factory, config)
    user = auth.create_initial_admin("billing_owner", "Billing Owner", "billing@example.com", "StrongPassword123")
    customers = CustomerService(database.session_factory, user.organization_id, user.id)
    customer_id = customers.save(
        CustomerSaveRequest(
            company_name="Treasure Coast Roofing",
            legal_name="Treasure Coast Roofing LLC",
            status="active",
            payment_terms_days=15,
            preferred_payment_method="ach",
            credit_limit_cents=500_000,
            readiness_score=90,
            relationship_score=95,
            internal_notes="",
            billing_email="billing@tcr.example",
        )
    )
    service = InvoiceService(
        database.session_factory,
        user.organization_id,
        user.id,
        config.paths.documents,
        config.paths.root / "missing-logo.png",
        can_write=True,
    )
    return service, customer_id


def _invoice_request(customer_id: str, total_cents: int = 10_000) -> InvoiceSaveRequest:
    today = date.today()
    return InvoiceSaveRequest(
        customer_id=customer_id,
        issued_on=today,
        due_on=today + timedelta(days=15),
        terms_days=15,
        purchase_order_number="PO-100",
        customer_reference="Project Alpha",
        discount_cents=0,
        tax_cents=0,
        customer_notes="Thank you for your business.",
        internal_notes="",
        lines=(InvoiceLineRequest("Jobsite delivery", Decimal("1"), total_cents),),
        issue_now=True,
    )


def test_invoice_and_partial_payment(database, config) -> None:
    service, customer_id = _setup(database, config)
    invoice_id = service.save_invoice(_invoice_request(customer_id))
    invoice = service.invoice(invoice_id)
    assert invoice.total_cents == 10_000
    assert invoice.balance_cents == 10_000
    assert invoice.status == "issued"

    service.record_payment(
        PaymentSaveRequest(
            customer_id=customer_id,
            payment_method="ach",
            received_at=datetime.now(UTC),
            gross_amount_cents=4_000,
            processing_fee_cents=0,
            external_reference="ACH-001",
            notes="",
            allocations=(PaymentAllocationRequest(invoice_id, 4_000),),
        )
    )
    invoice = service.invoice(invoice_id)
    assert invoice.paid_cents == 4_000
    assert invoice.balance_cents == 6_000
    assert invoice.status == "partially_paid"


def test_full_payment_marks_paid(database, config) -> None:
    service, customer_id = _setup(database, config)
    invoice_id = service.save_invoice(_invoice_request(customer_id, 7_500))
    service.record_payment(
        PaymentSaveRequest(
            customer_id=customer_id,
            payment_method="check",
            received_at=datetime.now(UTC),
            gross_amount_cents=7_500,
            processing_fee_cents=0,
            external_reference="CHECK-42",
            notes="",
            allocations=(PaymentAllocationRequest(invoice_id, 7_500),),
        )
    )
    invoice = service.invoice(invoice_id)
    assert invoice.balance_cents == 0
    assert invoice.status == "paid"


def test_invoice_and_statement_pdfs(database, config) -> None:
    service, customer_id = _setup(database, config)
    invoice_id = service.save_invoice(_invoice_request(customer_id, 12_500))
    invoice_pdf = service.generate_invoice_pdf(invoice_id)
    assert invoice_pdf.exists()
    assert invoice_pdf.read_bytes().startswith(b"%PDF")

    statement = service.generate_statement_pdf(
        customer_id,
        date.today() - timedelta(days=1),
        date.today() + timedelta(days=1),
    )
    assert statement.path.exists()
    assert statement.path.read_bytes().startswith(b"%PDF")
    assert statement.invoice_cents == 12_500
    assert statement.closing_balance_cents == 12_500
