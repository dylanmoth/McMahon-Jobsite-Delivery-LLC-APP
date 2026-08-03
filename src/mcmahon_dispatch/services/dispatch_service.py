from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from mcmahon_dispatch.core.enums import DriverStatus, JobStatus, VehicleStatus
from mcmahon_dispatch.core.exceptions import ValidationError
from mcmahon_dispatch.database.models import Driver, Job, Vehicle
from mcmahon_dispatch.repositories.dispatch_repository import (
    Choice,
    DispatchJobRecord,
    DispatchRepository,
    DriverRecord,
    StatusEventRecord,
    VehicleRecord,
)



DRIVER_STATUSES = frozenset(status.value for status in DriverStatus)
VEHICLE_STATUSES = frozenset(status.value for status in VehicleStatus)

BOARD_STATUSES: tuple[str, ...] = (
    JobStatus.SCHEDULED.value,
    JobStatus.PICKING_UP.value,
    JobStatus.WAITING.value,
    JobStatus.IN_TRANSIT.value,
    JobStatus.DELIVERED.value,
    JobStatus.COMPLETED.value,
    JobStatus.CANCELLED.value,
)

STATUS_LABELS: dict[str, str] = {
    JobStatus.DRAFT.value: "Draft",
    JobStatus.QUOTED.value: "Quoted",
    JobStatus.ACCEPTED.value: "Accepted",
    JobStatus.SCHEDULED.value: "Scheduled",
    JobStatus.PICKING_UP.value: "Picking Up",
    JobStatus.WAITING.value: "Waiting",
    JobStatus.IN_TRANSIT.value: "In Transit",
    JobStatus.DELIVERED.value: "Delivered",
    JobStatus.COMPLETED.value: "Completed",
    JobStatus.CANCELLED.value: "Cancelled",
    JobStatus.ON_HOLD.value: "On Hold",
    JobStatus.FAILED_PICKUP.value: "Failed Pickup",
    JobStatus.FAILED_DELIVERY.value: "Failed Delivery",
    JobStatus.RETURN.value: "Return",
}

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    JobStatus.DRAFT.value: frozenset({JobStatus.ACCEPTED.value, JobStatus.SCHEDULED.value, JobStatus.CANCELLED.value}),
    JobStatus.QUOTED.value: frozenset({JobStatus.ACCEPTED.value, JobStatus.SCHEDULED.value, JobStatus.CANCELLED.value}),
    JobStatus.ACCEPTED.value: frozenset({JobStatus.SCHEDULED.value, JobStatus.CANCELLED.value, JobStatus.ON_HOLD.value}),
    JobStatus.SCHEDULED.value: frozenset({JobStatus.PICKING_UP.value, JobStatus.CANCELLED.value, JobStatus.ON_HOLD.value}),
    JobStatus.PICKING_UP.value: frozenset({JobStatus.WAITING.value, JobStatus.IN_TRANSIT.value, JobStatus.CANCELLED.value, JobStatus.FAILED_PICKUP.value, JobStatus.ON_HOLD.value}),
    JobStatus.WAITING.value: frozenset({JobStatus.PICKING_UP.value, JobStatus.IN_TRANSIT.value, JobStatus.CANCELLED.value, JobStatus.FAILED_PICKUP.value, JobStatus.ON_HOLD.value}),
    JobStatus.IN_TRANSIT.value: frozenset({JobStatus.DELIVERED.value, JobStatus.CANCELLED.value, JobStatus.FAILED_DELIVERY.value, JobStatus.RETURN.value, JobStatus.ON_HOLD.value}),
    JobStatus.DELIVERED.value: frozenset({JobStatus.COMPLETED.value, JobStatus.CANCELLED.value, JobStatus.RETURN.value}),
    JobStatus.ON_HOLD.value: frozenset({JobStatus.SCHEDULED.value, JobStatus.PICKING_UP.value, JobStatus.IN_TRANSIT.value, JobStatus.CANCELLED.value}),
    JobStatus.FAILED_PICKUP.value: frozenset({JobStatus.SCHEDULED.value, JobStatus.CANCELLED.value}),
    JobStatus.FAILED_DELIVERY.value: frozenset({JobStatus.IN_TRANSIT.value, JobStatus.RETURN.value, JobStatus.CANCELLED.value}),
    JobStatus.RETURN.value: frozenset({JobStatus.COMPLETED.value, JobStatus.CANCELLED.value}),
    JobStatus.COMPLETED.value: frozenset(),
    JobStatus.CANCELLED.value: frozenset(),
}

ACTIVE_STATUSES = frozenset(
    {
        JobStatus.SCHEDULED.value,
        JobStatus.PICKING_UP.value,
        JobStatus.WAITING.value,
        JobStatus.IN_TRANSIT.value,
        JobStatus.DELIVERED.value,
        JobStatus.ON_HOLD.value,
        JobStatus.FAILED_PICKUP.value,
        JobStatus.FAILED_DELIVERY.value,
        JobStatus.RETURN.value,
    }
)


