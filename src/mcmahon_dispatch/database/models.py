from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mcmahon_dispatch.core.enums import (
    CustomerStatus,
    DocumentStatus,
    DriverStatus,
    InvoiceStatus,
    JobStatus,
    PaymentStatus,
    QuoteStatus,
    StopType,
    UserStatus,
    VehicleStatus,
)
from mcmahon_dispatch.database.base import (
    AuditMixin,
    Base,
    OrganizationScopedMixin,
    SoftDeleteMixin,
    UUIDPrimaryKeyMixin,
    utc_now,
)

# Money is always persisted as integer cents. Distance, weight, dimensions, fuel, and hours
# use fixed precision Numeric columns to remain portable between SQLite and PostgreSQL.


class Organization(UUIDPrimaryKeyMixin, AuditMixin, Base):
    __tablename__ = "organizations"

    legal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="America/New_York", nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(254))
    website: Mapped[str | None] = mapped_column(String(300))
    logo_document_id: Mapped[str | None] = mapped_column(String(36))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    users: Mapped[list[User]] = relationship(back_populates="organization")
    customers: Mapped[list[Customer]] = relationship(back_populates="organization")


class Permission(UUIDPrimaryKeyMixin, AuditMixin, Base):
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    role_links: Mapped[list[RolePermission]] = relationship(
        back_populates="permission", cascade="all, delete-orphan"
    )


class Role(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, Base):
    __tablename__ = "roles"

    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    permissions: Mapped[list[RolePermission]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )
    users: Mapped[list[UserRole]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_roles_org_code"),
        Index("ix_roles_org_active", "organization_id", "active"),
    )


class RolePermission(UUIDPrimaryKeyMixin, AuditMixin, Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)
    permission_id: Mapped[str] = mapped_column(
        ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False
    )

    role: Mapped[Role] = relationship(back_populates="permissions")
    permission: Mapped[Permission] = relationship(back_populates="role_links")

    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_role_permissions_pair"),
        Index("ix_role_permissions_permission", "permission_id"),
    )


class User(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, SoftDeleteMixin, Base):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(80), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(80))
    last_name: Mapped[str | None] = mapped_column(String(80))
    email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(32))
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=UserStatus.ACTIVE.value, nullable=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mfa_secret_encrypted: Mapped[str | None] = mapped_column(Text)
    notification_preferences_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )

    organization: Mapped[Organization] = relationship(back_populates="users")
    roles: Mapped[list[UserRole]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    devices: Mapped[list[Device]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    driver_profile: Mapped[Driver | None] = relationship(back_populates="user", uselist=False)

    __table_args__ = (
        UniqueConstraint("organization_id", "username", name="uq_users_org_username"),
        UniqueConstraint("organization_id", "email", name="uq_users_org_email"),
        Index("ix_users_org_status_username", "organization_id", "status", "username"),
        Index("ix_users_org_name", "organization_id", "display_name"),
    )


class UserRole(UUIDPrimaryKeyMixin, AuditMixin, Base):
    __tablename__ = "user_roles"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)

    user: Mapped[User] = relationship(back_populates="roles")
    role: Mapped[Role] = relationship(back_populates="users")

    __table_args__ = (
        UniqueConstraint("user_id", "role_id", name="uq_user_roles_pair"),
        Index("ix_user_roles_role", "role_id"),
    )


class Device(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, Base):
    __tablename__ = "devices"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    device_name: Mapped[str] = mapped_column(String(160), nullable=False)
    device_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    platform: Mapped[str] = mapped_column(String(80), nullable=False)
    app_version: Mapped[str] = mapped_column(String(30), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refresh_token_hash: Mapped[str | None] = mapped_column(String(512))

    user: Mapped[User] = relationship(back_populates="devices")

    __table_args__ = (
        UniqueConstraint("organization_id", "device_fingerprint", name="uq_devices_org_fp"),
        Index("ix_devices_user_revoked", "user_id", "revoked_at"),
    )


class AuditEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_events"

    organization_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    device_id: Mapped[str | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(80))
    entity_id: Mapped[str | None] = mapped_column(String(36))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    reason: Mapped[str | None] = mapped_column(Text)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        Index("ix_audit_org_occurred", "organization_id", "occurred_at"),
        Index("ix_audit_entity", "entity_type", "entity_id", "occurred_at"),
        Index("ix_audit_user_occurred", "user_id", "occurred_at"),
    )


class AppSetting(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(160), nullable=False)
    value_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("organization_id", "key", name="uq_settings_org_key"),)


class Contact(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, SoftDeleteMixin, Base):
    __tablename__ = "contacts"

    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str | None] = mapped_column(String(100))
    role_title: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(32))
    mobile: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(254))
    preferred_channel: Mapped[str | None] = mapped_column(String(20))
    transactional_sms_consent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    marketing_sms_consent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sms_opted_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    customer_links: Mapped[list[CustomerContact]] = relationship(
        back_populates="contact", cascade="all, delete-orphan"
    )
    supplier_links: Mapped[list[SupplierContact]] = relationship(
        back_populates="contact", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_contacts_org_email", "organization_id", "email"),
        Index("ix_contacts_org_phone", "organization_id", "phone"),
        Index("ix_contacts_org_name", "organization_id", "last_name", "first_name"),
    )


class Address(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, SoftDeleteMixin, Base):
    __tablename__ = "addresses"

    label: Mapped[str | None] = mapped_column(String(120))
    address_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entered_address: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_address: Mapped[str | None] = mapped_column(Text)
    line1: Mapped[str | None] = mapped_column(String(200))
    line2: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(120))
    state: Mapped[str | None] = mapped_column(String(80))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    country_code: Mapped[str] = mapped_column(String(2), default="US", nullable=False)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    geocode_provider: Mapped[str | None] = mapped_column(String(50))
    geocode_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    geofence_inside: Mapped[bool | None] = mapped_column(Boolean)
    geofence_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("geofence_versions.id", ondelete="SET NULL")
    )
    instructions: Mapped[str] = mapped_column(Text, default="", nullable=False)

    __table_args__ = (
        Index("ix_addresses_org_postal", "organization_id", "postal_code"),
        Index("ix_addresses_org_city", "organization_id", "city", "state"),
        CheckConstraint(
            "latitude IS NULL OR (latitude >= -90 AND latitude <= 90)",
            name="ck_addresses_latitude",
        ),
        CheckConstraint(
            "longitude IS NULL OR (longitude >= -180 AND longitude <= 180)",
            name="ck_addresses_longitude",
        ),
    )


