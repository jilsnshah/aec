import { usePriceList } from '@/features/pricing/usePriceList'
import { useEffect, useState } from 'react'
import { errorText } from '@/api/client'
import { api } from '@/api/endpoints'
import { useAction } from '@/api/queries'
import type { EnquiryOut } from '@/api/types'
import { fmtMoney, n } from '@/lib/format'
import { Button, Facts, Field, Notice } from '@/ui/core'
import { LineEditor, lineErrors, lineTotal, newLine, useCustomers, useProducts, type Line } from '@/ui/lines'
import { Sheet } from '@/ui/overlays'
import { Picker } from '@/ui/pickers'

/** A quote: products at MRP with a negotiated discount per line. */
export function EnquirySheet({ open, onClose, onSaved, editing, customerId }: { open: boolean; onClose: () => void; onSaved?: (enquiry: EnquiryOut) => void; editing?: EnquiryOut; customerId?: string }) {
  const customers = useCustomers()
  const products = useProducts()
  const [customer, setCustomer] = useState('')
  const [lines, setLines] = useState<Line[]>([newLine()])
  const pricing = usePriceList(open, customer, lines, setLines)
  const [notes, setNotes] = useState('')
  const [tried, setTried] = useState(false)
  const save = useAction(
    () => {
      const items = lines.filter((line) => line.product_id).map((line) => ({ product_id: line.product_id, quantity: line.quantity, discount_percent: line.discount || '0' }))
      return editing ? api.enquiries.update(editing.id, { notes: notes || null, items }) : api.enquiries.create({ customer_id: customer, notes: notes || null, items })
    },
    { success: (enquiry) => (editing ? `${enquiry.enquiry_number} saved` : `${enquiry.enquiry_number} opened`), quiet: true },
  )

  useEffect(() => {
    if (!open) return
    setCustomer(editing?.customer_id ?? customerId ?? '')
    setLines(editing ? editing.items.map((item) => newLine({ product_id: item.product_id, quantity: String(n(item.quantity)), discount: String(n(item.discount_percent)) })) : [newLine()])
    setNotes(editing?.notes ?? '')
    setTried(false)
    save.reset()
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  const chosen = lines.filter((line) => line.product_id)
  const atMrp = chosen.reduce((sum, line) => sum + n(line.quantity) * n(products.byId.get(line.product_id)?.mrp), 0)
  const total = chosen.reduce((sum, line) => sum + lineTotal(line, products.byId.get(line.product_id), 'sale'), 0)
  const errors = [...(customer ? [] : ['Choose a customer.']), ...lineErrors(lines, 'sale')]

  return (
    <Sheet
      open={open}
      onClose={onClose}
      width={1000}
      title={editing ? `Edit ${editing.enquiry_number}` : 'New enquiry'}
      subtitle={pricing?.price_list_active ? `Prices start from ${pricing.price_list} (the customer's price list). Negotiate per line, then close the deal into an order.` : "MRP comes from the product. Negotiate a discount per line, then close the deal into an order."}
      aside={
        <div className="space-y-5">
          <div>
            <div className="eyebrow mb-2">Deal</div>
            <Facts
              items={[
                { label: 'At MRP', value: fmtMoney(atMrp) },
                { label: 'Discount', value: atMrp - total > 0.005 ? `−${fmtMoney(atMrp - total)}` : '—' },
                { label: 'Deal value', value: fmtMoney(total), strong: true },
              ]}
            />
          </div>
          {atMrp > 0 ? <div className="num text-[12px] text-fg-3">{(((atMrp - total) / atMrp) * 100).toFixed(1)}% off MRP overall</div> : null}
        </div>
      }
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            kind="primary"
            busy={save.isPending}
            onClick={() => {
              setTried(true)
              if (errors.length === 0)
                save.mutate(undefined, {
                  onSuccess: (enquiry) => {
                    onClose()
                    onSaved?.(enquiry)
                  },
                })
            }}
          >
            {editing ? 'Save' : 'Open enquiry'}
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        {save.error ? <Notice tone="bad">{errorText(save.error)}</Notice> : null}
        {tried && errors.length > 0 ? <Notice tone="bad">{errors.join('\n')}</Notice> : null}
        <Field label="Customer">
          {(props) => <Picker {...props} value={customer} onChange={setCustomer} disabled={Boolean(editing)} invalid={tried && !customer} placeholder="Choose a customer…" options={customers.map((row) => ({ value: row.id, label: row.name, detail: row.phone ?? undefined }))} />}
        </Field>
        <div>
          <div className="label">Products</div>
          <LineEditor lines={lines} onChange={setLines} mode="sale" />
        </div>
        <Field label="Notes" optional>
          {(props) => <textarea {...props} className="field" placeholder="Delivery in two batches, call before dispatch…" value={notes} onChange={(event) => setNotes(event.target.value)} />}
        </Field>
      </div>
    </Sheet>
  )
}
