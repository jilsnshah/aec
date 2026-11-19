import { useState, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { AnimatePresence, motion } from 'motion/react'
import { AlertTriangle, ClipboardList, PackageCheck, PackageOpen, Truck, X } from 'lucide-react'
import { useCommitments } from '@/api/queries'
import type { CommitmentRow } from '@/api/types'
import { cn } from '@/lib/cn'
import { daysSince, fmtMoney, fmtQty, n, plural } from '@/lib/format'
import { useDebounced } from '@/lib/route'
import { STATE } from '@/lib/status'
import { Avatar, Badge, Button, Empty, Meter, SearchBox, Skeleton } from '@/ui/core'
import { Segmented } from '@/ui/overlays'
import { DeliverSheet } from '@/features/orders/DeliverSheet'
import { PurchaseSheet } from '@/features/purchasing/PurchaseSheet'
import { ReceiveSheet } from '@/features/receipts/ReceiveSheet'

type LaneKey = 'ready' | 'onOrder' | 'short'
const LANES: { key: LaneKey; title: string; hint: string; icon: ReactNode; color: string; qty: (row: CommitmentRow) => number }[] = [
  { key: 'ready', title: 'Ready to deliver', hint: 'In stock — load it on the truck', icon: <PackageCheck size={16} />, color: STATE.ready, qty: (row) => n(row.quantity_deliverable) },
  { key: 'onOrder', title: 'On order', hint: 'Bought from a supplier, arriving', icon: <PackageOpen size={16} />, color: STATE.onOrder, qty: (row) => n(row.quantity_incoming) },
  { key: 'short', title: 'Short', hint: 'Sold, nothing bought for it yet', icon: <AlertTriangle size={16} />, color: STATE.short, qty: (row) => n(row.quantity_unallocated) },
]

type Action = { kind: 'deliver'; row: CommitmentRow } | { kind: 'receive'; row: CommitmentRow } | { kind: 'buy'; row: CommitmentRow }

/** What customers are still owed, as a board: what can go now, what is
 *  coming, and what still has to be bought. */
export function Fulfilment() {
  const [params, setParams] = useSearchParams()
  const [search, setSearch] = useState('')
  const [view, setView] = useState<'board' | 'customers'>('board')
  const customer = params.get('customer') ?? undefined
  const focus = params.get('lane') as LaneKey | null
  const query = useDebounced(search)
  const report = useCommitments({ search: query || undefined, customer_id: customer })
  const rows = report.data?.rows ?? []
  const [action, setAction] = useState<Action | null>(null)
  const customerName = customer ? report.data?.customers.find((row) => row.customer_id === customer)?.customer_name : undefined
  const totals = report.data?.totals

  return (
    <div className="flex h-full min-h-0 flex-col gap-4 px-6 pt-1 pb-5 max-lg:overflow-y-auto max-md:gap-2 max-md:p-2">
      <header className="pane relative flex shrink-0 flex-wrap items-center gap-x-6 gap-y-3 overflow-hidden px-5 py-4">
        <div className="relative">
          <h1 className="text-[18px] font-semibold tracking-[-0.02em]">Fulfilment</h1>
          <p className="text-[12.5px] text-fg-3">Everything customers are still owed, oldest order first</p>
        </div>
        <div className="relative flex flex-wrap gap-6">
          <Stat label="To deliver" value={totals ? fmtQty(totals.quantity_outstanding) : undefined} hint={totals ? `${plural(totals.customer_count, 'customer')} · ${fmtMoney(totals.outstanding_value)}` : ''} />
          <Stat label="Ready" value={totals ? fmtQty(totals.quantity_deliverable) : undefined} color={STATE.ready} />
          <Stat label="On order" value={totals ? fmtQty(totals.quantity_incoming) : undefined} color={STATE.onOrder} />
          <Stat label="Short" value={totals ? fmtQty(totals.quantity_unallocated) : undefined} color={STATE.short} alert={n(totals?.quantity_unallocated) > 0} />
        </div>
        <div className="relative ml-auto flex flex-wrap items-center gap-2 max-md:ml-0">
          {customerName ? (
            <span className="flex h-7 items-center gap-1.5 rounded-full bg-peri/25 pr-1 pl-2.5 text-[12px] font-medium text-sky">
              {customerName}
              <button
                className="grid size-5 place-items-center rounded-full hover:bg-sky/20"
                aria-label="Show all customers"
                onClick={() =>
                  setParams((current) => {
                    current.delete('customer')
                    return current
                  })
                }
              >
                <X size={12} />
              </button>
            </span>
          ) : null}
          <div className="w-[240px] max-md:w-full">
            <SearchBox value={search} onChange={setSearch} placeholder="Customer, order or product" />
          </div>
          <Segmented
            value={view}
            onChange={setView}
            options={[
              { value: 'board', label: 'Board' },
              { value: 'customers', label: 'By customer' },
            ]}
          />
        </div>
      </header>

      {view === 'customers' ? (
        <CustomersView
          rows={report.data?.customers ?? []}
          loading={report.isPending}
          onPick={(id) => {
            setParams((current) => (current.set('customer', id), current))
            setView('board')
          }}
        />
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-3 gap-3 max-lg:flex-none max-lg:grid-cols-1">
          {LANES.map((lane, index) => {
            const laneRows = rows.filter((row) => lane.qty(row) > 0)
            const sum = laneRows.reduce((total, row) => total + lane.qty(row), 0)
            return (
              <motion.section
                key={lane.key}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, delay: index * 0.06, ease: [0.22, 1, 0.36, 1] }}
                className={cn('pane flex min-h-0 flex-col overflow-hidden max-lg:max-h-[560px]', focus === lane.key && 'ring-1 ring-sky/30')}
              >
                <header className="flex shrink-0 items-center gap-3 border-b border-white/7 px-4 py-3">
                  <span className="grid size-8 place-items-center rounded-lg" style={{ background: `${lane.color}1f`, color: lane.color }}>
                    {lane.icon}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 text-[13.5px] font-semibold">
                      {lane.title}
                      <span className="num rounded-full bg-white/7 px-1.5 text-[11px] font-medium text-fg-2">{laneRows.length}</span>
                    </div>
                    <div className="text-[11.5px] text-fg-3">{lane.hint}</div>
                  </div>
                  <span className="num text-[15px] font-semibold" style={{ color: lane.color }}>
                    {fmtQty(sum)}
                  </span>
                </header>
                <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-2.5">
                  {report.isPending ? (
                    [0, 1, 2].map((key) => <Skeleton key={key} className="h-24 rounded-xl" />)
                  ) : laneRows.length === 0 ? (
                    <Empty title="Nothing here" body={lane.key === 'short' ? 'No customer is waiting on a purchase.' : lane.key === 'ready' ? 'Nothing in stock is waiting for a truck.' : 'Nothing is on order for these customers.'} />
                  ) : (
                    <AnimatePresence initial={false}>
                      {laneRows.map((row) => (
                        <CommitmentCard key={row.order_item_id} row={row} lane={lane.key} qty={lane.qty(row)} onAction={setAction} />
                      ))}
                    </AnimatePresence>
                  )}
                </div>
              </motion.section>
            )
          })}
        </div>
      )}

      <DeliverSheet open={action?.kind === 'deliver'} onClose={() => setAction(null)} orderId={action?.row.order_id ?? ''} onlyItem={action?.kind === 'deliver' ? action.row.order_item_id : undefined} />
      <ReceiveSheet
        open={action?.kind === 'receive'}
        onClose={() => setAction(null)}
        poId={action?.kind === 'receive' ? action.row.incoming_sources[0]?.purchase_order_id : undefined}
        focusItem={action?.kind === 'receive' ? action.row.incoming_sources[0]?.purchase_order_item_id : undefined}
      />
      <PurchaseSheet
        open={action?.kind === 'buy'}
        onClose={() => setAction(null)}
        subtitle={action?.kind === 'buy' ? `For ${action.row.customer_name}'s ${fmtQty(action.row.quantity_unallocated)} ${action.row.unit_of_measure} short on ${action.row.order_number}.` : undefined}
        initial={
          action?.kind === 'buy'
            ? { supplier_id: action.row.last_supplier_id ?? undefined, lines: [{ product_id: action.row.product_id, quantity: String(n(action.row.quantity_unallocated)) }], prefer: action.row.order_item_id }
            : undefined
        }
      />
    </div>
  )
}

