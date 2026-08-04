from __future__ import annotations

from collections.abc import Iterable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableView


def configure_table_view(
    table: QTableView,
    model: QStandardItemModel,
    headers: Sequence[str],
    *,
    stretch_last: bool = True,
    sorting: bool = True,
) -> None:
    """Apply consistent behavior to model-backed report and management tables."""

    model.setColumnCount(len(headers))
    model.setHorizontalHeaderLabels(list(headers))
    table.setModel(model)
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSortingEnabled(sorting)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setHighlightSections(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    table.horizontalHeader().setStretchLastSection(stretch_last)


def replace_model_rows(
    table: QTableView,
    model: QStandardItemModel,
    rows: Iterable[Sequence[QStandardItem]],
) -> None:
    """Replace model contents without repainting and resorting once per inserted row."""

    sorting_enabled = table.isSortingEnabled()
    table.setSortingEnabled(False)
    table.setUpdatesEnabled(False)
    try:
        model.removeRows(0, model.rowCount())
        for row in rows:
            model.appendRow(list(row))
    finally:
        table.setUpdatesEnabled(True)
        table.setSortingEnabled(sorting_enabled)
        table.viewport().update()


def model_record_id(
    table: QTableView,
    model: QStandardItemModel,
    *,
    column: int = 0,
) -> str | None:
    index = table.currentIndex()
    if not index.isValid():
        return None
    item = model.item(index.row(), column)
    if item is None:
        return None
    value = item.data(Qt.ItemDataRole.UserRole)
    return str(value) if value not in (None, "") else None
