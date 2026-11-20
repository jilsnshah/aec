import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Ban, CheckCircle2, Phone, Send, Star, Truck, type LucideIcon } from 'lucide-react'
import { errorText } from '@/api/client'
import { useAction } from '@/api/queries'
import { transporters, type Booking, type BookingIn, type EstimateRow, type BookingStatus, type ReferenceType } from '@/api/transporters'
import { cn } from '@/lib/cn'
import { fmtMoney, n } from '@/lib/format'
import { useDebounced } from '@/lib/route'
import { Badge, Button, Field, Notice, Spinner } from '@/ui/core'
import { Sheet, useConfirm } from '@/ui/overlays'
import { TransporterPicker, useTransporterMeta } from './TransporterPicker'

export const BOOKING_STATUS: Record<BookingStatus, { label: string; tone: 'sky' | 'steel' | 'ok' | 'warn' | 'bad' | 'muted' }> = {
  draft: { label: 'Draft', tone: 'muted' },
  requested: { label: 'Requested', tone: 'steel' },
  confirmed: { label: 'Confirmed', tone: 'sky' },
  declined: { label: 'Declined', tone: 'bad' },
  done: { label: 'Done', tone: 'ok' },
  cancelled: { label: 'Cancelled', tone: 'muted' },
}

export function BookingBadge({ status }: { status: BookingStatus }) {
  const s = BOOKING_STATUS[status] ?? { label: status, tone: 'muted' as const }
  return (
    <Badge tone={s.tone} dot={status === 'requested' || status === 'confirmed'}>
      {s.label}
    </Badge>
  )
}

const PURPOSES = [
  ['delivery', 'Delivery'],
  ['purchase', 'Purchase pickup'],
  ['transfer', 'Transfer'],
  ['return', 'Return'],
  ['other', 'Other'],
] as const
const PURPOSE_FROM_REF: Record<ReferenceType, string> = { sales_order: 'delivery', purchase_order: 'purchase', stock_transfer: 'transfer' }

const blank = { transporter_id: '', purpose: 'delivery', from_place: '', to_place: '', needed_at: '', vehicle_type: '', load: '', weight_kg: '', notes: '' }

