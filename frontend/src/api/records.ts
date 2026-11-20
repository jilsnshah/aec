import { http } from './client'
import type { Statement } from './finance'

/** Record intelligence from /api/records: timelines, customer 360, prices,
 *  order checks, payment status per order, supplier scorecards and purchase
 *  suggestions. */

export type EventKind = 'return' | 'order' | 'cancel' | 'enquiry' | 'won' | 'lost' | 'delivery' | 'payment' | 'purchase' | 'receipt' | 'in' | 'out' | 'task' | 'done'
export interface TimelineEvent {
  at: string
  kind: EventKind
  title: string
  detail: string
  link: string | null
  amount: number | null
}

export interface CustomerProfile {
  customer_id: string
  segment: string
  orders: number
  lifetime_booked: number
  lifetime_revenue: number
  average_order_value: number
  average_days_between_orders: number | null
  days_since_last_order: number | null
  estimated_annual_value: number | null
  share_of_sales_percent: number | null
  rank: number | null
  average_discount_percent: number | null
  open_enquiries: number
  enquiry_win_rate_percent: number | null
  account: Statement['summary']
  credit_limit: number | null
  credit_used_percent: number | null
  monthly: { month: string; booked: number; orders: number }[]
  top_products: { product_id: string; name: string; unit: string; quantity: number; value: number; last_ordered: string }[]
}

export interface ProductPrices {
  product_id: string
  mrp: number
  average_cost: number
  last_purchase_price: number
  average_net_price: number | null
  lowest_net_price: number | null
  average_margin_percent: number | null
  sales: { order_id: string; order_number: string; date: string; customer_id: string; customer: string; quantity: number; list_price: number; discount_percent: number; net_price: number }[]
  suppliers: { supplier_id: string; name: string; orders: number; lowest: number; highest: number; average: number; last: number; last_date: string; preferred: boolean }[]
  stock_in_average_cost: number | null
  top_customers: { customer_id: string; name: string; quantity: number; value: number; last: string }[]
}

export interface OrderWarning {
  level: 'critical' | 'warning' | 'info'
  kind: string
  text: string
}
export interface OrderCheck {
  total: number
  warnings: OrderWarning[]
  lines: {
    product_id: string
    name: string
    unit: string
    net_price: number
    cost: number
    margin_percent: number | null
    free_stock: number
    short: number
    last_price_to_customer: { net_price: number; discount_percent: number; date: string } | null
    usual_discount_percent: number | null
  }[]
  credit: { limit: number | null; owed: number; overdue: number; undelivered_orders: number; exposure_after: number } | null
}

export type PayStatus = 'paid' | 'partly_paid' | 'unpaid' | 'overdue'
export interface OrderPayment {
  invoiced: number
  paid: number
  open: number
  days_overdue: number
  status: PayStatus
}

export interface SupplierScorecard {
  supplier_id: string
  score: number | null
  score_note: string
  performance: {
    purchase_orders: number
    ordered_value: number
    received_value: number
    still_due_value: number
    average_lead_days: number | null
    fill_rate_percent: number | null
    on_time_percent: number | null
  } | null
  late_orders: { purchase_order_id: string; po_number: string; expected: string; days_late: number; still_due_value: number }[]
  products: { product_id: string; name: string; unit: string; orders: number; quantity: number; last_ordered: string; last_cost: number | null; cheapest_supplier: string | null; cheapest_cost: number | null; is_cheapest: boolean }[]
}

export interface PurchaseSuggestions {
  total_value: number
  note: string
  groups: {
    supplier_id: string | null
    supplier_name: string | null
    value: number
    urgent: number
    lines: { product_id: string; name: string; unit: string; quantity: number; unit_cost: number; value: number; order_by: string | null; reason: string; short: number }[]
  }[]
}

export type TimelineFor = { customer_id?: string; supplier_id?: string; product_id?: string; order_id?: string }

export const records = {
  timeline: (target: TimelineFor, limit = 60) => http.get<{ events: TimelineEvent[] }>('/api/records/timeline', { ...target, limit }),
  customerProfile: (id: string) => http.get<CustomerProfile>(`/api/records/customers/${id}/profile`),
  productPrices: (id: string, customerId?: string) => http.get<ProductPrices>(`/api/records/products/${id}/prices`, { customer_id: customerId }),
  checkOrder: (body: { customer_id?: string | null; items: { product_id: string; quantity_ordered: number; unit_price?: number | null; discount_percent?: number }[] }) =>
    http.post<OrderCheck>('/api/records/order-check', body),
  orderPayments: () => http.get<Record<string, OrderPayment>>('/api/records/order-payments'),
  supplierScorecard: (id: string) => http.get<SupplierScorecard>(`/api/records/suppliers/${id}/scorecard`),
  purchaseSuggestions: () => http.get<PurchaseSuggestions>('/api/records/purchase-suggestions'),
}

