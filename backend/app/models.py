"""SQLAlchemy ORM models for the Phase 1 business management system.

Three numeric concepts exist for every product and are deliberately kept apart:

* **physical stock** -- units actually present in the business
  (``Product.physical_stock``, a transactionally maintained cache of the
  ``StockMovement`` ledger);
* **pending customer quantity** -- units still owed on confirmed sales orders
  (derived from ``SalesOrderItem``);
* **net stock position** -- physical stock minus pending customer quantity,
  which may legitimately be negative.
"""
from __future__ import annotations

import enum
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Enum as SAEnum,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Quantities allow three decimals so units such as kg or litres work.
QUANTITY_PRECISION = 18
QUANTITY_SCALE = 3
# Money uses two decimals.
MONEY_PRECISION = 14
MONEY_SCALE = 2
# Per-unit costs and prices keep four decimals so a cost such as 12.3456 per
# kg is not distorted before it is multiplied out.
UNIT_COST_PRECISION = 14
UNIT_COST_SCALE = 4

Quantity = Numeric(QUANTITY_PRECISION, QUANTITY_SCALE, asdecimal=True)
Money = Numeric(MONEY_PRECISION, MONEY_SCALE, asdecimal=True)
UnitCost = Numeric(UNIT_COST_PRECISION, UNIT_COST_SCALE, asdecimal=True)
Percent = Numeric(5, 2, asdecimal=True)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class UnitLineMixin:
    """A document line entered in one of the product's units (bag, tonne,
    brass...). Quantities and prices on the line stay in the product's base
    unit, so stock and costing never convert; ``unit`` and ``unit_factor``
    record what the customer or supplier actually asked for."""

    #: The unit the line was entered in; NULL means the product's base unit.
    unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    #: How many base units one ``unit`` holds, frozen when the line was written.
    unit_factor: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("1"))

    def _in_unit(self, value: Optional[Decimal]) -> Optional[Decimal]:
        if value is None:
            return None
        factor = self.unit_factor or Decimal("1")
        return (Decimal(value) / factor).quantize(Decimal("0.001"))

    @property
    def unit_name(self) -> str:
        product = getattr(self, "product", None)
        return self.unit or (product.unit_of_measure if product is not None else "")


class MovementType(str, enum.Enum):
    OPENING_STOCK = "OPENING_STOCK"
    #: Ad-hoc stock-in without a purchase order.
    STOCK_RECEIPT = "STOCK_RECEIPT"
    #: Goods arriving against a purchase order.
    GOODS_RECEIPT = "GOODS_RECEIPT"
    #: Goods physically handed to a customer. The only way stock leaves for a
    #: sale: reserving stock for an order moves nothing.
    CUSTOMER_DELIVERY = "CUSTOMER_DELIVERY"
    #: Written by Phase 1, when allocating to an order delivered it at once.
    #: No new movements of this type are created.
    ORDER_FULFILMENT = "ORDER_FULFILMENT"
    ADJUSTMENT = "ADJUSTMENT"
    #: Delivered goods a customer sent back in sellable condition.
    SALES_RETURN = "SALES_RETURN"
    #: Stock leaving one warehouse for another, and arriving there.
    TRANSFER_OUT = "TRANSFER_OUT"
    TRANSFER_IN = "TRANSFER_IN"
    #: Goods sent back to the supplier.
    PURCHASE_RETURN = "PURCHASE_RETURN"


class AllocationSource(str, enum.Enum):
    #: Stock that was on hand when the order was placed.
    ORDER_CREATION = "ORDER_CREATION"
    #: Stock that arrived later and was compulsorily settled against the order.
    STOCK_RECEIPT = "STOCK_RECEIPT"
    #: Stock that arrived on a purchase order and was settled against it.
    GOODS_RECEIPT = "GOODS_RECEIPT"
    #: Stock found in a count or adjustment, settled against waiting orders.
    ADJUSTMENT = "ADJUSTMENT"


class PurchaseOrderStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    ORDERED = "ORDERED"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class OrderStatus(str, enum.Enum):
    PENDING = "PENDING"
    PARTIALLY_FULFILLED = "PARTIALLY_FULFILLED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class CancellationKind(str, enum.Enum):
    FULL = "FULL"
    REMAINING = "REMAINING"


class EnquiryStatus(str, enum.Enum):
    #: Still being negotiated; quantities, discounts and notes can be edited.
    OPEN = "OPEN"
    #: The deal was agreed and a sales order was created from it.
    CONVERTED = "CONVERTED"
    #: The deal was not won. No order, no stock movement.
    LOST = "LOST"


class Product(Base, TimestampMixin):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("mrp >= 0", name="ck_products_mrp_non_negative"),
        CheckConstraint(
            "last_purchase_price IS NULL OR last_purchase_price >= 0",
            name="ck_products_last_purchase_price_non_negative",
        ),
        CheckConstraint("physical_stock >= 0", name="ck_products_physical_stock_non_negative"),
        Index("ix_products_active_name", "is_active", "name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    sku: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit_of_measure: Mapped[str] = mapped_column(String(32), nullable=False, default="pcs")
    mrp: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: Cached balance of the StockMovement ledger; never edited directly by users.
    physical_stock: Mapped[Decimal] = mapped_column(
        Quantity, nullable=False, default=Decimal("0.000")
    )
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    #: Most recent purchase price per unit; a convenience default, not a valuation.
    #: Stock is valued from the open cost layers (see :class:`StockCostLayer`).
    last_purchase_price: Mapped[Optional[Decimal]] = mapped_column(UnitCost, nullable=True)
    #: Grouping for analysis and filtering (e.g. Cement, Steel, Packaging).
    category: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    #: Minimum stock to keep on hand; the reorder point adds lead-time demand to it.
    reorder_level: Mapped[Decimal] = mapped_column(Quantity, nullable=False, default=Decimal("0"))
    #: Who this product is usually bought from, and how many days they take.
    preferred_supplier_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True
    )
    lead_time_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    #: Make or brand (UltraTech, Tata Tiscon...).
    brand: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    #: HSN code for GST invoices and Tally.
    hsn_code: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    #: GST rate in percent; NULL uses the rate in Settings.
    gst_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    #: Weight of one base unit in kilograms; spreads freight by weight.
    weight_kg: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    #: Any further details as name/value pairs: grade, size, colour, thickness...
    specs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    #: The unit orders and quotes start in, and the one purchase orders start
    #: in. NULL means the base unit.
    sales_unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    purchase_unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    #: Counted in whole base units only (bags, pieces); no 2.5 bags.
    whole_units: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Track batches (manufacture week, lot) and expiry; stock leaves earliest
    #: expiry first.
    track_batches: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    #: Days from manufacture to expiry, to fill the expiry date in.
    shelf_life_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    #: The HSN/GST last sent to this product's stock item in Tally ("hsn|rate").
    tally_gst_sig: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)

    preferred_supplier: Mapped[Optional["Supplier"]] = relationship(foreign_keys=[preferred_supplier_id])
    order_items: Mapped[List["SalesOrderItem"]] = relationship(back_populates="product")
    movements: Mapped[List["StockMovement"]] = relationship(back_populates="product")
    alt_units: Mapped[List["ProductUnit"]] = relationship(order_by="ProductUnit.factor", lazy="selectin", viewonly=True)

    @property
    def units(self) -> list:
        """Every unit it is counted in, base first."""
        return [{"name": self.unit_of_measure, "factor": 1.0, "base": True, "for_sales": True, "for_purchase": True}] + [
            {"name": u.name, "factor": float(u.factor), "base": False, "for_sales": u.for_sales, "for_purchase": u.for_purchase}
            for u in self.alt_units
        ]


class Customer(Base, TimestampMixin):
    __tablename__ = "customers"
    __table_args__ = (Index("ix_customers_active_name", "is_active", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    #: Days of credit: an invoice (a delivery) falls due this many days after it.
    payment_terms_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Most the customer may owe at once; None means no limit.
    credit_limit: Mapped[Optional[Decimal]] = mapped_column(Money, nullable=True)
    price_list_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("price_lists.id", ondelete="SET NULL", name="fk_customers_price_list"), nullable=True
    )
    #: Secret token for the customer's own enquiry page (/e/<token>); None = no link.
    portal_token: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, unique=True)
    #: A flat discount for this customer on everything (their own price
    #: lines, price list and groups may still give a better price).
    discount_percent: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    #: Tax identity and the ledger this party is posted to in Tally (kept
    #: once set, so renaming here never creates a second ledger there).
    gstin: Mapped[Optional[str]] = mapped_column(String(15), nullable=True, index=True)
    pan: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    tally_ledger_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    #: For greetings and occasion campaigns.
    birthday: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    anniversary: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    orders: Mapped[List["SalesOrder"]] = relationship(back_populates="customer")


