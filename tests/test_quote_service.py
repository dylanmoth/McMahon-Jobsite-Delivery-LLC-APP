from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select

from mcmahon_dispatch.database.models import (
    DocumentLink,
    QuickCallNote,
    Quote,
    QuoteCharge,
    QuoteIntake,
    QuoteRevision,
)
from mcmahon_dispatch.services.auth_service import AuthenticationService
from mcmahon_dispatch.services.customer_service import CustomerSaveRequest, CustomerService
from mcmahon_dispatch.services.quote_service import QuickNoteRequest, QuoteDraftRequest, QuoteService


def _services(database, config):
    auth = AuthenticationService(database.session_factory, config)
    user = auth.create_initial_admin(
        "owner",
        "Dylan McMahon",
        "owner@example.com",
        "StrongPassword123",
    )
    customers = CustomerService(database.session_factory, user.organization_id, user.id)
    customer_id = customers.save(
        CustomerSaveRequest(
            company_name="Test Roofing LLC",
            legal_name="Test Roofing LLC",
            status="active",
            payment_terms_days=15,
            preferred_payment_method="ach",
            credit_limit_cents=None,
            readiness_score=90,
            relationship_score=95,
            internal_notes="",
            primary_phone="772-555-0100",
            primary_email="test@example.com",
        )
    )
    quotes = QuoteService(
        database.session_factory,
        user.organization_id,
        user.id,
        config.paths.documents,
        Path(__file__).parents[1]
        / "src"
        / "mcmahon_dispatch"
        / "assets"
        / "images"
        / "mcmahon_dispatch_logo.png",
        can_override_price=True,
        can_write=True,
    )
    return user, customer_id, quotes


def _request(customer_id: str) -> QuoteDraftRequest:
    return QuoteDraftRequest(
        customer_id=customer_id,
        requested_service_at=datetime.now(UTC),
        customer_contact_name="Jane Contractor",
        customer_contact_phone="772-555-0100",
        customer_contact_email="jane@testroofing.com",
        supplier_name="ABC Supply",
        supplier_address="123 Supplier Way, Port St. Lucie, FL",
        order_number="PO-1001",
        order_paid=True,
        order_ready=True,
        pickup_authorization="Customer authorizes pickup.",
        jobsite_address="456 Jobsite Ave, Port St. Lucie, FL",
        site_contact="John Contractor",
        delivery_window="8:00 AM - 10:00 AM",
        materials="Roofing shingles",
        quantity=Decimal("1"),
        length_inches=Decimal("72"),
        width_inches=Decimal("48"),
        height_inches=Decimal("18"),
        weight_pounds=Decimal("300"),
        overweight=False,
        hazardous=False,
        store_inside_psl=True,
        jobsite_inside_psl=True,
        customer_notes="Delivery price assumes safe access.",
        fuel_cost_cents=1200,
    )


def test_quote_save_load_and_revision(database, config) -> None:
    _user, customer_id, service = _services(database, config)
    saved = service.save_draft(_request(customer_id))
    assert saved.quote_number.startswith("MJD-0001-Test-Roofing-LLC")
    assert saved.status == "ready_to_send"
    assert saved.pricing.total_cents == 7500
    assert saved.pricing.profit_cents == 6300

    loaded = service.load(saved.id)
    assert loaded.request.materials == "Roofing shingles"
    assert loaded.request.supplier_name == "ABC Supply"
    assert loaded.pricing.total_cents == 7500

    with database.session_factory() as session:
        quote = session.get(Quote, saved.id)
        assert quote is not None
        assert session.scalar(select(func.count(QuoteIntake.id))) == 1
        assert session.scalar(select(func.count(QuoteRevision.id))) == 1
        assert session.scalar(select(func.count(QuoteCharge.id))) == 1


def test_quote_pdf_and_document_link(database, config) -> None:
    _user, customer_id, service = _services(database, config)
    saved, path = service.generate_quote_pdf(_request(customer_id))
    assert path.is_file()
    assert path.read_bytes().startswith(b"%PDF")
    with database.session_factory() as session:
        count = session.scalar(
            select(func.count(DocumentLink.id)).where(
                DocumentLink.entity_type == "quote",
                DocumentLink.entity_id == saved.id,
            )
        )
        assert count == 1


def test_quick_note_save_lead_and_call_sheet(database, config) -> None:
    _user, _customer_id, service = _services(database, config)
    note = QuickNoteRequest(
        company_contact="Quick Lead Roofing",
        phone="772-555-0200",
        email="lead@example.com",
        supplier_address="Supplier address",
        jobsite_address="Jobsite address",
        materials="Lumber",
        dimensions_text="72 x 48 x 18",
        general_notes="Needs a quote tomorrow.",
    )
    note_id = service.save_quick_note(note)
    lead_id = service.save_quick_note_as_lead(note)
    call_sheet = service.generate_call_sheet(note)
    assert call_sheet.is_file()
    assert call_sheet.read_bytes().startswith(b"%PDF")
    with database.session_factory() as session:
        assert session.get(QuickCallNote, note_id) is not None
        assert lead_id is not None


def test_missing_operational_fields_block_customer_pdf(database, config) -> None:
    _user, customer_id, service = _services(database, config)
    request = QuoteDraftRequest(
        customer_id=customer_id,
        materials="Lumber",
        length_inches=Decimal("72"),
        width_inches=Decimal("48"),
        height_inches=Decimal("18"),
        overweight=False,
        store_inside_psl=True,
        jobsite_inside_psl=True,
    )
    result = service.calculate(request)
    assert result.recommended_status == "needs_information"
    assert not result.sendable
    assert {warning.code for warning in result.warnings} >= {
        "contact_missing",
        "pickup_missing",
        "jobsite_missing",
        "readiness_unknown",
    }


def test_frozen_quote_edit_creates_new_revision(database, config) -> None:
    _user, customer_id, service = _services(database, config)
    saved = service.save_draft(_request(customer_id))
    with database.session_factory.begin() as session:
        quote = session.get(Quote, saved.id)
        assert quote is not None
        quote.status = "sent"
    revised = service.save_draft(
        replace(_request(customer_id), same_day=True),
        saved.id,
    )
    assert revised.quote_number == saved.quote_number
    assert revised.revision_number == 2
    with database.session_factory() as session:
        revisions = session.scalars(
            select(QuoteRevision)
            .where(QuoteRevision.quote_id == saved.id)
            .order_by(QuoteRevision.revision_number)
        ).all()
        assert [revision.revision_number for revision in revisions] == [1, 2]
        assert revisions[0].total_cents == 7500
        assert revisions[1].total_cents == 17500


def test_read_only_quote_service_cannot_mutate(database, config) -> None:
    user, customer_id, _service = _services(database, config)
    read_only = QuoteService(
        database.session_factory,
        user.organization_id,
        user.id,
        config.paths.documents,
        Path(__file__).parents[1]
        / "src"
        / "mcmahon_dispatch"
        / "assets"
        / "images"
        / "mcmahon_dispatch_logo.png",
        can_override_price=False,
        can_write=False,
    )
    result = read_only.calculate(_request(customer_id))
    assert result.total_cents == 7500
    import pytest
    from mcmahon_dispatch.core.exceptions import ValidationError
    with pytest.raises(ValidationError):
        read_only.save_draft(_request(customer_id))
