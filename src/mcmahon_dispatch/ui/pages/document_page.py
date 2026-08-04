from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from mcmahon_dispatch.core.exceptions import ValidationError
from mcmahon_dispatch.services.document_service import (
    DocumentDetails,
    DocumentService,
    DocumentUploadRequest,
)
from mcmahon_dispatch.ui.common import DebouncedCall, PageHeader, configure_data_table


def _file_size(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


class UploadDialog(QDialog):
    TYPES = (
        "contract",
        "proof_of_delivery",
        "job_photo",
        "invoice",
        "quote",
        "insurance",
        "registration",
        "receipt",
        "permit",
        "blueprint",
        "other",
    )

    def __init__(self, parent: QWidget, source: Path | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Upload Document")
        self.setMinimumWidth(600)
        self.source = QLineEdit(str(source or ""))
        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse)
        source_row = QHBoxLayout()
        source_row.addWidget(self.source, 1)
        source_row.addWidget(browse)
        source_holder = QWidget()
        source_holder.setLayout(source_row)
        self.title = QLineEdit(source.stem if source else "")
        self.document_type = QComboBox()
        for value in self.TYPES:
            self.document_type.addItem(value.replace("_", " ").title(), value)
        self.retention = QComboBox()
        self.retention.addItem("Business Record", "business")
        self.retention.addItem("Financial Record", "financial")
        self.retention.addItem("Compliance Record", "compliance")
        self.retention.addItem("Temporary", "temporary")
        self.entity_type = QComboBox()
        self.entity_type.setEditable(True)
        self.entity_type.addItems(
            ["", "customer", "supplier", "quote", "job", "invoice", "vehicle", "driver"]
        )
        self.entity_id = QLineEdit()
        self.relationship = QComboBox()
        for value in ("attachment", "source", "proof", "receipt", "signed_copy", "photo"):
            self.relationship.addItem(value.replace("_", " ").title(), value)
        self.notes = QTextEdit()
        self.notes.setMinimumHeight(100)
        form = QFormLayout()
        form.addRow("File *", source_holder)
        form.addRow("Title *", self.title)
        form.addRow("Document type *", self.document_type)
        form.addRow("Retention", self.retention)
        form.addRow("Link to record type", self.entity_type)
        form.addRow("Record ID", self.entity_id)
        form.addRow("Relationship", self.relationship)
        form.addRow("Notes", self.notes)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _browse(self) -> None:
        file_name, _ = QFileDialog.getOpenFileName(self, "Select Document")
        if file_name:
            self.source.setText(file_name)
            if not self.title.text().strip():
                self.title.setText(Path(file_name).stem)

    def request(self) -> DocumentUploadRequest:
        entity_type = self.entity_type.currentText().strip()
        entity_id = self.entity_id.text().strip()
        return DocumentUploadRequest(
            source_path=Path(self.source.text()),
            title=self.title.text(),
            document_type=str(self.document_type.currentData()),
            retention_class=str(self.retention.currentData()),
            entity_type=entity_type or None,
            entity_id=entity_id or None,
            relationship_type=str(self.relationship.currentData()),
            notes=self.notes.toPlainText(),
        )


class DocumentPage(QWidget):
    """Searchable managed document library with safe local storage."""

    def __init__(self, service: DocumentService) -> None:
        super().__init__()
        self.service = service
        self.rows = []
        self.current: DocumentDetails | None = None
        self.setAcceptDrops(True)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        upload = QPushButton("Upload Document")
        upload.setObjectName("primary")
        upload.clicked.connect(self._upload)
        root.addWidget(
            PageHeader(
                "Documents",
                "Store, search, link, open, and manage business files in one place.",
                upload,
            )
        )

        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search title, file name, type, or metadata")
        self.document_type = QComboBox()
        self.document_type.addItem("All document types", None)
        self.status = QComboBox()
        self.status.addItem("Active documents", "active")
        self.status.addItem("Archived documents", "archived")
        self.status.addItem("Quarantined documents", "quarantined")
        self.status.addItem("All statuses", None)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        filters.addWidget(self.search, 2)
        filters.addWidget(self.document_type)
        filters.addWidget(self.status)
        filters.addWidget(refresh)
        root.addLayout(filters)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.table = QTableWidget()
        configure_data_table(
            self.table,
            ("Title", "Type", "File", "Size", "Added", "Links", "Status"),
            stretch_column=0,
        )
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.doubleClicked.connect(self._open)
        splitter.addWidget(self.table)

        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        self.title = QLabel("Select a document")
        self.title.setObjectName("pageTitle")
        self.meta = QLabel("")
        self.meta.setObjectName("muted")
        self.path = QLabel("")
        self.path.setWordWrap(True)
        self.notes = QTextEdit()
        self.notes.setReadOnly(True)
        self.links = QTextEdit()
        self.links.setReadOnly(True)
        for widget in (
            self.title,
            self.meta,
            self.path,
            QLabel("Notes"),
            self.notes,
            QLabel("Linked Records"),
            self.links,
        ):
            detail_layout.addWidget(widget)
        actions = QHBoxLayout()
        for label, handler in [
            ("Open", self._open),
            ("Open Folder", self._open_folder),
            ("Archive / Restore", self._toggle_archive),
            ("Delete", self._delete),
        ]:
            button = QPushButton(label)
            if label == "Delete":
                button.setObjectName("danger")
            button.clicked.connect(handler)
            actions.addWidget(button)
        actions.addStretch()
        detail_layout.addLayout(actions)
        detail_layout.addStretch()
        splitter.addWidget(detail)
        splitter.setSizes([850, 430])
        root.addWidget(splitter, 1)

        self._debounce = DebouncedCall(self.refresh, parent=self)
        self.search.textChanged.connect(self._debounce.schedule)
        self.document_type.currentIndexChanged.connect(self.refresh)
        self.status.currentIndexChanged.connect(self.refresh)
        self.refresh()

    def on_activated(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        current_type = self.document_type.currentData()
        self.rows = self.service.documents(
            self.search.text(),
            str(current_type) if current_type else None,
            self.status.currentData(),
        )
        types = self.service.document_types()
        self.document_type.blockSignals(True)
        self.document_type.clear()
        self.document_type.addItem("All document types", None)
        for value in types:
            self.document_type.addItem(value.replace("_", " ").title(), value)
        self.document_type.setCurrentIndex(max(0, self.document_type.findData(current_type)))
        self.document_type.blockSignals(False)
        self.table.setRowCount(len(self.rows))
        for row_index, row in enumerate(self.rows):
            values = [
                row.title,
                row.document_type.replace("_", " ").title(),
                row.file_name,
                _file_size(row.size_bytes),
                row.created_at.astimezone().strftime("%b %d, %Y"),
                str(row.link_count),
                row.status.replace("_", " ").title(),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, row.id)
                self.table.setItem(row_index, column, item)
        if self.rows:
            self.table.selectRow(0)
        else:
            self._clear()

    def _selected_id(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _selection_changed(self) -> None:
        document_id = self._selected_id()
        if not document_id:
            self._clear()
            return
        try:
            self.current = self.service.document(document_id)
        except ValidationError as exc:
            QMessageBox.warning(self, "Documents", str(exc))
            return
        current = self.current
        self.title.setText(current.title)
        self.meta.setText(
            f"{current.document_type.replace('_', ' ').title()} • "
            f"{_file_size(current.size_bytes)} • {current.status.title()}"
        )
        self.path.setText(str(current.storage_path))
        self.notes.setPlainText(str(current.metadata.get("notes", "")))
        self.links.setPlainText(
            "\n".join(
                f"{entity_type.replace('_', ' ').title()} {entity_id} ({relationship.replace('_', ' ')})"
                for entity_type, entity_id, relationship in current.links
            )
            or "Not linked to another record."
        )

    def _upload(self, source: Path | None = None) -> None:
        dialog = UploadDialog(self, source)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.service.upload(dialog.request())
            self.refresh()
        except (ValidationError, OSError) as exc:
            QMessageBox.warning(self, "Upload Document", str(exc))

    def _open(self) -> None:
        if self.current is None:
            return
        if not self.current.storage_path.exists():
            QMessageBox.warning(self, "Document", "The stored file could not be found.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.current.storage_path)))

    def _open_folder(self) -> None:
        if self.current is None:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.current.storage_path.parent)))

    def _toggle_archive(self) -> None:
        if self.current is None:
            return
        status = "active" if self.current.status == "archived" else "archived"
        try:
            self.service.set_status(self.current.id, status)
            self.refresh()
        except ValidationError as exc:
            QMessageBox.warning(self, "Document", str(exc))

    def _delete(self) -> None:
        if self.current is None:
            return
        if (
            QMessageBox.warning(
                self,
                "Delete Document",
                "Remove this document from normal views?\n\n"
                "The physical file is retained for audit and recovery.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            self.service.delete(self.current.id)
            self.refresh()
        except ValidationError as exc:
            QMessageBox.warning(self, "Document", str(exc))

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls() and any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # type: ignore[override]
        files = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if files:
            self._upload(files[0])
            event.acceptProposedAction()

    def _clear(self) -> None:
        self.current = None
        self.title.setText("Select a document")
        self.meta.clear()
        self.path.clear()
        self.notes.clear()
        self.links.clear()
