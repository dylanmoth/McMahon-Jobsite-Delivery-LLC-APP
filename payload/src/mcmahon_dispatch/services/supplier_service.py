from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from mcmahon_dispatch.core.exceptions import ValidationError
from mcmahon_dispatch.database.models import (
    Address,
    AuditEvent,
    Contact,
    Supplier,
    SupplierContact,
    SupplierLocation,
)
from mcmahon_dispatch.repositories.supplier_repository import (
    SupplierRepository,
    SupplierSummary,
)


@dataclass(frozen=True, slots=True)
class SupplierLocationData:
    id: str
    display_name: str
    store_number: str
    phone: str
    address: str
    city: str
    state: str
    postal_code: str
    pickup_desk: str
    pickup_instructions: str
    access_notes: str
    dock_available: bool | None
    loading_equipment: tuple[str, ...]
    average_wait_minutes: Decimal | None
    readiness_score: Decimal | None
    active: bool


@dataclass(frozen=True, slots=True)
class SupplierContactData:
    id: str
    first_name: str
    last_name: str
    role_title: str
    phone: str
    mobile: str
    email: str
    notes: str
    is_primary: bool


@dataclass(frozen=True, slots=True)
class SupplierDetails:
    id: str
    name: str
    category: str
    website: str
    active: bool
    notes: str
    locations: tuple[SupplierLocationData, ...]
    contacts: tuple[SupplierContactData, ...]


@dataclass(frozen=True, slots=True)
class SupplierSaveRequest:
    name: str
    category: str
    website: str
    active: bool
    notes: str


@dataclass(frozen=True, slots=True)
class SupplierLocationRequest:
    display_name: str
    store_number: str
    phone: str
    line1: str
    line2: str
    city: str
    state: str
    postal_code: str
    pickup_desk: str
    pickup_instructions: str
    access_notes: str
    dock_available: bool | None
    loading_equipment: tuple[str, ...]
    average_wait_minutes: Decimal | None
    readiness_score: Decimal | None
    active: bool


@dataclass(frozen=True, slots=True)
class SupplierContactRequest:
    first_name: str
    last_name: str
    role_title: str
    phone: str
    mobile: str
    email: str
    notes: str
    is_primary: bool


