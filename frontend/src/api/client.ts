import type {
  InboundMessage,
  Integration,
  IntegrationName,
  Integrations,
  Customer,
  CustomerListRow,
  CustomerDetail,
  DeliveryResult,
  DeliveryRow,
  Enquiry,
  EnquiryConversionResult,
  GoodsReceiptResult,
  GoodsReceiptRow,
  OrderFulfilment,
  Page,
  PendingCommitments,
  PurchaseOrder,
  ReceiptPreview,
  Supplier,
  SupplierListRow,
  SupplierDetail,
  InventorySummary,
  Order,
  OrderDetail,
  PendingOrders,
  Product,
  ProductInventory,
  StockReceiptResult,
} from './types'

const BASE_URL: string = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(
  /\/+$/,
  '',
)

/** An error carrying the backend's human-readable message and details. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: Record<string, unknown>

  constructor(status: number, code: string, message: string, details: Record<string, unknown>) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

export type Query = Record<string, string | number | boolean | undefined | null>

function buildUrl(path: string, query?: Query): string {
  const url = new URL(BASE_URL + path, window.location.origin)
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && value !== '') {
        url.searchParams.set(key, String(value))
      }
    }
  }
  return url.toString()
}

async function request<T>(
  path: string,
  options: { method?: string; body?: unknown; query?: Query; signal?: AbortSignal } = {},
): Promise<T> {
  const { method = 'GET', body, query, signal } = options
  let response: Response
  try {
    response = await fetch(buildUrl(path, query), {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    })
  } catch (cause) {
    if ((cause as Error)?.name === 'AbortError') throw cause
    throw new ApiError(
      0,
      'network_error',
      `Could not reach the API at ${BASE_URL}. Is the backend running?`,
      {},
    )
  }

  if (response.status === 204) return undefined as T

  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    // FastAPI's own validation errors use `detail`; ours use code/message/details.
    const message =
      (payload && typeof payload.message === 'string' && payload.message) ||
      (payload && formatFastApiDetail(payload.detail)) ||
      `Request failed with status ${response.status}.`
    throw new ApiError(
      response.status,
      (payload && payload.code) || 'error',
      message,
      (payload && payload.details) || {},
    )
  }
  return payload as T
}

function formatFastApiDetail(detail: unknown): string | null {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((entry: { loc?: unknown[]; msg?: string }) => {
        const field = Array.isArray(entry.loc) ? entry.loc.slice(1).join('.') : ''
        return field ? `${field}: ${entry.msg}` : String(entry.msg)
      })
      .join('; ')
  }
  return null
}

/** The most rows one listing request may return. */
export const MAX_PAGE_SIZE = 500

/** Every row a listing matches, for pickers and exports: pages through the
 *  server in the largest windows it allows. */
async function all<T>(path: string, query?: Query): Promise<T[]> {
  const rows: T[] = []
  for (let offset = 0; ; offset += MAX_PAGE_SIZE) {
    const page = await request<Page<T>>(path, { query: { ...query, limit: MAX_PAGE_SIZE, offset } })
    rows.push(...page.items)
    if (rows.length >= page.total || page.items.length === 0) return rows
  }
}

