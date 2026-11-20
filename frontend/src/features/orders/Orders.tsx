import { QtyCell, perUnit } from '@/ui/lines'
import { DeliveryEway } from './DeliveryEway'
import { BookingSheet } from '@/features/transport/BookingSheet'
import { useEffect, useState, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { parties } from '@/api/parties'
import { http } from '@/api/client'
import {
  AlertTriangle,
  Ban,
  Building2,
  Check,
  CheckCircle2,
  CircleDollarSign,
  ClipboardList,
  Clock,
  FileText,
  Layers,
  MessageCircle,
  MoreHorizontal,
  PackageCheck,
  Plus,
  ReceiptText,
  Repeat2,
  Send,
  Undo2,
  Scissors,
  ShoppingCart,
  Truck,
  UserRound,
  XCircle,
} from 'lucide-react'
import { api } from '@/api/endpoints'
import { useAction, useList, useOne } from '@/api/queries'
import type { OrderDetailOut, OrderOut } from '@/api/types'
import { fmtAgo, fmtAmount, fmtDate, fmtDateTime, fmtMoney, fmtPercent, fmtQty, n, plural } from '@/lib/format'
import { useDebounced, useRecordRoute } from '@/lib/route'
import { OrderBadge, STATE } from '@/lib/status'
import { cn } from '@/lib/cn'
import { AiStrip, AskButton, PageGuide, PayBadge, QuickChips, Timeline, useOrderPayments, type Chip } from '@/ui/smart'
import type { OrderPayment } from '@/api/records'
import { Badge, Button, Empty, Facts, Meter, SearchBox, Spinner } from '@/ui/core'
import { Menu, TabPanel, Tabs, useConfirm } from '@/ui/overlays'
import { FigureStrip, InspectorHeader, ListPane, ListRow, ListSkeleton, Section, SplitView } from '@/ui/split'
import { TallyPanel } from '@/features/integrations/TallyPanel'
import { PurchaseSheet } from '@/features/purchasing/PurchaseSheet'
import { DeliverSheet } from './DeliverSheet'
import { OrderSheet } from './OrderSheet'
import { ReturnSheet } from './ReturnSheet'
import { returns as returnsApi } from '@/api/records'

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

type OrderChip = 'all' | 'open' | 'ready' | 'short' | 'overdue' | 'unpaid' | 'done' | 'cancelled'

function matches(chip: OrderChip, order: OrderOut, payment?: OrderPayment) {
  const totals = orderTotals(order)
  const open = order.status === 'PENDING' || order.status === 'PARTIALLY_FULFILLED'
  switch (chip) {
    case 'open':
      return open
    case 'ready':
      return open && totals.ready > 0
    case 'short':
      return open && totals.short > 0
    case 'overdue':
      return payment?.status === 'overdue'
    case 'unpaid':
      return Boolean(payment && payment.open > 0.005)
    case 'done':
      return order.status === 'FULFILLED'
    case 'cancelled':
      return order.status === 'CANCELLED'
    default:
      return true
  }
}

export function Orders() {
  const route = useRecordRoute('/orders')
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [chip, setChip] = useState<OrderChip>((route.param('show') as OrderChip) || 'open')
  const query = useDebounced(search)
  const list = useList('orders', api.orders.list, { search: query, limit: 500 })
  const payments = useOrderPayments().data ?? {}
  const all = list.data?.items ?? []
  const items = all.filter((order) => matches(chip, order, payments[order.id]))
  const count = (key: OrderChip) => all.filter((order) => matches(key, order, payments[order.id])).length
  const chips: Chip<OrderChip>[] = [
    { key: 'open', label: 'Open', icon: Layers, count: count('open') },
    { key: 'ready', label: 'Ready to send', icon: Truck, count: count('ready'), hot: count('ready') > 0 },
    { key: 'short', label: 'Short', icon: AlertTriangle, count: count('short'), hot: count('short') > 0 },
    { key: 'overdue', label: 'Payment overdue', icon: Clock, count: count('overdue'), hot: count('overdue') > 0 },
    { key: 'unpaid', label: 'Unpaid', icon: CircleDollarSign, count: count('unpaid') },
    { key: 'done', label: 'Delivered', icon: CheckCircle2, count: count('done') },
    { key: 'cancelled', label: 'Cancelled', icon: XCircle, count: count('cancelled') },
    { key: 'all', label: 'All', count: all.length },
  ]
  const readyValue = all.filter((order) => matches('ready', order)).length
  const overdue = Object.values(payments).filter((payment) => payment.status === 'overdue')
  const overdueValue = overdue.reduce((sum, payment) => sum + payment.open, 0)
  const shortOrders = count('short')

  useEffect(() => {
    if (list.data && chip === 'open' && count('open') === 0) setChip('all')
  }, [list.data]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    // A quick filter that hides the open record moves to the first one shown.
    if (route.id && items.length > 0 && !items.some((row) => row.id === route.id) && window.innerWidth >= 1024) route.select(items[0].id)
  }, [chip]) // eslint-disable-line react-hooks/exhaustive-deps
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
            <>
              <PageGuide
                title="Sales orders"
                points={[
                  { icon: ShoppingCart, text: 'An order takes free stock the moment it is placed. What is not in stock waits as short.' },
                  { icon: Truck, text: '"Ready to send" orders have stock set aside: open one and press Deliver.' },
                  { icon: AlertTriangle, text: '"Short" orders need buying: open one and press "Buy what is short" for a pre-filled purchase order.' },
                  { icon: CircleDollarSign, text: 'Each row shows whether delivered goods are paid. Overdue counts days past the customer\'s credit terms.' },
                ]}
              />
              <Button kind="primary" small icon={<Plus size={14} />} onClick={route.openNew} aria-label="New sales order">
                New
              </Button>
            </>
          }
          filters={
            <>
              <SearchBox value={search} onChange={setSearch} placeholder="Order, customer or product" />
              <QuickChips chips={chips} value={chip} onChange={setChip} />
            </>
          }
        >
          {!search && chip === 'open' && all.length > 0 ? (
            <AiStrip
              className="mx-1.5 mb-2"
              insights={[
                readyValue ? { icon: Truck, text: <><b>{plural(readyValue, 'order')}</b> can be delivered now.</>, onClick: () => setChip('ready') } : null,
                shortOrders ? { icon: AlertTriangle, text: <><b>{plural(shortOrders, 'order')}</b> wait for stock — buy to release them.</>, onClick: () => setChip('short') } : null,
                overdue.length ? { icon: Clock, text: <><b>{fmtMoney(overdueValue)}</b> overdue on {plural(overdue.length, 'order')}.</>, onClick: () => setChip('overdue') } : null,
              ].filter(Boolean) as { icon: typeof Truck; text: ReactNode; onClick: () => void }[]}
              prompts={[
                { label: 'What to deliver first?', question: 'Which open orders should I deliver first today and why? Consider stock that is ready, how long each customer has waited and what they owe.' },
                { label: 'Who to chase?', question: 'Which customers should I chase for payment today? List overdue orders with amounts and days late, and draft a polite WhatsApp reminder for the biggest.' },
              ]}
            />
          ) : null}
          {list.isPending ? (
            <ListSkeleton />
          ) : items.length === 0 ? (
            <Empty icon={<ReceiptText size={20} />} title={search ? 'No orders match' : chip === 'all' ? 'No orders yet' : 'Nothing here'} body={chip !== 'all' && !search ? 'Try another filter above.' : undefined} action={!search && chip === 'all' ? <Button kind="primary" small onClick={route.openNew}>New order</Button> : undefined} />
          ) : (
            items.map((order) => {
              const totals = orderTotals(order)
              const open = order.status === 'PENDING' || order.status === 'PARTIALLY_FULFILLED'
              return (
                <ListRow key={order.id} group="orders" selected={order.id === route.id} onSelect={() => route.select(order.id)} alert={totals.short > 0 && open}>
                  <div className="flex items-baseline gap-2">
                    <span className="num text-[13px] font-semibold">{order.order_number}</span>
                    {open && totals.ready > 0 ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-blue/20 px-1.5 text-[10.5px] font-semibold text-fg" title="Stock is set aside and can be delivered">
                        <Truck size={10} /> ready
                      </span>
                    ) : null}
                    <span className="ml-auto num text-[13px] font-medium">{fmtMoney(order.total_amount)}</span>
                  </div>
                  <div className="mt-0.5 flex items-center gap-2 text-[12px] text-fg-3">
                    <span className="truncate">{order.customer.name}</span>
                    <span className="ml-auto shrink-0">{fmtAgo(order.created_at)}</span>
                  </div>
                  <div className="mt-2 flex items-center gap-2">
                    <Meter parts={lineParts({ quantity_fulfilled: String(totals.delivered), quantity_reserved: String(totals.ready), quantity_incoming: String(totals.onOrder), quantity_unallocated: String(totals.short) })} />
                    <PayBadge payment={payments[order.id]} />
                    <OrderBadge status={order.status} />
                  </div>
                </ListRow>
              )
            })
          )}
        </ListPane>
      }
    >
      {route.id ? (
        <OrderInspector id={route.id} payment={payments[route.id]} onRepeat={(id) => navigate(`/orders?new=1&repeat=${id}`)} />
      ) : (
        <Empty className="h-full" icon={<ReceiptText size={22} />} title="Choose an order" body="Its lines, deliveries, payment, profit and history show here." />
      )}
      <OrderSheet open={route.isNew} onClose={route.closeNew} onCreated={(order) => route.select(order.id)} repeatFrom={route.param('repeat') ?? undefined} customerId={route.param('customer') ?? undefined} />
    </SplitView>
  )
}

