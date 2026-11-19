import { PartyContactsAside, PartyProfile } from '@/features/parties/PartyProfile'
import { MergeSheet } from '@/features/parties/MergeSheet'
import { GitMerge } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { insights } from '@/api/insights'
import { finance } from '@/api/finance'
import { records } from '@/api/records'
import { AiStrip, AskButton, Gauge, PageGuide, QuickChips, Stat, Timeline, type Chip } from '@/ui/smart'
import { Account } from '@/features/finance/Account'
import { RecordTasks } from '@/features/tasks/RecordTasks'
import { AlarmClock, Archive, Award, BadgeCheck, Building2, Clock, IndianRupee, MapPin, MoreHorizontal, PackageCheck, Pencil, Plus, Timer, Truck, UserRound, Wallet } from 'lucide-react'
import { cn } from '@/lib/cn'
import { api } from '@/api/endpoints'
import { useAction, useList, useOne } from '@/api/queries'
import { fmtDate, fmtMoney, fmtQty, n } from '@/lib/format'
import { useDebounced, useRecordRoute } from '@/lib/route'
import { PurchaseBadge } from '@/lib/status'
import { Avatar, Badge, Button, Empty, Meter, SearchBox, Spinner } from '@/ui/core'
import { Menu, TabPanel, Tabs, useConfirm } from '@/ui/overlays'
import { FigureStrip, InspectorHeader, ListPane, ListRow, ListSkeleton, SplitView } from '@/ui/split'
import { Contact } from '@/features/customers/Customers'
import { PartySheet } from '@/features/customers/PartySheet'
import { PurchaseSheet } from '@/features/purchasing/PurchaseSheet'