class Customer(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, SoftDeleteMixin, Base):
    __tablename__ = "customers"

    customer_number: Mapped[str] = mapped_column(String(40), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(200))
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), default=CustomerStatus.LEAD.value, nullable=False
    )
    website: Mapped[str | None] = mapped_column(String(254))
    customer_type: Mapped[str | None] = mapped_column(String(80))
    primary_phone: Mapped[str | None] = mapped_column(String(32))
    primary_email: Mapped[str | None] = mapped_column(String(254))
    payment_terms_days: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    preferred_payment_method: Mapped[str | None] = mapped_column(String(40))
    billing_email: Mapped[str | None] = mapped_column(String(254))
    purchase_order_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    credit_limit_cents: Mapped[int | None] = mapped_column(Integer)
    requires_call_ahead: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    transactional_updates_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    photo_confirmation_required: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    appointment_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    forklift_available: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    liftgate_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    preferred_pickup_window: Mapped[str | None] = mapped_column(String(120))
    preferred_delivery_window: Mapped[str | None] = mapped_column(String(120))
    receiving_hours: Mapped[str | None] = mapped_column(String(200))
    typical_materials: Mapped[str] = mapped_column(Text, default="", nullable=False)
    default_access_instructions: Mapped[str] = mapped_column(Text, default="", nullable=False)
    delay_level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    readiness_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    relationship_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    discount_type: Mapped[str | None] = mapped_column(String(20))
    discount_value: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    internal_notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    organization: Mapped[Organization] = relationship(back_populates="customers")
    contacts: Mapped[list[CustomerContact]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )
    addresses: Mapped[list[CustomerAddress]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )
    quotes: Mapped[list[Quote]] = relationship(back_populates="customer")
    jobs: Mapped[list[Job]] = relationship(back_populates="customer")
    invoices: Mapped[list[Invoice]] = relationship(back_populates="customer")
    notes: Mapped[list[CustomerNote]] = relationship(
        back_populates="customer",
        cascade="all, delete-orphan",
        order_by="CustomerNote.created_at.desc()",
    )
    preferred_suppliers: Mapped[list[CustomerPreferredSupplier]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "customer_number", name="uq_customers_org_number"),
        Index("ix_customers_org_status_name", "organization_id", "status", "company_name"),
        CheckConstraint("payment_terms_days >= 0", name="ck_customers_terms_nonnegative"),
        CheckConstraint("delay_level >= 0", name="ck_customers_delay_nonnegative"),
    )


class CustomerContact(UUIDPrimaryKeyMixin, AuditMixin, Base):
    __tablename__ = "customer_contacts"

    customer_id: Mapped[str] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    contact_id: Mapped[str] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    role_context: Mapped[str | None] = mapped_column(String(100))

    customer: Mapped[Customer] = relationship(back_populates="contacts")
    contact: Mapped[Contact] = relationship(back_populates="customer_links")

    __table_args__ = (
        UniqueConstraint("customer_id", "contact_id", name="uq_customer_contact_pair"),
        Index("ix_customer_contacts_contact", "contact_id"),
    )


class CustomerAddress(UUIDPrimaryKeyMixin, AuditMixin, Base):
    __tablename__ = "customer_addresses"

    customer_id: Mapped[str] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    address_id: Mapped[str] = mapped_column(
        ForeignKey("addresses.id", ondelete="CASCADE"), nullable=False
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    usage_type: Mapped[str] = mapped_column(String(40), nullable=False)

    customer: Mapped[Customer] = relationship(back_populates="addresses")
    address: Mapped[Address] = relationship()

    __table_args__ = (
        UniqueConstraint("customer_id", "address_id", "usage_type", name="uq_customer_address_use"),
        Index("ix_customer_addresses_address", "address_id"),
    )


class CustomerNote(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, SoftDeleteMixin, Base):
    __tablename__ = "customer_notes"

    customer_id: Mapped[str] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    author_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    note_type: Mapped[str] = mapped_column(String(40), default="general", nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    customer: Mapped[Customer] = relationship(back_populates="notes")

    __table_args__ = (
        Index("ix_customer_notes_customer_created", "customer_id", "created_at"),
        Index("ix_customer_notes_customer_pinned", "customer_id", "pinned"),
    )


class CustomerPreferredSupplier(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, Base):
    __tablename__ = "customer_preferred_suppliers"

    customer_id: Mapped[str] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    supplier_id: Mapped[str] = mapped_column(
        ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False
    )
    rank: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    customer: Mapped[Customer] = relationship(back_populates="preferred_suppliers")
    supplier: Mapped[Supplier] = relationship()

    __table_args__ = (
        UniqueConstraint("customer_id", "supplier_id", name="uq_customer_preferred_supplier"),
        UniqueConstraint("customer_id", "rank", name="uq_customer_preferred_supplier_rank"),
        Index("ix_customer_preferred_supplier_supplier", "supplier_id"),
        CheckConstraint("rank >= 1", name="ck_customer_preferred_supplier_rank"),
    )


class CustomerDelayIncident(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, Base):
    __tablename__ = "customer_delay_incidents"

    customer_id: Mapped[str] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    wait_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    delay_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    charge_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    __table_args__ = (
        Index("ix_delay_customer_occurred", "customer_id", "occurred_at"),
        CheckConstraint("wait_minutes >= 0", name="ck_delay_wait_nonnegative"),
        CheckConstraint("delay_sequence >= 1", name="ck_delay_sequence_positive"),
    )


class Supplier(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, SoftDeleteMixin, Base):
    __tablename__ = "suppliers"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str | None] = mapped_column(String(100))
    website: Mapped[str | None] = mapped_column(String(300))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    locations: Mapped[list[SupplierLocation]] = relationship(
        back_populates="supplier", cascade="all, delete-orphan"
    )
    contacts: Mapped[list[SupplierContact]] = relationship(
        back_populates="supplier", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_suppliers_org_name", "organization_id", "name"),
        UniqueConstraint("organization_id", "name", name="uq_suppliers_org_name"),
    )


class SupplierLocation(
    UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, SoftDeleteMixin, Base
):
    __tablename__ = "supplier_locations"

    supplier_id: Mapped[str] = mapped_column(
        ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False
    )
    address_id: Mapped[str] = mapped_column(
        ForeignKey("addresses.id", ondelete="RESTRICT"), nullable=False
    )
    store_number: Mapped[str | None] = mapped_column(String(50))
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32))
    pickup_desk: Mapped[str | None] = mapped_column(String(120))
    pickup_instructions: Mapped[str] = mapped_column(Text, default="", nullable=False)
    access_notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    dock_available: Mapped[bool | None] = mapped_column(Boolean)
    loading_equipment_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    average_wait_minutes: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    readiness_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    supplier: Mapped[Supplier] = relationship(back_populates="locations")
    address: Mapped[Address] = relationship()
    hours: Mapped[list[SupplierBusinessHour]] = relationship(
        back_populates="location", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("supplier_id", "store_number", name="uq_supplier_store_number"),
        Index("ix_supplier_locations_org_name", "organization_id", "display_name"),
        Index("ix_supplier_locations_address", "address_id"),
    )


