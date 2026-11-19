"""Reports the assistant hands over as files: PDF, Excel and CSV.

A report is a title, a short summary and sections. Each section has a heading,
optional narrative, and optionally a table (and chart) built from a dataset --
real application data, never numbers typed by the model.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from ..config import get_settings
from . import outputs

FORMATS = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
}


def _now_text() -> str:
    return datetime.now(ZoneInfo(get_settings().business_timezone)).strftime("%d %b %Y, %H:%M")


def _plain(text: str) -> str:
    """Markdown down to plain text for the PDF."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text or "")
    text = re.sub(r"\[(.+?)\]\((.+?)\)", r"\1", text)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"`(.+?)`", r"\1", text)
    return text.replace("•", "-")


def _latin(text: Any) -> str:
    """Core PDF fonts are Latin-1 only (as for invoices)."""
    return (str(text) if text is not None else "").replace("₹", "INR ").replace("—", "-").replace("–", "-") \
        .replace("’", "'").replace("“", '"').replace("”", '"').replace("…", "...") \
        .encode("latin-1", "replace").decode("latin-1")


def _fmt(value: Any, kind: str) -> str:
    if value is None or value == "":
        return "-"
    if kind == "money" and isinstance(value, (int, float)):
        return "INR {:,.2f}".format(value)
    if kind == "percent" and isinstance(value, (int, float)):
        return "{:.1f}%".format(value)
    if kind == "number" and isinstance(value, float):
        return ("{:,.3f}".format(value)).rstrip("0").rstrip(".")
    if kind == "number" and isinstance(value, int):
        return "{:,}".format(value)
    if kind == "date" and isinstance(value, str):
        return value[:10]
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def _section_table(section: Dict[str, Any], datasets: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    dataset_id = section.get("dataset_id")
    if not dataset_id:
        return None
    dataset = datasets.get(dataset_id)
    if dataset is None:
        raise ValueError("Unknown dataset {}. Use a dataset_id returned by a data tool.".format(dataset_id))
    return outputs.table_block(dataset, section.get("heading") or "", section.get("path"), section.get("columns"), limit=2000)


def build(fmt: str, title: str, summary: str, sections: List[Dict[str, Any]], datasets: Dict[str, Dict[str, Any]]) -> Tuple[bytes, str]:
    if fmt not in FORMATS:
        raise ValueError("format must be pdf, xlsx or csv.")
    tables = [(section, _section_table(section, datasets)) for section in sections]
    if fmt == "csv":
        table = next((table for _, table in tables if table), None)
        if table is None:
            raise ValueError("A CSV report needs a section with a dataset_id.")
        return _csv(table), FORMATS[fmt]
    if fmt == "xlsx":
        return _xlsx(title, summary, tables, datasets), FORMATS[fmt]
    return _pdf(title, summary, tables, datasets), FORMATS[fmt]


def _csv(table: Dict[str, Any]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([column["label"] for column in table["columns"]])
    for row in table["rows"]:
        writer.writerow([row.get(column["key"]) if row.get(column["key"]) is not None else "" for column in table["columns"]])
    return buffer.getvalue().encode("utf-8-sig")


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

INK = (11, 11, 12)
GREY = (123, 129, 138)
SKY = (94, 196, 241)
SKY_LIGHT = (191, 232, 251)
RULE = (226, 230, 234)


def _pdf(title: str, summary: str, tables, datasets) -> bytes:
    from fpdf import FPDF

    wide = any(table and len(table["columns"]) > 6 for _, table in tables)
    pdf = FPDF(orientation="L" if wide else "P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.set_margins(14, 14, 14)
    business = get_settings().app_name

    def footer_line():
        pdf.set_y(-12)
        pdf.set_font("Helvetica", "", 7.5)
        pdf.set_text_color(*GREY)
        pdf.cell(0, 5, _latin("{}  |  {}  |  page {}".format(business, title, pdf.page_no())), align="R")

    pdf.footer = footer_line  # type: ignore[assignment]
    pdf.add_page()
    pdf.set_fill_color(*SKY)
    pdf.rect(0, 0, pdf.w, 3, "F")
    pdf.set_text_color(*INK)
    pdf.set_font("Helvetica", "B", 20)
    pdf.multi_cell(0, 9, _latin(title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*GREY)
    pdf.cell(0, 6, _latin("Prepared {} from live application data".format(_now_text())), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    if summary:
        pdf.set_text_color(*INK)
        pdf.set_font("Helvetica", "", 10.5)
        pdf.multi_cell(0, 5.5, _latin(_plain(summary)), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

    for section, table in tables:
        if pdf.get_y() > pdf.h - 60:
            pdf.add_page()
        pdf.set_draw_color(*RULE)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
        pdf.ln(3)
        pdf.set_text_color(*INK)
        pdf.set_font("Helvetica", "B", 13)
        pdf.multi_cell(0, 7, _latin(section.get("heading") or ""), new_x="LMARGIN", new_y="NEXT")
        if section.get("text"):
            pdf.set_font("Helvetica", "", 10)
            pdf.multi_cell(0, 5.2, _latin(_plain(section["text"])), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1.5)
        chart = section.get("chart")
        if chart and section.get("dataset_id"):
            try:
                block = outputs.chart_block(datasets[section["dataset_id"]], chart.get("type", "bar"), chart["x"], chart["y"],
                                            section.get("heading") or "", section.get("path"), limit=24)
                _pdf_bars(pdf, block)
            except (KeyError, ValueError):
                pass
        if table:
            _pdf_table(pdf, table)
        pdf.ln(4)
    return bytes(pdf.output())


def _pdf_table(pdf, table: Dict[str, Any]) -> None:
    columns = table["columns"]
    width = pdf.w - pdf.l_margin - pdf.r_margin
    weights = []
    for column in columns:
        longest = max([len(column["label"])] + [len(_fmt(row.get(column["key"]), column["kind"])) for row in table["rows"][:80]])
        weights.append(min(max(longest, 6), 40))
    total = sum(weights) or 1
    widths = [width * weight / total for weight in weights]

    def header():
        pdf.set_font("Helvetica", "B", 8.5)
        pdf.set_fill_color(242, 244, 246)
        pdf.set_text_color(*INK)
        for column, w in zip(columns, widths):
            align = "R" if column["kind"] in ("money", "number", "percent") else "L"
            pdf.cell(w, 7, _latin(column["label"])[:40], border=0, align=align, fill=True)
        pdf.ln(7)

    header()
    pdf.set_font("Helvetica", "", 8.5)
    for index, row in enumerate(table["rows"]):
        if pdf.get_y() > pdf.h - 22:
            pdf.add_page()
            header()
            pdf.set_font("Helvetica", "", 8.5)
        if index % 2:
            pdf.set_fill_color(250, 251, 252)
        for column, w in zip(columns, widths):
            text = _latin(_fmt(row.get(column["key"]), column["kind"]))
            limit = max(4, int(w / 1.75))
            if len(text) > limit:
                text = text[: limit - 1] + "."
            align = "R" if column["kind"] in ("money", "number", "percent") else "L"
            pdf.cell(w, 6, text, border=0, align=align, fill=bool(index % 2))
        pdf.ln(6)
    if table["total_rows"] > len(table["rows"]):
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(*GREY)
        pdf.cell(0, 5, _latin("Showing {} of {} rows.".format(len(table["rows"]), table["total_rows"])), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(*INK)


def _pdf_bars(pdf, chart: Dict[str, Any]) -> None:
    rows = chart["rows"]
    key = chart["series"][0]["key"]
    values = [float(row.get(key) or 0) for row in rows]
    if not rows or not any(values):
        return
    height = 46
    if pdf.get_y() + height + 14 > pdf.h - 16:
        pdf.add_page()
    left, top = pdf.l_margin + 2, pdf.get_y() + 2
    width = pdf.w - pdf.l_margin - pdf.r_margin - 4
    peak = max(max(values), 0.0001)
    slot = width / len(rows)
    bar = min(14, slot * 0.62)
    pdf.set_draw_color(*RULE)
    pdf.line(left, top + height, left + width, top + height)
    for index, (row, value) in enumerate(zip(rows, values)):
        h = max(0.6, height * value / peak) if value > 0 else 0
        x = left + index * slot + (slot - bar) / 2
        pdf.set_fill_color(*(SKY if index == values.index(max(values)) else SKY_LIGHT))
        if h:
            pdf.rect(x, top + height - h, bar, h, "F")
        pdf.set_font("Helvetica", "", 6.5)
        pdf.set_text_color(*GREY)
        label = _latin(row.get("x"))[: max(3, int(slot / 1.6))]
        pdf.set_xy(left + index * slot, top + height + 1)
        pdf.cell(slot, 4, label, align="C")
    pdf.set_text_color(*INK)
    pdf.set_y(top + height + 8)


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------


def _xlsx(title: str, summary: str, tables, datasets) -> bytes:
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, LineChart, PieChart, Reference
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    book = Workbook()
    cover = book.active
    cover.title = "Summary"
    cover["A1"] = title
    cover["A1"].font = Font(size=16, bold=True)
    cover["A2"] = "Prepared {} from live application data".format(_now_text())
    cover["A2"].font = Font(color="7B818A")
    row = 4
    for line in _plain(summary).splitlines():
        cover.cell(row=row, column=1, value=line)
        cover.cell(row=row, column=1).alignment = Alignment(wrap_text=True, vertical="top")
        row += 1
    row += 1
    for section, table in tables:
        cover.cell(row=row, column=1, value=section.get("heading")).font = Font(bold=True, size=12)
        row += 1
        if section.get("text"):
            for line in _plain(section["text"]).splitlines():
                cover.cell(row=row, column=1, value=line).alignment = Alignment(wrap_text=True)
                row += 1
        row += 1
    cover.column_dimensions["A"].width = 110

    used_names = set()
    header_fill = PatternFill("solid", fgColor="0B0B0C")
    for section, table in tables:
        if not table:
            continue
        name = re.sub(r"[\[\]\*\?/\\:]", "", section.get("heading") or "Data")[:28] or "Data"
        base, n = name, 2
        while name in used_names:
            name = "{} {}".format(base[:25], n)
            n += 1
        used_names.add(name)
        sheet = book.create_sheet(name)
        for col, column in enumerate(table["columns"], start=1):
            cell = sheet.cell(row=1, column=col, value=column["label"])
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = header_fill
        for r, data in enumerate(table["rows"], start=2):
            for col, column in enumerate(table["columns"], start=1):
                value = data.get(column["key"])
                cell = sheet.cell(row=r, column=col, value=value)
                if column["kind"] == "money":
                    cell.number_format = '"₹"#,##0.00'
                elif column["kind"] == "percent":
                    cell.number_format = '0.0"%"'
                elif column["kind"] == "number":
                    cell.number_format = "#,##0.###"
        for col, column in enumerate(table["columns"], start=1):
            longest = max([len(column["label"])] + [len(str(data.get(column["key"]) or "")) for data in table["rows"][:200]])
            sheet.column_dimensions[get_column_letter(col)].width = min(max(10, longest + 2), 48)
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        chart_spec = section.get("chart")
        if chart_spec and table["rows"]:
            keys = [column["key"] for column in table["columns"]]
            if chart_spec.get("x") in keys and all(key in keys for key in chart_spec.get("y", [])):
                kind = chart_spec.get("type", "bar")
                chart = PieChart() if kind == "pie" else LineChart() if kind in ("line", "area") else BarChart()
                if kind == "horizontal_bar" and isinstance(chart, BarChart):
                    chart.type = "bar"
                chart.title = section.get("heading")
                last = len(table["rows"]) + 1
                x_col = keys.index(chart_spec["x"]) + 1
                for y_key in chart_spec["y"][: 1 if kind == "pie" else 4]:
                    y_col = keys.index(y_key) + 1
                    chart.add_data(Reference(sheet, min_col=y_col, min_row=1, max_row=last), titles_from_data=True)
                chart.set_categories(Reference(sheet, min_col=x_col, min_row=2, max_row=last))
                chart.height, chart.width = 8, 18
                sheet.add_chart(chart, "{}2".format(get_column_letter(len(keys) + 2)))
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()
