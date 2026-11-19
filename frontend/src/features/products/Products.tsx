import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { insights, type ProductHealth } from '@/api/insights'
import { useAssistant } from '@/features/assistant/store'
import { motion } from 'motion/react'
import { Archive, Boxes, Check, ClipboardList, Download, MoreHorizontal, PackagePlus, Pencil, Plus, Sparkles, TrendingDown, TrendingUp, X } from 'lucide-react'
import { api } from '@/api/endpoints'
import { useAction, useList, useOne } from '@/api/queries'
import type { ProductInventoryOut } from '@/api/types'
import { cn } from '@/lib/cn'
import { fmtAmount, fmtDate, fmtDateTime, fmtMoney, fmtQty, n } from '@/lib/format'
import { useDebounced, useRecordRoute } from '@/lib/route'
import { Badge, Button, Empty, SearchBox, Spinner, Tip } from '@/ui/core'
import { Menu, TabPanel, Tabs, useConfirm } from '@/ui/overlays'
import { FigureStrip, InspectorHeader, ListPane, ListRow, ListSkeleton, Section, SplitView } from '@/ui/split'
import { PurchaseSheet } from '@/features/purchasing/PurchaseSheet'
import { ProductSheet } from './ProductSheet'

const MOVEMENT: Record<string, string> = {
  OPENING_STOCK: 'Opening stock',
  STOCK_RECEIPT: 'Stock in',
  GOODS_RECEIPT: 'Goods receipt',
  CUSTOMER_DELIVERY: 'Delivered',
  ORDER_FULFILMENT: 'Order fulfilled',
  ADJUSTMENT: 'Adjustment',
}

const FLAGS: { value: string; label: string }[] = [
  { value: '', label: 'Any health' },
  { value: 'reorder', label: 'To reorder' },
  { value: 'short', label: 'Short' },
  { value: 'below_minimum', label: 'Below minimum' },
  { value: 'low_cover', label: 'Running out' },
  { value: 'rising_demand', label: 'Demand rising' },
  { value: 'falling_demand', label: 'Demand falling' },
  { value: 'slow', label: 'Slow moving' },
  { value: 'dead', label: 'Dead stock' },
]
const SORTS: { value: string; label: string }[] = [
  { value: 'name', label: 'Name' },
  { value: 'stock', label: 'Stock (lowest first)' },
  { value: 'value', label: 'Value (highest first)' },
  { value: 'cover', label: 'Days of cover' },
  { value: 'idle', label: 'Days since last sale' },
  { value: 'reorder', label: 'Reorder value' },
  { value: 'risk', label: 'Capital at risk' },
]
const ACTION_TONE: Record<string, 'bad' | 'warn' | 'sky' | 'muted' | 'steel'> = { buy: 'bad', plan: 'sky', liquidate: 'bad', do_not_reorder: 'muted', watch: 'steel', ok: 'muted' }
const ACTION_LABEL: Record<string, string> = { buy: 'Buy', plan: 'Plan order', liquidate: 'Clear', do_not_reorder: "Don't reorder", watch: 'Watch', ok: '' }

/** The purchase order screen, pre-filled with these products at their
 *  recommended quantities and last costs. */
export function buyLink(rows: ProductHealth[]) {
  const suppliers = new Set(rows.map((row) => row.preferred_supplier_id).filter(Boolean))
  const lines = rows.map((row) => `${row.product_id}:${Math.max(1, row.reorder_quantity || 1)}:${row.unit_cost || ''}`).join(',')
  const supplier = suppliers.size === 1 ? `&supplier=${[...suppliers][0]}` : ''
  return `/purchase-orders?new=1&lines=${lines}${supplier}`
}

