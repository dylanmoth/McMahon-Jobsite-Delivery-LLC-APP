from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from mcmahon_dispatch.core.exceptions import ValidationError
from mcmahon_dispatch.services.supplier_service import (
    SupplierContactRequest,
    SupplierDetails,
    SupplierLocationRequest,
    SupplierSaveRequest,
    SupplierService,
)
from mcmahon_dispatch.ui.common import DebouncedCall, PageHeader, configure_data_table


class SupplierDialog(QDialog):
    def __init__(self, parent: QWidget, details: SupplierDetails | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Supplier" if details else "New Supplier")
        self.setMinimumWidth(560)
        self.name = QLineEdit(details.name if details else "")
        self.category = QLineEdit(details.category if details else "")
        self.website = QLineEdit(details.website if details else "")
        self.active = QCheckBox("Active supplier")
        self.active.setChecked(details.active if details else True)
        self.notes = QTextEdit(details.notes if details else "")
        self.notes.setMinimumHeight(120)
        form = QFormLayout()
        form.addRow("Supplier name *", self.name)
        form.addRow("Category", self.category)
        form.addRow("Website", self.website)
        form.addRow("", self.active)
        form.addRow("Internal notes", self.notes)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def request(self) -> SupplierSaveRequest:
        return SupplierSaveRequest(
            name=self.name.text(),
            category=self.category.text(),
            website=self.website.text(),
            active=self.active.isChecked(),
            notes=self.notes.toPlainText(),
        )


class LocationDialog(QDialog):
    def __init__(self, parent: QWidget, existing=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Location" if existing else "New Supplier Location")
        self.resize(720, 700)
        self.display_name = QLineEdit(existing.display_name if existing else "")
        self.store_number = QLineEdit(existing.store_number if existing else "")
        self.phone = QLineEdit(existing.phone if existing else "")
        self.line1 = QLineEdit(existing.address if existing else "")
        self.line2 = QLineEdit()
        self.city = QLineEdit(existing.city if existing else "")
        self.state = QLineEdit(existing.state if existing else "FL")
        self.postal_code = QLineEdit(existing.postal_code if existing else "")
        self.pickup_desk = QLineEdit(existing.pickup_desk if existing else "")
        self.pickup_instructions = QTextEdit(existing.pickup_instructions if existing else "")
        self.access_notes = QTextEdit(existing.access_notes if existing else "")
        self.dock = QComboBox()
        self.dock.addItem("Unknown", None)
        self.dock.addItem("Available", True)
        self.dock.addItem("Not available", False)
        if existing:
            self.dock.setCurrentIndex(max(0, self.dock.findData(existing.dock_available)))
        self.loading_equipment = QLineEdit(
            ", ".join(existing.loading_equipment) if existing else ""
        )
        self.wait = QDoubleSpinBox()
        self.wait.setRange(0, 1440)
        self.wait.setSuffix(" minutes")
        self.wait.setValue(float(existing.average_wait_minutes or 0) if existing else 0)
        self.readiness = QDoubleSpinBox()
        self.readiness.setRange(0, 100)
        self.readiness.setSuffix("%")
        self.readiness.setValue(float(existing.readiness_score or 0) if existing else 0)
        self.active = QCheckBox("Active location")
        self.active.setChecked(existing.active if existing else True)
        form = QFormLayout()
        for label, widget in [
            ("Location name *", self.display_name),
            ("Store number", self.store_number),
            ("Phone", self.phone),
            ("Street address *", self.line1),
            ("Address line 2", self.line2),
            ("City", self.city),
            ("State", self.state),
            ("Postal code", self.postal_code),
            ("Pickup desk", self.pickup_desk),
            ("Dock", self.dock),
            ("Loading equipment", self.loading_equipment),
            ("Average wait", self.wait),
            ("Readiness", self.readiness),
            ("Pickup instructions", self.pickup_instructions),
            ("Access notes", self.access_notes),
            ("", self.active),
        ]:
            form.addRow(label, widget)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def request(self) -> SupplierLocationRequest:
        return SupplierLocationRequest(
            display_name=self.display_name.text(),
            store_number=self.store_number.text(),
            phone=self.phone.text(),
            line1=self.line1.text(),
            line2=self.line2.text(),
            city=self.city.text(),
            state=self.state.text(),
            postal_code=self.postal_code.text(),
            pickup_desk=self.pickup_desk.text(),
            pickup_instructions=self.pickup_instructions.toPlainText(),
            access_notes=self.access_notes.toPlainText(),
            dock_available=self.dock.currentData(),
            loading_equipment=tuple(
                item.strip() for item in self.loading_equipment.text().split(",") if item.strip()
            ),
            average_wait_minutes=Decimal(str(self.wait.value())),
            readiness_score=Decimal(str(self.readiness.value())),
            active=self.active.isChecked(),
        )


class ContactDialog(QDialog):
    def __init__(self, parent: QWidget, existing=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Contact" if existing else "New Supplier Contact")
        self.setMinimumWidth(520)
        self.first_name = QLineEdit(existing.first_name if existing else "")
        self.last_name = QLineEdit(existing.last_name if existing else "")
        self.role_title = QLineEdit(existing.role_title if existing else "")
        self.phone = QLineEdit(existing.phone if existing else "")
        self.mobile = QLineEdit(existing.mobile if existing else "")
        self.email = QLineEdit(existing.email if existing else "")
        self.notes = QTextEdit(existing.notes if existing else "")
        self.primary = QCheckBox("Primary supplier contact")
        self.primary.setChecked(existing.is_primary if existing else False)
        form = QFormLayout()
        for label, widget in [
            ("First name *", self.first_name),
            ("Last name", self.last_name),
            ("Role / department", self.role_title),
            ("Phone", self.phone),
            ("Mobile", self.mobile),
            ("Email", self.email),
            ("Notes", self.notes),
            ("", self.primary),
        ]:
            form.addRow(label, widget)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def request(self) -> SupplierContactRequest:
        return SupplierContactRequest(
            first_name=self.first_name.text(),
            last_name=self.last_name.text(),
            role_title=self.role_title.text(),
            phone=self.phone.text(),
            mobile=self.mobile.text(),
            email=self.email.text(),
            notes=self.notes.toPlainText(),
            is_primary=self.primary.isChecked(),
        )


class SupplierPage(QWidget):
    """Supplier directory with operational pickup intelligence."""

    def __init__(self, service: SupplierService) -> None:
        super().__init__()
        self.service = service
        self.rows = []
        self.current_details: SupplierDetails | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        self.new_button = QPushButton("New Supplier")
        self.new_button.setObjectName("primary")
        self.new_button.clicked.connect(self._new_supplier)
        root.addWidget(
            PageHeader(
                "Suppliers",
                "Manage supplier stores, contacts, pickup instructions, wait times, and readiness.",
                self.new_button,
            )
        )

        filter_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search suppliers, stores, phone numbers, or instructions")
        self.status = QComboBox()
        self.status.addItem("Active suppliers", True)
        self.status.addItem("Archived suppliers", False)
        self.status.addItem("All suppliers", None)
        self.category = QComboBox()
        self.category.addItem("All categories", None)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        filter_row.addWidget(self.search, 2)
        filter_row.addWidget(self.status)
        filter_row.addWidget(self.category)
        filter_row.addWidget(refresh)
        root.addLayout(filter_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.table = QTableWidget()
        configure_data_table(
            self.table,
            (
                "Supplier",
                "Category",
                "Locations",
                "Primary Phone",
                "City / State",
                "Avg Wait",
                "Readiness",
                "Preferred By",
                "Status",
            ),
            stretch_column=0,
        )
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.doubleClicked.connect(self._edit_supplier)
        splitter.addWidget(self.table)

        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        self.detail_title = QLabel("Select a supplier")
        self.detail_title.setObjectName("pageTitle")
        self.detail_meta = QLabel("")
        self.detail_meta.setObjectName("muted")
        self.detail_notes = QLabel("")
        self.detail_notes.setWordWrap(True)
        detail_layout.addWidget(self.detail_title)
        detail_layout.addWidget(self.detail_meta)
        detail_layout.addWidget(self.detail_notes)
        actions = QHBoxLayout()
        for label, handler in [
            ("Edit Supplier", self._edit_supplier),
            ("Archive / Restore", self._toggle_active),
            ("Delete", self._delete_supplier),
        ]:
            button = QPushButton(label)
            if label == "Delete":
                button.setObjectName("danger")
            button.clicked.connect(handler)
            actions.addWidget(button)
        actions.addStretch()
        detail_layout.addLayout(actions)

        self.tabs = QTabWidget()
        self.location_table = QTableWidget()
        configure_data_table(
            self.location_table,
            ("Location", "Store", "Address", "Phone", "Wait", "Readiness", "Active"),
            stretch_column=0,
        )
        self.location_table.doubleClicked.connect(self._edit_location)
        location_page = QWidget()
        location_layout = QVBoxLayout(location_page)
        location_bar = QHBoxLayout()
        add_location = QPushButton("Add Location")
        add_location.clicked.connect(self._new_location)
        edit_location = QPushButton("Edit Location")
        edit_location.clicked.connect(self._edit_location)
        location_bar.addWidget(add_location)
        location_bar.addWidget(edit_location)
        location_bar.addStretch()
        location_layout.addLayout(location_bar)
        location_layout.addWidget(self.location_table)

        self.contact_table = QTableWidget()
        configure_data_table(
            self.contact_table,
            ("Name", "Role", "Phone", "Mobile", "Email", "Primary"),
            stretch_column=0,
        )
        self.contact_table.doubleClicked.connect(self._edit_contact)
        contact_page = QWidget()
        contact_layout = QVBoxLayout(contact_page)
        contact_bar = QHBoxLayout()
        add_contact = QPushButton("Add Contact")
        add_contact.clicked.connect(self._new_contact)
        edit_contact = QPushButton("Edit Contact")
        edit_contact.clicked.connect(self._edit_contact)
        contact_bar.addWidget(add_contact)
        contact_bar.addWidget(edit_contact)
        contact_bar.addStretch()
        contact_layout.addLayout(contact_bar)
        contact_layout.addWidget(self.contact_table)

        self.instructions = QTextEdit()
        self.instructions.setReadOnly(True)
        self.tabs.addTab(location_page, "Locations")
        self.tabs.addTab(contact_page, "Contacts")
        self.tabs.addTab(self.instructions, "Pickup Instructions")
        detail_layout.addWidget(self.tabs, 1)
        splitter.addWidget(detail)
        splitter.setSizes([720, 620])
        root.addWidget(splitter, 1)

        self._debounce = DebouncedCall(self.refresh, parent=self)
        self.search.textChanged.connect(self._debounce.schedule)
        self.status.currentIndexChanged.connect(self.refresh)
        self.category.currentIndexChanged.connect(self.refresh)
        self.refresh()

    def on_activated(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        category = self.category.currentData()
        self.rows = self.service.suppliers(
            self.search.text(),
            self.status.currentData(),
            str(category) if category else None,
        )
        current_category = self.category.currentData()
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItem("All categories", None)
        for value in self.service.categories():
            self.category.addItem(value, value)
        index = self.category.findData(current_category)
        self.category.setCurrentIndex(max(index, 0))
        self.category.blockSignals(False)

        self.table.setRowCount(len(self.rows))
        for row_index, row in enumerate(self.rows):
            values = [
                row.name,
                row.category,
                str(row.location_count),
                row.primary_phone,
                row.city_state,
                (
                    f"{row.average_wait_minutes:.0f} min"
                    if row.average_wait_minutes is not None
                    else "-"
                ),
                f"{row.readiness_score:.0f}%" if row.readiness_score is not None else "-",
                str(row.preferred_customer_count),
                "Active" if row.active else "Archived",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, row.id)
                self.table.setItem(row_index, column, item)
        if self.rows:
            self.table.selectRow(0)
        else:
            self._clear_detail()

    def _selected_id(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _selection_changed(self) -> None:
        supplier_id = self._selected_id()
        if not supplier_id:
            self._clear_detail()
            return
        try:
            self.current_details = self.service.supplier(supplier_id)
        except ValidationError as exc:
            QMessageBox.warning(self, "Suppliers", str(exc))
            return
        details = self.current_details
        self.detail_title.setText(details.name)
        self.detail_meta.setText(
            " • ".join(
                value
                for value in (
                    details.category,
                    "Active" if details.active else "Archived",
                    details.website,
                )
                if value
            )
        )
        self.detail_notes.setText(details.notes or "No internal notes.")
        self._fill_locations(details)
        self._fill_contacts(details)
        instructions = []
        for location in details.locations:
            instructions.append(
                f"{location.display_name}\n"
                f"Pickup: {location.pickup_instructions or '-'}\n"
                f"Access: {location.access_notes or '-'}"
            )
        self.instructions.setPlainText("\n\n".join(instructions))

    def _fill_locations(self, details: SupplierDetails) -> None:
        self.location_table.setRowCount(len(details.locations))
        for row, location in enumerate(details.locations):
            values = [
                location.display_name,
                location.store_number,
                ", ".join(v for v in (location.address, location.city, location.state) if v),
                location.phone,
                (
                    f"{location.average_wait_minutes:.0f} min"
                    if location.average_wait_minutes is not None
                    else "-"
                ),
                f"{location.readiness_score:.0f}%" if location.readiness_score is not None else "-",
                "Yes" if location.active else "No",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, location.id)
                self.location_table.setItem(row, column, item)

    def _fill_contacts(self, details: SupplierDetails) -> None:
        self.contact_table.setRowCount(len(details.contacts))
        for row, contact in enumerate(details.contacts):
            values = [
                " ".join(v for v in (contact.first_name, contact.last_name) if v),
                contact.role_title,
                contact.phone,
                contact.mobile,
                contact.email,
                "Yes" if contact.is_primary else "",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, contact.id)
                self.contact_table.setItem(row, column, item)

    def _new_supplier(self) -> None:
        dialog = SupplierDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._save_supplier(dialog)

    def _edit_supplier(self) -> None:
        if self.current_details is None:
            return
        dialog = SupplierDialog(self, self.current_details)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._save_supplier(dialog, self.current_details.id)

    def _save_supplier(self, dialog: SupplierDialog, supplier_id: str | None = None) -> None:
        try:
            self.service.save_supplier(dialog.request(), supplier_id)
            self.refresh()
        except ValidationError as exc:
            QMessageBox.warning(self, "Supplier", str(exc))

    def _new_location(self) -> None:
        if self.current_details is None:
            return
        dialog = LocationDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._save_location(dialog)

    def _edit_location(self) -> None:
        if self.current_details is None:
            return
        row = self.location_table.currentRow()
        if row < 0:
            return
        location = self.current_details.locations[row]
        dialog = LocationDialog(self, location)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._save_location(dialog, location.id)

    def _save_location(self, dialog: LocationDialog, location_id: str | None = None) -> None:
        try:
            self.service.save_location(
                self.current_details.id,
                dialog.request(),
                location_id,
            )
            self.refresh()
        except ValidationError as exc:
            QMessageBox.warning(self, "Supplier Location", str(exc))

    def _new_contact(self) -> None:
        if self.current_details is None:
            return
        dialog = ContactDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._save_contact(dialog)

    def _edit_contact(self) -> None:
        if self.current_details is None:
            return
        row = self.contact_table.currentRow()
        if row < 0:
            return
        contact = self.current_details.contacts[row]
        dialog = ContactDialog(self, contact)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._save_contact(dialog, contact.id)

    def _save_contact(self, dialog: ContactDialog, contact_id: str | None = None) -> None:
        try:
            self.service.save_contact(
                self.current_details.id,
                dialog.request(),
                contact_id,
            )
            self.refresh()
        except ValidationError as exc:
            QMessageBox.warning(self, "Supplier Contact", str(exc))

    def _toggle_active(self) -> None:
        if self.current_details is None:
            return
        try:
            self.service.set_active(
                self.current_details.id,
                not self.current_details.active,
            )
            self.refresh()
        except ValidationError as exc:
            QMessageBox.warning(self, "Supplier", str(exc))

    def _delete_supplier(self) -> None:
        if self.current_details is None:
            return
        if (
            QMessageBox.warning(
                self,
                "Delete Supplier",
                f"Delete {self.current_details.name}?\n\n"
                "Suppliers with job history cannot be deleted and should be archived.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            self.service.delete_supplier(self.current_details.id)
            self.refresh()
        except ValidationError as exc:
            QMessageBox.warning(self, "Supplier", str(exc))

    def _clear_detail(self) -> None:
        self.current_details = None
        self.detail_title.setText("Select a supplier")
        self.detail_meta.clear()
        self.detail_notes.clear()
        self.location_table.setRowCount(0)
        self.contact_table.setRowCount(0)
        self.instructions.clear()
