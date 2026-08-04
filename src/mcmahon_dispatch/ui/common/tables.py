from __future__ import annotations

from collections.abc import Iterable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
)


def configure_data_table(
    table: QTableWidget,
    headers: Sequence[str],
    *,
    stretch_column: int | None = None,
    single_selection: bool = True,
) -> None:
    """Apply the application's standard read-only table behavior."""

    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(list(headers))
    table.setAlternatingRowColors(True)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(
        QAbstractItemView.SelectionMode.SingleSelection
        if single_selection
        else QAbstractItemView.SelectionMode.ExtendedSelection
    )
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setHighlightSections(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    if stretch_column is not None:
        table.horizontalHeader().setSectionResizeMode(
            stretch_column,
            QHeaderView.ResizeMode.Stretch,
        )


def populate_table(
    table: QTableWidget,
    rows: Iterable[Sequence[str]],
    *,
    record_ids: Sequence[str] | None = None,
    id_column: int = 0,
) -> None:
    materialized = list(rows)
    sorting_enabled = table.isSortingEnabled()
    table.setSortingEnabled(False)
    table.setUpdatesEnabled(False)
    try:
        table.clearContents()
        table.setRowCount(len(materialized))
        for row_index, values in enumerate(materialized):
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                if record_ids is not None and column_index == id_column:
                    item.setData(Qt.ItemDataRole.UserRole, record_ids[row_index])
                table.setItem(row_index, column_index, item)
    finally:
        table.setUpdatesEnabled(True)
        table.setSortingEnabled(sorting_enabled)


def selected_record_id(table: QTableWidget, *, id_column: int = 0) -> str | None:
    row = table.currentRow()
    if row < 0:
        return None
    item = table.item(row, id_column)
    if item is None:
        return None
    value = item.data(Qt.ItemDataRole.UserRole)
    return str(value) if value not in (None, "") else None
