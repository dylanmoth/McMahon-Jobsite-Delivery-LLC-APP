from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from mcmahon_dispatch.core.exceptions import ValidationError
from mcmahon_dispatch.database.models import AuditEvent, FuelEntry, MaintenanceRecord, Vehicle
from mcmahon_dispatch.repositories.fleet_repository import (
    FleetRepository,
    FleetSummary,
    FuelRecord,
    MaintenanceRecordView,
    VehicleRecord,
)


@dataclass(frozen=True, slots=True)
class VehicleSaveRequest:
    vehicle_number: str
    year: int
    make: str
    model: str
    trim: str = ""
    ownership_type: str = "owned"
    status: str = "available"
    odometer_miles: Decimal = Decimal("0")
    estimated_mpg: Decimal | None = None
    cost_per_mile_cents: int | None = None
    registration_expires_on: date | None = None
    insurance_expires_on: date | None = None
    cargo_length_inches: Decimal | None = None
    cargo_width_inches: Decimal | None = None
    cargo_height_inches: Decimal | None = None
    payload_pounds: Decimal | None = None
    dimensions_verified: bool = False
    payload_verified: bool = False
    notes: str = ""


@dataclass(frozen=True, slots=True)
class MaintenanceSaveRequest:
    vehicle_id: str
    maintenance_type: str
    status: str
    due_date: date | None
    due_odometer_miles: Decimal | None
    completed_date: date | None
    completed_odometer_miles: Decimal | None
    service_vendor: str
    cost_cents: int
    description: str
    notes: str
    next_due_date: date | None
    next_due_odometer_miles: Decimal | None


@dataclass(frozen=True, slots=True)
class FuelSaveRequest:
    vehicle_id: str
    purchased_at: datetime
    odometer_miles: Decimal
    gallons: Decimal
    price_per_gallon_cents: int
    total_cost_cents: int
    vendor_name: str
    is_full_tank: bool


