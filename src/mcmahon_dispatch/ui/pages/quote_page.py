from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QDateTime, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from mcmahon_dispatch.core.exceptions import ValidationError
from mcmahon_dispatch.core.formatting import format_currency
from mcmahon_dispatch.repositories.quote_repository import CustomerChoice, QuoteSummary
from mcmahon_dispatch.services.pricing_engine import PricingResult
from mcmahon_dispatch.services.quote_service import (
    QuickNoteRequest,
    QuoteDraftRequest,
    QuoteEditorRecord,
    QuoteService,
)


class OptionalBooleanCombo(QComboBox):
    def __init__(self, *, unknown_label: str = "Unknown") -> None:
        super().__init__()
        self.addItem(unknown_label, None)
        self.addItem("No", False)
        self.addItem("Yes", True)

    def value(self) -> bool | None:
        return self.currentData()

    def set_value(self, value: bool | None) -> None:
        index = self.findData(value)
        self.setCurrentIndex(max(0, index))


class MoneySpinBox(QDoubleSpinBox):
    def __init__(self, *, allow_negative: bool = False) -> None:
        super().__init__()
        self.setDecimals(2)
        self.setPrefix("$")
        self.setGroupSeparatorShown(True)
        self.setMaximum(1_000_000.00)
        self.setMinimum(-1_000_000.00 if allow_negative else 0.00)
        self.setSingleStep(5.00)

    def cents(self) -> int:
        return int(round(self.value() * 100))

    def set_cents(self, cents: int) -> None:
        self.setValue(cents / 100)


class WarningRow(QFrame):
    def __init__(self, severity: str, message: str, next_action: str, rule_id: str | None) -> None:
        super().__init__()
        self.setObjectName("quoteWarning")
        self.setProperty("severity", severity)
        icon = QLabel({"danger": "!", "warning": "▲"}.get(severity, "i"))
        icon.setObjectName("quoteWarningIcon")
        icon.setProperty("severity", severity)
        title = QLabel(message)
        title.setObjectName("quoteWarningTitle")
        title.setWordWrap(True)
        action = QLabel(next_action)
        action.setObjectName("quoteWarningAction")
        action.setWordWrap(True)
        if rule_id:
            action.setText(f"{next_action}  ·  {rule_id}")
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(title)
        text.addWidget(action)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 7, 8, 7)
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(text, 1)


class QuickNotesPanel(QFrame):
    changed = Signal()
    transfer_requested = Signal()
    save_requested = Signal()
    save_lead_requested = Signal()
    call_sheet_requested = Signal()
    copy_requested = Signal()
    clear_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("quickNotesPanel")
        self.setMinimumWidth(300)
        self.setMaximumWidth(430)
        title = QLabel("Quick Call Notes")
        title.setObjectName("panelTitle")
        subtitle = QLabel("Jot the call first, then transfer confirmed details into the quote.")
        subtitle.setObjectName("panelSubtitle")
        subtitle.setWordWrap(True)

        self.company_contact = QLineEdit()
        self.phone = QLineEdit()
        self.email = QLineEdit()
        self.supplier_address = QTextEdit()
        self.supplier_address.setFixedHeight(54)
        self.jobsite_address = QTextEdit()
        self.jobsite_address.setFixedHeight(54)
        self.materials = QTextEdit()
        self.materials.setFixedHeight(60)
        self.dimensions = QLineEdit()
        self.dimensions.setPlaceholderText("Example: 72 x 48 x 18 in")
        self.weight = QLineEdit()
        self.overweight = OptionalBooleanCombo()
        self.pickup_stops = QSpinBox()
        self.pickup_stops.setRange(1, 99)
        self.order_ready = OptionalBooleanCombo()
        self.same_day = OptionalBooleanCombo()
        self.store_outside = OptionalBooleanCombo()
        self.jobsite_outside = OptionalBooleanCombo()
        self.miles = QLineEdit()
        self.miles.setPlaceholderText("Boundary/store and route notes")
        self.wait = QLineEdit()
        self.trash = QLineEdit()
        self.vehicle = QLineEdit()
        self.other_client = OptionalBooleanCombo()
        self.notes = QTextEdit()
        self.notes.setMinimumHeight(80)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.addRow("Company / contact", self.company_contact)
        form.addRow("Phone", self.phone)
        form.addRow("Email", self.email)
        form.addRow("Supplier / store", self.supplier_address)
        form.addRow("Jobsite", self.jobsite_address)
        form.addRow("Materials", self.materials)
        form.addRow("Dimensions", self.dimensions)
        form.addRow("Weight", self.weight)
        form.addRow("Overweight", self.overweight)
        form.addRow("Pickup stops", self.pickup_stops)
        form.addRow("Order ready", self.order_ready)
        form.addRow("Same-day", self.same_day)
        form.addRow("Store outside PSL", self.store_outside)
        form.addRow("Jobsite outside PSL", self.jobsite_outside)
        form.addRow("Miles", self.miles)
        form.addRow("Wait", self.wait)
        form.addRow("Trash", self.trash)
        form.addRow("Vehicle", self.vehicle)
        form.addRow("Other client scheduled", self.other_client)
        form.addRow("General notes", self.notes)

        primary = QPushButton("Transfer to Quote")
        primary.setObjectName("primary")
        primary.clicked.connect(self.transfer_requested)
        save = QPushButton("Save Note")
        save.clicked.connect(self.save_requested)
        lead = QPushButton("Save as Lead")
        lead.clicked.connect(self.save_lead_requested)
        call_sheet = QPushButton("Call Sheet PDF")
        call_sheet.clicked.connect(self.call_sheet_requested)
        copy = QPushButton("Copy")
        copy.clicked.connect(self.copy_requested)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.clear_requested)
        buttons = QGridLayout()
        buttons.addWidget(primary, 0, 0, 1, 2)
        buttons.addWidget(save, 1, 0)
        buttons.addWidget(lead, 1, 1)
        buttons.addWidget(call_sheet, 2, 0)
        buttons.addWidget(copy, 2, 1)
        buttons.addWidget(clear, 3, 0, 1, 2)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addLayout(form)
        layout.addLayout(buttons)
        layout.addStretch()
        self._connect_changes()

    def request(self) -> QuickNoteRequest:
        return QuickNoteRequest(
            company_contact=self.company_contact.text(),
            phone=self.phone.text(),
            email=self.email.text(),
            supplier_address=self.supplier_address.toPlainText(),
            jobsite_address=self.jobsite_address.toPlainText(),
            materials=self.materials.toPlainText(),
            dimensions_text=self.dimensions.text(),
            weight_text=self.weight.text(),
            overweight=self.overweight.value(),
            pickup_stops=self.pickup_stops.value(),
            order_ready=self.order_ready.value(),
            same_day=self.same_day.value(),
            store_outside_psl=self.store_outside.value(),
            jobsite_outside_psl=self.jobsite_outside.value(),
            miles_text=self.miles.text(),
            wait_text=self.wait.text(),
            trash_text=self.trash.text(),
            vehicle_text=self.vehicle.text(),
            other_client_scheduled=self.other_client.value(),
            general_notes=self.notes.toPlainText(),
        )

    def clear(self) -> None:
        for field in (
            self.company_contact,
            self.phone,
            self.email,
            self.dimensions,
            self.weight,
            self.miles,
            self.wait,
            self.trash,
            self.vehicle,
        ):
            field.clear()
        for field in (self.supplier_address, self.jobsite_address, self.materials, self.notes):
            field.clear()
        self.overweight.set_value(None)
        self.order_ready.set_value(None)
        self.same_day.set_value(None)
        self.store_outside.set_value(None)
        self.jobsite_outside.set_value(None)
        self.other_client.set_value(None)
        self.pickup_stops.setValue(1)

    def text_for_clipboard(self) -> str:
        request = self.request()
        values = (
            ("Company / contact", request.company_contact),
            ("Phone", request.phone),
            ("Email", request.email),
            ("Supplier", request.supplier_address),
            ("Jobsite", request.jobsite_address),
            ("Materials", request.materials),
            ("Dimensions", request.dimensions_text),
            ("Weight", request.weight_text),
            ("Overweight", self._bool_text(request.overweight)),
            ("Pickup stops", str(request.pickup_stops or "Unknown")),
            ("Order ready", self._bool_text(request.order_ready)),
            ("Same-day", self._bool_text(request.same_day)),
            ("Store outside PSL", self._bool_text(request.store_outside_psl)),
            ("Jobsite outside PSL", self._bool_text(request.jobsite_outside_psl)),
            ("Miles", request.miles_text),
            ("Wait", request.wait_text),
            ("Trash", request.trash_text),
            ("Vehicle", request.vehicle_text),
            ("Other client scheduled", self._bool_text(request.other_client_scheduled)),
            ("Notes", request.general_notes),
        )
        return "\n".join(f"{label}: {value or '—'}" for label, value in values)

    def _connect_changes(self) -> None:
        for field in (
            self.company_contact,
            self.phone,
            self.email,
            self.dimensions,
            self.weight,
            self.miles,
            self.wait,
            self.trash,
            self.vehicle,
        ):
            field.textChanged.connect(self.changed)
        for field in (self.supplier_address, self.jobsite_address, self.materials, self.notes):
            field.textChanged.connect(self.changed)
        for field in (
            self.overweight,
            self.order_ready,
            self.same_day,
            self.store_outside,
            self.jobsite_outside,
            self.other_client,
        ):
            field.currentIndexChanged.connect(self.changed)
        self.pickup_stops.valueChanged.connect(self.changed)

    @staticmethod
    def _bool_text(value: bool | None) -> str:
        return "Unknown" if value is None else ("Yes" if value else "No")


