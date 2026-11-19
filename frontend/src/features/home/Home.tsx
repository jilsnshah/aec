import { useMemo, useState, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { motion } from 'motion/react'
import { AlertTriangle, ArrowUpRight, ChevronRight, PackageCheck, PackageOpen, Plus, ReceiptText, Truck } from 'lucide-react'
import { api } from '@/api/endpoints'
import { useList, useSummary } from '@/api/queries'
import type { InventorySummaryOut } from '@/api/types'
import { useAuth } from '@/app/auth'
import { cn } from '@/lib/cn'
import { fmtAgo, fmtCompactMoney, fmtMoney, fmtMoneyRound, fmtPercent, fmtQty, fmtToday, n, plural } from '@/lib/format'
import { OrderBadge, PurchaseBadge } from '@/lib/status'
import { AreaChart } from '@/ui/AreaChart'
import { Aurora } from '@/ui/Aurora'
import { Button, CountUp, Empty, Skeleton } from '@/ui/core'
import { Segmented } from '@/ui/overlays'

const greeting = () => {
  const hour = new Date().getHours()
  return hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening'
}

/** Today at a glance: one board that fits the window. */
export function Home() {
  const summary = useSummary()
  const data = summary.data
  return (
    <div className="grid h-full min-h-0 grid-cols-12 grid-rows-[auto_minmax(0,1fr)_minmax(0,1fr)] gap-3 p-3 pl-0 max-lg:flex max-lg:flex-col max-lg:overflow-y-auto max-md:p-2">
      <Hero data={data} />
      <Kpis data={data} />
      <SalesPanel data={data} />
      <TradingPanel data={data} />
      <TodoPanel data={data} />
      <ActivityPanel data={data} />
    </div>
  )
}

function Tile({ className, children, delay = 0 }: { className?: string; children: ReactNode; delay?: number }) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45, delay, ease: [0.22, 1, 0.36, 1] }}
      className={cn('pane relative flex min-h-0 flex-col overflow-hidden', className)}
    >
      {children}
    </motion.section>
  )
}

function TileHead({ title, hint, actions }: { title: string; hint?: string; actions?: ReactNode }) {
  return (
    <header className="flex shrink-0 items-center gap-3 px-5 pt-4 pb-3">
      <div className="min-w-0 flex-1">
        <h2 className="text-[14px] font-semibold">{title}</h2>
        {hint ? <p className="text-[12px] text-fg-3">{hint}</p> : null}
      </div>
      {actions}
    </header>
  )
}

function Hero({ data }: { data?: InventorySummaryOut }) {
  const { user } = useAuth()
  const navigate = useNavigate()
  const month = useMemo(() => (data ? data.daily_sales.reduce((sum, day) => sum + n(day.booked_value), 0) : 0), [data])
  return (
    <Tile className="col-span-5 shrink-0 justify-between p-5">
      <Aurora strength={1.3} />
      <div className="relative">
        <p className="text-[12px] text-fg-3">{fmtToday()}</p>
        <h1 className="mt-1 text-[22px] font-semibold tracking-[-0.022em]">
          {greeting()}, {user?.username}
        </h1>
        <p className="mt-2 text-[13px] text-fg-2">
          {data ? (
            <>
              <span className="num font-semibold text-sky">{fmtMoneyRound(month)}</span> booked in the last 30 days
            </>
          ) : (
            <Skeleton className="w-48" />
          )}
        </p>
      </div>
      <div className="relative mt-4 flex flex-wrap gap-2">
        <Button kind="primary" small icon={<Plus size={14} strokeWidth={2.4} />} onClick={() => navigate('/orders?new=1')}>
          Sales order
        </Button>
        <Button small icon={<PackageOpen size={14} />} onClick={() => navigate('/receipts?new=1')}>
          Receive goods
        </Button>
        <Button small icon={<Truck size={14} />} onClick={() => navigate('/fulfilment')}>
          Deliver
        </Button>
      </div>
    </Tile>
  )
}

