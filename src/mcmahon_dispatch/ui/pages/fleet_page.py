from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from PySide6.QtCore import QDate, QDateTime, Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
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
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableView,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from mcmahon_dispatch.core.exceptions import ValidationError
from mcmahon_dispatch.repositories.fleet_repository import FuelRecord, MaintenanceRecordView, VehicleRecord
from mcmahon_dispatch.services.fleet_service import (
    FleetService,
    FuelSaveRequest,
    MaintenanceSaveRequest,
    VehicleSaveRequest,
)


STATUS_LABELS = {
    "available": "Available",
    "assigned": "Assigned",
    "reserved": "Reserved",
    "maintenance": "Maintenance",
    "out_of_service": "Out of Service",
    "inactive": "Inactive",
}


def money(cents: int | None) -> str:
    return "—" if cents is None else f"${cents / 100:,.2f}"


def date_text(value: date | None) -> str:
    return value.strftime("%b %d, %Y") if value else "—"


def optional_date(widget: QDateEdit, enabled: QCheckBox) -> date | None:
    return widget.date().toPython() if enabled.isChecked() else None


class SummaryCard(QFrame):
    def __init__(self, title: str) -> None:
        super().__init__()
        self.setObjectName("metricCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        label = QLabel(title)
        label.setObjectName("muted")
        self.value = QLabel("—")
        self.value.setObjectName("metricValue")
        layout.addWidget(label)
        layout.addWidget(self.value)


class VehicleDialog(QDialog):
    def __init__(self, parent: QWidget, record: VehicleRecord | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Vehicle" if record else "New Vehicle")
        self.resize(640, 720)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.number = QLineEdit(record.vehicle_number if record else "")
        self.year = QSpinBox(); self.year.setRange(1900, 2200); self.year.setValue(record.year if record else date.today().year)
        self.make = QLineEdit(record.make if record else "")
        self.model = QLineEdit(record.model if record else "")
        self.trim = QLineEdit(record.trim if record else "")
        self.ownership = QComboBox(); self.ownership.addItem("Owned", "owned"); self.ownership.addItem("Financed", "financed"); self.ownership.addItem("Leased", "leased"); self.ownership.addItem("Rental", "rental")
        self.status = QComboBox()
        for code, label in STATUS_LABELS.items(): self.status.addItem(label, code)
        self.odometer = QDoubleSpinBox(); self.odometer.setRange(0, 9_999_999); self.odometer.setDecimals(1); self.odometer.setSuffix(" mi")
        self.mpg = QDoubleSpinBox(); self.mpg.setRange(0, 999); self.mpg.setDecimals(2); self.mpg.setSpecialValueText("Not set")
        self.cost_per_mile = QDoubleSpinBox(); self.cost_per_mile.setRange(0, 9999); self.cost_per_mile.setDecimals(2); self.cost_per_mile.setPrefix("$"); self.cost_per_mile.setSuffix(" / mi")
        self.reg_enabled = QCheckBox("Track expiration")
        self.registration = QDateEdit(); self.registration.setCalendarPopup(True); self.registration.setDate(QDate.currentDate())
        self.ins_enabled = QCheckBox("Track expiration")
        self.insurance = QDateEdit(); self.insurance.setCalendarPopup(True); self.insurance.setDate(QDate.currentDate())
        self.length = QDoubleSpinBox(); self.length.setRange(0, 1000); self.length.setSuffix(" in")
        self.width_box = QDoubleSpinBox(); self.width_box.setRange(0, 1000); self.width_box.setSuffix(" in")
        self.height = QDoubleSpinBox(); self.height.setRange(0, 1000); self.height.setSuffix(" in")
        self.payload = QDoubleSpinBox(); self.payload.setRange(0, 100000); self.payload.setSuffix(" lb")
        self.dim_verified = QCheckBox("Cargo dimensions verified")
        self.payload_verified = QCheckBox("Payload verified")
        self.notes = QTextEdit()
        form.addRow("Vehicle number *", self.number); form.addRow("Year *", self.year); form.addRow("Make *", self.make); form.addRow("Model *", self.model); form.addRow("Trim", self.trim)
        form.addRow("Ownership", self.ownership); form.addRow("Status", self.status); form.addRow("Odometer", self.odometer); form.addRow("Estimated MPG", self.mpg); form.addRow("Cost per mile", self.cost_per_mile)
        reg_row = QWidget(); rl=QHBoxLayout(reg_row); rl.setContentsMargins(0,0,0,0); rl.addWidget(self.reg_enabled); rl.addWidget(self.registration)
        ins_row = QWidget(); il=QHBoxLayout(ins_row); il.setContentsMargins(0,0,0,0); il.addWidget(self.ins_enabled); il.addWidget(self.insurance)
        form.addRow("Registration", reg_row); form.addRow("Insurance", ins_row)
        dims = QWidget(); dl=QHBoxLayout(dims); dl.setContentsMargins(0,0,0,0); dl.addWidget(self.length); dl.addWidget(self.width_box); dl.addWidget(self.height)
        form.addRow("Cargo L × W × H", dims); form.addRow("Payload", self.payload); form.addRow("Verification", self.dim_verified); form.addRow("", self.payload_verified); form.addRow("Notes", self.notes)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
        if record:
            self.ownership.setCurrentIndex(max(0, self.ownership.findData(record.ownership_type))); self.status.setCurrentIndex(max(0, self.status.findData(record.status)))
            self.odometer.setValue(float(record.odometer_miles)); self.mpg.setValue(float(record.estimated_mpg or 0)); self.cost_per_mile.setValue((record.cost_per_mile_cents or 0)/100)
            if record.registration_expires_on: self.reg_enabled.setChecked(True); self.registration.setDate(QDate(record.registration_expires_on))
            if record.insurance_expires_on: self.ins_enabled.setChecked(True); self.insurance.setDate(QDate(record.insurance_expires_on))
            self.dim_verified.setChecked(record.dimensions_verified); self.payload_verified.setChecked(record.payload_verified); self.notes.setPlainText(record.notes)

    def request(self) -> VehicleSaveRequest:
        return VehicleSaveRequest(
            vehicle_number=self.number.text(), year=self.year.value(), make=self.make.text(), model=self.model.text(), trim=self.trim.text(),
            ownership_type=str(self.ownership.currentData()), status=str(self.status.currentData()), odometer_miles=Decimal(str(self.odometer.value())),
            estimated_mpg=Decimal(str(self.mpg.value())) if self.mpg.value() else None,
            cost_per_mile_cents=round(self.cost_per_mile.value()*100) if self.cost_per_mile.value() else None,
            registration_expires_on=optional_date(self.registration, self.reg_enabled), insurance_expires_on=optional_date(self.insurance, self.ins_enabled),
            cargo_length_inches=Decimal(str(self.length.value())) if self.length.value() else None, cargo_width_inches=Decimal(str(self.width_box.value())) if self.width_box.value() else None,
            cargo_height_inches=Decimal(str(self.height.value())) if self.height.value() else None, payload_pounds=Decimal(str(self.payload.value())) if self.payload.value() else None,
            dimensions_verified=self.dim_verified.isChecked(), payload_verified=self.payload_verified.isChecked(), notes=self.notes.toPlainText(),
        )


class MaintenanceDialog(QDialog):
    def __init__(self, parent: QWidget, vehicles: list[VehicleRecord]) -> None:
        super().__init__(parent); self.setWindowTitle("Add Maintenance or Repair"); self.resize(620, 650)
        layout=QVBoxLayout(self); form=QFormLayout()
        self.vehicle=QComboBox(); [self.vehicle.addItem(v.display_name, v.id) for v in vehicles]
        self.kind=QComboBox(); self.kind.setEditable(True); self.kind.addItems(["Oil Change", "Tire Rotation", "Brake Service", "Battery", "Inspection", "Repair", "Registration Renewal", "Insurance Renewal"])
        self.status=QComboBox(); self.status.addItem("Scheduled", "scheduled"); self.status.addItem("Completed", "completed"); self.status.addItem("Overdue", "overdue"); self.status.addItem("Cancelled", "cancelled")
        self.due_enabled=QCheckBox("Use due date"); self.due=QDateEdit(); self.due.setCalendarPopup(True); self.due.setDate(QDate.currentDate())
        self.due_miles=QDoubleSpinBox(); self.due_miles.setRange(0,9_999_999); self.due_miles.setDecimals(1); self.due_miles.setSpecialValueText("Not set")
        self.completed_enabled=QCheckBox("Completed"); self.completed=QDateEdit(); self.completed.setCalendarPopup(True); self.completed.setDate(QDate.currentDate())
        self.completed_miles=QDoubleSpinBox(); self.completed_miles.setRange(0,9_999_999); self.completed_miles.setDecimals(1); self.completed_miles.setSpecialValueText("Not set")
        self.vendor=QLineEdit(); self.cost=QDoubleSpinBox(); self.cost.setRange(0,999999); self.cost.setPrefix("$"); self.cost.setDecimals(2)
        self.description=QTextEdit(); self.notes=QTextEdit()
        self.next_enabled=QCheckBox("Set next due date"); self.next_due=QDateEdit(); self.next_due.setCalendarPopup(True); self.next_due.setDate(QDate.currentDate().addMonths(6))
        self.next_miles=QDoubleSpinBox(); self.next_miles.setRange(0,9_999_999); self.next_miles.setDecimals(1); self.next_miles.setSpecialValueText("Not set")
        form.addRow("Vehicle *",self.vehicle); form.addRow("Service / repair *",self.kind); form.addRow("Status",self.status)
        due_row=QWidget(); d=QHBoxLayout(due_row); d.setContentsMargins(0,0,0,0); d.addWidget(self.due_enabled); d.addWidget(self.due); form.addRow("Due date",due_row)
        form.addRow("Due mileage",self.due_miles)
        comp_row=QWidget(); c=QHBoxLayout(comp_row); c.setContentsMargins(0,0,0,0); c.addWidget(self.completed_enabled); c.addWidget(self.completed); form.addRow("Completion",comp_row)
        form.addRow("Completed mileage",self.completed_miles); form.addRow("Service provider",self.vendor); form.addRow("Cost",self.cost); form.addRow("Description",self.description); form.addRow("Notes",self.notes)
        next_row=QWidget(); n=QHBoxLayout(next_row); n.setContentsMargins(0,0,0,0); n.addWidget(self.next_enabled); n.addWidget(self.next_due); form.addRow("Next due",next_row); form.addRow("Next due mileage",self.next_miles)
        layout.addLayout(form); buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)

    def request(self)->MaintenanceSaveRequest:
        return MaintenanceSaveRequest(str(self.vehicle.currentData()),self.kind.currentText(),str(self.status.currentData()),optional_date(self.due,self.due_enabled),Decimal(str(self.due_miles.value())) if self.due_miles.value() else None,optional_date(self.completed,self.completed_enabled),Decimal(str(self.completed_miles.value())) if self.completed_miles.value() else None,self.vendor.text(),round(self.cost.value()*100),self.description.toPlainText(),self.notes.toPlainText(),optional_date(self.next_due,self.next_enabled),Decimal(str(self.next_miles.value())) if self.next_miles.value() else None)


class FuelDialog(QDialog):
    def __init__(self,parent:QWidget,vehicles:list[VehicleRecord])->None:
        super().__init__(parent); self.setWindowTitle("Add Fuel Purchase"); self.resize(520,470)
        layout=QVBoxLayout(self); form=QFormLayout(); self.vehicle=QComboBox(); [self.vehicle.addItem(v.display_name,v.id) for v in vehicles]
        self.when=QDateTimeEdit(); self.when.setCalendarPopup(True); self.when.setDateTime(QDateTime.currentDateTime())
        self.odometer=QDoubleSpinBox(); self.odometer.setRange(0,9_999_999); self.odometer.setDecimals(1); self.odometer.setSuffix(" mi")
        self.gallons=QDoubleSpinBox(); self.gallons.setRange(0.001,9999); self.gallons.setDecimals(3); self.gallons.setSuffix(" gal")
        self.price=QDoubleSpinBox(); self.price.setRange(0,99); self.price.setDecimals(3); self.price.setPrefix("$"); self.price.setSuffix(" / gal")
        self.total=QDoubleSpinBox(); self.total.setRange(0,99999); self.total.setDecimals(2); self.total.setPrefix("$")
        self.vendor=QLineEdit(); self.full=QCheckBox("Full tank (used for MPG calculation)"); self.full.setChecked(True)
        self.gallons.valueChanged.connect(self._calculate); self.price.valueChanged.connect(self._calculate)
        for label,w in [("Vehicle *",self.vehicle),("Purchased",self.when),("Odometer *",self.odometer),("Gallons *",self.gallons),("Price per gallon",self.price),("Total cost",self.total),("Station / vendor",self.vendor),("",self.full)]: form.addRow(label,w)
        layout.addLayout(form); buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
    def _calculate(self)->None: self.total.setValue(round(self.gallons.value()*self.price.value(),2))
    def request(self)->FuelSaveRequest:
        dt=self.when.dateTime().toPython(); dt=dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
        return FuelSaveRequest(str(self.vehicle.currentData()),dt,Decimal(str(self.odometer.value())),Decimal(str(self.gallons.value())),round(self.price.value()*100),round(self.total.value()*100),self.vendor.text(),self.full.isChecked())


class FleetPage(QWidget):
    def __init__(self, service:FleetService)->None:
        super().__init__(); self.service=service; self._vehicles:list[VehicleRecord]=[]
        root=QVBoxLayout(self); root.setContentsMargins(22,18,22,18); root.setSpacing(14)
        title=QLabel("Fleet Management"); title.setObjectName("pageTitle"); subtitle=QLabel("Vehicles, maintenance, fuel, insurance, registration, and operating costs."); subtitle.setObjectName("muted")
        root.addWidget(title); root.addWidget(subtitle)
        cards=QGridLayout(); self.vehicle_card=SummaryCard("Active Vehicles"); self.available_card=SummaryCard("Available Now"); self.due_card=SummaryCard("Maintenance Due"); self.docs_card=SummaryCard("Expired Documents"); self.cost_card=SummaryCard("Blended Cost / Mile")
        for i,c in enumerate([self.vehicle_card,self.available_card,self.due_card,self.docs_card,self.cost_card]): cards.addWidget(c,0,i)
        root.addLayout(cards)
        self.tabs=QTabWidget(); root.addWidget(self.tabs,1)
        self.tabs.addTab(self._build_vehicles(),"Vehicles"); self.tabs.addTab(self._build_maintenance(),"Maintenance & Repairs"); self.tabs.addTab(self._build_fuel(),"Fuel"); self.tabs.addTab(self._build_reports(),"Reports")
        self.refresh()

    def _build_vehicles(self)->QWidget:
        page=QWidget(); layout=QVBoxLayout(page); bar=QHBoxLayout(); self.search=QLineEdit(); self.search.setPlaceholderText("Search vehicles…"); self.search.textChanged.connect(self.refresh_vehicles)
        self.include_inactive=QCheckBox("Show inactive"); self.include_inactive.toggled.connect(self.refresh_vehicles)
        new=QPushButton("New Vehicle"); new.clicked.connect(self.new_vehicle); edit=QPushButton("Edit"); edit.clicked.connect(self.edit_vehicle); archive=QPushButton("Archive"); archive.clicked.connect(self.archive_vehicle); refresh=QPushButton("Refresh"); refresh.clicked.connect(self.refresh)
        bar.addWidget(self.search,1); bar.addWidget(self.include_inactive); bar.addWidget(new); bar.addWidget(edit); bar.addWidget(archive); bar.addWidget(refresh); layout.addLayout(bar)
        self.vehicle_table=QTableView(); self.vehicle_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.vehicle_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection); self.vehicle_table.setSortingEnabled(True); self.vehicle_table.doubleClicked.connect(self.edit_vehicle)
        self.vehicle_model=QStandardItemModel(0,9,self); self.vehicle_model.setHorizontalHeaderLabels(["Vehicle","Status","Odometer","MPG","Cost / Mile","Registration","Insurance","Ownership","Verification"]); self.vehicle_table.setModel(self.vehicle_model); self.vehicle_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents); self.vehicle_table.horizontalHeader().setStretchLastSection(True); layout.addWidget(self.vehicle_table,1); return page

    def _build_maintenance(self)->QWidget:
        page=QWidget(); layout=QVBoxLayout(page); bar=QHBoxLayout(); add=QPushButton("Add Maintenance / Repair"); add.clicked.connect(self.add_maintenance); refresh=QPushButton("Refresh"); refresh.clicked.connect(self.refresh_maintenance); bar.addStretch(); bar.addWidget(add); bar.addWidget(refresh); layout.addLayout(bar)
        self.maintenance_table=QTableView(); self.maintenance_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.maintenance_model=QStandardItemModel(0,9,self); self.maintenance_model.setHorizontalHeaderLabels(["Vehicle","Service / Repair","Status","Due Date","Due Mileage","Completed","Provider","Cost","Next Due"]); self.maintenance_table.setModel(self.maintenance_model); self.maintenance_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents); self.maintenance_table.horizontalHeader().setStretchLastSection(True); layout.addWidget(self.maintenance_table,1); return page

    def _build_fuel(self)->QWidget:
        page=QWidget(); layout=QVBoxLayout(page); bar=QHBoxLayout(); add=QPushButton("Add Fuel Purchase"); add.clicked.connect(self.add_fuel); refresh=QPushButton("Refresh"); refresh.clicked.connect(self.refresh_fuel); bar.addStretch(); bar.addWidget(add); bar.addWidget(refresh); layout.addLayout(bar)
        self.fuel_table=QTableView(); self.fuel_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.fuel_model=QStandardItemModel(0,8,self); self.fuel_model.setHorizontalHeaderLabels(["Date","Vehicle","Odometer","Gallons","Price / Gal","Total","Calculated MPG","Vendor"]); self.fuel_table.setModel(self.fuel_model); self.fuel_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents); self.fuel_table.horizontalHeader().setStretchLastSection(True); layout.addWidget(self.fuel_table,1); return page

    def _build_reports(self)->QWidget:
        page=QWidget(); layout=QVBoxLayout(page); self.report_label=QLabel(); self.report_label.setWordWrap(True); self.report_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse); self.report_label.setObjectName("reportSummary"); layout.addWidget(self.report_label); layout.addStretch(); return page

    def on_activated(self)->None: self.refresh()
    def refresh(self)->None: self.refresh_summary(); self.refresh_vehicles(); self.refresh_maintenance(); self.refresh_fuel()
    def refresh_summary(self)->None:
        s=self.service.summary(); self.vehicle_card.value.setText(str(s.vehicle_count)); self.available_card.value.setText(str(s.available_count)); self.due_card.value.setText(str(s.maintenance_due_count)); self.docs_card.value.setText(str(s.expired_document_count)); self.cost_card.value.setText(money(s.blended_cost_per_mile_cents))
        self.report_label.setText(f"<h2>Fleet Cost Summary</h2><p><b>Total recorded vehicle mileage:</b> {s.total_miles:,.1f} mi</p><p><b>Fuel spending:</b> {money(s.fuel_cost_cents)}</p><p><b>Maintenance and repair spending:</b> {money(s.maintenance_cost_cents)}</p><p><b>Average calculated MPG:</b> {s.average_mpg or 'Not enough full-tank entries'}</p><p><b>Blended fuel + maintenance cost per mile:</b> {money(s.blended_cost_per_mile_cents)}</p><p class='muted'>Cost per mile uses recorded fuel and maintenance costs divided by current fleet odometer totals. Fixed payments, insurance premiums, depreciation, and other overhead are not included unless recorded elsewhere.</p>")

    def refresh_vehicles(self)->None:
        self._vehicles=self.service.list_vehicles(self.search.text() if hasattr(self,'search') else "", self.include_inactive.isChecked() if hasattr(self,'include_inactive') else False); self.vehicle_model.removeRows(0,self.vehicle_model.rowCount())
        today=date.today()
        for v in self._vehicles:
            verification="Verified" if v.dimensions_verified and v.payload_verified else "Capacity not verified"
            row=[QStandardItem(v.display_name),QStandardItem(STATUS_LABELS.get(v.status,v.status.title())),QStandardItem(f"{v.odometer_miles:,.1f} mi"),QStandardItem(str(v.estimated_mpg or "—")),QStandardItem(money(v.cost_per_mile_cents)),QStandardItem(date_text(v.registration_expires_on)),QStandardItem(date_text(v.insurance_expires_on)),QStandardItem(v.ownership_type.title()),QStandardItem(verification)]
            row[0].setData(v.id,Qt.ItemDataRole.UserRole)
            if (v.registration_expires_on and v.registration_expires_on < today) or (v.insurance_expires_on and v.insurance_expires_on < today): [item.setToolTip("Registration or insurance is expired.") for item in row]
            self.vehicle_model.appendRow(row)

    def refresh_maintenance(self)->None:
        self.maintenance_model.removeRows(0,self.maintenance_model.rowCount())
        for r in self.service.list_maintenance(): self.maintenance_model.appendRow([QStandardItem(r.vehicle_name),QStandardItem(r.maintenance_type),QStandardItem(r.status.replace('_',' ').title()),QStandardItem(date_text(r.due_date)),QStandardItem(f"{r.due_odometer_miles:,.1f}" if r.due_odometer_miles is not None else "—"),QStandardItem(date_text(r.completed_date)),QStandardItem(r.service_vendor or "—"),QStandardItem(money(r.cost_cents)),QStandardItem(date_text(r.next_due_date) if r.next_due_date else (f"{r.next_due_odometer_miles:,.1f} mi" if r.next_due_odometer_miles is not None else "—"))])

    def refresh_fuel(self)->None:
        self.fuel_model.removeRows(0,self.fuel_model.rowCount())
        for r in self.service.list_fuel(): self.fuel_model.appendRow([QStandardItem(r.purchased_at.astimezone().strftime("%b %d, %Y %I:%M %p")),QStandardItem(r.vehicle_name),QStandardItem(f"{r.odometer_miles:,.1f} mi"),QStandardItem(f"{r.gallons:,.3f}"),QStandardItem(money(r.price_per_gallon_cents)),QStandardItem(money(r.total_cost_cents)),QStandardItem(str(r.calculated_mpg or "—")),QStandardItem(r.vendor_name or "—")])

    def _selected_vehicle(self)->VehicleRecord|None:
        idx=self.vehicle_table.currentIndex()
        if not idx.isValid(): return None
        vehicle_id=self.vehicle_model.item(idx.row(),0).data(Qt.ItemDataRole.UserRole)
        return next((v for v in self._vehicles if v.id==vehicle_id),None)

    def new_vehicle(self)->None:
        dialog=VehicleDialog(self)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        try:self.service.save_vehicle(dialog.request());self.refresh()
        except ValidationError as exc:QMessageBox.warning(self,"Vehicle",str(exc))
    def edit_vehicle(self)->None:
        record=self._selected_vehicle()
        if record is None: QMessageBox.information(self,"Vehicle","Select a vehicle first."); return
        dialog=VehicleDialog(self,record)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        try:self.service.save_vehicle(dialog.request(),record.id);self.refresh()
        except ValidationError as exc:QMessageBox.warning(self,"Vehicle",str(exc))
    def archive_vehicle(self)->None:
        record=self._selected_vehicle()
        if record is None:return
        if QMessageBox.question(self,"Archive vehicle",f"Archive {record.display_name}?\n\nHistorical fuel, maintenance, and job records will remain available.",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.Cancel)!=QMessageBox.StandardButton.Yes:return
        try:self.service.archive_vehicle(record.id);self.refresh()
        except ValidationError as exc:QMessageBox.warning(self,"Vehicle",str(exc))
    def add_maintenance(self)->None:
        vehicles=self.service.list_vehicles(include_inactive=True)
        if not vehicles: QMessageBox.information(self,"Maintenance","Add a vehicle first."); return
        dialog=MaintenanceDialog(self,vehicles)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        try:self.service.save_maintenance(dialog.request());self.refresh()
        except ValidationError as exc:QMessageBox.warning(self,"Maintenance",str(exc))
    def add_fuel(self)->None:
        vehicles=self.service.list_vehicles()
        if not vehicles: QMessageBox.information(self,"Fuel","Add an active vehicle first."); return
        dialog=FuelDialog(self,vehicles)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        try:self.service.save_fuel(dialog.request());self.refresh()
        except ValidationError as exc:QMessageBox.warning(self,"Fuel",str(exc))

    def resizeEvent(self,event)->None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        if hasattr(self,"vehicle_card"):
            # Summary cards wrap into two rows on compact windows.
            parent=self.vehicle_card.parentWidget()
            if parent and parent.layout() and isinstance(parent.layout(),QGridLayout):
                grid=parent.layout(); compact=self.width()<1180
                for i,card in enumerate([self.vehicle_card,self.available_card,self.due_card,self.docs_card,self.cost_card]): grid.addWidget(card,i//3 if compact else 0,i%3 if compact else i)
