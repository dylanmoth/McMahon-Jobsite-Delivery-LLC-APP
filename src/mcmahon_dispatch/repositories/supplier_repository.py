from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from mcmahon_dispatch.database.models import (
    Address,
    Contact,
    CustomerPreferredSupplier,
    JobStop,
    Supplier,
    SupplierContact,
    SupplierLocation,
)


@dataclass(frozen=True, slots=True)
class SupplierSummary:
    id: str
    name: str
    category: str
    active: bool
    location_count: int
    primary_phone: str
    city_state: str
    average_wait_minutes: Decimal | None
    readiness_score: Decimal | None
    preferred_customer_count: int


class SupplierRepository:
    """Persistence operations for supplier profiles, locations, and contacts."""

    def __init__(self, session: Session, organization_id: str) -> None:
        self.session = session
        self.organization_id = organization_id

    def list_suppliers(
        self,
        query: str = "",
        active: bool | None = True,
        category: str | None = None,
    ) -> list[SupplierSummary]:
        location_count = (
            select(func.count(SupplierLocation.id))
            .where(
                SupplierLocation.supplier_id == Supplier.id,
                SupplierLocation.deleted_at.is_(None),
            )
            .correlate(Supplier)
            .scalar_subquery()
        )
        preferred_count = (
            select(func.count(CustomerPreferredSupplier.id))
            .where(CustomerPreferredSupplier.supplier_id == Supplier.id)
            .correlate(Supplier)
            .scalar_subquery()
        )
        statement = (
            select(Supplier, location_count, preferred_count)
            .where(
                Supplier.organization_id == self.organization_id,
                Supplier.deleted_at.is_(None),
            )
            .options(selectinload(Supplier.locations).joinedload(SupplierLocation.address))
            .order_by(Supplier.name)
        )
        if active is not None:
            statement = statement.where(Supplier.active.is_(active))
        if category:
            statement = statement.where(Supplier.category == category)
        cleaned = query.strip()
        if cleaned:
            like = f"%{cleaned}%"
            statement = statement.where(
                or_(
                    Supplier.name.ilike(like),
                    Supplier.category.ilike(like),
                    Supplier.website.ilike(like),
                    Supplier.notes.ilike(like),
                    Supplier.locations.any(
                        or_(
                            SupplierLocation.display_name.ilike(like),
                            SupplierLocation.store_number.ilike(like),
                            SupplierLocation.phone.ilike(like),
                            SupplierLocation.pickup_instructions.ilike(like),
                        )
                    ),
                )
            )
        rows = self.session.execute(statement).all()
        results: list[SupplierSummary] = []
        for supplier, count, preferred in rows:
            active_locations = [
                location
                for location in supplier.locations
                if location.deleted_at is None and location.active
            ]
            primary = active_locations[0] if active_locations else None
            address = primary.address if primary else None
            waits = [
                location.average_wait_minutes
                for location in active_locations
                if location.average_wait_minutes is not None
            ]
            readiness = [
                location.readiness_score
                for location in active_locations
                if location.readiness_score is not None
            ]
            results.append(
                SupplierSummary(
                    id=supplier.id,
                    name=supplier.name,
                    category=supplier.category or "",
                    active=supplier.active,
                    location_count=int(count or 0),
                    primary_phone=(primary.phone or "") if primary else "",
                    city_state=", ".join(
                        part for part in (
                            address.city if address else None,
                            address.state if address else None,
                        )
                        if part
                    ),
                    average_wait_minutes=(
                        sum(waits, Decimal("0")) / len(waits) if waits else None
                    ),
                    readiness_score=(
                        sum(readiness, Decimal("0")) / len(readiness)
                        if readiness
                        else None
                    ),
                    preferred_customer_count=int(preferred or 0),
                )
            )
        return results

    def supplier(self, supplier_id: str) -> Supplier | None:
        return self.session.scalar(
            select(Supplier)
            .where(
                Supplier.id == supplier_id,
                Supplier.organization_id == self.organization_id,
                Supplier.deleted_at.is_(None),
            )
            .options(
                selectinload(Supplier.locations).joinedload(SupplierLocation.address),
                selectinload(Supplier.contacts).joinedload(SupplierContact.contact),
            )
        )

    def categories(self) -> list[str]:
        return list(
            self.session.scalars(
                select(Supplier.category)
                .where(
                    Supplier.organization_id == self.organization_id,
                    Supplier.deleted_at.is_(None),
                    Supplier.category.is_not(None),
                    Supplier.category != "",
                )
                .distinct()
                .order_by(Supplier.category)
            )
        )

    def name_exists(self, name: str, exclude_id: str | None = None) -> bool:
        statement = select(func.count(Supplier.id)).where(
            Supplier.organization_id == self.organization_id,
            func.lower(Supplier.name) == name.strip().lower(),
            Supplier.deleted_at.is_(None),
        )
        if exclude_id:
            statement = statement.where(Supplier.id != exclude_id)
        return bool(self.session.scalar(statement) or 0)

    def linked_job_count(self, supplier_id: str) -> int:
        location_ids = select(SupplierLocation.id).where(
            SupplierLocation.supplier_id == supplier_id
        )
        return int(
            self.session.scalar(
                select(func.count(JobStop.id)).where(
                    JobStop.supplier_location_id.in_(location_ids)
                )
            )
            or 0
        )

    def archive(self, supplier: Supplier) -> None:
        supplier.active = False

    def restore(self, supplier: Supplier) -> None:
        supplier.active = True

    def soft_delete(self, supplier: Supplier) -> None:
        from mcmahon_dispatch.database.base import utc_now

        supplier.deleted_at = utc_now()
        supplier.active = False
