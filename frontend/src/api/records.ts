import { http } from './client'
import type { Statement } from './finance'

/** Record intelligence from /api/records: timelines, customer 360, prices,
 *  order checks, payment status per order, supplier scorecards and purchase
 *  suggestions. */

export type EventKind = 'order' | 'cancel' | 'enquiry' | 'won' | 'lost' | 'delivery' | 'payment' | 'purchase' | 'receipt' | 'in' | 'out' | 'task' | 'done'
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
