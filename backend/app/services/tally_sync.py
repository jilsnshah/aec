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
#: An invoice for one delivery (when Tally is set to invoice on delivery).
DELIVERY_INVOICE = "delivery_invoice"
PURCHASE_ORDER = "purchase_order"
#: A received transfer between warehouses, as a Stock Journal.
STOCK_TRANSFER = "stock_transfer"
#: Goods sent back to a supplier, as a Debit Note.
PURCHASE_RETURN = "purchase_return"
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
    if config.config["create_invoices"] and config.config.get("invoice_on", "order") == "order":
        ids.append(_queue(
            session, SALES_INVOICE, order.id, order.order_number,
            notify=bool(send.enabled and send.config.get("send_invoices")),
        ))
    session.commit()
    return [row_id for row_id in ids if row_id]


def queue_transfer(session: Session, transfer_id: uuid.UUID) -> List[uuid.UUID]:
    """Queue a received transfer for Tally (Stock Journal), if Tally is on."""
    from ..models import StockTransfer

    config = settings_service.get(session, settings_service.TALLY)
    if not config.enabled or not config.config.get("sync_transfers", True):
        return []
    begin_write(session)
    transfer = session.get(StockTransfer, transfer_id)
    if transfer is None or transfer.status != "received":
        return []
    row_id = _queue(session, STOCK_TRANSFER, transfer.id, transfer.number)
    session.commit()
    return [row_id] if row_id else []


def queue_purchase_return(session: Session, return_id: uuid.UUID) -> List[uuid.UUID]:
    """Queue a purchase return for Tally (Debit Note), if Tally is on."""
    from ..models import PurchaseReturn

    config = settings_service.get(session, settings_service.TALLY)
    if not config.enabled or not config.config.get("sync_purchase_orders", True):
        return []
    begin_write(session)
    record = session.get(PurchaseReturn, return_id)
    if record is None:
        return []
    row_id = _queue(session, PURCHASE_RETURN, record.id, record.number)
    session.commit()
    return [row_id] if row_id else []


def godown_for(config: Dict[str, Any], warehouse) -> str:
    """The Tally godown a warehouse posts to: its own Tally name, else the
    Settings godown for the default warehouse, else its name."""
    if warehouse is None:
        return config["godown"]
    if warehouse.tally_godown:
        return warehouse.tally_godown
    return config["godown"] if warehouse.is_default else warehouse.name


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

def queue_delivery(session: Session, delivery_id: uuid.UUID) -> List[uuid.UUID]:
    """Queue the invoice for one delivery, when Tally invoices on delivery."""
    from ..models import CustomerDelivery

    config = settings_service.get(session, settings_service.TALLY)
    if not (config.enabled and config.config["create_invoices"] and config.config.get("invoice_on") == "delivery"):
        return []
    begin_write(session)
    delivery = session.get(CustomerDelivery, delivery_id)
    if delivery is None:
        return []
    send = settings_service.get(session, settings_service.WHATSAPP)
    row_id = _queue(session, DELIVERY_INVOICE, delivery.id, delivery.delivery_number,
                    notify=bool(send.enabled and send.config.get("send_invoices")))
    session.commit()
    return [row_id] if row_id else []


def _delivery(session: Session, delivery_id: uuid.UUID):
    from sqlalchemy.orm import joinedload

    from ..models import CustomerDelivery, CustomerDeliveryItem, SalesOrderItem

    delivery = session.execute(
        select(CustomerDelivery).where(CustomerDelivery.id == delivery_id)
        .options(joinedload(CustomerDelivery.items).joinedload(CustomerDeliveryItem.order_item).joinedload(SalesOrderItem.product),
                 joinedload(CustomerDelivery.sales_order), joinedload(CustomerDelivery.customer))
    ).unique().scalar_one_or_none()
    if delivery is None:
        raise NotFoundError("Delivery not found.")
    return delivery


def _delivery_lines(delivery) -> List[tally.Line]:
    return [
        tally.Line(item=line.order_item.product.name, unit=line.order_item.product.unit_of_measure, quantity=line.quantity,
                   rate=line.order_item.unit_price_net, amount=_cents(line.order_item.unit_price_net * line.quantity),
                   hsn=line.order_item.product.hsn_code, gst_rate=line.order_item.product.gst_rate)
        for line in delivery.items if line.quantity > 0
    ]


