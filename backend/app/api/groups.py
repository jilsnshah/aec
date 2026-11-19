"""Smart customer groups, a customer's own pricing, and applying the best
prices to an enquiry."""
from __future__ import annotations

import uuid
from typing import Any, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..services import enquiries as enquiry_service
from ..services import groups, pricelists

router = APIRouter(prefix="/api", tags=["pricing"])


class Rule(BaseModel):
    field: str
    op: str = Field(description=">=, <=, >, <, = or !=")
    value: Any


class GroupPriceItem(BaseModel):
    product_id: uuid.UUID
    min_quantity: Optional[str] = "0"
    price: Optional[str] = None
    discount_percent: Optional[str] = None


class GroupIn(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    rules: Optional[List[Rule]] = Field(default=None, description="Empty for a group picked by hand only.")
    match: Optional[str] = Field(default=None, description="all or any")
    discount_percent: Optional[str] = Field(default=None, description="Members' discount off MRP on everything; empty for none.")
    items: Optional[List[GroupPriceItem]] = Field(default=None, description="Members' product prices: fixed price or discount_percent, from min_quantity (replaces them all).")
    price_list_id: Optional[uuid.UUID] = Field(default=None, description="Legacy; prefer discount_percent and items.")
    is_active: Optional[bool] = None


class PreviewIn(BaseModel):
    rules: List[Rule]
    match: str = "all"


class MemberIn(BaseModel):
    source: Optional[str] = Field(default=None, description="manual (add by hand), excluded (keep out), or null to undo.")


class OwnPriceItem(BaseModel):
    product_id: uuid.UUID
    min_quantity: Optional[str] = "0"
    price: Optional[str] = None
    discount_percent: Optional[str] = None


class CustomerPricingIn(BaseModel):
    discount_percent: Optional[str] = Field(default=None, description="Flat discount for this customer; empty clears it.")
    items: Optional[List[OwnPriceItem]] = Field(default=None, description="This customer's own product prices (replaces them).")


@router.get("/customer-groups/fields")
def rule_fields():
    """What group rules can test: orders, spend, years with us, days since last
    order, money owed and overdue, segment, city, state."""
    return {"fields": groups.FIELDS, "ops": sorted(groups.OPS)}


@router.get("/customer-groups")
def list_groups(db: Session = Depends(get_db)):
    """Customer groups with their rules, prices and member count."""
    return {"items": groups.list_groups(db)}


@router.post("/customer-groups", status_code=201)
def create_group(payload: GroupIn, db: Session = Depends(get_db)):
    """Create a group: members by hand and/or rules, and the prices members get (discount_percent and product items)."""
    return groups.save(db, payload.model_dump(exclude_unset=True, mode="json"))


@router.post("/customer-groups/preview")
def preview(payload: PreviewIn, db: Session = Depends(get_db)):
    """Who these rules would put in a group, without saving."""
    return groups.preview(db, [r.model_dump() for r in payload.rules], payload.match)


@router.post("/customer-groups/recalculate")
def recalculate_all(db: Session = Depends(get_db)):
    """Recalculate every group's members now (also done once a day)."""
    return groups.recompute(db)


@router.get("/customer-groups/{group_id}")
def get_group(group_id: uuid.UUID, db: Session = Depends(get_db)):
    """A group with its members (rule, manual or excluded)."""
    return groups.get(db, group_id)


@router.put("/customer-groups/{group_id}")
def update_group(group_id: uuid.UUID, payload: GroupIn, db: Session = Depends(get_db)):
    """Change a group's name, rules, members' discount or product prices."""
    return groups.save(db, payload.model_dump(exclude_unset=True, mode="json"), group_id)


@router.delete("/customer-groups/{group_id}", status_code=204)
def delete_group(group_id: uuid.UUID, db: Session = Depends(get_db)):
    groups.delete_group(db, group_id)


@router.put("/customer-groups/{group_id}/members/{customer_id}")
def set_member(group_id: uuid.UUID, customer_id: uuid.UUID, payload: MemberIn, db: Session = Depends(get_db)):
    """Add a customer to a group by hand, keep one out, or undo."""
    return groups.set_member(db, group_id, customer_id, payload.source)


@router.get("/customers/{customer_id}/pricing")
def customer_pricing(customer_id: uuid.UUID, db: Session = Depends(get_db)):
    """A customer's flat discount, own product prices and groups (with how they joined)."""
    return pricelists.customer_pricing(db, customer_id)


@router.put("/customers/{customer_id}/pricing")
def set_customer_pricing(customer_id: uuid.UUID, payload: CustomerPricingIn, db: Session = Depends(get_db)):
    """Set a customer's flat discount and/or own product prices (fixed price or discount, from a quantity)."""
    data = payload.model_dump(exclude_unset=True)
    return pricelists.save_customer_pricing(
        db, customer_id, data["discount_percent"] if "discount_percent" in data else ...,
        [i.model_dump() for i in payload.items] if payload.items is not None else None,
    )


@router.post("/enquiries/{enquiry_id}/apply-prices")
def apply_prices(enquiry_id: uuid.UUID, db: Session = Depends(get_db)):
    """Set every line of an open enquiry to the customer's best price (own
    prices, discount, groups); says what changed."""
    return enquiry_service.apply_best_prices(db, enquiry_id)


class LinkIn(BaseModel):
    enabled: bool = True


@router.get("/customers/{customer_id}/enquiry-link")
def get_enquiry_link(customer_id: uuid.UUID, db: Session = Depends(get_db)):
    """The customer's own enquiry page link (path), if switched on."""
    from ..errors import NotFoundError
    from ..models import Customer
    from ..services import portal

    customer = db.get(Customer, customer_id)
    if customer is None:
        raise NotFoundError("Customer not found.")
    return portal.link_view(customer)


@router.post("/customers/{customer_id}/enquiry-link")
def set_enquiry_link(customer_id: uuid.UUID, payload: LinkIn, db: Session = Depends(get_db)):
    """Create a new link for the customer (the old one stops working), or switch it off (enabled false)."""
    from ..services import portal

    return portal.set_link(db, customer_id, payload.enabled)
