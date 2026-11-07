"""Supplier, purchase order and goods receipt endpoints."""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from .. import schemas
from ..database import get_db
from ..models import PurchaseOrderStatus
from ..services import tally_sync
from ..services import purchasing as purchasing_service
from ..services import suppliers as supplier_service
from .pagination import PageParams, page_params

suppliers_router = APIRouter(prefix="/api/suppliers", tags=["purchasing"])
po_router = APIRouter(prefix="/api/purchase-orders", tags=["purchasing"])
receipts_router = APIRouter(prefix="/api/goods-receipts", tags=["purchasing"])


# ---------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------

@suppliers_router.get("", response_model=schemas.Page[schemas.SupplierListRow])
def list_suppliers(
    search: Optional[str] = Query(default=None, description="Matches code, name or contact."),
    include_inactive: bool = Query(default=False),
    sort_by: str = Query(default="name"),
    sort_dir: str = Query(default="asc", pattern="^(asc|desc)$"),
    paging: PageParams = Depends(page_params),
    db: Session = Depends(get_db),
):
    suppliers = supplier_service.list_suppliers(
        db, search, include_inactive, sort_by, sort_dir, paging.limit, paging.offset
    )
    stats = supplier_service.supplier_stats(db, [supplier.id for supplier in suppliers])
    items = [
        {**schemas.SupplierOut.model_validate(supplier).model_dump(), **stats[supplier.id]}
        for supplier in suppliers
    ]
    return paging.page(items, supplier_service.count_suppliers(db, search, include_inactive))


@suppliers_router.post("", response_model=schemas.SupplierOut, status_code=201)
def create_supplier(payload: schemas.SupplierCreate, db: Session = Depends(get_db)):
    return supplier_service.create_supplier(db, **payload.model_dump())


@suppliers_router.get("/{supplier_id}", response_model=schemas.SupplierDetailOut)
def get_supplier(supplier_id: uuid.UUID, db: Session = Depends(get_db)):
    """A supplier with its purchasing and goods receipt history."""
    return supplier_service.supplier_detail(db, supplier_id)


@suppliers_router.patch("/{supplier_id}", response_model=schemas.SupplierOut)
def update_supplier(
    supplier_id: uuid.UUID, payload: schemas.SupplierUpdate, db: Session = Depends(get_db)
):
    return supplier_service.update_supplier(db, supplier_id, payload.model_dump(exclude_unset=True))


@suppliers_router.post("/{supplier_id}/archive", response_model=schemas.SupplierOut)
def archive_supplier(supplier_id: uuid.UUID, db: Session = Depends(get_db)):
    """Soft-delete. Purchase orders and receipts keep pointing at the supplier."""
    return supplier_service.archive_supplier(db, supplier_id)


# ---------------------------------------------------------------------------
# Purchase orders
# ---------------------------------------------------------------------------

@po_router.get("", response_model=schemas.Page[schemas.PurchaseOrderOut])
def list_purchase_orders(
    search: Optional[str] = Query(default=None, description="Matches PO number or supplier."),
    status: Optional[str] = Query(
        default=None, description="One status, or several separated by commas."
    ),
    supplier_id: Optional[uuid.UUID] = Query(default=None),
    product_id: Optional[uuid.UUID] = Query(default=None),
    paging: PageParams = Depends(page_params),
    db: Session = Depends(get_db),
):
    items = [
        purchasing_service.to_po_view(order)
        for order in purchasing_service.list_purchase_orders(
            db, search, status, supplier_id, product_id, paging.limit, paging.offset
        )
    ]
    total = purchasing_service.count_purchase_orders(db, search, status, supplier_id, product_id)
    return paging.page(items, total)


@po_router.post("", response_model=schemas.PurchaseOrderOut, status_code=201)
def create_purchase_order(
    payload: schemas.PurchaseOrderCreate, background: BackgroundTasks, db: Session = Depends(get_db)
):
    """Raise a purchase order. Placed straight away, it counts as stock at once."""
    order = purchasing_service.create_purchase_order(
        db,
        supplier_id=payload.supplier_id,
        items=[item.model_dump() for item in payload.items],
        expected_delivery_date=payload.expected_delivery_date,
        notes=payload.notes,
        confirm=payload.confirm,
        settlements=(
            [entry.model_dump() for entry in payload.settlements]
            if payload.settlements is not None
            else None
        ),
    )
    if order.status != PurchaseOrderStatus.DRAFT:
        _to_tally(db, order, background)
    return purchasing_service.to_po_view(order)


def _to_tally(db: Session, order, background: BackgroundTasks) -> None:
    """A placed purchase order goes to Tally, after the response."""
    for sync_id in tally_sync.queue_purchase_order(db, order):
        background.add_task(tally_sync.process, sync_id)