@dataclass(frozen=True, slots=True)
class JobSaveRequest:
    customer_id: str
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
    cancellation_reason: str = ""


@dataclass(frozen=True, slots=True)
class AssignmentRequest:
    driver_id: str
    vehicle_id: str
    starts_at: datetime
    ends_at: datetime
    reason: str = ""


@dataclass(frozen=True, slots=True)
class DriverSaveRequest:
    first_name: str
    last_name: str
    phone: str
    email: str
    status: str
    license_state: str
    license_expiration: date | None
    notes: str


@dataclass(frozen=True, slots=True)
class VehicleSaveRequest:
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
    registration_expires_on: date | None
    insurance_expires_on: date | None
    notes: str


@dataclass(frozen=True, slots=True)
class StatusChangeRequest:
    target_status: str
    note: str = ""
    reason: str = ""
    requirements_confirmed: bool = False
    override_reason: str = ""


@dataclass(frozen=True, slots=True)
class DispatchConflict:
    kind: str
    severity: str
    message: str
    related_job_id: str | None = None


@dataclass(frozen=True, slots=True)
class DispatchAlert:
    severity: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class DispatchJobView:
    record: DispatchJobRecord
    alerts: tuple[DispatchAlert, ...]

    @property
    def alert_count(self) -> int:
        return len(self.alerts)


@dataclass(frozen=True, slots=True)
class DispatchMetrics:
    active_jobs: int
    unassigned_jobs: int
    waiting_jobs: int
    overdue_jobs: int
    scheduled_today: int
    completed_today: int


