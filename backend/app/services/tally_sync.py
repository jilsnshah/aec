"""Keeping Tally in step with the app, and sending invoices on.

When a sales order is placed, it is queued for Tally as a Sales Order and as
a Sales invoice; when a purchase order is placed, as a Purchase Order. Each is
pushed in the background -- customer, supplier and stock items are created in
Tally first if missing -- and the number Tally gives the invoice is kept. As
soon as Tally has the invoice, a PDF of it goes to the customer on WhatsApp.

A failure (Tally off, a ledger missing) is kept with Tally's message and
retried a few times, a little later each time; it can also be retried by hand.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import begin_write
from ..errors import ConflictError, NotFoundError
from ..models import PurchaseOrder, SalesOrder, TallySync
from . import inbound
from . import integration_settings as settings_service
from . import invoice_pdf, tally, whatsapp
from .common import windowed

logger = logging.getLogger(__name__)

SALES_ORDER = "sales_order"
SALES_INVOICE = "sales_invoice"
PURCHASE_ORDER = "purchase_order"
#: Automatic attempts before a failure waits for a person.
MAX_ATTEMPTS = 5


def _cents(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _local_day(moment: datetime) -> date:
    return moment.astimezone(ZoneInfo(get_settings().business_timezone)).date()


# ---------------------------------------------------------------------------
# Queueing
# ---------------------------------------------------------------------------

def _queue(session: Session, kind: str, entity_id: uuid.UUID, reference: str, notify: bool = False) -> Optional[uuid.UUID]:
    existing = session.execute(
        select(TallySync).where(TallySync.kind == kind, TallySync.entity_id == entity_id)
    ).scalar_one_or_none()
    if existing is not None:
        return None
    row = TallySync(
        kind=kind,
        entity_id=entity_id,
        reference=reference,
        status="pending",
        notify_status="pending" if notify else "none",
    )
    session.add(row)
    session.flush()
    return row.id


def queue_sales_order(session: Session, order: SalesOrder) -> List[uuid.UUID]:
    """Queue a placed sales order for Tally, if Tally is switched on."""
    config = settings_service.get(session, settings_service.TALLY)
    if not config.enabled:
        return []
    begin_write(session)
    send = settings_service.get(session, settings_service.WHATSAPP)
    ids = []
    if config.config["sync_sales_orders"]:
        ids.append(_queue(session, SALES_ORDER, order.id, order.order_number))
    if config.config["create_invoices"]:
        ids.append(_queue(
            session, SALES_INVOICE, order.id, order.order_number,
            notify=bool(send.enabled and send.config.get("send_invoices")),
        ))
    session.commit()
    return [row_id for row_id in ids if row_id]


def queue_purchase_order(session: Session, order: PurchaseOrder) -> List[uuid.UUID]:
    """Queue a placed purchase order for Tally, if Tally is switched on."""
    config = settings_service.get(session, settings_service.TALLY)
    if not config.enabled or not config.config["sync_purchase_orders"]:
        return []
    begin_write(session)
    row_id = _queue(session, PURCHASE_ORDER, order.id, order.po_number)
    session.commit()
    return [row_id] if row_id else []


# ---------------------------------------------------------------------------
# Building what goes to Tally
# ---------------------------------------------------------------------------

def _sales_lines(order: SalesOrder) -> List[tally.Line]:
    return [
        tally.Line(
            item=item.product.name,
            unit=item.product.unit_of_measure,
            quantity=item.quantity_ordered,
            rate=item.unit_price_net,
            amount=_cents(item.unit_price_net * item.quantity_ordered),
        )
        for item in order.items
        if item.quantity_ordered > 0
    ]


def sales_taxes(config: Dict[str, Any], subtotal: Decimal) -> List[Tuple[str, Decimal]]:
    """GST on an invoice, as (ledger, amount) pairs, from the Tally settings."""
    rate = Decimal(str(config.get("gst_rate") or 0))
    if config["tax_mode"] == "none" or rate <= 0:
        return []
    tax = _cents(subtotal * rate / 100)
    if config["tax_mode"] == "igst":
        return [(config["igst_ledger"], tax)]
    half = _cents(tax / 2)
    return [(config["cgst_ledger"], half), (config["sgst_ledger"], tax - half)]


def _push(session: Session, row: TallySync, config: Dict[str, Any], client: tally.TallyClient) -> None:
    if row.kind in (SALES_ORDER, SALES_INVOICE):
        from .orders import get_order

        order = get_order(session, row.entity_id)
        customer = order.customer
        client.ensure_ledger(customer.name, config["customer_group"], customer.phone, customer.email)
        lines = _sales_lines(order)
        for item in order.items:
            client.ensure_stock_item(item.product.name, item.product.unit_of_measure)
        on = _local_day(order.created_at)
        if row.kind == SALES_ORDER:
            result = client.create_voucher(
                config["sales_order_type"], on, customer.name, config["sales_ledger"], lines,
                party_is_debit=True, godown=config["godown"], number=order.order_number,
                reference=order.order_number, narration=order.notes,
                order_number=order.order_number, order_due=on,
            )
            row.tally_number = order.order_number
        else:
            linked = session.execute(
                select(TallySync).where(TallySync.kind == SALES_ORDER, TallySync.entity_id == order.id,
                                        TallySync.status == "synced")
            ).scalar_one_or_none()
            subtotal = sum((line.amount for line in lines), Decimal("0"))
            result = client.create_voucher(
                config["sales_invoice_type"], on, customer.name, config["sales_ledger"], lines,
                party_is_debit=True, godown=config["godown"], reference=order.order_number,
                narration="Against {}".format(order.order_number),
                order_number=order.order_number if linked else None,
                taxes=sales_taxes(config, subtotal),
            )
            # The invoice number is Tally's own. The voucher exists by now, so
            # failing to read the number back must not fail the sync -- a
            # retry would post the invoice twice.
            number = None
            if result.master_id:
                try:
                    number = client.voucher_number(result.master_id)
                except tally.TallyError as exc:
                    logger.warning("Invoice for %s created; reading its number failed: %s", order.order_number, exc)
            row.tally_number = number or order.order_number
        row.tally_master_id = result.master_id
        return

    from .purchasing import get_purchase_order

    order = get_purchase_order(session, row.entity_id)
    client.ensure_ledger(order.supplier.name, config["supplier_group"], order.supplier.phone, order.supplier.email)
    for item in order.items:
        client.ensure_stock_item(item.product.name, item.product.unit_of_measure)
    on = _local_day(order.ordered_at or order.created_at)
    lines = [
        tally.Line(item.product.name, item.product.unit_of_measure, item.quantity_ordered,
                   item.unit_cost, _cents(item.unit_cost * item.quantity_ordered))
        for item in order.items
    ]
    due = order.expected_delivery_date.date() if order.expected_delivery_date else on
    result = client.create_voucher(
        config["purchase_order_type"], on, order.supplier.name, config["purchase_ledger"], lines,
        party_is_debit=False, godown=config["godown"], number=order.po_number,
        reference=order.po_number, narration=order.notes, order_number=order.po_number, order_due=due,
    )
    row.tally_master_id = result.master_id
    row.tally_number = order.po_number


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

def process(sync_id: uuid.UUID) -> None:
    """Push one queued document to Tally, then send its invoice on. Background."""
    session = inbound.session_factory()
    try:
        row = session.execute(
            select(TallySync).where(TallySync.id == sync_id).with_for_update(skip_locked=True)
        ).scalar_one_or_none()
        if row is None:
            return
        tally_row = settings_service.get(session, settings_service.TALLY)
        if row.status != "synced":
            if not tally_row.enabled:
                return
            client = tally.client_for(tally_row.config, settings_service.credentials(tally_row).get("auth_token"))
            try:
                _push(session, row, tally_row.config, client)
            except (tally.TallyError, NotFoundError) as exc:
                session.rollback()
                row = session.get(TallySync, sync_id)
                row.attempts += 1
                row.status = "failed"
                row.error = str(exc)[:2000]
                row.next_attempt_at = (
                    datetime.now(timezone.utc) + timedelta(minutes=2 ** row.attempts)
                    if row.attempts < MAX_ATTEMPTS else None
                )
                session.commit()
                logger.warning("Tally sync of %s %s failed: %s", row.kind, row.reference, exc)
                return
            row.status = "synced"
            row.error = None
            row.attempts += 1
            row.next_attempt_at = None
            row.synced_at = datetime.now(timezone.utc)
            session.commit()
            logger.info("Synced %s %s to Tally as %s", row.kind, row.reference, row.tally_number)
        if row.kind == SALES_INVOICE and row.notify_status == "pending":
            _send_invoice(session, row)
    finally:
        session.close()


def build_invoice(session: Session, row: TallySync) -> invoice_pdf.Invoice:
    from .orders import get_order

    order = get_order(session, row.entity_id)
    config = settings_service.get(session, settings_service.TALLY).config
    lines = [
        invoice_pdf.InvoiceLine(item.product.name, item.quantity_ordered, item.product.unit_of_measure,
                                item.unit_price_net, _cents(item.unit_price_net * item.quantity_ordered))
        for item in order.items if item.quantity_ordered > 0
    ]
    subtotal = sum((line.amount for line in lines), Decimal("0"))
    return invoice_pdf.Invoice(
        number=row.tally_number or order.order_number,
        on=_local_day(row.synced_at or order.created_at),
        order_number=order.order_number,
        seller_name=config["seller_name"],
        seller_address=config["seller_address"],
        seller_gstin=config["seller_gstin"],
        seller_phone=config["seller_phone"],
        customer_name=order.customer.name,
        customer_address=order.customer.address,
        customer_phone=order.customer.phone,
        lines=lines,
        taxes=sales_taxes(config, subtotal),
    )


def _send_invoice(session: Session, row: TallySync) -> None:
    send = settings_service.get(session, settings_service.WHATSAPP)
    token = settings_service.credentials(send).get("access_token")
    if not (send.enabled and send.config.get("send_invoices") and token and send.config.get("invoice_template")):
        row.notify_status = "skipped"
        row.notify_error = "Sending invoices on WhatsApp is not set up."
        session.commit()
        return
    invoice = build_invoice(session, row)
    to = whatsapp.recipient(invoice.customer_phone, send.config.get("country_code") or "")
    row.notify_to = to
    if not to:
        row.notify_status = "skipped"
        row.notify_error = "The customer has no phone number."
        session.commit()
        return
    try:
        message_id = whatsapp.send_invoice(
            send.config, token, to, invoice_pdf.render(invoice),
            "Invoice-{}.pdf".format(invoice.number.replace("/", "-")),
            [invoice.customer_name, invoice.number, "INR " + invoice_pdf.money(invoice.total)],
        )
    except whatsapp.SendError as exc:
        row.notify_status = "failed"
        row.notify_error = str(exc)[:2000]
        session.commit()
        logger.warning("Sending invoice %s on WhatsApp failed: %s", invoice.number, exc)
        return
    row.notify_status = "sent"
    row.notify_message_id = message_id
    row.notify_error = None
    row.notified_at = datetime.now(timezone.utc)
    session.commit()
    logger.info("Sent invoice %s to %s on WhatsApp", invoice.number, to)


def process_due() -> int:
    """One background tick: push whatever is waiting or due for a retry."""
    session = inbound.session_factory()
    try:
        if not settings_service.get(session, settings_service.TALLY).enabled:
            return 0
        now = datetime.now(timezone.utc)
        ids = session.execute(
            select(TallySync.id)
            .where(or_(
                TallySync.status == "pending",
                (TallySync.status == "failed") & (TallySync.next_attempt_at <= now),
            ))
            # Orders before their invoices, oldest first.
            .order_by(TallySync.created_at, TallySync.kind.desc())
            .limit(50)
        ).scalars().all()
    finally:
        session.close()
    for sync_id in ids:
        process(sync_id)
    return len(ids)


def retry(session: Session, sync_id: uuid.UUID) -> TallySync:
    """Try a failed sync again, or resend an invoice that failed to send."""
    row = session.get(TallySync, sync_id)
    if row is None:
        raise NotFoundError("Sync {} does not exist.".format(sync_id))
    begin_write(session)
    if row.status == "failed":
        row.status = "pending"
        row.attempts = 0
        row.next_attempt_at = None
    elif row.kind == SALES_INVOICE and row.notify_status in ("failed", "skipped"):
        row.notify_status = "pending"
        row.notify_error = None
    else:
        session.rollback()
        raise ConflictError("Only a failed sync, or an invoice that was not sent, can be retried.")
    session.commit()
    return row


def invoice_for_order(session: Session, order_id: uuid.UUID) -> Optional[TallySync]:
    return session.execute(
        select(TallySync).where(TallySync.kind == SALES_INVOICE, TallySync.entity_id == order_id,
                                TallySync.status == "synced")
    ).scalar_one_or_none()


def for_entity(session: Session, entity_id: uuid.UUID) -> List[TallySync]:
    return list(session.execute(
        select(TallySync).where(TallySync.entity_id == entity_id).order_by(TallySync.created_at, TallySync.kind)
    ).scalars().all())


def _filter(status: Optional[str]):
    stmt = select(TallySync)
    return stmt.where(TallySync.status == status) if status else stmt


def count(session: Session, status: Optional[str] = None) -> int:
    return session.execute(select(func.count()).select_from(_filter(status).subquery())).scalar_one()


def list_recent(session: Session, status: Optional[str] = None, limit: Optional[int] = None, offset: int = 0) -> List[TallySync]:
    stmt = _filter(status).order_by(TallySync.created_at.desc(), TallySync.kind)
    return list(session.execute(windowed(stmt, limit, offset)).scalars().all())


def view(row: TallySync) -> Dict[str, Any]:
    return {
        "id": row.id,
        "kind": row.kind,
        "entity_id": row.entity_id,
        "reference": row.reference,
        "status": row.status,
        "attempts": row.attempts,
        "next_attempt_at": row.next_attempt_at,
        "tally_number": row.tally_number,
        "error": row.error,
        "synced_at": row.synced_at,
        "notify_status": row.notify_status,
        "notify_to": row.notify_to,
        "notify_error": row.notify_error,
        "notified_at": row.notified_at,
        "created_at": row.created_at,
    }


def test_connection(session: Session) -> Dict[str, Any]:
    row = settings_service.get(session, settings_service.TALLY)
    if not row.config["server_url"]:
        raise tally.TallyError("Add the Tally server address first.")
    client = tally.client_for(row.config, settings_service.credentials(row).get("auth_token"))
    companies = client.companies()
    return {"companies": companies, "company_found": row.config["company"] in companies}
