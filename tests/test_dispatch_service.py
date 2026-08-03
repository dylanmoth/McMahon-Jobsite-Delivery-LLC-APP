from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from mcmahon_dispatch.core.exceptions import ValidationError
from mcmahon_dispatch.database.models import Driver, JobAssignment, JobStatusEvent, Vehicle, WaitEvent
from mcmahon_dispatch.services.auth_service import AuthenticationService
from mcmahon_dispatch.services.customer_service import CustomerSaveRequest, CustomerService
from mcmahon_dispatch.services.dispatch_service import (
    AssignmentRequest,
    DispatchService,
    DriverSaveRequest,
    JobSaveRequest,
    StatusChangeRequest,
    VehicleSaveRequest,
)


def _service(database, config):
    auth = AuthenticationService(database.session_factory, config)
    user = auth.create_initial_admin(
        "dispatch_owner",
        "Dispatch Owner",
        "dispatch@example.com",
        "StrongPassword123",
    )
    customers = CustomerService(database.session_factory, user.organization_id, user.id)
    customer_id = customers.save(
        CustomerSaveRequest(
            company_name="Treasure Coast Contractors",
            legal_name="Treasure Coast Contractors LLC",
            status="active",
            payment_terms_days=15,
            preferred_payment_method="ach",
            credit_limit_cents=None,
            readiness_score=90,
            relationship_score=95,
            internal_notes="",
        )
    )
    service = DispatchService(
        database.session_factory,
        user.organization_id,
        user.id,
        can_manage=True,
        can_view_financials=True,
    )
    driver_id = service.save_driver(
        DriverSaveRequest(
            first_name="Alex",
            last_name="Driver",
            phone="772-555-0101",
            email="alex@example.com",
            status="available",
            license_state="FL",
            license_expiration=date(2028, 1, 1),
            notes="Primary driver",
        )
    )
    vehicle_id = service.save_vehicle(
        VehicleSaveRequest(
            year=2025,
            make="Volkswagen",
            model="Tiguan",
            trim="SE R-Line Black",
            status="available",
            cargo_length_inches=Decimal("70"),
            cargo_width_inches=Decimal("42"),
            cargo_height_inches=Decimal("31"),
            payload_pounds=Decimal("1000"),
            cost_per_mile_cents=55,
            registration_expires_on=date(2027, 1, 1),
            insurance_expires_on=date(2027, 1, 1),
            notes="Initial dispatch vehicle",
        )
    )
    return user, customer_id, driver_id, vehicle_id, service


def _job_request(customer_id: str, start: datetime) -> JobSaveRequest:
    return JobSaveRequest(
        customer_id=customer_id,
        status="scheduled",
        priority="high",
        service_type="Jobsite Delivery",
        requested_window_start=start,
        requested_window_end=start + timedelta(hours=2),
        promised_pickup_at=start + timedelta(minutes=15),
        promised_delivery_at=start + timedelta(minutes=90),
        planned_miles=Decimal("18.5"),
        planned_minutes=90,
        quoted_revenue_cents=17500,
        estimated_cost_cents=6500,
        pickup_address="123 Supplier Way, Port St. Lucie, FL",
        pickup_order_number="PO-1001",
        pickup_instructions="Use contractor pickup desk.",
        delivery_address="456 Jobsite Avenue, Port St. Lucie, FL",
        delivery_instructions="Call site contact on arrival.",
        internal_notes="Customer requested morning delivery.",
        dispatch_notes="Verify order is paid and ready.",
    )


def test_dispatch_job_assignment_and_status_timeline(database, config) -> None:
    _user, customer_id, driver_id, vehicle_id, service = _service(database, config)
    start = datetime.now(UTC) + timedelta(days=1)
    job_id = service.save_job(_job_request(customer_id, start))

    service.assign(
        job_id,
        AssignmentRequest(driver_id, vehicle_id, start, start + timedelta(hours=2)),
    )
    service.change_status(
        job_id,
        StatusChangeRequest("picking_up", requirements_confirmed=True),
    )
    service.change_status(job_id, StatusChangeRequest("waiting", reason="Supplier delay"))
    service.change_status(
        job_id,
        StatusChangeRequest("in_transit", requirements_confirmed=True),
    )
    service.change_status(
        job_id,
        StatusChangeRequest("delivered", requirements_confirmed=True),
    )
    service.change_status(
        job_id,
        StatusChangeRequest("completed", requirements_confirmed=True),
    )

    loaded = service.load_job(job_id)
    assert loaded.record.status == "completed"
    assert loaded.record.assignment is None
    assert loaded.record.last_assignment is not None
    assert loaded.record.last_assignment.driver_name == "Alex Driver"
    assert loaded.record.pickup_order_number == "PO-1001"
    timeline = service.timeline(job_id)
    assert [event.to_status for event in timeline][:2] == ["completed", "delivered"]

    with database.session_factory() as session:
        assert session.scalar(select(func.count(JobStatusEvent.id)).where(JobStatusEvent.job_id == job_id)) == 6
        wait = session.scalar(select(WaitEvent).where(WaitEvent.job_id == job_id))
        assert wait is not None
        assert wait.ended_at is not None
        assert wait.wait_minutes is not None
        assert session.get(Driver, driver_id).status == "available"
        assert session.get(Vehicle, vehicle_id).status == "available"