function Stat({ label, value, hint, color, alert }: { label: string; value?: string; hint?: string; color?: string; alert?: boolean }) {
  return (
    <div>
      <div className="flex items-center gap-1.5 text-[11.5px] font-medium text-fg-3">
        {color ? <span className="size-1.5 rounded-full" style={{ background: color }} /> : null}
        {label}
      </div>
      <div className={cn('num text-[20px] font-semibold tracking-[-0.02em]', alert && 'text-bad')}>{value ?? '—'}</div>
      {hint ? <div className="text-[11px] text-fg-3">{hint}</div> : null}
    </div>
  )
}

function CommitmentCard({ row, lane, qty, onAction }: { row: CommitmentRow; lane: LaneKey; qty: number; onAction: (action: Action) => void }) {
  const age = daysSince(row.order_created_at)
  const button =
    lane === 'ready' ? (
      <Button kind="primary" small icon={<Truck size={13} />} onClick={() => onAction({ kind: 'deliver', row })}>
        Deliver
      </Button>
    ) : lane === 'onOrder' ? (
      <Button kind="quiet" small icon={<PackageOpen size={13} />} onClick={() => onAction({ kind: 'receive', row })} disabled={row.incoming_sources.length === 0}>
        Receive
      </Button>
    ) : (
      <Button kind="quiet" small icon={<ClipboardList size={13} />} onClick={() => onAction({ kind: 'buy', row })}>
        Buy
      </Button>
    )
  return (
    <motion.article layout initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.98 }} className="card group p-3.5 transition-colors hover:bg-ink-750">
      <div className="flex items-start gap-2.5">
        <Avatar name={row.customer_name} size={28} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-medium">{row.customer_name}</div>
          <div className="text-[11.5px] text-fg-3">
            <Link to={`/orders/${row.order_id}`} className="num text-sky hover:text-sky-2">
              {row.order_number}
            </Link>{' '}
            · <span className={cn(age > 14 ? 'text-warn' : undefined)}>{age === 0 ? 'today' : `${age} d waiting`}</span>
          </div>
        </div>
        <div className="text-right">
          <div className="num text-[17px] leading-tight font-semibold">{fmtQty(qty)}</div>
          <div className="text-[11px] text-fg-3">{row.unit_of_measure}</div>
        </div>
      </div>
      <div className="mt-3 flex items-center justify-between gap-2 text-[12.5px]">
        <span className="min-w-0 truncate text-fg-2">
          {row.product_name} <span className="text-fg-4">· {row.product_sku}</span>
        </span>
      </div>
      <Meter
        className="mt-2"
        total={n(row.quantity_ordered) - n(row.quantity_cancelled)}
        parts={[
          { label: 'Sent', value: n(row.quantity_delivered), color: STATE.delivered },
          { label: 'Ready', value: n(row.quantity_deliverable), color: STATE.ready },
          { label: 'On order', value: n(row.quantity_incoming), color: STATE.onOrder },
          { label: 'Short', value: n(row.quantity_unallocated), color: STATE.short },
        ]}
      />
      <div className="mt-3 flex items-center gap-2">
        <div className="flex min-w-0 flex-1 flex-wrap gap-1">
          {n(row.quantity_delivered) > 0 ? <Badge>{fmtQty(row.quantity_delivered)} sent</Badge> : null}
          {lane !== 'ready' && n(row.quantity_deliverable) > 0 ? <Badge tone="sky">{fmtQty(row.quantity_deliverable)} ready</Badge> : null}
          {lane !== 'onOrder' && n(row.quantity_incoming) > 0 ? <Badge tone="steel">{fmtQty(row.quantity_incoming)} on order</Badge> : null}
          {lane !== 'short' && n(row.quantity_unallocated) > 0 ? <Badge tone="bad">{fmtQty(row.quantity_unallocated)} short</Badge> : null}
          {lane === 'onOrder' && row.incoming_sources[0] ? <span className="truncate text-[11.5px] text-fg-3">{row.incoming_sources[0].po_number} · {row.incoming_sources[0].supplier_name}</span> : null}
        </div>
        {button}
      </div>
    </motion.article>
  )
}

