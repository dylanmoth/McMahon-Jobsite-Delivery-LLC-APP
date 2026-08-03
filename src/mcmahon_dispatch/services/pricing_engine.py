from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from typing import Any, Mapping

from mcmahon_dispatch.core.enums import QuoteStatus
from mcmahon_dispatch.core.exceptions import ValidationError

ZERO = Decimal("0")
ONE = Decimal("1")


@dataclass(frozen=True, slots=True)
class PricingConfiguration:
    version_code: str
    standard_base_cents: int
    standard_dimensions_inches: tuple[Decimal, Decimal]
    research_dimensions_inches: tuple[Decimal, Decimal, Decimal]
    mileage_rate_cents: int
    oversized_up_to_two_hours_cents: int
    oversized_started_hour_cents: int
    oversized_five_plus_hours_cents: int
    additional_stop_cents: int
    same_day_cents: int
    emergency_conflict_cents: int
    waiting_free_minutes: int
    waiting_started_half_hour_cents: int
    loading_free_minutes: int
    loading_increment_minutes: int
    loading_increment_cents: int
    trash_bag_cents: int
    cancellation_after_dispatch_cents: int
    rental_pass_through_enabled: bool

    @classmethod
    def from_mapping(
        cls, version_code: str, settings: Mapping[str, Any]
    ) -> "PricingConfiguration":
        standard = settings.get("standard_dimensions_inches", [76, 58])
        research = settings.get("research_dimensions_inches", [126, 70, 28])
        return cls(
            version_code=version_code,
            standard_base_cents=int(settings["standard_base_cents"]),
            standard_dimensions_inches=tuple(Decimal(str(value)) for value in standard),  # type: ignore[arg-type]
            research_dimensions_inches=tuple(Decimal(str(value)) for value in research),  # type: ignore[arg-type]
            mileage_rate_cents=int(settings["mileage_rate_cents"]),
            oversized_up_to_two_hours_cents=int(
                settings["oversized_up_to_two_hours_cents"]
            ),
            oversized_started_hour_cents=int(settings["oversized_started_hour_cents"]),
            oversized_five_plus_hours_cents=int(
                settings["oversized_five_plus_hours_cents"]
            ),
            additional_stop_cents=int(settings["additional_stop_cents"]),
            same_day_cents=int(settings["same_day_cents"]),
            emergency_conflict_cents=int(settings["emergency_conflict_cents"]),
            waiting_free_minutes=int(settings["waiting_free_minutes"]),
            waiting_started_half_hour_cents=int(
                settings["waiting_started_half_hour_cents"]
            ),
            loading_free_minutes=int(settings["loading_free_minutes"]),
            loading_increment_minutes=int(settings["loading_increment_minutes"]),
            loading_increment_cents=int(settings["loading_increment_cents"]),
            trash_bag_cents=int(settings["trash_bag_cents"]),
            cancellation_after_dispatch_cents=int(
                settings["cancellation_after_dispatch_cents"]
            ),
            rental_pass_through_enabled=bool(
                settings.get("rental_pass_through_enabled", False)
            ),
        )


@dataclass(frozen=True, slots=True)
class PricingInputs:
    length_inches: Decimal | None = None
    width_inches: Decimal | None = None
    height_inches: Decimal | None = None
    overweight: bool | None = None
    hazardous: bool | None = False
    prohibited_reason: str = ""
    estimated_hours: Decimal | None = None

    store_inside_psl: bool | None = None
    jobsite_inside_psl: bool | None = None
    boundary_to_store_miles: Decimal | None = None
    store_to_jobsite_miles: Decimal | None = None
    pickup_stops: int = 1

    same_day: bool = False
    other_client_affected: bool = False
    wait_minutes: int = 0
    delay_sequence: int = 1
    loading_minutes: int = 0
    trash_bag_count: int = 0
    trash_contents_identified: bool = False
    cancelled_after_dispatch: bool = False

    tolls_cents: int = 0
    tolls_pass_through: bool = False
    parking_cents: int = 0
    parking_pass_through: bool = False
    rental_cost_cents: int = 0
    rental_pass_through: bool | None = None
    rental_markup_cents: int = 0

    fuel_cost_cents: int = 0
    helper_cost_cents: int = 0
    securement_cost_cents: int = 0
    processing_fee_cents: int = 0
    other_direct_cost_cents: int = 0

    manual_adjustment_cents: int = 0
    manual_adjustment_reason: str = ""