def _sales_lines(order: SalesOrder) -> List[tally.Line]:
    return [
        tally.Line(
            item=item.product.name,
            unit=item.product.unit_of_measure,
            quantity=item.quantity_ordered,
            rate=item.unit_price_net,
            amount=_cents(item.unit_price_net * item.quantity_ordered),
            hsn=item.product.hsn_code,
            gst_rate=item.product.gst_rate,
        )
        for item in order.items
        if item.quantity_ordered > 0
    ]


def _line_rate(config: Dict[str, Any], rate: Optional[Decimal]) -> Decimal:
    """A line's GST %: the product's own rate, else the rate in Settings."""
    if config["tax_mode"] == "none":
        return Decimal("0")
    return Decimal(str(rate)) if rate is not None else Decimal(str(config.get("gst_rate") or 0))


def tax_breakup(config: Dict[str, Any], lines) -> List[Dict[str, Any]]:
    """GST on an invoice, rate by rate: [{rate, taxable, parts: [(ledger, label, amount)]}].
    Each line is taxed at its product's rate, so cement at 28% and steel at
    18% on one invoice come out right."""
    groups: Dict[Decimal, Decimal] = {}
    for line in lines:
        rate = _line_rate(config, getattr(line, "gst_rate", None))
        if rate > 0:
            groups[rate] = groups.get(rate, Decimal("0")) + Decimal(line.amount)
    out = []
    for rate, taxable in sorted(groups.items()):
        tax = _cents(taxable * rate / 100)
        if config["tax_mode"] == "igst":
            parts = [(config["igst_ledger"], "IGST @ {}%".format(format(rate.normalize(), "f")), tax)]
        else:
            half = _cents(tax / 2)
            label = format((rate / 2).normalize(), "f")
            parts = [(config["cgst_ledger"], "CGST @ {}%".format(label), half), (config["sgst_ledger"], "SGST @ {}%".format(label), tax - half)]
        out.append({"rate": rate, "taxable": taxable, "parts": parts})
    return out


def line_taxes(config: Dict[str, Any], lines) -> List[Tuple[str, Decimal]]:
    """Tax ledger amounts for Tally, summed over the rates."""
    ledgers: Dict[str, Decimal] = {}
    for group in tax_breakup(config, lines):
        for ledger, _, amount in group["parts"]:
            ledgers[ledger] = ledgers.get(ledger, Decimal("0")) + amount
    return list(ledgers.items())


def display_taxes(config: Dict[str, Any], lines) -> List[Tuple[str, Decimal]]:
    """Tax rows for the invoice PDF, one per rate and head."""
    return [(label, amount) for group in tax_breakup(config, lines) for _, label, amount in group["parts"]]


def _ensure_item(session: Session, client: tally.TallyClient, product) -> None:
    """The product's stock item in Tally, with its HSN and GST rate; corrected
    in Tally when either changed here."""
    rate = Decimal(str(product.gst_rate)) if product.gst_rate is not None else None
    sig = "{}|{}".format(product.hsn_code or "", format(rate.normalize(), "f") if rate is not None else "")
    has_gst = bool(product.hsn_code or rate is not None)
    client.ensure_stock_item(product.name, product.unit_of_measure, product.hsn_code, rate,
                             update_gst=has_gst and product.tally_gst_sig != sig)
    if has_gst:
        product.tally_gst_sig = sig


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


def ledger_name(party) -> str:
    """The Tally ledger a customer or supplier posts to. Fixed the first time
    it is used, so renaming the party here never creates a second ledger."""
    if not party.tally_ledger_name:
        party.tally_ledger_name = party.name
    return party.tally_ledger_name