class SalesOrder(Base, TimestampMixin):
    __tablename__ = "sales_orders"
    __table_args__ = (
        Index("ix_sales_orders_customer_created", "customer_id", "created_at"),
        Index("ix_sales_orders_fifo", "created_at", "order_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    order_number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        # RESTRICT: customers with history can never be deleted, only archived.
        ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[OrderStatus] = mapped_column(
        SAEnum(OrderStatus, native_enum=False, length=32, name="order_status"),
        nullable=False,
        default=OrderStatus.PENDING,
        index=True,
    )
    contact_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True
    )
    delivery_address_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("addresses.id", ondelete="SET NULL"), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    #: The enquiry this order was converted from, when it came from one.
    #: UNIQUE, so one enquiry can never produce two orders however many times
    #: the convert button is pressed or the request is retried.
    enquiry_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("customer_enquiries.id", ondelete="RESTRICT"),
        nullable=True,
        unique=True,
    )

    # Billed amounts, computed from the line items when the order is created and
    # kept in step transactionally. All three are for the quantity *ordered*;
    # delivered and outstanding values are derived from fulfilment at read time.
    subtotal_amount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    discount_amount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    total_amount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))

    customer: Mapped["Customer"] = relationship(back_populates="orders")
    enquiry: Mapped[Optional["CustomerEnquiry"]] = relationship(
        back_populates="sales_order", foreign_keys=[enquiry_id]
    )
    items: Mapped[List["SalesOrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="SalesOrderItem.line_number"
    )
    cancellations: Mapped[List["OrderCancellation"]] = relationship(back_populates="order")


class SalesOrderItem(UnitLineMixin, Base):
    __tablename__ = "sales_order_items"
    __table_args__ = (
        CheckConstraint("quantity_ordered > 0", name="ck_order_items_ordered_positive"),
        CheckConstraint("quantity_fulfilled >= 0", name="ck_order_items_fulfilled_non_negative"),
        CheckConstraint("quantity_cancelled >= 0", name="ck_order_items_cancelled_non_negative"),
        CheckConstraint("quantity_reserved >= 0", name="ck_order_items_reserved_non_negative"),
        CheckConstraint(
            "quantity_fulfilled + quantity_cancelled + quantity_reserved <= quantity_ordered",
            name="ck_order_items_reserved_within_ordered",
        ),
        CheckConstraint("quantity_incoming >= 0", name="ck_order_items_incoming_non_negative"),
        CheckConstraint(
            "quantity_fulfilled + quantity_cancelled + quantity_reserved + quantity_incoming"
            " <= quantity_ordered",
            name="ck_order_items_covered_within_ordered",
        ),
        CheckConstraint("unit_price >= 0", name="ck_order_items_unit_price_non_negative"),
        CheckConstraint("unit_price_net >= 0", name="ck_order_items_unit_price_net_non_negative"),
        CheckConstraint(
            "discount_percent >= 0 AND discount_percent <= 100",
            name="ck_order_items_discount_percent_range",
        ),
        CheckConstraint(
            "quantity_fulfilled + quantity_cancelled <= quantity_ordered",
            name="ck_order_items_within_ordered",
        ),
        Index("ix_order_items_product", "product_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sales_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    quantity_ordered: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    #: Quantity physically handed to the customer. Named ``fulfilled`` since
    #: Phase 1, where allocating stock delivered it immediately; every such row
    #: is a real past delivery, so the meaning is unchanged.
    quantity_fulfilled: Mapped[Decimal] = mapped_column(
        Quantity, nullable=False, default=Decimal("0.000")
    )
    #: Quantity set aside for this line and backed by stock on the shelf, but
    #: not yet delivered. Reserving moves no stock; delivering does.
    quantity_reserved: Mapped[Decimal] = mapped_column(
        Quantity, nullable=False, default=Decimal("0.000")
    )
    quantity_cancelled: Mapped[Decimal] = mapped_column(
        Quantity, nullable=False, default=Decimal("0.000")
    )
    #: Quantity covered by a confirmed purchase order whose goods have not
    #: arrived yet. When they arrive it turns into ``quantity_reserved``.
    quantity_incoming: Mapped[Decimal] = mapped_column(
        Quantity, nullable=False, default=Decimal("0.000"), server_default="0"
    )
    #: The product's MRP when the order was placed. Kept so a later MRP change
    #: cannot rewrite the history of what was sold and at what list price.
    mrp_snapshot: Mapped[Optional[Decimal]] = mapped_column(UnitCost, nullable=True)
    #: List price per unit at the time of the order, defaulted from the product MRP.
    unit_price: Mapped[Decimal] = mapped_column(UnitCost, nullable=False, default=Decimal("0.0000"))
    #: Line discount as a percentage of the list price.
    discount_percent: Mapped[Decimal] = mapped_column(
        Percent, nullable=False, default=Decimal("0.00")
    )
    #: ``unit_price`` after the discount; what the customer actually pays per unit.
    unit_price_net: Mapped[Decimal] = mapped_column(
        UnitCost, nullable=False, default=Decimal("0.0000")
    )

    order: Mapped["SalesOrder"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship(back_populates="order_items")
    allocations: Mapped[List["StockAllocation"]] = relationship(back_populates="order_item")

    @property
    def unit_quantity(self) -> Optional[Decimal]:
        return self._in_unit(self.quantity_ordered)

    @property
    def unit_rate(self) -> Decimal:
        """What the customer pays per ``unit`` after the discount."""
        return (self.unit_price_net * (self.unit_factor or Decimal("1"))).quantize(Decimal("0.01"))

    @property
    def quantity_pending(self) -> Decimal:
        """What the business still owes the customer on this line.

        ``ordered - delivered - cancelled``. Reserved stock is *not* subtracted:
        goods set aside are still owed until they are handed over.
        """
        return self.quantity_ordered - self.quantity_fulfilled - self.quantity_cancelled

    @property
    def quantity_unallocated(self) -> Decimal:
        """Outstanding quantity that nothing covers: not in the warehouse and
        not on any purchase order. This is what makes a product short."""
        remaining = self.quantity_pending - self.quantity_reserved - self.quantity_incoming
        return remaining if remaining > Decimal("0") else Decimal("0.000")


class StockReceipt(Base):
    """A goods-receipt header. One receipt may settle many pending order items."""

    __tablename__ = "stock_receipts"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_stock_receipts_quantity_positive"),
        CheckConstraint("unit_cost >= 0", name="ck_stock_receipts_unit_cost_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    #: The godown or yard this happened in.
    warehouse_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    receipt_number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    #: Purchase price per unit. Zero means the cost was not recorded.
    unit_cost: Mapped[Decimal] = mapped_column(UnitCost, nullable=False, default=Decimal("0.0000"))
    #: ``quantity * unit_cost``, stored so purchase spend is reportable directly.
    total_cost: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    supplier_reference: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: Supplied by the client so a retried submission cannot create a second receipt.
    idempotency_key: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, unique=True, index=True
    )
    #: Stored response payload, replayed verbatim for a duplicate submission.
    result_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )

    product: Mapped["Product"] = relationship()
    allocations: Mapped[List["StockAllocation"]] = relationship(back_populates="stock_receipt")


class StockMovement(Base):
    """Append-only ledger. Every change to physical stock writes one row."""

    __tablename__ = "stock_movements"
    __table_args__ = (Index("ix_stock_movements_product_created", "product_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    movement_type: Mapped[MovementType] = mapped_column(
        SAEnum(MovementType, native_enum=False, length=32, name="movement_type"),
        nullable=False,
        index=True,
    )
    #: Signed: positive adds physical stock, negative removes it.
    quantity_change: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    reference_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    reference_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: The godown or yard this happened in.
    warehouse_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )

    product: Mapped["Product"] = relationship(back_populates="movements")


class StockAllocation(Base):
    """Links a quantity of stock to the order item it was consumed by.

    This is what lets the system answer "exactly which customer orders received
    each incoming quantity".
    """

    __tablename__ = "stock_allocations"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_stock_allocations_quantity_positive"),
        Index("ix_stock_allocations_receipt", "stock_receipt_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    order_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sales_order_items.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    #: NULL when the stock was already on hand at order-creation time.
    stock_receipt_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("stock_receipts.id", ondelete="RESTRICT"), nullable=True
    )
    stock_movement_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("stock_movements.id", ondelete="RESTRICT"), nullable=True
    )
    #: The delivery that consumed this stock. NULL on Phase 1 rows, where
    #: allocating to an order delivered it in the same step.
    customer_delivery_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("customer_delivery_items.id", ondelete="RESTRICT"), nullable=True
    )
    source: Mapped[AllocationSource] = mapped_column(
        SAEnum(AllocationSource, native_enum=False, length=32, name="allocation_source"),
        nullable=False,
    )
    quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    #: Cost of goods sold for this allocation, drawn FIFO from the cost layers.
    cost_amount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )

    order_item: Mapped["SalesOrderItem"] = relationship(back_populates="allocations")
    stock_receipt: Mapped[Optional["StockReceipt"]] = relationship(back_populates="allocations")
    stock_movement: Mapped[Optional["StockMovement"]] = relationship()
    cost_consumptions: Mapped[List["StockLayerConsumption"]] = relationship(
        back_populates="allocation"
    )


