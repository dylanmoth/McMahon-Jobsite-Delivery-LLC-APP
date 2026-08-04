from decimal import Decimal

import pytest

from mcmahon_dispatch.core.exceptions import ValidationError
from mcmahon_dispatch.database.seed import DEFAULT_PRICING
from mcmahon_dispatch.services.pricing_engine import (
    PricingConfiguration,
    PricingEngine,
    PricingInputs,
)


@pytest.fixture
def config() -> PricingConfiguration:
    return PricingConfiguration.from_mapping("1.0", DEFAULT_PRICING)


@pytest.fixture
def engine() -> PricingEngine:
    return PricingEngine()


def standard(**changes: object) -> PricingInputs:
    values: dict[str, object] = {
        "length_inches": Decimal("72"),
        "width_inches": Decimal("48"),
        "height_inches": Decimal("18"),
        "overweight": False,
        "store_inside_psl": True,
        "jobsite_inside_psl": True,
    }
    values.update(changes)
    return PricingInputs(**values)  # type: ignore[arg-type]


def test_a001_standard_inside(engine: PricingEngine, config: PricingConfiguration) -> None:
    assert engine.calculate(standard(), config).total_cents == 7500


def test_a002_outside_store_example(engine: PricingEngine, config: PricingConfiguration) -> None:
    result = engine.calculate(
        standard(
            store_inside_psl=False,
            jobsite_inside_psl=True,
            boundary_to_store_miles=Decimal("18"),
            store_to_jobsite_miles=Decimal("2"),
        ),
        config,
    )
    assert result.chargeable_miles == Decimal("20")
    assert result.total_cents == 10500


def test_a003_inside_to_outside(engine: PricingEngine, config: PricingConfiguration) -> None:
    result = engine.calculate(
        standard(
            jobsite_inside_psl=False,
            store_to_jobsite_miles=Decimal("12"),
        ),
        config,
    )
    assert result.total_cents == 9300


def test_a004_outside_to_outside(engine: PricingEngine, config: PricingConfiguration) -> None:
    result = engine.calculate(
        standard(
            store_inside_psl=False,
            jobsite_inside_psl=False,
            boundary_to_store_miles=Decimal("8"),
            store_to_jobsite_miles=Decimal("20"),
        ),
        config,
    )
    assert result.total_cents == 11700


@pytest.mark.parametrize(
    ("hours", "expected"),
    [
        ("2", 10000),
        ("2.1", 16000),
        ("3.0", 16000),
        ("3.1", 22000),
        ("4.5", 28000),
        ("5", 30000),
        ("8", 30000),
    ],
)
def test_a005_through_a010_oversized_boundaries(
    engine: PricingEngine, config: PricingConfiguration, hours: str, expected: int
) -> None:
    result = engine.calculate(
        standard(
            length_inches=Decimal("80"),
            width_inches=Decimal("60"),
            estimated_hours=Decimal(hours),
        ),
        config,
    )
    assert result.total_cents == expected


def test_a011_orientation_swap(engine: PricingEngine, config: PricingConfiguration) -> None:
    assert (
        engine.calculate(
            standard(length_inches=Decimal("58"), width_inches=Decimal("76")), config
        ).total_cents
        == 7500
    )


def test_a012_exact_research_profile_is_not_research(
    engine: PricingEngine, config: PricingConfiguration
) -> None:
    result = engine.calculate(
        standard(
            length_inches=Decimal("126"),
            width_inches=Decimal("70"),
            height_inches=Decimal("28"),
            estimated_hours=Decimal("2"),
        ),
        config,
    )
    assert result.recommended_status == "ready_to_send"
    assert result.total_cents == 10000


def test_a013_research_threshold(engine: PricingEngine, config: PricingConfiguration) -> None:
    result = engine.calculate(
        standard(
            length_inches=Decimal("126.01"),
            width_inches=Decimal("70"),
            height_inches=Decimal("28"),
            estimated_hours=Decimal("2"),
        ),
        config,
    )
    assert result.recommended_status == "research_required"
    assert not result.sendable


def test_a014_research_profile_orientation(
    engine: PricingEngine, config: PricingConfiguration
) -> None:
    result = engine.calculate(
        standard(
            length_inches=Decimal("70"),
            width_inches=Decimal("28"),
            height_inches=Decimal("126"),
            estimated_hours=Decimal("2"),
        ),
        config,
    )
    assert result.recommended_status == "ready_to_send"
    assert result.total_cents == 10000


def test_a015_overweight_is_oversized(engine: PricingEngine, config: PricingConfiguration) -> None:
    result = engine.calculate(standard(overweight=True, estimated_hours=Decimal("1.5")), config)
    assert result.service_class == "oversized"
    assert result.total_cents == 10000


@pytest.mark.parametrize(("stops", "expected"), [(2, 10500), (4, 16500)])
def test_a016_a017_additional_stops(
    engine: PricingEngine, config: PricingConfiguration, stops: int, expected: int
) -> None:
    assert engine.calculate(standard(pickup_stops=stops), config).total_cents == expected


def test_a018_same_day(engine: PricingEngine, config: PricingConfiguration) -> None:
    assert engine.calculate(standard(same_day=True), config).total_cents == 17500


