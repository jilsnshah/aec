"""Inventory, settlement-preview and stock-receipt endpoints."""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import schemas
from ..database import get_db
from ..services import inventory as inventory_service
from ..services import products as product_service

router = APIRouter(prefix="/api", tags=["inventory"])


@router.get("/inventory/summary", response_model=schemas.InventorySummaryOut)
def inventory_summary(db: Session = Depends(get_db)):
    return inventory_service.inventory_summary(db)


@router.get("/products/{product_id}/inventory", response_model=schemas.ProductInventoryOut)
def product_inventory(product_id: uuid.UUID, db: Session = Depends(get_db)):
    return product_service.product_inventory(db, product_id)


@router.get("/products/{product_id}/pending-orders", response_model=schemas.PendingOrdersOut)
def pending_orders(
    product_id: uuid.UUID,
    receipt_quantity: Optional[Decimal] = Query(
        default=None,
        ge=0,
        description="When supplied, the response includes the FIFO proposal and the required allocation total.",
    ),
    db: Session = Depends(get_db),
):
    return inventory_service.pending_orders_for_product(db, product_id, receipt_quantity)


@router.post("/stock-receipts", response_model=schemas.StockReceiptResult, status_code=201)
def create_stock_receipt(payload: schemas.StockReceiptCreate, db: Session = Depends(get_db)):
    """Record received stock and compulsorily settle outstanding customer orders.

    Omit ``allocations`` to let the backend allocate FIFO. If you send them they
    are re-validated against live data and must total
    ``min(quantity, total pending)`` exactly.
    """
    allocations = (
        [item.model_dump() for item in payload.allocations]
        if payload.allocations is not None
        else None
    )
    return inventory_service.receive_stock(
        db,
        product_id=payload.product_id,
        received_quantity=payload.quantity,
        allocations=allocations,
        note=payload.note,
        idempotency_key=payload.idempotency_key,
        purchase_unit_cost=payload.unit_cost,
        supplier_reference=payload.supplier_reference,
    )


@router.get("/stock-receipts/{receipt_id}/allocations")
def receipt_allocations(receipt_id: uuid.UUID, db: Session = Depends(get_db)):
    """Exactly which customer orders received each incoming quantity."""
    return inventory_service.receipt_allocations(db, receipt_id)
