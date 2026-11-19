import { useMemo, useState, type ReactNode } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { motion } from 'motion/react'
import { AlertTriangle, ArrowDown, ArrowUp, ArrowUpRight, BarChart3, Boxes, CalendarDays, ChevronRight, Gauge, PackageCheck, PackageOpen, ReceiptText, SlidersHorizontal, Sparkles, Target, TrendingUp, Truck, Wallet, Zap } from 'lucide-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { errorText } from '@/api/client'
import { finance, workspace } from '@/api/finance'
import { insights } from '@/api/insights'
import { useAssistant } from '@/features/assistant/store'
import { SEVERITY_DOT } from '@/features/insights/AlertsBell'
import { api } from '@/api/endpoints'
import { useList, useSummary } from '@/api/queries'
import type { InventorySummaryOut } from '@/api/types'
import { useAuth } from '@/app/auth'
import { cn } from '@/lib/cn'
import { fmtCompactMoney, fmtMoney, fmtMoneyRound, fmtPercent, fmtQty, fmtShortDate, fmtToday, n, plural } from '@/lib/format'
import { OrderBadge, PurchaseBadge, STATE } from '@/lib/status'
import { Contours } from '@/ui/art'
import { Button, CountUp, Empty, Meter, Skeleton, Toggle } from '@/ui/core'
import { Segmented, Sheet } from '@/ui/overlays'

const ease = [0.22, 1, 0.36, 1] as const

const greeting = () => {
  const hour = new Date().getHours()
  return hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening'
}

type WidgetKey = 'kpis' | 'money' | 'target' | 'priorities' | 'gauge' | 'profit' | 'sales' | 'board' | 'dots'
const WIDGETS: { key: WidgetKey; label: string; hint: string; className: string }[] = [
  { key: 'kpis', label: 'Key figures', hint: 'To deliver, delivered, short', className: 'col-span-7 h-[190px]' },
  { key: 'money', label: 'Money', hint: 'Owed to you, owed by you, cash in', className: 'col-span-5 h-[190px]' },
  { key: 'priorities', label: "Today's priorities", hint: 'What to act on, with one-click actions', className: 'col-span-5 h-[400px]' },
  { key: 'sales', label: 'Sales', hint: 'Booked and delivered, 30 days', className: 'col-span-7 h-[400px]' },
  { key: 'target', label: 'Target', hint: 'This month against your target', className: 'col-span-4 h-[290px]' },
  { key: 'gauge', label: 'Ready to deliver', hint: 'Share of owed goods in hand', className: 'col-span-3 h-[290px]' },
  { key: 'profit', label: 'Gross profit', hint: 'On goods delivered', className: 'col-span-5 h-[290px]' },
  { key: 'board', label: 'Recent orders', hint: 'With to-buy and to-receive tabs', className: 'col-span-7 h-[420px]' },
  { key: 'dots', label: 'Orders this week', hint: 'One dot per order', className: 'col-span-5 h-[420px]' },
]
type Layout = { order: WidgetKey[]; hidden: WidgetKey[] }
const DEFAULT_LAYOUT: Layout = { order: WIDGETS.map((w) => w.key), hidden: [] }

/** The command centre: what matters today, each figure a door to the detail.
 *  Widgets can be hidden and re-ordered; the layout is saved per user. */
