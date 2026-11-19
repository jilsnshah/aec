import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link2, UserPlus, UserRound } from 'lucide-react'
import { errorText } from '@/api/client'
import { http } from '@/api/client'
import { useAction } from '@/api/queries'
import { parties } from '@/api/parties'
import { cn } from '@/lib/cn'
import { Button, Notice } from '@/ui/core'
import { Sheet } from '@/ui/overlays'
import { Picker } from '@/ui/pickers'
import { useCustomers } from '@/ui/lines'

interface Sender {
  id: string
  enquiry_number: string
  sender_name: string | null
  sender_phone: string | null
  sender_email: string | null
}

/** Say who an enquiry from an unknown number or email is from: an existing
 *  customer, or a new one made from the sender's details. Their number and
 *  email are then linked, so the next message is recognised. */
export function AssignCustomer({ enquiry, open, onClose, onDone, then }: { enquiry: Sender; open: boolean; onClose: () => void; onDone?: () => void; then?: string }) {
  const customers = useCustomers()
  const [mode, setMode] = useState<'existing' | 'new'>('existing')
  const [customerId, setCustomerId] = useState('')
  const [form, setForm] = useState({ name: '', phone: '', email: '' })
  useEffect(() => {
    if (!open) return
    setForm({ name: enquiry.sender_name ?? '', phone: enquiry.sender_phone ?? '', email: enquiry.sender_email ?? '' })
    setCustomerId('')
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps
  const similar = useQuery({
    queryKey: ['parties', 'duplicates', 'customer', enquiry.id],
    enabled: open && Boolean(enquiry.sender_name),
    queryFn: () => parties.duplicates('customer', { name: enquiry.sender_name ?? undefined }),
  })
  useEffect(() => {
    if (similar.data?.similar.length) setMode('existing')
  }, [similar.data])
  const save = useAction(
    () =>
      http.post(`/api/enquiries/${enquiry.id}/customer`, mode === 'existing' ? { customer_id: customerId } : { new_customer: { name: form.name.trim(), phone: form.phone || null, email: form.email || null } }),
    { success: 'Customer assigned', quiet: true },
  )
  return (
    <Sheet
      open={open}
      onClose={onClose}
      width={600}
      title={`Who sent ${enquiry.enquiry_number}?`}
      subtitle={`From ${[enquiry.sender_name, enquiry.sender_phone, enquiry.sender_email].filter(Boolean).join(' · ') || 'an unknown sender'}. Their number and email will be added to the customer, so next time they are recognised.`}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            kind="primary"
            icon={<Link2 size={14} />}
            busy={save.isPending}
            disabled={mode === 'existing' ? !customerId : !form.name.trim()}
            onClick={() => save.mutate(undefined, { onSuccess: () => (onClose(), onDone?.()) })}
          >
            {then ?? 'Assign customer'}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {save.error ? <Notice tone="bad">{errorText(save.error)}</Notice> : null}
        <div className="flex gap-1.5">
          {(
            [
              ['existing', 'Existing customer', UserRound],
              ['new', 'New customer', UserPlus],
            ] as const
          ).map(([value, label, Icon]) => (
            <button key={value} onClick={() => setMode(value)} className={cn('inline-flex h-[32px] items-center gap-1.5 rounded-full px-3.5 text-[12.5px] font-semibold', mode === value ? 'brand-fill' : 'bg-ink-700 text-fg-2')}>
              <Icon size={13} /> {label}
            </button>
          ))}
        </div>
        {mode === 'existing' ? (
          <div className="space-y-3">
            {similar.data?.similar.length ? (
              <div>
                <div className="eyebrow mb-1.5">Similar names</div>
                <div className="flex flex-wrap gap-1.5">
                  {similar.data.similar.map((hit) => (
                    <button key={hit.id} onClick={() => setCustomerId(hit.id)} className={cn('h-[30px] rounded-full px-3 text-[12px] font-semibold', customerId === hit.id ? 'brand-fill' : 'bg-peri/40')}>
                      {hit.name}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
            <Picker value={customerId} onChange={setCustomerId} placeholder="Search customers…" options={customers.filter((c) => c.is_active).map((c) => ({ value: c.id, label: c.name, detail: c.phone ?? undefined }))} />
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-3 max-md:grid-cols-1">
            <label className="col-span-2 block max-md:col-span-1">
              <span className="label">Name</span>
              <input className="field" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Business or person" />
            </label>
            <label className="block">
              <span className="label">Phone</span>
              <input className="field" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
            </label>
            <label className="block">
              <span className="label">Email</span>
              <input className="field" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
            </label>
          </div>
        )}
      </div>
    </Sheet>
  )
}
