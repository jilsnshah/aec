import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Ban, ClipboardList, MoreHorizontal, PackageOpen, Pencil, Plus, Send, Users } from 'lucide-react'
import { errorText } from '@/api/client'
import { api } from '@/api/endpoints'
import { useAction, useCommitments, useList, useOne } from '@/api/queries'
import type { PurchaseOrderOut } from '@/api/types'
import { fmtAmount, fmtDate, fmtDateTime, fmtMoney, fmtQty, n } from '@/lib/format'
import { useDebounced, useRecordRoute } from '@/lib/route'
import { PurchaseBadge } from '@/lib/status'
import { Button, Empty, Facts, Meter, Notice, SearchBox, Spinner } from '@/ui/core'
import { Menu, Segmented, Sheet, TabPanel, Tabs, useConfirm } from '@/ui/overlays'
import { FigureStrip, InspectorHeader, ListPane, ListRow, ListSkeleton, Section, SplitView } from '@/ui/split'
import { TallyPanel } from '@/features/integrations/TallyPanel'
import { ReceiveSheet } from '@/features/receipts/ReceiveSheet'
import { claimantsFrom, PurchaseSheet, SettleBlock, type SettlementState } from './PurchaseSheet'

const FILTERS = [
  { value: 'open', label: 'Open', status: 'DRAFT,ORDERED,PARTIALLY_RECEIVED' },
  { value: 'RECEIVED', label: 'Received', status: 'RECEIVED' },
  { value: 'CANCELLED', label: 'Cancelled', status: 'CANCELLED' },
  { value: 'all', label: 'All', status: undefined },
]

export function PurchaseOrders() {
  const route = useRecordRoute('/purchase-orders')
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState('open')
  const query = useDebounced(search)
  const list = useList('purchase-orders', api.purchaseOrders.list, { search: query, status: FILTERS.find((item) => item.value === filter)?.status, limit: 200 })
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
          title="Purchase Orders"
          count={list.data?.total}
          actions={
            <Button kind="ghost" small iconOnly onClick={route.openNew} aria-label="New purchase order">
              <Plus size={16} />
            </Button>
          }
          filters={
            <>
              <SearchBox value={search} onChange={setSearch} placeholder="PO number, supplier or product" />
              <Segmented value={filter} onChange={setFilter} options={FILTERS.map(({ value, label }) => ({ value, label }))} />
            </>
          }
        >
          {list.isPending ? (
            <ListSkeleton />
          ) : items.length === 0 ? (
            <Empty icon={<ClipboardList size={20} />} title={search ? 'No purchase orders match' : 'No purchase orders here'} action={<Button kind="primary" small onClick={route.openNew}>New purchase order</Button>} />
          ) : (
            items.map((po) => (
              <ListRow key={po.id} group="po" selected={po.id === route.id} onSelect={() => route.select(po.id)}>
                <div className="flex items-baseline gap-2">
                  <span className="num text-[13px] font-semibold">{po.po_number}</span>
                  <span className="num ml-auto text-[13px] font-medium">{fmtMoney(po.total_cost)}</span>
                </div>
                <div className="mt-0.5 flex items-center gap-2 text-[12px] text-fg-3">
                  <span className="truncate">{po.supplier.name}</span>
                  <span className="ml-auto shrink-0">{po.expected_delivery_date ? `due ${fmtDate(po.expected_delivery_date)}` : fmtDate(po.created_at)}</span>
                </div>
                <div className="mt-2 flex items-center gap-2.5">
                  <Meter parts={[{ label: 'Received', value: n(po.total_received), color: '#7cc4ff' }, { label: 'Due', value: n(po.total_remaining), color: 'rgba(255,255,255,0.08)' }]} />
                  <PurchaseBadge status={po.status} />
                </div>
              </ListRow>
            ))
          )}
        </ListPane>
      }
    >
      {route.id ? <PurchaseInspector id={route.id} /> : <Empty className="h-full" icon={<ClipboardList size={22} />} title="Choose a purchase order" />}
      <PurchaseSheet open={route.isNew} onClose={route.closeNew} onSaved={(po) => route.select(po.id)} />
    </SplitView>
  )
}