export function Home() {
  const summary = useSummary()
  const data = summary.data
  const { user } = useAuth()
  const client = useQueryClient()
  const saved = useQuery({ queryKey: ['preferences', 'home.layout'], queryFn: () => workspace.preference<Layout>('home.layout') })
  const layout: Layout = useMemo(() => {
    const value = saved.data?.value
    if (!value) return DEFAULT_LAYOUT
    const order = [...value.order.filter((key) => WIDGETS.some((w) => w.key === key)), ...WIDGETS.map((w) => w.key).filter((key) => !value.order.includes(key))]
    return { order, hidden: value.hidden ?? [] }
  }, [saved.data])
  const [searchParams, setSearchParams] = useSearchParams()
  const [customising, setCustomisingState] = useState(searchParams.get('customise') === '1')
  const setCustomising = (value: boolean) => {
    setCustomisingState(value)
    if (!value && searchParams.get('customise')) setSearchParams({}, { replace: true })
  }
  async function save(next: Layout) {
    client.setQueryData(['preferences', 'home.layout'], { key: 'home.layout', value: next })
    try {
      await workspace.setPreference('home.layout', next)
    } catch (error) {
      toast.error(errorText(error))
    }
  }
  const render: Record<WidgetKey, ReactNode> = {
    kpis: <Kpis data={data} />,
    money: <MoneyCard />,
    target: <TargetCard />,
    priorities: <Priorities />,
    gauge: <ReadyGauge data={data} />,
    profit: <ProfitCard data={data} />,
    sales: <SalesBars data={data} />,
    board: <Board data={data} />,
    dots: <OrderDots data={data} />,
  }
  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto px-6 pb-24 max-md:px-2 max-md:pb-20">
      <Hero data={data} name={user?.username ?? ''} onCustomise={() => setCustomising(true)} />
      <div className="grid grid-flow-dense grid-cols-12 gap-4 max-lg:flex max-lg:flex-col max-md:gap-2">
        {layout.order
          .filter((key) => !layout.hidden.includes(key))
          .map((key) => {
            const widget = WIDGETS.find((w) => w.key === key)!
            return (
              <div key={key} className={cn(widget.className, 'min-h-0 max-lg:h-auto max-lg:min-h-[220px]')}>
                {render[key]}
              </div>
            )
          })}
      </div>
      <Sheet open={customising} onClose={() => setCustomising(false)} title="Customise Home" subtitle="Show, hide and order the panels. Saved for you on every device." width={520}>
        <div className="space-y-1.5">
          {layout.order.map((key, index) => {
            const widget = WIDGETS.find((w) => w.key === key)!
            const shown = !layout.hidden.includes(key)
            return (
              <div key={key} className="card flex items-center gap-3 px-3 py-2.5">
                <Toggle checked={shown} label={`Show ${widget.label}`} onChange={(value) => void save({ order: layout.order, hidden: value ? layout.hidden.filter((k) => k !== key) : [...layout.hidden, key] })} />
                <span className="min-w-0 flex-1">
                  <span className="block text-[13px] font-medium">{widget.label}</span>
                  <span className="block text-[11.5px] text-fg-3">{widget.hint}</span>
                </span>
                <Button small kind="ghost" iconOnly aria-label={`Move ${widget.label} up`} disabled={index === 0} onClick={() => void save({ ...layout, order: move(layout.order, index, -1) })}>
                  <ArrowUp size={13} />
                </Button>
                <Button small kind="ghost" iconOnly aria-label={`Move ${widget.label} down`} disabled={index === layout.order.length - 1} onClick={() => void save({ ...layout, order: move(layout.order, index, 1) })}>
                  <ArrowDown size={13} />
                </Button>
              </div>
            )
          })}
          <Button kind="ghost" small onClick={() => void save(DEFAULT_LAYOUT)}>
            Reset to the standard layout
          </Button>
        </div>
      </Sheet>
    </div>
  )
}

function move<T>(list: T[], index: number, delta: number): T[] {
  const next = [...list]
  const [item] = next.splice(index, 1)
  next.splice(index + delta, 0, item)
  return next
}

