from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPaintEvent, QPen, QResizeEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from mcmahon_dispatch.core.formatting import format_currency
from mcmahon_dispatch.repositories.reporting_repository import RankedRow, TrendRow
from mcmahon_dispatch.services.reporting_service import ReportData, ReportingService
from mcmahon_dispatch.ui.common import PageHeader, configure_data_table
from mcmahon_dispatch.ui.common.tables import populate_table


class LineChart(QWidget):
    """Small dependency-free trend chart that supports positive and negative values."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(240)
        self._data: list[TrendRow] = []
        self._mode = "revenue"

    def set_data(self, rows: Iterable[TrendRow], mode: str) -> None:
        self._data = list(rows)
        self._mode = mode
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        plot = QRectF(self.rect().adjusted(54, 18, -18, -38))
        grid_color = self.palette().mid().color()
        text_color = self.palette().text().color()
        accent_color = self.palette().highlight().color()

        painter.setPen(QPen(grid_color, 1))
        painter.drawRoundedRect(plot, 4, 4)

        values = [float(getattr(row, f"{self._mode}_cents")) / 100 for row in self._data]
        if not values:
            painter.setPen(text_color)
            painter.drawText(plot, Qt.AlignmentFlag.AlignCenter, "No report data for this period")
            return

        minimum = min(min(values), 0.0)
        maximum = max(max(values), 0.0)
        span = max(maximum - minimum, 1.0)

        zero_y = plot.bottom() - ((0.0 - minimum) / span * plot.height())
        painter.setPen(QPen(grid_color, 1, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(plot.left(), zero_y), QPointF(plot.right(), zero_y))

        points: list[QPointF] = []
        for index, value in enumerate(values):
            x = plot.left() + (plot.width() * index / max(1, len(values) - 1))
            y = plot.bottom() - ((value - minimum) / span * plot.height())
            points.append(QPointF(x, y))

        painter.setPen(QPen(accent_color, 3))
        for first, second in zip(points, points[1:]):
            painter.drawLine(first, second)

        painter.setBrush(accent_color)
        for point, row in zip(points, self._data):
            painter.drawEllipse(point, 3.5, 3.5)
            painter.setPen(text_color)
            painter.drawText(
                int(point.x() - 28),
                int(plot.bottom() + 8),
                56,
                18,
                Qt.AlignmentFlag.AlignCenter,
                row.period[5:] if len(row.period) >= 7 else row.period,
            )
            painter.setPen(QPen(accent_color, 3))


class MetricCard(QFrame):
    def __init__(self, title: str) -> None:
        super().__init__()
        self.setObjectName("metricCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 13, 16, 13)
        layout.setSpacing(4)

        label = QLabel(title)
        label.setObjectName("muted")
        self.value = QLabel("$0.00")
        self.value.setObjectName("metricValue")
        layout.addWidget(label)
        layout.addWidget(self.value)


class ReportingPage(QWidget):
    def __init__(self, service: ReportingService) -> None:
        super().__init__()
        self.service = service
        self.data: ReportData | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 20)
        root.setSpacing(14)

        self.range = QComboBox()
        self.range.addItems(["This Month", "Last Month", "This Year", "Last 12 Months", "Custom"])
        self.range.currentTextChanged.connect(self._apply_range)

        self.from_date = QDateEdit()
        self.from_date.setCalendarPopup(True)
        self.from_date.setDisplayFormat("MMM d, yyyy")
        self.to_date = QDateEdit()
        self.to_date.setCalendarPopup(True)
        self.to_date.setDisplayFormat("MMM d, yyyy")

        actions = self._build_actions()
        root.addWidget(
            PageHeader(
                "Reporting",
                "Review revenue, profit, mileage, fuel, expenses, customers, and drivers.",
                actions,
            )
        )

        self.metrics_widget = QWidget()
        self.metrics_layout = QGridLayout(self.metrics_widget)
        self.metrics_layout.setContentsMargins(0, 0, 0, 0)
        self.metrics_layout.setSpacing(12)
        self.cards: dict[str, MetricCard] = {}
        for key, label in (
            ("revenue", "Revenue"),
            ("profit", "Profit"),
            ("ppm", "Profit per mile"),
            ("fuel", "Fuel"),
            ("expenses", "Expenses"),
            ("miles", "Miles"),
            ("jobs", "Jobs"),
        ):
            card = MetricCard(label)
            self.cards[key] = card
        self._layout_metrics(columns=4)
        root.addWidget(self.metrics_widget)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self._build_tabs()

        today = date.today()
        self.from_date.setDate(today.replace(day=1))
        self.to_date.setDate(today)
        self._apply_range("This Month")

    def _build_actions(self) -> QWidget:
        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        refresh = QPushButton("Refresh")
        refresh.setObjectName("primary")
        refresh.clicked.connect(self.refresh)
        csv_button = QPushButton("CSV")
        csv_button.clicked.connect(self._csv)
        excel_button = QPushButton("Excel")
        excel_button.clicked.connect(self._xlsx)
        pdf_button = QPushButton("PDF")
        pdf_button.clicked.connect(self._pdf)

        for widget in (
            self.range,
            self.from_date,
            self.to_date,
            refresh,
            csv_button,
            excel_button,
            pdf_button,
        ):
            layout.addWidget(widget)
        return holder

    def _build_tabs(self) -> None:
        overview = QWidget()
        overview_layout = QVBoxLayout(overview)
        overview_layout.setContentsMargins(10, 10, 10, 10)
        overview_layout.setSpacing(12)

        self.charts_widget = QWidget()
        self.charts_layout = QGridLayout(self.charts_widget)
        self.charts_layout.setContentsMargins(0, 0, 0, 0)
        self.charts_layout.setSpacing(12)
        self.revenue_chart = LineChart()
        self.profit_chart = LineChart()
        self.chart_boxes = [
            self._chart_box("Monthly Revenue", self.revenue_chart),
            self._chart_box("Monthly Profit", self.profit_chart),
        ]
        self._layout_charts(columns=2)
        overview_layout.addWidget(self.charts_widget)

        self.monthly = self._table(
            ("Month", "Revenue", "Profit", "Fuel", "Expenses", "Miles", "Jobs")
        )
        overview_layout.addWidget(self.monthly, 1)
        self.tabs.addTab(overview, "Monthly")

        self.yearly = self._table(
            ("Year", "Revenue", "Profit", "Fuel", "Expenses", "Miles", "Jobs")
        )
        self.tabs.addTab(self._wrapped(self.yearly), "Yearly")

        ranked_headers = (
            "Customer",
            "Revenue",
            "Cost",
            "Profit",
            "Miles",
            "Profit / Mile",
            "Jobs",
        )
        self.customers = self._table(ranked_headers)
        self.tabs.addTab(self._wrapped(self.customers), "By Customer")

        self.drivers = self._table(("Driver", *ranked_headers[1:]))
        self.tabs.addTab(self._wrapped(self.drivers), "By Driver")

        self.expenses = self._table(("Expense Category", "Amount"))
        self.tabs.addTab(self._wrapped(self.expenses), "Expenses")

    @staticmethod
    def _chart_box(title: str, chart: QWidget) -> QFrame:
        box = QFrame()
        box.setObjectName("sectionCard")
        layout = QVBoxLayout(box)
        heading = QLabel(title)
        heading.setObjectName("cardTitle")
        layout.addWidget(heading)
        layout.addWidget(chart)
        return box

    @staticmethod
    def _wrapped(widget: QWidget) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(widget)
        return holder

    @staticmethod
    def _table(headers: Sequence[str]) -> QTableWidget:
        table = QTableWidget()
        configure_data_table(table, headers, stretch_column=0)
        table.setSortingEnabled(True)
        return table

    def _apply_range(self, text: str) -> None:
        today = date.today()
        if text == "This Month":
            start, end = today.replace(day=1), today
        elif text == "Last Month":
            first_of_month = today.replace(day=1)
            end = date.fromordinal(first_of_month.toordinal() - 1)
            start = end.replace(day=1)
        elif text == "This Year":
            start, end = date(today.year, 1, 1), today
        elif text == "Last 12 Months":
            try:
                start = today.replace(year=today.year - 1)
            except ValueError:
                start = today.replace(year=today.year - 1, day=28)
            end = today
        else:
            return

        self.from_date.setDate(start)
        self.to_date.setDate(end)
        self.refresh()

    def on_activated(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        try:
            self.data = self.service.load(
                self.from_date.date().toPython(),
                self.to_date.date().toPython(),
            )
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Reporting", str(exc))
            return

        summary = self.data.summary
        values = {
            "revenue": format_currency(summary.revenue_cents),
            "profit": format_currency(summary.profit_cents),
            "ppm": format_currency(summary.profit_per_mile_cents),
            "fuel": format_currency(summary.fuel_cents),
            "expenses": format_currency(summary.expenses_cents),
            "miles": f"{summary.miles:,.1f}",
            "jobs": f"{summary.jobs:,}",
        }
        for key, value in values.items():
            self.cards[key].value.setText(value)

        self.revenue_chart.set_data(self.data.trend, "revenue")
        self.profit_chart.set_data(self.data.trend, "profit")
        populate_table(self.monthly, self._trend_rows(self.data.trend))
        populate_table(self.yearly, self._trend_rows(self.data.yearly))
        populate_table(self.customers, self._ranked_rows(self.data.customers))
        populate_table(self.drivers, self._ranked_rows(self.data.drivers))
        populate_table(
            self.expenses,
            ((row.category, format_currency(row.amount_cents)) for row in self.data.expenses),
        )

    @staticmethod
    def _trend_rows(rows: Iterable[TrendRow]) -> Iterable[Sequence[str]]:
        return (
            (
                row.period,
                format_currency(row.revenue_cents),
                format_currency(row.profit_cents),
                format_currency(row.fuel_cents),
                format_currency(row.expenses_cents),
                f"{row.miles:,.1f}",
                str(row.jobs),
            )
            for row in rows
        )

    @staticmethod
    def _ranked_rows(rows: Iterable[RankedRow]) -> Iterable[Sequence[str]]:
        return (
            (
                row.name,
                format_currency(row.revenue_cents),
                format_currency(row.cost_cents),
                format_currency(row.profit_cents),
                f"{row.miles:,.1f}",
                format_currency(row.profit_per_mile_cents),
                str(row.jobs),
            )
            for row in rows
        )

    def _choose(self, suffix: str, label: str) -> Path | None:
        filename = (
            f'McMahon-Report-{self.from_date.date().toString("yyyy-MM-dd")}-'
            f'{self.to_date.date().toString("yyyy-MM-dd")}.{suffix}'
        )
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            f"Export {label}",
            filename,
            f"{label} (*.{suffix})",
        )
        return Path(path) if path else None

    def _csv(self) -> None:
        self._export("csv", "CSV file", self.service.export_csv)

    def _xlsx(self) -> None:
        self._export("xlsx", "Excel workbook", self.service.export_excel)

    def _pdf(self) -> None:
        self._export("pdf", "PDF document", self.service.export_pdf)

    def _export(self, suffix: str, label: str, exporter: Any) -> None:
        if self.data is None:
            self.refresh()
        if self.data is None:
            return

        path = self._choose(suffix, label)
        if path is None:
            return
        try:
            exporter(self.data, path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Reporting", str(exc))
            return
        QMessageBox.information(self, "Reporting", f"{label} saved to:\n{path}")

    def _layout_metrics(self, columns: int) -> None:
        for index, card in enumerate(self.cards.values()):
            self.metrics_layout.addWidget(card, index // columns, index % columns)

    def _layout_charts(self, columns: int) -> None:
        for index, box in enumerate(self.chart_boxes):
            self.charts_layout.addWidget(box, index // columns, index % columns)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._layout_metrics(columns=2 if self.width() < 980 else 4)
        self._layout_charts(columns=1 if self.width() < 1120 else 2)
