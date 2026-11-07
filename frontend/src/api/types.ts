/** One page of a server listing. `total` counts every matching row. */
export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

/** Shapes returned by the backend. Decimals arrive as strings and are parsed at
 *  the boundary (see `api/client.ts`) so no precision is lost in transit. */

export type OrderStatus = 'PENDING' | 'PARTIALLY_FULFILLED' | 'FULFILLED' | 'CANCELLED'
export type MovementType = 'OPENING_STOCK' | 'STOCK_RECEIPT' | 'ORDER_FULFILMENT' | 'ADJUSTMENT'
export type AllocationSource = 'ORDER_CREATION' | 'STOCK_RECEIPT'

export interface Product {
  id: string
  sku: string
  name: string
  unit_of_measure: string
  mrp: string
  description: string | null
  is_active: boolean
  created_at: string
  updated_at: string
  physical_stock: string
  /** Of the physical stock, how much is already promised to an order. */
  reserved_stock: string
  /** Physical less reserved: what can still be sold to somebody else. */
  available_stock: string
  pending_quantity: string
  /** Owed to customers with no stock behind it yet. */
  unallocated_quantity: string
  net_stock_position: string
  /** Bought from suppliers on confirmed purchase orders, not yet received. */
  on_order_quantity: string
  /** Bought less sold: what the screens call stock. Negative when short. */
  stock: string
  /** Most recent purchase price per unit; the default on the next receipt. */
  last_purchase_price: string | null
  /** Weighted cost of a unit of the stock held, from the open FIFO layers. */
  average_cost: string
  /** What the stock on hand cost to buy. */
  stock_value: string
}

export interface CostLayer {
  id: string
  source: MovementType
  source_id: string | null
  unit_cost: string
  quantity: string
  quantity_remaining: string
  note: string | null
  created_at: string
}

export interface StockMovement {
  id: string
  product_id: string
  movement_type: MovementType
  quantity_change: string
  reference_type: string | null
  reference_id: string | null
  note: string | null
  created_at: string
}

export interface ProductInventory extends Product {
  ledger_balance: string
  movements: StockMovement[]
  cost_layers: CostLayer[]
}