/* ---------------------------------------------------------------- money */
function MoneyCard() {
  const receivables = useQuery({ queryKey: ['finance', 'receivables'], queryFn: finance.receivables })
  const payables = useQuery({ queryKey: ['finance', 'payables'], queryFn: finance.payables })
  const month = useQuery({ queryKey: ['insights', 'overview', 'month'], queryFn: () => insights.overview('month') })
  const items = [
    { label: 'Customers owe', value: receivables.data?.totals.open, hint: receivables.data ? `${fmtMoneyRound(receivables.data.totals.overdue)} overdue` : '', to: '/finance?tab=receivables', alert: (receivables.data?.totals.overdue ?? 0) > 0 },
    { label: 'You owe suppliers', value: payables.data?.totals.open, hint: payables.data ? `${fmtMoneyRound(payables.data.totals.overdue)} overdue` : '', to: '/finance?tab=payables' },
    { label: 'Collected this month', value: month.data?.current.cash_received, hint: month.data ? `${fmtMoneyRound(month.data.current.cash_paid ?? 0)} paid out` : '', to: '/finance?tab=payments' },
  ]
  return (
    <Card lift className="h-full">
      <div className="grid h-full grid-cols-3 divide-x divide-white/6">
        {items.map((item) => (
          <Link key={item.label} to={item.to} className="group flex flex-col justify-between p-5">
            <span className="flex items-center gap-2 text-[13px] font-medium">
              <span className={cn('size-8 shrink-0', item.alert ? 'grid place-items-center rounded-full bg-bad/12 text-bad' : 'icon-disc')}>
                <Wallet size={14} />
              </span>
              {item.label}
            </span>
            <span>
              <span className={cn('num block text-[24px] leading-none font-light tracking-[-0.035em]', item.alert && 'font-normal')}>{item.value === undefined ? <Skeleton className="h-6 w-20" /> : fmtMoneyRound(item.value)}</span>
              <span className="mt-1.5 block text-[11.5px] text-fg-3">{item.hint}</span>
            </span>
          </Link>
        ))}
      </div>
    </Card>
  )
}

/* ---------------------------------------------------------------- target */
function TargetCard() {
  const client = useQueryClient()
  const month = useQuery({ queryKey: ['insights', 'overview', 'month'], queryFn: () => insights.overview('month') })
  const [editing, setEditing] = useState(false)
  const [amount, setAmount] = useState('')
  const target = month.data?.target?.booked
  const thisMonth = new Date().toISOString().slice(0, 7)
  async function save() {
    if (!(Number(amount) >= 0)) return
    try {
      await workspace.setTarget({ month: thisMonth, metric: 'booked', amount })
      client.invalidateQueries({ queryKey: ['insights'] })
      setEditing(false)
      toast.success('Target saved')
    } catch (error) {
      toast.error(errorText(error))
    }
  }
  return (
    <Card className="h-full">
      <CardHead icon={<Target size={17} />} title="This month's target" hint="Orders booked against the target you set" actions={<Button small kind="ghost" onClick={() => { setAmount(target ? String(target.target) : ''); setEditing(true) }}>{target ? 'Change' : 'Set'}</Button>} />
      <div className="flex min-h-0 flex-1 flex-col justify-center px-6 pb-5">
        {editing ? (
          <form className="flex gap-2" onSubmit={(event) => { event.preventDefault(); void save() }}>
            <input className="field field-num" inputMode="decimal" autoFocus placeholder="Target, ₹" value={amount} onChange={(e) => setAmount(e.target.value)} />
            <Button kind="primary" type="submit">Save</Button>
          </form>
        ) : !target ? (
          <Empty title="No target for this month" body="Set one to track progress and see where the month is heading." />
        ) : (
          <>
            <div className="flex items-baseline justify-between">
              <span className="num text-[30px] leading-none font-light tracking-[-0.04em]">{fmtMoneyRound(target.actual)}</span>
              <span className="num text-[13px] text-fg-3">of {fmtMoneyRound(target.target)}</span>
            </div>
            <div className="relative mt-3 h-3 overflow-hidden rounded-full bg-white/[0.07]">
              <motion.div className="absolute inset-y-0 left-0 rounded-full bg-blue" initial={{ width: 0 }} animate={{ width: `${Math.min(100, target.percent ?? 0)}%` }} transition={{ duration: 1, ease }} />
              <span className="absolute inset-y-0 w-0.5 bg-solid" style={{ left: `${Math.min(100, (target.days_elapsed / target.days_in_month) * 100)}%` }} title="Where you should be today" />
            </div>
            <div className="mt-2 flex justify-between text-[11.5px] text-fg-3">
              <span>{target.percent ?? 0}% reached · day {target.days_elapsed} of {target.days_in_month}</span>
              <span>Estimate: {fmtMoneyRound(target.projected)} by month end</span>
            </div>
          </>
        )}
      </div>
    </Card>
  )
}

