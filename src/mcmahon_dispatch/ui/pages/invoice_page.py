from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import QDate, QDateTime, QSignalBlocker, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
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
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from mcmahon_dispatch.core.enums import InvoiceStatus
from mcmahon_dispatch.core.exceptions import ValidationError
from mcmahon_dispatch.core.formatting import format_currency, format_date
from mcmahon_dispatch.repositories.invoice_repository import (
    BillingReport,
    CustomerChoice,
    InvoiceSummary,
    PaymentSummary,
)
from mcmahon_dispatch.ui.common import DebouncedCall, PageHeader, configure_data_table
from mcmahon_dispatch.ui.common.tables import populate_table, selected_record_id
from mcmahon_dispatch.services.invoice_service import (
    InvoiceLineRequest,
    InvoiceSaveRequest,
    InvoiceService,
    PaymentAllocationRequest,
    PaymentSaveRequest,
)


STATUS_LABELS = {
    "draft": "Draft",
    "issued": "Issued",
    "sent": "Sent",
    "viewed": "Viewed",
    "partially_paid": "Partially Paid",
    "paid": "Paid",
    "overdue": "Overdue",
    "void": "Void",
    "written_off": "Written Off",
}
PAYMENT_METHODS = ("ACH", "Check", "Card", "Cash", "External Link", "Other")


def money(cents: int | None) -> str:
    return format_currency(cents, empty="-")


def date_text(value) -> str:
    return format_date(value, empty="-")


def set_combo_data(combo: QComboBox, value: str | None) -> None:
    index = combo.findData(value)
    combo.setCurrentIndex(max(0, index))


