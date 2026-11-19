import { useEffect, useMemo, useState } from 'react'
import { Truck } from 'lucide-react'
import { errorText } from '@/api/client'
import { api } from '@/api/endpoints'
import { useAction, useOne } from '@/api/queries'
import { fmtQty, isQty, n } from '@/lib/format'
import { Button, Field, Notice, Spinner } from '@/ui/core'
import { Sheet } from '@/ui/overlays'

/** Load the truck: how much of each ready line leaves now. */
export function DeliverSheet({ orderId, open, onClose, onlyItem }: { orderId: string; open: boolean; onClose: () => void; onlyItem?: string }) {
  const fulfilment = useOne('fulfilment', api.orders.fulfilment, open ? orderId : undefined)
  const lines = useMemo(() => (fulfilment.data?.lines ?? []).filter((line) => n(line.quantity_deliverable) > 0 && (!onlyItem || line.order_item_id === onlyItem)), [fulfilment.data, onlyItem])
  const [amounts, setAmounts] = useState<Record<string, string>>({})
  const [reference, setReference] = useState('')
  const [notes, setNotes] = useState('')
  const [key, setKey] = useState(() => crypto.randomUUID())
  const deliver = useAction((body: Parameters<typeof api.orders.deliver>[1]) => api.orders.deliver(orderId, body), {
    success: (result) => `${result.delivery_number} · ${fmtQty(result.total_delivered)} delivered`,
    quiet: true,
  })

  useEffect(() => {
    if (!open) return
    setAmounts(Object.fromEntries(lines.map((line) => [line.order_item_id, String(n(line.quantity_deliverable))])))
    setReference('')
    setNotes('')
    setKey(crypto.randomUUID())
    deliver.reset()
  }, [open, lines.length]) // eslint-disable-line react-hooks/exhaustive-deps

  const errors = lines.filter((line) => {
    const value = amounts[line.order_item_id] ?? ''
    return value !== '' && (!isQty(value) || n(value) > n(line.quantity_deliverable))
  })
  const chosen = lines.filter((line) => n(amounts[line.order_item_id]) > 0)
  const total = chosen.reduce((sum, line) => sum + n(amounts[line.order_item_id]), 0)

  function submit() {
    deliver.mutate(
      { lines: chosen.map((line) => ({ order_item_id: line.order_item_id, quantity: amounts[line.order_item_id] })), reference: reference || null, notes: notes || null, idempotency_key: key },
      { onSuccess: onClose },
    )
  }

  return (
    <Sheet
      open={open}
      onClose={onClose}
      width={720}
      title={fulfilment.data ? `Deliver against ${fulfilment.data.order_number}` : 'Deliver'}
      subtitle={fulfilment.data ? `To ${fulfilment.data.customer_name}. Stock leaves the warehouse; this cannot be undone.` : undefined}
      footer={
        <>
          <span className="mr-auto text-[12.5px] text-fg-3">{chosen.length > 0 ? `${fmtQty(total)} units on ${chosen.length} line${chosen.length === 1 ? '' : 's'}` : 'Nothing chosen'}</span>
          <Button onClick={onClose}>Cancel</Button>
          <Button kind="primary" icon={<Truck size={15} />} busy={deliver.isPending} disabled={chosen.length === 0 || errors.length > 0} onClick={submit}>
            Deliver {total > 0 ? fmtQty(total) : ''}
          </Button>
        </>
      }
    >
      {fulfilment.isPending ? (
        <Spinner />
      ) : lines.length === 0 ? (
        <Notice tone="warn">Nothing on this order is ready to deliver.</Notice>
      ) : (
        <div className="space-y-5">
          {deliver.error ? <Notice tone="bad">{errorText(deliver.error)}</Notice> : null}
          <div className="overflow-hidden rounded-xl bg-ink-900 ring-1 ring-white/7 ring-inset">
            <table className="grid-table">
              <thead>
                <tr>
                  <th>Product</th>
                  <th className="r">To deliver</th>
                  <th className="r">Ready</th>
                  <th className="r w-[130px]">Deliver now</th>
                </tr>
              </thead>
              <tbody>
                {lines.map((line) => {
                  const value = amounts[line.order_item_id] ?? ''
                  const bad = value !== '' && (!isQty(value) || n(value) > n(line.quantity_deliverable))
                  return (
                    <tr key={line.order_item_id}>
                      <td>
                        <div className="text-[13px] font-medium">{line.product_name}</div>
                        <div className="text-[11.5px] text-fg-3">
                          {line.product_sku} · {line.unit_of_measure}
                        </div>
                      </td>
                      <td className="r num">{fmtQty(line.quantity_outstanding)}</td>
                      <td className="r num text-sky">{fmtQty(line.quantity_deliverable)}</td>
                      <td className="r">
                        <input className="field field-sm field-num" inputMode="decimal" aria-invalid={bad || undefined} value={value} onChange={(event) => setAmounts({ ...amounts, [line.order_item_id]: event.target.value })} />
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          {errors.length > 0 ? <Notice tone="bad">You can deliver at most what is ready on each line.</Notice> : null}
          <div className="grid grid-cols-2 gap-4">
            <Field label="Reference" optional>
              {(props) => <input {...props} className="field" placeholder="Vehicle, docket…" value={reference} onChange={(event) => setReference(event.target.value)} />}
            </Field>
            <Field label="Note" optional>
              {(props) => <input {...props} className="field" value={notes} onChange={(event) => setNotes(event.target.value)} />}
            </Field>
          </div>
        </div>
      )}
    </Sheet>
  )
}
