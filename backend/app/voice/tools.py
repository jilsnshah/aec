"""What the AI receptionist may do during a call.

A deliberately small, safe set: look up products (stock and the caller's own
price), the caller's orders and what they owe, and take an enquiry. It cannot
place orders, give discounts beyond the price list, or reveal another
customer's information. A caller is identified only by the number they call
from; an unknown number gets general product information only.
"""
from __future__ import annotations

import re
import uuid
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional

from google.genai import types
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models import Customer, OrderStatus, Product, SalesOrder
from ..services import enquiries as enquiry_service
from ..services import finance, pricelists, reservations


def match_caller(session: Session, number: Optional[str]) -> Optional[Customer]:
    """The customer whose phone numbers include this one (any of them)."""
    from ..services import parties

    kind, party = parties.find_by_phone(session, number)
    return party if kind == "customer" and party is not None and party.is_active else None


def caller_brief(session: Session, customer: Optional[Customer]) -> str:
    if customer is None:
        return "The caller's number is not on record: treat them as a new customer. Ask their name and business."
    owed = finance.statement(session, "customer", customer.id)["summary"]
    open_orders = session.execute(
        select(func.count(SalesOrder.id)).where(SalesOrder.customer_id == customer.id,
                                                SalesOrder.status.in_([OrderStatus.PENDING, OrderStatus.PARTIALLY_FULFILLED]))
    ).scalar_one()
    return ("The caller is the existing customer {} (phone on record). Open orders: {}. They owe ₹{:,.0f}, of which ₹{:,.0f} is overdue. "
            "Greet them by name.".format(customer.name, open_orders, owed["open"], owed["overdue"]))


DECLARATIONS = [
    types.FunctionDeclaration(
        name="find_products",
        description="Search products by name or code (e.g. 'cement', 'tmt 8mm'). Returns name, unit, free stock and the price for this caller.",
        parameters=types.Schema(type="OBJECT", properties={"query": types.Schema(type="STRING")}, required=["query"]),
    ),
    types.FunctionDeclaration(
        name="my_orders",
        description="The caller's open orders: what is delivered, ready and still to come. Only for a recognised caller.",
        parameters=types.Schema(type="OBJECT", properties={}),
    ),
    types.FunctionDeclaration(
        name="my_balance",
        description="What the caller owes and what is overdue. Only for a recognised caller.",
        parameters=types.Schema(type="OBJECT", properties={}),
    ),
    types.FunctionDeclaration(
        name="take_enquiry",
        description=("Record the caller's request as an enquiry (a quote) for the sales team, AFTER reading the items and quantities "
                     "back and the caller agreeing. For a new caller give their name. product_id comes from find_products."),
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "items": types.Schema(type="ARRAY", items=types.Schema(type="OBJECT", properties={
                    "product_id": types.Schema(type="STRING"), "quantity": types.Schema(type="NUMBER")}, required=["product_id", "quantity"])),
                "caller_name": types.Schema(type="STRING", description="Only for a new caller."),
                "notes": types.Schema(type="STRING", description="Delivery site, timing or anything else they asked."),
            },
            required=["items"],
        ),
    ),
    types.FunctionDeclaration(
        name="end_call",
        description="Hang up after saying goodbye, when the caller is done.",
        parameters=types.Schema(type="OBJECT", properties={}),
    ),
]