class SupplierService:
    """Business workflows for the supplier directory."""

    def __init__(
        self,
        factory: sessionmaker[Session],
        organization_id: str,
        actor_user_id: str,
        *,
        can_write: bool,
    ) -> None:
        self.factory = factory
        self.organization_id = organization_id
        self.actor_user_id = actor_user_id
        self.can_write = can_write

    def suppliers(
        self,
        query: str = "",
        active: bool | None = True,
        category: str | None = None,
    ) -> list[SupplierSummary]:
        with self.factory() as session:
            return SupplierRepository(session, self.organization_id).list_suppliers(
                query, active, category
            )

    def categories(self) -> list[str]:
        with self.factory() as session:
            return SupplierRepository(session, self.organization_id).categories()

    def supplier(self, supplier_id: str) -> SupplierDetails:
        with self.factory() as session:
            supplier = SupplierRepository(session, self.organization_id).supplier(supplier_id)
            if supplier is None:
                raise ValidationError("The selected supplier no longer exists.")
            return self._details(supplier)

    def save_supplier(
        self,
        request: SupplierSaveRequest,
        supplier_id: str | None = None,
    ) -> str:
        self._require_write()
        name = request.name.strip()
        if not name:
            raise ValidationError("Supplier name is required.")
        with self.factory.begin() as session:
            repo = SupplierRepository(session, self.organization_id)
            if repo.name_exists(name, supplier_id):
                raise ValidationError("A supplier with that name already exists.")
            supplier = repo.supplier(supplier_id) if supplier_id else None
            if supplier_id and supplier is None:
                raise ValidationError("The selected supplier no longer exists.")
            if supplier is None:
                supplier = Supplier(
                    organization_id=self.organization_id,
                    name=name,
                    created_by_id=self.actor_user_id,
                    updated_by_id=self.actor_user_id,
                )
                session.add(supplier)
                event_type = "suppliers.created"
            else:
                event_type = "suppliers.updated"
            supplier.name = name
            supplier.category = request.category.strip() or None
            supplier.website = request.website.strip() or None
            supplier.active = request.active
            supplier.notes = request.notes.strip()
            supplier.updated_by_id = self.actor_user_id
            session.flush()
            self._audit(session, event_type, "supplier", supplier.id)
            return supplier.id

    def save_location(
        self,
        supplier_id: str,
        request: SupplierLocationRequest,
        location_id: str | None = None,
    ) -> str:
        self._require_write()
        display_name = request.display_name.strip()
        line1 = request.line1.strip()
        if not display_name:
            raise ValidationError("Location name is required.")
        if not line1:
            raise ValidationError("Street address is required.")
        self._validate_score(request.readiness_score, "Readiness score")
        if request.average_wait_minutes is not None and request.average_wait_minutes < 0:
            raise ValidationError("Average wait cannot be negative.")

        with self.factory.begin() as session:
            repo = SupplierRepository(session, self.organization_id)
            supplier = repo.supplier(supplier_id)
            if supplier is None:
                raise ValidationError("The selected supplier no longer exists.")
            location = next(
                (item for item in supplier.locations if item.id == location_id),
                None,
            )
            if location_id and location is None:
                raise ValidationError("The selected supplier location no longer exists.")
            if location is None:
                address = Address(
                    organization_id=self.organization_id,
                    address_type="supplier",
                    entered_address=self._address_text(request),
                    line1=line1,
                    line2=request.line2.strip() or None,
                    city=request.city.strip() or None,
                    state=request.state.strip() or None,
                    postal_code=request.postal_code.strip() or None,
                    country_code="US",
                    created_by_id=self.actor_user_id,
                    updated_by_id=self.actor_user_id,
                )
                session.add(address)
                session.flush()
                location = SupplierLocation(
                    organization_id=self.organization_id,
                    supplier_id=supplier.id,
                    address_id=address.id,
                    display_name=display_name,
                    created_by_id=self.actor_user_id,
                    updated_by_id=self.actor_user_id,
                )
                session.add(location)
                event_type = "supplier_locations.created"
            else:
                address = location.address
                event_type = "supplier_locations.updated"
            address.entered_address = self._address_text(request)
            address.line1 = line1
            address.line2 = request.line2.strip() or None
            address.city = request.city.strip() or None
            address.state = request.state.strip() or None
            address.postal_code = request.postal_code.strip() or None
            address.updated_by_id = self.actor_user_id

            location.display_name = display_name
            location.store_number = request.store_number.strip() or None
            location.phone = request.phone.strip() or None
            location.pickup_desk = request.pickup_desk.strip() or None
            location.pickup_instructions = request.pickup_instructions.strip()
            location.access_notes = request.access_notes.strip()
            location.dock_available = request.dock_available
            location.loading_equipment_json = list(request.loading_equipment)
            location.average_wait_minutes = request.average_wait_minutes
            location.readiness_score = request.readiness_score
            location.active = request.active
            location.updated_by_id = self.actor_user_id
            session.flush()
            self._audit(
                session,
                event_type,
                "supplier_location",
                location.id,
                details={"supplier_id": supplier.id},
            )
            return location.id

    def save_contact(
        self,
        supplier_id: str,
        request: SupplierContactRequest,
        contact_id: str | None = None,
    ) -> str:
        self._require_write()
        first_name = request.first_name.strip()
        if not first_name:
            raise ValidationError("Contact first name is required.")
        email = request.email.strip().lower()
        if email and "@" not in email:
            raise ValidationError("Enter a valid contact email address.")
        with self.factory.begin() as session:
            repo = SupplierRepository(session, self.organization_id)
            supplier = repo.supplier(supplier_id)
            if supplier is None:
                raise ValidationError("The selected supplier no longer exists.")
            link = next(
                (item for item in supplier.contacts if item.contact_id == contact_id),
                None,
            )
            if contact_id and link is None:
                raise ValidationError("The selected supplier contact no longer exists.")
            if link is None:
                contact = Contact(
                    organization_id=self.organization_id,
                    first_name=first_name,
                    created_by_id=self.actor_user_id,
                    updated_by_id=self.actor_user_id,
                )
                session.add(contact)
                session.flush()
                link = SupplierContact(
                    supplier_id=supplier.id,
                    contact_id=contact.id,
                    is_primary=request.is_primary,
                    created_by_id=self.actor_user_id,
                    updated_by_id=self.actor_user_id,
                )
                session.add(link)
                event_type = "supplier_contacts.created"
            else:
                contact = link.contact
                event_type = "supplier_contacts.updated"
            contact.first_name = first_name
            contact.last_name = request.last_name.strip() or None
            contact.role_title = request.role_title.strip() or None
            contact.phone = request.phone.strip() or None
            contact.mobile = request.mobile.strip() or None
            contact.email = email or None
            contact.notes = request.notes.strip()
            contact.updated_by_id = self.actor_user_id
            if request.is_primary:
                for existing in supplier.contacts:
                    existing.is_primary = existing.id == link.id
            else:
                link.is_primary = False
            link.updated_by_id = self.actor_user_id
            session.flush()
            self._audit(
                session,
                event_type,
                "contact",
                contact.id,
                details={"supplier_id": supplier.id},
            )
            return contact.id

    def set_active(self, supplier_id: str, active: bool) -> None:
        self._require_write()
        with self.factory.begin() as session:
            repo = SupplierRepository(session, self.organization_id)
            supplier = repo.supplier(supplier_id)
            if supplier is None:
                raise ValidationError("The selected supplier no longer exists.")
            if active:
                repo.restore(supplier)
                event = "suppliers.restored"
            else:
                repo.archive(supplier)
                event = "suppliers.archived"
            supplier.updated_by_id = self.actor_user_id
            self._audit(session, event, "supplier", supplier.id)

    def delete_supplier(self, supplier_id: str) -> None:
        self._require_write()
        with self.factory.begin() as session:
            repo = SupplierRepository(session, self.organization_id)
            supplier = repo.supplier(supplier_id)
            if supplier is None:
                raise ValidationError("The selected supplier no longer exists.")
            linked_jobs = repo.linked_job_count(supplier.id)
            if linked_jobs:
                raise ValidationError(
                    f"This supplier is linked to {linked_jobs} job stop(s). Archive it instead."
                )
            repo.soft_delete(supplier)
            supplier.updated_by_id = self.actor_user_id
            self._audit(session, "suppliers.deleted", "supplier", supplier.id)

    def _require_write(self) -> None:
        if not self.can_write:
            raise ValidationError("You do not have permission to change suppliers.")

    @staticmethod
    def _validate_score(value: Decimal | None, label: str) -> None:
        if value is not None and not Decimal("0") <= value <= Decimal("100"):
            raise ValidationError(f"{label} must be between 0 and 100.")

    @staticmethod
    def _address_text(request: SupplierLocationRequest) -> str:
        return ", ".join(
            part
            for part in (
                request.line1.strip(),
                request.line2.strip(),
                request.city.strip(),
                request.state.strip(),
                request.postal_code.strip(),
            )
            if part
        )

    @staticmethod
    def _details(supplier: Supplier) -> SupplierDetails:
        locations = tuple(
            SupplierLocationData(
                id=location.id,
                display_name=location.display_name,
                store_number=location.store_number or "",
                phone=location.phone or "",
                address=location.address.line1 or location.address.entered_address,
                city=location.address.city or "",
                state=location.address.state or "",
                postal_code=location.address.postal_code or "",
                pickup_desk=location.pickup_desk or "",
                pickup_instructions=location.pickup_instructions,
                access_notes=location.access_notes,
                dock_available=location.dock_available,
                loading_equipment=tuple(location.loading_equipment_json or []),
                average_wait_minutes=location.average_wait_minutes,
                readiness_score=location.readiness_score,
                active=location.active,
            )
            for location in supplier.locations
            if location.deleted_at is None
        )
        contacts = tuple(
            SupplierContactData(
                id=link.contact.id,
                first_name=link.contact.first_name,
                last_name=link.contact.last_name or "",
                role_title=link.contact.role_title or "",
                phone=link.contact.phone or "",
                mobile=link.contact.mobile or "",
                email=link.contact.email or "",
                notes=link.contact.notes,
                is_primary=link.is_primary,
            )
            for link in supplier.contacts
        )
        return SupplierDetails(
            id=supplier.id,
            name=supplier.name,
            category=supplier.category or "",
            website=supplier.website or "",
            active=supplier.active,
            notes=supplier.notes,
            locations=locations,
            contacts=contacts,
        )

    def _audit(
        self,
        session: Session,
        event_type: str,
        entity_type: str,
        entity_id: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        session.add(
            AuditEvent(
                organization_id=self.organization_id,
                user_id=self.actor_user_id,
                event_type=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                occurred_at=datetime.now(UTC),
                details_json=details or {},
            )
        )
