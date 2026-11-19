import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { finance } from '@/api/finance'
import { Account } from '@/features/finance/Account'
import { RecordTasks } from '@/features/tasks/RecordTasks'
import { useAssistant } from '@/features/assistant/store'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Archive, BadgePercent, CalendarClock, Clock, Crown, Gauge as GaugeIcon, HeartHandshake, IndianRupee, Mail, MapPin, MessageSquareQuote, Moon, MoreHorizontal, Pencil, Phone, Plus, Repeat2, ShoppingCart, Sparkles, Trophy, Truck, UserPlus, Users, MessageCircle, Wallet, AlertTriangle } from 'lucide-react'
import type { ReactNode } from 'react'
import { insights, type Segment } from '@/api/insights'
import { records } from '@/api/records'
import { AiStrip, AskButton, Gauge, MiniBars, PageGuide, QuickChips, Stat, Timeline, type Chip } from '@/ui/smart'
import { api } from '@/api/endpoints'
import { useAction, useList, useOne } from '@/api/queries'
import { fmtCompactMoney, fmtDate, fmtMoney, fmtQty, n, plural } from '@/lib/format'
import { useDebounced, useRecordRoute } from '@/lib/route'
import { EnquiryBadge, OrderBadge } from '@/lib/status'
import { Avatar, Badge, Button, Empty, SearchBox, Spinner } from '@/ui/core'
import { Menu, TabPanel, Tabs, useConfirm } from '@/ui/overlays'
import { FigureStrip, InspectorHeader, ListPane, ListRow, ListSkeleton, SplitView } from '@/ui/split'
import { EnquirySheet } from '@/features/enquiries/EnquirySheet'
import { OrderSheet } from '@/features/orders/OrderSheet'
import { PartySheet } from './PartySheet'

export const SEGMENT_LABEL: Record<Segment, [string, typeof Crown]> = {
  champion: ['Champion', Crown],
  loyal: ['Loyal', HeartHandshake],
  at_risk: ['At risk', AlertTriangle],
  dormant: ['Dormant', Moon],
  new: ['New', UserPlus],
  occasional: ['Occasional', Repeat2],
}

export function SegmentBadge({ segment }: { segment?: Segment | string }) {
  const entry = segment ? SEGMENT_LABEL[segment as Segment] : undefined
  if (!entry) return null
  const [label, Icon] = entry
  return (
    <Badge tone={segment === 'champion' ? 'sky' : segment === 'at_risk' || segment === 'dormant' ? 'bad' : 'muted'}>
      <Icon size={11} /> {label}
    </Badge>
  )
}

type CustomerChip = 'all' | 'owes' | 'overdue' | Segment | 'archived'

