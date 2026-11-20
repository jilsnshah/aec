"""Landed costs on goods receipts, purchase returns (debit notes) and rate contracts."""
from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..services import landed_costs, purchase_returns, rate_contracts
from .auth import require_user

router = APIRouter(prefix="/api", tags=["purchasing"])


class ChargeIn(BaseModel):
    kind: str = Field(default="freight", description="freight, unloading, loading, insurance, octroi, commission or other.")
    amount: str
    transporter_id: Optional[uuid.UUID] = Field(default=None, description="Owed to this transporter.")
    paid_to: Optional[str] = None
    bill_number: Optional[str] = None


class LandedIn(BaseModel):
    charges: List[ChargeIn] = Field(min_length=1)
    method: str = Field(default="quantity", description="Spread by quantity, value or weight.")
    note: Optional[str] = None


class ReturnLineIn(BaseModel):
    goods_receipt_item_id: Optional[uuid.UUID] = Field(default=None, description="The receipt line going back (preferred).")
    product_id: Optional[uuid.UUID] = Field(default=None, description="Without a receipt line: the product.")
    quantity: str
    unit_cost: Optional[str] = Field(default=None, description="Without a receipt line: the price to debit; else the PO price.")


class PurchaseReturnIn(BaseModel):
    goods_receipt_id: Optional[uuid.UUID] = None
    purchase_order_id: Optional[uuid.UUID] = None
    supplier_id: Optional[uuid.UUID] = None
    reason: str = Field(description="damaged, quality, wrong_item, excess, expired or other.")
    note: Optional[str] = None
    replace: bool = Field(default=False, description="The supplier will send these again: the PO is owed them once more.")
    warehouse_id: Optional[uuid.UUID] = Field(default=None, description="Warehouse the goods leave from; the receipt's by default.")
    transporter_id: Optional[uuid.UUID] = None
    vehicle_number: Optional[str] = None
    lines: List[ReturnLineIn] = Field(min_length=1)


class ContractLineIn(BaseModel):
    product_id: uuid.UUID
    rate: Optional[str] = Field(default=None, description="Agreed price per `unit` (or base unit).")
    discount_percent: Optional[str] = Field(default=None, description="Or a discount off MRP.")
    unit: Optional[str] = None
    min_quantity: Optional[str] = Field(default=None, description="Rate applies from this quantity (slab).")
    committed_quantity: Optional[str] = Field(default=None, description="Quantity agreed over the contract.")


class ContractIn(BaseModel):
    supplier_id: Optional[uuid.UUID] = None
    customer_id: Optional[uuid.UUID] = None
    title: Optional[str] = None
    valid_from: Optional[str] = Field(default=None, description="YYYY-MM-DD; today if omitted.")
    valid_until: Optional[str] = Field(default=None, description="YYYY-MM-DD; a year from now if omitted.")
    reference: Optional[str] = None
    terms: Optional[str] = None
    address_id: Optional[uuid.UUID] = Field(default=None, description="Customer's project site.")
    items: Optional[List[ContractLineIn]] = None


@router.get("/landed-costs")
def list_landed(db: Session = Depends(get_db)):
    """Freight and other charges added to goods receipts, newest first."""
    return {"items": landed_costs.list_all(db), "kinds": landed_costs.KINDS}


@router.get("/goods-receipts/{receipt_id}/landed-costs")
def receipt_landed(receipt_id: uuid.UUID, db: Session = Depends(get_db)):
    return {"items": landed_costs.for_receipt(db, receipt_id)}


@router.post("/goods-receipts/{receipt_id}/landed-costs", status_code=201)
def add_landed(receipt_id: uuid.UUID, payload: LandedIn, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Add freight, unloading and other charges to a receipt (now or when the bill comes); they go into the goods' cost."""
    return landed_costs.add(db, receipt_id, [c.model_dump() for c in payload.charges], payload.method, payload.note, user)


@router.get("/purchase-returns")
def list_purchase_returns(supplier_id: Optional[uuid.UUID] = Query(default=None), purchase_order_id: Optional[uuid.UUID] = Query(default=None),
                          db: Session = Depends(get_db)):
    """Goods sent back to suppliers (debit notes)."""
    return {"items": purchase_returns.list_returns(db, supplier_id, purchase_order_id), "reasons": purchase_returns.REASONS}


@router.get("/goods-receipts/{receipt_id}/returnable")
def returnable(receipt_id: uuid.UUID, db: Session = Depends(get_db)):
    """A receipt's lines with what can still go back."""
    return purchase_returns.returnable(db, receipt_id)


@router.post("/purchase-returns", status_code=201)
def create_purchase_return(payload: PurchaseReturnIn, background: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Send goods back to the supplier: stock out at the cost it came in, debit note raised (and sent to Tally)."""
    result = purchase_returns.create(db, [l.model_dump() for l in payload.lines], payload.reason, payload.goods_receipt_id, payload.purchase_order_id,
                                     payload.supplier_id, payload.note, payload.replace, payload.warehouse_id,
                                     {"transporter_id": payload.transporter_id, "vehicle_number": payload.vehicle_number}, user)
    from ..services import tally_sync

    for sync_id in tally_sync.queue_purchase_return(db, uuid.UUID(str(result["id"]))):
        background.add_task(tally_sync.process, sync_id)
    return result


@router.get("/purchase-returns/{return_id}")
def get_purchase_return(return_id: uuid.UUID, db: Session = Depends(get_db)):
    return purchase_returns.get(db, return_id)


@router.get("/rate-contracts")
def list_contracts(party: Optional[str] = Query(default=None, description="supplier or customer"), party_id: Optional[uuid.UUID] = Query(default=None),
                   db: Session = Depends(get_db)):
    """Rate contracts with status (active, expiring, expired) and quantity used against each line."""
    return {"items": rate_contracts.list_contracts(db, party, party_id)}


@router.get("/rate-contracts/supplier-rates")
def supplier_rates(supplier_id: uuid.UUID = Query(...), db: Session = Depends(get_db)):
    """Running contract rates from a supplier, per product (per base unit)."""
    from sqlalchemy import select

    from ..models import Product

    out = {}
    for contract in rate_contracts.list_contracts(db, "supplier", supplier_id, include_old=False):
        if contract["status"] == "upcoming":
            continue
        for item in contract["items"]:
            hit = rate_contracts.supplier_rate(db, supplier_id, item["product_id"])
            if hit:
                out[str(item["product_id"])] = {"rate": float(hit[0]), "contract": hit[1].number, "valid_until": hit[1].valid_until}
    return {"rates": out}


@router.post("/rate-contracts", status_code=201)
def create_contract(payload: ContractIn, db: Session = Depends(get_db)):
    """Agree rates with a supplier or customer for a period, optionally with quantities."""
    return rate_contracts.save(db, payload.model_dump(exclude_unset=True, mode="json"))


@router.get("/rate-contracts/{contract_id}")
def get_contract(contract_id: uuid.UUID, db: Session = Depends(get_db)):
    return rate_contracts.get(db, contract_id)


@router.patch("/rate-contracts/{contract_id}")
def update_contract(contract_id: uuid.UUID, payload: ContractIn, db: Session = Depends(get_db)):
    """Change dates, terms or lines (items replace them all)."""
    data = payload.model_dump(exclude_unset=True, mode="json")
    data.pop("supplier_id", None)
    data.pop("customer_id", None)
    return rate_contracts.save(db, data, contract_id)


@router.post("/rate-contracts/{contract_id}/cancel")
def cancel_contract(contract_id: uuid.UUID, db: Session = Depends(get_db)):
    return rate_contracts.cancel(db, contract_id)