class StockCostLayer(Base):
    """A batch of stock bought at one price, consumed first-in-first-out.

    Every quantity that enters physical stock opens a layer; every quantity that
    leaves draws from the oldest open layers. That makes the cost of goods sold
    exact rather than an average, and lets the system say which receipt paid for
    the units a given customer received.

    Invariant: for each product, the sum of ``quantity_remaining`` across its
    layers equals ``Product.physical_stock``.
    """

    __tablename__ = "stock_cost_layers"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_cost_layers_quantity_positive"),
        CheckConstraint("unit_cost >= 0", name="ck_cost_layers_unit_cost_non_negative"),
        CheckConstraint(
            "quantity_remaining >= 0 AND quantity_remaining <= quantity",
            name="ck_cost_layers_remaining_within_quantity",
        ),
        Index("ix_cost_layers_fifo", "product_id", "created_at", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    source: Mapped[MovementType] = mapped_column(
        SAEnum(MovementType, native_enum=False, length=32, name="movement_type"), nullable=False
    )
    #: The stock receipt (or product, for opening stock) this layer came from.
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), nullable=True)
    unit_cost: Mapped[Decimal] = mapped_column(UnitCost, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    quantity_remaining: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: The godown or yard this happened in.
    warehouse_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    #: The batch these units belong to (products that track batches).
    batch_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("batches.id", ondelete="RESTRICT", name="fk_cost_layers_batch"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )

    product: Mapped["Product"] = relationship()


class StockLayerConsumption(Base):
    """One draw from one cost layer, for one allocation.

    An allocation that spans two differently priced layers produces two of
    these, so the cost trail stays exact.
    """

    __tablename__ = "stock_layer_consumptions"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_layer_consumptions_quantity_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    stock_allocation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("stock_allocations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    stock_cost_layer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("stock_cost_layers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(UnitCost, nullable=False)
    cost_amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    allocation: Mapped["StockAllocation"] = relationship(back_populates="cost_consumptions")
    cost_layer: Mapped["StockCostLayer"] = relationship()


class CustomerEnquiry(Base, TimestampMixin):
    """A customer requirement being negotiated, before it becomes an order.

    An enquiry holds the products and quantities a customer asked for, and the
    discount agreed on each. When the deal is won it is converted into an
    ordinary :class:`SalesOrder` through the Phase 1 service, so stock
    allocation and pending quantities behave exactly as they do for an order
    entered directly.
    """

    __tablename__ = "customer_enquiries"
    __table_args__ = (
        Index("ix_enquiries_status_created", "status", "created_at"),
        Index("ix_enquiries_customer_created", "customer_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    enquiry_number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    #: None while the sender is not yet a known customer (a message from a
    #: number or email not on file). Set when someone assigns the customer,
    #: at the latest when the enquiry becomes an order.
    customer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    #: Who sent it, as received (name, phone, email): kept even after the
    #: customer is known.
    sender_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sender_phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    sender_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    contact_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True
    )
    delivery_address_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("addresses.id", ondelete="SET NULL"), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[EnquiryStatus] = mapped_column(
        SAEnum(EnquiryStatus, native_enum=False, length=16, name="enquiry_status"),
        nullable=False,
        default=EnquiryStatus.OPEN,
        index=True,
    )
    #: Set when the enquiry is converted. The reverse side of the unique
    #: ``SalesOrder.enquiry_id``, kept for convenient reads.
    sales_order_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("sales_orders.id", ondelete="RESTRICT", use_alter=True),
        nullable=True,
        unique=True,
    )
    converted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lost_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    lost_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: Where the enquiry came from: typed in, or captured from a message.
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="manual", server_default="manual"
    )
    #: Who sent it, for captured enquiries (a phone number or an email address).
    source_detail: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    customer: Mapped[Optional["Customer"]] = relationship()
    items: Mapped[List["CustomerEnquiryItem"]] = relationship(
        back_populates="enquiry",
        cascade="all, delete-orphan",
        order_by="CustomerEnquiryItem.line_number",
    )
    sales_order: Mapped[Optional["SalesOrder"]] = relationship(
        back_populates="enquiry", foreign_keys="SalesOrder.enquiry_id", uselist=False
    )

    @property
    def is_editable(self) -> bool:
        return self.status == EnquiryStatus.OPEN


class CustomerEnquiryItem(UnitLineMixin, Base, TimestampMixin):
    """One product line on an enquiry, priced from a snapshot of its MRP."""

    __tablename__ = "customer_enquiry_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_enquiry_items_quantity_positive"),
        CheckConstraint("mrp_snapshot >= 0", name="ck_enquiry_items_mrp_non_negative"),
        CheckConstraint(
            "discount_percent >= 0 AND discount_percent <= 100",
            name="ck_enquiry_items_discount_range",
        ),
        CheckConstraint("quoted_unit_price >= 0", name="ck_enquiry_items_price_non_negative"),
        # One row per product: adding a product twice consolidates the quantity.
        UniqueConstraint("enquiry_id", "product_id", name="uq_enquiry_items_product"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    enquiry_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("customer_enquiries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    #: The product's MRP when this line was added. The deal is negotiated
    #: against this figure, so a later MRP change cannot move an agreed price.
    mrp_snapshot: Mapped[Decimal] = mapped_column(UnitCost, nullable=False)
    discount_percent: Mapped[Decimal] = mapped_column(
        Percent, nullable=False, default=Decimal("0.00")
    )
    #: Calculated by the pricing service; never accepted from the client.
    quoted_unit_price: Mapped[Decimal] = mapped_column(UnitCost, nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Money, nullable=False)

    enquiry: Mapped["CustomerEnquiry"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship()

    @property
    def unit_quantity(self) -> Optional[Decimal]:
        return self._in_unit(self.quantity)

    @property
    def unit_rate(self) -> Decimal:
        """The quoted price per ``unit``."""
        return (self.quoted_unit_price * (self.unit_factor or Decimal("1"))).quantize(Decimal("0.01"))


class StockReservation(Base):
    """Stock set aside for one sales order line, not yet delivered.

    A reservation moves no stock: the units stay on the shelf and in the cost
    layers until they are delivered. What it does is take them out of the pool
    other customers can be sold from, which is why available stock is
    ``physical stock - reserved stock``.

    ``quantity_released`` records how much of the reservation has since been
    delivered or cancelled, so the open amount is
    ``quantity - quantity_released``.
    """

    __tablename__ = "stock_reservations"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_reservations_quantity_positive"),
        CheckConstraint(
            "quantity_released >= 0 AND quantity_released <= quantity",
            name="ck_reservations_released_within_quantity",
        ),
        Index("ix_reservations_product_open", "product_id", "created_at"),
        Index("ix_reservations_order_item", "order_item_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    order_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sales_order_items.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    quantity_released: Mapped[Decimal] = mapped_column(
        Quantity, nullable=False, default=Decimal("0.000")
    )
    source: Mapped[AllocationSource] = mapped_column(
        SAEnum(AllocationSource, native_enum=False, length=32, name="allocation_source"),
        nullable=False,
    )
    #: Where the stock came from, when it came from a receipt.
    stock_receipt_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("stock_receipts.id", ondelete="RESTRICT"), nullable=True
    )
    goods_receipt_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("goods_receipt_items.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )

    order_item: Mapped["SalesOrderItem"] = relationship()
    product: Mapped["Product"] = relationship()

    @property
    def quantity_open(self) -> Decimal:
        return self.quantity - self.quantity_released


class PurchaseAssignment(Base):
    """Part of a purchase order line promised to a waiting sales order line.

    Stock counts a purchase the moment it is confirmed, so a customer who was
    waiting is settled from it straight away. Nothing physical moves: when the
    goods arrive the assignment is released and becomes a reservation.
    The open amount is ``quantity - quantity_released``.
    """

    __tablename__ = "purchase_assignments"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_assignments_quantity_positive"),
        CheckConstraint(
            "quantity_released >= 0 AND quantity_released <= quantity",
            name="ck_assignments_released_within_quantity",
        ),
        Index("ix_assignments_po_item", "purchase_order_item_id"),
        Index("ix_assignments_order_item", "order_item_id"),
        Index("ix_assignments_product", "product_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    purchase_order_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("purchase_order_items.id", ondelete="RESTRICT"), nullable=False
    )
    order_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sales_order_items.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    quantity_released: Mapped[Decimal] = mapped_column(
        Quantity, nullable=False, default=Decimal("0.000")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    purchase_order_item: Mapped["PurchaseOrderItem"] = relationship()
    order_item: Mapped["SalesOrderItem"] = relationship()

    @property
    def quantity_open(self) -> Decimal:
        return self.quantity - self.quantity_released


class Supplier(Base, TimestampMixin):
    """A business the company buys stock from."""

    __tablename__ = "suppliers"
    __table_args__ = (Index("ix_suppliers_active_name", "is_active", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    contact_person: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    #: Tax identity and the ledger this party is posted to in Tally (kept
    #: once set, so renaming here never creates a second ledger there).
    gstin: Mapped[Optional[str]] = mapped_column(String(15), nullable=True, index=True)
    pan: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    tally_ledger_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    #: Days of credit the supplier gives on goods received.
    payment_terms_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Typical days from placing an order to the goods arriving.
    lead_time_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    purchase_orders: Mapped[List["PurchaseOrder"]] = relationship(back_populates="supplier")


class PurchaseOrder(Base, TimestampMixin):
    """Goods ordered from a supplier. Ordering changes no stock."""

    __tablename__ = "purchase_orders"
    __table_args__ = (
        Index("ix_purchase_orders_supplier_created", "supplier_id", "created_at"),
        Index("ix_purchase_orders_status_created", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    po_number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[PurchaseOrderStatus] = mapped_column(
        SAEnum(PurchaseOrderStatus, native_enum=False, length=24, name="purchase_order_status"),
        nullable=False,
        default=PurchaseOrderStatus.DRAFT,
        index=True,
    )
    expected_delivery_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ordered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    supplier: Mapped["Supplier"] = relationship(back_populates="purchase_orders")
    items: Mapped[List["PurchaseOrderItem"]] = relationship(
        back_populates="purchase_order",
        cascade="all, delete-orphan",
        order_by="PurchaseOrderItem.line_number",
    )
    receipts: Mapped[List["GoodsReceipt"]] = relationship(back_populates="purchase_order")

    @property
    def is_editable(self) -> bool:
        return self.status == PurchaseOrderStatus.DRAFT

    @property
    def can_receive(self) -> bool:
        return self.status in (
            PurchaseOrderStatus.ORDERED,
            PurchaseOrderStatus.PARTIALLY_RECEIVED,
        )


class PurchaseOrderItem(UnitLineMixin, Base, TimestampMixin):
    __tablename__ = "purchase_order_items"
    __table_args__ = (
        CheckConstraint("quantity_ordered > 0", name="ck_po_items_ordered_positive"),
        CheckConstraint("quantity_received >= 0", name="ck_po_items_received_non_negative"),
        CheckConstraint("unit_cost >= 0", name="ck_po_items_unit_cost_non_negative"),
        UniqueConstraint("purchase_order_id", "product_id", name="uq_po_items_product"),
        Index("ix_po_items_product", "product_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    quantity_ordered: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    quantity_received: Mapped[Decimal] = mapped_column(
        Quantity, nullable=False, default=Decimal("0.000")
    )
    #: Expected purchase price agreed when ordering. What is actually paid is
    #: recorded on the receipt line, which may differ.
    unit_cost: Mapped[Decimal] = mapped_column(UnitCost, nullable=False, default=Decimal("0.0000"))
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: The rate contract this line's cost came from, if any.
    rate_contract_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("rate_contracts.id", ondelete="SET NULL"), nullable=True
    )

    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship()

    @property
    def unit_quantity(self) -> Optional[Decimal]:
        return self._in_unit(self.quantity_ordered)

    @property
    def unit_rate(self) -> Decimal:
        """The agreed cost per ``unit``."""
        return (self.unit_cost * (self.unit_factor or Decimal("1"))).quantize(Decimal("0.01"))

    @property
    def quantity_remaining(self) -> Decimal:
        remaining = self.quantity_ordered - self.quantity_received
        return remaining if remaining > Decimal("0") else Decimal("0.000")


class GoodsReceipt(Base):
    """Goods physically arriving against a purchase order."""

    __tablename__ = "goods_receipts"
    __table_args__ = (
        Index("ix_goods_receipts_po_created", "purchase_order_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    #: Who carried the goods, in what, the lorry receipt number and the freight.
    transporter_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("transporters.id", ondelete="SET NULL"), nullable=True, index=True
    )
    vehicle_number: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    lr_number: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    driver_phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    #: The godown or yard this happened in.
    warehouse_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    receipt_number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("purchase_orders.id", ondelete="RESTRICT"), nullable=False
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    #: The supplier's own delivery note or invoice reference.
    delivery_note_reference: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: Supplied by the client so a retried submission cannot book the goods twice.
    idempotency_key: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, unique=True, index=True
    )
    result_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )

    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="receipts")
    supplier: Mapped["Supplier"] = relationship()
    items: Mapped[List["GoodsReceiptItem"]] = relationship(
        back_populates="receipt", cascade="all, delete-orphan"
    )


class GoodsReceiptItem(Base):
    __tablename__ = "goods_receipt_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_gr_items_quantity_positive"),
        CheckConstraint("unit_cost >= 0", name="ck_gr_items_unit_cost_non_negative"),
        Index("ix_gr_items_product", "product_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    goods_receipt_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("goods_receipts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    purchase_order_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("purchase_order_items.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    #: What was actually paid, which may differ from the ordered unit cost.
    unit_cost: Mapped[Decimal] = mapped_column(UnitCost, nullable=False, default=Decimal("0.0000"))
    total_cost: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    #: True when this line was allowed past the remaining PO quantity.
    is_over_receipt: Mapped[bool] = mapped_column(nullable=False, default=False)
    over_receipt_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    stock_movement_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("stock_movements.id", ondelete="RESTRICT"), nullable=True
    )

    receipt: Mapped["GoodsReceipt"] = relationship(back_populates="items")
    purchase_order_item: Mapped["PurchaseOrderItem"] = relationship()
    product: Mapped["Product"] = relationship()


class CustomerDelivery(Base):
    """Goods physically handed to a customer against a sales order."""

    __tablename__ = "customer_deliveries"
    __table_args__ = (Index("ix_deliveries_order_created", "sales_order_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    #: E-way bill for this movement: from Tally, or typed in.
    eway_bill_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    eway_bill_valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Who carried the goods, in what, the lorry receipt number and the freight.
    transporter_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("transporters.id", ondelete="SET NULL"), nullable=True, index=True
    )
    vehicle_number: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    lr_number: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    driver_phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    #: Freight for this trip, and who pays it: us (an expense) or the customer.
    freight_amount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"), server_default="0")
    freight_paid_by: Mapped[str] = mapped_column(String(10), nullable=False, default="us", server_default="us")
    #: The godown or yard this happened in.
    warehouse_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    delivery_number: Mapped[str] = mapped_column(
        String(32), nullable=False, unique=True, index=True
    )
    sales_order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sales_orders.id", ondelete="RESTRICT"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    reference: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, unique=True, index=True
    )
    result_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )

    sales_order: Mapped["SalesOrder"] = relationship()
    customer: Mapped["Customer"] = relationship()
    warehouse: Mapped[Optional["Warehouse"]] = relationship()
    transporter: Mapped[Optional["Transporter"]] = relationship()
    items: Mapped[List["CustomerDeliveryItem"]] = relationship(
        back_populates="delivery", cascade="all, delete-orphan"
    )


class CustomerDeliveryItem(Base):
    __tablename__ = "customer_delivery_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_delivery_items_quantity_positive"),
        Index("ix_delivery_items_order_item", "order_item_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    customer_delivery_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("customer_deliveries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sales_order_items.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    stock_movement_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("stock_movements.id", ondelete="RESTRICT"), nullable=True
    )

    delivery: Mapped["CustomerDelivery"] = relationship(back_populates="items")
    order_item: Mapped["SalesOrderItem"] = relationship()
    product: Mapped["Product"] = relationship()


class OrderCancellation(Base):
    """Audit row written whenever pending quantity is cancelled."""

    __tablename__ = "order_cancellations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sales_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sales_order_items.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[CancellationKind] = mapped_column(
        SAEnum(CancellationKind, native_enum=False, length=16, name="cancellation_kind"),
        nullable=False,
    )
    quantity_cancelled: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )

    order: Mapped["SalesOrder"] = relationship(back_populates="cancellations")


class DocumentCounter(Base):
    """Row-locked counter used to generate gap-free human-readable numbers."""

    __tablename__ = "document_counters"

    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    last_value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class IntegrationSetting(Base):
    """Configuration of one integration: ``ai``, ``whatsapp`` or ``email``.

    Plain settings live in ``config``. Credentials (API keys, passwords, app
    secrets) live in ``secrets``, encrypted with the application's
    ``SECRET_KEY``; they are never returned by the API, only whether each one
    is set.
    """

    __tablename__ = "integration_settings"

    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    secrets: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class InboundMessage(Base):
    """A message received on WhatsApp or email, and what the AI made of it.

    ``external_id`` is the channel's own id (WhatsApp message id, email
    Message-ID), unique per channel, so a message delivered twice -- Meta
    retries webhooks, a mailbox can be read twice -- is only processed once.
    """

    __tablename__ = "inbound_messages"
    __table_args__ = (
        UniqueConstraint("channel", "external_id", name="uq_inbound_channel_external"),
        Index("ix_inbound_received", "received_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    sender: Mapped[str] = mapped_column(String(255), nullable=False)
    sender_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    subject: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    #: pending -> enquiry_created | not_enquiry | no_match | failed | skipped
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    enquiry_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("customer_enquiries.id", ondelete="SET NULL"), nullable=True
    )
    #: The agent's own one-line account of what it did and why.
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    enquiry: Mapped[Optional["CustomerEnquiry"]] = relationship()


class TallySync(Base):
    """One document pushed to Tally, and the invoice sent on from it.

    ``kind`` is ``sales_order``, ``sales_invoice`` or ``purchase_order``; each
    document is synced once per kind. ``tally_master_id`` and ``tally_number``
    are what Tally reports back -- the invoice number on a sales invoice comes
    from Tally. ``notify_*`` tracks sending that invoice to the customer on
    WhatsApp.
    """

    __tablename__ = "tally_syncs"
    __table_args__ = (
        UniqueConstraint("kind", "entity_id", name="uq_tally_sync_kind_entity"),
        Index("ix_tally_syncs_status", "status", "next_attempt_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    reference: Mapped[str] = mapped_column(String(64), nullable=False)
    #: pending -> synced | failed (retried automatically a few times)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    tally_master_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    tally_number: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    #: Read back from Tally after it generates them: the e-invoice (IRN,
    #: acknowledgement, signed QR) and the e-way bill.
    irn: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    irn_ack_no: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    irn_ack_date: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    irn_qr: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    eway_bill_no: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    eway_bill_date: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    statutory_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    #: For sales invoices: none | pending | sent | failed | skipped
    notify_status: Mapped[str] = mapped_column(String(16), nullable=False, default="none")
    notify_to: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    notify_message_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    notify_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class User(Base):
    """Someone who can sign in. Passwords are stored as scrypt hashes only."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Raised when the password changes, which signs out every session.
    session_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------------------
# Follow-ups
# ---------------------------------------------------------------------------


class TaskStatus(str, enum.Enum):
    OPEN = "OPEN"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class TaskPriority(str, enum.Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"


class Task(Base, TimestampMixin):
    """A follow-up someone has to do by a date: call a customer back about a
    quote, chase a supplier, collect a payment. It may point at the record it
    is about, so it shows up there and the record shows its open follow-ups."""

    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    status: Mapped[TaskStatus] = mapped_column(
        SAEnum(TaskStatus, native_enum=False, length=16, name="task_status"), nullable=False, default=TaskStatus.OPEN, index=True
    )
    priority: Mapped[TaskPriority] = mapped_column(
        SAEnum(TaskPriority, native_enum=False, length=16, name="task_priority"), nullable=False, default=TaskPriority.NORMAL
    )
    assignee_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    customer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=True, index=True
    )
    enquiry_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("customer_enquiries.id", ondelete="CASCADE"), nullable=True, index=True
    )
    sales_order_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sales_orders.id", ondelete="CASCADE"), nullable=True, index=True
    )
    supplier_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=True, index=True
    )
    purchase_order_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=True, index=True
    )
    #: manual, assistant, or automatic
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    #: todo, or call: a phone call to make.
    kind: Mapped[str] = mapped_column(String(8), nullable=False, default="todo", server_default="todo")
    #: Who does it: a person (assignee), or PAI, the sales AI agent, who rings
    #: at ``due_at`` and follows ``instructions``.
    doer: Mapped[str] = mapped_column(String(8), nullable=False, default="person", server_default="person")
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: The number to ring; empty uses the linked customer's, supplier's or transporter's.
    call_phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    transporter_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("transporters.id", ondelete="SET NULL"), nullable=True)
    #: PAI's progress: scheduled, calling, done, no_answer, failed; and what came of it.
    ai_status: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    ai_result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    call_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_call_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    phone_call_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("phone_calls.id", ondelete="SET NULL"), nullable=True)

    assignee: Mapped[Optional["User"]] = relationship(foreign_keys=[assignee_id])
    customer: Mapped[Optional["Customer"]] = relationship()
    enquiry: Mapped[Optional["CustomerEnquiry"]] = relationship()
    sales_order: Mapped[Optional["SalesOrder"]] = relationship()
    supplier: Mapped[Optional["Supplier"]] = relationship()
    purchase_order: Mapped[Optional["PurchaseOrder"]] = relationship()


# ---------------------------------------------------------------------------
# The assistant
# ---------------------------------------------------------------------------


class AiConversation(Base):
    """One chat with the assistant. Each user sees only their own."""

    __tablename__ = "ai_conversations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="New chat")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )

    messages: Mapped[List["AiMessage"]] = relationship(
        back_populates="conversation", order_by="AiMessage.created_at", cascade="all, delete-orphan"
    )


class AiMessage(Base):
    """A turn in a conversation. ``blocks_json`` holds the rich parts of an
    assistant reply (tables, charts, files, record links, action cards), each
    built from real tool results; ``content`` is the text."""

    __tablename__ = "ai_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("ai_conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: user, assistant, or event (an action's outcome fed back to the agent)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    blocks_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: Tool calls made while writing this reply: names, arguments, outcomes.
    steps_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attachments_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    context_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    conversation: Mapped["AiConversation"] = relationship(back_populates="messages")


class AiAction(Base):
    """A change the assistant proposed. It runs only when the user confirms it,
    through the same API route the screens use."""

    __tablename__ = "ai_actions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("ai_conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("ai_messages.id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    tool: Mapped[str] = mapped_column(String(64), nullable=False)
    arguments_json: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    #: write, financial, or destructive
    risk: Mapped[str] = mapped_column(String(16), nullable=False)
    #: pending, running, done, failed, cancelled
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    result_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class AiFile(Base):
    """A file in a conversation: one the user attached, or a report the
    assistant generated."""

    __tablename__ = "ai_files"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("ai_conversations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    #: upload or report
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AiToolCall(Base):
    """Audit trail: every tool the assistant ran, for whom, and how it ended."""

    __tablename__ = "ai_tool_calls"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    conversation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("ai_conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    tool: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    route: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    arguments_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )


# ---------------------------------------------------------------------------
# Money in and out, targets, preferences
# ---------------------------------------------------------------------------


class Payment(Base):
    """Money received from a customer or paid to a supplier.

    Receivables are what customers owe for goods delivered, less what they
    paid; payables are what the business owes for goods received, less what it
    paid. Payments settle the oldest open invoices first. A payment is never
    deleted: a mistaken one is voided, with a reason.
    """

    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    #: in (from a customer) or out (to a supplier)
    direction: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    customer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("customers.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    supplier_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    sales_order_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sales_orders.id", ondelete="SET NULL"), nullable=True
    )
    transporter_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("transporters.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    purchase_order_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("purchase_orders.id", ondelete="SET NULL"), nullable=True
    )
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    paid_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    #: cash, bank, upi, cheque, card or other
    method: Mapped[str] = mapped_column(String(16), nullable=False, default="bank")
    reference: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    voided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    void_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    customer: Mapped[Optional["Customer"]] = relationship()
    transporter: Mapped[Optional["Transporter"]] = relationship()
    supplier: Mapped[Optional["Supplier"]] = relationship()

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
        CheckConstraint(
            "(direction = 'in' AND customer_id IS NOT NULL AND supplier_id IS NULL AND transporter_id IS NULL)"
            " OR (direction = 'out' AND num_nonnulls(supplier_id, transporter_id) = 1 AND customer_id IS NULL)",
            name="ck_payments_party",
        ),
    )


class SalesTarget(Base):
    """A monthly sales target for the whole business."""

    __tablename__ = "sales_targets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    #: First day of the month, local time.
    month: Mapped[str] = mapped_column(String(7), nullable=False)  # YYYY-MM
    #: booked (orders placed) or revenue (goods delivered)
    metric: Mapped[str] = mapped_column(String(16), nullable=False, default="booked")
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (UniqueConstraint("month", "metric", name="uq_sales_targets_month_metric"),)


class UserPreference(Base):
    """A per-user setting, e.g. the Home layout."""

    __tablename__ = "user_preferences"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_user_preferences_user_key"),)


class SavedView(Base):
    """A named set of filters on a page, kept per user (or shared)."""

    __tablename__ = "saved_views"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    state_json: Mapped[str] = mapped_column(Text, nullable=False)
    shared: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class StockAdjustment(Base):
    """A correction to physical stock: a count that differs from the books,
    damage, loss, or stock found. Decreases draw from the oldest cost layers
    (the loss is valued at cost); increases open a layer at the current
    average cost. Adjustments posted together in one count share a
    ``count_number``."""

    __tablename__ = "stock_adjustments"
    __table_args__ = (CheckConstraint("quantity_change <> 0", name="ck_adjustments_nonzero"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    #: The godown or yard this happened in.
    warehouse_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    count_number: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(String(16), nullable=False)
    system_quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    counted_quantity: Mapped[Optional[Decimal]] = mapped_column(Quantity, nullable=True)
    quantity_change: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(UnitCost, nullable=False, default=Decimal("0.0000"))
    value_change: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    released_to_short: Mapped[Decimal] = mapped_column(Quantity, nullable=False, default=Decimal("0.000"))
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)

    product: Mapped["Product"] = relationship()


class SalesReturn(Base):
    """Goods a customer sent back: a credit note. Its value is credited to the
    customer's account (settling their oldest invoices first). Lines returned
    in sellable condition go back into stock at the cost they left at."""

    __tablename__ = "sales_returns"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    #: The godown or yard this happened in.
    warehouse_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    sales_order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sales_orders.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(String(24), nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    restocked_cost: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    created_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)

    sales_order: Mapped["SalesOrder"] = relationship()
    customer: Mapped["Customer"] = relationship()
    items: Mapped[List["SalesReturnItem"]] = relationship(back_populates="sales_return", cascade="all, delete-orphan")


class SalesReturnItem(Base):
    __tablename__ = "sales_return_items"
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_return_items_quantity_positive"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    sales_return_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sales_returns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sales_order_items.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    unit_price_net: Mapped[Decimal] = mapped_column(UnitCost, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    restock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    unit_cost: Mapped[Decimal] = mapped_column(UnitCost, nullable=False, default=Decimal("0.0000"))

    sales_return: Mapped["SalesReturn"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship()


class AuditEvent(Base):
    """Who did what and when, for changes that matter: control overrides,
    stock adjustments, returns, voided payments, settings. Append-only."""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    entity: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class PriceList(Base):
    """A set of negotiated prices for a group of customers (dealers,
    contractors, builders). A customer on the list gets, for each product, the
    matching quantity break -- a fixed price or a discount off MRP -- or else
    the list's own discount."""

    __tablename__ = "price_lists"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("0"))
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    valid_from: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: Set for a customer's own special prices (not a shared list).
    customer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE", name="fk_price_lists_customer"), nullable=True, unique=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    items: Mapped[List["PriceListItem"]] = relationship(back_populates="price_list", cascade="all, delete-orphan")


class PriceListItem(Base):
    __tablename__ = "price_list_items"
    __table_args__ = (
        CheckConstraint("min_quantity >= 0", name="ck_price_items_min_qty"),
        CheckConstraint("(price IS NULL) <> (discount_percent IS NULL)", name="ck_price_items_one_rule"),
        UniqueConstraint("price_list_id", "product_id", "min_quantity", name="uq_price_items_break"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    price_list_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("price_lists.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    min_quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False, default=Decimal("0"))
    price: Mapped[Optional[Decimal]] = mapped_column(UnitCost, nullable=True)
    discount_percent: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    #: For a rate contract: the quantity agreed over its life (base units).
    committed_quantity: Mapped[Optional[Decimal]] = mapped_column(Quantity, nullable=True)

    price_list: Mapped["PriceList"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship()


class PhoneCall(Base):
    """One phone call handled by the AI receptionist: who called, how long,
    what was said, and what came of it."""

    __tablename__ = "phone_calls"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_call_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    direction: Mapped[str] = mapped_column(String(8), nullable=False, default="in")
    from_number: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    to_number: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    customer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="in_progress")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    transcript: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    actions: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    enquiry_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("customer_enquiries.id", ondelete="SET NULL"), nullable=True
    )


# ---------------------------------------------------------------------------
# Party details: contacts, phone numbers and emails, addresses and sites
# ---------------------------------------------------------------------------
# Each belongs to exactly one customer or one supplier. The customer's and
# supplier's own phone, email and address columns mirror the primary entries,
# for screens and integrations that show a single value.

_ONE_PARTY = "num_nonnulls(customer_id, supplier_id, transporter_id) = 1"


class Contact(Base, TimestampMixin):
    """A person at a customer or supplier: the owner, a site engineer, accounts."""

    __tablename__ = "contacts"
    __table_args__ = (CheckConstraint(_ONE_PARTY, name="ck_contacts_one_party"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    customer_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=True, index=True)
    supplier_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=True, index=True)
    transporter_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("transporters.id", ondelete="CASCADE"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class ContactPoint(Base, TimestampMixin):
    """One phone number or email address of a party (optionally of one of its
    contacts). A number or address belongs to one party only, so WhatsApp,
    email and phone calls always resolve to the right customer or supplier."""

    __tablename__ = "contact_points"
    __table_args__ = (
        CheckConstraint(_ONE_PARTY, name="ck_contact_points_one_party"),
        CheckConstraint("kind IN ('phone', 'email')", name="ck_contact_points_kind"),
        Index("uq_contact_points_active_value", "kind", "normalized", unique=True, postgresql_where=text("is_active")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    customer_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=True, index=True)
    supplier_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=True, index=True)
    transporter_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("transporters.id", ondelete="CASCADE"), nullable=True, index=True)
    contact_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    #: Phone: the last 10 digits. Email: lower case. Used for matching.
    normalized: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    label: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    is_whatsapp: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Address(Base, TimestampMixin):
    """A billing address, office, warehouse or delivery site of a party."""

    __tablename__ = "addresses"
    __table_args__ = (
        CheckConstraint(_ONE_PARTY, name="ck_addresses_one_party"),
        CheckConstraint("kind IN ('billing', 'site', 'office', 'warehouse')", name="ck_addresses_kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    customer_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=True, index=True)
    supplier_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=True, index=True)
    transporter_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("transporters.id", ondelete="CASCADE"), nullable=True, index=True)
    contact_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    kind: Mapped[str] = mapped_column(String(12), nullable=False, default="site")
    label: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    line: Mapped[str] = mapped_column(Text, nullable=False)
    city: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    state: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    pincode: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    map_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ProductAlias(Base, TimestampMixin):
    """Another name a product goes by: what customers call it ("8mm sariya"),
    a barcode, or a supplier's item code. Used to match messages, calls and
    scanned codes to the one product."""

    __tablename__ = "product_aliases"
    __table_args__ = (
        CheckConstraint("kind IN ('alias', 'barcode', 'supplier_code')", name="ck_product_aliases_kind"),
        UniqueConstraint("kind", "normalized", "supplier_id", name="uq_product_aliases_value"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="alias")
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    supplier_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=True)


class ProductUnit(Base, TimestampMixin):
    """Another unit a product is counted in, as a multiple of its base unit:
    1 tonne = 20 bags, 1 bundle = 10 pieces."""

    __tablename__ = "product_units"
    __table_args__ = (
        CheckConstraint("factor > 0", name="ck_product_units_factor"),
        UniqueConstraint("product_id", "name", name="uq_product_units_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    #: How many base units one of this unit holds.
    factor: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    #: Offered on sales (orders, quotes) and on purchases.
    for_sales: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    for_purchase: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class CustomerGroup(Base, TimestampMixin):
    """A group of customers, filled automatically by rules (orders in the last
    year, spend, years with us, payment behaviour, city...) and/or by hand.
    Members get the group's price list; a customer in several groups gets the
    best price for each product."""

    __tablename__ = "customer_groups"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: [{"field": "spend_12m", "op": ">=", "value": 500000}, ...]
    rules: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    #: "all" rules must match, or "any" one of them.
    match: Mapped[str] = mapped_column(String(3), nullable=False, default="all")
    price_list_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("price_lists.id", ondelete="SET NULL", name="fk_customer_groups_price_list"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    member_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_computed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    price_list: Mapped[Optional["PriceList"]] = relationship()


class CustomerGroupMember(Base):
    """A customer in a group: added by the rules, by hand, or kept out by hand."""

    __tablename__ = "customer_group_members"
    __table_args__ = (
        UniqueConstraint("group_id", "customer_id", name="uq_group_members"),
        CheckConstraint("source IN ('rule', 'manual', 'excluded')", name="ck_group_members_source"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    group_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("customer_groups.id", ondelete="CASCADE"), nullable=False, index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="rule")
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AutomationFlow(Base):
    """One automation pipeline (sales or purchase): its steps as nodes with
    their settings, and the order they run in as edges. Edited in Settings ->
    Automation; read by the agents at run time."""

    __tablename__ = "automation_flows"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    flow: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    updated_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class OutboundMessage(Base):
    """A message the agents (or people) sent, or want to send, to a customer
    or supplier: a reply, a quote, an order summary. Held for approval when
    the flow says so."""

    __tablename__ = "outbound_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    to: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    subject: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    #: sent, failed, pending_approval, discarded
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="sent", index=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    author: Mapped[str] = mapped_column(String(32), nullable=False, default="tai")
    inbound_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("inbound_messages.id", ondelete="SET NULL"), nullable=True)
    customer_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True)
    enquiry_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("customer_enquiries.id", ondelete="SET NULL"), nullable=True)
    provider_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class AgentDraft(Base):
    """An order an agent has read back to a customer, waiting for their yes."""

    __tablename__ = "agent_drafts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    sender: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)
    enquiry_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("customer_enquiries.id", ondelete="SET NULL"), nullable=True)
    items: Mapped[list] = mapped_column(JSON, nullable=False)
    total: Mapped[Decimal] = mapped_column(Money, nullable=False)
    #: awaiting_confirmation, placed, held, cancelled
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="awaiting_confirmation")
    order_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("sales_orders.id", ondelete="SET NULL"), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Warehouse(Base, TimestampMixin):
    """A place stock is kept: a godown, yard, shop or a customer's site store.
    One is the default, used whenever a warehouse is not chosen. "In transit"
    is a system warehouse holding goods between two others."""

    __tablename__ = "warehouses"
    __table_args__ = (CheckConstraint("kind IN ('godown', 'yard', 'shop', 'site', 'transit')", name="ck_warehouses_kind"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    code: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(10), nullable=False, default="godown")
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: Who looks after it, and their phone.
    contact: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    #: Matching Tally godown name.
    tally_godown: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class StockTransfer(Base, TimestampMixin):
    """Goods moving from one warehouse to another: drafted, dispatched (in
    transit), then received. Freight and handling costs are spread over the
    lines and added to the goods' cost at the destination."""

    __tablename__ = "stock_transfers"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'in_transit', 'received', 'cancelled')", name="ck_transfers_status"),
        CheckConstraint("cost_method IN ('quantity', 'value', 'weight')", name="ck_transfers_cost_method"),
        CheckConstraint("from_warehouse_id <> to_warehouse_id", name="ck_transfers_different"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    #: E-way bill for this movement: from Tally, or typed in.
    eway_bill_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    eway_bill_valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    from_warehouse_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False, index=True)
    to_warehouse_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="draft", index=True)
    #: How the costs are spread over the lines.
    cost_method: Mapped[str] = mapped_column(String(10), nullable=False, default="quantity")
    vehicle: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    transporter: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    transporter_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("transporters.id", ondelete="SET NULL"), nullable=True, index=True
    )
    lr_number: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: Value of the goods sent (FIFO cost at the source) and the costs added.
    goods_value: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    extra_cost: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    #: Value of goods that did not arrive (written off).
    loss_value: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    created_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    dispatched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    from_warehouse: Mapped["Warehouse"] = relationship(foreign_keys=[from_warehouse_id])
    to_warehouse: Mapped["Warehouse"] = relationship(foreign_keys=[to_warehouse_id])
    items: Mapped[List["StockTransferItem"]] = relationship(back_populates="transfer", cascade="all, delete-orphan", order_by="StockTransferItem.line_number")
    costs: Mapped[List["StockTransferCost"]] = relationship(back_populates="transfer", cascade="all, delete-orphan")


class StockTransferItem(UnitLineMixin, Base):
    __tablename__ = "stock_transfer_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_transfer_items_quantity"),
        CheckConstraint("quantity_received >= 0 AND quantity_received <= quantity", name="ck_transfer_items_received"),
        UniqueConstraint("transfer_id", "product_id", name="uq_transfer_items_product"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    transfer_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("stock_transfers.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True)
    line_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: Base units sent and received.
    quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    quantity_received: Mapped[Decimal] = mapped_column(Quantity, nullable=False, default=Decimal("0.000"))
    #: FIFO cost of the units sent, from the source warehouse's layers.
    goods_value: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    #: This line's share of the transfer costs.
    extra_cost: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))

    transfer: Mapped["StockTransfer"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship()

    @property
    def unit_quantity(self) -> Optional[Decimal]:
        return self._in_unit(self.quantity)


class StockTransferCost(Base):
    """Freight, loading, unloading, toll... paid to move the goods."""

    __tablename__ = "stock_transfer_costs"
    __table_args__ = (CheckConstraint("amount >= 0", name="ck_transfer_costs_amount"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    transfer_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("stock_transfers.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="freight")
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    paid_to: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    transporter_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("transporters.id", ondelete="SET NULL"), nullable=True, index=True
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    transfer: Mapped["StockTransfer"] = relationship(back_populates="costs")


# ---------------------------------------------------------------------------
# Transporters, landed costs, purchase returns, rate contracts, bookings
# ---------------------------------------------------------------------------


class Transporter(Base, TimestampMixin):
    """A lorry owner, transport company, broker or tempo operator who carries
    goods. A complete party like a customer or supplier: contacts, numbers,
    addresses, GSTIN, Tally ledger, vehicles and a rate card."""

    __tablename__ = "transporters"
    __table_args__ = (
        CheckConstraint("kind IN ('company', 'fleet_owner', 'broker', 'tempo', 'courier', 'own_fleet')", name="ck_transporters_kind"),
        Index("ix_transporters_active_name", "is_active", "name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(12), nullable=False, default="company")
    contact_person: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    gstin: Mapped[Optional[str]] = mapped_column(String(15), nullable=True, index=True)
    pan: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    tally_ledger_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: Places and routes they serve, as free text ("Ahmedabad, Gandhinagar, Mehsana").
    service_areas: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: Days of credit they give on freight bills.
    payment_terms_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: How to reach them for a booking: whatsapp, call or either.
    booking_channel: Mapped[str] = mapped_column(String(10), nullable=False, default="whatsapp")
    #: Our own rating of them, 1-5.
    rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)

    vehicles: Mapped[List["TransporterVehicle"]] = relationship(back_populates="transporter", cascade="all, delete-orphan", order_by="TransporterVehicle.created_at")
    rates: Mapped[List["TransporterRate"]] = relationship(back_populates="transporter", cascade="all, delete-orphan", order_by="TransporterRate.created_at")


VEHICLE_TYPES = ("tempo", "pickup", "lcv", "6_wheeler", "10_wheeler", "12_wheeler", "14_wheeler", "trailer", "tractor", "container", "other")


class TransporterVehicle(Base, TimestampMixin):
    __tablename__ = "transporter_vehicles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    transporter_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("transporters.id", ondelete="CASCADE"), nullable=False, index=True)
    number: Mapped[str] = mapped_column(String(32), nullable=False)
    vehicle_type: Mapped[str] = mapped_column(String(16), nullable=False, default="other")
    capacity_kg: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    driver_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    driver_phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    transporter: Mapped["Transporter"] = relationship(back_populates="vehicles")


class TransporterRate(Base, TimestampMixin):
    """One line of a transporter's rate card: a route and vehicle, and how it is charged."""

    __tablename__ = "transporter_rates"
    __table_args__ = (
        CheckConstraint("basis IN ('trip', 'km', 'tonne', 'quintal', 'kg', 'unit', 'hour')", name="ck_transporter_rates_basis"),
        CheckConstraint("rate >= 0", name="ck_transporter_rates_rate"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    transporter_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("transporters.id", ondelete="CASCADE"), nullable=False, index=True)
    #: Empty means anywhere.
    from_place: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    to_place: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    vehicle_type: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    basis: Mapped[str] = mapped_column(String(8), nullable=False, default="trip")
    rate: Mapped[Decimal] = mapped_column(Money, nullable=False)
    min_charge: Mapped[Optional[Decimal]] = mapped_column(Money, nullable=True)
    loading_included: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    valid_from: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    transporter: Mapped["Transporter"] = relationship(back_populates="rates")


class LandedCost(Base, TimestampMixin):
    """Freight, unloading, insurance and other charges on a goods receipt,
    spread over its lines and added to the goods' cost. Added with the receipt
    or later, when the transporter's bill comes in."""

    __tablename__ = "landed_costs"
    __table_args__ = (CheckConstraint("method IN ('quantity', 'value', 'weight')", name="ck_landed_costs_method"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    goods_receipt_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("goods_receipts.id", ondelete="RESTRICT"), nullable=False, index=True)
    method: Mapped[str] = mapped_column(String(10), nullable=False, default="quantity")
    total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    #: Of the total, what went onto stock still on hand, and what was for goods
    #: already sold (charged to cost of sales).
    on_stock: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    on_sold: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    charges: Mapped[List["LandedCostCharge"]] = relationship(back_populates="landed_cost", cascade="all, delete-orphan")
    lines: Mapped[List["LandedCostLine"]] = relationship(back_populates="landed_cost", cascade="all, delete-orphan")


class LandedCostCharge(Base):
    __tablename__ = "landed_cost_charges"
    __table_args__ = (CheckConstraint("amount >= 0", name="ck_landed_charges_amount"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    landed_cost_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("landed_costs.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="freight")
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    transporter_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("transporters.id", ondelete="SET NULL"), nullable=True, index=True)
    paid_to: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    bill_number: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    landed_cost: Mapped["LandedCost"] = relationship(back_populates="charges")


class LandedCostLine(Base):
    __tablename__ = "landed_cost_lines"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    landed_cost_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("landed_costs.id", ondelete="CASCADE"), nullable=False, index=True)
    goods_receipt_item_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("goods_receipt_items.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    per_unit: Mapped[Decimal] = mapped_column(UnitCost, nullable=False)
    on_stock: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    on_sold: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))

    landed_cost: Mapped["LandedCost"] = relationship(back_populates="lines")
    product: Mapped["Product"] = relationship()


class PurchaseReturn(Base, TimestampMixin):
    """Goods sent back to a supplier (damaged, short-dated, wrong item...):
    stock goes out at the cost it came in, and a debit note is raised. With
    ``replace`` the supplier is to send the goods again, so the purchase
    order is owed that quantity once more."""

    __tablename__ = "purchase_returns"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    #: E-way bill for this movement: from Tally, or typed in.
    eway_bill_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    eway_bill_valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    supplier_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False, index=True)
    purchase_order_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("purchase_orders.id", ondelete="RESTRICT"), nullable=True, index=True)
    goods_receipt_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("goods_receipts.id", ondelete="RESTRICT"), nullable=True, index=True)
    warehouse_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=True)
    reason: Mapped[str] = mapped_column(String(16), nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    replace: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: What the supplier owes back (debit note), at the purchase price.
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    #: What the goods cost on our books (FIFO), taken out of stock value.
    stock_value: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    transporter_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("transporters.id", ondelete="SET NULL"), nullable=True)
    vehicle_number: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    created_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    supplier: Mapped["Supplier"] = relationship()
    items: Mapped[List["PurchaseReturnItem"]] = relationship(back_populates="purchase_return", cascade="all, delete-orphan")


class PurchaseReturnItem(Base):
    __tablename__ = "purchase_return_items"
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_purchase_return_items_qty"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    purchase_return_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("purchase_returns.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    goods_receipt_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("goods_receipt_items.id", ondelete="RESTRICT"), nullable=True)
    purchase_order_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("purchase_order_items.id", ondelete="RESTRICT"), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(UnitCost, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    stock_value: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))

    purchase_return: Mapped["PurchaseReturn"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship()


class RateContract(Base, TimestampMixin):
    """An agreed rate for a period: with a supplier (a mill's annual rate) or
    a customer (a builder's project rate). Its rates live in a price list
    with the contract's dates; purchase orders and quotes pick them up while
    it runs, and the quantity bought or sold against it is tracked."""

    __tablename__ = "rate_contracts"
    __table_args__ = (
        CheckConstraint("(customer_id IS NOT NULL) <> (supplier_id IS NOT NULL)", name="ck_rate_contracts_one_party"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    customer_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("customers.id", ondelete="RESTRICT"), nullable=True, index=True)
    supplier_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=True, index=True)
    #: For a customer's project: the site it is for.
    address_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("addresses.id", ondelete="SET NULL"), nullable=True)
    price_list_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("price_lists.id", ondelete="RESTRICT"), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reference: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    terms: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_cancelled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    price_list: Mapped["PriceList"] = relationship()
    customer: Mapped[Optional["Customer"]] = relationship()
    supplier: Mapped[Optional["Supplier"]] = relationship()


class TransportBooking(Base, TimestampMixin):
    """A request to a transporter for a vehicle: by a person, or by TAI on
    WhatsApp or PAI on a call, at whichever workflow step needs one."""

    __tablename__ = "transport_bookings"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'requested', 'confirmed', 'declined', 'done', 'cancelled')", name="ck_transport_bookings_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    transporter_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("transporters.id", ondelete="SET NULL"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="draft", index=True)
    #: delivery, purchase, transfer, return or other; and the document it is for.
    purpose: Mapped[str] = mapped_column(String(10), nullable=False, default="other")
    reference_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    reference_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    reference_number: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    from_place: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    to_place: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    needed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    vehicle_type: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    load: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    weight_kg: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    #: The estimate from the rate card, and what was agreed.
    estimate: Mapped[Optional[Decimal]] = mapped_column(Money, nullable=True)
    agreed_amount: Mapped[Optional[Decimal]] = mapped_column(Money, nullable=True)
    vehicle_number: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    driver_phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    #: Who asked (person, tai, pai) and how (whatsapp, call, manual).
    requested_by: Mapped[str] = mapped_column(String(8), nullable=False, default="person")
    channel: Mapped[str] = mapped_column(String(10), nullable=False, default="manual")
    reply: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    transporter: Mapped[Optional["Transporter"]] = relationship()


# ---------------------------------------------------------------------------
# Trigger engine: runs, events, supplier quote requests, feedback
# ---------------------------------------------------------------------------


class AutomationState(Base):
    """When a scheduled trigger last ran, and anything it must remember."""

    __tablename__ = "automation_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class AutomationEvent(Base):
    """One thing a trigger or step did, for whom: the activity log, and what
    frequency caps and cool-downs are counted from."""

    __tablename__ = "automation_events"
    __table_args__ = (Index("ix_automation_events_party", "party_type", "party_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    step: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    #: The rule that fired (reorder_point, dormant, ...) or the action.
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    party_type: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    party_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), nullable=True)
    subject_type: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    subject_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    #: done, sent, held, skipped, failed, awaiting_reply, replied
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="done")
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    detail: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)


