import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { motion } from 'motion/react'
import { Archive, Boxes, ClipboardList, MoreHorizontal, PackagePlus, Pencil, Plus } from 'lucide-react'
import { api } from '@/api/endpoints'
import { useAction, useList, useOne } from '@/api/queries'
import type { ProductInventoryOut } from '@/api/types'
import { cn } from '@/lib/cn'
import { fmtAmount, fmtDate, fmtDateTime, fmtMoney, fmtQty, n } from '@/lib/format'
import { useDebounced, useRecordRoute } from '@/lib/route'
import { Badge, Button, Empty, SearchBox, Spinner } from '@/ui/core'
import { Menu, Segmented, TabPanel, Tabs, useConfirm } from '@/ui/overlays'
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

export function Products() {
  const route = useRecordRoute('/products')
  const [search, setSearch] = useState('')
  const [scope, setScope] = useState<'active' | 'short' | 'all'>('active')
  const query = useDebounced(search)
  const list = useList('products', api.products.list, { search: query, include_inactive: scope === 'all', limit: 500, sort_by: 'name', sort_dir: 'asc' as const })
  const items = (list.data?.items ?? []).filter((product) => scope !== 'short' || n(product.stock) < 0)
  useEffect(() => {
    if (!route.id && items.length > 0 && window.innerWidth >= 1024 && !search) route.select(items[0].id)
  }, [route.id, items.length]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <SplitView
      showDetail={Boolean(route.id)}
      onBack={route.back}
      list={
        <ListPane
          title="Products"
          count={list.data?.total}
          actions={
            <Button kind="ghost" small iconOnly onClick={route.openNew} aria-label="New product">
              <Plus size={16} />
            </Button>
          }
          filters={
            <>
              <SearchBox value={search} onChange={setSearch} placeholder="Name or code" />
              <Segmented
                value={scope}
                onChange={setScope}
                options={[
                  { value: 'active', label: 'Active' },
                  { value: 'short', label: 'Short', count: (list.data?.items ?? []).filter((product) => n(product.stock) < 0).length },
                  { value: 'all', label: 'With archived' },
                ]}
              />
            </>
          }
        >
          {list.isPending ? (
            <ListSkeleton />
          ) : items.length === 0 ? (
            <Empty icon={<Boxes size={20} />} title={search ? 'No products match' : scope === 'short' ? 'Nothing is short' : 'No products yet'} action={scope !== 'short' ? <Button kind="primary" small onClick={route.openNew}>New product</Button> : undefined} />
          ) : (
            items.map((product) => {
              const stock = n(product.stock)
              return (
                <ListRow key={product.id} group="products" selected={product.id === route.id} onSelect={() => route.select(product.id)} alert={stock < 0}>
                  <div className="flex items-center gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="truncate text-[13px] font-semibold">{product.name}</span>
                        {!product.is_active ? <Badge>Archived</Badge> : null}
                      </div>
                      <div className="truncate text-[12px] text-fg-3">
                        {product.sku} · MRP {fmtAmount(product.mrp)}
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
      {route.id ? <ProductInspector id={route.id} /> : <Empty className="h-full" icon={<Boxes size={22} />} title="Choose a product" />}
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
            <Button kind="primary" icon={<ClipboardList size={14} />} onClick={() => setSheet('buy')}>
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
            <stop offset="0" stopColor="#7cc4ff" stopOpacity="0.22" />
            <stop offset="1" stopColor="#7cc4ff" stopOpacity="0" />
          </linearGradient>
        </defs>
        <line x1="0" x2={width} y1={y(0)} y2={y(0)} stroke="rgba(255,255,255,0.08)" strokeDasharray="3 4" />
        <motion.path d={`${d} V${height} H0 Z`} fill="url(#stockfill)" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.3 }} />
        <motion.path d={d} fill="none" stroke="#7cc4ff" strokeWidth="1.8" vectorEffect="non-scaling-stroke" initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 1.1, ease: [0.22, 1, 0.36, 1] }} />
      </svg>
      <div className="mt-2 flex justify-between text-[11px] text-fg-4">
        <span>{fmtDate(points[0].at)}</span>
        <span className="num text-fg-3">now {fmtQty(points[points.length - 1].value)}</span>
      </div>
    </div>
  )
}
