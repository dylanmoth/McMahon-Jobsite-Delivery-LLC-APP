from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from PySide6.QtCore import QDate, QDateTime, QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QDrag, QMouseEvent, QTextCharFormat
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCalendarWidget,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
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
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from mcmahon_dispatch.core.enums import JobStatus
from mcmahon_dispatch.core.formatting import format_currency
from mcmahon_dispatch.core.exceptions import ValidationError
from mcmahon_dispatch.repositories.dispatch_repository import (
    Choice,
    DispatchJobRecord,
    DriverRecord,
    VehicleRecord,
)
from mcmahon_dispatch.services.dispatch_service import (
    ALLOWED_TRANSITIONS,
    BOARD_STATUSES,
    STATUS_LABELS,
    AssignmentRequest,
    DispatchConflict,
    DispatchJobView,
    DispatchService,
    DriverSaveRequest,
    JobSaveRequest,
    StatusChangeRequest,
    VehicleSaveRequest,
)

JOB_MIME = "application/x-mcmahon-dispatch-job"


def _label(status: str) -> str:
    return STATUS_LABELS.get(status, status.replace("_", " ").title())


def _local_text(value: datetime | None, *, include_date: bool = True) -> str:
    if value is None:
        return "Not set"
    local = value.astimezone()
    return local.strftime("%b %d, %Y · %I:%M %p" if include_date else "%I:%M %p")


def _qdate(value: date) -> QDate:
    return QDate(value.year, value.month, value.day)


def _qdatetime(value: datetime | None, fallback: datetime | None = None) -> QDateTime:
    actual = value or fallback or datetime.now(UTC)
    return QDateTime(actual.astimezone())


def _python_datetime(value: QDateTime) -> datetime:
    result = value.toPython()
    if result.tzinfo is None:
        return result.astimezone().astimezone(UTC)
    return result.astimezone(UTC)


def _money(cents: int) -> str:
    return format_currency(cents)


def _display_assignment(record: DispatchJobRecord):
    if record.assignment is not None:
        return record.assignment
    if record.status in {JobStatus.COMPLETED.value, JobStatus.CANCELLED.value}:
        return record.last_assignment
    return None


class MoneySpinBox(QDoubleSpinBox):
    def __init__(self) -> None:
        super().__init__()
        self.setDecimals(2)
        self.setPrefix("$")
        self.setGroupSeparatorShown(True)
        self.setMaximum(1_000_000.00)
        self.setSingleStep(25.00)

    def cents(self) -> int:
        return int(round(self.value() * 100))

    def set_cents(self, cents: int) -> None:
        self.setValue(cents / 100)


class MetricTile(QFrame):
    def __init__(self, label: str) -> None:
        super().__init__()
        self.setObjectName("dispatchMetric")
        self.value = QLabel("0")
        self.value.setObjectName("dispatchMetricValue")
        title = QLabel(label)
        title.setObjectName("dispatchMetricLabel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(1)
        layout.addWidget(self.value)
        layout.addWidget(title)


class JobCard(QFrame):
    selected = Signal(str)
    activated = Signal(str)

    def __init__(
        self,
        view: DispatchJobView,
        *,
        compact: bool = False,
        draggable: bool = True,
    ) -> None:
        super().__init__()
        self.view = view
        self.draggable = draggable
        self.job_id = view.record.id
        self._drag_start = QPoint()
        self.setObjectName("dispatchJobCard")
        self.setProperty("priority", view.record.priority)
        self.setCursor(
            Qt.CursorShape.OpenHandCursor if draggable else Qt.CursorShape.PointingHandCursor
        )

        record = view.record
        number = QLabel(record.job_number)
        number.setObjectName("dispatchJobNumber")
        priority = QLabel(record.priority.upper())
        priority.setObjectName("dispatchPriority")
        priority.setProperty("priority", record.priority)
        header = QHBoxLayout()
        header.addWidget(number)
        header.addStretch()
        header.addWidget(priority)

        customer = QLabel(record.customer_name)
        customer.setObjectName("dispatchCustomer")
        customer.setWordWrap(True)
        route = QLabel(self._route_text(record))
        route.setObjectName("dispatchRoute")
        route.setWordWrap(True)
        schedule = QLabel(self._schedule_text(record))
        schedule.setObjectName("dispatchSchedule")
        schedule.setWordWrap(True)

        assignment_text = "Unassigned"
        display_assignment = _display_assignment(record)
        if display_assignment is not None:
            prefix = "Last: " if record.assignment is None else ""
            assignment_text = (
                f"{prefix}{display_assignment.driver_name}\n{display_assignment.vehicle_name}"
            )
        assignment = QLabel(assignment_text)
        assignment.setObjectName("dispatchAssignment")
        assignment.setWordWrap(True)

        footer = QHBoxLayout()
        amount = QLabel(_money(record.quoted_revenue_cents))
        amount.setObjectName("dispatchAmount")
        alert = QLabel(f"{view.alert_count} alert{'s' if view.alert_count != 1 else ''}")
        alert.setObjectName("dispatchAlertCount")
        alert.setProperty("hasAlerts", bool(view.alert_count))
        footer.addWidget(amount)
        footer.addStretch()
        footer.addWidget(alert)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 9, 10, 9)
        layout.setSpacing(5)
        layout.addLayout(header)
        layout.addWidget(customer)
        if not compact:
            layout.addWidget(route)
        layout.addWidget(schedule)
        layout.addWidget(assignment)
        layout.addLayout(footer)

    @staticmethod
    def _route_text(record: DispatchJobRecord) -> str:
        pickup = record.pickup_address or "Pickup missing"
        delivery = record.delivery_address or "Jobsite missing"
        return f"Pickup: {pickup}\nDeliver: {delivery}"

    @staticmethod
    def _schedule_text(record: DispatchJobRecord) -> str:
        if record.requested_window_start is None:
            return "Unscheduled"
        start = _local_text(record.requested_window_start)
        if record.requested_window_end is None:
            return start
        return f"{start} – {_local_text(record.requested_window_end, include_date=False)}"

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
            self.selected.emit(self.job_id)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self.job_id)
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self.draggable:
            return
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if (event.position().toPoint() - self._drag_start).manhattanLength() < 10:
            return
        mime = QMimeData()
        mime.setData(JOB_MIME, self.job_id.encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)


class DropContainer(QWidget):
    job_dropped = Signal(str, str)

    def __init__(self, status: str, *, editable: bool = True) -> None:
        super().__init__()
        self.status = status
        self.editable = editable
        self.setAcceptDrops(editable)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(6, 6, 6, 6)
        self.layout.setSpacing(8)
        self.layout.addStretch()

    def clear_cards(self) -> None:
        while self.layout.count() > 1:
            item = self.layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def add_card(self, card: JobCard) -> None:
        self.layout.insertWidget(self.layout.count() - 1, card)

    def dragEnterEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self.editable and event.mimeData().hasFormat(JOB_MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self.editable and event.mimeData().hasFormat(JOB_MIME):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if not self.editable or not event.mimeData().hasFormat(JOB_MIME):
            return
        job_id = bytes(event.mimeData().data(JOB_MIME)).decode("utf-8")
        self.job_dropped.emit(job_id, self.status)
        event.acceptProposedAction()


class KanbanLane(QFrame):
    job_selected = Signal(str)
    job_activated = Signal(str)
    job_dropped = Signal(str, str)

    def __init__(self, status: str, *, editable: bool = True) -> None:
        super().__init__()
        self.status = status
        self.editable = editable
        self.setObjectName("kanbanLane")
        self.setMinimumWidth(260)
        self.setMaximumWidth(340)
        self.title = QLabel(_label(status))
        self.title.setObjectName("kanbanTitle")
        self.count = QLabel("0")
        self.count.setObjectName("kanbanCount")
        header = QHBoxLayout()
        header.addWidget(self.title)
        header.addStretch()
        header.addWidget(self.count)

        self.container = DropContainer(status, editable=editable)
        self.container.job_dropped.connect(self.job_dropped)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self.container)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(7, 8, 7, 8)
        layout.setSpacing(6)
        layout.addLayout(header)
        layout.addWidget(scroll, 1)

    def set_jobs(self, jobs: list[DispatchJobView]) -> None:
        self.container.clear_cards()
        self.count.setText(str(len(jobs)))
        for view in jobs:
            card = JobCard(view, draggable=self.editable)
            card.selected.connect(self.job_selected)
            card.activated.connect(self.job_activated)
            self.container.add_card(card)


