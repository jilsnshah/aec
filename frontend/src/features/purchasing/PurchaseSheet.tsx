import { useEffect, useMemo, useState } from 'react'
import { useContractRates } from '@/features/contracts/ContractBadge'
import { Send } from 'lucide-react'
import { errorText } from '@/api/client'
import { api } from '@/api/endpoints'
import { useAction, useCommitments } from '@/api/queries'
import type { CommitmentRow, PurchaseOrderOut } from '@/api/types'
import { fmtMoney, fmtQty, n } from '@/lib/format'
import { AllocationEditor, useAllocation, type Claimant } from '@/ui/allocate'
import { Button, Facts, Field, Notice } from '@/ui/core'
import { LineEditor, baseQty, lineErrors, lineUnit, newLine, unitParam, useProducts, useSuppliers, type Line } from '@/ui/lines'
import { Sheet } from '@/ui/overlays'
import { Picker } from '@/ui/pickers'

export interface SettlementState {
  balanced: boolean
  allocations: { order_item_id: string; quantity: string }[]
}

export const claimantsFrom = (rows: CommitmentRow[]): Claimant[] =>
  rows
    .filter((row) => n(row.quantity_unallocated) > 0)
    .map((row) => ({ id: row.order_item_id, name: row.customer_name, reference: row.order_number, date: row.order_created_at, capacity: n(row.quantity_unallocated) }))

/** One product's settlement: which short customers this purchase covers. */
export function SettleBlock({ productName, unit, claimants, required, onState, prefer }: { productName: string; unit: string; claimants: Claimant[]; required: number; onState: (state: SettlementState) => void; prefer?: string }) {
  const state = useAllocation(claimants, required, prefer)
  const key = JSON.stringify(state.allocations) + state.balanced
  useEffect(() => onState({ balanced: state.balanced, allocations: state.allocations }), [key]) // eslint-disable-line react-hooks/exhaustive-deps
  return <AllocationEditor claimants={claimants} required={required} unit={unit} state={state} title={`Settle short customers · ${productName}`} />
}

/** A purchase order: lines from one supplier. Placing it must settle the
 *  customers who are short of its products — the user chooses who. */
