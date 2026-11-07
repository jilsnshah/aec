"""Helpers for the fixed-scale decimal arithmetic used across the domain."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Union

from .errors import ValidationError

QUANTITY_EXPONENT = Decimal("0.001")
MONEY_EXPONENT = Decimal("0.01")
UNIT_COST_EXPONENT = Decimal("0.0001")
PERCENT_EXPONENT = Decimal("0.01")

ZERO = Decimal("0.000")
ZERO_MONEY = Decimal("0.00")
HUNDRED = Decimal("100")

Numberish = Union[Decimal, int, float, str]


def _to_decimal(value: Numberish, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValidationError("{} is not a valid number.".format(field)) from exc


def quantity(value: Numberish, field: str = "quantity") -> Decimal:
    """Normalise any numeric input to the canonical 3-decimal quantity scale."""
    decimal_value = _to_decimal(value, field)
    if not decimal_value.is_finite():
        raise ValidationError("{} must be a finite number.".format(field))
    return decimal_value.quantize(QUANTITY_EXPONENT, rounding=ROUND_HALF_UP)


def money(value: Numberish, field: str = "amount") -> Decimal:
    decimal_value = _to_decimal(value, field)
    if not decimal_value.is_finite():
        raise ValidationError("{} must be a finite number.".format(field))
    return decimal_value.quantize(MONEY_EXPONENT, rounding=ROUND_HALF_UP)


def unit_cost(value: Numberish, field: str = "unit cost") -> Decimal:
    """Normalise a per-unit price or cost to four decimal places."""
    decimal_value = _to_decimal(value, field)
    if not decimal_value.is_finite():
        raise ValidationError("{} must be a finite number.".format(field))
    return decimal_value.quantize(UNIT_COST_EXPONENT, rounding=ROUND_HALF_UP)


def percent(value: Numberish, field: str = "percentage") -> Decimal:
    """Normalise a percentage and keep it within 0-100."""
    decimal_value = _to_decimal(value, field)
    if not decimal_value.is_finite():
        raise ValidationError("{} must be a finite number.".format(field))
    decimal_value = decimal_value.quantize(PERCENT_EXPONENT, rounding=ROUND_HALF_UP)
    if decimal_value < 0 or decimal_value > HUNDRED:
        raise ValidationError("{} must be between 0 and 100.".format(field))
    return decimal_value


def net_of_discount(price: Decimal, discount_percent: Decimal) -> Decimal:
    """Apply a percentage discount to a unit price."""
    return unit_cost(price * (HUNDRED - discount_percent) / HUNDRED)


def aggregate(value: Numberish) -> Decimal:
    """Normalise a SQL aggregate (which may be None, int or float) to a quantity."""
    if value is None:
        return ZERO
    return quantity(value, "total")


def require_positive(value: Decimal, field: str) -> Decimal:
    if value <= ZERO:
        raise ValidationError("{} must be greater than zero.".format(field))
    return value


def require_non_negative(value: Decimal, field: str) -> Decimal:
    if value < ZERO:
        raise ValidationError("{} cannot be negative.".format(field))
    return value
