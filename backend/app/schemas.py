"""Pydantic request/response models.

Decimals are serialised as JSON strings so no quantity or price is distorted by
a float round-trip. The frontend parses them at the API boundary.
"""
from __future__ import annotations

import uuid
from datetime import date as date_type, datetime
from decimal import Decimal
from typing import Any, Dict, Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from .models import (
    AllocationSource,
    CancellationKind,
    EnquiryStatus,
    MovementType,
    OrderStatus,
    PurchaseOrderStatus,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """One page of a listing: the rows, plus enough to draw the pager."""

    items: List[T]
    total: int = Field(description="Rows matching the filters, across all pages.")
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ErrorResponse(BaseModel):
    code: str
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

class ProductRef(ORMModel):
    id: uuid.UUID
    sku: str
    name: str
    unit_of_measure: str


class ProductCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    unit_of_measure: str = Field(default="pcs", max_length=32)
    mrp: Decimal = Field(default=Decimal("0"), ge=0)
    description: Optional[str] = None
    opening_stock: Decimal = Field(
        default=Decimal("0"), ge=0, description="Optional opening stock, recorded as a stock movement."
    )
    opening_unit_cost: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        description="What each opening-stock unit cost to buy. Opens the first FIFO cost layer.",
    )


class ProductUpdate(BaseModel):
    """Stock is intentionally not editable here; use a stock receipt instead."""

    sku: Optional[str] = Field(default=None, min_length=1, max_length=64)
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    unit_of_measure: Optional[str] = Field(default=None, max_length=32)
    mrp: Optional[Decimal] = Field(default=None, ge=0)
    description: Optional[str] = None
    is_active: Optional[bool] = None


class ProductOut(ORMModel):
    id: uuid.UUID
    sku: str
    name: str
    unit_of_measure: str
    mrp: Decimal
    description: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    physical_stock: Decimal
    #: Of the physical stock, how much is already promised to an order.
    reserved_stock: Decimal = Decimal("0")
    #: Physical less reserved: what can still be sold to somebody else.
    available_stock: Decimal = Decimal("0")
    pending_quantity: Decimal
    #: Owed to customers with no stock behind it yet.
    unallocated_quantity: Decimal = Decimal("0")
    net_stock_position: Decimal
    #: Bought from suppliers on confirmed purchase orders, not yet received.
    on_order_quantity: Decimal = Decimal("0")
    #: Bought less sold: physical + on order - pending. What the screens call stock.
    stock: Decimal = Decimal("0")
    #: Most recent purchase price per unit, offered as the default on the next receipt.
    last_purchase_price: Optional[Decimal] = None
    #: Weighted cost of a unit of the stock currently held, from the open FIFO layers.
    average_cost: Decimal = Decimal("0")
    #: What the stock on hand cost to buy.
    stock_value: Decimal = Decimal("0")


class CostLayerOut(ORMModel):
    id: uuid.UUID
    source: MovementType
    source_id: Optional[uuid.UUID] = None
    unit_cost: Decimal
    quantity: Decimal
    quantity_remaining: Decimal
    note: Optional[str] = None
    created_at: datetime


class StockMovementOut(ORMModel):
    id: uuid.UUID
    product_id: uuid.UUID
    movement_type: MovementType
    quantity_change: Decimal
    reference_type: Optional[str] = None
    reference_id: Optional[uuid.UUID] = None
    note: Optional[str] = None
    created_at: datetime


class ProductInventoryOut(ProductOut):
    ledger_balance: Decimal
    movements: List[StockMovementOut] = Field(default_factory=list)
    cost_layers: List[CostLayerOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------

class CustomerRef(ORMModel):
    id: uuid.UUID
    name: str


class CustomerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=32)
    email: Optional[str] = Field(default=None, max_length=255)
    address: Optional[str] = None
    notes: Optional[str] = None


class CustomerUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=32)
    email: Optional[str] = Field(default=None, max_length=255)
    address: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class CustomerOut(ORMModel):
    id: uuid.UUID
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CustomerListRow(CustomerOut):
    """A customer in a listing, with a summary of their trading."""

    order_count: int = 0
    open_order_count: int = 0
    ordered_value: Decimal = Decimal("0.00")
    outstanding_quantity: Decimal = Decimal("0.000")
    outstanding_value: Decimal = Decimal("0.00")
    last_order_at: Optional[datetime] = None


class OutstandingLine(BaseModel):
    product_id: uuid.UUID
    product_sku: str
    product_name: str
    unit_of_measure: str
    pending_quantity: Decimal


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