class SupplierQuoteRequest(Base, TimestampMixin):
    """A request for prices sent to several suppliers (RFQ): what is needed,
    who was asked, what they replied, and which offer was chosen."""

    __tablename__ = "supplier_quote_requests"
    __table_args__ = (CheckConstraint("status IN ('open', 'decided', 'ordered', 'cancelled')", name="ck_rfq_status"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="open", index=True)
    #: Why it was raised: the trigger rule, or "manual".
    reason: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    needed_by: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reply_by: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    chosen_quote_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), nullable=True)
    purchase_order_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("purchase_orders.id", ondelete="SET NULL"), nullable=True)
    decision: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(8), nullable=False, default="system")

    lines: Mapped[List["SupplierQuoteRequestLine"]] = relationship(back_populates="request", cascade="all, delete-orphan")
    quotes: Mapped[List["SupplierQuote"]] = relationship(back_populates="request", cascade="all, delete-orphan")


class SupplierQuoteRequestLine(UnitLineMixin, Base):
    __tablename__ = "supplier_quote_request_lines"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    request_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("supplier_quote_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    #: Base units wanted.
    quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    #: What it is for: short customers, reorder level, cover.
    why: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)

    request: Mapped["SupplierQuoteRequest"] = relationship(back_populates="lines")
    product: Mapped["Product"] = relationship()


