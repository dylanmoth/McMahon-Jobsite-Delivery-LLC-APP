from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from mcmahon_dispatch.database.models import (
    ExpenseCategory,
    NumberSequence,
    Organization,
    Permission,
    PricingVersion,
    Role,
    RolePermission,
    Vehicle,
)

PERMISSIONS: Final[dict[str, tuple[str, str, str]]] = {
    "dashboard.view": ("View dashboard", "View the operational dashboard", "dashboard"),
    "dashboard.financial": (
        "View financial dashboard",
        "View financial dashboard metrics",
        "dashboard",
    ),
    "quotes.read": ("Read quotes", "Read quotes and revisions", "quotes"),
    "quotes.write": ("Manage quotes", "Create and edit quotes", "quotes"),
    "quotes.override_price": (
        "Override pricing",
        "Override calculated pricing with audit",
        "quotes",
    ),
    "dispatch.read": ("Read dispatch", "Read jobs and dispatch records", "dispatch"),
    "dispatch.manage": ("Manage dispatch", "Schedule, assign, and update jobs", "dispatch"),
    "customers.read": ("Read customers", "Read customer and contact records", "customers"),
    "customers.write": ("Manage customers", "Create and edit customer records", "customers"),
    "suppliers.read": ("Read suppliers", "Read supplier records", "suppliers"),
    "suppliers.write": ("Manage suppliers", "Create and edit supplier records", "suppliers"),
    "fleet.read": ("Read fleet", "Read drivers, vehicles, fuel, and maintenance", "fleet"),
    "fleet.write": ("Manage fleet", "Manage drivers, vehicles, fuel, and maintenance", "fleet"),
    "billing.read": ("Read billing", "Read invoices, payments, and expenses", "billing"),
    "billing.write": (
        "Manage billing",
        "Create and update invoices, payments, and expenses",
        "billing",
    ),
    "documents.read": ("Read documents", "Read authorized documents and proof", "documents"),
    "documents.write": ("Manage documents", "Upload and manage documents and proof", "documents"),
    "reports.operational": ("Operational reports", "View operational reports", "reports"),
    "reports.financial": ("Financial reports", "View financial reports", "reports"),
    "users.manage": (
        "Manage users",
        "Manage users, roles, devices, and sessions",
        "administration",
    ),
    "settings.manage": (
        "Manage settings",
        "Manage organization and application settings",
        "administration",
    ),
    "audit.read": ("Read audit", "Read audit history", "administration"),
    "backups.manage": ("Manage backups", "Create, verify, and restore backups", "administration"),
}

ROLE_PERMISSION_CODES: Final[dict[str, set[str]]] = {
    "admin": set(PERMISSIONS),
    "dispatcher": {
        "dashboard.view",
        "dashboard.financial",
        "quotes.read",
        "quotes.write",
        "dispatch.read",
        "dispatch.manage",
        "customers.read",
        "customers.write",
        "suppliers.read",
        "suppliers.write",
        "fleet.read",
        "billing.read",
        "billing.write",
        "documents.read",
        "documents.write",
        "reports.operational",
    },
    "driver": {
        "dashboard.view",
        "dispatch.read",
        "customers.read",
        "documents.read",
        "documents.write",
    },
    "accounting": {
        "dashboard.view",
        "dashboard.financial",
        "quotes.read",
        "customers.read",
        "billing.read",
        "billing.write",
        "documents.read",
        "reports.operational",
        "reports.financial",
        "audit.read",
    },
    "auditor": {
        "dashboard.view",
        "quotes.read",
        "dispatch.read",
        "customers.read",
        "suppliers.read",
        "fleet.read",
        "billing.read",
        "documents.read",
        "reports.operational",
        "audit.read",
    },
}

DEFAULT_PRICING: Final[dict[str, object]] = {
    "currency": "USD",
    "tax_enabled": False,
    "standard_base_cents": 7500,
    "standard_dimensions_inches": [76, 58],
    "research_dimensions_inches": [126, 70, 28],
    "mileage_rate_cents": 150,
    "oversized_up_to_two_hours_cents": 10000,
    "oversized_started_hour_cents": 6000,
    "oversized_five_plus_hours_cents": 30000,
    "additional_stop_cents": 3000,
    "same_day_cents": 10000,
    "emergency_conflict_cents": 25000,
    "waiting_free_minutes": 30,
    "waiting_started_half_hour_cents": 5000,
    "loading_free_minutes": 15,
    "loading_increment_minutes": 15,
    "loading_increment_cents": 1500,
    "trash_bag_cents": 1000,
    "cancellation_after_dispatch_cents": 7500,
    "rental_pass_through_enabled": False,
}


