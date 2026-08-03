from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QItemSelection, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QInputDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
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
    QVBoxLayout,
    QWidget,
)

from mcmahon_dispatch.core.exceptions import ValidationError
from mcmahon_dispatch.core.enums import CustomerStatus
from mcmahon_dispatch.database.models import Address, Contact, Customer, CustomerAddress, CustomerContact
from mcmahon_dispatch.repositories.customer_repository import CustomerStatistics
from mcmahon_dispatch.services.customer_service import CustomerSaveRequest, CustomerService


def money(cents: int | None) -> str:
    return f"${(cents or 0) / 100:,.2f}"


def add_cell(table: QTableWidget, row: int, column: int, text: str, user_data: Any = None) -> None:
    item = QTableWidgetItem(text)
    if user_data is not None:
        item.setData(Qt.ItemDataRole.UserRole, user_data)
    table.setItem(row, column, item)


class StatCard(QFrame):
    def __init__(self, title: str) -> None:
        super().__init__()
        self.setObjectName("metricCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        label = QLabel(title)
        label.setObjectName("muted")
        self.value = QLabel("—")
        self.value.setObjectName("metricValue")
        layout.addWidget(label)
        layout.addWidget(self.value)


class CustomerEditorDialog(QDialog):
    """Customer intake tailored to construction-delivery operations."""

    def __init__(self, customer: Customer | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Customer Profile" if customer else "New Customer")
        self.setMinimumSize(760, 680)
        self.resize(860, 760)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        heading = QLabel("Customer profile")
        heading.setObjectName("pageTitle")
        subtitle = QLabel(
            "Capture the defaults dispatchers need for faster quotes, safer deliveries, and cleaner billing."
        )
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        root.addWidget(heading)
        root.addWidget(subtitle)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        root.addWidget(self.tabs, 1)

        self._build_identity_tab(customer)
        self._build_operations_tab(customer)
        self._build_billing_tab(customer)
        self._build_relationship_tab(customer)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @staticmethod
    def _line(value: str | None = None, placeholder: str = "") -> QLineEdit:
        field = QLineEdit(value or "")
        field.setPlaceholderText(placeholder)
        field.setClearButtonEnabled(True)
        return field

    @staticmethod
    def _check(label: str, checked: bool = False) -> QCheckBox:
        field = QCheckBox(label)
        field.setChecked(checked)
        return field

    def _scroll_tab(self) -> tuple[QWidget, QFormLayout]:
        content = QWidget()
        form = QFormLayout(content)
        form.setContentsMargins(18, 18, 18, 18)
        form.setHorizontalSpacing(24)
        form.setVerticalSpacing(13)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        return scroll, form

    def _build_identity_tab(self, customer: Customer | None) -> None:
        tab, form = self._scroll_tab()
        self.company = self._line(customer.company_name if customer else None, "Example: Treasure Coast Plumbing")
        self.legal = self._line(customer.legal_name if customer else None, "Legal billing entity, when different")
        self.customer_type = QComboBox()
        self.customer_type.setEditable(True)
        self.customer_type.addItems([
            "", "General Contractor", "Subcontractor", "Plumber", "Electrician",
            "Roofer", "Remodeler", "Property Manager", "Supplier", "Other",
        ])
        if customer and customer.customer_type:
            self.customer_type.setCurrentText(customer.customer_type)
        self.status = QComboBox()
        for status in CustomerStatus:
            self.status.addItem(status.value.replace("_", " ").title(), status.value)
        if customer:
            self.status.setCurrentIndex(max(0, self.status.findData(customer.status)))
        self.phone = self._line(customer.primary_phone if customer else None, "Best business phone")
        self.email = self._line(customer.primary_email if customer else None, "Primary operational email")
        self.website = self._line(customer.website if customer else None, "https://")

        form.addRow("Company / display name*", self.company)
        form.addRow("Legal business name", self.legal)
        form.addRow("Customer type", self.customer_type)
        form.addRow("Account status", self.status)
        form.addRow("Main phone", self.phone)
        form.addRow("Main email", self.email)
        form.addRow("Website", self.website)
        self.tabs.addTab(tab, "Identity")

    def _build_operations_tab(self, customer: Customer | None) -> None:
        tab, form = self._scroll_tab()
        self.pickup_window = self._line(
            customer.preferred_pickup_window if customer else None,
            "Example: Weekdays 7:00–9:00 AM",
        )
        self.delivery_window = self._line(
            customer.preferred_delivery_window if customer else None,
            "Example: Before noon whenever possible",
        )
        self.receiving_hours = self._line(
            customer.receiving_hours if customer else None,
            "Recurring jobsite or office receiving hours",
        )
        self.typical_materials = QTextEdit(customer.typical_materials if customer else "")
        self.typical_materials.setPlaceholderText(
            "Common materials or job types: tile, plumbing fixtures, lumber, electrical supplies..."
        )
        self.typical_materials.setMaximumHeight(95)
        self.access = QTextEdit(customer.default_access_instructions if customer else "")
        self.access.setPlaceholderText(
            "Gate codes, parking, loading zones, stairs, call-ahead instructions, site hazards..."
        )
        self.access.setMaximumHeight(105)
        self.call_ahead = self._check("Call before arrival", bool(customer and customer.requires_call_ahead))
        self.updates = self._check(
            "Send transactional status updates",
            True if customer is None else customer.transactional_updates_enabled,
        )
        self.photos = self._check(
            "Photo confirmation required at delivery",
            bool(customer and customer.photo_confirmation_required),
        )
        self.appointment = self._check(
            "Pickup or delivery appointment normally required",
            bool(customer and customer.appointment_required),
        )
        self.forklift = self._check("Forklift commonly available", bool(customer and customer.forklift_available))
        self.liftgate = self._check("Liftgate commonly required", bool(customer and customer.liftgate_required))

        form.addRow("Preferred pickup window", self.pickup_window)
        form.addRow("Preferred delivery window", self.delivery_window)
        form.addRow("Receiving hours", self.receiving_hours)
        form.addRow("Typical materials / work", self.typical_materials)
        form.addRow("Default access instructions", self.access)
        form.addRow("", self.call_ahead)
        form.addRow("", self.updates)
        form.addRow("", self.photos)
        form.addRow("", self.appointment)
        form.addRow("", self.forklift)
        form.addRow("", self.liftgate)
        self.tabs.addTab(tab, "Delivery Preferences")

    def _build_billing_tab(self, customer: Customer | None) -> None:
        tab, form = self._scroll_tab()
        self.terms = QComboBox()
        self.terms.setEditable(True)
        for label, days in (("Due on receipt", 0), ("Net 7", 7), ("Net 15", 15), ("Net 30", 30), ("Net 45", 45)):
            self.terms.addItem(label, days)
        terms_days = customer.payment_terms_days if customer else 15
        idx = self.terms.findData(terms_days)
        if idx >= 0:
            self.terms.setCurrentIndex(idx)
        else:
            self.terms.setCurrentText(f"Net {terms_days}")
        self.payment = QComboBox()
        self.payment.setEditable(True)
        self.payment.addItems(["", "ACH", "Check", "Credit / Debit Card", "Cash", "External Payment Link", "Other"])
        if customer and customer.preferred_payment_method:
            self.payment.setCurrentText(customer.preferred_payment_method)
        self.billing_email = self._line(customer.billing_email if customer else None, "Invoice recipient email")
        self.po_required = self._check("Purchase order or job reference required", bool(customer and customer.purchase_order_required))
        self.credit = QDoubleSpinBox()
        self.credit.setRange(0, 10_000_000)
        self.credit.setDecimals(2)
        self.credit.setPrefix("$")
        self.credit.setSingleStep(500)
        self.credit.setSpecialValueText("No limit configured")
        self.credit.setValue((customer.credit_limit_cents or 0) / 100 if customer else 0)

        form.addRow("Payment terms", self.terms)
        form.addRow("Preferred payment method", self.payment)
        form.addRow("Billing email", self.billing_email)
        form.addRow("Credit limit", self.credit)
        form.addRow("", self.po_required)
        self.tabs.addTab(tab, "Billing")

    def _build_relationship_tab(self, customer: Customer | None) -> None:
        tab, form = self._scroll_tab()
        guidance = QLabel(
            "These scores are optional operational judgments. Revenue, profit, quote conversion, "
            "payment speed, and wait history are calculated automatically from completed work."
        )
        guidance.setWordWrap(True)
        guidance.setObjectName("muted")
        self.readiness = QDoubleSpinBox()
        self.readiness.setRange(0, 100)
        self.readiness.setDecimals(0)
        self.readiness.setSuffix(" / 100")
        self.readiness.setSpecialValueText("Not rated")
        self.relationship = QDoubleSpinBox()
        self.relationship.setRange(0, 100)
        self.relationship.setDecimals(0)
        self.relationship.setSuffix(" / 100")
        self.relationship.setSpecialValueText("Not rated")
        if customer and customer.readiness_score is not None:
            self.readiness.setValue(float(customer.readiness_score))
        if customer and customer.relationship_score is not None:
            self.relationship.setValue(float(customer.relationship_score))
        self.notes = QTextEdit(customer.internal_notes if customer else "")
        self.notes.setPlaceholderText(
            "Private operational context, service concerns, promises, relationship details, or account warnings."
        )
        self.notes.setMinimumHeight(180)

        form.addRow("", guidance)
        form.addRow("Order readiness rating", self.readiness)
        form.addRow("Relationship rating", self.relationship)
        form.addRow("Internal account notes", self.notes)
        self.tabs.addTab(tab, "Relationship & Risk")

    def _terms_days(self) -> int:
        data = self.terms.currentData()
        if isinstance(data, int):
            return data
        text = self.terms.currentText().strip().lower()
        if text in {"due on receipt", "cod", "cash on delivery"}:
            return 0
        digits = "".join(ch for ch in text if ch.isdigit())
        return int(digits) if digits else 15

    def _validate_and_accept(self) -> None:
        if not self.company.text().strip():
            self.tabs.setCurrentIndex(0)
            self.company.setFocus()
            QMessageBox.warning(self, "Company name required", "Enter the company or customer display name.")
            return
        email_values = [self.email.text().strip(), self.billing_email.text().strip()]
        for value in email_values:
            if value and ("@" not in value or value.startswith("@") or value.endswith("@")):
                QMessageBox.warning(self, "Check email address", f"'{value}' does not appear to be a valid email address.")
                return
        self.accept()

    def request(self) -> CustomerSaveRequest:
        readiness = self.readiness.value() or None
        relationship = self.relationship.value() or None
        return CustomerSaveRequest(
            company_name=self.company.text().strip(),
            legal_name=self.legal.text().strip() or None,
            status=str(self.status.currentData()),
            website=self.website.text().strip() or None,
            customer_type=self.customer_type.currentText().strip() or None,
            primary_phone=self.phone.text().strip() or None,
            primary_email=self.email.text().strip() or None,
            payment_terms_days=self._terms_days(),
            preferred_payment_method=self.payment.currentText().strip() or None,
            billing_email=self.billing_email.text().strip() or None,
            purchase_order_required=self.po_required.isChecked(),
            credit_limit_cents=int(round(self.credit.value() * 100)) or None,
            requires_call_ahead=self.call_ahead.isChecked(),
            transactional_updates_enabled=self.updates.isChecked(),
            photo_confirmation_required=self.photos.isChecked(),
            appointment_required=self.appointment.isChecked(),
            forklift_available=self.forklift.isChecked(),
            liftgate_required=self.liftgate.isChecked(),
            preferred_pickup_window=self.pickup_window.text().strip() or None,
            preferred_delivery_window=self.delivery_window.text().strip() or None,
            receiving_hours=self.receiving_hours.text().strip() or None,
            typical_materials=self.typical_materials.toPlainText().strip(),
            default_access_instructions=self.access.toPlainText().strip(),
            readiness_score=readiness,
            relationship_score=relationship,
            internal_notes=self.notes.toPlainText().strip(),
        )


class ContactDialog(QDialog):
    def __init__(self, link: CustomerContact | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent); self.setWindowTitle("Contact"); self.setMinimumWidth(520)
        c = link.contact if link else None
        form = QFormLayout()
        self.first = QLineEdit(c.first_name if c else ""); self.last = QLineEdit(c.last_name or "" if c else "")
        self.title = QLineEdit(c.role_title or "" if c else ""); self.phone = QLineEdit(c.phone or "" if c else "")
        self.mobile = QLineEdit(c.mobile or "" if c else ""); self.email = QLineEdit(c.email or "" if c else "")
        self.channel = QComboBox(); self.channel.addItems(["", "Phone", "SMS", "Email"])
        if c and c.preferred_channel: self.channel.setCurrentText(c.preferred_channel)
        self.primary = QCheckBox("Primary contact"); self.primary.setChecked(link.is_primary if link else False)
        self.transactional = QCheckBox("Transactional SMS consent"); self.transactional.setChecked(c.transactional_sms_consent if c else False)
        self.marketing = QCheckBox("Marketing SMS consent"); self.marketing.setChecked(c.marketing_sms_consent if c else False)
        self.notes = QTextEdit(c.notes if c else ""); self.notes.setMaximumHeight(90)
        for label, widget in (("First name*", self.first), ("Last name", self.last), ("Title/role", self.title), ("Phone", self.phone), ("Mobile", self.mobile), ("Email", self.email), ("Preferred channel", self.channel)):
            form.addRow(label, widget)
        form.addRow("", self.primary); form.addRow("", self.transactional); form.addRow("", self.marketing); form.addRow("Notes", self.notes)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        layout=QVBoxLayout(self); layout.addLayout(form); layout.addWidget(buttons)

    def data(self) -> dict[str, object]:
        return {"first_name": self.first.text(), "last_name": self.last.text(), "role_title": self.title.text(), "phone": self.phone.text(), "mobile": self.mobile.text(), "email": self.email.text(), "preferred_channel": self.channel.currentText(), "is_primary": self.primary.isChecked(), "transactional_sms_consent": self.transactional.isChecked(), "marketing_sms_consent": self.marketing.isChecked(), "notes": self.notes.toPlainText()}


class AddressDialog(QDialog):
    def __init__(self, link: CustomerAddress | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent); self.setWindowTitle("Address"); self.setMinimumWidth(580)
        a = link.address if link else None
        form=QFormLayout(); self.label=QLineEdit(a.label or "" if a else "")
        self.usage=QComboBox(); self.usage.addItems(["billing", "office", "jobsite", "other"])
        if link: self.usage.setCurrentText(link.usage_type)
        self.line1=QLineEdit(a.line1 or "" if a else ""); self.line2=QLineEdit(a.line2 or "" if a else "")
        self.city=QLineEdit(a.city or "" if a else ""); self.state=QLineEdit(a.state or "FL" if a else "FL"); self.zip=QLineEdit(a.postal_code or "" if a else "")
        self.full=QTextEdit(a.entered_address if a else ""); self.full.setMaximumHeight(75)
        self.instructions=QTextEdit(a.instructions if a else ""); self.instructions.setMaximumHeight(75)
        self.primary=QCheckBox("Primary for this usage"); self.primary.setChecked(link.is_primary if link else False)
        for label, widget in (("Label", self.label), ("Usage", self.usage), ("Address line 1", self.line1), ("Address line 2", self.line2), ("City", self.city), ("State", self.state), ("ZIP", self.zip), ("Complete address*", self.full), ("Instructions", self.instructions)):
            form.addRow(label, widget)
        form.addRow("", self.primary)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        layout=QVBoxLayout(self); layout.addLayout(form); layout.addWidget(buttons)

    def data(self) -> dict[str, object]:
        entered=self.full.toPlainText().strip() or ", ".join(x for x in [self.line1.text().strip(), self.city.text().strip(), self.state.text().strip(), self.zip.text().strip()] if x)
        return {"label":self.label.text(), "usage_type":self.usage.currentText(), "address_type":self.usage.currentText(), "line1":self.line1.text(), "line2":self.line2.text(), "city":self.city.text(), "state":self.state.text(), "postal_code":self.zip.text(), "entered_address":entered, "instructions":self.instructions.toPlainText(), "is_primary":self.primary.isChecked()}


class NoteDialog(QDialog):
    def __init__(self, body: str = "", note_type: str = "general", pinned: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent); self.setWindowTitle("Customer Note"); self.resize(520, 300)
        self.note_type=QComboBox(); self.note_type.addItems(["general", "operations", "billing", "service", "complaint", "follow-up"]); self.note_type.setCurrentText(note_type)
        self.pinned=QCheckBox("Pin note"); self.pinned.setChecked(pinned)
        self.body=QTextEdit(body)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        layout=QVBoxLayout(self); layout.addWidget(self.note_type); layout.addWidget(self.pinned); layout.addWidget(self.body,1); layout.addWidget(buttons)


class CustomerDetail(QWidget):
    edit_requested = Signal(str)
    data_changed = Signal()

    def __init__(self, service: CustomerService) -> None:
        super().__init__(); self.service=service; self.customer_id: str|None=None; self._customer: Customer|None=None; self._suppliers=[]
        outer=QVBoxLayout(self); outer.setContentsMargins(24,20,24,20)
        header=QHBoxLayout(); self.title=QLabel("Select a customer"); self.title.setObjectName("pageTitle"); self.number=QLabel(""); self.number.setObjectName("muted")
        title_box=QVBoxLayout(); title_box.addWidget(self.title); title_box.addWidget(self.number); header.addLayout(title_box); header.addStretch()
        self.edit=QPushButton("Edit profile"); self.edit.setObjectName("primaryButton"); self.edit.clicked.connect(lambda: self.customer_id and self.edit_requested.emit(self.customer_id)); header.addWidget(self.edit)
        outer.addLayout(header)
        stats=QGridLayout(); self.stat_cards={name:StatCard(name) for name in ("Revenue", "Profit", "Outstanding", "Quotes", "Invoices", "Jobs")}
        for i,card in enumerate(self.stat_cards.values()): stats.addWidget(card,i//3,i%3)
        outer.addLayout(stats)
        self.tabs=QTabWidget(); outer.addWidget(self.tabs,1)
        self.overview=QWidget(); self.contacts=QWidget(); self.addresses=QWidget(); self.history=QWidget(); self.quotes=QWidget(); self.invoices=QWidget(); self.documents=QWidget(); self.notes=QWidget(); self.suppliers=QWidget()
        for widget,label in ((self.overview,"Profile"),(self.contacts,"Contacts"),(self.addresses,"Addresses"),(self.history,"History"),(self.quotes,"Quotes"),(self.invoices,"Invoices"),(self.documents,"Documents"),(self.notes,"Notes"),(self.suppliers,"Preferred Suppliers")): self.tabs.addTab(widget,label)
        self._build_overview(); self._build_contacts(); self._build_addresses(); self._build_tables(); self._build_notes(); self._build_suppliers()
        self.setEnabled(False)

    def _build_overview(self) -> None:
        form=QFormLayout(self.overview); self.status=QLabel(); self.payment=QLabel(); self.terms=QLabel(); self.credit=QLabel(); self.readiness=QLabel(); self.relationship=QLabel(); self.internal=QTextEdit(); self.internal.setReadOnly(True)
        for label,widget in (("Status",self.status),("Preferred payment",self.payment),("Payment terms",self.terms),("Credit limit",self.credit),("Readiness score",self.readiness),("Relationship score",self.relationship),("Internal profile notes",self.internal)): form.addRow(label,widget)

    def _toolbar_table(self, parent: QWidget, columns: list[str]) -> tuple[QTableWidget,QHBoxLayout]:
        layout=QVBoxLayout(parent); tools=QHBoxLayout(); layout.addLayout(tools); table=QTableWidget(0,len(columns)); table.setHorizontalHeaderLabels(columns); table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch); layout.addWidget(table,1); return table,tools

    def _build_contacts(self) -> None:
        self.contacts_table,tools=self._toolbar_table(self.contacts,["Name","Role","Phone","Email","Primary"])
        add=QPushButton("Add contact"); edit=QPushButton("Edit"); remove=QPushButton("Remove"); tools.addWidget(add); tools.addWidget(edit); tools.addWidget(remove); tools.addStretch()
        add.clicked.connect(self._add_contact); edit.clicked.connect(self._edit_contact); remove.clicked.connect(self._remove_contact)

    def _build_addresses(self) -> None:
        self.address_table,tools=self._toolbar_table(self.addresses,["Usage","Label","Address","Primary"])
        add=QPushButton("Add address"); edit=QPushButton("Edit"); remove=QPushButton("Remove"); tools.addWidget(add); tools.addWidget(edit); tools.addWidget(remove); tools.addStretch()
        add.clicked.connect(self._add_address); edit.clicked.connect(self._edit_address); remove.clicked.connect(self._remove_address)

    def _build_tables(self) -> None:
        self.history_table,_=self._toolbar_table(self.history,["Date","Type","Reference","Status","Amount"])
        self.quote_table,_=self._toolbar_table(self.quotes,["Quote","Status","Created","Requested","Total","Profit"])
        self.invoice_table,_=self._toolbar_table(self.invoices,["Invoice","Status","Issued","Due","Total","Paid","Balance"])
        self.document_table,_=self._toolbar_table(self.documents,["Title","Type","File","Size","Uploaded"])

    def _build_notes(self) -> None:
        self.notes_table,tools=self._toolbar_table(self.notes,["Pinned","Type","Date","Note"])
        add=QPushButton("Add note"); edit=QPushButton("Edit"); delete=QPushButton("Delete"); tools.addWidget(add);tools.addWidget(edit);tools.addWidget(delete);tools.addStretch()
        add.clicked.connect(self._add_note); edit.clicked.connect(self._edit_note); delete.clicked.connect(self._delete_note)

    def _build_suppliers(self) -> None:
        layout=QVBoxLayout(self.suppliers); layout.addWidget(QLabel("Select suppliers in preferred order. The first selected supplier is the primary preference."))
        self.supplier_list=QListWidget(); layout.addWidget(self.supplier_list,1); save=QPushButton("Save preferred suppliers"); save.setObjectName("primaryButton"); save.clicked.connect(self._save_suppliers); layout.addWidget(save)

    def load(self, customer_id: str) -> None:
        try: customer,stats,quotes,invoices,jobs,documents,suppliers=self.service.load(customer_id)
        except ValidationError as exc: QMessageBox.warning(self,"Customer",str(exc)); return
        self.customer_id=customer_id; self._customer=customer; self._suppliers=suppliers; self.setEnabled(True)
        self.title.setText(customer.company_name); self.number.setText(customer.customer_number)
        self.status.setText(customer.status.replace("_"," ").title()); self.payment.setText(customer.preferred_payment_method or "Not specified"); self.terms.setText(f"Net {customer.payment_terms_days}")
        self.credit.setText(money(customer.credit_limit_cents)); self.readiness.setText(f"{customer.readiness_score}%" if customer.readiness_score is not None else "Not rated"); self.relationship.setText(f"{customer.relationship_score}%" if customer.relationship_score is not None else "Not rated"); self.internal.setPlainText(customer.internal_notes)
        self._set_stats(stats); self._fill_contacts(customer); self._fill_addresses(customer); self._fill_quotes(quotes); self._fill_invoices(invoices); self._fill_history(quotes,invoices,jobs); self._fill_documents(documents); self._fill_notes(customer); self._fill_suppliers(customer,suppliers)

    def _set_stats(self,s:CustomerStatistics)->None:
        vals={"Revenue":money(s.paid_revenue_cents),"Profit":money(s.actual_profit_cents),"Outstanding":money(s.outstanding_cents),"Quotes":str(s.quote_count),"Invoices":str(s.invoice_count),"Jobs":str(s.job_count)}
        for key,value in vals.items(): self.stat_cards[key].value.setText(value)

    def _fill_contacts(self,c:Customer)->None:
        self.contacts_table.setRowCount(0)
        for link in sorted(c.contacts,key=lambda x:(not x.is_primary,x.contact.last_name or "",x.contact.first_name)):
            r=self.contacts_table.rowCount();self.contacts_table.insertRow(r);name=f"{link.contact.first_name} {link.contact.last_name or ''}".strip();add_cell(self.contacts_table,r,0,name,link.contact.id);add_cell(self.contacts_table,r,1,link.contact.role_title or "");add_cell(self.contacts_table,r,2,link.contact.mobile or link.contact.phone or "");add_cell(self.contacts_table,r,3,link.contact.email or "");add_cell(self.contacts_table,r,4,"Yes" if link.is_primary else "")

    def _fill_addresses(self,c:Customer)->None:
        self.address_table.setRowCount(0)
        for link in c.addresses:
            r=self.address_table.rowCount();self.address_table.insertRow(r);add_cell(self.address_table,r,0,link.usage_type.title(),link.address.id);add_cell(self.address_table,r,1,link.address.label or "");add_cell(self.address_table,r,2,link.address.normalized_address or link.address.entered_address);add_cell(self.address_table,r,3,"Yes" if link.is_primary else "")

    def _fill_quotes(self,items)->None:
        self.quote_table.setRowCount(0)
        for q in items:
            r=self.quote_table.rowCount();self.quote_table.insertRow(r)
            for col,text in enumerate((q.quote_number,q.status.replace("_"," ").title(),q.created_at.strftime("%m/%d/%Y"),q.requested_service_at.strftime("%m/%d/%Y") if q.requested_service_at else "",money(q.total_cents),money(q.profit_cents))): add_cell(self.quote_table,r,col,text,q.id if col==0 else None)

    def _fill_invoices(self,items)->None:
        self.invoice_table.setRowCount(0)
        for inv in items:
            r=self.invoice_table.rowCount();self.invoice_table.insertRow(r)
            vals=(inv.invoice_number,inv.status.replace("_"," ").title(),inv.issued_at.strftime("%m/%d/%Y") if inv.issued_at else "",inv.due_at.strftime("%m/%d/%Y") if inv.due_at else "",money(inv.total_cents),money(inv.paid_cents),money(inv.balance_cents))
            for col,text in enumerate(vals):add_cell(self.invoice_table,r,col,text,inv.id if col==0 else None)

    def _fill_history(self,quotes,invoices,jobs)->None:
        rows=[]
        rows += [(q.created_at,"Quote",q.quote_number,q.status,money(q.total_cents)) for q in quotes]
        rows += [(i.created_at,"Invoice",i.invoice_number,i.status,money(i.total_cents)) for i in invoices]
        rows += [(j.created_at,"Job",j.job_number,j.status,money(j.actual_revenue_cents or j.quoted_revenue_cents)) for j in jobs]
        rows.sort(key=lambda x:x[0],reverse=True);self.history_table.setRowCount(0)
        for dt,kind,ref,status,amount in rows:
            r=self.history_table.rowCount();self.history_table.insertRow(r)
            for col,text in enumerate((dt.strftime("%m/%d/%Y %I:%M %p"),kind,ref,status.replace("_"," ").title(),amount)):add_cell(self.history_table,r,col,text)

    def _fill_documents(self,items)->None:
        self.document_table.setRowCount(0)
        for d in items:
            r=self.document_table.rowCount();self.document_table.insertRow(r)
            vals=(d.title,d.document_type.replace("_"," ").title(),d.file_name,f"{d.size_bytes/1024:,.1f} KB",d.created_at.strftime("%m/%d/%Y"))
            for col,text in enumerate(vals):add_cell(self.document_table,r,col,text,d.id if col==0 else None)

    def _fill_notes(self,c:Customer)->None:
        self.notes_table.setRowCount(0)
        for n in [x for x in c.notes if x.deleted_at is None]:
            r=self.notes_table.rowCount();self.notes_table.insertRow(r);add_cell(self.notes_table,r,0,"★" if n.pinned else "",n.id);add_cell(self.notes_table,r,1,n.note_type.title());add_cell(self.notes_table,r,2,n.created_at.strftime("%m/%d/%Y %I:%M %p"));add_cell(self.notes_table,r,3,n.body)

    def _fill_suppliers(self,c:Customer,suppliers)->None:
        selected={link.supplier_id:link.rank for link in c.preferred_suppliers};self.supplier_list.clear()
        for supplier in sorted(suppliers,key=lambda s:(selected.get(s.id,9999),s.name)):
            item=QListWidgetItem(supplier.name);item.setData(Qt.ItemDataRole.UserRole,supplier.id);item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable);item.setCheckState(Qt.CheckState.Checked if supplier.id in selected else Qt.CheckState.Unchecked);self.supplier_list.addItem(item)

    def _selected_id(self,table:QTableWidget)->str|None:
        row=table.currentRow();return str(table.item(row,0).data(Qt.ItemDataRole.UserRole)) if row>=0 and table.item(row,0) else None
    def _contact_link(self,cid:str): return next((x for x in self._customer.contacts if x.contact.id==cid),None) if self._customer else None
    def _address_link(self,aid:str): return next((x for x in self._customer.addresses if x.address.id==aid),None) if self._customer else None
    def _reload(self):
        if self.customer_id:self.load(self.customer_id);self.data_changed.emit()
    def _run(self,fn):
        try:fn();self._reload()
        except ValidationError as exc:QMessageBox.warning(self,"Customer",str(exc))
    def _add_contact(self):
        if not self.customer_id:return
        d=ContactDialog(parent=self)
        if d.exec()==QDialog.DialogCode.Accepted:self._run(lambda:self.service.save_contact(self.customer_id,d.data()))
    def _edit_contact(self):
        cid=self._selected_id(self.contacts_table);link=self._contact_link(cid) if cid else None
        if not cid or not link:return
        d=ContactDialog(link,self)
        if d.exec()==QDialog.DialogCode.Accepted:self._run(lambda:self.service.save_contact(self.customer_id,d.data(),cid))
    def _remove_contact(self):
        cid=self._selected_id(self.contacts_table)
        if cid and QMessageBox.question(self,"Remove contact","Remove this contact from the customer?")==QMessageBox.StandardButton.Yes:self._run(lambda:self.service.remove_contact(self.customer_id,cid))
    def _add_address(self):
        if not self.customer_id:return
        d=AddressDialog(parent=self)
        if d.exec()==QDialog.DialogCode.Accepted:self._run(lambda:self.service.save_address(self.customer_id,d.data()))
    def _edit_address(self):
        aid=self._selected_id(self.address_table);link=self._address_link(aid) if aid else None
        if not aid or not link:return
        d=AddressDialog(link,self)
        if d.exec()==QDialog.DialogCode.Accepted:self._run(lambda:self.service.save_address(self.customer_id,d.data(),aid))
    def _remove_address(self):
        aid=self._selected_id(self.address_table)
        if aid and QMessageBox.question(self,"Remove address","Remove this address from the customer?")==QMessageBox.StandardButton.Yes:self._run(lambda:self.service.remove_address(self.customer_id,aid))
    def _note_id(self):return self._selected_id(self.notes_table)
    def _add_note(self):
        if not self.customer_id:return
        d=NoteDialog(parent=self)
        if d.exec()==QDialog.DialogCode.Accepted:self._run(lambda:self.service.add_note(self.customer_id,d.body.toPlainText(),d.note_type.currentText(),d.pinned.isChecked()))
    def _edit_note(self):
        nid=self._note_id();note=next((n for n in self._customer.notes if n.id==nid),None) if self._customer else None
        if not note:return
        d=NoteDialog(note.body,note.note_type,note.pinned,self)
        if d.exec()==QDialog.DialogCode.Accepted:self._run(lambda:self.service.update_note(nid,d.body.toPlainText(),d.note_type.currentText(),d.pinned.isChecked()))
    def _delete_note(self):
        nid=self._note_id()
        if nid and QMessageBox.question(self,"Delete note","Delete this note?")==QMessageBox.StandardButton.Yes:self._run(lambda:self.service.delete_note(nid))
    def _save_suppliers(self):
        ids=[str(self.supplier_list.item(i).data(Qt.ItemDataRole.UserRole)) for i in range(self.supplier_list.count()) if self.supplier_list.item(i).checkState()==Qt.CheckState.Checked]
        self._run(lambda:self.service.set_preferred_suppliers(self.customer_id,ids))


class CustomerPage(QWidget):
    def __init__(self, service: CustomerService) -> None:
        super().__init__()
        self.service = service
        self._customers: list[Customer] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        top = QFrame()
        top.setObjectName("pageHeader")
        top_layout = QHBoxLayout(top)
        title = QLabel("Customers")
        title.setObjectName("pageTitle")
        top_layout.addWidget(title)
        top_layout.addStretch()

        self.new_button = QPushButton("New Customer")
        self.new_button.setObjectName("primaryButton")
        self.edit_button = QPushButton("Edit")
        self.duplicate_button = QPushButton("Duplicate")
        self.archive_button = QPushButton("Archive")
        self.delete_button = QPushButton("Delete")
        self.delete_button.setObjectName("dangerButton")
        for button in (
            self.new_button,
            self.edit_button,
            self.duplicate_button,
            self.archive_button,
            self.delete_button,
        ):
            top_layout.addWidget(button)
        root.addWidget(top)

        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        left = QWidget()
        left.setMinimumWidth(360)
        left.setMaximumWidth(560)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(18, 18, 12, 18)
        left_layout.setSpacing(10)

        self.search = QLineEdit()
        self.search.setPlaceholderText(
            "Search company, contact, phone, email, address, notes, quote, or invoice…"
        )
        self.search.setClearButtonEnabled(True)

        filters = QHBoxLayout()
        self.view_filter = QComboBox()
        self.view_filter.addItem("Active customers", "active")
        self.view_filter.addItem("Archived customers", "archived")
        self.view_filter.addItem("All customers", "all")
        self.status_filter = QComboBox()
        self.status_filter.addItem("All statuses", None)
        for status in CustomerStatus:
            self.status_filter.addItem(status.value.replace("_", " ").title(), status.value)
        self.balance_filter = QComboBox()
        self.balance_filter.addItem("All balances", None)
        self.balance_filter.addItem("Outstanding only", True)
        self.balance_filter.addItem("No outstanding", False)
        filters.addWidget(self.view_filter)
        filters.addWidget(self.status_filter)
        filters.addWidget(self.balance_filter)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Customer", "Status", "Contact", "Phone / Email", "Balance"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 5):
            self.table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )

        left_layout.addWidget(self.search)
        left_layout.addLayout(filters)
        left_layout.addWidget(self.table, 1)
        splitter.addWidget(left)

        self.detail = CustomerDetail(service)
        self.detail.edit_requested.connect(self._edit)
        self.detail.data_changed.connect(self.refresh)
        splitter.addWidget(self.detail)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([440, 1000])

        self.search.textChanged.connect(self._schedule)
        self.view_filter.currentIndexChanged.connect(self.refresh)
        self.status_filter.currentIndexChanged.connect(self.refresh)
        self.balance_filter.currentIndexChanged.connect(self.refresh)
        self.table.itemSelectionChanged.connect(self._selected)
        self.table.itemDoubleClicked.connect(lambda _item: self._edit_selected())
        self.table.customContextMenuRequested.connect(self._show_context_menu)

        self.new_button.clicked.connect(self._new)
        self.edit_button.clicked.connect(self._edit_selected)
        self.duplicate_button.clicked.connect(self._duplicate_selected)
        self.archive_button.clicked.connect(self._archive_or_restore_selected)
        self.delete_button.clicked.connect(self._delete_selected)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.refresh)
        self.refresh()

    def _schedule(self) -> None:
        self.timer.start()

    def _selected_customer_id(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return str(value) if value else None

    def _selected_customer(self) -> Customer | None:
        customer_id = self._selected_customer_id()
        return next((item for item in self._customers if item.id == customer_id), None)

    def _update_actions(self) -> None:
        customer = self._selected_customer()
        enabled = customer is not None
        self.edit_button.setEnabled(enabled)
        self.duplicate_button.setEnabled(enabled)
        self.archive_button.setEnabled(enabled)
        self.delete_button.setEnabled(enabled)
        if customer is None:
            self.archive_button.setText("Archive")
        elif customer.status == "archived":
            self.archive_button.setText("Restore")
        else:
            self.archive_button.setText("Archive")

    def refresh(self) -> None:
        current = self._selected_customer_id() or self.detail.customer_id
        statuses = [self.status_filter.currentData()] if self.status_filter.currentData() else None
        view = str(self.view_filter.currentData())
        self._customers = self.service.search(
            self.search.text(),
            statuses,
            has_outstanding=self.balance_filter.currentData(),
            include_archived=view == "all",
            only_archived=view == "archived",
        )

        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for customer in self._customers:
            row = self.table.rowCount()
            self.table.insertRow(row)
            primary = next(
                (link.contact for link in customer.contacts if link.is_primary),
                customer.contacts[0].contact if customer.contacts else None,
            )
            contact_name = (
                f"{primary.first_name} {primary.last_name or ''}".strip() if primary else ""
            )
            contact_method = (
                primary.mobile or primary.phone or primary.email or "" if primary else ""
            )
            add_cell(self.table, row, 0, customer.company_name, customer.id)
            add_cell(self.table, row, 1, customer.status.replace("_", " ").title())
            add_cell(self.table, row, 2, contact_name)
            add_cell(self.table, row, 3, contact_method)
            add_cell(self.table, row, 4, "")
            if customer.status == "archived":
                for column in range(self.table.columnCount()):
                    item = self.table.item(row, column)
                    if item:
                        item.setForeground(QColor("#9CA3AF"))
            if customer.id == current:
                self.table.selectRow(row)
        self.table.setSortingEnabled(True)

        if current and any(customer.id == current for customer in self._customers):
            self.detail.load(current)
        elif self._customers:
            self.table.selectRow(0)
        else:
            self.detail.customer_id = None
            self.detail.setEnabled(False)
        self._update_actions()

    def _selected(self) -> None:
        customer_id = self._selected_customer_id()
        if customer_id:
            self.detail.load(customer_id)
        self._update_actions()

    def _new(self) -> None:
        dialog = CustomerEditorDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            customer_id = self.service.save(dialog.request())
            self.refresh()
            self.detail.load(customer_id)
        except ValidationError as exc:
            QMessageBox.warning(self, "Customer", str(exc))

    def _edit_selected(self) -> None:
        customer_id = self._selected_customer_id()
        if customer_id:
            self._edit(customer_id)

    def _edit(self, customer_id: str) -> None:
        try:
            customer, *_ = self.service.load(customer_id)
        except ValidationError as exc:
            QMessageBox.warning(self, "Customer", str(exc))
            return
        dialog = CustomerEditorDialog(customer, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.service.save(dialog.request(), customer_id)
            self.refresh()
            self.detail.load(customer_id)
        except ValidationError as exc:
            QMessageBox.warning(self, "Customer", str(exc))

    def _archive_or_restore_selected(self) -> None:
        customer = self._selected_customer()
        if customer is None:
            return
        try:
            if customer.status == "archived":
                if QMessageBox.question(
                    self,
                    "Restore customer",
                    f"Restore {customer.company_name} to Active customers?",
                ) == QMessageBox.StandardButton.Yes:
                    self.service.restore(customer.id)
            else:
                if QMessageBox.question(
                    self,
                    "Archive customer",
                    f"Archive {customer.company_name}?\n\n"
                    "All quotes, jobs, invoices, documents, and history will be preserved.",
                ) == QMessageBox.StandardButton.Yes:
                    self.service.archive(customer.id)
            self.refresh()
        except ValidationError as exc:
            QMessageBox.warning(self, "Customer", str(exc))

    def _delete_selected(self) -> None:
        customer = self._selected_customer()
        if customer is None:
            return
        try:
            assessment = self.service.delete_assessment(customer.id)
        except ValidationError as exc:
            QMessageBox.warning(self, "Customer", str(exc))
            return
        if not assessment.can_delete:
            QMessageBox.information(
                self,
                "Archive required",
                f"{customer.company_name} cannot be deleted because it has "
                f"{', '.join(assessment.blockers)}.\n\n"
                "Archive the customer instead so historical business records remain intact.",
            )
            return
        answer = QMessageBox.warning(
            self,
            "Delete customer",
            f"Delete {customer.company_name}?\n\n"
            "This customer has no linked quotes, jobs, invoices, payments, or documents. "
            "The deletion will still be retained in the audit history.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.service.delete(customer.id)
            self.refresh()
        except ValidationError as exc:
            QMessageBox.warning(self, "Customer", str(exc))

    def _duplicate_selected(self) -> None:
        customer = self._selected_customer()
        if customer is None:
            return
        name, accepted = QInputDialog.getText(
            self,
            "Duplicate customer",
            "New company / branch name:",
            text=f"{customer.company_name} - Copy",
        )
        if not accepted:
            return
        try:
            duplicate_id = self.service.duplicate(customer.id, name)
            self.view_filter.setCurrentIndex(0)
            self.refresh()
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 0)
                if item and item.data(Qt.ItemDataRole.UserRole) == duplicate_id:
                    self.table.selectRow(row)
                    break
        except ValidationError as exc:
            QMessageBox.warning(self, "Customer", str(exc))

    def _merge_selected(self) -> None:
        source = self._selected_customer()
        if source is None:
            return
        candidates = [customer for customer in self._customers if customer.id != source.id]
        if not candidates:
            QMessageBox.information(
                self, "Merge customers", "No other customer is available in the current view."
            )
            return
        labels = [f"{customer.company_name} ({customer.customer_number})" for customer in candidates]
        selected_label, accepted = QInputDialog.getItem(
            self,
            "Merge customers",
            f"Move all history from {source.company_name} into:",
            labels,
            0,
            False,
        )
        if not accepted:
            return
        target = candidates[labels.index(selected_label)]
        try:
            preview = self.service.merge_preview(source.id, target.id)
        except ValidationError as exc:
            QMessageBox.warning(self, "Merge customers", str(exc))
            return
        answer = QMessageBox.warning(
            self,
            "Confirm customer merge",
            f"Merge {preview.source_name} into {preview.target_name}?\n\n"
            f"Source: {preview.source_statistics.quote_count} quotes, "
            f"{preview.source_statistics.job_count} jobs, "
            f"{preview.source_statistics.invoice_count} invoices.\n"
            f"Target: {preview.target_statistics.quote_count} quotes, "
            f"{preview.target_statistics.job_count} jobs, "
            f"{preview.target_statistics.invoice_count} invoices.\n\n"
            "Operational history will move to the target customer. The source profile will be archived.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            target_id = self.service.merge(source.id, target.id)
            self.refresh()
            self.detail.load(target_id)
        except ValidationError as exc:
            QMessageBox.warning(self, "Merge customers", str(exc))

    def _show_context_menu(self, position) -> None:
        index = self.table.indexAt(position)
        if index.isValid():
            self.table.selectRow(index.row())
        customer = self._selected_customer()
        if customer is None:
            return
        menu = QMenu(self)
        open_action = QAction("Open", menu)
        edit_action = QAction("Edit", menu)
        duplicate_action = QAction("Duplicate", menu)
        merge_action = QAction("Merge into another customer…", menu)
        archive_action = QAction(
            "Restore" if customer.status == "archived" else "Archive", menu
        )
        delete_action = QAction("Delete", menu)
        open_action.triggered.connect(self._selected)
        edit_action.triggered.connect(self._edit_selected)
        duplicate_action.triggered.connect(self._duplicate_selected)
        merge_action.triggered.connect(self._merge_selected)
        archive_action.triggered.connect(self._archive_or_restore_selected)
        delete_action.triggered.connect(self._delete_selected)
        menu.addAction(open_action)
        menu.addAction(edit_action)
        menu.addSeparator()
        menu.addAction(duplicate_action)
        menu.addAction(merge_action)
        menu.addSeparator()
        menu.addAction(archive_action)
        menu.addAction(delete_action)
        menu.exec(self.table.viewport().mapToGlobal(position))

