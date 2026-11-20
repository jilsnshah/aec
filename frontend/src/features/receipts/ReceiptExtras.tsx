import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { RotateCcw, Trash2, Truck } from 'lucide-react'
import { errorText, http } from '@/api/client'
import { useAction } from '@/api/queries'
import { cn } from '@/lib/cn'
import { fmtDateTime, fmtMoney, fmtQty, n } from '@/lib/format'
import { Badge, Button, Field, Notice } from '@/ui/core'
import { Segmented, Sheet } from '@/ui/overlays'
import { Section } from '@/ui/split'

type Method = 'quantity' | 'value' | 'weight'
interface LandedCost {
  id: string
  number: string
  method: Method
  total: number
  on_stock: number
  on_sold: number
  note: string | null
  created_at: string
  charges: { id: string; kind: string; label: string; amount: number; transporter: string | null; paid_to: string | null; bill_number: string | null }[]
  lines: { product_id: string; product: string; unit: string; quantity: number; amount: number; per_unit: number; on_stock: number; on_sold: number }[]
}
interface PurchaseReturn {
  id: string
  number: string
  reason_label: string
  note: string | null
  replace: boolean
  amount: number
  stock_value: number
  created_at: string
  goods_receipt_id: string | null
  items: { product_id: string; product: string; unit: string; quantity: number; unit_cost: number; amount: number }[]
}
interface Returnable {
  goods_receipt_item_id: string
  product_id: string
  product: string
  unit: string
  received: number
  returned: number
  returnable: number
  unit_cost: number
}

export const CHARGE_KINDS: [string, string][] = [
  ['freight', 'Freight'],
  ['unloading', 'Unloading'],
  ['loading', 'Loading'],
  ['insurance', 'Insurance'],
  ['octroi', 'Octroi / entry tax'],
  ['commission', 'Commission'],
  ['other', 'Other'],
]
const REASONS: [string, string][] = [
  ['damaged', 'Damaged'],
  ['quality', 'Quality not as agreed'],
  ['wrong_item', 'Wrong item or grade'],
  ['excess', 'Excess supplied'],
  ['expired', 'Expired or short-dated'],
  ['other', 'Other'],
]

/** Active transporters, for a select. */
export function useTransporterOptions() {
  return useQuery({ queryKey: ['transporters', 'options'], queryFn: () => http.get<{ items: { id: string; name: string; is_active: boolean }[] }>('/api/transporters') })
}

export type ChargeRow = { kind: string; amount: string; transporter_id: string; paid_to: string; bill_number: string }
export const newCharge = (kind = 'freight'): ChargeRow => ({ kind, amount: '', transporter_id: '', paid_to: '', bill_number: '' })

