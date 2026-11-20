"""Warehouses (godowns, yards, shops, site stores) and transfers between them.

Stock in each warehouse is the sum of the open FIFO cost layers tagged with
it, so the per-warehouse figures always add up to the product's physical stock.

A transfer follows the usual industry flow:

1. **Draft** -- from, to, products, quantities, and the costs of moving them
   (freight, loading, unloading, toll...).
2. **Dispatch** -- the goods leave the source: its oldest layers are drawn
   (FIFO) and the same units, at the same cost, sit in the system "In transit"
   warehouse. Nothing is lost from the books while the truck is on the road.
3. **Receive** -- what arrived goes into the destination. The transfer costs
   are spread over the lines (by quantity, value or weight) and added to the
   cost of the units received, so the destination's stock is valued at what
   it really cost to have it there (landed cost). Anything that did not arrive
   is written off as lost in transit.

A transfer in transit can be cancelled: the goods go back to the source at
their original cost.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..database import begin_write
from ..errors import ConflictError, NotFoundError, ValidationError
from ..models import (
    MovementType,
    Product,
    StockCostLayer,
    StockTransfer,
    StockTransferCost,
    StockTransferItem,
    User,
    Warehouse,
)
from ..numeric import ZERO, ZERO_MONEY, money, quantity as to_quantity
from .common import lock_product, next_document_number, record_movement

KINDS = {"godown": "Godown", "yard": "Yard", "shop": "Shop", "site": "Site store"}
COST_KINDS = {"freight": "Freight", "loading": "Loading", "unloading": "Unloading", "toll": "Toll", "insurance": "Insurance", "other": "Other"}
METHODS = {"quantity": "By quantity", "value": "By value", "weight": "By weight"}
TRANSFER_COUNTER = "stock_transfer"


# ---------------------------------------------------------------------------
# Warehouses
# ---------------------------------------------------------------------------


def _system(session: Session, kind: str) -> Warehouse:
    if kind == "transit":
        row = session.execute(select(Warehouse).where(Warehouse.kind == "transit")).scalars().first()
        if row is None:
            row = Warehouse(code="TRANSIT", name="In transit", kind="transit", is_default=False)
            session.add(row)
            session.flush()
        return row
    row = session.execute(select(Warehouse).where(Warehouse.is_default.is_(True))).scalars().first()
    if row is None:
        row = session.execute(select(Warehouse).where(Warehouse.kind != "transit", Warehouse.is_active.is_(True)).order_by(Warehouse.created_at)).scalars().first()
        if row is None:
            row = Warehouse(code="MAIN", name="Main godown", kind="godown", is_default=True)
            session.add(row)
        row.is_default = True
        session.flush()
    return row


def default_id(session: Session) -> uuid.UUID:
    """The warehouse used whenever none is chosen."""
    return _system(session, "default").id


def transit_id(session: Session) -> uuid.UUID:
    return _system(session, "transit").id


def resolve(session: Session, warehouse_id: Any) -> uuid.UUID:
    """A chosen, usable warehouse -- or the default one when none is chosen."""
    if warehouse_id in (None, ""):
        return default_id(session)
    try:
        row = session.get(Warehouse, uuid.UUID(str(warehouse_id)))
    except ValueError:
        row = None
    if row is None:
        raise NotFoundError("Warehouse not found.")
    if row.kind == "transit":
        raise ValidationError("Goods in transit are moved by receiving the transfer.")
    if not row.is_active:
        raise ValidationError("{} is closed.".format(row.name))
    return row.id


def on_hand(session: Session, product_id: uuid.UUID, warehouse_id: uuid.UUID) -> Decimal:
    return Decimal(session.execute(
        select(func.coalesce(func.sum(StockCostLayer.quantity_remaining), 0))
        .where(StockCostLayer.product_id == product_id, StockCostLayer.warehouse_id == warehouse_id)
    ).scalar_one())


def _view(row: Warehouse, figures: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    figures = figures or {}
    return {
        "id": row.id, "code": row.code, "name": row.name, "kind": row.kind, "kind_label": KINDS.get(row.kind, "In transit"),
        "address": row.address, "contact": row.contact, "tally_godown": row.tally_godown, "notes": row.notes,
        "is_default": row.is_default, "is_active": row.is_active,
        "products": int(figures.get("products", 0)), "quantity": float(figures.get("quantity", 0)), "value": float(figures.get("value", 0)),
    }


def _figures(session: Session) -> Dict[uuid.UUID, Dict[str, Any]]:
    rows = session.execute(
        select(StockCostLayer.warehouse_id, func.count(func.distinct(StockCostLayer.product_id)),
               func.sum(StockCostLayer.quantity_remaining), func.sum(StockCostLayer.quantity_remaining * StockCostLayer.unit_cost))
        .where(StockCostLayer.quantity_remaining > 0).group_by(StockCostLayer.warehouse_id)
    ).all()
    return {wid: {"products": n, "quantity": q or 0, "value": v or 0} for wid, n, q, v in rows}


def list_warehouses(session: Session, include_inactive: bool = True) -> List[Dict[str, Any]]:
    default_id(session)
    transit_id(session)
    session.commit()
    figures = _figures(session)
    stmt = select(Warehouse).order_by(Warehouse.is_default.desc(), Warehouse.kind == "transit", Warehouse.name)
    if not include_inactive:
        stmt = stmt.where(Warehouse.is_active.is_(True))
    return [_view(row, figures.get(row.id)) for row in session.execute(stmt).scalars()]


def save(session: Session, data: Dict[str, Any], warehouse_id: Optional[uuid.UUID] = None) -> Dict[str, Any]:
    begin_write(session)
    try:
        if warehouse_id is None:
            default_id(session)  # the main godown exists before any other
        row = session.get(Warehouse, warehouse_id) if warehouse_id else Warehouse()
        if row is None:
            raise NotFoundError("Warehouse not found.")
        if row.kind == "transit" and warehouse_id:
            raise ValidationError("'In transit' is kept by the system.")
        if "name" in data or warehouse_id is None:
            name = (data.get("name") or "").strip()
            if not name:
                raise ValidationError("Give the warehouse a name.")
            clash = session.execute(select(Warehouse).where(func.lower(Warehouse.name) == name.lower())).scalars().first()
            if clash is not None and clash.id != row.id:
                raise ConflictError("A warehouse called '{}' already exists.".format(name))
            row.name = name[:80]
        if "code" in data or warehouse_id is None:
            code = re.sub(r"[^A-Z0-9-]", "", (data.get("code") or row.name or "").upper())[:16] or "WH"
            base, n = code, 2
            while True:
                clash = session.execute(select(Warehouse).where(Warehouse.code == code)).scalars().first()
                if clash is None or clash.id == row.id:
                    break
                if data.get("code"):
                    raise ConflictError("The code {} is already used.".format(code))
                code, n = "{}{}".format(base[:14], n), n + 1
            row.code = code
        if "kind" in data and data["kind"] is not None:
            if data["kind"] not in KINDS:
                raise ValidationError("Kind must be godown, yard, shop or site.")
            row.kind = data["kind"]
        elif warehouse_id is None:
            row.kind = "godown"
        for key in ("address", "contact", "tally_godown", "notes"):
            if key in data:
                setattr(row, key, (data[key] or "").strip() or None)
        if data.get("is_active") is not None:
            if not data["is_active"] and row.id is not None:
                if row.is_default:
                    raise ValidationError("Make another warehouse the default before closing this one.")
                if on_hand_total(session, row.id) > ZERO:
                    raise ValidationError("{} still holds stock; transfer it out before closing.".format(row.name))
            row.is_active = bool(data["is_active"])
        session.add(row)
        session.flush()
        if data.get("is_default"):
            if not row.is_active:
                raise ValidationError("A closed warehouse cannot be the default.")
            for other in session.execute(select(Warehouse).where(Warehouse.is_default.is_(True), Warehouse.id != row.id)).scalars():
                other.is_default = False
            row.is_default = True
        session.commit()
    except Exception:
        session.rollback()
        raise
    return get(session, row.id)


def on_hand_total(session: Session, warehouse_id: uuid.UUID) -> Decimal:
    return Decimal(session.execute(select(func.coalesce(func.sum(StockCostLayer.quantity_remaining), 0)).where(StockCostLayer.warehouse_id == warehouse_id)).scalar_one())


def get(session: Session, warehouse_id: uuid.UUID) -> Dict[str, Any]:
    row = session.get(Warehouse, warehouse_id)
    if row is None:
        raise NotFoundError("Warehouse not found.")
    return _view(row, _figures(session).get(row.id))


def stock(session: Session, warehouse_id: Optional[uuid.UUID] = None, product_id: Optional[uuid.UUID] = None) -> List[Dict[str, Any]]:
    """Quantity and value on hand per product and warehouse."""
    stmt = (
        select(StockCostLayer.product_id, StockCostLayer.warehouse_id, func.sum(StockCostLayer.quantity_remaining),
               func.sum(StockCostLayer.quantity_remaining * StockCostLayer.unit_cost))
        .where(StockCostLayer.quantity_remaining > 0)
        .group_by(StockCostLayer.product_id, StockCostLayer.warehouse_id)
    )
    if warehouse_id:
        stmt = stmt.where(StockCostLayer.warehouse_id == warehouse_id)
    if product_id:
        stmt = stmt.where(StockCostLayer.product_id == product_id)
    rows = session.execute(stmt).all()
    products = {p.id: p for p in session.execute(select(Product).where(Product.id.in_({r[0] for r in rows}))).scalars()} if rows else {}
    houses = {w.id: w for w in session.execute(select(Warehouse)).scalars()}
    out = []
    for pid, wid, qty, value in rows:
        product, house = products.get(pid), houses.get(wid)
        qty, value = Decimal(qty or 0), Decimal(value or 0)
        out.append({
            "product_id": pid, "product": product.name if product else "?", "sku": product.sku if product else "", "unit": product.unit_of_measure if product else "",
            "category": product.category if product else None,
            "warehouse_id": wid, "warehouse": house.name if house else "Unassigned", "warehouse_kind": house.kind if house else None,
            "quantity": float(qty), "value": float(money(value)), "average_cost": float((value / qty).quantize(Decimal("0.01"))) if qty else 0.0,
        })
    out.sort(key=lambda r: (r["warehouse"], r["product"]))
    return out


# ---------------------------------------------------------------------------
# Moving layers
# ---------------------------------------------------------------------------


def _take(session: Session, product: Product, warehouse_id: uuid.UUID, amount: Decimal, source_id: Optional[uuid.UUID] = None) -> List[StockCostLayer]:
    """Draw ``amount`` from a warehouse's oldest layers; returns detached
    pieces (unsaved layers with the quantity taken) to re-home elsewhere."""
    stmt = select(StockCostLayer).where(StockCostLayer.product_id == product.id, StockCostLayer.warehouse_id == warehouse_id,
                                        StockCostLayer.quantity_remaining > 0)
    if source_id is not None:
        stmt = stmt.where(StockCostLayer.source_id == source_id)
    pieces: List[StockCostLayer] = []
    remaining = amount
    for layer in session.execute(stmt.order_by(StockCostLayer.created_at, StockCostLayer.id).with_for_update()).scalars():
        if remaining <= ZERO:
            break
        take = min(layer.quantity_remaining, remaining)
        layer.quantity_remaining = layer.quantity_remaining - take
        remaining = remaining - take
        pieces.append(StockCostLayer(product_id=product.id, source=layer.source, source_id=layer.source_id, unit_cost=layer.unit_cost,
                                     quantity=take, quantity_remaining=take, note=layer.note, created_at=layer.created_at))
    if remaining > ZERO:
        raise ValidationError("Only {} {} of {} is in that warehouse.".format(amount - remaining, product.unit_of_measure, product.name))
    return pieces


def _place(session: Session, pieces: Iterable[StockCostLayer], warehouse_id: uuid.UUID, source_id: uuid.UUID, note: str,
           extra_per_unit: Decimal = ZERO) -> Decimal:
    """Put drawn pieces into a warehouse (keeping their age for FIFO); returns their value."""
    value = ZERO_MONEY
    for piece in pieces:
        piece.warehouse_id = warehouse_id
        piece.source = MovementType.TRANSFER_IN
        piece.source_id = source_id
        piece.unit_cost = (piece.unit_cost + extra_per_unit).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        piece.note = note
        session.add(piece)
        value = value + money(piece.quantity * piece.unit_cost)
    session.flush()
    return value


# ---------------------------------------------------------------------------
# Transfers
# ---------------------------------------------------------------------------


def _load(session: Session, transfer_id: uuid.UUID, lock: bool = False) -> StockTransfer:
    stmt = select(StockTransfer).where(StockTransfer.id == transfer_id).options(
        joinedload(StockTransfer.items).joinedload(StockTransferItem.product), joinedload(StockTransfer.costs),
        joinedload(StockTransfer.from_warehouse), joinedload(StockTransfer.to_warehouse))
    row = session.execute(stmt).unique().scalar_one_or_none()
    if row is None:
        raise NotFoundError("Transfer not found.")
    if lock:
        session.execute(select(StockTransfer.id).where(StockTransfer.id == transfer_id).with_for_update())
    return row


def view(session: Session, transfer: StockTransfer) -> Dict[str, Any]:
    total_qty = sum((i.quantity for i in transfer.items), ZERO)
    costs = sum((c.amount for c in transfer.costs), ZERO_MONEY)
    return {
        "id": transfer.id, "number": transfer.number, "status": transfer.status,
        "from_warehouse_id": transfer.from_warehouse_id, "from_warehouse": transfer.from_warehouse.name,
        "to_warehouse_id": transfer.to_warehouse_id, "to_warehouse": transfer.to_warehouse.name,
        "cost_method": transfer.cost_method, "vehicle": transfer.vehicle, "transporter": transfer.transporter, "notes": transfer.notes,
        "transporter_id": transfer.transporter_id, "lr_number": transfer.lr_number,
        "goods_value": float(transfer.goods_value), "extra_cost": float(transfer.extra_cost or costs), "costs_total": float(costs),
        "loss_value": float(transfer.loss_value),
        "landed_value": float(transfer.goods_value - transfer.loss_value + (transfer.extra_cost if transfer.status == "received" else 0)),
        "created_at": transfer.created_at, "dispatched_at": transfer.dispatched_at, "received_at": transfer.received_at,
        "total_quantity": float(total_qty), "line_count": len(transfer.items),
        "items": [{
            "id": i.id, "product_id": i.product_id, "product": i.product.name, "sku": i.product.sku, "base_unit": i.product.unit_of_measure,
            "unit": i.unit, "unit_name": i.unit_name, "unit_factor": float(i.unit_factor), "unit_quantity": float(i.unit_quantity or 0),
            "quantity": float(i.quantity), "quantity_received": float(i.quantity_received), "weight_kg": float(i.product.weight_kg) if i.product.weight_kg is not None else None,
            "available": float(on_hand(session, i.product_id, transfer.from_warehouse_id)) if transfer.status == "draft" else None,
            "goods_value": float(i.goods_value), "extra_cost": float(i.extra_cost),
            "unit_cost_before": float((i.goods_value / i.quantity).quantize(Decimal("0.01"))) if i.quantity and i.goods_value else None,
            "unit_cost_after": float(((i.goods_value / i.quantity) + (i.extra_cost / i.quantity_received)).quantize(Decimal("0.01")))
            if i.quantity and i.quantity_received and transfer.status == "received" else None,
        } for i in transfer.items],
        "costs": [{"id": c.id, "kind": c.kind, "label": COST_KINDS.get(c.kind, c.kind), "amount": float(c.amount), "paid_to": c.paid_to,
                   "transporter_id": c.transporter_id, "note": c.note} for c in transfer.costs],
    }


def list_transfers(session: Session, status: Optional[str] = None, warehouse_id: Optional[uuid.UUID] = None, limit: int = 100) -> List[Dict[str, Any]]:
    stmt = select(StockTransfer).options(joinedload(StockTransfer.items).joinedload(StockTransferItem.product), joinedload(StockTransfer.costs),
                                         joinedload(StockTransfer.from_warehouse), joinedload(StockTransfer.to_warehouse)).order_by(StockTransfer.created_at.desc())
    if status:
        stmt = stmt.where(StockTransfer.status == status)
    if warehouse_id:
        stmt = stmt.where((StockTransfer.from_warehouse_id == warehouse_id) | (StockTransfer.to_warehouse_id == warehouse_id))
    rows = session.execute(stmt.limit(limit)).unique().scalars().all()
    out = []
    for t in rows:
        v = view(session, t)
        v.pop("items")
        v["products"] = ", ".join(i.product.name for i in t.items[:3]) + (" +{}".format(len(t.items) - 3) if len(t.items) > 3 else "")
        out.append(v)
    return out


def get_transfer(session: Session, transfer_id: uuid.UUID) -> Dict[str, Any]:
    return view(session, _load(session, transfer_id))


def _apply_draft(session: Session, transfer: StockTransfer, data: Dict[str, Any]) -> None:
    from . import units

    if "from_warehouse_id" in data or transfer.from_warehouse_id is None:
        transfer.from_warehouse_id = resolve(session, data.get("from_warehouse_id"))
    if "to_warehouse_id" in data or transfer.to_warehouse_id is None:
        if not data.get("to_warehouse_id"):
            raise ValidationError("Choose where the goods are going.")
        transfer.to_warehouse_id = resolve(session, data.get("to_warehouse_id"))
    if transfer.from_warehouse_id == transfer.to_warehouse_id:
        raise ValidationError("Choose two different warehouses.")
    if data.get("cost_method") is not None:
        if data["cost_method"] not in METHODS:
            raise ValidationError("Spread costs by quantity, value or weight.")
        transfer.cost_method = data["cost_method"]
    for key in ("vehicle", "transporter", "notes", "lr_number"):
        if key in data:
            setattr(transfer, key, (data[key] or "").strip() or None)
    if "transporter_id" in data:
        if data["transporter_id"]:
            from .transporters import get as get_transporter

            found = get_transporter(session, uuid.UUID(str(data["transporter_id"])))
            transfer.transporter_id = found.id
            transfer.transporter = transfer.transporter or found.name
        else:
            transfer.transporter_id = None
    if data.get("items") is not None:
        lines = [dict(line) for line in data["items"] if line.get("product_id")]
        if not lines:
            raise ValidationError("Add at least one product.")
        found = units.apply(session, lines, "quantity", None, "sales")
        merged: Dict[uuid.UUID, Decimal] = {}
        order: List[uuid.UUID] = []
        for line in lines:
            pid = uuid.UUID(str(line["product_id"]))
            qty = to_quantity(line.get("quantity"), "Quantity")
            if qty <= ZERO:
                raise ValidationError("Quantities must be above zero.")
            if pid not in merged:
                order.append(pid)
            merged[pid] = merged.get(pid, ZERO) + qty
        transfer.items.clear()
        session.flush()
        for number, pid in enumerate(order, start=1):
            if session.get(Product, pid) is None:
                raise NotFoundError("Product not found.")
            item = StockTransferItem(product_id=pid, line_number=number, quantity=merged[pid])
            units.stamp(item, found)
            transfer.items.append(item)
    if data.get("costs") is not None:
        transfer.costs.clear()
        session.flush()
        for cost in data["costs"]:
            amount = money(cost.get("amount") or 0)
            if amount < ZERO:
                raise ValidationError("Costs cannot be negative.")
            if amount == ZERO:
                continue
            kind = cost.get("kind") or "freight"
            if kind not in COST_KINDS:
                raise ValidationError("Unknown cost '{}'.".format(kind))
            cost_transporter = cost.get("transporter_id")
            if cost_transporter is None and kind == "freight" and not cost.get("paid_to"):
                cost_transporter = data.get("transporter_id") or transfer.transporter_id
            transfer.costs.append(StockTransferCost(kind=kind, amount=amount, paid_to=(cost.get("paid_to") or "").strip() or None,
                                                    transporter_id=uuid.UUID(str(cost_transporter)) if cost_transporter else None,
                                                    note=(cost.get("note") or "").strip() or None))
    transfer.extra_cost = sum((c.amount for c in transfer.costs), ZERO_MONEY)


def create_transfer(session: Session, data: Dict[str, Any], user: Optional[User] = None, dispatch_now: bool = False) -> Dict[str, Any]:
    begin_write(session)
    try:
        transfer = StockTransfer(number=next_document_number(session, TRANSFER_COUNTER, "TR"), status="draft",
                                 created_by_id=user.id if user else None, cost_method="quantity")
        _apply_draft(session, transfer, data)
        session.add(transfer)
        session.flush()
        session.commit()
    except Exception:
        session.rollback()
        raise
    if dispatch_now:
        return dispatch(session, transfer.id, user)
    return get_transfer(session, transfer.id)


def update_transfer(session: Session, transfer_id: uuid.UUID, data: Dict[str, Any]) -> Dict[str, Any]:
    begin_write(session)
    try:
        transfer = _load(session, transfer_id, lock=True)
        if transfer.status == "draft":
            _apply_draft(session, transfer, data)
        elif transfer.status == "in_transit":
            # On the road, only the paperwork and the costs can still change.
            allowed = {k: v for k, v in data.items() if k in ("vehicle", "transporter", "notes", "costs", "cost_method", "transporter_id", "lr_number")}
            if set(data) - set(allowed) - {"items", "from_warehouse_id", "to_warehouse_id"}:
                pass
            if any(k in data and data[k] is not None for k in ("items", "from_warehouse_id", "to_warehouse_id")):
                raise ConflictError("{} is already on its way; only costs and notes can change.".format(transfer.number))
            _apply_draft(session, transfer, allowed)
        else:
            raise ConflictError("{} is {} and can no longer change.".format(transfer.number, transfer.status.replace("_", " ")))
        session.commit()
    except Exception:
        session.rollback()
        raise
    return get_transfer(session, transfer_id)


def dispatch(session: Session, transfer_id: uuid.UUID, user: Optional[User] = None) -> Dict[str, Any]:
    """The goods leave the source warehouse and go into transit."""
    begin_write(session)
    try:
        transfer = _load(session, transfer_id, lock=True)
        if transfer.status != "draft":
            raise ConflictError("{} has already been dispatched.".format(transfer.number))
        if not transfer.items:
            raise ValidationError("Add at least one product.")
        transit = transit_id(session)
        label = "Transfer {}: {} to {}".format(transfer.number, transfer.from_warehouse.name, transfer.to_warehouse.name)
        total = ZERO_MONEY
        for item in sorted(transfer.items, key=lambda i: str(i.product_id)):
            product = lock_product(session, item.product_id)
            pieces = _take(session, product, transfer.from_warehouse_id, item.quantity)
            value = _place(session, pieces, transit, transfer.id, label)
            for piece in pieces:
                piece.source = MovementType.TRANSFER_OUT  # marks layers on the road for this transfer
            item.goods_value = value
            total = total + value
            record_movement(session, product, MovementType.TRANSFER_OUT, -item.quantity, "stock_transfer", transfer.id,
                            "Sent to {} ({})".format(transfer.to_warehouse.name, transfer.number), warehouse_id=transfer.from_warehouse_id)
            record_movement(session, product, MovementType.TRANSFER_IN, item.quantity, "stock_transfer", transfer.id,
                            "On the road to {} ({})".format(transfer.to_warehouse.name, transfer.number), warehouse_id=transit)
        transfer.goods_value = total
        transfer.status = "in_transit"
        transfer.dispatched_at = datetime.now(timezone.utc)
        _audit(session, user, transfer, "dispatched")
        session.commit()
    except Exception:
        session.rollback()
        raise
    return get_transfer(session, transfer_id)


def _shares(transfer: StockTransfer, received: Dict[uuid.UUID, Decimal]) -> Dict[uuid.UUID, Decimal]:
    """Each line's share of the costs, by the transfer's method, over what arrived."""
    total_cost = sum((c.amount for c in transfer.costs), ZERO_MONEY)
    if total_cost <= ZERO:
        return {i.id: ZERO_MONEY for i in transfer.items}
    method = transfer.cost_method
    if method == "weight" and any(i.product.weight_kg is None for i in transfer.items if received.get(i.id, ZERO) > ZERO):
        method = "quantity"  # some products have no weight: fall back to quantity
    basis: Dict[uuid.UUID, Decimal] = {}
    for item in transfer.items:
        got = received.get(item.id, ZERO)
        if got <= ZERO:
            basis[item.id] = ZERO
        elif method == "value":
            basis[item.id] = (item.goods_value / item.quantity) * got if item.quantity else ZERO
        elif method == "weight":
            basis[item.id] = got * Decimal(item.product.weight_kg)
        else:
            basis[item.id] = got
    whole = sum(basis.values(), ZERO)
    if whole <= ZERO:
        return {i.id: ZERO_MONEY for i in transfer.items}
    shares: Dict[uuid.UUID, Decimal] = {}
    given = ZERO_MONEY
    ordered = [i for i in transfer.items if basis[i.id] > ZERO]
    for index, item in enumerate(ordered):
        share = total_cost - given if index == len(ordered) - 1 else money(total_cost * basis[item.id] / whole)
        shares[item.id] = share
        given = given + share
    for item in transfer.items:
        shares.setdefault(item.id, ZERO_MONEY)
    return shares


def receive(session: Session, transfer_id: uuid.UUID, lines: Optional[Iterable[Dict[str, Any]]] = None, user: Optional[User] = None,
            note: Optional[str] = None) -> Dict[str, Any]:
    """The goods arrive. ``lines`` say what arrived per item (default: all of it);
    anything short is written off as lost in transit."""
    from . import reservations
    from ..models import AllocationSource

    begin_write(session)
    try:
        transfer = _load(session, transfer_id, lock=True)
        if transfer.status != "in_transit":
            raise ConflictError("{} is not on its way ({}).".format(transfer.number, transfer.status.replace("_", " ")))
        transit = transit_id(session)
        got: Dict[uuid.UUID, Decimal] = {i.id: i.quantity for i in transfer.items}
        for line in lines or []:
            item_id = uuid.UUID(str(line.get("item_id")))
            if item_id not in got:
                raise NotFoundError("That line is not on {}.".format(transfer.number))
            qty = to_quantity(line.get("quantity_received"), "Quantity received")
            item = next(i for i in transfer.items if i.id == item_id)
            if qty < ZERO or qty > item.quantity:
                raise ValidationError("Received for {} must be between 0 and {}.".format(item.product.name, item.quantity))
            got[item_id] = qty
        shares = _shares(transfer, got)
        label = "Transfer {} from {}".format(transfer.number, transfer.from_warehouse.name)
        loss = ZERO_MONEY
        for item in sorted(transfer.items, key=lambda i: str(i.product_id)):
            product = lock_product(session, item.product_id)
            arrived = got[item.id]
            short = item.quantity - arrived
            if arrived > ZERO:
                pieces = _take(session, product, transit, arrived, source_id=transfer.id)
                extra = (shares[item.id] / arrived) if arrived else ZERO
                _place(session, pieces, transfer.to_warehouse_id, transfer.id, label, extra)
                record_movement(session, product, MovementType.TRANSFER_OUT, -arrived, "stock_transfer", transfer.id,
                                "Arrived at {} ({})".format(transfer.to_warehouse.name, transfer.number), warehouse_id=transit)
                record_movement(session, product, MovementType.TRANSFER_IN, arrived, "stock_transfer", transfer.id, label,
                                warehouse_id=transfer.to_warehouse_id)
            if short > ZERO:
                lost = _take(session, product, transit, short, source_id=transfer.id)
                loss = loss + sum((money(p.quantity * p.unit_cost) for p in lost), ZERO_MONEY)
                record_movement(session, product, MovementType.ADJUSTMENT, -short, "stock_transfer", transfer.id,
                                "Lost in transit on {}{}".format(transfer.number, ": " + note if note else ""), warehouse_id=transit)
                # Fewer units exist now: if that leaves customers' reservations
                # unbacked, the newest orders give theirs back first.
                from .adjustments import _release_newest

                reserved = reservations.reserved_for_product(session, product.id)
                if reserved > product.physical_stock:
                    _release_newest(session, product, reserved - product.physical_stock)
            item.quantity_received = arrived
            item.extra_cost = shares[item.id]
        transfer.loss_value = loss
        transfer.extra_cost = sum((c.amount for c in transfer.costs), ZERO_MONEY)
        transfer.status = "received"
        transfer.received_at = datetime.now(timezone.utc)
        if note:
            transfer.notes = ((transfer.notes + "\n") if transfer.notes else "") + "On receipt: " + note.strip()
        _audit(session, user, transfer, "received")
        session.commit()
    except Exception:
        session.rollback()
        raise
    return get_transfer(session, transfer_id)


def cancel(session: Session, transfer_id: uuid.UUID, user: Optional[User] = None) -> Dict[str, Any]:
    """A draft is dropped; a transfer on the road comes back to the source at its original cost."""
    begin_write(session)
    try:
        transfer = _load(session, transfer_id, lock=True)
        if transfer.status in ("received", "cancelled"):
            raise ConflictError("{} is already {}.".format(transfer.number, transfer.status))
        if transfer.status == "in_transit":
            transit = transit_id(session)
            for item in sorted(transfer.items, key=lambda i: str(i.product_id)):
                product = lock_product(session, item.product_id)
                pieces = _take(session, product, transit, item.quantity, source_id=transfer.id)
                _place(session, pieces, transfer.from_warehouse_id, transfer.id, "Transfer {} cancelled; back in {}".format(transfer.number, transfer.from_warehouse.name))
                record_movement(session, product, MovementType.TRANSFER_OUT, -item.quantity, "stock_transfer", transfer.id,
                                "Cancelled {}".format(transfer.number), warehouse_id=transit)
                record_movement(session, product, MovementType.TRANSFER_IN, item.quantity, "stock_transfer", transfer.id,
                                "Back from cancelled {}".format(transfer.number), warehouse_id=transfer.from_warehouse_id)
        transfer.status = "cancelled"
        _audit(session, user, transfer, "cancelled")
        session.commit()
    except Exception:
        session.rollback()
        raise
    return get_transfer(session, transfer_id)


def _audit(session: Session, user: Optional[User], transfer: StockTransfer, what: str) -> None:
    from .controls import log

    log(session, user, "stock_transfer", "stock_transfer", str(transfer.id),
        "{} {}: {} to {}, {} line(s){}".format(transfer.number, what, transfer.from_warehouse.name, transfer.to_warehouse.name, len(transfer.items),
                                              ", costs Rs {:,.2f}".format(float(transfer.extra_cost)) if transfer.extra_cost else ""))
