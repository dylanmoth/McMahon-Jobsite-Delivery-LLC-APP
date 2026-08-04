from __future__ import annotations

from sqlalchemy import inspect, select

from mcmahon_dispatch.database.migrations import current_revision
from mcmahon_dispatch.database.models import (
    Customer,
    Driver,
    Expense,
    Invoice,
    Job,
    MaintenanceRecord,
    Payment,
    Quote,
    Supplier,
    User,
    Vehicle,
)


EXPECTED_TABLES = {
    "organizations",
    "users",
    "roles",
    "permissions",
    "user_roles",
    "role_permissions",
    "devices",
    "audit_events",
    "app_settings",
    "customers",
    "contacts",
    "addresses",
    "customer_contacts",
    "customer_addresses",
    "customer_delay_incidents",
    "customer_notes",
    "customer_preferred_suppliers",
    "suppliers",
    "supplier_locations",
    "supplier_contacts",
    "supplier_business_hours",
    "drivers",
    "driver_shifts",
    "vehicles",
    "vehicle_availability",
    "pricing_versions",
    "quotes",
    "quote_revisions",
    "quote_stops",
    "quote_loads",
    "quote_charges",
    "quote_intakes",
    "quick_call_notes",
    "jobs",
    "job_stops",
    "job_assignments",
    "job_status_events",
    "wait_events",
    "dispatch_messages",
    "invoices",
    "invoice_lines",
    "payments",
    "payment_allocations",
    "expense_categories",
    "expenses",
    "maintenance_records",
    "fuel_entries",
    "documents",
    "document_links",
    "signatures",
    "geofence_versions",
    "route_snapshots",
    "communications",
    "number_sequences",
    "sync_queue",
    "sync_conflicts",
}


def test_complete_schema_and_revision(database) -> None:
    inspector = inspect(database.engine)
    assert EXPECTED_TABLES == set(inspector.get_table_names()) - {"alembic_version"}
    assert current_revision(database.engine) is not None


def test_required_operational_indexes(database) -> None:
    inspector = inspect(database.engine)
    required = {
        "customers": "ix_customers_org_status_name",
        "quotes": "ix_quotes_org_status_updated",
        "jobs": "ix_jobs_org_status_window",
        "job_assignments": "ix_assignments_driver_window",
        "invoices": "ix_invoices_org_status_due",
        "payments": "ix_payments_org_received",
        "maintenance_records": "ix_maintenance_org_due",
        "documents": "ix_documents_org_type_created",
        "sync_queue": "ix_sync_pending",
    }
    for table, index_name in required.items():
        assert index_name in {item["name"] for item in inspector.get_indexes(table)}


def test_primary_models_are_mapped(database) -> None:
    with database.session_factory() as session:
        for model in (
            User,
            Customer,
            Supplier,
            Driver,
            Vehicle,
            Quote,
            Job,
            Invoice,
            Payment,
            Expense,
            MaintenanceRecord,
        ):
            session.execute(select(model).limit(1)).all()
