import { http } from './client'
import type { PriceListItemRow } from './records'

/** Customer groups (by hand and by rules) and a customer's own pricing. */

export interface RuleField {
  key: string
  label: string
  unit?: string
  type: 'number' | 'money' | 'choice' | 'text'
  choices?: string[]
}
export interface Rule {
  field: string
  op: string
  value: string | number
}
export interface Group {
  id: string
  name: string
  description: string | null
  rules: Rule[]
  match: 'all' | 'any'
  price_list_id: string | null
  price_list_name: string | null
  price_list_discount: number | null
  discount_percent: number | null
  price_count: number
  items?: PriceListItemRow[]
  is_active: boolean
  member_count: number
  last_computed_at: string | null
  members?: { customer_id: string; name: string; source: 'rule' | 'manual' | 'excluded'; added_at: string }[]
}
export interface GroupIn {
  name?: string
  description?: string | null
  rules?: Rule[]
  match?: 'all' | 'any'
  discount_percent?: string | null
  items?: { product_id: string; min_quantity: string; price: string | null; discount_percent: string | null }[]
  is_active?: boolean
}
export interface PreviewRow {
  customer_id: string
  name: string
  orders_12m: number
  spend_12m: number
  years_with_us: number
  days_since_last_order: number | null
  overdue: number
  segment: string
}
export interface CustomerPricing {
  customer_id: string
  discount_percent: number | null
  price_list: { id: string; name: string; discount_percent: number } | null
  own_items: PriceListItemRow[]
  groups: Membership[]
  kept_out: Membership[]
}
export interface Membership {
  id: string
  name: string
  price_list_id: string | null
  price_list_name: string | null
  source: 'rule' | 'manual' | 'excluded'
  is_active: boolean
}

export const groups = {
  fields: () => http.get<{ fields: RuleField[]; ops: string[] }>('/api/customer-groups/fields'),
  list: () => http.get<{ items: Group[] }>('/api/customer-groups'),
  get: (id: string) => http.get<Group>(`/api/customer-groups/${id}`),
  create: (body: GroupIn) => http.post<Group>('/api/customer-groups', body),
  update: ({ id, ...body }: GroupIn & { id: string }) => http.put<Group>(`/api/customer-groups/${id}`, body),
  remove: (id: string) => fetch(`/api/customer-groups/${id}`, { method: 'DELETE', credentials: 'include' }),
  preview: (body: { rules: Rule[]; match: string }) => http.post<{ count: number; of: number; customers: PreviewRow[] }>('/api/customer-groups/preview', body),
  recalculate: () => http.post<{ groups: number }>('/api/customer-groups/recalculate'),
  setMember: ({ id, customerId, source }: { id: string; customerId: string; source: 'manual' | 'excluded' | null }) =>
    http.put<Group>(`/api/customer-groups/${id}/members/${customerId}`, { source }),
  pricing: (customerId: string) => http.get<CustomerPricing>(`/api/customers/${customerId}/pricing`),
  setPricing: ({ customerId, ...body }: { customerId: string; discount_percent?: string | null; items?: { product_id: string; min_quantity: string; price: string | null; discount_percent: string | null }[] }) =>
    http.put<CustomerPricing>(`/api/customers/${customerId}/pricing`, body),
  applyPrices: (enquiryId: string) => http.post<{ changed: { product: string; from: number; to: number; rule: string | null }[] }>(`/api/enquiries/${enquiryId}/apply-prices`),
}
