import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { CheckCircle2, Package, RotateCcw, Truck } from 'lucide-react'
import { errorText, http } from '@/api/client'
import { cn } from '@/lib/cn'
import { fmtDate, fmtMoney, fmtQty } from '@/lib/format'
import type { PortalOrder, SentEnquiry } from './types'
import { Empty, Loading } from './ui'

const STATUS: Record<PortalOrder['status'], { label: string; tone: string }> = {
  PENDING: { label: 'Confirmed', tone: 'bg-blue/15 text-blue' },
  PARTIALLY_FULFILLED: { label: 'Part delivered', tone: 'bg-warn/15 text-warn' },
  FULFILLED: { label: 'Delivered', tone: 'bg-ok/15 text-ok' },
  CANCELLED: { label: 'Cancelled', tone: 'bg-ink-700 text-fg-3' },
}

export function MyOrdersTab({ token }: { token: string }) {
  const data = useQuery({
    queryKey: ['public', token, 'orders'],
    queryFn: () => http.get<{ orders: PortalOrder[] }>(`/api/public/e/${token}/orders`),
    retry: false,
  })
  if (data.isPending) return <Loading />
  if (data.error) return <Empty text={errorText(data.error)} />
  if (!data.data.orders.length) return <Empty icon={<Package size={22} />} text="No orders yet. Your orders and deliveries will show here." />
  return (
    <div className="space-y-3">
      {data.data.orders.map((order) => (
        <OrderCard key={order.id} token={token} order={order} />
      ))}
    </div>
  )
}

function OrderCard({ token, order }: { token: string; order: PortalOrder }) {
  const [open, setOpen] = useState(false)
  const again = useMutation({ mutationFn: () => http.post<SentEnquiry>(`/api/public/e/${token}/reorder/${order.id}`) })
  const ordered = order.lines.reduce((sum, l) => sum + Math.max(0, l.ordered - l.cancelled), 0)
  const delivered = order.lines.reduce((sum, l) => sum + l.delivered, 0)
  const progress = ordered > 0 ? Math.min(100, Math.round((delivered / ordered) * 100)) : 0
  const status = STATUS[order.status] ?? STATUS.PENDING
  return (
    <div className="card p-4">
      <div className="flex flex-wrap items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="text-[15px] font-semibold">{order.number}</div>
          <div className="text-[12.5px] text-fg-3">
            {fmtDate(order.date)} · {order.lines.length} item{order.lines.length === 1 ? '' : 's'}
          </div>
        </div>
        <div className="text-right">
          <span className={cn('inline-block rounded-full px-2.5 py-0.5 text-[11.5px] font-semibold', status.tone)}>{status.label}</span>
          <div className="num mt-1 text-[14px] font-semibold">{fmtMoney(order.total)}</div>
        </div>
      </div>

      {order.status !== 'CANCELLED' ? (
        <div className="mt-3">
          <div className="flex justify-between text-[11.5px] text-fg-3">
            <span>Delivered</span>
            <span>{progress}%</span>
          </div>
          <div className="mt-1 h-2 overflow-hidden rounded-full bg-ink-700">
            <div className={cn('h-full rounded-full', progress >= 100 ? 'bg-ok' : 'bg-blue')} style={{ width: `${progress}%` }} />
          </div>
        </div>
      ) : null}

      <div className="mt-3 divide-y divide-[var(--card-border)]">
        {order.lines.map((line) => (
          <div key={line.id} className="py-2 text-[13px]">
            <div className="flex gap-2">
              <span className="min-w-0 flex-1 break-words font-medium">{line.product}</span>
              <span className="num shrink-0">
                {fmtQty(line.ordered)} {line.unit}
              </span>
            </div>
            <div className="mt-0.5 flex flex-wrap gap-x-3 text-[12px] text-fg-3">
              <span>Delivered {fmtQty(line.delivered)}</span>
              {line.ready > 0 ? <span className="text-ok">Ready {fmtQty(line.ready)}</span> : null}
              {line.pending > 0 ? <span>Pending {fmtQty(line.pending)}</span> : null}
              {line.cancelled > 0 ? <span>Cancelled {fmtQty(line.cancelled)}</span> : null}
            </div>
          </div>
        ))}
      </div>

      {order.deliveries.length ? (
        <div className="mt-2">
          <button className="btn-quiet btn btn-sm -ml-2" onClick={() => setOpen((prev) => !prev)}>
            <Truck size={14} /> {order.deliveries.length} deliver{order.deliveries.length === 1 ? 'y' : 'ies'} {open ? '▴' : '▾'}
          </button>
          {open ? (
            <div className="mt-2 space-y-2">
              {order.deliveries.map((d) => (
                <div key={d.id} className="rounded-xl bg-ink-800 p-3 text-[12.5px]">
                  <div className="flex flex-wrap justify-between gap-2">
                    <b>{d.number}</b>
                    <span className="text-fg-3">{fmtDate(d.date)}</span>
                  </div>
                  <div className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5 text-fg-2">
                    {d.vehicle_number ? <Meta label="Vehicle" value={d.vehicle_number} /> : null}
                    {d.lr_number ? <Meta label="LR" value={d.lr_number} /> : null}
                    {d.transporter ? <Meta label="Transporter" value={d.transporter} /> : null}
                    {d.eway_bill_number ? <Meta label="E-way bill" value={d.eway_bill_number} /> : null}
                  </div>
                  <ul className="mt-1.5 space-y-0.5">
                    {d.lines.map((l, i) => (
                      <li key={i} className="flex gap-2">
                        <span className="min-w-0 flex-1 break-words">{l.product}</span>
                        <span className="num shrink-0">
                          {fmtQty(l.quantity)} {l.unit}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="mt-3 border-t border-[var(--card-border)] pt-3">
        {again.data ? (
          <p className="flex items-center gap-2 text-[13px] text-ok">
            <CheckCircle2 size={16} className="shrink-0" /> Enquiry {again.data.enquiry_number} sent · about {fmtMoney(again.data.total)}. We will confirm shortly.
          </p>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            <button className="btn btn-sm" disabled={again.isPending} onClick={() => again.mutate()}>
              <RotateCcw size={14} /> Order again
            </button>
            {again.error ? <span className="text-[12.5px] text-bad">{errorText(again.error)}</span> : null}
          </div>
        )}
      </div>
    </div>
  )
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <span className="min-w-0 break-words">
      <span className="text-fg-3">{label}: </span>
      {value}
    </span>
  )
}