class OrderLineCreate(BaseModel):
    product_id: uuid.UUID
    quantity_ordered: Decimal = Field(gt=0)
    unit_price: Optional[Decimal] = Field(
        default=None, ge=0, description="Price per unit before discount. Defaults to the product MRP."
    )
    discount_percent: Decimal = Field(
        default=Decimal("0"), ge=0, le=100, description="Line discount as a percentage."
    )


class OrderCreate(BaseModel):
    customer_id: uuid.UUID
    notes: Optional[str] = None
    items: List[OrderLineCreate] = Field(min_length=1)


class CancelRequest(BaseModel):
    reason: Optional[str] = None


class OrderItemOut(ORMModel):
    id: uuid.UUID
    product_id: uuid.UUID
    line_number: int
    quantity_ordered: Decimal
    quantity_fulfilled: Decimal
    quantity_cancelled: Decimal
    quantity_pending: Decimal
    #: Set aside for this line and sitting on the shelf, not yet delivered.
    quantity_reserved: Decimal = Decimal("0")
    #: Outstanding with no stock behind it.
    quantity_unallocated: Decimal = Decimal("0")
    #: Covered by a confirmed purchase order whose goods have not arrived.
    quantity_incoming: Decimal = Decimal("0")
    mrp_snapshot: Optional[Decimal] = None
    unit_price: Decimal
    discount_percent: Decimal
    unit_price_net: Decimal
    product: ProductRef


class OrderCancellationOut(ORMModel):
    id: uuid.UUID
    order_item_id: uuid.UUID
    kind: CancellationKind
    quantity_cancelled: Decimal
    reason: Optional[str] = None
    created_at: datetime


class OrderLineFinancials(BaseModel):
    order_item_id: uuid.UUID
    product_id: uuid.UUID
    unit_price: Decimal
    discount_percent: Decimal
    unit_price_net: Decimal
    line_subtotal: Decimal
    line_discount: Decimal
    line_total: Decimal
    delivered_amount: Decimal
    pending_amount: Decimal
    cancelled_amount: Decimal
    cost_of_goods_sold: Decimal
    gross_profit: Decimal
    margin_percent: Decimal


class OrderTotals(BaseModel):
    subtotal_amount: Decimal
    discount_amount: Decimal
    total_amount: Decimal
    delivered_amount: Decimal
    pending_amount: Decimal
    cancelled_amount: Decimal
    cost_of_goods_sold: Decimal
    gross_profit: Decimal
    margin_percent: Decimal


class OrderFinancials(BaseModel):
    lines: List[OrderLineFinancials] = Field(default_factory=list)
    totals: OrderTotals


class OrderOut(ORMModel):
    id: uuid.UUID
    order_number: str
    customer_id: uuid.UUID
    status: OrderStatus
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    cancelled_at: Optional[datetime] = None
    #: Set when this order was converted from a customer enquiry.
    enquiry_id: Optional[uuid.UUID] = None
    subtotal_amount: Decimal
    discount_amount: Decimal
    total_amount: Decimal
    customer: CustomerRef
    items: List[OrderItemOut] = Field(default_factory=list)


class OrderAllocationOut(BaseModel):
    allocation_id: uuid.UUID
    order_item_id: uuid.UUID
    product_id: uuid.UUID
    product_sku: str
    product_name: str
    source: AllocationSource
    stock_receipt_id: Optional[uuid.UUID] = None
    quantity: Decimal
    cost_amount: Decimal = Decimal("0")
    created_at: datetime


class OrderDetailOut(OrderOut):
    cancellations: List[OrderCancellationOut] = Field(default_factory=list)
    allocations: List[OrderAllocationOut] = Field(default_factory=list)
    financials: Optional[OrderFinancials] = None
    enquiry_number: Optional[str] = None


# ---------------------------------------------------------------------------
# Customer enquiries
# ---------------------------------------------------------------------------

class EnquiryLineCreate(BaseModel):
    product_id: uuid.UUID
    quantity: Decimal = Field(gt=0)
    discount_percent: Decimal = Field(
        default=Decimal("0"), ge=0, le=100, description="Discount for this product, 0-100."
    )


class EnquiryCreate(BaseModel):
    customer_id: uuid.UUID
    notes: Optional[str] = None
    items: List[EnquiryLineCreate] = Field(min_length=1)


class EnquiryUpdate(BaseModel):
    """Only an OPEN enquiry can be changed. Omitted fields are left alone."""

    notes: Optional[str] = None
    items: Optional[List[EnquiryLineCreate]] = None


class MarkLostRequest(BaseModel):
    reason: Optional[str] = None


