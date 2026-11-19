"""Datasets, tables and charts.

Every data tool's result is kept as a *dataset* with an id. Tables, charts and
reports are built from dataset ids, never from numbers the model types, so
what the user sees is exactly what the application returned.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

MAX_TABLE_ROWS = 500
MAX_CHART_POINTS = 200

MONEY_WORDS = ("value", "revenue", "cost", "profit", "amount", "price", "mrp", "spend", "booked", "total", "outstanding")
PERCENT_WORDS = ("percent", "rate", "share", "margin")


def new_dataset_id() -> str:
    return "ds_" + uuid.uuid4().hex[:8]


def get_path(value: Any, path: Optional[str]) -> Any:
    """Follow a dotted path ('totals.age_value', 'items', 'ages.90+.value')."""
    if not path:
        return value
    current = value
    for part in path.split("."):
        if isinstance(current, dict):
            if part in current:
                current = current[part]
                continue
            return None
        if isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
            continue
        return None
    return current


def rows_of(data: Any, path: Optional[str] = None) -> Tuple[List[Dict[str, Any]], str]:
    """The list of records inside a result, and the path used to reach it."""
    target = get_path(data, path)
    if path and target is None:
        raise ValueError("'{}' is not in that dataset. Lists in it: {}.".format(path, ", ".join(list_paths(data)) or "none"))
    if isinstance(target, list):
        return [row if isinstance(row, dict) else {"value": row} for row in target], path or ""
    if isinstance(target, dict):
        for key in ("items", "products", "customers", "suppliers", "alerts", "rows", "stale", "daily", "by_source"):
            if isinstance(target.get(key), list):
                prefix = (path + "." if path else "") + key
                return [row if isinstance(row, dict) else {"value": row} for row in target[key]], prefix
        lists = list_paths(target)
        if lists:
            return rows_of(data, (path + "." if path else "") + lists[0])
        # A single record or a dict of figures: one row per key, or one row.
        scalars = {key: value for key, value in target.items() if _scalar(value)}
        if scalars and all(_scalar(value) for value in target.values()) and len(target) > 6:
            return [{"name": key, "value": value} for key, value in target.items()], path or ""
        return [_flatten(target)], path or ""
    return [{"value": target}], path or ""


def list_paths(data: Any, prefix: str = "", depth: int = 0) -> List[str]:
    found = []
    if isinstance(data, dict) and depth < 2:
        for key, value in data.items():
            here = prefix + key
            if isinstance(value, list) and value and isinstance(value[0], dict):
                found.append(here)
            elif isinstance(value, dict):
                found.extend(list_paths(value, here + ".", depth + 1))
    return found


def _scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _flatten(row: Dict[str, Any], prefix: str = "", depth: int = 0) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in row.items():
        name = prefix + key
        if isinstance(value, dict) and depth < 2:
            out.update(_flatten(value, name + ".", depth + 1))
        elif _scalar(value):
            out[name] = value
    return out


def kind_of(key: str, values: List[Any]) -> str:
    sample = [value for value in values if value is not None][:20]
    lowered = key.lower()
    if sample and all(isinstance(value, bool) for value in sample):
        return "boolean"
    if sample and all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in sample):
        if any(word in lowered for word in PERCENT_WORDS):
            return "percent"
        if any(word in lowered for word in MONEY_WORDS):
            return "money"
        return "number"
    if sample and all(isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}", value) for value in sample):
        return "date"
    return "text"


def label_of(key: str) -> str:
    text = key.split(".")[-1] if key.count(".") == 0 else key.replace(".", " ")
    text = text.replace("_", " ").strip()
    return text[:1].upper() + text[1:]


HIDDEN = re.compile(r"(^|\.)(id|.*_id|is_active|idempotency_key|result_json)$")

LINKS = [
    ("order_number", ("sales_order_id", "order_id"), "/orders/"),
    ("enquiry_number", ("enquiry_id",), "/enquiries/"),
    ("po_number", ("purchase_order_id", "po_id"), "/purchase-orders/"),
    ("customer_name", ("customer_id",), "/customers/"),
    ("supplier_name", ("supplier_id",), "/suppliers/"),
    ("name", ("product_id",), "/products/"),
    ("name", ("customer_id",), "/customers/"),
    ("name", ("supplier_id",), "/suppliers/"),
]
TOOL_HOME = {
    "list_orders": "/orders/", "list_enquiries": "/enquiries/", "list_purchase_orders": "/purchase-orders/",
    "list_products": "/products/", "list_customers": "/customers/", "list_suppliers": "/suppliers/",
    "list_goods_receipts": "/receipts/",
}
TOOL_LABEL = {
    "list_orders": "order_number", "list_enquiries": "enquiry_number", "list_purchase_orders": "po_number",
    "list_products": "name", "list_customers": "name", "list_suppliers": "name", "list_goods_receipts": "receipt_number",
}


def _links(tool: str, rows: List[Dict[str, Any]], keys: List[str]) -> Dict[str, Dict[str, str]]:
    """Which columns link to a record, and through which id field."""
    if not rows:
        return {}
    sample = rows[0]
    found: Dict[str, Dict[str, str]] = {}
    for column, ids, route in LINKS:
        if column in keys and column not in found:
            id_key = next((key for key in ids if key in sample), None)
            if id_key:
                found[column] = {"id": id_key, "route": route}
    home = TOOL_HOME.get(tool)
    label = TOOL_LABEL.get(tool)
    if home and label in keys and label not in found and "id" in sample:
        found[label] = {"id": "id", "route": home}
    return found


def choose_columns(rows: List[Dict[str, Any]], wanted: Optional[List[str]] = None, limit: int = 9) -> List[str]:
    flat = [_flatten(row) for row in rows[:50]]
    keys: List[str] = []
    for row in flat:
        for key in row:
            if key not in keys:
                keys.append(key)
    if wanted:
        missing = [key for key in wanted if key not in keys]
        if missing:
            raise ValueError("Unknown column(s) {}. Available: {}.".format(", ".join(missing), ", ".join(keys[:60])))
        return wanted
    visible = [key for key in keys if not HIDDEN.search(key)]
    return visible[:limit]


def table_block(dataset: Dict[str, Any], title: str, path: Optional[str] = None, columns: Optional[List[str]] = None,
                limit: Optional[int] = None) -> Dict[str, Any]:
    rows, used = rows_of(dataset["data"], path)
    keys = choose_columns(rows, columns)
    flat = [_flatten(row) for row in rows]
    cap = min(limit or MAX_TABLE_ROWS, MAX_TABLE_ROWS)
    links = _links(dataset["tool"], flat, keys)
    id_keys = {link["id"] for link in links.values()}
    shown = [{key: row.get(key) for key in list(keys) + list(id_keys)} for row in flat[:cap]]
    return {
        "type": "table",
        "title": title,
        "dataset_id": dataset["id"],
        "path": used,
        "columns": [
            {"key": key, "label": label_of(key), "kind": kind_of(key, [row.get(key) for row in flat]), "link": links.get(key)}
            for key in keys
        ],
        "rows": shown,
        "total_rows": len(rows),
    }


CHART_TYPES = ("bar", "horizontal_bar", "stacked_bar", "line", "area", "pie")


def chart_block(dataset: Dict[str, Any], chart_type: str, x: str, y: List[str], title: str,
                path: Optional[str] = None, limit: Optional[int] = None) -> Dict[str, Any]:
    if chart_type not in CHART_TYPES:
        raise ValueError("chart_type must be one of: {}.".format(", ".join(CHART_TYPES)))
    if not y:
        raise ValueError("Give at least one value column in y.")
    rows, used = rows_of(dataset["data"], path)
    flat = [_flatten(row) for row in rows]
    keys = choose_columns(rows, None, limit=200) + [key for key in (flat[0].keys() if flat else []) if HIDDEN.search(key)]
    unknown = [key for key in [x] + y if flat and key not in flat[0] and key not in keys]
    if unknown:
        raise ValueError("Unknown column(s) {}. Available: {}.".format(", ".join(unknown), ", ".join(keys[:60])))
    for key in y:
        if flat and not all(isinstance(row.get(key), (int, float)) or row.get(key) is None for row in flat):
            raise ValueError("Column '{}' is not numeric, so it cannot be charted.".format(key))
    cap = min(limit or MAX_CHART_POINTS, MAX_CHART_POINTS)
    if chart_type == "pie":
        y = y[:1]
    points = [{"x": row.get(x), **{key: row.get(key) or 0 for key in y}} for row in flat[:cap]]
    unit = kind_of(y[0], [row.get(y[0]) for row in flat])
    return {
        "type": "chart",
        "chart": chart_type,
        "title": title,
        "dataset_id": dataset["id"],
        "path": used,
        "x": {"key": x, "label": label_of(x)},
        "series": [{"key": key, "label": label_of(key)} for key in y],
        "unit": unit if unit in ("money", "percent") else "number",
        "rows": points,
        "total_rows": len(rows),
    }


def describe(dataset: Dict[str, Any]) -> str:
    """A one-line description used when the agent's history is rebuilt."""
    try:
        rows, used = rows_of(dataset["data"])
        size = "{} rows at '{}'".format(len(rows), used) if used else "{} row(s)".format(len(rows))
    except ValueError:
        size = "data"
    args = ", ".join("{}={}".format(key, value) for key, value in (dataset.get("args") or {}).items() if key != "summary")
    return "{} = {}({}) -> {}".format(dataset["id"], dataset["tool"], args, size)


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