class QuotePage(QWidget):
    def __init__(self, service: QuoteService) -> None:
        super().__init__()
        self.service = service
        self.current_quote_id: str | None = None
        self.current_quote_number = "Unsaved quote"
        self._loading = False
        self._dirty = False
        self._last_result: PricingResult | None = None
        self._customers: dict[str, CustomerChoice] = {}
        self._quotes: list[QuoteSummary] = []

        title = QLabel("Quote Builder")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Fast intake, transparent SRS pricing, profit review, and customer-ready PDFs"
        )
        subtitle.setObjectName("muted")
        heading = QVBoxLayout()
        heading.setSpacing(2)
        heading.addWidget(title)
        heading.addWidget(subtitle)

        self.quote_selector = QComboBox()
        self.quote_selector.setMinimumWidth(285)
        self.quote_selector.currentIndexChanged.connect(self._quote_selected)
        self.new_button = QPushButton("New Quote")
        self.new_button.clicked.connect(self.new_quote)
        self.save_button = QPushButton("Save Draft")
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self.save)
        self.save_button.setEnabled(service.can_write)
        self.pdf_button = QPushButton("Generate PDF")
        self.pdf_button.clicked.connect(self.generate_pdf)
        self.pdf_button.setEnabled(False)
        self.quick_toggle = QToolButton()
        self.quick_toggle.setText("Quick Notes")
        self.quick_toggle.setCheckable(True)
        self.quick_toggle.setChecked(True)
        self.quick_toggle.toggled.connect(self._toggle_quick_notes)
        toolbar = QHBoxLayout()
        toolbar.addLayout(heading)
        toolbar.addStretch()
        toolbar.addWidget(QLabel("Open"))
        toolbar.addWidget(self.quote_selector)
        toolbar.addWidget(self.new_button)
        toolbar.addWidget(self.save_button)
        toolbar.addWidget(self.pdf_button)
        toolbar.addWidget(self.quick_toggle)

        self.form_scroll = QScrollArea()
        self.form_scroll.setWidgetResizable(True)
        self.form_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.form_content = QWidget()
        self.form_scroll.setWidget(self.form_content)
        self.form_layout = QVBoxLayout(self.form_content)
        self.form_layout.setContentsMargins(4, 4, 10, 20)
        self.form_layout.setSpacing(12)
        self._build_form()
        self.form_layout.addStretch()

        self.summary = self._build_summary()
        self.quick_notes = QuickNotesPanel()
        self.quick_notes.setEnabled(service.can_write)
        self.quick_notes.transfer_requested.connect(self._transfer_quick_notes)
        self.quick_notes.save_requested.connect(self._save_quick_note)
        self.quick_notes.save_lead_requested.connect(self._save_quick_lead)
        self.quick_notes.call_sheet_requested.connect(self._call_sheet)
        self.quick_notes.copy_requested.connect(self._copy_quick_notes)
        self.quick_notes.clear_requested.connect(self._clear_quick_notes)

        # Operational three-column workspace: fast call intake on the left,
        # structured quote in the center, and a compact live review rail on the right.
        self.outer_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.outer_splitter.setObjectName("quoteMainSplitter")
        self.outer_splitter.setChildrenCollapsible(False)
        self.outer_splitter.addWidget(self.quick_notes)
        self.outer_splitter.addWidget(self.form_scroll)
        self.outer_splitter.addWidget(self.summary)
        self.outer_splitter.setStretchFactor(0, 0)
        self.outer_splitter.setStretchFactor(1, 1)
        self.outer_splitter.setStretchFactor(2, 0)
        self.outer_splitter.setSizes([300, 760, 330])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(12)
        layout.addLayout(toolbar)
        layout.addWidget(self.outer_splitter, 1)

        self.recalc_timer = QTimer(self)
        self.recalc_timer.setSingleShot(True)
        self.recalc_timer.setInterval(60)
        self.recalc_timer.timeout.connect(self.recalculate)
        self._connect_live_updates()
        self.refresh_reference_data()
        self.new_quote(force=True)

    def _build_form(self) -> None:
        identity = QGroupBox("Customer & Quote")
        identity_form = QFormLayout(identity)
        self.quote_number = QLabel("Unsaved quote")
        self.quote_number.setObjectName("quoteNumber")
        self.customer = QComboBox()
        self.customer.setEditable(True)
        self.customer_contact_name = QLineEdit()
        self.customer_contact_phone = QLineEdit()
        self.customer_contact_email = QLineEdit()
        self.requested_at = QDateTimeEdit(QDateTime.currentDateTime())
        self.requested_at.setCalendarPopup(True)
        self.requested_at.setDisplayFormat("MMM d, yyyy  h:mm AP")
        self.expires_at = QDateTimeEdit(QDateTime.currentDateTime().addDays(14))
        self.expires_at.setCalendarPopup(True)
        self.expires_at.setDisplayFormat("MMM d, yyyy  h:mm AP")
        identity_form.addRow("Quote number", self.quote_number)
        identity_form.addRow("Customer*", self.customer)
        identity_form.addRow("Customer contact*", self.customer_contact_name)
        identity_form.addRow("Contact phone", self.customer_contact_phone)
        identity_form.addRow("Contact email", self.customer_contact_email)
        identity_form.addRow("Requested service", self.requested_at)
        identity_form.addRow("Quote expires", self.expires_at)
        self.form_layout.addWidget(identity)

        pickup = QGroupBox("Pickup")
        pickup_form = QFormLayout(pickup)
        self.supplier_name = QLineEdit()
        self.supplier_address = QTextEdit()
        self.supplier_address.setFixedHeight(62)
        self.supplier_contact = QLineEdit()
        self.order_number = QLineEdit()
        self.order_paid = OptionalBooleanCombo()
        self.order_ready = OptionalBooleanCombo()
        self.pickup_authorization = QTextEdit()
        self.pickup_authorization.setFixedHeight(52)
        self.pickup_instructions = QTextEdit()
        self.pickup_instructions.setFixedHeight(62)
        pickup_form.addRow("Supplier / store", self.supplier_name)
        pickup_form.addRow("Pickup address", self.supplier_address)
        pickup_form.addRow("Store contact", self.supplier_contact)
        pickup_form.addRow("Order number", self.order_number)
        pickup_form.addRow("Order paid", self.order_paid)
        pickup_form.addRow("Order ready", self.order_ready)
        pickup_form.addRow("Pickup authorization", self.pickup_authorization)
        pickup_form.addRow("Instructions", self.pickup_instructions)
        self.form_layout.addWidget(pickup)

        delivery = QGroupBox("Jobsite")
        delivery_form = QFormLayout(delivery)
        self.jobsite_address = QTextEdit()
        self.jobsite_address.setFixedHeight(62)
        self.site_contact = QLineEdit()
        self.delivery_window = QLineEdit()
        self.access_instructions = QTextEdit()
        self.access_instructions.setFixedHeight(70)
        delivery_form.addRow("Jobsite address", self.jobsite_address)
        delivery_form.addRow("Site contact", self.site_contact)
        delivery_form.addRow("Delivery window", self.delivery_window)
        delivery_form.addRow("Access instructions", self.access_instructions)
        self.form_layout.addWidget(delivery)

        load = QGroupBox("Load & Fit")
        load_grid = QGridLayout(load)
        self.materials = QTextEdit()
        self.materials.setMinimumHeight(70)
        self.quantity = QDoubleSpinBox()
        self.quantity.setRange(0.001, 999999)
        self.quantity.setDecimals(3)
        self.quantity.setValue(1)
        self.length = self._dimension_spin()
        self.load_width = self._dimension_spin()
        self.load_height = self._dimension_spin()
        self.weight = QDoubleSpinBox()
        self.weight.setRange(0, 1_000_000)
        self.weight.setDecimals(2)
        self.weight.setSpecialValueText("Unknown")
        self.overweight = OptionalBooleanCombo()
        self.hazardous = OptionalBooleanCombo()
        self.hazardous.set_value(False)
        self.prohibited_reason = QLineEdit()
        self.estimated_hours = QDoubleSpinBox()
        self.estimated_hours.setRange(0, 72)
        self.estimated_hours.setDecimals(2)
        self.estimated_hours.setSpecialValueText("Not entered")
        load_grid.addWidget(QLabel("Materials*"), 0, 0)
        load_grid.addWidget(self.materials, 0, 1, 1, 5)
        load_grid.addWidget(QLabel("Quantity"), 1, 0)
        load_grid.addWidget(self.quantity, 1, 1)
        load_grid.addWidget(QLabel("Length (in)"), 1, 2)
        load_grid.addWidget(self.length, 1, 3)
        load_grid.addWidget(QLabel("Width (in)"), 1, 4)
        load_grid.addWidget(self.load_width, 1, 5)
        load_grid.addWidget(QLabel("Height (in)"), 2, 0)
        load_grid.addWidget(self.load_height, 2, 1)
        load_grid.addWidget(QLabel("Weight (lb)"), 2, 2)
        load_grid.addWidget(self.weight, 2, 3)
        load_grid.addWidget(QLabel("Overweight"), 2, 4)
        load_grid.addWidget(self.overweight, 2, 5)
        load_grid.addWidget(QLabel("Hazardous / prohibited"), 3, 0)
        load_grid.addWidget(self.hazardous, 3, 1)
        load_grid.addWidget(QLabel("Reason / material detail"), 3, 2)
        load_grid.addWidget(self.prohibited_reason, 3, 3, 1, 3)
        load_grid.addWidget(QLabel("Estimated service hours"), 4, 0)
        load_grid.addWidget(self.estimated_hours, 4, 1)
        self.form_layout.addWidget(load)

        route = QGroupBox("Route & Mileage")
        route_grid = QGridLayout(route)
        self.store_inside = OptionalBooleanCombo()
        self.jobsite_inside = OptionalBooleanCombo()
        self.boundary_miles = self._distance_spin()
        self.route_miles = self._distance_spin()
        self.pickup_stops = QSpinBox()
        self.pickup_stops.setRange(1, 99)
        route_grid.addWidget(QLabel("Store inside PSL"), 0, 0)
        route_grid.addWidget(self.store_inside, 0, 1)
        route_grid.addWidget(QLabel("Jobsite inside PSL"), 0, 2)
        route_grid.addWidget(self.jobsite_inside, 0, 3)
        route_grid.addWidget(QLabel("Boundary → outside store miles"), 1, 0)
        route_grid.addWidget(self.boundary_miles, 1, 1)
        route_grid.addWidget(QLabel("Store → jobsite miles"), 1, 2)
        route_grid.addWidget(self.route_miles, 1, 3)
        route_grid.addWidget(QLabel("Pickup stops"), 2, 0)
        route_grid.addWidget(self.pickup_stops, 2, 1)
        self.form_layout.addWidget(route)

        services = QGroupBox("Timing & Services")
        service_grid = QGridLayout(services)
        self.same_day = QCheckBox("Same-day / no notice")
        self.other_client = QCheckBox("Another scheduled client will be affected")
        self.wait_minutes = QSpinBox()
        self.wait_minutes.setRange(0, 1440)
        self.delay_sequence = QSpinBox()
        self.delay_sequence.setRange(1, 999)
        self.loading_minutes = QSpinBox()
        self.loading_minutes.setRange(0, 1440)
        self.trash_bags = QSpinBox()
        self.trash_bags.setRange(0, 999)
        self.trash_identified = QCheckBox("Contents identified as non-hazardous contractor bags")
        self.cancelled = QCheckBox("Cancelled after dispatch")
        service_grid.addWidget(self.same_day, 0, 0, 1, 2)
        service_grid.addWidget(self.other_client, 0, 2, 1, 2)
        service_grid.addWidget(QLabel("Wait minutes"), 1, 0)
        service_grid.addWidget(self.wait_minutes, 1, 1)
        service_grid.addWidget(QLabel("Delay sequence"), 1, 2)
        service_grid.addWidget(self.delay_sequence, 1, 3)
        service_grid.addWidget(QLabel("Loading / unloading minutes"), 2, 0)
        service_grid.addWidget(self.loading_minutes, 2, 1)
        service_grid.addWidget(QLabel("Trash bags"), 2, 2)
        service_grid.addWidget(self.trash_bags, 2, 3)
        service_grid.addWidget(self.trash_identified, 3, 0, 1, 4)
        service_grid.addWidget(self.cancelled, 4, 0, 1, 4)
        self.form_layout.addWidget(services)

        costs = QGroupBox("Direct Costs & Adjustments")
        costs_grid = QGridLayout(costs)
        self.tolls = MoneySpinBox()
        self.tolls_bill = QCheckBox("Bill customer")
        self.parking = MoneySpinBox()
        self.parking_bill = QCheckBox("Bill customer")
        self.rental = MoneySpinBox()
        self.rental_bill = QCheckBox("Pass through")
        self.rental_markup = MoneySpinBox()
        self.fuel_cost = MoneySpinBox()
        self.helper_cost = MoneySpinBox()
        self.securement_cost = MoneySpinBox()
        self.processing_cost = MoneySpinBox()
        self.other_cost = MoneySpinBox()
        self.manual_adjustment = MoneySpinBox(allow_negative=True)
        self.manual_reason = QLineEdit()
        self.manual_adjustment.setEnabled(self.service.can_override_price)
        self.manual_reason.setEnabled(self.service.can_override_price)
        if not self.service.can_override_price:
            self.manual_adjustment.setToolTip("Price override permission is required.")
            self.manual_reason.setToolTip("Price override permission is required.")
        rows = (
            ("Tolls", self.tolls, self.tolls_bill),
            ("Parking", self.parking, self.parking_bill),
            ("Rental cost", self.rental, self.rental_bill),
            ("Rental markup", self.rental_markup, None),
            ("Fuel estimate", self.fuel_cost, None),
            ("Helper / contract labor", self.helper_cost, None),
            ("Securement supplies", self.securement_cost, None),
            ("Processing fee", self.processing_cost, None),
            ("Other direct cost", self.other_cost, None),
            ("Manual adjustment (+ charge / - discount)", self.manual_adjustment, None),
        )
        for row, (label, field, option) in enumerate(rows):
            costs_grid.addWidget(QLabel(label), row, 0)
            costs_grid.addWidget(field, row, 1)
            if option:
                costs_grid.addWidget(option, row, 2)
        costs_grid.addWidget(QLabel("Adjustment reason"), len(rows), 0)
        costs_grid.addWidget(self.manual_reason, len(rows), 1, 1, 2)
        self.form_layout.addWidget(costs)

        notes = QGroupBox("Notes")
        notes_form = QFormLayout(notes)
        self.customer_notes = QTextEdit()
        self.internal_notes = QTextEdit()
        self.dispatch_notes = QTextEdit()
        for editor in (self.customer_notes, self.internal_notes, self.dispatch_notes):
            editor.setMinimumHeight(65)
        notes_form.addRow("Customer-facing notes", self.customer_notes)
        notes_form.addRow("Internal notes", self.internal_notes)
        notes_form.addRow("Dispatch notes", self.dispatch_notes)
        self.form_layout.addWidget(notes)

    def _build_summary(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("quoteSummary")
        panel.setMinimumWidth(300)
        panel.setMaximumWidth(410)
        title = QLabel("Live Quote Summary")
        title.setObjectName("panelTitle")
        self.service_class = QLabel("Waiting for input")
        self.service_class.setObjectName("panelSubtitle")
        self.total_label = QLabel("$0.00")
        self.total_label.setObjectName("quoteTotal")
        self.cost_label = QLabel("$0.00")
        self.profit_label = QLabel("$0.00")
        self.margin_label = QLabel("—")
        self.confidence_label = QLabel("Research / Decline")
        self.status_label = QLabel("Needs Information")
        metrics = QGridLayout()
        metrics.addWidget(QLabel("Customer total"), 0, 0)
        metrics.addWidget(self.total_label, 0, 1)
        metrics.addWidget(QLabel("Direct cost"), 1, 0)
        metrics.addWidget(self.cost_label, 1, 1)
        metrics.addWidget(QLabel("Estimated profit"), 2, 0)
        metrics.addWidget(self.profit_label, 2, 1)
        metrics.addWidget(QLabel("Margin"), 3, 0)
        metrics.addWidget(self.margin_label, 3, 1)
        metrics.addWidget(QLabel("Confidence"), 4, 0)
        metrics.addWidget(self.confidence_label, 4, 1)
        metrics.addWidget(QLabel("Recommended status"), 5, 0)
        metrics.addWidget(self.status_label, 5, 1)

        self.charge_table = QTableWidget(0, 3)
        self.charge_table.setHorizontalHeaderLabels(["Charge", "Reason", "Amount"])
        self.charge_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.charge_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.charge_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self.charge_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.charge_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.charge_table.setMinimumHeight(170)

        warnings_title = QLabel("Warnings & Next Actions")
        warnings_title.setObjectName("panelTitle")
        self.warning_layout = QVBoxLayout()
        self.warning_layout.setSpacing(6)
        warning_container = QWidget()
        warning_container.setLayout(self.warning_layout)
        warning_scroll = QScrollArea()
        warning_scroll.setWidgetResizable(True)
        warning_scroll.setWidget(warning_container)
        warning_scroll.setMinimumHeight(145)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addWidget(self.service_class)
        layout.addLayout(metrics)
        layout.addWidget(QLabel("Price Breakdown"))
        layout.addWidget(self.charge_table)
        layout.addWidget(warnings_title)
        layout.addWidget(warning_scroll, 1)
        return panel

    def refresh_reference_data(self) -> None:
        """Reload customer and quote choices without disturbing in-progress work."""
        selected_customer = self.customer.currentData() if hasattr(self, "customer") else None
        selected_customer_text = (
            self.customer.currentText().strip() if hasattr(self, "customer") else ""
        )
        selected_quote = self.current_quote_id or (
            self.quote_selector.currentData() if hasattr(self, "quote_selector") else None
        )
        was_dirty = self._dirty
        self._loading = True
        try:
            self.customer.clear()
            self.customer.addItem("Select customer…", None)
            choices = self.service.customers()
            self._customers = {choice.id: choice for choice in choices}
            for choice in choices:
                self.customer.addItem(
                    f"{choice.company_name}  ·  {choice.customer_number}", choice.id
                )

            customer_index = self.customer.findData(selected_customer)
            if customer_index >= 0:
                self.customer.setCurrentIndex(customer_index)
            elif selected_customer_text and selected_customer_text != "Select customer…":
                self.customer.setEditText(selected_customer_text)
            else:
                self.customer.setCurrentIndex(0)

            self.quote_selector.clear()
            self.quote_selector.addItem("Select saved quote…", None)
            self._quotes = self.service.quotes()
            for summary in self._quotes:
                self.quote_selector.addItem(
                    f"{summary.quote_number}  ·  {summary.customer_name}  ·  "
                    f"{summary.status.replace('_', ' ').title()}",
                    summary.id,
                )
            quote_index = self.quote_selector.findData(selected_quote)
            self.quote_selector.setCurrentIndex(max(0, quote_index))
        finally:
            self._loading = False
            self._dirty = was_dirty

    def on_activated(self) -> None:
        """Refresh reference choices whenever the user returns to the quote page."""
        self.refresh_reference_data()

    def new_quote(self, *, force: bool = False) -> None:
        if not force and not self._confirm_discard():
            return
        self._loading = True
        self.current_quote_id = None
        self.current_quote_number = "Unsaved quote"
        self.quote_number.setText(self.current_quote_number)
        self.quote_selector.setCurrentIndex(0)
        self.customer.setCurrentIndex(0)
        self.requested_at.setDateTime(QDateTime.currentDateTime())
        self.expires_at.setDateTime(QDateTime.currentDateTime().addDays(14))
        for field in (
            self.customer_contact_name,
            self.customer_contact_phone,
            self.customer_contact_email,
            self.supplier_name,
            self.supplier_contact,
            self.order_number,
            self.prohibited_reason,
            self.site_contact,
            self.delivery_window,
            self.manual_reason,
        ):
            field.clear()
        for field in (
            self.supplier_address,
            self.pickup_authorization,
            self.pickup_instructions,
            self.jobsite_address,
            self.access_instructions,
            self.materials,
            self.customer_notes,
            self.internal_notes,
            self.dispatch_notes,
        ):
            field.clear()
        for combo in (
            self.order_paid,
            self.order_ready,
            self.overweight,
            self.store_inside,
            self.jobsite_inside,
        ):
            combo.set_value(None)
        self.hazardous.set_value(False)
        self.quantity.setValue(1)
        for spin in (
            self.length,
            self.load_width,
            self.load_height,
            self.weight,
            self.estimated_hours,
            self.boundary_miles,
            self.route_miles,
            self.wait_minutes,
            self.loading_minutes,
            self.trash_bags,
        ):
            spin.setValue(0)
        self.pickup_stops.setValue(1)
        self.delay_sequence.setValue(1)
        for check in (
            self.same_day,
            self.other_client,
            self.trash_identified,
            self.cancelled,
            self.tolls_bill,
            self.parking_bill,
            self.rental_bill,
        ):
            check.setChecked(False)
        for money in (
            self.tolls,
            self.parking,
            self.rental,
            self.rental_markup,
            self.fuel_cost,
            self.helper_cost,
            self.securement_cost,
            self.processing_cost,
            self.other_cost,
            self.manual_adjustment,
        ):
            money.set_cents(0)
        self._loading = False
        self._dirty = False
        self.recalculate()

    def save(self) -> bool:
        try:
            saved = self.service.save_draft(self.request(), self.current_quote_id)
        except ValidationError as exc:
            QMessageBox.warning(self, "Quote", str(exc))
            return False
        self.current_quote_id = saved.id
        self.current_quote_number = saved.quote_number
        self.quote_number.setText(saved.quote_number)
        self._dirty = False
        self.refresh_reference_data()
        index = self.quote_selector.findData(saved.id)
        if index >= 0:
            self._loading = True
            self.quote_selector.setCurrentIndex(index)
            self._loading = False
        QMessageBox.information(
            self,
            "Quote saved",
            f"{saved.quote_number} was saved as {saved.status.replace('_', ' ').title()}.",
        )
        return True

    def generate_pdf(self) -> None:
        try:
            saved, path = self.service.generate_quote_pdf(self.request(), self.current_quote_id)
        except ValidationError as exc:
            QMessageBox.warning(self, "Quote PDF", str(exc))
            return
        self.current_quote_id = saved.id
        self.current_quote_number = saved.quote_number
        self.quote_number.setText(saved.quote_number)
        self._dirty = False
        self.refresh_reference_data()
        QMessageBox.information(self, "Quote PDF", f"Quote PDF created:\n{path}")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def recalculate(self) -> None:
        if self._loading:
            return
        try:
            result = self.service.calculate(self.request())
        except ValidationError as exc:
            self._apply_calculation_error(str(exc))
            return
        self._last_result = result
        self._apply_result(result)

    def request(self) -> QuoteDraftRequest:
        return QuoteDraftRequest(
            customer_id=self._selected_customer_id(),
            requested_service_at=self._datetime(self.requested_at),
            expires_at=self._datetime(self.expires_at),
            customer_notes=self.customer_notes.toPlainText(),
            internal_notes=self.internal_notes.toPlainText(),
            dispatch_notes=self.dispatch_notes.toPlainText(),
            customer_contact_name=self.customer_contact_name.text(),
            customer_contact_phone=self.customer_contact_phone.text(),
            customer_contact_email=self.customer_contact_email.text(),
            supplier_name=self.supplier_name.text(),
            supplier_address=self.supplier_address.toPlainText(),
            supplier_contact=self.supplier_contact.text(),
            order_number=self.order_number.text(),
            order_paid=self.order_paid.value(),
            order_ready=self.order_ready.value(),
            pickup_authorization=self.pickup_authorization.toPlainText(),
            pickup_instructions=self.pickup_instructions.toPlainText(),
            jobsite_address=self.jobsite_address.toPlainText(),
            site_contact=self.site_contact.text(),
            access_instructions=self.access_instructions.toPlainText(),
            delivery_window=self.delivery_window.text(),
            materials=self.materials.toPlainText(),
            quantity=Decimal(str(self.quantity.value())),
            length_inches=self._optional_decimal(self.length),
            width_inches=self._optional_decimal(self.load_width),
            height_inches=self._optional_decimal(self.load_height),
            weight_pounds=self._optional_decimal(self.weight),
            overweight=self.overweight.value(),
            hazardous=self.hazardous.value(),
            prohibited_reason=self.prohibited_reason.text(),
            estimated_hours=self._optional_decimal(self.estimated_hours),
            store_inside_psl=self.store_inside.value(),
            jobsite_inside_psl=self.jobsite_inside.value(),
            boundary_to_store_miles=self._optional_decimal(self.boundary_miles),
            store_to_jobsite_miles=self._optional_decimal(self.route_miles),
            pickup_stops=self.pickup_stops.value(),
            same_day=self.same_day.isChecked(),
            other_client_affected=self.other_client.isChecked(),
            wait_minutes=self.wait_minutes.value(),
            delay_sequence=self.delay_sequence.value(),
            loading_minutes=self.loading_minutes.value(),
            trash_bag_count=self.trash_bags.value(),
            trash_contents_identified=self.trash_identified.isChecked(),
            cancelled_after_dispatch=self.cancelled.isChecked(),
            tolls_cents=self.tolls.cents(),
            tolls_pass_through=self.tolls_bill.isChecked(),
            parking_cents=self.parking.cents(),
            parking_pass_through=self.parking_bill.isChecked(),
            rental_cost_cents=self.rental.cents(),
            rental_pass_through=self.rental_bill.isChecked(),
            rental_markup_cents=self.rental_markup.cents(),
            fuel_cost_cents=self.fuel_cost.cents(),
            helper_cost_cents=self.helper_cost.cents(),
            securement_cost_cents=self.securement_cost.cents(),
            processing_fee_cents=self.processing_cost.cents(),
            other_direct_cost_cents=self.other_cost.cents(),
            manual_adjustment_cents=self.manual_adjustment.cents(),
            manual_adjustment_reason=self.manual_reason.text(),
        )

    def _apply_result(self, result: PricingResult) -> None:
        self.total_label.setText(self._money(result.total_cents))
        self.cost_label.setText(self._money(result.direct_cost_cents))
        self.profit_label.setText(self._money(result.profit_cents))
        self.profit_label.setProperty("negative", result.profit_cents < 0)
        self.margin_label.setText(
            f"{result.margin_basis_points / 100:.2f}%"
            if result.margin_basis_points is not None
            else "—"
        )
        self.confidence_label.setText(result.confidence)
        self.status_label.setText(result.recommended_status.replace("_", " ").title())
        self.service_class.setText(
            f"{result.service_class.replace('_', ' ').title()}  ·  "
            f"{self._decimal_text(result.chargeable_miles)} chargeable miles  ·  "
            f"Pricing v{result.pricing_version_code}"
        )
        self.charge_table.setRowCount(len(result.charges))
        for row, line in enumerate(result.charges):
            self.charge_table.setItem(row, 0, QTableWidgetItem(line.description))
            reason = line.reason or (line.rule_id or "")
            self.charge_table.setItem(row, 1, QTableWidgetItem(reason))
            amount = QTableWidgetItem(self._money(line.total_cents))
            amount.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.charge_table.setItem(row, 2, amount)
        self._clear_layout(self.warning_layout)
        if not result.warnings:
            label = QLabel("No active pricing warnings. The quote is ready for review.")
            label.setObjectName("emptyState")
            label.setWordWrap(True)
            self.warning_layout.addWidget(label)
        else:
            for warning in result.warnings:
                self.warning_layout.addWidget(
                    WarningRow(
                        warning.severity,
                        warning.message,
                        warning.next_action,
                        warning.rule_id,
                    )
                )
        self.warning_layout.addStretch()
        self.pdf_button.setEnabled(result.sendable and self.service.can_write)

    def _apply_calculation_error(self, message: str) -> None:
        self.total_label.setText("Calculation blocked")
        self.cost_label.setText("—")
        self.profit_label.setText("—")
        self.margin_label.setText("—")
        self.confidence_label.setText("Research / Decline")
        self.status_label.setText("Needs Information")
        self.service_class.setText("Correct invalid input to recalculate")
        self.charge_table.setRowCount(0)
        self._clear_layout(self.warning_layout)
        self.warning_layout.addWidget(
            WarningRow("danger", message, "Correct the highlighted input and try again.", None)
        )
        self.warning_layout.addStretch()
        self.pdf_button.setEnabled(False)

    def _quote_selected(self) -> None:
        if self._loading:
            return
        quote_id = self.quote_selector.currentData()
        if not quote_id:
            return
        if not self._confirm_discard():
            self._loading = True
            index = self.quote_selector.findData(self.current_quote_id)
            self.quote_selector.setCurrentIndex(max(0, index))
            self._loading = False
            return
        try:
            record = self.service.load(str(quote_id))
        except ValidationError as exc:
            QMessageBox.warning(self, "Quote", str(exc))
            return
        self._load_record(record)

    def _load_record(self, record: QuoteEditorRecord) -> None:
        self._loading = True
        self.current_quote_id = record.id
        self.current_quote_number = record.quote_number
        self.quote_number.setText(record.quote_number)
        request = record.request
        self.customer.setCurrentIndex(max(0, self.customer.findData(request.customer_id)))
        self._set_datetime(self.requested_at, request.requested_service_at)
        self._set_datetime(self.expires_at, request.expires_at)
        self.customer_notes.setPlainText(request.customer_notes)
        self.internal_notes.setPlainText(request.internal_notes)
        self.dispatch_notes.setPlainText(request.dispatch_notes)
        self.customer_contact_name.setText(request.customer_contact_name)
        self.customer_contact_phone.setText(request.customer_contact_phone)
        self.customer_contact_email.setText(request.customer_contact_email)
        self.supplier_name.setText(request.supplier_name)
        self.supplier_address.setPlainText(request.supplier_address)
        self.supplier_contact.setText(request.supplier_contact)
        self.order_number.setText(request.order_number)
        self.order_paid.set_value(request.order_paid)
        self.order_ready.set_value(request.order_ready)
        self.pickup_authorization.setPlainText(request.pickup_authorization)
        self.pickup_instructions.setPlainText(request.pickup_instructions)
        self.jobsite_address.setPlainText(request.jobsite_address)
        self.site_contact.setText(request.site_contact)
        self.access_instructions.setPlainText(request.access_instructions)
        self.delivery_window.setText(request.delivery_window)
        self.materials.setPlainText(request.materials)
        self.quantity.setValue(float(request.quantity))
        self._set_decimal(self.length, request.length_inches)
        self._set_decimal(self.load_width, request.width_inches)
        self._set_decimal(self.load_height, request.height_inches)
        self._set_decimal(self.weight, request.weight_pounds)
        self.overweight.set_value(request.overweight)
        self.hazardous.set_value(request.hazardous)
        self.prohibited_reason.setText(request.prohibited_reason)
        self._set_decimal(self.estimated_hours, request.estimated_hours)
        self.store_inside.set_value(request.store_inside_psl)
        self.jobsite_inside.set_value(request.jobsite_inside_psl)
        self._set_decimal(self.boundary_miles, request.boundary_to_store_miles)
        self._set_decimal(self.route_miles, request.store_to_jobsite_miles)
        self.pickup_stops.setValue(request.pickup_stops)
        self.same_day.setChecked(request.same_day)
        self.other_client.setChecked(request.other_client_affected)
        self.wait_minutes.setValue(request.wait_minutes)
        self.delay_sequence.setValue(request.delay_sequence)
        self.loading_minutes.setValue(request.loading_minutes)
        self.trash_bags.setValue(request.trash_bag_count)
        self.trash_identified.setChecked(request.trash_contents_identified)
        self.cancelled.setChecked(request.cancelled_after_dispatch)
        self.tolls.set_cents(request.tolls_cents)
        self.tolls_bill.setChecked(request.tolls_pass_through)
        self.parking.set_cents(request.parking_cents)
        self.parking_bill.setChecked(request.parking_pass_through)
        self.rental.set_cents(request.rental_cost_cents)
        self.rental_bill.setChecked(bool(request.rental_pass_through))
        self.rental_markup.set_cents(request.rental_markup_cents)
        self.fuel_cost.set_cents(request.fuel_cost_cents)
        self.helper_cost.set_cents(request.helper_cost_cents)
        self.securement_cost.set_cents(request.securement_cost_cents)
        self.processing_cost.set_cents(request.processing_fee_cents)
        self.other_cost.set_cents(request.other_direct_cost_cents)
        self.manual_adjustment.set_cents(request.manual_adjustment_cents)
        self.manual_reason.setText(request.manual_adjustment_reason)
        self._loading = False
        self._dirty = False
        self._apply_result(record.pricing)

    def _transfer_quick_notes(self) -> None:
        note = self.quick_notes.request()
        overwrites: list[str] = []
        for label, current, incoming in (
            ("supplier address", self.supplier_address.toPlainText(), note.supplier_address),
            ("jobsite address", self.jobsite_address.toPlainText(), note.jobsite_address),
            ("materials", self.materials.toPlainText(), note.materials),
        ):
            if current.strip() and incoming.strip() and current.strip() != incoming.strip():
                overwrites.append(label)
        if overwrites:
            answer = QMessageBox.question(
                self,
                "Transfer quick notes",
                "The transfer will replace populated " + ", ".join(overwrites) + ". Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        if note.company_contact.strip() and not self.customer_contact_name.text().strip():
            self.customer_contact_name.setText(note.company_contact.strip())
        if note.phone.strip() and not self.customer_contact_phone.text().strip():
            self.customer_contact_phone.setText(note.phone.strip())
        if note.email.strip() and not self.customer_contact_email.text().strip():
            self.customer_contact_email.setText(note.email.strip())
        if note.weight_text.strip():
            weight_values = re.findall(r"\d+(?:\.\d+)?", note.weight_text)
            if weight_values:
                self.weight.setValue(float(weight_values[0]))
        mileage_values = re.findall(r"\d+(?:\.\d+)?", note.miles_text)
        if len(mileage_values) >= 2:
            self.boundary_miles.setValue(float(mileage_values[0]))
            self.route_miles.setValue(float(mileage_values[1]))
        elif len(mileage_values) == 1:
            self.route_miles.setValue(float(mileage_values[0]))
        wait_values = re.findall(r"\d+", note.wait_text)
        if wait_values:
            self.wait_minutes.setValue(int(wait_values[0]))
        trash_values = re.findall(r"\d+", note.trash_text)
        if trash_values:
            self.trash_bags.setValue(int(trash_values[0]))
            lowered_trash = note.trash_text.lower()
            self.trash_identified.setChecked(
                any(
                    word in lowered_trash
                    for word in ("identified", "known", "non-hazardous", "nonhazardous")
                )
            )
        if note.vehicle_text.strip():
            existing_dispatch = self.dispatch_notes.toPlainText().strip()
            vehicle_note = f"Vehicle note: {note.vehicle_text.strip()}"
            self.dispatch_notes.setPlainText(
                "\n\n".join(value for value in (existing_dispatch, vehicle_note) if value)
            )
        if note.supplier_address.strip():
            self.supplier_address.setPlainText(note.supplier_address)
        if note.jobsite_address.strip():
            self.jobsite_address.setPlainText(note.jobsite_address)
        if note.materials.strip():
            self.materials.setPlainText(note.materials)
        if note.pickup_stops:
            self.pickup_stops.setValue(note.pickup_stops)
        if note.overweight is not None:
            self.overweight.set_value(note.overweight)
        if note.order_ready is not None:
            self.order_ready.set_value(note.order_ready)
        if note.same_day is not None:
            self.same_day.setChecked(note.same_day)
        if note.other_client_scheduled is not None:
            self.other_client.setChecked(note.other_client_scheduled)
        if note.store_outside_psl is not None:
            self.store_inside.set_value(not note.store_outside_psl)
        if note.jobsite_outside_psl is not None:
            self.jobsite_inside.set_value(not note.jobsite_outside_psl)
        dimensions = self._parse_dimensions(note.dimensions_text)
        if dimensions:
            self.length.setValue(float(dimensions[0]))
            self.load_width.setValue(float(dimensions[1]))
            self.load_height.setValue(float(dimensions[2]))
        if note.general_notes.strip():
            existing = self.internal_notes.toPlainText().strip()
            self.internal_notes.setPlainText(
                "\n\n".join(value for value in (existing, note.general_notes.strip()) if value)
            )
        self._mark_changed()

    def _save_quick_note(self) -> None:
        try:
            self.service.save_quick_note(self.quick_notes.request(), self.current_quote_id)
        except ValidationError as exc:
            QMessageBox.warning(self, "Quick Call Notes", str(exc))
            return
        QMessageBox.information(self, "Quick Call Notes", "The call note was saved.")

    def _save_quick_lead(self) -> None:
        try:
            customer_id = self.service.save_quick_note_as_lead(self.quick_notes.request())
        except ValidationError as exc:
            QMessageBox.warning(self, "Save as Lead", str(exc))
            return
        self.refresh_reference_data()
        index = self.customer.findData(customer_id)
        if index >= 0:
            self.customer.setCurrentIndex(index)
        QMessageBox.information(
            self, "Save as Lead", "A new lead customer was created and selected."
        )

    def _call_sheet(self) -> None:
        try:
            path = self.service.generate_call_sheet(self.quick_notes.request())
        except ValidationError as exc:
            QMessageBox.warning(self, "Contractor Call Sheet", str(exc))
            return
        QMessageBox.information(self, "Contractor Call Sheet", f"Call sheet created:\n{path}")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _copy_quick_notes(self) -> None:
        QApplication.clipboard().setText(self.quick_notes.text_for_clipboard())
        QMessageBox.information(self, "Quick Call Notes", "Call notes copied to the clipboard.")

    def _clear_quick_notes(self) -> None:
        if not self.quick_notes.text_for_clipboard().strip():
            return
        answer = QMessageBox.question(
            self,
            "Clear quick notes",
            "Clear all quick call notes?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.quick_notes.clear()

    def _customer_changed(self) -> None:
        customer_id = self.customer.currentData()
        choice = self._customers.get(str(customer_id)) if customer_id else None
        if choice and not self._loading:
            self.delay_sequence.setValue(2 if choice.delay_level >= 1 else 1)
            if not self.customer_contact_phone.text().strip():
                self.customer_contact_phone.setText(choice.primary_phone)
            if not self.customer_contact_email.text().strip():
                self.customer_contact_email.setText(choice.primary_email)
        self._mark_changed()

    def _connect_live_updates(self) -> None:
        self.customer.currentIndexChanged.connect(self._customer_changed)
        for field in (
            self.customer_contact_name,
            self.customer_contact_phone,
            self.customer_contact_email,
            self.supplier_name,
            self.supplier_contact,
            self.order_number,
            self.prohibited_reason,
            self.site_contact,
            self.delivery_window,
            self.manual_reason,
        ):
            field.textChanged.connect(self._mark_changed)
        for field in (
            self.supplier_address,
            self.pickup_authorization,
            self.pickup_instructions,
            self.jobsite_address,
            self.access_instructions,
            self.materials,
            self.customer_notes,
            self.internal_notes,
            self.dispatch_notes,
        ):
            field.textChanged.connect(self._mark_changed)
        for combo in (
            self.order_paid,
            self.order_ready,
            self.overweight,
            self.hazardous,
            self.store_inside,
            self.jobsite_inside,
        ):
            combo.currentIndexChanged.connect(self._mark_changed)
        for spin in (
            self.quantity,
            self.length,
            self.load_width,
            self.load_height,
            self.weight,
            self.estimated_hours,
            self.boundary_miles,
            self.route_miles,
            self.pickup_stops,
            self.wait_minutes,
            self.delay_sequence,
            self.loading_minutes,
            self.trash_bags,
            self.tolls,
            self.parking,
            self.rental,
            self.rental_markup,
            self.fuel_cost,
            self.helper_cost,
            self.securement_cost,
            self.processing_cost,
            self.other_cost,
            self.manual_adjustment,
        ):
            spin.valueChanged.connect(self._mark_changed)
        for check in (
            self.same_day,
            self.other_client,
            self.trash_identified,
            self.cancelled,
            self.tolls_bill,
            self.parking_bill,
            self.rental_bill,
        ):
            check.toggled.connect(self._mark_changed)
        self.requested_at.dateTimeChanged.connect(self._mark_changed)
        self.expires_at.dateTimeChanged.connect(self._mark_changed)

    def _mark_changed(self) -> None:
        if self._loading:
            return
        self._dirty = True
        self.recalc_timer.start()

    def _confirm_discard(self) -> bool:
        if not self._dirty:
            return True
        answer = QMessageBox.warning(
            self,
            "Unsaved quote changes",
            "Save changes before continuing?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self.save()
        return answer == QMessageBox.StandardButton.Discard

    def _toggle_quick_notes(self, visible: bool) -> None:
        self.quick_notes.setVisible(visible)

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        if self.width() < 1180 and self.quick_toggle.isChecked():
            self.quick_toggle.setChecked(False)
        elif self.width() >= 1500 and not self.quick_toggle.isChecked():
            self.quick_toggle.setChecked(True)

    def _selected_customer_id(self) -> str | None:
        index = self.customer.currentIndex()
        if index <= 0:
            return None
        if self.customer.currentText().strip() != self.customer.itemText(index).strip():
            return None
        value = self.customer.itemData(index)
        return str(value) if value else None

    @staticmethod
    def _dimension_spin() -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0, 10000)
        spin.setDecimals(2)
        spin.setSpecialValueText("Unknown")
        return spin

    @staticmethod
    def _distance_spin() -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0, 100000)
        spin.setDecimals(2)
        spin.setSuffix(" mi")
        spin.setSpecialValueText("Not entered")
        return spin

    @staticmethod
    def _optional_decimal(spin: QDoubleSpinBox) -> Decimal | None:
        return None if spin.value() == spin.minimum() else Decimal(str(spin.value()))

    @staticmethod
    def _set_decimal(spin: QDoubleSpinBox, value: Decimal | None) -> None:
        spin.setValue(float(value) if value is not None else spin.minimum())

    @staticmethod
    def _datetime(field: QDateTimeEdit) -> datetime:
        value = field.dateTime().toPython()
        if value.tzinfo is None:
            return value.astimezone().astimezone(UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _set_datetime(field: QDateTimeEdit, value: datetime | None) -> None:
        if value is not None:
            field.setDateTime(QDateTime(value.astimezone()))

    @staticmethod
    def _parse_dimensions(text: str) -> tuple[Decimal, Decimal, Decimal] | None:
        values = re.findall(r"\d+(?:\.\d+)?", text)
        if len(values) < 3:
            return None
        try:
            return Decimal(values[0]), Decimal(values[1]), Decimal(values[2])
        except InvalidOperation:
            return None

    @staticmethod
    def _money(cents: int) -> str:
        sign = "-" if cents < 0 else ""
        return f"{sign}${abs(cents) / 100:,.2f}"

    @staticmethod
    def _decimal_text(value: Decimal) -> str:
        return format(value.normalize(), "f")

    @staticmethod
    def _clear_layout(layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
