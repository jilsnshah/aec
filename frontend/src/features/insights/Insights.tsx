import { useMemo, useState, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { motion } from 'motion/react'
import { ArrowDownRight, ArrowUpRight, BarChart3, CalendarPlus, Sparkles } from 'lucide-react'
import { toast } from 'sonner'
import type { ChartBlock, ColumnKind, TableBlock } from '@/api/ai'
import { errorText } from '@/api/client'
import { api } from '@/api/endpoints'
import { insights, type Period, type Trading } from '@/api/insights'
import { cn } from '@/lib/cn'
import { fmtMoney, fmtQty } from '@/lib/format'
import { HeaderArt } from '@/ui/art'
import { Button, Empty, Skeleton, Spinner } from '@/ui/core'
import { Segmented, TabPanel, Tabs } from '@/ui/overlays'
import { ChartView, TableView } from '@/features/assistant/blocks'
import { useAssistant } from '@/features/assistant/store'

const TABS = [
  { value: 'overview', label: 'Overview' },
  { value: 'stock', label: 'Stock health' },
  { value: 'sales', label: 'Sales' },
  { value: 'enquiries', label: 'Enquiries' },
  { value: 'customers', label: 'Customers' },
  { value: 'suppliers', label: 'Suppliers' },
]

const PERIODS: { value: Period; label: string }[] = [
  { value: 'week', label: 'Week' },
  { value: 'month', label: 'Month' },
  { value: 'quarter', label: 'Quarter' },
  { value: 'year', label: 'Year' },
]

const ASK: Record<string, string> = {
  overview: 'Analyse how the business is doing this period against the last one. Explain what drove the change and what I should do next.',
  stock: 'Review stock health: what is short, what to reorder and how much, and which items are slow or dead and tying up capital. Recommend actions.',
  sales: 'Which products and customers drive revenue and profit, and where is margin weak? Recommend what to push or fix.',
  enquiries: 'Review our enquiry funnel: conversion by source, stale quotes, and why we lose deals. Which enquiries should we follow up today?',
  customers: 'Who are our most valuable customers, who has gone quiet, and who should we contact this week?',
  suppliers: 'How reliable are our suppliers? Who is late or short-ships, and what is still due?',
}

/** Analytics computed by the backend, the same figures the assistant uses. */
export function Insights() {
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') ?? 'overview'
  const [period, setPeriod] = useState<Period>('month')
  const { ask } = useAssistant()
  return (
    <div className="flex h-full min-h-0 flex-col gap-4 px-6 pt-1 pb-5 max-md:gap-2 max-md:p-2">
      <header className="pane relative flex shrink-0 flex-wrap items-center gap-4 overflow-hidden px-5 py-4">
        <HeaderArt seed={8} />
        <span className="icon-tile relative size-11">
          <BarChart3 size={20} />
        </span>
        <div className="relative min-w-0 flex-1">
          <h1 className="text-[20px] font-semibold tracking-[-0.02em]">Insights</h1>
          <p className="text-[12.5px] text-fg-3">Stock ageing, reorders, conversion, customer and supplier performance — computed from live data.</p>
        </div>
        <div className="relative flex flex-wrap items-center gap-2">
          {tab === 'overview' || tab === 'sales' ? <Segmented value={period} onChange={setPeriod} options={PERIODS} /> : null}
          <Button icon={<Sparkles size={14} />} onClick={() => ask(ASK[tab] ?? ASK.overview)}>
            Ask the assistant
          </Button>
        </div>
      </header>
      <section className="pane flex min-h-0 flex-1 flex-col overflow-hidden">
        <Tabs value={tab} onChange={(value) => setParams({ tab: value })} tabs={TABS} className="min-h-0 flex-1">
          <TabPanel value="overview" className="p-5 pb-24">
            <OverviewTab period={period} />
          </TabPanel>
          <TabPanel value="stock" className="p-5 pb-24">
            <StockTab />
          </TabPanel>
          <TabPanel value="sales" className="p-5 pb-24">
            <SalesTab period={period} />
          </TabPanel>
          <TabPanel value="enquiries" className="p-5 pb-24">
            <EnquiriesTab />
          </TabPanel>
          <TabPanel value="customers" className="p-5 pb-24">
            <CustomersTab />
          </TabPanel>
          <TabPanel value="suppliers" className="p-5 pb-24">
            <SuppliersTab />
          </TabPanel>
        </Tabs>
      </section>
    </div>
  )
}

/* ---------------------------------------------------------------- helpers */

function table(title: string, rows: Record<string, unknown>[], columns: [string, string, ColumnKind, { id: string; route: string }?][]): TableBlock {
  return {
    type: 'table',
    id: title,
    title,
    dataset_id: '',
    columns: columns.map(([key, label, kind, link]) => ({ key, label, kind, link: link ?? null })),
    rows,
    total_rows: rows.length,
  }
}

function Figure({ label, value, change, hint, strong, delay = 0 }: { label: string; value: ReactNode; change?: number | null; hint?: string; strong?: boolean; delay?: number }) {
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay }} className={cn('rounded-[18px] p-4', strong ? 'pane-contrast' : 'card')}>
      <div className={cn('text-[12px] font-medium', strong ? 'opacity-70' : 'text-fg-3')}>{label}</div>
      <div className="num mt-1 text-[26px] leading-none font-light tracking-[-0.035em]">{value}</div>
      <div className="mt-2 flex items-center gap-1.5 text-[11.5px]">
        {change !== undefined && change !== null ? (
          <span className={cn('flex items-center gap-0.5 rounded-full px-1.5 py-0.5 font-semibold', change >= 0 ? 'bg-peri/30' : 'bg-solid text-on-brand')}>
            {change >= 0 ? <ArrowUpRight size={11} /> : <ArrowDownRight size={11} />}
            {Math.abs(change).toFixed(change % 1 ? 1 : 0)}%
          </span>
        ) : null}
        {hint ? <span className={strong ? 'opacity-70' : 'text-fg-3'}>{hint}</span> : null}
      </div>
    </motion.div>
  )
}