/* ---------------------------------------------------------------- priorities */
function Priorities() {
  const { ask } = useAssistant()
  const navigate = useNavigate()
  const alerts = useQuery({ queryKey: ['insights', 'alerts'], queryFn: insights.alerts })
  const list = alerts.data?.alerts ?? []
  return (
    <Card className="h-full">
      <CardHead
        icon={<Zap size={17} />}
        title="Today's priorities"
        hint={alerts.data ? `${alerts.data.counts.critical ?? 0} urgent · ${alerts.data.counts.warning ?? 0} to act on` : 'Checking…'}
        actions={
          <Button small icon={<Sparkles size={13} />} onClick={() => ask("Give me today's briefing: what happened, what needs attention first and why, and the concrete actions to take — with buttons to the right screens.")}>
            AI briefing
          </Button>
        }
      />
      <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
        {alerts.data && !list.length ? <Empty icon={<PackageCheck size={20} />} title="Nothing urgent" body="Every product, order and account looks fine." /> : null}
        {list.slice(0, 12).map((alert) => (
          <button key={alert.id} onClick={() => navigate(alert.link)} className="group flex w-full items-start gap-2.5 rounded-[14px] px-3 py-2 text-left hover:bg-white/[0.04]">
            <span className={cn('mt-1.5 size-2 shrink-0 rounded-full', SEVERITY_DOT[alert.severity])} />
            <span className="min-w-0 flex-1">
              <span className="block text-[12.5px] leading-snug font-medium">{alert.title}</span>
              <span className="block truncate text-[11.5px] text-fg-3">{alert.detail}</span>
            </span>
            <ChevronRight size={14} className="mt-1 text-fg-4 group-hover:text-fg-2" />
          </button>
        ))}
      </div>
    </Card>
  )
}

function Card({ className, children, delay = 0, dark, lift }: { className?: string; children: ReactNode; delay?: number; dark?: boolean; lift?: boolean }) {
  const surface = cn(dark ? 'pane-contrast' : 'pane', 'relative flex min-h-0 flex-col overflow-hidden')
  if (lift) {
    // The entrance animation owns the outer transform, so the hover lift lives on the inner surface.
    return (
      <motion.section initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, delay, ease }} className={cn('min-h-0', className)}>
        <div className={cn(surface, 'lift h-full')}>{children}</div>
      </motion.section>
    )
  }
  return (
    <motion.section initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, delay, ease }} className={cn(surface, className)}>
      {children}
    </motion.section>
  )
}

/** The greeting banner: bright blue, with the day's numbers as chips and a few
 *  floating icon tiles for decoration. */
