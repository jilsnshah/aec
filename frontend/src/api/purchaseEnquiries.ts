import { http, request } from './client'

/** Purchase enquiries: what we want to buy, the suppliers asked, their offers,
 *  and the offer that became the purchase order. */

export type EnquiryStatus = 'draft' | 'open' | 'to_choose' | 'ordered' | 'decided' | 'cancelled'

export interface PurchaseOffer {
  id: string
  supplier_id: string
  supplier: string
  phone: string | null
  status: 'to_ask' | 'asked' | 'calling' | 'replied' | 'declined' | 'no_reply'
  channel: string | null
  source: string | null
  asked_at: string | null
  replied_at: string | null
  reply: string | null
  delivery_days: number | null
  freight: number | null
  gst_included: boolean | null
  score: number | null
  call_attempts: number
  prices: Record<string, number>
  available: Record<string, number>
  total: number
}

export interface PurchaseEnquiry {
  id: string
  number: string
  status: EnquiryStatus
  reason: string
  notes: string | null
  decision: string | null
  reply_by: string | null
  created_at: string
  created_by: string
  chosen_quote_id: string | null
  orders: { id: string; po_number: string; supplier: string; status: string; total: number }[]
  lines: { id: string; product_id: string; product: string; unit: string; quantity: number; why: string | null; last_paid: number | null }[]
  quotes: PurchaseOffer[]
}

const base = '/api/purchase-enquiries'

export const purchaseEnquiries = {
  list: (query: { status?: string } = {}) => http.get<{ items: PurchaseEnquiry[] }>(base, query),
  get: (id: string) => http.get<PurchaseEnquiry>(`${base}/${id}`),
  create: (body: { lines: { product_id: string; quantity: string }[]; supplier_ids: string[]; notes?: string; send: boolean }) =>
    http.post<PurchaseEnquiry>(base, body),
  send: (id: string) => http.post<PurchaseEnquiry>(`${base}/${id}/send`),
  addSupplier: ({ id, supplier_id }: { id: string; supplier_id: string }) => http.post<PurchaseEnquiry>(`${base}/${id}/suppliers`, { supplier_id }),
  removeSupplier: ({ id, supplier_id }: { id: string; supplier_id: string }) => request<PurchaseEnquiry>('DELETE', `${base}/${id}/suppliers/${supplier_id}`),
  recordOffer: ({ id, ...body }: { id: string; supplier_id: string; prices: Record<string, string>; delivery_days?: number | null; note?: string }) =>
    http.post<PurchaseEnquiry>(`${base}/${id}/offers`, body),
  compare: (id: string) => http.post<PurchaseEnquiry>(`${base}/${id}/compare`),
  order: ({ id, supplier_id }: { id: string; supplier_id?: string | null }) => http.post<PurchaseEnquiry>(`${base}/${id}/order`, { supplier_id: supplier_id ?? null }),
  cancel: (id: string) => http.post<PurchaseEnquiry>(`${base}/${id}/cancel`),
}