class DispatchService:
    def __init__(
        self,
        factory: sessionmaker[Session],
        organization_id: str,
        user_id: str | None,
        *,
        can_manage: bool,
        can_view_financials: bool,
    ) -> None:
        self.factory = factory
        self.organization_id = organization_id
        self.user_id = user_id
        self.can_manage = can_manage
        self.can_view_financials = can_view_financials

    def choices(self) -> tuple[list[Choice], list[Choice], list[Choice]]:
        with self.factory() as session:
            repo = DispatchRepository(session, self.organization_id)
            return repo.customer_choices(), repo.driver_choices(), repo.vehicle_choices()

    def validate_job_request(self, request: JobSaveRequest) -> JobSaveRequest:
        normalized = self._normalized_job_request(request)
        self._validate_job_request(normalized)
        return normalized

    def validate_assignment_request(self, request: AssignmentRequest) -> AssignmentRequest:
        normalized = self._normalized_assignment_request(request)
        self._validate_assignment_request(normalized)
        return normalized

    def jobs(
        self,
        *,
        statuses: Iterable[str] | None = None,
        query: str = "",
        starts_before: datetime | None = None,
        ends_after: datetime | None = None,
        driver_id: str | None = None,
    ) -> list[DispatchJobView]:
        with self.factory() as session:
            repo = DispatchRepository(session, self.organization_id)
            records = repo.list_jobs(
                statuses=statuses,
                query=query,
                starts_before=starts_before,
                ends_after=ends_after,
                driver_id=driver_id,
            )
            return [DispatchJobView(record, tuple(self._alerts(record))) for record in records]

    def load_job(self, job_id: str) -> DispatchJobView:
        with self.factory() as session:
            repo = DispatchRepository(session, self.organization_id)
            record = repo.get_job(job_id)
            if record is None:
                raise ValidationError("Job not found or no longer available.")
            return DispatchJobView(record, tuple(self._alerts(record)))

    def save_job(self, request: JobSaveRequest, job_id: str | None = None) -> str:
        self._require_manage()
        request = self.validate_job_request(request)
        now = datetime.now(UTC)
        with self.factory.begin() as session:
            repo = DispatchRepository(session, self.organization_id)
            if job_id is not None:
                exists = session.scalar(
                    select(Job.id).where(
                        Job.organization_id == self.organization_id,
                        Job.id == job_id,
                        Job.deleted_at.is_(None),
                    )
                )
                if exists is None:
                    raise ValidationError("Job not found or no longer available.")

            values = {
                "customer_id": request.customer_id,
                "status": request.status,
                "priority": request.priority,
                "service_type": request.service_type,
                "requested_window_start": request.requested_window_start,
                "requested_window_end": request.requested_window_end,
                "promised_pickup_at": request.promised_pickup_at,
                "promised_delivery_at": request.promised_delivery_at,
                "planned_miles": request.planned_miles,
                "planned_minutes": request.planned_minutes,
                "quoted_revenue_cents": request.quoted_revenue_cents,
                "estimated_cost_cents": request.estimated_cost_cents,
                "internal_notes": request.internal_notes,
                "dispatch_notes": request.dispatch_notes,
                "cancellation_reason": request.cancellation_reason or None,
                "updated_by_id": self.user_id,
            }
            if job_id is None:
                values["created_by_id"] = self.user_id
                job = repo.create_job(values)
                repo.add_status_event(
                    job_id=job.id,
                    from_status=None,
                    to_status=request.status,
                    user_id=self.user_id,
                    occurred_at=now,
                    note="Job created in Dispatch Center.",
                    override_reason="",
                )
                event_type = "dispatch.job.created"
            else:
                job = repo.get_job_model(job_id)
                if job is None:
                    raise ValidationError("Job not found or no longer available.")
                prior_status = job.status
                for key, value in values.items():
                    setattr(job, key, value)
                if prior_status != request.status:
                    self._validate_transition(
                        prior_status,
                        StatusChangeRequest(
                            target_status=request.status,
                            reason=request.cancellation_reason,
                            requirements_confirmed=True,
                            override_reason="Edited from job form.",
                        ),
                        has_assignment=repo.active_assignment(job.id) is not None,
                    )
                    repo.add_status_event(
                        job_id=job.id,
                        from_status=prior_status,
                        to_status=request.status,
                        user_id=self.user_id,
                        occurred_at=now,
                        note="Status updated from job form.",
                        override_reason="Edited from job form.",
                    )
                event_type = "dispatch.job.updated"

            repo.replace_stops(
                job,
                {
                    "address": request.pickup_address,
                    "order_number": request.pickup_order_number,
                    "instructions": request.pickup_instructions,
                    "planned_arrival_at": request.promised_pickup_at,
                    "service_minutes": 15,
                    "label": "Pickup",
                },
                {
                    "address": request.delivery_address,
                    "instructions": request.delivery_instructions,
                    "planned_arrival_at": request.promised_delivery_at,
                    "service_minutes": 15,
                    "label": "Delivery",
                },
            )
            repo.audit(
                user_id=self.user_id,
                event_type=event_type,
                entity_type="job",
                entity_id=job.id,
                details={
                    "job_number": job.job_number,
                    "status": request.status,
                    "customer_id": request.customer_id,
                },
            )
            return job.id

    def delete_job(self, job_id: str, reason: str) -> None:
        self._require_manage()
        normalized = reason.strip()
        if not normalized:
            raise ValidationError("A reason is required to delete a draft job.")
        with self.factory.begin() as session:
            repo = DispatchRepository(session, self.organization_id)
            job = repo.get_job_model(job_id)
            if job is None:
                raise ValidationError("Job not found.")
            if job.status not in {JobStatus.DRAFT.value, JobStatus.ACCEPTED.value, JobStatus.SCHEDULED.value}:
                raise ValidationError("Operational jobs cannot be deleted. Cancel the job instead.")
            if repo.active_assignment(job.id) is not None:
                raise ValidationError("Unassign the driver and vehicle before deleting the job.")
            job.deleted_at = datetime.now(UTC)
            job.deleted_by_id = self.user_id
            repo.audit(
                user_id=self.user_id,
                event_type="dispatch.job.deleted",
                entity_type="job",
                entity_id=job.id,
                reason=normalized,
            )

    def assignment_conflicts(self, job_id: str, request: AssignmentRequest) -> list[DispatchConflict]:
        request = self.validate_assignment_request(request)
        with self.factory() as session:
            repo = DispatchRepository(session, self.organization_id)
            if repo.get_job_model(job_id) is None:
                raise ValidationError("Job not found.")
            driver = repo.get_driver(request.driver_id)
            vehicle = repo.get_vehicle(request.vehicle_id)
            if driver is None:
                raise ValidationError("Driver not found.")
            if vehicle is None:
                raise ValidationError("Vehicle not found.")
            conflicts: list[DispatchConflict] = []
            if driver.status in {"inactive", "unavailable", "off_duty", "time_off"}:
                conflicts.append(
                    DispatchConflict(
                        "driver_status",
                        "danger",
                        f"{driver.first_name} {driver.last_name} is marked {driver.status.replace('_', ' ')}.",
                    )
                )
            if vehicle.status in {"maintenance", "out_of_service", "inactive"} or not vehicle.active:
                conflicts.append(
                    DispatchConflict(
                        "vehicle_status",
                        "danger",
                        f"{vehicle.vehicle_number} is marked {vehicle.status.replace('_', ' ')}.",
                    )
                )
            job_record = repo.get_job(job_id)
            if job_record is not None:
                assignment_minutes = int((request.ends_at - request.starts_at).total_seconds() / 60)
                if job_record.planned_minutes and assignment_minutes < job_record.planned_minutes:
                    conflicts.append(
                        DispatchConflict(
                            "duration",
                            "warning",
                            f"Assignment window is {assignment_minutes} minutes but the job plan requires "
                            f"{job_record.planned_minutes} minutes.",
                            job_id,
                        )
                    )
                if job_record.promised_delivery_at and request.ends_at < job_record.promised_delivery_at:
                    conflicts.append(
                        DispatchConflict(
                            "promised_window",
                            "warning",
                            "Assignment ends before the promised delivery time.",
                            job_id,
                        )
                    )
            for kind, assignment in repo.assignment_conflicts(
                job_id=job_id,
                driver_id=request.driver_id,
                vehicle_id=request.vehicle_id,
                starts_at=request.starts_at,
                ends_at=request.ends_at,
            ):
                related = assignment.job
                customer = related.customer.company_name if related and related.customer else "Unlinked customer"
                label = "Driver" if kind == "driver" else "Vehicle"
                conflicts.append(
                    DispatchConflict(
                        kind,
                        "danger",
                        f"{label} overlaps {related.job_number} for {customer} "
                        f"({self._format_window(assignment.starts_at, assignment.ends_at)}).",
                        related.id,
                    )
                )
            return conflicts

    def assign(self, job_id: str, request: AssignmentRequest, *, allow_conflicts: bool = False) -> str:
        self._require_manage()
        request = self.validate_assignment_request(request)
        conflicts = self.assignment_conflicts(job_id, request)
        if conflicts and not allow_conflicts:
            raise ValidationError("Assignment has conflicts. Review and explicitly approve the override.")
        now = datetime.now(UTC)
        with self.factory.begin() as session:
            repo = DispatchRepository(session, self.organization_id)
            job = repo.get_job_model(job_id)
            if job is None:
                raise ValidationError("Job not found.")
            driver = repo.get_driver(request.driver_id)
            vehicle = repo.get_vehicle(request.vehicle_id)
            if driver is None or vehicle is None:
                raise ValidationError("The selected driver or vehicle is no longer available.")
            current = repo.active_assignment(job_id)
            previous_driver_id: str | None = None
            previous_vehicle_id: str | None = None
            if current is not None:
                same_assignment = (
                    current.driver_id == request.driver_id
                    and current.vehicle_id == request.vehicle_id
                    and self._utc(current.starts_at) == request.starts_at
                    and self._utc(current.ends_at) == request.ends_at
                )
                if same_assignment:
                    return current.id
                previous_driver_id = current.driver_id
                previous_vehicle_id = current.vehicle_id
                repo.close_assignment(
                    current,
                    at=now,
                    reason=request.reason or "Reassigned in Dispatch Center",
                )
            assignment = repo.create_assignment(
                job_id=job_id,
                driver_id=request.driver_id,
                vehicle_id=request.vehicle_id,
                user_id=self.user_id,
                starts_at=request.starts_at,
                ends_at=request.ends_at,
            )
            driver.status = "assigned"
            vehicle.status = "assigned"
            driver.updated_by_id = self.user_id
            vehicle.updated_by_id = self.user_id
            if previous_driver_id and previous_driver_id != request.driver_id:
                previous_driver = session.get(Driver, previous_driver_id)
                if previous_driver is not None and not repo.driver_has_active_assignment(previous_driver_id):
                    previous_driver.status = "available"
                    previous_driver.updated_by_id = self.user_id
            if previous_vehicle_id and previous_vehicle_id != request.vehicle_id:
                previous_vehicle = session.get(Vehicle, previous_vehicle_id)
                if previous_vehicle is not None and not repo.vehicle_has_active_assignment(previous_vehicle_id):
                    previous_vehicle.status = "available"
                    previous_vehicle.updated_by_id = self.user_id
            if job.status in {JobStatus.DRAFT.value, JobStatus.QUOTED.value, JobStatus.ACCEPTED.value}:
                prior = job.status
                job.status = JobStatus.SCHEDULED.value
                repo.add_status_event(
                    job_id=job.id,
                    from_status=prior,
                    to_status=job.status,
                    user_id=self.user_id,
                    occurred_at=now,
                    note="Job scheduled during assignment.",
                    override_reason="",
                )
            repo.audit(
                user_id=self.user_id,
                event_type="dispatch.assignment.changed",
                entity_type="job",
                entity_id=job_id,
                reason=request.reason,
                details={
                    "driver_id": request.driver_id,
                    "vehicle_id": request.vehicle_id,
                    "starts_at": request.starts_at.isoformat(),
                    "ends_at": request.ends_at.isoformat(),
                    "conflict_override": bool(conflicts),
                    "conflicts": [conflict.message for conflict in conflicts],
                },
            )
            return assignment.id

    def unassign(self, job_id: str, reason: str) -> None:
        self._require_manage()
        normalized = reason.strip()
        if not normalized:
            raise ValidationError("A reason is required when unassigning a job.")
        now = datetime.now(UTC)
        with self.factory.begin() as session:
            repo = DispatchRepository(session, self.organization_id)
            assignment = repo.active_assignment(job_id)
            if assignment is None:
                return
            repo.close_assignment(assignment, at=now, reason=normalized)
            driver = session.get(Driver, assignment.driver_id)
            vehicle = session.get(Vehicle, assignment.vehicle_id)
            if driver is not None and not repo.driver_has_active_assignment(assignment.driver_id):
                driver.status = "available"
                driver.updated_by_id = self.user_id
            if vehicle is not None and not repo.vehicle_has_active_assignment(assignment.vehicle_id):
                vehicle.status = "available"
                vehicle.updated_by_id = self.user_id
            repo.audit(
                user_id=self.user_id,
                event_type="dispatch.assignment.removed",
                entity_type="job",
                entity_id=job_id,
                reason=normalized,
            )

    def change_status(self, job_id: str, request: StatusChangeRequest) -> None:
        self._require_manage()
        normalized = replace(
            request,
            target_status=request.target_status.strip(),
            note=request.note.strip(),
            reason=request.reason.strip(),
            override_reason=request.override_reason.strip(),
        )
        now = datetime.now(UTC)
        with self.factory.begin() as session:
            repo = DispatchRepository(session, self.organization_id)
            job = repo.get_job_model(job_id)
            if job is None:
                raise ValidationError("Job not found.")
            if job.status == normalized.target_status:
                return
            assignment = repo.active_assignment(job_id)
            self._validate_transition(
                job.status,
                normalized,
                has_assignment=assignment is not None,
            )
            prior = job.status
            job.status = normalized.target_status
            job.updated_by_id = self.user_id
            if normalized.target_status == JobStatus.CANCELLED.value:
                job.cancellation_reason = normalized.reason
            if normalized.target_status == JobStatus.ON_HOLD.value:
                job.hold_reason = normalized.reason
            if normalized.target_status == JobStatus.WAITING.value:
                if repo.open_wait(job_id) is None:
                    repo.create_wait(job_id, now, normalized.reason or normalized.note)
            elif prior == JobStatus.WAITING.value:
                wait = repo.open_wait(job_id)
                if wait is not None:
                    wait.ended_at = now
                    elapsed = max(0, math.ceil((now - (self._utc(wait.started_at) or now)).total_seconds() / 60))
                    wait.wait_minutes = elapsed
                    sequence = wait.delay_sequence or 1
                    wait.recommended_charge_cents = (
                        0 if sequence == 1 else math.ceil(elapsed / 30) * 5000
                    )
                    wait.updated_by_id = self.user_id
            if normalized.target_status == JobStatus.COMPLETED.value:
                job.actual_profit_cents = job.actual_revenue_cents - job.actual_cost_cents
            if assignment is not None and normalized.target_status in {
                JobStatus.PICKING_UP.value,
                JobStatus.WAITING.value,
                JobStatus.IN_TRANSIT.value,
                JobStatus.DELIVERED.value,
            }:
                driver = session.get(Driver, assignment.driver_id)
                vehicle = session.get(Vehicle, assignment.vehicle_id)
                if driver is not None:
                    driver.status = "on_job"
                    driver.updated_by_id = self.user_id
                if vehicle is not None:
                    vehicle.status = "assigned"
                    vehicle.updated_by_id = self.user_id
            if assignment is not None and normalized.target_status in {
                JobStatus.COMPLETED.value,
                JobStatus.CANCELLED.value,
            }:
                repo.close_assignment(
                    assignment,
                    at=now,
                    reason=f"Job moved to {normalized.target_status.replace('_', ' ')}",
                )
                driver = session.get(Driver, assignment.driver_id)
                vehicle = session.get(Vehicle, assignment.vehicle_id)
                if driver is not None and not repo.driver_has_active_assignment(assignment.driver_id):
                    driver.status = "available"
                    driver.updated_by_id = self.user_id
                if vehicle is not None and not repo.vehicle_has_active_assignment(assignment.vehicle_id):
                    vehicle.status = "available"
                    vehicle.updated_by_id = self.user_id
            repo.add_status_event(
                job_id=job_id,
                from_status=prior,
                to_status=normalized.target_status,
                user_id=self.user_id,
                occurred_at=now,
                note=normalized.note or normalized.reason,
                override_reason=normalized.override_reason,
            )
            repo.audit(
                user_id=self.user_id,
                event_type="dispatch.status.changed",
                entity_type="job",
                entity_id=job_id,
                reason=normalized.reason,
                details={
                    "from": prior,
                    "to": normalized.target_status,
                    "override_reason": normalized.override_reason,
                },
            )

    def reschedule_conflicts(self, job_id: str, target_date: date) -> list[DispatchConflict]:
        with self.factory() as session:
            repo = DispatchRepository(session, self.organization_id)
            record = repo.get_job(job_id)
            if record is None:
                raise ValidationError("Job not found.")
            if record.assignment is None:
                return []
            new_start, new_end = self._rescheduled_window(record, target_date)
            conflicts = self.assignment_conflicts(
                job_id,
                AssignmentRequest(
                    record.assignment.driver_id,
                    record.assignment.vehicle_id,
                    new_start,
                    new_end,
                    "Calendar reschedule",
                ),
            )
            # The promised window moves with the job, so comparing the new assignment
            # against the old promised time would create a false warning.
            return [conflict for conflict in conflicts if conflict.kind != "promised_window"]

    def reschedule_job(
        self,
        job_id: str,
        target_date: date,
        *,
        allow_conflicts: bool = False,
    ) -> None:
        self._require_manage()
        conflicts = self.reschedule_conflicts(job_id, target_date)
        if conflicts and not allow_conflicts:
            raise ValidationError("Rescheduling creates assignment conflicts. Review and approve the override.")
        with self.factory.begin() as session:
            repo = DispatchRepository(session, self.organization_id)
            job = repo.get_job_model(job_id)
            if job is None:
                raise ValidationError("Job not found.")
            old_start = self._utc(job.requested_window_start)
            old_end = self._utc(job.requested_window_end)
            start_time = old_start.timetz().replace(tzinfo=None) if old_start else time(9, 0)
            duration = (
                old_end - old_start
                if old_start and old_end and old_end > old_start
                else timedelta(minutes=job.planned_minutes or 90)
            )
            new_start = datetime.combine(target_date, start_time, tzinfo=UTC)
            new_end = new_start + duration
            delta = new_start - old_start if old_start else timedelta(0)
            job.requested_window_start = new_start
            job.requested_window_end = new_end
            if job.promised_pickup_at is not None:
                job.promised_pickup_at += delta
            if job.promised_delivery_at is not None:
                job.promised_delivery_at += delta
            assignment = repo.active_assignment(job_id)
            if assignment is not None:
                assignment.starts_at = new_start
                assignment.ends_at = new_end
                assignment.updated_by_id = self.user_id
            job.updated_by_id = self.user_id
            repo.audit(
                user_id=self.user_id,
                event_type="dispatch.job.rescheduled",
                entity_type="job",
                entity_id=job_id,
                details={
                    "old_start": old_start.isoformat() if old_start else None,
                    "new_start": new_start.isoformat(),
                    "conflict_override": bool(conflicts),
                    "conflicts": [conflict.message for conflict in conflicts],
                },
            )

    def timeline(self, job_id: str) -> list[StatusEventRecord]:
        with self.factory() as session:
            repo = DispatchRepository(session, self.organization_id)
            if repo.get_job_model(job_id) is None:
                raise ValidationError("Job not found.")
            return repo.status_events(job_id)

    def metrics(self, jobs: Iterable[DispatchJobView] | None = None) -> DispatchMetrics:
        values = list(jobs if jobs is not None else self.jobs(statuses=BOARD_STATUSES))
        now = datetime.now(UTC)
        today = now.date()
        active = [item for item in values if item.record.status in ACTIVE_STATUSES]
        return DispatchMetrics(
            active_jobs=len(active),
            unassigned_jobs=sum(item.record.assignment is None for item in active),
            waiting_jobs=sum(item.record.status == JobStatus.WAITING.value for item in values),
            overdue_jobs=sum(any(alert.code == "overdue" for alert in item.alerts) for item in values),
            scheduled_today=sum(
                bool(item.record.requested_window_start and item.record.requested_window_start.date() == today)
                for item in values
            ),
            completed_today=sum(
                item.record.status == JobStatus.COMPLETED.value
                and item.record.updated_at.date() == today
                for item in values
            ),
        )

    def list_drivers(self) -> list[DriverRecord]:
        with self.factory() as session:
            return DispatchRepository(session, self.organization_id).list_drivers()

    def save_driver(self, request: DriverSaveRequest, driver_id: str | None = None) -> str:
        self._require_manage()
        first = request.first_name.strip()
        last = request.last_name.strip()
        if not first or not last:
            raise ValidationError("Driver first and last name are required.")
        email = request.email.strip().lower()
        if email and "@" not in email:
            raise ValidationError("Enter a valid driver email address.")
        status = request.status.strip().lower()
        if status not in DRIVER_STATUSES:
            raise ValidationError("Select a valid driver status.")
        values = {
            "first_name": first,
            "last_name": last,
            "phone": request.phone.strip() or None,
            "email": email or None,
            "status": status,
            "license_state": request.license_state.strip().upper()[:2] or None,
            "license_expiration": request.license_expiration,
            "notes": request.notes.strip(),
            "updated_by_id": self.user_id,
        }
        with self.factory.begin() as session:
            repo = DispatchRepository(session, self.organization_id)
            if driver_id is None:
                values["created_by_id"] = self.user_id
                driver = repo.create_driver(values)
                event = "dispatch.driver.created"
            else:
                driver = repo.get_driver(driver_id)
                if driver is None:
                    raise ValidationError("Driver not found.")
                for key, value in values.items():
                    setattr(driver, key, value)
                event = "dispatch.driver.updated"
            repo.audit(
                user_id=self.user_id,
                event_type=event,
                entity_type="driver",
                entity_id=driver.id,
                details={"driver_number": driver.driver_number, "status": driver.status},
            )
            return driver.id

    def list_vehicles(self) -> list[VehicleRecord]:
        with self.factory() as session:
            return DispatchRepository(session, self.organization_id).list_vehicles()

    def save_vehicle(self, request: VehicleSaveRequest, vehicle_id: str | None = None) -> str:
        self._require_manage()
        make = request.make.strip()
        model = request.model.strip()
        if request.year < 1900 or request.year > 2200:
            raise ValidationError("Enter a valid vehicle year.")
        if not make or not model:
            raise ValidationError("Vehicle make and model are required.")
        status = request.status.strip().lower()
        if status not in VEHICLE_STATUSES:
            raise ValidationError("Select a valid vehicle status.")
        numeric_values = (
            request.cargo_length_inches,
            request.cargo_width_inches,
            request.cargo_height_inches,
            request.payload_pounds,
        )
        if any(value is not None and value < 0 for value in numeric_values):
            raise ValidationError("Vehicle dimensions and payload cannot be negative.")
        if request.cost_per_mile_cents is not None and request.cost_per_mile_cents < 0:
            raise ValidationError("Cost per mile cannot be negative.")
        values = {
            "year": request.year,
            "make": make,
            "model": model,
            "trim": request.trim.strip() or None,
            "status": status,
            "cargo_length_inches": request.cargo_length_inches,
            "cargo_width_inches": request.cargo_width_inches,
            "cargo_height_inches": request.cargo_height_inches,
            "payload_pounds": request.payload_pounds,
            "cost_per_mile_cents": request.cost_per_mile_cents,
            "registration_expires_on": request.registration_expires_on,
            "insurance_expires_on": request.insurance_expires_on,
            "active": status != VehicleStatus.INACTIVE.value,
            "notes": request.notes.strip(),
            "updated_by_id": self.user_id,
        }
        with self.factory.begin() as session:
            repo = DispatchRepository(session, self.organization_id)
            if vehicle_id is None:
                values["created_by_id"] = self.user_id
                vehicle = repo.create_vehicle(values)
                event = "dispatch.vehicle.created"
            else:
                vehicle = repo.get_vehicle(vehicle_id)
                if vehicle is None:
                    raise ValidationError("Vehicle not found.")
                for key, value in values.items():
                    setattr(vehicle, key, value)
                event = "dispatch.vehicle.updated"
            repo.audit(
                user_id=self.user_id,
                event_type=event,
                entity_type="vehicle",
                entity_id=vehicle.id,
                details={"vehicle_number": vehicle.vehicle_number, "status": vehicle.status},
            )
            return vehicle.id

    def suggested_assignment_window(self, record: DispatchJobRecord) -> tuple[datetime, datetime]:
        start = record.requested_window_start or record.promised_pickup_at or datetime.now(UTC)
        end = record.requested_window_end or record.promised_delivery_at
        if end is None or end <= start:
            end = start + timedelta(minutes=record.planned_minutes or 90)
        return start, end

    def _rescheduled_window(
        self,
        record: DispatchJobRecord,
        target_date: date,
    ) -> tuple[datetime, datetime]:
        old_start = record.requested_window_start or record.promised_pickup_at
        old_end = record.requested_window_end or record.promised_delivery_at
        start_time = old_start.timetz().replace(tzinfo=None) if old_start else time(9, 0)
        duration = (
            old_end - old_start
            if old_start and old_end and old_end > old_start
            else timedelta(minutes=record.planned_minutes or 90)
        )
        new_start = datetime.combine(target_date, start_time, tzinfo=UTC)
        return new_start, new_start + duration

    def _alerts(self, record: DispatchJobRecord) -> list[DispatchAlert]:
        alerts: list[DispatchAlert] = []
        now = datetime.now(UTC)
        if record.status in ACTIVE_STATUSES and record.assignment is None:
            alerts.append(DispatchAlert("danger", "unassigned", "Driver and vehicle are not assigned."))
        if (
            record.promised_delivery_at is not None
            and record.promised_delivery_at < now
            and record.status not in {JobStatus.DELIVERED.value, JobStatus.COMPLETED.value, JobStatus.CANCELLED.value}
        ):
            alerts.append(DispatchAlert("danger", "overdue", "Promised delivery time has passed."))
        if not record.pickup_address:
            alerts.append(DispatchAlert("warning", "pickup_missing", "Pickup address is missing."))
        if not record.delivery_address:
            alerts.append(DispatchAlert("warning", "delivery_missing", "Jobsite address is missing."))
        if record.requested_window_start and record.requested_window_end and record.planned_minutes:
            available = int((record.requested_window_end - record.requested_window_start).total_seconds() / 60)
            if record.planned_minutes > available:
                alerts.append(
                    DispatchAlert(
                        "warning",
                        "window_infeasible",
                        f"Planned duration ({record.planned_minutes} min) exceeds the requested window ({available} min).",
                    )
                )
        if record.assignment is not None:
            if record.assignment.driver_status in {"inactive", "unavailable", "off_duty", "time_off"}:
                alerts.append(DispatchAlert("danger", "driver_unavailable", "Assigned driver is unavailable."))
            if record.assignment.vehicle_status in {"maintenance", "out_of_service", "inactive"}:
                alerts.append(DispatchAlert("danger", "vehicle_unavailable", "Assigned vehicle is unavailable."))
        if self.can_view_financials and record.estimated_cost_cents > record.quoted_revenue_cents:
            alerts.append(DispatchAlert("warning", "negative_margin", "Estimated direct cost exceeds quoted revenue."))
        return alerts

    def _normalized_job_request(self, request: JobSaveRequest) -> JobSaveRequest:
        return replace(
            request,
            customer_id=request.customer_id.strip(),
            status=request.status.strip(),
            priority=request.priority.strip().lower(),
            service_type=request.service_type.strip(),
            pickup_address=request.pickup_address.strip(),
            pickup_order_number=request.pickup_order_number.strip(),
            pickup_instructions=request.pickup_instructions.strip(),
            delivery_address=request.delivery_address.strip(),
            delivery_instructions=request.delivery_instructions.strip(),
            internal_notes=request.internal_notes.strip(),
            dispatch_notes=request.dispatch_notes.strip(),
            cancellation_reason=request.cancellation_reason.strip(),
            requested_window_start=self._utc(request.requested_window_start),
            requested_window_end=self._utc(request.requested_window_end),
            promised_pickup_at=self._utc(request.promised_pickup_at),
            promised_delivery_at=self._utc(request.promised_delivery_at),
        )

    def _validate_job_request(self, request: JobSaveRequest) -> None:
        if not request.customer_id:
            raise ValidationError("Select a customer before saving the job.")
        if request.status not in STATUS_LABELS:
            raise ValidationError("Select a valid job status.")
        if request.priority not in {"low", "normal", "high", "urgent"}:
            raise ValidationError("Select a valid priority.")
        if not request.service_type:
            raise ValidationError("Service type is required.")
        if not request.pickup_address:
            raise ValidationError("Pickup address is required.")
        if not request.delivery_address:
            raise ValidationError("Jobsite address is required.")
        if request.requested_window_start and request.requested_window_end:
            if request.requested_window_end <= request.requested_window_start:
                raise ValidationError("Requested window end must be after its start.")
        if request.promised_pickup_at and request.promised_delivery_at:
            if request.promised_delivery_at < request.promised_pickup_at:
                raise ValidationError("Promised delivery cannot be before promised pickup.")
        if request.planned_miles is not None and request.planned_miles < 0:
            raise ValidationError("Planned mileage cannot be negative.")
        if request.planned_minutes is not None and request.planned_minutes < 0:
            raise ValidationError("Planned minutes cannot be negative.")
        if request.quoted_revenue_cents < 0 or request.estimated_cost_cents < 0:
            raise ValidationError("Revenue and estimated cost cannot be negative.")
        if request.status == JobStatus.CANCELLED.value and not request.cancellation_reason:
            raise ValidationError("A cancellation reason is required.")

    def _normalized_assignment_request(self, request: AssignmentRequest) -> AssignmentRequest:
        return replace(
            request,
            driver_id=request.driver_id.strip(),
            vehicle_id=request.vehicle_id.strip(),
            starts_at=self._utc(request.starts_at) or request.starts_at,
            ends_at=self._utc(request.ends_at) or request.ends_at,
            reason=request.reason.strip(),
        )

    @staticmethod
    def _validate_assignment_request(request: AssignmentRequest) -> None:
        if not request.driver_id:
            raise ValidationError("Select a driver.")
        if not request.vehicle_id:
            raise ValidationError("Select a vehicle.")
        if request.ends_at <= request.starts_at:
            raise ValidationError("Assignment end must be after its start.")

    def _validate_transition(
        self,
        current_status: str,
        request: StatusChangeRequest,
        *,
        has_assignment: bool,
    ) -> None:
        target = request.target_status
        allowed = ALLOWED_TRANSITIONS.get(current_status, frozenset())
        if target not in allowed:
            raise ValidationError(
                f"{STATUS_LABELS.get(current_status, current_status)} cannot move directly to "
                f"{STATUS_LABELS.get(target, target)}."
            )
        if current_status == JobStatus.SCHEDULED.value and target == JobStatus.PICKING_UP.value:
            if not has_assignment:
                raise ValidationError("Assign a driver and vehicle before starting pickup.")
            if not request.requirements_confirmed and not request.override_reason:
                raise ValidationError("Confirm the pickup checklist or enter an override reason.")
        if current_status == JobStatus.PICKING_UP.value and target == JobStatus.IN_TRANSIT.value:
            if not request.requirements_confirmed and not request.override_reason:
                raise ValidationError("Confirm pickup completion or enter an override reason.")
        if current_status == JobStatus.IN_TRANSIT.value and target == JobStatus.DELIVERED.value:
            if not request.requirements_confirmed and not request.override_reason:
                raise ValidationError("Confirm delivery proof or enter an override reason.")
        if current_status == JobStatus.DELIVERED.value and target == JobStatus.COMPLETED.value:
            if not request.requirements_confirmed and not request.override_reason:
                raise ValidationError("Confirm actuals and invoicing review or enter an override reason.")
        if target in {JobStatus.CANCELLED.value, JobStatus.ON_HOLD.value, JobStatus.FAILED_PICKUP.value, JobStatus.FAILED_DELIVERY.value}:
            if not request.reason:
                raise ValidationError("A reason is required for this status change.")

    def _require_manage(self) -> None:
        if not self.can_manage:
            raise ValidationError("Your account has read-only dispatch access.")

    @staticmethod
    def _utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _format_window(start: datetime, end: datetime) -> str:
        return f"{start.astimezone().strftime('%b %d %I:%M %p')}–{end.astimezone().strftime('%I:%M %p')}"
