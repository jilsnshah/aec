"""Exact calculations over dataset rows: filter, group, aggregate, sort.

The assistant uses this instead of doing arithmetic itself."""
from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, List, Optional

from .outputs import _flatten

OPS = {"=", "!=", ">", ">=", "<", "<=", "contains", "in"}
FUNCS = {"sum", "avg", "min", "max", "count"}


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").replace("₹", "").strip())
    except (TypeError, ValueError):
        return None


def _match(row: Dict[str, Any], rule: Dict[str, Any]) -> bool:
    field, op, wanted = rule.get("field"), rule.get("op", "="), rule.get("value")
    if op not in OPS:
        raise ValueError("Filter op must be one of {}.".format(", ".join(sorted(OPS))))
    value = row.get(field)
    if op == "contains":
        if isinstance(value, list):
            return wanted in value
        return str(wanted).lower() in str(value or "").lower()
    if op == "in":
        options = wanted if isinstance(wanted, list) else [part.strip() for part in str(wanted).split(",")]
        return str(value) in [str(option) for option in options]
    if op in ("=", "!="):
        same = str(value).lower() == str(wanted).lower() if not isinstance(value, (int, float)) else _num(value) == _num(wanted)
        return same if op == "=" else not same
    left, right = _num(value), _num(wanted)
    if left is None or right is None:
        left, right = str(value or ""), str(wanted or "")  # dates compare as ISO text
    return {">": left > right, ">=": left >= right, "<": left < right, "<=": left <= right}[op]


def run(rows: List[Dict[str, Any]], filters: List[Dict[str, Any]], group_by: List[str], metrics: List[Dict[str, str]],
        sort_by: Optional[str], descending: bool, limit: Optional[int]) -> Dict[str, Any]:
    flat = [_flatten(row) for row in rows]
    known = set().union(*[row.keys() for row in flat]) if flat else set()
    for name in [rule.get("field") for rule in filters] + list(group_by) + [m.get("field") for m in metrics if m.get("fn") != "count"]:
        if name and flat and name not in known:
            raise ValueError("Unknown field '{}'. Fields: {}.".format(name, ", ".join(sorted(known))[:1500]))
    for metric in metrics:
        if metric.get("fn") not in FUNCS:
            raise ValueError("Metric fn must be one of {}.".format(", ".join(sorted(FUNCS))))
    kept = [row for row in flat if all(_match(row, rule) for rule in filters)]
    if group_by or metrics:
        groups: "OrderedDict[tuple, List[Dict[str, Any]]]" = OrderedDict()
        for row in kept:
            groups.setdefault(tuple(row.get(key) for key in group_by), []).append(row)
        if not group_by:
            groups = OrderedDict({(): kept})
        out = []
        for key, members in groups.items():
            item: Dict[str, Any] = dict(zip(group_by, key))
            item["count"] = len(members)
            for metric in metrics:
                fn, field = metric["fn"], metric.get("field")
                name = "{}_{}".format(fn, field) if field else fn
                values = [v for v in (_num(m.get(field)) for m in members) if v is not None] if field else []
                if fn == "count":
                    item[name] = len(members) if not field else len(values)
                elif not values:
                    item[name] = None
                elif fn == "sum":
                    item[name] = round(sum(values), 4)
                elif fn == "avg":
                    item[name] = round(sum(values) / len(values), 4)
                elif fn == "min":
                    item[name] = min(values)
                else:
                    item[name] = max(values)
            out.append(item)
        result_rows = out
    else:
        result_rows = kept
    if sort_by:
        def key(row):
            value = row.get(sort_by)
            number = _num(value)
            return (number is None, number if number is not None else str(value or ""))
        result_rows = sorted(result_rows, key=key, reverse=descending)
        if descending:  # keep missing values last
            result_rows = [r for r in result_rows if r.get(sort_by) is not None] + [r for r in result_rows if r.get(sort_by) is None]
    total = len(result_rows)
    if limit:
        result_rows = result_rows[: max(1, limit)]
    return {"rows": result_rows, "total_rows": total, "matched_before_grouping": len(kept), "rows_in": len(flat)}
