"""Units of measure.

A product is stocked in one base unit (bag, piece, kg, cft...) and may be
bought and sold in any number of other units, each a fixed multiple of the
base: 1 tonne = 20 bags, 1 brass = 100 cft, 1 bundle = 10 pieces.

Document lines (enquiries, sales orders, purchase orders) can be entered in
any of those units. They are converted to the base unit as they come in, so
stock, reservations, FIFO costing and Tally all keep working in one unit; the
line remembers the unit and factor it was entered in, for display and PDFs.
"""
from __future__ import annotations

import re
import uuid
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import NotFoundError, ValidationError
from ..models import Product, ProductUnit

ONE = Decimal("1")

#: Common ways people write the same unit.
SYNONYMS = {
    "ton": "tonne", "tons": "tonne", "tonnes": "tonne", "mt": "tonne", "metric ton": "tonne", "t": "tonne",
    "pc": "pcs", "piece": "pcs", "pieces": "pcs", "nos": "pcs", "no": "pcs", "number": "pcs", "unit": "pcs", "units": "pcs",
    "kgs": "kg", "kilo": "kg", "kilos": "kg", "kilogram": "kg", "kilograms": "kg",
    "ltr": "litre", "liter": "litre", "litres": "litre", "liters": "litre", "l": "litre",
    "mtr": "metre", "meter": "metre", "metres": "metre", "meters": "metre", "m": "metre",
    "sq ft": "sqft", "sq.ft": "sqft", "square feet": "sqft", "cu ft": "cft", "cubic feet": "cft",
    "quintal": "quintal", "qtl": "quintal",
}


def norm(name: Optional[str]) -> str:
    text = re.sub(r"\s+", " ", (name or "").strip().lower()).rstrip(".")
    text = SYNONYMS.get(text, text)
    if len(text) > 3 and text.endswith("es") and text[:-2] in SYNONYMS.values():
        text = text[:-2]
    elif len(text) > 2 and text.endswith("s") and not text.endswith("ss"):
        text = text[:-1]
    return SYNONYMS.get(text, text)


def units_of(session: Session, product: Product) -> List[Dict[str, Any]]:
    """The base unit first, then the others, smallest first."""
    rows = session.execute(select(ProductUnit).where(ProductUnit.product_id == product.id).order_by(ProductUnit.factor)).scalars().all()
    return [{"name": product.unit_of_measure, "factor": 1.0, "base": True, "for_sales": True, "for_purchase": True}] + [
        {"name": u.name, "factor": float(u.factor), "base": False, "for_sales": u.for_sales, "for_purchase": u.for_purchase} for u in rows
    ]


def find(session: Session, product: Product, name: Optional[str], purpose: str = "sales") -> Tuple[Optional[str], Decimal]:
    """The unit called ``name`` on this product, as (stored name, factor).
    The base unit comes back as (None, 1)."""
    if not name or norm(name) == norm(product.unit_of_measure):
        return None, ONE
    wanted = norm(name)
    for unit in session.execute(select(ProductUnit).where(ProductUnit.product_id == product.id)).scalars():
        if norm(unit.name) == wanted:
            if purpose == "sales" and not unit.for_sales or purpose == "purchase" and not unit.for_purchase:
                raise ValidationError("{} is not {} in {}.".format(product.name, "sold" if purpose == "sales" else "bought", unit.name))
            return unit.name, Decimal(unit.factor)
    names = [u["name"] for u in units_of(session, product)]
    raise ValidationError("{} is counted in {}; '{}' is not one of its units. Add it under the product's units first.".format(
        product.name, " or ".join(names), name))


def _fmt(value: Decimal) -> str:
    return "{:f}".format(value.normalize()) if value == value.to_integral() else "{:f}".format(value.quantize(Decimal("0.001")).normalize())


def check_whole(product: Product, base_quantity: Decimal, unit: Optional[str] = None, quantity: Optional[Decimal] = None) -> None:
    if product.whole_units and base_quantity != base_quantity.to_integral():
        entered = " ({} {} is {} {})".format(_fmt(quantity), unit, _fmt(base_quantity), product.unit_of_measure) if unit and quantity is not None else ""
        raise ValidationError("{} is counted in whole {}{}.".format(product.name, product.unit_of_measure, entered))


