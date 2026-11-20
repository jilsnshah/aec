import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  ArrowRight,
  Ban,
  Boxes,
  CheckCircle2,
  Factory,
  MapPin,
  PackageCheck,
  Pencil,
  Plus,
  Star,
  Store,
  Trash2,
  Truck,
  Warehouse as WarehouseIcon,
  type LucideIcon,
} from 'lucide-react'
import { errorText } from '@/api/client'
import { useAction } from '@/api/queries'
import { warehouses, type Transfer, type TransferIn, type Warehouse } from '@/api/warehouses'
import { cn } from '@/lib/cn'
import { fmtDate, fmtDateTime, fmtMoney, fmtQty, n } from '@/lib/format'
import { Badge, Button, Empty, Field, Notice, SearchBox, Spinner } from '@/ui/core'
import { Segmented, Sheet, TabPanel, Tabs, useConfirm } from '@/ui/overlays'
import { Picker } from '@/ui/pickers'
import { baseQty, factorOf, productOption, unitsOf, useProducts } from '@/ui/lines'
import { FigureStrip, InspectorHeader, ListPane, ListRow, Section, SplitView } from '@/ui/split'
import { PageGuide } from '@/ui/smart'
import { useTransporterOptions } from '@/features/receipts/ReceiptExtras'

const KIND_ICON: Record<string, LucideIcon> = { godown: WarehouseIcon, yard: Factory, shop: Store, site: MapPin, transit: Truck }
const STATUS: Record<Transfer['status'], { label: string; tone: 'sky' | 'steel' | 'ok' | 'muted' }> = {
  draft: { label: 'Draft', tone: 'muted' },
  in_transit: { label: 'In transit', tone: 'sky' },
  received: { label: 'Received', tone: 'ok' },
  cancelled: { label: 'Cancelled', tone: 'muted' },
}

/** Warehouses and the transfers between them. */
export function Warehouses() {
  const [params, setParams] = useSearchParams()
  const view = (params.get('view') as 'warehouses' | 'transfers') ?? 'warehouses'
  const selected = params.get('id')
  const houses = useQuery({ queryKey: ['warehouses'], queryFn: warehouses.list })
  const transfers = useQuery({ queryKey: ['stock-transfers'], queryFn: () => warehouses.transfers() })
  const [sheet, setSheet] = useState<null | { kind: 'warehouse'; editing?: Warehouse } | { kind: 'transfer'; editing?: Transfer; from?: string }>(null)
  const set = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params)
    Object.entries(patch).forEach(([k, v]) => (v === null ? next.delete(k) : next.set(k, v)))
    setParams(next, { replace: true })
  }
  const list = houses.data?.items ?? []
  const moves = transfers.data?.items ?? []
  const onRoad = moves.filter((t) => t.status === 'in_transit').length
  useEffect(() => {
    if (selected) return
    if (view === 'warehouses' && list.length) set({ id: list[0].id })
    if (view === 'transfers' && moves.length) set({ id: moves[0].id })
  }, [view, list.length, moves.length]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <SplitView
        showDetail={Boolean(selected)}
        onBack={() => set({ id: null })}
        list={
          <ListPane
            title="Warehouses"
            count={view === 'warehouses' ? list.filter((w) => w.kind !== 'transit').length : moves.length}
            actions={
              <>
                <PageGuide
                  title="Warehouses and transfers"
                  points={[
                    { icon: WarehouseIcon, text: 'Keep stock in godowns, yards, shops or site stores. Stock-in, receipts, counts and deliveries can each name a warehouse; the default one is used otherwise.' },
                    { icon: Truck, text: 'A transfer is drafted, dispatched (the goods are "In transit") and received. What does not arrive is written off as lost in transit.' },
                    { icon: Boxes, text: 'Freight, loading, unloading and toll are spread over the goods by quantity, value or weight and added to their cost at the destination (landed cost).' },
                    { icon: Factory, text: 'With Tally on, each received transfer becomes a Stock Journal between godowns.' },
                  ]}
                />
                <Button small kind="primary" icon={<Plus size={14} />} onClick={() => setSheet(view === 'warehouses' ? { kind: 'warehouse' } : { kind: 'transfer' })}>
                  New
                </Button>
              </>
            }
            filters={
              <Segmented
                value={view}
                onChange={(v) => set({ view: v, id: null })}
                options={[
                  { value: 'warehouses', label: 'Warehouses' },
                  { value: 'transfers', label: 'Transfers', count: onRoad || undefined },
                ]}
              />
            }
          >
            {houses.isPending || transfers.isPending ? (
              <Spinner />
            ) : view === 'warehouses' ? (
              list.map((w) => {
                const Icon = KIND_ICON[w.kind] ?? WarehouseIcon
                return (
                  <ListRow key={w.id} group="wh" selected={selected === w.id} onSelect={() => set({ id: w.id })}>
                    <div className="flex items-center gap-2.5">
                      <span className={cn('grid size-8 shrink-0 place-items-center rounded-full', w.kind === 'transit' ? 'bg-sky/15' : 'bg-white/7')}>
                        <Icon size={15} />
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5">
                          <span className="truncate text-[13.5px] font-semibold">{w.name}</span>
                          {w.is_default ? <Star size={12} className="shrink-0 fill-current" aria-label="Default" /> : null}
                          {!w.is_active ? <Badge>Closed</Badge> : null}
                        </div>
                        <div className="truncate text-[12px] text-fg-3">
                          {w.kind_label} · {w.products} product{w.products === 1 ? '' : 's'}
                        </div>
                      </div>
                      <span className="num text-[12.5px] font-semibold">{fmtMoney(w.value)}</span>
                    </div>
                  </ListRow>
                )
              })
            ) : moves.length ? (
              moves.map((t) => (
                <ListRow key={t.id} group="tr" selected={selected === t.id} onSelect={() => set({ id: t.id })}>
                  <div className="flex items-center gap-2">
                    <span className="text-[13.5px] font-semibold">{t.number}</span>
                    <Badge tone={STATUS[t.status].tone} dot={t.status === 'in_transit'}>
                      {STATUS[t.status].label}
                    </Badge>
                    <span className="num ml-auto text-[12.5px] font-semibold">{fmtMoney(t.status === 'received' ? t.landed_value : t.goods_value)}</span>
                  </div>
                  <div className="mt-0.5 flex items-center gap-1 truncate text-[12px] text-fg-3">
                    {t.from_warehouse} <ArrowRight size={11} /> {t.to_warehouse} · {t.products}
                  </div>
                </ListRow>
              ))
            ) : (
              <Empty icon={<Truck size={20} />} title="No transfers yet" body="Move stock between warehouses with New." />
            )}
          </ListPane>
        }
      >
        {!selected ? (
          <Empty className="h-full" icon={<WarehouseIcon size={22} />} title="Choose a warehouse" />
        ) : view === 'warehouses' ? (
          <WarehouseView key={selected} id={selected} house={list.find((w) => w.id === selected)} onEdit={(w) => setSheet({ kind: 'warehouse', editing: w })} onTransfer={(from) => setSheet({ kind: 'transfer', from })} />
        ) : (
          <TransferView key={selected} id={selected} onEdit={(t) => setSheet({ kind: 'transfer', editing: t })} />
        )}
      </SplitView>
      <WarehouseSheet open={sheet?.kind === 'warehouse'} editing={sheet?.kind === 'warehouse' ? sheet.editing : undefined} onClose={() => setSheet(null)} onSaved={(id) => set({ view: 'warehouses', id })} />
      <TransferSheet
        open={sheet?.kind === 'transfer'}
        editing={sheet?.kind === 'transfer' ? sheet.editing : undefined}
        from={sheet?.kind === 'transfer' ? sheet.from : undefined}
        houses={list}
        onClose={() => setSheet(null)}
        onSaved={(id) => set({ view: 'transfers', id })}
      />
    </>
  )
}

