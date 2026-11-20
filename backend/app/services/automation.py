"""Automation pipelines: the sales and purchase flows, step by step.

Each flow is a graph: nodes are steps (from the step library below) with their
settings -- who does it (system, person, TAI the text agent, PAI the phone
agent, or several), how much it may do alone (auto, auto within limits, prepare
for approval, off), its limits, the AI model and instructions, channels and
timing -- and edges give the order. Users edit the flows in Settings ->
Automation; the agents read their step's settings when they act.

A step is "live" when the app can carry it out today and "planned" when its
settings are kept for when it can; the editor shows which is which.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..database import begin_write
from ..errors import NotFoundError, ValidationError
from ..models import AutomationFlow, User
from .automation_config import clean, defaults

ACTORS = ("system", "person", "tai", "pai")
MODES = ("auto", "limits", "approval", "off")
CATEGORIES = ("trigger", "communicate", "decide", "record", "person")

#: Limits a step can be given, by key.
LIMIT_FIELDS = {
    "order_value": {"label": "Order value", "unit": "₹"},
    "discount_percent": {"label": "Discount", "unit": "%"},
    "extra_discount_percent": {"label": "Extra discount beyond price list", "unit": "%"},
    "margin_percent": {"label": "Margin", "unit": "%"},
    "customer": {"label": "Customer is", "choices": ["known", "new"]},
    "segment": {"label": "Customer segment", "choices": ["champion", "loyal", "occasional", "at_risk", "dormant", "new"]},
    "po_value": {"label": "Purchase order value", "unit": "₹"},
    "price_change_percent": {"label": "Price above last paid", "unit": "%"},
    "supplier_score": {"label": "Supplier score", "unit": "/100"},
    "days_overdue": {"label": "Days overdue", "unit": "days"},
    "freight_amount": {"label": "Freight agreed", "unit": "₹"},
    "over_estimate_percent": {"label": "Freight above the rate card", "unit": "%"},
}


def _step(key, flow, label, category, actors, default_actor, live, description, limits=(), ai=False, channels=(), timing=None, modes=MODES):
    from .automation_config import CONFIG

    return {"key": key, "flow": flow, "label": label, "category": category, "actors": list(actors), "default_actor": default_actor,
            "live": live, "description": description, "limit_fields": list(limits), "ai": ai, "channels": list(channels),
            "timing": timing, "modes": list(modes), "config_fields": CONFIG.get(key, [])}


LIBRARY: List[Dict[str, Any]] = [
    # --- Sales ------------------------------------------------------------------------
    _step("sales.trigger_incoming", "sales", "Enquiry comes in", "trigger", ["tai", "pai", "person"], "tai", True,
          "A WhatsApp message, email, phone call or the customer's own link starts the flow.", channels=("whatsapp", "email", "call", "link")),
    _step("sales.trigger_outreach", "sales", "Reach out to customers", "trigger", ["tai", "pai", "person"], "tai", True,
          "Contact customers who are late for their usual order, or dormant ones worth winning back.", limits=("segment",), ai=True,
          channels=("whatsapp", "call"), timing={"every_days": 1}),
    _step("sales.identify", "sales", "Identify the customer", "record", ["system"], "system", True,
          "Exact match of the sender's phone number or email to a customer on file. Unknown senders wait for a person.", modes=("auto",)),
    _step("sales.understand", "sales", "Understand what they want", "communicate", ["tai", "pai", "person"], "tai", True,
          "Products and quantities from the message or call, using product aliases; asks back when unclear.", ai=True, channels=("whatsapp", "email", "call")),
    _step("sales.check_stock", "sales", "Check stock and delivery", "record", ["system"], "system", True,
          "Free stock, stock on order and lead time for each line.", modes=("auto",)),
    _step("sales.price", "sales", "Price and discount", "decide", ["system", "tai", "pai", "person"], "system", True,
          "Best price from the customer's own prices, discount, price list and groups; any extra bargaining within limits.",
          limits=("extra_discount_percent", "margin_percent", "segment"), ai=True),
    _step("sales.send_quote", "sales", "Send the quote", "communicate", ["tai", "pai", "person"], "tai", True,
          "Reply with prices, stock and the quote PDF (WhatsApp within 24 h of their message, or email).", ai=True,
          channels=("whatsapp", "email", "call")),
    _step("sales.confirm_order", "sales", "Customer confirms, order placed", "decide", ["tai", "pai", "person"], "person", True,
          "Read back items and total; on a clear yes, place the order (credit, discount and margin holds still apply).",
          limits=("order_value", "customer", "segment"), ai=True, channels=("whatsapp", "email", "call")),
    _step("sales.order_confirmation", "sales", "Order confirmation", "communicate", ["system"], "system", True,
          "Approved WhatsApp template to the customer when the order is placed.", channels=("whatsapp",), modes=("auto", "off")),
    _step("sales.invoice", "sales", "Invoice in Tally", "record", ["system"], "system", True,
          "Invoice created in Tally when the order is placed or on each delivery, and sent on WhatsApp.",
          timing={"invoice_on": "order"}, modes=("auto", "off")),
    _step("sales.plan_dispatch", "sales", "Plan dispatch", "decide", ["system", "person"], "person", False,
          "What is ready, grouped by customer and area, for loading."),
    _step("sales.deliver", "sales", "Deliver", "person", ["person"], "person", True,
          "Goods leave with the truck; recorded as a delivery (partial allowed).", modes=("approval",)),
    _step("sales.payment_reminders", "sales", "Payment reminders", "communicate", ["tai", "pai", "person"], "person", True,
          "Friendly, firm and final reminders by days overdue; a call at the final level.", limits=("days_overdue",), ai=True,
          channels=("whatsapp", "call"), timing={"every_days": 3}),
    _step("sales.payment_received", "sales", "Payment received", "person", ["person", "system"], "person", True,
          "Recorded by a person today; automatic with payment links or a bank feed.", modes=("approval", "auto")),
    _step("sales.after_sales", "sales", "After-sales follow-up", "communicate", ["tai", "pai", "person"], "tai", True,
          "After delivery: was everything right? A rating, and any complaint becomes a task for the team.", ai=True, channels=("whatsapp", "call")),
    # --- Purchase ---------------------------------------------------------------------
    _step("sales.book_transport", "sales", "Book transport", "communicate", ["system", "person", "tai", "pai"], "tai", True,
          "Ask a transporter for a vehicle: when the order is placed or its stock is ready. TAI asks on WhatsApp, PAI calls; "
          "a YES with the vehicle number and rate confirms it within the limits, a NO moves on to the next transporter.",
          limits=("freight_amount", "over_estimate_percent"), ai=True, channels=("whatsapp", "call"),
          timing={"when": "order_placed", "choose": "cheapest", "transporter_id": "", "vehicle_type": ""}),
    _step("purchase.need_detected", "purchase", "Need detected", "trigger", ["system", "person"], "system", True,
          "Watches stock on a schedule: customers short, below the reorder point, low days of cover, or a weekly review. "
          "Then asks suppliers for prices, drafts a PO or makes a task.", modes=("auto", "off")),
    _step("purchase.choose_supplier", "purchase", "Choose supplier and quantity", "decide", ["system", "person"], "system", True,
          "Cheapest reliable supplier, quantity from lead time and sales, target price from the last paid.", limits=("supplier_score",)),
    _step("purchase.ask_supplier", "purchase", "Ask the supplier", "communicate", ["tai", "pai", "person"], "tai", True,
          "Ask availability, price and delivery date; to two or three suppliers at once. By WhatsApp/email (text AI) or by phone "
          "(purchasing voice AI), which can also place the order on the call.", ai=True, channels=("whatsapp", "call", "email")),
    _step("purchase.read_reply", "purchase", "Read the reply", "communicate", ["tai", "pai", "person"], "tai", True,
          "Record the supplier's price, quantity and date; unclear replies go to a person.", ai=True),
    _step("purchase.compare_quotes", "purchase", "Compare and pick", "decide", ["system", "person"], "system", True,
          "Lowest price weighed with reliability and delivery date.", limits=("supplier_score",)),
    _step("purchase.approve_po", "purchase", "Approve", "decide", ["system", "person"], "person", True,
          "Automatic within limits, otherwise one tap in the approvals inbox.", limits=("po_value", "price_change_percent")),
    _step("purchase.place_po", "purchase", "Create and place the PO", "record", ["system", "person"], "person", True,
          "The purchase order is placed and sent to Tally."),
    _step("purchase.send_po", "purchase", "Send the PO to the supplier", "communicate", ["system", "pai"], "system", True,
          "WhatsApp message with the PO; optionally the voice AI calls to confirm the order and the dispatch date.",
          channels=("whatsapp", "call"), modes=("auto", "off")),
    _step("purchase.chase_delivery", "purchase", "Chase the delivery", "communicate", ["tai", "pai", "person"], "tai", True,
          "Confirm before the due date, ask again when late, update the expected date from the reply, then a task for the buyer.",
          ai=True, channels=("whatsapp", "call")),
    _step("purchase.receive_goods", "purchase", "Receive goods", "person", ["person"], "person", True,
          "Count and receive; 'scan bill' fills it in from a photo of the delivery note.", modes=("approval",)),
    _step("purchase.allocate", "purchase", "Give stock to waiting customers", "record", ["system"], "system", True,
          "Oldest orders first.", modes=("auto",)),
    _step("purchase.book_transport", "purchase", "Book transport (pickup)", "communicate", ["system", "person", "tai", "pai"], "tai", True,
          "When we collect from the supplier: book a vehicle once the purchase order is placed. TAI asks on WhatsApp, PAI calls.",
          limits=("freight_amount", "over_estimate_percent"), ai=True, channels=("whatsapp", "call"),
          timing={"when": "po_placed", "choose": "cheapest", "transporter_id": "", "vehicle_type": ""}),
    _step("purchase.pay_supplier", "purchase", "Pay the supplier", "person", ["person"], "person", True,
          "Money leaves the business: always a person, after order, receipt and bill agree.", modes=("approval",)),
]
LIBRARY_BY_KEY = {s["key"]: s for s in LIBRARY}
#: Steps switched off for now: transport is booked by hand (Buying → Transporters).
#: They are hidden from the flow editor, dropped from saved flows and never run.
PARKED = {"sales.book_transport", "purchase.book_transport"}

DEFAULT_SEQUENCE = {
    "sales": ["sales.trigger_incoming", "sales.identify", "sales.understand", "sales.check_stock", "sales.price", "sales.send_quote",
              "sales.confirm_order", "sales.order_confirmation", "sales.invoice", "sales.plan_dispatch", "sales.deliver",
              "sales.payment_reminders", "sales.payment_received", "sales.after_sales"],
    "purchase": ["purchase.need_detected", "purchase.choose_supplier", "purchase.ask_supplier", "purchase.read_reply",
                 "purchase.compare_quotes", "purchase.approve_po", "purchase.place_po", "purchase.send_po",
                 "purchase.chase_delivery", "purchase.receive_goods", "purchase.allocate", "purchase.pay_supplier"],
}
#: Default limits and modes where the step should start careful.
DEFAULT_OVERRIDES: Dict[str, Dict[str, Any]] = {
    "sales.price": {"mode": "limits", "limits": [{"field": "extra_discount_percent", "op": "<=", "value": 0}]},
    "sales.send_quote": {"mode": "approval"},
    "sales.confirm_order": {"mode": "approval", "limits": [{"field": "customer", "op": "=", "value": "known"}, {"field": "order_value", "op": "<=", "value": 50000}]},
    "sales.order_confirmation": {"mode": "off"},
    "sales.payment_reminders": {"mode": "approval"},
    "purchase.approve_po": {"mode": "approval", "limits": [{"field": "po_value", "op": "<=", "value": 100000}, {"field": "price_change_percent", "op": "<=", "value": 3}]},
    "purchase.ask_supplier": {"mode": "approval"},
}


def default_node(step_key: str, index: int, node_id: Optional[str] = None) -> Dict[str, Any]:
    step = LIBRARY_BY_KEY[step_key]
    data = {
        "step": step_key,
        "title": step["label"],
        "actors": [step["default_actor"]],
        "mode": step["modes"][0] if step["modes"] != list(MODES) else "auto",
        "limits": [],
        "ai": {"model": "", "instructions": ""} if step["ai"] else None,
        "channels": list(step["channels"]),
        "timing": copy.deepcopy(step["timing"]),
        "config": defaults(step["config_fields"]) if step["config_fields"] else None,
        "notes": "",
    }
    data.update(copy.deepcopy(DEFAULT_OVERRIDES.get(step_key, {})))
    return {"id": node_id or "n{}".format(index + 1), "type": "step", "position": {"x": (index % 4) * 340, "y": (index // 4) * 190}, "data": data}


def default_flow(key: str) -> Dict[str, Any]:
    keys = DEFAULT_SEQUENCE[key]
    nodes = [default_node(k, i) for i, k in enumerate(keys)]
    edges = [{"id": "e{}".format(i + 1), "source": nodes[i]["id"], "target": nodes[i + 1]["id"]} for i in range(len(nodes) - 1)]
    return {"key": key, "name": "Sales" if key == "sales" else "Purchase", "nodes": nodes, "edges": edges}


def _validate(key: str, flow: Dict[str, Any]) -> Dict[str, Any]:
    if key not in DEFAULT_SEQUENCE:
        raise NotFoundError("No flow called {}.".format(key))
    nodes = flow.get("nodes") or []
    edges = flow.get("edges") or []
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValidationError("A flow needs nodes and edges.")
    nodes, edges = _without_parked(nodes, edges)
    if len(nodes) > 80:
        raise ValidationError("A flow can have at most 80 steps.")
    ids = set()
    clean_nodes = []
    for node in nodes:
        data = dict(node.get("data") or {})
        step = LIBRARY_BY_KEY.get(data.get("step"))
        if step is None or step["flow"] != key:
            raise ValidationError("Unknown step '{}' for the {} flow.".format(data.get("step"), key))
        node_id = str(node.get("id") or "")
        if not node_id or node_id in ids:
            raise ValidationError("Every step needs its own id.")
        ids.add(node_id)
        actors = [a for a in (data.get("actors") or []) if a in step["actors"]]
        if not actors:
            raise ValidationError("'{}' needs someone to do it: {}.".format(data.get("title") or step["label"], ", ".join(step["actors"])))
        mode = data.get("mode")
        if mode not in step["modes"]:
            raise ValidationError("'{}' can only be {}.".format(data.get("title") or step["label"], ", ".join(step["modes"])))
        limits = []
        for limit in data.get("limits") or []:
            if limit.get("field") not in step["limit_fields"]:
                raise ValidationError("'{}' cannot be limited by {}.".format(step["label"], limit.get("field")))
            if limit.get("op") not in (">=", "<=", "=", "!="):
                raise ValidationError("Unknown comparison in a limit.")
            limits.append({"field": limit["field"], "op": limit["op"], "value": limit.get("value")})
        ai = data.get("ai") if step["ai"] else None
        if ai is not None:
            ai = {"model": str(ai.get("model") or "")[:80], "instructions": str(ai.get("instructions") or "")[:4000]}
        clean_nodes.append({
            "id": node_id, "type": "step",
            "position": {"x": float((node.get("position") or {}).get("x", 0)), "y": float((node.get("position") or {}).get("y", 0))},
            "data": {"step": step["key"], "title": str(data.get("title") or step["label"])[:80], "actors": actors, "mode": mode,
                     "limits": limits, "ai": ai, "channels": [c for c in (data.get("channels") or []) if c in step["channels"]],
                     "timing": data.get("timing") if isinstance(data.get("timing"), dict) else step["timing"],
                     "config": clean(step["config_fields"], data.get("config")) if step["config_fields"] else None,
                     "notes": str(data.get("notes") or "")[:2000]},
        })
    clean_edges = []
    for edge in edges:
        if edge.get("source") not in ids or edge.get("target") not in ids or edge.get("source") == edge.get("target"):
            raise ValidationError("A connection points at a step that is not in the flow.")
        clean_edges.append({"id": str(edge.get("id") or "{}-{}".format(edge["source"], edge["target"])), "source": edge["source"], "target": edge["target"],
                            "label": str(edge.get("label") or "")[:40] or None})
    return {"key": key, "name": "Sales" if key == "sales" else "Purchase", "nodes": clean_nodes, "edges": clean_edges}


def _without_parked(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]):
    """Drop parked steps, joining what came before each one to what came after."""
    parked = {n.get("id") for n in nodes if (n.get("data") or {}).get("step") in PARKED}
    if not parked:
        return nodes, edges
    edges = list(edges)
    for node_id in parked:
        into = [e["source"] for e in edges if e.get("target") == node_id]
        out = [e["target"] for e in edges if e.get("source") == node_id]
        edges = [e for e in edges if node_id not in (e.get("source"), e.get("target"))]
        known = {(e["source"], e["target"]) for e in edges}
        for a in into:
            for b in out:
                if a != b and (a, b) not in known:
                    edges.append({"id": "{}-{}".format(a, b), "source": a, "target": b})
                    known.add((a, b))
    return [n for n in nodes if n.get("id") not in parked], edges


def get(session: Session, key: str) -> Dict[str, Any]:
    if key not in DEFAULT_SEQUENCE:
        raise NotFoundError("No flow called {}.".format(key))
    row = session.get(AutomationFlow, key)
    flow = row.flow if row is not None else _defaults_from_settings(session, default_flow(key))
    nodes, edges = _without_parked(flow.get("nodes") or [], flow.get("edges") or [])
    flow = {**flow, "nodes": nodes, "edges": edges}
    return {**flow, "updated_at": row.updated_at if row else None, "updated_by": row.updated_by if row else None, "customised": row is not None}


def _defaults_from_settings(session: Session, flow: Dict[str, Any]) -> Dict[str, Any]:
    from . import integration_settings as settings_service

    whatsapp = settings_service.get(session, settings_service.WHATSAPP).config
    tally = settings_service.get(session, settings_service.TALLY).config
    for node in flow["nodes"]:
        data = node["data"]
        if data["step"] == "sales.order_confirmation":
            data["mode"] = "auto" if whatsapp.get("send_order_confirmations") else "off"
        if data["step"] == "sales.invoice":
            data["timing"] = {"invoice_on": tally.get("invoice_on", "order")}
            data["mode"] = "auto" if tally.get("create_invoices", True) else "off"
    return flow


def save(session: Session, key: str, flow: Dict[str, Any], user: Optional[User] = None) -> Dict[str, Any]:
    clean = _validate(key, flow)
    begin_write(session)
    try:
        row = session.get(AutomationFlow, key) or AutomationFlow(key=key)
        row.flow = clean
        row.updated_by = user.username if user else None
        session.add(row)
        session.flush()
        _sync_settings(session, clean)
        from .controls import log

        log(session, user, "automation_saved", "automation", key, "{} flow saved: {} steps".format(clean["name"], len(clean["nodes"])))
        session.commit()
    except Exception:
        session.rollback()
        raise
    return get(session, key)


def reset(session: Session, key: str, user: Optional[User] = None) -> Dict[str, Any]:
    begin_write(session)
    row = session.get(AutomationFlow, key)
    if row is not None:
        session.delete(row)
    session.commit()
    return get(session, key)


def _sync_settings(session: Session, flow: Dict[str, Any]) -> None:
    """Steps that existing settings already control keep those settings in step."""
    from ..models import IntegrationSetting
    from . import integration_settings as settings_service

    def row(name: str) -> IntegrationSetting:
        stored = session.get(IntegrationSetting, name)
        if stored is None:
            stored = IntegrationSetting(name=name, enabled=False, config=dict(settings_service.DEFINITIONS[name]["config"]), secrets=None)
            session.add(stored)
        return stored

    for node in flow["nodes"]:
        data = node["data"]
        if data["step"] == "sales.order_confirmation":
            stored = row(settings_service.WHATSAPP)
            stored.config = {**(stored.config or {}), "send_order_confirmations": data["mode"] == "auto"}
        if data["step"] == "sales.invoice":
            stored = row(settings_service.TALLY)
            timing = data.get("timing") if isinstance(data.get("timing"), dict) else {}
            stored.config = {**(stored.config or {}), "create_invoices": data["mode"] != "off",
                             **({"invoice_on": timing["invoice_on"]} if timing.get("invoice_on") in ("order", "delivery") else {})}


def step(session: Session, step_key: str) -> Dict[str, Any]:
    """The settings of the first node of a step type in its flow (defaults if
    the step is not in the flow -- then it counts as off)."""
    flow_key = step_key.split(".")[0]
    flow = get(session, flow_key)
    fields = LIBRARY_BY_KEY[step_key]["config_fields"]
    for node in flow["nodes"]:
        if node["data"]["step"] == step_key:
            data = dict(node["data"])
            if fields:
                data["config"] = clean(fields, data.get("config"))
            return data
    data = default_node(step_key, 0)["data"]
    data["mode"] = "off"
    return data


def allowed(data: Dict[str, Any], actor: str) -> bool:
    return data["mode"] != "off" and actor in data["actors"]


def within_limits(data: Dict[str, Any], facts: Dict[str, Any]) -> Optional[str]:
    """None if the facts pass the step's limits, else the first limit broken."""
    for limit in data.get("limits") or []:
        actual = facts.get(limit["field"])
        if actual is None:
            continue
        value, op = limit["value"], limit["op"]
        try:
            if isinstance(actual, (int, float)):
                value = float(value)
                ok = {">=": actual >= value, "<=": actual <= value, "=": actual == value, "!=": actual != value}[op]
            else:
                ok = (str(actual) == str(value)) if op == "=" else (str(actual) != str(value))
        except (TypeError, ValueError):
            ok = False
        if not ok:
            label = LIMIT_FIELDS.get(limit["field"], {}).get("label", limit["field"])
            return "{} {} {}".format(label, op, limit["value"])
    return None


def library() -> Dict[str, Any]:
    from . import agents

    steps = [{**s, "agent": agents.agent_for(s["key"]), "agent_label": agents.AGENTS.get(agents.agent_for(s["key"]) or "", {}).get("label")}
             for s in LIBRARY if s["key"] not in PARKED]
    return {"steps": steps, "actors": ACTORS, "modes": MODES, "limit_fields": LIMIT_FIELDS}