class SupplierBusinessHour(UUIDPrimaryKeyMixin, AuditMixin, Base):
    __tablename__ = "supplier_business_hours"

    supplier_location_id: Mapped[str] = mapped_column(
        ForeignKey("supplier_locations.id", ondelete="CASCADE"), nullable=False
    )
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)
    opens_at: Mapped[time | None] = mapped_column(Time)
    closes_at: Mapped[time | None] = mapped_column(Time)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    location: Mapped[SupplierLocation] = relationship(back_populates="hours")

    __table_args__ = (
        UniqueConstraint("supplier_location_id", "weekday", name="uq_supplier_hours_day"),
        CheckConstraint("weekday >= 0 AND weekday <= 6", name="ck_supplier_hours_weekday"),
    )


class SupplierContact(UUIDPrimaryKeyMixin, AuditMixin, Base):
    __tablename__ = "supplier_contacts"

    supplier_id: Mapped[str] = mapped_column(
        ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False
    )
    supplier_location_id: Mapped[str | None] = mapped_column(
        ForeignKey("supplier_locations.id", ondelete="CASCADE")
    )
    contact_id: Mapped[str] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    supplier: Mapped[Supplier] = relationship(back_populates="contacts")
    contact: Mapped[Contact] = relationship(back_populates="supplier_links")
    location: Mapped[SupplierLocation | None] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "supplier_id", "supplier_location_id", "contact_id", name="uq_supplier_contact_scope"
        ),
        Index("ix_supplier_contacts_contact", "contact_id"),
    )


class Driver(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, SoftDeleteMixin, Base):
    __tablename__ = "drivers"

    driver_number: Mapped[str] = mapped_column(String(40), nullable=False)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), unique=True
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(254))
    status: Mapped[str] = mapped_column(
        String(30), default=DriverStatus.AVAILABLE.value, nullable=False
    )
    license_number_encrypted: Mapped[str | None] = mapped_column(Text)
    license_state: Mapped[str | None] = mapped_column(String(2))
    license_expiration: Mapped[date | None] = mapped_column(Date)
    hire_date: Mapped[date | None] = mapped_column(Date)
    qualifications_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    emergency_contact_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    user: Mapped[User | None] = relationship(back_populates="driver_profile")
    shifts: Mapped[list[DriverShift]] = relationship(
        back_populates="driver", cascade="all, delete-orphan"
    )
    assignments: Mapped[list[JobAssignment]] = relationship(back_populates="driver")

    __table_args__ = (
        UniqueConstraint("organization_id", "driver_number", name="uq_drivers_org_number"),
        Index("ix_drivers_org_status_name", "organization_id", "status", "last_name", "first_name"),
    )


