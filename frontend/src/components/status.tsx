import type { ReactNode } from 'react'
import {
  ENQUIRY_STATUS_LABELS,
  FULFILMENT_STATUS_LABELS,
  PO_STATUS_LABELS,
  STATUS_LABELS,
  formatQuantity,
} from '../lib/format'
import { Badge, MetricStrip, type Tone } from './primitives'

const ORDER_TONE: Record<string, Tone> = {
  PENDING: 'orange',
  PARTIALLY_FULFILLED: 'blue',
  FULFILLED: 'green',
  CANCELLED: 'gray',
}

export function StatusBadge({ status }: { status: string }) {
  return (
    <Badge tone={ORDER_TONE[status] ?? 'gray'} dot>
      {STATUS_LABELS[status] ?? status}
    </Badge>
  )
}

const ENQUIRY_TONE: Record<string, Tone> = { OPEN: 'blue', CONVERTED: 'green', LOST: 'gray' }

export function EnquiryStatusBadge({ status }: { status: string }) {
  return (
    <Badge tone={ENQUIRY_TONE[status] ?? 'gray'} dot>
      {ENQUIRY_STATUS_LABELS[status] ?? status}
    </Badge>
  )
}

const PO_TONE: Record<string, Tone> = {
  DRAFT: 'gray',
  ORDERED: 'orange',
  PARTIALLY_RECEIVED: 'blue',
  RECEIVED: 'green',
  CANCELLED: 'gray',
}

export function PurchaseStatusBadge({ status }: { status: string }) {
  return (
    <Badge tone={PO_TONE[status] ?? 'gray'} dot>
      {PO_STATUS_LABELS[status] ?? status}
    </Badge>
  )
}

const FULFILMENT_TONE: Record<string, Tone> = {
  AWAITING_STOCK: 'red',
  ON_ORDER: 'orange',
  RESERVED: 'indigo',
  READY_TO_DELIVER: 'green',
  PARTIALLY_DELIVERED: 'blue',
}

export function FulfilmentStatusBadge({ status }: { status: string }) {
  return (
    <Badge tone={FULFILMENT_TONE[status] ?? 'gray'} dot>
      {FULFILMENT_STATUS_LABELS[status] ?? status}
    </Badge>
  )
}

/** What is left on an order line, split by state: one small badge per state
 *  that has any quantity, so a line that is partly sent, partly ready, partly
 *  on order and partly short says so at a glance. */
export function FulfilmentMix({
  delivered,
  ready,
  onOrder,
  short,
}: {
  delivered: string | number
  ready: string | number
  onOrder: string | number
  short: string | number
}) {
  const parts: { value: number; label: string; tone: Tone; title: string }[] = [
    { value: Number(delivered), label: 'sent', tone: 'gray', title: 'Already delivered' },
    { value: Number(ready), label: 'ready', tone: 'indigo', title: 'In the warehouse — can be delivered now' },
    { value: Number(onOrder), label: 'on order', tone: 'orange', title: 'Bought from a supplier, not arrived yet' },
    { value: Number(short), label: 'short', tone: 'red', title: 'Nothing bought for it yet' },
  ]
  return (
    <span className="badge-mix">
      {parts
        .filter((part) => part.value > 0)
        .map((part) => (
          <Badge key={part.label} tone={part.tone} title={part.title}>
            {formatQuantity(String(part.value))} {part.label}
          </Badge>
        ))}
    </span>
  )
}

/** Marks an enquiry the AI captured from a message. Typed-in ones show nothing. */
export function EnquirySourceBadge({ source, detail }: { source: string; detail?: string | null }) {
  if (source === 'whatsapp') {
    return <Badge tone="green" title={detail ? `From ${detail} on WhatsApp` : undefined}>WhatsApp</Badge>
  }
  if (source === 'email') {
    return <Badge tone="blue" title={detail ? `From ${detail}` : undefined}>Email</Badge>
  }
  return null
}

export function ArchivedBadge() {
  return <Badge tone="gray">Archived</Badge>
}

/** A quantity in red when negative, so an obligation never reads as stock. */
export function SignedQuantity({ value, unit }: { value: string | number; unit?: string }) {
  const parsed = Number(value)
  const negative = Number.isFinite(parsed) && parsed < 0
  return (
    <span className={negative ? 'q-negative' : undefined}>
      {formatQuantity(value)}
      {unit ? ` ${unit}` : ''}
    </span>
  )
}

/** A quantity that is only shown when it is not zero. */
export function Quantity({
  value,
  tone,
  dashWhenZero = true,
}: {
  value: string | number
  tone?: 'reserved' | 'available' | 'owed' | 'awaiting' | 'strong'
  dashWhenZero?: boolean
}) {
  const parsed = Number(value)
  if (dashWhenZero && (!Number.isFinite(parsed) || parsed === 0)) {
    return <span className="q-muted">—</span>
  }
  return <span className={tone ? `q-${tone}` : undefined}>{formatQuantity(value)}</span>
}

/** Stock as the business counts it: bought less sold. Both count the moment
 *  the order is placed, whatever has physically arrived or left, so this goes
 *  negative when more has been sold than bought. */
export function StockFigures({
  stock,
  toReceive,
  toDeliver,
  unit,
  extra,
}: {
  stock: string
  toReceive?: string
  toDeliver: string
  unit?: string
  extra?: { label: string; value: ReactNode; hint?: ReactNode }[]
}) {
  const short = Number(stock) < 0
  return (
    <MetricStrip
      items={[
        {
          label: 'Stock',
          value: formatQuantity(stock),
          hint: short
            ? `short by ${formatQuantity(String(-Number(stock)))}${unit ? ` ${unit}` : ''}`
            : unit
              ? `${unit} free to sell`
              : 'free to sell',
          tone: short ? ('negative' as const) : ('positive' as const),
        },
        ...(toReceive !== undefined
          ? [
              {
                label: 'To receive',
                value: formatQuantity(toReceive),
                hint: 'bought, not arrived yet',
              },
            ]
          : []),
        {
          label: 'To deliver',
          value: formatQuantity(toDeliver),
          hint: 'sold, truck not gone yet',
          tone: Number(toDeliver) > 0 ? ('owed' as const) : undefined,
        },
        ...(extra ?? []),
      ]}
    />
  )
}