class EnquiryItemOut(ORMModel):
    id: uuid.UUID
    product_id: uuid.UUID
    product: ProductRef
    line_number: int
    quantity: Decimal
    #: The MRP this line was opened against; the deal is negotiated from it.
    mrp_snapshot: Decimal
    discount_percent: Decimal
    #: Calculated by the backend pricing service, never supplied by the client.
    quoted_unit_price: Decimal
    line_total: Decimal
    discount_amount: Decimal


class EnquiryOut(ORMModel):
    id: uuid.UUID
    enquiry_number: str
    customer_id: uuid.UUID
    customer: CustomerRef
    notes: Optional[str] = None
    status: EnquiryStatus
    created_at: datetime
    updated_at: datetime
    converted_at: Optional[datetime] = None
    lost_at: Optional[datetime] = None
    lost_reason: Optional[str] = None
    #: manual, whatsapp or email
    source: str = "manual"
    #: Who sent it, for enquiries captured from a message.
    source_detail: Optional[str] = None
    sales_order_id: Optional[uuid.UUID] = None
    sales_order_number: Optional[str] = None
    is_editable: bool
    item_count: int
    items: List[EnquiryItemOut] = Field(default_factory=list)
    #: All amounts are before tax; this phase does not calculate tax.
    mrp_total: Decimal
    discount_total: Decimal
    total_amount: Decimal


class EnquiryConversionResult(BaseModel):
    enquiry: EnquiryOut
    order: OrderDetailOut


class CustomerDetailOut(CustomerOut):
    outstanding: List[OutstandingLine] = Field(default_factory=list)
    orders: List[OrderOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Inventory / stock receipts
# ---------------------------------------------------------------------------

class PendingOrderRow(BaseModel):
    order_item_id: uuid.UUID
    order_id: uuid.UUID
    order_number: str
    order_created_at: datetime
    order_status: OrderStatus
    customer_id: uuid.UUID
    customer_name: str
    product_id: uuid.UUID
    quantity_ordered: Decimal
    quantity_fulfilled: Decimal
    quantity_cancelled: Decimal
    quantity_reserved: Decimal = Decimal("0")
    quantity_pending: Decimal
    quantity_unallocated: Decimal = Decimal("0")
    #: Covered by a confirmed purchase order whose goods have not arrived.
    quantity_incoming: Decimal = Decimal("0")
    proposed_allocation: Decimal


class PendingOrdersOut(BaseModel):
    product_id: uuid.UUID
    product_sku: str
    product_name: str
    unit_of_measure: str
    physical_stock: Decimal
    reserved_stock: Decimal = Decimal("0")
    available_stock: Decimal = Decimal("0")
    pending_quantity: Decimal
    unallocated_quantity: Decimal = Decimal("0")
    net_stock_position: Decimal
    #: Bought less sold, now and after this receipt.
    stock: Decimal = Decimal("0")
    stock_after: Optional[Decimal] = None
    receipt_quantity: Optional[Decimal] = None
    required_allocation: Decimal
    surplus_quantity: Optional[Decimal] = None
    free_stock_after: Optional[Decimal] = None
    pending_after: Optional[Decimal] = None
    items: List[PendingOrderRow] = Field(default_factory=list)


class AllocationInput(BaseModel):
    order_item_id: uuid.UUID
    quantity: Decimal = Field(ge=0)


class StockReceiptCreate(BaseModel):
    product_id: uuid.UUID
    quantity: Decimal = Field(gt=0)
    unit_cost: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        description="Purchase price per unit. Opens the FIFO cost layer this stock is sold from.",
    )
    supplier_reference: Optional[str] = Field(default=None, max_length=128)
    note: Optional[str] = None
    allocations: Optional[List[AllocationInput]] = Field(
        default=None,
        description=(
            "Optional custom distribution. Omit it and the backend allocates FIFO. "
            "Whatever is sent is re-validated server-side."
        ),
    )
    idempotency_key: Optional[str] = Field(default=None, max_length=128)


class ReceiptAllocationOut(BaseModel):
    order_item_id: uuid.UUID
    order_id: uuid.UUID
    order_number: str
    customer_id: uuid.UUID
    customer_name: str
    order_created_at: datetime
    order_status: OrderStatus
    quantity_allocated: Decimal
    quantity_ordered: Decimal
    quantity_fulfilled: Decimal
    quantity_reserved: Decimal = Decimal("0")
    quantity_pending: Decimal
    quantity_unallocated: Decimal = Decimal("0")
    #: Covered by a confirmed purchase order whose goods have not arrived.
    quantity_incoming: Decimal = Decimal("0")
    unit_price_net: Decimal
    revenue: Decimal


