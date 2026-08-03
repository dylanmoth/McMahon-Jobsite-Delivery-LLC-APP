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
