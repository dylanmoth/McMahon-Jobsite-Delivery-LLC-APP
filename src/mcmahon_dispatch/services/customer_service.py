from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Iterable

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from mcmahon_dispatch.core.exceptions import ValidationError
from mcmahon_dispatch.database.models import (
    Address,
    Contact,
    Customer,
    CustomerAddress,
    CustomerContact,
    CustomerNote,
    CustomerPreferredSupplier,
    DocumentLink,
    Invoice,
    Job,
    Payment,
    Quote,
)
from mcmahon_dispatch.repositories.customer_repository import (
    CustomerDeleteAssessment,
    CustomerRepository,
    CustomerStatistics,
)


@dataclass(frozen=True, slots=True)
class CustomerSaveRequest:
    company_name: str
    legal_name: str | None
    status: str
    payment_terms_days: int
    preferred_payment_method: str | None
    credit_limit_cents: int | None
    readiness_score: float | None
    relationship_score: float | None
    internal_notes: str
    website: str | None = None
    customer_type: str | None = None
    primary_phone: str | None = None
    primary_email: str | None = None
    billing_email: str | None = None
    purchase_order_required: bool = False
    requires_call_ahead: bool = False
    transactional_updates_enabled: bool = True
    photo_confirmation_required: bool = False
    appointment_required: bool = False
    forklift_available: bool = False
    liftgate_required: bool = False
    preferred_pickup_window: str | None = None
    preferred_delivery_window: str | None = None
    receiving_hours: str | None = None
    typical_materials: str = ""
    default_access_instructions: str = ""


@dataclass(frozen=True, slots=True)
class CustomerMergePreview:
    source_id: str
    source_name: str
    target_id: str
    target_name: str
    source_statistics: CustomerStatistics
    target_statistics: CustomerStatistics