export function Customers() {
  const route = useRecordRoute('/customers')
  const [search, setSearch] = useState('')
  const [chip, setChip] = useState<CustomerChip>('all')
  const query = useDebounced(search)
  const list = useList('customers', api.customers.list, { search: query, include_inactive: chip === 'archived', limit: 500 })
  const segments = useQuery({ queryKey: ['insights', 'segments'], queryFn: insights.segments, staleTime: 60_000 })
  const byId = new Map((segments.data?.customers ?? []).map((row) => [row.customer_id, row]))
  const all = list.data?.items ?? []
  const test = (key: CustomerChip, id: string, active: boolean) => {
    const row = byId.get(id)
    if (key === 'all') return active
    if (key === 'archived') return !active
    if (key === 'owes') return (row?.open_receivable ?? 0) > 0
    if (key === 'overdue') return (row?.overdue_receivable ?? 0) > 0
    return row?.segment === key
  }
  const items = all.filter((customer) => test(chip, customer.id, customer.is_active))
  const count = (key: CustomerChip) => all.filter((customer) => test(key, customer.id, customer.is_active)).length
  const chips: Chip<CustomerChip>[] = [
    { key: 'all', label: 'All', icon: Users, count: count('all') },
    { key: 'owes', label: 'Owes you', icon: Wallet, count: count('owes') },
    { key: 'overdue', label: 'Overdue', icon: Clock, count: count('overdue'), hot: count('overdue') > 0 },
    { key: 'champion', label: 'Champions', icon: Crown, count: count('champion') },
    { key: 'at_risk', label: 'At risk', icon: AlertTriangle, count: count('at_risk'), hot: count('at_risk') > 0 },
    { key: 'dormant', label: 'Dormant', icon: Moon, count: count('dormant') },
    { key: 'new', label: 'New', icon: UserPlus, count: count('new') },
    { key: 'archived', label: 'Archived', icon: Archive },
  ]
  const rows = segments.data?.customers ?? []
  const overdueTotal = rows.reduce((sum, row) => sum + row.overdue_receivable, 0)
  const atRisk = rows.filter((row) => row.segment === 'at_risk' || row.segment === 'dormant')
  const overLimit = rows.filter((row) => row.over_credit_limit)

  useEffect(() => {
    if (!route.id && items.length > 0 && window.innerWidth >= 1024 && !search) route.select(items[0].id)
  }, [route.id, items.length]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <SplitView
      showDetail={Boolean(route.id)}
      onBack={route.back}
      list={
        <ListPane
          title="Customers"
          count={list.data?.total}
          actions={
            <>
              <PageGuide
                title="Customers"
                points={[
                  { icon: Crown, text: 'Segments come from how recently, how often and how much each customer buys: champions, loyal, at risk, dormant, new.' },
                  { icon: Wallet, text: '"Owes you" counts delivered goods not yet paid; overdue means past their credit terms (set under Edit details).' },
                  { icon: Sparkles, text: 'Open a customer for their 360 view: spend by month, what they buy, credit used and every event on the timeline.' },
                ]}
              />
              <Button kind="primary" small icon={<Plus size={14} />} onClick={route.openNew} aria-label="New customer">
                New
              </Button>
            </>
          }
          filters={
            <>
              <SearchBox value={search} onChange={setSearch} placeholder="Name, phone or email" />
              <QuickChips chips={chips} value={chip} onChange={setChip} />
            </>
          }
        >
          {!search && chip === 'all' && rows.length > 0 ? (
            <AiStrip
              className="mx-1.5 mb-2"
              insights={
                [
                  overdueTotal > 0 ? { icon: Clock, text: <><b>{fmtMoney(overdueTotal)}</b> overdue from {plural(count('overdue'), 'customer')}.</>, onClick: () => setChip('overdue') } : null,
                  atRisk.length ? { icon: AlertTriangle, text: <><b>{plural(atRisk.length, 'customer')}</b> buying less often than usual — worth a call.</>, onClick: () => setChip('at_risk') } : null,
                  overLimit.length ? { icon: GaugeIcon, text: <><b>{plural(overLimit.length, 'customer')}</b> over their credit limit.</>, onClick: () => setChip('owes') } : null,
                ].filter(Boolean) as { icon: typeof Clock; text: ReactNode; onClick: () => void }[]
              }
              prompts={[
                { label: 'Who to call today?', question: 'Which customers should I call today and why? Use customer_segments and receivables: at-risk regulars, overdue payments, and open enquiries. Suggest what to say to each.' },
                { label: 'Win back dormant', question: 'Which dormant or at-risk customers were most valuable, what did they buy, and draft a short WhatsApp message to win each back.' },
              ]}
            />
          ) : null}
          {list.isPending ? (
            <ListSkeleton />
          ) : items.length === 0 ? (
            <Empty icon={<Users size={20} />} title={search ? 'No customers match' : chip === 'all' ? 'No customers yet' : 'Nobody here'} action={chip === 'all' ? <Button kind="primary" small onClick={route.openNew}>New customer</Button> : undefined} />
          ) : (
            items.map((customer) => {
              const row = byId.get(customer.id)
              return (
                <ListRow key={customer.id} group="customers" selected={customer.id === route.id} onSelect={() => route.select(customer.id)} alert={(row?.overdue_receivable ?? 0) > 0}>
                  <div className="flex items-center gap-3">
                    <Avatar name={customer.name} size={34} />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="truncate text-[13px] font-semibold">{customer.name}</span>
                        {!customer.is_active ? <Badge>Archived</Badge> : null}
                      </div>
                      <div className="mt-0.5 flex items-center gap-1.5">
                        <SegmentBadge segment={row?.segment} />
                        <span className="truncate text-[11.5px] text-fg-3">{row?.days_since_last_order !== undefined ? `last order ${row.days_since_last_order}d ago` : customer.phone ?? 'No orders yet'}</span>
                      </div>
                    </div>
                    <div className="text-right">
                      {(row?.open_receivable ?? 0) > 0 ? (
                        <>
                          <div className="num text-[13px] font-semibold">{fmtMoney(row!.open_receivable)}</div>
                          <div className={(row?.overdue_receivable ?? 0) > 0 ? 'text-[11px] font-semibold' : 'text-[11px] text-fg-3'}>{(row?.overdue_receivable ?? 0) > 0 ? 'overdue' : 'owes'}</div>
                        </>
                      ) : n(customer.outstanding_quantity) > 0 ? (
                        <>
                          <div className="num text-[13px] font-semibold text-sky">{fmtQty(customer.outstanding_quantity)}</div>
                          <div className="text-[11px] text-fg-3">to deliver</div>
                        </>
                      ) : (
                        <div className="num text-[12px] text-fg-3">{fmtMoney(customer.ordered_value)}</div>
                      )}
                    </div>
                  </div>
                </ListRow>
              )
            })
          )}
        </ListPane>
      }
    >
      {route.id ? <CustomerInspector id={route.id} /> : <Empty className="h-full" icon={<Users size={22} />} title="Choose a customer" />}
      <PartySheet kind="customer" open={route.isNew} onClose={route.closeNew} onSaved={route.select} />
    </SplitView>
  )
}