export function Suppliers() {
  const route = useRecordRoute('/suppliers')
  const [search, setSearch] = useState('')
  const [chip, setChip] = useState<'all' | 'due' | 'late' | 'owed' | 'archived'>('all')
  const query = useDebounced(search)
  const list = useList('suppliers', api.suppliers.list, { search: query, include_inactive: chip === 'archived', limit: 500 })
  const perf = useQuery({ queryKey: ['insights', 'suppliers'], queryFn: insights.suppliers, staleTime: 60_000 })
  const payables = useQuery({ queryKey: ['finance', 'payables'], queryFn: finance.payables, staleTime: 60_000 })
  const perfById = new Map((perf.data?.suppliers ?? []).map((row) => [row.supplier_id, row]))
  const owedById = new Map((payables.data?.parties ?? []).map((row) => [row.party_id, row]))
  const lateIds = new Set((perf.data?.late_purchase_orders ?? []).map((row) => row.supplier_id))
  const all = list.data?.items ?? []
  const test = (key: typeof chip, supplier: (typeof all)[number]) =>
    key === 'all' ? supplier.is_active : key === 'archived' ? !supplier.is_active : key === 'due' ? n(supplier.on_order_quantity) > 0 : key === 'late' ? lateIds.has(supplier.id) : (owedById.get(supplier.id)?.open ?? 0) > 0
  const items = all.filter((supplier) => test(chip, supplier))
  const count = (key: typeof chip) => all.filter((supplier) => test(key, supplier)).length
  const chips: Chip<typeof chip>[] = [
    { key: 'all', label: 'All', icon: Building2, count: count('all') },
    { key: 'due', label: 'Goods due', icon: Truck, count: count('due') },
    { key: 'late', label: 'Late', icon: AlarmClock, count: count('late'), hot: count('late') > 0 },
    { key: 'owed', label: 'You owe', icon: Wallet, count: count('owed') },
    { key: 'archived', label: 'Archived', icon: Archive },
  ]
  const late = perf.data?.late_purchase_orders ?? []
  const owedTotal = payables.data?.totals.open ?? 0
  const owedOverdue = payables.data?.totals.overdue ?? 0
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
          title="Suppliers"
          count={list.data?.total}
          actions={
            <>
              <PageGuide
                title="Suppliers"
                points={[
                  { icon: Award, text: 'Each supplier gets a score from fill rate (how much of what you order arrives) and on-time rate.' },
                  { icon: IndianRupee, text: 'The Scorecard tab compares their last price on each product with the cheapest supplier.' },
                  { icon: Wallet, text: '"You owe" counts goods received and not yet paid, aged by their payment terms.' },
                ]}
              />
              <Button kind="primary" small icon={<Plus size={14} />} onClick={route.openNew} aria-label="New supplier">
                New
              </Button>
            </>
          }
          filters={
            <>
              <SearchBox value={search} onChange={setSearch} placeholder="Name, code or contact" />
              <QuickChips chips={chips} value={chip} onChange={setChip} />
            </>
          }
        >
          {!search && chip === 'all' && all.length ? (
            <AiStrip
              className="mx-1.5 mb-2"
              insights={
                [
                  late.length ? { icon: AlarmClock, text: <><b>{late.length} late purchase orders</b> — worst is {late[0].po_number}, {late[0].days_late} days.</>, onClick: () => setChip('late') } : null,
                  owedTotal > 0 ? { icon: Wallet, text: <>You owe suppliers <b>{fmtMoney(owedTotal)}</b>{owedOverdue > 0 ? <>, <b>{fmtMoney(owedOverdue)}</b> past terms</> : null}.</>, onClick: () => setChip('owed') } : null,
                ].filter(Boolean) as { icon: typeof Clock; text: ReactNode; onClick: () => void }[]
              }
              prompts={[
                { label: 'Best supplier per product', question: 'For each product we buy, which supplier is cheapest and most reliable? Use product_prices and supplier_performance and flag where we pay more than we need to.' },
                { label: 'Who to pay first?', question: 'Which supplier bills should I pay first this week and why? Use payables with their terms, and keep the reliable suppliers happy.' },
              ]}
            />
          ) : null}
          {list.isPending ? (
            <ListSkeleton />
          ) : items.length === 0 ? (
            <Empty icon={<Building2 size={20} />} title={search ? 'No suppliers match' : 'No suppliers yet'} action={<Button kind="primary" small onClick={route.openNew}>New supplier</Button>} />
          ) : (
            items.map((supplier) => (
              <ListRow key={supplier.id} group="suppliers" selected={supplier.id === route.id} onSelect={() => route.select(supplier.id)} alert={lateIds.has(supplier.id)}>
                <div className="flex items-center gap-3">
                  <Avatar name={supplier.name} size={32} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-[13px] font-semibold">{supplier.name}</span>
                      {!supplier.is_active ? <Badge>Archived</Badge> : null}
                    </div>
                    <div className="mt-0.5 flex items-center gap-1.5 truncate text-[12px] text-fg-3">
                      <ScoreBadge fill={perfById.get(supplier.id)?.fill_rate_percent} onTime={perfById.get(supplier.id)?.on_time_percent} />
                      <span className="truncate">
                        {supplier.code}
                        {supplier.contact_person ? ` · ${supplier.contact_person}` : ''}
                      </span>
                    </div>
                  </div>
                  {n(supplier.on_order_quantity) > 0 ? (
                    <div className="text-right">
                      <div className="num text-[13px] font-semibold text-sky">{fmtQty(supplier.on_order_quantity)}</div>
                      <div className="text-[11px] text-fg-3">still due</div>
                    </div>
                  ) : null}
                </div>
              </ListRow>
            ))
          )}
        </ListPane>
      }
    >
      {route.id ? <SupplierInspector id={route.id} /> : <Empty className="h-full" icon={<Building2 size={22} />} title="Choose a supplier" />}
      <PartySheet kind="supplier" open={route.isNew} onClose={route.closeNew} onSaved={route.select} />
    </SplitView>
  )
}