/** Where an order stands, as four steps. */
function Stepper({ order, payment }: { order: OrderDetailOut; payment?: OrderPayment }) {
  const totals = orderTotals(order)
  const live = totals.ordered - totals.cancelled
  const cancelled = order.status === 'CANCELLED'
  const steps = [
    { label: 'Placed', icon: ShoppingCart, done: true, hint: fmtDate(order.created_at) },
    { label: 'Stock ready', icon: PackageCheck, done: live > 0 && totals.short + totals.onOrder === 0, hint: totals.short > 0 ? `${fmtQty(totals.short)} short` : totals.onOrder > 0 ? `${fmtQty(totals.onOrder)} on order` : 'all in stock' },
    { label: 'Delivered', icon: Truck, done: order.status === 'FULFILLED', hint: totals.delivered > 0 ? `${fmtQty(totals.delivered)} of ${fmtQty(live)}` : 'not yet' },
    { label: 'Paid', icon: CircleDollarSign, done: payment?.status === 'paid' && order.status === 'FULFILLED', hint: payment ? `${fmtMoney(payment.paid)} of ${fmtMoney(payment.invoiced)}` : 'nothing billed' },
  ]
  const current = steps.findIndex((step) => !step.done)
  return (
    <div className="flex shrink-0 items-start gap-0 border-b border-white/7 px-7 py-4 max-md:px-4">
      {steps.map((step, index) => {
        const Icon = step.done ? Check : step.icon
        const active = index === current && !cancelled
        return (
          <div key={step.label} className="flex min-w-0 flex-1 items-start">
            <div className="flex min-w-0 flex-col items-center text-center">
              <span className={cn('grid size-8 place-items-center rounded-full', step.done ? 'icon-disc' : active ? 'bg-blue text-[#0b0b0c] ring-4 ring-blue/25' : 'bg-white/7 text-fg-3')}>
                <Icon size={14} strokeWidth={step.done ? 3 : 2} />
              </span>
              <span className={cn('mt-1.5 text-[12px] font-semibold', !step.done && !active && 'text-fg-3')}>{step.label}</span>
              <span className="text-[11px] text-fg-3">{cancelled && !step.done ? 'cancelled' : step.hint}</span>
            </div>
            {index < steps.length - 1 ? <span className={cn('mx-2 mt-4 h-[2px] flex-1 rounded-full', steps[index + 1].done ? 'bg-fg' : 'bg-white/10')} /> : null}
          </div>
        )
      })}
    </div>
  )
}

