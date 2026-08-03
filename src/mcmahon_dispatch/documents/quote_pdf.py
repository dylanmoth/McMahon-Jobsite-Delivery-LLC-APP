from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from mcmahon_dispatch.services.pricing_engine import ChargeLine

ORANGE = colors.HexColor("#F97316")
DARK = colors.HexColor("#111827")
SLATE = colors.HexColor("#475569")
LIGHT = colors.HexColor("#F3F4F6")
GREEN = colors.HexColor("#15803D")

DEFAULT_TERMS = (
    "Pricing is subject to confirmation of dimensions, weight, material, readiness, "
    "vehicle availability, safe loading, and access. Customers normally place and pay "
    "for supplier orders and authorize pickup. Hazardous materials are prohibited. "
    "Trash service is limited to identified non-hazardous contractor bags and excludes "
    "landfill or transfer-station trips. Extensive loading, unloading, placement, stairs, "
    "or difficult access may require additional labor or a custom quote."
)


@dataclass(frozen=True, slots=True)
class QuotePdfData:
    quote_number: str
    generated_at: datetime
    expires_at: datetime | None
    status: str
    customer_name: str
    contact_name: str
    contact_phone: str
    contact_email: str
    supplier_name: str
    supplier_address: str
    order_number: str
    jobsite_address: str
    site_contact: str
    requested_window: str
    service_description: str
    materials: str
    customer_notes: str
    charges: tuple[ChargeLine, ...]
    total_cents: int
    terms: str = DEFAULT_TERMS


@dataclass(frozen=True, slots=True)
class CallSheetPdfData:
    created_at: datetime
    company_contact: str
    phone: str
    email: str
    supplier_address: str
    jobsite_address: str
    materials: str
    dimensions_text: str
    weight_text: str
    pickup_stops: str
    order_ready: str
    same_day: str
    psl_status: str
    miles_text: str
    wait_text: str
    trash_text: str
    vehicle_text: str
    other_client: str
    general_notes: str


