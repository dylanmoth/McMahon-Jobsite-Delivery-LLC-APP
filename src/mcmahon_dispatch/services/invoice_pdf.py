from __future__ import annotations

from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from mcmahon_dispatch.database.models import Customer, Invoice, Organization, Payment


ORANGE = colors.HexColor("#F97316")
DARK = colors.HexColor("#111827")
SLATE = colors.HexColor("#475569")
LIGHT = colors.HexColor("#F3F4F6")
BORDER = colors.HexColor("#CBD5E1")
GREEN = colors.HexColor("#15803D")
RED = colors.HexColor("#B91C1C")


def money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def date_text(value) -> str:
    if value is None:
        return "-"
    return value.strftime("%b %d, %Y")


class InvoicePdfWriter:
    def __init__(self, logo_path: Path) -> None:
        self.logo_path = logo_path
        styles = getSampleStyleSheet()
        self.body = ParagraphStyle("Body", parent=styles["BodyText"], fontName="Helvetica", fontSize=9, leading=13, textColor=DARK)
        self.small = ParagraphStyle("Small", parent=self.body, fontSize=8, leading=11, textColor=SLATE)
        self.heading = ParagraphStyle("Heading", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=22, leading=26, textColor=DARK)
        self.section = ParagraphStyle("Section", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=10, leading=14, textColor=ORANGE, spaceBefore=8, spaceAfter=5)
        self.right = ParagraphStyle("Right", parent=self.body, alignment=TA_RIGHT)
        self.total = ParagraphStyle("Total", parent=self.right, fontName="Helvetica-Bold", fontSize=12, textColor=DARK)

    def write_invoice(self, path: Path, organization: Organization, customer: Customer, invoice: Invoice) -> None:
        doc = SimpleDocTemplate(
            str(path), pagesize=letter, rightMargin=0.55 * inch, leftMargin=0.55 * inch,
            topMargin=0.45 * inch, bottomMargin=0.45 * inch,
            title=f"Invoice {invoice.invoice_number}", author=organization.legal_name,
        )
        story = []
        story.extend(self._header(organization, "INVOICE", invoice.invoice_number))
        status = invoice.status.replace("_", " ").title()
        meta = [
            [Paragraph("<b>Bill To</b>", self.body), Paragraph("<b>Invoice Details</b>", self.body)],
            [Paragraph(self._customer_block(customer), self.body), Paragraph(
                f"<b>Issued:</b> {date_text(invoice.issued_at)}<br/>"
                f"<b>Due:</b> {date_text(invoice.due_at)}<br/>"
                f"<b>Status:</b> {status}<br/>"
                f"<b>Terms:</b> Net {invoice.terms_days}<br/>"
                f"<b>PO / Reference:</b> {invoice.purchase_order_number or invoice.customer_reference or '-'}",
                self.body,
            )],
        ]
        meta_table = Table(meta, colWidths=[3.7 * inch, 3.15 * inch], hAlign="LEFT")
        meta_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), LIGHT),
            ("BOX", (0, 0), (-1, -1), 0.75, BORDER),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        story.extend([meta_table, Spacer(1, 14)])

        rows = [["Description", "Qty", "Rate", "Amount"]]
        for line in invoice.lines:
            rows.append([
                Paragraph(line.description, self.body),
                f"{line.quantity:g}",
                money(line.unit_rate_cents),
                money(line.line_total_cents),
            ])
        charge_table = Table(rows, colWidths=[4.35 * inch, 0.65 * inch, 0.9 * inch, 1.0 * inch], repeatRows=1)
        charge_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), DARK),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(charge_table)

        totals = [
            ["Subtotal", money(invoice.subtotal_cents)],
            ["Discount", f"-{money(invoice.discount_cents)}"],
            ["Tax", money(invoice.tax_cents)],
            [Paragraph("<b>Total</b>", self.right), Paragraph(f"<b>{money(invoice.total_cents)}</b>", self.right)],
            ["Payments", f"-{money(invoice.paid_cents)}"],
            [Paragraph("<b>Balance Due</b>", self.total), Paragraph(f"<b>{money(invoice.balance_cents)}</b>", self.total)],
        ]
        totals_table = Table(totals, colWidths=[1.35 * inch, 1.15 * inch], hAlign="RIGHT")
        totals_table.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
            ("LINEABOVE", (0, 3), (-1, 3), 0.75, BORDER),
            ("LINEABOVE", (0, 5), (-1, 5), 1.2, ORANGE),
            ("TEXTCOLOR", (0, 5), (-1, 5), DARK),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.extend([Spacer(1, 10), totals_table])

        if invoice.customer_notes:
            story.extend([
                Spacer(1, 14), Paragraph("Notes", self.section),
                Paragraph(invoice.customer_notes.replace("\n", "<br/>"), self.body),
            ])
        story.extend([
            Spacer(1, 18),
            Paragraph(
                "Payment methods accepted: ACH, check, card, cash, external payment link, or another approved method. "
                "Please include the invoice number with payment. Contact us promptly with billing questions.",
                self.small,
            ),
        ])
        doc.build(story, onFirstPage=self._footer, onLaterPages=self._footer)

    def write_statement(
        self,
        path: Path,
        organization: Organization,
        customer: Customer,
        date_from: date,
        date_to: date,
        opening_balance_cents: int,
        invoices: list[Invoice],
        payments: list[Payment],
        closing_balance_cents: int,
    ) -> None:
        doc = SimpleDocTemplate(
            str(path), pagesize=letter, rightMargin=0.55 * inch, leftMargin=0.55 * inch,
            topMargin=0.45 * inch, bottomMargin=0.45 * inch,
            title=f"Statement - {customer.company_name}", author=organization.legal_name,
        )
        story = self._header(organization, "CUSTOMER STATEMENT", f"{date_from:%b %d, %Y} - {date_to:%b %d, %Y}")
        story.extend([
            Paragraph("Statement For", self.section),
            Paragraph(self._customer_block(customer), self.body),
            Spacer(1, 12),
        ])
        transactions: list[tuple[date, str, str, int, int]] = []
        for invoice in invoices:
            tx_date = (invoice.issued_at or invoice.created_at).date()
            transactions.append((tx_date, invoice.invoice_number, "Invoice", invoice.total_cents, 0))
        for payment in payments:
            transactions.append((payment.received_at.date(), payment.payment_number, f"Payment - {payment.payment_method.replace('_', ' ').title()}", 0, payment.gross_amount_cents))
        transactions.sort(key=lambda item: (item[0], item[1]))
        rows = [["Date", "Reference", "Activity", "Charges", "Payments"]]
        rows.append([date_from.strftime("%b %d, %Y"), "", "Opening balance", money(opening_balance_cents), ""])
        for tx_date, reference, activity, charge, payment in transactions:
            rows.append([tx_date.strftime("%b %d, %Y"), reference, activity, money(charge) if charge else "", money(payment) if payment else ""])
        table = Table(rows, colWidths=[1.0 * inch, 1.35 * inch, 2.65 * inch, 0.95 * inch, 0.95 * inch], repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), DARK),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.2),
            ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
            ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.extend([table, Spacer(1, 12)])
        balance_table = Table([
            [Paragraph("<b>Closing Balance</b>", self.total), Paragraph(f"<b>{money(closing_balance_cents)}</b>", self.total)]
        ], colWidths=[1.55 * inch, 1.15 * inch], hAlign="RIGHT")
        balance_table.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 1.2, ORANGE), ("TOPPADDING", (0, 0), (-1, -1), 7)]))
        story.append(balance_table)
        story.extend([Spacer(1, 16), Paragraph("Please contact us if your records differ from this statement.", self.small)])
        doc.build(story, onFirstPage=self._footer, onLaterPages=self._footer)

    def _header(self, organization: Organization, title: str, reference: str) -> list:
        logo = None
        if self.logo_path.exists():
            logo = Image(str(self.logo_path), width=1.55 * inch, height=0.74 * inch, kind="proportional")
        company = Paragraph(
            f"<b>{organization.legal_name}</b><br/>"
            f"{organization.phone or ''}<br/>"
            f"{organization.email or ''}<br/>"
            f"{organization.website or ''}",
            self.small,
        )
        title_block = Paragraph(
            f'<font size="18"><b>{title}</b></font><br/><br/><font size="10" color="#F97316"><b>{reference}</b></font>',
            self.right,
        )
        table = Table([[logo or company, company if logo else "", title_block]], colWidths=[1.65 * inch, 3.25 * inch, 2.0 * inch])
        table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (-1, 0), (-1, 0), "RIGHT")]))
        return [table, Spacer(1, 12)]

    def _customer_block(self, customer: Customer) -> str:
        pieces = [f"<b>{customer.company_name}</b>"]
        if customer.legal_name and customer.legal_name != customer.company_name:
            pieces.append(customer.legal_name)
        if customer.billing_email or customer.primary_email:
            pieces.append(customer.billing_email or customer.primary_email or "")
        if customer.primary_phone:
            pieces.append(customer.primary_phone)
        return "<br/>".join(pieces)

    @staticmethod
    def _footer(canvas, doc) -> None:
        canvas.saveState()
        canvas.setStrokeColor(BORDER)
        canvas.line(0.55 * inch, 0.37 * inch, 7.95 * inch, 0.37 * inch)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(SLATE)
        canvas.drawString(0.55 * inch, 0.22 * inch, "McMahon Dispatch - Confidential business document")
        canvas.drawRightString(7.95 * inch, 0.22 * inch, f"Page {doc.page}")
        canvas.restoreState()