export function PurchaseSheet({
  open,
  onClose,
  onSaved,
  editing,
  initial,
  subtitle,
}: {
  open: boolean
  onClose: () => void
  onSaved?: (po: PurchaseOrderOut) => void
  editing?: PurchaseOrderOut
  initial?: { supplier_id?: string; lines?: Partial<Line>[]; prefer?: string }
  subtitle?: string
}) {
  const suppliers = useSuppliers()
  const products = useProducts()
  const short = useCommitments({ only_unallocated: true })
  const [supplier, setSupplier] = useState('')
  const contractRates = useContractRates(supplier || undefined)
  const [lines, setLines] = useState<Line[]>([newLine()])
  const [expected, setExpected] = useState('')
  const [notes, setNotes] = useState('')
  const [tried, setTried] = useState(false)
  const [settlements, setSettlements] = useState<Record<string, SettlementState>>({})

  const create = useAction(api.purchaseOrders.create, { success: (po) => `${po.po_number} ${po.status === 'DRAFT' ? 'saved as draft' : 'placed'}`, quiet: true })
  const update = useAction((body: Parameters<typeof api.purchaseOrders.update>[1]) => api.purchaseOrders.update(editing!.id, body), { success: 'Purchase order saved', quiet: true })
  const error = create.error ?? update.error

  useEffect(() => {
    if (!open) return
    if (editing) {
      setSupplier(editing.supplier_id)
      setLines(editing.items.map((item) => newLine({ product_id: item.product_id, unit: lineUnit(item), quantity: String(n(item.unit_quantity ?? item.quantity_ordered)), cost: String(n(item.unit_rate ?? item.unit_cost)) })))
      setExpected(editing.expected_delivery_date ?? '')
      setNotes(editing.notes ?? '')
    } else {
      setSupplier(initial?.supplier_id ?? '')
      setLines(initial?.lines?.length ? initial.lines.map((line) => newLine(line)) : [newLine()])
      setExpected('')
      setNotes('')
    }
    setTried(false)
    setSettlements({})
    create.reset()
    update.reset()
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  // Fill a blank cost from the product's last price once products load.
  useEffect(() => {
    if (!open || products.items.length === 0) return
    setLines((current) => current.map((line) => (line.product_id && !line.cost ? { ...line, cost: String(n(products.byId.get(line.product_id)?.last_purchase_price ?? products.byId.get(line.product_id)?.average_cost) || '') } : line)))
  }, [open, products.items.length]) // eslint-disable-line react-hooks/exhaustive-deps

  const chosen = lines.filter((line) => line.product_id)
  const total = chosen.reduce((sum, line) => sum + n(line.quantity) * n(line.cost), 0)

  /** Per product: how much this purchase must settle, and who could get it. */
  const needs = useMemo(() => {
    const byProduct = new Map<string, number>()
    chosen.forEach((line) => byProduct.set(line.product_id, (byProduct.get(line.product_id) ?? 0) + baseQty(line, products.byId.get(line.product_id))))
    return [...byProduct.entries()]
      .map(([productId, quantity]) => {
        const claimants = claimantsFrom((short.data?.rows ?? []).filter((row) => row.product_id === productId))
        const shortTotal = claimants.reduce((sum, claimant) => sum + claimant.capacity, 0)
        const product = products.byId.get(productId)
        return { productId, name: product?.name ?? '', unit: product?.unit_of_measure ?? '', claimants, required: Math.min(quantity, shortTotal) }
      })
      .filter((need) => need.required > 0)
  }, [JSON.stringify(chosen.map((line) => [line.product_id, line.quantity, line.unit])), short.data, products.items.length]) // eslint-disable-line react-hooks/exhaustive-deps

  const allSettled = needs.every((need) => settlements[need.productId]?.balanced)
  const errors = [...(supplier ? [] : ['Choose a supplier.']), ...lineErrors(lines, 'purchase', products.byId)]
  const body = () => ({
    supplier_id: supplier,
    items: chosen.map((line) => ({ product_id: line.product_id, quantity_ordered: line.quantity, unit: unitParam(line), unit_cost: line.cost, notes: null })),
    expected_delivery_date: expected || null,
    notes: notes || null,
  })

  function save(place: boolean) {
    setTried(true)
    if (errors.length > 0 || (place && !allSettled)) return
    const settle = place ? needs.map((need) => ({ product_id: need.productId, allocations: settlements[need.productId].allocations })) : null
    const done = (po: PurchaseOrderOut) => {
      onClose()
      onSaved?.(po)
    }
    if (editing) {
      update.mutate({ items: body().items, expected_delivery_date: body().expected_delivery_date, notes: body().notes }, { onSuccess: done })
    } else {
      create.mutate({ ...body(), confirm: place, settlements: settle }, { onSuccess: done })
    }
  }

  return (
    <Sheet
      open={open}
      onClose={onClose}
      width={1040}
      title={editing ? `Edit ${editing.po_number}` : 'New purchase order'}
      subtitle={subtitle ?? 'Stock rises the moment it is placed. Customers who are short of these products must be settled from it.'}
      aside={
        <div className="space-y-5">
          <div>
            <div className="eyebrow mb-2">Purchase</div>
            <Facts
              items={[
                { label: 'Lines', value: chosen.length },
                { label: 'Units', value: fmtQty(chosen.reduce((sum, line) => sum + baseQty(line, products.byId.get(line.product_id)), 0)) },
                { label: 'Value', value: fmtMoney(total), strong: true },
              ]}
            />
          </div>
          {needs.length > 0 ? (
            <div>
              <div className="eyebrow mb-2">Settles</div>
              {needs.map((need) => (
                <div key={need.productId} className="flex items-center justify-between py-1.5 text-[12.5px]">
                  <span className="truncate text-fg-2">{need.name}</span>
                  <span className={settlements[need.productId]?.balanced ? 'num text-ok' : 'num text-sky'}>{fmtQty(need.required)}</span>
                </div>
              ))}
            </div>
          ) : chosen.length > 0 ? (
            <p className="text-[12px] text-fg-3">No customer is short of these products, so everything goes into free stock.</p>
          ) : null}
        </div>
      }
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          {editing ? (
            <Button kind="primary" busy={update.isPending} onClick={() => save(false)}>
              Save changes
            </Button>
          ) : (
            <>
              <Button busy={create.isPending && !create.variables?.confirm} onClick={() => save(false)}>
                Save draft
              </Button>
              <Button kind="primary" icon={<Send size={14} />} busy={create.isPending && create.variables?.confirm} disabled={tried && (!allSettled || errors.length > 0)} onClick={() => save(true)}>
                Place order
              </Button>
            </>
          )}
        </>
      }
    >
      <div className="space-y-5">
        {error ? <Notice tone="bad">{errorText(error)}</Notice> : null}
        {tried && errors.length > 0 ? <Notice tone="bad">{errors.join('\n')}</Notice> : null}
        {tried && !allSettled && !editing ? <Notice tone="warn">Finish settling the short customers before placing the order.</Notice> : null}
        <div className="grid grid-cols-[minmax(0,1fr)_200px] gap-4">
          <Field label="Supplier">
            {(props) => (
              <Picker {...props} value={supplier} onChange={setSupplier} disabled={Boolean(editing)} invalid={tried && !supplier} placeholder="Choose a supplier…" options={suppliers.map((row) => ({ value: row.id, label: row.name, detail: row.code }))} />
            )}
          </Field>
          <Field label="Expected delivery" optional>
            {(props) => <input {...props} type="date" className="field" value={expected} onChange={(event) => setExpected(event.target.value)} />}
          </Field>
        </div>
        <div>
          <div className="label">Products</div>
          <LineEditor lines={lines} onChange={setLines} mode="purchase" contractRates={contractRates} />
        </div>
        {!editing
          ? needs.map((need) => (
              <SettleBlock key={need.productId + need.required} productName={need.name} unit={need.unit} claimants={need.claimants} required={need.required} prefer={initial?.prefer} onState={(state) => setSettlements((current) => ({ ...current, [need.productId]: state }))} />
            ))
          : null}
        <Field label="Notes" optional>
          {(props) => <textarea {...props} className="field" placeholder="Delivery instructions, agreed terms…" value={notes} onChange={(event) => setNotes(event.target.value)} />}
        </Field>
      </div>
    </Sheet>
  )
}