class StockReceiptResult(BaseModel):
    receipt_id: uuid.UUID
    receipt_number: str
    created_at: datetime
    product_id: uuid.UUID
    product_sku: str
    product_name: str
    unit_of_measure: str
    receipt_quantity: Decimal
    unit_cost: Decimal
    total_cost: Decimal
    supplier_reference: Optional[str] = None
    total_pending_before: Decimal
    unallocated_before: Decimal
    required_allocation: Decimal
    allocated_total: Decimal
    surplus_quantity: Decimal
    allocations: List[ReceiptAllocationOut] = Field(default_factory=list)
    physical_stock_after: Decimal
    reserved_stock_after: Decimal
    available_stock_after: Decimal
    pending_quantity_after: Decimal
    unallocated_after: Decimal
    net_stock_position_after: Decimal
    stock_after: Decimal = Decimal("0")
    stock_value_after: Decimal
    average_cost_after: Decimal


class NegativePositionRow(BaseModel):
    product_id: uuid.UUID
    sku: str
    name: str
    unit_of_measure: str
    physical_stock: Decimal
    reserved_stock: Decimal = Decimal("0")
    pending_quantity: Decimal
    net_stock_position: Decimal
    on_order_quantity: Decimal = Decimal("0")
    stock: Decimal = Decimal("0")
    stock_value: Decimal = Decimal("0")


class RecentOrderRow(BaseModel):
    id: uuid.UUID
    order_number: str
    customer_id: uuid.UUID
    customer_name: str
    status: OrderStatus
    created_at: datetime
    line_count: int
    total_ordered: Decimal
    total_pending: Decimal
    total_amount: Decimal


class RecentReceiptRow(BaseModel):
    id: uuid.UUID
    receipt_number: str
    product_id: uuid.UUID
    product_sku: str
    product_name: str
    unit_of_measure: str
    quantity: Decimal
    unit_cost: Decimal
    total_cost: Decimal
    allocated_quantity: Decimal
    created_at: datetime


class DailySalesRow(BaseModel):
    date: date_type
    orders: int
    booked_value: Decimal
    delivered_value: Decimal


class InventorySummaryOut(BaseModel):
    active_products: int
    active_customers: int
    total_physical_stock: Decimal
    total_reserved_stock: Decimal = Decimal("0")
    total_available_stock: Decimal = Decimal("0")
    total_pending_quantity: Decimal
    total_unallocated_quantity: Decimal = Decimal("0")
    open_orders: int
    total_stock_value: Decimal
    purchase_spend: Decimal
    revenue_delivered: Decimal
    cost_of_goods_sold: Decimal
    gross_profit: Decimal
    margin_percent: Decimal
    discounts_given: Decimal
    outstanding_order_value: Decimal
    products_with_negative_position: List[NegativePositionRow] = Field(default_factory=list)
    #: Products sold beyond what was bought (stock below zero), most short first.
    products_short: List[NegativePositionRow] = Field(default_factory=list)
    recent_orders: List[RecentOrderRow] = Field(default_factory=list)
    recent_receipts: List[RecentReceiptRow] = Field(default_factory=list)
    daily_sales: List[DailySalesRow] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------

class SupplierRef(ORMModel):
    id: uuid.UUID
    code: str
    name: str


class SupplierCreate(BaseModel):
    #: Optional: the backend generates a SUP- code when none is given.
    code: Optional[str] = Field(default=None, max_length=32)
    name: str = Field(min_length=1, max_length=255)
    contact_person: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=32)
    email: Optional[str] = Field(default=None, max_length=255)
    address: Optional[str] = None
    notes: Optional[str] = None


class SupplierUpdate(BaseModel):
    code: Optional[str] = Field(default=None, max_length=32)
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    contact_person: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=32)
    email: Optional[str] = Field(default=None, max_length=255)
    address: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class SupplierOut(ORMModel):
    id: uuid.UUID
    code: str
    name: str
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SupplierListRow(SupplierOut):
    """A supplier in a listing, with what is still due from them."""

    po_count: int = 0
    open_po_count: int = 0
    on_order_quantity: Decimal = Decimal("0.000")
    on_order_value: Decimal = Decimal("0.00")
    last_po_at: Optional[datetime] = None


class SupplierPurchaseOrderRow(BaseModel):
    id: uuid.UUID
    po_number: str
    status: PurchaseOrderStatus
    created_at: datetime
    expected_delivery_date: Optional[datetime] = None
    line_count: int
    total_ordered: Decimal
    total_received: Decimal
    total_cost: Decimal