function Loading() {
  return (
    <div className="grid grid-cols-4 gap-3 max-md:grid-cols-2">
      {Array.from({ length: 8 }, (_, i) => (
        <Skeleton key={i} className="h-24 rounded-[18px]" />
      ))}
    </div>
  )
}

/* ---------------------------------------------------------------- overview */

function OverviewTab({ period }: { period: Period }) {
  const data = useQuery({ queryKey: ['insights', 'overview', period], queryFn: () => insights.overview(period) })
  if (data.isPending) return <Loading />
  if (!data.data) return <Empty title="Could not load the overview" />
  const { current: c, change_percent: d } = data.data
  const items: [string, ReactNode, keyof Trading, string?][] = [
    ['Booked', fmtMoney(c.booked_value), 'booked_value', `${c.orders} orders`],
    ['Revenue delivered', fmtMoney(c.revenue), 'revenue', `${c.deliveries} deliveries`],
    ['Gross profit', fmtMoney(c.gross_profit), 'gross_profit', c.margin_percent !== null ? `${c.margin_percent}% margin` : undefined],
    ['Average order', fmtMoney(c.average_order_value), 'average_order_value'],
    ['Enquiries', c.enquiries, 'enquiries', `${c.enquiries_converted} won · ${c.enquiries_lost} lost`],
    ['Conversion', c.conversion_rate !== null ? `${c.conversion_rate}%` : '—', 'conversion_rate'],
    ['New customers', c.new_customers, 'new_customers'],
    ['Bought in', fmtMoney(c.goods_received_value), 'goods_received_value', `${c.purchase_orders_placed} POs placed`],
  ]
  const chart: ChartBlock = {
    type: 'chart',
    id: 'daily',
    chart: data.data.daily.length > 40 ? 'area' : 'bar',
    title: 'Booked and delivered, day by day',
    x: { key: 'date', label: 'Date' },
    series: [
      { key: 'booked', label: 'Booked' },
      { key: 'revenue', label: 'Delivered' },
    ],
    unit: 'money',
    rows: data.data.daily.map((day) => ({ x: day.date, booked: day.booked, revenue: day.revenue })),
    total_rows: data.data.daily.length,
  }
  return (
    <div className="space-y-4">
      <p className="text-[12.5px] text-fg-3">
        {data.data.start} to {data.data.end}, compared with {data.data.previous_start} to {data.data.previous_end}.
      </p>
      <div className="grid grid-cols-4 gap-3 max-lg:grid-cols-2">
        {items.map(([label, value, key, hint], index) => (
          <Figure key={label} label={label} value={value} change={key === 'conversion_rate' ? undefined : d[key]} hint={hint} strong={index === 2} delay={index * 0.03} />
        ))}
      </div>
      <ChartView block={chart} />
    </div>
  )
}

/* ---------------------------------------------------------------- stock */