/** Book a vehicle with a transporter, optionally for an order, purchase order or transfer. */
export function BookingSheet({
  open,
  onClose,
  transporterId,
  referenceType,
  referenceId,
  onSaved,
}: {
  open: boolean
  onClose: () => void
  transporterId?: string
  referenceType?: ReferenceType
  referenceId?: string
  onSaved?: (booking: Booking) => void
}) {
  const meta = useTransporterMeta()
  const [form, setForm] = useState(blank)
  useEffect(() => {
    if (open) setForm({ ...blank, transporter_id: transporterId ?? '', purpose: referenceType ? PURPOSE_FROM_REF[referenceType] : 'delivery' })
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps
  const est = useDebounced(JSON.stringify({ f: form.from_place, t: form.to_place, v: form.vehicle_type, w: form.weight_kg }))
  const q = JSON.parse(est) as { f: string; t: string; v: string; w: string }
  const estimates = useQuery({
    queryKey: ['transporters', 'estimate', q],
    queryFn: () => transporters.estimate({ from_place: q.f || undefined, to_place: q.t || undefined, vehicle_type: q.v || undefined, weight_kg: q.w || undefined }),
    enabled: open && Boolean(q.f || q.t || q.v),
  })
  const save = useAction(
    (status: BookingStatus) => {
      const body: BookingIn = {
        transporter_id: form.transporter_id || null,
        reference_type: referenceType ?? null,
        reference_id: referenceId ?? null,
        purpose: form.purpose || null,
        from_place: form.from_place || null,
        to_place: form.to_place || null,
        needed_at: form.needed_at || null,
        vehicle_type: form.vehicle_type || null,
        load: form.load || null,
        weight_kg: form.weight_kg || null,
        notes: form.notes || null,
        status,
      }
      return transporters.createBooking(body)
    },
    { success: (b) => (b.status === 'requested' ? `${b.number} requested` : `${b.number} saved as draft`), quiet: true },
  )
  const done = (b: Booking) => {
    onClose()
    onSaved?.(b)
  }
  const set = (key: keyof typeof blank) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => {
    const value = e.target.value
    setForm((f) => ({ ...f, [key]: value }))
  }
  const rows = estimates.data?.items ?? []
  return (
    <Sheet
      open={open}
      onClose={onClose}
      width={900}
      title="Book a vehicle"
      subtitle={referenceType ? 'Route, load and weight are taken from the order when left empty.' : 'Ask a transporter for a vehicle. Requests go out on their booking channel.'}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button busy={save.isPending} onClick={() => save.mutate('draft', { onSuccess: done })}>
            Save as draft
          </Button>
          <Button kind="primary" icon={<Send size={14} />} busy={save.isPending} disabled={!form.transporter_id} onClick={() => save.mutate('requested', { onSuccess: done })}>
            Request
          </Button>
        </>
      }
      aside={
        <div className="space-y-3">
          <div className="text-[12px] font-semibold text-fg-2">Estimates</div>
          {!(q.f || q.t || q.v) ? (
            <p className="text-[12px] text-fg-3">Enter a route or vehicle type to compare rate cards.</p>
          ) : estimates.isPending ? (
            <Spinner />
          ) : rows.length ? (
            rows.map((r) => <EstimateCard key={r.rate_id} row={r} chosen={form.transporter_id === r.transporter_id} onPick={() => setForm((f) => ({ ...f, transporter_id: r.transporter_id }))} />)
          ) : (
            <p className="text-[12px] text-fg-3">No rate card matches this route.</p>
          )}
        </div>
      }
    >
      <div className="grid grid-cols-6 gap-4">
        {save.error ? (
          <div className="col-span-6">
            <Notice tone="bad">{errorText(save.error)}</Notice>
          </div>
        ) : null}
        <Field label="Transporter" className="col-span-6" hint={form.transporter_id ? undefined : 'Needed to send a request. A draft can be saved without one.'}>
          {() => <TransporterPicker value={form.transporter_id} onChange={(id) => setForm((f) => ({ ...f, transporter_id: id }))} />}
        </Field>
        <Field label="Purpose" className="col-span-3 max-md:col-span-6">
          {(props) => (
            <select {...props} className="field" value={form.purpose} onChange={set('purpose')}>
              {PURPOSES.map(([k, label]) => (
                <option key={k} value={k}>
                  {label}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Vehicle type" optional className="col-span-3 max-md:col-span-6">
          {(props) => (
            <select {...props} className="field" value={form.vehicle_type} onChange={set('vehicle_type')}>
              <option value="">Any</option>
              {Object.entries(meta.vehicles).map(([k, label]) => (
                <option key={k} value={k}>
                  {label}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="From" optional={Boolean(referenceType)} className="col-span-3 max-md:col-span-6">
          {(props) => <input {...props} className="field" value={form.from_place} onChange={set('from_place')} placeholder="e.g. Changodar" />}
        </Field>
        <Field label="To" optional={Boolean(referenceType)} className="col-span-3 max-md:col-span-6">
          {(props) => <input {...props} className="field" value={form.to_place} onChange={set('to_place')} placeholder="e.g. Sanand" />}
        </Field>
        <Field label="Needed at" optional className="col-span-2 max-md:col-span-6">
          {(props) => <input {...props} type="datetime-local" className="field" value={form.needed_at} onChange={set('needed_at')} />}
        </Field>
        <Field label="Load" optional className="col-span-2 max-md:col-span-6">
          {(props) => <input {...props} className="field" value={form.load} onChange={set('load')} placeholder="e.g. 200 bags cement" />}
        </Field>
        <Field label="Weight (kg)" optional className="col-span-2 max-md:col-span-6">
          {(props) => <input {...props} className="field field-num" inputMode="decimal" value={form.weight_kg} onChange={set('weight_kg')} />}
        </Field>
        <Field label="Notes" optional className="col-span-6">
          {(props) => <input {...props} className="field" value={form.notes} onChange={set('notes')} />}
        </Field>
        {rows.length ? (
          <div className="col-span-6 space-y-2 md:hidden">
            <div className="label">Estimates</div>
            {rows.map((r) => (
              <EstimateCard key={r.rate_id} row={r} chosen={form.transporter_id === r.transporter_id} onPick={() => setForm((f) => ({ ...f, transporter_id: r.transporter_id }))} />
            ))}
          </div>
        ) : null}
      </div>
    </Sheet>
  )
}

function EstimateCard({ row, chosen, onPick }: { row: EstimateRow; chosen: boolean; onPick: () => void }) {
  return (
    <button type="button" onClick={onPick} className={cn('card block w-full p-3 text-left text-[12.5px] transition-colors', chosen && 'ring-2 ring-sky')}>
      <div className="flex items-center gap-2">
        <span className="min-w-0 flex-1 truncate font-semibold">{row.transporter}</span>
        {chosen ? <CheckCircle2 size={14} className="shrink-0 text-sky" /> : null}
      </div>
      <div className="mt-0.5 truncate text-fg-3">
        {row.route}
        {row.vehicle_label ? ` · ${row.vehicle_label}` : ''}
      </div>
      <div className="mt-1 flex items-center gap-2">
        <span className="num text-[14px] font-semibold">{row.amount != null ? fmtMoney(row.amount) : `${fmtMoney(row.rate)} / ${row.basis}`}</span>
        {row.rating ? (
          <span className="ml-auto flex items-center gap-0.5 text-fg-3">
            <Star size={11} className="fill-current" /> {row.rating}
          </span>
        ) : null}
      </div>
      {row.note ? <div className="mt-0.5 text-[11.5px] text-fg-3">{row.note}</div> : null}
      {row.loading_included ? <div className="mt-0.5 text-[11.5px] text-fg-3">Loading included</div> : null}
    </button>
  )
}

/** Confirm a booking: what was agreed and which vehicle is coming. */
export function ConfirmBookingSheet({ booking, open, onClose }: { booking: Booking; open: boolean; onClose: () => void }) {
  const [form, setForm] = useState({ agreed_amount: '', vehicle_number: '', driver_phone: '' })
  useEffect(() => {
    if (open)
      setForm({
        agreed_amount: booking.agreed_amount != null ? String(booking.agreed_amount) : booking.estimate != null ? String(booking.estimate) : '',
        vehicle_number: booking.vehicle_number ?? '',
        driver_phone: booking.driver_phone ?? '',
      })
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps
  const save = useAction(
    () =>
      transporters.updateBooking({
        id: booking.id,
        status: 'confirmed',
        agreed_amount: form.agreed_amount || null,
        vehicle_number: form.vehicle_number || null,
        driver_phone: form.driver_phone || null,
      }),
    { success: (b) => `${b.number} confirmed`, quiet: true },
  )
  return (
    <Sheet
      open={open}
      onClose={onClose}
      width={520}
      title={`Confirm ${booking.number}`}
      subtitle={booking.transporter ?? undefined}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button kind="primary" icon={<CheckCircle2 size={14} />} busy={save.isPending} onClick={() => save.mutate(undefined, { onSuccess: onClose })}>
            Confirm
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {save.error ? <Notice tone="bad">{errorText(save.error)}</Notice> : null}
        <Field label="Agreed amount" hint={booking.estimate != null ? `Rate card estimate: ${fmtMoney(booking.estimate)}` : undefined}>
          {(props) => <input {...props} autoFocus className="field field-num" inputMode="decimal" placeholder="₹" value={form.agreed_amount} onChange={(e) => { const v = e.target.value; setForm((f) => ({ ...f, agreed_amount: v })) }} />}
        </Field>
        <Field label="Vehicle number" optional>
          {(props) => <input {...props} className="field" placeholder="GJ01AB1234" value={form.vehicle_number} onChange={(e) => { const v = e.target.value; setForm((f) => ({ ...f, vehicle_number: v })) }} />}
        </Field>
        <Field label="Driver phone" optional>
          {(props) => <input {...props} className="field" inputMode="tel" value={form.driver_phone} onChange={(e) => { const v = e.target.value; setForm((f) => ({ ...f, driver_phone: v })) }} />}
        </Field>
      </div>
    </Sheet>
  )
}

/** Buttons that move a booking along: confirm, done, cancel. */
export function BookingActions({ booking, small }: { booking: Booking; small?: boolean }) {
  const [confirming, setConfirming] = useState(false)
  const confirm = useConfirm()
  const move = useAction((status: BookingStatus) => transporters.updateBooking({ id: booking.id, status }), { success: (b) => `${b.number}: ${BOOKING_STATUS[b.status]?.label ?? b.status}` })
  const open = booking.status === 'draft' || booking.status === 'requested'
  const actions: { key: string; label: string; icon: LucideIcon; kind?: 'primary' | 'ghost'; run: () => void }[] = []
  if (booking.status === 'draft' && booking.transporter_id) actions.push({ key: 'request', label: 'Request', icon: Send, run: () => move.mutate('requested') })
  if (open) actions.push({ key: 'confirm', label: 'Confirm', icon: CheckCircle2, kind: 'primary', run: () => setConfirming(true) })
  if (booking.status === 'confirmed') actions.push({ key: 'done', label: 'Done', icon: Truck, kind: 'primary', run: () => move.mutate('done') })
  if (open || booking.status === 'confirmed')
    actions.push({
      key: 'cancel',
      label: 'Cancel',
      icon: Ban,
      kind: 'ghost',
      run: async () => {
        const answer = await confirm.ask({ title: `Cancel ${booking.number}?`, body: booking.status === 'confirmed' ? 'Let the transporter know the vehicle is not needed.' : undefined, confirm: 'Cancel booking', danger: true })
        if (answer.ok) move.mutate('cancelled')
      },
    })
  if (!actions.length) return null
  // Clicks inside the sheets (portals) still bubble through React; keep them off clickable rows.
  return (
    <div onClick={(e) => e.stopPropagation()}>
      <div className="flex flex-wrap items-center gap-1.5">
        {actions.map((a) => (
          <Button key={a.key} small={small} kind={a.kind} icon={<a.icon size={small ? 13 : 14} />} busy={move.isPending && move.variables === (a.key === 'cancel' ? 'cancelled' : a.key === 'request' ? 'requested' : a.key)} onClick={a.run}>
            {a.label}
          </Button>
        ))}
      </div>
      <ConfirmBookingSheet booking={booking} open={confirming} onClose={() => setConfirming(false)} />
      {confirm.element}
    </div>
  )
}

/** A phone link for a driver or transporter. */
export function PhoneLink({ phone }: { phone: string | null | undefined }) {
  if (!phone) return null
  return (
    <a href={`tel:${phone}`} className="inline-flex items-center gap-1 text-sky hover:underline" onClick={(e) => e.stopPropagation()}>
      <Phone size={12} /> {phone}
    </a>
  )
}

export const bookingAmount = (b: Booking) => (b.agreed_amount != null && n(b.agreed_amount) > 0 ? fmtMoney(b.agreed_amount) : b.estimate != null ? `~${fmtMoney(b.estimate)}` : '—')