class DriverShift(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, Base):
    __tablename__ = "driver_shifts"

    driver_id: Mapped[str] = mapped_column(
        ForeignKey("drivers.id", ondelete="CASCADE"), nullable=False
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    shift_type: Mapped[str] = mapped_column(String(30), default="available", nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    driver: Mapped[Driver] = relationship(back_populates="shifts")

    __table_args__ = (
        Index("ix_driver_shifts_driver_start", "driver_id", "starts_at"),
        CheckConstraint("ends_at > starts_at", name="ck_driver_shift_order"),
    )


class Vehicle(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, SoftDeleteMixin, Base):
    __tablename__ = "vehicles"

    vehicle_number: Mapped[str] = mapped_column(String(40), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    make: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    trim: Mapped[str | None] = mapped_column(String(100))
    vin_encrypted: Mapped[str | None] = mapped_column(Text)
    plate_number_encrypted: Mapped[str | None] = mapped_column(Text)
    plate_state: Mapped[str | None] = mapped_column(String(2))
    ownership_type: Mapped[str] = mapped_column(String(30), default="owned", nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), default=VehicleStatus.AVAILABLE.value, nullable=False
    )
    cargo_length_inches: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    cargo_width_inches: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    cargo_height_inches: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    payload_pounds: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    towing_pounds: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    dimensions_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    payload_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    odometer_miles: Mapped[Decimal] = mapped_column(Numeric(12, 1), default=0, nullable=False)
    estimated_mpg: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    cost_per_mile_cents: Mapped[int | None] = mapped_column(Integer)
    registration_expires_on: Mapped[date | None] = mapped_column(Date)
    insurance_expires_on: Mapped[date | None] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    assignments: Mapped[list[JobAssignment]] = relationship(back_populates="vehicle")
    maintenance_records: Mapped[list[MaintenanceRecord]] = relationship(back_populates="vehicle")
    fuel_entries: Mapped[list[FuelEntry]] = relationship(back_populates="vehicle")

    __table_args__ = (
        UniqueConstraint("organization_id", "vehicle_number", name="uq_vehicles_org_number"),
        Index("ix_vehicles_org_status", "organization_id", "status"),
        CheckConstraint("year >= 1900 AND year <= 2200", name="ck_vehicles_year"),
        CheckConstraint("odometer_miles >= 0", name="ck_vehicles_odometer"),
    )


class VehicleAvailability(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, Base):
    __tablename__ = "vehicle_availability"

    vehicle_id: Mapped[str] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    availability_type: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_vehicle_availability_vehicle_start", "vehicle_id", "starts_at"),
        CheckConstraint("ends_at > starts_at", name="ck_vehicle_availability_order"),
    )


class PricingVersion(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, Base):
    __tablename__ = "pricing_versions"

    version_code: Mapped[str] = mapped_column(String(40), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settings_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (
        UniqueConstraint("organization_id", "version_code", name="uq_pricing_org_version"),
        Index("ix_pricing_org_effective", "organization_id", "effective_from", "effective_to"),
    )


class QuickCallNote(
    UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, SoftDeleteMixin, Base
):
    __tablename__ = "quick_call_notes"

    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.id", ondelete="SET NULL"))
    quote_id: Mapped[str | None] = mapped_column(ForeignKey("quotes.id", ondelete="SET NULL"))
    company_contact: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    phone: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    email: Mapped[str] = mapped_column(String(254), default="", nullable=False)
    supplier_address: Mapped[str] = mapped_column(Text, default="", nullable=False)
    jobsite_address: Mapped[str] = mapped_column(Text, default="", nullable=False)
    materials: Mapped[str] = mapped_column(Text, default="", nullable=False)
    dimensions_text: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    weight_text: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    overweight: Mapped[bool | None] = mapped_column(Boolean)
    pickup_stops: Mapped[int | None] = mapped_column(Integer)
    order_ready: Mapped[bool | None] = mapped_column(Boolean)
    same_day: Mapped[bool | None] = mapped_column(Boolean)
    store_outside_psl: Mapped[bool | None] = mapped_column(Boolean)
    jobsite_outside_psl: Mapped[bool | None] = mapped_column(Boolean)
    miles_text: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    wait_text: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    trash_text: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    vehicle_text: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    other_client_scheduled: Mapped[bool | None] = mapped_column(Boolean)
    general_notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="open", nullable=False)

    __table_args__ = (
        Index("ix_quick_call_notes_org_created", "organization_id", "created_at"),
        Index("ix_quick_call_notes_quote", "quote_id"),
        CheckConstraint("pickup_stops IS NULL OR pickup_stops >= 1", name="ck_quick_call_stops"),
    )


class QuoteIntake(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, Base):
    __tablename__ = "quote_intakes"

    quote_id: Mapped[str] = mapped_column(
        ForeignKey("quotes.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    customer_contact_name: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    customer_contact_phone: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    customer_contact_email: Mapped[str] = mapped_column(String(254), default="", nullable=False)
    supplier_name: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    supplier_address: Mapped[str] = mapped_column(Text, default="", nullable=False)
    supplier_contact: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    order_number: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    order_paid: Mapped[bool | None] = mapped_column(Boolean)
    order_ready: Mapped[bool | None] = mapped_column(Boolean)
    pickup_authorization: Mapped[str] = mapped_column(Text, default="", nullable=False)
    pickup_instructions: Mapped[str] = mapped_column(Text, default="", nullable=False)

    jobsite_address: Mapped[str] = mapped_column(Text, default="", nullable=False)
    site_contact: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    access_instructions: Mapped[str] = mapped_column(Text, default="", nullable=False)
    delivery_window: Mapped[str] = mapped_column(String(240), default="", nullable=False)

    materials: Mapped[str] = mapped_column(Text, default="", nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=1, nullable=False)
    length_inches: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    width_inches: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    height_inches: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    weight_pounds: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    overweight: Mapped[bool | None] = mapped_column(Boolean)
    hazardous: Mapped[bool | None] = mapped_column(Boolean, default=False)
    prohibited_reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    estimated_hours: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))

    store_inside_psl: Mapped[bool | None] = mapped_column(Boolean)
    jobsite_inside_psl: Mapped[bool | None] = mapped_column(Boolean)
    boundary_to_store_miles: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    store_to_jobsite_miles: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    pickup_stops: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    same_day: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    other_client_affected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    wait_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    delay_sequence: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    loading_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    trash_bag_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    trash_contents_identified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cancelled_after_dispatch: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    tolls_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tolls_pass_through: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    parking_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    parking_pass_through: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rental_cost_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rental_pass_through: Mapped[bool | None] = mapped_column(Boolean)
    rental_markup_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fuel_cost_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    helper_cost_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    securement_cost_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processing_fee_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    other_direct_cost_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    manual_adjustment_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    manual_adjustment_reason: Mapped[str] = mapped_column(Text, default="", nullable=False)

    __table_args__ = (
        Index("ix_quote_intakes_org_quote", "organization_id", "quote_id"),
        CheckConstraint("quantity > 0", name="ck_quote_intake_quantity"),
        CheckConstraint("pickup_stops >= 1", name="ck_quote_intake_stops"),
        CheckConstraint("wait_minutes >= 0", name="ck_quote_intake_wait"),
        CheckConstraint("delay_sequence >= 1", name="ck_quote_intake_delay_sequence"),
        CheckConstraint("loading_minutes >= 0", name="ck_quote_intake_loading"),
        CheckConstraint("trash_bag_count >= 0", name="ck_quote_intake_trash"),
    )


class Quote(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, SoftDeleteMixin, Base):
    __tablename__ = "quotes"

    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.id", ondelete="SET NULL"))
    primary_contact_id: Mapped[str | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL")
    )
    quote_number: Mapped[str] = mapped_column(String(100), nullable=False)
    current_revision_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default=QuoteStatus.DRAFT.value, nullable=False)
    requested_service_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    declined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    customer_notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    internal_notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    dispatch_notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    total_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    direct_cost_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    profit_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    margin_basis_points: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[str] = mapped_column(String(40), default="research", nullable=False)
    manual_review_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    customer: Mapped[Customer | None] = relationship(back_populates="quotes")
    primary_contact: Mapped[Contact | None] = relationship()
    revisions: Mapped[list[QuoteRevision]] = relationship(
        back_populates="quote",
        cascade="all, delete-orphan",
        order_by="QuoteRevision.revision_number",
    )
    intake: Mapped[QuoteIntake | None] = relationship(cascade="all, delete-orphan", uselist=False)
    quick_notes: Mapped[list[QuickCallNote]] = relationship(
        cascade="save-update, merge", foreign_keys="QuickCallNote.quote_id"
    )
    jobs: Mapped[list[Job]] = relationship(back_populates="source_quote")

    __table_args__ = (
        UniqueConstraint("organization_id", "quote_number", name="uq_quotes_org_number"),
        Index("ix_quotes_org_status_updated", "organization_id", "status", "updated_at"),
        Index("ix_quotes_customer_status", "customer_id", "status"),
        CheckConstraint("current_revision_number >= 1", name="ck_quotes_revision_positive"),
        CheckConstraint("total_cents >= 0", name="ck_quotes_total_nonnegative"),
    )


