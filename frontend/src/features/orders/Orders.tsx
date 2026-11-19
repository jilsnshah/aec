import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Ban, ClipboardList, FileText, MoreHorizontal, Plus, ReceiptText, Scissors, Truck, UserRound } from 'lucide-react'
import { api } from '@/api/endpoints'
import { useAction, useList, useOne } from '@/api/queries'
import type { OrderDetailOut, OrderOut } from '@/api/types'
import { fmtAgo, fmtAmount, fmtDate, fmtDateTime, fmtMoney, fmtPercent, fmtQty, n, plural } from '@/lib/format'
import { useDebounced, useRecordRoute } from '@/lib/route'
import { ORDER_FILTERS, OrderBadge, STATE } from '@/lib/status'
import { Badge, Button, Empty, Facts, Meter, SearchBox, Spinner } from '@/ui/core'
import { Menu, Segmented, TabPanel, Tabs, useConfirm } from '@/ui/overlays'
import { FigureStrip, InspectorHeader, ListPane, ListRow, ListSkeleton, Section, SplitView } from '@/ui/split'
import { TallyPanel } from '@/features/integrations/TallyPanel'
import { PurchaseSheet } from '@/features/purchasing/PurchaseSheet'
import { DeliverSheet } from './DeliverSheet'
import { OrderSheet } from './OrderSheet'

export function lineParts(item: { quantity_fulfilled: string; quantity_reserved: string; quantity_incoming: string; quantity_unallocated: string }) {
  return [
    { label: 'Delivered', value: n(item.quantity_fulfilled), color: STATE.delivered },
    { label: 'Ready', value: n(item.quantity_reserved), color: STATE.ready },
    { label: 'On order', value: n(item.quantity_incoming), color: STATE.onOrder },
    { label: 'Short', value: n(item.quantity_unallocated), color: STATE.short },
  ]
}

function orderTotals(order: OrderOut) {
  const sum = (key: 'quantity_ordered' | 'quantity_fulfilled' | 'quantity_reserved' | 'quantity_incoming' | 'quantity_unallocated' | 'quantity_pending' | 'quantity_cancelled') =>
    order.items.reduce((total, item) => total + n(item[key]), 0)
  return {
    ordered: sum('quantity_ordered'),
    delivered: sum('quantity_fulfilled'),
    ready: sum('quantity_reserved'),
    onOrder: sum('quantity_incoming'),
    short: sum('quantity_unallocated'),
    pending: sum('quantity_pending'),
    cancelled: sum('quantity_cancelled'),
  }
}

export function Orders() {
  const route = useRecordRoute('/orders')
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState<string>('all')
  const query = useDebounced(search)
  const list = useList('orders', api.orders.list, { search: query, status: status === 'all' ? undefined : status, limit: 200 })
  const items = list.data?.items ?? []

  useEffect(() => {
    if (!route.id && items.length > 0 && window.innerWidth >= 1024 && !search) route.select(items[0].id)
  }, [route.id, items.length]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <SplitView
      showDetail={Boolean(route.id)}
      onBack={route.back}
      list={
        <ListPane
          title="Sales Orders"
          count={list.data?.total}
          actions={
            <Button kind="ghost" small iconOnly onClick={route.openNew} aria-label="New sales order">
              <Plus size={16} />
            </Button>
          }
          filters={
            <>
              <SearchBox value={search} onChange={setSearch} placeholder="Order, customer or product" />
              <Segmented value={status} onChange={setStatus} options={ORDER_FILTERS.map((filter) => ({ value: filter.value, label: filter.label }))} />
            </>
          }
        >
          {list.isPending ? (
            <ListSkeleton />
          ) : items.length === 0 ? (
            <Empty icon={<ReceiptText size={20} />} title={search ? 'No orders match' : 'No orders yet'} action={!search ? <Button kind="primary" small onClick={route.openNew}>New order</Button> : undefined} />
          ) : (
            items.map((order) => {
              const totals = orderTotals(order)
              return (
                <ListRow key={order.id} group="orders" selected={order.id === route.id} onSelect={() => route.select(order.id)} alert={totals.short > 0 && order.status !== 'CANCELLED'}>
                  <div className="flex items-baseline gap-2">
                    <span className="num text-[13px] font-semibold">{order.order_number}</span>
                    <span className="ml-auto num text-[13px] font-medium">{fmtMoney(order.total_amount)}</span>
                  </div>
                  <div className="mt-0.5 flex items-center gap-2 text-[12px] text-fg-3">
                    <span className="truncate">{order.customer.name}</span>
                    <span className="ml-auto shrink-0">{fmtDate(order.created_at)}</span>
                  </div>
                  <div className="mt-2 flex items-center gap-2.5">
                    <Meter parts={lineParts({ quantity_fulfilled: String(totals.delivered), quantity_reserved: String(totals.ready), quantity_incoming: String(totals.onOrder), quantity_unallocated: String(totals.short) })} />
                    <OrderBadge status={order.status} />
                  </div>
                </ListRow>
              )
            })
          )}
        </ListPane>
      }
    >
      {route.id ? <OrderInspector id={route.id} /> : <Empty className="h-full" icon={<ReceiptText size={22} />} title="Choose an order" body="Its lines, deliveries, profit and Tally status show here." />}
      <OrderSheet open={route.isNew} onClose={route.closeNew} onCreated={(order) => route.select(order.id)} />
    </SplitView>
  )
}