export const api = {
  products: {
    list: (query?: Query) => request<Page<Product>>('/api/products', { query }),
    all: (query?: Query) => all<Product>('/api/products', query),
    get: (id: string) => request<Product>(`/api/products/${id}`),
    create: (body: unknown) => request<Product>('/api/products', { method: 'POST', body }),
    update: (id: string, body: unknown) =>
      request<Product>(`/api/products/${id}`, { method: 'PATCH', body }),
    archive: (id: string) => request<Product>(`/api/products/${id}/archive`, { method: 'POST' }),
    inventory: (id: string) => request<ProductInventory>(`/api/products/${id}/inventory`),
    pendingOrders: (id: string, receiptQuantity?: string) =>
      request<PendingOrders>(`/api/products/${id}/pending-orders`, {
        query: { receipt_quantity: receiptQuantity },
      }),
  },
  customers: {
    list: (query?: Query) => request<Page<CustomerListRow>>('/api/customers', { query }),
    all: (query?: Query) => all<CustomerListRow>('/api/customers', query),
    get: (id: string) => request<CustomerDetail>(`/api/customers/${id}`),
    create: (body: unknown) => request<Customer>('/api/customers', { method: 'POST', body }),
    update: (id: string, body: unknown) =>
      request<Customer>(`/api/customers/${id}`, { method: 'PATCH', body }),
    archive: (id: string) => request<Customer>(`/api/customers/${id}/archive`, { method: 'POST' }),
  },
  orders: {
    list: (query?: Query) => request<Page<Order>>('/api/orders', { query }),
    all: (query?: Query) => all<Order>('/api/orders', query),
    get: (id: string) => request<OrderDetail>(`/api/orders/${id}`),
    create: (body: unknown) => request<OrderDetail>('/api/orders', { method: 'POST', body }),
    cancel: (id: string, reason?: string) =>
      request<OrderDetail>(`/api/orders/${id}/cancel`, { method: 'POST', body: { reason } }),
    cancelRemaining: (id: string, reason?: string) =>
      request<OrderDetail>(`/api/orders/${id}/cancel-remaining`, {
        method: 'POST',
        body: { reason },
      }),
  },
  enquiries: {
    list: (query?: Query) => request<Page<Enquiry>>('/api/enquiries', { query }),
    all: (query?: Query) => all<Enquiry>('/api/enquiries', query),
    get: (id: string) => request<Enquiry>(`/api/enquiries/${id}`),
    create: (body: unknown) => request<Enquiry>('/api/enquiries', { method: 'POST', body }),
    update: (id: string, body: unknown) =>
      request<Enquiry>(`/api/enquiries/${id}`, { method: 'PATCH', body }),
    convert: (id: string) =>
      request<EnquiryConversionResult>(`/api/enquiries/${id}/convert`, { method: 'POST' }),
    markLost: (id: string, reason?: string) =>
      request<Enquiry>(`/api/enquiries/${id}/mark-lost`, { method: 'POST', body: { reason } }),
  },
  suppliers: {
    list: (query?: Query) => request<Page<SupplierListRow>>('/api/suppliers', { query }),
    all: (query?: Query) => all<SupplierListRow>('/api/suppliers', query),
    get: (id: string) => request<SupplierDetail>(`/api/suppliers/${id}`),
    create: (body: unknown) => request<Supplier>('/api/suppliers', { method: 'POST', body }),
    update: (id: string, body: unknown) =>
      request<Supplier>(`/api/suppliers/${id}`, { method: 'PATCH', body }),
    archive: (id: string) => request<Supplier>(`/api/suppliers/${id}/archive`, { method: 'POST' }),
  },
  purchaseOrders: {
    list: (query?: Query) => request<Page<PurchaseOrder>>('/api/purchase-orders', { query }),
    all: (query?: Query) => all<PurchaseOrder>('/api/purchase-orders', query),
    get: (id: string) => request<PurchaseOrder>(`/api/purchase-orders/${id}`),
    create: (body: unknown) =>
      request<PurchaseOrder>('/api/purchase-orders', { method: 'POST', body }),
    update: (id: string, body: unknown) =>
      request<PurchaseOrder>(`/api/purchase-orders/${id}`, { method: 'PATCH', body }),
    confirm: (id: string, body?: unknown) =>
      request<PurchaseOrder>(`/api/purchase-orders/${id}/confirm`, { method: 'POST', body }),
    settle: (id: string, body: unknown) =>
      request<PurchaseOrder>(`/api/purchase-orders/${id}/settle`, { method: 'POST', body }),
    cancel: (id: string, reason?: string) =>
      request<PurchaseOrder>(`/api/purchase-orders/${id}/cancel`, {
        method: 'POST',
        body: { reason },
      }),
  },
  goodsReceipts: {
    list: (query?: Query) => request<Page<GoodsReceiptRow>>('/api/goods-receipts', { query }),
    all: (query?: Query) => all<GoodsReceiptRow>('/api/goods-receipts', query),
    get: (id: string) => request<GoodsReceiptResult>(`/api/goods-receipts/${id}`),
    preview: (body: unknown) =>
      request<ReceiptPreview>('/api/goods-receipts/preview', { method: 'POST', body }),
    create: (body: unknown) =>
      request<GoodsReceiptResult>('/api/goods-receipts', { method: 'POST', body }),
  },
  fulfilment: {
    order: (orderId: string) => request<OrderFulfilment>(`/api/orders/${orderId}/fulfilment`),
    deliver: (orderId: string, body: unknown) =>
      request<DeliveryResult>(`/api/orders/${orderId}/deliveries`, { method: 'POST', body }),
    deliveries: (query?: Query) => request<Page<DeliveryRow>>('/api/deliveries', { query }),
    commitments: (query?: Query) =>
      request<PendingCommitments>('/api/inventory/pending-commitments', { query }),
  },
  inventory: {
    summary: () => request<InventorySummary>('/api/inventory/summary'),
    receiveStock: (body: unknown) =>
      request<StockReceiptResult>('/api/stock-receipts', { method: 'POST', body }),
  },
  integrations: {
    get: () => request<Integrations>('/api/integrations'),
    update: (
      name: IntegrationName,
      body: {
        enabled?: boolean
        config?: Record<string, string | number>
        /** Omit a credential to keep it; send '' to remove it. */
        credentials?: Record<string, string>
      },
    ) => request<Integration>(`/api/integrations/${name}`, { method: 'PUT', body }),
    testAi: () => request<{ ok: boolean; model: string; reply: string }>('/api/integrations/ai/test', { method: 'POST' }),
    checkEmail: () => request<{ new_messages: number }>('/api/integrations/email/check', { method: 'POST' }),
    messages: (query?: Query) => request<Page<InboundMessage>>('/api/integrations/messages', { query }),
    retry: (id: string) =>
      request<InboundMessage>(`/api/integrations/messages/${id}/retry`, { method: 'POST' }),
  },
}

export { BASE_URL }
