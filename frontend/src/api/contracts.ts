import { http } from './client'

/** Rate contracts: an agreed rate for a period with one supplier or one customer. */

export type ContractParty = 'supplier' | 'customer'
export type ContractStatus = 'upcoming' | 'active' | 'expiring' | 'expired' | 'cancelled'

export interface ContractItem {
  id: string
  product_id: string
  product: string
  /** The product's base unit. */
  unit: string
  mrp: number | string | null
  /** Per base unit. */
  rate: number | string | null
  discount_percent: number | string | null
  min_quantity: number | string
  committed_quantity: number | string | null
  used_quantity: number | string
  left_quantity: number | string | null
  used_percent: number | string | null
}
export interface Contract {
  id: string
  number: string
  title: string
  party: ContractParty
  supplier_id: string | null
  customer_id: string | null
  party_name: string
  address_id: string | null
  valid_from: string
  valid_until: string
  reference: string | null
  terms: string | null
  status: ContractStatus
  days_left: number | null
  created_at: string
  items: ContractItem[]
}
export interface ContractItemIn {
  product_id: string
  /** Price per ``unit`` (base unit when omitted). */
  rate?: string | null
  /** Alternative to rate: percent off MRP. */
  discount_percent?: string | null
  unit?: string | null
  min_quantity?: string | null
  committed_quantity?: string | null
}
export interface ContractIn {
  supplier_id?: string | null
  customer_id?: string | null
  title: string
  valid_from: string
  valid_until: string
  reference?: string | null
  terms?: string | null
  address_id?: string | null
  items: ContractItemIn[]
}
export interface ContractRate {
  /** Per base unit. */
  rate: number | string
  contract: string
  valid_until: string
}

export const contracts = {
  list: (params: { party?: ContractParty; party_id?: string } = {}) => http.get<{ items: Contract[] }>('/api/rate-contracts', params),
  get: (id: string) => http.get<Contract>(`/api/rate-contracts/${id}`),
  create: (body: ContractIn) => http.post<Contract>('/api/rate-contracts', body),
  update: ({ id, supplier_id: _s, customer_id: _c, ...body }: ContractIn & { id: string }) => http.patch<Contract>(`/api/rate-contracts/${id}`, body),
  cancel: (id: string) => http.post<Contract>(`/api/rate-contracts/${id}/cancel`),
  supplierRates: (supplier_id: string) => http.get<{ rates: Record<string, ContractRate> }>('/api/rate-contracts/supplier-rates', { supplier_id }),
}