function Kpis({ data }: { data?: InventorySummaryOut }) {
  const items = [
    { label: 'To deliver', value: data?.total_pending_quantity, hint: data ? `${plural(data.open_orders, 'open order')}` : '', to: '/fulfilment', icon: <Truck size={15} /> },
    { label: 'Ready to deliver', value: data?.total_reserved_stock, hint: 'in hand, truck not gone', to: '/fulfilment?lane=ready', icon: <PackageCheck size={15} /> },
    { label: 'Short', value: data?.total_unallocated_quantity, hint: 'sold, not bought yet', to: '/fulfilment?lane=short', icon: <AlertTriangle size={15} />, alert: n(data?.total_unallocated_quantity) > 0 },
    { label: 'Products short', value: data ? String(data.products_short.length) : undefined, hint: 'sold more than bought', to: '/products', icon: <AlertTriangle size={15} />, alert: (data?.products_short.length ?? 0) > 0 },
  ]
  return (
    <div className="col-span-7 grid shrink-0 grid-cols-4 gap-3 max-md:grid-cols-2">
      {items.map((item, index) => (
        <Tile key={item.label} delay={0.04 * (index + 1)}>
          <Link to={item.to} className="group flex h-full flex-col justify-between p-4 transition-colors hover:bg-white/[0.02]">
            <div className="flex items-center justify-between">
              <span className="text-[12px] font-medium text-fg-2">{item.label}</span>
              <span className={cn('grid size-7 place-items-center rounded-lg', item.alert ? 'bg-bad/12 text-bad' : 'bg-sky/10 text-sky')}>{item.icon}</span>
            </div>
            <div>
              <div className={cn('text-[30px] font-semibold tracking-[-0.03em]', item.alert && 'text-bad')}>
                {item.value !== undefined ? <CountUp value={n(item.value)} format={(v) => fmtQty(Math.round(v * 1000) / 1000)} /> : <Skeleton className="my-3 h-6 w-16" />}
              </div>
              <div className="flex items-center justify-between text-[11.5px] text-fg-3">
                {item.hint}
                <ArrowUpRight size={13} className="opacity-0 transition group-hover:opacity-100" />
              </div>
            </div>
          </Link>
        </Tile>
      ))}
    </div>
  )
}

function SalesPanel({ data }: { data?: InventorySummaryOut }) {
  const [measure, setMeasure] = useState<'booked' | 'delivered'>('booked')
  const points = useMemo(() => {
    let running = 0
    return (data?.daily_sales ?? []).map((day) => {
      const [y, m, d] = day.date.split('-').map(Number)
      const date = new Date(y, m - 1, d)
      const value = n(measure === 'booked' ? day.booked_value : day.delivered_value)
      running += value
      return {
        label: date.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }),
        date,
        value: running,
        extra: `${fmtMoney(value)} that day${measure === 'booked' ? ` · ${plural(day.orders, 'order')}` : ''}`,
      }
    })
  }, [data, measure])
  const total = points.length ? points[points.length - 1].value : 0
  return (
    <Tile className="col-span-8 max-lg:h-[340px] max-lg:shrink-0" delay={0.12}>
      <TileHead
        title="Sales"
        hint={`Running total ${measure === 'booked' ? 'booked' : 'delivered'} over the last 30 days`}
        actions={
          <Segmented
            value={measure}
            onChange={setMeasure}
            options={[
              { value: 'booked', label: 'Booked' },
              { value: 'delivered', label: 'Delivered' },
            ]}
          />
        }
      />
      <div className="px-5">
        <div className="num text-[28px] font-semibold tracking-[-0.03em]">{data ? <CountUp value={total} format={fmtMoney} /> : <Skeleton className="h-7 w-40" />}</div>
      </div>
      <div className="min-h-0 flex-1 px-3 pt-2 pb-3">{data ? <AreaChart points={points} format={fmtMoney} tick={fmtCompactMoney} /> : null}</div>
    </Tile>
  )
}

function TradingPanel({ data }: { data?: InventorySummaryOut }) {
  const rows = data
    ? [
        { label: 'Revenue delivered', value: fmtMoney(data.revenue_delivered) },
        { label: 'Cost of goods', value: fmtMoney(data.cost_of_goods_sold) },
        { label: 'Discounts given', value: fmtMoney(data.discounts_given) },
        { label: 'Spent on stock', value: fmtMoney(data.purchase_spend) },
        { label: 'Value in warehouse', value: fmtMoney(data.total_stock_value) },
        { label: 'Still to deliver', value: fmtMoney(data.outstanding_order_value) },
      ]
    : []
  const profit = n(data?.gross_profit)
  return (
    <Tile className="col-span-4 max-lg:shrink-0" delay={0.16}>
      <TileHead title="Trading" hint="Counts delivered goods only" />
      <div className="mx-5 rounded-xl bg-gradient-to-br from-sky/[0.12] to-sky/[0.03] px-4 py-3 ring-1 ring-sky/15 ring-inset">
        <div className="text-[12px] text-fg-2">Gross profit</div>
        <div className="mt-0.5 flex items-baseline justify-between">
          <span className={cn('num text-[24px] font-semibold tracking-[-0.025em]', profit < 0 && 'text-bad')}>{data ? <CountUp value={profit} format={fmtMoney} /> : '—'}</span>
          <span className="num text-[13px] font-medium text-sky">{data ? fmtPercent(data.margin_percent) : ''} margin</span>
        </div>
      </div>
      <dl className="min-h-0 flex-1 overflow-y-auto px-5 py-2">
        {rows.map((row) => (
          <div key={row.label} className="flex items-baseline justify-between border-b border-white/5 py-[6px] last:border-0">
            <dt className="text-[13px] text-fg-3">{row.label}</dt>
            <dd className="num text-[13px] font-medium">{row.value}</dd>
          </div>
        ))}
      </dl>
    </Tile>
  )
}

