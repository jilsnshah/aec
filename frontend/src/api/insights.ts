import { http } from './client'

/** Business intelligence from /api/insights. The backend computes every
 *  figure; these types describe what it sends. */

export type Period = 'today' | 'week' | 'month' | 'quarter' | 'year' | 'last_7' | 'last_30' | 'last_90'

export interface Trading {
  orders: number
  booked_value: number
  average_order_value: number
  deliveries: number
  revenue: number
  cost_of_goods: number
  gross_profit: number
  margin_percent: number | null
  enquiries: number
  enquiries_converted: number
  enquiries_lost: number
  conversion_rate: number | null
  new_customers: number
  purchase_orders_placed: number
  purchase_orders_value: number
  goods_received_value: number
}
export interface Overview {
  period: string
  start: string
  end: string
  previous_start: string
  previous_end: string
  current: Trading
  previous: Trading
  change_percent: Partial<Record<keyof Trading, number | null>>
  daily: { date: string; orders: number; booked: number; revenue: number }[]
}

export type StockFlag = 'short' | 'dead' | 'slow' | 'low_cover' | 'reorder'
export interface ProductHealth {
  product_id: string
  sku: string
  name: string
  unit: string
  physical: number
  reserved: number
  free: number
  on_order: number
  to_deliver: number
  short: number
  stock_figure: number
  stock_value: number
  ages: Record<string, { quantity: number; value: number }>
  oldest_stock_days: number | null
  sold_30_days: number
  sold_90_days: number
  daily_sales_rate: number
  days_of_cover: number | null
  last_sale: string | null
  days_since_last_sale: number | null
  reorder_quantity: number
  reorder_value: number
  flags: StockFlag[]
}
export interface InventoryHealth {
  as_of: string
  thresholds: { dead_stock_days: number; slow_cover_days: number; low_cover_days: number; target_cover_days: number }
  totals: {
    products: number
    stock_value: number
    age_value: Record<string, number>
    dead_stock_value: number
    slow_stock_value: number
    capital_at_risk: number
    short_quantity_products: number
    low_cover_products: number
    reorder_products: number
    reorder_value: number
  }
  products: ProductHealth[]
}

export interface SalesRow {
  name: string
  product_id?: string
  customer_id?: string
  sku?: string
  orders: number
  quantity_booked: number
  booked_value: number
  quantity_delivered: number
  revenue: number
  cost_of_goods: number
  gross_profit: number
  margin_percent: number | null
  share_of_booked_percent: number | null
}
export interface SalesBreakdown {
  group_by: string
  start: string
  end: string
  totals: { booked_value: number; revenue: number; cost_of_goods: number; gross_profit: number }
  items: SalesRow[]
  truncated: boolean
}

export interface StaleEnquiry {
  enquiry_id: string
  enquiry_number: string
  customer_id: string
  customer_name: string
  value: number
  days_idle: number
  age_days: number
  source: string
  has_open_follow_up: boolean
}
export interface EnquiryFunnel {
  counts: { total: number; open: number; converted: number; lost: number }
  conversion_rate: number | null
  open_pipeline_value: number
  average_days_to_convert: number | null
  by_source: { source: string; total: number; open: number; converted: number; lost: number; value_converted: number; conversion_rate: number | null }[]
  lost_reasons: { reason: string; count: number }[]
  stale_days: number
  stale: StaleEnquiry[]
  stale_without_follow_up: number
}

export interface CustomerValue {
  customer_id: string
  name: string
  orders: number
  booked_value: number
  revenue: number
  average_order_value: number
  outstanding_value: number
  open_enquiries: number
  last_order: string
  days_since_last_order: number
  dormant: boolean
  rank: number
  share_percent: number | null
  cumulative_share_percent: number | null
}
export interface CustomerInsights {
  dormant_days: number
  customers: CustomerValue[]
  dormant: CustomerValue[]
  never_ordered: { customer_id: string; name: string; open_enquiries: number }[]
  top_share_percent: number | null
}

export interface SupplierRow {
  supplier_id: string
  name: string
  purchase_orders: number
  ordered_value: number
  received_value: number
  open_orders: number
  still_due_value: number
  average_lead_days: number | null
  fill_rate_percent: number | null
  on_time_percent: number | null
  cancelled: number
}
export interface SupplierInsights {
  suppliers: SupplierRow[]
  late_purchase_orders: { purchase_order_id: string; po_number: string; supplier_id: string; supplier_name: string; expected: string; days_late: number; still_due_value: number }[]
}

export type Severity = 'critical' | 'warning' | 'info'
export interface Alert {
  id: string
  kind: string
  severity: Severity
  title: string
  detail: string
  link: string
  record?: { type: string; id: string }
  suggested_action?: { tool: string; enquiry_id?: string; customer_id?: string }
}
export interface Alerts {
  counts: Partial<Record<Severity, number>>
  alerts: Alert[]
}

export const insights = {
  overview: (period: Period = 'month') => http.get<Overview>('/api/insights/overview', { period }),
  inventory: () => http.get<InventoryHealth>('/api/insights/inventory'),
  sales: (group_by: string, period: Period) => http.get<SalesBreakdown>('/api/insights/sales', { group_by, period }),
  enquiries: () => http.get<EnquiryFunnel>('/api/insights/enquiries'),
  customers: () => http.get<CustomerInsights>('/api/insights/customers'),
  suppliers: () => http.get<SupplierInsights>('/api/insights/suppliers'),
  alerts: () => http.get<Alerts>('/api/insights/alerts'),
}
