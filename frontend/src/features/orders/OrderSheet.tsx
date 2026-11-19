import { useEffect, useState } from 'react'
import { errorText } from '@/api/client'
import { api } from '@/api/endpoints'
import { useAction } from '@/api/queries'
import type { OrderDetailOut } from '@/api/types'
import { fmtMoney, fmtQty, n } from '@/lib/format'
import { Button, Facts, Field, Notice } from '@/ui/core'
import { LineEditor, lineErrors, lineTotal, newLine, useCustomers, useProducts, type Line } from '@/ui/lines'
import { Sheet } from '@/ui/overlays'
import { Picker } from '@/ui/pickers'

/** A new sales order: stock is taken the moment it is placed. */
export function OrderSheet({ open, onClose, onCreated, customerId }: { open: boolean; onClose: () => void; onCreated?: (order: OrderDetailOut) => void; customerId?: string }) {
  const customers = useCustomers()
  const products = useProducts()
  const [customer, setCustomer] = useState('')
  const [lines, setLines] = useState<Line[]>([newLine()])
  const [notes, setNotes] = useState('')
  const [tried, setTried] = useState(false)
  const create = useAction(api.orders.create, { success: (order) => `${order.order_number} placed`, quiet: true })

  useEffect(() => {
    if (!open) return
    setCustomer(customerId ?? '')
    setLines([newLine()])
    setNotes('')
    setTried(false)
    create.reset()
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  const errors = [...(customer ? [] : ['Choose a customer.']), ...lineErrors(lines, 'sale')]
  const chosen = lines.filter((line) => line.product_id)
  const subtotal = chosen.reduce((sum, line) => sum + n(line.quantity) * n(products.byId.get(line.product_id)?.mrp), 0)
  const total = chosen.reduce((sum, line) => sum + lineTotal(line, products.byId.get(line.product_id), 'sale'), 0)
  const short = chosen.reduce((sum, line) => sum + Math.max(0, n(line.quantity) - Math.max(0, n(products.byId.get(line.product_id)?.stock))), 0)

  function submit() {
    setTried(true)
    if (errors.length > 0) return
    create.mutate(
      { customer_id: customer, notes: notes || null, items: chosen.map((line) => ({ product_id: line.product_id, quantity_ordered: line.quantity, discount_percent: line.discount || '0', unit_price: null })) },
      {
        onSuccess: (order) => {
          onClose()
          onCreated?.(order)
        },
      },
    )
  }

  return (
    <Sheet
      open={open}
      onClose={onClose}
      width={1000}
      title="New sales order"
      subtitle="Prices start at MRP; set a discount per line. Anything short waits for the next purchase."
      aside={
        <div className="space-y-5">
          <div>
            <div className="eyebrow mb-2">Order</div>
            <Facts
              items={[
                { label: 'Lines', value: chosen.length },
                { label: 'At MRP', value: fmtMoney(subtotal) },
                { label: 'Discount', value: subtotal - total > 0.005 ? `−${fmtMoney(subtotal - total)}` : '—' },
                { label: 'Total', value: fmtMoney(total), strong: true },
              ]}
            />
          </div>
          {short > 0 ? <Notice tone="warn">{fmtQty(short)} units are not in stock. They will show as short until bought.</Notice> : null}
          <p className="text-[12px] text-fg-3">Before tax. The server confirms prices when the order is placed.</p>
        </div>
      }
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button kind="primary" busy={create.isPending} onClick={submit}>
            Place order
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        {create.error ? <Notice tone="bad">{errorText(create.error)}</Notice> : null}
        {tried && errors.length > 0 ? <Notice tone="bad">{errors.join('\n')}</Notice> : null}
        <Field label="Customer">
          {(props) => (
            <Picker
              {...props}
              value={customer}
              onChange={setCustomer}
              invalid={tried && !customer}
              placeholder="Choose a customer…"
              options={customers.map((row) => ({ value: row.id, label: row.name, detail: row.phone ?? row.email ?? undefined }))}
            />
          )}
        </Field>
        <div>
          <div className="label">Products</div>
          <LineEditor lines={lines} onChange={setLines} mode="sale" />
        </div>
        <Field label="Notes" optional>
          {(props) => <textarea {...props} className="field" placeholder="Anything the customer asked for" value={notes} onChange={(event) => setNotes(event.target.value)} />}
        </Field>
      </div>
    </Sheet>
  )
}