class JobEditorDialog(QDialog):
    def __init__(
        self,
        service: DispatchService,
        customers: list[Choice],
        record: DispatchJobRecord | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.record = record
        self.setWindowTitle("Edit Job" if record else "New Job")
        self.resize(820, 760)

        self.customer = QComboBox()
        self.customer.setEditable(True)
        self.customer.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.customer.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.customer.addItem("Select customer…", "")
        for choice in customers:
            self.customer.addItem(choice.label, choice.id)

        self.status = QComboBox()
        editable_statuses = (JobStatus.ACCEPTED.value, JobStatus.SCHEDULED.value)
        for status in editable_statuses:
            self.status.addItem(_label(status), status)
        if record is not None and self.status.findData(record.status) < 0:
            self.status.addItem(_label(record.status), record.status)
        if record is not None:
            self.status.setEnabled(False)
            self.status.setToolTip(
                "Use the validated status workflow on the Dispatch board to change status."
            )
        self.priority = QComboBox()
        for value in ("low", "normal", "high", "urgent"):
            self.priority.addItem(value.title(), value)
        self.service_type = QLineEdit("Jobsite Delivery")

        self.window_start = QDateTimeEdit()
        self.window_start.setCalendarPopup(True)
        self.window_start.setDisplayFormat("MMM d, yyyy h:mm AP")
        self.window_end = QDateTimeEdit()
        self.window_end.setCalendarPopup(True)
        self.window_end.setDisplayFormat("MMM d, yyyy h:mm AP")
        start = datetime.now().astimezone().replace(minute=0, second=0, microsecond=0) + timedelta(
            hours=1
        )
        self.window_start.setDateTime(
            _qdatetime(record.requested_window_start if record else None, start)
        )
        self.window_end.setDateTime(
            _qdatetime(record.requested_window_end if record else None, start + timedelta(hours=2))
        )

        self.promised_pickup = QDateTimeEdit()
        self.promised_pickup.setCalendarPopup(True)
        self.promised_pickup.setDisplayFormat("MMM d, yyyy h:mm AP")
        self.promised_delivery = QDateTimeEdit()
        self.promised_delivery.setCalendarPopup(True)
        self.promised_delivery.setDisplayFormat("MMM d, yyyy h:mm AP")
        self.promised_pickup.setDateTime(
            _qdatetime(record.promised_pickup_at if record else None, start)
        )
        self.promised_delivery.setDateTime(
            _qdatetime(record.promised_delivery_at if record else None, start + timedelta(hours=2))
        )

        self.planned_miles = QDoubleSpinBox()
        self.planned_miles.setRange(0, 10000)
        self.planned_miles.setDecimals(2)
        self.planned_miles.setSuffix(" mi")
        self.planned_minutes = QSpinBox()
        self.planned_minutes.setRange(0, 10000)
        self.planned_minutes.setSuffix(" min")
        self.planned_minutes.setValue(90)
        self.revenue = MoneySpinBox()
        self.cost = MoneySpinBox()

        self.pickup_address = QTextEdit()
        self.pickup_address.setFixedHeight(70)
        self.pickup_order = QLineEdit()
        self.pickup_instructions = QTextEdit()
        self.pickup_instructions.setFixedHeight(75)
        self.delivery_address = QTextEdit()
        self.delivery_address.setFixedHeight(70)
        self.delivery_instructions = QTextEdit()
        self.delivery_instructions.setFixedHeight(75)
        self.internal_notes = QTextEdit()
        self.internal_notes.setFixedHeight(80)
        self.dispatch_notes = QTextEdit()
        self.dispatch_notes.setFixedHeight(80)
        self.cancellation_reason = QTextEdit()
        self.cancellation_reason.setFixedHeight(60)

        identity = QGroupBox("Job")
        identity_form = QFormLayout(identity)
        identity_form.addRow("Customer", self.customer)
        identity_form.addRow("Status", self.status)
        identity_form.addRow("Priority", self.priority)
        identity_form.addRow("Service", self.service_type)

        schedule = QGroupBox("Schedule")
        schedule_form = QFormLayout(schedule)
        schedule_form.addRow("Requested start", self.window_start)
        schedule_form.addRow("Requested end", self.window_end)
        schedule_form.addRow("Promised pickup", self.promised_pickup)
        schedule_form.addRow("Promised delivery", self.promised_delivery)
        schedule_form.addRow("Planned miles", self.planned_miles)
        schedule_form.addRow("Planned duration", self.planned_minutes)

        finances = QGroupBox("Financial plan")
        finance_form = QFormLayout(finances)
        finance_form.addRow("Quoted revenue", self.revenue)
        finance_form.addRow("Estimated direct cost", self.cost)
        if not service.can_view_financials:
            finances.hide()

        pickup = QGroupBox("Pickup")
        pickup_form = QFormLayout(pickup)
        pickup_form.addRow("Address", self.pickup_address)
        pickup_form.addRow("Order number", self.pickup_order)
        pickup_form.addRow("Instructions", self.pickup_instructions)

        delivery = QGroupBox("Delivery")
        delivery_form = QFormLayout(delivery)
        delivery_form.addRow("Jobsite address", self.delivery_address)
        delivery_form.addRow("Instructions", self.delivery_instructions)

        notes = QGroupBox("Internal operations")
        notes_form = QFormLayout(notes)
        notes_form.addRow("Internal notes", self.internal_notes)
        notes_form.addRow("Driver / dispatch notes", self.dispatch_notes)
        notes_form.addRow("Cancellation reason", self.cancellation_reason)

        grid = QGridLayout()
        grid.addWidget(identity, 0, 0)
        grid.addWidget(schedule, 0, 1)
        grid.addWidget(pickup, 1, 0)
        grid.addWidget(delivery, 1, 1)
        grid.addWidget(finances, 2, 0)
        grid.addWidget(notes, 2, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        content = QWidget()
        content.setLayout(grid)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        if not service.can_manage:
            buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(False)

        layout = QVBoxLayout(self)
        layout.addWidget(scroll, 1)
        layout.addWidget(buttons)
        self.status.currentIndexChanged.connect(self._update_cancellation_visibility)
        self._load_record()
        self._update_cancellation_visibility()

    def _load_record(self) -> None:
        record = self.record
        if record is None:
            self.status.setCurrentIndex(self.status.findData(JobStatus.SCHEDULED.value))
            self.priority.setCurrentIndex(self.priority.findData("normal"))
            return
        self.customer.setCurrentIndex(max(0, self.customer.findData(record.customer_id or "")))
        self.status.setCurrentIndex(max(0, self.status.findData(record.status)))
        self.priority.setCurrentIndex(max(0, self.priority.findData(record.priority)))
        self.service_type.setText(record.service_type)
        self.planned_miles.setValue(float(record.planned_miles or 0))
        self.planned_minutes.setValue(record.planned_minutes or 0)
        self.revenue.set_cents(record.quoted_revenue_cents)
        self.cost.set_cents(record.estimated_cost_cents)
        self.pickup_address.setPlainText(record.pickup_address)
        self.pickup_order.setText(record.pickup_order_number)
        self.pickup_instructions.setPlainText(record.pickup_instructions)
        self.delivery_address.setPlainText(record.delivery_address)
        self.delivery_instructions.setPlainText(record.delivery_instructions)
        self.internal_notes.setPlainText(record.internal_notes)
        self.dispatch_notes.setPlainText(record.dispatch_notes)
        self.cancellation_reason.setPlainText(record.cancellation_reason or "")

    def _update_cancellation_visibility(self) -> None:
        is_cancelled = self.status.currentData() == JobStatus.CANCELLED.value
        self.cancellation_reason.setEnabled(is_cancelled and self.record is None)

    def request(self) -> JobSaveRequest:
        miles = Decimal(str(self.planned_miles.value())) if self.planned_miles.value() else None
        minutes = self.planned_minutes.value() or None
        return JobSaveRequest(
            customer_id=str(self.customer.currentData() or ""),
            status=str(self.status.currentData()),
            priority=str(self.priority.currentData()),
            service_type=self.service_type.text(),
            requested_window_start=_python_datetime(self.window_start.dateTime()),
            requested_window_end=_python_datetime(self.window_end.dateTime()),
            promised_pickup_at=_python_datetime(self.promised_pickup.dateTime()),
            promised_delivery_at=_python_datetime(self.promised_delivery.dateTime()),
            planned_miles=miles,
            planned_minutes=minutes,
            quoted_revenue_cents=self.revenue.cents(),
            estimated_cost_cents=self.cost.cents(),
            pickup_address=self.pickup_address.toPlainText(),
            pickup_order_number=self.pickup_order.text(),
            pickup_instructions=self.pickup_instructions.toPlainText(),
            delivery_address=self.delivery_address.toPlainText(),
            delivery_instructions=self.delivery_instructions.toPlainText(),
            internal_notes=self.internal_notes.toPlainText(),
            dispatch_notes=self.dispatch_notes.toPlainText(),
            cancellation_reason=self.cancellation_reason.toPlainText(),
        )

    def accept(self) -> None:
        try:
            self.service.validate_job_request(self.request())
        except ValidationError as exc:
            QMessageBox.warning(self, "Job", str(exc))
            return
        super().accept()


class AssignmentDialog(QDialog):
    def __init__(
        self,
        service: DispatchService,
        record: DispatchJobRecord,
        drivers: list[Choice],
        vehicles: list[Choice],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.record = record
        self.setWindowTitle(f"Assign {record.job_number}")
        self.resize(600, 520)

        self.driver = QComboBox()
        self.driver.addItem("Select driver…", "")
        for choice in drivers:
            self.driver.addItem(
                f"{choice.label} · {choice.status.replace('_', ' ').title()}", choice.id
            )
        self.vehicle = QComboBox()
        self.vehicle.addItem("Select vehicle…", "")
        for choice in vehicles:
            self.vehicle.addItem(
                f"{choice.label} · {choice.status.replace('_', ' ').title()}", choice.id
            )

        start, end = service.suggested_assignment_window(record)
        self.starts_at = QDateTimeEdit(_qdatetime(start))
        self.starts_at.setCalendarPopup(True)
        self.starts_at.setDisplayFormat("MMM d, yyyy h:mm AP")
        self.ends_at = QDateTimeEdit(_qdatetime(end))
        self.ends_at.setCalendarPopup(True)
        self.ends_at.setDisplayFormat("MMM d, yyyy h:mm AP")
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("Reason for assignment or reassignment")

        if record.assignment is not None:
            self.driver.setCurrentIndex(max(0, self.driver.findData(record.assignment.driver_id)))
            self.vehicle.setCurrentIndex(
                max(0, self.vehicle.findData(record.assignment.vehicle_id))
            )
            self.starts_at.setDateTime(_qdatetime(record.assignment.starts_at))
            self.ends_at.setDateTime(_qdatetime(record.assignment.ends_at))

        form = QFormLayout()
        form.addRow("Driver", self.driver)
        form.addRow("Vehicle", self.vehicle)
        form.addRow("Starts", self.starts_at)
        form.addRow("Ends", self.ends_at)
        form.addRow("Reason", self.reason)

        check = QPushButton("Check conflicts")
        check.clicked.connect(self._check_conflicts)
        self.conflicts = QTextEdit()
        self.conflicts.setReadOnly(True)
        self.conflicts.setMinimumHeight(170)
        self.conflicts.setPlainText("Choose a driver and vehicle, then check conflicts.")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(check)
        layout.addWidget(self.conflicts, 1)
        layout.addWidget(buttons)

    def request(self) -> AssignmentRequest:
        return AssignmentRequest(
            driver_id=str(self.driver.currentData() or ""),
            vehicle_id=str(self.vehicle.currentData() or ""),
            starts_at=_python_datetime(self.starts_at.dateTime()),
            ends_at=_python_datetime(self.ends_at.dateTime()),
            reason=self.reason.text(),
        )

    def _check_conflicts(self) -> list[DispatchConflict]:
        try:
            values = self.service.assignment_conflicts(self.record.id, self.request())
        except ValidationError as exc:
            QMessageBox.warning(self, "Assignment", str(exc))
            return []
        if not values:
            self.conflicts.setPlainText(
                "No driver, vehicle, availability, or overlap conflicts found."
            )
        else:
            self.conflicts.setPlainText("\n\n".join(f"• {value.message}" for value in values))
        return values

    def accept(self) -> None:
        try:
            request = self.request()
            self.service.validate_assignment_request(request)
        except ValidationError as exc:
            QMessageBox.warning(self, "Assignment", str(exc))
            return
        super().accept()


class StatusChangeDialog(QDialog):
    def __init__(
        self,
        current_status: str,
        target_status: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.current_status = current_status
        self.target_status = target_status
        self.setWindowTitle(f"Move to {_label(target_status)}")
        self.resize(520, 420)

        transition = QLabel(f"{_label(current_status)}  →  {_label(target_status)}")
        transition.setObjectName("statusTransition")
        transition.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.requirements = QCheckBox(self._confirmation_text(current_status, target_status))
        self.requirements.setChecked(
            target_status in {JobStatus.WAITING.value, JobStatus.CANCELLED.value}
        )
        self.note = QTextEdit()
        self.note.setFixedHeight(80)
        self.reason = QTextEdit()
        self.reason.setFixedHeight(70)
        self.override = QTextEdit()
        self.override.setFixedHeight(70)
        form = QFormLayout()
        form.addRow("Operational confirmation", self.requirements)
        form.addRow("Status note", self.note)
        form.addRow("Reason", self.reason)
        form.addRow("Override reason", self.override)

        guidance = QLabel(self._guidance(current_status, target_status))
        guidance.setObjectName("panelSubtitle")
        guidance.setWordWrap(True)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(transition)
        layout.addWidget(guidance)
        layout.addLayout(form)
        layout.addWidget(buttons)

    @staticmethod
    def _confirmation_text(current: str, target: str) -> str:
        if current == JobStatus.SCHEDULED.value and target == JobStatus.PICKING_UP.value:
            return "Pickup checklist and assignment are confirmed"
        if current == JobStatus.PICKING_UP.value and target == JobStatus.IN_TRANSIT.value:
            return "Pickup, material condition, and securement are confirmed"
        if current == JobStatus.IN_TRANSIT.value and target == JobStatus.DELIVERED.value:
            return "Delivery proof requirements are complete"
        if current == JobStatus.DELIVERED.value and target == JobStatus.COMPLETED.value:
            return "Actuals and invoicing disposition are reviewed"
        return "Operational requirements for this status are confirmed"

    @staticmethod
    def _guidance(current: str, target: str) -> str:
        if target == JobStatus.WAITING.value:
            return "The wait timer starts immediately when this change is saved."
        if current == JobStatus.WAITING.value:
            return "The open wait timer stops and the charge recommendation recalculates."
        if target == JobStatus.CANCELLED.value:
            return "Cancellation requires a reason. Pricing and customer communication should be reviewed."
        return (
            "The change is recorded in the permanent job timeline with the current user and time."
        )

    def request(self) -> StatusChangeRequest:
        return StatusChangeRequest(
            target_status=self.target_status,
            note=self.note.toPlainText(),
            reason=self.reason.toPlainText(),
            requirements_confirmed=self.requirements.isChecked(),
            override_reason=self.override.toPlainText(),
        )


class DriverDialog(QDialog):
    STATUSES = (
        "available",
        "on_duty",
        "assigned",
        "on_job",
        "off_duty",
        "time_off",
        "unavailable",
        "inactive",
    )

    def __init__(self, record: DriverRecord | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.record = record
        self.setWindowTitle("Edit Driver" if record else "New Driver")
        self.resize(520, 520)
        self.first_name = QLineEdit()
        self.last_name = QLineEdit()
        self.phone = QLineEdit()
        self.email = QLineEdit()
        self.status = QComboBox()
        for value in self.STATUSES:
            self.status.addItem(value.replace("_", " ").title(), value)
        self.license_state = QLineEdit()
        self.license_state.setMaxLength(2)
        self.license_expiration = QDateEdit()
        self.license_expiration.setCalendarPopup(True)
        self.license_expiration.setSpecialValueText("Not set")
        self.license_expiration.setMinimumDate(QDate(1900, 1, 1))
        self.license_expiration.setDate(QDate(1900, 1, 1))
        self.notes = QTextEdit()
        self.notes.setMinimumHeight(100)
        form = QFormLayout()
        form.addRow("First name", self.first_name)
        form.addRow("Last name", self.last_name)
        form.addRow("Phone", self.phone)
        form.addRow("Email", self.email)
        form.addRow("Status", self.status)
        form.addRow("License state", self.license_state)
        form.addRow("License expiration", self.license_expiration)
        form.addRow("Notes", self.notes)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        if record:
            self.first_name.setText(record.first_name)
            self.last_name.setText(record.last_name)
            self.phone.setText(record.phone)
            self.email.setText(record.email)
            self.status.setCurrentIndex(max(0, self.status.findData(record.status)))
            self.license_state.setText(record.license_state)
            if record.license_expiration:
                self.license_expiration.setDate(_qdate(record.license_expiration))
            self.notes.setPlainText(record.notes)

    def request(self) -> DriverSaveRequest:
        expiration = self.license_expiration.date().toPython()
        if expiration == date(1900, 1, 1):
            expiration = None
        return DriverSaveRequest(
            first_name=self.first_name.text(),
            last_name=self.last_name.text(),
            phone=self.phone.text(),
            email=self.email.text(),
            status=str(self.status.currentData()),
            license_state=self.license_state.text(),
            license_expiration=expiration,
            notes=self.notes.toPlainText(),
        )


class VehicleDialog(QDialog):
    STATUSES = ("available", "assigned", "reserved", "maintenance", "out_of_service", "inactive")

    def __init__(self, record: VehicleRecord | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.record = record
        self.setWindowTitle("Edit Vehicle" if record else "New Vehicle")
        self.resize(560, 650)
        self.year = QSpinBox()
        self.year.setRange(1900, 2200)
        self.year.setValue(datetime.now().year)
        self.make = QLineEdit()
        self.model = QLineEdit()
        self.trim = QLineEdit()
        self.status = QComboBox()
        for value in self.STATUSES:
            self.status.addItem(value.replace("_", " ").title(), value)
        self.cargo_length = QDoubleSpinBox()
        self.cargo_width = QDoubleSpinBox()
        self.cargo_height = QDoubleSpinBox()
        for field in (self.cargo_length, self.cargo_width, self.cargo_height):
            field.setRange(0, 1000)
            field.setDecimals(2)
            field.setSuffix(" in")
        self.payload = QDoubleSpinBox()
        self.payload.setRange(0, 100000)
        self.payload.setDecimals(2)
        self.payload.setSuffix(" lb")
        self.cost_per_mile = QDoubleSpinBox()
        self.cost_per_mile.setRange(0, 1000)
        self.cost_per_mile.setDecimals(2)
        self.cost_per_mile.setPrefix("$")
        self.cost_per_mile.setSuffix(" / mi")
        self.registration = QDateEdit()
        self.insurance = QDateEdit()
        for field in (self.registration, self.insurance):
            field.setCalendarPopup(True)
            field.setSpecialValueText("Not set")
            field.setMinimumDate(QDate(1900, 1, 1))
            field.setDate(QDate(1900, 1, 1))
        self.notes = QTextEdit()
        self.notes.setMinimumHeight(90)
        form = QFormLayout()
        form.addRow("Year", self.year)
        form.addRow("Make", self.make)
        form.addRow("Model", self.model)
        form.addRow("Trim", self.trim)
        form.addRow("Status", self.status)
        form.addRow("Cargo length", self.cargo_length)
        form.addRow("Cargo width", self.cargo_width)
        form.addRow("Cargo height", self.cargo_height)
        form.addRow("Payload", self.payload)
        form.addRow("Direct cost per mile", self.cost_per_mile)
        form.addRow("Registration expires", self.registration)
        form.addRow("Insurance expires", self.insurance)
        form.addRow("Notes", self.notes)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        if record:
            self.year.setValue(record.year)
            self.make.setText(record.make)
            self.model.setText(record.model)
            self.trim.setText(record.trim)
            self.status.setCurrentIndex(max(0, self.status.findData(record.status)))
            self.cargo_length.setValue(float(record.cargo_length_inches or 0))
            self.cargo_width.setValue(float(record.cargo_width_inches or 0))
            self.cargo_height.setValue(float(record.cargo_height_inches or 0))
            self.payload.setValue(float(record.payload_pounds or 0))
            self.cost_per_mile.setValue((record.cost_per_mile_cents or 0) / 100)
            if record.registration_expires_on:
                self.registration.setDate(_qdate(record.registration_expires_on))
            if record.insurance_expires_on:
                self.insurance.setDate(_qdate(record.insurance_expires_on))
            self.notes.setPlainText(record.notes)

    @staticmethod
    def _decimal_or_none(value: float) -> Decimal | None:
        return Decimal(str(value)) if value else None

    def request(self) -> VehicleSaveRequest:
        registration = self.registration.date().toPython()
        insurance = self.insurance.date().toPython()
        return VehicleSaveRequest(
            year=self.year.value(),
            make=self.make.text(),
            model=self.model.text(),
            trim=self.trim.text(),
            status=str(self.status.currentData()),
            cargo_length_inches=self._decimal_or_none(self.cargo_length.value()),
            cargo_width_inches=self._decimal_or_none(self.cargo_width.value()),
            cargo_height_inches=self._decimal_or_none(self.cargo_height.value()),
            payload_pounds=self._decimal_or_none(self.payload.value()),
            cost_per_mile_cents=int(round(self.cost_per_mile.value() * 100)) or None,
            registration_expires_on=None if registration == date(1900, 1, 1) else registration,
            insurance_expires_on=None if insurance == date(1900, 1, 1) else insurance,
            notes=self.notes.toPlainText(),
        )


class JobDetailPanel(QFrame):
    edit_requested = Signal(str)
    assign_requested = Signal(str)
    status_requested = Signal(str)

    def __init__(self, service: DispatchService) -> None:
        super().__init__()
        self.service = service
        self.current_id: str | None = None
        self.setObjectName("dispatchDetail")
        self.setMinimumWidth(290)
        self.setMaximumWidth(390)
        self.title = QLabel("Job details")
        self.title.setObjectName("panelTitle")
        self.number = QLabel("Select a job")
        self.number.setObjectName("quoteNumber")
        self.summary = QLabel(
            "Select a card or row to inspect assignment, route, schedule, alerts, and timeline."
        )
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.alerts = QTextEdit()
        self.alerts.setReadOnly(True)
        self.alerts.setMinimumHeight(120)
        self.timeline = QTextEdit()
        self.timeline.setReadOnly(True)
        self.timeline.setMinimumHeight(180)
        self.edit_button = QPushButton("Edit job")
        self.edit_button.setObjectName("primary")
        self.edit_button.clicked.connect(
            lambda _checked=False: self.current_id and self.edit_requested.emit(self.current_id)
        )
        self.assign_button = QPushButton("Assign driver / vehicle")
        self.assign_button.clicked.connect(
            lambda _checked=False: self.current_id and self.assign_requested.emit(self.current_id)
        )
        self.status_button = QPushButton("Change status")
        self.status_button.clicked.connect(
            lambda _checked=False: self.current_id and self.status_requested.emit(self.current_id)
        )
        for button in (self.edit_button, self.assign_button, self.status_button):
            button.setEnabled(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(9)
        layout.addWidget(self.title)
        layout.addWidget(self.number)
        layout.addWidget(self.summary)
        alert_title = QLabel("Warnings and next actions")
        alert_title.setObjectName("sectionTitle")
        layout.addWidget(alert_title)
        layout.addWidget(self.alerts)
        timeline_title = QLabel("Status timeline")
        timeline_title.setObjectName("sectionTitle")
        layout.addWidget(timeline_title)
        layout.addWidget(self.timeline, 1)
        layout.addWidget(self.edit_button)
        layout.addWidget(self.assign_button)
        layout.addWidget(self.status_button)

    def show_job(self, view: DispatchJobView) -> None:
        self.current_id = view.record.id
        record = view.record
        self.number.setText(f"{record.job_number} · {_label(record.status)}")
        assignment = "Unassigned"
        display_assignment = _display_assignment(record)
        if display_assignment:
            prefix = "Last assignment: " if record.assignment is None else ""
            assignment = (
                f"{prefix}{display_assignment.driver_name} / {display_assignment.vehicle_name}"
            )
        financial = ""
        if self.service.can_view_financials:
            financial = f"\nRevenue: {_money(record.quoted_revenue_cents)} · Estimated cost: {_money(record.estimated_cost_cents)}"
        self.summary.setText(
            f"{record.customer_name}\n"
            f"{record.service_type} · {record.priority.title()} priority\n"
            f"Window: {_local_text(record.requested_window_start)} to {_local_text(record.requested_window_end, include_date=False)}\n"
            f"Pickup: {record.pickup_address or 'Missing'}\n"
            f"Delivery: {record.delivery_address or 'Missing'}\n"
            f"Assignment: {assignment}{financial}"
        )
        if view.alerts:
            self.alerts.setPlainText("\n\n".join(f"• {alert.message}" for alert in view.alerts))
        else:
            self.alerts.setPlainText("No active dispatch warnings.")
        try:
            events = self.service.timeline(record.id)
        except ValidationError:
            events = []
        self.timeline.setPlainText(
            "\n\n".join(
                f"{_local_text(event.occurred_at)}\n"
                f"{_label(event.from_status) if event.from_status else 'Created'} → {_label(event.to_status)}"
                f"{f'\n{event.note}' if event.note else ''}"
                f"{f'\nOverride: {event.override_reason}' if event.override_reason else ''}"
                for event in events
            )
            or "No timeline events recorded."
        )
        for button in (self.edit_button, self.assign_button, self.status_button):
            button.setEnabled(self.service.can_manage)


class CalendarDropBody(QWidget):
    job_dropped = Signal(str, object)

    def __init__(self, lane_date: date, *, editable: bool = True) -> None:
        super().__init__()
        self.lane_date = lane_date
        self.editable = editable
        self.setAcceptDrops(editable)
        self.cards = QVBoxLayout(self)
        self.cards.setContentsMargins(6, 6, 6, 6)
        self.cards.setSpacing(8)
        self.cards.addStretch()

    def clear_cards(self) -> None:
        while self.cards.count() > 1:
            item = self.cards.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def add_card(self, card: JobCard) -> None:
        self.cards.insertWidget(self.cards.count() - 1, card)

    def dragEnterEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self.editable and event.mimeData().hasFormat(JOB_MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self.editable and event.mimeData().hasFormat(JOB_MIME):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if not self.editable or not event.mimeData().hasFormat(JOB_MIME):
            return
        job_id = bytes(event.mimeData().data(JOB_MIME)).decode("utf-8")
        self.job_dropped.emit(job_id, self.lane_date)
        event.acceptProposedAction()


class DateDropLane(QFrame):
    job_dropped = Signal(str, object)
    job_selected = Signal(str)
    job_activated = Signal(str)

    def __init__(
        self,
        lane_date: date,
        title_text: str | None = None,
        *,
        editable: bool = True,
    ) -> None:
        super().__init__()
        self.lane_date = lane_date
        self.editable = editable
        self.setObjectName("calendarLane")
        self.setMinimumWidth(245)
        title = QLabel(title_text or lane_date.strftime("%A\n%b %d"))
        title.setObjectName("calendarLaneTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setWordWrap(True)
        self.body = CalendarDropBody(lane_date, editable=editable)
        self.body.job_dropped.connect(self.job_dropped)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self.body)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(7, 7, 7, 7)
        layout.addWidget(title)
        layout.addWidget(scroll, 1)

    def set_jobs(self, jobs: list[DispatchJobView]) -> None:
        self.body.clear_cards()
        for view in jobs:
            card = JobCard(view, compact=True, draggable=self.editable)
            card.selected.connect(self.job_selected)
            card.activated.connect(self.job_activated)
            self.body.add_card(card)


class CalendarPanel(QWidget):
    job_selected = Signal(str)
    job_activated = Signal(str)
    job_reschedule_requested = Signal(str, object)
    range_changed = Signal()

    def __init__(self, *, editable: bool = True) -> None:
        super().__init__()
        self.editable = editable
        self.anchor = date.today()
        self.mode = "week"
        self.jobs: list[DispatchJobView] = []
        self._rendering_month = False
        self.previous = QPushButton("‹")
        self.next = QPushButton("›")
        self.today = QPushButton("Today")
        self.period = QLabel("")
        self.period.setObjectName("calendarPeriod")
        self.day_button = QToolButton()
        self.day_button.setText("Day")
        self.week_button = QToolButton()
        self.week_button.setText("Week")
        self.month_button = QToolButton()
        self.month_button.setText("Month")
        for button in (self.day_button, self.week_button, self.month_button):
            button.setCheckable(True)
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_group.addButton(self.day_button)
        self.mode_group.addButton(self.week_button)
        self.mode_group.addButton(self.month_button)
        self.week_button.setChecked(True)
        self.previous.clicked.connect(lambda _checked=False: self._move(-1))
        self.next.clicked.connect(lambda _checked=False: self._move(1))
        self.today.clicked.connect(self._today)
        self.day_button.clicked.connect(lambda _checked=False: self.set_mode("day"))
        self.week_button.clicked.connect(lambda _checked=False: self.set_mode("week"))
        self.month_button.clicked.connect(lambda _checked=False: self.set_mode("month"))
        toolbar = QHBoxLayout()
        toolbar.addWidget(self.previous)
        toolbar.addWidget(self.today)
        toolbar.addWidget(self.next)
        toolbar.addWidget(self.period)
        toolbar.addStretch()
        toolbar.addWidget(self.day_button)
        toolbar.addWidget(self.week_button)
        toolbar.addWidget(self.month_button)

        self.stack = QStackedWidget()
        self.timeline_host = QWidget()
        self.timeline_layout = QHBoxLayout(self.timeline_host)
        self.timeline_layout.setContentsMargins(0, 0, 0, 0)
        self.timeline_layout.setSpacing(8)
        self.timeline_scroll = QScrollArea()
        self.timeline_scroll.setWidgetResizable(True)
        self.timeline_scroll.setWidget(self.timeline_host)
        self.stack.addWidget(self.timeline_scroll)

        self.month_calendar = QCalendarWidget()
        self.month_calendar.setGridVisible(True)
        self.month_calendar.setNavigationBarVisible(False)
        self.month_calendar.selectionChanged.connect(self._month_selection_changed)
        self.month_agenda = QVBoxLayout()
        self.month_agenda.addStretch()
        agenda_widget = QWidget()
        agenda_widget.setLayout(self.month_agenda)
        agenda_scroll = QScrollArea()
        agenda_scroll.setWidgetResizable(True)
        agenda_scroll.setWidget(agenda_widget)
        month_splitter = QSplitter(Qt.Orientation.Horizontal)
        month_splitter.addWidget(self.month_calendar)
        month_splitter.addWidget(agenda_scroll)
        month_splitter.setSizes([620, 420])
        self.stack.addWidget(month_splitter)

        self.queue_panel = QFrame()
        self.queue_panel.setObjectName("dispatchDetail")
        self.queue_panel.setMinimumWidth(260)
        self.queue_panel.setMaximumWidth(340)
        queue_title = QLabel("Unassigned / Unscheduled")
        queue_title.setObjectName("panelTitle")
        queue_help = QLabel("Drag a job into a day or week lane to move its schedule.")
        queue_help.setObjectName("panelSubtitle")
        queue_help.setWordWrap(True)
        self.queue_layout = QVBoxLayout()
        self.queue_layout.setSpacing(8)
        self.queue_layout.addStretch()
        queue_content = QWidget()
        queue_content.setLayout(self.queue_layout)
        queue_scroll = QScrollArea()
        queue_scroll.setWidgetResizable(True)
        queue_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        queue_scroll.setWidget(queue_content)
        queue_box = QVBoxLayout(self.queue_panel)
        queue_box.setContentsMargins(12, 12, 12, 12)
        queue_box.addWidget(queue_title)
        queue_box.addWidget(queue_help)
        queue_box.addWidget(queue_scroll, 1)

        self.body = QSplitter(Qt.Orientation.Horizontal)
        self.body.addWidget(self.stack)
        self.body.addWidget(self.queue_panel)
        self.body.setStretchFactor(0, 1)
        self.body.setStretchFactor(1, 0)
        self.body.setSizes([1050, 300])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(toolbar)
        layout.addWidget(self.body, 1)
        self.render()

    def visible_range(self) -> tuple[datetime, datetime]:
        if self.mode == "day":
            start_date = self.anchor
            end_date = self.anchor + timedelta(days=1)
        elif self.mode == "week":
            start_date = self.anchor - timedelta(days=self.anchor.weekday())
            end_date = start_date + timedelta(days=7)
        else:
            start_date = self.anchor.replace(day=1)
            if start_date.month == 12:
                end_date = date(start_date.year + 1, 1, 1)
            else:
                end_date = date(start_date.year, start_date.month + 1, 1)
        return (
            datetime.combine(start_date, time.min, tzinfo=UTC),
            datetime.combine(end_date, time.min, tzinfo=UTC),
        )

    def set_jobs(self, jobs: list[DispatchJobView]) -> None:
        self.jobs = jobs
        self.render()

    def set_mode(self, mode: str) -> None:
        if mode not in {"day", "week", "month"}:
            return
        self.mode = mode
        self.stack.setCurrentIndex(1 if mode == "month" else 0)
        self.render()
        self.range_changed.emit()

    def _move(self, direction: int) -> None:
        if self.mode == "day":
            self.anchor += timedelta(days=direction)
        elif self.mode == "week":
            self.anchor += timedelta(days=7 * direction)
        else:
            month = self.anchor.month + direction
            year = self.anchor.year
            if month < 1:
                month = 12
                year -= 1
            elif month > 12:
                month = 1
                year += 1
            self.anchor = date(year, month, 1)
        self.render()
        self.range_changed.emit()

    def _today(self) -> None:
        self.anchor = date.today()
        self.render()
        self.range_changed.emit()

    def render(self) -> None:
        self._render_queue()
        if self.mode == "month":
            self._render_month()
        else:
            self._render_timeline()

    def _render_timeline(self) -> None:
        while self.timeline_layout.count():
            item = self.timeline_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        grouped_by_date: dict[date, list[DispatchJobView]] = defaultdict(list)
        for view in self.jobs:
            value = view.record.requested_window_start or view.record.promised_pickup_at
            if value:
                grouped_by_date[value.astimezone().date()].append(view)
        if self.mode == "day":
            self.period.setText(self.anchor.strftime("%A, %B %d, %Y"))
            day_jobs = grouped_by_date.get(self.anchor, [])
            grouped_by_driver: dict[str, list[DispatchJobView]] = defaultdict(list)
            for view in day_jobs:
                display_assignment = _display_assignment(view.record)
                driver = display_assignment.driver_name if display_assignment else "Unassigned"
                grouped_by_driver[driver].append(view)
            if not grouped_by_driver:
                grouped_by_driver["Unassigned"] = []
            for driver_name in sorted(
                grouped_by_driver, key=lambda value: (value == "Unassigned", value)
            ):
                lane = DateDropLane(
                    self.anchor,
                    f"{driver_name}\n{self.anchor.strftime('%b %d')}",
                    editable=self.editable,
                )
                lane.set_jobs(grouped_by_driver[driver_name])
                lane.job_selected.connect(self.job_selected)
                lane.job_activated.connect(self.job_activated)
                lane.job_dropped.connect(self.job_reschedule_requested)
                self.timeline_layout.addWidget(lane, 1)
        else:
            start = self.anchor - timedelta(days=self.anchor.weekday())
            dates = [start + timedelta(days=index) for index in range(7)]
            self.period.setText(f"{dates[0].strftime('%b %d')} – {dates[-1].strftime('%b %d, %Y')}")
            for lane_date in dates:
                lane = DateDropLane(lane_date, editable=self.editable)
                lane.set_jobs(grouped_by_date.get(lane_date, []))
                lane.job_selected.connect(self.job_selected)
                lane.job_activated.connect(self.job_activated)
                lane.job_dropped.connect(self.job_reschedule_requested)
                self.timeline_layout.addWidget(lane, 1)
        self.timeline_layout.addStretch()

    def _render_month(self) -> None:
        self.period.setText(self.anchor.strftime("%B %Y"))
        self._rendering_month = True
        self.month_calendar.setCurrentPage(self.anchor.year, self.anchor.month)
        self.month_calendar.setSelectedDate(_qdate(self.anchor))
        default = QTextCharFormat()
        for day_offset in range(1, 32):
            candidate = QDate(self.anchor.year, self.anchor.month, day_offset)
            if candidate.isValid():
                self.month_calendar.setDateTextFormat(candidate, default)
        counts: dict[date, int] = defaultdict(int)
        for view in self.jobs:
            value = view.record.requested_window_start or view.record.promised_pickup_at
            if value:
                counts[value.astimezone().date()] += 1
        for target, count in counts.items():
            if target.year != self.anchor.year or target.month != self.anchor.month:
                continue
            fmt = QTextCharFormat()
            fmt.setToolTip(f"{count} job{'s' if count != 1 else ''}")
            fmt.setFontWeight(700)
            self.month_calendar.setDateTextFormat(_qdate(target), fmt)
        self._rendering_month = False
        self._render_month_agenda(self.month_calendar.selectedDate().toPython())

    def _month_selection_changed(self) -> None:
        if self._rendering_month:
            return
        selected = self.month_calendar.selectedDate().toPython()
        month_changed = (selected.year, selected.month) != (self.anchor.year, self.anchor.month)
        self.anchor = selected
        self._render_month_agenda(selected)
        if month_changed:
            self.range_changed.emit()

    def _render_month_agenda(self, selected: date) -> None:
        while self.month_agenda.count() > 1:
            item = self.month_agenda.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        title = QLabel(selected.strftime("%A, %B %d"))
        title.setObjectName("panelTitle")
        self.month_agenda.insertWidget(0, title)
        matched: list[DispatchJobView] = []
        for view in self.jobs:
            value = view.record.requested_window_start or view.record.promised_pickup_at
            if value and value.astimezone().date() == selected:
                matched.append(view)
        if not matched:
            empty = QLabel("No scheduled jobs.")
            empty.setObjectName("emptyState")
            self.month_agenda.insertWidget(1, empty)
        else:
            for index, view in enumerate(matched, start=1):
                card = JobCard(view, compact=True, draggable=False)
                card.selected.connect(self.job_selected)
                card.activated.connect(self.job_activated)
                self.month_agenda.insertWidget(index, card)

    def _render_queue(self) -> None:
        while self.queue_layout.count() > 1:
            item = self.queue_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        queued = [
            view
            for view in self.jobs
            if view.record.status not in {JobStatus.COMPLETED.value, JobStatus.CANCELLED.value}
            and (
                view.record.assignment is None
                or view.record.requested_window_start is None
                or view.record.status == JobStatus.ACCEPTED.value
            )
        ]
        if not queued:
            empty = QLabel("No unassigned or unscheduled jobs.")
            empty.setObjectName("emptyState")
            empty.setWordWrap(True)
            self.queue_layout.insertWidget(0, empty)
            return
        for index, view in enumerate(queued):
            card = JobCard(view, compact=True, draggable=self.editable)
            card.selected.connect(self.job_selected)
            card.activated.connect(self.job_activated)
            self.queue_layout.insertWidget(index, card)

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        narrow = self.width() < 900
        if narrow:
            if self.body.orientation() != Qt.Orientation.Vertical:
                self.body.setOrientation(Qt.Orientation.Vertical)
            self.queue_panel.setMaximumWidth(16_777_215)
            self.queue_panel.setMaximumHeight(260)
            self.body.setSizes([max(420, self.height() - 270), 250])
        else:
            if self.body.orientation() != Qt.Orientation.Horizontal:
                self.body.setOrientation(Qt.Orientation.Horizontal)
            self.queue_panel.setMaximumHeight(16_777_215)
            self.queue_panel.setMaximumWidth(340)
            self.body.setSizes([max(700, self.width() - 310), 300])


class DispatchPage(QWidget):
    def __init__(self, service: DispatchService) -> None:
        super().__init__()
        self.service = service
        self.current_job_id: str | None = None
        self.customer_choices: list[Choice] = []
        self.driver_choices: list[Choice] = []
        self.vehicle_choices: list[Choice] = []
        self.current_jobs: list[DispatchJobView] = []
        self.all_jobs: list[DispatchJobView] = []
        self.setObjectName("dispatchPage")

        title = QLabel("Dispatch Center")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Schedule, assign, and move every delivery through a validated operational workflow."
        )
        subtitle.setObjectName("panelSubtitle")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search job, customer, service, or notes")
        self.search.setClearButtonEnabled(True)
        self.search.returnPressed.connect(self.refresh)
        self.driver_filter = QComboBox()
        self.driver_filter.addItem("All drivers", "")
        self.driver_filter.currentIndexChanged.connect(self.refresh)
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh)
        self.new_job_button = QPushButton("New Job")
        self.new_job_button.setObjectName("primary")
        self.new_job_button.clicked.connect(self.new_job)
        self.new_job_button.setEnabled(service.can_manage)

        self.heading_widget = QWidget()
        heading = QVBoxLayout(self.heading_widget)
        heading.setContentsMargins(0, 0, 0, 0)
        heading.setSpacing(1)
        heading.addWidget(title)
        heading.addWidget(subtitle)
        self.subtitle = subtitle
        self.refresh_button = refresh_button
        self.header_grid = QGridLayout()
        self.header_grid.setContentsMargins(0, 0, 0, 0)
        self.header_grid.setHorizontalSpacing(8)
        self.header_grid.setVerticalSpacing(8)

        self.metric_active = MetricTile("Active")
        self.metric_unassigned = MetricTile("Unassigned")
        self.metric_waiting = MetricTile("Waiting")
        self.metric_overdue = MetricTile("Overdue")
        self.metric_today = MetricTile("Today")
        self.metric_completed = MetricTile("Completed today")
        self.metric_tiles = (
            self.metric_active,
            self.metric_unassigned,
            self.metric_waiting,
            self.metric_overdue,
            self.metric_today,
            self.metric_completed,
        )
        self.metrics_grid = QGridLayout()
        self.metrics_grid.setContentsMargins(0, 0, 0, 0)
        self.metrics_grid.setHorizontalSpacing(8)
        self.metrics_grid.setVerticalSpacing(8)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.board = self._build_board()
        self.calendar = CalendarPanel(editable=service.can_manage)
        self.calendar.job_selected.connect(self.select_job)
        self.calendar.job_activated.connect(self.edit_job)
        self.calendar.job_reschedule_requested.connect(self._reschedule_from_calendar)
        self.calendar.range_changed.connect(self._refresh_calendar)
        self.jobs_table = self._build_jobs_table()
        self.drivers_tab = self._build_drivers_tab()
        self.fleet_tab = self._build_fleet_tab()
        self.tabs.addTab(self.board, "Job Board")
        self.tabs.addTab(self.calendar, "Calendar")
        self.tabs.addTab(self.jobs_table, "All Jobs")
        self.tabs.addTab(self.drivers_tab, "Drivers")
        self.tabs.addTab(self.fleet_tab, "Fleet")

        self.detail = JobDetailPanel(service)
        self.detail.edit_requested.connect(self.edit_job)
        self.detail.assign_requested.connect(self.assign_job)
        self.detail.status_requested.connect(self.choose_status)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.tabs)
        self.splitter.addWidget(self.detail)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setSizes([1120, 330])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        layout.addLayout(self.header_grid)
        layout.addLayout(self.metrics_grid)
        layout.addWidget(self.splitter, 1)
        self._arrange_responsive()
        self.refresh()

    def _arrange_responsive(self) -> None:
        while self.header_grid.count():
            self.header_grid.takeAt(0)
        while self.metrics_grid.count():
            self.metrics_grid.takeAt(0)
        narrow = self.width() < 1050
        self.subtitle.setVisible(not narrow)
        if narrow:
            self.header_grid.addWidget(self.heading_widget, 0, 0, 1, 5)
            self.header_grid.addWidget(self.search, 1, 0, 1, 2)
            self.header_grid.addWidget(self.driver_filter, 1, 2)
            self.header_grid.addWidget(self.refresh_button, 1, 3)
            self.header_grid.addWidget(self.new_job_button, 1, 4)
            columns = 3
        else:
            self.header_grid.addWidget(self.heading_widget, 0, 0)
            self.header_grid.setColumnStretch(0, 1)
            self.header_grid.addWidget(self.search, 0, 1)
            self.header_grid.setColumnStretch(1, 2)
            self.header_grid.addWidget(self.driver_filter, 0, 2)
            self.header_grid.addWidget(self.refresh_button, 0, 3)
            self.header_grid.addWidget(self.new_job_button, 0, 4)
            columns = 6
        for index, metric in enumerate(self.metric_tiles):
            self.metrics_grid.addWidget(metric, index // columns, index % columns)
            self.metrics_grid.setColumnStretch(index % columns, 1)

    def _build_board(self) -> QWidget:
        host = QWidget()
        layout = QHBoxLayout(host)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)
        self.lanes: dict[str, KanbanLane] = {}
        for status in BOARD_STATUSES:
            lane = KanbanLane(status, editable=self.service.can_manage)
            lane.job_selected.connect(self.select_job)
            lane.job_activated.connect(self.edit_job)
            lane.job_dropped.connect(self._move_job)
            self.lanes[status] = lane
            layout.addWidget(lane)
        layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(host)
        return scroll

    def _build_jobs_table(self) -> QTableWidget:
        table = QTableWidget(0, 10)
        table.setHorizontalHeaderLabels(
            [
                "Job",
                "Customer",
                "Status",
                "Priority",
                "Window",
                "Driver",
                "Vehicle",
                "Pickup",
                "Delivery",
                "Alerts",
            ]
        )
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().hide()
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeMode.Stretch)
        table.itemSelectionChanged.connect(self._table_selected)
        table.itemDoubleClicked.connect(
            lambda item, _column: self.edit_job(str(item.data(Qt.ItemDataRole.UserRole)))
        )
        return table

    def _build_drivers_tab(self) -> QWidget:
        page = QWidget()
        self.drivers_table = QTableWidget(0, 8)
        self.drivers_table.setHorizontalHeaderLabels(
            [
                "Number",
                "Driver",
                "Status",
                "Phone",
                "Email",
                "License State",
                "License Expires",
                "Notes",
            ]
        )
        self.drivers_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.drivers_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.drivers_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.drivers_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.drivers_table.horizontalHeader().setSectionResizeMode(
            7, QHeaderView.ResizeMode.Stretch
        )
        add = QPushButton("New Driver")
        add.setObjectName("primary")
        add.setEnabled(self.service.can_manage)
        add.clicked.connect(self.new_driver)
        edit = QPushButton("Edit Selected")
        edit.setEnabled(self.service.can_manage)
        edit.clicked.connect(self.edit_selected_driver)
        actions = QHBoxLayout()
        actions.addWidget(add)
        actions.addWidget(edit)
        actions.addStretch()
        layout = QVBoxLayout(page)
        layout.addLayout(actions)
        layout.addWidget(self.drivers_table, 1)
        return page

    def _build_fleet_tab(self) -> QWidget:
        page = QWidget()
        self.vehicles_table = QTableWidget(0, 10)
        self.vehicles_table.setHorizontalHeaderLabels(
            [
                "Number",
                "Vehicle",
                "Status",
                "Cargo L",
                "Cargo W",
                "Cargo H",
                "Payload",
                "Cost/Mile",
                "Registration",
                "Insurance",
            ]
        )
        self.vehicles_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.vehicles_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.vehicles_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.vehicles_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        add = QPushButton("New Vehicle")
        add.setObjectName("primary")
        add.setEnabled(self.service.can_manage)
        add.clicked.connect(self.new_vehicle)
        edit = QPushButton("Edit Selected")
        edit.setEnabled(self.service.can_manage)
        edit.clicked.connect(self.edit_selected_vehicle)
        actions = QHBoxLayout()
        actions.addWidget(add)
        actions.addWidget(edit)
        actions.addStretch()
        layout = QVBoxLayout(page)
        layout.addLayout(actions)
        layout.addWidget(self.vehicles_table, 1)
        return page

    def on_activated(self) -> None:
        self.refresh()

    def set_view(self, key: str) -> None:
        mapping = {"dispatch": 0, "calendar": 1, "fleet": 4}
        self.tabs.setCurrentIndex(mapping.get(key, 0))

    def refresh(self) -> None:
        try:
            self.customer_choices, self.driver_choices, self.vehicle_choices = (
                self.service.choices()
            )
            selected_driver = str(self.driver_filter.currentData() or "")
            self._refresh_driver_filter(selected_driver)
            driver_id = str(self.driver_filter.currentData() or "") or None
            self.all_jobs = self.service.jobs(
                statuses=None,
                query=self.search.text(),
                driver_id=driver_id,
            )
            self.current_jobs = [
                view for view in self.all_jobs if view.record.status in BOARD_STATUSES
            ]
        except ValidationError as exc:
            QMessageBox.warning(self, "Dispatch Center", str(exc))
            return
        self._render_board()
        self._render_table()
        self._render_metrics()
        self._render_drivers()
        self._render_vehicles()
        self._refresh_calendar()
        if self.current_job_id:
            matching = next(
                (item for item in self.all_jobs if item.record.id == self.current_job_id), None
            )
            if matching:
                self.detail.show_job(matching)

    def _refresh_driver_filter(self, selected: str) -> None:
        self.driver_filter.blockSignals(True)
        self.driver_filter.clear()
        self.driver_filter.addItem("All drivers", "")
        for choice in self.driver_choices:
            self.driver_filter.addItem(choice.label, choice.id)
        self.driver_filter.setCurrentIndex(max(0, self.driver_filter.findData(selected)))
        self.driver_filter.blockSignals(False)

    def _render_board(self) -> None:
        grouped: dict[str, list[DispatchJobView]] = defaultdict(list)
        for view in self.current_jobs:
            grouped[view.record.status].append(view)
        for status, lane in self.lanes.items():
            lane.set_jobs(grouped.get(status, []))

    def _render_table(self) -> None:
        self.jobs_table.setRowCount(len(self.all_jobs))
        for row, view in enumerate(self.all_jobs):
            record = view.record
            assignment = _display_assignment(record)
            values = (
                record.job_number,
                record.customer_name,
                _label(record.status),
                record.priority.title(),
                _local_text(record.requested_window_start),
                assignment.driver_name if assignment else "Unassigned",
                assignment.vehicle_name if assignment else "Unassigned",
                record.pickup_address,
                record.delivery_address,
                str(view.alert_count),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, record.id)
                self.jobs_table.setItem(row, column, item)

    def _render_metrics(self) -> None:
        metrics = self.service.metrics(self.current_jobs)
        self.metric_active.value.setText(str(metrics.active_jobs))
        self.metric_unassigned.value.setText(str(metrics.unassigned_jobs))
        self.metric_waiting.value.setText(str(metrics.waiting_jobs))
        self.metric_overdue.value.setText(str(metrics.overdue_jobs))
        self.metric_today.value.setText(str(metrics.scheduled_today))
        self.metric_completed.value.setText(str(metrics.completed_today))

    def _render_drivers(self) -> None:
        records = self.service.list_drivers()
        self.drivers_table.setRowCount(len(records))
        for row, record in enumerate(records):
            values = (
                record.driver_number,
                record.display_name,
                record.status.replace("_", " ").title(),
                record.phone,
                record.email,
                record.license_state,
                record.license_expiration.isoformat() if record.license_expiration else "",
                record.notes,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, record.id)
                item.setData(Qt.ItemDataRole.UserRole + 1, record)
                self.drivers_table.setItem(row, column, item)

    def _render_vehicles(self) -> None:
        records = self.service.list_vehicles()
        self.vehicles_table.setRowCount(len(records))
        for row, record in enumerate(records):
            values = (
                record.vehicle_number,
                f"{record.year} {record.make} {record.model} {record.trim}".strip(),
                record.status.replace("_", " ").title(),
                str(record.cargo_length_inches or ""),
                str(record.cargo_width_inches or ""),
                str(record.cargo_height_inches or ""),
                str(record.payload_pounds or ""),
                _money(record.cost_per_mile_cents or 0),
                (
                    record.registration_expires_on.isoformat()
                    if record.registration_expires_on
                    else ""
                ),
                record.insurance_expires_on.isoformat() if record.insurance_expires_on else "",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, record.id)
                item.setData(Qt.ItemDataRole.UserRole + 1, record)
                self.vehicles_table.setItem(row, column, item)

    def _refresh_calendar(self) -> None:
        start, end = self.calendar.visible_range()
        driver_id = str(self.driver_filter.currentData() or "") or None
        try:
            values = self.service.jobs(
                statuses=None,
                query=self.search.text(),
                starts_before=end,
                ends_after=start,
                driver_id=driver_id,
            )
            # Keep the operational queue useful even when an unassigned or accepted job
            # falls outside the currently visible calendar range.
            queue_candidates = self.service.jobs(
                statuses=None,
                query=self.search.text(),
                driver_id=driver_id,
            )
            existing_ids = {view.record.id for view in values}
            for view in queue_candidates:
                record = view.record
                should_queue = record.status not in {
                    JobStatus.COMPLETED.value,
                    JobStatus.CANCELLED.value,
                } and (
                    record.assignment is None
                    or record.requested_window_start is None
                    or record.status == JobStatus.ACCEPTED.value
                )
                if should_queue and record.id not in existing_ids:
                    values.append(view)
                    existing_ids.add(record.id)
        except ValidationError:
            values = []
        self.calendar.set_jobs(values)

    def _tab_changed(self, index: int) -> None:
        if index == 1:
            self._refresh_calendar()

    def select_job(self, job_id: str) -> None:
        self.current_job_id = job_id
        try:
            view = self.service.load_job(job_id)
        except ValidationError as exc:
            QMessageBox.warning(self, "Job", str(exc))
            return
        self.detail.show_job(view)

    def _table_selected(self) -> None:
        items = self.jobs_table.selectedItems()
        if items:
            self.select_job(str(items[0].data(Qt.ItemDataRole.UserRole)))

    def new_job(self) -> None:
        dialog = JobEditorDialog(self.service, self.customer_choices, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            job_id = self.service.save_job(dialog.request())
        except ValidationError as exc:
            QMessageBox.warning(self, "Job", str(exc))
            return
        self.current_job_id = job_id
        self.refresh()

    def edit_job(self, job_id: str) -> None:
        try:
            view = self.service.load_job(job_id)
        except ValidationError as exc:
            QMessageBox.warning(self, "Job", str(exc))
            return
        dialog = JobEditorDialog(self.service, self.customer_choices, view.record, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.service.save_job(dialog.request(), job_id)
        except ValidationError as exc:
            QMessageBox.warning(self, "Job", str(exc))
            return
        self.current_job_id = job_id
        self.refresh()

    def assign_job(self, job_id: str) -> None:
        try:
            view = self.service.load_job(job_id)
        except ValidationError as exc:
            QMessageBox.warning(self, "Assignment", str(exc))
            return
        if not self.driver_choices:
            QMessageBox.information(
                self,
                "Assignment",
                "Create a driver from the Drivers tab before assigning this job.",
            )
            self.tabs.setCurrentIndex(3)
            return
        if not self.vehicle_choices:
            QMessageBox.information(
                self, "Assignment", "Create a vehicle from the Fleet tab before assigning this job."
            )
            self.tabs.setCurrentIndex(4)
            return
        dialog = AssignmentDialog(
            self.service,
            view.record,
            self.driver_choices,
            self.vehicle_choices,
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        request = dialog.request()
        try:
            conflicts = self.service.assignment_conflicts(job_id, request)
            allow_conflicts = False
            if conflicts:
                messages = "\n\n".join(f"• {conflict.message}" for conflict in conflicts)
                answer = QMessageBox.warning(
                    self,
                    "Assignment conflicts",
                    f"{messages}\n\nAssign anyway and record this override?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
                allow_conflicts = True
            self.service.assign(job_id, request, allow_conflicts=allow_conflicts)
        except ValidationError as exc:
            QMessageBox.warning(self, "Assignment", str(exc))
            return
        self.current_job_id = job_id
        self.refresh()

    def choose_status(self, job_id: str) -> None:
        try:
            view = self.service.load_job(job_id)
        except ValidationError as exc:
            QMessageBox.warning(self, "Status", str(exc))
            return
        allowed = [
            status
            for status in ALLOWED_TRANSITIONS.get(view.record.status, frozenset())
            if status in STATUS_LABELS
        ]
        if not allowed:
            QMessageBox.information(
                self, "Status", "This job has no available forward status transitions."
            )
            return
        picker = QDialog(self)
        picker.setWindowTitle("Choose next status")
        buttons_layout = QVBoxLayout()
        for status in sorted(allowed, key=lambda value: list(STATUS_LABELS).index(value)):
            button = QPushButton(_label(status))
            button.clicked.connect(
                lambda _checked=False, value=status: (
                    picker.setProperty("status", value),
                    picker.accept(),
                )
            )
            buttons_layout.addWidget(button)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(picker.reject)
        buttons_layout.addWidget(cancel)
        picker.setLayout(buttons_layout)
        if picker.exec() != QDialog.DialogCode.Accepted:
            return
        target = str(picker.property("status"))
        self._change_status(job_id, view.record.status, target)

    def _move_job(self, job_id: str, target_status: str) -> None:
        try:
            view = self.service.load_job(job_id)
        except ValidationError as exc:
            QMessageBox.warning(self, "Dispatch", str(exc))
            return
        if view.record.status == target_status:
            return
        if target_status not in ALLOWED_TRANSITIONS.get(view.record.status, frozenset()):
            QMessageBox.warning(
                self,
                "Invalid transition",
                f"{_label(view.record.status)} cannot move directly to {_label(target_status)}.",
            )
            return
        self._change_status(job_id, view.record.status, target_status)

    def _change_status(self, job_id: str, current: str, target: str) -> None:
        dialog = StatusChangeDialog(current, target, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.service.change_status(job_id, dialog.request())
        except ValidationError as exc:
            QMessageBox.warning(self, "Status", str(exc))
            return
        self.current_job_id = job_id
        self.refresh()

    def _reschedule_from_calendar(self, job_id: str, target_date: date) -> None:
        try:
            conflicts = self.service.reschedule_conflicts(job_id, target_date)
        except ValidationError as exc:
            QMessageBox.warning(self, "Calendar", str(exc))
            return
        explanation = (
            f"Move this job to {target_date.strftime('%A, %B %d, %Y')}?\n\n"
            "Its time of day and duration will be preserved. The active assignment window moves with it."
        )
        if conflicts:
            messages = "\n\n".join(f"• {conflict.message}" for conflict in conflicts)
            explanation += (
                f"\n\nConflicts found:\n\n{messages}"
                "\n\nMove the job anyway and record this scheduling override?"
            )
            icon = QMessageBox.Icon.Warning
        else:
            icon = QMessageBox.Icon.Question
        box = QMessageBox(self)
        box.setIcon(icon)
        box.setWindowTitle("Reschedule job")
        box.setText(explanation)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        try:
            self.service.reschedule_job(
                job_id,
                target_date,
                allow_conflicts=bool(conflicts),
            )
        except ValidationError as exc:
            QMessageBox.warning(self, "Calendar", str(exc))
            return
        self.current_job_id = job_id
        self.refresh()

    def new_driver(self) -> None:
        dialog = DriverDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.service.save_driver(dialog.request())
        except ValidationError as exc:
            QMessageBox.warning(self, "Driver", str(exc))
            return
        self.refresh()

    def edit_selected_driver(self) -> None:
        items = self.drivers_table.selectedItems()
        if not items:
            QMessageBox.information(self, "Driver", "Select a driver first.")
            return
        record = items[0].data(Qt.ItemDataRole.UserRole + 1)
        if not isinstance(record, DriverRecord):
            return
        dialog = DriverDialog(record, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.service.save_driver(dialog.request(), record.id)
        except ValidationError as exc:
            QMessageBox.warning(self, "Driver", str(exc))
            return
        self.refresh()

    def new_vehicle(self) -> None:
        dialog = VehicleDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.service.save_vehicle(dialog.request())
        except ValidationError as exc:
            QMessageBox.warning(self, "Vehicle", str(exc))
            return
        self.refresh()

    def edit_selected_vehicle(self) -> None:
        items = self.vehicles_table.selectedItems()
        if not items:
            QMessageBox.information(self, "Vehicle", "Select a vehicle first.")
            return
        record = items[0].data(Qt.ItemDataRole.UserRole + 1)
        if not isinstance(record, VehicleRecord):
            return
        dialog = VehicleDialog(record, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.service.save_vehicle(dialog.request(), record.id)
        except ValidationError as exc:
            QMessageBox.warning(self, "Vehicle", str(exc))
            return
        self.refresh()

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        self._arrange_responsive()
        narrow = self.width() < 1120
        self.detail.setVisible(True)
        if narrow:
            if self.splitter.orientation() != Qt.Orientation.Vertical:
                self.splitter.setOrientation(Qt.Orientation.Vertical)
            self.detail.setMaximumWidth(16_777_215)
            self.detail.setMaximumHeight(310)
            self.splitter.setSizes([max(420, self.height() - 320), 300])
        else:
            if self.splitter.orientation() != Qt.Orientation.Horizontal:
                self.splitter.setOrientation(Qt.Orientation.Horizontal)
            self.detail.setMaximumHeight(16_777_215)
            self.detail.setMaximumWidth(390)
            self.splitter.setSizes([max(700, self.width() - 350), 340])
