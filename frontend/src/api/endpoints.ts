import { http } from './client'
import type * as T from './types'

type ListQuery = { search?: string; limit?: number; offset?: number; sort_by?: string; sort_dir?: 'asc' | 'desc' }

/** One function per backend endpoint the app uses. */
export const api = {
  auth: {
    me: () => http.get<T.Me>('/api/auth/me'),
    login: (body: T.SignIn) => http.post<T.Me>('/api/auth/login', body),
    logout: () => http.post<unknown>('/api/auth/logout'),
    password: (body: T.PasswordChange) => http.post<T.Me>('/api/auth/password', body),
  },

  summary: () => http.get<T.InventorySummaryOut>('/api/inventory/summary'),
  commitments: (query: { search?: string; customer_id?: string; product_id?: string; only_unallocated?: boolean } = {}) =>
    http.get<T.PendingCommitmentsOut>('/api/inventory/pending-commitments', query),

  products: {
    list: (query: ListQuery & { include_inactive?: boolean; category?: string; supplier_id?: string; ids?: string } = {}) => http.get<T.Page<T.ProductOut>>('/api/products', query),
    categories: () => http.get<{ name: string; products: number }[]>('/api/products/categories'),
    get: (id: string) => http.get<T.ProductOut>(`/api/products/${id}`),
    inventory: (id: string) => http.get<T.ProductInventoryOut>(`/api/products/${id}/inventory`),
    pendingOrders: (id: string, receipt_quantity?: string) =>
      http.get<T.PendingOrdersOut>(`/api/products/${id}/pending-orders`, { receipt_quantity }),
    create: (body: T.ProductCreate) => http.post<T.ProductOut>('/api/products', body),
    update: (id: string, body: T.ProductUpdate) => http.patch<T.ProductOut>(`/api/products/${id}`, body),
    archive: (id: string) => http.post<T.ProductOut>(`/api/products/${id}/archive`),
  },

  customers: {
    list: (query: ListQuery & { include_inactive?: boolean } = {}) => http.get<T.Page<T.CustomerListRow>>('/api/customers', query),
    get: (id: string) => http.get<T.CustomerDetailOut>(`/api/customers/${id}`),
    create: (body: T.CustomerCreate) => http.post<T.CustomerOut>('/api/customers', body),
    update: (id: string, body: T.CustomerUpdate) => http.patch<T.CustomerOut>(`/api/customers/${id}`, body),
    archive: (id: string) => http.post<T.CustomerOut>(`/api/customers/${id}/archive`),
  },

  suppliers: {
    list: (query: ListQuery & { include_inactive?: boolean } = {}) => http.get<T.Page<T.SupplierListRow>>('/api/suppliers', query),
    get: (id: string) => http.get<T.SupplierDetailOut>(`/api/suppliers/${id}`),
    create: (body: T.SupplierCreate) => http.post<T.SupplierOut>('/api/suppliers', body),
    update: (id: string, body: T.SupplierUpdate) => http.patch<T.SupplierOut>(`/api/suppliers/${id}`, body),
    archive: (id: string) => http.post<T.SupplierOut>(`/api/suppliers/${id}/archive`),
  },

  enquiries: {
    list: (query: ListQuery & { status?: string; customer_id?: string } = {}) => http.get<T.Page<T.EnquiryOut>>('/api/enquiries', query),
    get: (id: string) => http.get<T.EnquiryOut>(`/api/enquiries/${id}`),
    create: (body: T.EnquiryCreate) => http.post<T.EnquiryOut>('/api/enquiries', body),
    update: (id: string, body: T.EnquiryUpdate) => http.patch<T.EnquiryOut>(`/api/enquiries/${id}`, body),
    convert: (id: string, approval?: string) =>
      http.post<T.EnquiryConversionResult>(`/api/enquiries/${id}/convert${approval ? `?override=true&override_reason=${encodeURIComponent(approval)}` : ''}`),
    markLost: (id: string, reason: string | null) => http.post<T.EnquiryOut>(`/api/enquiries/${id}/mark-lost`, { reason }),
  },

  orders: {
    list: (query: ListQuery & { status?: string; customer_id?: string; product_id?: string } = {}) =>
      http.get<T.Page<T.OrderOut>>('/api/orders', query),
    get: (id: string) => http.get<T.OrderDetailOut>(`/api/orders/${id}`),
    fulfilment: (id: string) => http.get<T.OrderFulfilmentOut>(`/api/orders/${id}/fulfilment`),
    create: (body: T.OrderCreate, approval?: string) =>
      http.post<T.OrderDetailOut>(approval ? `/api/orders?override=true&override_reason=${encodeURIComponent(approval)}` : '/api/orders', body),
    cancel: (id: string, reason: string | null) => http.post<T.OrderDetailOut>(`/api/orders/${id}/cancel`, { reason }),
    cancelRemaining: (id: string, reason: string | null) =>
      http.post<T.OrderDetailOut>(`/api/orders/${id}/cancel-remaining`, { reason }),
    deliver: (id: string, body: T.DeliveryRequest) => http.post<T.DeliveryResult>(`/api/orders/${id}/deliveries`, body),
  },

  deliveries: (query: ListQuery & { customer_id?: string; order_id?: string } = {}) =>
    http.get<T.Page<T.DeliveryRow>>('/api/deliveries', query),

  purchaseOrders: {
    list: (query: ListQuery & { status?: string; supplier_id?: string; product_id?: string } = {}) =>
      http.get<T.Page<T.PurchaseOrderOut>>('/api/purchase-orders', query),
    get: (id: string) => http.get<T.PurchaseOrderOut>(`/api/purchase-orders/${id}`),
    create: (body: T.PurchaseOrderCreate) => http.post<T.PurchaseOrderOut>('/api/purchase-orders', body),
    update: (id: string, body: T.PurchaseOrderUpdate) => http.patch<T.PurchaseOrderOut>(`/api/purchase-orders/${id}`, body),
    confirm: (id: string, body: T.PurchaseSettleRequest = { settlements: null }) => http.post<T.PurchaseOrderOut>(`/api/purchase-orders/${id}/confirm`, body),
    settle: (id: string, body: T.PurchaseSettleRequest) => http.post<T.PurchaseOrderOut>(`/api/purchase-orders/${id}/settle`, body),
    cancel: (id: string, reason: string | null) => http.post<T.PurchaseOrderOut>(`/api/purchase-orders/${id}/cancel`, { reason }),
  },

  goodsReceipts: {
    list: (query: ListQuery & { supplier_id?: string; purchase_order_id?: string } = {}) =>
      http.get<T.Page<T.GoodsReceiptRow>>('/api/goods-receipts', query),
    get: (id: string) => http.get<T.GoodsReceiptResult>(`/api/goods-receipts/${id}`),
    preview: (body: T.GoodsReceiptRequest) => http.post<T.ReceiptPreviewOut>('/api/goods-receipts/preview', body),
    create: (body: T.GoodsReceiptRequest) => http.post<T.GoodsReceiptResult>('/api/goods-receipts', body),
  },

  stockReceipts: {
    create: (body: T.StockReceiptCreate) => http.post<T.StockReceiptResult>('/api/stock-receipts', body),
  },

  tasks: {
    list: (query: { status?: string; due?: string; search?: string; customer_id?: string; enquiry_id?: string; sales_order_id?: string; supplier_id?: string; purchase_order_id?: string; assignee_id?: string; limit?: number } = {}) =>
      http.get<T.Page<T.TaskOut>>('/api/tasks', query),
    counts: () => http.get<T.TaskCounts>('/api/tasks/counts'),
    assignees: () => http.get<T.UserRef[]>('/api/tasks/assignees'),
    create: (body: Omit<T.TaskCreate, 'priority'> & { priority?: string }) => http.post<T.TaskOut>('/api/tasks', body),
    update: (id: string, body: T.TaskUpdate) => http.patch<T.TaskOut>(`/api/tasks/${id}`, body),
  },

  integrations: {
    get: () => http.get<T.IntegrationsOut>('/api/integrations'),
    update: (name: string, body: T.IntegrationUpdate) => http.put<T.IntegrationOut>(`/api/integrations/${name}`, body),
    testAi: () => http.post<T.AiTestOut>('/api/integrations/ai/test'),
    checkEmail: () => http.post<T.EmailCheckOut>('/api/integrations/email/check'),
    messages: (query: { channel?: string; status?: string; limit?: number; offset?: number } = {}) =>
      http.get<T.Page<T.InboundMessageOut>>('/api/integrations/messages', query),
    retryMessage: (id: string) => http.post<T.InboundMessageOut>(`/api/integrations/messages/${id}/retry`),
    testTally: () => http.post<T.TallyTestOut>('/api/integrations/tally/test'),
    syncs: (query: { status?: string; entity_id?: string; limit?: number; offset?: number } = {}) =>
      http.get<T.Page<T.TallySyncOut>>('/api/integrations/tally/syncs', query),
    retrySync: (id: string) => http.post<T.TallySyncOut>(`/api/integrations/tally/syncs/${id}/retry`),
    template: () => http.get<T.TemplateStatusOut>('/api/integrations/whatsapp/template'),
    invoiceUrl: (orderId: string) => `/api/integrations/invoices/${orderId}.pdf`,
  },
}
