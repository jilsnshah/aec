import { http, request } from './client'

/** Transporters (trucking companies, fleet owners, brokers, tempos, couriers),
 *  their vehicles and rate cards, trips, what we owe them and vehicle bookings. */

export type TransporterKind = 'company' | 'fleet_owner' | 'broker' | 'tempo' | 'courier' | 'own_fleet'
export type BookingChannel = 'whatsapp' | 'call' | 'either'
export type VehicleType = 'tempo' | 'pickup' | 'lcv' | '6_wheeler' | '10_wheeler' | '12_wheeler' | '14_wheeler' | 'trailer' | 'tractor' | 'container' | 'other'
export type RateBasis = 'trip' | 'km' | 'tonne' | 'quintal' | 'kg' | 'unit' | 'hour'
export type BookingStatus = 'draft' | 'requested' | 'confirmed' | 'declined' | 'done' | 'cancelled'
export type ReferenceType = 'sales_order' | 'purchase_order' | 'stock_transfer'

export interface TransporterMeta {
  kinds: Record<string, string>
  vehicles: Record<string, string>
  bases: Record<string, string>
}

export interface Transporter {
  id: string
  code: string
  name: string
  kind: TransporterKind
  kind_label: string
  contact_person: string | null
  phone: string | null
  email: string | null
  address: string | null
  gstin: string | null
  pan: string | null
  tally_ledger_name: string | null
  service_areas: string | null
  payment_terms_days: number | null
  booking_channel: BookingChannel | null
  rating: number | null
  notes: string | null
  is_active: boolean
  vehicle_count: number
  rate_count: number
  vehicle_types: string[]
  /** What we owe them. */
  balance: number
  trips: number
}

export interface Vehicle {
  id: string
  number: string
  vehicle_type: string
  vehicle_label: string
  capacity_kg: number | string | null
  driver_name: string | null
  driver_phone: string | null
  is_active: boolean
  notes: string | null
}

export interface RateLine {
  id: string
  from_place: string | null
  to_place: string | null
  vehicle_type: string | null
  vehicle_label: string | null
  basis: RateBasis
  basis_label: string
  rate: number | string
  min_charge: number | string | null
  loading_included: boolean
  valid_from: string | null
  valid_until: string | null
  notes: string | null
  is_active: boolean
}

export interface Trip {
  transporter_id: string
  date: string
  kind: 'delivery' | 'receipt' | 'transfer' | 'booking'
  number: string
  id: string
  vehicle: string | null
  lr_number: string | null
  amount: number | string | null
  charge?: string | null
}

export interface TransporterStatementSummary {
  billed: number
  paid: number
  balance: number
  overdue: number
  payment_terms_days: number | null
}

export interface Booking {
  id: string
  number: string
  status: BookingStatus
  transporter_id: string | null
  transporter: string | null
  purpose: string | null
  reference_type: ReferenceType | null
  reference_id: string | null
  reference_number: string | null
  from_place: string | null
  to_place: string | null
  needed_at: string | null
  vehicle_type: string | null
  vehicle_label: string | null
  load: string | null
  weight_kg: number | string | null
  estimate: number | string | null
  agreed_amount: number | string | null
  vehicle_number: string | null
  driver_phone: string | null
  requested_by: 'person' | 'system' | 'tai' | 'pai' | null
  channel: string | null
  reply: string | null
  notes: string | null
  created_at: string
  confirmed_at: string | null
}

/** Everything about one transporter. `trips` is the list here (a count in the list). */
export interface TransporterFull extends Omit<Transporter, 'trips'> {
  vehicles: Vehicle[]
  rates: RateLine[]
  trips: Trip[]
  statement: TransporterStatementSummary
  bookings: Booking[]
  profile: unknown
}

export interface StatementEntry {
  date: string
  kind: string
  number: string | null
  id: string | null
  debit: number | string
  credit: number | string
  balance: number | string
  detail: string | null
}

export interface VehicleIn {
  number?: string
  vehicle_type?: string
  capacity_kg?: string | null
  driver_name?: string | null
  driver_phone?: string | null
  notes?: string | null
  is_active?: boolean
}
export interface RateIn {
  from_place?: string | null
  to_place?: string | null
  vehicle_type?: string | null
  basis?: string
  rate?: string
  min_charge?: string | null
  loading_included?: boolean
  valid_from?: string | null
  valid_until?: string | null
  notes?: string | null
  is_active?: boolean
}
export interface TransporterIn {
  name?: string
  code?: string | null
  kind?: string
  contact_person?: string | null
  phone?: string | null
  email?: string | null
  address?: string | null
  gstin?: string | null
  pan?: string | null
  tally_ledger_name?: string | null
  service_areas?: string | null
  payment_terms_days?: number | null
  booking_channel?: string | null
  rating?: number | null
  notes?: string | null
  is_active?: boolean
  vehicles?: VehicleIn[]
  rates?: RateIn[]
}

