"""Warehouses and stock transfers between them."""
from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..services import warehouses
from .auth import require_user

router = APIRouter(prefix="/api", tags=["stock"])


class WarehouseIn(BaseModel):
    name: Optional[str] = Field(default=None, max_length=80)
    code: Optional[str] = Field(default=None, max_length=16, description="Short code; made from the name if omitted.")
    kind: Optional[str] = Field(default=None, description="godown, yard, shop or site.")
    address: Optional[str] = None
    contact: Optional[str] = Field(default=None, max_length=120, description="Who looks after it, and their phone.")
    tally_godown: Optional[str] = Field(default=None, max_length=120, description="The matching godown name in Tally.")
    notes: Optional[str] = None
    is_default: Optional[bool] = Field(default=None, description="Use when no warehouse is chosen.")
    is_active: Optional[bool] = Field(default=None, description="False closes it (only when empty).")


class TransferLine(BaseModel):
    product_id: uuid.UUID
    quantity: str = Field(description="In `unit` if given, else the product's base unit.")
    unit: Optional[str] = Field(default=None, max_length=32)


class TransferCostIn(BaseModel):
    kind: str = Field(default="freight", description="freight, loading, unloading, toll, insurance or other.")
    amount: str
    paid_to: Optional[str] = Field(default=None, max_length=120)
    note: Optional[str] = None


class TransferIn(BaseModel):
    from_warehouse_id: Optional[uuid.UUID] = Field(default=None, description="Source; the default warehouse if omitted.")
    to_warehouse_id: Optional[uuid.UUID] = None
    items: Optional[List[TransferLine]] = None
    costs: Optional[List[TransferCostIn]] = Field(default=None, description="Costs of moving the goods (replaces them all).")
    cost_method: Optional[str] = Field(default=None, description="Spread costs by quantity, value or weight.")
    vehicle: Optional[str] = Field(default=None, max_length=60)
    transporter: Optional[str] = Field(default=None, max_length=120)
    notes: Optional[str] = None
    dispatch: bool = Field(default=False, description="Create and send it straight away.")


class ReceiveLine(BaseModel):
    item_id: uuid.UUID
    quantity_received: str


class ReceiveIn(BaseModel):
    lines: Optional[List[ReceiveLine]] = Field(default=None, description="What arrived per line; omit when everything arrived.")
    note: Optional[str] = Field(default=None, description="E.g. why something is short.")


@router.get("/warehouses")
def list_warehouses(include_closed: bool = Query(default=True), db: Session = Depends(get_db)):
    """Every warehouse with how many products, units and what value it holds."""
    return {"items": warehouses.list_warehouses(db, include_closed), "kinds": warehouses.KINDS,
            "cost_kinds": warehouses.COST_KINDS, "methods": warehouses.METHODS}


@router.post("/warehouses", status_code=201)
def create_warehouse(payload: WarehouseIn, db: Session = Depends(get_db)):
    """Add a godown, yard, shop or site store."""
    return warehouses.save(db, payload.model_dump(exclude_unset=True))


@router.get("/warehouses/stock")
def warehouse_stock(warehouse_id: Optional[uuid.UUID] = Query(default=None), product_id: Optional[uuid.UUID] = Query(default=None),
                    db: Session = Depends(get_db)):
    """Quantity, value and average cost on hand per product and warehouse."""
    return {"items": warehouses.stock(db, warehouse_id, product_id)}


@router.get("/warehouses/{warehouse_id}")
def get_warehouse(warehouse_id: uuid.UUID, db: Session = Depends(get_db)):
    return warehouses.get(db, warehouse_id)


@router.put("/warehouses/{warehouse_id}")
def update_warehouse(warehouse_id: uuid.UUID, payload: WarehouseIn, db: Session = Depends(get_db)):
    """Change a warehouse, make it the default, or close it (only when empty)."""
    return warehouses.save(db, payload.model_dump(exclude_unset=True), warehouse_id)


@router.get("/stock-transfers")
def list_transfers(status: Optional[str] = Query(default=None, description="draft, in_transit, received or cancelled"),
                   warehouse_id: Optional[uuid.UUID] = Query(default=None), db: Session = Depends(get_db)):
    """Transfers between warehouses, newest first."""
    return {"items": warehouses.list_transfers(db, status, warehouse_id)}


@router.post("/stock-transfers", status_code=201)
def create_transfer(payload: TransferIn, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Draft a transfer: from, to, products and the costs of moving them. With dispatch, send it at once."""
    data = payload.model_dump(exclude_unset=True, mode="json")
    data.pop("dispatch", None)
    return warehouses.create_transfer(db, data, user, payload.dispatch)


@router.get("/stock-transfers/{transfer_id}")
def get_transfer(transfer_id: uuid.UUID, db: Session = Depends(get_db)):
    return warehouses.get_transfer(db, transfer_id)


@router.put("/stock-transfers/{transfer_id}")
def update_transfer(transfer_id: uuid.UUID, payload: TransferIn, db: Session = Depends(get_db)):
    """Change a draft; on the road only costs and notes can change."""
    data = payload.model_dump(exclude_unset=True, mode="json")
    data.pop("dispatch", None)
    return warehouses.update_transfer(db, transfer_id, data)


@router.post("/stock-transfers/{transfer_id}/dispatch")
def dispatch_transfer(transfer_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """The goods leave the source (oldest stock first) and are in transit."""
    return warehouses.dispatch(db, transfer_id, user)


@router.post("/stock-transfers/{transfer_id}/receive")
def receive_transfer(transfer_id: uuid.UUID, payload: ReceiveIn, background: BackgroundTasks, db: Session = Depends(get_db),
                     user: User = Depends(require_user)):
    """The goods arrive. Costs are spread over what arrived and added to its cost; anything short is written off.
    With Tally on, the transfer goes to Tally as a Stock Journal."""
    result = warehouses.receive(db, transfer_id, [line.model_dump() for line in payload.lines] if payload.lines else None, user, payload.note)
    from ..services import tally_sync

    for sync_id in tally_sync.queue_transfer(db, transfer_id):
        background.add_task(tally_sync.process, sync_id)
    return result


@router.post("/stock-transfers/{transfer_id}/cancel")
def cancel_transfer(transfer_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Drop a draft, or bring goods on the road back to the source."""
    return warehouses.cancel(db, transfer_id, user)
