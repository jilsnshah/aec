"""The single place where a selling price is worked out.

Both sales orders and customer enquiries price their lines through here, so a
deal negotiated on an enquiry and an order typed in directly cannot drift apart.

    selling price per unit = MRP x (1 - discount percent / 100)
    line total             = selling price per unit x quantity

Unit prices keep four decimals so a discount such as 12.5% off 1,999 is not
distorted before it is multiplied out; line totals and every amount shown to a
customer are rounded to two decimals with ROUND_HALF_UP.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Iterable

from ..config import get_settings
from ..errors import ValidationError
from ..numeric import (
    HUNDRED,
    ZERO,
    ZERO_MONEY,
    money,
    net_of_discount,
    percent,
    quantity as to_quantity,
    require_non_negative,
    require_positive,
    unit_cost,
)


def selling_price(list_price: Decimal, discount_percent: Decimal) -> Decimal:
    """Apply a percentage discount to a list price. Never returns a negative."""
    price = net_of_discount(list_price, discount_percent)
    return price if price > ZERO_MONEY else Decimal("0.0000")


def line_total(unit_price: Decimal, line_quantity: Decimal) -> Decimal:
    return money(unit_price * line_quantity)


def quote_line(
    mrp: Any,
    line_quantity: Any,
    discount_percent: Any = 0,
    field_prefix: str = "Line",
) -> Dict[str, Decimal]:
    """Price one line from an MRP, a quantity and a discount.

    The MRP must come from the product master: this function is given it, it
    never takes a price from the caller's client.
    """
    mrp_value = require_non_negative(
        unit_cost(mrp, "{} MRP".format(field_prefix)), "{} MRP".format(field_prefix)
    )
    qty = require_positive(
        to_quantity(line_quantity, "{} quantity".format(field_prefix)),
        "{} quantity".format(field_prefix),
    )
    discount = percent(discount_percent or 0, "{} discount".format(field_prefix))

    price = selling_price(mrp_value, discount)
    if price <= ZERO_MONEY and not get_settings().allow_zero_price_lines:
        raise ValidationError(
            "{} would be free at a {}% discount, which this business does not "
            "allow. Set ALLOW_ZERO_PRICE_LINES=true to permit it.".format(field_prefix, discount)
        )

    return {
        "mrp_snapshot": mrp_value,
        "quantity": qty,
        "discount_percent": discount,
        "quoted_unit_price": price,
        "line_total": line_total(price, qty),
    }


def sum_line_totals(lines: Iterable[Dict[str, Any]]) -> Decimal:
    """Total of already-priced lines, before tax."""
    return money(sum((Decimal(str(line["line_total"])) for line in lines), ZERO_MONEY))


def discount_amount(mrp: Decimal, price: Decimal, line_quantity: Decimal) -> Decimal:
    """How much the discount took off this line."""
    return money((mrp - price) * line_quantity)


__all__ = [
    "HUNDRED",
    "ZERO",
    "discount_amount",
    "line_total",
    "quote_line",
    "selling_price",
    "sum_line_totals",
]
