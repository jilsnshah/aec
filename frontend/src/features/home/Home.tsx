import { useMemo, useState, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { motion } from 'motion/react'
import { AlertTriangle, ArrowUpRight, ChevronRight, PackageCheck, PackageOpen, ReceiptText, Truck } from 'lucide-react'
import { api } from '@/api/endpoints'
import { useList, useSummary } from '@/api/queries'
import type { InventorySummaryOut } from '@/api/types'
import { useAuth } from '@/app/auth'
import { cn } from '@/lib/cn'
import { fmtCompactMoney, fmtMoney, fmtMoneyRound, fmtPercent, fmtQty, fmtShortDate, fmtToday, n, plural } from '@/lib/format'
import { OrderBadge, PurchaseBadge } from '@/lib/status'
import { CountUp, Empty, Skeleton } from '@/ui/core'
import { Segmented } from '@/ui/overlays'

const ease = [0.22, 1, 0.36, 1] as const

const greeting = () => {
  const hour = new Date().getHours()
  return hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening'
}

/** Today at a glance: one board of cards that fits the window. */
export function Home() {
  const summary = useSummary()
  const data = summary.data
  const { user } = useAuth()
  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto px-6 pb-5 max-md:px-2 max-md:pb-2">
      <div className="flex shrink-0 flex-wrap items-baseline gap-x-3 pb-4 max-md:px-1">
        <h1 className="text-[24px] font-semibold tracking-[-0.03em]">
          {greeting()}, {user?.username}
        </h1>
        <p className="text-[13px] text-fg-3">{fmtToday()}</p>
      </div>
      <div className="grid min-h-[600px] flex-1 grid-cols-12 grid-rows-[auto_minmax(0,0.95fr)_minmax(0,1.15fr)] gap-4 max-lg:flex max-lg:min-h-0 max-lg:flex-col max-md:gap-2">
        <Kpis data={data} />
        <ReadyGauge data={data} />
        <ProfitCard data={data} />
        <SalesBars data={data} />
        <Board data={data} />
        <OrderDots data={data} />
      </div>
    </div>
  )
}

function Card({ className, children, delay = 0, dark }: { className?: string; children: ReactNode; delay?: number; dark?: boolean }) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay, ease }}
      className={cn(dark ? 'pane-contrast' : 'pane', 'relative flex min-h-0 flex-col overflow-hidden', className)}
    >
      {children}
    </motion.section>
  )
}

function CardHead({ title, hint, actions }: { title: string; hint?: string; actions?: ReactNode }) {
  return (
    <header className="flex shrink-0 items-start gap-3 px-6 pt-5 pb-2">
      <div className="min-w-0 flex-1">
        <h2 className="text-[17px] font-semibold tracking-[-0.02em]">{title}</h2>
        {hint ? <p className="mt-0.5 text-[12px] text-fg-3">{hint}</p> : null}
      </div>
      {actions}
    </header>
  )
}

const IconDot = ({ children, tone = 'peri' }: { children: ReactNode; tone?: 'peri' | 'bad' }) => (
  <span className={cn('grid size-8 shrink-0 place-items-center rounded-full', tone === 'bad' ? 'bg-bad/14 text-bad' : 'bg-peri/30 text-sky')}>{children}</span>
)

