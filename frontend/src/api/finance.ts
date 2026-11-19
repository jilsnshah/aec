import { http } from './client'

/** Money in and out, from /api/payments and /api/finance. */

export type Bucket = 'not_due' | '1-30' | '31-60' | '61-90' | '90+'
export const BUCKETS: { key: Bucket; label: string }[] = [
  { key: 'not_due', label: 'Not yet due' },
  { key: '1-30', label: '1–30 days late' },
  { key: '31-60', label: '31–60 days' },
  { key: '61-90', label: '61–90 days' },
  { key: '90+', label: 'Over 90 days' },
]

export interface AgeingParty {
  party_id: string
  name: string
  payment_terms_days: number
  invoiced: number
  paid: number
  open: number
  advance: number
  overdue: number
  oldest_overdue_days: number
  buckets: Record<Bucket, number>
  credit_limit?: number | null
  over_credit_limit?: boolean
  credit_available?: number | null
}
export interface OverdueDocument {
  document_id: string
  number: string
  date: string
  due_date: string
  order_id: string
  order_number: string
  amount: number
  open: number
  days_overdue: number
  party_id: string
  party_name: string
}
export interface Ageing {
  as_of: string
  totals: { invoiced: number; paid: number; open: number; overdue: number; advances: number; buckets: Record<Bucket, number> }
  parties: AgeingParty[]
  overdue: OverdueDocument[]
}
export interface Payment {
  id: string
  number: string
  direction: 'in' | 'out'
  customer_id: string | null
  supplier_id: string | null
  party_name: string | null
  sales_order_id: string | null
  purchase_order_id: string | null
  amount: string
  paid_on: string
  method: string
  reference: string | null
  notes: string | null
  voided: boolean
  void_reason: string | null
  created_at: string
}
export interface StatementEntry {
  date: string
  kind: 'invoice' | 'bill' | 'payment'
  number: string
  id: string
  order_id: string | null
  order_number: string | null
  debit: number
  credit: number
  balance: number
  due_date?: string
  open?: number
  days_overdue?: number
  method?: string
  reference?: string | null
}
export interface Statement {
  party: 'customer' | 'supplier'
  party_id: string
  name: string
  summary: { invoiced: number; paid: number; balance: number; open: number; overdue: number; advance: number; payment_terms_days: number; credit_limit?: number | null; over_credit_limit?: boolean }
  entries: StatementEntry[]
}
export interface PaymentIn {
  direction: 'in' | 'out'
  amount: string
  paid_on?: string | null
  customer_id?: string | null
  supplier_id?: string | null
  method: string
  reference?: string | null
  notes?: string | null
  sales_order_id?: string | null
  purchase_order_id?: string | null
}

export const finance = {
  receivables: () => http.get<Ageing>('/api/finance/receivables'),
  payables: () => http.get<Ageing>('/api/finance/payables'),
  statement: (party: 'customers' | 'suppliers', id: string) => http.get<Statement>(`/api/finance/${party}/${id}/statement`),
  payments: (query: { direction?: 'in' | 'out'; customer_id?: string; supplier_id?: string; search?: string; include_voided?: boolean; limit?: number } = {}) =>
    http.get<{ items: Payment[]; total: number }>('/api/payments', query),
  record: (body: PaymentIn) => http.post<Payment>('/api/payments', body),
  void: (id: string, reason: string | null) => http.post<Payment>(`/api/payments/${id}/void`, { reason }),
}

export interface Target {
  month: string
  metric: 'booked' | 'revenue'
  amount: string | number
}
export interface SavedView<S = unknown> {
  id: string
  page: string
  name: string
  state: S
  shared: boolean
  mine: boolean
}
export const workspace = {
  targets: () => http.get<Target[]>('/api/targets'),
  setTarget: (body: { month: string; metric: 'booked' | 'revenue'; amount: string }) => http.put<Target>('/api/targets', body),
  preference: <T>(key: string) => http.get<{ key: string; value: T | null }>(`/api/preferences/${key}`),
  setPreference: <T>(key: string, value: T) => http.put<{ key: string; value: T }>(`/api/preferences/${key}`, { value }),
  views: <S>(page: string) => http.get<SavedView<S>[]>('/api/views', { page }),
  saveView: <S>(body: { page: string; name: string; state: S; shared?: boolean }) => http.post<SavedView<S>>('/api/views', body),
  deleteView: (id: string) => fetch(`/api/views/${id}`, { method: 'DELETE', credentials: 'include' }),
}