class SupplierQuote(Base, TimestampMixin):
    """One supplier's answer to a request."""

    __tablename__ = "supplier_quotes"
    __table_args__ = (CheckConstraint("status IN ('to_ask', 'asked', 'replied', 'declined', 'no_reply')", name="ck_supplier_quotes_status"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    request_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("supplier_quote_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    supplier_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="to_ask")
    channel: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    asked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reminded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    replied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reply: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    delivery_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    #: Why this supplier was asked (preferred, contract, past supplier).
    source: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    score: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2), nullable=True)

    request: Mapped["SupplierQuoteRequest"] = relationship(back_populates="quotes")
    supplier: Mapped["Supplier"] = relationship()
    lines: Mapped[List["SupplierQuoteLine"]] = relationship(back_populates="quote", cascade="all, delete-orphan")


class SupplierQuoteLine(Base):
    __tablename__ = "supplier_quote_lines"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    quote_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("supplier_quotes.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    #: Price per base unit, before tax.
    price: Mapped[Decimal] = mapped_column(UnitCost, nullable=False)
    quantity_available: Mapped[Optional[Decimal]] = mapped_column(Quantity, nullable=True)

    quote: Mapped["SupplierQuote"] = relationship(back_populates="lines")
    product: Mapped["Product"] = relationship()


class CustomerFeedback(Base):
    """What a customer said when asked after delivery: a rating and any complaint."""

    __tablename__ = "customer_feedback"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    customer_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    sales_order_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("sales_orders.id", ondelete="SET NULL"), nullable=True)
    delivery_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("customer_deliveries.id", ondelete="SET NULL"), nullable=True, index=True)
    rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    complaint: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)


