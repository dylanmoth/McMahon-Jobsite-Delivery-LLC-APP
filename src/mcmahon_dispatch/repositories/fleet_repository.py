from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from mcmahon_dispatch.database.models import FuelEntry, MaintenanceRecord, Vehicle


@dataclass(frozen=True, slots=True)
class VehicleRecord:
    id: str
    vehicle_number: str
    year: int
    make: str
    model: str
    trim: str
    ownership_type: str
    status: str
    odometer_miles: Decimal
    estimated_mpg: Decimal | None
    cost_per_mile_cents: int | None
    registration_expires_on: date | None
    insurance_expires_on: date | None
    dimensions_verified: bool
    payload_verified: bool
    active: bool
    notes: str

    @property
    def display_name(self) -> str:
        return f"{self.vehicle_number} · {self.year} {self.make} {self.model}".strip()


@dataclass(frozen=True, slots=True)
class MaintenanceRecordView:
    id: str
    vehicle_id: str
    vehicle_name: str
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
class FuelRecord:
    id: str
    vehicle_id: str
    vehicle_name: str
    purchased_at: datetime
    odometer_miles: Decimal
    gallons: Decimal
    price_per_gallon_cents: int
    total_cost_cents: int
    calculated_mpg: Decimal | None
    vendor_name: str
    is_full_tank: bool


@dataclass(frozen=True, slots=True)
class FleetSummary:
    vehicle_count: int
    available_count: int
    maintenance_due_count: int
    expired_document_count: int
    fuel_cost_cents: int
    maintenance_cost_cents: int
    total_miles: Decimal
    average_mpg: Decimal | None
    blended_cost_per_mile_cents: int | None


