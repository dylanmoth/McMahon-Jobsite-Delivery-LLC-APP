from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Sequence

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.orm import Session, sessionmaker

from mcmahon_dispatch.core.formatting import format_currency
from mcmahon_dispatch.repositories.reporting_repository import (
    ExpenseRow,
    RankedRow,
    ReportingRepository,
    SummaryTotals,
    TrendRow,
)

if TYPE_CHECKING:
    import xlsxwriter


DARK = colors.HexColor("#111827")
BORDER = colors.HexColor("#CBD5E1")
ROW_ALT = colors.HexColor("#F8FAFC")


def money(cents: int) -> str:
    """Backward-compatible public formatter used by existing integrations and tests."""

    return format_currency(cents)


@dataclass(frozen=True, slots=True)
class ReportData:
    date_from: date
    date_to: date
    summary: SummaryTotals
    trend: list[TrendRow]
    yearly: list[TrendRow]
    customers: list[RankedRow]
    drivers: list[RankedRow]
    expenses: list[ExpenseRow]


class ReportingService:
    """Read financial reporting data and export it in customer-ready formats."""

    TREND_HEADERS = ("Period", "Revenue", "Profit", "Fuel", "Expenses", "Miles", "Jobs")
    RANKED_HEADERS = (
        "Name",
        "Revenue",
        "Cost",
        "Profit",
        "Miles",
        "Profit per mile",
        "Jobs",
    )

    def __init__(
        self,
        factory: sessionmaker[Session],
        organization_id: str,
        documents_dir: Path,
    ) -> None:
        self.factory = factory
        self.organization_id = organization_id
        self.documents_dir = documents_dir

    def load(self, date_from: date, date_to: date) -> ReportData:
        if date_to < date_from:
            raise ValueError("The ending date cannot be before the starting date.")

        with self.factory() as session:
            repository = ReportingRepository(session, self.organization_id)
            return ReportData(
                date_from=date_from,
                date_to=date_to,
                summary=repository.summary(date_from, date_to),
                trend=repository.monthly_trend(date_from, date_to),
                yearly=repository.yearly_trend(date_from, date_to),
                customers=repository.by_customer(date_from, date_to),
                drivers=repository.by_driver(date_from, date_to),
                expenses=repository.expense_breakdown(date_from, date_to),
            )

    def export_csv(self, data: ReportData, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(["McMahon Dispatch Reporting"])
            writer.writerow(["Period", data.date_from.isoformat(), data.date_to.isoformat()])
            self._write_csv_summary(writer, data.summary)
            self._write_csv_trend(writer, "Monthly", data.trend)
            self._write_csv_trend(writer, "Year", data.yearly)
            self._write_csv_ranked(writer, "Customer", data.customers)
            self._write_csv_ranked(writer, "Driver", data.drivers)
        return path

    def export_excel(self, data: ReportData, path: Path) -> Path:
        import xlsxwriter

        path.parent.mkdir(parents=True, exist_ok=True)
        workbook = xlsxwriter.Workbook(path)
        try:
            formats = self._excel_formats(workbook)
            self._write_excel_summary(workbook, data, formats)
            self._write_excel_ranked(workbook, "Customers", data.customers, formats)
            self._write_excel_ranked(workbook, "Drivers", data.drivers, formats)
            self._write_excel_trend(workbook, "Monthly", data.trend, formats)
            self._write_excel_trend(workbook, "Yearly", data.yearly, formats)
        finally:
            workbook.close()
        return path

    def export_pdf(self, data: ReportData, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        styles = getSampleStyleSheet()
        document = SimpleDocTemplate(
            str(path),
            pagesize=landscape(letter),
            leftMargin=0.45 * inch,
            rightMargin=0.45 * inch,
            topMargin=0.45 * inch,
            bottomMargin=0.45 * inch,
            title="McMahon Dispatch Report",
        )

        story = [
            Paragraph("McMahon Dispatch Report", styles["Title"]),
            Paragraph(
                f"{data.date_from:%b %d, %Y} - {data.date_to:%b %d, %Y}",
                styles["Heading2"],
            ),
            Spacer(1, 10),
            self._pdf_summary_table(data.summary),
            Spacer(1, 14),
        ]
        self._append_ranked_pdf_section(story, styles, "Profit by Customer", data.customers)
        self._append_ranked_pdf_section(story, styles, "Profit by Driver", data.drivers)
        document.build(story)
        return path

    @staticmethod
    def _write_csv_summary(writer: csv.writer, summary: SummaryTotals) -> None:
        writer.writerow([])
        writer.writerow(["Metric", "Value"])
        rows = (
            ("Revenue", money(summary.revenue_cents)),
            ("Profit", money(summary.profit_cents)),
            ("Miles", f"{summary.miles:,.1f}"),
            ("Profit per mile", money(summary.profit_per_mile_cents)),
            ("Fuel", money(summary.fuel_cents)),
            ("Expenses", money(summary.expenses_cents)),
            ("Jobs", summary.jobs),
        )
        writer.writerows(rows)

    @classmethod
    def _write_csv_trend(
        cls,
        writer: csv.writer,
        first_header: str,
        rows: Iterable[TrendRow],
    ) -> None:
        writer.writerow([])
        writer.writerow([first_header, *cls.TREND_HEADERS[1:]])
        writer.writerows(
            (
                row.period,
                money(row.revenue_cents),
                money(row.profit_cents),
                money(row.fuel_cents),
                money(row.expenses_cents),
                f"{row.miles:.1f}",
                row.jobs,
            )
            for row in rows
        )

    @classmethod
    def _write_csv_ranked(
        cls,
        writer: csv.writer,
        first_header: str,
        rows: Iterable[RankedRow],
    ) -> None:
        writer.writerow([])
        writer.writerow([first_header, *cls.RANKED_HEADERS[1:]])
        writer.writerows(
            (
                row.name,
                money(row.revenue_cents),
                money(row.cost_cents),
                money(row.profit_cents),
                f"{row.miles:.1f}",
                money(row.profit_per_mile_cents),
                row.jobs,
            )
            for row in rows
        )

    @staticmethod
    def _excel_formats(workbook: xlsxwriter.Workbook) -> dict[str, object]:
        return {
            "header": workbook.add_format(
                {
                    "bold": True,
                    "bg_color": "#111827",
                    "font_color": "#FFFFFF",
                    "border": 1,
                }
            ),
            "money": workbook.add_format({"num_format": "$#,##0.00", "border": 1}),
            "number": workbook.add_format({"num_format": "#,##0.0", "border": 1}),
            "integer": workbook.add_format({"num_format": "#,##0", "border": 1}),
            "cell": workbook.add_format({"border": 1}),
            "title": workbook.add_format({"bold": True, "font_size": 18, "font_color": "#F97316"}),
        }

    @staticmethod
    def _write_excel_summary(
        workbook: xlsxwriter.Workbook,
        data: ReportData,
        formats: dict[str, object],
    ) -> None:
        sheet = workbook.add_worksheet("Summary")
        sheet.write("A1", "McMahon Dispatch Report", formats["title"])
        sheet.write("A2", f"{data.date_from:%b %d, %Y} - {data.date_to:%b %d, %Y}")
        sheet.write_row(3, 0, ["Metric", "Value"], formats["header"])

        metrics = (
            ("Revenue", data.summary.revenue_cents / 100, "money"),
            ("Profit", data.summary.profit_cents / 100, "money"),
            ("Profit per mile", data.summary.profit_per_mile_cents / 100, "money"),
            ("Fuel", data.summary.fuel_cents / 100, "money"),
            ("Expenses", data.summary.expenses_cents / 100, "money"),
            ("Miles", data.summary.miles, "number"),
            ("Jobs", data.summary.jobs, "integer"),
        )
        for row_index, (name, value, format_name) in enumerate(metrics, 4):
            sheet.write(row_index, 0, name, formats["cell"])
            sheet.write(row_index, 1, value, formats[format_name])

        sheet.set_column("A:A", 24)
        sheet.set_column("B:B", 18)

    @classmethod
    def _write_excel_ranked(
        cls,
        workbook: xlsxwriter.Workbook,
        name: str,
        rows: Sequence[RankedRow],
        formats: dict[str, object],
    ) -> None:
        sheet = workbook.add_worksheet(name)
        sheet.write_row(0, 0, cls.RANKED_HEADERS, formats["header"])
        for row_index, row in enumerate(rows, 1):
            sheet.write(row_index, 0, row.name, formats["cell"])
            sheet.write(row_index, 1, row.revenue_cents / 100, formats["money"])
            sheet.write(row_index, 2, row.cost_cents / 100, formats["money"])
            sheet.write(row_index, 3, row.profit_cents / 100, formats["money"])
            sheet.write(row_index, 4, row.miles, formats["number"])
            sheet.write(row_index, 5, row.profit_per_mile_cents / 100, formats["money"])
            sheet.write(row_index, 6, row.jobs, formats["integer"])

        sheet.set_column("A:A", 30)
        sheet.set_column("B:G", 16)
        sheet.autofilter(0, 0, max(1, len(rows)), len(cls.RANKED_HEADERS) - 1)
        sheet.freeze_panes(1, 0)

    @classmethod
    def _write_excel_trend(
        cls,
        workbook: xlsxwriter.Workbook,
        name: str,
        rows: Sequence[TrendRow],
        formats: dict[str, object],
    ) -> None:
        sheet = workbook.add_worksheet(name)
        sheet.write_row(0, 0, cls.TREND_HEADERS, formats["header"])
        for row_index, row in enumerate(rows, 1):
            sheet.write(row_index, 0, row.period, formats["cell"])
            sheet.write(row_index, 1, row.revenue_cents / 100, formats["money"])
            sheet.write(row_index, 2, row.profit_cents / 100, formats["money"])
            sheet.write(row_index, 3, row.fuel_cents / 100, formats["money"])
            sheet.write(row_index, 4, row.expenses_cents / 100, formats["money"])
            sheet.write(row_index, 5, row.miles, formats["number"])
            sheet.write(row_index, 6, row.jobs, formats["integer"])

        sheet.set_column("A:A", 14)
        sheet.set_column("B:G", 16)
        sheet.freeze_panes(1, 0)

    @staticmethod
    def _pdf_summary_table(summary: SummaryTotals) -> Table:
        rows = [
            ["Revenue", "Profit", "Profit / Mile", "Fuel", "Expenses", "Miles", "Jobs"],
            [
                money(summary.revenue_cents),
                money(summary.profit_cents),
                money(summary.profit_per_mile_cents),
                money(summary.fuel_cents),
                money(summary.expenses_cents),
                f"{summary.miles:,.1f}",
                str(summary.jobs),
            ],
        ]
        table = Table(rows, colWidths=[1.35 * inch] * 7)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), DARK),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ]
            )
        )
        return table

    @staticmethod
    def _append_ranked_pdf_section(
        story: list[object],
        styles: object,
        title: str,
        rows: Sequence[RankedRow],
    ) -> None:
        story.append(Paragraph(title, styles["Heading2"]))
        table_rows = [["Name", "Revenue", "Cost", "Profit", "Miles", "Profit / Mile", "Jobs"]]
        table_rows.extend(
            [
                row.name,
                money(row.revenue_cents),
                money(row.cost_cents),
                money(row.profit_cents),
                f"{row.miles:,.1f}",
                money(row.profit_per_mile_cents),
                str(row.jobs),
            ]
            for row in rows[:25]
        )
        table = Table(
            table_rows,
            colWidths=[
                2.6 * inch,
                1.1 * inch,
                1.1 * inch,
                1.1 * inch,
                0.8 * inch,
                1.1 * inch,
                0.55 * inch,
            ],
            repeatRows=1,
        )
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), DARK),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ROW_ALT]),
                ]
            )
        )
        story.extend([table, Spacer(1, 12)])
