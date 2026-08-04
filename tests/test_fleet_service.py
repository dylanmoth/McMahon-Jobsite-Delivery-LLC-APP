from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from mcmahon_dispatch.services.auth_service import AuthenticationService
from mcmahon_dispatch.services.fleet_service import (
    FleetService,
    FuelSaveRequest,
    MaintenanceSaveRequest,
    VehicleSaveRequest,
)


def _service(database, config):
    auth = AuthenticationService(database.session_factory, config)
    user = auth.create_initial_admin(
        "fleet_owner", "Fleet Owner", "fleet@example.com", "StrongPassword123"
    )
    return FleetService(database.session_factory, user.organization_id, user.id, can_write=True)


def test_vehicle_maintenance_fuel_and_summary(database, config) -> None:
    service = _service(database, config)
    vehicle_id = service.save_vehicle(
        VehicleSaveRequest(
            vehicle_number="V-001",
            year=2025,
            make="Volkswagen",
            model="Tiguan",
            trim="SE R-Line Black",
            odometer_miles=Decimal("10000.0"),
            estimated_mpg=Decimal("25.0"),
            cost_per_mile_cents=55,
            registration_expires_on=date.today() + timedelta(days=180),
            insurance_expires_on=date.today() + timedelta(days=180),
        )
    )
    service.save_maintenance(
        MaintenanceSaveRequest(
            vehicle_id=vehicle_id,
            maintenance_type="Oil Change",
            status="completed",
            due_date=None,
            due_odometer_miles=None,
            completed_date=date.today(),
            completed_odometer_miles=Decimal("10000.0"),
            service_vendor="Dealer",
            cost_cents=8999,
            description="Synthetic oil and filter",
            notes="",
            next_due_date=date.today() + timedelta(days=180),
            next_due_odometer_miles=Decimal("15000.0"),
        )
    )
    service.save_fuel(
        FuelSaveRequest(
            vehicle_id,
            datetime.now(UTC) - timedelta(days=7),
            Decimal("10000"),
            Decimal("10"),
            350,
            3500,
            "Fuel Stop",
            True,
        )
    )
    service.save_fuel(
        FuelSaveRequest(
            vehicle_id,
            datetime.now(UTC),
            Decimal("10250"),
            Decimal("10"),
            360,
            3600,
            "Fuel Stop",
            True,
        )
    )
    vehicles = service.list_vehicles()
    created = next(vehicle for vehicle in vehicles if vehicle.id == vehicle_id)
    assert created.display_name.startswith("V-001")
    maintenance = service.list_maintenance(vehicle_id)
    assert maintenance[0].maintenance_type == "Oil Change"
    fuel = service.list_fuel(vehicle_id)
    assert fuel[0].calculated_mpg == Decimal("25.00")
    summary = service.summary()
    assert summary.vehicle_count >= 1
    assert summary.fuel_cost_cents == 7100
    assert summary.maintenance_cost_cents == 8999
    assert summary.average_mpg == Decimal("25.00")


def test_archive_vehicle_hides_it_by_default(database, config) -> None:
    service = _service(database, config)
    vehicle_id = service.save_vehicle(VehicleSaveRequest("V-002", 2024, "Ford", "Transit"))
    service.archive_vehicle(vehicle_id)
    assert all(vehicle.id != vehicle_id for vehicle in service.list_vehicles())
    assert any(vehicle.id == vehicle_id for vehicle in service.list_vehicles(include_inactive=True))