class FleetRepository:
    def __init__(self, session: Session, organization_id: str) -> None:
        self.session = session
        self.organization_id = organization_id

    def list_vehicles(self, query: str = "", include_inactive: bool = False) -> list[VehicleRecord]:
        stmt = select(Vehicle).where(
            Vehicle.organization_id == self.organization_id,
            Vehicle.deleted_at.is_(None),
        )
        if not include_inactive:
            stmt = stmt.where(Vehicle.active.is_(True), Vehicle.status != "inactive")
        if query.strip():
            like = f"%{query.strip()}%"
            stmt = stmt.where(
                or_(
                    Vehicle.vehicle_number.ilike(like),
                    Vehicle.make.ilike(like),
                    Vehicle.model.ilike(like),
                    Vehicle.trim.ilike(like),
                    Vehicle.notes.ilike(like),
                )
            )
        vehicles = self.session.scalars(stmt.order_by(Vehicle.vehicle_number)).all()
        return [self._vehicle_record(vehicle) for vehicle in vehicles]

    def get_vehicle(self, vehicle_id: str) -> VehicleRecord | None:
        vehicle = self.session.scalar(
            select(Vehicle).where(
                Vehicle.id == vehicle_id,
                Vehicle.organization_id == self.organization_id,
                Vehicle.deleted_at.is_(None),
            )
        )
        return self._vehicle_record(vehicle) if vehicle else None

    def add_vehicle(self, vehicle: Vehicle) -> None:
        self.session.add(vehicle)

    def list_maintenance(self, vehicle_id: str | None = None) -> list[MaintenanceRecordView]:
        stmt = (
            select(MaintenanceRecord, Vehicle)
            .join(Vehicle, MaintenanceRecord.vehicle_id == Vehicle.id)
            .where(
                MaintenanceRecord.organization_id == self.organization_id,
                MaintenanceRecord.deleted_at.is_(None),
                Vehicle.deleted_at.is_(None),
            )
        )
        if vehicle_id:
            stmt = stmt.where(MaintenanceRecord.vehicle_id == vehicle_id)
        rows = self.session.execute(
            stmt.order_by(
                case(
                    (MaintenanceRecord.status == "overdue", 0),
                    (MaintenanceRecord.status == "scheduled", 1),
                    else_=2,
                ),
                MaintenanceRecord.due_date.is_(None),
                MaintenanceRecord.due_date,
                MaintenanceRecord.created_at.desc(),
            )
        ).all()
        return [
            MaintenanceRecordView(
                id=str(record.id),
                vehicle_id=str(record.vehicle_id),
                vehicle_name=f"{vehicle.vehicle_number} · {vehicle.year} {vehicle.make} {vehicle.model}",
                maintenance_type=record.maintenance_type,
                status=record.status,
                due_date=record.due_date,
                due_odometer_miles=record.due_odometer_miles,
                completed_date=record.completed_date,
                completed_odometer_miles=record.completed_odometer_miles,
                service_vendor=record.service_vendor or "",
                cost_cents=record.cost_cents,
                description=record.description,
                notes=record.notes,
                next_due_date=record.next_due_date,
                next_due_odometer_miles=record.next_due_odometer_miles,
            )
            for record, vehicle in rows
        ]

    def list_fuel(self, vehicle_id: str | None = None, limit: int = 1000) -> list[FuelRecord]:
        stmt = (
            select(FuelEntry, Vehicle)
            .join(Vehicle, FuelEntry.vehicle_id == Vehicle.id)
            .where(
                FuelEntry.organization_id == self.organization_id,
                Vehicle.deleted_at.is_(None),
            )
        )
        if vehicle_id:
            stmt = stmt.where(FuelEntry.vehicle_id == vehicle_id)
        rows = self.session.execute(stmt.order_by(FuelEntry.purchased_at.desc()).limit(limit)).all()
        return [
            FuelRecord(
                id=str(entry.id),
                vehicle_id=str(entry.vehicle_id),
                vehicle_name=f"{vehicle.vehicle_number} · {vehicle.year} {vehicle.make} {vehicle.model}",
                purchased_at=entry.purchased_at,
                odometer_miles=entry.odometer_miles,
                gallons=entry.gallons,
                price_per_gallon_cents=entry.price_per_gallon_cents,
                total_cost_cents=entry.total_cost_cents,
                calculated_mpg=entry.calculated_mpg,
                vendor_name=entry.vendor_name or "",
                is_full_tank=entry.is_full_tank,
            )
            for entry, vehicle in rows
        ]

    def summary(self, as_of: date) -> FleetSummary:
        vehicles = self.session.scalars(
            select(Vehicle).where(
                Vehicle.organization_id == self.organization_id,
                Vehicle.deleted_at.is_(None),
                Vehicle.active.is_(True),
            )
        ).all()
        maintenance = self.session.scalars(
            select(MaintenanceRecord).where(
                MaintenanceRecord.organization_id == self.organization_id,
                MaintenanceRecord.deleted_at.is_(None),
            )
        ).all()
        fuel_rows = self.session.execute(
            select(
                func.coalesce(func.sum(FuelEntry.total_cost_cents), 0),
                func.avg(FuelEntry.calculated_mpg),
            ).where(FuelEntry.organization_id == self.organization_id)
        ).one()
        maintenance_cost = int(
            self.session.scalar(
                select(func.coalesce(func.sum(MaintenanceRecord.cost_cents), 0)).where(
                    MaintenanceRecord.organization_id == self.organization_id,
                    MaintenanceRecord.deleted_at.is_(None),
                )
            )
            or 0
        )
        total_miles = sum((vehicle.odometer_miles for vehicle in vehicles), Decimal("0"))
        total_cost = int(fuel_rows[0] or 0) + maintenance_cost
        blended = round(total_cost / float(total_miles)) if total_miles > 0 else None
        due_count = sum(
            1
            for record in maintenance
            if record.status in {"scheduled", "overdue"}
            and (
                (record.due_date is not None and record.due_date <= as_of)
                or any(
                    vehicle.id == record.vehicle_id
                    and record.due_odometer_miles is not None
                    and vehicle.odometer_miles >= record.due_odometer_miles
                    for vehicle in vehicles
                )
            )
        )
        expired_docs = sum(
            int(
                vehicle.registration_expires_on is not None
                and vehicle.registration_expires_on < as_of
            )
            + int(vehicle.insurance_expires_on is not None and vehicle.insurance_expires_on < as_of)
            for vehicle in vehicles
        )
        avg_mpg = (
            Decimal(str(fuel_rows[1])).quantize(Decimal("0.01"))
            if fuel_rows[1] is not None
            else None
        )
        return FleetSummary(
            vehicle_count=len(vehicles),
            available_count=sum(vehicle.status == "available" for vehicle in vehicles),
            maintenance_due_count=due_count,
            expired_document_count=expired_docs,
            fuel_cost_cents=int(fuel_rows[0] or 0),
            maintenance_cost_cents=maintenance_cost,
            total_miles=total_miles,
            average_mpg=avg_mpg,
            blended_cost_per_mile_cents=blended,
        )

    @staticmethod
    def _vehicle_record(vehicle: Vehicle) -> VehicleRecord:
        return VehicleRecord(
            id=str(vehicle.id),
            vehicle_number=vehicle.vehicle_number,
            year=vehicle.year,
            make=vehicle.make,
            model=vehicle.model,
            trim=vehicle.trim or "",
            ownership_type=vehicle.ownership_type,
            status=vehicle.status,
            odometer_miles=vehicle.odometer_miles,
            estimated_mpg=vehicle.estimated_mpg,
            cost_per_mile_cents=vehicle.cost_per_mile_cents,
            registration_expires_on=vehicle.registration_expires_on,
            insurance_expires_on=vehicle.insurance_expires_on,
            dimensions_verified=vehicle.dimensions_verified,
            payload_verified=vehicle.payload_verified,
            active=vehicle.active,
            notes=vehicle.notes,
        )