const FLAG_TEXT: Record<string, string> = { short: 'Short', dead: 'Dead stock', slow: 'Slow', low_cover: 'Runs out soon', reorder: 'Reorder' }

function StockTab() {
  const { ask } = useAssistant()
  const data = useQuery({ queryKey: ['insights', 'inventory'], queryFn: insights.inventory })
  const rows = useMemo(
    () =>
      (data.data?.products ?? []).map((row) => ({
        ...row,
        status: row.flags.map((flag) => FLAG_TEXT[flag]).join(', ') || 'Healthy',
        aged_90: row.ages['90+']?.value ?? 0,
      })),
    [data.data],
  )
  if (data.isPending) return <Loading />
  if (!data.data) return <Empty title="Could not load stock health" />
  const t = data.data.totals
  const ages: ChartBlock = {
    type: 'chart',
    id: 'ages',
    chart: 'bar',
    title: 'Stock value by age (days since received)',
    x: { key: 'x', label: 'Age' },
    series: [{ key: 'value', label: 'Value at cost' }],
    unit: 'money',
    rows: Object.entries(t.age_value).map(([bucket, value]) => ({ x: `${bucket} days`, value })),
    total_rows: 4,
  }
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-4 gap-3 max-lg:grid-cols-2">
        <Figure label="Stock value at cost" value={fmtMoney(t.stock_value)} hint={`${t.products} products`} />
        <Figure label="Capital at risk" value={fmtMoney(t.capital_at_risk)} hint="slow or dead stock" strong />
        <Figure label="To reorder" value={fmtMoney(t.reorder_value)} hint={`${t.reorder_products} products, ${data.data.thresholds.target_cover_days} days' cover`} />
        <Figure label="Short or running out" value={t.short_quantity_products + t.low_cover_products} hint={`${t.short_quantity_products} short · ${t.low_cover_products} under ${data.data.thresholds.low_cover_days} days`} />
      </div>
      <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)] gap-4 max-lg:grid-cols-1">
        <ChartView block={ages} />
        <div className="card flex flex-col justify-between gap-3 p-4">
          <div>
            <div className="text-[13px] font-semibold">Turn this into action</div>
            <p className="mt-1 text-[12.5px] text-fg-3">
              The assistant can draft purchase orders for every reorder line, grouped by the supplier you last bought from, and suggest how to clear slow stock. You confirm each one.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button kind="primary" small icon={<Sparkles size={13} />} onClick={() => ask('Prepare draft purchase orders for every product the stock-health report says to reorder, grouped by the supplier we last bought each from. Use the recommended quantities and last purchase prices, and show me the plan before proposing them.')}>
              Draft purchase orders
            </Button>
            <Button small icon={<Sparkles size={13} />} onClick={() => ask('Which slow or dead stock items tie up the most capital, and what should we do to clear them? Quantify it.')}>
              Plan for slow stock
            </Button>
          </div>
        </div>
      </div>
      <TableView
        block={table('Every product', rows, [
          ['name', 'Product', 'text', { id: 'product_id', route: '/products/' }],
          ['status', 'Status', 'text'],
          ['free', 'Free', 'number'],
          ['on_order', 'On order', 'number'],
          ['short', 'Short', 'number'],
          ['days_of_cover', 'Days of cover', 'number'],
          ['days_since_last_sale', 'Days since sale', 'number'],
          ['stock_value', 'Value', 'money'],
          ['aged_90', 'Over 90 days', 'money'],
          ['reorder_quantity', 'Reorder qty', 'number'],
        ])}
      />
    </div>
  )
}

/* ---------------------------------------------------------------- sales */