/* ---------------------------------------------------------------- figures */
function Kpis({ data }: { data?: InventorySummaryOut }) {
  const days = data?.daily_sales ?? []
  const half = Math.floor(days.length / 2)
  const recent = days.slice(half).reduce((sum, day) => sum + n(day.delivered_value), 0)
  const before = days.slice(0, half).reduce((sum, day) => sum + n(day.delivered_value), 0)
  const change = before > 0 ? ((recent - before) / before) * 100 : null
  const items = [
    {
      label: 'To deliver',
      icon: <Truck size={15} />,
      value: data ? <CountUp value={n(data.total_pending_quantity)} format={(v) => fmtQty(Math.round(v * 1000) / 1000)} /> : null,
      note: data ? <span className="text-fg-3">{plural(data.open_orders, 'open order')}</span> : null,
      to: '/fulfilment',
    },
    {
      label: 'Delivered',
      icon: <PackageCheck size={15} />,
      value: data ? <CountUp value={recent + before} format={fmtMoneyRound} /> : null,
      note: change === null ? null : <span className={change >= 0 ? 'text-ok' : 'text-bad'} title="Last 15 days against the 15 before">{`${change >= 0 ? '+' : ''}${change.toFixed(0)}%`} <span className="text-fg-3">30 days</span></span>,
      to: '/orders',
    },
    {
      label: 'Short',
      icon: <AlertTriangle size={15} />,
      tone: n(data?.total_unallocated_quantity) > 0 ? ('bad' as const) : undefined,
      value: data ? <CountUp value={n(data.total_unallocated_quantity)} format={(v) => fmtQty(Math.round(v * 1000) / 1000)} /> : null,
      note: data ? <span className={data.products_short?.length ? 'text-bad' : 'text-fg-3'}>{plural(data.products_short?.length ?? 0, 'product')} to buy</span> : null,
      to: '/fulfilment?lane=short',
    },
  ]
  return (
    <div className="col-span-7 grid shrink-0 grid-cols-3 gap-4 max-md:grid-cols-1 max-md:gap-2">
      {items.map((item, index) => (
        <Card key={item.label} delay={0.04 * index}>
          <Link to={item.to} className="group flex h-full flex-col gap-4 p-5">
            <div className="flex items-center gap-2.5">
              <IconDot tone={item.tone}>{item.icon}</IconDot>
              <span className="text-[14px] font-medium">{item.label}</span>
              <ArrowUpRight size={15} className="ml-auto text-fg-4 opacity-0 transition group-hover:opacity-100" />
            </div>
            <div className="flex items-baseline gap-2">
              <span className={cn('num text-[30px] leading-none font-semibold tracking-[-0.035em]', item.tone === 'bad' && 'text-bad')}>{item.value ?? <Skeleton className="h-7 w-24" />}</span>
              <span className="text-[11.5px] font-medium whitespace-nowrap">{item.note}</span>
            </div>
          </Link>
        </Card>
      ))}
    </div>
  )
}

/* ---------------------------------------------------------------- gauge */
/** How much of what customers are owed is already in hand. */
function ReadyGauge({ data }: { data?: InventorySummaryOut }) {
  const owed = n(data?.total_pending_quantity)
  const ready = Math.min(owed, n(data?.total_reserved_stock))
  const share = owed > 0 ? (ready / owed) * 100 : 100
  const gap = share > 0 && share < 100 ? 1.2 : 0
  const arc = 'M 20 110 A 90 90 0 0 1 200 110'
  return (
    <Card className="col-span-3 max-lg:min-h-[260px]" delay={0.1}>
      <CardHead title="Ready to deliver" hint="Share of owed goods in hand" />
      <div className="flex min-h-0 flex-1 flex-col items-center px-5 pt-1 pb-4">
        <div className="relative flex min-h-0 w-full flex-1 items-end justify-center">
          <svg viewBox="-14 -14 248 134" className="h-full max-h-[150px] w-auto max-w-full">
            <path d={arc} pathLength={100} fill="none" strokeWidth={26} className="stroke-blue" />
            <motion.path
              d={arc}
              pathLength={100}
              fill="none"
              strokeWidth={26}
              className="stroke-peri"
              initial={{ strokeDasharray: '0 100' }}
              animate={{ strokeDasharray: `${Math.max(0, share - gap)} 100` }}
              transition={{ duration: 1.1, ease }}
            />
          </svg>
          <div className="absolute inset-x-0 bottom-0 text-center">
            <span className="num text-[28px] leading-none font-semibold tracking-[-0.035em]">{data ? <CountUp value={share} format={(v) => `${Math.round(v)}%`} /> : '—'}</span>
          </div>
        </div>
        <div className="mt-3 flex shrink-0 gap-4 text-[11.5px] text-fg-2">
          <span className="flex items-center gap-1.5">
            <span className="size-2.5 rounded-full bg-peri" /> Ready {data ? fmtQty(ready) : ''}
          </span>
          <span className="flex items-center gap-1.5">
            <span className="size-2.5 rounded-full bg-blue" /> To come {data ? fmtQty(owed - ready) : ''}
          </span>
        </div>
      </div>
    </Card>
  )
}