class CustomerService:
    def __init__(
        self, factory: sessionmaker[Session], organization_id: str, user_id: str | None
    ) -> None:
        self.factory = factory
        self.organization_id = organization_id
        self.user_id = user_id

    def search(
        self,
        query: str = "",
        statuses: Iterable[str] | None = None,
        payment_method: str | None = None,
        has_outstanding: bool | None = None,
        include_archived: bool = False,
        only_archived: bool = False,
    ) -> list[Customer]:
        with self.factory() as session:
            return CustomerRepository(session, self.organization_id).search(
                query,
                statuses,
                payment_method,
                has_outstanding,
                include_archived,
                only_archived,
            )

    def load(self, customer_id: str):
        with self.factory() as session:
            repo = CustomerRepository(session, self.organization_id)
            customer = repo.get(customer_id)
            if customer is None:
                raise ValidationError("Customer not found or no longer available.")
            stats = repo.statistics(customer_id)
            return (
                customer,
                stats,
                repo.quotes(customer_id),
                repo.invoices(customer_id),
                repo.jobs(customer_id),
                repo.documents(customer_id),
                repo.suppliers(),
            )

    def save(self, request: CustomerSaveRequest, customer_id: str | None = None) -> str:
        company_name = request.company_name.strip()
        if not company_name:
            raise ValidationError("Company name is required.")
        if request.payment_terms_days < 0:
            raise ValidationError("Payment terms cannot be negative.")
        with self.factory.begin() as session:
            repo = CustomerRepository(session, self.organization_id)
            customer = (
                repo.get(customer_id)
                if customer_id
                else repo.create(
                    company_name=company_name,
                    legal_name=request.legal_name,
                    status=request.status,
                )
            )
            if customer is None:
                raise ValidationError("Customer not found.")
            customer.company_name = company_name
            customer.legal_name = request.legal_name.strip() if request.legal_name else None
            customer.status = request.status
            customer.website = request.website.strip() if request.website else None
            customer.customer_type = (
                request.customer_type.strip() if request.customer_type else None
            )
            customer.primary_phone = (
                request.primary_phone.strip() if request.primary_phone else None
            )
            customer.primary_email = (
                request.primary_email.strip().lower() if request.primary_email else None
            )
            customer.payment_terms_days = request.payment_terms_days
            customer.preferred_payment_method = request.preferred_payment_method or None
            customer.billing_email = (
                request.billing_email.strip().lower() if request.billing_email else None
            )
            customer.purchase_order_required = request.purchase_order_required
            customer.credit_limit_cents = request.credit_limit_cents
            customer.requires_call_ahead = request.requires_call_ahead
            customer.transactional_updates_enabled = request.transactional_updates_enabled
            customer.photo_confirmation_required = request.photo_confirmation_required
            customer.appointment_required = request.appointment_required
            customer.forklift_available = request.forklift_available
            customer.liftgate_required = request.liftgate_required
            customer.preferred_pickup_window = (
                request.preferred_pickup_window.strip()
                if request.preferred_pickup_window
                else None
            )
            customer.preferred_delivery_window = (
                request.preferred_delivery_window.strip()
                if request.preferred_delivery_window
                else None
            )
            customer.receiving_hours = (
                request.receiving_hours.strip() if request.receiving_hours else None
            )
            customer.typical_materials = request.typical_materials.strip()
            customer.default_access_instructions = request.default_access_instructions.strip()
            customer.readiness_score = request.readiness_score
            customer.relationship_score = request.relationship_score
            customer.internal_notes = request.internal_notes.strip()
            customer.updated_by_id = self.user_id
            return customer.id

    def archive(self, customer_id: str) -> None:
        with self.factory.begin() as session:
            repo = CustomerRepository(session, self.organization_id)
            customer = repo.get(customer_id)
            if customer is None:
                raise ValidationError("Customer not found.")
            if customer.status == "archived":
                return
            repo.archive(customer)
            customer.updated_by_id = self.user_id

    def restore(self, customer_id: str) -> None:
        with self.factory.begin() as session:
            repo = CustomerRepository(session, self.organization_id)
            customer = repo.get(customer_id)
            if customer is None:
                raise ValidationError("Archived customer not found.")
            repo.restore(customer)
            customer.updated_by_id = self.user_id

    def delete_assessment(self, customer_id: str) -> CustomerDeleteAssessment:
        with self.factory() as session:
            repo = CustomerRepository(session, self.organization_id)
            if repo.get(customer_id) is None:
                raise ValidationError("Customer not found.")
            return repo.delete_assessment(customer_id)

    def delete(self, customer_id: str) -> None:
        with self.factory.begin() as session:
            repo = CustomerRepository(session, self.organization_id)
            customer = repo.get(customer_id)
            if customer is None:
                raise ValidationError("Customer not found.")
            assessment = repo.delete_assessment(customer_id)
            if not assessment.can_delete:
                detail = ", ".join(assessment.blockers)
                raise ValidationError(
                    f"This customer cannot be deleted because it has {detail}. Archive the customer instead."
                )
            repo.soft_delete(customer, self.user_id)

    def duplicate(self, customer_id: str, company_name: str | None = None) -> str:
        with self.factory.begin() as session:
            repo = CustomerRepository(session, self.organization_id)
            source = repo.get(customer_id)
            if source is None:
                raise ValidationError("Customer not found.")
            duplicate_name = (company_name or f"{source.company_name} - Copy").strip()
            if not duplicate_name:
                raise ValidationError("A company name is required for the duplicate customer.")
            target = repo.create(
                company_name=duplicate_name,
                legal_name=source.legal_name,
                status="lead" if source.status == "archived" else source.status,
            )
            copy_fields = (
                "website",
                "customer_type",
                "primary_phone",
                "primary_email",
                "payment_terms_days",
                "preferred_payment_method",
                "billing_email",
                "purchase_order_required",
                "credit_limit_cents",
                "requires_call_ahead",
                "transactional_updates_enabled",
                "photo_confirmation_required",
                "appointment_required",
                "forklift_available",
                "liftgate_required",
                "preferred_pickup_window",
                "preferred_delivery_window",
                "receiving_hours",
                "typical_materials",
                "default_access_instructions",
                "readiness_score",
                "relationship_score",
                "discount_type",
                "discount_value",
                "internal_notes",
            )
            for field in copy_fields:
                setattr(target, field, getattr(source, field))
            target.created_by_id = self.user_id
            target.updated_by_id = self.user_id

            for link in source.contacts:
                old = link.contact
                contact = Contact(
                    organization_id=self.organization_id,
                    first_name=old.first_name,
                    last_name=old.last_name,
                    role_title=old.role_title,
                    phone=old.phone,
                    mobile=old.mobile,
                    email=old.email,
                    preferred_channel=old.preferred_channel,
                    transactional_sms_consent=old.transactional_sms_consent,
                    marketing_sms_consent=old.marketing_sms_consent,
                    notes=old.notes,
                    created_by_id=self.user_id,
                    updated_by_id=self.user_id,
                )
                session.add(contact)
                session.flush()
                session.add(
                    CustomerContact(
                        customer_id=target.id,
                        contact_id=contact.id,
                        is_primary=link.is_primary,
                        role_context=link.role_context,
                        created_by_id=self.user_id,
                        updated_by_id=self.user_id,
                    )
                )

            for link in source.addresses:
                old = link.address
                address = Address(
                    organization_id=self.organization_id,
                    label=old.label,
                    address_type=old.address_type,
                    entered_address=old.entered_address,
                    normalized_address=old.normalized_address,
                    line1=old.line1,
                    line2=old.line2,
                    city=old.city,
                    state=old.state,
                    postal_code=old.postal_code,
                    country_code=old.country_code,
                    latitude=old.latitude,
                    longitude=old.longitude,
                    geocode_provider=old.geocode_provider,
                    geocode_confidence=old.geocode_confidence,
                    geofence_inside=old.geofence_inside,
                    geofence_version_id=old.geofence_version_id,
                    instructions=old.instructions,
                    created_by_id=self.user_id,
                    updated_by_id=self.user_id,
                )
                session.add(address)
                session.flush()
                session.add(
                    CustomerAddress(
                        customer_id=target.id,
                        address_id=address.id,
                        is_primary=link.is_primary,
                        usage_type=link.usage_type,
                        created_by_id=self.user_id,
                        updated_by_id=self.user_id,
                    )
                )

            for link in source.preferred_suppliers:
                session.add(
                    CustomerPreferredSupplier(
                        organization_id=self.organization_id,
                        customer_id=target.id,
                        supplier_id=link.supplier_id,
                        rank=link.rank,
                        notes=link.notes,
                        created_by_id=self.user_id,
                        updated_by_id=self.user_id,
                    )
                )
            return target.id

    def merge_preview(self, source_id: str, target_id: str) -> CustomerMergePreview:
        if source_id == target_id:
            raise ValidationError("Choose two different customers to merge.")
        with self.factory() as session:
            repo = CustomerRepository(session, self.organization_id)
            source = repo.get(source_id)
            target = repo.get(target_id)
            if source is None or target is None:
                raise ValidationError("One of the selected customers no longer exists.")
            return CustomerMergePreview(
                source.id,
                source.company_name,
                target.id,
                target.company_name,
                repo.statistics(source.id),
                repo.statistics(target.id),
            )

    def merge(self, source_id: str, target_id: str) -> str:
        if source_id == target_id:
            raise ValidationError("Choose two different customers to merge.")
        with self.factory.begin() as session:
            repo = CustomerRepository(session, self.organization_id)
            source = repo.get(source_id)
            target = repo.get(target_id)
            if source is None or target is None:
                raise ValidationError("One of the selected customers no longer exists.")

            for model in (Quote, Job, Invoice, Payment):
                session.execute(
                    update(model)
                    .where(model.customer_id == source.id)
                    .values(customer_id=target.id)
                )
            session.execute(
                update(DocumentLink)
                .where(
                    DocumentLink.organization_id == self.organization_id,
                    DocumentLink.entity_type == "customer",
                    DocumentLink.entity_id == source.id,
                )
                .values(entity_id=target.id)
            )
            session.execute(
                update(CustomerNote)
                .where(CustomerNote.customer_id == source.id)
                .values(customer_id=target.id, updated_by_id=self.user_id)
            )

            target_contact_ids = {link.contact_id for link in target.contacts}
            for link in list(source.contacts):
                if link.contact_id in target_contact_ids:
                    session.delete(link)
                else:
                    link.customer_id = target.id
                    target_contact_ids.add(link.contact_id)

            target_address_keys = {
                (link.address_id, link.usage_type) for link in target.addresses
            }
            for link in list(source.addresses):
                key = (link.address_id, link.usage_type)
                if key in target_address_keys:
                    session.delete(link)
                else:
                    link.customer_id = target.id
                    target_address_keys.add(key)

            target_supplier_ids = {link.supplier_id for link in target.preferred_suppliers}
            next_rank = max((link.rank for link in target.preferred_suppliers), default=0) + 1
            for link in list(source.preferred_suppliers):
                if link.supplier_id in target_supplier_ids:
                    session.delete(link)
                else:
                    link.customer_id = target.id
                    link.rank = next_rank
                    next_rank += 1
                    target_supplier_ids.add(link.supplier_id)

            if not target.primary_phone and source.primary_phone:
                target.primary_phone = source.primary_phone
            if not target.primary_email and source.primary_email:
                target.primary_email = source.primary_email
            if not target.billing_email and source.billing_email:
                target.billing_email = source.billing_email
            if source.internal_notes:
                heading = f"Merged from {source.company_name} ({source.customer_number})"
                target.internal_notes = "\n\n".join(
                    part
                    for part in (
                        target.internal_notes.strip(),
                        f"{heading}:\n{source.internal_notes.strip()}",
                    )
                    if part
                )
            target.updated_by_id = self.user_id
            source.status = "archived"
            source.internal_notes = (
                f"Merged into {target.company_name} ({target.customer_number}) on "
                f"{datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}."
            )
            source.updated_by_id = self.user_id
            return target.id

    def save_contact(
        self, customer_id: str, data: dict[str, object], contact_id: str | None = None
    ) -> str:
        first_name = str(data.get("first_name") or "").strip()
        if not first_name:
            raise ValidationError("Contact first name is required.")
        with self.factory.begin() as session:
            repo = CustomerRepository(session, self.organization_id)
            customer = repo.get(customer_id)
            if customer is None:
                raise ValidationError("Customer not found.")
            contact = (
                session.get(Contact, contact_id)
                if contact_id
                else Contact(organization_id=self.organization_id, first_name=first_name)
            )
            if contact is None or contact.organization_id != self.organization_id:
                raise ValidationError("Contact not found.")
            for field in (
                "first_name",
                "last_name",
                "role_title",
                "phone",
                "mobile",
                "email",
                "preferred_channel",
                "notes",
            ):
                value = data.get(field)
                setattr(contact, field, str(value).strip() if value else None if field != "notes" else "")
            contact.transactional_sms_consent = bool(data.get("transactional_sms_consent"))
            contact.marketing_sms_consent = bool(data.get("marketing_sms_consent"))
            contact.updated_by_id = self.user_id
            session.add(contact)
            session.flush()
            link = (
                session.query(CustomerContact)
                .filter_by(customer_id=customer_id, contact_id=contact.id)
                .one_or_none()
            )
            if link is None:
                link = CustomerContact(customer_id=customer_id, contact_id=contact.id)
                session.add(link)
            link.is_primary = bool(data.get("is_primary"))
            link.role_context = str(data.get("role_context") or "").strip() or None
            if link.is_primary:
                session.query(CustomerContact).filter(
                    CustomerContact.customer_id == customer_id,
                    CustomerContact.id != link.id,
                ).update({CustomerContact.is_primary: False})
            return contact.id

    def remove_contact(self, customer_id: str, contact_id: str) -> None:
        with self.factory.begin() as session:
            link = (
                session.query(CustomerContact)
                .filter_by(customer_id=customer_id, contact_id=contact_id)
                .one_or_none()
            )
            if link:
                session.delete(link)

    def save_address(
        self, customer_id: str, data: dict[str, object], address_id: str | None = None
    ) -> str:
        entered = str(data.get("entered_address") or "").strip()
        if not entered:
            raise ValidationError("Address is required.")
        with self.factory.begin() as session:
            address = (
                session.get(Address, address_id)
                if address_id
                else Address(
                    organization_id=self.organization_id,
                    address_type=str(data.get("address_type") or "jobsite"),
                    entered_address=entered,
                )
            )
            if address is None or address.organization_id != self.organization_id:
                raise ValidationError("Address not found.")
            for field in (
                "label",
                "address_type",
                "entered_address",
                "line1",
                "line2",
                "city",
                "state",
                "postal_code",
                "instructions",
            ):
                value = data.get(field)
                setattr(
                    address,
                    field,
                    str(value).strip()
                    if value
                    else ""
                    if field in {"entered_address", "instructions"}
                    else None,
                )
            address.updated_by_id = self.user_id
            session.add(address)
            session.flush()
            usage_type = str(data.get("usage_type") or address.address_type)
            link = (
                session.query(CustomerAddress)
                .filter_by(
                    customer_id=customer_id,
                    address_id=address.id,
                    usage_type=usage_type,
                )
                .one_or_none()
            )
            if link is None:
                link = CustomerAddress(
                    customer_id=customer_id,
                    address_id=address.id,
                    usage_type=usage_type,
                )
                session.add(link)
            link.is_primary = bool(data.get("is_primary"))
            if link.is_primary:
                session.query(CustomerAddress).filter(
                    CustomerAddress.customer_id == customer_id,
                    CustomerAddress.usage_type == usage_type,
                    CustomerAddress.id != link.id,
                ).update({CustomerAddress.is_primary: False})
            return address.id

    def remove_address(self, customer_id: str, address_id: str) -> None:
        with self.factory.begin() as session:
            links = (
                session.query(CustomerAddress)
                .filter_by(customer_id=customer_id, address_id=address_id)
                .all()
            )
            for link in links:
                session.delete(link)

    def add_note(
        self, customer_id: str, body: str, note_type: str = "general", pinned: bool = False
    ) -> str:
        body = body.strip()
        if not body:
            raise ValidationError("Note cannot be empty.")
        with self.factory.begin() as session:
            note = CustomerNote(
                organization_id=self.organization_id,
                customer_id=customer_id,
                author_user_id=self.user_id,
                note_type=note_type,
                body=body,
                pinned=pinned,
                created_by_id=self.user_id,
                updated_by_id=self.user_id,
            )
            session.add(note)
            session.flush()
            return note.id

    def update_note(self, note_id: str, body: str, note_type: str, pinned: bool) -> None:
        with self.factory.begin() as session:
            note = session.get(CustomerNote, note_id)
            if note is None or note.organization_id != self.organization_id:
                raise ValidationError("Note not found.")
            note.body = body.strip()
            note.note_type = note_type
            note.pinned = pinned
            note.updated_by_id = self.user_id

    def delete_note(self, note_id: str) -> None:
        with self.factory.begin() as session:
            note = session.get(CustomerNote, note_id)
            if note is not None and note.organization_id == self.organization_id:
                note.deleted_at = datetime.now(UTC)
                note.deleted_by_id = self.user_id

    def set_preferred_suppliers(self, customer_id: str, supplier_ids: list[str]) -> None:
        with self.factory.begin() as session:
            session.query(CustomerPreferredSupplier).filter_by(customer_id=customer_id).delete()
            for rank, supplier_id in enumerate(supplier_ids, start=1):
                session.add(
                    CustomerPreferredSupplier(
                        organization_id=self.organization_id,
                        customer_id=customer_id,
                        supplier_id=supplier_id,
                        rank=rank,
                        created_by_id=self.user_id,
                        updated_by_id=self.user_id,
                    )
                )