/* ------------------------------------------------------------ stock adjustments */
export interface Adjustment {
  id: string
  number: string
  count_number: string | null
  product_id: string
  product_name: string
  product_sku: string
  unit: string
  reason: string
  reason_label: string
  system_quantity: number
  counted_quantity: number | null
  quantity_change: number
  unit_cost: number
  value_change: number
  released_to_short: number
  note: string | null
  created_at: string
}
export interface CountRow {
  product_id: string
  name: string
  sku: string
  unit: string
  category: string | null
  system_quantity: number
  reserved: number
  average_cost: number
  last_counted: string | null
}
export interface AdjustmentLineIn {
  product_id: string
  counted_quantity?: string
  quantity_change?: string
  reason?: string
  unit_cost?: string
  note?: string
  warehouse_id?: string
}
export interface PostResult {
  count_number: string | null
  checked: number
  adjusted: number
  matched: number
  value_change: number
  released_to_short: number
  adjustments: Adjustment[]
}

export const stock = {
  adjustments: (query: { product_id?: string; reason?: string; count_number?: string; limit?: number } = {}) =>
    http.get<{ items: Adjustment[]; total: number; by_reason: { reason: string; label: string; count: number; value_change: number }[] }>('/api/stock-adjustments', query),
  countSheet: (category?: string, warehouse_id?: string) => http.get<{ products: CountRow[]; reasons: Record<string, string> }>('/api/stock-adjustments/count-sheet', { category, warehouse_id }),
  post: (body: { lines: AdjustmentLineIn[]; as_count?: boolean }) => http.post<PostResult>('/api/stock-adjustments', body),
}

/* ------------------------------------------------------------ sales returns */
export interface ReturnableLine {
  order_item_id: string
  product_id: string
  product_name: string
  unit: string
  delivered: number
  returned: number
  returnable: number
  unit_price_net: number
}
export interface SalesReturn {
  id: string
  number: string
  sales_order_id: string
  order_number: string
  customer_id: string
  customer_name: string
  reason: string
  reason_label: string
  note: string | null
  amount: number
  restocked_cost: number
  created_at: string
  lines: { order_item_id: string; product_id: string; product_name: string; unit: string; quantity: number; unit_price_net: number; amount: number; restock: boolean; unit_cost: number }[]
}
export const returns = {
  returnable: (orderId: string) => http.get<{ lines: ReturnableLine[]; reasons: Record<string, string> }>(`/api/orders/${orderId}/returnable`),
  forOrder: (orderId: string) => http.get<{ items: SalesReturn[] }>(`/api/orders/${orderId}/returns`),
  create: ({ orderId, ...body }: { orderId: string; reason: string; note?: string; lines: { order_item_id: string; quantity: string; restock: boolean }[] }) =>
    http.post<SalesReturn>(`/api/orders/${orderId}/returns`, body),
}

export const controlsApi = {
  check: (body: { customer_id?: string | null; items: { product_id: string; quantity_ordered: number; unit_price?: number | null; discount_percent?: number }[] }) =>
    http.post<{ mode: 'off' | 'warn' | 'block'; holds: { kind: string; text: string }[]; warnings: OrderWarning[] }>('/api/controls/check', body),
  audit: (query: { limit?: number; action?: string; entity_id?: string } = {}) =>
    http.get<{ events: { id: string; at: string; user: string | null; action: string; entity: string; entity_id: string | null; summary: string }[] }>('/api/audit', query),
}

export interface ReminderRow {
  customer_id: string
  name: string
  phone: string | null
  overdue: number
  invoices: number
  oldest_days: number
  level: 1 | 2 | 3
  level_name: string
  last_reminded: string | null
  reminders_sent: number
  message: string
}
export const reminders = {
  due: () => http.get<{ customers: ReminderRow[]; total_overdue: number; levels: { level: number; name: string; from_days: number }[] }>('/api/finance/reminders'),
  sent: ({ id, channel }: { id: string; channel: string }) => http.post<{ logged: boolean }>(`/api/finance/reminders/${id}/sent`, { channel }),
}

/* ------------------------------------------------------------ price lists */
export interface PriceListItemRow {
  id?: string
  product_id: string
  product_name?: string | null
  unit?: string | null
  mrp?: number | null
  min_quantity: number
  price: number | null
  discount_percent: number | null
}
export interface PriceListRow {
  id: string
  name: string
  discount_percent: number
  notes: string | null
  valid_from: string | null
  valid_until: string | null
  is_active: boolean
  customers: number | null
  items: PriceListItemRow[]
}
export interface PriceListIn {
  name: string
  discount_percent: string
  notes?: string | null
  valid_from?: string | null
  valid_until?: string | null
  is_active?: boolean
  items: { product_id: string; min_quantity: string; price: string | null; discount_percent: string | null }[]
}
export const priceLists = {
  list: (includeInactive = true) => http.get<{ items: PriceListRow[] }>('/api/price-lists', { include_inactive: includeInactive }),
  create: (body: PriceListIn) => http.post<PriceListRow>('/api/price-lists', body),
  update: ({ id, ...body }: PriceListIn & { id: string }) => http.put<PriceListRow>(`/api/price-lists/${id}`, body),
  resolve: (body: { customer_id?: string | null; lines: { product_id: string; quantity: string }[] }) =>
    http.post<{ price_list: string | null; price_list_active: boolean; lines: { product_id: string; mrp: number; discount_percent: number; net_price: number; rule: string }[] }>('/api/price-lists/resolve', body),
}