def _pricing_checksum(settings: dict[str, object]) -> str:
    payload = json.dumps(settings, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def seed_foundation_data(factory: sessionmaker[Session]) -> None:
    with factory.begin() as session:
        organization = session.scalar(select(Organization).limit(1))
        if organization is None:
            organization = Organization(
                legal_name="McMahon Jobsite Delivery LLC",
                display_name="McMahon Jobsite Delivery",
                timezone="America/New_York",
                currency="USD",
            )
            session.add(organization)
            session.flush()

        permissions: dict[str, Permission] = {}
        for code, (name, description, category) in PERMISSIONS.items():
            permission = session.scalar(select(Permission).where(Permission.code == code))
            if permission is None:
                permission = Permission(
                    code=code,
                    name=name,
                    description=description,
                    category=category,
                    is_system=True,
                )
                session.add(permission)
                session.flush()
            permissions[code] = permission

        for code, permission_codes in ROLE_PERMISSION_CODES.items():
            role = session.scalar(
                select(Role).where(Role.organization_id == organization.id, Role.code == code)
            )
            if role is None:
                role = Role(
                    organization_id=organization.id,
                    code=code,
                    name=code.replace("_", " ").title(),
                    description=f"Built-in {code} role",
                    is_system=True,
                )
                session.add(role)
                session.flush()
            existing = {link.permission.code for link in role.permissions}
            for permission_code in permission_codes - existing:
                session.add(
                    RolePermission(role_id=role.id, permission_id=permissions[permission_code].id)
                )

        for sequence_code, prefix in {
            "customer": "MJD-CUST-",
            "quote": "MJD-",
            "job": "MJD-JOB-",
            "invoice": "MJD-INV-",
            "payment": "MJD-PAY-",
            "driver": "MJD-DRV-",
            "vehicle": "MJD-VEH-",
        }.items():
            exists = session.scalar(
                select(NumberSequence.id).where(
                    NumberSequence.organization_id == organization.id,
                    NumberSequence.sequence_code == sequence_code,
                )
            )
            if exists is None:
                session.add(
                    NumberSequence(
                        organization_id=organization.id,
                        sequence_code=sequence_code,
                        prefix=prefix,
                        next_value=1,
                        padding=4,
                    )
                )

        for code, name in {
            "fuel": "Fuel",
            "rental": "Rental vehicle",
            "tolls_parking": "Tolls and parking",
            "labor": "Helper or contract labor",
            "service_recovery": "Service recovery discount",
            "securement": "Securement supplies",
            "processing_fee": "Processing fees",
            "maintenance": "Vehicle maintenance",
            "other": "Other job-specific expense",
        }.items():
            exists = session.scalar(
                select(ExpenseCategory.id).where(
                    ExpenseCategory.organization_id == organization.id,
                    ExpenseCategory.code == code,
                )
            )
            if exists is None:
                session.add(
                    ExpenseCategory(
                        organization_id=organization.id, code=code, name=name, active=True
                    )
                )

        pricing = session.scalar(
            select(PricingVersion).where(
                PricingVersion.organization_id == organization.id,
                PricingVersion.version_code == "1.0",
            )
        )
        if pricing is None:
            session.add(
                PricingVersion(
                    organization_id=organization.id,
                    version_code="1.0",
                    effective_from=datetime(2026, 8, 3, tzinfo=UTC),
                    settings_json=DEFAULT_PRICING,
                    checksum=_pricing_checksum(DEFAULT_PRICING),
                    active=True,
                )
            )

        vehicle = session.scalar(
            select(Vehicle).where(
                Vehicle.organization_id == organization.id,
                Vehicle.vehicle_number == "MJD-VEH-0001",
            )
        )
        if vehicle is None:
            session.add(
                Vehicle(
                    organization_id=organization.id,
                    vehicle_number="MJD-VEH-0001",
                    year=2025,
                    make="Volkswagen",
                    model="Tiguan",
                    trim="SE R-Line Black",
                    status="available",
                    ownership_type="owned",
                    dimensions_verified=False,
                    payload_verified=False,
                )
            )