function CustomersView({ rows, loading, onPick }: { rows: { customer_id: string; customer_name: string; order_count: number; line_count: number; quantity_outstanding: string; quantity_reserved: string; quantity_unallocated: string; quantity_incoming: string; outstanding_value: string; oldest_order_at: string }[]; loading: boolean; onPick: (id: string) => void }) {
  if (loading) return <div className="pane flex-1" />
  if (rows.length === 0) return <Empty className="pane flex-1" icon={<Truck size={20} />} title="Nobody is waiting" body="Every order has been delivered." />
  return (
    <div className="grid min-h-0 flex-1 auto-rows-min grid-cols-3 gap-3 overflow-y-auto max-lg:grid-cols-1">
      {rows.map((row, index) => (
        <motion.button
          key={row.customer_id}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: index * 0.03 }}
          onClick={() => onPick(row.customer_id)}
          className="pane p-4 text-left transition-colors hover:bg-ink-800"
        >
          <div className="flex items-center gap-3">
            <Avatar name={row.customer_name} size={34} />
            <div className="min-w-0 flex-1">
              <div className="truncate text-[14px] font-semibold">{row.customer_name}</div>
              <div className="text-[12px] text-fg-3">
                {plural(row.order_count, 'order')} · oldest {daysSince(row.oldest_order_at)} d ago
              </div>
            </div>
            <div className="text-right">
              <div className="num text-[17px] font-semibold">{fmtQty(row.quantity_outstanding)}</div>
              <div className="num text-[11.5px] text-fg-3">{fmtMoney(row.outstanding_value)}</div>
            </div>
          </div>
          <Meter
            className="mt-3"
            total={n(row.quantity_outstanding)}
            parts={[
              { label: 'Ready', value: n(row.quantity_reserved), color: STATE.ready },
              { label: 'On order', value: n(row.quantity_incoming), color: STATE.onOrder },
              { label: 'Short', value: n(row.quantity_unallocated), color: STATE.short },
            ]}
          />
          <div className="mt-2 flex gap-3 text-[11.5px] text-fg-3">
            <span className="text-sky">{fmtQty(row.quantity_reserved)} ready</span>
            <span className="text-steel">{fmtQty(row.quantity_incoming)} on order</span>
            <span className="text-bad">{fmtQty(row.quantity_unallocated)} short</span>
          </div>
        </motion.button>
      ))}
    </div>
  )
}
