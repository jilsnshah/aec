import { http, request as raw } from './client'

const request = (method: string, path: string) => raw<ProductNames>(method, path)

/** Customers and suppliers as full parties: contacts, phone numbers and emails,
 *  addresses and delivery sites; duplicates and merging; product names and units. */

export type PartyKind = 'customer' | 'supplier'
export interface PartyContact {
  id: string
  name: string
  role: string | null
  is_primary: boolean
  is_active: boolean
  notes: string | null
}
export interface ContactPoint {
  id: string
  kind: 'phone' | 'email'
  value: string
  label: string | null
  contact_id: string | null
  is_whatsapp: boolean
  is_primary: boolean
  is_active: boolean
}
export interface PartyAddress {
  id: string
  kind: 'billing' | 'site' | 'office' | 'warehouse'
  label: string | null
  line: string
  city: string | null
  state: string | null
  pincode: string | null
  map_url: string | null
  contact_id: string | null
  is_default: boolean
  is_active: boolean
}
export interface PartyProfile {
  kind: PartyKind
  id: string
  name: string
  gstin: string | null
  pan: string | null
  tally_ledger_name: string | null
  contacts: PartyContact[]
  points: ContactPoint[]
  addresses: PartyAddress[]
}
export interface DuplicateHit {
  kind: PartyKind
  id: string
  name: string
  reason: string
  active?: boolean
}
export interface ProductNames {
  product_id: string
  base_unit: string
  aliases: { id: string; kind: 'alias' | 'barcode' | 'supplier_code'; value: string; supplier_id: string | null; supplier_name: string | null }[]
  units: { id: string; name: string; factor: number; for_sales: boolean; for_purchase: boolean }[]
  sales_unit: string | null
  purchase_unit: string | null
  whole_units: boolean
}

const base = (kind: PartyKind, id: string) => `/api/parties/${kind}/${id}`

export const parties = {
  profile: (kind: PartyKind, id: string) => http.get<PartyProfile>(`${base(kind, id)}/profile`),
  addContact: (kind: PartyKind, id: string, body: Partial<PartyContact>) => http.post<PartyContact>(`${base(kind, id)}/contacts`, body),
  updateContact: (kind: PartyKind, id: string, contactId: string, body: Partial<PartyContact>) => http.patch<PartyContact>(`${base(kind, id)}/contacts/${contactId}`, body),
  addPoint: (kind: PartyKind, id: string, body: Partial<ContactPoint>) => http.post<ContactPoint>(`${base(kind, id)}/points`, body),
  updatePoint: (kind: PartyKind, id: string, pointId: string, body: Partial<ContactPoint>) => http.patch<ContactPoint>(`${base(kind, id)}/points/${pointId}`, body),
  addAddress: (kind: PartyKind, id: string, body: Partial<PartyAddress>) => http.post<PartyAddress>(`${base(kind, id)}/addresses`, body),
  updateAddress: (kind: PartyKind, id: string, addressId: string, body: Partial<PartyAddress>) => http.patch<PartyAddress>(`${base(kind, id)}/addresses/${addressId}`, body),
  duplicates: (kind: PartyKind, query: { name?: string; phone?: string; email?: string; gstin?: string; exclude_id?: string }) =>
    http.get<{ blocking: DuplicateHit[]; similar: DuplicateHit[] }>(`/api/parties/${kind}/duplicates`, query),
  merge: (kind: PartyKind, id: string, mergeId: string) => http.post<{ moved: Record<string, number> }>(`${base(kind, id)}/merge`, { merge_id: mergeId }),
  productNames: (id: string) => http.get<ProductNames>(`/api/products/${id}/names`),
  addAlias: (id: string, body: { kind: string; value: string; supplier_id?: string | null }) => http.post<ProductNames>(`/api/products/${id}/aliases`, body),
  removeAlias: (id: string, aliasId: string) => request('DELETE', `/api/products/${id}/aliases/${aliasId}`),
  addUnit: (id: string, body: { name: string; factor: string; for_sales?: boolean; for_purchase?: boolean }) => http.post<ProductNames>(`/api/products/${id}/units`, body),
  updateUnit: (id: string, unitId: string, body: { name: string; factor: string; for_sales: boolean; for_purchase: boolean }) => http.put<ProductNames>(`/api/products/${id}/units/${unitId}`, body),
  removeUnit: (id: string, unitId: string) => request('DELETE', `/api/products/${id}/units/${unitId}`),
}