function TodoPanel({ data }: { data?: InventorySummaryOut }) {
  const [tab, setTab] = useState<'short' | 'incoming'>('short')
  const incoming = useList('purchase-orders', api.purchaseOrders.list, { status: 'ORDERED,PARTIALLY_RECEIVED', limit: 50 })
  const pos = (incoming.data?.items ?? []).filter((po) => po.can_receive)
  const short = data?.products_short ?? []
  return (
    <Tile className="col-span-6 max-lg:h-[360px] max-lg:shrink-0" delay={0.2}>
      <TileHead
        title="To do"
        actions={
          <Segmented
            value={tab}
            onChange={setTab}
            options={[
              { value: 'short', label: 'Buy', count: short.length },
              { value: 'incoming', label: 'Receive', count: pos.length },
            ]}
          />
        }
      />
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {tab === 'short' ? (
          short.length === 0 ? (
            <Empty icon={<PackageCheck size={20} />} title="Nothing to buy" body="Every product covers what has been sold." />
          ) : (
            short.map((row) => (
              <Row key={row.product_id} to={`/products/${row.product_id}`} icon={<AlertTriangle size={15} />} tone="bad" title={row.name} meta={`${row.sku} · buy ${fmtQty(-n(row.stock))} ${row.unit_of_measure} to cover orders`} trail={<span className="num text-[13px] font-semibold text-bad">−{fmtQty(-n(row.stock))}</span>} />
            ))
          )
        ) : pos.length === 0 ? (
          <Empty icon={<PackageOpen size={20} />} title="Nothing on the way" body="No purchase order is waiting for delivery." />
        ) : (
          pos.map((po) => (
            <Row key={po.id} to={`/receipts?new=1&po=${po.id}`} icon={<PackageOpen size={15} />} tone="sky" title={`${po.po_number} · ${po.supplier.name}`} meta={`${fmtQty(po.total_remaining)} still to arrive`} trail={<PurchaseBadge status={po.status} />} />
          ))
        )}
      </div>
    </Tile>
  )
}

function ActivityPanel({ data }: { data?: InventorySummaryOut }) {
  const events = useMemo(() => {
    if (!data) return []
    return [
      ...data.recent_orders.map((order) => ({
        key: `o${order.id}`,
        at: order.created_at,
        to: `/orders/${order.id}`,
        icon: <ReceiptText size={15} />,
        title: `${order.order_number} · ${order.customer_name}`,
        meta: `${fmtAgo(order.created_at)} · ${plural(order.line_count, 'line')} · ${fmtMoney(order.total_amount)}`,
        trail: <OrderBadge status={order.status} />,
      })),
      ...data.recent_receipts.map((receipt) => ({
        key: `r${receipt.id}`,
        at: receipt.created_at,
        to: `/products/${receipt.product_id}`,
        icon: <PackageOpen size={15} />,
        title: `${receipt.receipt_number} · ${receipt.product_name}`,
        meta: `${fmtAgo(receipt.created_at)} · ${fmtQty(receipt.quantity)} ${receipt.unit_of_measure} in`,
        trail: <span className="num text-[12px] text-fg-3">{fmtMoney(receipt.total_cost)}</span>,
      })),
    ]
      .sort((a, b) => new Date(b.at).getTime() - new Date(a.at).getTime())
      .slice(0, 12)
  }, [data])
  return (
    <Tile className="col-span-6 max-lg:h-[420px] max-lg:shrink-0" delay={0.24}>
      <TileHead title="Recent activity" hint="Orders and stock as they happen" />
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {events.length === 0 && data ? <Empty title="No activity yet" /> : events.map(({ key, ...event }) => <Row key={key} {...event} tone="muted" />)}
      </div>
    </Tile>
  )
}

function Row({ to, icon, title, meta, trail, tone }: { to: string; icon: ReactNode; title: string; meta: string; trail: ReactNode; tone: 'bad' | 'sky' | 'muted' }) {
  return (
    <Link to={to} className="group flex items-center gap-3 rounded-[10px] px-3 py-2.5 transition-colors hover:bg-white/[0.035]">
      <span className={cn('grid size-8 shrink-0 place-items-center rounded-lg', tone === 'bad' && 'bg-bad/12 text-bad', tone === 'sky' && 'bg-sky/10 text-sky', tone === 'muted' && 'bg-white/5 text-fg-2')}>{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px] font-medium">{title}</span>
        <span className="block truncate text-[12px] text-fg-3">{meta}</span>
      </span>
      {trail}
      <ChevronRight size={14} className="text-fg-4 transition group-hover:translate-x-0.5 group-hover:text-fg-2" />
    </Link>
  )
}
