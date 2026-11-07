"""Product master service."""
from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..errors import ConflictError, NotFoundError, ValidationError
from ..models import (
    MovementType,
    OrderStatus,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    SalesOrder,
    SalesOrderItem,
    StockCostLayer,
    StockMovement,
)
from ..numeric import ZERO, ZERO_MONEY, aggregate, money, quantity, require_non_negative, unit_cost
from ..database import begin_write
from . import costing
from . import reservations
from .common import (
    count_matching,
    OPEN_PURCHASE_STATUSES,
    lock_product,
    on_order_quantity_expression,
    on_order_quantity_for_product,
    on_order_quantity_map,
    pending_quantity_expression,
    pending_quantity_map,
    record_movement,
    windowed,
)

logger = logging.getLogger(__name__)

SORTABLE_FIELDS = {
    "sku": Product.sku,
    "name": Product.name,
    "mrp": Product.mrp,
    "physical_stock": Product.physical_stock,
    "created_at": Product.created_at,
    "updated_at": Product.updated_at,
}


def _stock_expression():
    """Bought less sold, per product, in SQL.

    This is the stock figure the business works with: a purchase order adds its
    units the moment it is confirmed and a sales order takes them the moment it
    is placed, whether or not anything has arrived or left the warehouse yet.
    """
    due = on_order_quantity_expression()
    bought = (
        select(func.coalesce(func.sum(due), 0))
        .select_from(PurchaseOrderItem)
        .join(PurchaseOrder, PurchaseOrderItem.purchase_order_id == PurchaseOrder.id)
        .where(
            PurchaseOrderItem.product_id == Product.id,
            PurchaseOrder.status.in_(OPEN_PURCHASE_STATUSES),
            due > 0,
        )
        .correlate(Product)
        .scalar_subquery()
    )
    pending = pending_quantity_expression()
    promised = (
        select(func.coalesce(func.sum(pending), 0))
        .select_from(SalesOrderItem)
        .join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
        .where(
            SalesOrderItem.product_id == Product.id,
            SalesOrder.status != OrderStatus.CANCELLED,
            pending > 0,
        )
        .correlate(Product)
        .scalar_subquery()
    )
    return Product.physical_stock + bought - promised


def _normalise_sku(sku: str) -> str:
    cleaned = (sku or "").strip().upper()
    if not cleaned:
        raise ValidationError("SKU is required.")
    return cleaned


def get_product(session: Session, product_id: uuid.UUID) -> Product:
    product = session.get(Product, product_id)
    if product is None:
        raise NotFoundError("Product {} does not exist.".format(product_id))
    return product


def to_view(
    product: Product,
    pending: Decimal,
    valuation: Optional[Dict[str, Decimal]] = None,
    reserved: Decimal = ZERO,
    on_order: Decimal = ZERO,
) -> Dict[str, Any]:
    """Shape a product plus its distinct stock figures for the API.

    Five numbers, all different and all kept apart:

    * physical stock -- units on the shelf
    * reserved stock -- of those, units already promised to an order
    * available stock -- physical less reserved: what can still be sold
    * pending quantity -- what customers are owed but have not received
    * net stock position -- physical less pending, negative when short

    plus ``stock``, the one figure the screens show: bought less sold, i.e.
    physical plus what suppliers still owe less what customers are still owed.
    """
    physical = Decimal(str(product.physical_stock))
    valuation = valuation or {"stock_value": ZERO_MONEY, "average_cost": Decimal("0.0000")}
    return {
        "id": product.id,
        "sku": product.sku,
        "name": product.name,
        "unit_of_measure": product.unit_of_measure,
        "mrp": product.mrp,
        "description": product.description,
        "is_active": product.is_active,
        "created_at": product.created_at,
        "updated_at": product.updated_at,
        "physical_stock": physical,
        "reserved_stock": reserved,
        "available_stock": physical - reserved,
        "pending_quantity": pending,
        "unallocated_quantity": (pending - reserved) if pending > reserved else ZERO,
        "net_stock_position": physical - pending,
        "on_order_quantity": on_order,
        "stock": physical + on_order - pending,
        "last_purchase_price": product.last_purchase_price,
        "average_cost": valuation["average_cost"],
        "stock_value": valuation["stock_value"],
    }