function WarehouseView({ id, house, onEdit, onTransfer }: { id: string; house?: Warehouse; onEdit: (w: Warehouse) => void; onTransfer: (from: string) => void }) {
  const stock = useQuery({ queryKey: ['warehouses', 'stock', id], queryFn: () => warehouses.stock({ warehouse_id: id }) })
  const moves = useQuery({ queryKey: ['stock-transfers', id], queryFn: () => warehouses.transfers({ warehouse_id: id }) })
  const update = useAction(warehouses.update, { success: 'Saved' })
  const confirm = useConfirm()
  const [tab, setTab] = useState('stock')
  const [search, setSearch] = useState('')
  if (!house) return <Spinner />
  const rows = (stock.data?.items ?? []).filter((r) => !search || r.product.toLowerCase().includes(search.toLowerCase()) || r.sku.toLowerCase().includes(search.toLowerCase()))
  const transit = house.kind === 'transit'
  const incoming = (moves.data?.items ?? []).filter((t) => t.status === 'in_transit' && t.to_warehouse_id === id)
  return (
    <>
      <InspectorHeader
        eyebrow={`${house.kind_label}${house.code ? ` · ${house.code}` : ''}`}
        title={house.name}
        badges={
          <>
            {house.is_default ? <Badge tone="sky">Default</Badge> : null}
            {!house.is_active ? <Badge>Closed</Badge> : null}
          </>
        }
        meta={transit ? 'Goods on the road between two warehouses. They arrive when the transfer is received.' : [house.address, house.contact, house.tally_godown ? `Tally godown: ${house.tally_godown}` : null].filter(Boolean).join(' · ') || undefined}
        actions={
          transit ? null : (
            <>
              <Button icon={<Pencil size={14} />} onClick={() => onEdit(house)}>
                Edit
              </Button>
              {!house.is_default && house.is_active ? (
                <Button icon={<Star size={14} />} onClick={() => update.mutate({ id, is_default: true })}>
                  Make default
                </Button>
              ) : null}
              {!house.is_default ? (
                <Button
                  kind="ghost"
                  icon={<Ban size={14} />}
                  onClick={async () => {
                    if (!house.is_active) return update.mutate({ id, is_active: true })
                    const answer = await confirm.ask({ title: `Close ${house.name}?`, body: 'Only an empty warehouse can be closed. It can be reopened later.', confirm: 'Close', danger: true })
                    if (answer.ok) update.mutate({ id, is_active: false })
                  }}
                >
                  {house.is_active ? 'Close' : 'Reopen'}
                </Button>
              ) : null}
              <Button kind="primary" icon={<Truck size={14} />} disabled={!house.products} onClick={() => onTransfer(id)}>
                Transfer out
              </Button>
            </>
          )
        }
      />
      {update.error ? <div className="px-6 pt-3"><Notice tone="bad">{errorText(update.error)}</Notice></div> : null}
      <FigureStrip
        items={[
          { label: 'Stock value', value: fmtMoney(house.value), tone: 'sky', hint: 'at cost, incl. transfer costs' },
          { label: 'Products', value: String(house.products) },
          { label: 'Units', value: fmtQty(house.quantity), hint: 'all products' },
          { label: 'Arriving', value: String(incoming.length), tone: incoming.length ? 'steel' : undefined, hint: 'transfers on the way' },
        ]}
      />
      <Tabs
        value={tab}
        onChange={setTab}
        className="min-h-0 flex-1"
        tabs={[
          { value: 'stock', label: 'Stock', count: stock.data?.items.length },
          { value: 'transfers', label: 'Transfers', count: moves.data?.items.length },
        ]}
      >
        <TabPanel value="stock">
          <div className="mb-3 max-w-[320px]">
            <SearchBox value={search} onChange={setSearch} placeholder="Find a product" />
          </div>
          {stock.isPending ? (
            <Spinner />
          ) : rows.length ? (
            <div className="overflow-x-auto">
              <table className="grid-table min-w-[560px]">
                <thead>
                  <tr>
                    <th>Product</th>
                    <th className="r">Quantity</th>
                    <th className="r">Avg cost</th>
                    <th className="r">Value</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.product_id}>
                      <td>
                        <div className="text-[13px] font-medium">{r.product}</div>
                        <div className="text-[11.5px] text-fg-3">
                          {r.sku}
                          {r.category ? ` · ${r.category}` : ''}
                        </div>
                      </td>
                      <td className="r num">
                        {fmtQty(r.quantity)} <span className="text-[11px] text-fg-3">{r.unit}</span>
                      </td>
                      <td className="r num">{fmtMoney(r.average_cost)}</td>
                      <td className="r num font-semibold">{fmtMoney(r.value)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty icon={<Boxes size={20} />} title="Nothing here" body={transit ? 'No goods on the road right now.' : 'Receive stock into this warehouse, or transfer some in.'} />
          )}
        </TabPanel>
        <TabPanel value="transfers">
          <TransferTable items={moves.data?.items ?? []} here={id} />
        </TabPanel>
      </Tabs>
    </>
  )
}

