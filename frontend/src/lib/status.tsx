import { Badge, type Tone } from '@/ui/core'

const ORDER: Record<string, [string, Tone]> = {
  PENDING: ['Open', 'sky'],
  PARTIALLY_FULFILLED: ['Part delivered', 'steel'],
  FULFILLED: ['Delivered', 'ok'],
  CANCELLED: ['Cancelled', 'muted'],
}
const ENQUIRY: Record<string, [string, Tone]> = {
  OPEN: ['Open', 'sky'],
  CONVERTED: ['Won', 'ok'],
  LOST: ['Lost', 'muted'],
}
const PURCHASE: Record<string, [string, Tone]> = {
  DRAFT: ['Draft', 'muted'],
  ORDERED: ['Ordered', 'sky'],
  PARTIALLY_RECEIVED: ['Part received', 'steel'],
  RECEIVED: ['Received', 'ok'],
  CANCELLED: ['Cancelled', 'muted'],
}

export const orderStatus = (status: string) => ORDER[status]?.[0] ?? status
export const purchaseStatus = (status: string) => PURCHASE[status]?.[0] ?? status

export const OrderBadge = ({ status }: { status: string }) => {
  const [label, tone] = ORDER[status] ?? [status, 'muted']
  return <Badge tone={tone} dot>{label}</Badge>
}
export const EnquiryBadge = ({ status }: { status: string }) => {
  const [label, tone] = ENQUIRY[status] ?? [status, 'muted']
  return <Badge tone={tone} dot>{label}</Badge>
}
export const PurchaseBadge = ({ status }: { status: string }) => {
  const [label, tone] = PURCHASE[status] ?? [status, 'muted']
  return <Badge tone={tone} dot>{label}</Badge>
}

/** The colours of a line's states, used by meters and legends everywhere. */
export const STATE = {
  delivered: 'var(--color-fg-4)',
  ready: 'var(--color-blue)',
  onOrder: 'var(--color-peri)',
  short: 'var(--color-bad)',
} as const

export const ORDER_FILTERS = [
  { value: 'all', label: 'All' },
  { value: 'PENDING', label: 'Open' },
  { value: 'PARTIALLY_FULFILLED', label: 'Part' },
  { value: 'FULFILLED', label: 'Done' },
  { value: 'CANCELLED', label: 'Cancelled' },
] as const
