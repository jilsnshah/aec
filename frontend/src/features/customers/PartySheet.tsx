import { useEffect, useState } from 'react'
import { errorText } from '@/api/client'
import { api } from '@/api/endpoints'
import { useAction } from '@/api/queries'
import { Button, Field, Notice } from '@/ui/core'
import { Sheet } from '@/ui/overlays'

type Kind = 'customer' | 'supplier'
interface Party {
  id: string
  name: string
  phone: string | null
  email: string | null
  address: string | null
  notes: string | null
  code?: string
  contact_person?: string | null
  payment_terms_days?: number
  credit_limit?: string | number | null
  lead_time_days?: number | null
}

const blank = { name: '', phone: '', email: '', address: '', notes: '', code: '', contact_person: '', terms: '0', credit: '', lead: '' }

/** Create or edit a customer or supplier: who they are and how to reach them. */
export function PartySheet({ kind, open, onClose, editing, onSaved }: { kind: Kind; open: boolean; onClose: () => void; editing?: Party; onSaved?: (id: string) => void }) {
  const [form, setForm] = useState(blank)
  const [tried, setTried] = useState(false)
  const label = kind === 'customer' ? 'customer' : 'supplier'
  const save = useAction(
    async () => {
      const clean = (value: string) => value.trim() || null
      const base = { name: form.name.trim(), phone: clean(form.phone), email: clean(form.email), address: clean(form.address), notes: clean(form.notes), payment_terms_days: Number(form.terms) || 0 }
      if (kind === 'customer') {
        const customer = { ...base, credit_limit: form.credit.trim() === '' ? null : form.credit.trim() }
        return editing ? api.customers.update(editing.id, customer) : api.customers.create(customer)
      }
      const supplier = { ...base, code: clean(form.code), contact_person: clean(form.contact_person), lead_time_days: form.lead.trim() === '' ? null : Number(form.lead) }
      return editing ? api.suppliers.update(editing.id, supplier) : api.suppliers.create(supplier)
    },
    { success: editing ? `${form.name} saved` : `${form.name} added`, quiet: true },
  )

  useEffect(() => {
    if (!open) return
    setForm(editing ? { name: editing.name, phone: editing.phone ?? '', email: editing.email ?? '', address: editing.address ?? '', notes: editing.notes ?? '', code: editing.code ?? '', contact_person: editing.contact_person ?? '', terms: String(editing.payment_terms_days ?? 0), credit: editing.credit_limit == null ? '' : String(editing.credit_limit), lead: editing.lead_time_days == null ? '' : String(editing.lead_time_days) } : blank)
    setTried(false)
    save.reset()
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  const set = (key: keyof typeof blank) => (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setForm({ ...form, [key]: event.target.value })
  const termsBad = !/^\d{1,3}$/.test(form.terms.trim()) || Number(form.terms) > 365
  const creditBad = form.credit.trim() !== '' && !(Number(form.credit) >= 0)
  const leadBad = form.lead.trim() !== '' && !/^\d{1,3}$/.test(form.lead.trim())
  const emailBad = form.email.trim() !== '' && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(form.email.trim())

  function submit() {
    setTried(true)
    if (!form.name.trim() || emailBad || termsBad || creditBad || leadBad) return
    save.mutate(undefined, {
      onSuccess: (result) => {
        onClose()
        onSaved?.(result.id)
      },
    })
  }

  return (
    <Sheet
      open={open}
      onClose={onClose}
      width={640}
      title={editing ? `Edit ${editing.name}` : `New ${label}`}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button kind="primary" busy={save.isPending} onClick={submit}>
            {editing ? 'Save' : `Add ${label}`}
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-2 gap-4">
        {save.error ? (
          <div className="col-span-2">
            <Notice tone="bad">{errorText(save.error)}</Notice>
          </div>
        ) : null}
        <Field label="Name" className="col-span-2" error={tried && !form.name.trim() ? 'A name is needed.' : null}>
          {(props) => <input {...props} className="field" autoFocus value={form.name} onChange={set('name')} />}
        </Field>
        {kind === 'supplier' ? (
          <>
            <Field label="Code" optional hint="Leave blank to number it automatically.">
              {(props) => <input {...props} className="field" value={form.code} onChange={set('code')} />}
            </Field>
            <Field label="Contact person" optional>
              {(props) => <input {...props} className="field" value={form.contact_person} onChange={set('contact_person')} />}
            </Field>
          </>
        ) : null}
        <Field label="Phone" optional hint={kind === 'customer' ? 'WhatsApp messages are matched to customers by this number.' : undefined}>
          {(props) => <input {...props} className="field" inputMode="tel" value={form.phone} onChange={set('phone')} />}
        </Field>
        <Field label="Email" optional error={tried && emailBad ? 'This does not look like an email address.' : null}>
          {(props) => <input {...props} className="field" type="email" value={form.email} onChange={set('email')} />}
        </Field>
        <Field label="Address" optional className="col-span-2">
          {(props) => <textarea {...props} className="field" rows={2} value={form.address} onChange={set('address')} />}
        </Field>
        <Field label="Payment terms (days)" hint={kind === 'customer' ? 'Each delivery falls due this many days later. 0 = pay on delivery.' : 'Days of credit this supplier gives on goods received.'} error={tried && termsBad ? 'Enter 0 to 365 days.' : null}>
          {(props) => <input {...props} className="field field-num" inputMode="numeric" value={form.terms} onChange={set('terms')} />}
        </Field>
        {kind === 'customer' ? (
          <Field label="Credit limit (₹)" optional hint="Most they may owe at once; you are warned when they go over." error={tried && creditBad ? 'Enter an amount.' : null}>
            {(props) => <input {...props} className="field field-num" inputMode="decimal" placeholder="No limit" value={form.credit} onChange={set('credit')} />}
          </Field>
        ) : (
          <Field label="Lead time (days)" optional hint="Typical days from ordering to delivery; used for reorder timing." error={tried && leadBad ? 'Enter whole days.' : null}>
            {(props) => <input {...props} className="field field-num" inputMode="numeric" placeholder="Unknown" value={form.lead} onChange={set('lead')} />}
          </Field>
        )}
        <Field label="Notes" optional className="col-span-2">
          {(props) => <textarea {...props} className="field" rows={2} value={form.notes} onChange={set('notes')} />}
        </Field>
      </div>
    </Sheet>
  )
}