class CallTools:
    def __init__(self, factory: Callable[[], Session], caller_number: Optional[str]):
        self.factory = factory
        self.number = caller_number
        self.customer_id: Optional[uuid.UUID] = None
        self.customer_name: Optional[str] = None
        self.enquiry_id: Optional[uuid.UUID] = None
        self.actions: List[Dict[str, Any]] = []
        self.hangup = False

    def identify(self) -> str:
        session = self.factory()
        try:
            customer = match_caller(session, self.number)
            if customer:
                self.customer_id, self.customer_name = customer.id, customer.name
            return caller_brief(session, customer)
        finally:
            session.close()

    def run(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        session = self.factory()
        try:
            handler = getattr(self, "_" + name, None)
            if handler is None:
                return {"error": "unknown tool"}
            result = handler(session, args or {})
            self.actions.append({"tool": name, "args": args, "ok": "error" not in result})
            return result
        except Exception as exc:  # report, don't crash the call
            session.rollback()
            return {"error": str(exc)[:300]}
        finally:
            session.close()

    def _find_products(self, session: Session, args: Dict[str, Any]) -> Dict[str, Any]:
        words = [w for w in re.split(r"\s+", str(args.get("query", "")).strip()) if w]
        stmt = select(Product).where(Product.is_active.is_(True))
        for word in words[:4]:
            pattern = "%{}%".format(word.lower())
            stmt = stmt.where(or_(func.lower(Product.name).like(pattern), func.lower(Product.sku).like(pattern), func.lower(func.coalesce(Product.category, "")).like(pattern)))
        products = session.execute(stmt.limit(6)).scalars().all()
        if not products and words:
            products = session.execute(select(Product).where(Product.is_active.is_(True), func.lower(Product.name).like("%{}%".format(words[0].lower()))).limit(6)).scalars().all()
        reserved = reservations.reserved_map(session, [p.id for p in products])
        prices = pricelists.resolve(session, self.customer_id, [{"product_id": p.id, "quantity": "1"} for p in products])["lines"] if products else []
        by_id = {line["product_id"]: line for line in prices}
        return {"products": [
            {"product_id": str(p.id), "name": p.name, "unit": p.unit_of_measure,
             "in_stock": float(max(Decimal("0"), p.physical_stock - reserved.get(p.id, Decimal("0")))),
             "price_per_unit": by_id.get(p.id, {}).get("net_price", float(p.mrp or 0)), "mrp": float(p.mrp or 0)}
            for p in products]}

    def _my_orders(self, session: Session, args: Dict[str, Any]) -> Dict[str, Any]:
        if not self.customer_id:
            return {"error": "Caller not recognised; do not share order details."}
        orders = session.execute(
            select(SalesOrder).where(SalesOrder.customer_id == self.customer_id,
                                     SalesOrder.status.in_([OrderStatus.PENDING, OrderStatus.PARTIALLY_FULFILLED]))
            .order_by(SalesOrder.created_at.desc()).limit(5)
        ).scalars().all()
        out = []
        for order in orders:
            out.append({"order": order.order_number, "placed": order.created_at.date().isoformat(), "lines": [
                {"product": item.product.name, "ordered": float(item.quantity_ordered), "delivered": float(item.quantity_fulfilled),
                 "ready_to_send": float(item.quantity_reserved), "waiting_for_stock": float(item.quantity_unallocated + item.quantity_incoming)}
                for item in order.items]})
        return {"open_orders": out}

    def _my_balance(self, session: Session, args: Dict[str, Any]) -> Dict[str, Any]:
        if not self.customer_id:
            return {"error": "Caller not recognised; do not share account details."}
        summary = finance.statement(session, "customer", self.customer_id)["summary"]
        return {"owed": summary["open"], "overdue": summary["overdue"], "payment_terms_days": summary["payment_terms_days"]}

    def _take_enquiry(self, session: Session, args: Dict[str, Any]) -> Dict[str, Any]:
        items = [{"product_id": uuid.UUID(str(i["product_id"])), "quantity": str(i["quantity"]), "discount_percent": "0"} for i in args.get("items") or []]
        if not items:
            return {"error": "No items."}
        customer_id = self.customer_id
        if customer_id is None:
            from ..services import customers as customer_service

            name = (args.get("caller_name") or "").strip() or "Phone caller {}".format(self.number or "")
            customer = customer_service.create_customer(session, name=name, phone=self.number)
            customer_id, self.customer_id, self.customer_name = customer.id, customer.id, customer.name
        # Start from the caller's price list, like a quote typed in the app.
        resolved = {line["product_id"]: line for line in pricelists.resolve(session, customer_id, [{"product_id": i["product_id"], "quantity": i["quantity"]} for i in items])["lines"]}
        for item in items:
            hit = resolved.get(item["product_id"])
            if hit:
                item["discount_percent"] = str(hit["discount_percent"])
        enquiry = enquiry_service.create_enquiry(session, customer_id, items, notes=args.get("notes") or None, source="phone", source_detail=self.number)
        self.enquiry_id = enquiry.id
        return {"enquiry": enquiry.enquiry_number, "total": float(enquiry_service.enquiry_total(enquiry)),
                "say": "Tell the caller the enquiry number and that the team will confirm price and delivery shortly."}

    def _end_call(self, session: Session, args: Dict[str, Any]) -> Dict[str, Any]:
        self.hangup = True
        return {"ok": True}