class QuoteRevision(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, Base):
    __tablename__ = "quote_revisions"

    quote_id: Mapped[str] = mapped_column(
        ForeignKey("quotes.id", ondelete="CASCADE"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    pricing_version_id: Mapped[str] = mapped_column(
        ForeignKey("pricing_versions.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acceptance_method: Mapped[str | None] = mapped_column(String(50))
    acceptance_evidence_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    terms_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    configuration_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    change_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    subtotal_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    discount_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tax_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    direct_cost_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    profit_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    margin_basis_points: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[str] = mapped_column(String(40), nullable=False)

    quote: Mapped[Quote] = relationship(back_populates="revisions")
    pricing_version: Mapped[PricingVersion] = relationship()
    stops: Mapped[list[QuoteStop]] = relationship(
        back_populates="revision", cascade="all, delete-orphan", order_by="QuoteStop.sequence"
    )
    loads: Mapped[list[QuoteLoad]] = relationship(
        back_populates="revision", cascade="all, delete-orphan"
    )
    charges: Mapped[list[QuoteCharge]] = relationship(
        back_populates="revision", cascade="all, delete-orphan", order_by="QuoteCharge.sequence"
    )

    __table_args__ = (
        UniqueConstraint("quote_id", "revision_number", name="uq_quote_revision_number"),
        Index("ix_quote_revisions_quote_status", "quote_id", "status"),
        CheckConstraint("revision_number >= 1", name="ck_quote_revisions_positive"),
    )


class QuoteStop(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, Base):
    __tablename__ = "quote_stops"

    quote_revision_id: Mapped[str] = mapped_column(
        ForeignKey("quote_revisions.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    stop_type: Mapped[str] = mapped_column(String(30), nullable=False)
    supplier_location_id: Mapped[str | None] = mapped_column(
        ForeignKey("supplier_locations.id", ondelete="SET NULL")
    )
    address_id: Mapped[str | None] = mapped_column(ForeignKey("addresses.id", ondelete="SET NULL"))
    contact_id: Mapped[str | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"))
    address_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    geocode_snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    requested_window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    service_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    order_number: Mapped[str | None] = mapped_column(String(100))
    order_paid: Mapped[bool | None] = mapped_column(Boolean)
    order_ready: Mapped[bool | None] = mapped_column(Boolean)
    instructions: Mapped[str] = mapped_column(Text, default="", nullable=False)

    revision: Mapped[QuoteRevision] = relationship(back_populates="stops")

    __table_args__ = (
        UniqueConstraint("quote_revision_id", "sequence", name="uq_quote_stop_sequence"),
        Index("ix_quote_stops_address", "address_id"),
        CheckConstraint("sequence >= 1", name="ck_quote_stops_sequence"),
        CheckConstraint("service_minutes >= 0", name="ck_quote_stops_service_minutes"),
    )


class QuoteLoad(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, Base):
    __tablename__ = "quote_loads"

    quote_revision_id: Mapped[str] = mapped_column(
        ForeignKey("quote_revisions.id", ondelete="CASCADE"), nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=1, nullable=False)
    length_inches: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    width_inches: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    height_inches: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    weight_pounds: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    overweight: Mapped[bool | None] = mapped_column(Boolean)
    hazardous: Mapped[bool | None] = mapped_column(Boolean)
    prohibited_reason: Mapped[str | None] = mapped_column(Text)
    trash_bag_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    trash_contents_identified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    recommended_vehicle_id: Mapped[str | None] = mapped_column(
        ForeignKey("vehicles.id", ondelete="SET NULL")
    )

    revision: Mapped[QuoteRevision] = relationship(back_populates="loads")

    __table_args__ = (
        Index("ix_quote_loads_revision", "quote_revision_id"),
        CheckConstraint("quantity > 0", name="ck_quote_loads_quantity"),
        CheckConstraint("trash_bag_count >= 0", name="ck_quote_loads_trash_count"),
    )


class QuoteCharge(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, Base):
    __tablename__ = "quote_charges"

    quote_revision_id: Mapped[str] = mapped_column(
        ForeignKey("quote_revisions.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    charge_code: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=1, nullable=False)
    rate_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    total_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    internal_cost_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rule_id: Mapped[str | None] = mapped_column(String(80))
    rule_reason: Mapped[str | None] = mapped_column(Text)
    customer_visible: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_manual_adjustment: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    override_reason: Mapped[str | None] = mapped_column(Text)
    approved_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    revision: Mapped[QuoteRevision] = relationship(back_populates="charges")

    __table_args__ = (
        UniqueConstraint("quote_revision_id", "sequence", name="uq_quote_charge_sequence"),
        Index("ix_quote_charges_revision_code", "quote_revision_id", "charge_code"),
        CheckConstraint("quantity >= 0", name="ck_quote_charges_quantity"),
    )


class Job(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, SoftDeleteMixin, Base):
    __tablename__ = "jobs"

    source_quote_id: Mapped[str | None] = mapped_column(
        ForeignKey("quotes.id", ondelete="SET NULL")
    )
    source_quote_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("quote_revisions.id", ondelete="SET NULL")
    )
    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.id", ondelete="SET NULL"))
    job_number: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default=JobStatus.DRAFT.value, nullable=False)
    priority: Mapped[str] = mapped_column(String(20), default="normal", nullable=False)
    service_type: Mapped[str] = mapped_column(String(60), nullable=False)
    requested_window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    promised_pickup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    promised_delivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    planned_miles: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    actual_miles: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    planned_minutes: Mapped[int | None] = mapped_column(Integer)
    actual_minutes: Mapped[int | None] = mapped_column(Integer)
    quoted_revenue_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    actual_revenue_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_cost_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    actual_cost_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    actual_profit_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    hold_reason: Mapped[str | None] = mapped_column(Text)
    internal_notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    dispatch_notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    source_quote: Mapped[Quote | None] = relationship(
        back_populates="jobs", foreign_keys=[source_quote_id]
    )
    source_quote_revision: Mapped[QuoteRevision | None] = relationship(
        foreign_keys=[source_quote_revision_id]
    )
    customer: Mapped[Customer | None] = relationship(back_populates="jobs")
    stops: Mapped[list[JobStop]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="JobStop.sequence"
    )
    assignments: Mapped[list[JobAssignment]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    status_events: Mapped[list[JobStatusEvent]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="JobStatusEvent.occurred_at"
    )
    waits: Mapped[list[WaitEvent]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    invoices: Mapped[list[Invoice]] = relationship(back_populates="job")
    expenses: Mapped[list[Expense]] = relationship(back_populates="job")

    __table_args__ = (
        UniqueConstraint("organization_id", "job_number", name="uq_jobs_org_number"),
        Index("ix_jobs_org_status_window", "organization_id", "status", "requested_window_start"),
        Index("ix_jobs_customer_status", "customer_id", "status"),
        Index("ix_jobs_quote", "source_quote_id"),
    )


class JobStop(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, Base):
    __tablename__ = "job_stops"

    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    stop_type: Mapped[str] = mapped_column(String(30), nullable=False)
    supplier_location_id: Mapped[str | None] = mapped_column(
        ForeignKey("supplier_locations.id", ondelete="SET NULL")
    )
    address_id: Mapped[str | None] = mapped_column(ForeignKey("addresses.id", ondelete="SET NULL"))
    contact_id: Mapped[str | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"))
    address_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    instructions_snapshot: Mapped[str] = mapped_column(Text, default="", nullable=False)
    planned_arrival_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_arrival_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_departure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    service_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    order_number: Mapped[str | None] = mapped_column(String(100))
    completion_status: Mapped[str | None] = mapped_column(String(40))
    completion_notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    job: Mapped[Job] = relationship(back_populates="stops")

    __table_args__ = (
        UniqueConstraint("job_id", "sequence", name="uq_job_stop_sequence"),
        Index("ix_job_stops_address", "address_id"),
        CheckConstraint("sequence >= 1", name="ck_job_stops_sequence"),
    )


class JobAssignment(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, Base):
    __tablename__ = "job_assignments"

    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    driver_id: Mapped[str] = mapped_column(
        ForeignKey("drivers.id", ondelete="RESTRICT"), nullable=False
    )
    vehicle_id: Mapped[str] = mapped_column(
        ForeignKey("vehicles.id", ondelete="RESTRICT"), nullable=False
    )
    assigned_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    unassigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unassigned_reason: Mapped[str | None] = mapped_column(Text)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    job: Mapped[Job] = relationship(back_populates="assignments")
    driver: Mapped[Driver] = relationship(back_populates="assignments")
    vehicle: Mapped[Vehicle] = relationship(back_populates="assignments")

    __table_args__ = (
        Index("ix_assignments_driver_window", "driver_id", "starts_at", "ends_at"),
        Index("ix_assignments_vehicle_window", "vehicle_id", "starts_at", "ends_at"),
        Index("ix_assignments_job_active", "job_id", "unassigned_at"),
        CheckConstraint("ends_at > starts_at", name="ck_assignments_order"),
    )


class JobStatusEvent(UUIDPrimaryKeyMixin, OrganizationScopedMixin, Base):
    __tablename__ = "job_status_events"

    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(40))
    to_status: Mapped[str] = mapped_column(String(40), nullable=False)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    device_id: Mapped[str | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    note: Mapped[str | None] = mapped_column(Text)
    override_reason: Mapped[str | None] = mapped_column(Text)

    job: Mapped[Job] = relationship(back_populates="status_events")

    __table_args__ = (Index("ix_job_status_events_job_time", "job_id", "occurred_at"),)


class WaitEvent(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, Base):
    __tablename__ = "wait_events"

    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    job_stop_id: Mapped[str | None] = mapped_column(ForeignKey("job_stops.id", ondelete="SET NULL"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    wait_minutes: Mapped[int | None] = mapped_column(Integer)
    delay_sequence: Mapped[int | None] = mapped_column(Integer)
    recommended_charge_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    approved_charge_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)

    job: Mapped[Job] = relationship(back_populates="waits")

    __table_args__ = (
        Index("ix_wait_events_job_started", "job_id", "started_at"),
        CheckConstraint("wait_minutes IS NULL OR wait_minutes >= 0", name="ck_wait_minutes"),
    )


class DispatchMessage(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, Base):
    __tablename__ = "dispatch_messages"

    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    sender_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    recipient_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    channel: Mapped[str] = mapped_column(String(30), default="in_app", nullable=False)
    subject: Mapped[str | None] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_message_id: Mapped[str | None] = mapped_column(String(200))
    provider_status: Mapped[str | None] = mapped_column(String(50))
    failure_reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_dispatch_messages_job_created", "job_id", "created_at"),
        Index("ix_dispatch_messages_recipient_read", "recipient_user_id", "read_at"),
    )


class Invoice(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, SoftDeleteMixin, Base):
    __tablename__ = "invoices"

    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.id", ondelete="SET NULL"))
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    quote_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("quote_revisions.id", ondelete="SET NULL")
    )
    billing_contact_id: Mapped[str | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL")
    )
    billing_address_id: Mapped[str | None] = mapped_column(
        ForeignKey("addresses.id", ondelete="SET NULL")
    )
    invoice_number: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), default=InvoiceStatus.DRAFT.value, nullable=False
    )
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terms_days: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    purchase_order_number: Mapped[str | None] = mapped_column(String(100))
    customer_reference: Mapped[str | None] = mapped_column(String(100))
    subtotal_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    discount_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tax_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    paid_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    balance_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    internal_notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    customer_notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    void_reason: Mapped[str | None] = mapped_column(Text)
    written_off_reason: Mapped[str | None] = mapped_column(Text)

    customer: Mapped[Customer | None] = relationship(back_populates="invoices")
    job: Mapped[Job | None] = relationship(back_populates="invoices")
    lines: Mapped[list[InvoiceLine]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", order_by="InvoiceLine.sequence"
    )
    payments: Mapped[list[PaymentAllocation]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "invoice_number", name="uq_invoices_org_number"),
        Index("ix_invoices_org_status_due", "organization_id", "status", "due_at"),
        Index("ix_invoices_customer_status", "customer_id", "status"),
        CheckConstraint("terms_days >= 0", name="ck_invoices_terms"),
        CheckConstraint("subtotal_cents >= 0", name="ck_invoices_subtotal"),
        CheckConstraint("tax_cents >= 0", name="ck_invoices_tax"),
        CheckConstraint("total_cents >= 0", name="ck_invoices_total"),
        CheckConstraint("paid_cents >= 0", name="ck_invoices_paid"),
        CheckConstraint("balance_cents >= 0", name="ck_invoices_balance"),
    )


class InvoiceLine(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, Base):
    __tablename__ = "invoice_lines"

    invoice_id: Mapped[str] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    charge_code: Mapped[str | None] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=1, nullable=False)
    unit_rate_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    line_total_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    taxable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source_quote_charge_id: Mapped[str | None] = mapped_column(
        ForeignKey("quote_charges.id", ondelete="SET NULL")
    )
    adjustment_reason: Mapped[str | None] = mapped_column(Text)

    invoice: Mapped[Invoice] = relationship(back_populates="lines")

    __table_args__ = (
        UniqueConstraint("invoice_id", "sequence", name="uq_invoice_line_sequence"),
        CheckConstraint("quantity >= 0", name="ck_invoice_lines_quantity"),
    )


class Payment(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, Base):
    __tablename__ = "payments"

    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.id", ondelete="SET NULL"))
    payment_number: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), default=PaymentStatus.PENDING.value, nullable=False
    )
    payment_method: Mapped[str] = mapped_column(String(40), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    gross_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    processing_fee_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    net_deposit_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    external_reference: Mapped[str | None] = mapped_column(String(200))
    provider: Mapped[str | None] = mapped_column(String(60))
    provider_transaction_id: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refund_reason: Mapped[str | None] = mapped_column(Text)

    allocations: Mapped[list[PaymentAllocation]] = relationship(
        back_populates="payment", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "payment_number", name="uq_payments_org_number"),
        Index("ix_payments_org_received", "organization_id", "received_at"),
        Index("ix_payments_customer_received", "customer_id", "received_at"),
        CheckConstraint("gross_amount_cents >= 0", name="ck_payments_gross"),
        CheckConstraint("processing_fee_cents >= 0", name="ck_payments_fee"),
        CheckConstraint("net_deposit_cents >= 0", name="ck_payments_net"),
    )


class PaymentAllocation(UUIDPrimaryKeyMixin, AuditMixin, Base):
    __tablename__ = "payment_allocations"

    payment_id: Mapped[str] = mapped_column(
        ForeignKey("payments.id", ondelete="CASCADE"), nullable=False
    )
    invoice_id: Mapped[str] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)

    payment: Mapped[Payment] = relationship(back_populates="allocations")
    invoice: Mapped[Invoice] = relationship(back_populates="payments")

    __table_args__ = (
        UniqueConstraint("payment_id", "invoice_id", name="uq_payment_invoice_allocation"),
        Index("ix_payment_allocations_invoice", "invoice_id"),
        CheckConstraint("amount_cents > 0", name="ck_payment_allocations_amount"),
    )


class ExpenseCategory(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, Base):
    __tablename__ = "expense_categories"

    code: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_expense_categories_org_code"),
    )


class Expense(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, SoftDeleteMixin, Base):
    __tablename__ = "expenses"

    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    vehicle_id: Mapped[str | None] = mapped_column(ForeignKey("vehicles.id", ondelete="SET NULL"))
    supplier_id: Mapped[str | None] = mapped_column(ForeignKey("suppliers.id", ondelete="SET NULL"))
    category_id: Mapped[str] = mapped_column(
        ForeignKey("expense_categories.id", ondelete="RESTRICT"), nullable=False
    )
    expense_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    tax_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reimbursable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reimbursement_status: Mapped[str | None] = mapped_column(String(30))
    vendor_name: Mapped[str | None] = mapped_column(String(200))
    payment_method: Mapped[str | None] = mapped_column(String(40))
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    job: Mapped[Job | None] = relationship(back_populates="expenses")
    category: Mapped[ExpenseCategory] = relationship()

    __table_args__ = (
        Index("ix_expenses_org_date", "organization_id", "expense_date"),
        Index("ix_expenses_job", "job_id"),
        Index("ix_expenses_vehicle", "vehicle_id"),
        CheckConstraint("amount_cents >= 0", name="ck_expenses_amount"),
        CheckConstraint("tax_cents >= 0", name="ck_expenses_tax"),
    )


class MaintenanceRecord(
    UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, SoftDeleteMixin, Base
):
    __tablename__ = "maintenance_records"

    vehicle_id: Mapped[str] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False
    )
    maintenance_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="scheduled", nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    due_odometer_miles: Mapped[Decimal | None] = mapped_column(Numeric(12, 1))
    completed_date: Mapped[date | None] = mapped_column(Date)
    completed_odometer_miles: Mapped[Decimal | None] = mapped_column(Numeric(12, 1))
    service_vendor: Mapped[str | None] = mapped_column(String(200))
    cost_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    next_due_date: Mapped[date | None] = mapped_column(Date)
    next_due_odometer_miles: Mapped[Decimal | None] = mapped_column(Numeric(12, 1))

    vehicle: Mapped[Vehicle] = relationship(back_populates="maintenance_records")

    __table_args__ = (
        Index("ix_maintenance_vehicle_due", "vehicle_id", "status", "due_date"),
        Index("ix_maintenance_org_due", "organization_id", "status", "due_date"),
        CheckConstraint("cost_cents >= 0", name="ck_maintenance_cost"),
    )


