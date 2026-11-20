"""What the AI receptionist may do during a call.

A deliberately small, safe set: look up products (stock and the caller's own
price), the caller's orders and what they owe, and take an enquiry. It cannot
place orders, give discounts beyond their prices, or reveal another
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
        name="product_details",
        description="Everything about a product to describe it: description, brand, grade/size details, units it is sold in, price and stock.",
        parameters=types.Schema(type="OBJECT", properties={"product_id": types.Schema(type="STRING")}, required=["product_id"]),
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
                    "product_id": types.Schema(type="STRING"), "quantity": types.Schema(type="NUMBER"),
                    "unit": types.Schema(type="STRING", description="Unit the caller said (tonne, bag, bundle...) if it is one of the product's units.")}, required=["product_id", "quantity"])),
                "caller_name": types.Schema(type="STRING", description="Only for a new caller."),
                "notes": types.Schema(type="STRING", description="Delivery site, timing or anything else they asked."),
            },
            required=["items"],
        ),
    ),
    types.FunctionDeclaration(
        name="prepare_order",
        description="For a recognised caller who wants to order: prepare it at their prices and get the summary to read back. Then ask for a clear yes.",
        parameters=types.Schema(type="OBJECT", properties={"items": types.Schema(type="ARRAY", items=types.Schema(type="OBJECT", properties={
            "product_id": types.Schema(type="STRING"), "quantity": types.Schema(type="NUMBER"),
                    "unit": types.Schema(type="STRING", description="Unit the caller said (tonne, bag, bundle...) if it is one of the product's units.")}, required=["product_id", "quantity"]))}, required=["items"]),
    ),
    types.FunctionDeclaration(
        name="place_order",
        description="Place the order the caller just confirmed with a clear yes to the summary you read back.",
        parameters=types.Schema(type="OBJECT", properties={}),
    ),
    types.FunctionDeclaration(
        name="end_call",
        description="Hang up after saying goodbye, when the caller is done.",
        parameters=types.Schema(type="OBJECT", properties={}),
    ),
]


FINISH_TASK = types.FunctionDeclaration(
    name="finish_followup",
    description="At the end of a follow-up call: record what came of it. outcome: done (the instructions were carried out), call_back (they asked to be called later) or needs_person (a person must take over).",
    parameters=types.Schema(type="OBJECT", properties={
        "outcome": types.Schema(type="STRING", enum=["done", "call_back", "needs_person"]),
        "summary": types.Schema(type="STRING", description="Two or three sentences: what was said, agreed and promised.")}, required=["outcome", "summary"]),
)


BOOKING_DECLARATIONS = [
    types.FunctionDeclaration(
        name="confirm_booking",
        description="The transporter agreed to send a vehicle: record the vehicle number, the agreed freight in rupees and the driver's phone if given.",
        parameters=types.Schema(type="OBJECT", properties={
            "vehicle_number": types.Schema(type="STRING"), "amount": types.Schema(type="NUMBER"), "driver_phone": types.Schema(type="STRING")}),
    ),
    types.FunctionDeclaration(
        name="decline_booking",
        description="The transporter cannot send a vehicle for this trip.",
        parameters=types.Schema(type="OBJECT", properties={"reason": types.Schema(type="STRING")}),
    ),
    types.FunctionDeclaration(
        name="end_call",
        description="Hang up after saying goodbye.",
        parameters=types.Schema(type="OBJECT", properties={}),
    ),
]


_END_CALL = types.FunctionDeclaration(name="end_call", description="Hang up after saying goodbye.", parameters=types.Schema(type="OBJECT", properties={}))

#: The purchasing agent asking a supplier for prices.
SUPPLIER_QUOTE_DECLARATIONS = [
    types.FunctionDeclaration(
        name="record_quote",
        description="Record the supplier's quote once you have read it back and they agreed it is right. One entry per item they priced, "
                    "using the item number from the request and the price per the unit named in the request (before GST).",
        parameters=types.Schema(type="OBJECT", properties={
            "lines": types.Schema(type="ARRAY", items=types.Schema(type="OBJECT", properties={
                "item": types.Schema(type="INTEGER", description="Item number from the request."),
                "price": types.Schema(type="NUMBER", description="Rupees per unit as named in the request."),
                "available_quantity": types.Schema(type="NUMBER", description="Only if they can supply less than asked, in the same unit.")},
                required=["item", "price"])),
            "delivery_days": types.Schema(type="INTEGER", description="Days from order to delivery."),
            "freight": types.Schema(type="NUMBER", description="Freight or delivery charge in rupees for the whole order, 0 if free."),
            "gst_included": types.Schema(type="BOOLEAN", description="True only if they said the price includes GST."),
            "valid_days": types.Schema(type="INTEGER", description="How many days the price holds."),
            "notes": types.Schema(type="STRING", description="Anything else they said: minimum quantity, payment terms, brand.")},
            required=["lines"]),
    ),
    types.FunctionDeclaration(
        name="order_now",
        description="Only when record_quote returned can_order true and the supplier agreed to supply now: place the purchase order.",
        parameters=types.Schema(type="OBJECT", properties={
            "delivery_date": types.Schema(type="STRING", description="Agreed delivery date as YYYY-MM-DD."),
            "notes": types.Schema(type="STRING")}),
    ),
    types.FunctionDeclaration(
        name="cannot_quote",
        description="The supplier cannot supply these items.",
        parameters=types.Schema(type="OBJECT", properties={"reason": types.Schema(type="STRING")}),
    ),
    types.FunctionDeclaration(
        name="call_back_later",
        description="They are busy or need time to check prices: call again later.",
        parameters=types.Schema(type="OBJECT", properties={"minutes": types.Schema(type="INTEGER", description="When to call back, in minutes.")}),
    ),
    _END_CALL,
]

#: The purchasing agent confirming a placed purchase order.
SUPPLIER_ORDER_DECLARATIONS = [
    types.FunctionDeclaration(
        name="confirm_order",
        description="The supplier confirmed the purchase order. Record the dispatch or delivery date they gave.",
        parameters=types.Schema(type="OBJECT", properties={
            "dispatch_date": types.Schema(type="STRING", description="YYYY-MM-DD."), "notes": types.Schema(type="STRING")}),
    ),
    types.FunctionDeclaration(
        name="cannot_supply",
        description="The supplier cannot supply this order (or part of it).",
        parameters=types.Schema(type="OBJECT", properties={"reason": types.Schema(type="STRING")}),
    ),
    _END_CALL,
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
        self.booking_id: Optional[uuid.UUID] = None
        self.task_id: Optional[uuid.UUID] = None
        self.task_finished = False
        self.quote_id: Optional[uuid.UUID] = None
        self.po_id: Optional[uuid.UUID] = None
        self.call_record_id: Optional[uuid.UUID] = None

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
            {"product_id": str(p.id), "name": p.name, "brand": p.brand, "unit": p.unit_of_measure,
             "also_sold_in": ["{} ({:g} {})".format(u.name, float(u.factor), p.unit_of_measure) for u in p.alt_units if u.for_sales],
             "in_stock": float(max(Decimal("0"), p.physical_stock - reserved.get(p.id, Decimal("0")))),
             "price_per_unit": by_id.get(p.id, {}).get("net_price", float(p.mrp or 0)), "mrp": float(p.mrp or 0)}
            for p in products]}

    def _product_details(self, session: Session, args: Dict[str, Any]) -> Dict[str, Any]:
        from ..services import units as unit_service

        product = session.get(Product, uuid.UUID(str(args.get("product_id"))))
        if product is None or not product.is_active:
            return {"error": "Unknown product."}
        return unit_service.product_card(session, product, self.customer_id)

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
        from ..services import units as unit_service

        items = [{"product_id": uuid.UUID(str(i["product_id"])), "quantity": str(i["quantity"]), "unit": i.get("unit"), "discount_percent": "0"} for i in args.get("items") or []]
        if not items:
            return {"error": "No items."}
        unit_service.apply(session, items, "quantity", None, "sales")
        customer_id = self.customer_id
        # Start from the caller's best prices, like a quote typed in the app.
        resolved = {line["product_id"]: line for line in pricelists.resolve(session, customer_id, [{"product_id": i["product_id"], "quantity": i["quantity"]} for i in items])["lines"]}
        for item in items:
            hit = resolved.get(item["product_id"])
            if hit:
                item["discount_percent"] = str(hit["discount_percent"])
        # A caller not on file stays an unknown sender (name and number kept);
        # a person assigns or creates the customer later.
        enquiry = enquiry_service.create_enquiry(session, customer_id, items, notes=args.get("notes") or None, source="phone",
                                                 source_detail=self.number, sender_name=(args.get("caller_name") or "").strip() or None,
                                                 sender_phone=self.number)
        self.enquiry_id = enquiry.id
        return {"enquiry": enquiry.enquiry_number, "total": float(enquiry_service.enquiry_total(enquiry)),
                "say": "Tell the caller the enquiry number and that the team will confirm price and delivery shortly."}

    def _prepare_order(self, session: Session, args: Dict[str, Any]) -> Dict[str, Any]:
        from ..models import AgentDraft
        from ..services import automation

        if not automation.allowed(automation.step(session, "sales.confirm_order"), "pai"):
            return {"error": "Orders are confirmed by the team: take an enquiry instead."}
        if not self.customer_id:
            return {"error": "Caller not recognised: take an enquiry instead."}
        from ..services import units as unit_service

        items = [{"product_id": str(i["product_id"]), "quantity": float(i["quantity"]), "unit": i.get("unit")} for i in args.get("items") or []]
        unit_service.apply(session, items, "quantity", None, "sales")
        for item in items:
            item["quantity"], item["unit_factor"] = float(item["quantity"]), float(item["unit_factor"])
        resolved = {str(r["product_id"]): r for r in pricelists.resolve(session, self.customer_id, [{"product_id": i["product_id"], "quantity": str(i["quantity"])} for i in items])["lines"]}
        total, said = 0.0, []
        for item in items:
            hit = resolved.get(item["product_id"])
            if hit is None:
                return {"error": "Unknown product."}
            item["discount_percent"] = hit["discount_percent"]
            product = session.get(Product, uuid.UUID(item["product_id"]))
            total += hit["net_price"] * item["quantity"]
            factor = item["unit_factor"] or 1.0
            said.append("{:g} {} {} at {:,.0f} rupees per {}".format(item["quantity"] / factor, item["unit"] or product.unit_of_measure, product.name,
                                                                    hit["net_price"] * factor, item["unit"] or product.unit_of_measure))
        session.add(AgentDraft(channel="call", sender=self.number or "", customer_id=self.customer_id, items=items, total=round(total, 2)))
        session.commit()
        return {"read_back": said, "total": round(total, 2), "say": "Read this back with the total, before GST, and ask for a clear yes."}

    def _place_order(self, session: Session, args: Dict[str, Any]) -> Dict[str, Any]:
        from sqlalchemy import select

        from ..models import AgentDraft
        from ..services import automation, controls, notifications
        from ..services import orders as order_service

        draft = session.execute(select(AgentDraft).where(AgentDraft.sender == (self.number or ""), AgentDraft.channel == "call",
                                                         AgentDraft.status == "awaiting_confirmation").order_by(AgentDraft.created_at.desc())).scalars().first()
        if draft is None:
            return {"error": "No order was read back yet."}
        step = automation.step(session, "sales.confirm_order")
        broken = automation.within_limits(step, {"order_value": float(draft.total), "customer": "known"}) if step.get("mode") == "limits" else None
        gate = controls.evaluate(session, draft.customer_id, [{"product_id": i["product_id"], "quantity_ordered": i["quantity"], "discount_percent": i["discount_percent"]} for i in draft.items])
        if step.get("mode") == "approval" or broken or gate["holds"]:
            draft.status, draft.note = "held", "Needs a person: " + ("approval required by the flow" if step.get("mode") == "approval" else broken or "; ".join(h["text"] for h in gate["holds"]))
            session.commit()
            return {"held": True, "say": "Tell the caller the team will confirm the order shortly. Do not say it is placed."}
        order = order_service.create_order(session, draft.customer_id, [{"product_id": i["product_id"], "quantity_ordered": str(i["quantity"]), "discount_percent": str(i["discount_percent"]), "unit_price": None,
                                                                        "unit": i.get("unit"), "unit_factor": i.get("unit_factor") or 1} for i in draft.items],
                                           notes="Placed by PAI after the caller confirmed on the phone.")
        draft.status, draft.order_id = "placed", order.id
        session.commit()
        notifications.order_placed(order.id)
        return {"placed": order.order_number, "say": "Tell them the order number in words."}

    def booking_brief(self) -> str:
        """What PAI needs to ask a transporter for this booking."""
        from ..models import TransportBooking
        from ..services import transporters

        session = self.factory()
        try:
            booking = session.get(TransportBooking, self.booking_id) if self.booking_id else None
            if booking is None:
                return ""
            return transporters.request_message(session, booking)
        finally:
            session.close()

    def _settle(self, session: Session, answer: str, args: Dict[str, Any]) -> Dict[str, Any]:
        from ..models import TransportBooking
        from ..services import transport_automation

        booking = session.get(TransportBooking, self.booking_id) if self.booking_id else None
        if booking is None:
            return {"error": "No booking on this call."}
        amount = args.get("amount")
        result = transport_automation.settle(
            session, booking, answer, Decimal(str(amount)) if amount not in (None, "") else None,
            (str(args.get("vehicle_number") or "").replace(" ", "").upper() or None), args.get("driver_phone") or None,
            reply="On the call: {}".format(args.get("reason") or (answer + (" " + str(amount) if amount else ""))), via="pai")
        return {"status": result["status"], "say": "Thank them and say goodbye." if result["status"] in ("confirmed", "declined") else
                "Tell them the team will confirm shortly, then say goodbye."}

    def _confirm_booking(self, session: Session, args: Dict[str, Any]) -> Dict[str, Any]:
        return self._settle(session, "yes", args)

    def _decline_booking(self, session: Session, args: Dict[str, Any]) -> Dict[str, Any]:
        return self._settle(session, "no", args)

    def task_brief(self) -> str:
        from ..services import triggers

        session = self.factory()
        try:
            return triggers.call_brief(session, self.task_id) if self.task_id else ""
        finally:
            session.close()

    def _finish_followup(self, session: Session, args: Dict[str, Any]) -> Dict[str, Any]:
        from ..services import triggers

        if not self.task_id:
            return {"error": "No follow-up on this call."}
        triggers.finish_call(session, self.task_id, str(args.get("outcome") or "needs_person"), str(args.get("summary") or ""))
        self.task_finished = True
        return {"ok": True, "say": "Thank them and say goodbye, then end the call."}

    # --- purchasing agent -------------------------------------------------

    def supplier_brief(self) -> str:
        from ..services import supplier_calls

        session = self.factory()
        try:
            if self.quote_id:
                return supplier_calls.quote_brief(session, self.quote_id)
            if self.po_id:
                return supplier_calls.order_brief(session, self.po_id)
            return ""
        finally:
            session.close()

    def _record_quote(self, session: Session, args: Dict[str, Any]) -> Dict[str, Any]:
        from ..services import supplier_calls

        if not self.quote_id:
            return {"error": "No price request on this call."}
        return supplier_calls.record_quote(session, self.quote_id, args, self.call_record_id)

    def _order_now(self, session: Session, args: Dict[str, Any]) -> Dict[str, Any]:
        from ..services import supplier_calls

        if not self.quote_id:
            return {"error": "No price request on this call."}
        return supplier_calls.order_now(session, self.quote_id, args, self.call_record_id)

    def _cannot_quote(self, session: Session, args: Dict[str, Any]) -> Dict[str, Any]:
        from ..services import supplier_calls

        return supplier_calls.cannot_quote(session, self.quote_id, str(args.get("reason") or "")) if self.quote_id else {"error": "No price request."}

    def _call_back_later(self, session: Session, args: Dict[str, Any]) -> Dict[str, Any]:
        from ..services import supplier_calls

        return supplier_calls.call_back(session, self.quote_id, args.get("minutes")) if self.quote_id else {"error": "No price request."}

    def _confirm_order(self, session: Session, args: Dict[str, Any]) -> Dict[str, Any]:
        from ..services import supplier_calls

        return supplier_calls.confirm_order(session, self.po_id, args) if self.po_id else {"error": "No purchase order."}

    def _cannot_supply(self, session: Session, args: Dict[str, Any]) -> Dict[str, Any]:
        from ..services import supplier_calls

        return supplier_calls.cannot_supply(session, self.po_id, str(args.get("reason") or "")) if self.po_id else {"error": "No purchase order."}

    def _end_call(self, session: Session, args: Dict[str, Any]) -> Dict[str, Any]:
        self.hangup = True
        return {"ok": True}