def test_a019_emergency_replaces_same_day(
    engine: PricingEngine, config: PricingConfiguration
) -> None:
    result = engine.calculate(standard(same_day=True, other_client_affected=True), config)
    assert result.total_cents == 32500
    assert [line.code for line in result.charges].count("same_day") == 0
    assert [line.code for line in result.charges].count("emergency_conflict") == 1


@pytest.mark.parametrize(
    ("wait", "sequence", "expected"),
    [(30, 2, 7500), (31, 1, 7500), (31, 2, 12500), (60, 2, 12500), (61, 2, 17500)],
)
def test_a020_through_a024_waiting(
    engine: PricingEngine,
    config: PricingConfiguration,
    wait: int,
    sequence: int,
    expected: int,
) -> None:
    assert (
        engine.calculate(standard(wait_minutes=wait, delay_sequence=sequence), config).total_cents
        == expected
    )


@pytest.mark.parametrize(("minutes", "expected"), [(15, 7500), (16, 9000), (45, 10500)])
def test_a025_through_a027_loading(
    engine: PricingEngine, config: PricingConfiguration, minutes: int, expected: int
) -> None:
    assert engine.calculate(standard(loading_minutes=minutes), config).total_cents == expected


def test_a028_trash(engine: PricingEngine, config: PricingConfiguration) -> None:
    result = engine.calculate(standard(trash_bag_count=6, trash_contents_identified=True), config)
    assert result.total_cents == 13500


def test_a029_unknown_trash(engine: PricingEngine, config: PricingConfiguration) -> None:
    result = engine.calculate(standard(trash_bag_count=1), config)
    assert result.recommended_status == "needs_information"
    assert not result.sendable


def test_a030_hazardous(engine: PricingEngine, config: PricingConfiguration) -> None:
    result = engine.calculate(standard(hazardous=True), config)
    assert result.recommended_status == "declined"
    assert result.total_cents == 0


def test_a031_cancel_after_dispatch(engine: PricingEngine, config: PricingConfiguration) -> None:
    assert engine.calculate(standard(cancelled_after_dispatch=True), config).total_cents == 7500


def test_a032_cancel_with_earned_wait(engine: PricingEngine, config: PricingConfiguration) -> None:
    result = engine.calculate(
        standard(cancelled_after_dispatch=True, wait_minutes=61, delay_sequence=2), config
    )
    assert result.total_cents == 17500
    assert {line.code for line in result.charges} == {
        "cancellation_after_dispatch",
        "earned_waiting",
    }


def test_a033_rental_internal_cost_only(
    engine: PricingEngine, config: PricingConfiguration
) -> None:
    result = engine.calculate(standard(rental_cost_cents=8000), config)
    assert result.total_cents == 7500
    assert result.direct_cost_cents == 8000
    assert result.profit_cents == -500


def test_a034_rental_pass_through(engine: PricingEngine, config: PricingConfiguration) -> None:
    result = engine.calculate(standard(rental_cost_cents=8000, rental_pass_through=True), config)
    assert result.total_cents == 15500
    assert result.direct_cost_cents == 8000
    assert result.profit_cents == 7500


def test_a035_authorized_discount(engine: PricingEngine, config: PricingConfiguration) -> None:
    result = engine.calculate(
        standard(manual_adjustment_cents=-2500, manual_adjustment_reason="Owner-approved discount"),
        config,
    )
    assert result.total_cents == 5000


@pytest.mark.parametrize(
    "input_value",
    [
        standard(store_to_jobsite_miles=Decimal("-1")),
        standard(estimated_hours=Decimal("-1")),
        standard(wait_minutes=-1),
        standard(loading_minutes=-1),
    ],
)
def test_a036_negative_values_rejected(
    engine: PricingEngine, config: PricingConfiguration, input_value: PricingInputs
) -> None:
    with pytest.raises(ValidationError):
        engine.calculate(input_value, config)


def test_a037_missing_oversized_hours(engine: PricingEngine, config: PricingConfiguration) -> None:
    result = engine.calculate(
        standard(length_inches=Decimal("80"), width_inches=Decimal("60")), config
    )
    assert result.recommended_status == "needs_information"
    assert not result.sendable


def test_a038_outside_mileage_missing(engine: PricingEngine, config: PricingConfiguration) -> None:
    result = engine.calculate(
        standard(store_inside_psl=False, boundary_to_store_miles=Decimal("8")), config
    )
    assert result.recommended_status == "needs_information"


def test_a039_research_priority(engine: PricingEngine, config: PricingConfiguration) -> None:
    result = engine.calculate(
        standard(
            length_inches=Decimal("127"),
            width_inches=Decimal("70"),
            height_inches=Decimal("28"),
            same_day=True,
        ),
        config,
    )
    assert result.recommended_status == "research_required"
    assert not result.sendable
    assert result.total_cents == 10000


def test_a040_both_flags_only_emergency(
    engine: PricingEngine, config: PricingConfiguration
) -> None:
    result = engine.calculate(standard(same_day=True, other_client_affected=True), config)
    codes = [line.code for line in result.charges]
    assert "emergency_conflict" in codes
    assert "same_day" not in codes
