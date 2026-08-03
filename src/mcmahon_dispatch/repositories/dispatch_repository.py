from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from mcmahon_dispatch.database.models import (
    AuditEvent,
    Customer,
    Driver,
    Job,
    JobAssignment,
    JobStatusEvent,
    JobStop,
    Vehicle,
    WaitEvent,
)


@dataclass(frozen=True, slots=True)
class Choice:
    id: str
    label: str
    status: str = ""


@dataclass(frozen=True, slots=True)
class AssignmentSummary:
    id: str
    driver_id: str
    driver_name: str
    driver_status: str
    vehicle_id: str
    vehicle_name: str
    vehicle_status: str
    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True, slots=True)
class DispatchJobRecord:
    id: str
    job_number: str
    customer_id: str | None
    customer_name: str
    status: str
    priority: str
    service_type: str
    requested_window_start: datetime | None
    requested_window_end: datetime | None
    promised_pickup_at: datetime | None
    promised_delivery_at: datetime | None
    planned_miles: Decimal | None
    planned_minutes: int | None
    quoted_revenue_cents: int
    estimated_cost_cents: int
    pickup_address: str
    pickup_order_number: str
    pickup_instructions: str
    delivery_address: str
    delivery_instructions: str
    internal_notes: str
    dispatch_notes: str
    cancellation_reason: str | None
    assignment: AssignmentSummary | None
    last_assignment: AssignmentSummary | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class DriverRecord:
    id: str
    driver_number: str
    first_name: str
    last_name: str
    phone: str
    email: str
    status: str
    license_state: str
    license_expiration: object | None
    notes: str

    @property
    def display_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


@dataclass(frozen=True, slots=True)
class VehicleRecord:
    id: str
    vehicle_number: str
    year: int
    make: str
    model: str
    trim: str
    status: str
    cargo_length_inches: Decimal | None
    cargo_width_inches: Decimal | None
    cargo_height_inches: Decimal | None
    payload_pounds: Decimal | None
    cost_per_mile_cents: int | None
    registration_expires_on: object | None
    insurance_expires_on: object | None
    notes: str

    @property
    def display_name(self) -> str:
        vehicle = f"{self.year} {self.make} {self.model}".strip()
        return f"{self.vehicle_number} · {vehicle}"


@dataclass(frozen=True, slots=True)
class StatusEventRecord:
    id: str
    from_status: str | None
    to_status: str
    occurred_at: datetime
    note: str
    override_reason: str