class QuotePdfGenerator:
    def __init__(self, logo_path: Path | None = None) -> None:
        self.logo_path = logo_path
        base = getSampleStyleSheet()
        self.title = ParagraphStyle(
            "Title", parent=base["Title"], fontName="Helvetica-Bold", fontSize=22,
            leading=25, textColor=DARK, alignment=TA_RIGHT, spaceAfter=0,
        )
        self.heading = ParagraphStyle(
            "Heading", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=11,
            leading=14, textColor=DARK, spaceBefore=8, spaceAfter=6,
        )
        self.body = ParagraphStyle(
            "Body", parent=base["BodyText"], fontName="Helvetica", fontSize=9,
            leading=12, textColor=DARK,
        )
        self.small = ParagraphStyle(
            "Small", parent=self.body, fontSize=7.5, leading=10, textColor=SLATE,
        )
        self.right = ParagraphStyle(
            "Right", parent=self.body, alignment=TA_RIGHT,
        )

    def build_quote(self, destination: Path, data: QuotePdfData) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        doc = SimpleDocTemplate(
            str(destination), pagesize=letter, rightMargin=0.55 * inch,
            leftMargin=0.55 * inch, topMargin=0.45 * inch, bottomMargin=0.5 * inch,
            title=f"Quote {data.quote_number}", author="McMahon Jobsite Delivery LLC",
        )
        story: list[object] = []
        logo = self._logo(1.55 * inch, 0.72 * inch)
        quote_header = [
            Paragraph("QUOTE", self.title),
            Paragraph(f"<b>{self._escape(data.quote_number)}</b>", self.right),
            Paragraph(
                f"Issued {data.generated_at.astimezone():%B %d, %Y}<br/>"
                + (f"Expires {data.expires_at.astimezone():%B %d, %Y}<br/>" if data.expires_at else "")
                + f"Status: {self._escape(data.status.replace('_', ' ').title())}",
                self.right,
            ),
        ]
        header = Table([[logo, quote_header]], colWidths=[2.4 * inch, 4.45 * inch])
        header.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.extend([header, Spacer(1, 8), HRFlowable(width="100%", thickness=2, color=ORANGE), Spacer(1, 10)])

        bill_to = self._detail_block(
            "PREPARED FOR",
            [data.customer_name, data.contact_name, data.contact_phone, data.contact_email],
        )
        company = self._detail_block(
            "FROM",
            [
                "McMahon Jobsite Delivery LLC",
                "Port St. Lucie, Florida",
                "Construction-material and jobsite logistics",
            ],
        )
        info = Table([[bill_to, company]], colWidths=[3.45 * inch, 3.4 * inch])
        info.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ]))
        story.extend([info, Spacer(1, 10)])

        route_rows = [
            [Paragraph("PICKUP", self.heading), Paragraph("DELIVERY", self.heading)],
            [
                Paragraph(self._join_lines([data.supplier_name, data.supplier_address, f"Order: {data.order_number}" if data.order_number else ""]), self.body),
                Paragraph(self._join_lines([data.jobsite_address, data.site_contact, data.requested_window]), self.body),
            ],
        ]
        route_table = Table(route_rows, colWidths=[3.45 * inch, 3.4 * inch])
        route_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), LIGHT),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        story.extend([route_table, Spacer(1, 12)])

        story.append(Paragraph("SERVICE", self.heading))
        story.append(Paragraph(self._escape(data.service_description or "Jobsite delivery service"), self.body))
        if data.materials:
            story.extend([Spacer(1, 4), Paragraph(f"<b>Materials:</b> {self._escape(data.materials)}", self.body)])
        story.append(Spacer(1, 10))

        charge_rows: list[list[object]] = [[
            Paragraph("Description", self.body), Paragraph("Qty", self.right),
            Paragraph("Rate", self.right), Paragraph("Amount", self.right),
        ]]
        for line in data.charges:
            if not line.customer_visible:
                continue
            charge_rows.append([
                Paragraph(self._escape(line.description), self.body),
                Paragraph(self._quantity(line.quantity), self.right),
                Paragraph(self._money(line.rate_cents), self.right),
                Paragraph(self._money(line.total_cents), self.right),
            ])
        charge_rows.append(["", "", Paragraph("<b>TOTAL</b>", self.right), Paragraph(f"<b>{self._money(data.total_cents)}</b>", self.right)])
        charges = Table(charge_rows, colWidths=[3.85 * inch, 0.7 * inch, 1.05 * inch, 1.25 * inch], repeatRows=1)
        charges.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), DARK),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -2), 0.35, colors.HexColor("#CBD5E1")),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#FFF7ED")),
            ("LINEABOVE", (0, -1), (-1, -1), 1.5, ORANGE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        story.append(charges)

        if data.customer_notes:
            story.extend([
                Spacer(1, 12), Paragraph("CUSTOMER NOTES", self.heading),
                Paragraph(self._escape(data.customer_notes).replace("\n", "<br/>"), self.body),
            ])
        story.extend([
            Spacer(1, 13),
            KeepTogether([
                Paragraph("TERMS &amp; EXCLUSIONS", self.heading),
                Paragraph(self._escape(data.terms), self.small),
            ]),
            Spacer(1, 12),
            HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#CBD5E1")),
            Spacer(1, 6),
            Paragraph(
                "Thank you for choosing McMahon Jobsite Delivery. This quote contains no sales tax by default.",
                ParagraphStyle("Thanks", parent=self.small, textColor=GREEN),
            ),
        ])
        doc.build(story)
        return destination

    def build_call_sheet(self, destination: Path, data: CallSheetPdfData) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        doc = SimpleDocTemplate(
            str(destination), pagesize=letter, rightMargin=0.55 * inch,
            leftMargin=0.55 * inch, topMargin=0.45 * inch, bottomMargin=0.5 * inch,
            title="Contractor Call Sheet", author="McMahon Jobsite Delivery LLC",
        )
        story: list[object] = []
        header = Table(
            [[self._logo(1.45 * inch, 0.68 * inch), Paragraph("CONTRACTOR CALL SHEET", self.title)]],
            colWidths=[2.1 * inch, 4.75 * inch],
        )
        header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 0), (1, 0), "RIGHT")]))
        story.extend([
            header, Spacer(1, 8), HRFlowable(width="100%", thickness=2, color=ORANGE),
            Spacer(1, 8), Paragraph(f"Captured {data.created_at.astimezone():%B %d, %Y at %I:%M %p}", self.small), Spacer(1, 8),
        ])
        rows = [
            ("Company / contact", data.company_contact), ("Phone", data.phone), ("Email", data.email),
            ("Supplier / store", data.supplier_address), ("Jobsite", data.jobsite_address),
            ("Materials", data.materials), ("Dimensions", data.dimensions_text), ("Weight / overweight", data.weight_text),
            ("Pickup stops", data.pickup_stops), ("Order ready", data.order_ready), ("Same-day", data.same_day),
            ("PSL status", data.psl_status), ("Mileage", data.miles_text), ("Wait", data.wait_text),
            ("Trash", data.trash_text), ("Vehicle", data.vehicle_text), ("Other client scheduled", data.other_client),
            ("General notes", data.general_notes),
        ]
        table_data = [[Paragraph(f"<b>{self._escape(label)}</b>", self.body), Paragraph(self._escape(value or "—").replace("\n", "<br/>"), self.body)] for label, value in rows]
        table = Table(table_data, colWidths=[1.55 * inch, 5.3 * inch])
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")),
            ("BACKGROUND", (0, 0), (0, -1), LIGHT),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        story.extend([table, Spacer(1, 10), Paragraph("Internal intake document — not a customer quote.", self.small)])
        doc.build(story)
        return destination

    def _logo(self, width: float, height: float) -> object:
        if self.logo_path is not None and self.logo_path.is_file():
            image = Image(str(self.logo_path), width=width, height=height, kind="proportional")
            image.hAlign = "LEFT"
            return image
        return Paragraph("<b>McMahon Dispatch</b><br/><font color='#F97316'>Jobsite Delivery</font>", self.heading)

    def _detail_block(self, heading: str, values: list[str]) -> object:
        return [Paragraph(heading, self.heading), Paragraph(self._join_lines(values), self.body)]

    @staticmethod
    def _join_lines(values: list[str]) -> str:
        return "<br/>".join(QuotePdfGenerator._escape(value) for value in values if value.strip()) or "—"

    @staticmethod
    def _money(cents: int) -> str:
        sign = "-" if cents < 0 else ""
        return f"{sign}${abs(cents) / 100:,.2f}"

    @staticmethod
    def _quantity(value: object) -> str:
        text = format(value, "f")  # type: ignore[arg-type]
        return text.rstrip("0").rstrip(".") or "0"

    @staticmethod
    def _escape(value: str) -> str:
        return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