@dataclass(frozen=True, slots=True)
class ChargeLine:
    code: str
    description: str
    quantity: Decimal
    rate_cents: int
    total_cents: int
    internal_cost_cents: int = 0
    rule_id: str | None = None
    reason: str = ""
    customer_visible: bool = True
    manual: bool = False


@dataclass(frozen=True, slots=True)
class PricingWarning:
    code: str
    severity: str
    message: str
    next_action: str
    rule_id: str | None = None


@dataclass(frozen=True, slots=True)
class PricingResult:
    charges: tuple[ChargeLine, ...]
    warnings: tuple[PricingWarning, ...]
    total_cents: int
    direct_cost_cents: int
    profit_cents: int
    margin_basis_points: int | None
    confidence: str
    recommended_status: str
    manual_review_required: bool
    sendable: bool
    service_class: str
    chargeable_miles: Decimal
    pricing_version_code: str


class PricingEngine:
    """Pure SRS v1.0 pricing engine. No GUI, database, or provider dependencies."""

    def calculate(
        self, inputs: PricingInputs, configuration: PricingConfiguration
    ) -> PricingResult:
        self._validate_nonnegative(inputs)
        if inputs.manual_adjustment_cents and not inputs.manual_adjustment_reason.strip():
            raise ValidationError("A reason is required for a manual price adjustment.")
        if inputs.rental_markup_cents and inputs.rental_cost_cents <= 0:
            raise ValidationError("Rental markup requires an entered rental cost.")

        charges: list[ChargeLine] = []
        warnings: list[PricingWarning] = []
        critical_missing = False
        research = False
        hazardous = inputs.hazardous is True
        service_class = "undetermined"

        if hazardous:
            reason = inputs.prohibited_reason.strip() or "Hazardous or prohibited material selected."
            warnings.append(
                PricingWarning(
                    "hazardous_material",
                    "danger",
                    reason,
                    "Decline the request. McMahon Jobsite Delivery does not transport hazardous materials.",
                    "BR-PRICE-001",
                )
            )
            return self._result(
                (), warnings, inputs, configuration, ZERO, "declined", "hazardous", True, False
            )

        dimensions = self._dimensions(inputs)
        if dimensions is None:
            critical_missing = True
            warnings.append(
                PricingWarning(
                    "dimensions_missing",
                    "danger",
                    "Load dimensions are incomplete.",
                    "Confirm length, width, and height before sending the quote.",
                    "FR-QUOTE-006",
                )
            )
        else:
            research_profile = tuple(sorted(configuration.research_dimensions_inches))
            if any(actual > limit for actual, limit in zip(dimensions, research_profile, strict=True)):
                research = True
                service_class = "research"
                warnings.append(
                    PricingWarning(
                        "research_dimensions",
                        "danger",
                        "The oriented load dimensions exceed 126 × 70 × 28 inches.",
                        "Perform manual vehicle, legal, and rental research before approval.",
                        "BR-PRICE-002",
                    )
                )

        if inputs.overweight is None:
            critical_missing = True
            warnings.append(
                PricingWarning(
                    "weight_unconfirmed",
                    "warning",
                    "Weight or overweight status has not been confirmed.",
                    "Verify the material weight and vehicle payload before sending.",
                    "BR-PRICE-003",
                )
            )

        if not research and dimensions is not None:
            standard_profile = tuple(sorted(configuration.standard_dimensions_inches))
            planar = tuple(sorted(dimensions, reverse=True)[:2])
            standard_sorted = tuple(sorted(standard_profile, reverse=True))
            fits_standard = all(
                actual <= limit for actual, limit in zip(planar, standard_sorted, strict=True)
            )
            is_oversized = inputs.overweight is True or not fits_standard
            if is_oversized:
                service_class = "oversized"
                if inputs.estimated_hours is None or inputs.estimated_hours <= ZERO:
                    critical_missing = True
                    warnings.append(
                        PricingWarning(
                            "oversized_hours_missing",
                            "danger",
                            "Oversized service requires an estimated duration greater than zero.",
                            "Enter the expected service hours before sending.",
                            "BR-PRICE-005",
                        )
                    )
                else:
                    service_fee = self._oversized_fee(
                        inputs.estimated_hours, configuration
                    )
                    charges.append(
                        ChargeLine(
                            "oversized_service",
                            "Oversized delivery service",
                            inputs.estimated_hours,
                            service_fee,
                            service_fee,
                            rule_id="BR-PRICE-005",
                            reason=self._oversized_reason(inputs.estimated_hours),
                        )
                    )
            else:
                service_class = "standard"
                charges.append(
                    ChargeLine(
                        "standard_service",
                        "Standard store-to-jobsite delivery",
                        ONE,
                        configuration.standard_base_cents,
                        configuration.standard_base_cents,
                        rule_id="BR-PRICE-004",
                        reason="Confirmed standard fit, not overweight, subject to PSL mileage rules.",
                    )
                )

        chargeable_miles, mileage_missing = self._chargeable_miles(inputs)
        if mileage_missing:
            critical_missing = True
            warnings.append(
                PricingWarning(
                    "mileage_missing",
                    "danger",
                    "Outside-PSL mileage is required but incomplete.",
                    "Enter boundary-to-store and store-to-jobsite miles as applicable.",
                    "BR-PRICE-MILEAGE",
                )
            )
        elif chargeable_miles > ZERO:
            mileage_total = self._money_product(
                chargeable_miles, configuration.mileage_rate_cents
            )
            charges.append(
                ChargeLine(
                    "mileage",
                    "Chargeable mileage",
                    chargeable_miles,
                    configuration.mileage_rate_cents,
                    mileage_total,
                    rule_id="BR-PRICE-MILEAGE",
                    reason=f"{self._decimal_text(chargeable_miles)} chargeable miles at $1.50 per mile.",
                )
            )

        extra_stops = max(0, inputs.pickup_stops - 1)
        if extra_stops:
            charges.append(
                ChargeLine(
                    "additional_stop",
                    "Additional pickup stop",
                    Decimal(extra_stops),
                    configuration.additional_stop_cents,
                    extra_stops * configuration.additional_stop_cents,
                    rule_id="BR-PRICE-STOPS",
                    reason="The first pickup stop is included; each additional pickup stop is $30.",
                )
            )

        if inputs.other_client_affected:
            charges.append(
                ChargeLine(
                    "emergency_conflict",
                    "Emergency scheduling conflict",
                    ONE,
                    configuration.emergency_conflict_cents,
                    configuration.emergency_conflict_cents,
                    rule_id="BR-PRICE-EMERGENCY",
                    reason="Another scheduled client will be affected; this replaces the same-day fee.",
                )
            )
            warnings.append(
                PricingWarning(
                    "emergency_contact_required",
                    "warning",
                    "Another client is affected by this emergency request.",
                    "Confirm the current client accepts the $250 fee, contact the displaced client, and document any service-recovery discount.",
                    "FR-DISP-006",
                )
            )
        elif inputs.same_day:
            charges.append(
                ChargeLine(
                    "same_day",
                    "Same-day service without notice",
                    ONE,
                    configuration.same_day_cents,
                    configuration.same_day_cents,
                    rule_id="BR-PRICE-SAME-DAY",
                    reason="Same-day request with no other scheduled client affected.",
                )
            )

        waiting_cents = self._waiting_charge(inputs, configuration, warnings)
        if waiting_cents:
            increments = Decimal(waiting_cents) / Decimal(
                configuration.waiting_started_half_hour_cents
            )
            charges.append(
                ChargeLine(
                    "waiting",
                    "Customer delay waiting charge",
                    increments,
                    configuration.waiting_started_half_hour_cents,
                    waiting_cents,
                    rule_id="BR-PRICE-WAITING",
                    reason="Second or later delay: $50 per started half-hour after the free first 30 minutes.",
                )
            )

        loading_cents = self._loading_charge(inputs, configuration)
        if loading_cents:
            increments = Decimal(loading_cents) / Decimal(configuration.loading_increment_cents)
            charges.append(
                ChargeLine(
                    "loading_unloading",
                    "Loading / unloading assistance",
                    increments,
                    configuration.loading_increment_cents,
                    loading_cents,
                    rule_id="BR-PRICE-LOADING",
                    reason="First 15 minutes included; then $15 per started 15-minute increment.",
                )
            )

        if inputs.trash_bag_count:
            if not inputs.trash_contents_identified:
                critical_missing = True
                warnings.append(
                    PricingWarning(
                        "trash_contents_unknown",
                        "danger",
                        "Trash contents have not been identified as non-hazardous contractor bags.",
                        "Identify the contents or remove trash service from the quote.",
                        "BR-PRICE-TRASH",
                    )
                )
            else:
                charges.append(
                    ChargeLine(
                        "trash_bags",
                        "Identified non-hazardous contractor bag",
                        Decimal(inputs.trash_bag_count),
                        configuration.trash_bag_cents,
                        inputs.trash_bag_count * configuration.trash_bag_cents,
                        rule_id="BR-PRICE-TRASH",
                        reason="Trash service excludes dump, landfill, and transfer-station trips.",
                    )
                )

        internal_costs = self._direct_costs(inputs)
        charges.extend(self._pass_through_lines(inputs, configuration))

        if inputs.cancelled_after_dispatch:
            charges = [
                ChargeLine(
                    "cancellation_after_dispatch",
                    "Cancellation after dispatch",
                    ONE,
                    configuration.cancellation_after_dispatch_cents,
                    configuration.cancellation_after_dispatch_cents,
                    rule_id="BR-PRICE-CANCELLATION",
                    reason="Cancellation after dispatch replaces unearned automatic service surcharges.",
                )
            ]
            if waiting_cents:
                charges.append(
                    ChargeLine(
                        "earned_waiting",
                        "Earned waiting before cancellation",
                        Decimal(waiting_cents)
                        / Decimal(configuration.waiting_started_half_hour_cents),
                        configuration.waiting_started_half_hour_cents,
                        waiting_cents,
                        rule_id="BR-PRICE-CANCELLATION",
                        reason="Earned waiting remains billable after cancellation.",
                    )
                )
            service_class = "cancelled"

        if inputs.manual_adjustment_cents:
            charges.append(
                ChargeLine(
                    "manual_adjustment",
                    "Manual adjustment",
                    ONE,
                    inputs.manual_adjustment_cents,
                    inputs.manual_adjustment_cents,
                    rule_id="BR-PRICE-MANUAL",
                    reason=inputs.manual_adjustment_reason.strip(),
                    manual=True,
                )
            )

        if research:
            recommended_status = QuoteStatus.RESEARCH_REQUIRED.value
            sendable = False
            manual_review = True
        elif critical_missing:
            recommended_status = QuoteStatus.NEEDS_INFORMATION.value
            sendable = False
            manual_review = True
        else:
            recommended_status = QuoteStatus.READY_TO_SEND.value
            sendable = True
            manual_review = bool(inputs.other_client_affected)

        return self._result(
            charges,
            warnings,
            inputs,
            configuration,
            chargeable_miles,
            recommended_status,
            service_class,
            manual_review,
            sendable,
            direct_costs=internal_costs,
        )

    @staticmethod
    def _validate_nonnegative(inputs: PricingInputs) -> None:
        decimal_fields = {
            "length": inputs.length_inches,
            "width": inputs.width_inches,
            "height": inputs.height_inches,
            "estimated hours": inputs.estimated_hours,
            "boundary-to-store miles": inputs.boundary_to_store_miles,
            "store-to-jobsite miles": inputs.store_to_jobsite_miles,
        }
        for label, value in decimal_fields.items():
            if value is not None and value < ZERO:
                raise ValidationError(f"{label.title()} cannot be negative.")
        integer_fields = {
            "pickup stops": inputs.pickup_stops,
            "wait minutes": inputs.wait_minutes,
            "delay sequence": inputs.delay_sequence,
            "loading minutes": inputs.loading_minutes,
            "trash bag count": inputs.trash_bag_count,
            "tolls": inputs.tolls_cents,
            "parking": inputs.parking_cents,
            "rental cost": inputs.rental_cost_cents,
            "rental markup": inputs.rental_markup_cents,
            "fuel cost": inputs.fuel_cost_cents,
            "helper cost": inputs.helper_cost_cents,
            "securement cost": inputs.securement_cost_cents,
            "processing fee": inputs.processing_fee_cents,
            "other direct cost": inputs.other_direct_cost_cents,
        }
        for label, value in integer_fields.items():
            if value < 0:
                raise ValidationError(f"{label.title()} cannot be negative.")
        if inputs.pickup_stops < 1:
            raise ValidationError("Pickup stops must be at least one.")
        if inputs.delay_sequence < 1:
            raise ValidationError("Delay sequence must be at least one.")

    @staticmethod
    def _dimensions(inputs: PricingInputs) -> tuple[Decimal, Decimal, Decimal] | None:
        values = (inputs.length_inches, inputs.width_inches, inputs.height_inches)
        if any(value is None or value <= ZERO for value in values):
            return None
        return tuple(sorted(value for value in values if value is not None))  # type: ignore[return-value]

    @staticmethod
    def _oversized_fee(hours: Decimal, config: PricingConfiguration) -> int:
        if hours <= Decimal("2"):
            return config.oversized_up_to_two_hours_cents
        if hours >= Decimal("5"):
            return config.oversized_five_plus_hours_cents
        started_hours = int((hours - Decimal("2")).to_integral_value(rounding=ROUND_CEILING))
        return config.oversized_up_to_two_hours_cents + (
            started_hours * config.oversized_started_hour_cents
        )

    @staticmethod
    def _oversized_reason(hours: Decimal) -> str:
        if hours <= Decimal("2"):
            return "Oversized service up to two hours uses the $100 service fee."
        if hours >= Decimal("5"):
            return "Oversized service of five or more hours uses the $300 all-day total."
        return "After two hours, each started hour adds $60 until the five-hour all-day threshold."

    @staticmethod
    def _chargeable_miles(inputs: PricingInputs) -> tuple[Decimal, bool]:
        if inputs.store_inside_psl is None or inputs.jobsite_inside_psl is None:
            return ZERO, True
        store_to_jobsite = inputs.store_to_jobsite_miles
        boundary_to_store = inputs.boundary_to_store_miles
        if inputs.store_inside_psl and inputs.jobsite_inside_psl:
            return ZERO, False
        if store_to_jobsite is None:
            return ZERO, True
        if inputs.store_inside_psl and not inputs.jobsite_inside_psl:
            return store_to_jobsite, False
        if not inputs.store_inside_psl:
            if boundary_to_store is None:
                return ZERO, True
            return boundary_to_store + store_to_jobsite, False
        return ZERO, True

    @staticmethod
    def _waiting_charge(
        inputs: PricingInputs,
        config: PricingConfiguration,
        warnings: list[PricingWarning],
    ) -> int:
        if inputs.wait_minutes <= config.waiting_free_minutes:
            return 0
        if inputs.delay_sequence <= 1:
            warnings.append(
                PricingWarning(
                    "first_delay_documented",
                    "warning",
                    "This is the customer's first delay over 30 minutes; no waiting fee is charged.",
                    "Document the first delay and explain the future waiting-fee policy.",
                    "BR-PRICE-WAITING",
                )
            )
            return 0
        extra = Decimal(inputs.wait_minutes - config.waiting_free_minutes)
        increments = int((extra / Decimal("30")).to_integral_value(rounding=ROUND_CEILING))
        return increments * config.waiting_started_half_hour_cents

    @staticmethod
    def _loading_charge(inputs: PricingInputs, config: PricingConfiguration) -> int:
        if inputs.loading_minutes <= config.loading_free_minutes:
            return 0
        extra = Decimal(inputs.loading_minutes - config.loading_free_minutes)
        increments = int(
            (extra / Decimal(config.loading_increment_minutes)).to_integral_value(
                rounding=ROUND_CEILING
            )
        )
        return increments * config.loading_increment_cents

    @staticmethod
    def _direct_costs(inputs: PricingInputs) -> int:
        return sum(
            (
                inputs.fuel_cost_cents,
                inputs.tolls_cents,
                inputs.parking_cents,
                inputs.rental_cost_cents,
                inputs.helper_cost_cents,
                inputs.securement_cost_cents,
                inputs.processing_fee_cents,
                inputs.other_direct_cost_cents,
            )
        )

    @staticmethod
    def _pass_through_lines(
        inputs: PricingInputs, config: PricingConfiguration
    ) -> list[ChargeLine]:
        lines: list[ChargeLine] = []
        if inputs.tolls_cents and inputs.tolls_pass_through:
            lines.append(
                ChargeLine(
                    "tolls",
                    "Tolls",
                    ONE,
                    inputs.tolls_cents,
                    inputs.tolls_cents,
                    internal_cost_cents=inputs.tolls_cents,
                    rule_id="BR-PRICE-PASS-THROUGH",
                    reason="Entered actual toll cost passed through to the customer.",
                )
            )
        if inputs.parking_cents and inputs.parking_pass_through:
            lines.append(
                ChargeLine(
                    "parking",
                    "Parking",
                    ONE,
                    inputs.parking_cents,
                    inputs.parking_cents,
                    internal_cost_cents=inputs.parking_cents,
                    rule_id="BR-PRICE-PASS-THROUGH",
                    reason="Entered actual parking cost passed through to the customer.",
                )
            )
        rental_pass_through = (
            config.rental_pass_through_enabled
            if inputs.rental_pass_through is None
            else inputs.rental_pass_through
        )
        if inputs.rental_cost_cents and rental_pass_through:
            customer_charge = inputs.rental_cost_cents + inputs.rental_markup_cents
            lines.append(
                ChargeLine(
                    "rental",
                    "Rental vehicle",
                    ONE,
                    customer_charge,
                    customer_charge,
                    internal_cost_cents=inputs.rental_cost_cents,
                    rule_id="BR-PRICE-RENTAL",
                    reason="Actual rental cost passed through"
                    + (
                        f" with a {inputs.rental_markup_cents / 100:.2f} markup."
                        if inputs.rental_markup_cents
                        else "."
                    ),
                )
            )
        return lines

    def _result(
        self,
        charges: tuple[ChargeLine, ...] | list[ChargeLine],
        warnings: tuple[PricingWarning, ...] | list[PricingWarning],
        inputs: PricingInputs,
        configuration: PricingConfiguration,
        chargeable_miles: Decimal,
        recommended_status: str,
        service_class: str,
        manual_review: bool,
        sendable: bool,
        *,
        direct_costs: int | None = None,
    ) -> PricingResult:
        charge_tuple = tuple(charges)
        warning_tuple = tuple(warnings)
        total = max(0, sum(line.total_cents for line in charge_tuple))
        costs = self._direct_costs(inputs) if direct_costs is None else direct_costs
        profit = total - costs
        margin = int((Decimal(profit) / Decimal(total) * Decimal("10000")).quantize(ONE)) if total else None
        confidence = self._confidence(
            total, margin, warning_tuple, inputs, recommended_status
        )
        return PricingResult(
            charges=charge_tuple,
            warnings=warning_tuple,
            total_cents=total,
            direct_cost_cents=costs,
            profit_cents=profit,
            margin_basis_points=margin,
            confidence=confidence,
            recommended_status=recommended_status,
            manual_review_required=manual_review,
            sendable=sendable,
            service_class=service_class,
            chargeable_miles=chargeable_miles,
            pricing_version_code=configuration.version_code,
        )

    @staticmethod
    def _confidence(
        total: int,
        margin: int | None,
        warnings: tuple[PricingWarning, ...],
        inputs: PricingInputs,
        status: str,
    ) -> str:
        if status in {
            QuoteStatus.RESEARCH_REQUIRED.value,
            QuoteStatus.NEEDS_INFORMATION.value,
            QuoteStatus.DECLINED.value,
        } or not total:
            return "Research / Decline"
        has_risk = (
            inputs.overweight is None
            or inputs.wait_minutes > 0
            or inputs.rental_cost_cents > 0
            or inputs.other_client_affected
            or any(item.severity == "danger" for item in warnings)
        )
        if margin is None or margin < 4500 or has_risk:
            return "Reconsider"
        if margin < 6000 or len(warnings) == 1:
            return "Acceptable Margin"
        if not warnings and margin >= 6000:
            return "High"
        return "Acceptable Margin"

    @staticmethod
    def _money_product(quantity: Decimal, rate_cents: int) -> int:
        return int((quantity * Decimal(rate_cents)).quantize(ONE, rounding=ROUND_HALF_UP))

    @staticmethod
    def _decimal_text(value: Decimal) -> str:
        return format(value.normalize(), "f")