function OrderInspector({ id }: { id: string }) {
  const order = useOne('orders', api.orders.get, id)
  const [tab, setTab] = useState('lines')
  const [delivering, setDelivering] = useState(false)
  const [buying, setBuying] = useState(false)
  const confirm = useConfirm()
  const cancel = useAction((reason: string | null) => api.orders.cancel(id, reason), { success: 'Order cancelled' })
  const cancelRest = useAction((reason: string | null) => api.orders.cancelRemaining(id, reason), { success: 'The rest of the order was cancelled' })

  if (order.isPending) return <Spinner />
  if (!order.data) return <Empty title="This order could not be loaded" />
  const data = order.data
  const totals = orderTotals(data)
  const open = data.status === 'PENDING' || data.status === 'PARTIALLY_FULFILLED'

  async function askCancel(rest: boolean) {
    const answer = await confirm.ask({
      title: rest ? 'Cancel what is left?' : `Cancel ${data.order_number}?`,
      body: rest ? 'Delivered goods stay delivered. Everything still to deliver is cancelled and its stock is freed.' : 'Nothing has been delivered. The whole order is cancelled and its stock is freed.',
      confirm: rest ? 'Cancel the rest' : 'Cancel order',
      danger: true,
      withReason: true,
    })
    if (answer.ok) (rest ? cancelRest : cancel).mutate(answer.reason || null)
  }

  return (
    <>
      <InspectorHeader
        eyebrow={data.enquiry_number ? `Sales order · from ${data.enquiry_number}` : 'Sales order'}
        title={data.order_number}
        badges={<OrderBadge status={data.status} />}
        meta={
          <>
            <Link to={`/customers/${data.customer_id}`} className="text-sky hover:text-sky-2">
              {data.customer.name}
            </Link>{' '}
            · placed {fmtDateTime(data.created_at)}
          </>
        }
        actions={
          <>
            {open && totals.short > 0 ? (
              <Button kind={totals.ready > 0 ? 'quiet' : 'primary'} icon={<ClipboardList size={15} />} onClick={() => setBuying(true)}>
                Buy what is short
              </Button>
            ) : null}
            {open && totals.ready > 0 ? (
              <Button kind="primary" icon={<Truck size={15} />} onClick={() => setDelivering(true)}>
                Deliver {fmtQty(totals.ready)}
              </Button>
            ) : null}
            <Menu
              trigger={
                <Button iconOnly aria-label="More actions">
                  <MoreHorizontal size={16} />
                </Button>
              }
              items={[
                { label: 'Open invoice PDF', icon: <FileText size={14} />, onSelect: () => window.open(api.integrations.invoiceUrl(id), '_blank') },
                { label: 'Open customer', icon: <UserRound size={14} />, onSelect: () => (window.location.href = `/customers/${data.customer_id}`) },
                { label: 'Cancel what is left', icon: <Scissors size={14} />, onSelect: () => askCancel(true), disabled: !open || totals.delivered === 0, danger: true, separator: true },
                { label: 'Cancel order', icon: <Ban size={14} />, onSelect: () => askCancel(false), disabled: !open || totals.delivered > 0, danger: true },
              ]}
            />
          </>
        }
      />
      <FigureStrip
        items={[
          { label: 'Ordered', value: fmtQty(totals.ordered) },
          { label: 'Delivered', value: fmtQty(totals.delivered) },
          { label: 'Ready', value: fmtQty(totals.ready), tone: totals.ready > 0 ? 'sky' : undefined, hint: 'in stock' },
          { label: 'On order', value: fmtQty(totals.onOrder), tone: totals.onOrder > 0 ? 'steel' : undefined, hint: 'bought, coming' },
          { label: 'Short', value: fmtQty(totals.short), tone: totals.short > 0 ? 'bad' : undefined, hint: 'not bought yet' },
          { label: 'Value', value: fmtMoney(data.total_amount), hint: n(data.discount_amount) > 0 ? `−${fmtAmount(data.discount_amount)} discount` : 'before tax' },
        ]}
      />
      <Tabs
        value={tab}
        onChange={setTab}
        className="min-h-0 flex-1"
        tabs={[
          { value: 'lines', label: 'Lines', count: data.items.length },
          { value: 'deliveries', label: 'Deliveries' },
          { value: 'profit', label: 'Bill & profit' },
          { value: 'tally', label: 'Tally' },
        ]}
      >
        <TabPanel value="lines">
          <LinesTab order={data} />
        </TabPanel>
        <TabPanel value="deliveries">
          <DeliveriesTab id={id} />
        </TabPanel>
        <TabPanel value="profit">
          <ProfitTab order={data} />
        </TabPanel>
        <TabPanel value="tally">
          <TallyPanel entityId={id} />
        </TabPanel>
      </Tabs>
      <DeliverSheet orderId={id} open={delivering} onClose={() => setDelivering(false)} />
      <PurchaseSheet
        open={buying}
        onClose={() => setBuying(false)}
        subtitle={`For ${data.customer.name}'s ${fmtQty(totals.short)} units short on ${data.order_number}.`}
        initial={{
          lines: data.items.filter((item) => n(item.quantity_unallocated) > 0).map((item) => ({ product_id: item.product_id, quantity: String(n(item.quantity_unallocated)) })),
          prefer: data.items.find((item) => n(item.quantity_unallocated) > 0)?.id,
        }}
      />
      {confirm.element}
    </>
  )
}