class FuelEntry(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, Base):
    __tablename__ = "fuel_entries"

    vehicle_id: Mapped[str] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False
    )
    driver_id: Mapped[str | None] = mapped_column(ForeignKey("drivers.id", ondelete="SET NULL"))
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    purchased_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    odometer_miles: Mapped[Decimal] = mapped_column(Numeric(12, 1), nullable=False)
    gallons: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    price_per_gallon_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    total_cost_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    calculated_mpg: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    vendor_name: Mapped[str | None] = mapped_column(String(200))
    is_full_tank: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    vehicle: Mapped[Vehicle] = relationship(back_populates="fuel_entries")

    __table_args__ = (
        Index("ix_fuel_vehicle_purchased", "vehicle_id", "purchased_at"),
        CheckConstraint("odometer_miles >= 0", name="ck_fuel_odometer"),
        CheckConstraint("gallons > 0", name="ck_fuel_gallons"),
        CheckConstraint("price_per_gallon_cents >= 0", name="ck_fuel_price"),
        CheckConstraint("total_cost_cents >= 0", name="ck_fuel_total"),
    )


class Document(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, SoftDeleteMixin, Base):
    __tablename__ = "documents"

    document_type: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_provider: Mapped[str] = mapped_column(String(50), default="local", nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1000), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(150), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    retention_class: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), default=DocumentStatus.ACTIVE.value, nullable=False
    )
    uploader_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scan_result: Mapped[str | None] = mapped_column(String(50))
    thumbnail_storage_key: Mapped[str | None] = mapped_column(String(1000))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    links: Mapped[list[DocumentLink]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    signature: Mapped[Signature | None] = relationship(
        back_populates="document", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "checksum_sha256", "storage_key", name="uq_document_storage"
        ),
        Index("ix_documents_org_type_created", "organization_id", "document_type", "created_at"),
        Index("ix_documents_checksum", "checksum_sha256"),
        CheckConstraint("size_bytes >= 0", name="ck_documents_size"),
    )


