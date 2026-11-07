const QUANTITY_FORMAT = new Intl.NumberFormat(undefined, {
  minimumFractionDigits: 0,
  maximumFractionDigits: 3,
})
/** ISO 4217 code, so the deployment decides its own currency. */
const CURRENCY: string = import.meta.env.VITE_CURRENCY ?? 'INR'

const MONEY_FORMAT = new Intl.NumberFormat(undefined, {
  style: 'currency',
  currency: CURRENCY,
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})
/** Same scale, no symbol — for columns where the heading already says money. */
const AMOUNT_FORMAT = new Intl.NumberFormat(undefined, {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})
const UNIT_PRICE_FORMAT = new Intl.NumberFormat(undefined, {
  style: 'currency',
  currency: CURRENCY,
  minimumFractionDigits: 2,
  maximumFractionDigits: 4,
})
const PERCENT_FORMAT = new Intl.NumberFormat(undefined, {
  minimumFractionDigits: 0,
  maximumFractionDigits: 2,
})
const DATE_FORMAT = new Intl.DateTimeFormat(undefined, {
  year: 'numeric',
  month: 'short',
  day: '2-digit',
})
const DATETIME_FORMAT = new Intl.DateTimeFormat(undefined, {
  year: 'numeric',
  month: 'short',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
})

/** A bare quantity, trimmed of trailing zeros: "15.000" -> "15". */
export function formatQuantity(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return String(value)
  return QUANTITY_FORMAT.format(parsed)
}

/** A quantity with its unit of measure: "15 pcs". */
export function formatQuantityWithUnit(
  value: string | number | null | undefined,
  unit: string | null | undefined,
): string {
  const quantity = formatQuantity(value)
  if (quantity === '—') return quantity
  return unit ? `${quantity} ${unit}` : quantity
}

const COMPACT_MONEY_FORMAT = new Intl.NumberFormat(undefined, {
  style: 'currency',
  currency: CURRENCY,
  notation: 'compact',
  minimumFractionDigits: 0,
  maximumFractionDigits: 1,
})

/** Money for axis labels and tight spaces: "₹15K". */
export function formatCompactMoney(value: number): string {
  return COMPACT_MONEY_FORMAT.format(value)
}

export function formatMoney(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return String(value)
  return MONEY_FORMAT.format(parsed)
}

/** A money amount without the currency symbol, for dense numeric columns. */
export function formatAmount(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return String(value)
  return AMOUNT_FORMAT.format(parsed)
}

/** A per-unit price or cost, which may carry up to four decimals. */
export function formatUnitPrice(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return String(value)
  return UNIT_PRICE_FORMAT.format(parsed)
}

export function formatPercent(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return String(value)
  return `${PERCENT_FORMAT.format(parsed)}%`
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return '—'
  return DATE_FORMAT.format(new Date(value))
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  return DATETIME_FORMAT.format(new Date(value))
}

export const STATUS_LABELS: Record<string, string> = {
  PENDING: 'Pending',
  PARTIALLY_FULFILLED: 'Partly delivered',
  FULFILLED: 'Delivered',
  CANCELLED: 'Cancelled',
}

export const ENQUIRY_STATUS_LABELS: Record<string, string> = {
  OPEN: 'Open',
  CONVERTED: 'Converted',
  LOST: 'Lost',
}

export const PO_STATUS_LABELS: Record<string, string> = {
  DRAFT: 'Draft',
  ORDERED: 'Ordered',
  PARTIALLY_RECEIVED: 'Partly received',
  RECEIVED: 'Received',
  CANCELLED: 'Cancelled',
}

export const FULFILMENT_STATUS_LABELS: Record<string, string> = {
  AWAITING_STOCK: 'Short',
  ON_ORDER: 'On order',
  RESERVED: 'Ready',
  READY_TO_DELIVER: 'Ready to deliver',
  PARTIALLY_DELIVERED: 'Partly delivered',
}

export const MOVEMENT_LABELS: Record<string, string> = {
  OPENING_STOCK: 'Opening stock',
  STOCK_RECEIPT: 'Stock receipt',
  GOODS_RECEIPT: 'Goods receipt',
  CUSTOMER_DELIVERY: 'Customer delivery',
  ORDER_FULFILMENT: 'Order fulfilment (legacy)',
  ADJUSTMENT: 'Adjustment',
}

export const ALLOCATION_SOURCE_LABELS: Record<string, string> = {
  ORDER_CREATION: 'Stock on hand at order time',
  STOCK_RECEIPT: 'Covered by a stock receipt',
  GOODS_RECEIPT: 'Covered by a goods receipt',
}

const RELATIVE = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' })
const LONG_DATE = new Intl.DateTimeFormat(undefined, {
  weekday: 'long',
  day: 'numeric',
  month: 'long',
  year: 'numeric',
})

/** "just now", "12 minutes ago", "yesterday", then a date. */
export function formatRelative(value: string | null | undefined): string {
  if (!value) return '—'
  const seconds = (new Date(value).getTime() - Date.now()) / 1000
  const abs = Math.abs(seconds)
  if (abs < 45) return 'just now'
  if (abs < 3600) return RELATIVE.format(Math.round(seconds / 60), 'minute')
  if (abs < 86_400) return RELATIVE.format(Math.round(seconds / 3600), 'hour')
  if (abs < 86_400 * 7) return RELATIVE.format(Math.round(seconds / 86_400), 'day')
  return formatDate(value)
}

export function formatLongDate(value: Date = new Date()): string {
  return LONG_DATE.format(value)
}