class DispatchRepository:
    def __init__(self, session: Session, organization_id: str) -> None:
        self.session = session
        self.organization_id = organization_id

    def customer_choices(self) -> list[Choice]:
        rows = self.session.execute(
            select(Customer.id, Customer.company_name, Customer.status)
            .where(
                Customer.organization_id == self.organization_id,
                Customer.deleted_at.is_(None),
                Customer.status != "archived",
            )
            .order_by(Customer.company_name.asc())
        ).all()
        return [Choice(str(row.id), str(row.company_name), str(row.status)) for row in rows]

    def driver_choices(self, *, include_inactive: bool = False) -> list[Choice]:
        stmt = select(Driver.id, Driver.first_name, Driver.last_name, Driver.status).where(
            Driver.organization_id == self.organization_id,
            Driver.deleted_at.is_(None),
        )
        if not include_inactive:
            stmt = stmt.where(Driver.status != "inactive")
        rows = self.session.execute(stmt.order_by(Driver.last_name, Driver.first_name)).all()
        return [
            Choice(str(row.id), f"{row.first_name} {row.last_name}".strip(), str(row.status))
            for row in rows
        ]

    def vehicle_choices(self, *, include_inactive: bool = False) -> list[Choice]:
        stmt = select(
            Vehicle.id,
            Vehicle.vehicle_number,
            Vehicle.year,
            Vehicle.make,
            Vehicle.model,
            Vehicle.status,
        ).where(
            Vehicle.organization_id == self.organization_id,
            Vehicle.deleted_at.is_(None),
        )
        if not include_inactive:
            stmt = stmt.where(Vehicle.status != "inactive", Vehicle.active.is_(True))
        rows = self.session.execute(stmt.order_by(Vehicle.vehicle_number)).all()
        return [
            Choice(
                str(row.id),
                f"{row.vehicle_number} · {row.year} {row.make} {row.model}",
                str(row.status),
            )
            for row in rows
        ]

    def list_jobs(
        self,
        *,
        statuses: Iterable[str] | None = None,
        query: str = "",
        starts_before: datetime | None = None,
        ends_after: datetime | None = None,
        driver_id: str | None = None,
        limit: int = 1000,
    ) -> list[DispatchJobRecord]:
        stmt = (
            select(Job)
            .where(
                Job.organization_id == self.organization_id,
                Job.deleted_at.is_(None),
            )
            .options(
                selectinload(Job.customer),
                selectinload(Job.stops),
                selectinload(Job.assignments).selectinload(JobAssignment.driver),
                selectinload(Job.assignments).selectinload(JobAssignment.vehicle),
            )
            .order_by(
                Job.requested_window_start.is_(None),
                Job.requested_window_start.asc(),
                Job.priority.desc(),
                Job.job_number.asc(),
            )
            .limit(limit)
        )
        status_values = tuple(statuses or ())
        if status_values:
            stmt = stmt.where(Job.status.in_(status_values))
        normalized = query.strip()
        if normalized:
            like = f"%{normalized}%"
            matching_customers = select(Customer.id).where(
                Customer.organization_id == self.organization_id,
                or_(
                    Customer.company_name.ilike(like),
                    Customer.customer_number.ilike(like),
                    Customer.primary_phone.ilike(like),
                ),
            )
            stmt = stmt.where(
                or_(
                    Job.job_number.ilike(like),
                    Job.service_type.ilike(like),
                    Job.internal_notes.ilike(like),
                    Job.dispatch_notes.ilike(like),
                    Job.customer_id.in_(matching_customers),
                )
            )
        if starts_before is not None:
            stmt = stmt.where(
                or_(
                    Job.requested_window_start.is_(None),
                    Job.requested_window_start < starts_before,
                )
            )
        if ends_after is not None:
            stmt = stmt.where(
                or_(
                    Job.requested_window_end.is_(None),
                    Job.requested_window_end > ends_after,
                )
            )
        if driver_id:
            assigned_job_ids = select(JobAssignment.job_id).where(
                JobAssignment.organization_id == self.organization_id,
                JobAssignment.driver_id == driver_id,
                JobAssignment.unassigned_at.is_(None),
            )
            stmt = stmt.where(Job.id.in_(assigned_job_ids))
        return [self._job_record(job) for job in self.session.scalars(stmt).unique()]

    def get_job(self, job_id: str) -> DispatchJobRecord | None:
        stmt = (
            select(Job)
            .where(
                Job.id == job_id,
                Job.organization_id == self.organization_id,
                Job.deleted_at.is_(None),
            )
            .options(
                selectinload(Job.customer),
                selectinload(Job.stops),
                selectinload(Job.assignments).selectinload(JobAssignment.driver),
                selectinload(Job.assignments).selectinload(JobAssignment.vehicle),
            )
        )
        job = self.session.scalar(stmt)
        return self._job_record(job) if job is not None else None

    def get_job_model(self, job_id: str) -> Job | None:
        return self.session.scalar(
            select(Job).where(
                Job.id == job_id,
                Job.organization_id == self.organization_id,
                Job.deleted_at.is_(None),
            )
        )

    def next_job_number(self) -> str:
        values = self.session.scalars(
            select(Job.job_number).where(Job.organization_id == self.organization_id)
        ).all()
        highest = 0
        for value in values:
            digits = "".join(character for character in value if character.isdigit())
            if digits:
                highest = max(highest, int(digits))
        return f"MJD-JOB-{highest + 1:05d}"

    def create_job(self, values: dict[str, Any]) -> Job:
        job = Job(
            organization_id=self.organization_id,
            job_number=self.next_job_number(),
            **values,
        )
        self.session.add(job)
        self.session.flush()
        return job

    def replace_stops(
        self,
        job: Job,
        pickup: dict[str, Any],
        delivery: dict[str, Any],
    ) -> None:
        self.session.execute(
            JobStop.__table__.delete().where(JobStop.job_id == job.id)
        )
        for sequence, stop_type, values in (
            (1, "pickup", pickup),
            (2, "delivery", delivery),
        ):
            self.session.add(
                JobStop(
                    organization_id=self.organization_id,
                    job_id=job.id,
                    sequence=sequence,
                    stop_type=stop_type,
                    address_snapshot_json={
                        "entered_address": values.get("address", ""),
                        "label": values.get("label", ""),
                    },
                    instructions_snapshot=values.get("instructions", ""),
                    planned_arrival_at=values.get("planned_arrival_at"),
                    service_minutes=max(0, int(values.get("service_minutes", 0))),
                    order_number=values.get("order_number") or None,
                )
            )

    def active_assignment(self, job_id: str) -> JobAssignment | None:
        return self.session.scalar(
            select(JobAssignment)
            .where(
                JobAssignment.job_id == job_id,
                JobAssignment.organization_id == self.organization_id,
                JobAssignment.unassigned_at.is_(None),
            )
            .order_by(JobAssignment.assigned_at.desc())
            .limit(1)
        )

    def assignment_conflicts(
        self,
        *,
        job_id: str,
        driver_id: str,
        vehicle_id: str,
        starts_at: datetime,
        ends_at: datetime,
    ) -> list[tuple[str, JobAssignment]]:
        stmt = (
            select(JobAssignment)
            .where(
                JobAssignment.organization_id == self.organization_id,
                JobAssignment.job_id != job_id,
                JobAssignment.unassigned_at.is_(None),
                JobAssignment.starts_at < ends_at,
                JobAssignment.ends_at > starts_at,
                or_(
                    JobAssignment.driver_id == driver_id,
                    JobAssignment.vehicle_id == vehicle_id,
                ),
            )
            .options(
                selectinload(JobAssignment.job).selectinload(Job.customer),
                selectinload(JobAssignment.driver),
                selectinload(JobAssignment.vehicle),
            )
        )
        conflicts: list[tuple[str, JobAssignment]] = []
        for assignment in self.session.scalars(stmt).unique():
            if assignment.driver_id == driver_id:
                conflicts.append(("driver", assignment))
            if assignment.vehicle_id == vehicle_id:
                conflicts.append(("vehicle", assignment))
        return conflicts

    def close_assignment(self, assignment: JobAssignment, *, at: datetime, reason: str) -> None:
        assignment.unassigned_at = at
        assignment.unassigned_reason = reason
        assignment.updated_at = at

    def driver_has_active_assignment(self, driver_id: str, *, excluding_job_id: str | None = None) -> bool:
        stmt = select(func.count(JobAssignment.id)).where(
            JobAssignment.organization_id == self.organization_id,
            JobAssignment.driver_id == driver_id,
            JobAssignment.unassigned_at.is_(None),
        )
        if excluding_job_id:
            stmt = stmt.where(JobAssignment.job_id != excluding_job_id)
        return bool(self.session.scalar(stmt) or 0)

    def vehicle_has_active_assignment(self, vehicle_id: str, *, excluding_job_id: str | None = None) -> bool:
        stmt = select(func.count(JobAssignment.id)).where(
            JobAssignment.organization_id == self.organization_id,
            JobAssignment.vehicle_id == vehicle_id,
            JobAssignment.unassigned_at.is_(None),
        )
        if excluding_job_id:
            stmt = stmt.where(JobAssignment.job_id != excluding_job_id)
        return bool(self.session.scalar(stmt) or 0)

    def create_assignment(
        self,
        *,
        job_id: str,
        driver_id: str,
        vehicle_id: str,
        user_id: str | None,
        starts_at: datetime,
        ends_at: datetime,
    ) -> JobAssignment:
        assignment = JobAssignment(
            organization_id=self.organization_id,
            job_id=job_id,
            driver_id=driver_id,
            vehicle_id=vehicle_id,
            assigned_by_id=user_id,
            starts_at=starts_at,
            ends_at=ends_at,
            is_primary=True,
            created_by_id=user_id,
            updated_by_id=user_id,
        )
        self.session.add(assignment)
        self.session.flush()
        return assignment

    def add_status_event(
        self,
        *,
        job_id: str,
        from_status: str | None,
        to_status: str,
        user_id: str | None,
        occurred_at: datetime,
        note: str,
        override_reason: str,
    ) -> JobStatusEvent:
        event = JobStatusEvent(
            organization_id=self.organization_id,
            job_id=job_id,
            from_status=from_status,
            to_status=to_status,
            user_id=user_id,
            occurred_at=occurred_at,
            note=note or None,
            override_reason=override_reason or None,
        )
        self.session.add(event)
        self.session.flush()
        return event

    def status_events(self, job_id: str) -> list[StatusEventRecord]:
        rows = self.session.scalars(
            select(JobStatusEvent)
            .where(
                JobStatusEvent.organization_id == self.organization_id,
                JobStatusEvent.job_id == job_id,
            )
            .order_by(JobStatusEvent.occurred_at.desc())
        ).all()
        return [
            StatusEventRecord(
                id=row.id,
                from_status=row.from_status,
                to_status=row.to_status,
                occurred_at=self._utc_datetime(row.occurred_at),
                note=row.note or "",
                override_reason=row.override_reason or "",
            )
            for row in rows
        ]

    def open_wait(self, job_id: str) -> WaitEvent | None:
        return self.session.scalar(
            select(WaitEvent)
            .where(
                WaitEvent.organization_id == self.organization_id,
                WaitEvent.job_id == job_id,
                WaitEvent.ended_at.is_(None),
            )
            .order_by(WaitEvent.started_at.desc())
            .limit(1)
        )

    def wait_count(self, job_id: str) -> int:
        return int(
            self.session.scalar(
                select(func.count(WaitEvent.id)).where(
                    WaitEvent.organization_id == self.organization_id,
                    WaitEvent.job_id == job_id,
                )
            )
            or 0
        )

    def create_wait(self, job_id: str, started_at: datetime, reason: str) -> WaitEvent:
        event = WaitEvent(
            organization_id=self.organization_id,
            job_id=job_id,
            started_at=started_at,
            delay_sequence=self.wait_count(job_id) + 1,
            reason=reason or None,
        )
        self.session.add(event)
        self.session.flush()
        return event

    def list_drivers(self) -> list[DriverRecord]:
        drivers = self.session.scalars(
            select(Driver)
            .where(
                Driver.organization_id == self.organization_id,
                Driver.deleted_at.is_(None),
            )
            .order_by(Driver.status, Driver.last_name, Driver.first_name)
        ).all()
        return [self._driver_record(driver) for driver in drivers]

    def get_driver(self, driver_id: str) -> Driver | None:
        return self.session.scalar(
            select(Driver).where(
                Driver.id == driver_id,
                Driver.organization_id == self.organization_id,
                Driver.deleted_at.is_(None),
            )
        )

    def next_driver_number(self) -> str:
        values = self.session.scalars(
            select(Driver.driver_number).where(Driver.organization_id == self.organization_id)
        ).all()
        highest = 0
        for value in values:
            digits = "".join(character for character in value if character.isdigit())
            if digits:
                highest = max(highest, int(digits))
        return f"DRV-{highest + 1:03d}"

    def create_driver(self, values: dict[str, Any]) -> Driver:
        driver = Driver(
            organization_id=self.organization_id,
            driver_number=self.next_driver_number(),
            **values,
        )
        self.session.add(driver)
        self.session.flush()
        return driver

    def list_vehicles(self) -> list[VehicleRecord]:
        vehicles = self.session.scalars(
            select(Vehicle)
            .where(
                Vehicle.organization_id == self.organization_id,
                Vehicle.deleted_at.is_(None),
            )
            .order_by(Vehicle.status, Vehicle.vehicle_number)
        ).all()
        return [self._vehicle_record(vehicle) for vehicle in vehicles]

    def get_vehicle(self, vehicle_id: str) -> Vehicle | None:
        return self.session.scalar(
            select(Vehicle).where(
                Vehicle.id == vehicle_id,
                Vehicle.organization_id == self.organization_id,
                Vehicle.deleted_at.is_(None),
            )
        )

    def next_vehicle_number(self) -> str:
        values = self.session.scalars(
            select(Vehicle.vehicle_number).where(Vehicle.organization_id == self.organization_id)
        ).all()
        highest = 0
        for value in values:
            digits = "".join(character for character in value if character.isdigit())
            if digits:
                highest = max(highest, int(digits))
        return f"VEH-{highest + 1:03d}"

    def create_vehicle(self, values: dict[str, Any]) -> Vehicle:
        vehicle = Vehicle(
            organization_id=self.organization_id,
            vehicle_number=self.next_vehicle_number(),
            **values,
        )
        self.session.add(vehicle)
        self.session.flush()
        return vehicle

    def audit(
        self,
        *,
        user_id: str | None,
        event_type: str,
        entity_type: str,
        entity_id: str,
        reason: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        self.session.add(
            AuditEvent(
                organization_id=self.organization_id,
                user_id=user_id,
                event_type=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                reason=reason or None,
                details_json=details or {},
            )
        )

    @staticmethod
    def _utc_datetime(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _snapshot_address(stop: JobStop | None) -> str:
        if stop is None:
            return ""
        snapshot = stop.address_snapshot_json or {}
        return str(snapshot.get("entered_address") or snapshot.get("normalized_address") or "")

    @staticmethod
    def _assignment_summary(assignment: JobAssignment | None) -> AssignmentSummary | None:
        if assignment is None:
            return None
        driver_name = "Unassigned"
        driver_status = ""
        if assignment.driver is not None:
            driver_name = f"{assignment.driver.first_name} {assignment.driver.last_name}".strip()
            driver_status = assignment.driver.status
        vehicle_name = "No vehicle"
        vehicle_status = ""
        if assignment.vehicle is not None:
            vehicle_name = (
                f"{assignment.vehicle.vehicle_number} · "
                f"{assignment.vehicle.year} {assignment.vehicle.make} {assignment.vehicle.model}"
            )
            vehicle_status = assignment.vehicle.status
        return AssignmentSummary(
            id=assignment.id,
            driver_id=assignment.driver_id,
            driver_name=driver_name,
            driver_status=driver_status,
            vehicle_id=assignment.vehicle_id,
            vehicle_name=vehicle_name,
            vehicle_status=vehicle_status,
            starts_at=DispatchRepository._utc_datetime(assignment.starts_at),
            ends_at=DispatchRepository._utc_datetime(assignment.ends_at),
        )

    @staticmethod
    def _active_assignment_record(job: Job) -> AssignmentSummary | None:
        active = [assignment for assignment in job.assignments if assignment.unassigned_at is None]
        assignment = max(active, key=lambda item: item.assigned_at) if active else None
        return DispatchRepository._assignment_summary(assignment)

    @staticmethod
    def _latest_assignment_record(job: Job) -> AssignmentSummary | None:
        assignment = max(job.assignments, key=lambda item: item.assigned_at) if job.assignments else None
        return DispatchRepository._assignment_summary(assignment)

    def _job_record(self, job: Job) -> DispatchJobRecord:
        pickup = next((stop for stop in job.stops if stop.stop_type == "pickup"), None)
        delivery = next((stop for stop in job.stops if stop.stop_type == "delivery"), None)
        return DispatchJobRecord(
            id=job.id,
            job_number=job.job_number,
            customer_id=job.customer_id,
            customer_name=job.customer.company_name if job.customer else "Unlinked customer",
            status=job.status,
            priority=job.priority,
            service_type=job.service_type,
            requested_window_start=self._utc_datetime(job.requested_window_start),
            requested_window_end=self._utc_datetime(job.requested_window_end),
            promised_pickup_at=self._utc_datetime(job.promised_pickup_at),
            promised_delivery_at=self._utc_datetime(job.promised_delivery_at),
            planned_miles=job.planned_miles,
            planned_minutes=job.planned_minutes,
            quoted_revenue_cents=job.quoted_revenue_cents,
            estimated_cost_cents=job.estimated_cost_cents,
            pickup_address=self._snapshot_address(pickup),
            pickup_order_number=pickup.order_number if pickup and pickup.order_number else "",
            pickup_instructions=pickup.instructions_snapshot if pickup else "",
            delivery_address=self._snapshot_address(delivery),
            delivery_instructions=delivery.instructions_snapshot if delivery else "",
            internal_notes=job.internal_notes,
            dispatch_notes=job.dispatch_notes,
            cancellation_reason=job.cancellation_reason,
            assignment=self._active_assignment_record(job),
            last_assignment=self._latest_assignment_record(job),
            created_at=self._utc_datetime(job.created_at),
            updated_at=self._utc_datetime(job.updated_at),
        )

    @staticmethod
    def _driver_record(driver: Driver) -> DriverRecord:
        return DriverRecord(
            id=driver.id,
            driver_number=driver.driver_number,
            first_name=driver.first_name,
            last_name=driver.last_name,
            phone=driver.phone or "",
            email=driver.email or "",
            status=driver.status,
            license_state=driver.license_state or "",
            license_expiration=driver.license_expiration,
            notes=driver.notes,
        )

    @staticmethod
    def _vehicle_record(vehicle: Vehicle) -> VehicleRecord:
        return VehicleRecord(
            id=vehicle.id,
            vehicle_number=vehicle.vehicle_number,
            year=vehicle.year,
            make=vehicle.make,
            model=vehicle.model,
            trim=vehicle.trim or "",
            status=vehicle.status,
            cargo_length_inches=vehicle.cargo_length_inches,
            cargo_width_inches=vehicle.cargo_width_inches,
            cargo_height_inches=vehicle.cargo_height_inches,
            payload_pounds=vehicle.payload_pounds,
            cost_per_mile_cents=vehicle.cost_per_mile_cents,
            registration_expires_on=vehicle.registration_expires_on,
            insurance_expires_on=vehicle.insurance_expires_on,
            notes=vehicle.notes,
        )