class DocumentLink(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, Base):
    __tablename__ = "document_links"

    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    relationship_type: Mapped[str] = mapped_column(String(60), nullable=False)

    document: Mapped[Document] = relationship(back_populates="links")

    __table_args__ = (
        UniqueConstraint(
            "document_id", "entity_type", "entity_id", "relationship_type", name="uq_document_link"
        ),
        Index("ix_document_links_entity", "entity_type", "entity_id"),
    )


class Signature(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, Base):
    __tablename__ = "signatures"

    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    signer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    signer_role: Mapped[str | None] = mapped_column(String(120))
    signed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    statement_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    device_id: Mapped[str | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))

    document: Mapped[Document] = relationship(back_populates="signature")

    __table_args__ = (Index("ix_signatures_job_signed", "job_id", "signed_at"),)


class GeofenceVersion(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, Base):
    __tablename__ = "geofence_versions"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    version_code: Mapped[str] = mapped_column(String(40), nullable=False)
    source: Mapped[str] = mapped_column(String(300), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    geojson: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (
        UniqueConstraint("organization_id", "version_code", name="uq_geofence_org_version"),
        Index("ix_geofence_org_active", "organization_id", "active"),
    )


class RouteSnapshot(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, Base):
    __tablename__ = "route_snapshots"

    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    quote_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("quote_revisions.id", ondelete="CASCADE")
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_route_id: Mapped[str | None] = mapped_column(String(200))
    request_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    route_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    total_miles: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    chargeable_miles: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    tolls_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    traffic_basis: Mapped[str | None] = mapped_column(String(50))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_routes_request_hash", "request_hash"),
        Index("ix_routes_job", "job_id"),
        CheckConstraint("total_miles >= 0", name="ck_routes_total_miles"),
        CheckConstraint("chargeable_miles >= 0", name="ck_routes_chargeable_miles"),
        CheckConstraint("duration_seconds >= 0", name="ck_routes_duration"),
    )