function Hero({ data, name, onCustomise }: { data?: InventorySummaryOut; name: string; onCustomise: () => void }) {
  const incoming = useList('purchase-orders', api.purchaseOrders.list, { status: 'ORDERED,PARTIALLY_RECEIVED', limit: 50 })
  const arriving = (incoming.data?.items ?? []).filter((po) => po.can_receive).length
  const chips = data
    ? [
        { to: '/fulfilment?lane=ready', icon: <PackageCheck size={14} />, text: `${fmtQty(data.total_reserved_stock)} ready to load` },
        { to: '/fulfilment?lane=short', icon: <AlertTriangle size={14} />, text: `${plural(data.products_short?.length ?? 0, 'product')} to buy` },
        { to: '/receipts?new=1', icon: <PackageOpen size={14} />, text: `${plural(arriving, 'delivery', 'deliveries')} arriving` },
        { to: '/orders', icon: <ReceiptText size={14} />, text: plural(data.open_orders, 'open order') },
      ]
    : []
  const tiles = [
    { icon: <Truck size={22} />, className: 'right-[23%] top-[18%] size-14 rotate-[-8deg]', delay: 0 },
    { icon: <Boxes size={26} />, className: 'right-[12%] top-[34%] size-16 rotate-[6deg]', delay: 0.6 },
    { icon: <ReceiptText size={18} />, className: 'right-[4%] top-[12%] size-11 rotate-[-4deg]', delay: 1.2 },
  ]
  return (
    <motion.section
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease }}
      className="pane-contrast relative mb-4 flex shrink-0 flex-wrap items-center gap-x-8 gap-y-3 overflow-hidden px-7 py-5 max-md:mb-2 max-md:px-5 [&>*:not(.deco)]:relative"
    >
      <Contours className="deco absolute -top-[120%] right-[-6%] size-[520px] text-[rgb(255_255_255/0.55)]" rings={14} seed={9} />
      <div className="deco pointer-events-none absolute inset-0 max-xl:hidden" aria-hidden="true">
        {tiles.map((tile, index) => (
          <motion.span
            key={index}
            className={cn('glass-tile absolute', tile.className)}
            animate={{ y: [0, -6, 0] }}
            transition={{ duration: 5, repeat: Infinity, ease: 'easeInOut', delay: tile.delay }}
          >
            {tile.icon}
          </motion.span>
        ))}
      </div>
      <div className="min-w-0">
        <p className="flex items-center gap-1.5 text-[12.5px] opacity-80">
          <Sparkles size={13} /> {fmtToday()}
        </p>
        <h1 className="mt-0.5 text-[30px] font-light tracking-[-0.035em]">
          {greeting()}, {name}
        </h1>
      </div>
      <div className="flex flex-wrap gap-2 xl:max-w-[52%]">
        {chips.map((chip) => (
          <Link key={chip.to} to={chip.to} className="glass-tile flex! h-9 items-center gap-2 rounded-full! px-3.5 text-[12.5px] font-medium transition hover:bg-[rgb(255_255_255/0.85)]">
            {chip.icon}
            {chip.text}
          </Link>
        ))}
        <button onClick={onCustomise} className="glass-tile flex! h-9 items-center gap-2 rounded-full! px-3.5 text-[12.5px] font-medium transition hover:bg-[rgb(255_255_255/0.85)]">
          <SlidersHorizontal size={14} /> Customise
        </button>
      </div>
    </motion.section>
  )
}

function CardHead({ title, hint, actions, icon }: { title: string; hint?: string; actions?: ReactNode; icon?: ReactNode }) {
  return (
    <header className="flex shrink-0 items-start gap-3 px-6 pt-5 pb-2">
      {icon ? <span className="icon-disc size-10 shrink-0">{icon}</span> : null}
      <div className="min-w-0 flex-1">
        <h2 className="text-[17px] font-semibold tracking-[-0.02em]">{title}</h2>
        {hint ? <p className="mt-0.5 text-[12px] text-fg-3">{hint}</p> : null}
      </div>
      {actions}
    </header>
  )
}

const IconDot = ({ children, tone = 'peri' }: { children: ReactNode; tone?: 'peri' | 'bad' }) => (
  <span className={cn('size-9 shrink-0', tone === 'bad' ? 'grid place-items-center rounded-full bg-bad/12 text-bad ring-1 ring-bad/15 ring-inset' : 'icon-disc')}>{children}</span>
)

/** A small running-total line with a soft fill. */
function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) return <div className="h-9" />
  const max = Math.max(1, ...values)
  const points = values.map((value, index) => [(index / (values.length - 1)) * 100, 34 - (value / max) * 30] as const)
  const line = points.map(([x, y], index) => `${index ? 'L' : 'M'}${x.toFixed(2)} ${y.toFixed(2)}`).join('')
  return (
    <svg viewBox="0 0 100 36" preserveAspectRatio="none" className="h-9 w-full overflow-visible" aria-hidden="true">
      <defs>
        <linearGradient id="spark-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" style={{ stopColor: 'var(--color-blue)', stopOpacity: 0.28 }} />
          <stop offset="1" style={{ stopColor: 'var(--color-blue)', stopOpacity: 0 }} />
        </linearGradient>
      </defs>
      <motion.path d={`${line}L100 36L0 36Z`} fill="url(#spark-fill)" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.6, duration: 0.6 }} />
      <motion.path d={line} fill="none" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" style={{ stroke: 'var(--color-blue)' }} initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 1.1, ease }} />
    </svg>
  )
}

