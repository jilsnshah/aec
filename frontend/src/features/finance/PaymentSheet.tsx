import { useEffect, useState } from 'react'
import { errorText } from '@/api/client'
import { useAction } from '@/api/queries'
import { finance } from '@/api/finance'
import { fmtMoney } from '@/lib/format'
import { Button, Field, Notice } from '@/ui/core'
import { Segmented, Sheet } from '@/ui/overlays'
import { Picker } from '@/ui/pickers'
import { useCustomers, useSuppliers } from '@/ui/lines'

const METHODS = [
  { value: 'bank', label: 'Bank' },
  { value: 'upi', label: 'UPI' },
  { value: 'cash', label: 'Cash' },
  { value: 'cheque', label: 'Cheque' },
  { value: 'card', label: 'Card' },
]
const today = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60_000).toISOString().slice(0, 10)

/** Record money received from a customer or paid to a supplier. It settles
 *  the oldest open invoices or bills first. */
export function PaymentSheet({
  open,
  onClose,
  direction: fixedDirection,
  partyId,
  suggested,
}: {
  open: boolean
  onClose: () => void
  direction?: 'in' | 'out'
  partyId?: string
  /** An amount to start from, e.g. what is open. */
  suggested?: number
}) {
  const customers = useCustomers()
  const suppliers = useSuppliers()
  const [direction, setDirection] = useState<'in' | 'out'>(fixedDirection ?? 'in')
  const [party, setParty] = useState(partyId ?? '')
  const [amount, setAmount] = useState('')
  const [day, setDay] = useState(today())
  const [method, setMethod] = useState('bank')
  const [reference, setReference] = useState('')
  const [notes, setNotes] = useState('')
  const [tried, setTried] = useState(false)
  const save = useAction(finance.record, { success: (p) => `${p.number} recorded · ${fmtMoney(p.amount)}`, quiet: true })

  useEffect(() => {
    if (!open) return
    setDirection(fixedDirection ?? 'in')
    setParty(partyId ?? '')
    setAmount(suggested && suggested > 0 ? String(suggested) : '')
    setDay(today())
    setMethod('bank')
    setReference('')
    setNotes('')
    setTried(false)
    save.reset()
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  const amountBad = !(Number(amount) > 0)
  const options = direction === 'in' ? customers.map((c) => ({ value: c.id, label: c.name, detail: c.phone ?? undefined })) : suppliers.map((s) => ({ value: s.id, label: s.name, detail: s.code }))

  function submit() {
    setTried(true)
    if (amountBad || !party) return
    save.mutate(
      {
        direction,
        amount,
        paid_on: day,
        method,
        reference: reference.trim() || null,
        notes: notes.trim() || null,
        customer_id: direction === 'in' ? party : null,
        supplier_id: direction === 'out' ? party : null,
      },
      { onSuccess: onClose },
    )
  }

  return (
    <Sheet
      open={open}
      onClose={onClose}
      width={560}
      title={direction === 'in' ? 'Money received' : 'Money paid'}
      subtitle={direction === 'in' ? 'From a customer. It settles their oldest open invoices first.' : 'To a supplier. It settles their oldest open bills first.'}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button kind="primary" busy={save.isPending} onClick={submit}>
            Record {amount && !amountBad ? fmtMoney(amount) : 'payment'}
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-2 gap-4 max-md:grid-cols-1">
        {save.error ? (
          <div className="col-span-2 max-md:col-span-1">
            <Notice tone="bad">{errorText(save.error)}</Notice>
          </div>
        ) : null}
        {!fixedDirection ? (
          <Field label="Direction" className="col-span-2 max-md:col-span-1">
            {() => (
              <Segmented
                value={direction}
                onChange={(value) => {
                  setDirection(value)
                  setParty('')
                }}
                options={[
                  { value: 'in', label: 'Received from a customer' },
                  { value: 'out', label: 'Paid to a supplier' },
                ]}
              />
            )}
          </Field>
        ) : null}
        <Field label={direction === 'in' ? 'Customer' : 'Supplier'} className="col-span-2 max-md:col-span-1" error={tried && !party ? 'Choose who.' : null}>
          {() => <Picker value={party} onChange={setParty} options={options} placeholder={direction === 'in' ? 'Choose a customer…' : 'Choose a supplier…'} disabled={Boolean(partyId)} />}
        </Field>
        <Field label="Amount (₹)" error={tried && amountBad ? 'Enter an amount above zero.' : null}>
          {(props) => <input {...props} className="field field-num h-11 text-[18px] font-semibold" inputMode="decimal" autoFocus value={amount} onChange={(e) => setAmount(e.target.value)} />}
        </Field>
        <Field label="Date">
          {(props) => <input {...props} type="date" className="field h-11" max={today()} value={day} onChange={(e) => setDay(e.target.value)} />}
        </Field>
        <Field label="Method" className="col-span-2 max-md:col-span-1">
          {() => <Segmented value={method} onChange={setMethod} options={METHODS} />}
        </Field>
        <Field label="Reference" optional hint="Cheque number, UTR or transaction id.">
          {(props) => <input {...props} className="field" value={reference} onChange={(e) => setReference(e.target.value)} />}
        </Field>
        <Field label="Notes" optional>
          {(props) => <input {...props} className="field" value={notes} onChange={(e) => setNotes(e.target.value)} />}
        </Field>
      </div>
    </Sheet>
  )
}