/* ---------------------------------------------------------------- the black card */
function ProfitCard({ data }: { data?: InventorySummaryOut }) {
  const revenue = n(data?.revenue_delivered)
  const cost = Math.max(0, n(data?.cost_of_goods_sold))
  const profit = n(data?.gross_profit)
  const costShare = revenue > 0 ? Math.min(100, (cost / revenue) * 100) : 0
  return (
    <Card dark className="col-span-4 justify-between gap-3 p-6 max-lg:min-h-[240px]" delay={0.14}>
      <div>
        <h2 className="text-[17px] font-semibold tracking-[-0.02em]">Gross profit</h2>
        <p className="mt-0.5 text-[12px] opacity-55">On goods delivered so far</p>
      </div>
      <div>
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className={cn('num text-[32px] leading-none font-semibold tracking-[-0.035em]', profit < 0 && 'text-bad')}>{data ? <CountUp value={profit} format={fmtMoneyRound} /> : '—'}</span>
          <span className="text-[12.5px] opacity-60">{data ? `${fmtPercent(data.margin_percent)} margin` : ''}</span>
        </div>
        <div className="mt-4 flex h-9 gap-1.5">
          <motion.div className="h-full min-w-[8px] rounded-[10px] bg-peri" initial={{ width: 0 }} animate={{ width: `${costShare}%` }} transition={{ duration: 1, ease }} />
          <motion.div className="h-full min-w-[8px] flex-1 rounded-[10px] bg-[#fff]" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.5 }} />
        </div>
        <div className="mt-2.5 flex justify-between text-[11.5px]">
          <span className="flex items-center gap-1.5 opacity-70">
            <span className="size-2 rounded-full bg-peri" /> Cost {fmtMoneyRound(cost)}
          </span>
          <span className="flex items-center gap-1.5 opacity-70">
            Revenue {fmtMoneyRound(revenue)} <span className="size-2 rounded-full bg-[#fff]" />
          </span>
        </div>
      </div>
    </Card>
  )
}

