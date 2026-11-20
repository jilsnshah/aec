import { http } from './client'

/** Warehouses (godowns, yards, shops, site stores) and transfers between them. */

export interface Warehouse {
  id: string
  code: string
  name: string
  kind: 'godown' | 'yard' | 'shop' | 'site' | 'transit'
  kind_label: string
  address: string | null
  contact: string | null
  tally_godown: string | null
  notes: string | null
  is_default: boolean
  is_active: boolean
  products: number
  quantity: number
  value: number
}
export interface WarehouseIn {
  name?: string
  code?: string
  kind?: string
  address?: string | null
  contact?: string | null
  tally_godown?: string | null
  notes?: string | null
  is_default?: boolean
  is_active?: boolean
}
export interface StockRow {
  product_id: string
  product: string
  sku: string
  unit: string
  category: string | null
  warehouse_id: string
  warehouse: string
  warehouse_kind: string | null
  quantity: number
  value: number
  average_cost: number
}
export interface TransferItem {
  id: string
  product_id: string
  product: string
  sku: string
  base_unit: string
  unit: string | null
  unit_name: string
  unit_factor: number
  unit_quantity: number
  quantity: number
  quantity_received: number
  weight_kg: number | null
  available: number | null
  goods_value: number
  extra_cost: number
  unit_cost_before: number | null
  unit_cost_after: number | null
}
export interface TransferCost {
  id?: string
  kind: string
  label?: string
  amount: number | string
  paid_to: string | null
  note?: string | null
}
export interface Transfer {
  id: string
  number: string
  status: 'draft' | 'in_transit' | 'received' | 'cancelled'
  from_warehouse_id: string
  from_warehouse: string
  to_warehouse_id: string
  to_warehouse: string
  cost_method: 'quantity' | 'value' | 'weight'
  vehicle: string | null
  transporter: string | null
  notes: string | null
  goods_value: number
  extra_cost: number
  costs_total: number
  loss_value: number
  landed_value: number
  created_at: string
  dispatched_at: string | null
  received_at: string | null
  total_quantity: number
  line_count: number
  products?: string
  items: TransferItem[]
  costs: TransferCost[]
}
export interface TransferIn {
  from_warehouse_id?: string | null
  to_warehouse_id?: string | null
  items?: { product_id: string; quantity: string; unit: string | null }[]
  costs?: { kind: string; amount: string; paid_to: string | null; note?: string | null }[]
  cost_method?: string
  vehicle?: string | null
  transporter?: string | null
  notes?: string | null
  dispatch?: boolean
}

export const warehouses = {
  list: () => http.get<{ items: Warehouse[]; kinds: Record<string, string>; cost_kinds: Record<string, string>; methods: Record<string, string> }>('/api/warehouses'),
  create: (body: WarehouseIn) => http.post<Warehouse>('/api/warehouses', body),
  update: ({ id, ...body }: WarehouseIn & { id: string }) => http.put<Warehouse>(`/api/warehouses/${id}`, body),
  stock: (params: { warehouse_id?: string; product_id?: string }) => http.get<{ items: StockRow[] }>('/api/warehouses/stock', params),
  transfers: (params: { status?: string; warehouse_id?: string } = {}) => http.get<{ items: Transfer[] }>('/api/stock-transfers', params),
  transfer: (id: string) => http.get<Transfer>(`/api/stock-transfers/${id}`),
  createTransfer: (body: TransferIn) => http.post<Transfer>('/api/stock-transfers', body),
  updateTransfer: ({ id, ...body }: TransferIn & { id: string }) => http.put<Transfer>(`/api/stock-transfers/${id}`, body),
  dispatch: (id: string) => http.post<Transfer>(`/api/stock-transfers/${id}/dispatch`),
  receive: ({ id, lines, note }: { id: string; lines?: { item_id: string; quantity_received: string }[]; note?: string }) =>
    http.post<Transfer>(`/api/stock-transfers/${id}/receive`, { lines, note }),
  cancel: (id: string) => http.post<Transfer>(`/api/stock-transfers/${id}/cancel`),
}