class Batch(Base):
    """A batch (lot) of a product: cement of one manufacture week, a paint lot.
    Units carry their batch through receipts, transfers and deliveries."""

    __tablename__ = "batches"
    __table_args__ = (UniqueConstraint("product_id", "number", name="uq_batches_product_number"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    number: Mapped[str] = mapped_column(String(64), nullable=False)
    manufactured_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    expires_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    supplier_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    product: Mapped["Product"] = relationship()


# ---------------------------------------------------------------------------
# Marketing
# ---------------------------------------------------------------------------


class MarketingConsent(Base):
    """Whether a customer agreed to marketing on a channel, how and when.
    Nothing promotional is sent without an opted_in row for that channel."""

    __tablename__ = "marketing_consents"
    __table_args__ = (UniqueConstraint("customer_id", "channel", name="uq_marketing_consents_customer_channel"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    customer_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE", name="fk_marketing_consents_customer"), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    #: opted_in | opted_out
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    #: manual | portal | whatsapp_keyword | import | enquiry | order
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    evidence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    recorded_by: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class MarketingAudience(Base, TimestampMixin):
    """A saved, live audience: customer groups and/or rules over ERP figures,
    with people added or kept out by hand."""

    __tablename__ = "marketing_audiences"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: {"group_ids": [...], "rules": [...], "match": "all", "include": [...], "exclude": [...]}
    definition: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class MarketingOpportunity(Base):
    """Something worth promoting, found by the Strategist or a rule: aged
    stock, a new product, customers going quiet, a festival coming."""

    __tablename__ = "marketing_opportunities"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    why: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    product_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    #: Audience definition (same shape as MarketingAudience.definition).
    audience: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    channels: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    objective: Mapped[str] = mapped_column(String(24), nullable=False, default="sales")
    score: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    value_estimate: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    #: new | accepted | dismissed | expired
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="new", index=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="strategist")
    dedupe_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    campaign_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("marketing_campaigns.id", ondelete="SET NULL", name="fk_marketing_opportunities_campaign", use_alter=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class MarketingCampaign(Base, TimestampMixin):
    """A campaign: goal, audience, products, offer, dates, content per channel,
    approval and results."""

    __tablename__ = "marketing_campaigns"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    #: Short code used in links and replies to attribute results (e.g. C7K2Q).
    code: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    #: sales | launch | clearance | reactivation | festival | loyalty | awareness | greeting
    objective: Mapped[str] = mapped_column(String(24), nullable=False, default="sales")
    #: draft | review | approved | running | completed | paused | cancelled
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="draft", index=True)
    channels: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    audience_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("marketing_audiences.id", ondelete="SET NULL", name="fk_marketing_campaigns_audience"), nullable=True)
    #: Used when no saved audience is chosen.
    audience: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    product_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    offer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    brief: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    starts_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    budget: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    spend: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    #: Who made it: a username or an agent (strategist, rule:<name>).
    created_by: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    opportunity_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("marketing_opportunities.id", ondelete="SET NULL", name="fk_marketing_campaigns_opportunity"), nullable=True)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    contents: Mapped[List["MarketingContent"]] = relationship(back_populates="campaign", cascade="all, delete-orphan", order_by="MarketingContent.created_at")


class MarketingMedia(Base):
    """An image for a post or message, kept in the database (hosting has no
    disk) and served at an unguessable public URL so Instagram and WhatsApp
    can fetch it."""

    __tablename__ = "marketing_media"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    token: Mapped[str] = mapped_column(String(48), nullable=False, unique=True)
    mime: Mapped[str] = mapped_column(String(40), nullable=False, default="image/jpeg")
    width: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    height: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    #: upload | card | ai
    source: Mapped[str] = mapped_column(String(12), nullable=False, default="upload")
    prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    name: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    product_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL", name="fk_marketing_media_product"), nullable=True)
    campaign_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("marketing_campaigns.id", ondelete="SET NULL", name="fk_marketing_media_campaign"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class MarketingContent(Base, TimestampMixin):
    """One piece of a campaign on one channel: an Instagram post or a
    WhatsApp broadcast, with its schedule, state and results."""

    __tablename__ = "marketing_contents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    campaign_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("marketing_campaigns.id", ondelete="CASCADE", name="fk_marketing_contents_campaign"), nullable=False, index=True)
    #: instagram | whatsapp
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    caption: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    hashtags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    #: WhatsApp: the approved template, its language and the value of each {{n}}
    #: (may contain {name}, {first_name}, {product}, {offer}, {link}).
    template_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    template_language: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    variables: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    media_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("marketing_media.id", ondelete="SET NULL", name="fk_marketing_contents_media"), nullable=True)
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    #: draft | scheduled | publishing | published | sending | sent | failed | cancelled
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="draft", index=True)
    ai_generated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: Instagram: container id, media id and link once published.
    container_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, unique=True)
    permalink: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    campaign: Mapped["MarketingCampaign"] = relationship(back_populates="contents")
    media: Mapped[Optional["MarketingMedia"]] = relationship()