/** A customer's 360: value, rhythm, credit, spend by month and favourite products. */
function Overview({ id, name, onOrder }: { id: string; name: string; onOrder: () => void }) {
  const navigate = useNavigate()
  const profile = useQuery({ queryKey: ['records', 'profile', id], queryFn: () => records.customerProfile(id) })
  if (profile.isPending) return <Spinner />
  if (!profile.data) return <Empty title="No profile yet" />
  const p = profile.data
  const months: { label: string; value: number }[] = []
  const now = new Date()
  for (let back = 11; back >= 0; back -= 1) {
    const d = new Date(now.getFullYear(), now.getMonth() - back, 1)
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
    months.push({ label: d.toLocaleString('en-IN', { month: 'short' }).slice(0, 3), value: p.monthly.find((m) => m.month === key)?.booked ?? 0 })
  }
  const dueAgain = p.average_days_between_orders && p.average_days_between_orders >= 1 && p.days_since_last_order !== null ? Math.round(p.average_days_between_orders - p.days_since_last_order) : null
  return (
    <div className="space-y-4 p-6 pb-20 max-md:p-4">
      <div className="grid grid-cols-[repeat(auto-fit,minmax(210px,1fr))] gap-3">
        <Stat strong icon={Trophy} label="Lifetime booked" value={fmtMoney(p.lifetime_booked)} hint={p.rank ? `#${p.rank} customer · ${p.share_of_sales_percent ?? 0}% of sales` : 'no orders yet'} />
        <Stat icon={ShoppingCart} label="Average order" value={fmtMoney(p.average_order_value)} hint={plural(p.orders, 'order')} />
        <Stat icon={CalendarClock} label="Buys every" value={p.average_days_between_orders !== null ? (p.average_days_between_orders < 1 ? 'Same day' : `${Math.round(p.average_days_between_orders)} days`) : '—'} hint={p.orders < 2 ? 'needs two orders' : dueAgain === null || p.average_days_between_orders! < 1 ? 'orders close together' : dueAgain < 0 ? `${-dueAgain} days later than usual` : `next order likely in ~${dueAgain} days`} />
        <Stat icon={BadgePercent} label="Average discount" value={p.average_discount_percent !== null ? `${p.average_discount_percent}%` : '—'} hint={p.enquiry_win_rate_percent !== null ? `wins ${p.enquiry_win_rate_percent}% of quotes` : `${p.open_enquiries} open enquiries`} />
      </div>
      {dueAgain !== null && dueAgain < -7 ? (
        <div className="flex items-center gap-3 rounded-2xl bg-peri/45 px-4 py-3 text-[13px]">
          <AlertTriangle size={16} className="shrink-0" />
          <span className="flex-1">
            {name} usually orders every {Math.round(p.average_days_between_orders!)} days; it has been {p.days_since_last_order}. A call now may keep them.
          </span>
          <Button small kind="primary" icon={<Plus size={13} />} onClick={onOrder}>
            New order
          </Button>
        </div>
      ) : null}
      <div className="grid grid-cols-[1.4fr_1fr] gap-3 max-xl:grid-cols-1">
        <div className="card p-4">
          <div className="flex items-baseline justify-between">
            <span className="text-[13px] font-semibold">Spend by month</span>
            <span className="text-[11.5px] text-fg-3">last 12 months, booked</span>
          </div>
          <div className="mt-4">
            <MiniBars values={months.map((m) => m.value)} labels={months.map((m) => m.label)} format={fmtCompactMoney} />
          </div>
        </div>
        <div className="card space-y-3 p-4">
          <div className="flex items-center gap-2 text-[13px] font-semibold">
            <IndianRupee size={14} /> Money
          </div>
          <div className="grid grid-cols-2 gap-2 text-[12px]">
            <div>
              <div className="text-fg-3">Owes</div>
              <div className="num text-[16px] font-semibold">{fmtMoney(p.account.open)}</div>
            </div>
            <div>
              <div className="text-fg-3">Overdue</div>
              <div className={p.account.overdue > 0 ? 'num text-[16px] font-bold underline decoration-2 underline-offset-4' : 'num text-[16px] font-semibold'}>{fmtMoney(p.account.overdue)}</div>
            </div>
          </div>
          {p.credit_limit ? (
            <Gauge percent={p.credit_used_percent ?? 0} label={`Credit used of ${fmtMoney(p.credit_limit)}`} />
          ) : (
            <p className="text-[11.5px] text-fg-3">No credit limit set. Set one under Edit details to get warnings while taking orders.</p>
          )}
          <p className="text-[11.5px] text-fg-3">{p.account.payment_terms_days ? `${p.account.payment_terms_days}-day terms` : 'Due on delivery'} · paid {fmtMoney(p.account.paid)} so far</p>
        </div>
      </div>
      <div className="card overflow-hidden">
        <div className="flex items-center justify-between px-4 pt-3.5 pb-2">
          <span className="text-[13px] font-semibold">What {name.split(' ')[0]} buys</span>
          <span className="text-[11.5px] text-fg-3">by value, all time</span>
        </div>
        {p.top_products.length ? (
          <table className="grid-table">
            <thead>
              <tr>
                <th>Product</th>
                <th className="r">Quantity</th>
                <th className="r">Value</th>
                <th className="r">Last ordered</th>
              </tr>
            </thead>
            <tbody>
              {p.top_products.map((product) => (
                <tr key={product.product_id} className="cursor-pointer" onClick={() => navigate(`/products/${product.product_id}`)}>
                  <td className="text-[13px] font-medium">{product.name}</td>
                  <td className="r num">
                    {fmtQty(product.quantity)} <span className="text-fg-3">{product.unit}</span>
                  </td>
                  <td className="r num">{fmtMoney(product.value)}</td>
                  <td className="r text-[12px] text-fg-3">{fmtDate(product.last_ordered)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="px-4 pb-4 text-[12.5px] text-fg-3">No orders yet.</p>
        )}
      </div>
      <p className="text-[11.5px] text-fg-3">
        Segment: {SEGMENT_LABEL[p.segment as Segment]?.[0] ?? p.segment}. {p.estimated_annual_value ? `Estimated yearly value ${fmtMoney(p.estimated_annual_value)} (an estimate from their own buying rhythm).` : ''}
      </p>
    </div>
  )
}

function CustomerInspector({ id }: { id: string }) {
  const navigate = useNavigate()
  const customer = useOne('customers', api.customers.get, id)
  const enquiries = useList('enquiries', api.enquiries.list, { customer_id: id, limit: 100 })
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') ?? 'overview'
  const setTab = (value: string) => setParams({ tab: value }, { replace: true })
  const { ask } = useAssistant()
  const account = useQuery({ queryKey: ['finance', 'statement', 'customer', id], queryFn: () => finance.statement('customers', id) })
  const segments = useQuery({ queryKey: ['insights', 'segments'], queryFn: insights.segments, staleTime: 60_000 })
  const [sheet, setSheet] = useState<null | 'edit' | 'order' | 'enquiry'>(null)
  const confirm = useConfirm()
  const archive = useAction(() => api.customers.archive(id), { success: 'Customer archived' })

  if (customer.isPending) return <Spinner />
  if (!customer.data) return <Empty title="This customer could not be loaded" />
  const data = customer.data
  const outstanding = data.outstanding.reduce((sum, line) => sum + n(line.pending_quantity), 0)
  const value = data.orders.filter((order) => order.status !== 'CANCELLED').reduce((sum, order) => sum + n(order.total_amount), 0)
  const open = data.orders.filter((order) => order.status === 'PENDING' || order.status === 'PARTIALLY_FULFILLED').length
  const segment = segments.data?.customers.find((row) => row.customer_id === id)?.segment

  return (
    <>
      <InspectorHeader
        eyebrow={data.is_active ? 'Customer' : 'Customer · archived'}
        title={
          <span className="flex items-center gap-3">
            <Avatar name={data.name} size={34} />
            {data.name}
          </span>
        }
        badges={<SegmentBadge segment={segment} />}
        meta={`Customer since ${fmtDate(data.created_at)}`}
        actions={
          <>
            <AskButton label="Next best action" question={`What is the next best action with customer ${data.name} (id ${id})? Use customer_profile, their statement and open enquiries. Give one clear recommendation with the numbers behind it, then a ready-to-send WhatsApp message.`} />
            <Button icon={<MessageSquareQuote size={14} />} onClick={() => setSheet('enquiry')} disabled={!data.is_active}>
              Enquiry
            </Button>
            <Button kind="primary" icon={<Plus size={14} />} onClick={() => setSheet('order')} disabled={!data.is_active}>
              New order
            </Button>
            <Menu
              trigger={
                <Button iconOnly aria-label="More actions">
                  <MoreHorizontal size={16} />
                </Button>
              }
              items={[
                { label: 'Edit details', icon: <Pencil size={14} />, onSelect: () => setSheet('edit') },
                { label: 'Show on fulfilment board', icon: <Truck size={14} />, onSelect: () => navigate(`/fulfilment?customer=${id}`), disabled: outstanding === 0 },
                {
                  label: 'Archive',
                  icon: <Archive size={14} />,
                  danger: true,
                  separator: true,
                  disabled: !data.is_active,
                  onSelect: async () => {
                    const answer = await confirm.ask({ title: `Archive ${data.name}?`, body: 'Their orders and history stay. They no longer appear when choosing a customer.', confirm: 'Archive', danger: true })
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
          { label: 'Orders', value: data.orders.length, hint: `${open} open` },
          { label: 'To deliver', value: fmtQty(outstanding), tone: outstanding > 0 ? 'sky' : undefined, hint: 'units across orders' },
          { label: 'Ordered value', value: fmtMoney(value), hint: 'before tax' },
          { label: 'Enquiries', value: enquiries.data?.total ?? '—' },
          {
            label: 'Owes you',
            value: account.data ? fmtMoney(account.data.summary.open) : '—',
            tone: account.data && account.data.summary.overdue > 0 ? 'bad' : undefined,
            hint: account.data ? (account.data.summary.overdue > 0 ? `${fmtMoney(account.data.summary.overdue)} overdue` : account.data.summary.payment_terms_days ? `${account.data.summary.payment_terms_days}-day terms` : 'due on delivery') : undefined,
          },
        ]}
      />
      <div className="flex min-h-0 flex-1">
        <Tabs
          value={tab}
          onChange={setTab}
          className="min-w-0 flex-1"
          tabs={[
            { value: 'overview', label: 'Overview' },
            { value: 'owed', label: 'To deliver', count: data.outstanding.length },
            { value: 'orders', label: 'Orders', count: data.orders.length },
            { value: 'enquiries', label: 'Enquiries', count: enquiries.data?.total },
            { value: 'account', label: 'Account' },
            { value: 'activity', label: 'Activity' },
            { value: 'followups', label: 'Follow-ups' },
          ]}
        >
          <TabPanel value="overview">
            <Overview id={id} name={data.name} onOrder={() => setSheet('order')} />
          </TabPanel>
          <TabPanel value="activity">
            <Timeline target={{ customer_id: id }} />
          </TabPanel>
          <TabPanel value="owed">
            {data.outstanding.length === 0 ? (
              <Empty icon={<Truck size={20} />} title="Nothing to deliver" body="Every order for this customer has been delivered." />
            ) : (
              <table className="grid-table">
                <thead>
                  <tr>
                    <th>Product</th>
                    <th className="r">To deliver</th>
                  </tr>
                </thead>
                <tbody>
                  {data.outstanding.map((line) => (
                    <tr key={line.product_id}>
                      <td>
                        <Link to={`/products/${line.product_id}`} className="text-[13px] font-medium hover:text-sky">
                          {line.product_name}
                        </Link>
                        <div className="text-[11.5px] text-fg-3">{line.product_sku}</div>
                      </td>
                      <td className="r num font-semibold text-sky">
                        {fmtQty(line.pending_quantity)} <span className="font-normal text-fg-3">{line.unit_of_measure}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </TabPanel>
          <TabPanel value="orders">
            {data.orders.length === 0 ? (
              <Empty title="No orders yet" />
            ) : (
              <table className="grid-table">
                <thead>
                  <tr>
                    <th>Order</th>
                    <th>Status</th>
                    <th className="r">Lines</th>
                    <th className="r">Value</th>
                  </tr>
                </thead>
                <tbody>
                  {data.orders.map((order) => (
                    <tr key={order.id} className="cursor-pointer" onClick={() => navigate(`/orders/${order.id}`)}>
                      <td>
                        <div className="num text-[13px] font-medium">{order.order_number}</div>
                        <div className="text-[11.5px] text-fg-3">{fmtDate(order.created_at)}</div>
                      </td>
                      <td>
                        <OrderBadge status={order.status} />
                      </td>
                      <td className="r num">{order.items.length}</td>
                      <td className="r num">{fmtMoney(order.total_amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </TabPanel>
          <TabPanel value="enquiries">
            {(enquiries.data?.items ?? []).length === 0 ? (
              <Empty title="No enquiries" />
            ) : (
              <table className="grid-table">
                <thead>
                  <tr>
                    <th>Enquiry</th>
                    <th>Status</th>
                    <th className="r">Value</th>
                  </tr>
                </thead>
                <tbody>
                  {enquiries.data?.items.map((enquiry) => (
                    <tr key={enquiry.id} className="cursor-pointer" onClick={() => navigate(`/enquiries/${enquiry.id}`)}>
                      <td>
                        <div className="num text-[13px] font-medium">{enquiry.enquiry_number}</div>
                        <div className="text-[11.5px] text-fg-3">
                          {fmtDate(enquiry.created_at)} · {plural(enquiry.item_count, 'product')}
                        </div>
                      </td>
                      <td>
                        <EnquiryBadge status={enquiry.status} />
                      </td>
                      <td className="r num">{fmtMoney(enquiry.total_amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </TabPanel>
          <TabPanel value="account">
            <Account party="customer" id={id} />
          </TabPanel>
          <TabPanel value="followups">
            <RecordTasks link={{ customer_id: id }} suggestion={`Call ${data.name}`} />
          </TabPanel>
        </Tabs>
        <aside className="w-[270px] shrink-0 space-y-4 overflow-y-auto border-l border-white/7 p-5 max-xl:hidden">
          <div className="eyebrow">Contact</div>
          <Contact icon={<Phone size={14} />} value={data.phone} href={data.phone ? `tel:${data.phone}` : undefined} />
          {data.phone ? (
            <a className="btn btn-sm w-full" href={`https://wa.me/${data.phone.replace(/\D/g, '').replace(/^(\d{10})$/, '91$1')}`} target="_blank" rel="noreferrer">
              <MessageCircle size={13} /> WhatsApp
            </a>
          ) : null}
          <Contact icon={<Mail size={14} />} value={data.email} href={data.email ? `mailto:${data.email}` : undefined} />
          <Contact icon={<MapPin size={14} />} value={data.address} />
          <Button
            small
            kind="quiet"
            className="w-full"
            icon={<Sparkles size={13} />}
            onClick={() => ask(`Give me a full picture of customer ${data.name} (id ${id}): what they buy, how often, what they owe and whether it is overdue, open enquiries and orders, and what I should do next with them.`)}
          >
            Ask AI about {data.name.split(' ')[0]}
          </Button>
          {data.notes ? (
            <>
              <div className="eyebrow pt-2">Notes</div>
              <p className="text-[12.5px] whitespace-pre-line text-fg-2" data-selectable>
                {data.notes}
              </p>
            </>
          ) : null}
        </aside>
      </div>
      <PartySheet kind="customer" open={sheet === 'edit'} onClose={() => setSheet(null)} editing={data} />
      <OrderSheet open={sheet === 'order'} onClose={() => setSheet(null)} customerId={id} onCreated={(order) => navigate(`/orders/${order.id}`)} />
      <EnquirySheet open={sheet === 'enquiry'} onClose={() => setSheet(null)} customerId={id} onSaved={(enquiry) => navigate(`/enquiries/${enquiry.id}`)} />
      {confirm.element}
    </>
  )
}

export function Contact({ icon, value, href }: { icon: React.ReactNode; value: string | null; href?: string }) {
  return (
    <div className="flex items-start gap-2.5 text-[13px]">
      <span className="mt-0.5 text-fg-3">{icon}</span>
      {value ? (
        href ? (
          <a href={href} className="min-w-0 break-words text-fg hover:text-sky" data-selectable>
            {value}
          </a>
        ) : (
          <span className="min-w-0 whitespace-pre-line break-words text-fg-2" data-selectable>
            {value}
          </span>
        )
      ) : (
        <span className="text-fg-4">—</span>
      )}
    </div>
  )
}