function SupplierInspector({ id }: { id: string }) {
  const navigate = useNavigate()
  const supplier = useOne('suppliers', api.suppliers.get, id)
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') ?? 'scorecard'
  const setTab = (value: string) => setParams({ tab: value }, { replace: true })
  const [sheet, setSheet] = useState<null | 'edit' | 'po'>(null)
  const confirm = useConfirm()
  const [merging, setMerging] = useState(false)
  const archive = useAction(() => api.suppliers.archive(id), { success: 'Supplier archived' })
  if (supplier.isPending) return <Spinner />
  if (!supplier.data) return <Empty title="This supplier could not be loaded" />
  const data = supplier.data
  const open = data.purchase_orders.filter((po) => ['DRAFT', 'ORDERED', 'PARTIALLY_RECEIVED'].includes(po.status))
  const due = open.reduce((sum, po) => sum + n(po.total_ordered) - n(po.total_received), 0)
  const spend = data.purchase_orders.filter((po) => po.status !== 'CANCELLED' && po.status !== 'DRAFT').reduce((sum, po) => sum + n(po.total_cost), 0)

  return (
    <>
      <InspectorHeader
        eyebrow={`Supplier · ${data.code}${data.is_active ? '' : ' · archived'}`}
        title={
          <span key={data.name} className="flex min-w-0 items-center gap-3">
            <Avatar name={data.name} size={34} className="shrink-0" />
            <span className="min-w-0 truncate">{data.name}</span>
          </span>
        }
        meta={data.contact_person ? `Contact: ${data.contact_person}` : `Supplier since ${fmtDate(data.created_at)}`}
        actions={
          <>
            <AskButton question={`How good a supplier is ${data.name} (id ${id})? Use supplier_scorecard: reliability, lead time, prices against other suppliers, late orders and what we owe them. Should I buy more or less from them?`} />
            <Button kind="primary" icon={<Plus size={14} />} onClick={() => setSheet('po')} disabled={!data.is_active}>
              Purchase order
            </Button>
            <Menu
              trigger={
                <Button iconOnly aria-label="More actions">
                  <MoreHorizontal size={16} />
                </Button>
              }
              items={[
                { label: 'Edit details', icon: <Pencil size={14} />, onSelect: () => setSheet('edit') },
                { label: 'Merge a duplicate into this', icon: <GitMerge size={14} />, onSelect: () => setMerging(true) },
                {
                  label: 'Archive',
                  icon: <Archive size={14} />,
                  danger: true,
                  separator: true,
                  disabled: !data.is_active,
                  onSelect: async () => {
                    const answer = await confirm.ask({ title: `Archive ${data.name}?`, body: 'Their purchase orders and receipts stay. They no longer appear when choosing a supplier.', confirm: 'Archive', danger: true })
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
          { label: 'Purchase orders', value: data.purchase_orders.length, hint: `${open.length} open` },
          { label: 'Still due', value: fmtQty(due), tone: due > 0 ? 'sky' : undefined, hint: 'units to arrive' },
          { label: 'Bought', value: fmtMoney(spend), hint: 'placed orders' },
          { label: 'Deliveries', value: data.goods_receipts.length },
        ]}
      />
      <div className="flex min-h-0 flex-1">
        <Tabs
          value={tab}
          onChange={setTab}
          className="min-w-0 flex-1"
          tabs={[
            { value: 'scorecard', label: 'Scorecard' },
            { value: 'profile', label: 'Profile' },
            { value: 'orders', label: 'Purchase orders', count: data.purchase_orders.length },
            { value: 'receipts', label: 'Deliveries', count: data.goods_receipts.length },
            { value: 'account', label: 'Account' },
            { value: 'activity', label: 'Activity' },
            { value: 'followups', label: 'Follow-ups' },
          ]}
        >
          <TabPanel value="profile">
            <PartyProfile kind="supplier" id={id} />
          </TabPanel>
          <TabPanel value="scorecard">
            <Scorecard id={id} />
          </TabPanel>
          <TabPanel value="activity">
            <Timeline target={{ supplier_id: id }} />
          </TabPanel>
          <TabPanel value="orders">
            {data.purchase_orders.length === 0 ? (
              <Empty title="No purchase orders yet" action={<Button kind="primary" small onClick={() => setSheet('po')}>New purchase order</Button>} />
            ) : (
              <table className="grid-table">
                <thead>
                  <tr>
                    <th>Order</th>
                    <th>Status</th>
                    <th className="w-[160px]">Received</th>
                    <th className="r">Value</th>
                  </tr>
                </thead>
                <tbody>
                  {data.purchase_orders.map((po) => (
                    <tr key={po.id} className="cursor-pointer" onClick={() => navigate(`/purchase-orders/${po.id}`)}>
                      <td>
                        <div className="num text-[13px] font-medium">{po.po_number}</div>
                        <div className="text-[11.5px] text-fg-3">{po.expected_delivery_date ? `expected ${fmtDate(po.expected_delivery_date)}` : fmtDate(po.created_at)}</div>
                      </td>
                      <td>
                        <PurchaseBadge status={po.status} />
                      </td>
                      <td>
                        <Meter parts={[{ label: 'Received', value: n(po.total_received), color: 'var(--color-blue)' }]} total={n(po.total_ordered)} />
                        <div className="num mt-1 text-[11px] text-fg-3">
                          {fmtQty(po.total_received)} of {fmtQty(po.total_ordered)}
                        </div>
                      </td>
                      <td className="r num">{fmtMoney(po.total_cost)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </TabPanel>
          <TabPanel value="receipts">
            {data.goods_receipts.length === 0 ? (
              <Empty title="Nothing delivered yet" />
            ) : (
              <table className="grid-table">
                <thead>
                  <tr>
                    <th>Receipt</th>
                    <th>Against</th>
                    <th className="r">Quantity</th>
                    <th className="r">Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {data.goods_receipts.map((receipt) => (
                    <tr key={receipt.id} className="cursor-pointer" onClick={() => navigate(`/receipts/${receipt.id}`)}>
                      <td>
                        <div className="num text-[13px] font-medium">{receipt.receipt_number}</div>
                        <div className="text-[11.5px] text-fg-3">
                          {fmtDate(receipt.created_at)}
                          {receipt.delivery_note_reference ? ` · ${receipt.delivery_note_reference}` : ''}
                        </div>
                      </td>
                      <td className="num text-[13px] text-fg-2">{receipt.po_number}</td>
                      <td className="r num">{fmtQty(receipt.total_quantity)}</td>
                      <td className="r num">{fmtMoney(receipt.total_cost)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </TabPanel>
          <TabPanel value="account">
            <Account party="supplier" id={id} />
          </TabPanel>
          <TabPanel value="followups">
            <RecordTasks link={{ supplier_id: id }} suggestion={`Chase ${data.name}`} />
          </TabPanel>
        </Tabs>
        <aside className="w-[270px] shrink-0 space-y-4 overflow-y-auto border-l border-white/7 p-5 max-xl:hidden">
          <div className="eyebrow">Contact</div>
          <Contact icon={<UserRound size={14} />} value={data.contact_person} />
          <PartyContactsAside kind="supplier" id={id} />
          <Contact icon={<MapPin size={14} />} value={data.address} />
          {data.notes ? (
            <>
              <div className="eyebrow pt-2">Notes</div>
              <p className="text-[12.5px] whitespace-pre-line text-fg-2">{data.notes}</p>
            </>
          ) : null}
        </aside>
      </div>
      <PartySheet kind="supplier" open={sheet === 'edit'} onClose={() => setSheet(null)} editing={data} />
      <PurchaseSheet open={sheet === 'po'} onClose={() => setSheet(null)} initial={{ supplier_id: id }} onSaved={(po) => navigate(`/purchase-orders/${po.id}`)} />
      <MergeSheet kind="supplier" id={id} name={data.name} open={merging} onClose={() => setMerging(false)} />
      {confirm.element}
    </>
  )
}

function ScoreBadge({ fill, onTime }: { fill?: number | null; onTime?: number | null }) {
  if (!fill && (onTime === null || onTime === undefined)) return null
  const parts = [fill, onTime].filter((value): value is number => value !== null && value !== undefined)
  if (!parts.length) return null
  const score = Math.round(parts.reduce((a, b) => a + b, 0) / parts.length)
  return (
    <Badge tone={score >= 85 ? 'sky' : score >= 60 ? 'muted' : 'bad'} title="Average of fill rate and on-time rate">
      <Award size={11} /> {score}
    </Badge>
  )
}

/** Reliability, lateness and price against other suppliers. */
function Scorecard({ id }: { id: string }) {
  const navigate = useNavigate()
  const card = useQuery({ queryKey: ['records', 'scorecard', id], queryFn: () => records.supplierScorecard(id) })
  if (card.isPending) return <Spinner />
  if (!card.data) return <Empty title="No scorecard yet" />
  const c = card.data
  const p = c.performance
  return (
    <div className="space-y-4 p-6 pb-20 max-md:p-4">
      <div className="grid grid-cols-[repeat(auto-fit,minmax(190px,1fr))] gap-3">
        <Stat strong icon={Award} label="Supplier score" value={c.score !== null ? `${c.score} / 100` : '—'} hint={c.score_note} />
        <Stat icon={PackageCheck} label="Fill rate" value={p?.fill_rate_percent !== null && p?.fill_rate_percent !== undefined ? `${p.fill_rate_percent}%` : '—'} hint="of ordered quantity received" />
        <Stat icon={BadgeCheck} label="On time" value={p?.on_time_percent !== null && p?.on_time_percent !== undefined ? `${p.on_time_percent}%` : '—'} hint="received by the expected date" />
        <Stat icon={Timer} label="Lead time" value={p?.average_lead_days !== null && p?.average_lead_days !== undefined ? `${p.average_lead_days} days` : '—'} hint="order placed to first delivery" />
      </div>
      {p ? (
        <div className="card grid grid-cols-2 gap-4 p-4">
          <Gauge percent={p.fill_rate_percent ?? 0} label="Fill rate" />
          <Gauge percent={p.on_time_percent ?? 0} label="On time" />
        </div>
      ) : null}
      {c.late_orders.length ? (
        <div className="space-y-1.5">
          {c.late_orders.map((late) => (
            <button key={late.purchase_order_id} onClick={() => navigate(`/purchase-orders/${late.purchase_order_id}`)} className="flex w-full items-center gap-3 rounded-xl bg-[#0b0b0c] px-3.5 py-2.5 text-left text-[12.5px] text-[#fff]">
              <AlarmClock size={14} />
              <span className="flex-1">
                {late.po_number} is {late.days_late} days late (expected {fmtDate(late.expected)})
              </span>
              <span className="num font-semibold">{fmtMoney(late.still_due_value)} due</span>
            </button>
          ))}
        </div>
      ) : null}
      <div className="card overflow-hidden">
        <div className="flex items-center gap-2 px-4 pt-3.5 pb-2 text-[13px] font-semibold">
          <IndianRupee size={14} /> Products and prices
        </div>
        {c.products.length ? (
          <table className="grid-table">
            <thead>
              <tr>
                <th>Product</th>
                <th className="r">Bought</th>
                <th className="r">Their last price</th>
                <th>Cheapest</th>
              </tr>
            </thead>
            <tbody>
              {c.products.map((row) => (
                <tr key={row.product_id} className="cursor-pointer" onClick={() => navigate(`/products/${row.product_id}?tab=prices`)}>
                  <td>
                    <div className="text-[13px] font-medium">{row.name}</div>
                    <div className="text-[11.5px] text-fg-3">last ordered {fmtDate(row.last_ordered)}</div>
                  </td>
                  <td className="r num">
                    {fmtQty(row.quantity)} <span className="text-fg-3">{row.unit}</span>
                  </td>
                  <td className="r num font-semibold">{row.last_cost !== null ? fmtMoney(row.last_cost) : '—'}</td>
                  <td>
                    {row.is_cheapest ? (
                      <Badge tone="sky">
                        <Award size={11} /> Cheapest
                      </Badge>
                    ) : row.cheapest_supplier ? (
                      <span className={cn('text-[12px]')}>
                        {row.cheapest_supplier} · <span className="num font-semibold">{fmtMoney(row.cheapest_cost)}</span>
                      </span>
                    ) : (
                      '—'
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="px-4 pb-4 text-[12.5px] text-fg-3">Nothing bought from this supplier yet.</p>
        )}
      </div>
    </div>
  )
}