function LinesTab({ order }: { order: OrderDetailOut }) {
  return (
    <div className="pb-4">
      <table className="grid-table">
        <thead>
          <tr>
            <th>Product</th>
            <th className="r">Price</th>
            <th className="r">Ordered</th>
            <th className="w-[200px]">Where it stands</th>
            <th className="r">To deliver</th>
            <th className="r">Total</th>
          </tr>
        </thead>
        <tbody>
          {order.items.map((item) => (
            <tr key={item.id}>
              <td>
                <Link to={`/products/${item.product_id}`} className="text-[13px] font-medium hover:text-sky">
                  {item.product.name}
                </Link>
                <div className="text-[11.5px] text-fg-3">
                  {item.product.sku} · {item.product.unit_of_measure}
                </div>
              </td>
              <td className="r num text-[13px]">
                {fmtAmount(item.unit_price_net)}
                {n(item.discount_percent) > 0 ? <div className="text-[11px] text-fg-3">−{fmtPercent(item.discount_percent)}</div> : null}
              </td>
              <td className="r num">{fmtQty(item.quantity_ordered)}</td>
              <td>
                <Meter parts={lineParts(item)} total={n(item.quantity_ordered) - n(item.quantity_cancelled)} />
                <div className="mt-1.5 flex flex-wrap gap-x-2 text-[11px] text-fg-3">
                  {n(item.quantity_fulfilled) > 0 ? <span>{fmtQty(item.quantity_fulfilled)} sent</span> : null}
                  {n(item.quantity_reserved) > 0 ? <span className="text-sky">{fmtQty(item.quantity_reserved)} ready</span> : null}
                  {n(item.quantity_incoming) > 0 ? <span className="text-steel">{fmtQty(item.quantity_incoming)} on order</span> : null}
                  {n(item.quantity_unallocated) > 0 ? <span className="text-bad">{fmtQty(item.quantity_unallocated)} short</span> : null}
                  {n(item.quantity_cancelled) > 0 ? <span>{fmtQty(item.quantity_cancelled)} cancelled</span> : null}
                </div>
              </td>
              <td className="r num font-semibold">{n(item.quantity_pending) > 0 ? fmtQty(item.quantity_pending) : '—'}</td>
              <td className="r num">{fmtAmount(n(item.unit_price_net) * n(item.quantity_ordered))}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <Legend />
      {order.notes ? (
        <Section title="Notes">
          <p className="text-[13px] whitespace-pre-line text-fg-2" data-selectable>
            {order.notes}
          </p>
        </Section>
      ) : null}
    </div>
  )
}

export function Legend() {
  return (
    <div className="flex gap-4 px-[18px] pt-3 text-[11.5px] text-fg-3">
      {[
        ['Delivered', STATE.delivered],
        ['Ready', STATE.ready],
        ['On order', STATE.onOrder],
        ['Short', STATE.short],
      ].map(([label, color]) => (
        <span key={label} className="flex items-center gap-1.5">
          <span className="size-2 rounded-sm" style={{ background: color }} />
          {label}
        </span>
      ))}
    </div>
  )
}

function DeliveriesTab({ id }: { id: string }) {
  const fulfilment = useOne('fulfilment', api.orders.fulfilment, id)
  if (fulfilment.isPending) return <Spinner />
  const deliveries = fulfilment.data?.deliveries ?? []
  if (deliveries.length === 0) return <Empty icon={<Truck size={20} />} title="Nothing delivered yet" body="Deliveries appear here as the truck leaves." />
  return (
    <div className="space-y-2 p-4">
      {deliveries.map((delivery) => (
        <div key={delivery.id} className="card p-4">
          <div className="flex items-center gap-2">
            <span className="grid size-8 place-items-center rounded-lg bg-sky/10 text-sky">
              <Truck size={15} />
            </span>
            <div className="min-w-0 flex-1">
              <div className="num text-[13px] font-semibold">{delivery.delivery_number}</div>
              <div className="text-[12px] text-fg-3">
                {fmtDateTime(delivery.created_at)}
                {delivery.reference ? ` · ${delivery.reference}` : ''}
              </div>
            </div>
            <span className="text-[12px] text-fg-3">{fmtAgo(delivery.created_at)}</span>
          </div>
          <div className="mt-3 space-y-1 pl-10">
            {delivery.lines.map((line) => (
              <div key={line.product_sku} className="flex justify-between text-[12.5px]">
                <span className="text-fg-2">{line.product_name}</span>
                <span className="num">{fmtQty(line.quantity)}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

function ProfitTab({ order }: { order: OrderDetailOut }) {
  const totals = order.financials?.totals
  if (!totals) return <Empty title="No figures yet" />
  return (
    <div className="grid grid-cols-2 gap-4 p-5">
      <div className="card px-4 py-2">
        <div className="eyebrow pt-2 pb-1">Bill</div>
        <Facts
          items={[
            { label: 'Subtotal at MRP', value: fmtMoney(totals.subtotal_amount) },
            { label: 'Discount', value: n(totals.discount_amount) > 0 ? `−${fmtMoney(totals.discount_amount)}` : '—' },
            { label: 'Order total', value: fmtMoney(totals.total_amount), strong: true },
            { label: 'Cancelled', value: n(totals.cancelled_amount) > 0 ? fmtMoney(totals.cancelled_amount) : '—' },
          ]}
        />
      </div>
      <div className="card px-4 py-2">
        <div className="eyebrow pt-2 pb-1">Profit on delivered goods</div>
        <Facts
          items={[
            { label: 'Delivered', value: fmtMoney(totals.delivered_amount) },
            { label: 'Cost of goods', value: fmtMoney(totals.cost_of_goods_sold) },
            { label: 'Gross profit', value: <span className={n(totals.gross_profit) < 0 ? 'text-bad' : 'text-ok'}>{fmtMoney(totals.gross_profit)}</span>, strong: true },
            { label: 'Margin', value: fmtPercent(totals.margin_percent) },
            { label: 'Still to deliver', value: fmtMoney(totals.pending_amount) },
          ]}
        />
      </div>
      {order.allocations.length > 0 ? (
        <div className="card col-span-2 overflow-hidden">
          <div className="eyebrow px-[18px] pt-3.5 pb-1">Where delivered stock came from</div>
          <table className="grid-table">
            <thead>
              <tr>
                <th>Product</th>
                <th>Source</th>
                <th className="r">Quantity</th>
                <th className="r">Cost</th>
              </tr>
            </thead>
            <tbody>
              {order.allocations.map((allocation) => (
                <tr key={allocation.allocation_id}>
                  <td className="text-[13px]">{allocation.product_name}</td>
                  <td>
                    <Badge tone="muted">{allocation.source === 'ORDER_CREATION' ? 'Stock at order time' : allocation.source === 'GOODS_RECEIPT' ? 'Goods receipt' : 'Stock in'}</Badge>
                  </td>
                  <td className="r num">{fmtQty(allocation.quantity)}</td>
                  <td className="r num">{fmtAmount(allocation.cost_amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <p className="col-span-2 text-[12px] text-fg-3">{plural(order.items.length, 'line')} · prices are before tax.</p>
    </div>
  )
}
