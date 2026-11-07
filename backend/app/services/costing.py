"""FIFO inventory costing.

Every quantity that enters physical stock opens a :class:`StockCostLayer` at the
price it was bought for. Every quantity that leaves draws from the oldest open
layers. The cost of goods sold is therefore exact for each delivered unit, and
the system can say which purchase paid for the units a customer received.

Invariant, asserted by the tests: for each product, the sum of
``quantity_remaining`` across its layers equals ``Product.physical_stock``.
"""
from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    MovementType,
    Product,
    StockAllocation,
    StockCostLayer,
    StockLayerConsumption,
)
from ..numeric import ZERO, ZERO_MONEY, aggregate, money, quantity, unit_cost

logger = logging.getLogger(__name__)


def open_cost_layer(
    session: Session,
    product: Product,
    received_quantity: Decimal,
    purchase_unit_cost: Decimal,
    source: MovementType,
    source_id: Optional[uuid.UUID] = None,
    note: Optional[str] = None,
) -> StockCostLayer:
    """Record a batch of stock bought at one price."""
    layer = StockCostLayer(
        product_id=product.id,
        source=source,
        source_id=source_id,
        unit_cost=purchase_unit_cost,
        quantity=received_quantity,
        quantity_remaining=received_quantity,
        note=note,
    )
    session.add(layer)
    session.flush()
    if purchase_unit_cost > ZERO_MONEY:
        product.last_purchase_price = purchase_unit_cost
    return layer


def _open_layers(session: Session, product_id: uuid.UUID) -> List[StockCostLayer]:
    """Layers with stock left, oldest first."""
    return list(
        session.execute(
            select(StockCostLayer)
            .where(
                StockCostLayer.product_id == product_id,
                StockCostLayer.quantity_remaining > 0,
            )
            .order_by(StockCostLayer.created_at.asc(), StockCostLayer.id.asc())
        )
        .scalars()
        .all()
    )


def consume_cost_layers(
    session: Session,
    product: Product,
    allocation: StockAllocation,
    consumed_quantity: Decimal,
) -> Decimal:
    """Draw ``consumed_quantity`` from the oldest layers and cost the allocation.

    Returns the total cost of goods sold, which is also written onto the
    allocation. Callers hold the product row lock, so layers are drawn down by
    one transaction at a time.
    """
    remaining = consumed_quantity
    total_cost = ZERO_MONEY

    for layer in _open_layers(session, product.id):
        if remaining <= ZERO:
            break
        take = layer.quantity_remaining if layer.quantity_remaining < remaining else remaining
        if take <= ZERO:
            continue
        line_cost = money(take * layer.unit_cost)
        layer.quantity_remaining = layer.quantity_remaining - take
        session.add(
            StockLayerConsumption(
                stock_allocation_id=allocation.id,
                stock_cost_layer_id=layer.id,
                quantity=take,
                unit_cost=layer.unit_cost,
                cost_amount=line_cost,
            )
        )
        total_cost = total_cost + line_cost
        remaining = remaining - take

    if remaining > ZERO:
        # Should be unreachable: stock is only ever allocated after it has been
        # added, so a layer always exists to cover it. Reaching here means the
        # layers and the ledger have diverged (for example, stock that predates
        # cost tracking). Cost the shortfall at the last known purchase price
        # rather than failing the delivery, and make the gap loud in the log.
        fallback = product.last_purchase_price or Decimal("0.0000")
        logger.warning(
            "Cost layers short by %s for product %s (%s); costing the shortfall at %s per unit. "
            "Stock valuation for this product should be reviewed.",
            remaining,
            product.sku,
            product.id,
            fallback,
        )
        layer = open_cost_layer(
            session,
            product,
            remaining,
            fallback,
            MovementType.ADJUSTMENT,
            None,
            "Auto-created to cover a cost-layer shortfall",
        )
        line_cost = money(remaining * layer.unit_cost)
        layer.quantity_remaining = ZERO
        session.add(
            StockLayerConsumption(
                stock_allocation_id=allocation.id,
                stock_cost_layer_id=layer.id,
                quantity=remaining,
                unit_cost=layer.unit_cost,
                cost_amount=line_cost,
            )
        )
        total_cost = total_cost + line_cost

    allocation.cost_amount = total_cost
    session.flush()
    return total_cost


def stock_valuation(session: Session, product_id: uuid.UUID) -> Dict[str, Decimal]:
    """Value of the stock on hand, and the average cost of a unit of it."""
    row = session.execute(
        select(
            func.coalesce(func.sum(StockCostLayer.quantity_remaining), 0),
            func.coalesce(
                func.sum(StockCostLayer.quantity_remaining * StockCostLayer.unit_cost), 0
            ),
        ).where(StockCostLayer.product_id == product_id)
    ).one()
    on_hand = aggregate(row[0])
    value = money(row[1] or 0)
    average = unit_cost(value / on_hand) if on_hand > ZERO else Decimal("0.0000")
    return {"layer_quantity": on_hand, "stock_value": value, "average_cost": average}


def stock_valuation_map(session: Session) -> Dict[uuid.UUID, Dict[str, Decimal]]:
    """Valuation for every product that has open layers, keyed by product id."""
    rows = session.execute(
        select(
            StockCostLayer.product_id,
            func.coalesce(func.sum(StockCostLayer.quantity_remaining), 0),
            func.coalesce(
                func.sum(StockCostLayer.quantity_remaining * StockCostLayer.unit_cost), 0
            ),
        )
        .where(StockCostLayer.quantity_remaining > 0)
        .group_by(StockCostLayer.product_id)
    ).all()
    result: Dict[uuid.UUID, Dict[str, Decimal]] = {}
    for product_id, on_hand_raw, value_raw in rows:
        on_hand = aggregate(on_hand_raw)
        value = money(value_raw or 0)
        result[product_id] = {
            "layer_quantity": on_hand,
            "stock_value": value,
            "average_cost": unit_cost(value / on_hand) if on_hand > ZERO else Decimal("0.0000"),
        }
    return result


def total_stock_value(session: Session) -> Decimal:
    total = session.execute(
        select(
            func.coalesce(
                func.sum(StockCostLayer.quantity_remaining * StockCostLayer.unit_cost), 0
            )
        )
    ).scalar_one()
    return money(total or 0)


def cost_trail(session: Session, allocation_ids: Sequence[uuid.UUID]) -> Dict[uuid.UUID, List[Dict[str, Any]]]:
    """Which layers paid for each allocation, keyed by allocation id."""
    if not allocation_ids:
        return {}
    rows = session.execute(
        select(StockLayerConsumption, StockCostLayer)
        .join(StockCostLayer, StockLayerConsumption.stock_cost_layer_id == StockCostLayer.id)
        .where(StockLayerConsumption.stock_allocation_id.in_(list(allocation_ids)))
        .order_by(StockLayerConsumption.created_at)
    ).all()
    trail: Dict[uuid.UUID, List[Dict[str, Any]]] = {}
    for consumption, layer in rows:
        trail.setdefault(consumption.stock_allocation_id, []).append(
            {
                "quantity": consumption.quantity,
                "unit_cost": consumption.unit_cost,
                "cost_amount": consumption.cost_amount,
                "layer_source": layer.source,
                "layer_source_id": layer.source_id,
                "layer_created_at": layer.created_at,
            }
        )
    return trail


def layers_match_physical_stock(session: Session, product: Product) -> Tuple[bool, Decimal]:
    """Check the costing invariant for one product. Used by the tests."""
    on_hand = stock_valuation(session, product.id)["layer_quantity"]
    return on_hand == quantity(product.physical_stock), on_hand