def test_assignment_conflict_detection_and_override(database, config) -> None:
    _user, customer_id, driver_id, vehicle_id, service = _service(database, config)
    start = datetime.now(UTC) + timedelta(days=2)
    first_id = service.save_job(_job_request(customer_id, start))
    second_id = service.save_job(_job_request(customer_id, start + timedelta(minutes=30)))
    service.assign(
        first_id,
        AssignmentRequest(driver_id, vehicle_id, start, start + timedelta(hours=2)),
    )
    second_request = AssignmentRequest(
        driver_id,
        vehicle_id,
        start + timedelta(minutes=30),
        start + timedelta(hours=2, minutes=30),
    )
    conflicts = service.assignment_conflicts(second_id, second_request)
    assert {conflict.kind for conflict in conflicts} >= {"driver", "vehicle"}
    with pytest.raises(ValidationError):
        service.assign(second_id, second_request)
    service.assign(second_id, second_request, allow_conflicts=True)
    assert service.load_job(second_id).record.assignment is not None


def test_reassignment_preserves_history(database, config) -> None:
    _user, customer_id, driver_id, vehicle_id, service = _service(database, config)
    second_driver = service.save_driver(
        DriverSaveRequest("Jamie", "Backup", "", "", "available", "FL", None, "")
    )
    start = datetime.now(UTC) + timedelta(days=3)
    job_id = service.save_job(_job_request(customer_id, start))
    service.assign(job_id, AssignmentRequest(driver_id, vehicle_id, start, start + timedelta(hours=2)))
    service.assign(
        job_id,
        AssignmentRequest(
            second_driver,
            vehicle_id,
            start + timedelta(hours=3),
            start + timedelta(hours=5),
            "Driver swap",
        ),
    )
    with database.session_factory() as session:
        assignments = session.scalars(
            select(JobAssignment).where(JobAssignment.job_id == job_id).order_by(JobAssignment.assigned_at)
        ).all()
        assert len(assignments) == 2
        assert assignments[0].unassigned_at is not None
        assert assignments[0].unassigned_reason == "Driver swap"
        assert assignments[1].unassigned_at is None


def test_calendar_reschedule_moves_assignment(database, config) -> None:
    _user, customer_id, driver_id, vehicle_id, service = _service(database, config)
    start = datetime.now(UTC) + timedelta(days=4)
    job_id = service.save_job(_job_request(customer_id, start))
    service.assign(job_id, AssignmentRequest(driver_id, vehicle_id, start, start + timedelta(hours=2)))
    target = start.date() + timedelta(days=5)
    service.reschedule_job(job_id, target)
    loaded = service.load_job(job_id).record
    assert loaded.requested_window_start is not None
    assert loaded.requested_window_start.date() == target
    assert loaded.assignment is not None
    assert loaded.assignment.starts_at.date() == target


def test_read_only_dispatch_cannot_write(database, config) -> None:
    user, customer_id, _driver_id, _vehicle_id, service = _service(database, config)
    read_only = DispatchService(
        database.session_factory,
        user.organization_id,
        user.id,
        can_manage=False,
        can_view_financials=False,
    )
    with pytest.raises(ValidationError):
        read_only.save_job(_job_request(customer_id, datetime.now(UTC) + timedelta(days=1)))


def test_calendar_reschedule_blocks_conflicts_until_overridden(database, config) -> None:
    _user, customer_id, driver_id, vehicle_id, service = _service(database, config)
    start = datetime.now(UTC).replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=10)
    first_id = service.save_job(_job_request(customer_id, start))
    second_id = service.save_job(_job_request(customer_id, start + timedelta(days=1)))
    service.assign(first_id, AssignmentRequest(driver_id, vehicle_id, start, start + timedelta(hours=2)))
    service.assign(
        second_id,
        AssignmentRequest(
            driver_id,
            vehicle_id,
            start + timedelta(days=1),
            start + timedelta(days=1, hours=2),
        ),
    )

    target = start.date()
    conflicts = service.reschedule_conflicts(second_id, target)
    assert {conflict.kind for conflict in conflicts} >= {"driver", "vehicle"}
    assert "promised_window" not in {conflict.kind for conflict in conflicts}
    with pytest.raises(ValidationError):
        service.reschedule_job(second_id, target)
    service.reschedule_job(second_id, target, allow_conflicts=True)
    assert service.load_job(second_id).record.requested_window_start.date() == target


def test_driver_and_vehicle_statuses_are_validated(database, config) -> None:
    _user, _customer_id, _driver_id, _vehicle_id, service = _service(database, config)
    with pytest.raises(ValidationError):
        service.save_driver(
            DriverSaveRequest("Bad", "Status", "", "", "flying", "FL", None, "")
        )
    with pytest.raises(ValidationError):
        service.save_vehicle(
            VehicleSaveRequest(
                year=2025,
                make="Test",
                model="Truck",
                trim="",
                status="teleporting",
                cargo_length_inches=None,
                cargo_width_inches=None,
                cargo_height_inches=None,
                payload_pounds=None,
                cost_per_mile_cents=None,
                registration_expires_on=None,
                insurance_expires_on=None,
                notes="",
            )
        )