class Communication(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, Base):
    __tablename__ = "communications"

    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.id", ondelete="SET NULL"))
    contact_id: Mapped[str | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"))
    quote_id: Mapped[str | None] = mapped_column(ForeignKey("quotes.id", ondelete="SET NULL"))
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    invoice_id: Mapped[str | None] = mapped_column(ForeignKey("invoices.id", ondelete="SET NULL"))
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    template_code: Mapped[str | None] = mapped_column(String(80))
    subject: Mapped[str | None] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str | None] = mapped_column(String(50))
    provider_message_id: Mapped[str | None] = mapped_column(String(200))
    provider_status: Mapped[str | None] = mapped_column(String(50))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    transactional: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (
        Index("ix_communications_customer_created", "customer_id", "created_at"),
        Index("ix_communications_job_created", "job_id", "created_at"),
        Index("ix_communications_provider_id", "provider", "provider_message_id"),
    )


class NumberSequence(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, Base):
    __tablename__ = "number_sequences"

    sequence_code: Mapped[str] = mapped_column(String(60), nullable=False)
    prefix: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    next_value: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    padding: Mapped[int] = mapped_column(Integer, default=4, nullable=False)

    __table_args__ = (
        UniqueConstraint("organization_id", "sequence_code", name="uq_number_sequences_org_code"),
        CheckConstraint("next_value >= 1", name="ck_number_sequences_next"),
        CheckConstraint("padding >= 1 AND padding <= 12", name="ck_number_sequences_padding"),
    )


class SyncQueueItem(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, Base):
    __tablename__ = "sync_queue"

    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    operation: Mapped[str] = mapped_column(String(30), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    base_version: Mapped[int | None] = mapped_column(Integer)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key", name="uq_sync_org_idempotency"),
        Index("ix_sync_pending", "organization_id", "completed_at", "next_attempt_at"),
        Index("ix_sync_entity", "entity_type", "entity_id"),
    )


class SyncConflict(UUIDPrimaryKeyMixin, OrganizationScopedMixin, AuditMixin, Base):
    __tablename__ = "sync_conflicts"

    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    local_version: Mapped[int] = mapped_column(Integer, nullable=False)
    remote_version: Mapped[int] = mapped_column(Integer, nullable=False)
    local_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    remote_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="open", nullable=False)
    resolved_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    resolution_reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_sync_conflicts_open", "organization_id", "status", "created_at"),
        Index("ix_sync_conflicts_entity", "entity_type", "entity_id"),
    )