/* ---------------------------------------------------------------- bars */
/** Booked against delivered, in six five-day spans. */
function SalesBars({ data }: { data?: InventorySummaryOut }) {
  const [hover, setHover] = useState<number | null>(null)
  const buckets = useMemo(() => {
    const days = data?.daily_sales ?? []
    const size = Math.max(1, Math.ceil(days.length / 6))
    const out: { label: string; range: string; booked: number; delivered: number; orders: number }[] = []
    for (let start = 0; start < days.length; start += size) {
      const span = days.slice(start, start + size)
      const first = span[0].date
      const last = span[span.length - 1].date
      out.push({
        label: fmtShortDate(last),
        range: `${fmtShortDate(first)} – ${fmtShortDate(last)}`,
        booked: span.reduce((sum, day) => sum + n(day.booked_value), 0),
        delivered: span.reduce((sum, day) => sum + n(day.delivered_value), 0),
        orders: span.reduce((sum, day) => sum + day.orders, 0),
      })
    }
    return out
  }, [data])
  const total = buckets.reduce((sum, bucket) => sum + bucket.booked, 0)
  const top = niceMax(Math.max(1, ...buckets.map((bucket) => Math.max(bucket.booked, bucket.delivered))))
  const ticks = [1, 0.75, 0.5, 0.25, 0].map((fraction) => top * fraction)

  return (
    <Card className="col-span-5 col-start-8 row-span-2 row-start-1 max-lg:h-[420px] max-lg:shrink-0" delay={0.08}>
      <CardHead
        title="Sales"
        hint="Last 30 days, in five-day spans"
        actions={
          <div className="flex items-center gap-3 pt-1 text-[11.5px] text-fg-2">
            <span className="flex items-center gap-1.5">
              <span className="size-2.5 rounded-full bg-peri" /> Booked
            </span>
            <span className="flex items-center gap-1.5">
              <span className="size-2.5 rounded-full bg-blue" /> Delivered
            </span>
          </div>
        }
      />
      <div className="px-6">
        <span className="num text-[30px] font-semibold tracking-[-0.035em]">{data ? <CountUp value={total} format={fmtMoneyRound} /> : <Skeleton className="h-7 w-40" />}</span>
      </div>
      <div className="relative min-h-0 flex-1 px-6 pt-4 pb-5">
        <div className="relative flex h-full">
          <div className="flex w-12 shrink-0 flex-col justify-between pb-6 text-[10.5px] text-fg-4">
            {ticks.map((tick) => (
              <span key={tick} className="num -translate-y-1/2 leading-none">
                {fmtCompactMoney(tick)}
              </span>
            ))}
          </div>
          <div className="relative flex min-w-0 flex-1 flex-col">
            <div className="pointer-events-none absolute inset-x-0 top-0 bottom-6 flex flex-col justify-between">
              {ticks.map((tick) => (
                <span key={tick} className={cn('h-px w-full', tick === 0 ? 'bg-white/12' : 'border-t border-dashed border-white/8')} />
              ))}
            </div>
            <div className="relative flex min-h-0 flex-1 items-end justify-around gap-2">
              {buckets.map((bucket, index) => (
                <div
                  key={bucket.range}
                  className="relative flex h-full w-full max-w-[44px] flex-col justify-end"
                  onMouseEnter={() => setHover(index)}
                  onMouseLeave={() => setHover(null)}
                >
                  <motion.div
                    className={cn('relative w-full overflow-hidden rounded-[12px] bg-peri transition-opacity', hover !== null && hover !== index && 'opacity-45')}
                    initial={{ height: 0 }}
                    animate={{ height: `${(bucket.booked / top) * 100}%` }}
                    transition={{ duration: 0.9, delay: 0.15 + index * 0.06, ease }}
                    style={{ minHeight: bucket.booked > 0 ? 6 : 0 }}
                  >
                    <motion.div
                      className="absolute inset-x-0 bottom-0 rounded-[12px] bg-blue"
                      initial={{ height: 0 }}
                      animate={{ height: `${bucket.booked > 0 ? Math.min(100, (bucket.delivered / bucket.booked) * 100) : 0}%` }}
                      transition={{ duration: 0.9, delay: 0.45 + index * 0.06, ease }}
                    />
                  </motion.div>
                  {hover === index ? (
                    <div className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-2 w-max -translate-x-1/2 rounded-xl bg-contrast px-3 py-2 text-[11.5px] text-on-contrast shadow-pop animate-fade">
                      <div className="font-semibold">{bucket.range}</div>
                      <div className="num mt-0.5 opacity-80">Booked {fmtMoney(bucket.booked)}</div>
                      <div className="num opacity-80">Delivered {fmtMoney(bucket.delivered)}</div>
                      <div className="opacity-60">{plural(bucket.orders, 'order')}</div>
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
            <div className="flex h-6 shrink-0 items-end justify-around gap-2">
              {buckets.map((bucket) => (
                <span key={bucket.range} className="w-full max-w-[44px] text-center text-[11px] whitespace-nowrap text-fg-3">
                  {bucket.label}
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>
    </Card>
  )
}

function niceMax(value: number) {
  const power = 10 ** Math.floor(Math.log10(value))
  const step = [1, 2, 2.5, 5, 10].find((candidate) => candidate * power >= value) ?? 10
  return step * power
}

/* ---------------------------------------------------------------- table board */
function Board({ data }: { data?: InventorySummaryOut }) {
  const [tab, setTab] = useState<'orders' | 'buy' | 'receive'>('orders')
  const navigate = useNavigate()
  const incoming = useList('purchase-orders', api.purchaseOrders.list, { status: 'ORDERED,PARTIALLY_RECEIVED', limit: 50 })
  const pos = (incoming.data?.items ?? []).filter((po) => po.can_receive)
  const short = data?.products_short ?? []
  const orders = data?.recent_orders ?? []
  return (
    <Card className="col-span-7 max-lg:h-[440px] max-lg:shrink-0" delay={0.18}>
      <CardHead
        title={tab === 'orders' ? 'Recent orders' : tab === 'buy' ? 'To buy' : 'To receive'}
        actions={
          <Segmented
            value={tab}
            onChange={setTab}
            options={[
              { value: 'orders', label: 'Orders' },
              { value: 'buy', label: 'Buy', count: short.length },
              { value: 'receive', label: 'Receive', count: pos.length },
            ]}
          />
        }
      />
      <div className="min-h-0 flex-1 overflow-auto pb-2">
        {tab === 'orders' ? (
          !data ? (
            <div className="space-y-3 px-6 py-3">{Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-4" />)}</div>
          ) : orders.length === 0 ? (
            <Empty icon={<ReceiptText size={20} />} title="No orders yet" />
          ) : (
            <table className="grid-table">
              <thead>
                <tr>
                  <th>Order</th>
                  <th>Date</th>
                  <th>Customer</th>
                  <th>Status</th>
                  <th className="r">Amount</th>
                </tr>
              </thead>
              <tbody>
                {orders.map((order) => (
                  <tr key={order.id} onClick={() => navigate(`/orders/${order.id}`)} className="cursor-default">
                    <td className="num text-[13px] font-medium">{order.order_number}</td>
                    <td className="text-[12.5px] text-fg-3">{fmtShortDate(order.created_at)}</td>
                    <td className="max-w-[200px] truncate text-[13px]">{order.customer_name}</td>
                    <td>
                      <OrderBadge status={order.status} />
                    </td>
                    <td className="r num text-[13px] font-semibold">{fmtMoney(order.total_amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        ) : tab === 'buy' ? (
          short.length === 0 ? (
            <Empty icon={<PackageCheck size={20} />} title="Nothing to buy" body="Every product covers what has been sold." />
          ) : (
            <div className="px-3">
              {short.map((row) => (
                <Row key={row.product_id} to={`/products/${row.product_id}`} icon={<AlertTriangle size={15} />} tone="bad" title={row.name} meta={`${row.sku} · buy ${fmtQty(-n(row.stock))} ${row.unit_of_measure} to cover orders`} trail={<span className="num text-[13px] font-semibold text-bad">−{fmtQty(-n(row.stock))}</span>} />
              ))}
            </div>
          )
        ) : pos.length === 0 ? (
          <Empty icon={<PackageOpen size={20} />} title="Nothing on the way" body="No purchase order is waiting for delivery." />
        ) : (
          <div className="px-3">
            {pos.map((po) => (
              <Row key={po.id} to={`/receipts?new=1&po=${po.id}`} icon={<PackageOpen size={15} />} title={`${po.po_number} · ${po.supplier.name}`} meta={`${fmtQty(po.total_remaining)} still to arrive`} trail={<PurchaseBadge status={po.status} />} />
            ))}
          </div>
        )}
      </div>
    </Card>
  )
}

function Row({ to, icon, title, meta, trail, tone }: { to: string; icon: ReactNode; title: string; meta: string; trail: ReactNode; tone?: 'bad' }) {
  return (
    <Link to={to} className="group flex items-center gap-3 rounded-[14px] px-3 py-2.5 transition-colors hover:bg-white/[0.04]">
      <IconDot tone={tone}>{icon}</IconDot>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px] font-medium">{title}</span>
        <span className="block truncate text-[12px] text-fg-3">{meta}</span>
      </span>
      {trail}
      <ChevronRight size={14} className="text-fg-4 transition group-hover:translate-x-0.5 group-hover:text-fg-2" />
    </Link>
  )
}

/* ---------------------------------------------------------------- dots */
/** Orders booked on each of the last seven days, one dot per order. */
function OrderDots({ data }: { data?: InventorySummaryOut }) {
  const days = (data?.daily_sales ?? []).slice(-7)
  const peak = Math.max(1, ...days.map((day) => day.orders))
  const rows = Math.min(8, Math.max(5, peak))
  const per = peak > rows ? peak / rows : 1
  return (
    <Card className="col-span-5 max-lg:h-[300px] max-lg:shrink-0" delay={0.22}>
      <CardHead title="Orders this week" hint={days.length && days.every((day) => day.orders === 0) ? 'No orders booked in the last seven days' : per > 1 ? `Each dot about ${Math.round(per)} orders` : 'Each dot one order'} />
      <div className="flex min-h-0 flex-1 items-stretch justify-around gap-2 px-6 pt-2 pb-4">
        {days.map((day, column) => {
          const filled = Math.round(day.orders / per)
          const [y, m, d] = day.date.split('-').map(Number)
          const weekday = new Date(y, m - 1, d).toLocaleDateString('en-IN', { weekday: 'short' })
          return (
            <div key={day.date} className="flex min-w-0 flex-1 flex-col items-center gap-2" title={`${weekday}: ${plural(day.orders, 'order')}`}>
              <div className="grid min-h-0 w-full flex-1 justify-items-center gap-[5px]" style={{ gridTemplateRows: `repeat(${rows}, minmax(0, 1fr))` }}>
                {Array.from({ length: rows }, (_, slot) => rows - 1 - slot).map((index) => (
                  <motion.span
                    key={index}
                    className={cn('aspect-square h-full max-h-[24px] rounded-full', index < filled ? 'bg-blue' : 'bg-peri/35')}
                    initial={{ scale: 0 }}
                    animate={{ scale: 1 }}
                    transition={{ delay: 0.25 + column * 0.04 + index * 0.025, type: 'spring', stiffness: 420, damping: 22 }}
                  />
                ))}
              </div>
              <span className="text-[11px] text-fg-3">{weekday}</span>
            </div>
          )
        })}
      </div>
    </Card>
  )
}
