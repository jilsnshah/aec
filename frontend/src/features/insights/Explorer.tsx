import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDownRight, ArrowUpRight, Bookmark, Download, Sparkles, Trash2, X } from 'lucide-react'
import { toast } from 'sonner'
import { errorText } from '@/api/client'
import { api } from '@/api/endpoints'
import { workspace } from '@/api/finance'
import { insights, type Explore, type ExploreGroup, type ExploreQuery, type ExploreRow, type Measure, type Period } from '@/api/insights'
import { cn } from '@/lib/cn'
import { fmtMoney, fmtQty } from '@/lib/format'
import { Button, Empty, Spinner } from '@/ui/core'
import { Menu, Segmented } from '@/ui/overlays'
import { Picker } from '@/ui/pickers'
import { useCustomers, useProducts } from '@/ui/lines'
import { ChartView } from '@/features/assistant/blocks'
import { useAssistant } from '@/features/assistant/store'

const MEASURES: { value: Measure; label: string; money: boolean }[] = [
  { value: 'booked_value', label: 'Booked value', money: true },
  { value: 'revenue', label: 'Delivered revenue', money: true },
  { value: 'gross_profit', label: 'Gross profit', money: true },
  { value: 'cost_of_goods', label: 'Cost of goods', money: true },
  { value: 'discount', label: 'Discount given', money: true },
  { value: 'orders', label: 'Orders', money: false },
  { value: 'quantity_booked', label: 'Quantity booked', money: false },
  { value: 'quantity_delivered', label: 'Quantity delivered', money: false },
]
const GROUPS: { value: ExploreGroup; label: string }[] = [
  { value: 'month', label: 'Month' },
  { value: 'week', label: 'Week' },
  { value: 'day', label: 'Day' },
  { value: 'weekday', label: 'Weekday' },
  { value: 'product', label: 'Product' },
  { value: 'category', label: 'Category' },
  { value: 'customer', label: 'Customer' },
]
const PERIODS: { value: Period | 'custom'; label: string }[] = [
  { value: 'last_30', label: 'Last 30 days' },
  { value: 'last_90', label: 'Last 90 days' },
  { value: 'month', label: 'This month' },
  { value: 'quarter', label: 'This quarter' },
  { value: 'year', label: 'This year' },
  { value: 'custom', label: 'Custom…' },
]

interface State {
  measure: Measure
  group_by: ExploreGroup
  period: Period | 'custom'
  start: string
  end: string
  categories: string[]
  products: string[]
  customers: string[]
  view: 'chart' | 'table'
}
const DEFAULT: State = { measure: 'booked_value', group_by: 'month', period: 'year', start: '', end: '', categories: [], products: [], customers: [], view: 'chart' }

/** Ask the data anything: a measure, a grouping, a window, filters — with the
 *  previous window alongside. Click a row to drill down. */
