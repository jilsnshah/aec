export interface CustomerSummary {
  open_orders: number
  amount_open: number
  overdue: number
  payment_terms_days: number
  last_order_date: string | null
}

export interface PageData {
  business: string
  customer: string
  customer_summary: CustomerSummary
  products: { id: string; name: string; unit: string; category: string | null; mrp: number; price: number; in_stock: boolean }[]
}

export interface PortalOrderLine {
  id: string
  product: string
  unit: string
  ordered: number
  delivered: number
  ready: number
  pending: number
  cancelled: number
  rate: number
}

export interface PortalDelivery {
  id: string
  number: string
  date: string
  vehicle_number: string | null
  lr_number: string | null
  transporter: string | null
  eway_bill_number: string | null
  lines: { product: string; unit: string; quantity: number }[]
}

export interface PortalOrder {
  id: string
  number: string
  date: string
  status: 'PENDING' | 'PARTIALLY_FULFILLED' | 'FULFILLED' | 'CANCELLED'
  total: number
  lines: PortalOrderLine[]
  deliveries: PortalDelivery[]
}

export interface PortalInvoice {
  id: string
  number: string
  date: string | null
  order_number: string | null
  amount: number | null
  eway_bill_number: string | null
  download: string
}

export interface PortalStatement {
  summary: { invoiced: number; paid: number; open: number; overdue: number; payment_terms_days: number }
  entries: {
    date: string
    kind: 'invoice' | 'payment' | 'credit_note' | 'debit_note'
    number: string
    debit: number
    credit: number
    balance: number
    due_date: string | null
    days_overdue: number | null
  }[]
}

export interface SentEnquiry {
  enquiry_number: string
  total: number
}