function SalesTab({ period }: { period: Period }) {
  const [group, setGroup] = useState<'product' | 'customer' | 'month'>('product')
  const data = useQuery({ queryKey: ['insights', 'sales', group, period], queryFn: () => insights.sales(group, group === 'month' ? 'year' : period) })
  const link = group === 'product' ? { id: 'product_id', route: '/products/' } : group === 'customer' ? { id: 'customer_id', route: '/customers/' } : undefined
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Segmented
          value={group}
          onChange={setGroup}
          options={[
            { value: 'product', label: 'By product' },
            { value: 'customer', label: 'By customer' },
            { value: 'month', label: 'By month' },
          ]}
        />
        {data.data ? (
          <span className="text-[12.5px] text-fg-3">
            {data.data.start} to {data.data.end} · booked {fmtMoney(data.data.totals.booked_value)} · delivered {fmtMoney(data.data.totals.revenue)} · profit {fmtMoney(data.data.totals.gross_profit)}
          </span>
        ) : null}
      </div>
      {data.isPending ? (
        <Spinner />
      ) : !data.data?.items.length ? (
        <Empty title="No sales in this period" />
      ) : (
        <>
          <ChartView
            block={{
              type: 'chart',
              id: 'sales',
              chart: group === 'month' ? 'bar' : 'horizontal_bar',
              title: group === 'month' ? 'Booked and delivered by month' : `Top ${group === 'product' ? 'products' : 'customers'} by value booked`,
              x: { key: 'name', label: group },
              series: group === 'month' ? [{ key: 'booked_value', label: 'Booked' }, { key: 'revenue', label: 'Delivered' }] : [{ key: 'booked_value', label: 'Booked' }],
              unit: 'money',
              rows: data.data.items.slice(0, 12).map((row) => ({ x: row.name, booked_value: row.booked_value, revenue: row.revenue })),
              total_rows: data.data.items.length,
            }}
          />
          <TableView
            block={table('Breakdown', data.data.items as unknown as Record<string, unknown>[], [
              ['name', group === 'month' ? 'Month' : group === 'product' ? 'Product' : 'Customer', 'text', link],
              ['orders', 'Orders', 'number'],
              ['quantity_booked', 'Qty booked', 'number'],
              ['booked_value', 'Booked', 'money'],
              ['revenue', 'Delivered', 'money'],
              ['gross_profit', 'Profit', 'money'],
              ['margin_percent', 'Margin', 'percent'],
              ['share_of_booked_percent', 'Share', 'percent'],
            ])}
          />
        </>
      )}
    </div>
  )
}

/* ---------------------------------------------------------------- enquiries */