export function Explorer() {
  const [state, setState] = useState<State>(DEFAULT)
  const { ask } = useAssistant()
  const navigate = useNavigate()
  const client = useQueryClient()
  const products = useProducts()
  const customers = useCustomers()
  const categories = useQuery({ queryKey: ['products', 'categories'], queryFn: api.products.categories })
  const views = useQuery({ queryKey: ['views', 'explorer'], queryFn: () => workspace.views<State>('explorer') })
  const query: ExploreQuery = {
    measure: state.measure,
    group_by: state.group_by,
    period: state.period === 'custom' ? 'last_90' : state.period,
    start: state.period === 'custom' && state.start ? state.start : undefined,
    end: state.period === 'custom' && state.end ? state.end : undefined,
    categories: state.categories.join(',') || undefined,
    product_ids: state.products.join(',') || undefined,
    customer_ids: state.customers.join(',') || undefined,
  }
  const data = useQuery({ queryKey: ['insights', 'explore', query], queryFn: () => insights.explore(query), placeholderData: keepPreviousData })
  const heat = useQuery({ queryKey: ['insights', 'heatmap', state.measure], queryFn: () => insights.heatmap(state.measure, 12) })
  const measure = MEASURES.find((m) => m.value === state.measure)!
  const format = (value: number | null | undefined) => (value === null || value === undefined ? '—' : measure.money ? fmtMoney(value) : fmtQty(value))
  const update = (patch: Partial<State>) => setState((current) => ({ ...current, ...patch }))

  function drill(row: ExploreRow) {
    if (state.group_by === 'category') update({ categories: [row.key], group_by: 'product' })
    else if (state.group_by === 'month') {
      const [y, m] = row.key.split('-').map(Number)
      const last = new Date(y, m, 0).getDate()
      update({ period: 'custom', start: `${row.key}-01`, end: `${row.key}-${String(last).padStart(2, '0')}`, group_by: 'day' })
    } else if (state.group_by === 'week') {
      const end = new Date(row.key)
      end.setDate(end.getDate() + 6)
      update({ period: 'custom', start: row.key, end: end.toISOString().slice(0, 10), group_by: 'day' })
    } else if (row.link) navigate(row.link)
  }

  async function saveView() {
    const name = window.prompt('Name this view', `${measure.label} by ${GROUPS.find((g) => g.value === state.group_by)?.label.toLowerCase()}`)
    if (!name) return
    try {
      await workspace.saveView({ page: 'explorer', name, state })
      client.invalidateQueries({ queryKey: ['views', 'explorer'] })
      toast.success(`Saved “${name}”`)
    } catch (error) {
      toast.error(errorText(error))
    }
  }

  function exportCsv(result: Explore) {
    const header = ['Group', measure.label, 'Previous period', 'Change %', 'Share %', 'Orders', 'Booked', 'Delivered', 'Profit', 'Margin %']
    const rows = result.rows.map((r) => [r.label, r.value, r.previous ?? '', r.change_percent ?? '', r.share_percent ?? '', r.orders, r.booked_value, r.revenue, r.gross_profit, r.margin_percent ?? ''])
    const csv = [header, ...rows].map((row) => row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(',')).join('\n')
    const url = URL.createObjectURL(new Blob(['﻿' + csv], { type: 'text/csv' }))
    const a = document.createElement('a')
    a.href = url
    a.download = `explore-${state.measure}-by-${state.group_by}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  const timeBased = ['month', 'week', 'day', 'weekday'].includes(state.group_by)
  const result = data.data
  const chips = useMemo(
    () => [
      ...state.categories.map((c) => ({ key: `c:${c}`, label: c, remove: () => update({ categories: state.categories.filter((x) => x !== c) }) })),
      ...state.products.map((p) => ({ key: `p:${p}`, label: products.byId.get(p)?.name ?? 'Product', remove: () => update({ products: state.products.filter((x) => x !== p) }) })),
      ...state.customers.map((id) => ({ key: `u:${id}`, label: customers.find((c) => c.id === id)?.name ?? 'Customer', remove: () => update({ customers: state.customers.filter((x) => x !== id) }) })),
    ],
    [state, products.byId, customers], // eslint-disable-line react-hooks/exhaustive-deps
  )

  return (
    <div className="space-y-4">
      <div className="card space-y-3 p-3.5">
        <div className="flex flex-wrap items-end gap-2">
          <label className="min-w-[170px] flex-1">
            <span className="label">Measure</span>
            <select className="field field-sm" value={state.measure} onChange={(e) => update({ measure: e.target.value as Measure })}>
              {MEASURES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
            </select>
          </label>
          <label className="min-w-[140px] flex-1">
            <span className="label">By</span>
            <select className="field field-sm" value={state.group_by} onChange={(e) => update({ group_by: e.target.value as ExploreGroup })}>
              {GROUPS.map((g) => <option key={g.value} value={g.value}>{g.label}</option>)}
            </select>
          </label>
          <label className="min-w-[150px] flex-1">
            <span className="label">Period</span>
            <select className="field field-sm" value={state.period} onChange={(e) => update({ period: e.target.value as State['period'] })}>
              {PERIODS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
            </select>
          </label>
          {state.period === 'custom' ? (
            <>
              <label>
                <span className="label">From</span>
                <input type="date" className="field field-sm" value={state.start} onChange={(e) => update({ start: e.target.value })} />
              </label>
              <label>
                <span className="label">To</span>
                <input type="date" className="field field-sm" value={state.end} onChange={(e) => update({ end: e.target.value })} />
              </label>
            </>
          ) : null}
          <label className="min-w-[150px] flex-1">
            <span className="label">Category</span>
            <select className="field field-sm" value="" onChange={(e) => e.target.value && update({ categories: [...new Set([...state.categories, e.target.value])] })}>
              <option value="">Add a category…</option>
              {(categories.data ?? []).map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
            </select>
          </label>
          <div className="min-w-[170px] flex-1">
            <span className="label">Product</span>
            <Picker small value="" onChange={(value) => update({ products: [...new Set([...state.products, value])] })} placeholder="Add a product…" options={products.items.map((p) => ({ value: p.id, label: p.name, detail: p.sku }))} />
          </div>
          <div className="min-w-[170px] flex-1">
            <span className="label">Customer</span>
            <Picker small value="" onChange={(value) => update({ customers: [...new Set([...state.customers, value])] })} placeholder="Add a customer…" options={customers.map((c) => ({ value: c.id, label: c.name }))} />
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {chips.map((chip) => (
            <button key={chip.key} onClick={chip.remove} className="flex items-center gap-1 rounded-full bg-peri/25 px-2.5 py-1 text-[12px] font-medium">
              {chip.label} <X size={12} />
            </button>
          ))}
          {chips.length ? <Button small kind="ghost" onClick={() => update({ categories: [], products: [], customers: [] })}>Clear filters</Button> : <span className="text-[12px] text-fg-3">No filters — everything is included.</span>}
          <span className="flex-1" />
          <Segmented value={state.view} onChange={(view) => update({ view })} options={[{ value: 'chart', label: 'Chart' }, { value: 'table', label: 'Table' }]} />
          <Menu
            trigger={<Button small icon={<Bookmark size={13} />}>Views</Button>}
            items={[
              { label: 'Save this view…', icon: <Bookmark size={14} />, onSelect: () => void saveView() },
              ...(views.data ?? []).map((view, index) => ({ label: view.name, separator: index === 0, onSelect: () => setState({ ...DEFAULT, ...view.state }) })),
              ...(views.data ?? []).filter((v) => v.mine).map((view, index) => ({
                label: `Delete “${view.name}”`,
                icon: <Trash2 size={14} />,
                danger: true,
                separator: index === 0,
                onSelect: async () => {
                  await workspace.deleteView(view.id)
                  client.invalidateQueries({ queryKey: ['views', 'explorer'] })
                },
              })),
            ]}
          />
          <Button small icon={<Download size={13} />} disabled={!result} onClick={() => result && exportCsv(result)}>
            CSV
          </Button>
          <Button
            small
            icon={<Sparkles size={13} />}
            disabled={!result}
            onClick={() => result && ask(`Explain this view: ${measure.label} by ${state.group_by} from ${result.start} to ${result.end}${chips.length ? `, filtered to ${chips.map((c) => c.label).join(', ')}` : ''}. Total ${format(result.total)} vs ${format(result.total_previous)} the period before. What drove the change, what stands out, and what should I do? Use sales_explorer to dig deeper.`)}
          >
            Explain
          </Button>
        </div>
      </div>

      {!result ? (
        <Spinner />
      ) : (
        <div className={cn('space-y-4 transition-opacity', data.isFetching && 'opacity-60')}>
          <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
            <span className="num text-[30px] font-light tracking-[-0.04em]">{format(result.total)}</span>
            {result.change_percent !== null ? (
              <span className={cn('flex items-center gap-0.5 rounded-full px-2 py-0.5 text-[12px] font-semibold', result.change_percent >= 0 ? 'bg-peri/30' : 'bg-solid text-on-brand')}>
                {result.change_percent >= 0 ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}
                {Math.abs(result.change_percent)}%
              </span>
            ) : null}
            <span className="text-[12.5px] text-fg-3">
              {result.measure_label}, {result.start} to {result.end} · previous period {format(result.total_previous)} ({result.previous_start} to {result.previous_end})
            </span>
          </div>
          {result.rows.length === 0 ? (
            <Empty title="Nothing in this window" body="Try a longer period or remove a filter." />
          ) : state.view === 'chart' ? (
            <ChartView
              block={{
                type: 'chart',
                id: 'explore',
                chart: timeBased ? (state.group_by === 'day' ? 'area' : 'bar') : 'horizontal_bar',
                title: `${measure.label} by ${GROUPS.find((g) => g.value === state.group_by)?.label.toLowerCase()} — click a row in the table to drill down`,
                x: { key: 'label', label: '' },
                series: [{ key: 'value', label: measure.label }],
                unit: measure.money ? 'money' : 'number',
                rows: result.rows.slice(0, timeBased ? 200 : 20).map((row) => ({ x: row.label, value: row.value })),
                total_rows: result.row_count,
              }}
            />
          ) : null}
          {result.rows.length ? (
            <div className="card overflow-x-auto">
              <table className="grid-table">
                <thead>
                  <tr>
                    <th>{GROUPS.find((g) => g.value === state.group_by)?.label}</th>
                    <th className="r">{measure.label}</th>
                    {!timeBased ? <th className="r">Previous</th> : null}
                    {!timeBased ? <th className="r">Change</th> : null}
                    <th className="r">Share</th>
                    {!timeBased ? <th className="r">Running share</th> : null}
                    <th className="r">Orders</th>
                    <th className="r">Profit</th>
                    <th className="r">Margin</th>
                  </tr>
                </thead>
                <tbody>
                  {result.rows.map((row) => (
                    <tr key={row.key} onClick={() => drill(row)} className="cursor-pointer">
                      <td className="font-medium underline decoration-blue/40 decoration-2 underline-offset-2">{row.label}</td>
                      <td className="r num font-semibold">{format(row.value)}</td>
                      {!timeBased ? <td className="r num text-fg-3">{format(row.previous)}</td> : null}
                      {!timeBased ? <td className="r num">{row.change_percent === null ? '—' : `${row.change_percent > 0 ? '+' : ''}${row.change_percent}%`}</td> : null}
                      <td className="r num text-fg-2">{row.share_percent === null ? '—' : `${row.share_percent}%`}</td>
                      {!timeBased ? <td className={cn('r num', (row.cumulative_percent ?? 0) <= 80 ? 'font-semibold' : 'text-fg-3')}>{row.cumulative_percent ?? '—'}%</td> : null}
                      <td className="r num text-fg-2">{row.orders}</td>
                      <td className="r num">{fmtMoney(row.gross_profit)}</td>
                      <td className="r num text-fg-2">{row.margin_percent === null ? '—' : `${row.margin_percent}%`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          {!timeBased && result.rows.length > 2 ? (
            <p className="text-[12px] text-fg-3">Pareto: rows in bold make up the first 80% of {measure.label.toLowerCase()}.</p>
          ) : null}
        </div>
      )}

      {heat.data ? (
        <div className="card p-4">
          <div className="mb-3 flex items-baseline justify-between">
            <span className="text-[13px] font-semibold">Weekly rhythm — {measure.label.toLowerCase()} by weekday, last 12 weeks</span>
            <span className="text-[12px] text-fg-3">{heat.data.busiest_weekday ? `Busiest: ${heat.data.busiest_weekday}` : 'No activity yet'}</span>
          </div>
          <Heat data={heat.data} format={format} />
        </div>
      ) : null}
    </div>
  )
}

function Heat({ data, format }: { data: NonNullable<Awaited<ReturnType<typeof insights.heatmap>>>; format: (v: number) => string }) {
  const peak = Math.max(1, ...data.weeks.flatMap((w) => w.values))
  return (
    <div className="overflow-x-auto">
      <div className="grid min-w-[560px] gap-1" style={{ gridTemplateColumns: `52px repeat(${data.weeks.length}, minmax(0, 1fr))` }}>
        {data.weekdays.map((day, d) => (
          <div key={day} className="contents">
            <span className="self-center text-[11px] text-fg-3">{day}</span>
            {data.weeks.map((week) => {
              const value = week.values[d]
              return (
                <span
                  key={week.week + d}
                  title={`${day}, week of ${week.week}: ${format(value)}`}
                  className="h-6 rounded-md"
                  style={{ background: value ? `color-mix(in oklab, var(--color-blue) ${Math.round(15 + (value / peak) * 85)}%, transparent)` : 'color-mix(in oklab, var(--c-tint) 5%, transparent)' }}
                />
              )
            })}
          </div>
        ))}
        <span />
        {data.weeks.map((week, i) => (
          <span key={week.week} className="text-center text-[10px] text-fg-4">{i % 2 === 0 ? week.week.slice(5) : ''}</span>
        ))}
      </div>
    </div>
  )
}
