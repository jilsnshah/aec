"""The invoice PDF sent to a customer: Tally's invoice number, our order's lines.

The amounts are the same ones posted to Tally (the order's net prices, plus
GST when the Tally integration adds it), so the PDF and the voucher in Tally
agree. Built with fpdf2's core fonts, which have no rupee sign -- amounts are
labelled INR.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import List, Optional, Sequence, Tuple

from fpdf import FPDF


@dataclass
class InvoiceLine:
    description: str
    quantity: Decimal
    unit: str
    rate: Decimal
    amount: Decimal


@dataclass
class Invoice:
    number: str
    on: date
    order_number: str
    seller_name: str
    seller_address: str
    seller_gstin: str
    seller_phone: str
    customer_name: str
    customer_address: Optional[str]
    customer_phone: Optional[str]
    lines: List[InvoiceLine]
    taxes: Sequence[Tuple[str, Decimal]]

    @property
    def subtotal(self) -> Decimal:
        return sum((line.amount for line in self.lines), Decimal("0"))

    @property
    def total(self) -> Decimal:
        return self.subtotal + sum((amount for _, amount in self.taxes), Decimal("0"))


def money(value: Decimal) -> str:
    return "{:,.2f}".format(Decimal(value))


def _latin(text: Optional[str]) -> str:
    """Core PDF fonts are Latin-1; replace what they cannot draw."""
    return (text or "").replace("₹", "INR ").encode("latin-1", "replace").decode("latin-1")


def render(invoice: Invoice) -> bytes:
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    pdf.set_margins(16, 16, 16)

    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 9, _latin(invoice.seller_name or "Invoice"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    for text in (invoice.seller_address, invoice.seller_phone and "Phone: " + invoice.seller_phone,
                 invoice.seller_gstin and "GSTIN: " + invoice.seller_gstin):
        if text:
            pdf.multi_cell(0, 4.5, _latin(text), new_x="LMARGIN", new_y="NEXT")

    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, "TAX INVOICE" if invoice.taxes else "INVOICE", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    top = pdf.get_y()
    pdf.multi_cell(95, 5, _latin("Bill to:\n{}{}{}".format(
        invoice.customer_name,
        "\n" + invoice.customer_address if invoice.customer_address else "",
        "\nPhone: " + invoice.customer_phone if invoice.customer_phone else "",
    )))
    left_bottom = pdf.get_y()
    pdf.set_xy(115, top)
    pdf.multi_cell(0, 5, _latin("Invoice no: {}\nDate: {}\nOrder: {}".format(
        invoice.number, invoice.on.strftime("%d %b %Y"), invoice.order_number,
    )), align="R")
    pdf.set_y(max(left_bottom, pdf.get_y()) + 5)

    widths = (84, 26, 34, 34)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(240, 240, 243)
    for width, title, align in zip(widths, ("Item", "Qty", "Rate (INR)", "Amount (INR)"), ("L", "R", "R", "R")):
        pdf.cell(width, 7, title, border="B", align=align, fill=True)
    pdf.ln()
    pdf.set_font("Helvetica", "", 9)
    for line in invoice.lines:
        pdf.cell(widths[0], 7, _latin(line.description)[:60])
        pdf.cell(widths[1], 7, "{} {}".format(format(Decimal(line.quantity).normalize(), "f"), _latin(line.unit)), align="R")
        pdf.cell(widths[2], 7, money(line.rate), align="R")
        pdf.cell(widths[3], 7, money(line.amount), align="R")
        pdf.ln()

    pdf.ln(2)
    rows = [("Subtotal", invoice.subtotal)] + list(invoice.taxes) + [("Total (INR)", invoice.total)]
    for index, (label, amount) in enumerate(rows):
        last = index == len(rows) - 1
        pdf.set_font("Helvetica", "B" if last else "", 10 if last else 9)
        pdf.cell(sum(widths[:3]), 7, _latin(label), align="R", border="T" if last else 0)
        pdf.cell(widths[3], 7, money(amount), align="R", border="T" if last else 0)
        pdf.ln()

    pdf.ln(8)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(110, 110, 115)
    pdf.multi_cell(0, 4, "This invoice is recorded in our books (Tally) under number {}.".format(_latin(invoice.number)))
    return bytes(pdf.output())