function EnquiriesTab() {
  const client = useQueryClient()
  const data = useQuery({ queryKey: ['insights', 'enquiries'], queryFn: insights.enquiries })
  const [planning, setPlanning] = useState<string | null>(null)
  if (data.isPending) return <Loading />
  if (!data.data) return <Empty title="Could not load enquiries" />
  const f = data.data

  async function plan(row: (typeof f.stale)[number]) {
    setPlanning(row.enquiry_id)
    try {
      const tomorrow = new Date(Date.now() + 86_400_000).toISOString().slice(0, 10)
      await api.tasks.create({ title: `Follow up ${row.enquiry_number} with ${row.customer_name}`, enquiry_id: row.enquiry_id, customer_id: row.customer_id, due_date: tomorrow, priority: row.value > 10000 ? 'HIGH' : 'NORMAL' })
      toast.success(`Follow-up planned for tomorrow`)
      client.invalidateQueries({ queryKey: ['insights'] })
      client.invalidateQueries({ queryKey: ['tasks'] })
    } catch (error) {
      toast.error(errorText(error))
    } finally {
      setPlanning(null)
    }
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-4 gap-3 max-lg:grid-cols-2">
        <Figure label="Open enquiries" value={f.counts.open} hint={`${fmtMoney(f.open_pipeline_value)} in the pipeline`} strong />
        <Figure label="Conversion" value={f.conversion_rate !== null ? `${f.conversion_rate}%` : '—'} hint={`${f.counts.converted} won · ${f.counts.lost} lost`} />
        <Figure label="Days to convert" value={f.average_days_to_convert ?? '—'} hint="on average" />
        <Figure label="Gone quiet" value={f.stale.length} hint={`${f.stale_without_follow_up} with no follow-up`} />
      </div>
      <div className="card overflow-hidden">
        <div className="border-b border-white/6 px-3.5 py-2.5 text-[13px] font-semibold">Untouched for {f.stale_days}+ days</div>
        {f.stale.length === 0 ? (
          <Empty title="Every open enquiry is moving" />
        ) : (
          f.stale.map((row) => (
            <div key={row.enquiry_id} className="flex items-center gap-3 border-b border-white/5 px-3.5 py-2.5 text-[12.5px] last:border-0">
              <Link to={`/enquiries/${row.enquiry_id}`} className="font-semibold underline decoration-blue/50 decoration-2 underline-offset-2">
                {row.enquiry_number}
              </Link>
              <span className="min-w-0 flex-1 truncate text-fg-2">
                {row.customer_name} · {row.days_idle} days idle · {row.source}
              </span>
              <span className="num font-medium">{fmtMoney(row.value)}</span>
              {row.has_open_follow_up ? (
                <span className="rounded-full bg-peri/30 px-2 py-0.5 text-[11px] font-semibold">Follow-up planned</span>
              ) : (
                <Button small icon={<CalendarPlus size={13} />} busy={planning === row.enquiry_id} onClick={() => void plan(row)}>
                  Follow up tomorrow
                </Button>
              )}
            </div>
          ))
        )}
      </div>
      <div className="grid grid-cols-2 gap-4 max-lg:grid-cols-1">
        <TableView
          block={table('Conversion by source', f.by_source as unknown as Record<string, unknown>[], [
            ['source', 'Source', 'text'],
            ['total', 'Enquiries', 'number'],
            ['converted', 'Won', 'number'],
            ['lost', 'Lost', 'number'],
            ['conversion_rate', 'Conversion', 'percent'],
            ['value_converted', 'Won value', 'money'],
          ])}
        />
        <TableView block={table('Why deals are lost', f.lost_reasons as unknown as Record<string, unknown>[], [['reason', 'Reason', 'text'], ['count', 'Times', 'number']])} />
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------- customers and suppliers */

function CustomersTab() {
  const data = useQuery({ queryKey: ['insights', 'customers'], queryFn: insights.customers })
  if (data.isPending) return <Loading />
  if (!data.data) return <Empty title="Could not load customers" />
  const top = data.data.customers.slice(0, 10)
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-3 max-lg:grid-cols-1">
        <Figure label="Customers who ordered" value={data.data.customers.length} />
        <Figure label="Top fifth's share of sales" value={data.data.top_share_percent !== null ? `${data.data.top_share_percent}%` : '—'} hint="concentration risk" strong />
        <Figure label="Gone quiet" value={data.data.dormant.length} hint={`no order for ${data.data.dormant_days}+ days`} />
      </div>
      {top.length ? (
        <ChartView
          block={{
            type: 'chart',
            id: 'customers',
            chart: 'horizontal_bar',
            title: 'Top customers by value booked',
            x: { key: 'name', label: 'Customer' },
            series: [{ key: 'booked_value', label: 'Booked' }],
            unit: 'money',
            rows: top.map((row) => ({ x: row.name, booked_value: row.booked_value })),
            total_rows: top.length,
          }}
        />
      ) : null}
      <TableView
        block={table('Customers by value', data.data.customers as unknown as Record<string, unknown>[], [
          ['name', 'Customer', 'text', { id: 'customer_id', route: '/customers/' }],
          ['orders', 'Orders', 'number'],
          ['booked_value', 'Booked', 'money'],
          ['revenue', 'Delivered', 'money'],
          ['outstanding_value', 'Still to deliver', 'money'],
          ['open_enquiries', 'Open enquiries', 'number'],
          ['days_since_last_order', 'Days since order', 'number'],
          ['share_percent', 'Share', 'percent'],
        ])}
      />
    </div>
  )
}

function SuppliersTab() {
  const data = useQuery({ queryKey: ['insights', 'suppliers'], queryFn: insights.suppliers })
  if (data.isPending) return <Loading />
  if (!data.data) return <Empty title="Could not load suppliers" />
  return (
    <div className="space-y-4">
      {data.data.late_purchase_orders.length ? (
        <TableView
          block={table('Late purchase orders', data.data.late_purchase_orders as unknown as Record<string, unknown>[], [
            ['po_number', 'PO', 'text', { id: 'purchase_order_id', route: '/purchase-orders/' }],
            ['supplier_name', 'Supplier', 'text', { id: 'supplier_id', route: '/suppliers/' }],
            ['expected', 'Expected', 'date'],
            ['days_late', 'Days late', 'number'],
            ['still_due_value', 'Still due', 'money'],
          ])}
        />
      ) : null}
      <TableView
        block={table('Supplier performance', data.data.suppliers as unknown as Record<string, unknown>[], [
          ['name', 'Supplier', 'text', { id: 'supplier_id', route: '/suppliers/' }],
          ['purchase_orders', 'POs', 'number'],
          ['ordered_value', 'Ordered', 'money'],
          ['received_value', 'Received', 'money'],
          ['still_due_value', 'Still due', 'money'],
          ['average_lead_days', 'Lead days', 'number'],
          ['fill_rate_percent', 'Fill rate', 'percent'],
          ['on_time_percent', 'On time', 'percent'],
        ])}
      />
      <p className="text-[12px] text-fg-3">
        Lead time runs from placing the order to the first delivery. Fill rate is quantity received against quantity ordered. On time compares the last delivery with the expected date. {fmtQty(data.data.suppliers.length)} suppliers.
      </p>
    </div>
  )
}
