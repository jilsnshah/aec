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
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Enum as SAEnum,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
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


class AllocationSource(str, enum.Enum):
    #: Stock that was on hand when the order was placed.
    ORDER_CREATION = "ORDER_CREATION"
    #: Stock that arrived later and was compulsorily settled against the order.
    STOCK_RECEIPT = "STOCK_RECEIPT"
    #: Stock that arrived on a purchase order and was settled against it.
    GOODS_RECEIPT = "GOODS_RECEIPT"


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

    order_items: Mapped[List["SalesOrderItem"]] = relationship(back_populates="product")
    movements: Mapped[List["StockMovement"]] = relationship(back_populates="product")


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


class SalesOrderItem(Base):
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
    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
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

    customer: Mapped["Customer"] = relationship()
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


class CustomerEnquiryItem(Base, TimestampMixin):
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
    phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)

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


class PurchaseOrderItem(Base, TimestampMixin):
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

    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship()

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