class FleetService:
    def __init__(
        self,
        factory: sessionmaker[Session],
        organization_id: str,
        user_id: str,
        *,
        can_write: bool,
    ) -> None:
        self.factory = factory
        self.organization_id = organization_id
        self.user_id = user_id
        self.can_write = can_write

    def list_vehicles(self, query: str = "", include_inactive: bool = False) -> list[VehicleRecord]:
        with self.factory() as session:
            return FleetRepository(session, self.organization_id).list_vehicles(query, include_inactive)

    def vehicle(self, vehicle_id: str) -> VehicleRecord:
        with self.factory() as session:
            record = FleetRepository(session, self.organization_id).get_vehicle(vehicle_id)
            if record is None:
                raise ValidationError("Vehicle not found.")
            return record

    def save_vehicle(self, request: VehicleSaveRequest, vehicle_id: str | None = None) -> str:
        self._require_write()
        self._validate_vehicle(request)
        with self.factory.begin() as session:
            duplicate = session.scalar(
                select(Vehicle.id).where(
                    Vehicle.organization_id == self.organization_id,
                    Vehicle.vehicle_number == request.vehicle_number.strip(),
                    Vehicle.deleted_at.is_(None),
                    Vehicle.id != (vehicle_id or ""),
                )
            )
            if duplicate:
                raise ValidationError("Vehicle number already exists.")
            if vehicle_id:
                vehicle = self._vehicle_entity(session, vehicle_id)
            else:
                vehicle = Vehicle(organization_id=self.organization_id, created_by_id=self.user_id)
                session.add(vehicle)
            vehicle.vehicle_number = request.vehicle_number.strip()
            vehicle.year = request.year
            vehicle.make = request.make.strip()
            vehicle.model = request.model.strip()
            vehicle.trim = request.trim.strip() or None
            vehicle.ownership_type = request.ownership_type
            vehicle.status = request.status
            vehicle.odometer_miles = request.odometer_miles
            vehicle.estimated_mpg = request.estimated_mpg
            vehicle.cost_per_mile_cents = request.cost_per_mile_cents
            vehicle.registration_expires_on = request.registration_expires_on
            vehicle.insurance_expires_on = request.insurance_expires_on
            vehicle.cargo_length_inches = request.cargo_length_inches
            vehicle.cargo_width_inches = request.cargo_width_inches
            vehicle.cargo_height_inches = request.cargo_height_inches
            vehicle.payload_pounds = request.payload_pounds
            vehicle.dimensions_verified = request.dimensions_verified
            vehicle.payload_verified = request.payload_verified
            vehicle.notes = request.notes.strip()
            vehicle.active = request.status != "inactive"
            vehicle.updated_by_id = self.user_id
            session.flush()
            self._audit(session, "vehicle.updated" if vehicle_id else "vehicle.created", "vehicle", str(vehicle.id))
            return str(vehicle.id)

    def archive_vehicle(self, vehicle_id: str) -> None:
        self._require_write()
        with self.factory.begin() as session:
            vehicle = self._vehicle_entity(session, vehicle_id)
            vehicle.active = False
            vehicle.status = "inactive"
            vehicle.updated_by_id = self.user_id
            self._audit(session, "vehicle.archived", "vehicle", vehicle_id)

    def list_maintenance(self, vehicle_id: str | None = None) -> list[MaintenanceRecordView]:
        with self.factory() as session:
            return FleetRepository(session, self.organization_id).list_maintenance(vehicle_id)

    def save_maintenance(self, request: MaintenanceSaveRequest, record_id: str | None = None) -> str:
        self._require_write()
        if not request.maintenance_type.strip():
            raise ValidationError("Maintenance type is required.")
        if request.cost_cents < 0:
            raise ValidationError("Maintenance cost cannot be negative.")
        with self.factory.begin() as session:
            vehicle = self._vehicle_entity(session, request.vehicle_id)
            if record_id:
                record = session.scalar(
                    select(MaintenanceRecord).where(
                        MaintenanceRecord.id == record_id,
                        MaintenanceRecord.organization_id == self.organization_id,
                        MaintenanceRecord.deleted_at.is_(None),
                    )
                )
                if record is None:
                    raise ValidationError("Maintenance record not found.")
            else:
                record = MaintenanceRecord(
                    organization_id=self.organization_id,
                    vehicle_id=request.vehicle_id,
                    created_by_id=self.user_id,
                )
                session.add(record)
            record.vehicle_id = request.vehicle_id
            record.maintenance_type = request.maintenance_type.strip()
            record.status = request.status
            record.due_date = request.due_date
            record.due_odometer_miles = request.due_odometer_miles
            record.completed_date = request.completed_date
            record.completed_odometer_miles = request.completed_odometer_miles
            record.service_vendor = request.service_vendor.strip() or None
            record.cost_cents = request.cost_cents
            record.description = request.description.strip()
            record.notes = request.notes.strip()
            record.next_due_date = request.next_due_date
            record.next_due_odometer_miles = request.next_due_odometer_miles
            if request.status == "completed" and request.completed_odometer_miles is not None:
                vehicle.odometer_miles = max(vehicle.odometer_miles, request.completed_odometer_miles)
                vehicle.updated_by_id = self.user_id
            record.updated_by_id = self.user_id
            session.flush()
            self._audit(session, "maintenance.updated" if record_id else "maintenance.created", "maintenance_record", str(record.id))
            return str(record.id)

    def list_fuel(self, vehicle_id: str | None = None) -> list[FuelRecord]:
        with self.factory() as session:
            return FleetRepository(session, self.organization_id).list_fuel(vehicle_id)

    def save_fuel(self, request: FuelSaveRequest) -> str:
        self._require_write()
        if request.gallons <= 0:
            raise ValidationError("Gallons must be greater than zero.")
        if request.odometer_miles < 0 or request.price_per_gallon_cents < 0 or request.total_cost_cents < 0:
            raise ValidationError("Fuel values cannot be negative.")
        with self.factory.begin() as session:
            vehicle = self._vehicle_entity(session, request.vehicle_id)
            previous = session.scalar(
                select(FuelEntry)
                .where(
                    FuelEntry.organization_id == self.organization_id,
                    FuelEntry.vehicle_id == request.vehicle_id,
                    FuelEntry.is_full_tank.is_(True),
                    FuelEntry.odometer_miles < request.odometer_miles,
                )
                .order_by(FuelEntry.odometer_miles.desc())
                .limit(1)
            )
            calculated_mpg = None
            if request.is_full_tank and previous is not None:
                miles = request.odometer_miles - previous.odometer_miles
                if miles > 0:
                    calculated_mpg = (miles / request.gallons).quantize(Decimal("0.01"))
            entry = FuelEntry(
                organization_id=self.organization_id,
                vehicle_id=request.vehicle_id,
                purchased_at=request.purchased_at.astimezone(UTC),
                odometer_miles=request.odometer_miles,
                gallons=request.gallons,
                price_per_gallon_cents=request.price_per_gallon_cents,
                total_cost_cents=request.total_cost_cents,
                calculated_mpg=calculated_mpg,
                vendor_name=request.vendor_name.strip() or None,
                is_full_tank=request.is_full_tank,
                created_by_id=self.user_id,
                updated_by_id=self.user_id,
            )
            session.add(entry)
            vehicle.odometer_miles = max(vehicle.odometer_miles, request.odometer_miles)
            vehicle.updated_by_id = self.user_id
            session.flush()
            self._audit(session, "fuel.created", "fuel_entry", str(entry.id))
            return str(entry.id)

    def summary(self) -> FleetSummary:
        with self.factory() as session:
            return FleetRepository(session, self.organization_id).summary(date.today())

    def _vehicle_entity(self, session: Session, vehicle_id: str) -> Vehicle:
        vehicle = session.scalar(
            select(Vehicle).where(
                Vehicle.id == vehicle_id,
                Vehicle.organization_id == self.organization_id,
                Vehicle.deleted_at.is_(None),
            )
        )
        if vehicle is None:
            raise ValidationError("Vehicle not found.")
        return vehicle

    def _validate_vehicle(self, request: VehicleSaveRequest) -> None:
        if not request.vehicle_number.strip():
            raise ValidationError("Vehicle number is required.")
        if not request.make.strip() or not request.model.strip():
            raise ValidationError("Vehicle make and model are required.")
        if request.year < 1900 or request.year > 2200:
            raise ValidationError("Vehicle year is invalid.")
        if request.odometer_miles < 0:
            raise ValidationError("Odometer cannot be negative.")
        if request.cost_per_mile_cents is not None and request.cost_per_mile_cents < 0:
            raise ValidationError("Cost per mile cannot be negative.")

    def _require_write(self) -> None:
        if not self.can_write:
            raise ValidationError("Your account does not have permission to change fleet records.")

    def _audit(self, session: Session, action: str, entity_type: str, entity_id: str) -> None:
        session.add(
            AuditEvent(
                organization_id=self.organization_id,
                user_id=self.user_id,
                event_type=action,
                entity_type=entity_type,
                entity_id=entity_id,
                occurred_at=datetime.now(UTC),
                details_json={},
            )
        )