function PurchaseInspector({ id }: { id: string }) {
  const po = useOne('purchase-orders', api.purchaseOrders.get, id)
  const [tab, setTab] = useState('lines')
  const [editing, setEditing] = useState(false)
  const [receiving, setReceiving] = useState(false)
  const [settling, setSettling] = useState<null | 'place' | 'settle'>(null)
  const confirm = useConfirm()
  const cancel = useAction((reason: string | null) => api.purchaseOrders.cancel(id, reason), { success: 'Purchase order cancelled' })

  if (po.isPending) return <Spinner />
  if (!po.data) return <Empty title="This purchase order could not be loaded" />
  const data = po.data
  const draft = data.status === 'DRAFT'
  const needsSettling = !draft && data.can_receive && data.items.some((item) => n(item.settle_required) > 0)

  async function askCancel() {
    const answer = await confirm.ask({
      title: `Cancel ${data.po_number}?`,
      body: 'What has not arrived is cancelled. Customers it was covering become short again.',
      confirm: 'Cancel purchase order',
      danger: true,
      withReason: true,
    })
    if (answer.ok) cancel.mutate(answer.reason || null)
  }

  return (
    <>
      <InspectorHeader
        eyebrow="Purchase order"
        title={data.po_number}
        badges={<PurchaseBadge status={data.status} />}
        meta={
          <>
            <Link to={`/suppliers/${data.supplier_id}`} className="text-sky hover:text-sky-2">
              {data.supplier.name}
            </Link>
            {' · '}
            {data.ordered_at ? `placed ${fmtDateTime(data.ordered_at)}` : `drafted ${fmtDateTime(data.created_at)}`}
            {data.expected_delivery_date ? ` · expected ${fmtDate(data.expected_delivery_date)}` : ''}
          </>
        }
        actions={
          <>
            {draft ? (
              <>
                <Button icon={<Pencil size={14} />} onClick={() => setEditing(true)}>
                  Edit
                </Button>
                <Button kind="primary" icon={<Send size={14} />} onClick={() => setSettling('place')}>
                  Place order
                </Button>
              </>
            ) : data.can_receive ? (
              <Button kind="primary" icon={<PackageOpen size={15} />} onClick={() => setReceiving(true)}>
                Receive goods
              </Button>
            ) : null}
            <Menu
              trigger={
                <Button iconOnly aria-label="More actions">
                  <MoreHorizontal size={16} />
                </Button>
              }
              items={[
                { label: 'Settle short customers', icon: <Users size={14} />, onSelect: () => setSettling('settle'), disabled: !needsSettling },
                { label: 'Cancel purchase order', icon: <Ban size={14} />, onSelect: askCancel, danger: true, separator: true, disabled: data.status === 'CANCELLED' || data.status === 'RECEIVED' },
              ]}
            />
          </>
        }
      />
      {draft ? (
        <div className="shrink-0 px-6 pt-4">
          <Notice tone="sky">This is a draft. Nothing counts until it is placed with the supplier.</Notice>
        </div>
      ) : needsSettling ? (
        <div className="shrink-0 px-6 pt-4">
          <Notice tone="warn">
            Some of this order is promised to nobody while customers are short.{' '}
            <button className="font-medium text-sky hover:text-sky-2" onClick={() => setSettling('settle')}>
              Settle them
            </button>
          </Notice>
        </div>
      ) : null}
      <FigureStrip
        items={[
          { label: 'Ordered', value: fmtQty(data.total_ordered) },
          { label: 'Received', value: fmtQty(data.total_received), hint: n(data.total_ordered) > 0 ? `${Math.round((n(data.total_received) / n(data.total_ordered)) * 100)}% of the order` : undefined },
          { label: 'Still to come', value: fmtQty(data.total_remaining), tone: n(data.total_remaining) > 0 ? 'sky' : undefined },
          { label: 'Value', value: fmtMoney(data.total_cost), hint: 'at ordered cost' },
        ]}
      />
      <Tabs
        value={tab}
        onChange={setTab}
        className="min-h-0 flex-1"
        tabs={[
          { value: 'lines', label: 'Lines', count: data.items.length },
          { value: 'receipts', label: 'Receipts', count: data.receipts.length },
          { value: 'tally', label: 'Tally' },
        ]}
      >
        <TabPanel value="lines">
          <table className="grid-table">
            <thead>
              <tr>
                <th>Product</th>
                <th className="r">Cost</th>
                <th className="r">Ordered</th>
                <th className="w-[180px]">Received</th>
                <th className="r">For customers</th>
                <th className="r">Line cost</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((item) => (
                <tr key={item.id}>
                  <td>
                    <Link to={`/products/${item.product_id}`} className="text-[13px] font-medium hover:text-sky">
                      {item.product.name}
                    </Link>
                    <div className="text-[11.5px] text-fg-3">
                      {item.product.sku} · {item.product.unit_of_measure}
                    </div>
                  </td>
                  <td className="r num">{fmtAmount(item.unit_cost)}</td>
                  <td className="r num">{fmtQty(item.quantity_ordered)}</td>
                  <td>
                    <Meter parts={[{ label: 'Received', value: n(item.quantity_received), color: '#7cc4ff' }]} total={n(item.quantity_ordered)} />
                    <div className="mt-1 text-[11px] text-fg-3">
                      {fmtQty(item.quantity_received)} in · {fmtQty(item.quantity_remaining)} due
                    </div>
                  </td>
                  <td className="r num text-[13px]">
                    {fmtQty(item.quantity_assigned)}
                    <div className="text-[11px] text-fg-3">{fmtQty(item.quantity_free)} free</div>
                  </td>
                  <td className="r num">{fmtAmount(item.line_cost)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.notes || data.cancellation_reason ? (
            <Section title="Notes">
              <p className="text-[13px] whitespace-pre-line text-fg-2">{[data.notes, data.cancellation_reason ? `Cancelled: ${data.cancellation_reason}` : null].filter(Boolean).join('\n')}</p>
            </Section>
          ) : null}
        </TabPanel>
        <TabPanel value="receipts">
          {data.receipts.length === 0 ? (
            <Empty icon={<PackageOpen size={20} />} title="Nothing received yet" body="Each delivery from the supplier is booked in as a goods receipt." />
          ) : (
            <table className="grid-table">
              <thead>
                <tr>
                  <th>Receipt</th>
                  <th>Received</th>
                  <th>Delivery note</th>
                  <th className="r">Quantity</th>
                </tr>
              </thead>
              <tbody>
                {data.receipts.map((receipt) => (
                  <tr key={receipt.id}>
                    <td>
                      <Link to={`/receipts/${receipt.id}`} className="num text-[13px] font-medium text-sky hover:text-sky-2">
                        {receipt.receipt_number}
                      </Link>
                    </td>
                    <td className="text-[13px] text-fg-2">{fmtDateTime(receipt.created_at)}</td>
                    <td className="text-[13px] text-fg-3">{receipt.delivery_note_reference ?? '—'}</td>
                    <td className="r num">{fmtQty(receipt.total_quantity)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </TabPanel>
        <TabPanel value="tally">
          <TallyPanel entityId={id} />
        </TabPanel>
      </Tabs>
      <PurchaseSheet open={editing} onClose={() => setEditing(false)} editing={data} />
      <ReceiveSheet open={receiving} onClose={() => setReceiving(false)} poId={id} />
      <SettleSheet po={data} mode={settling} onClose={() => setSettling(null)} />
      {confirm.element}
    </>
  )
}

/** Place a draft, or settle a placed order: choose which short customers it covers. */
function SettleSheet({ po, mode, onClose }: { po: PurchaseOrderOut; mode: null | 'place' | 'settle'; onClose: () => void }) {
  const short = useCommitments({ only_unallocated: true })
  const [plans, setPlans] = useState<Record<string, SettlementState>>({})
  const place = useAction((body: { settlements: { product_id: string; allocations: { order_item_id: string; quantity: string }[] }[] | null }) => api.purchaseOrders.confirm(po.id, body), { success: `${po.po_number} placed`, quiet: true })
  const settle = useAction((body: { settlements: { product_id: string; allocations: { order_item_id: string; quantity: string }[] }[] | null }) => api.purchaseOrders.settle(po.id, body), { success: 'Customers settled', quiet: true })
  const action = mode === 'place' ? place : settle

  useEffect(() => {
    if (mode) {
      setPlans({})
      place.reset()
      settle.reset()
    }
  }, [mode]) // eslint-disable-line react-hooks/exhaustive-deps

  const needs = useMemo(() => {
    const byProduct = new Map<string, { name: string; unit: string; required: number }>()
    po.items.forEach((item) => {
      const current = byProduct.get(item.product_id) ?? { name: item.product.name, unit: item.product.unit_of_measure, required: 0 }
      current.required += n(item.settle_required)
      byProduct.set(item.product_id, current)
    })
    return [...byProduct.entries()]
      .map(([productId, info]) => ({ productId, ...info, claimants: claimantsFrom((short.data?.rows ?? []).filter((row) => row.product_id === productId)) }))
      .filter((need) => need.required > 0 && need.claimants.length > 0)
  }, [po, short.data])
  const ready = !short.isPending && needs.every((need) => plans[need.productId]?.balanced)

  return (
    <Sheet
      open={mode !== null}
      onClose={onClose}
      width={820}
      title={mode === 'place' ? `Place ${po.po_number}` : `Settle customers from ${po.po_number}`}
      subtitle={mode === 'place' ? `Send it to ${po.supplier.name}. It counts as stock at once, so customers who are short must be covered from it.` : 'Give what this order has not promised to customers who are short.'}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button kind="primary" icon={mode === 'place' ? <Send size={14} /> : <Users size={14} />} busy={action.isPending} disabled={!ready} onClick={() => action.mutate({ settlements: needs.map((need) => ({ product_id: need.productId, allocations: plans[need.productId].allocations })) }, { onSuccess: onClose })}>
            {mode === 'place' ? 'Place order' : 'Settle'}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {action.error ? <Notice tone="bad">{errorText(action.error)}</Notice> : null}
        {short.isPending ? <Spinner /> : needs.length === 0 ? <Notice tone="sky">No customer is short of these products. Everything goes into free stock.</Notice> : null}
        {needs.map((need) => (
          <SettleBlock key={need.productId} productName={need.name} unit={need.unit} claimants={need.claimants} required={need.required} onState={(state) => setPlans((current) => ({ ...current, [need.productId]: state }))} />
        ))}
        <Facts items={[{ label: 'Order value', value: fmtMoney(po.total_cost) }]} />
      </div>
    </Sheet>
  )
}