def apply(session: Session, lines: List[Dict[str, Any]], quantity_key: str, price_key: Optional[str] = None,
          purpose: str = "sales") -> Dict[uuid.UUID, Tuple[Optional[str], Decimal]]:
    """Convert lines entered in other units to the base unit, in place.

    A line with ``unit`` has its quantity (and price, if ``price_key``) in that
    unit; both are converted to the base unit. A line that already carries
    ``unit_factor`` is in base units already (for example a converted
    enquiry) and is left as it is. Returns the unit of each product's line.
    """
    found: Dict[uuid.UUID, Tuple[Optional[str], Decimal]] = {}
    for line in lines:
        try:
            product_id = uuid.UUID(str(line["product_id"]))
        except (KeyError, ValueError, TypeError):
            continue
        product = session.get(Product, product_id)
        if product is None:
            raise NotFoundError("Product not found.")
        if "unit_factor" in line and line.get("unit_factor") is not None:
            unit, factor = (line.get("unit") or None), Decimal(str(line["unit_factor"]))
        else:
            unit, factor = find(session, product, line.get("unit"), purpose)
            if factor != ONE and line.get(quantity_key) is not None:
                try:
                    entered = Decimal(str(line[quantity_key]))
                except InvalidOperation:
                    raise ValidationError("Quantity must be a number.")
                line[quantity_key] = (entered * factor).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
                check_whole(product, line[quantity_key], unit, entered)
                if price_key and line.get(price_key) is not None:
                    line[price_key] = (Decimal(str(line[price_key])) / factor).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        if factor == ONE and line.get(quantity_key) is not None:
            try:
                check_whole(product, Decimal(str(line[quantity_key])))
            except InvalidOperation:
                raise ValidationError("Quantity must be a number.")
        line["unit"], line["unit_factor"] = unit, factor
        previous = found.get(product_id)
        # The same product twice in different units is merged in base units.
        found[product_id] = (unit, factor) if previous is None or previous == (unit, factor) else (None, ONE)
    return found


def stamp(item: Any, found: Dict[uuid.UUID, Tuple[Optional[str], Decimal]]) -> None:
    unit, factor = found.get(item.product_id, (None, ONE))
    item.unit, item.unit_factor = unit, factor


def describe(quantity: Decimal, product: Product, unit: Optional[str], factor: Optional[Decimal]) -> str:
    """'2 tonne (40 bags)' or '40 bags'."""
    base = "{} {}".format(_fmt(Decimal(quantity)), product.unit_of_measure)
    if not unit or not factor or Decimal(factor) == ONE:
        return base
    return "{} {} ({})".format(_fmt(Decimal(quantity) / Decimal(factor)), unit, base)


def product_card(session: Session, product: Product, customer_id: Optional[uuid.UUID] = None) -> Dict[str, Any]:
    """Everything an agent may tell a customer about a product: what it is,
    its details, the units it is sold in, this customer's price and stock."""
    from . import pricelists, reservations

    price = None
    try:
        price = pricelists.resolve(session, customer_id, [{"product_id": product.id, "quantity": "1"}])["lines"][0]["net_price"]
    except Exception:  # pragma: no cover - pricing must never break a description
        price = float(product.mrp or 0)
    free = float(product.physical_stock - reservations.reserved_map(session, [product.id]).get(product.id, 0))
    sold_in = [u for u in units_of(session, product) if u["for_sales"]]
    return {
        "id": str(product.id), "code": product.sku, "name": product.name, "brand": product.brand, "category": product.category,
        "description": product.description, "details": product.specs or [],
        "base_unit": product.unit_of_measure,
        "sold_in": [{"unit": u["name"], "holds": "{:g} {}".format(u["factor"], product.unit_of_measure)} if not u["base"] else {"unit": u["name"]} for u in sold_in],
        "usual_unit": product.sales_unit or product.unit_of_measure, "whole_units_only": product.whole_units,
        "price_per_base_unit": price, "mrp": float(product.mrp or 0), "gst_rate": float(product.gst_rate) if product.gst_rate is not None else None,
        "hsn": product.hsn_code, "weight_kg_per_unit": float(product.weight_kg) if product.weight_kg is not None else None,
        "in_stock": free > 0, "available_now": max(0.0, free),
    }
