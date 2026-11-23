"""What each automation step can be set to.

Every configurable step publishes a list of fields; the flow editor draws a
form from it and the saved values travel with the step as ``config``. Field
types: number, text, textarea, select, multiselect, toggle, time, days, and
group (a switchable set of fields -- one trigger rule). ``source`` on a
multiselect names a list the editor loads (categories, suppliers, customer
groups, segments, warehouses).

The defaults follow common practice for a building-materials trader: check
stock every few hours in working time, reorder below minimum plus lead-time
demand, ask three suppliers and wait half a day, contact a customer at most
once a fortnight, ask for feedback a day after delivery.
"""
from __future__ import annotations

from typing import Any, Dict, List

DAYS = [["mon", "Mon"], ["tue", "Tue"], ["wed", "Wed"], ["thu", "Thu"], ["fri", "Fri"], ["sat", "Sat"], ["sun", "Sun"]]
WORK_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat"]


def schedule(every_default: str = "6h", start: str = "09:00", end: str = "19:00") -> List[Dict[str, Any]]:
    return [
        {"key": "every", "label": "Check", "type": "select", "default": every_default,
         "options": [["1h", "Every hour"], ["2h", "Every 2 hours"], ["4h", "Every 4 hours"], ["6h", "Every 6 hours"], ["12h", "Twice a day"],
                     ["1d", "Once a day"], ["7d", "Once a week"]]},
        {"key": "days", "label": "On", "type": "days", "default": WORK_DAYS, "options": DAYS},
        {"key": "window_start", "label": "From", "type": "time", "default": start},
        {"key": "window_end", "label": "Until", "type": "time", "default": end, "help": "Nothing is sent outside these hours."},
    ]