/* ---------------------------------------------------------------- figures */
function Kpis({ data }: { data?: InventorySummaryOut }) {
  const days = data?.daily_sales ?? []
  const half = Math.floor(days.length / 2)
  const recent = days.slice(half).reduce((sum, day) => sum + n(day.delivered_value), 0)
  const before = days.slice(0, half).reduce((sum, day) => sum + n(day.delivered_value), 0)
  const change = before > 0 ? ((recent - before) / before) * 100 : null
  let running = 0
  const cumulative = days.map((day) => (running += n(day.delivered_value)))
  const items = [
    {
      label: 'To deliver',
      icon: <Truck size={15} />,
      value: data ? <CountUp value={n(data.total_pending_quantity)} format={(v) => fmtQty(Math.round(v * 1000) / 1000)} /> : null,
      note: data ? <span className="text-fg-3">{plural(data.open_orders, 'open order')}</span> : null,
      extra: data ? (
        <Meter
          className="h-2"
          parts={[
            { label: 'Ready', value: n(data.total_reserved_stock), color: STATE.ready },
            { label: 'On order', value: Math.max(0, n(data.total_pending_quantity) - n(data.total_reserved_stock) - n(data.total_unallocated_quantity)), color: STATE.onOrder },
            { label: 'Short', value: n(data.total_unallocated_quantity), color: STATE.short },
          ]}
        />
      ) : null,
      to: '/fulfilment',
    },
    {
      label: 'Delivered',
      icon: <PackageCheck size={15} />,
      value: data ? <CountUp value={recent + before} format={fmtMoneyRound} /> : null,
      note: change === null ? null : <span className={change >= 0 ? 'text-ok' : 'text-bad'} title="Last 15 days against the 15 before">{`${change >= 0 ? '+' : ''}${change.toFixed(0)}%`} <span className="text-fg-3">30 days</span></span>,
      extra: <Sparkline values={cumulative} />,
      to: '/orders',
    },
    {
      label: 'Short',
      icon: <AlertTriangle size={15} />,
      tone: n(data?.total_unallocated_quantity) > 0 ? ('bad' as const) : undefined,
      value: data ? <CountUp value={n(data.total_unallocated_quantity)} format={(v) => fmtQty(Math.round(v * 1000) / 1000)} /> : null,
      note: data ? <span className={data.products_short?.length ? 'text-bad' : 'text-fg-3'}>{plural(data.products_short?.length ?? 0, 'product')} to buy</span> : null,
      extra: (
        <div className="flex min-w-0 gap-1.5 overflow-hidden">
          {(data?.products_short ?? []).slice(0, 2).map((row) => (
            <span key={row.product_id} className="truncate rounded-full bg-bad/10 px-2.5 py-1 text-[11px] font-medium text-bad">
              {row.name}
            </span>
          ))}
        </div>
      ),
      to: '/fulfilment?lane=short',
    },
  ]
  return (
    <div className="grid h-full grid-cols-3 gap-4 max-md:grid-cols-1 max-md:gap-2">
      {items.map((item, index) => (
        <Card key={item.label} delay={0.04 * index} lift>
          <Link to={item.to} className="group flex h-full flex-col gap-3.5 p-5">
            <div className="flex items-center gap-2.5">
              <IconDot tone={item.tone}>{item.icon}</IconDot>
              <span className="text-[14px] font-medium">{item.label}</span>
              <ArrowUpRight size={15} className="ml-auto text-fg-4 opacity-0 transition group-hover:opacity-100" />
            </div>
            <div className="flex items-baseline gap-2">
              <span className={cn('num text-[34px] leading-none font-light tracking-[-0.04em]', item.tone === 'bad' && 'text-bad')}>{item.value ?? <Skeleton className="h-7 w-24" />}</span>
              <span className="text-[11.5px] font-medium whitespace-nowrap">{item.note}</span>
            </div>
            <div className="mt-auto flex h-9 items-end">{item.extra}</div>
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
    <Card className="h-full" delay={0.1}>
      <CardHead icon={<Gauge size={17} />} title="Ready to deliver" hint="Share of owed goods in hand" />
      <div className="flex min-h-0 flex-1 flex-col items-center px-5 pt-1 pb-4">
        <div className="relative flex min-h-0 w-full flex-1 items-end justify-center">
          <svg viewBox="-16 -16 252 136" className="h-full max-h-[160px] w-auto max-w-full overflow-visible">
            <defs>
              <linearGradient id="gauge-blue" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0" style={{ stopColor: 'var(--color-blue-2)' }} />
                <stop offset="1" style={{ stopColor: 'var(--color-blue)' }} />
              </linearGradient>
              <linearGradient id="gauge-peri" x1="0" y1="1" x2="1" y2="0">
                <stop offset="0" style={{ stopColor: 'var(--color-peri)' }} />
                <stop offset="1" style={{ stopColor: 'color-mix(in oklab, var(--color-peri) 70%, white)' }} />
              </linearGradient>
            </defs>
            {Array.from({ length: 37 }, (_, index) => {
              const angle = Math.PI + (index / 36) * Math.PI
              const lit = (index / 36) * 100 <= share
              const long = index % 6 === 0
              return (
                <motion.line
                  key={index}
                  x1={110 + Math.cos(angle) * 108}
                  y1={110 + Math.sin(angle) * 108}
                  x2={110 + Math.cos(angle) * (long ? 117 : 113)}
                  y2={110 + Math.sin(angle) * (long ? 117 : 113)}
                  strokeWidth={long ? 1.6 : 1.1}
                  strokeLinecap="round"
                  className={lit ? 'stroke-peri' : 'stroke-fg-4/40'}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: 0.3 + index * 0.015 }}
                />
              )
            })}
            <path d={arc} pathLength={100} fill="none" strokeWidth={24} stroke="url(#gauge-blue)" />
            <motion.path
              d={arc}
              pathLength={100}
              fill="none"
              strokeWidth={24}
              stroke="url(#gauge-peri)"
              initial={{ strokeDasharray: '0 100' }}
              animate={{ strokeDasharray: `${Math.max(0, share - gap)} 100` }}
              transition={{ duration: 1.1, ease }}
            />
          </svg>
          <div className="absolute inset-x-0 bottom-0 text-center">
            <span className="num text-[30px] leading-none font-light tracking-[-0.04em]">{data ? <CountUp value={share} format={(v) => `${Math.round(v)}%`} /> : '—'}</span>
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
    <Card dark className="h-full justify-between gap-3 p-6 [&>*:not(svg)]:relative" delay={0.14}>
      <Contours className="absolute -top-[55%] -right-[18%] size-[120%] text-[rgb(255_255_255/0.5)]" rings={13} seed={7} />
      <div>
        <div className="flex items-center gap-3">
          <span className="glass-tile size-10 rounded-full!">
            <TrendingUp size={17} />
          </span>
          <div>
            <h2 className="text-[17px] font-semibold tracking-[-0.02em]">Gross profit</h2>
            <p className="mt-0.5 text-[12px] opacity-70">On goods delivered so far</p>
          </div>
        </div>
      </div>
      <div>
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className={cn('num text-[38px] leading-none font-light tracking-[-0.04em]', profit < 0 && 'text-bad')}>{data ? <CountUp value={profit} format={fmtMoneyRound} /> : '—'}</span>
          <span className="text-[12.5px] opacity-60">{data ? `${fmtPercent(data.margin_percent)} margin` : ''}</span>
        </div>
        <div className="mt-4 flex h-9 gap-1.5">
          <motion.div className="h-full min-w-[8px] rounded-[10px] bg-[#0b0b0c]" initial={{ width: 0 }} animate={{ width: `${costShare}%` }} transition={{ duration: 1, ease }} />
          <motion.div className="h-full min-w-[8px] flex-1 rounded-[10px] bg-[#fff]" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.5 }} />
        </div>
        <div className="mt-2.5 flex justify-between text-[11.5px]">
          <span className="flex items-center gap-1.5 opacity-70">
            <span className="size-2 rounded-full bg-[#0b0b0c]" /> Cost {fmtMoneyRound(cost)}
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
  const peak = buckets.reduce((best, bucket, index) => (bucket.booked > (buckets[best]?.booked ?? 0) ? index : best), 0)
  const average = buckets.length ? total / buckets.length : 0

  return (
    <Card className="h-full" delay={0.08}>
      <CardHead
        icon={<BarChart3 size={17} />}
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
        <span className="num text-[36px] font-light tracking-[-0.04em]">{data ? <CountUp value={total} format={fmtMoneyRound} /> : <Skeleton className="h-7 w-40" />}</span>
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
            {average > 0 ? (
              <motion.div
                className="pointer-events-none absolute inset-x-0 z-[1] border-t border-dashed border-fg/45"
                style={{ bottom: `calc(24px + (100% - 24px) * ${average / top})` }}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 1 }}
              >
                <span className="num absolute -top-[22px] right-0 rounded-full bg-ink-850/90 px-2 py-0.5 text-[11px] font-medium text-fg-2 shadow-pane">avg {fmtCompactMoney(average)}</span>
              </motion.div>
            ) : null}
            <div className="relative flex min-h-0 flex-1 items-end justify-around gap-2">
              {buckets.map((bucket, index) => (
                <div
                  key={bucket.range}
                  className="relative flex h-full w-full max-w-[44px] flex-col justify-end"
                  onMouseEnter={() => setHover(index)}
                  onMouseLeave={() => setHover(null)}
                >
                  <span className={cn('absolute inset-0 rounded-[14px] transition-colors', hover === index ? 'bg-white/[0.09]' : 'bg-white/[0.045]')} />
                  <motion.div
                    className={cn('relative w-full overflow-hidden rounded-[14px] bg-[linear-gradient(180deg,color-mix(in_oklab,var(--c-peri)_62%,white),var(--c-peri))] shadow-[inset_0_1px_0_rgb(255_255_255/0.45)] transition-opacity', hover !== null && hover !== index && 'opacity-45')}
                    initial={{ height: 0 }}
                    animate={{ height: `${(bucket.booked / top) * 100}%` }}
                    transition={{ duration: 0.9, delay: 0.15 + index * 0.06, ease }}
                    style={{
                      minHeight: bucket.booked > 0 ? 6 : 0,
                      // The busiest span is hatched so it stands out.
                      backgroundImage: index === peak && bucket.booked > 0 ? 'repeating-linear-gradient(135deg, var(--c-blue) 0 1.2px, transparent 1.2px 8px), linear-gradient(180deg, var(--c-peri-2), var(--c-peri-2))' : undefined,
                    }}
                  >
                    <motion.div
                      className="absolute inset-x-0 bottom-0 rounded-[14px] bg-[linear-gradient(180deg,var(--c-blue-2),var(--c-blue))] shadow-[inset_0_1px_0_rgb(255_255_255/0.3)]"
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
  const step = [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].find((candidate) => candidate * power >= value) ?? 10
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
    <Card className="h-full" delay={0.18}>
      <CardHead
        icon={tab === 'orders' ? <ReceiptText size={17} /> : tab === 'buy' ? <AlertTriangle size={17} /> : <PackageOpen size={17} />}
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
    <Card className="h-full" delay={0.22}>
      <CardHead icon={<CalendarDays size={17} />} title="Orders this week" hint={days.length && days.every((day) => day.orders === 0) ? 'No orders booked in the last seven days' : per > 1 ? `Each dot about ${Math.round(per)} orders` : 'Each dot one order'} />
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
                    className={cn('aspect-square h-full max-h-[24px] rounded-full', index < filled ? 'bg-[radial-gradient(circle_at_35%_30%,var(--c-blue-2),var(--c-blue))] shadow-[0_3px_8px_-3px_var(--c-blue)]' : 'bg-white/[0.07]')}
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
