"""Bringing a business's existing data in from TallyPrime.

Reads, through TallyPrime's own XML interface (never its data files):

* stock items -> products, with today's quantity as opening stock at Tally's
  closing rate (the FIFO cost basis), and the MRP where Tally has one;
* ledgers under Sundry Debtors -> customers;
* ledgers under Sundry Creditors -> suppliers.

It goes through the ordinary services, so every rule applies, and it is safe
to run again: a product, customer or supplier that already exists (by name,
or by code for products) is left alone.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Customer, Product, Supplier
from . import customers as customer_service
from . import products as product_service
from . import suppliers as supplier_service
from .tally import TallyClient

logger = logging.getLogger(__name__)

STOCK_FIELDS = "Name, Parent, BaseUnits, ClosingBalance, ClosingRate, ClosingValue, MRPDetails, StandardSellingPrice, PartNo, Alias"
PARTY_FIELDS = "Name, Parent, LedgerPhone, LedgerMobile, Email, LedgerContact, Address, PartyGSTIN, LedGSTRegDetails, IncomeTaxNumber"
_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


@dataclass
class Report:
    products: int = 0
    customers: int = 0
    suppliers: int = 0
    skipped: int = 0
    vouchers: Dict[str, int] = field(default_factory=dict)
    problems: List[str] = field(default_factory=list)


def _number(text: Optional[str]) -> Decimal:
    """'1,250.50 Nos', '-12000.00', '450.00/Nos' -> Decimal (0 when absent)."""
    match = _NUMBER.search(text or "")
    if not match:
        return Decimal("0")
    try:
        return Decimal(match.group(0).replace(",", ""))
    except InvalidOperation:
        return Decimal("0")


def _texts(node, path: str) -> List[str]:
    return [element.text.strip() for element in node.iter(path) if element.text and element.text.strip()]


def _first(node, *tags: str) -> Optional[str]:
    for tag in tags:
        values = _texts(node, tag)
        if values:
            return values[0]
    return None


def _items(client: TallyClient, object_type: str, fetch: str, formula: Optional[str] = None):
    root = client._collection("AECImport", object_type, fetch, formula)
    tag = object_type.upper().replace(" ", "")
    return list(root.iter(tag))


def read_stock_items(client: TallyClient) -> List[Dict[str, Any]]:
    rows = []
    for node in _items(client, "Stock Item", STOCK_FIELDS):
        name = (node.get("NAME") or _first(node, "NAME") or "").strip()
        if not name:
            continue
        unit = (_first(node, "BASEUNITS") or "Nos").strip()
        quantity = _number(_first(node, "CLOSINGBALANCE"))
        rate = abs(_number(_first(node, "CLOSINGRATE")))
        value = abs(_number(_first(node, "CLOSINGVALUE")))
        if not rate and quantity > 0 and value:
            rate = (value / quantity).quantize(Decimal("0.0001"))
        mrp = _number(_first(node, "MRPRATE", "STANDARDSELLINGPRICE", "RATE"))
        aliases = [text for text in _texts(node, "NAME") if text != name]
        rows.append({
            "name": name,
            "code": _first(node, "PARTNO") or (aliases[0] if aliases else None),
            "group": _first(node, "PARENT"),
            "unit": unit,
            "quantity": quantity,
            "rate": rate,
            "mrp": abs(mrp),
        })
    return rows


def read_parties(client: TallyClient, group_function: str) -> List[Dict[str, Any]]:
    """Ledgers that belong (directly or through sub-groups) to Debtors or Creditors."""
    rows = []
    for node in _items(client, "Ledger", PARTY_FIELDS, "$$IsBelongsTo:$${}".format(group_function)):
        name = (node.get("NAME") or _first(node, "NAME") or "").strip()
        if not name:
            continue
        address = ", ".join(_texts(node, "ADDRESS"))
        gstin = _first(node, "PARTYGSTIN", "GSTIN")
        rows.append({
            "name": name,
            "group": _first(node, "PARENT"),
            "phone": _first(node, "LEDGERMOBILE", "LEDGERPHONE"),
            "email": _first(node, "EMAIL"),
            "contact": _first(node, "LEDGERCONTACT"),
            "address": address or None,
            "gstin": gstin,
            "pan": _first(node, "INCOMETAXNUMBER"),
        })
    return rows


def count_vouchers(client: TallyClient) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for node in _items(client, "Voucher", "VoucherTypeName"):
        kind = _first(node, "VOUCHERTYPENAME") or "?"
        counts[kind] = counts.get(kind, 0) + 1
    return counts


def _sku(session: Session, row: Dict[str, Any], used: set) -> str:
    base = (row["code"] or re.sub(r"[^A-Z0-9]+", "-", row["name"].upper()).strip("-"))[:28] or "ITEM"
    candidate, n = base, 1
    while candidate in used or session.execute(select(Product.id).where(Product.sku == candidate)).first():
        n += 1
        candidate = "{}-{}".format(base[:24], n)
    used.add(candidate)
    return candidate


def _notes(row: Dict[str, Any]) -> str:
    parts = ["Imported from Tally ({})".format(row.get("group") or "ledger")]
    if row.get("gstin"):
        parts.append("GSTIN {}".format(row["gstin"]))
    if row.get("pan"):
        parts.append("PAN {}".format(row["pan"]))
    return " · ".join(parts)


def run(session: Session, client: TallyClient, dry_run: bool = False) -> Report:
    report = Report()
    stock = read_stock_items(client)
    debtors = read_parties(client, "GroupSundryDebtors")
    creditors = read_parties(client, "GroupSundryCreditors")
    try:
        report.vouchers = count_vouchers(client)
    except Exception as exc:  # counting is informative only
        report.problems.append("Could not count vouchers: {}".format(exc))
    if dry_run:
        report.products, report.customers, report.suppliers = len(stock), len(debtors), len(creditors)
        return report

    used: set = set()
    for row in stock:
        exists = session.execute(select(Product.id).where(func.lower(Product.name) == row["name"].lower())).first()
        if exists:
            report.skipped += 1
            continue
        try:
            product_service.create_product(
                session,
                sku=_sku(session, row, used),
                name=row["name"][:255],
                unit_of_measure=(row["unit"] or "Nos")[:32],
                mrp=row["mrp"],
                opening_stock=row["quantity"] if row["quantity"] > 0 else 0,
                opening_unit_cost=row["rate"] if row["quantity"] > 0 else 0,
                description="Tally group: {}".format(row["group"]) if row["group"] else None,
            )
            report.products += 1
        except Exception as exc:
            session.rollback()
            report.problems.append("Product '{}': {}".format(row["name"], exc))

    for row in debtors:
        if session.execute(select(Customer.id).where(func.lower(Customer.name) == row["name"].lower())).first():
            report.skipped += 1
            continue
        try:
            customer_service.create_customer(
                session, name=row["name"], phone=row["phone"], email=row["email"],
                address=row["address"], notes=_notes(row),
            )
            report.customers += 1
        except Exception as exc:
            session.rollback()
            report.problems.append("Customer '{}': {}".format(row["name"], exc))

    for row in creditors:
        if session.execute(select(Supplier.id).where(func.lower(Supplier.name) == row["name"].lower())).first():
            report.skipped += 1
            continue
        try:
            supplier_service.create_supplier(
                session, name=row["name"], contact_person=row["contact"], phone=row["phone"],
                email=row["email"], address=row["address"], notes=_notes(row),
            )
            report.suppliers += 1
        except Exception as exc:
            session.rollback()
            report.problems.append("Supplier '{}': {}".format(row["name"], exc))
    return report