CONFIG: Dict[str, List[Dict[str, Any]]] = {
    # ------------------------------------------------------------------ purchase
    "purchase.need_detected": [
        {"key": "schedule", "label": "When to look", "type": "section", "fields": schedule("4h", "08:00", "20:00")},
        {"key": "rules", "label": "What counts as a need", "type": "section", "fields": [
            {"key": "shortage", "label": "Customers are waiting (orders short of stock)", "type": "group", "default": True, "fields": [
                {"key": "min_quantity", "label": "Ignore below", "type": "number", "default": 0, "unit": "base units"}]},
            {"key": "reorder_point", "label": "Stock below the reorder point", "type": "group", "default": True,
             "help": "Reorder point = minimum stock + what sells during the supplier's lead time.", "fields": [
                {"key": "safety_days", "label": "Extra safety days", "type": "number", "default": 2, "unit": "days"},
                {"key": "lookback_days", "label": "Sales rate from the last", "type": "number", "default": 30, "unit": "days"}]},
            {"key": "days_of_cover", "label": "Stock lasts fewer than N days", "type": "group", "default": False, "fields": [
                {"key": "days", "label": "Days of cover", "type": "number", "default": 10, "unit": "days"},
                {"key": "lookback_days", "label": "Sales rate from the last", "type": "number", "default": 30, "unit": "days"}]},
            {"key": "fixed_review", "label": "Fixed weekly review (top everything up)", "type": "group", "default": False, "fields": [
                {"key": "day", "label": "Review on", "type": "select", "default": "mon", "options": DAYS}]},
        ]},
        {"key": "scope", "label": "Which products", "type": "section", "fields": [
            {"key": "categories", "label": "Only these categories", "type": "multiselect", "source": "categories", "default": [], "help": "Empty means all."},
            {"key": "suppliers", "label": "Only from these suppliers", "type": "multiselect", "source": "suppliers", "default": []},
            {"key": "skip_covered", "label": "Skip what open purchase orders already cover", "type": "toggle", "default": True},
            {"key": "cooldown_hours", "label": "Do not raise the same product again within", "type": "number", "default": 24, "unit": "hours"},
        ]},
        {"key": "then", "label": "Then", "type": "select", "default": "ask_suppliers",
         "options": [["ask_suppliers", "Start a purchase enquiry (next steps)"], ["task", "Only make a task for the buyer"]]},
    ],
    "purchase.choose_supplier": [
        {"key": "quantity", "label": "How much to buy", "type": "section", "fields": [
            {"key": "method", "label": "Quantity", "type": "select", "default": "up_to_cover",
             "options": [["shortage_only", "Only what customers are short"], ["up_to_reorder", "Back up to the reorder point"],
                         ["up_to_cover", "Enough for N days of sales"], ["up_to_max", "Up to a maximum (2× minimum)"]]},
            {"key": "cover_days", "label": "N days", "type": "number", "default": 15, "unit": "days"},
            {"key": "round_to_purchase_unit", "label": "Round up to whole purchase units (tonnes, bundles…)", "type": "toggle", "default": True},
            {"key": "min_value", "label": "Skip a request worth less than", "type": "number", "default": 0, "unit": "₹"},
        ]},
        {"key": "suppliers", "label": "Which suppliers", "type": "section", "fields": [
            {"key": "who", "label": "Ask", "type": "select", "default": "best_three",
             "options": [["preferred", "Only the product's usual supplier"], ["best_three", "Usual supplier + best past suppliers"],
                         ["all_category", "Every supplier who has sold this category"]]},
            {"key": "how_many", "label": "Ask at most", "type": "number", "default": 3, "unit": "suppliers"},
            {"key": "use_contract", "label": "If a rate contract is running, buy on it without asking", "type": "toggle", "default": True},
        ]},
    ],
    "purchase.ask_supplier": [
        {"key": "how", "label": "Ask by", "type": "select", "default": "text",
         "options": [["text", "WhatsApp or email (text AI)"], ["call", "Phone call (purchasing voice AI)"],
                     ["text_then_call", "WhatsApp first, call if no reply"]]},
        {"key": "call_after_hours", "label": "Call if no reply after", "type": "number", "default": 2, "unit": "hours"},
        {"key": "call_tries", "label": "Call attempts", "type": "number", "default": 2, "unit": "tries"},
        {"key": "negotiate", "label": "Ask for the last price paid when the quote is higher", "type": "toggle", "default": True},
        {"key": "wait_hours", "label": "Wait for replies", "type": "number", "default": 6, "unit": "hours"},
        {"key": "remind_after_hours", "label": "Remind those who have not replied after", "type": "number", "default": 3, "unit": "hours"},
        {"key": "window_start", "label": "Send from", "type": "time", "default": "09:00"},
        {"key": "window_end", "label": "Send until", "type": "time", "default": "19:00"},
    ],
    "purchase.compare_quotes": [
        {"key": "rule", "label": "Pick", "type": "select", "default": "weighted",
         "options": [["lowest_price", "Lowest price"], ["fastest", "Fastest delivery"], ["weighted", "Best score (price, delivery, supplier record)"]]},
        {"key": "weight_price", "label": "Weight of price", "type": "number", "default": 60, "unit": "%"},
        {"key": "weight_delivery", "label": "Weight of delivery time", "type": "number", "default": 20, "unit": "%"},
        {"key": "weight_score", "label": "Weight of supplier record", "type": "number", "default": 20, "unit": "%"},
        {"key": "max_over_last_percent", "label": "Reject offers above the last price paid by more than", "type": "number", "default": 8, "unit": "%"},
        {"key": "decide_when", "label": "Decide", "type": "select", "default": "all_or_wait",
         "options": [["all_or_wait", "When all replied, or the wait is over"], ["first_good", "On the first offer within limits"]]},
    ],
    "purchase.send_po": [
        {"key": "send_on", "label": "Send", "type": "select", "default": "placed", "options": [["placed", "When the PO is placed"], ["manual", "Only when asked"]]},
        {"key": "message", "label": "Message", "type": "textarea", "default": "Please find our purchase order {po} attached. Kindly confirm the delivery date."},
    ],
    "purchase.chase_delivery": [
        {"key": "before_days", "label": "Confirm with the supplier before the due date", "type": "number", "default": 1, "unit": "days"},
        {"key": "on_due_day", "label": "Ask on the due day if nothing arrived", "type": "toggle", "default": True},
        {"key": "overdue_every_days", "label": "When late, ask again every", "type": "number", "default": 1, "unit": "days"},
        {"key": "max_reminders", "label": "At most", "type": "number", "default": 3, "unit": "reminders"},
        {"key": "escalate", "label": "Then make a task for the buyer", "type": "toggle", "default": True},
        {"key": "update_date", "label": "Update the expected date from the supplier's reply", "type": "toggle", "default": True},
        {"key": "window_start", "label": "Send from", "type": "time", "default": "10:00"},
        {"key": "window_end", "label": "Send until", "type": "time", "default": "18:00"},
    ],
    # --------------------------------------------------------------------- sales
    "sales.trigger_outreach": [
        {"key": "schedule", "label": "When", "type": "section", "fields": schedule("1d", "10:30", "18:30")},
        {"key": "rules", "label": "Who to contact", "type": "section", "fields": [
            {"key": "dormant", "label": "Customers who stopped ordering", "type": "group", "default": True, "fields": [
                {"key": "days", "label": "No order for", "type": "number", "default": 60, "unit": "days"},
                {"key": "min_orders", "label": "Who ordered at least", "type": "number", "default": 2, "unit": "times before"}]},
            {"key": "reorder_due", "label": "Due to reorder (past their usual gap)", "type": "group", "default": True, "fields": [
                {"key": "grace_percent", "label": "Gap passed by", "type": "number", "default": 25, "unit": "%"}]},
            {"key": "quote_followup", "label": "Quotes not turned into orders", "type": "group", "default": True, "fields": [
                {"key": "days", "label": "Quote older than", "type": "number", "default": 2, "unit": "days"}]},
            {"key": "back_in_stock", "label": "Products they buy are back in stock", "type": "group", "default": False, "fields": [
                {"key": "days", "label": "Arrived in the last", "type": "number", "default": 2, "unit": "days"}]},
            {"key": "group_members", "label": "Members of chosen customer groups", "type": "group", "default": False, "fields": [
                {"key": "groups", "label": "Groups", "type": "multiselect", "source": "customer_groups", "default": []}]},
            {"key": "clear_stock", "label": "Offer slow-moving stock", "type": "group", "default": False, "fields": [
                {"key": "aged_days", "label": "Stock older than", "type": "number", "default": 90, "unit": "days"}]},
        ]},
        {"key": "audience", "label": "Never contact", "type": "section", "fields": [
            {"key": "skip_overdue_days", "label": "Customers with bills overdue more than", "type": "number", "default": 30, "unit": "days"},
            {"key": "skip_segments", "label": "These segments", "type": "multiselect", "source": "segments", "default": []},
            {"key": "skip_groups", "label": "These groups", "type": "multiselect", "source": "customer_groups", "default": []},
            {"key": "min_spend", "label": "Who spent less than (last 12 months)", "type": "number", "default": 0, "unit": "₹"},
        ]},
        {"key": "caps", "label": "Limits", "type": "section", "fields": [
            {"key": "once_every_days", "label": "Contact a customer at most once every", "type": "number", "default": 14, "unit": "days"},
            {"key": "max_per_day", "label": "At most per day", "type": "number", "default": 30, "unit": "customers"},
        ]},
        {"key": "offer", "label": "What to say", "type": "section", "fields": [
            {"key": "pitch", "label": "Products to mention", "type": "select", "default": "their_products",
             "options": [["their_products", "What they usually buy (in stock)"], ["in_stock", "Best sellers in stock"], ["slow", "Slow-moving stock"]]},
            {"key": "with_prices", "label": "Include their prices", "type": "toggle", "default": True},
            {"key": "extra_discount", "label": "Extra discount TAI may offer", "type": "number", "default": 0, "unit": "%"},
        ]},
    ],
    "sales.payment_reminders": [
        {"key": "how", "label": "Remind by", "type": "select", "default": "text",
         "options": [["text", "WhatsApp (text AI)"], ["call", "Phone call (collections voice AI)"], ["text_then_call", "WhatsApp first, then call"]]},
        {"key": "call_from_level", "label": "Call from", "type": "select", "default": "2",
         "options": [["1", "The first reminder"], ["2", "The second (firm) reminder"], ["3", "Only the final notice"]]},
        {"key": "every_days", "label": "Remind the same customer at most every", "type": "number", "default": 7, "unit": "days"},
        {"key": "min_overdue", "label": "Only when at least this much is overdue", "type": "number", "default": 1000, "unit": "₹"},
        {"key": "per_run", "label": "At most this many reminders per run", "type": "number", "default": 20, "unit": "customers"},
        {"key": "window_start", "label": "Send from", "type": "time", "default": "10:00"},
        {"key": "window_end", "label": "Send until", "type": "time", "default": "18:00"},
    ],
    "sales.after_sales": [
        {"key": "how", "label": "Ask by", "type": "select", "default": "text",
         "options": [["text", "WhatsApp (text AI)"], ["call", "Phone call (customer care voice AI)"]]},
        {"key": "delay_hours", "label": "Ask after delivery", "type": "number", "default": 24, "unit": "hours"},
        {"key": "who", "label": "Ask", "type": "select", "default": "all",
         "options": [["all", "Every delivery"], ["first_orders", "Only first orders of a customer"], ["big", "Only big orders"]]},
        {"key": "min_value", "label": "Big order means over", "type": "number", "default": 25000, "unit": "₹"},
        {"key": "skip_days", "label": "Skip if we asked this customer in the last", "type": "number", "default": 15, "unit": "days"},
        {"key": "ask_rating", "label": "Ask for a rating 1–5", "type": "toggle", "default": True},
        {"key": "complaint_words", "label": "Words that mean a complaint", "type": "text",
         "default": "broken, damaged, wet, short, less, late, wrong, missing, kharab, tuta, kam, problem"},
        {"key": "low_rating", "label": "A rating at or below this is a complaint", "type": "number", "default": 2},
        {"key": "complaint_priority", "label": "Complaint task priority", "type": "select", "default": "high", "options": [["high", "High"], ["normal", "Normal"]]},
        {"key": "window_start", "label": "Send from", "type": "time", "default": "10:00"},
        {"key": "window_end", "label": "Send until", "type": "time", "default": "19:00"},
    ],
}


