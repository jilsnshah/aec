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
  cash_received?: number
  cash_paid?: number
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
  target: Partial<Record<'booked' | 'revenue', { target: number; actual: number; percent: number | null; projected: number; days_elapsed: number; days_in_month: number }>> | null
}

export type StockFlag = 'short' | 'dead' | 'slow' | 'low_cover' | 'reorder' | 'below_minimum' | 'rising_demand' | 'falling_demand'
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
  category: string | null
  reorder_level: number
  reorder_point: number
  lead_time_days: number
  lead_time_source: 'product' | 'supplier' | 'assumed'
  order_by: string | null
  preferred_supplier_id: string | null
  preferred_supplier_name: string | null
  unit_cost: number
  sold_prev_30_days: number
  demand_trend: 'rising' | 'falling' | 'steady' | 'insufficient_data'
  demand_change_percent: number | null
  turnover_per_year: number | null
  holding_days: number | null
  days_to_clear: number | null
  open_enquiry_quantity: number
  sales_at_risk_value: number
  liquidation_priority: number
  action: { code: 'buy' | 'plan' | 'liquidate' | 'do_not_reorder' | 'watch' | 'ok'; text: string }
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
    sales_at_risk_value: number
    turnover_per_year: number | null
    categories: { category: string; products: number; stock_value: number; aged_90_value: number; capital_at_risk: number; reorder_value: number; short_products: number }[]
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
  priorities: { enquiry_id: string; enquiry_number: string; customer_id: string; customer_name: string; phone: string | null; value: number; age_days: number; days_idle: number; in_stock: boolean; score: number; reasons: string[]; has_open_follow_up: boolean }[]
  priority_note: string
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

export type Measure = 'booked_value' | 'quantity_booked' | 'orders' | 'discount' | 'revenue' | 'quantity_delivered' | 'cost_of_goods' | 'gross_profit'
export type ExploreGroup = 'product' | 'category' | 'customer' | 'month' | 'week' | 'weekday' | 'day' | 'none'
export interface ExploreRow {
  key: string
  label: string
  link: string | null
  value: number
  previous: number | null
  change_percent: number | null
  share_percent: number | null
  cumulative_percent?: number | null
  booked_value: number
  quantity_booked: number
  orders: number
  discount: number
  revenue: number
  quantity_delivered: number
  cost_of_goods: number
  gross_profit: number
  margin_percent: number | null
}
export interface Explore {
  measure: Measure
  measure_label: string
  group_by: ExploreGroup
  start: string
  end: string
  previous_start: string
  previous_end: string
  total: number
  total_previous: number
  change_percent: number | null
  rows: ExploreRow[]
  row_count: number
}
export interface ExploreQuery {
  measure: Measure
  group_by: ExploreGroup
  period: Period
  start?: string
  end?: string
  categories?: string
  product_ids?: string
  customer_ids?: string
}
export interface Heatmap {
  measure: Measure
  weekdays: string[]
  weeks: { week: string; values: number[] }[]
  by_weekday: number[]
  busiest_weekday: string | null
}
export interface ProductIntel {
  product_id: string
  name: string
  booked_value: number
  previous_booked_value: number | null
  growth_percent: number | null
  growth: 'growing' | 'declining' | 'steady' | 'new' | 'none'
  revenue: number
  gross_profit: number
  margin_percent: number | null
  discount: number
  share_percent: number | null
  abc_class: 'A' | 'B' | 'C'
  quadrant: 'star' | 'volume_low_margin' | 'niche_high_margin' | 'weak' | null
  enquiries: number
  enquiries_won: number
  enquiries_lost: number
  enquiry_conversion_percent: number | null
  stock_flags: StockFlag[]
  short: number
  category: string | null
}
export interface ProductIntelligence {
  start: string
  end: string
  median_revenue: number
  median_margin_percent: number | null
  products: ProductIntel[]
  weak_enquiry_conversion: ProductIntel[]
  bought_together: { a: string; a_id: string; b: string; b_id: string; orders: number }[] | null
  bought_together_note: string | null
}
export type Segment = 'champion' | 'loyal' | 'at_risk' | 'dormant' | 'new' | 'occasional'
export interface Segments {
  segments: Partial<Record<Segment, number>>
  customers: (CustomerValue & { segment: Segment; average_days_between_orders: number | null; estimated_annual_value: number | null; open_receivable: number; overdue_receivable: number; over_credit_limit: boolean })[]
  new_vs_returning: { month: string; new: number; returning: number }[]
  repeat_rate_percent: number | null
  note: string
}

export const insights = {
  explore: (query: ExploreQuery) => http.get<Explore>('/api/insights/explore', { ...query } as Record<string, string>),
  heatmap: (measure: Measure = 'booked_value', weeks = 12) => http.get<Heatmap>('/api/insights/heatmap', { measure, weeks }),
  products: (period: Period = 'last_90') => http.get<ProductIntelligence>('/api/insights/products', { period }),
  segments: () => http.get<Segments>('/api/insights/segments'),
  overview: (period: Period = 'month') => http.get<Overview>('/api/insights/overview', { period }),
  inventory: () => http.get<InventoryHealth>('/api/insights/inventory'),
  sales: (group_by: string, period: Period) => http.get<SalesBreakdown>('/api/insights/sales', { group_by, period }),
  enquiries: () => http.get<EnquiryFunnel>('/api/insights/enquiries'),
  customers: () => http.get<CustomerInsights>('/api/insights/customers'),
  suppliers: () => http.get<SupplierInsights>('/api/insights/suppliers'),
  alerts: () => http.get<Alerts>('/api/insights/alerts'),
}
