from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from mcmahon_dispatch.core.enums import QuoteStatus, StopType
from mcmahon_dispatch.core.exceptions import ValidationError
from mcmahon_dispatch.database.models import (
    AuditEvent,
    QuickCallNote,
    Quote,
    QuoteCharge,
    QuoteIntake,
    QuoteLoad,
    QuoteRevision,
    QuoteStop,
)
from mcmahon_dispatch.documents.quote_pdf import (
    CallSheetPdfData,
    DEFAULT_TERMS,
    QuotePdfData,
    QuotePdfGenerator,
)
from mcmahon_dispatch.repositories.quote_repository import (
    CustomerChoice,
    QuoteRepository,
    QuoteSummary,
)
from mcmahon_dispatch.services.pricing_engine import (
    PricingConfiguration,
    PricingEngine,
    PricingInputs,
    PricingResult,
    PricingWarning,
)


@dataclass(frozen=True, slots=True)
class QuoteDraftRequest:
    customer_id: str | None = None
    requested_service_at: datetime | None = None
    expires_at: datetime | None = None
    customer_notes: str = ""
    internal_notes: str = ""
    dispatch_notes: str = ""

    customer_contact_name: str = ""
    customer_contact_phone: str = ""
    customer_contact_email: str = ""

    supplier_name: str = ""
    supplier_address: str = ""
    supplier_contact: str = ""
    order_number: str = ""
    order_paid: bool | None = None
    order_ready: bool | None = None
    pickup_authorization: str = ""
    pickup_instructions: str = ""

    jobsite_address: str = ""
    site_contact: str = ""
    access_instructions: str = ""
    delivery_window: str = ""

    materials: str = ""
    quantity: Decimal = Decimal("1")
    length_inches: Decimal | None = None
    width_inches: Decimal | None = None
    height_inches: Decimal | None = None
    weight_pounds: Decimal | None = None
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

    def pricing_inputs(self) -> PricingInputs:
        return PricingInputs(
            length_inches=self.length_inches,
            width_inches=self.width_inches,
            height_inches=self.height_inches,
            overweight=self.overweight,
            hazardous=self.hazardous,
            prohibited_reason=self.prohibited_reason,
            estimated_hours=self.estimated_hours,
            store_inside_psl=self.store_inside_psl,
            jobsite_inside_psl=self.jobsite_inside_psl,
            boundary_to_store_miles=self.boundary_to_store_miles,
            store_to_jobsite_miles=self.store_to_jobsite_miles,
            pickup_stops=self.pickup_stops,
            same_day=self.same_day,
            other_client_affected=self.other_client_affected,
            wait_minutes=self.wait_minutes,
            delay_sequence=self.delay_sequence,
            loading_minutes=self.loading_minutes,
            trash_bag_count=self.trash_bag_count,
            trash_contents_identified=self.trash_contents_identified,
            cancelled_after_dispatch=self.cancelled_after_dispatch,
            tolls_cents=self.tolls_cents,
            tolls_pass_through=self.tolls_pass_through,
            parking_cents=self.parking_cents,
            parking_pass_through=self.parking_pass_through,
            rental_cost_cents=self.rental_cost_cents,
            rental_pass_through=self.rental_pass_through,
            rental_markup_cents=self.rental_markup_cents,
            fuel_cost_cents=self.fuel_cost_cents,
            helper_cost_cents=self.helper_cost_cents,
            securement_cost_cents=self.securement_cost_cents,
            processing_fee_cents=self.processing_fee_cents,
            other_direct_cost_cents=self.other_direct_cost_cents,
            manual_adjustment_cents=self.manual_adjustment_cents,
            manual_adjustment_reason=self.manual_adjustment_reason,
        )