def defaults(fields: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The default values of a field list, nested as they are stored."""
    out: Dict[str, Any] = {}
    for field in fields:
        if field["type"] == "section":
            out[field["key"]] = defaults(field["fields"])
        elif field["type"] == "group":
            out[field["key"]] = {"enabled": bool(field.get("default", False)), **defaults(field.get("fields", []))}
        else:
            out[field["key"]] = field.get("default")
    return out


def clean(fields: List[Dict[str, Any]], values: Any) -> Dict[str, Any]:
    """Saved values merged over the defaults, with the right types."""
    values = values if isinstance(values, dict) else {}
    out: Dict[str, Any] = {}
    for field in fields:
        key, kind = field["key"], field["type"]
        value = values.get(key)
        if kind == "section":
            out[key] = clean(field["fields"], value)
        elif kind == "group":
            sub = value if isinstance(value, dict) else {}
            out[key] = {"enabled": bool(sub.get("enabled", field.get("default", False))), **clean(field.get("fields", []), sub)}
        elif value is None:
            out[key] = field.get("default")
        elif kind == "number":
            try:
                number = float(value)
            except (TypeError, ValueError):
                number = float(field.get("default") or 0)
            out[key] = max(number, 0)
        elif kind == "toggle":
            out[key] = bool(value)
        elif kind in ("multiselect", "days"):
            out[key] = [str(v) for v in value] if isinstance(value, list) else []
        elif kind == "select":
            allowed = [o[0] for o in field.get("options", [])]
            out[key] = value if value in allowed else field.get("default")
        else:
            out[key] = str(value)[:4000]
    return out