class MarketingSend(Base):
    """One customer in a WhatsApp broadcast. Unique per broadcast and customer,
    so nobody is messaged twice by the same broadcast."""

    __tablename__ = "marketing_sends"
    __table_args__ = (UniqueConstraint("content_id", "customer_id", name="uq_marketing_sends_content_customer"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    campaign_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("marketing_campaigns.id", ondelete="CASCADE", name="fk_marketing_sends_campaign"), nullable=False, index=True)
    content_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("marketing_contents.id", ondelete="CASCADE", name="fk_marketing_sends_content"), nullable=False, index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE", name="fk_marketing_sends_customer"), nullable=False, index=True)
    to: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    #: queued | sending | sent | delivered | read | replied | failed | skipped
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="queued", index=True)
    skip_reason: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    wamid: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, unique=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    replied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class InstagramComment(Base):
    """A comment on one of our Instagram posts, with our reply."""

    __tablename__ = "instagram_comments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    media_external_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    content_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("marketing_contents.id", ondelete="SET NULL", name="fk_instagram_comments_content"), nullable=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    commented_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    #: The suggested or sent reply.
    reply_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: none | draft | sent | failed
    reply_status: Mapped[str] = mapped_column(String(8), nullable=False, default="none")
    reply_external_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    replied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: question | buying | praise | complaint | spam | other
    intent: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class WhatsappTemplate(Base):
    """A message template on the WhatsApp Business account, as Meta last
    reported it."""

    __tablename__ = "whatsapp_templates"
    __table_args__ = (UniqueConstraint("name", "language", name="uq_whatsapp_templates_name_language"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    language: Mapped[str] = mapped_column(String(12), nullable=False, default="en")
    category: Mapped[str] = mapped_column(String(20), nullable=False, default="MARKETING")
    #: APPROVED | PENDING | REJECTED | PAUSED | DISABLED | DRAFT (not sent to Meta yet)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="DRAFT")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    header: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    footer: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    variable_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    examples: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    external_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class MarketingRule(Base, TimestampMixin):
    """A marketing automation: when <trigger> (and <conditions>), do <action>,
    with an approval policy and a cooldown so it does not repeat itself."""

    __tablename__ = "marketing_rules"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    trigger: Mapped[str] = mapped_column(String(32), nullable=False)
    #: Trigger settings: days, threshold, product/category, festival...
    conditions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    #: suggest | draft_campaign | send_message | create_task
    action: Mapped[str] = mapped_column(String(24), nullable=False, default="draft_campaign")
    action_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    #: approval: drafts wait for a person; auto: allowed to run within the limits.
    approval: Mapped[str] = mapped_column(String(10), nullable=False, default="approval")
    cooldown_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class MarketingConversion(Base):
    """An order or enquiry counted towards a campaign, and why."""

    __tablename__ = "marketing_conversions"
    __table_args__ = (
        UniqueConstraint("campaign_id", "sales_order_id", name="uq_marketing_conversions_order"),
        UniqueConstraint("campaign_id", "enquiry_id", name="uq_marketing_conversions_enquiry"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    campaign_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("marketing_campaigns.id", ondelete="CASCADE", name="fk_marketing_conversions_campaign"), nullable=False, index=True)
    customer_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL", name="fk_marketing_conversions_customer"), nullable=True)
    sales_order_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("sales_orders.id", ondelete="CASCADE", name="fk_marketing_conversions_order"), nullable=True)
    enquiry_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("customer_enquiries.id", ondelete="CASCADE", name="fk_marketing_conversions_enquiry"), nullable=True)
    value: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    #: reply | link | after_message | after_post
    reason: Mapped[str] = mapped_column(String(16), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class MarketingEvent(Base):
    """The marketing log: what agents and the executor did, and what failed."""

    __tablename__ = "marketing_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid)
    campaign_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("marketing_campaigns.id", ondelete="CASCADE", name="fk_marketing_events_campaign"), nullable=True, index=True)
    content_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("marketing_contents.id", ondelete="SET NULL", name="fk_marketing_events_content"), nullable=True)
    #: strategist | creative | executor | engagement | analyst | person | rule
    actor: Mapped[str] = mapped_column(String(24), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    #: info | success | warning | error
    level: Mapped[str] = mapped_column(String(8), nullable=False, default="info")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