export function Products() {
  const route = useRecordRoute('/products')
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const { ask } = useAssistant()
  const search = params.get('q') ?? ''
  const flag = params.get('flag') ?? ''
  const category = params.get('category') ?? ''
  const ids = params.get('ids') ?? ''
  const sort = params.get('sort') ?? 'name'
  const archived = params.get('archived') === '1'
  const set = (key: string, value: string) =>
    setParams((current) => {
      if (value) current.set(key, value)
      else current.delete(key)
      return current
    }, { replace: true })
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const query = useDebounced(search)
  const list = useList('products', api.products.list, { search: query, include_inactive: archived, limit: 500, sort_by: 'name', sort_dir: 'asc' as const, category: category || undefined, ids: ids || undefined })
  const health = useQuery({ queryKey: ['insights', 'inventory'], queryFn: insights.inventory })
  const categories = useQuery({ queryKey: ['products', 'categories'], queryFn: api.products.categories })
  const byId = useMemo(() => new Map((health.data?.products ?? []).map((row) => [row.product_id, row])), [health.data])
  const items = useMemo(() => {
    const rows = (list.data?.items ?? []).filter((product) => !flag || byId.get(product.id)?.flags.includes(flag as never))
    const h = (id: string) => byId.get(id)
    const by: Record<string, (a: (typeof rows)[number], b: (typeof rows)[number]) => number> = {
      name: (a, b) => a.name.localeCompare(b.name),
      stock: (a, b) => n(a.stock) - n(b.stock),
      value: (a, b) => n(b.stock_value) - n(a.stock_value),
      cover: (a, b) => (h(a.id)?.days_of_cover ?? 1e9) - (h(b.id)?.days_of_cover ?? 1e9),
      idle: (a, b) => (h(b.id)?.days_since_last_sale ?? 1e9) - (h(a.id)?.days_since_last_sale ?? 1e9),
      reorder: (a, b) => (h(b.id)?.reorder_value ?? 0) - (h(a.id)?.reorder_value ?? 0),
      risk: (a, b) => (h(b.id)?.liquidation_priority ?? 0) - (h(a.id)?.liquidation_priority ?? 0),
    }
    return [...rows].sort(by[sort] ?? by.name)
  }, [list.data, flag, sort, byId])
  useEffect(() => {
    if (!route.id && items.length > 0 && window.innerWidth >= 1024 && !search && !flag && !ids) route.select(items[0].id)
  }, [route.id, items.length]) // eslint-disable-line react-hooks/exhaustive-deps

  const chosen = items.filter((product) => selected.has(product.id))
  const chosenHealth = chosen.map((product) => byId.get(product.id)).filter(Boolean) as ProductHealth[]
  const toggle = (id: string) => setSelected((current) => {
    const next = new Set(current)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
  })

  function exportCsv() {
    const rows = (chosen.length ? chosen : items).map((product) => {
      const row = byId.get(product.id)
      return [product.sku, product.name, product.category ?? '', product.unit_of_measure, n(product.physical_stock), n(product.on_order_quantity), n(product.pending_quantity), n(product.stock), n(product.stock_value), row?.days_of_cover ?? '', row?.days_since_last_sale ?? '', row?.reorder_quantity ?? '', row?.flags.join(' ') ?? '', row?.action.text ?? '']
    })
    const header = ['SKU', 'Name', 'Category', 'Unit', 'In warehouse', 'On order', 'To deliver', 'Stock', 'Value', 'Days of cover', 'Days since sale', 'Reorder qty', 'Flags', 'Recommendation']
    const csv = [header, ...rows].map((row) => row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(',')).join('\n')
    const url = URL.createObjectURL(new Blob(['\ufeff' + csv], { type: 'text/csv' }))
    const a = document.createElement('a')
    a.href = url
    a.download = `products-${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <SplitView
      showDetail={Boolean(route.id)}
      onBack={route.back}
      listWidth={410}
      list={
        <ListPane
          title="Products"
          count={items.length}
          actions={
            <>
              <Tip label="Export to CSV">
                <Button kind="ghost" small iconOnly onClick={exportCsv} aria-label="Export products">
                  <Download size={15} />
                </Button>
              </Tip>
              <Button kind="ghost" small iconOnly onClick={route.openNew} aria-label="New product">
                <Plus size={16} />
              </Button>
            </>
          }
          filters={
            <>
              <SearchBox value={search} onChange={(value) => set('q', value)} placeholder="Name or code" />
              <div className="grid grid-cols-3 gap-1.5">
                <select className="field field-sm" value={flag} onChange={(e) => set('flag', e.target.value)} aria-label="Health">
                  {FLAGS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                      {option.value && health.data ? ` (${health.data.products.filter((p) => p.flags.includes(option.value as never)).length})` : ''}
                    </option>
                  ))}
                </select>
                <select className="field field-sm" value={category} onChange={(e) => set('category', e.target.value)} aria-label="Category">
                  <option value="">All categories</option>
                  {(categories.data ?? []).map((c) => (
                    <option key={c.name} value={c.name}>
                      {c.name} ({c.products})
                    </option>
                  ))}
                </select>
                <select className="field field-sm" value={sort} onChange={(e) => set('sort', e.target.value)} aria-label="Sort">
                  {SORTS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>
              {ids || archived ? (
                <div className="flex flex-wrap gap-1.5 text-[12px]">
                  {ids ? (
                    <button onClick={() => set('ids', '')} className="flex items-center gap-1 rounded-full bg-peri/25 px-2.5 py-1 font-medium">
                      {ids.split(',').length} chosen products <X size={12} />
                    </button>
                  ) : null}
                  {archived ? (
                    <button onClick={() => set('archived', '')} className="flex items-center gap-1 rounded-full bg-white/[0.07] px-2.5 py-1">
                      Including archived <X size={12} />
                    </button>
                  ) : null}
                </div>
              ) : null}
              {chosen.length ? (
                <div className="flex flex-wrap items-center gap-1.5 rounded-xl bg-peri/[0.18] px-2.5 py-1.5 text-[12px]">
                  <span className="font-semibold">{chosen.length} selected</span>
                  <span className="flex-1" />
                  <Button small kind="primary" icon={<ClipboardList size={13} />} onClick={() => navigate(buyLink(chosenHealth))}>
                    Buy
                  </Button>
                  <Button small icon={<Sparkles size={13} />} onClick={() => ask(`Compare these products and tell me what to do with each: ${chosen.map((p) => `${p.name} (id ${p.id})`).join('; ')}.`)}>
                    Ask AI
                  </Button>
                  <Button small kind="ghost" onClick={() => setSelected(new Set())}>
                    Clear
                  </Button>
                </div>
              ) : null}
            </>
          }
          footer={
            <button className="hover:text-fg" onClick={() => set('archived', archived ? '' : '1')}>
              {archived ? 'Hide archived products' : 'Show archived products too'}
            </button>
          }
        >
          {list.isPending ? (
            <ListSkeleton />
          ) : items.length === 0 ? (
            <Empty icon={<Boxes size={20} />} title={search || flag || category || ids ? 'No products match these filters' : 'No products yet'} action={search || flag || category || ids ? <Button small onClick={() => setParams({})}>Clear filters</Button> : <Button kind="primary" small onClick={route.openNew}>New product</Button>} />
          ) : (
            items.map((product) => {
              const stock = n(product.stock)
              const row = byId.get(product.id)
              const action = row?.action.code ?? 'ok'
              return (
                <ListRow key={product.id} group="products" selected={product.id === route.id} onSelect={() => route.select(product.id)} alert={stock < 0}>
                  <div className="flex items-center gap-2.5">
                    <span
                      role="checkbox"
                      aria-checked={selected.has(product.id)}
                      aria-label={`Select ${product.name}`}
                      tabIndex={0}
                      onClick={(event) => {
                        event.stopPropagation()
                        toggle(product.id)
                      }}
                      onKeyDown={(event) => {
                        if (event.key === ' ' || event.key === 'Enter') {
                          event.preventDefault()
                          event.stopPropagation()
                          toggle(product.id)
                        }
                      }}
                      className={cn('grid size-[18px] shrink-0 place-items-center rounded-md ring-2 transition', selected.has(product.id) ? 'bg-solid text-on-brand ring-transparent' : 'ring-white/15 hover:ring-blue')}
                    >
                      {selected.has(product.id) ? <Check size={11} strokeWidth={3} /> : null}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="truncate text-[13px] font-semibold">{product.name}</span>
                        {!product.is_active ? <Badge>Archived</Badge> : null}
                      </div>
                      <div className="flex items-center gap-1.5 truncate text-[12px] text-fg-3">
                        <span className="truncate">
                          {product.sku}
                          {product.category ? ` · ${product.category}` : ''}
                        </span>
                        {ACTION_LABEL[action] ? <Badge tone={ACTION_TONE[action]}>{ACTION_LABEL[action]}</Badge> : null}
                      </div>
                    </div>
                    <div className="text-right">
                      <div className={cn('num text-[14px] font-semibold', stock < 0 ? 'text-bad' : stock === 0 ? 'text-fg-3' : undefined)}>{fmtQty(stock)}</div>
                      <div className="text-[11px] text-fg-3">{product.unit_of_measure}</div>
                    </div>
                  </div>
                </ListRow>
              )
            })
          )}
        </ListPane>
      }
    >
      {route.id ? <ProductInspector id={route.id} /> : <Empty className="h-full" icon={<Boxes size={22} />} title="Choose a product" body={chosen.length ? `${chosen.length} selected — use Buy to order them together.` : undefined} />}
      <ProductSheet open={route.isNew} onClose={route.closeNew} onSaved={route.select} />
    </SplitView>
  )
}

function ProductInspector({ id }: { id: string }) {
  const navigate = useNavigate()
  const product = useOne('product-inventory', api.products.inventory, id)
  const waiting = useOne('pending-orders', (pid: string) => api.products.pendingOrders(pid), id)
  const [tab, setTab] = useState('overview')
  const [sheet, setSheet] = useState<null | 'edit' | 'buy'>(null)
  const health = useQuery({ queryKey: ['insights', 'inventory'], queryFn: insights.inventory })
  const intel = health.data?.products.find((row) => row.product_id === id)
  const { ask } = useAssistant()
  const confirm = useConfirm()
  const archive = useAction(() => api.products.archive(id), { success: 'Product archived' })
  if (product.isPending) return <Spinner />
  if (!product.data) return <Empty title="This product could not be loaded" />
  const data = product.data
  const stock = n(data.stock)
  const waitingRows = (waiting.data?.items ?? []).filter((row) => n(row.quantity_pending) > 0)

  return (
    <>
      <InspectorHeader
        eyebrow={`Product · ${data.sku}${data.is_active ? '' : ' · archived'}`}
        title={data.name}
        badges={stock < 0 ? <Badge tone="bad" dot>Short {fmtQty(-stock)}</Badge> : stock === 0 ? <Badge tone="warn" dot>None free</Badge> : null}
        meta={`Sold in ${data.unit_of_measure} · MRP ${fmtMoney(data.mrp)}${data.description ? ` · ${data.description}` : ''}`}
        actions={
          <>
            <Button icon={<PackagePlus size={14} />} onClick={() => navigate(`/stock-in?product=${id}`)}>
              Stock in
            </Button>
            <Button kind="primary" icon={<ClipboardList size={14} />} onClick={() => (intel && intel.reorder_quantity > 0 ? navigate(buyLink([intel])) : setSheet('buy'))}>
              Buy
            </Button>
            <Menu
              trigger={
                <Button iconOnly aria-label="More actions">
                  <MoreHorizontal size={16} />
                </Button>
              }
              items={[
                { label: 'Edit product', icon: <Pencil size={14} />, onSelect: () => setSheet('edit') },
                {
                  label: 'Archive',
                  icon: <Archive size={14} />,
                  danger: true,
                  separator: true,
                  disabled: !data.is_active,
                  onSelect: async () => {
                    const answer = await confirm.ask({ title: `Archive ${data.name}?`, body: 'Its history stays. It no longer appears when choosing a product.', confirm: 'Archive', danger: true })
                    if (answer.ok) archive.mutate(undefined)
                  },
                },
              ]}
            />
          </>
        }
      />
      <FigureStrip
        items={[
          { label: 'Stock', value: fmtQty(stock), tone: stock < 0 ? 'bad' : 'sky', hint: stock < 0 ? 'sold more than bought' : 'bought less sold' },
          { label: 'To receive', value: fmtQty(data.on_order_quantity), tone: n(data.on_order_quantity) > 0 ? 'steel' : undefined, hint: 'bought, not arrived' },
          { label: 'To deliver', value: fmtQty(data.pending_quantity), hint: 'sold, not sent' },
          { label: 'In warehouse', value: fmtQty(data.physical_stock), hint: 'physically here' },
          { label: 'Avg cost', value: fmtMoney(data.average_cost), hint: data.last_purchase_price ? `last ${fmtMoney(data.last_purchase_price)}` : undefined },
          { label: 'Stock value', value: fmtMoney(data.stock_value) },
        ]}
      />
      <Tabs
        value={tab}
        onChange={setTab}
        className="min-h-0 flex-1"
        tabs={[
          { value: 'overview', label: 'Overview' },
          { value: 'waiting', label: 'Waiting customers', count: waitingRows.length },
          { value: 'ledger', label: 'Movements', count: data.movements.length },
          { value: 'layers', label: 'Cost layers', count: data.cost_layers.length },
        ]}
      >
        <TabPanel value="overview">
          {intel ? <Intelligence row={intel} onBuy={() => navigate(buyLink([intel]))} onAsk={() => ask(`Analyse product ${data.name} (id ${id}): demand trend, stock position, ageing, profitability and enquiries. Should we buy, hold or clear it, and how much?`)} /> : null}
          <Section title="Warehouse over time" hint="Physical quantity after each movement">
            <StockHistory data={data} />
          </Section>
          <Section title="How stock adds up">
            <div className="grid grid-cols-4 gap-3">
              {[
                ['In the warehouse', data.physical_stock, 'physically here'],
                ['+ To receive', data.on_order_quantity, 'bought, arriving'],
                ['− To deliver', data.pending_quantity, 'sold, not sent'],
                ['= Stock', data.stock, 'free to sell'],
              ].map(([label, value, hint], index) => (
                <div key={label} className={cn('card p-3.5', index === 3 && 'bg-sky/[0.06] ring-1 ring-sky/15')}>
                  <div className="text-[11.5px] text-fg-3">{label}</div>
                  <div className={cn('num mt-1 text-[18px] font-semibold', index === 3 && n(value) < 0 && 'text-bad')}>{fmtQty(value)}</div>
                  <div className="text-[11px] text-fg-4">{hint}</div>
                </div>
              ))}
            </div>
          </Section>
        </TabPanel>
        <TabPanel value="waiting">
          {waitingRows.length === 0 ? (
            <Empty title="Nobody is waiting" body="No open order is still owed this product." />
          ) : (
            <table className="grid-table">
              <thead>
                <tr>
                  <th>Customer · order</th>
                  <th className="r">To deliver</th>
                  <th className="r">Ready</th>
                  <th className="r">On order</th>
                  <th className="r">Short</th>
                </tr>
              </thead>
              <tbody>
                {waitingRows.map((row) => (
                  <tr key={row.order_item_id}>
                    <td>
                      <div className="text-[13px] font-medium">{row.customer_name}</div>
                      <Link to={`/orders/${row.order_id}`} className="num text-[11.5px] text-sky hover:text-sky-2">
                        {row.order_number}
                      </Link>
                      <span className="text-[11.5px] text-fg-3"> · {fmtDate(row.order_created_at)}</span>
                    </td>
                    <td className="r num">{fmtQty(row.quantity_pending)}</td>
                    <td className="r num text-sky">{n(row.quantity_reserved) > 0 ? fmtQty(row.quantity_reserved) : '—'}</td>
                    <td className="r num text-steel">{n(row.quantity_incoming) > 0 ? fmtQty(row.quantity_incoming) : '—'}</td>
                    <td className="r num text-bad">{n(row.quantity_unallocated) > 0 ? fmtQty(row.quantity_unallocated) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </TabPanel>
        <TabPanel value="ledger">
          <table className="grid-table">
            <thead>
              <tr>
                <th>When</th>
                <th>Movement</th>
                <th>Note</th>
                <th className="r">Change</th>
              </tr>
            </thead>
            <tbody>
              {[...data.movements].reverse().map((movement) => (
                <tr key={movement.id}>
                  <td className="text-[13px] text-fg-2">{fmtDateTime(movement.created_at)}</td>
                  <td>
                    <Badge tone={n(movement.quantity_change) >= 0 ? 'sky' : 'muted'}>{MOVEMENT[movement.movement_type] ?? movement.movement_type}</Badge>
                  </td>
                  <td className="max-w-[280px] truncate text-[12.5px] text-fg-3">{movement.note ?? '—'}</td>
                  <td className={cn('r num font-semibold', n(movement.quantity_change) >= 0 ? 'text-sky' : 'text-fg-2')}>
                    {n(movement.quantity_change) > 0 ? '+' : ''}
                    {fmtQty(movement.quantity_change)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TabPanel>
        <TabPanel value="layers">
          <table className="grid-table">
            <thead>
              <tr>
                <th>Received</th>
                <th>Source</th>
                <th className="r">Unit cost</th>
                <th className="r">Quantity</th>
                <th className="r">Left</th>
              </tr>
            </thead>
            <tbody>
              {data.cost_layers.map((layer) => (
                <tr key={layer.id} className={n(layer.quantity_remaining) === 0 ? 'opacity-50' : undefined}>
                  <td className="text-[13px] text-fg-2">{fmtDateTime(layer.created_at)}</td>
                  <td className="text-[13px]">{MOVEMENT[layer.source] ?? layer.source}</td>
                  <td className="r num">{fmtAmount(layer.unit_cost)}</td>
                  <td className="r num">{fmtQty(layer.quantity)}</td>
                  <td className="r num font-semibold">{fmtQty(layer.quantity_remaining)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="px-[18px] py-3 text-[12px] text-fg-3">Deliveries use the oldest layer first, so cost of goods follows what was actually bought.</p>
        </TabPanel>
      </Tabs>
      <ProductSheet open={sheet === 'edit'} onClose={() => setSheet(null)} editing={data} />
      <PurchaseSheet open={sheet === 'buy'} onClose={() => setSheet(null)} initial={{ lines: [{ product_id: id, quantity: String(Math.max(1, -stock)) }] }} onSaved={(po) => navigate(`/purchase-orders/${po.id}`)} />
      {confirm.element}
    </>
  )
}

/** Physical quantity after each movement, as a stepped light-blue line. */
function StockHistory({ data }: { data: ProductInventoryOut }) {
  const points = useMemo(() => {
    let running = 0
    return data.movements.map((movement) => {
      running += n(movement.quantity_change)
      return { at: movement.created_at, value: running }
    })
  }, [data])
  if (points.length < 2) return <p className="text-[12.5px] text-fg-3">Not enough movements to draw yet.</p>
  const width = 760
  const height = 120
  const max = Math.max(...points.map((point) => point.value), 1)
  const min = Math.min(...points.map((point) => point.value), 0)
  const x = (index: number) => (index / (points.length - 1)) * width
  const y = (value: number) => height - ((value - min) / (max - min || 1)) * (height - 10) - 5
  let d = `M0,${y(points[0].value)}`
  points.slice(1).forEach((point, index) => {
    d += ` H${x(index + 1)} V${y(point.value)}`
  })
  return (
    <div className="card p-4">
      <svg viewBox={`0 0 ${width} ${height}`} className="h-[120px] w-full" preserveAspectRatio="none">
        <defs>
          <linearGradient id="stockfill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" style={{ stopColor: "var(--color-blue)" }} stopOpacity="0.22" />
            <stop offset="1" style={{ stopColor: "var(--color-blue)" }} stopOpacity="0" />
          </linearGradient>
        </defs>
        <line x1="0" x2={width} y1={y(0)} y2={y(0)} style={{ stroke: "var(--hair)" }} strokeDasharray="3 4" />
        <motion.path d={`${d} V${height} H0 Z`} fill="url(#stockfill)" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.3 }} />
        <motion.path d={d} fill="none" style={{ stroke: "var(--color-blue)" }} strokeWidth="1.8" vectorEffect="non-scaling-stroke" initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 1.1, ease: [0.22, 1, 0.36, 1] }} />
      </svg>
      <div className="mt-2 flex justify-between text-[11px] text-fg-4">
        <span>{fmtDate(points[0].at)}</span>
        <span className="num text-fg-3">now {fmtQty(points[points.length - 1].value)}</span>
      </div>
    </div>
  )
}


/** What the numbers say about this product, and what to do. Recorded facts and
 *  estimates are kept apart. */
function Intelligence({ row, onBuy, onAsk }: { row: ProductHealth; onBuy: () => void; onAsk: () => void }) {
  const facts: [string, string, string?][] = [
    ['Sold, last 30 days', `${fmtQty(row.sold_30_days)} ${row.unit}`, row.demand_trend === 'insufficient_data' ? 'too little to call a trend' : `${row.demand_trend}${row.demand_change_percent !== null ? ` ${row.demand_change_percent > 0 ? '+' : ''}${row.demand_change_percent}%` : ''} vs the 30 before`],
    ['Last sale', row.days_since_last_sale === null ? 'Never' : `${row.days_since_last_sale} days ago`],
    ['Oldest stock', row.oldest_stock_days === null ? '—' : `${row.oldest_stock_days} days`, row.ages['90+'].value > 0 ? `${fmtMoney(row.ages['90+'].value)} over 90 days` : undefined],
    ['Open enquiries', `${fmtQty(row.open_enquiry_quantity)} ${row.unit}`, 'asked for, not yet ordered'],
    ['Sales at risk', fmtMoney(row.sales_at_risk_value), row.short > 0 ? `${fmtQty(row.short)} ${row.unit} sold with nothing behind it` : 'nothing short'],
    ['Turnover', row.turnover_per_year ? `${row.turnover_per_year}× a year` : '—', row.holding_days ? `stock is held about ${row.holding_days} days` : 'needs deliveries in the last 90 days'],
  ]
  const estimates: [string, string, string?][] = [
    ['Days of cover', row.days_of_cover === null ? '—' : `${row.days_of_cover} days`, 'at the recent sales rate'],
    ['Reorder point', `${fmtQty(row.reorder_point)} ${row.unit}`, `${row.lead_time_days}-day lead time (${row.lead_time_source === 'assumed' ? 'assumed — set it on the product or supplier' : `from the ${row.lead_time_source}`}) + minimum ${fmtQty(row.reorder_level)}`],
    ['Order by', row.order_by ?? '—', row.order_by ? 'so it arrives before stock drops below the reorder point' : undefined],
    ['Days to clear', row.days_to_clear === null ? '—' : `${row.days_to_clear} days`, 'to sell what is in the warehouse'],
  ]
  const urgent = row.action.code === 'buy' || row.action.code === 'liquidate'
  return (
    <Section
      title={
        <span className="flex items-center gap-2">
          {row.demand_trend === 'rising' ? <TrendingUp size={15} /> : row.demand_trend === 'falling' ? <TrendingDown size={15} /> : <Sparkles size={15} />}
          Recommendation: {row.action.text}
        </span>
      }
      hint={row.preferred_supplier_name ? `Usually bought from ${row.preferred_supplier_name}` : 'No preferred supplier set — edit the product to add one.'}
      actions={
        <div className="flex gap-2">
          <Button small icon={<Sparkles size={13} />} onClick={onAsk}>
            Ask AI
          </Button>
          {row.reorder_quantity > 0 ? (
            <Button small kind={urgent ? 'primary' : 'default'} icon={<ClipboardList size={13} />} onClick={onBuy}>
              Buy {fmtQty(row.reorder_quantity)} {row.unit}
            </Button>
          ) : null}
        </div>
      }
    >
      <div className="grid grid-cols-2 gap-3 max-lg:grid-cols-1">
        <div className="card p-3.5">
          <div className="eyebrow mb-2">Recorded</div>
          {facts.map(([label, value, hint]) => (
            <div key={label} className="flex items-baseline justify-between gap-3 py-1 text-[12.5px]">
              <span className="text-fg-3">{label}</span>
              <span className="text-right">
                <span className="num font-semibold">{value}</span>
                {hint ? <span className="block text-[11px] text-fg-4">{hint}</span> : null}
              </span>
            </div>
          ))}
        </div>
        <div className="card p-3.5">
          <div className="eyebrow mb-2">Estimated from recent sales</div>
          {estimates.map(([label, value, hint]) => (
            <div key={label} className="flex items-baseline justify-between gap-3 py-1 text-[12.5px]">
              <span className="text-fg-3">{label}</span>
              <span className="text-right">
                <span className="num font-semibold">{value}</span>
                {hint ? <span className="block text-[11px] text-fg-4">{hint}</span> : null}
              </span>
            </div>
          ))}
        </div>
      </div>
    </Section>
  )
}
