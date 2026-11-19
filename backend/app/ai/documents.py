"""Files users attach to a conversation.

* Images and PDFs go to Gemini as they are: it reads invoices, bills, receipts
  and photos natively.
* Spreadsheets and CSV files are parsed here into rows. The rows become a
  dataset (so the assistant can table them, check them against records, or
  turn them into entries) and a preview goes into the prompt.
* Plain text, JSON and Markdown are inlined.
"""
from __future__ import annotations

import base64
import csv
import io
import json
from datetime import date, datetime
from typing import Any, Dict, List, Tuple

from ..errors import ValidationError
from . import outputs

MAX_BYTES = 15 * 1024 * 1024
MAX_FILES_PER_MESSAGE = 6
MAX_ROWS = 5000
PREVIEW_ROWS = 40

NATIVE = {
    "application/pdf", "image/png", "image/jpeg", "image/webp", "image/heic", "image/heif", "image/gif",
}
SHEETS = {
    "text/csv", "application/csv",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel.sheet.macroenabled.12",
}
TEXT = {"text/plain", "text/markdown", "application/json"}
EXTENSIONS = {
    ".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".heic": "image/heic", ".gif": "image/gif", ".csv": "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xlsm": "application/vnd.ms-excel.sheet.macroenabled.12",
    ".txt": "text/plain", ".md": "text/markdown", ".json": "application/json",
}


def mime_for(filename: str, declared: str) -> str:
    lowered = (filename or "").lower()
    for ext, mime in EXTENSIONS.items():
        if lowered.endswith(ext):
            return mime
    return (declared or "").split(";")[0].strip().lower()


def check(filename: str, mime: str, size: int) -> str:
    kind = mime_for(filename, mime)
    if kind not in NATIVE | SHEETS | TEXT:
        raise ValidationError(
            "{} cannot be read. Attach a PDF, an image (PNG, JPEG, WebP), a spreadsheet (XLSX, CSV) or a text file.".format(filename)
        )
    if size > MAX_BYTES:
        raise ValidationError("{} is larger than 15 MB.".format(filename))
    if size == 0:
        raise ValidationError("{} is empty.".format(filename))
    return kind


def _cell(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()[:19]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def parse_sheet(filename: str, mime: str, data: bytes) -> Dict[str, Any]:
    """Rows from a CSV or the sheets of an Excel workbook."""
    sheets: List[Dict[str, Any]] = []
    if mime in ("text/csv", "application/csv"):
        text = data.decode("utf-8-sig", errors="replace")
        reader = csv.reader(io.StringIO(text))
        table = [row for row in reader]
        sheets.append(_table("Sheet1", table))
    else:
        from openpyxl import load_workbook

        book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        for sheet in book.worksheets[:5]:
            table = []
            for row in sheet.iter_rows(values_only=True):
                table.append([_cell(value) for value in row])
                if len(table) > MAX_ROWS:
                    break
            sheets.append(_table(sheet.title, table))
    return {"file": filename, "sheets": sheets}


def _table(name: str, table: List[List[Any]]) -> Dict[str, Any]:
    while table and not any(value not in (None, "") for value in table[-1]):
        table.pop()
    while table and not any(value not in (None, "") for value in table[0]):
        table.pop(0)
    if not table:
        return {"name": name, "columns": [], "rows": [], "row_count": 0}
    header = [str(value).strip() if value not in (None, "") else "column_{}".format(i + 1) for i, value in enumerate(table[0])]
    seen: Dict[str, int] = {}
    for i, key in enumerate(header):
        if key in seen:
            seen[key] += 1
            header[i] = "{}_{}".format(key, seen[key])
        else:
            seen[key] = 1
    rows = []
    for raw in table[1:MAX_ROWS + 1]:
        if not any(value not in (None, "") for value in raw):
            continue
        rows.append({header[i]: _cell(raw[i]) if i < len(raw) else None for i in range(len(header))})
    return {"name": name, "columns": header, "rows": rows, "row_count": len(rows)}


def sheet_prompt(file: Dict[str, Any], dataset: Dict[str, Any]) -> Dict[str, Any]:
    """How a parsed spreadsheet is shown to the model: where its rows are, and a preview."""
    lines = ["[Attached file: {} ({}), file_id={}]".format(file["filename"], file["mime_type"], file["id"]),
             "Parsed into dataset {} (use path 'sheets.0.rows' for the first sheet).".format(dataset["id"])]
    for index, sheet in enumerate(dataset["data"]["sheets"]):
        lines.append("Sheet {} '{}': {} rows; columns: {}".format(index, sheet["name"], sheet["row_count"], ", ".join(sheet["columns"][:40])))
        preview = sheet["rows"][:PREVIEW_ROWS]
        if preview:
            lines.append(json.dumps(preview, default=str)[:12000])
    return {"type": "text", "text": "\n".join(lines)}


def for_model(file: Dict[str, Any], data: bytes) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Content blocks for the model, and datasets made from the file."""
    mime, name, file_id = file["mime_type"], file["filename"], file["id"]
    intro = {"type": "text", "text": "[Attached file: {} ({}), file_id={}]".format(name, mime, file_id)}
    if mime in NATIVE:
        kind = "image" if mime.startswith("image/") else "file"
        return [intro, {"type": kind, "base64": base64.b64encode(data).decode("ascii"), "mime_type": mime}], []
    if mime in SHEETS:
        parsed = parse_sheet(name, mime, data)
        dataset = {"id": outputs.new_dataset_id(), "tool": "attachment", "args": {"file": name, "file_id": file_id}, "data": parsed}
        return [sheet_prompt(file, dataset)], [dataset]
    text = data.decode("utf-8", errors="replace")[:60000]
    return [{"type": "text", "text": "{}\n<file_content>\n{}\n</file_content>".format(intro["text"], text)}], []
