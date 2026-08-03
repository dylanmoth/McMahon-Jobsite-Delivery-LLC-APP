from __future__ import annotations

from mcmahon_dispatch.services.customer_service import CustomerSaveRequest, CustomerService


def test_customer_crm_create_search_and_statistics(database) -> None:
    from mcmahon_dispatch.database.seed import seed_foundation_data
    seed_foundation_data(database.session_factory)
    with database.session_factory() as session:
        organization_id = session.execute(__import__('sqlalchemy').select(__import__('mcmahon_dispatch.database.models', fromlist=['Organization']).Organization.id)).scalar_one()
        user_id = session.execute(__import__('sqlalchemy').select(__import__('mcmahon_dispatch.database.models', fromlist=['User']).User.id)).scalar_one_or_none()
    # seed may not create a user in tests; audit columns permit None-equivalent actor only through service constructor string
    service = CustomerService(database.session_factory, organization_id, user_id or "system")
    customer_id = service.save(CustomerSaveRequest(
        company_name="Treasure Coast Builders",
        legal_name="Treasure Coast Builders LLC",
        status="active",
        payment_terms_days=15,
        preferred_payment_method="ACH",
        credit_limit_cents=250000,
        readiness_score=90.0,
        relationship_score=95.0,
        internal_notes="Priority contractor account.",
    ))
    results = service.search("Treasure Coast")
    assert [item.id for item in results] == [customer_id]
    customer, stats, quotes, invoices, jobs, documents, suppliers = service.load(customer_id)
    assert customer.company_name == "Treasure Coast Builders"
    assert stats.quote_count == 0
    assert not quotes and not invoices and not jobs and not documents


def test_customer_crm_notes(database) -> None:
    from mcmahon_dispatch.database.seed import seed_foundation_data
    from sqlalchemy import select
    from mcmahon_dispatch.database.models import Organization
    seed_foundation_data(database.session_factory)
    with database.session_factory() as session:
        organization_id = session.scalar(select(Organization.id))
    service = CustomerService(database.session_factory, organization_id, None)
    customer_id = service.save(CustomerSaveRequest("Apex Electric", None, "lead", 15, "Check", None, None, None, ""))
    service.add_note(customer_id, "Call estimator Monday.", "follow-up", True)
    customer, *_ = service.load(customer_id)
    assert len(customer.notes) == 1
    assert customer.notes[0].pinned is True


def _crm_service(database):
    from sqlalchemy import select
    from mcmahon_dispatch.database.models import Organization
    from mcmahon_dispatch.database.seed import seed_foundation_data

    seed_foundation_data(database.session_factory)
    with database.session_factory() as session:
        organization_id = session.scalar(select(Organization.id))
    assert organization_id is not None
    return CustomerService(database.session_factory, organization_id, None)


def _customer_request(name: str, status: str = "active") -> CustomerSaveRequest:
    return CustomerSaveRequest(
        company_name=name,
        legal_name=f"{name} LLC",
        status=status,
        payment_terms_days=15,
        preferred_payment_method="ACH",
        credit_limit_cents=100_000,
        readiness_score=90.0,
        relationship_score=95.0,
        internal_notes="Operations account.",
        primary_phone="772-555-0100",
        primary_email="dispatch@example.com",
        typical_materials="Tile and plumbing supplies",
    )


def test_customer_archive_restore_and_safe_delete(database) -> None:
    service = _crm_service(database)
    customer_id = service.save(_customer_request("Archive Test"))

    service.archive(customer_id)
    assert service.search("Archive Test") == []
    archived = service.search("Archive Test", only_archived=True)
    assert [customer.id for customer in archived] == [customer_id]

    service.restore(customer_id)
    assert [customer.id for customer in service.search("Archive Test")] == [customer_id]

    assessment = service.delete_assessment(customer_id)
    assert assessment.can_delete is True
    service.delete(customer_id)
    assert service.search("Archive Test", include_archived=True) == []


def test_customer_duplicate_copies_profile_contacts_and_addresses(database) -> None:
    service = _crm_service(database)
    source_id = service.save(_customer_request("Original Contractor"))
    service.save_contact(
        source_id,
        {
            "first_name": "Jordan",
            "last_name": "Smith",
            "phone": "772-555-0199",
            "email": "jordan@example.com",
            "is_primary": True,
        },
    )
    service.save_address(
        source_id,
        {
            "entered_address": "123 Main Street, Port St. Lucie, FL 34953",
            "address_type": "office",
            "usage_type": "office",
            "city": "Port St. Lucie",
            "state": "FL",
            "postal_code": "34953",
            "is_primary": True,
        },
    )

    duplicate_id = service.duplicate(source_id, "Original Contractor - Palm Beach")
    duplicate, *_ = service.load(duplicate_id)
    assert duplicate.company_name == "Original Contractor - Palm Beach"
    assert duplicate.customer_number != service.load(source_id)[0].customer_number
    assert len(duplicate.contacts) == 1
    assert duplicate.contacts[0].contact.first_name == "Jordan"
    assert len(duplicate.addresses) == 1
    assert duplicate.addresses[0].address.city == "Port St. Lucie"


def test_customer_merge_moves_notes_and_archives_source(database) -> None:
    service = _crm_service(database)
    source_id = service.save(_customer_request("Duplicate Company"))
    target_id = service.save(_customer_request("Canonical Company"))
    service.add_note(source_id, "Move this note.", "operations", True)

    preview = service.merge_preview(source_id, target_id)
    assert preview.source_name == "Duplicate Company"
    assert preview.target_name == "Canonical Company"

    result_id = service.merge(source_id, target_id)
    assert result_id == target_id
    target, *_ = service.load(target_id)
    assert any(note.body == "Move this note." for note in target.notes)
    source, *_ = service.load(source_id)
    assert source.status == "archived"