def _push(session: Session, row: TallySync, config: Dict[str, Any], client: tally.TallyClient) -> None:
    if row.kind == PURCHASE_RETURN:
        from sqlalchemy.orm import joinedload

        from ..models import PurchaseReturn, PurchaseReturnItem, Warehouse

        record = session.execute(select(PurchaseReturn).where(PurchaseReturn.id == row.entity_id).options(
            joinedload(PurchaseReturn.items).joinedload(PurchaseReturnItem.product), joinedload(PurchaseReturn.supplier))).unique().scalar_one()
        ledger = ledger_name(record.supplier)
        client.ensure_ledger(ledger, config["supplier_group"], record.supplier.phone, record.supplier.email)
        for item in record.items:
            _ensure_item(session, client, item.product)
        lines = [tally.Line(i.product.name, i.product.unit_of_measure, i.quantity, i.unit_cost, _cents(i.amount)) for i in record.items]
        house = session.get(Warehouse, record.warehouse_id) if record.warehouse_id else None
        result = client.create_voucher(
            config.get("debit_note_type") or "Debit Note", _local_day(record.created_at), ledger, config["purchase_ledger"], lines,
            party_is_debit=True, godown=godown_for(config, house), number=record.number, reference=record.number,
            narration="Goods returned: {}{}".format(record.reason.replace("_", " "), " - " + record.note if record.note else ""),
        )
        row.tally_master_id = result.master_id
        row.tally_number = record.number
        return
    if row.kind == STOCK_TRANSFER:
        from . import warehouses as warehouse_service
        from ..models import StockTransfer

        transfer = warehouse_service._load(session, row.entity_id)
        source, target = godown_for(config, transfer.from_warehouse), godown_for(config, transfer.to_warehouse)
        for godown in {source, target}:
            client.ensure_godown(godown)
        sent, received = [], []
        for item in transfer.items:
            product = item.product
            _ensure_item(session, client, product)
            cost = (item.goods_value / item.quantity) if item.quantity else Decimal("0")
            sent.append(tally.Line(product.name, product.unit_of_measure, item.quantity, _cents(cost), _cents(item.goods_value)))
            if item.quantity_received > 0:
                landed = cost * item.quantity_received + item.extra_cost
                received.append(tally.Line(product.name, product.unit_of_measure, item.quantity_received,
                                           _cents(landed / item.quantity_received), _cents(landed)))
        narration = "Transfer {} from {} to {}".format(transfer.number, transfer.from_warehouse.name, transfer.to_warehouse.name)
        if transfer.extra_cost:
            narration += "; freight and handling Rs {:,.2f} added to cost".format(float(transfer.extra_cost))
        if transfer.loss_value:
            narration += "; lost in transit Rs {:,.2f}".format(float(transfer.loss_value))
        result = client.create_stock_journal(_local_day(transfer.received_at or transfer.created_at), transfer.number, narration,
                                             source, target, sent, received)
        row.tally_master_id = result.master_id
        row.tally_number = transfer.number
        return
    if row.kind == DELIVERY_INVOICE:
        delivery = _delivery(session, row.entity_id)
        order = delivery.sales_order
        ledger = ledger_name(delivery.customer)
        client.ensure_ledger(ledger, config["customer_group"], delivery.customer.phone, delivery.customer.email)
        lines = _delivery_lines(delivery)
        for line in delivery.items:
            _ensure_item(session, client, line.order_item.product)
        linked = session.execute(
            select(TallySync).where(TallySync.kind == SALES_ORDER, TallySync.entity_id == order.id, TallySync.status == "synced")
        ).scalar_one_or_none()
        subtotal = sum((line.amount for line in lines), Decimal("0"))
        result = client.create_voucher(
            config["sales_invoice_type"], _local_day(delivery.created_at), ledger, config["sales_ledger"], lines,
            party_is_debit=True, godown=godown_for(config, delivery.warehouse), reference=delivery.delivery_number,
            narration="Delivery {} against {}".format(delivery.delivery_number, order.order_number),
            order_number=order.order_number if linked else None, taxes=line_taxes(config, lines),
        )
        number = None
        if result.master_id:
            try:
                number = client.voucher_number(result.master_id)
            except tally.TallyError:
                number = None
        row.tally_number = number or delivery.delivery_number
        return
    if row.kind in (SALES_ORDER, SALES_INVOICE):
        from .orders import get_order

        order = get_order(session, row.entity_id)
        customer = order.customer
        ledger = ledger_name(customer)
        client.ensure_ledger(ledger, config["customer_group"], customer.phone, customer.email)
        lines = _sales_lines(order)
        for item in order.items:
            _ensure_item(session, client, item.product)
        on = _local_day(order.created_at)
        if row.kind == SALES_ORDER:
            result = client.create_voucher(
                config["sales_order_type"], on, ledger, config["sales_ledger"], lines,
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
                config["sales_invoice_type"], on, ledger, config["sales_ledger"], lines,
                party_is_debit=True, godown=config["godown"], reference=order.order_number,
                narration="Against {}".format(order.order_number),
                order_number=order.order_number if linked else None,
                taxes=line_taxes(config, lines),
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
    supplier_ledger = ledger_name(order.supplier)
    client.ensure_ledger(supplier_ledger, config["supplier_group"], order.supplier.phone, order.supplier.email)
    for item in order.items:
        _ensure_item(session, client, item.product)
    on = _local_day(order.ordered_at or order.created_at)
    lines = [
        tally.Line(item.product.name, item.product.unit_of_measure, item.quantity_ordered,
                   item.unit_cost, _cents(item.unit_cost * item.quantity_ordered))
        for item in order.items
    ]
    due = order.expected_delivery_date.date() if order.expected_delivery_date else on
    result = client.create_voucher(
        config["purchase_order_type"], on, supplier_ledger, config["purchase_ledger"], lines,
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
            if row.kind in STATUTORY_KINDS and row.tally_master_id:
                try:
                    read_statutory(session, row, client)
                except tally.TallyError:
                    session.rollback()
        if row.kind in (SALES_INVOICE, DELIVERY_INVOICE) and row.notify_status == "pending":
            _send_invoice(session, row)
    finally:
        session.close()


def _statutory_fields(row: TallySync) -> Dict[str, Any]:
    return {"irn": row.irn, "irn_ack_no": row.irn_ack_no, "irn_ack_date": row.irn_ack_date, "irn_qr": row.irn_qr,
            "eway_bill_no": row.eway_bill_no, "eway_bill_date": row.eway_bill_date}


#: Documents whose e-invoice / e-way bill Tally may generate.
STATUTORY_KINDS = (SALES_INVOICE, DELIVERY_INVOICE, STOCK_TRANSFER, PURCHASE_RETURN)


def read_statutory(session: Session, row: TallySync, client: Optional[tally.TallyClient] = None) -> bool:
    """Read the e-invoice and e-way bill Tally holds for a synced voucher and
    keep them (and the e-way bill on the delivery, transfer or return).
    True when something new arrived."""
    if not row.tally_master_id or row.kind not in STATUTORY_KINDS:
        return False
    if client is None:
        tally_row = settings_service.get(session, settings_service.TALLY)
        client = tally.client_for(tally_row.config, settings_service.credentials(tally_row).get("auth_token"))
    found = client.statutory(row.tally_master_id)
    row.statutory_checked_at = datetime.now(timezone.utc)
    changed = False
    for attr, value in (("irn", found.irn), ("irn_ack_no", found.ack_no), ("irn_ack_date", found.ack_date), ("irn_qr", found.qr),
                        ("eway_bill_no", found.eway_bill_no), ("eway_bill_date", found.eway_bill_date)):
        if value and getattr(row, attr) != value:
            setattr(row, attr, value[:4000] if attr == "irn_qr" else value[:80])
            changed = True
    if found.eway_bill_no:
        from ..models import CustomerDelivery, PurchaseReturn, StockTransfer

        model = {DELIVERY_INVOICE: CustomerDelivery, STOCK_TRANSFER: StockTransfer, PURCHASE_RETURN: PurchaseReturn}.get(row.kind)
        document = session.get(model, row.entity_id) if model else None
        if document is not None and not document.eway_bill_number:
            document.eway_bill_number = found.eway_bill_no[:20]
            if found.eway_valid_upto:
                try:
                    document.eway_bill_valid_until = datetime.fromisoformat(found.eway_valid_upto)
                except ValueError:
                    pass
    session.commit()
    return changed


def refresh_statutory(session: Optional[Session] = None, limit: int = 40) -> int:
    """Background: look in Tally for e-invoices and e-way bills generated since
    our vouchers went in (within a week; each voucher at most every 15 min)."""
    own = session is None
    session = session or inbound.session_factory()
    try:
        tally_row = settings_service.get(session, settings_service.TALLY)
        if not tally_row.enabled:
            return 0
        now = datetime.now(timezone.utc)
        rows = session.execute(
            select(TallySync).where(
                TallySync.kind.in_(STATUTORY_KINDS), TallySync.status == "synced", TallySync.tally_master_id.is_not(None),
                TallySync.synced_at >= now - timedelta(days=7),
                or_(TallySync.irn.is_(None), TallySync.eway_bill_no.is_(None)),
                or_(TallySync.statutory_checked_at.is_(None), TallySync.statutory_checked_at < now - timedelta(minutes=15)),
            ).order_by(TallySync.synced_at.desc()).limit(limit)
        ).scalars().all()
        if not rows:
            return 0
        client = tally.client_for(tally_row.config, settings_service.credentials(tally_row).get("auth_token"))
        found = 0
        for row in rows:
            try:
                found += 1 if read_statutory(session, row, client) else 0
            except tally.TallyError as exc:
                session.rollback()
                logger.info("Could not read e-invoice details for %s: %s", row.reference, exc)
                break
        return found
    finally:
        if own:
            session.close()


def build_invoice(session: Session, row: TallySync) -> invoice_pdf.Invoice:
    from .orders import get_order

    if row.kind == DELIVERY_INVOICE:
        delivery = _delivery(session, row.entity_id)
        config = settings_service.get(session, settings_service.TALLY).config
        lines = [invoice_pdf.line_in_unit(line.order_item.product.name, line.quantity, line.order_item.product.unit_of_measure,
                                          line.order_item.unit_price_net, _cents(line.order_item.unit_price_net * line.quantity),
                                          line.order_item.unit, line.order_item.unit_factor, line.order_item.product.hsn_code,
                                          line.order_item.product.gst_rate)
                 for line in delivery.items if line.quantity > 0]
        subtotal = sum((line.amount for line in lines), Decimal("0"))
        return invoice_pdf.Invoice(
            number=row.tally_number or delivery.delivery_number, on=_local_day(row.synced_at or delivery.created_at),
            order_number="{} (delivery {})".format(delivery.sales_order.order_number, delivery.delivery_number),
            seller_name=config["seller_name"], seller_address=config["seller_address"], seller_gstin=config["seller_gstin"],
            seller_phone=config["seller_phone"], customer_name=delivery.customer.name, customer_address=delivery.customer.address,
            customer_phone=delivery.customer.phone, lines=lines, taxes=display_taxes(config, lines),
            customer_gstin=delivery.customer.gstin, **_statutory_fields(row),
        )

    order = get_order(session, row.entity_id)
    config = settings_service.get(session, settings_service.TALLY).config
    lines = [
        invoice_pdf.line_in_unit(item.product.name, item.quantity_ordered, item.product.unit_of_measure,
                                 item.unit_price_net, _cents(item.unit_price_net * item.quantity_ordered), item.unit, item.unit_factor,
                                 item.product.hsn_code, item.product.gst_rate)
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
        taxes=display_taxes(config, lines),
        customer_gstin=order.customer.gstin,
        **_statutory_fields(row),
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
    """The order's invoice; when invoicing on delivery, its latest delivery's."""
    row = session.execute(
        select(TallySync).where(TallySync.kind == SALES_INVOICE, TallySync.entity_id == order_id,
                                TallySync.status == "synced")
    ).scalar_one_or_none()
    if row is not None:
        return row
    from ..models import CustomerDelivery

    return session.execute(
        select(TallySync).join(CustomerDelivery, CustomerDelivery.id == TallySync.entity_id)
        .where(TallySync.kind == DELIVERY_INVOICE, CustomerDelivery.sales_order_id == order_id, TallySync.status == "synced")
        .order_by(TallySync.synced_at.desc())
    ).scalars().first()


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