def product_view(session: Session, product: Product) -> Dict[str, Any]:
    """One product with its stock figures and valuation, as the API returns it."""
    pending = pending_quantity_map(session, [product.id]).get(product.id, ZERO)
    reserved = reservations.reserved_for_product(session, product.id)
    return to_view(
        product,
        pending,
        costing.stock_valuation(session, product.id),
        reserved,
        on_order_quantity_for_product(session, product.id),
    )


def _product_filter(search: Optional[str], include_inactive: bool):
    stmt = select(Product)
    if not include_inactive:
        stmt = stmt.where(Product.is_active.is_(True))
    if search:
        pattern = "%{}%".format(search.strip().lower())
        stmt = stmt.where(
            or_(
                func.lower(Product.sku).like(pattern),
                func.lower(Product.name).like(pattern),
            )
        )
    return stmt


def count_products(
    session: Session, search: Optional[str] = None, include_inactive: bool = False
) -> int:
    return count_matching(session, _product_filter(search, include_inactive))


def list_products(
    session: Session,
    search: Optional[str] = None,
    include_inactive: bool = False,
    sort_by: str = "name",
    sort_dir: str = "asc",
    limit: Optional[int] = None,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    stmt = _product_filter(search, include_inactive)
    column = _stock_expression() if sort_by == "stock" else SORTABLE_FIELDS.get(sort_by, Product.name)
    # The id tiebreak keeps pages stable when many rows share a sort value.
    stmt = stmt.order_by(column.desc() if sort_dir == "desc" else column.asc(), Product.id)

    products = list(session.execute(windowed(stmt, limit, offset)).scalars().all())
    pending = pending_quantity_map(session, [product.id for product in products])
    valuations = costing.stock_valuation_map(session)
    reserved = reservations.reserved_map(session, [product.id for product in products])
    on_order = on_order_quantity_map(session, [product.id for product in products])
    return [
        to_view(
            product,
            pending.get(product.id, ZERO),
            valuations.get(product.id),
            reserved.get(product.id, ZERO),
            on_order.get(product.id, ZERO),
        )
        for product in products
    ]


def create_product(
    session: Session,
    sku: str,
    name: str,
    unit_of_measure: str = "pcs",
    mrp: Any = 0,
    description: Optional[str] = None,
    opening_stock: Any = 0,
    opening_unit_cost: Any = 0,
) -> Product:
    """Create a product, optionally with validated opening stock.

    Opening stock is never written straight onto the product row: it goes
    through the movement ledger like every other change to physical stock, and
    it opens a FIFO cost layer at the price it was bought for so that profit on
    those units is real rather than assumed.
    """
    sku = _normalise_sku(sku)
    name = (name or "").strip()
    if not name:
        raise ValidationError("Product name is required.")

    mrp_value = require_non_negative(money(mrp, "MRP"), "MRP")
    opening = require_non_negative(quantity(opening_stock, "Opening stock"), "Opening stock")
    opening_cost = require_non_negative(
        unit_cost(opening_unit_cost, "Opening stock unit cost"), "Opening stock unit cost"
    )

    begin_write(session)
    existing = session.execute(select(Product.id).where(Product.sku == sku)).first()
    if existing is not None:
        raise ConflictError("A product with SKU '{}' already exists.".format(sku))

    product = Product(
        sku=sku,
        name=name,
        unit_of_measure=(unit_of_measure or "pcs").strip() or "pcs",
        mrp=mrp_value,
        description=(description or None),
        physical_stock=ZERO,
    )
    session.add(product)

    try:
        session.flush()
        if opening > ZERO:
            record_movement(
                session,
                product,
                MovementType.OPENING_STOCK,
                opening,
                reference_type="product",
                reference_id=product.id,
                note="Opening stock recorded at product creation",
            )
            costing.open_cost_layer(
                session,
                product,
                opening,
                opening_cost,
                MovementType.OPENING_STOCK,
                product.id,
                "Opening stock",
            )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        # Lost the race against a concurrent create with the same SKU.
        raise ConflictError("A product with SKU '{}' already exists.".format(sku)) from exc
    except Exception:
        session.rollback()
        raise

    logger.info("Created product %s (%s) with opening stock %s", product.sku, product.id, opening)
    return product


def update_product(session: Session, product_id: uuid.UUID, changes: Dict[str, Any]) -> Product:
    """Update editable product fields.

    ``physical_stock`` is deliberately absent: stock only moves through
    validated stock-in operations and order fulfilment.
    """
    begin_write(session)
    product = get_product(session, product_id)

    if "sku" in changes and changes["sku"] is not None:
        new_sku = _normalise_sku(changes["sku"])
        if new_sku != product.sku:
            clash = session.execute(
                select(Product.id).where(Product.sku == new_sku, Product.id != product.id)
            ).first()
            if clash is not None:
                raise ConflictError("A product with SKU '{}' already exists.".format(new_sku))
            product.sku = new_sku

    if "name" in changes and changes["name"] is not None:
        name = changes["name"].strip()
        if not name:
            raise ValidationError("Product name is required.")
        product.name = name

    if "unit_of_measure" in changes and changes["unit_of_measure"] is not None:
        uom = changes["unit_of_measure"].strip()
        if not uom:
            raise ValidationError("Unit of measure is required.")
        product.unit_of_measure = uom

    if "mrp" in changes and changes["mrp"] is not None:
        product.mrp = require_non_negative(money(changes["mrp"], "MRP"), "MRP")

    if "description" in changes:
        product.description = changes["description"] or None

    if "is_active" in changes and changes["is_active"] is not None:
        product.is_active = bool(changes["is_active"])

    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("That SKU is already in use.") from exc
    except Exception:
        session.rollback()
        raise
    return product


def archive_product(session: Session, product_id: uuid.UUID) -> Product:
    """Soft-delete a product. Historical orders and movements are untouched."""
    begin_write(session)
    product = get_product(session, product_id)
    product.is_active = False
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise
    logger.info("Archived product %s (%s)", product.sku, product.id)
    return product


def product_inventory(session: Session, product_id: uuid.UUID) -> Dict[str, Any]:
    """Full inventory picture for one product, including its audit trail."""
    product = get_product(session, product_id)
    pending = pending_quantity_map(session, [product.id]).get(product.id, ZERO)

    movements = list(
        session.execute(
            select(StockMovement)
            .where(StockMovement.product_id == product.id)
            .order_by(StockMovement.created_at.desc(), StockMovement.id.desc())
            .limit(200)
        )
        .scalars()
        .all()
    )
    ledger_balance = session.execute(
        select(func.coalesce(func.sum(StockMovement.quantity_change), 0)).where(
            StockMovement.product_id == product.id
        )
    ).scalar_one()

    valuation = costing.stock_valuation(session, product.id)
    view = to_view(
        product,
        pending,
        valuation,
        reservations.reserved_for_product(session, product.id),
        on_order_quantity_for_product(session, product.id),
    )
    view["ledger_balance"] = aggregate(ledger_balance)
    view["movements"] = movements
    view["cost_layers"] = list(
        session.execute(
            select(StockCostLayer)
            .where(StockCostLayer.product_id == product.id, StockCostLayer.quantity_remaining > 0)
            .order_by(StockCostLayer.created_at.asc())
        )
        .scalars()
        .all()
    )
    return view


def has_history(session: Session, product_id: uuid.UUID) -> bool:
    """True when a product is referenced by orders or stock movements."""
    in_orders = session.execute(
        select(SalesOrderItem.id).where(SalesOrderItem.product_id == product_id).limit(1)
    ).first()
    if in_orders is not None:
        return True
    in_movements = session.execute(
        select(StockMovement.id).where(StockMovement.product_id == product_id).limit(1)
    ).first()
    return in_movements is not None