class SupplierReceiptRow(BaseModel):
    id: uuid.UUID
    receipt_number: str
    created_at: datetime
    purchase_order_id: uuid.UUID
    po_number: str
    delivery_note_reference: Optional[str] = None
    line_count: int
    total_quantity: Decimal
    total_cost: Decimal


class SupplierDetailOut(SupplierOut):
    purchase_orders: List[SupplierPurchaseOrderRow] = Field(default_factory=list)
    goods_receipts: List[SupplierReceiptRow] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Purchase orders
# ---------------------------------------------------------------------------

class PurchaseOrderLineCreate(BaseModel):
    product_id: uuid.UUID
    quantity_ordered: Decimal = Field(gt=0)
    unit_cost: Decimal = Field(default=Decimal("0"), ge=0)
    notes: Optional[str] = None


class PurchaseSettlementInput(BaseModel):
    """Who one product's purchase settles, and how much each."""

    product_id: uuid.UUID
    allocations: List["ReceiptAllocationInput"] = Field(default_factory=list)


class PurchaseOrderCreate(BaseModel):
    supplier_id: uuid.UUID
    items: List[PurchaseOrderLineCreate] = Field(min_length=1)
    expected_delivery_date: Optional[datetime] = None
    notes: Optional[str] = None
    #: Place the order straight away instead of saving it as a draft.
    confirm: bool = False
    #: With ``confirm``: the user's choice of which short customers this
    #: purchase settles. Each product must settle exactly
    #: ``min(quantity bought, quantity short)``. Omitted entirely, the oldest
    #: orders are settled first.
    settlements: Optional[List[PurchaseSettlementInput]] = None


class PurchaseSettleRequest(BaseModel):
    settlements: Optional[List[PurchaseSettlementInput]] = None


class PurchaseOrderUpdate(BaseModel):
    items: Optional[List[PurchaseOrderLineCreate]] = None
    expected_delivery_date: Optional[datetime] = None
    notes: Optional[str] = None