/** Freight, unloading and other charges: rows with who is owed. */
export function ChargeRows({ rows, setRows, defaultTransporter }: { rows: ChargeRow[]; setRows: (update: (rows: ChargeRow[]) => ChargeRow[]) => void; defaultTransporter?: string }) {
  const transporters = useTransporterOptions()
  return (
    <div className="space-y-2">
      {rows.map((row, i) => (
        <div key={i} className="flex flex-wrap items-center gap-2">
          <select className="field field-sm w-[150px]" aria-label="Charge" value={row.kind} onChange={(e) => setRows((r) => r.map((x, j) => (j === i ? { ...x, kind: e.target.value } : x)))}>
            {CHARGE_KINDS.map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </select>
          <input className="field field-sm field-num w-[110px]" inputMode="decimal" placeholder="₹" aria-label="Amount" value={row.amount} onChange={(e) => setRows((r) => r.map((x, j) => (j === i ? { ...x, amount: e.target.value } : x)))} />
          <select className="field field-sm min-w-[170px] flex-1" aria-label="Owed to" value={row.transporter_id} onChange={(e) => setRows((r) => r.map((x, j) => (j === i ? { ...x, transporter_id: e.target.value } : x)))}>
            <option value="">{defaultTransporter && row.kind === 'freight' ? 'The receipt’s transporter' : 'Not a transporter'}</option>
            {(transporters.data?.items ?? []).filter((t) => t.is_active).map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
          {!row.transporter_id ? (
            <input className="field field-sm w-[130px]" placeholder="Paid to" aria-label="Paid to" value={row.paid_to} onChange={(e) => setRows((r) => r.map((x, j) => (j === i ? { ...x, paid_to: e.target.value } : x)))} />
          ) : null}
          <input className="field field-sm w-[110px]" placeholder="Bill no." aria-label="Bill number" value={row.bill_number} onChange={(e) => setRows((r) => r.map((x, j) => (j === i ? { ...x, bill_number: e.target.value } : x)))} />
          <button className="grid size-7 place-items-center rounded-full text-fg-3 hover:bg-white/8" aria-label="Remove charge" onClick={() => setRows((r) => r.filter((_, j) => j !== i))}>
            <Trash2 size={13} />
          </button>
        </div>
      ))}
      <div className="flex flex-wrap gap-1.5">
        {CHARGE_KINDS.filter(([k]) => k === 'other' || !rows.some((r) => r.kind === k)).map(([k, label]) => (
          <button key={k} type="button" onClick={() => setRows((r) => [...r, newCharge(k)])} className="h-[26px] rounded-full bg-ink-700 px-2.5 text-[11.5px] text-fg-2 hover:text-fg">
            + {label}
          </button>
        ))}
      </div>
    </div>
  )
}

export const chargePayload = (rows: ChargeRow[]) =>
  rows.filter((r) => n(r.amount) > 0).map((r) => ({ kind: r.kind, amount: r.amount, transporter_id: r.transporter_id || null, paid_to: r.paid_to || null, bill_number: r.bill_number || null }))

export function MethodSwitch({ value, onChange }: { value: Method; onChange: (value: Method) => void }) {
  return (
    <Segmented
      className="w-[270px]"
      value={value}
      onChange={onChange}
      options={[
        { value: 'quantity', label: 'By quantity' },
        { value: 'value', label: 'By value' },
        { value: 'weight', label: 'By weight' },
      ]}
    />
  )
}

/** Add charges to a receipt after the fact (the transporter's bill came in). */
export function LandedCostSheet({ open, onClose, receiptId, receiptNumber }: { open: boolean; onClose: () => void; receiptId: string; receiptNumber: string }) {
  const [rows, setRows] = useState<ChargeRow[]>([newCharge()])
  const [method, setMethod] = useState<Method>('quantity')
  const [note, setNote] = useState('')
  useEffect(() => {
    if (open) (setRows([newCharge()]), setMethod('quantity'), setNote(''))
  }, [open])
  const save = useAction(() => http.post(`/api/goods-receipts/${receiptId}/landed-costs`, { charges: chargePayload(rows), method, note: note || null }), { success: 'Charges added to the cost', quiet: true })
  const total = rows.reduce((s, r) => s + n(r.amount), 0)
  return (
    <Sheet
      open={open}
      onClose={onClose}
      width={760}
      title={`Freight and charges on ${receiptNumber}`}
      subtitle="Spread over the goods and added to their cost. Units already sold are reported separately."
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button kind="primary" busy={save.isPending} disabled={total <= 0} onClick={() => save.mutate(undefined, { onSuccess: onClose })}>
            Add {fmtMoney(total)}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {save.error ? <Notice tone="bad">{errorText(save.error)}</Notice> : null}
        <ChargeRows rows={rows} setRows={setRows} />
        <div className="flex flex-wrap items-center gap-3 text-[12.5px]">
          Spread <MethodSwitch value={method} onChange={setMethod} />
        </div>
        <Field label="Note" optional>
          {(props) => <input {...props} className="field" value={note} onChange={(e) => setNote(e.target.value)} />}
        </Field>
      </div>
    </Sheet>
  )
}

/** Send goods back to the supplier. */
export function PurchaseReturnSheet({ open, onClose, receiptId, receiptNumber }: { open: boolean; onClose: () => void; receiptId: string; receiptNumber: string }) {
  const lines = useQuery({ queryKey: ['returnable', receiptId], queryFn: () => http.get<{ lines: Returnable[] }>(`/api/goods-receipts/${receiptId}/returnable`), enabled: open })
  const [qty, setQty] = useState<Record<string, string>>({})
  const [reason, setReason] = useState('damaged')
  const [note, setNote] = useState('')
  const [replace, setReplace] = useState(false)
  useEffect(() => {
    if (open) (setQty({}), setReason('damaged'), setNote(''), setReplace(false))
  }, [open])
  const rows = lines.data?.lines ?? []
  const chosen = rows.filter((r) => n(qty[r.goods_receipt_item_id]) > 0)
  const total = chosen.reduce((s, r) => s + n(qty[r.goods_receipt_item_id]) * r.unit_cost, 0)
  const over = chosen.filter((r) => n(qty[r.goods_receipt_item_id]) > r.returnable)
  const save = useAction(
    () => http.post('/api/purchase-returns', { goods_receipt_id: receiptId, reason, note: note || null, replace, lines: chosen.map((r) => ({ goods_receipt_item_id: r.goods_receipt_item_id, quantity: qty[r.goods_receipt_item_id] })) }),
    { success: 'Returned; debit note raised', quiet: true },
  )
  return (
    <Sheet
      open={open}
      onClose={onClose}
      width={720}
      title={`Return goods from ${receiptNumber}`}
      subtitle="The goods leave stock at the cost they came in, and a debit note is raised for what the supplier billed."
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button kind="primary" icon={<RotateCcw size={14} />} busy={save.isPending} disabled={!chosen.length || over.length > 0} onClick={() => save.mutate(undefined, { onSuccess: onClose })}>
            Return · debit {fmtMoney(total)}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {save.error ? <Notice tone="bad">{errorText(save.error)}</Notice> : null}
        <div className="overflow-x-auto">
          <table className="grid-table min-w-[560px]">
            <thead>
              <tr>
                <th>Product</th>
                <th className="r">Received</th>
                <th className="r">Returned</th>
                <th className="r">Price</th>
                <th className="r w-[120px]">Send back</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.goods_receipt_item_id}>
                  <td className="text-[13px] font-medium">{r.product}</td>
                  <td className="r num">
                    {fmtQty(r.received)} <span className="text-[11px] text-fg-3">{r.unit}</span>
                  </td>
                  <td className="r num">{r.returned ? fmtQty(r.returned) : '—'}</td>
                  <td className="r num">{fmtMoney(r.unit_cost)}</td>
                  <td className="r">
                    <input
                      className={cn('field field-sm field-num w-[100px]', n(qty[r.goods_receipt_item_id]) > r.returnable && 'ring-1 ring-bad')}
                      inputMode="decimal"
                      placeholder="0"
                      aria-label={`Return ${r.product}`}
                      disabled={r.returnable <= 0}
                      value={qty[r.goods_receipt_item_id] ?? ''}
                      onChange={(e) => {
                        const value = e.target.value
                        setQty((q) => ({ ...q, [r.goods_receipt_item_id]: value }))
                      }}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {over.length ? <Notice tone="bad">More than what can still go back on {over.map((r) => r.product).join(', ')}.</Notice> : null}
        <div className="grid grid-cols-2 gap-3 max-md:grid-cols-1">
          <Field label="Reason">
            {(props) => (
              <select {...props} className="field" value={reason} onChange={(e) => setReason(e.target.value)}>
                {REASONS.map(([k, label]) => (
                  <option key={k} value={k}>
                    {label}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label="Note" optional>
            {(props) => <input {...props} className="field" value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. 8 bags torn, photos on WhatsApp" />}
          </Field>
        </div>
        <label className="flex items-center gap-2 text-[13px]">
          <input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} />
          The supplier will send these again (the purchase order is owed them once more)
        </label>
      </div>
    </Sheet>
  )
}

/** Charges and returns recorded on a receipt. */
export function ReceiptCostsAndReturns({ receiptId, purchaseOrderId }: { receiptId: string; purchaseOrderId: string }) {
  const landed = useQuery({ queryKey: ['landed-costs', receiptId], queryFn: () => http.get<{ items: LandedCost[] }>(`/api/goods-receipts/${receiptId}/landed-costs`) })
  const returns = useQuery({ queryKey: ['purchase-returns', purchaseOrderId], queryFn: () => http.get<{ items: PurchaseReturn[] }>('/api/purchase-returns', { purchase_order_id: purchaseOrderId }) })
  const mine = (returns.data?.items ?? []).filter((r) => r.goods_receipt_id === receiptId)
  return (
    <>
      {landed.data?.items.length ? (
        <Section title="Freight and charges" hint="Added to the goods' cost">
          <div className="space-y-3">
            {landed.data.items.map((lc) => (
              <div key={lc.id} className="card p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <Truck size={14} />
                  <span className="text-[13.5px] font-semibold">{lc.number}</span>
                  <span className="text-[12px] text-fg-3">{fmtDateTime(lc.created_at)} · by {lc.method}</span>
                  <span className="num ml-auto text-[14px] font-semibold">{fmtMoney(lc.total)}</span>
                </div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {lc.charges.map((c) => (
                    <Badge key={c.id}>
                      {c.label} {fmtMoney(c.amount)}
                      {c.transporter ? ` · ${c.transporter}` : c.paid_to ? ` · ${c.paid_to}` : ''}
                    </Badge>
                  ))}
                </div>
                <div className="mt-2 overflow-x-auto">
                  <table className="grid-table min-w-[480px]">
                    <thead>
                      <tr>
                        <th>Product</th>
                        <th className="r">Share</th>
                        <th className="r">Per unit</th>
                        <th className="r">On stock</th>
                        <th className="r">On goods sold</th>
                      </tr>
                    </thead>
                    <tbody>
                      {lc.lines.map((l) => (
                        <tr key={l.product_id}>
                          <td className="text-[13px]">{l.product}</td>
                          <td className="r num">{fmtMoney(l.amount)}</td>
                          <td className="r num">
                            +{fmtMoney(l.per_unit)} <span className="text-[11px] text-fg-3">/ {l.unit}</span>
                          </td>
                          <td className="r num">{fmtMoney(l.on_stock)}</td>
                          <td className="r num">{l.on_sold ? fmtMoney(l.on_sold) : '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ))}
          </div>
        </Section>
      ) : null}
      {mine.length ? (
        <Section title="Returned to the supplier" hint="Debit notes">
          <div className="card divide-y divide-white/6">
            {mine.map((r) => (
              <div key={r.id} className="flex flex-wrap items-center gap-3 px-4 py-3 text-[13px]">
                <RotateCcw size={14} />
                <span className="font-semibold">{r.number}</span>
                <span className="text-fg-3">
                  {r.items.map((i) => `${fmtQty(i.quantity)} ${i.unit} ${i.product}`).join(', ')} · {r.reason_label}
                  {r.replace ? ' · to be replaced' : ''}
                </span>
                <span className="num ml-auto font-semibold">{fmtMoney(r.amount)}</span>
              </div>
            ))}
          </div>
        </Section>
      ) : null}
    </>
  )
}