@dataclass(frozen=True, slots=True)
class QuickNoteRequest:
    company_contact: str = ""
    phone: str = ""
    email: str = ""
    supplier_address: str = ""
    jobsite_address: str = ""
    materials: str = ""
    dimensions_text: str = ""
    weight_text: str = ""
    overweight: bool | None = None
    pickup_stops: int | None = None
    order_ready: bool | None = None
    same_day: bool | None = None
    store_outside_psl: bool | None = None
    jobsite_outside_psl: bool | None = None
    miles_text: str = ""
    wait_text: str = ""
    trash_text: str = ""
    vehicle_text: str = ""
    other_client_scheduled: bool | None = None
    general_notes: str = ""


@dataclass(frozen=True, slots=True)
class SavedQuote:
    id: str
    quote_number: str
    status: str
    revision_number: int
    pricing: PricingResult


@dataclass(frozen=True, slots=True)
class QuoteEditorRecord:
    id: str
    quote_number: str
    status: str
    revision_number: int
    request: QuoteDraftRequest
    pricing: PricingResult


class QuoteService:
    def __init__(
        self,
        factory: sessionmaker[Session],
        organization_id: str,
        user_id: str,
        documents_root: Path,
        logo_path: Path,
        *,
        can_override_price: bool,
        can_write: bool,
    ) -> None:
        self.factory = factory
        self.organization_id = organization_id
        self.user_id = user_id
        self.documents_root = documents_root
        self.can_override_price = can_override_price
        self.can_write = can_write
        self.engine = PricingEngine()
        self.pdf = QuotePdfGenerator(logo_path)

    def customers(self) -> list[CustomerChoice]:
        with self.factory() as session:
            return QuoteRepository(session, self.organization_id).customer_choices()

    def quotes(self, query: str = "") -> list[QuoteSummary]:
        with self.factory() as session:
            return QuoteRepository(session, self.organization_id).list_quotes(query)

    def calculate(self, request: QuoteDraftRequest) -> PricingResult:
        if request.manual_adjustment_cents and not self.can_override_price:
            raise ValidationError("Your account is not permitted to override quote pricing.")
        with self.factory() as session:
            pricing = QuoteRepository(session, self.organization_id).active_pricing()
            configuration = PricingConfiguration.from_mapping(
                pricing.version_code, pricing.settings_json
            )
        result = self.engine.calculate(request.pricing_inputs(), configuration)
        return self._operationalize_result(request, result)

    def save_draft(self, request: QuoteDraftRequest, quote_id: str | None = None) -> SavedQuote:
        self._ensure_write()
        if not request.customer_id:
            raise ValidationError("Select a customer before saving the quote.")
        if request.manual_adjustment_cents and not self.can_override_price:
            raise ValidationError("Your account is not permitted to override quote pricing.")

        with self.factory.begin() as session:
            repo = QuoteRepository(session, self.organization_id)
            customer = repo.customer(request.customer_id)
            if customer is None:
                raise ValidationError("The selected customer is unavailable.")
            if customer.status == "do_not_serve":
                raise ValidationError("This customer is marked Do Not Serve.")

            pricing_version = repo.active_pricing()
            configuration = PricingConfiguration.from_mapping(
                pricing_version.version_code, pricing_version.settings_json
            )
            result = self._operationalize_result(
                request, self.engine.calculate(request.pricing_inputs(), configuration)
            )

            quote = repo.get(quote_id) if quote_id else None
            if quote_id and quote is None:
                raise ValidationError("The quote could not be found.")
            if quote is None:
                quote = Quote(
                    organization_id=self.organization_id,
                    customer_id=customer.id,
                    quote_number=repo.next_quote_number(customer.company_name),
                    status=result.recommended_status,
                    current_revision_number=1,
                    created_by_id=self.user_id,
                    updated_by_id=self.user_id,
                )
                session.add(quote)
                session.flush()
                intake = QuoteIntake(
                    organization_id=self.organization_id,
                    quote_id=quote.id,
                    created_by_id=self.user_id,
                    updated_by_id=self.user_id,
                )
                session.add(intake)
                quote.intake = intake
                revision = QuoteRevision(
                    organization_id=self.organization_id,
                    quote_id=quote.id,
                    revision_number=1,
                    pricing_version_id=pricing_version.id,
                    status=result.recommended_status,
                    terms_snapshot=DEFAULT_TERMS,
                    configuration_snapshot_json={},
                    confidence=result.confidence,
                    created_by_id=self.user_id,
                    updated_by_id=self.user_id,
                )
                session.add(revision)
                quote.revisions.append(revision)
                session.flush()
            else:
                quote.customer_id = customer.id
                mutable_statuses = {
                    QuoteStatus.DRAFT.value,
                    QuoteStatus.NEEDS_INFORMATION.value,
                    QuoteStatus.RESEARCH_REQUIRED.value,
                    QuoteStatus.READY_TO_SEND.value,
                }
                revision = repo.current_revision(quote)
                if revision is None:
                    raise ValidationError("The quote has no current revision.")
                if quote.status not in mutable_statuses:
                    quote.current_revision_number += 1
                    revision = QuoteRevision(
                        organization_id=self.organization_id,
                        quote_id=quote.id,
                        revision_number=quote.current_revision_number,
                        pricing_version_id=pricing_version.id,
                        status=result.recommended_status,
                        terms_snapshot=DEFAULT_TERMS,
                        configuration_snapshot_json={},
                        change_summary="Updated after a frozen revision.",
                        confidence=result.confidence,
                        created_by_id=self.user_id,
                        updated_by_id=self.user_id,
                    )
                    session.add(revision)
                    quote.revisions.append(revision)
                    session.flush()
                else:
                    repo.clear_revision_detail(revision)
                    revision.pricing_version_id = pricing_version.id

            self._apply_quote(quote, request, result)
            if quote.intake is None:
                quote.intake = QuoteIntake(
                    organization_id=self.organization_id,
                    quote_id=quote.id,
                    created_by_id=self.user_id,
                )
            self._apply_intake(quote.intake, request)
            self._apply_revision(
                session, revision, quote, request, result, pricing_version.settings_json
            )
            self._audit(
                session,
                "quote.saved",
                quote.id,
                {
                    "quote_number": quote.quote_number,
                    "revision": revision.revision_number,
                    "status": quote.status,
                    "total_cents": result.total_cents,
                    "pricing_version": pricing_version.version_code,
                },
            )
            session.flush()
            return SavedQuote(
                id=quote.id,
                quote_number=quote.quote_number,
                status=quote.status,
                revision_number=revision.revision_number,
                pricing=result,
            )

    def load(self, quote_id: str) -> QuoteEditorRecord:
        with self.factory() as session:
            repo = QuoteRepository(session, self.organization_id)
            quote = repo.get(quote_id)
            if quote is None or quote.intake is None:
                raise ValidationError("The quote could not be loaded.")
            request = self._request_from_quote(quote)
            pricing_version = repo.active_pricing()
            current = repo.current_revision(quote)
            if current is not None:
                pricing_version = current.pricing_version
            configuration = PricingConfiguration.from_mapping(
                pricing_version.version_code, pricing_version.settings_json
            )
            result = self._operationalize_result(
                request, self.engine.calculate(request.pricing_inputs(), configuration)
            )
            return QuoteEditorRecord(
                id=quote.id,
                quote_number=quote.quote_number,
                status=quote.status,
                revision_number=quote.current_revision_number,
                request=request,
                pricing=result,
            )

    def generate_quote_pdf(
        self, request: QuoteDraftRequest, quote_id: str | None = None
    ) -> tuple[SavedQuote, Path]:
        saved = self.save_draft(request, quote_id)
        if not saved.pricing.sendable:
            messages = "\n".join(f"• {warning.message}" for warning in saved.pricing.warnings)
            raise ValidationError(
                "This quote cannot be generated for the customer until required information or review is complete."
                + (f"\n\n{messages}" if messages else "")
            )
        with self.factory.begin() as session:
            repo = QuoteRepository(session, self.organization_id)
            quote = repo.get(saved.id)
            if quote is None or quote.intake is None:
                raise ValidationError("The saved quote could not be reloaded for PDF generation.")
            customer = quote.customer
            if customer is None:
                raise ValidationError("The quote does not have a customer.")
            revision = repo.current_revision(quote)
            if revision is None:
                raise ValidationError("The quote has no current revision.")
            directory = self.documents_root / "quotes" / f"{datetime.now():%Y}"
            file_name = (
                f"{quote.quote_number}-R{revision.revision_number}-"
                f"{datetime.now():%Y%m%d-%H%M%S-%f}.pdf"
            )
            destination = directory / file_name
            data = QuotePdfData(
                quote_number=quote.quote_number,
                generated_at=datetime.now(UTC),
                expires_at=quote.expires_at,
                status=quote.status,
                customer_name=customer.company_name,
                contact_name=quote.intake.customer_contact_name,
                contact_phone=quote.intake.customer_contact_phone or customer.primary_phone or "",
                contact_email=quote.intake.customer_contact_email or customer.primary_email or "",
                supplier_name=quote.intake.supplier_name,
                supplier_address=quote.intake.supplier_address,
                order_number=quote.intake.order_number,
                jobsite_address=quote.intake.jobsite_address,
                site_contact=quote.intake.site_contact,
                requested_window=quote.intake.delivery_window,
                service_description=self._service_description(saved.pricing),
                materials=quote.intake.materials,
                customer_notes=quote.customer_notes,
                charges=saved.pricing.charges,
                total_cents=saved.pricing.total_cents,
                terms=revision.terms_snapshot,
            )
            self.pdf.build_quote(destination, data)
            digest = hashlib.sha256(destination.read_bytes()).hexdigest()
            repo.add_document(
                title=f"Quote {quote.quote_number} Revision {revision.revision_number}",
                file_name=file_name,
                storage_key=str(destination),
                mime_type="application/pdf",
                size_bytes=destination.stat().st_size,
                checksum_sha256=digest,
                uploader_user_id=self.user_id,
                quote_id=quote.id,
                metadata={
                    "revision_number": revision.revision_number,
                    "pricing_version": saved.pricing.pricing_version_code,
                    "total_cents": saved.pricing.total_cents,
                },
            )
            self._audit(
                session,
                "quote.pdf_generated",
                quote.id,
                {"path": str(destination), "revision": revision.revision_number},
            )
            return saved, destination

    def save_quick_note(self, request: QuickNoteRequest, quote_id: str | None = None) -> str:
        self._ensure_write()
        if not any(
            value.strip()
            for value in (
                request.company_contact,
                request.phone,
                request.email,
                request.supplier_address,
                request.jobsite_address,
                request.materials,
                request.general_notes,
            )
        ):
            raise ValidationError("Enter at least one quick-note value before saving.")
        with self.factory.begin() as session:
            note = QuickCallNote(
                organization_id=self.organization_id,
                quote_id=quote_id,
                company_contact=request.company_contact.strip(),
                phone=request.phone.strip(),
                email=request.email.strip().lower(),
                supplier_address=request.supplier_address.strip(),
                jobsite_address=request.jobsite_address.strip(),
                materials=request.materials.strip(),
                dimensions_text=request.dimensions_text.strip(),
                weight_text=request.weight_text.strip(),
                overweight=request.overweight,
                pickup_stops=request.pickup_stops,
                order_ready=request.order_ready,
                same_day=request.same_day,
                store_outside_psl=request.store_outside_psl,
                jobsite_outside_psl=request.jobsite_outside_psl,
                miles_text=request.miles_text.strip(),
                wait_text=request.wait_text.strip(),
                trash_text=request.trash_text.strip(),
                vehicle_text=request.vehicle_text.strip(),
                other_client_scheduled=request.other_client_scheduled,
                general_notes=request.general_notes.strip(),
                created_by_id=self.user_id,
                updated_by_id=self.user_id,
            )
            note_id = QuoteRepository(session, self.organization_id).save_quick_note(note)
            self._audit(session, "quick_call_note.saved", note_id, {})
            return note_id

    def save_quick_note_as_lead(self, request: QuickNoteRequest) -> str:
        self._ensure_write()
        company = request.company_contact.strip()
        if not company:
            raise ValidationError("Company / contact is required to save a lead.")
        with self.factory.begin() as session:
            repo = QuoteRepository(session, self.organization_id)
            customer = repo.create_lead(company, request.phone, request.email)
            customer.internal_notes = request.general_notes.strip()
            customer.typical_materials = request.materials.strip()
            customer.created_by_id = self.user_id
            customer.updated_by_id = self.user_id
            self._audit(
                session,
                "customer.lead_created_from_call_note",
                customer.id,
                {"company_name": customer.company_name},
            )
            return customer.id

    def generate_call_sheet(self, request: QuickNoteRequest) -> Path:
        directory = self.documents_root / "call_sheets" / f"{datetime.now():%Y}"
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        destination = directory / f"Contractor-Call-Sheet-{timestamp}.pdf"
        psl = (
            f"Store: {self._yes_no_unknown(request.store_outside_psl, yes='Outside', no='Inside')}; "
            f"Jobsite: {self._yes_no_unknown(request.jobsite_outside_psl, yes='Outside', no='Inside')}"
        )
        data = CallSheetPdfData(
            created_at=datetime.now(UTC),
            company_contact=request.company_contact,
            phone=request.phone,
            email=request.email,
            supplier_address=request.supplier_address,
            jobsite_address=request.jobsite_address,
            materials=request.materials,
            dimensions_text=request.dimensions_text,
            weight_text=request.weight_text,
            pickup_stops=str(request.pickup_stops or "Unknown"),
            order_ready=self._yes_no_unknown(request.order_ready),
            same_day=self._yes_no_unknown(request.same_day),
            psl_status=psl,
            miles_text=request.miles_text,
            wait_text=request.wait_text,
            trash_text=request.trash_text,
            vehicle_text=request.vehicle_text,
            other_client=self._yes_no_unknown(request.other_client_scheduled),
            general_notes=request.general_notes,
        )
        return self.pdf.build_call_sheet(destination, data)

    def _operationalize_result(
        self, request: QuoteDraftRequest, result: PricingResult
    ) -> PricingResult:
        warnings = list(result.warnings)
        missing: list[tuple[str, str, str]] = []
        if not request.customer_id:
            missing.append(
                (
                    "customer_missing",
                    "Customer is not selected.",
                    "Select a customer before sending.",
                )
            )
        if not request.customer_contact_name.strip():
            missing.append(
                (
                    "contact_missing",
                    "Customer contact is missing.",
                    "Enter the contractor contact responsible for this quote.",
                )
            )
        if not request.supplier_name.strip() or not request.supplier_address.strip():
            missing.append(
                (
                    "pickup_missing",
                    "Pickup supplier or address is incomplete.",
                    "Confirm the supplier/store and pickup address.",
                )
            )
        if not request.jobsite_address.strip():
            missing.append(
                (
                    "jobsite_missing",
                    "Jobsite address is missing.",
                    "Enter the complete delivery address.",
                )
            )
        if not request.materials.strip():
            missing.append(
                (
                    "materials_missing",
                    "Material description is missing.",
                    "Describe the material, tools, or supplies being delivered.",
                )
            )
        if request.order_ready is None:
            missing.append(
                (
                    "readiness_unknown",
                    "Order readiness is unknown.",
                    "Confirm whether the supplier order is ready or not ready.",
                )
            )
        for code, message, action in missing:
            if not any(item.code == code for item in warnings):
                warnings.append(PricingWarning(code, "danger", message, action, "FR-QUOTE-006"))
        if not missing or result.recommended_status in {
            QuoteStatus.RESEARCH_REQUIRED.value,
            QuoteStatus.DECLINED.value,
        }:
            return (
                result
                if not missing
                else PricingResult(
                    charges=result.charges,
                    warnings=tuple(warnings),
                    total_cents=result.total_cents,
                    direct_cost_cents=result.direct_cost_cents,
                    profit_cents=result.profit_cents,
                    margin_basis_points=result.margin_basis_points,
                    confidence=result.confidence,
                    recommended_status=result.recommended_status,
                    manual_review_required=True,
                    sendable=False,
                    service_class=result.service_class,
                    chargeable_miles=result.chargeable_miles,
                    pricing_version_code=result.pricing_version_code,
                )
            )
        return PricingResult(
            charges=result.charges,
            warnings=tuple(warnings),
            total_cents=result.total_cents,
            direct_cost_cents=result.direct_cost_cents,
            profit_cents=result.profit_cents,
            margin_basis_points=result.margin_basis_points,
            confidence="Research / Decline",
            recommended_status=QuoteStatus.NEEDS_INFORMATION.value,
            manual_review_required=True,
            sendable=False,
            service_class=result.service_class,
            chargeable_miles=result.chargeable_miles,
            pricing_version_code=result.pricing_version_code,
        )

    @staticmethod
    def _apply_quote(quote: Quote, request: QuoteDraftRequest, result: PricingResult) -> None:
        quote.requested_service_at = request.requested_service_at
        quote.expires_at = request.expires_at or (datetime.now(UTC) + timedelta(days=14))
        quote.customer_notes = request.customer_notes.strip()
        quote.internal_notes = request.internal_notes.strip()
        quote.dispatch_notes = request.dispatch_notes.strip()
        quote.total_cents = result.total_cents
        quote.direct_cost_cents = result.direct_cost_cents
        quote.profit_cents = result.profit_cents
        quote.margin_basis_points = result.margin_basis_points
        quote.confidence = result.confidence
        quote.manual_review_required = result.manual_review_required
        quote.status = result.recommended_status

    @staticmethod
    def _apply_intake(intake: QuoteIntake, request: QuoteDraftRequest) -> None:
        for field, value in asdict(request).items():
            if field in {
                "customer_id",
                "requested_service_at",
                "expires_at",
                "customer_notes",
                "internal_notes",
                "dispatch_notes",
            }:
                continue
            if hasattr(intake, field):
                setattr(intake, field, value)

    def _apply_revision(
        self,
        session: Session,
        revision: QuoteRevision,
        quote: Quote,
        request: QuoteDraftRequest,
        result: PricingResult,
        settings: dict[str, Any],
    ) -> None:
        revision.status = result.recommended_status
        revision.configuration_snapshot_json = {
            "pricing_settings": settings,
            "inputs": self._json_safe(asdict(request.pricing_inputs())),
            "warnings": [asdict(item) for item in result.warnings],
        }
        revision.subtotal_cents = result.total_cents
        revision.discount_cents = max(0, -request.manual_adjustment_cents)
        revision.tax_cents = 0
        revision.total_cents = result.total_cents
        revision.direct_cost_cents = result.direct_cost_cents
        revision.profit_cents = result.profit_cents
        revision.margin_basis_points = result.margin_basis_points
        revision.confidence = result.confidence
        revision.updated_by_id = self.user_id

        session.add(
            QuoteStop(
                organization_id=self.organization_id,
                quote_revision_id=revision.id,
                sequence=1,
                stop_type=StopType.PICKUP.value,
                address_snapshot_json={
                    "label": request.supplier_name,
                    "entered_address": request.supplier_address,
                },
                geocode_snapshot_json={
                    "inside_psl": request.store_inside_psl,
                    "boundary_to_store_miles": self._decimal_or_none(
                        request.boundary_to_store_miles
                    ),
                },
                order_number=request.order_number or None,
                order_paid=request.order_paid,
                order_ready=request.order_ready,
                instructions=request.pickup_instructions,
                created_by_id=self.user_id,
                updated_by_id=self.user_id,
            )
        )
        session.add(
            QuoteStop(
                organization_id=self.organization_id,
                quote_revision_id=revision.id,
                sequence=2,
                stop_type=StopType.DELIVERY.value,
                address_snapshot_json={
                    "entered_address": request.jobsite_address,
                    "site_contact": request.site_contact,
                },
                geocode_snapshot_json={
                    "inside_psl": request.jobsite_inside_psl,
                    "store_to_jobsite_miles": self._decimal_or_none(request.store_to_jobsite_miles),
                    "chargeable_miles": str(result.chargeable_miles),
                },
                instructions=request.access_instructions,
                created_by_id=self.user_id,
                updated_by_id=self.user_id,
            )
        )
        session.add(
            QuoteLoad(
                organization_id=self.organization_id,
                quote_revision_id=revision.id,
                description=request.materials.strip(),
                quantity=request.quantity,
                length_inches=request.length_inches,
                width_inches=request.width_inches,
                height_inches=request.height_inches,
                weight_pounds=request.weight_pounds,
                overweight=request.overweight,
                hazardous=request.hazardous,
                prohibited_reason=request.prohibited_reason or None,
                trash_bag_count=request.trash_bag_count,
                trash_contents_identified=request.trash_contents_identified,
                created_by_id=self.user_id,
                updated_by_id=self.user_id,
            )
        )
        for sequence, line in enumerate(result.charges, start=1):
            session.add(
                QuoteCharge(
                    organization_id=self.organization_id,
                    quote_revision_id=revision.id,
                    sequence=sequence,
                    charge_code=line.code,
                    description=line.description,
                    quantity=line.quantity,
                    rate_cents=line.rate_cents,
                    total_cents=line.total_cents,
                    internal_cost_cents=line.internal_cost_cents,
                    rule_id=line.rule_id,
                    rule_reason=line.reason,
                    customer_visible=line.customer_visible,
                    is_manual_adjustment=line.manual,
                    override_reason=(request.manual_adjustment_reason if line.manual else None),
                    approved_by_id=self.user_id if line.manual else None,
                    created_by_id=self.user_id,
                    updated_by_id=self.user_id,
                )
            )

    @staticmethod
    def _request_from_quote(quote: Quote) -> QuoteDraftRequest:
        intake = quote.intake
        if intake is None:
            raise ValidationError("Quote intake data is missing.")
        values: dict[str, Any] = {
            field: getattr(intake, field)
            for field in QuoteDraftRequest.__dataclass_fields__
            if hasattr(intake, field)
        }
        values.update(
            {
                "customer_id": quote.customer_id,
                "requested_service_at": quote.requested_service_at,
                "expires_at": quote.expires_at,
                "customer_notes": quote.customer_notes,
                "internal_notes": quote.internal_notes,
                "dispatch_notes": quote.dispatch_notes,
            }
        )
        return QuoteDraftRequest(**values)

    @staticmethod
    def _json_safe(value: Any) -> Any:
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, dict):
            return {key: QuoteService._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [QuoteService._json_safe(item) for item in value]
        return value

    @staticmethod
    def _decimal_or_none(value: Decimal | None) -> str | None:
        return str(value) if value is not None else None

    @staticmethod
    def _service_description(result: PricingResult) -> str:
        labels = {
            "standard": "Standard store-to-jobsite delivery service",
            "oversized": "Oversized construction-material delivery service",
            "cancelled": "Cancellation after dispatch",
            "research": "Custom delivery service — manual review required",
        }
        return labels.get(result.service_class, "Construction-material delivery service")

    @staticmethod
    def _yes_no_unknown(value: bool | None, *, yes: str = "Yes", no: str = "No") -> str:
        if value is None:
            return "Unknown"
        return yes if value else no

    def _ensure_write(self) -> None:
        if not self.can_write:
            raise ValidationError("Your account has read-only access to quotes.")

    def _audit(
        self,
        session: Session,
        event_type: str,
        entity_id: str,
        details: dict[str, Any],
    ) -> None:
        session.add(
            AuditEvent(
                organization_id=self.organization_id,
                user_id=self.user_id,
                event_type=event_type,
                entity_type="quote",
                entity_id=entity_id,
                details_json=self._json_safe(details),
            )
        )