function TransferTable({ items, here }: { items: Transfer[]; here?: string }) {
  const [, setParams] = useSearchParams()
  if (!items.length) return <Empty icon={<Truck size={20} />} title="No transfers" />
  return (
    <div className="overflow-x-auto">
      <table className="grid-table min-w-[620px]">
        <thead>
          <tr>
            <th>Transfer</th>
            <th>Route</th>
            <th>Status</th>
            <th className="r">Goods</th>
            <th className="r">Costs</th>
          </tr>
        </thead>
        <tbody>
          {items.map((t) => (
            <tr key={t.id} className="cursor-pointer hover:bg-white/[0.03]" onClick={() => setParams({ view: 'transfers', id: t.id })}>
              <td>
                <div className="text-[13px] font-semibold">{t.number}</div>
                <div className="text-[11.5px] text-fg-3">{fmtDate(t.created_at)}</div>
              </td>
              <td className="text-[12.5px]">
                {here ? (t.from_warehouse_id === here ? <>Out to {t.to_warehouse}</> : <>In from {t.from_warehouse}</>) : (
                  <>
                    {t.from_warehouse} → {t.to_warehouse}
                  </>
                )}
                <div className="truncate text-[11.5px] text-fg-3">{t.products}</div>
              </td>
              <td>
                <Badge tone={STATUS[t.status].tone}>{STATUS[t.status].label}</Badge>
              </td>
              <td className="r num">{fmtMoney(t.goods_value)}</td>
              <td className="r num">{t.costs_total ? fmtMoney(t.costs_total) : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function TransferView({ id, onEdit }: { id: string; onEdit: (t: Transfer) => void }) {
  const data = useQuery({ queryKey: ['stock-transfers', 'one', id], queryFn: () => warehouses.transfer(id) })
  const dispatch = useAction(warehouses.dispatch, { success: 'Dispatched: the goods are in transit', quiet: true })
  const cancel = useAction(warehouses.cancel, { success: 'Transfer cancelled' })
  const confirm = useConfirm()
  const [receiving, setReceiving] = useState(false)
  if (data.isPending) return <Spinner />
  if (!data.data) return <Empty title="Transfer not found" />
  const t = data.data
  const steps = [
    { label: 'Drafted', at: t.created_at, done: true },
    { label: 'Dispatched', at: t.dispatched_at, done: Boolean(t.dispatched_at) },
    { label: t.status === 'cancelled' ? 'Cancelled' : 'Received', at: t.received_at, done: t.status === 'received' || t.status === 'cancelled' },
  ]
  return (
    <>
      <InspectorHeader
        eyebrow="Stock transfer"
        title={t.number}
        badges={<Badge tone={STATUS[t.status].tone} dot={t.status === 'in_transit'}>{STATUS[t.status].label}</Badge>}
        meta={[t.vehicle ? `Vehicle ${t.vehicle}` : null, t.transporter, t.notes].filter(Boolean).join(' · ') || undefined}
        actions={
          <>
            {t.status === 'draft' ? (
              <Button icon={<Pencil size={14} />} onClick={() => onEdit(t)}>
                Edit
              </Button>
            ) : null}
            {t.status === 'in_transit' ? (
              <Button icon={<Pencil size={14} />} onClick={() => onEdit(t)}>
                Costs
              </Button>
            ) : null}
            {t.status === 'draft' || t.status === 'in_transit' ? (
              <Button
                kind="ghost"
                icon={<Ban size={14} />}
                onClick={async () => {
                  const answer = await confirm.ask({
                    title: `Cancel ${t.number}?`,
                    body: t.status === 'in_transit' ? `The goods go back into ${t.from_warehouse} at their original cost.` : 'The draft is dropped.',
                    confirm: 'Cancel transfer',
                    danger: true,
                  })
                  if (answer.ok) cancel.mutate(t.id)
                }}
              >
                Cancel
              </Button>
            ) : null}
            {t.status === 'draft' ? (
              <Button kind="primary" icon={<Truck size={14} />} busy={dispatch.isPending} onClick={() => dispatch.mutate(t.id)}>
                Dispatch
              </Button>
            ) : null}
            {t.status === 'in_transit' ? (
              <Button kind="primary" icon={<PackageCheck size={14} />} onClick={() => setReceiving(true)}>
                Receive
              </Button>
            ) : null}
          </>
        }
      />
      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-6 pb-24 max-md:p-4">
        {dispatch.error ? <Notice tone="bad">{errorText(dispatch.error)}</Notice> : null}
        <div className="card flex flex-wrap items-center gap-4 p-4">
          <div className="min-w-[140px] flex-1">
            <div className="text-[11px] text-fg-3">From</div>
            <div className="text-[15px] font-semibold">{t.from_warehouse}</div>
          </div>
          <div className="flex flex-1 items-center gap-2">
            {steps.map((s, i) => (
              <div key={s.label} className="flex flex-1 items-center gap-2">
                <div className="text-center">
                  <span className={cn('mx-auto grid size-7 place-items-center rounded-full', s.done ? 'brand-fill' : 'bg-white/8 text-fg-3')}>
                    {s.done ? <CheckCircle2 size={14} /> : i + 1}
                  </span>
                  <div className="mt-1 text-[11px] whitespace-nowrap">{s.label}</div>
                  <div className="text-[10.5px] whitespace-nowrap text-fg-3">{s.at && s.done ? fmtDateTime(s.at) : ''}</div>
                </div>
                {i < steps.length - 1 ? <div className={cn('h-[2px] flex-1 rounded', steps[i + 1].done ? 'bg-blue' : 'bg-white/10')} /> : null}
              </div>
            ))}
          </div>
          <div className="min-w-[140px] flex-1 text-right">
            <div className="text-[11px] text-fg-3">To</div>
            <div className="text-[15px] font-semibold">{t.to_warehouse}</div>
          </div>
        </div>
        <FigureStrip
          items={[
            { label: 'Goods at cost', value: fmtMoney(t.goods_value), hint: 'FIFO cost at the source' },
            { label: 'Transfer costs', value: fmtMoney(t.costs_total), tone: t.costs_total ? 'steel' : undefined, hint: { quantity: 'spread by quantity', value: 'spread by value', weight: 'spread by weight' }[t.cost_method] },
            { label: 'Lost in transit', value: fmtMoney(t.loss_value), tone: t.loss_value ? 'bad' : undefined },
            { label: 'Landed value', value: t.status === 'received' ? fmtMoney(t.landed_value) : '—', tone: 'sky', hint: 'what arrived, incl. costs' },
          ]}
        />
        <Section title="Products">
          <div className="overflow-x-auto">
            <table className="grid-table min-w-[680px]">
              <thead>
                <tr>
                  <th>Product</th>
                  <th className="r">Sent</th>
                  <th className="r">Received</th>
                  <th className="r">Cost / unit</th>
                  <th className="r">Share of costs</th>
                  <th className="r">Landed / unit</th>
                </tr>
              </thead>
              <tbody>
                {t.items.map((i) => (
                  <tr key={i.id}>
                    <td>
                      <div className="text-[13px] font-medium">{i.product}</div>
                      <div className="text-[11.5px] text-fg-3">{i.sku}</div>
                    </td>
                    <td className="r num">
                      {i.unit ? (
                        <>
                          {fmtQty(i.unit_quantity)} {i.unit}
                          <div className="text-[11px] text-fg-3">= {fmtQty(i.quantity)} {i.base_unit}</div>
                        </>
                      ) : (
                        <>
                          {fmtQty(i.quantity)} <span className="text-[11px] text-fg-3">{i.base_unit}</span>
                        </>
                      )}
                      {t.status === 'draft' && i.available != null && i.available < i.quantity ? <div className="text-[11px] text-bad">only {fmtQty(i.available)} there</div> : null}
                    </td>
                    <td className={cn('r num', t.status === 'received' && i.quantity_received < i.quantity && 'text-bad')}>{t.status === 'received' ? fmtQty(i.quantity_received) : '—'}</td>
                    <td className="r num">{i.unit_cost_before != null ? fmtMoney(i.unit_cost_before) : '—'}</td>
                    <td className="r num">{t.status === 'received' ? fmtMoney(i.extra_cost) : '—'}</td>
                    <td className="r num font-semibold">{i.unit_cost_after != null ? fmtMoney(i.unit_cost_after) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
        {t.costs.length ? (
          <Section title="Costs of moving the goods">
            <div className="card divide-y divide-white/6">
              {t.costs.map((c) => (
                <div key={c.id} className="flex items-center gap-3 px-4 py-2.5 text-[13px]">
                  <span className="font-medium">{c.label}</span>
                  {c.paid_to ? <span className="text-fg-3">to {c.paid_to}</span> : null}
                  <span className="num ml-auto font-semibold">{fmtMoney(c.amount)}</span>
                </div>
              ))}
            </div>
          </Section>
        ) : null}
      </div>
      <ReceiveSheet open={receiving} transfer={t} onClose={() => setReceiving(false)} />
    </>
  )
}

function ReceiveSheet({ open, transfer, onClose }: { open: boolean; transfer: Transfer; onClose: () => void }) {
  const [got, setGot] = useState<Record<string, string>>({})
  const [note, setNote] = useState('')
  useEffect(() => {
    if (open) setGot(Object.fromEntries(transfer.items.map((i) => [i.id, String(i.quantity)])))
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps
  const receive = useAction(() => warehouses.receive({ id: transfer.id, lines: transfer.items.map((i) => ({ item_id: i.id, quantity_received: got[i.id] || '0' })), note: note || undefined }), {
    success: 'Received',
    quiet: true,
  })
  const short = transfer.items.filter((i) => n(got[i.id]) < i.quantity)
  return (
    <Sheet
      open={open}
      onClose={onClose}
      width={640}
      title={`Receive ${transfer.number}`}
      subtitle={`Into ${transfer.to_warehouse}. Costs of ${fmtMoney(transfer.costs_total)} are added to what arrives.`}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button kind="primary" busy={receive.isPending} onClick={() => receive.mutate(undefined, { onSuccess: onClose })}>
            Receive
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        {receive.error ? <Notice tone="bad">{errorText(receive.error)}</Notice> : null}
        {transfer.items.map((i) => (
          <div key={i.id} className="card flex items-center gap-3 p-3">
            <div className="min-w-0 flex-1">
              <div className="text-[13.5px] font-medium">{i.product}</div>
              <div className="text-[12px] text-fg-3">
                Sent {fmtQty(i.quantity)} {i.base_unit}
              </div>
            </div>
            <label className="flex items-center gap-2 text-[12.5px]">
              Arrived
              <input className="field field-sm field-num w-[100px]" inputMode="decimal" aria-label={`Arrived ${i.product}`} value={got[i.id] ?? ''} onChange={(e) => setGot({ ...got, [i.id]: e.target.value })} />
              {i.base_unit}
            </label>
          </div>
        ))}
        {short.length ? (
          <>
            <Notice tone="warn">
              {short.map((i) => `${fmtQty(i.quantity - n(got[i.id]))} ${i.base_unit} of ${i.product}`).join(', ')} will be written off as lost in transit.
            </Notice>
            <Field label="What happened" optional>
              {(props) => <input {...props} className="field" value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. 2 bags torn while unloading" />}
            </Field>
          </>
        ) : null}
      </div>
    </Sheet>
  )
}

type CostRow = { kind: string; amount: string; paid_to: string }
type LineRow = { key: string; product_id: string; quantity: string; unit: string }
const newLine = (): LineRow => ({ key: Math.random().toString(36).slice(2), product_id: '', quantity: '', unit: '' })
const COSTS = [
  ['freight', 'Freight'],
  ['loading', 'Loading'],
  ['unloading', 'Unloading'],
  ['toll', 'Toll'],
  ['insurance', 'Insurance'],
  ['other', 'Other'],
]

function TransferSheet({ open, editing, from, houses, onClose, onSaved }: { open: boolean; editing?: Transfer; from?: string; houses: Warehouse[]; onClose: () => void; onSaved: (id: string) => void }) {
  const products = useProducts()
  const usable = houses.filter((w) => w.kind !== 'transit' && w.is_active)
  const [form, setForm] = useState({ from: '', to: '', method: 'quantity', vehicle: '', transporter: '', transporter_id: '', lr: '', notes: '' })
  const transporterOptions = useTransporterOptions()
  const [lines, setLines] = useState<LineRow[]>([newLine()])
  const [costs, setCosts] = useState<CostRow[]>([])
  const onRoad = editing?.status === 'in_transit'
  useEffect(() => {
    if (!open) return
    const fallback = from ?? usable.find((w) => w.is_default)?.id ?? ''
    setForm(
      editing
        ? { from: editing.from_warehouse_id, to: editing.to_warehouse_id, method: editing.cost_method, vehicle: editing.vehicle ?? '', transporter: editing.transporter ?? '', transporter_id: editing.transporter_id ?? '', lr: editing.lr_number ?? '', notes: editing.notes ?? '' }
        : { from: fallback, to: usable.find((w) => w.id !== fallback)?.id ?? '', method: 'quantity', vehicle: '', transporter: '', transporter_id: '', lr: '', notes: '' },
    )
    setLines(editing ? editing.items.map((i) => ({ key: i.id, product_id: i.product_id, quantity: String(i.unit ? i.unit_quantity : i.quantity), unit: i.unit ?? '' })) : [newLine()])
    setCosts(editing ? editing.costs.map((c) => ({ kind: c.kind, amount: String(c.amount), paid_to: c.paid_to ?? '' })) : [])
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps
  const stock = useQuery({ queryKey: ['warehouses', 'stock', form.from], queryFn: () => warehouses.stock({ warehouse_id: form.from }), enabled: open && Boolean(form.from) })
  const there = useMemo(() => new Map((stock.data?.items ?? []).map((r) => [r.product_id, r])), [stock.data])
  const chosen = lines.filter((l) => l.product_id && n(l.quantity) > 0)
  const totalCost = costs.reduce((s, c) => s + n(c.amount), 0)
  const basis = chosen.map((l) => {
    const product = products.byId.get(l.product_id)
    const qty = baseQty(l, product)
    const avg = there.get(l.product_id)?.average_cost ?? 0
    const weight = n(product?.weight_kg)
    return { line: l, product, qty, value: qty * avg, avg, b: form.method === 'value' ? qty * avg : form.method === 'weight' ? qty * (weight || 0) : qty }
  })
  const missingWeight = form.method === 'weight' && basis.some((x) => !n(x.product?.weight_kg))
  const whole = basis.reduce((s, x) => s + (missingWeight ? x.qty : x.b), 0)
  const errors = [
    !form.from || !form.to ? 'Choose both warehouses.' : form.from === form.to ? 'Choose two different warehouses.' : null,
    chosen.length ? null : 'Add at least one product and quantity.',
    ...basis.filter((x) => x.qty > (there.get(x.line.product_id)?.quantity ?? 0)).map((x) => `${x.product?.name}: only ${fmtQty(there.get(x.line.product_id)?.quantity ?? 0)} ${x.product?.unit_of_measure} in the source.`),
  ].filter(Boolean) as string[]
  const body = (dispatchNow: boolean): TransferIn => ({
    ...(onRoad
      ? {}
      : {
          from_warehouse_id: form.from,
          to_warehouse_id: form.to,
          items: chosen.map((l) => ({ product_id: l.product_id, quantity: l.quantity, unit: l.unit || null })),
        }),
    costs: costs.filter((c) => n(c.amount) > 0).map((c) => ({ kind: c.kind, amount: c.amount, paid_to: c.paid_to || null })),
    cost_method: form.method,
    vehicle: form.vehicle || null,
    transporter: form.transporter_id ? null : form.transporter || null,
    transporter_id: form.transporter_id || null,
    lr_number: form.lr || null,
    notes: form.notes || null,
    dispatch: dispatchNow,
  })
  const save = useAction((dispatchNow: boolean) => (editing ? warehouses.updateTransfer({ id: editing.id, ...body(false) }) : warehouses.createTransfer(body(dispatchNow))), {
    success: (t) => (t.status === 'in_transit' && !editing ? `${t.number} dispatched` : `${t.number} saved`),
    quiet: true,
  })
  const done = (t: Transfer) => (onClose(), onSaved(t.id))
  return (
    <Sheet
      open={open}
      onClose={onClose}
      width={980}
      title={editing ? `${onRoad ? 'Costs of' : 'Edit'} ${editing.number}` : 'New transfer'}
      subtitle="Move stock between warehouses. Costs of moving it are added to its cost at the destination."
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button busy={save.isPending} disabled={!onRoad && errors.length > 0} onClick={() => save.mutate(false, { onSuccess: done })}>
            {editing ? 'Save' : 'Save draft'}
          </Button>
          {!editing ? (
            <Button kind="primary" icon={<Truck size={14} />} busy={save.isPending} disabled={errors.length > 0} onClick={() => save.mutate(true, { onSuccess: done })}>
              Dispatch now
            </Button>
          ) : null}
        </>
      }
      aside={
        <div className="space-y-3 text-[13px]">
          <div className="text-[12px] font-semibold text-fg-2">Summary</div>
          <div className="flex justify-between">
            <span className="text-fg-3">Goods at cost</span>
            <span className="num">{fmtMoney(basis.reduce((s, x) => s + x.value, 0))}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-fg-3">Transfer costs</span>
            <span className="num">{fmtMoney(totalCost)}</span>
          </div>
          {totalCost > 0 && whole > 0 ? (
            <div className="space-y-1.5 border-t border-white/7 pt-2">
              <div className="text-[11.5px] text-fg-3">Added to each unit at {usable.find((w) => w.id === form.to)?.name ?? 'the destination'}</div>
              {basis.map((x) => {
                const share = (totalCost * (missingWeight ? x.qty : x.b)) / whole
                return (
                  <div key={x.line.key} className="flex justify-between gap-2 text-[12px]">
                    <span className="truncate">{x.product?.name}</span>
                    <span className="num shrink-0">
                      +{fmtMoney(x.qty ? share / x.qty : 0)} / {x.product?.unit_of_measure}
                    </span>
                  </div>
                )
              })}
              {missingWeight ? <div className="text-[11px] text-warn">Some products have no weight; spread by quantity instead.</div> : null}
            </div>
          ) : null}
          {errors.length && !onRoad ? <div className="space-y-1 border-t border-white/7 pt-2 text-[12px] text-bad">{errors.map((e) => <div key={e}>{e}</div>)}</div> : null}
        </div>
      }
    >
      <div className="space-y-5">
        {save.error ? <Notice tone="bad">{errorText(save.error)}</Notice> : null}
        <div className="grid grid-cols-[1fr_auto_1fr] items-end gap-3 max-md:grid-cols-1">
          <Field label="From">
            {(props) => (
              <select {...props} className="field" disabled={onRoad} value={form.from} onChange={(e) => setForm((f) => ({ ...f, from: e.target.value }))}>
                {usable.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <ArrowRight size={18} className="mb-2.5 text-fg-3 max-md:hidden" />
          <Field label="To">
            {(props) => (
              <select {...props} className="field" disabled={onRoad} value={form.to} onChange={(e) => setForm((f) => ({ ...f, to: e.target.value }))}>
                <option value="">Choose…</option>
                {usable.filter((w) => w.id !== form.from).map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name}
                  </option>
                ))}
              </select>
            )}
          </Field>
        </div>
        {!onRoad ? (
          <div>
            <div className="label">Products</div>
            <div className="space-y-2">
              {lines.map((line) => {
                const product = products.byId.get(line.product_id)
                const units = unitsOf(product, 'sale')
                const avail = there.get(line.product_id)
                return (
                  <div key={line.key} className="flex flex-wrap items-center gap-2">
                    <div className="min-w-[240px] flex-1">
                      <Picker
                        small
                        value={line.product_id}
                        placeholder="Choose a product…"
                        options={products.items.filter((p) => there.has(p.id) || p.id === line.product_id).map(productOption)}
                        onChange={(v) => setLines(lines.map((l) => (l.key === line.key ? { ...l, product_id: v, unit: '' } : l)))}
                      />
                    </div>
                    <input className="field field-sm field-num w-[90px]" inputMode="decimal" aria-label="Quantity" placeholder="0" value={line.quantity} onChange={(e) => setLines(lines.map((l) => (l.key === line.key ? { ...l, quantity: e.target.value } : l)))} />
                    {units.length > 1 ? (
                      <select className="field field-sm w-[100px]" aria-label="Unit" value={line.unit} onChange={(e) => setLines(lines.map((l) => (l.key === line.key ? { ...l, unit: e.target.value } : l)))}>
                        {units.map((u) => (
                          <option key={u.name} value={u.base ? '' : u.name}>
                            {u.name}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <span className="w-[100px] text-[12.5px] text-fg-3">{product?.unit_of_measure ?? ''}</span>
                    )}
                    <span className="w-[150px] text-[11.5px] text-fg-3">
                      {product ? (
                        <>
                          {fmtQty(avail?.quantity ?? 0)} {product.unit_of_measure} there
                          {line.unit && factorOf(line, product) !== 1 ? ` · = ${fmtQty(baseQty(line, product))}` : ''}
                        </>
                      ) : null}
                    </span>
                    <button className="grid size-7 place-items-center rounded-full text-fg-3 hover:bg-white/8 disabled:opacity-30" disabled={lines.length === 1} aria-label="Remove line" onClick={() => setLines(lines.filter((l) => l.key !== line.key))}>
                      <Trash2 size={13} />
                    </button>
                  </div>
                )
              })}
            </div>
            <Button small className="mt-2" icon={<Plus size={13} />} onClick={() => setLines([...lines, newLine()])}>
              Add product
            </Button>
          </div>
        ) : null}
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <div className="label m-0">Costs of moving the goods</div>
            <div className="ml-auto flex items-center gap-2 text-[12px]">
              Spread
              <Segmented
                className="w-[270px]"
                value={form.method as 'quantity' | 'value' | 'weight'}
                onChange={(v) => setForm((f) => ({ ...f, method: v }))}
                options={[
                  { value: 'quantity', label: 'By quantity' },
                  { value: 'value', label: 'By value' },
                  { value: 'weight', label: 'By weight' },
                ]}
              />
            </div>
          </div>
          <div className="mt-2 space-y-2">
            {costs.map((c, i) => (
              <div key={i} className="flex flex-wrap items-center gap-2">
                <select className="field field-sm w-[140px]" aria-label="Cost kind" value={c.kind} onChange={(e) => setCosts(costs.map((x, j) => (j === i ? { ...x, kind: e.target.value } : x)))}>
                  {COSTS.map(([k, label]) => (
                    <option key={k} value={k}>
                      {label}
                    </option>
                  ))}
                </select>
                <input className="field field-sm field-num w-[120px]" inputMode="decimal" aria-label="Amount" placeholder="₹" value={c.amount} onChange={(e) => setCosts(costs.map((x, j) => (j === i ? { ...x, amount: e.target.value } : x)))} />
                <input className="field field-sm min-w-[160px] flex-1" aria-label="Paid to" placeholder="Paid to (transporter, labour…)" value={c.paid_to} onChange={(e) => setCosts(costs.map((x, j) => (j === i ? { ...x, paid_to: e.target.value } : x)))} />
                <button className="grid size-7 place-items-center rounded-full text-fg-3 hover:bg-white/8" aria-label="Remove cost" onClick={() => setCosts(costs.filter((_, j) => j !== i))}>
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {COSTS.filter(([k]) => k === 'other' || !costs.some((c) => c.kind === k)).map(([k, label]) => (
              <button key={k} onClick={() => setCosts([...costs, { kind: k, amount: '', paid_to: '' }])} className="h-[26px] rounded-full bg-ink-700 px-2.5 text-[11.5px] text-fg-2 hover:text-fg">
                + {label}
              </button>
            ))}
          </div>
        </div>
        <div className="grid grid-cols-4 gap-3 max-md:grid-cols-1">
          <Field label="Vehicle" optional>
            {(props) => <input {...props} className="field" value={form.vehicle} onChange={(e) => setForm((f) => ({ ...f, vehicle: e.target.value }))} placeholder="GJ01AB1234" />}
          </Field>
          <Field label="Transporter" optional>
            {(props) => (
              <select {...props} className="field" value={form.transporter_id} onChange={(e) => {
                const value = e.target.value
                setForm((f) => ({ ...f, transporter_id: value }))
              }}>
                <option value="">Own vehicle / none</option>
                {(transporterOptions.data?.items ?? []).filter((t) => t.is_active).map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label="LR / bilty no." optional>
            {(props) => <input {...props} className="field" value={form.lr} onChange={(e) => {
              const value = e.target.value
              setForm((f) => ({ ...f, lr: value }))
            }} />}
          </Field>
          <Field label="Notes" optional>
            {(props) => <input {...props} className="field" value={form.notes} onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))} />}
          </Field>
        </div>
      </div>
    </Sheet>
  )
}

function WarehouseSheet({ open, editing, onClose, onSaved }: { open: boolean; editing?: Warehouse; onClose: () => void; onSaved: (id: string) => void }) {
  const blank = { name: '', code: '', kind: 'godown', address: '', contact: '', tally_godown: '', notes: '', is_default: false }
  const [form, setForm] = useState(blank)
  useEffect(() => {
    if (open)
      setForm(
        editing
          ? { name: editing.name, code: editing.code, kind: editing.kind, address: editing.address ?? '', contact: editing.contact ?? '', tally_godown: editing.tally_godown ?? '', notes: editing.notes ?? '', is_default: editing.is_default }
          : blank,
      )
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps
  const save = useAction(
    () => {
      const body = { ...form, code: form.code || undefined, address: form.address || null, contact: form.contact || null, tally_godown: form.tally_godown || null, notes: form.notes || null, is_default: form.is_default || undefined }
      return editing ? warehouses.update({ id: editing.id, ...body }) : warehouses.create(body)
    },
    { success: 'Warehouse saved', quiet: true },
  )
  const set = (key: keyof typeof blank) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const value = e.target.value
    setForm((f) => ({ ...f, [key]: value }))
  }
  return (
    <Sheet
      open={open}
      onClose={onClose}
      width={620}
      title={editing ? `Edit ${editing.name}` : 'New warehouse'}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button kind="primary" busy={save.isPending} disabled={!form.name.trim()} onClick={() => save.mutate(undefined, { onSuccess: (w) => (onClose(), onSaved(w.id)) })}>
            Save
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-6 gap-4">
        {save.error ? (
          <div className="col-span-6">
            <Notice tone="bad">{errorText(save.error)}</Notice>
          </div>
        ) : null}
        <Field label="Name" className="col-span-4">
          {(props) => <input {...props} className="field" autoFocus value={form.name} onChange={set('name')} placeholder="e.g. Changodar yard" />}
        </Field>
        <Field label="Code" optional className="col-span-2" hint="Made from the name if empty.">
          {(props) => <input {...props} className="field" value={form.code} onChange={set('code')} placeholder="YARD2" />}
        </Field>
        <div className="col-span-6">
          <div className="label">Kind</div>
          <div className="grid grid-cols-4 gap-2 max-md:grid-cols-2">
            {(['godown', 'yard', 'shop', 'site'] as const).map((k) => {
              const Icon = KIND_ICON[k]
              return (
                <button key={k} type="button" onClick={() => setForm({ ...form, kind: k })} className={cn('flex items-center gap-2 rounded-xl px-3 py-2.5 text-[13px] font-semibold', form.kind === k ? 'brand-fill' : 'bg-ink-700 text-fg-2')}>
                  <Icon size={15} /> {{ godown: 'Godown', yard: 'Yard', shop: 'Shop', site: 'Site store' }[k]}
                </button>
              )
            })}
          </div>
        </div>
        <Field label="Address" optional className="col-span-6">
          {(props) => <input {...props} className="field" value={form.address} onChange={set('address')} />}
        </Field>
        <Field label="In charge" optional className="col-span-3" hint="Name and phone.">
          {(props) => <input {...props} className="field" value={form.contact} onChange={set('contact')} />}
        </Field>
        <Field label="Tally godown" optional className="col-span-3" hint="Its name in Tally, if different.">
          {(props) => <input {...props} className="field" value={form.tally_godown} onChange={set('tally_godown')} />}
        </Field>
        <label className="col-span-6 flex items-center gap-2 text-[13px]">
          <input type="checkbox" checked={form.is_default} disabled={editing?.is_default} onChange={(e) => setForm({ ...form, is_default: e.target.checked })} />
          Default warehouse: used when stock-in, receipts or deliveries don't name one.
        </label>
      </div>
    </Sheet>
  )
}
