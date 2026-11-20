import { useEffect, useMemo, useState } from 'react'
import { WarehouseSelect } from '@/features/stock/WarehouseSelect'
import { ChargeRows, MethodSwitch, chargePayload, useTransporterOptions, type ChargeRow } from './ReceiptExtras'
import { useQuery } from '@tanstack/react-query'
import { PackageCheck } from 'lucide-react'
import { errorText } from '@/api/client'
import { api } from '@/api/endpoints'
import { useAction, useList, useOne } from '@/api/queries'
import type { GoodsReceiptResult, ReceiptPreviewLine } from '@/api/types'
import { fmtDate, fmtMoney, fmtQty, isQty, n } from '@/lib/format'
import { useDebounced } from '@/lib/route'
import { PurchaseBadge } from '@/lib/status'
import { AllocationEditor, useAllocation, type Claimant } from '@/ui/allocate'
import { Button, Facts, Field, Notice, Spinner, Toggle } from '@/ui/core'
import { Sheet } from '@/ui/overlays'
import { Picker } from '@/ui/pickers'
import { useProducts } from '@/ui/lines'

interface Entry {
  quantity: string
  cost: string
  reason: string
  batch?: string
  made?: string
  expires?: string
}

/** Book in a supplier's delivery against a purchase order. */
export function ReceiveSheet({ open, onClose, poId: initialPo, focusItem, onDone }: { open: boolean; onClose: () => void; poId?: string; focusItem?: string; onDone?: (result: GoodsReceiptResult) => void }) {
  const receivable = useList('purchase-orders', api.purchaseOrders.list, { status: 'ORDERED,PARTIALLY_RECEIVED', limit: 200 }, open)
  const [poId, setPoId] = useState('')
  const po = useOne('purchase-orders', api.purchaseOrders.get, open && poId ? poId : undefined)
  const [entries, setEntries] = useState<Record<string, Entry>>({})
  const productList = useProducts()
  const tracked = new Set(productList.items.filter((p) => p.track_batches).map((p) => p.id))
  const [note, setNote] = useState('')
  const [transport, setTransport] = useState({ transporter_id: '', vehicle_number: '', lr_number: '' })
  const [charges, setCharges] = useState<ChargeRow[]>([])
  const [method, setMethod] = useState<'quantity' | 'value' | 'weight'>('quantity')
  const transporters = useTransporterOptions()
  const [deliveryNote, setDeliveryNote] = useState('')
  const [warehouse, setWarehouse] = useState('')
  const [allowOver, setAllowOver] = useState(false)
  const [key, setKey] = useState(() => crypto.randomUUID())
  const [plans, setPlans] = useState<Record<string, { balanced: boolean; allocations: { order_item_id: string; quantity: string }[] }>>({})
  const receive = useAction(api.goodsReceipts.create, { success: (result) => `${result.receipt_number} · ${fmtQty(result.total_received)} booked in`, quiet: true })

  useEffect(() => {
    if (!open) return
    setPoId(initialPo ?? '')
    setNote('')
    setDeliveryNote('')
    setAllowOver(false)
    setTransport({ transporter_id: '', vehicle_number: '', lr_number: '' })
    setCharges([])
    setMethod('quantity')
    setPlans({})
    setKey(crypto.randomUUID())
    receive.reset()
  }, [open, initialPo]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!po.data) return
    setEntries(
      Object.fromEntries(
        po.data.items.map((item) => [item.id, { quantity: focusItem === item.id ? String(n(item.quantity_remaining)) : '', cost: String(n(item.unit_cost)), reason: '' }]),
      ),
    )
    setPlans({})
  }, [po.data?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const typed = (po.data?.items ?? []).filter((item) => isQty(entries[item.id]?.quantity ?? '') && n(entries[item.id]?.quantity) > 0)
  const requestLines = typed.map((item) => ({
    purchase_order_item_id: item.id,
    quantity: entries[item.id].quantity,
    unit_cost: entries[item.id].cost || null,
    over_receipt_reason: entries[item.id].reason || null,
    batch_number: entries[item.id].batch || null,
    manufactured_on: entries[item.id].made || null,
    expires_on: entries[item.id].expires || null,
    allocations: null,
  }))
  const debounced = useDebounced(JSON.stringify(requestLines), 300)
  const preview = useQuery({
    queryKey: ['receipt-preview', poId, debounced, allowOver],
    enabled: open && Boolean(poId) && requestLines.length > 0 && debounced !== '[]',
    queryFn: () => api.goodsReceipts.preview({ purchase_order_id: poId, lines: JSON.parse(debounced), allow_over_receipt: allowOver }),
    retry: false,
  })
  const previewLines = preview.data?.lines ?? []
  const needs = previewLines.filter((line) => n(line.required_allocation) > 0)
  const overLines = previewLines.filter((line) => line.is_over_receipt)
  const ready = requestLines.length > 0 && !preview.isFetching && !preview.error && needs.every((line) => plans[line.purchase_order_item_id]?.balanced) && overLines.every((line) => entries[line.purchase_order_item_id]?.reason.trim())

  function submit() {
    receive.mutate(
      {
        purchase_order_id: poId,
        lines: requestLines.map((line) => ({ ...line, allocations: plans[line.purchase_order_item_id]?.allocations ?? null })),
        delivery_note_reference: deliveryNote || null,
        warehouse_id: warehouse || null,
        transporter_id: transport.transporter_id || null,
        vehicle_number: transport.vehicle_number || null,
        lr_number: transport.lr_number || null,
        costs: chargePayload(charges),
        cost_method: method,
        notes: note || null,
        idempotency_key: key,
        allow_over_receipt: allowOver,
      },
      {
        onSuccess: (result) => {
          onClose()
          onDone?.(result)
        },
      },
    )
  }

  const options = (receivable.data?.items ?? []).filter((row) => row.can_receive).map((row) => ({ value: row.id, label: `${row.po_number} · ${row.supplier.name}`, detail: `${fmtQty(row.total_remaining)} still to come${row.expected_delivery_date ? ` · expected ${fmtDate(row.expected_delivery_date)}` : ''}` }))

  return (
    <Sheet
      open={open}
      onClose={onClose}
      width={1040}
      title={po.data ? `Receive against ${po.data.po_number}` : 'Receive goods'}
      subtitle={po.data ? `${po.data.supplier.name}. Stock does not change; it counted when the order was placed. Waiting customers get theirs first.` : 'Choose the purchase order this delivery is for.'}
      aside={
        <div className="space-y-5">
          <div>
            <div className="eyebrow mb-2">This delivery</div>
            <Facts
              items={[
                { label: 'Arriving', value: fmtQty(preview.data?.total_receiving ?? requestLines.reduce((sum, line) => sum + n(line.quantity), 0)) },
                { label: 'To waiting customers', value: fmtQty(preview.data?.total_required_allocation ?? 0) },
                { label: 'Into free stock', value: fmtQty(preview.data?.total_surplus ?? 0) },
                { label: 'Cost', value: fmtMoney(preview.data?.total_cost ?? 0), strong: true },
              ]}
            />
          </div>
          {po.data ? (
            <div className="text-[12px] text-fg-3">
              <PurchaseBadge status={po.data.status} /> <span className="ml-1">{fmtQty(po.data.total_remaining)} of {fmtQty(po.data.total_ordered)} still due</span>
            </div>
          ) : null}
        </div>
      }
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button kind="primary" icon={<PackageCheck size={15} />} busy={receive.isPending} disabled={!ready} onClick={submit}>
            Book in
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        {receive.error ? <Notice tone="bad">{errorText(receive.error)}</Notice> : null}
        <Field label="Purchase order">
          {(props) => <Picker {...props} value={poId} onChange={setPoId} options={options} placeholder="Choose a purchase order awaiting delivery…" emptyText="No purchase order is awaiting delivery." />}
        </Field>
        {poId && po.isPending ? <Spinner /> : null}
        {po.data ? (
          <>
            <div className="overflow-hidden rounded-xl bg-ink-900 ring-1 ring-white/7 ring-inset">
              <table className="grid-table">
                <thead>
                  <tr>
                    <th>Product</th>
                    <th className="r">Ordered</th>
                    <th className="r">Received</th>
                    <th className="r">Due</th>
                    <th className="r w-[110px]">Arrived now</th>
                    <th className="r w-[110px]">Cost / unit</th>
                  </tr>
                </thead>
                <tbody>
                  {po.data.items.map((item) => {
                    const entry = entries[item.id] ?? { quantity: '', cost: '', reason: '' }
                    const bad = entry.quantity !== '' && !isQty(entry.quantity)
                    const over = n(entry.quantity) > n(item.quantity_remaining)
                    return (
                      <tr key={item.id}>
                        <td>
                          <div className="text-[13px] font-medium">{item.product.name}</div>
                          <div className="text-[11.5px] text-fg-3">
                            {item.product.sku} · {item.product.unit_of_measure}
                          </div>
                          {tracked.has(item.product_id) ? (
                            <div className="mt-1.5 flex flex-wrap gap-1.5">
                              <input className="field field-sm w-[120px]" placeholder="Batch no." aria-label={`Batch of ${item.product.name}`} value={entry.batch ?? ''}
                                onChange={(event) => {
                                  const value = event.target.value
                                  setEntries((all) => ({ ...all, [item.id]: { ...(all[item.id] ?? entry), batch: value } }))
                                }} />
                              <input type="date" className="field field-sm w-[140px]" title="Made on" aria-label="Made on" value={entry.made ?? ''}
                                onChange={(event) => {
                                  const value = event.target.value
                                  setEntries((all) => ({ ...all, [item.id]: { ...(all[item.id] ?? entry), made: value } }))
                                }} />
                              <input type="date" className="field field-sm w-[140px]" title="Expires on (from shelf life if empty)" aria-label="Expires on" value={entry.expires ?? ''}
                                onChange={(event) => {
                                  const value = event.target.value
                                  setEntries((all) => ({ ...all, [item.id]: { ...(all[item.id] ?? entry), expires: value } }))
                                }} />
                            </div>
                          ) : null}
                          {over && allowOver ? (
                            <input className="field field-sm mt-1.5" placeholder="Why more than ordered? (required)" value={entry.reason} onChange={(event) => setEntries({ ...entries, [item.id]: { ...entry, reason: event.target.value } })} />
                          ) : null}
                        </td>
                        <td className="r num">{fmtQty(item.quantity_ordered)}</td>
                        <td className="r num text-fg-3">{fmtQty(item.quantity_received)}</td>
                        <td className="r num font-semibold">{fmtQty(item.quantity_remaining)}</td>
                        <td className="r">
                          <input className="field field-sm field-num" inputMode="decimal" placeholder="0" aria-invalid={bad || (over && !allowOver) || undefined} value={entry.quantity} onChange={(event) => setEntries({ ...entries, [item.id]: { ...entry, quantity: event.target.value } })} />
                        </td>
                        <td className="r">
                          <input className="field field-sm field-num" inputMode="decimal" value={entry.cost} onChange={(event) => setEntries({ ...entries, [item.id]: { ...entry, cost: event.target.value } })} />
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              <label className="flex items-center gap-3 border-t border-white/6 px-[18px] py-3 text-[12.5px] text-fg-2">
                <Toggle checked={allowOver} onChange={setAllowOver} label="Allow more than ordered" />
                Allow receiving more than the order still owes (each extra line needs a reason)
              </label>
            </div>
            {preview.error ? <Notice tone="bad">{errorText(preview.error)}</Notice> : null}
            {needs.map((line) => (
              <LinePlan key={line.purchase_order_item_id + line.required_allocation} line={line} onState={(state) => setPlans((current) => ({ ...current, [line.purchase_order_item_id]: state }))} />
            ))}
            {previewLines.length > 0 && needs.length === 0 && !preview.isFetching ? <Notice tone="sky">Nobody is waiting for these products, so everything goes into free stock.</Notice> : null}
            <WarehouseSelect value={warehouse} onChange={setWarehouse} label="Put into" hint="Where the goods are unloaded." />
            <div className="grid grid-cols-3 gap-3 max-md:grid-cols-1">
              <Field label="Transporter" optional>
                {(props) => (
                  <select {...props} className="field" value={transport.transporter_id} onChange={(e) => {
                    const value = e.target.value
                    setTransport((t) => ({ ...t, transporter_id: value }))
                  }}>
                    <option value="">Supplier delivered / none</option>
                    {(transporters.data?.items ?? []).filter((t) => t.is_active).map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.name}
                      </option>
                    ))}
                  </select>
                )}
              </Field>
              <Field label="Vehicle" optional>
                {(props) => <input {...props} className="field" placeholder="GJ01AB1234" value={transport.vehicle_number} onChange={(e) => {
                  const value = e.target.value
                  setTransport((t) => ({ ...t, vehicle_number: value }))
                }} />}
              </Field>
              <Field label="LR / bilty no." optional>
                {(props) => <input {...props} className="field" value={transport.lr_number} onChange={(e) => {
                  const value = e.target.value
                  setTransport((t) => ({ ...t, lr_number: value }))
                }} />}
              </Field>
            </div>
            <div className="card space-y-3 p-4">
              <div className="flex flex-wrap items-center gap-3">
                <div className="min-w-[200px] flex-1">
                  <div className="text-[13.5px] font-semibold">Freight and other charges</div>
                  <div className="text-[11.5px] text-fg-3">Added to the goods' cost (landed cost). Can also be added later when the bill comes.</div>
                </div>
                {charges.length ? <MethodSwitch value={method} onChange={setMethod} /> : null}
              </div>
              <ChargeRows rows={charges} setRows={setCharges} defaultTransporter={transport.transporter_id || undefined} />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Supplier's delivery note" optional>
                {(props) => <input {...props} className="field" placeholder="DN-4471" value={deliveryNote} onChange={(event) => setDeliveryNote(event.target.value)} />}
              </Field>
              <Field label="Note" optional>
                {(props) => <input {...props} className="field" placeholder="Condition on arrival, driver…" value={note} onChange={(event) => setNote(event.target.value)} />}
              </Field>
            </div>
          </>
        ) : null}
      </div>
    </Sheet>
  )
}

function LinePlan({ line, onState }: { line: ReceiptPreviewLine; onState: (state: { balanced: boolean; allocations: { order_item_id: string; quantity: string }[] }) => void }) {
  const claimants: Claimant[] = useMemo(
    () => line.allocations.filter((row) => n(row.quantity_eligible) > 0).map((row) => ({ id: row.order_item_id, name: row.customer_name, reference: row.order_number, date: row.order_created_at, capacity: n(row.quantity_eligible), proposed: n(row.proposed_allocation) })),
    [line],
  )
  const required = n(line.required_allocation)
  const state = useAllocation(claimants, required)
  const signature = JSON.stringify(state.allocations) + state.balanced
  useEffect(() => onState({ balanced: state.balanced, allocations: state.allocations }), [signature]) // eslint-disable-line react-hooks/exhaustive-deps
  return <AllocationEditor claimants={claimants} required={required} unit={line.unit_of_measure} state={state} title={`Who gets the ${line.product_name}`} />
}