export interface Customer {
  id: string
  name: string
  phone: string | null
  email: string | null
  address: string | null
  notes: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

/** A customer in a listing, with a summary of their trading. */
export interface CustomerListRow extends Customer {
  order_count: number
  open_order_count: number
  ordered_value: string
  outstanding_quantity: string
  outstanding_value: string
  last_order_at: string | null
}

export interface OutstandingLine {
  product_id: string
  product_sku: string
  product_name: string
  unit_of_measure: string
  pending_quantity: string
}

export interface CustomerDetail extends Customer {
  outstanding: OutstandingLine[]
  orders: Order[]
}

export interface OrderItem {
  id: string
  product_id: string
  line_number: number
  quantity_ordered: string
  quantity_fulfilled: string
  quantity_cancelled: string
  quantity_pending: string
  /** Set aside for this line and on the shelf, not yet delivered. */
  quantity_reserved: string
  /** Outstanding with no stock behind it. */
  quantity_unallocated: string
  /** Covered by a confirmed purchase order whose goods have not arrived. */
  quantity_incoming: string
  mrp_snapshot: string | null
  unit_price: string
  discount_percent: string
  unit_price_net: string
  product: { id: string; sku: string; name: string; unit_of_measure: string }
}

export interface Order {
  id: string
  order_number: string
  customer_id: string
  status: OrderStatus
  notes: string | null
  created_at: string
  updated_at: string
  cancelled_at: string | null
  enquiry_id: string | null
  subtotal_amount: string
  discount_amount: string
  total_amount: string
  customer: { id: string; name: string }
  items: OrderItem[]
}

export interface OrderLineFinancials {
  order_item_id: string
  product_id: string
  unit_price: string
  discount_percent: string
  unit_price_net: string
  line_subtotal: string
  line_discount: string
  line_total: string
  delivered_amount: string
  pending_amount: string
  cancelled_amount: string
  cost_of_goods_sold: string
  gross_profit: string
  margin_percent: string
}

export interface OrderTotals {
  subtotal_amount: string
  discount_amount: string
  total_amount: string
  delivered_amount: string
  pending_amount: string
  cancelled_amount: string
  cost_of_goods_sold: string
  gross_profit: string
  margin_percent: string
}

export interface OrderFinancials {
  lines: OrderLineFinancials[]
  totals: OrderTotals
}

export interface OrderCancellation {
  id: string
  order_item_id: string
  kind: 'FULL' | 'REMAINING'
  quantity_cancelled: string
  reason: string | null
  created_at: string
}

export interface OrderAllocation {
  allocation_id: string
  order_item_id: string
  product_id: string
  product_sku: string
  product_name: string
  source: AllocationSource
  stock_receipt_id: string | null
  quantity: string
  cost_amount: string
  created_at: string
}

export interface OrderDetail extends Order {
  cancellations: OrderCancellation[]
  allocations: OrderAllocation[]
  financials: OrderFinancials | null
  /** Set when this order was converted from a customer enquiry. */
  enquiry_number: string | null
}

export interface PendingOrderRow {
  order_item_id: string
  order_id: string
  order_number: string
  order_created_at: string
  order_status: OrderStatus
  customer_id: string
  customer_name: string
  product_id: string
  quantity_ordered: string
  quantity_fulfilled: string
  quantity_cancelled: string
  quantity_reserved: string
  quantity_pending: string
  quantity_unallocated: string
  /** Covered by a confirmed purchase order whose goods have not arrived. */
  quantity_incoming: string
  proposed_allocation: string
}

export interface PendingOrders {
  product_id: string
  product_sku: string
  product_name: string
  unit_of_measure: string
  physical_stock: string
  reserved_stock: string
  available_stock: string
  pending_quantity: string
  unallocated_quantity: string
  net_stock_position: string
  stock: string
  stock_after: string | null
  receipt_quantity: string | null
  required_allocation: string
  surplus_quantity: string | null
  free_stock_after: string | null
  pending_after: string | null
  items: PendingOrderRow[]
}

export interface ReceiptAllocation {
  order_item_id: string
  order_id: string
  order_number: string
  customer_id: string
  customer_name: string
  order_created_at: string
  order_status: OrderStatus
  quantity_allocated: string
  quantity_ordered: string
  quantity_fulfilled: string
  quantity_reserved: string
  quantity_pending: string
  quantity_unallocated: string
  /** Covered by a confirmed purchase order whose goods have not arrived. */
  quantity_incoming: string
  unit_price_net: string
  revenue: string
}

export interface StockReceiptResult {
  receipt_id: string
  receipt_number: string
  created_at: string
  product_id: string
  product_sku: string
  product_name: string
  unit_of_measure: string
  receipt_quantity: string
  unit_cost: string
  total_cost: string
  supplier_reference: string | null
  total_pending_before: string
  unallocated_before: string
  required_allocation: string
  allocated_total: string
  surplus_quantity: string
  allocations: ReceiptAllocation[]
  physical_stock_after: string
  reserved_stock_after: string
  available_stock_after: string
  pending_quantity_after: string
  unallocated_after: string
  net_stock_position_after: string
  stock_after: string
  stock_value_after: string
  average_cost_after: string
}

export interface NegativePositionRow {
  product_id: string
  sku: string
  name: string
  unit_of_measure: string
  physical_stock: string
  reserved_stock: string
  pending_quantity: string
  net_stock_position: string
  on_order_quantity: string
  stock: string
  stock_value: string
}

export interface RecentOrderRow {
  id: string
  order_number: string
  customer_id: string
  customer_name: string
  status: OrderStatus
  created_at: string
  line_count: number
  total_ordered: string
  total_pending: string
  total_amount: string
}

export interface RecentReceiptRow {
  id: string
  receipt_number: string
  product_id: string
  product_sku: string
  product_name: string
  unit_of_measure: string
  quantity: string
  unit_cost: string
  total_cost: string
  allocated_quantity: string
  created_at: string
}

export interface DailySales {
  /** Local calendar day, YYYY-MM-DD. */
  date: string
  orders: number
  booked_value: string
  delivered_value: string
}

export interface InventorySummary {
  active_products: number
  active_customers: number
  total_physical_stock: string
  total_reserved_stock: string
  total_available_stock: string
  total_pending_quantity: string
  total_unallocated_quantity: string
  open_orders: number
  total_stock_value: string
  purchase_spend: string
  revenue_delivered: string
  cost_of_goods_sold: string
  gross_profit: string
  margin_percent: string
  discounts_given: string
  outstanding_order_value: string
  products_with_negative_position: NegativePositionRow[]
  /** Sold beyond what was bought, most short first. */
  products_short: NegativePositionRow[]
  recent_orders: RecentOrderRow[]
  recent_receipts: RecentReceiptRow[]
  daily_sales: DailySales[]
}

/* -------------------------------------------------------------------------- */
/* Customer enquiries                                                          */
/* -------------------------------------------------------------------------- */

export type EnquiryStatus = 'OPEN' | 'CONVERTED' | 'LOST'

export interface EnquiryItem {
  id: string
  product_id: string
  product: { id: string; sku: string; name: string; unit_of_measure: string }
  line_number: number
  quantity: string
  /** The MRP this line was opened against; the deal is negotiated from it. */
  mrp_snapshot: string
  discount_percent: string
  /** Calculated by the backend, never sent by the client. */
  quoted_unit_price: string
  line_total: string
  discount_amount: string
}

export interface Enquiry {
  id: string
  enquiry_number: string
  customer_id: string
  customer: { id: string; name: string }
  notes: string | null
  status: EnquiryStatus
  created_at: string
  updated_at: string
  converted_at: string | null
  lost_at: string | null
  lost_reason: string | null
  /** Where it came from: typed in, or captured from a message. */
  source: 'manual' | 'whatsapp' | 'email'
  /** Who sent it, for captured enquiries. */
  source_detail: string | null
  sales_order_id: string | null
  sales_order_number: string | null
  is_editable: boolean
  item_count: number
  items: EnquiryItem[]
  /** All amounts are before tax. */
  mrp_total: string
  discount_total: string
  total_amount: string
}

export interface EnquiryConversionResult {
  enquiry: Enquiry
  order: OrderDetail
}

/* -------------------------------------------------------------------------- */
/* Suppliers, purchasing and fulfilment                                        */
/* -------------------------------------------------------------------------- */

export type PurchaseOrderStatus =
  | 'DRAFT'
  | 'ORDERED'
  | 'PARTIALLY_RECEIVED'
  | 'RECEIVED'
  | 'CANCELLED'

export interface Supplier {
  id: string
  code: string
  name: string
  contact_person: string | null
  phone: string | null
  email: string | null
  address: string | null
  notes: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

/** A supplier in a listing, with what is still due from them. */
export interface SupplierListRow extends Supplier {
  po_count: number
  open_po_count: number
  on_order_quantity: string
  on_order_value: string
  last_po_at: string | null
}

export interface SupplierPurchaseOrderRow {
  id: string
  po_number: string
  status: PurchaseOrderStatus
  created_at: string
  expected_delivery_date: string | null
  line_count: number
  total_ordered: string
  total_received: string
  total_cost: string
}

export interface SupplierReceiptRow {
  id: string
  receipt_number: string
  created_at: string
  purchase_order_id: string
  po_number: string
  delivery_note_reference: string | null
  line_count: number
  total_quantity: string
  total_cost: string
}

export interface SupplierDetail extends Supplier {
  purchase_orders: SupplierPurchaseOrderRow[]
  goods_receipts: SupplierReceiptRow[]
}

export interface PurchaseOrderItem {
  id: string
  product_id: string
  product: { id: string; sku: string; name: string; unit_of_measure: string }
  line_number: number
  quantity_ordered: string
  quantity_received: string
  quantity_remaining: string
  unit_cost: string
  line_cost: string
  notes: string | null
  /** Of what is still to arrive, how much already covers waiting customers. */
  quantity_assigned: string
  /** Still to arrive and promised to nobody. */
  quantity_free: string
  /** How much of the free quantity must still go to customers who are short. */
  settle_required: string
}

export interface PurchaseOrder {
  id: string
  po_number: string
  supplier_id: string
  supplier: { id: string; code: string; name: string }
  status: PurchaseOrderStatus
  expected_delivery_date: string | null
  ordered_at: string | null
  cancelled_at: string | null
  cancellation_reason: string | null
  notes: string | null
  created_at: string
  updated_at: string
  is_editable: boolean
  can_receive: boolean
  item_count: number
  items: PurchaseOrderItem[]
  total_ordered: string
  total_received: string
  total_remaining: string
  total_cost: string
  receipts: {
    id: string
    receipt_number: string
    created_at: string
    delivery_note_reference: string | null
    total_quantity: string
  }[]
}

export interface ReceiptPreviewAllocation {
  order_item_id: string
  order_id: string
  order_number: string
  order_created_at: string
  customer_id: string
  customer_name: string
  quantity_ordered: string
  quantity_delivered: string
  quantity_reserved: string
  quantity_outstanding: string
  quantity_unallocated: string
  /** Covered by a confirmed purchase order whose goods have not arrived. */
  quantity_incoming: string
  /** The most this line can take from the receipt. */
  quantity_eligible: string
  proposed_allocation: string
}

export interface ReceiptPreviewLine {
  purchase_order_item_id: string
  product_id: string
  product_sku: string
  product_name: string
  unit_of_measure: string
  quantity_ordered: string
  quantity_already_received: string
  quantity_remaining: string
  quantity_receiving: string
  is_over_receipt: boolean
  unit_cost: string
  line_cost: string
  eligible_demand: string
  required_allocation: string
  surplus_quantity: string
  physical_stock: string
  reserved_stock: string
  available_stock: string
  physical_stock_after: string
  reserved_stock_after: string
  available_stock_after: string
  pending_quantity: string
  stock: string
  stock_after: string
  allocations: ReceiptPreviewAllocation[]
}

export interface ReceiptPreview {
  purchase_order_id: string
  po_number: string
  supplier_id: string
  supplier_name: string
  status: PurchaseOrderStatus
  lines: ReceiptPreviewLine[]
  total_receiving: string
  total_required_allocation: string
  total_surplus: string
  total_cost: string
}

export interface GoodsReceiptResultLine {
  goods_receipt_item_id: string
  purchase_order_item_id: string
  product_id: string
  product_sku: string
  product_name: string
  unit_of_measure: string
  quantity_received: string
  unit_cost: string
  total_cost: string
  is_over_receipt: boolean
  over_receipt_reason: string | null
  quantity_allocated: string
  surplus_quantity: string
  quantity_ordered_on_po: string
  quantity_received_on_po: string
  quantity_remaining_on_po: string
  physical_stock_after: string
  reserved_stock_after: string
  available_stock_after: string
  net_stock_position_after: string
  stock_after: string
  allocations: {
    order_item_id: string
    order_id: string
    order_number: string
    customer_id: string
    customer_name: string
    quantity_allocated: string
    quantity_outstanding: string
    quantity_reserved: string
  }[]
}

export interface GoodsReceiptResult {
  receipt_id: string
  receipt_number: string
  created_at: string
  purchase_order_id: string
  po_number: string
  po_status: PurchaseOrderStatus
  supplier_id: string
  supplier_name: string
  delivery_note_reference: string | null
  notes: string | null
  lines: GoodsReceiptResultLine[]
  total_received: string
  total_allocated: string
  total_surplus: string
  total_cost: string
}

export interface GoodsReceiptRow {
  id: string
  receipt_number: string
  created_at: string
  purchase_order_id: string
  po_number: string
  supplier_id: string
  supplier_name: string
  delivery_note_reference: string | null
  notes: string | null
  line_count: number
  total_quantity: string
  total_cost: string
  lines: {
    product_id: string
    product_sku: string
    product_name: string
    unit_of_measure: string
    quantity: string
    unit_cost: string
    is_over_receipt: boolean
  }[]
}

export interface ReservationRow {
  reservation_id: string
  quantity: string
  quantity_released: string
  quantity_open: string
  source: AllocationSource
  stock_receipt_id: string | null
  goods_receipt_item_id: string | null
  created_at: string
}

export interface FulfilmentLine {
  order_item_id: string
  product_id: string
  product_sku: string
  product_name: string
  unit_of_measure: string
  line_number: number
  quantity_ordered: string
  quantity_delivered: string
  quantity_reserved: string
  quantity_cancelled: string
  quantity_outstanding: string
  quantity_unallocated: string
  /** Covered by a confirmed purchase order whose goods have not arrived. */
  quantity_incoming: string
  quantity_deliverable: string
  physical_stock: string
  reserved_stock: string
  available_stock: string
  unit_price_net: string
  reservations: ReservationRow[]
}

export interface OrderFulfilment {
  order_id: string
  order_number: string
  customer_id: string
  customer_name: string
  status: OrderStatus
  created_at: string
  can_deliver: boolean
  lines: FulfilmentLine[]
  total_outstanding: string
  total_deliverable: string
  deliveries: {
    id: string
    delivery_number: string
    reference: string | null
    created_at: string
    lines: { product_sku: string; product_name: string; quantity: string }[]
  }[]
}

export interface DeliveryResult {
  delivery_id: string
  delivery_number: string
  created_at: string
  reference: string | null
  notes: string | null
  order_id: string
  order_number: string
  order_status: OrderStatus
  customer_id: string
  customer_name: string
  lines: {
    order_item_id: string
    product_id: string
    product_sku: string
    product_name: string
    unit_of_measure: string
    quantity_delivered_now: string
    quantity_delivered_total: string
    quantity_outstanding: string
    quantity_reserved: string
    physical_stock_after: string
    available_stock_after: string
  }[]
  total_delivered: string
  order_outstanding_after: string
}

export interface DeliveryRow {
  id: string
  delivery_number: string
  created_at: string
  reference: string | null
  notes: string | null
  order_id: string
  order_number: string
  customer_id: string
  customer_name: string
  line_count: number
  total_quantity: string
  lines: {
    product_id: string
    product_sku: string
    product_name: string
    unit_of_measure: string
    quantity: string
  }[]
}

export type FulfilmentStatus =
  | 'AWAITING_STOCK'
  | 'ON_ORDER'
  | 'RESERVED'
  | 'READY_TO_DELIVER'
  | 'PARTIALLY_DELIVERED'

export interface CommitmentRow {
  order_item_id: string
  order_id: string
  order_number: string
  order_created_at: string
  order_status: OrderStatus
  customer_id: string
  customer_name: string
  product_id: string
  product_sku: string
  product_name: string
  unit_of_measure: string
  quantity_ordered: string
  quantity_delivered: string
  quantity_reserved: string
  quantity_cancelled: string
  quantity_unallocated: string
  /** Covered by a confirmed purchase order whose goods have not arrived. */
  quantity_incoming: string
  quantity_outstanding: string
  quantity_deliverable: string
  physical_stock: string
  reserved_stock: string
  available_stock: string
  fulfilment_status: FulfilmentStatus
  outstanding_value: string
  /** The purchase orders covering what is on order, and how much each. */
  incoming_sources: IncomingSource[]
  /** Who this product was last bought from, to suggest when buying more. */
  last_supplier_id: string | null
}

export interface IncomingSource {
  purchase_order_id: string
  purchase_order_item_id: string
  po_number: string
  supplier_name: string
  quantity: string
}

export interface PendingCommitments {
  rows: CommitmentRow[]
  customers: {
    customer_id: string
    customer_name: string
    order_count: number
    line_count: number
    quantity_outstanding: string
    quantity_reserved: string
    quantity_unallocated: string
    /** Covered by a confirmed purchase order whose goods have not arrived. */
    quantity_incoming: string
    outstanding_value: string
    oldest_order_at: string
  }[]
  totals: {
    line_count: number
    customer_count: number
    quantity_outstanding: string
    quantity_reserved: string
    quantity_unallocated: string
    /** Covered by a confirmed purchase order whose goods have not arrived. */
    quantity_incoming: string
    quantity_deliverable: string
    outstanding_value: string
  }
}

/* ---------------------------------------------------------------- integrations */

export type IntegrationName = 'ai' | 'whatsapp' | 'email'

export interface IntegrationCredential {
  /** Whether it is saved. The value itself is never sent to the browser. */
  set: boolean
  /** The last four characters, to tell keys apart. */
  hint: string | null
}

export interface Integration {
  name: IntegrationName
  enabled: boolean
  config: Record<string, string | number | null>
  credentials: Record<string, IntegrationCredential>
  updated_at: string | null
}

export interface AiModel {
  id: string
  label: string
  hint: string
}

export interface Integrations {
  ai: Integration
  whatsapp: Integration
  email: Integration
  models: AiModel[]
}

export type InboundStatus = 'pending' | 'enquiry_created' | 'not_enquiry' | 'no_match' | 'failed' | 'skipped'

export interface InboundMessage {
  id: string
  channel: 'whatsapp' | 'email'
  sender: string
  sender_name: string | null
  subject: string | null
  body: string
  received_at: string
  status: InboundStatus
  enquiry_id: string | null
  enquiry_number: string | null
  summary: string | null
  error: string | null
  processed_at: string | null
}