export interface EstimateRow {
  transporter_id: string
  transporter: string
  rate_id: string
  route: string
  vehicle_type: string | null
  vehicle_label: string | null
  basis: string
  rate: number | string
  amount: number | string | null
  note: string | null
  loading_included: boolean
  match: string | null
  rating: number | null
}
export interface EstimateQuery {
  from_place?: string
  to_place?: string
  vehicle_type?: string
  weight_kg?: string
  units?: string
  km?: string
  hours?: string
  transporter_id?: string
}

export interface BookingIn {
  transporter_id?: string | null
  reference_type?: string | null
  reference_id?: string | null
  purpose?: string | null
  from_place?: string | null
  to_place?: string | null
  needed_at?: string | null
  vehicle_type?: string | null
  load?: string | null
  weight_kg?: string | null
  agreed_amount?: string | null
  vehicle_number?: string | null
  driver_phone?: string | null
  notes?: string | null
  status?: BookingStatus
}

export interface TransporterPaymentIn {
  amount: string
  transporter_id: string
  method: 'cash' | 'bank' | 'upi' | 'cheque' | 'card' | 'other'
  reference?: string | null
  notes?: string | null
  paid_on?: string | null
}

const base = '/api/transporters'

export const transporters = {
  meta: () => http.get<TransporterMeta>(`${base}/meta`),
  list: (params: { search?: string; include_inactive?: boolean; kind?: string } = {}) => http.get<{ items: Transporter[] }>(base, params),
  get: (id: string) => http.get<TransporterFull>(`${base}/${id}`),
  create: (body: TransporterIn) => http.post<TransporterFull>(base, body),
  update: ({ id, ...body }: TransporterIn & { id: string }) => http.patch<TransporterFull>(`${base}/${id}`, body),
  statement: (id: string) => http.get<{ summary: TransporterStatementSummary; entries: StatementEntry[] }>(`${base}/${id}/statement`),
  addVehicle: ({ id, ...body }: VehicleIn & { id: string }) => http.post<TransporterFull>(`${base}/${id}/vehicles`, body),
  updateVehicle: ({ id, vehicleId, ...body }: VehicleIn & { id: string; vehicleId: string }) => http.patch<TransporterFull>(`${base}/${id}/vehicles/${vehicleId}`, body),
  removeVehicle: ({ id, vehicleId }: { id: string; vehicleId: string }) => request<TransporterFull>('DELETE', `${base}/${id}/vehicles/${vehicleId}`),
  addRate: ({ id, ...body }: RateIn & { id: string }) => http.post<TransporterFull>(`${base}/${id}/rates`, body),
  updateRate: ({ id, rateId, ...body }: RateIn & { id: string; rateId: string }) => http.patch<TransporterFull>(`${base}/${id}/rates/${rateId}`, body),
  removeRate: ({ id, rateId }: { id: string; rateId: string }) => request<TransporterFull>('DELETE', `${base}/${id}/rates/${rateId}`),
  estimate: (params: EstimateQuery) => http.get<{ items: EstimateRow[] }>(`${base}/estimate`, { ...params }),
  bookings: (params: { status?: string; reference_id?: string } = {}) => http.get<{ items: Booking[] }>('/api/transport-bookings', params),
  createBooking: (body: BookingIn) => http.post<Booking>('/api/transport-bookings', body),
  updateBooking: ({ id, ...body }: BookingIn & { id: string }) => http.patch<Booking>(`/api/transport-bookings/${id}`, body),
  pay: (body: TransporterPaymentIn) => http.post<unknown>('/api/payments', { direction: 'out', ...body }),
}

/** Fallback labels, used until /meta has loaded. */
export const KIND_LABEL: Record<TransporterKind, string> = {
  company: 'Transport company',
  fleet_owner: 'Fleet owner',
  broker: 'Broker',
  tempo: 'Tempo',
  courier: 'Courier',
  own_fleet: 'Own fleet',
}
export const VEHICLE_LABEL: Record<VehicleType, string> = {
  tempo: 'Tempo',
  pickup: 'Pickup',
  lcv: 'LCV',
  '6_wheeler': '6 wheeler',
  '10_wheeler': '10 wheeler',
  '12_wheeler': '12 wheeler',
  '14_wheeler': '14 wheeler',
  trailer: 'Trailer',
  tractor: 'Tractor',
  container: 'Container',
  other: 'Other',
}
export const BASIS_LABEL: Record<RateBasis, string> = {
  trip: 'Per trip',
  km: 'Per km',
  tonne: 'Per tonne',
  quintal: 'Per quintal',
  kg: 'Per kg',
  unit: 'Per unit',
  hour: 'Per hour',
}