class PurchaseOrderItemOut(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    product: ProductRef
    line_number: int
    quantity_ordered: Decimal
    quantity_received: Decimal
    quantity_remaining: Decimal
    unit_cost: Decimal
    line_cost: Decimal
    notes: Optional[str] = None
    #: Of what is still to arrive, how much is already promised to waiting customers.
    quantity_assigned: Decimal = Decimal("0")
    #: Still to arrive and promised to nobody.
    quantity_free: Decimal = Decimal("0")
    #: How much of the free quantity must still go to customers who are short.
    settle_required: Decimal = Decimal("0")


class PurchaseOrderReceiptRow(BaseModel):
    id: uuid.UUID
    receipt_number: str
    created_at: datetime
    delivery_note_reference: Optional[str] = None
    total_quantity: Decimal


class PurchaseOrderOut(BaseModel):
    id: uuid.UUID
    po_number: str
    supplier_id: uuid.UUID
    supplier: SupplierRef
    status: PurchaseOrderStatus
    expected_delivery_date: Optional[datetime] = None
    ordered_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    cancellation_reason: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    is_editable: bool
    can_receive: bool
    item_count: int
    items: List[PurchaseOrderItemOut] = Field(default_factory=list)
    total_ordered: Decimal
    total_received: Decimal
    total_remaining: Decimal
    total_cost: Decimal
    receipts: List[PurchaseOrderReceiptRow] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Goods receipts
# ---------------------------------------------------------------------------

class ReceiptAllocationInput(BaseModel):
    order_item_id: uuid.UUID
    quantity: Decimal = Field(ge=0)


class GoodsReceiptLineInput(BaseModel):
    purchase_order_item_id: uuid.UUID
    quantity: Decimal = Field(ge=0)
    #: Defaults to the price agreed on the purchase order.
    unit_cost: Optional[Decimal] = Field(default=None, ge=0)
    over_receipt_reason: Optional[str] = None
    #: Omit to allocate FIFO; whatever is sent is re-validated server-side.
    allocations: Optional[List[ReceiptAllocationInput]] = None


class GoodsReceiptRequest(BaseModel):
    purchase_order_id: uuid.UUID
    lines: List[GoodsReceiptLineInput] = Field(min_length=1)
    delivery_note_reference: Optional[str] = Field(default=None, max_length=128)
    notes: Optional[str] = None
    idempotency_key: Optional[str] = Field(default=None, max_length=128)
    #: Accept more than the purchase order still owes. Each over-received line
    #: must carry a reason, which is stored with it.
    allow_over_receipt: bool = False


class ReceiptPreviewAllocation(BaseModel):
    order_item_id: uuid.UUID
    order_id: uuid.UUID
    order_number: str
    order_created_at: datetime
    customer_id: uuid.UUID
    customer_name: str
    quantity_ordered: Decimal
    quantity_delivered: Decimal
    quantity_reserved: Decimal
    quantity_outstanding: Decimal
    quantity_unallocated: Decimal
    #: Covered by a confirmed purchase order whose goods have not arrived.
    quantity_incoming: Decimal = Decimal("0")
    #: The most this line can take from the receipt.
    quantity_eligible: Decimal = Decimal("0")
    proposed_allocation: Decimal


class ReceiptPreviewLine(BaseModel):
    purchase_order_item_id: uuid.UUID
    product_id: uuid.UUID
    product_sku: str
    product_name: str
    unit_of_measure: str
    quantity_ordered: Decimal
    quantity_already_received: Decimal
    quantity_remaining: Decimal
    quantity_receiving: Decimal
    is_over_receipt: bool
    unit_cost: Decimal
    line_cost: Decimal
    eligible_demand: Decimal
    required_allocation: Decimal
    surplus_quantity: Decimal
    physical_stock: Decimal
    reserved_stock: Decimal
    available_stock: Decimal
    physical_stock_after: Decimal
    reserved_stock_after: Decimal
    available_stock_after: Decimal
    pending_quantity: Decimal
    stock: Decimal = Decimal("0")
    stock_after: Decimal = Decimal("0")
    allocations: List[ReceiptPreviewAllocation] = Field(default_factory=list)


class ReceiptPreviewOut(BaseModel):
    purchase_order_id: uuid.UUID
    po_number: str
    supplier_id: uuid.UUID
    supplier_name: str
    status: PurchaseOrderStatus
    lines: List[ReceiptPreviewLine] = Field(default_factory=list)
    total_receiving: Decimal
    total_required_allocation: Decimal
    total_surplus: Decimal
    total_cost: Decimal


class ReceiptResultAllocation(BaseModel):
    order_item_id: uuid.UUID
    order_id: uuid.UUID
    order_number: str
    customer_id: uuid.UUID
    customer_name: str
    quantity_allocated: Decimal
    quantity_outstanding: Decimal
    quantity_reserved: Decimal


class GoodsReceiptResultLine(BaseModel):
    goods_receipt_item_id: uuid.UUID
    purchase_order_item_id: uuid.UUID
    product_id: uuid.UUID
    product_sku: str
    product_name: str
    unit_of_measure: str
    quantity_received: Decimal
    unit_cost: Decimal
    total_cost: Decimal
    is_over_receipt: bool
    over_receipt_reason: Optional[str] = None
    quantity_allocated: Decimal
    surplus_quantity: Decimal
    quantity_ordered_on_po: Decimal
    quantity_received_on_po: Decimal
    quantity_remaining_on_po: Decimal
    physical_stock_after: Decimal
    reserved_stock_after: Decimal
    available_stock_after: Decimal
    # In less promised: the stock figure the business works with.
    net_stock_position_after: Decimal = Decimal("0.000")
    stock_after: Decimal = Decimal("0.000")
    allocations: List[ReceiptResultAllocation] = Field(default_factory=list)


class GoodsReceiptResult(BaseModel):
    receipt_id: uuid.UUID
    receipt_number: str
    created_at: datetime
    purchase_order_id: uuid.UUID
    po_number: str
    po_status: PurchaseOrderStatus
    supplier_id: uuid.UUID
    supplier_name: str
    delivery_note_reference: Optional[str] = None
    notes: Optional[str] = None
    lines: List[GoodsReceiptResultLine] = Field(default_factory=list)
    total_received: Decimal
    total_allocated: Decimal
    total_surplus: Decimal
    total_cost: Decimal


class GoodsReceiptRowLine(BaseModel):
    product_id: uuid.UUID
    product_sku: str
    product_name: str
    unit_of_measure: str
    quantity: Decimal
    unit_cost: Decimal
    is_over_receipt: bool


class GoodsReceiptRow(BaseModel):
    id: uuid.UUID
    receipt_number: str
    created_at: datetime
    purchase_order_id: uuid.UUID
    po_number: str
    supplier_id: uuid.UUID
    supplier_name: str
    delivery_note_reference: Optional[str] = None
    notes: Optional[str] = None
    line_count: int
    total_quantity: Decimal
    total_cost: Decimal
    lines: List[GoodsReceiptRowLine] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Customer deliveries and commitments
# ---------------------------------------------------------------------------

class DeliveryLineInput(BaseModel):
    order_item_id: uuid.UUID
    quantity: Decimal = Field(ge=0)


class DeliveryRequest(BaseModel):
    lines: List[DeliveryLineInput] = Field(min_length=1)
    reference: Optional[str] = Field(default=None, max_length=128)
    notes: Optional[str] = None
    idempotency_key: Optional[str] = Field(default=None, max_length=128)


class ReservationRow(BaseModel):
    reservation_id: uuid.UUID
    quantity: Decimal
    quantity_released: Decimal
    quantity_open: Decimal
    source: AllocationSource
    stock_receipt_id: Optional[uuid.UUID] = None
    goods_receipt_item_id: Optional[uuid.UUID] = None
    created_at: datetime


class FulfilmentLine(BaseModel):
    order_item_id: uuid.UUID
    product_id: uuid.UUID
    product_sku: str
    product_name: str
    unit_of_measure: str
    line_number: int
    quantity_ordered: Decimal
    quantity_delivered: Decimal
    quantity_reserved: Decimal
    quantity_cancelled: Decimal
    quantity_outstanding: Decimal
    quantity_unallocated: Decimal
    #: Covered by a confirmed purchase order whose goods have not arrived.
    quantity_incoming: Decimal = Decimal("0")
    #: What can be handed over right now: reserved and still owed.
    quantity_deliverable: Decimal
    physical_stock: Decimal
    reserved_stock: Decimal
    available_stock: Decimal
    unit_price_net: Decimal
    reservations: List[ReservationRow] = Field(default_factory=list)


class DeliveryHistoryLine(BaseModel):
    product_sku: str
    product_name: str
    quantity: Decimal


class DeliveryHistoryRow(BaseModel):
    id: uuid.UUID
    delivery_number: str
    reference: Optional[str] = None
    created_at: datetime
    lines: List[DeliveryHistoryLine] = Field(default_factory=list)


class OrderFulfilmentOut(BaseModel):
    order_id: uuid.UUID
    order_number: str
    customer_id: uuid.UUID
    customer_name: str
    status: OrderStatus
    created_at: datetime
    can_deliver: bool
    lines: List[FulfilmentLine] = Field(default_factory=list)
    total_outstanding: Decimal
    total_deliverable: Decimal
    deliveries: List[DeliveryHistoryRow] = Field(default_factory=list)


class DeliveryResultLine(BaseModel):
    order_item_id: uuid.UUID
    product_id: uuid.UUID
    product_sku: str
    product_name: str
    unit_of_measure: str
    quantity_delivered_now: Decimal
    quantity_delivered_total: Decimal
    quantity_outstanding: Decimal
    quantity_reserved: Decimal
    physical_stock_after: Decimal
    available_stock_after: Decimal


class DeliveryResult(BaseModel):
    delivery_id: uuid.UUID
    delivery_number: str
    created_at: datetime
    reference: Optional[str] = None
    notes: Optional[str] = None
    order_id: uuid.UUID
    order_number: str
    order_status: OrderStatus
    customer_id: uuid.UUID
    customer_name: str
    lines: List[DeliveryResultLine] = Field(default_factory=list)
    total_delivered: Decimal
    order_outstanding_after: Decimal


class DeliveryRowLine(BaseModel):
    product_id: uuid.UUID
    product_sku: str
    product_name: str
    unit_of_measure: str
    quantity: Decimal


class DeliveryRow(BaseModel):
    id: uuid.UUID
    delivery_number: str
    created_at: datetime
    reference: Optional[str] = None
    notes: Optional[str] = None
    order_id: uuid.UUID
    order_number: str
    customer_id: uuid.UUID
    customer_name: str
    line_count: int
    total_quantity: Decimal
    lines: List[DeliveryRowLine] = Field(default_factory=list)


class CommitmentRow(BaseModel):
    order_item_id: uuid.UUID
    order_id: uuid.UUID
    order_number: str
    order_created_at: datetime
    order_status: OrderStatus
    customer_id: uuid.UUID
    customer_name: str
    product_id: uuid.UUID
    product_sku: str
    product_name: str
    unit_of_measure: str
    quantity_ordered: Decimal
    quantity_delivered: Decimal
    quantity_reserved: Decimal
    quantity_cancelled: Decimal
    quantity_unallocated: Decimal
    #: Covered by a confirmed purchase order whose goods have not arrived.
    quantity_incoming: Decimal = Decimal("0")
    quantity_outstanding: Decimal
    quantity_deliverable: Decimal
    physical_stock: Decimal
    reserved_stock: Decimal
    available_stock: Decimal
    fulfilment_status: str
    outstanding_value: Decimal
    #: The purchase orders covering what is on order, and how much each.
    incoming_sources: List["IncomingSource"] = Field(default_factory=list)
    #: Who this product was last bought from, to suggest when buying more.
    last_supplier_id: Optional[uuid.UUID] = None


class IncomingSource(BaseModel):
    purchase_order_id: uuid.UUID
    purchase_order_item_id: uuid.UUID
    po_number: str
    supplier_name: str
    quantity: Decimal


CommitmentRow.model_rebuild()


class CommitmentCustomerSummary(BaseModel):
    customer_id: uuid.UUID
    customer_name: str
    order_count: int
    line_count: int
    quantity_outstanding: Decimal
    quantity_reserved: Decimal
    quantity_unallocated: Decimal
    #: Covered by a confirmed purchase order whose goods have not arrived.
    quantity_incoming: Decimal = Decimal("0")
    outstanding_value: Decimal
    oldest_order_at: datetime


class CommitmentTotals(BaseModel):
    line_count: int
    customer_count: int
    quantity_outstanding: Decimal
    quantity_reserved: Decimal
    quantity_unallocated: Decimal
    #: Covered by a confirmed purchase order whose goods have not arrived.
    quantity_incoming: Decimal = Decimal("0")
    quantity_deliverable: Decimal
    outstanding_value: Decimal


class PendingCommitmentsOut(BaseModel):
    rows: List[CommitmentRow] = Field(default_factory=list)
    customers: List[CommitmentCustomerSummary] = Field(default_factory=list)
    totals: CommitmentTotals


PurchaseSettlementInput.model_rebuild()
PurchaseOrderCreate.model_rebuild()
PurchaseSettleRequest.model_rebuild()


# ---------------------------------------------------------------------------
# Integrations: AI, WhatsApp, email
# ---------------------------------------------------------------------------


class IntegrationCredentialOut(BaseModel):
    #: Whether this credential is saved. Its value is never returned.
    set: bool
    #: The last four characters, to tell keys apart.
    hint: Optional[str] = None


class IntegrationOut(BaseModel):
    name: str
    enabled: bool
    config: Dict[str, Any]
    credentials: Dict[str, IntegrationCredentialOut]
    updated_at: Optional[datetime] = None


class AiModelOut(BaseModel):
    id: str
    provider: str
    label: str
    hint: str


class IntegrationsOut(BaseModel):
    ai: IntegrationOut
    whatsapp: IntegrationOut
    email: IntegrationOut
    tally: IntegrationOut
    #: Only models the server holds credentials for.
    models: List[AiModelOut]
    #: Providers configured on the server, by name.
    providers: List[str] = []


class IntegrationUpdate(BaseModel):
    enabled: Optional[bool] = None
    config: Optional[Dict[str, Any]] = None
    #: Omit a credential to keep it; send "" to remove it.
    credentials: Optional[Dict[str, Optional[str]]] = None


class AiTestOut(BaseModel):
    ok: bool
    model: str
    reply: str


class EmailCheckOut(BaseModel):
    new_messages: int


class InboundMessageOut(BaseModel):
    id: uuid.UUID
    channel: str
    sender: str
    sender_name: Optional[str] = None
    subject: Optional[str] = None
    body: str
    received_at: datetime
    status: str
    enquiry_id: Optional[uuid.UUID] = None
    enquiry_number: Optional[str] = None
    summary: Optional[str] = None
    error: Optional[str] = None
    processed_at: Optional[datetime] = None


class TallySyncOut(BaseModel):
    id: uuid.UUID
    #: sales_order, sales_invoice or purchase_order
    kind: str
    entity_id: uuid.UUID
    reference: str
    #: pending, synced or failed
    status: str
    attempts: int
    next_attempt_at: Optional[datetime] = None
    #: Tally's number for it -- for an invoice, Tally's invoice number.
    tally_number: Optional[str] = None
    error: Optional[str] = None
    synced_at: Optional[datetime] = None
    #: Invoice to the customer on WhatsApp: none, pending, sent, failed, skipped
    notify_status: str
    notify_to: Optional[str] = None
    notify_error: Optional[str] = None
    notified_at: Optional[datetime] = None
    created_at: datetime


class TallyTestOut(BaseModel):
    companies: List[str]
    company_found: bool


class TemplateStatusOut(BaseModel):
    template: str
    status: str