@po_router.get("/{po_id}", response_model=schemas.PurchaseOrderOut)
def get_purchase_order(po_id: uuid.UUID, db: Session = Depends(get_db)):
    return purchasing_service.to_po_view(purchasing_service.get_purchase_order(db, po_id))


@po_router.patch("/{po_id}", response_model=schemas.PurchaseOrderOut)
def update_purchase_order(
    po_id: uuid.UUID, payload: schemas.PurchaseOrderUpdate, db: Session = Depends(get_db)
):
    changes = payload.model_dump(exclude_unset=True)
    if "items" in changes and changes["items"] is not None:
        changes["items"] = [dict(item) for item in changes["items"]]
    return purchasing_service.to_po_view(
        purchasing_service.update_purchase_order(db, po_id, changes)
    )


def _settlements(payload: Optional[schemas.PurchaseSettleRequest]):
    if payload is None or payload.settlements is None:
        return None
    return [entry.model_dump() for entry in payload.settlements]


@po_router.post("/{po_id}/confirm", response_model=schemas.PurchaseOrderOut)
def confirm_purchase_order(
    po_id: uuid.UUID,
    background: BackgroundTasks,
    payload: Optional[schemas.PurchaseSettleRequest] = None,
    db: Session = Depends(get_db),
):
    """Place a draft order with the supplier.

    It counts as stock at once, so it must settle customers who are short;
    ``settlements`` says who and how much.
    """
    order = purchasing_service.confirm_purchase_order(db, po_id, _settlements(payload))
    _to_tally(db, order, background)
    return purchasing_service.to_po_view(order)


@po_router.post("/{po_id}/settle", response_model=schemas.PurchaseOrderOut)
def settle_purchase_order(
    po_id: uuid.UUID, payload: schemas.PurchaseSettleRequest, db: Session = Depends(get_db)
):
    """Give a placed order's unpromised quantity to customers who are short."""
    return purchasing_service.to_po_view(
        purchasing_service.settle_purchase_order(db, po_id, _settlements(payload) or [])
    )


@po_router.post("/{po_id}/cancel", response_model=schemas.PurchaseOrderOut)
def cancel_purchase_order(
    po_id: uuid.UUID,
    payload: Optional[schemas.CancelRequest] = None,
    db: Session = Depends(get_db),
):
    reason = payload.reason if payload else None
    return purchasing_service.to_po_view(
        purchasing_service.cancel_purchase_order(db, po_id, reason)
    )


# ---------------------------------------------------------------------------
# Goods receipts
# ---------------------------------------------------------------------------

@receipts_router.get("", response_model=schemas.Page[schemas.GoodsReceiptRow])
def list_goods_receipts(
    search: Optional[str] = Query(default=None),
    supplier_id: Optional[uuid.UUID] = Query(default=None),
    purchase_order_id: Optional[uuid.UUID] = Query(default=None),
    paging: PageParams = Depends(page_params),
    db: Session = Depends(get_db),
):
    items = purchasing_service.list_goods_receipts(
        db, search, supplier_id, purchase_order_id, paging.limit, paging.offset
    )
    total = purchasing_service.count_goods_receipts(db, search, supplier_id, purchase_order_id)
    return paging.page(items, total)


@receipts_router.post("/preview", response_model=schemas.ReceiptPreviewOut)
def preview_goods_receipt(payload: schemas.GoodsReceiptRequest, db: Session = Depends(get_db)):
    """What confirming this receipt would do. Writes nothing.

    Shows, per line, the eligible customer demand, the allocation the backend
    proposes, the quantity that must be allocated and the surplus that would be
    left freely available.
    """
    return purchasing_service.preview_receipt(
        db, payload.purchase_order_id, [line.model_dump() for line in payload.lines]
    )


@receipts_router.post("", response_model=schemas.GoodsReceiptResult, status_code=201)
def create_goods_receipt(payload: schemas.GoodsReceiptRequest, db: Session = Depends(get_db)):
    """Book goods in and compulsorily reserve them against waiting orders.

    Omit a line's ``allocations`` to allocate FIFO. Anything sent is
    re-validated against live data and must total
    ``min(quantity received, unallocated customer demand)``.
    """
    lines = []
    for line in payload.lines:
        entry = line.model_dump()
        if entry.get("allocations") is not None:
            entry["allocations"] = [dict(row) for row in entry["allocations"]]
        lines.append(entry)
    return purchasing_service.create_goods_receipt(
        db,
        po_id=payload.purchase_order_id,
        lines=lines,
        delivery_note_reference=payload.delivery_note_reference,
        notes=payload.notes,
        idempotency_key=payload.idempotency_key,
        allow_over_receipt=payload.allow_over_receipt,
    )


@receipts_router.get("/{receipt_id}", response_model=schemas.GoodsReceiptResult)
def get_goods_receipt(receipt_id: uuid.UUID, db: Session = Depends(get_db)):
    return purchasing_service.get_goods_receipt(db, receipt_id)