function OrderInspector({ id, payment, onRepeat }: { id: string; payment?: OrderPayment; onRepeat: (id: string) => void }) {
  const order = useOne('orders', api.orders.get, id)
  const customer = useQuery({ queryKey: ['customers', 'one', order.data?.customer_id], enabled: Boolean(order.data), queryFn: () => api.customers.get(order.data!.customer_id) })
  const partyProfile = useQuery({ queryKey: ['parties', 'customer', order.data?.customer_id], enabled: Boolean(order.data?.delivery_address_id || order.data?.contact_id), queryFn: () => parties.profile('customer', order.data!.customer_id) })
  const [tab, setTab] = useState('lines')
  const [delivering, setDelivering] = useState(false)
  const [buying, setBuying] = useState(false)
  const [returning, setReturning] = useState(false)
  const [booking, setBooking] = useState(false)
  const sendConfirmation = useAction(() => http.post<{ to: string }>(`/api/orders/${id}/send-confirmation`), { success: (r) => `Confirmation sent to ${r.to}` })
  const confirm = useConfirm()
  const cancel = useAction((reason: string | null) => api.orders.cancel(id, reason), { success: 'Order cancelled' })
  const cancelRest = useAction((reason: string | null) => api.orders.cancelRemaining(id, reason), { success: 'The rest of the order was cancelled' })

  if (order.isPending) return <Spinner />
  if (!order.data) return <Empty title="This order could not be loaded" />
  const data = order.data
  const totals = orderTotals(data)
  const open = data.status === 'PENDING' || data.status === 'PARTIALLY_FULFILLED'
  const site = partyProfile.data?.addresses.find((a) => a.id === data.delivery_address_id)
  const orderedBy = partyProfile.data?.contacts.find((c) => c.id === data.contact_id)
  const phone = customer.data?.phone?.replace(/\D/g, '').replace(/^(\d{10})$/, '91$1')
  const update = `Hello ${data.customer.name}, an update on your order ${data.order_number}: ${fmtQty(totals.delivered)} delivered${totals.ready > 0 ? `, ${fmtQty(totals.ready)} ready to dispatch` : ''}${totals.short + totals.onOrder > 0 ? `, ${fmtQty(totals.short + totals.onOrder)} arriving soon` : ''}.${payment && payment.open > 0 ? ` Amount due: ${fmtMoney(payment.open)}.` : ''} Thank you.`

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
            {site ? <> · <Building2 size={12} className="inline" /> {site.label || 'Site'}{site.city ? `, ${site.city}` : ''}</> : null}
            {orderedBy ? ` · by ${orderedBy.name}` : null}
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
            <AskButton question={`Explain where order ${data.order_number} for ${data.customer.name} stands: what is delivered, ready, short and paid, its profit, and what I should do next.`} />
            <Menu
              trigger={
                <Button iconOnly aria-label="More actions">
                  <MoreHorizontal size={16} />
                </Button>
              }
              items={[
                { label: 'Open invoice PDF', icon: <FileText size={14} />, onSelect: () => window.open(api.integrations.invoiceUrl(id), '_blank') },
                { label: 'Open customer', icon: <UserRound size={14} />, onSelect: () => (window.location.href = `/customers/${data.customer_id}`) },
                { label: 'Repeat this order', icon: <Repeat2 size={14} />, onSelect: () => onRepeat(id) },
                { label: 'Book transport', icon: <Truck size={14} />, onSelect: () => setBooking(true), disabled: !open },
                { label: 'Record a return', icon: <Undo2 size={14} />, onSelect: () => setReturning(true), disabled: totals.delivered === 0 },
                { label: 'Send order confirmation (WhatsApp template)', icon: <Send size={14} />, onSelect: () => sendConfirmation.mutate(undefined) },
                { label: 'Send update on WhatsApp', icon: <MessageCircle size={14} />, onSelect: () => window.open(`https://wa.me/${phone}?text=${encodeURIComponent(update)}`, '_blank'), disabled: !phone },
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
          { label: 'Paid', value: payment ? fmtMoney(payment.paid) : '—', tone: payment?.status === 'overdue' ? 'bad' : payment?.status === 'paid' ? 'ok' : undefined, hint: payment ? (payment.open > 0 ? `${fmtMoney(payment.open)} due${payment.days_overdue ? ` · ${payment.days_overdue}d late` : ''}` : 'settled') : 'nothing delivered yet' },
        ]}
      />
      <Stepper order={data} payment={payment} />
      <Tabs
        value={tab}
        onChange={setTab}
        className="min-h-0 flex-1"
        tabs={[
          { value: 'lines', label: 'Lines', count: data.items.length },
          { value: 'deliveries', label: 'Deliveries' },
          { value: 'profit', label: 'Bill & profit' },
          { value: 'activity', label: 'Activity' },
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
        <TabPanel value="activity">
          <Timeline target={{ order_id: id }} />
        </TabPanel>
        <TabPanel value="tally">
          <TallyPanel entityId={id} />
        </TabPanel>
      </Tabs>
      <DeliverSheet orderId={id} open={delivering} onClose={() => setDelivering(false)} />
      <ReturnSheet orderId={id} orderNumber={data.order_number} open={returning} onClose={() => setReturning(false)} />
      <BookingSheet open={booking} onClose={() => setBooking(false)} referenceType="sales_order" referenceId={id} />
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
                {fmtAmount(perUnit(item.unit_price_net, item))}
                {item.unit ? <div className="text-[11px] text-fg-3">per {item.unit}</div> : null}
                {n(item.discount_percent) > 0 ? <div className="text-[11px] text-fg-3">−{fmtPercent(item.discount_percent)}</div> : null}
              </td>
              <td className="r num">
                <QtyCell item={item} base={item.quantity_ordered} />
              </td>
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
  const credit = useQuery({ queryKey: ['returns', 'order', id], queryFn: () => returnsApi.forOrder(id) })
  if (fulfilment.isPending) return <Spinner />
  const deliveries = fulfilment.data?.deliveries ?? []
  const back = credit.data?.items ?? []
  if (deliveries.length === 0 && !back.length) return <Empty icon={<Truck size={20} />} title="Nothing delivered yet" body="Deliveries appear here as the truck leaves." />
  return (
    <div className="space-y-2 p-4">
      {back.map((r) => (
        <div key={r.id} className="card flex items-center gap-3 p-4">
          <span className="grid size-8 place-items-center rounded-lg bg-[#0b0b0c] text-[#fff]">
            <Undo2 size={15} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="num text-[13px] font-semibold">
              {r.number} · returned {r.lines.map((line) => `${fmtQty(line.quantity)} ${line.product_name}${line.restock ? '' : ' (damaged)'}`).join(', ')}
            </div>
            <div className="text-[12px] text-fg-3">
              {fmtDateTime(r.created_at)} · {r.reason_label}
              {r.note ? ` · ${r.note}` : ''}
            </div>
          </div>
          <span className="num text-[13px] font-semibold">−{fmtMoney(r.amount)}</span>
        </div>
      ))}
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
          <div className="pl-10">
            <DeliveryEway orderId={id} deliveryId={delivery.id} />
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