class BillingMetric(QFrame):
    def __init__(self, title: str) -> None:
        super().__init__()
        self.setObjectName("metricCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 12, 15, 12)
        label = QLabel(title)
        label.setObjectName("muted")
        self.value = QLabel("-")
        self.value.setObjectName("metricValue")
        layout.addWidget(label)
        layout.addWidget(self.value)


class InvoiceDialog(QDialog):
    def __init__(
        self, parent: QWidget, service: InvoiceService, invoice_id: str | None = None
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.invoice_id = invoice_id
        self.customers = service.customer_choices()
        self.setWindowTitle("Edit Invoice" if invoice_id else "New Invoice")
        self.resize(940, 760)
        root = QVBoxLayout(self)

        form_box = QGroupBox("Invoice details")
        form = QGridLayout(form_box)
        self.customer = QComboBox()
        self.customer.setEditable(True)
        self.customer.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        for item in self.customers:
            self.customer.addItem(f"{item.company_name} ({item.number})", item.id)
        self.issue_date = QDateEdit()
        self.issue_date.setCalendarPopup(True)
        self.issue_date.setDate(QDate.currentDate())
        self.due_date = QDateEdit()
        self.due_date.setCalendarPopup(True)
        self.due_date.setDate(QDate.currentDate().addDays(15))
        self.terms = QSpinBox()
        self.terms.setRange(0, 365)
        self.terms.setValue(15)
        self.terms.setSuffix(" days")
        self.po = QLineEdit()
        self.reference = QLineEdit()
        form.addWidget(QLabel("Customer *"), 0, 0)
        form.addWidget(self.customer, 0, 1, 1, 3)
        form.addWidget(QLabel("Issue date"), 1, 0)
        form.addWidget(self.issue_date, 1, 1)
        form.addWidget(QLabel("Due date"), 1, 2)
        form.addWidget(self.due_date, 1, 3)
        form.addWidget(QLabel("Terms"), 2, 0)
        form.addWidget(self.terms, 2, 1)
        form.addWidget(QLabel("PO number"), 2, 2)
        form.addWidget(self.po, 2, 3)
        form.addWidget(QLabel("Customer reference"), 3, 0)
        form.addWidget(self.reference, 3, 1, 1, 3)
        root.addWidget(form_box)

        line_bar = QHBoxLayout()
        line_title = QLabel("Charges")
        line_title.setObjectName("sectionTitle")
        add_line = QPushButton("Add Charge")
        add_line.clicked.connect(self._add_line)
        remove_line = QPushButton("Remove Selected")
        remove_line.clicked.connect(self._remove_line)
        line_bar.addWidget(line_title)
        line_bar.addStretch()
        line_bar.addWidget(add_line)
        line_bar.addWidget(remove_line)
        root.addLayout(line_bar)

        self.lines = QTableWidget(0, 5)
        self.lines.setHorizontalHeaderLabels(
            ["Description", "Quantity", "Rate", "Taxable", "Line Total"]
        )
        self.lines.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.lines.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.lines.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.lines.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self.lines.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        self.lines.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.ResizeToContents
        )
        root.addWidget(self.lines, 1)

        totals_row = QHBoxLayout()
        self.customer_notes = QTextEdit()
        self.customer_notes.setPlaceholderText("Notes visible to the customer")
        self.internal_notes = QTextEdit()
        self.internal_notes.setPlaceholderText("Internal billing notes - never shown on PDFs")
        notes_tabs = QTabWidget()
        notes_tabs.addTab(self.customer_notes, "Customer Notes")
        notes_tabs.addTab(self.internal_notes, "Internal Notes")
        totals_row.addWidget(notes_tabs, 1)
        totals_form = QFormLayout()
        self.discount = QDoubleSpinBox()
        self.discount.setRange(0, 9999999)
        self.discount.setDecimals(2)
        self.discount.setPrefix("$")
        self.tax = QDoubleSpinBox()
        self.tax.setRange(0, 9999999)
        self.tax.setDecimals(2)
        self.tax.setPrefix("$")
        self.subtotal_label = QLabel("$0.00")
        self.total_label = QLabel("$0.00")
        self.total_label.setObjectName("metricValue")
        totals_form.addRow("Subtotal", self.subtotal_label)
        totals_form.addRow("Discount", self.discount)
        totals_form.addRow("Tax", self.tax)
        totals_form.addRow("Total", self.total_label)
        totals_holder = QWidget()
        totals_holder.setLayout(totals_form)
        totals_holder.setMinimumWidth(260)
        totals_row.addWidget(totals_holder)
        root.addLayout(totals_row)

        self.issue_now = QCheckBox("Issue this invoice now")
        self.issue_now.setChecked(True)
        root.addWidget(self.issue_now)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.customer.currentIndexChanged.connect(self._customer_changed)
        self.terms.valueChanged.connect(self._terms_changed)
        self.issue_date.dateChanged.connect(self._terms_changed)
        self.discount.valueChanged.connect(self._recalculate)
        self.tax.valueChanged.connect(self._recalculate)
        if invoice_id:
            self._load(invoice_id)
        else:
            self._add_line("Delivery service", Decimal("1"), 7500)
            self._customer_changed()

    def _add_line(
        self,
        description: str = "",
        quantity: Decimal = Decimal("1"),
        rate_cents: int = 0,
        taxable: bool = False,
    ) -> None:
        row = self.lines.rowCount()
        self.lines.insertRow(row)
        description_item = QTableWidgetItem(description)
        self.lines.setItem(row, 0, description_item)
        qty = QDoubleSpinBox()
        qty.setRange(0.0001, 999999)
        qty.setDecimals(4)
        qty.setValue(float(quantity))
        qty.valueChanged.connect(self._recalculate)
        self.lines.setCellWidget(row, 1, qty)
        rate = QDoubleSpinBox()
        rate.setRange(0, 9999999)
        rate.setDecimals(2)
        rate.setPrefix("$")
        rate.setValue(rate_cents / 100)
        rate.valueChanged.connect(self._recalculate)
        self.lines.setCellWidget(row, 2, rate)
        check = QCheckBox()
        check.setChecked(taxable)
        check.stateChanged.connect(self._recalculate)
        holder = QWidget()
        hl = QHBoxLayout(holder)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hl.addWidget(check)
        self.lines.setCellWidget(row, 3, holder)
        total = QTableWidgetItem("$0.00")
        total.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        total.setFlags(total.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.lines.setItem(row, 4, total)
        self._recalculate()

    def _remove_line(self) -> None:
        rows = sorted({index.row() for index in self.lines.selectedIndexes()}, reverse=True)
        for row in rows:
            self.lines.removeRow(row)
        self._recalculate()

    def _line_requests(self) -> tuple[InvoiceLineRequest, ...]:
        requests = []
        for row in range(self.lines.rowCount()):
            description = self.lines.item(row, 0).text() if self.lines.item(row, 0) else ""
            qty = self.lines.cellWidget(row, 1)
            rate = self.lines.cellWidget(row, 2)
            holder = self.lines.cellWidget(row, 3)
            check = holder.findChild(QCheckBox) if holder else None
            requests.append(
                InvoiceLineRequest(
                    description=description,
                    quantity=Decimal(str(qty.value() if isinstance(qty, QDoubleSpinBox) else 0)),
                    unit_rate_cents=round(
                        (rate.value() if isinstance(rate, QDoubleSpinBox) else 0) * 100
                    ),
                    taxable=bool(check and check.isChecked()),
                )
            )
        return tuple(requests)

    def _recalculate(self) -> None:
        subtotal = 0
        for row, line in enumerate(self._line_requests()):
            subtotal += line.line_total_cents
            item = self.lines.item(row, 4)
            if item:
                item.setText(money(line.line_total_cents))
        total = max(
            0, subtotal - round(self.discount.value() * 100) + round(self.tax.value() * 100)
        )
        self.subtotal_label.setText(money(subtotal))
        self.total_label.setText(money(total))

    def _customer_changed(self) -> None:
        customer_id = self.customer.currentData()
        selected = next((item for item in self.customers if item.id == customer_id), None)
        if selected:
            self.terms.setValue(selected.terms_days)
            self._terms_changed()

    def _terms_changed(self) -> None:
        self.due_date.setDate(self.issue_date.date().addDays(self.terms.value()))

    def _load(self, invoice_id: str) -> None:
        invoice = self.service.invoice(invoice_id)
        set_combo_data(self.customer, invoice.customer_id)
        if invoice.issued_at:
            self.issue_date.setDate(QDate(invoice.issued_at.date()))
        if invoice.due_at:
            self.due_date.setDate(QDate(invoice.due_at.date()))
        self.terms.setValue(invoice.terms_days)
        self.po.setText(invoice.purchase_order_number or "")
        self.reference.setText(invoice.customer_reference or "")
        self.discount.setValue(invoice.discount_cents / 100)
        self.tax.setValue(invoice.tax_cents / 100)
        self.customer_notes.setPlainText(invoice.customer_notes)
        self.internal_notes.setPlainText(invoice.internal_notes)
        self.issue_now.setChecked(invoice.status != InvoiceStatus.DRAFT.value)
        for line in invoice.lines:
            self._add_line(line.description, line.quantity, line.unit_rate_cents, line.taxable)
        self._recalculate()

    def request(self) -> InvoiceSaveRequest:
        return InvoiceSaveRequest(
            customer_id=str(self.customer.currentData() or ""),
            issued_on=self.issue_date.date().toPython(),
            due_on=self.due_date.date().toPython(),
            terms_days=self.terms.value(),
            purchase_order_number=self.po.text(),
            customer_reference=self.reference.text(),
            discount_cents=round(self.discount.value() * 100),
            tax_cents=round(self.tax.value() * 100),
            customer_notes=self.customer_notes.toPlainText(),
            internal_notes=self.internal_notes.toPlainText(),
            lines=self._line_requests(),
            issue_now=self.issue_now.isChecked(),
        )

    def _accept(self) -> None:
        try:
            self.invoice_id = self.service.save_invoice(self.request(), self.invoice_id)
        except ValidationError as exc:
            QMessageBox.warning(self, "Invoice", str(exc))
            return
        self.accept()


class PaymentDialog(QDialog):
    def __init__(
        self, parent: QWidget, service: InvoiceService, preferred_customer_id: str | None = None
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.customers = service.customer_choices()
        self.setWindowTitle("Record Payment")
        self.resize(760, 650)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.customer = QComboBox()
        [self.customer.addItem(f"{c.company_name} ({c.number})", c.id) for c in self.customers]
        if preferred_customer_id:
            set_combo_data(self.customer, preferred_customer_id)
        self.method = QComboBox()
        [self.method.addItem(label, label.lower().replace(" ", "_")) for label in PAYMENT_METHODS]
        self.received = QDateTimeEdit()
        self.received.setCalendarPopup(True)
        self.received.setDateTime(QDateTime.currentDateTime())
        self.amount = QDoubleSpinBox()
        self.amount.setRange(0.01, 99999999)
        self.amount.setDecimals(2)
        self.amount.setPrefix("$")
        self.fee = QDoubleSpinBox()
        self.fee.setRange(0, 999999)
        self.fee.setDecimals(2)
        self.fee.setPrefix("$")
        self.reference = QLineEdit()
        self.notes = QTextEdit()
        form.addRow("Customer *", self.customer)
        form.addRow("Payment method *", self.method)
        form.addRow("Received", self.received)
        form.addRow("Amount *", self.amount)
        form.addRow("Processing fee", self.fee)
        form.addRow("Reference", self.reference)
        form.addRow("Notes", self.notes)
        root.addLayout(form)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Apply payment to invoices"))
        bar.addStretch()
        auto = QPushButton("Apply Oldest First")
        auto.clicked.connect(self._auto_allocate)
        bar.addWidget(auto)
        root.addLayout(bar)
        self.allocations = QTableWidget(0, 4)
        self.allocations.setHorizontalHeaderLabels(["Invoice", "Due", "Open Balance", "Apply"])
        self.allocations.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.allocations, 1)
        self.summary = QLabel("Allocated: $0.00 • Remaining: $0.00")
        self.summary.setObjectName("sectionTitle")
        root.addWidget(self.summary)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.customer.currentIndexChanged.connect(self._load_invoices)
        self.amount.valueChanged.connect(self._allocation_changed)
        self._load_invoices()

    def _load_invoices(self) -> None:
        self.allocations.setRowCount(0)
        customer_id = str(self.customer.currentData() or "")
        for invoice in self.service.customer_open_invoices(customer_id) if customer_id else []:
            row = self.allocations.rowCount()
            self.allocations.insertRow(row)
            item = QTableWidgetItem(invoice.invoice_number)
            item.setData(Qt.ItemDataRole.UserRole, invoice.id)
            self.allocations.setItem(row, 0, item)
            self.allocations.setItem(row, 1, QTableWidgetItem(date_text(invoice.due_at)))
            balance = QTableWidgetItem(money(invoice.balance_cents))
            balance.setData(Qt.ItemDataRole.UserRole, invoice.balance_cents)
            self.allocations.setItem(row, 2, balance)
            amount = QDoubleSpinBox()
            amount.setRange(0, invoice.balance_cents / 100)
            amount.setDecimals(2)
            amount.setPrefix("$")
            amount.valueChanged.connect(self._allocation_changed)
            self.allocations.setCellWidget(row, 3, amount)
        self._allocation_changed()

    def _auto_allocate(self) -> None:
        remaining = round(self.amount.value() * 100)
        for row in range(self.allocations.rowCount()):
            balance = int(self.allocations.item(row, 2).data(Qt.ItemDataRole.UserRole) or 0)
            apply = min(balance, remaining)
            widget = self.allocations.cellWidget(row, 3)
            if isinstance(widget, QDoubleSpinBox):
                widget.setValue(apply / 100)
            remaining -= apply
        self._allocation_changed()

    def _allocation_changed(self) -> None:
        allocated = 0
        for row in range(self.allocations.rowCount()):
            widget = self.allocations.cellWidget(row, 3)
            if isinstance(widget, QDoubleSpinBox):
                allocated += round(widget.value() * 100)
        total = round(self.amount.value() * 100)
        self.summary.setText(f"Allocated: {money(allocated)} • Remaining: {money(total-allocated)}")

    def request(self) -> PaymentSaveRequest:
        allocations = []
        for row in range(self.allocations.rowCount()):
            widget = self.allocations.cellWidget(row, 3)
            amount = round(widget.value() * 100) if isinstance(widget, QDoubleSpinBox) else 0
            if amount:
                allocations.append(
                    PaymentAllocationRequest(
                        str(self.allocations.item(row, 0).data(Qt.ItemDataRole.UserRole)), amount
                    )
                )
        dt = self.received.dateTime().toPython()
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return PaymentSaveRequest(
            customer_id=str(self.customer.currentData() or ""),
            payment_method=str(self.method.currentData()),
            received_at=dt,
            gross_amount_cents=round(self.amount.value() * 100),
            processing_fee_cents=round(self.fee.value() * 100),
            external_reference=self.reference.text(),
            notes=self.notes.toPlainText(),
            allocations=tuple(allocations),
        )

    def _accept(self) -> None:
        try:
            self.service.record_payment(self.request())
        except ValidationError as exc:
            QMessageBox.warning(self, "Payment", str(exc))
            return
        self.accept()


class InvoicePage(QWidget):
    def __init__(self, service: InvoiceService) -> None:
        super().__init__()
        self.service = service
        self._invoice_rows: list[InvoiceSummary] = []
        self._payment_rows: list[PaymentSummary] = []
        self._customers: list[CustomerChoice] = []
        self.setObjectName("invoicePage")
        self._search_debounce = DebouncedCall(self.refresh, parent=self)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)
        self.new_invoice_button = QPushButton("New Invoice")
        self.new_invoice_button.setObjectName("primary")
        self.new_invoice_button.clicked.connect(self.new_invoice)
        self.record_payment_button = QPushButton("Record Payment")
        self.record_payment_button.clicked.connect(self.record_payment)
        actions = QWidget()
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(8)
        actions_layout.addWidget(self.new_invoice_button)
        actions_layout.addWidget(self.record_payment_button)
        root.addWidget(
            PageHeader(
                "Invoice Management",
                "Create invoices, record payments, monitor balances, and send customer statements.",
                actions,
            )
        )
        self.metrics_widget = QWidget()
        self.metrics_layout = QGridLayout(self.metrics_widget)
        self.metrics_layout.setContentsMargins(0, 0, 0, 0)
        self.metrics_layout.setSpacing(12)
        self.invoiced_metric = BillingMetric("Invoiced")
        self.collected_metric = BillingMetric("Collected")
        self.outstanding_metric = BillingMetric("Outstanding")
        self.overdue_metric = BillingMetric("Overdue")
        self.metric_cards = (
            self.invoiced_metric,
            self.collected_metric,
            self.outstanding_metric,
            self.overdue_metric,
        )
        self._layout_metric_cards(columns=4)
        root.addWidget(self.metrics_widget)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._invoice_tab(), "Invoices")
        self.tabs.addTab(self._payment_tab(), "Payments")
        self.tabs.addTab(self._statement_tab(), "Customer Statements")
        self.tabs.addTab(self._report_tab(), "Reports")
        root.addWidget(self.tabs, 1)
        QShortcut(QKeySequence("Ctrl+N"), self).activated.connect(self.new_invoice)
        QShortcut(QKeySequence("Ctrl+Shift+P"), self).activated.connect(self.record_payment)
        self.on_activated()

    def _invoice_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        filters = QHBoxLayout()
        self.invoice_search = QLineEdit()
        self.invoice_search.setPlaceholderText("Search invoice, customer, PO, or reference")
        self.invoice_status = QComboBox()
        self.invoice_status.addItem("All statuses", "")
        for code, label in STATUS_LABELS.items():
            self.invoice_status.addItem(label, code)
        self.invoice_customer = QComboBox()
        self.invoice_customer.addItem("All customers", "")
        self.outstanding_only = QCheckBox("Outstanding only")
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        filters.addWidget(self.invoice_search, 2)
        filters.addWidget(self.invoice_status)
        filters.addWidget(self.invoice_customer)
        filters.addWidget(self.outstanding_only)
        filters.addWidget(refresh)
        layout.addLayout(filters)
        self.invoice_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.invoice_table = QTableWidget()
        configure_data_table(
            self.invoice_table,
            ("Invoice", "Customer", "Status", "Issued", "Due", "Total", "Paid", "Balance"),
            stretch_column=1,
        )
        self.invoice_table.doubleClicked.connect(self.edit_invoice)
        self.invoice_table.itemSelectionChanged.connect(self._show_invoice_detail)
        self.invoice_splitter.addWidget(self.invoice_table)
        self.invoice_detail = self._invoice_detail_panel()
        self.invoice_splitter.addWidget(self.invoice_detail)
        self.invoice_splitter.setSizes([920, 340])
        layout.addWidget(self.invoice_splitter, 1)
        self.invoice_search.textChanged.connect(self._search_debounce.schedule)
        self.invoice_status.currentIndexChanged.connect(self.refresh)
        self.invoice_customer.currentIndexChanged.connect(self.refresh)
        self.outstanding_only.stateChanged.connect(self.refresh)
        return page

    def _invoice_detail_panel(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("dispatchDetail")
        frame.setMinimumWidth(300)
        layout = QVBoxLayout(frame)
        self.detail_number = QLabel("Select an invoice")
        self.detail_number.setObjectName("pageTitle")
        self.detail_customer = QLabel("")
        self.detail_customer.setObjectName("muted")
        self.detail_status = QLabel("")
        self.detail_balance = QLabel("")
        self.detail_balance.setObjectName("metricValue")
        self.detail_dates = QLabel("")
        self.detail_dates.setWordWrap(True)
        layout.addWidget(self.detail_number)
        layout.addWidget(self.detail_customer)
        layout.addWidget(self.detail_status)
        layout.addWidget(self.detail_balance)
        layout.addWidget(self.detail_dates)
        self.edit_button = QPushButton("Edit Invoice")
        self.edit_button.clicked.connect(self.edit_invoice)
        self.pdf_button = QPushButton("Generate PDF")
        self.pdf_button.clicked.connect(self.generate_invoice_pdf)
        self.email_button = QPushButton("Prepare Email")
        self.email_button.clicked.connect(self.prepare_email)
        self.late_button = QPushButton("Add Late Fee")
        self.late_button.clicked.connect(self.add_late_fee)
        self.void_button = QPushButton("Void Invoice")
        self.void_button.clicked.connect(self.void_invoice)
        for button in (
            self.edit_button,
            self.pdf_button,
            self.email_button,
            self.late_button,
            self.void_button,
        ):
            layout.addWidget(button)
        layout.addStretch()
        return frame

    def _payment_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        filters = QHBoxLayout()
        self.payment_search = QLineEdit()
        self.payment_search.setPlaceholderText("Search payment number, customer, or reference")
        self.payment_customer = QComboBox()
        self.payment_customer.addItem("All customers", "")
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        filters.addWidget(self.payment_search, 2)
        filters.addWidget(self.payment_customer)
        filters.addWidget(refresh)
        layout.addLayout(filters)
        self.payment_table = QTableWidget()
        configure_data_table(
            self.payment_table,
            ("Payment", "Customer", "Received", "Method", "Gross", "Fee", "Net", "Reference"),
            stretch_column=1,
        )
        layout.addWidget(self.payment_table, 1)
        self.payment_search.textChanged.connect(self._search_debounce.schedule)
        self.payment_customer.currentIndexChanged.connect(self.refresh)
        return page

    def _statement_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 18, 12, 12)
        intro = QLabel(
            "Generate a customer-ready statement showing opening balance, invoices, payments, and closing balance."
        )
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        layout.addWidget(intro)
        form = QFormLayout()
        self.statement_customer = QComboBox()
        self.statement_from = QDateEdit()
        self.statement_from.setCalendarPopup(True)
        self.statement_from.setDate(QDate.currentDate().addMonths(-1))
        self.statement_to = QDateEdit()
        self.statement_to.setCalendarPopup(True)
        self.statement_to.setDate(QDate.currentDate())
        form.addRow("Customer", self.statement_customer)
        form.addRow("From", self.statement_from)
        form.addRow("Through", self.statement_to)
        layout.addLayout(form)
        generate = QPushButton("Generate Statement PDF")
        generate.clicked.connect(self.generate_statement)
        layout.addWidget(generate)
        self.statement_result = QLabel("")
        self.statement_result.setWordWrap(True)
        layout.addWidget(self.statement_result)
        layout.addStretch()
        return page

    def _report_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        filters = QHBoxLayout()
        self.report_from = QDateEdit()
        self.report_from.setCalendarPopup(True)
        self.report_from.setDate(QDate(QDate.currentDate().year(), QDate.currentDate().month(), 1))
        self.report_to = QDateEdit()
        self.report_to.setCalendarPopup(True)
        self.report_to.setDate(QDate.currentDate())
        run = QPushButton("Run Report")
        run.clicked.connect(self._refresh_report)
        filters.addWidget(QLabel("From"))
        filters.addWidget(self.report_from)
        filters.addWidget(QLabel("Through"))
        filters.addWidget(self.report_to)
        filters.addWidget(run)
        filters.addStretch()
        layout.addLayout(filters)
        report_metrics = QHBoxLayout()
        self.report_invoiced = BillingMetric("Invoiced")
        self.report_collected = BillingMetric("Collected")
        self.report_average = BillingMetric("Average Invoice")
        self.report_rate = BillingMetric("Collection Rate")
        for metric in (
            self.report_invoiced,
            self.report_collected,
            self.report_average,
            self.report_rate,
        ):
            report_metrics.addWidget(metric)
        layout.addLayout(report_metrics)
        tables = QHBoxLayout()
        self.aging_table = QTableWidget()
        configure_data_table(
            self.aging_table,
            ("Age", "Invoices", "Balance"),
            stretch_column=0,
        )
        self.methods_table = QTableWidget()
        configure_data_table(
            self.methods_table,
            ("Payment Method", "Payments", "Amount"),
            stretch_column=0,
        )
        tables.addWidget(self.aging_table)
        tables.addWidget(self.methods_table)
        layout.addLayout(tables, 1)
        return page

    def on_activated(self) -> None:
        self._customers = self.service.customer_choices()
        self._populate_customers()
        self.refresh()

    def _populate_customers(self) -> None:
        combos = (self.invoice_customer, self.payment_customer, self.statement_customer)
        selected = [combo.currentData() for combo in combos]
        blockers = [QSignalBlocker(combo) for combo in combos]
        try:
            self.invoice_customer.clear()
            self.invoice_customer.addItem("All customers", "")
            self.payment_customer.clear()
            self.payment_customer.addItem("All customers", "")
            self.statement_customer.clear()
            for customer in self._customers:
                label = f"{customer.company_name} ({customer.number})"
                self.invoice_customer.addItem(label, customer.id)
                self.payment_customer.addItem(label, customer.id)
                self.statement_customer.addItem(label, customer.id)
            for combo, value in zip(combos, selected):
                if value:
                    set_combo_data(combo, str(value))
        finally:
            del blockers

    def refresh(self) -> None:
        selected_invoice_id = selected_record_id(self.invoice_table)
        status = str(self.invoice_status.currentData() or "")
        try:
            self._invoice_rows = self.service.invoices(
                query=self.invoice_search.text(),
                statuses=(status,) if status else None,
                customer_id=str(self.invoice_customer.currentData() or "") or None,
                outstanding_only=self.outstanding_only.isChecked(),
            )
            self._payment_rows = self.service.payments(
                query=self.payment_search.text(),
                customer_id=str(self.payment_customer.currentData() or "") or None,
            )
        except ValidationError as exc:
            QMessageBox.warning(self, "Invoice Management", str(exc))
            return

        self._fill_invoice_table()
        self._fill_payment_table()
        self._restore_invoice_selection(selected_invoice_id)
        self._refresh_report()

    def _fill_invoice_table(self) -> None:
        populate_table(
            self.invoice_table,
            (
                (
                    invoice.invoice_number,
                    invoice.customer_name,
                    STATUS_LABELS.get(invoice.status, invoice.status),
                    date_text(invoice.issued_at),
                    date_text(invoice.due_at),
                    money(invoice.total_cents),
                    money(invoice.paid_cents),
                    money(invoice.balance_cents),
                )
                for invoice in self._invoice_rows
            ),
            record_ids=[invoice.id for invoice in self._invoice_rows],
        )

    def _fill_payment_table(self) -> None:
        populate_table(
            self.payment_table,
            (
                (
                    payment.payment_number,
                    payment.customer_name,
                    date_text(payment.received_at),
                    payment.payment_method.replace("_", " ").title(),
                    money(payment.gross_amount_cents),
                    money(payment.processing_fee_cents),
                    money(payment.net_deposit_cents),
                    payment.external_reference or "-",
                )
                for payment in self._payment_rows
            ),
        )

    def _restore_invoice_selection(self, invoice_id: str | None) -> None:
        if not invoice_id:
            return
        for row_index in range(self.invoice_table.rowCount()):
            item = self.invoice_table.item(row_index, 0)
            if item and str(item.data(Qt.ItemDataRole.UserRole)) == invoice_id:
                self.invoice_table.selectRow(row_index)
                return

    def _selected_invoice(self) -> InvoiceSummary | None:
        invoice_id = selected_record_id(self.invoice_table)
        if invoice_id is None:
            return None
        return next((invoice for invoice in self._invoice_rows if invoice.id == invoice_id), None)

    def _show_invoice_detail(self) -> None:
        invoice = self._selected_invoice()
        if not invoice:
            return
        self.detail_number.setText(invoice.invoice_number)
        self.detail_customer.setText(invoice.customer_name)
        self.detail_status.setText(STATUS_LABELS.get(invoice.status, invoice.status))
        self.detail_balance.setText(f"Balance {money(invoice.balance_cents)}")
        self.detail_dates.setText(
            f"Issued: {date_text(invoice.issued_at)}\nDue: {date_text(invoice.due_at)}\nTotal: {money(invoice.total_cents)}\nPaid: {money(invoice.paid_cents)}"
        )
        self.late_button.setEnabled(
            invoice.status == InvoiceStatus.OVERDUE.value and invoice.balance_cents > 0
        )
        self.void_button.setEnabled(
            invoice.paid_cents == 0
            and invoice.status not in (InvoiceStatus.VOID.value, InvoiceStatus.PAID.value)
        )
        self.edit_button.setEnabled(
            invoice.status
            not in (
                InvoiceStatus.PAID.value,
                InvoiceStatus.VOID.value,
                InvoiceStatus.WRITTEN_OFF.value,
            )
        )

    def new_invoice(self) -> None:
        dialog = InvoiceDialog(self, self.service)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def edit_invoice(self) -> None:
        invoice = self._selected_invoice()
        if not invoice:
            return
        dialog = InvoiceDialog(self, self.service, invoice.id)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def record_payment(self) -> None:
        invoice = self._selected_invoice()
        customer_id = invoice.customer_id if invoice else None
        dialog = PaymentDialog(self, self.service, customer_id)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def generate_invoice_pdf(self) -> None:
        invoice = self._selected_invoice()
        if not invoice:
            return
        try:
            path = self.service.generate_invoice_pdf(invoice.id)
        except ValidationError as exc:
            QMessageBox.warning(self, "Invoice PDF", str(exc))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def prepare_email(self) -> None:
        invoice = self._selected_invoice()
        if not invoice:
            return
        try:
            path = self.service.generate_invoice_pdf(invoice.id)
        except ValidationError as exc:
            QMessageBox.warning(self, "Prepare Email", str(exc))
            return
        customer = next((c for c in self._customers if c.id == invoice.customer_id), None)
        email = customer.billing_email if customer else ""
        subject = f"Invoice {invoice.invoice_number} from McMahon Jobsite Delivery LLC"
        body = f"Hello,\n\nAttached is invoice {invoice.invoice_number} with a balance of {money(invoice.balance_cents)}.\n\nThank you,\nMcMahon Jobsite Delivery LLC"
        QApplication.clipboard().setText(
            f"To: {email or '[billing email needed]'}\nSubject: {subject}\nAttachment: {path}\n\n{body}"
        )
        QMessageBox.information(
            self,
            "Email Ready",
            f"The PDF is ready and the email details were copied to your clipboard.\n\n{path}",
        )

    def add_late_fee(self) -> None:
        invoice = self._selected_invoice()
        if not invoice:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Add Late Fee")
        layout = QFormLayout(dialog)
        amount = QDoubleSpinBox()
        amount.setRange(0.01, 999999)
        amount.setPrefix("$")
        reason = QLineEdit()
        reason.setPlaceholderText("Configured policy or approved reason")
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow("Late fee", amount)
        layout.addRow("Reason", reason)
        layout.addRow(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.service.apply_late_fee(invoice.id, round(amount.value() * 100), reason.text())
        except ValidationError as exc:
            QMessageBox.warning(self, "Late Fee", str(exc))
            return
        self.refresh()

    def void_invoice(self) -> None:
        invoice = self._selected_invoice()
        if not invoice:
            return
        from PySide6.QtWidgets import QInputDialog

        reason, ok = QInputDialog.getMultiLineText(
            self, "Void Invoice", f"Reason for voiding {invoice.invoice_number}:"
        )
        if not ok:
            return
        try:
            self.service.void_invoice(invoice.id, reason)
        except ValidationError as exc:
            QMessageBox.warning(self, "Void Invoice", str(exc))
            return
        self.refresh()

    def generate_statement(self) -> None:
        customer_id = str(self.statement_customer.currentData() or "")
        if not customer_id:
            QMessageBox.warning(self, "Customer Statement", "Select a customer.")
            return
        try:
            result = self.service.generate_statement_pdf(
                customer_id,
                self.statement_from.date().toPython(),
                self.statement_to.date().toPython(),
            )
        except ValidationError as exc:
            QMessageBox.warning(self, "Customer Statement", str(exc))
            return
        self.statement_result.setText(
            f"{result.customer_name}\nOpening: {money(result.opening_balance_cents)} • Invoices: {money(result.invoice_cents)} • Payments: {money(result.payment_cents)} • Closing: {money(result.closing_balance_cents)}\n{result.path}"
        )
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(result.path)))

    def _refresh_report(self) -> None:
        try:
            report = self.service.report(
                self.report_from.date().toPython(), self.report_to.date().toPython()
            )
        except ValidationError:
            return
        self.invoiced_metric.value.setText(money(report.invoiced_cents))
        self.collected_metric.value.setText(money(report.collected_cents))
        self.outstanding_metric.value.setText(money(report.outstanding_cents))
        self.overdue_metric.value.setText(money(report.overdue_cents))
        self.report_invoiced.value.setText(money(report.invoiced_cents))
        self.report_collected.value.setText(money(report.collected_cents))
        self.report_average.value.setText(money(report.average_invoice_cents))
        self.report_rate.value.setText(f"{report.collection_rate}%")
        populate_table(
            self.aging_table,
            (
                (bucket.label, str(bucket.invoice_count), money(bucket.balance_cents))
                for bucket in report.aging
            ),
        )
        populate_table(
            self.methods_table,
            (
                (method.replace("_", " ").title(), str(count), money(amount))
                for method, count, amount in report.payment_methods
            ),
        )

    def _layout_metric_cards(self, columns: int) -> None:
        for index, card in enumerate(self.metric_cards):
            self.metrics_layout.addWidget(card, index // columns, index % columns)

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        compact = self.width() < 1050
        self._layout_metric_cards(columns=2 if compact else 4)
        orientation = Qt.Orientation.Vertical if compact else Qt.Orientation.Horizontal
        if self.invoice_splitter.orientation() != orientation:
            self.invoice_splitter.setOrientation(orientation)
            self.invoice_splitter.setSizes([620, 300] if compact else [920, 340])
