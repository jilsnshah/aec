import { useEffect, useState, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  ArrowRight,
  Ban,
  Building2,
  CalendarClock,
  Calculator,
  Car,
  ClipboardList,
  Handshake,
  House,
  IndianRupee,
  MessageCircle,
  Package,
  Pencil,
  Phone,
  Plus,
  ReceiptText,
  RotateCcw,
  Route,
  Star,
  Trash2,
  Truck,
  Wallet,
  type LucideIcon,
} from 'lucide-react'
import { errorText } from '@/api/client'
import { useAction } from '@/api/queries'
import {
  transporters,
  type Booking,
  type RateIn,
  type RateLine,
  type Transporter,
  type TransporterFull,
  type TransporterIn,
  type Trip,
  type Vehicle,
  type VehicleIn,
  VEHICLE_LABEL,
} from '@/api/transporters'
import { PartyProfile } from '@/features/parties/PartyProfile'
import { cn } from '@/lib/cn'
import { fmtDate, fmtDateTime, fmtMoney, fmtQty, n } from '@/lib/format'
import { useDebounced } from '@/lib/route'
import { Badge, Button, Empty, Field, Notice, SearchBox, Spinner } from '@/ui/core'
import { Segmented, Sheet, TabPanel, Tabs, useConfirm } from '@/ui/overlays'
import { FigureStrip, InspectorHeader, ListPane, ListRow, Section, SplitView } from '@/ui/split'
import { PageGuide } from '@/ui/smart'
import { BOOKING_STATUS, BookingActions, BookingBadge, BookingSheet, PhoneLink, bookingAmount } from './BookingSheet'
import { useTransporterMeta } from './TransporterPicker'

const KIND_ICON: Record<string, LucideIcon> = { company: Building2, fleet_owner: Truck, broker: Handshake, tempo: Car, courier: Package, own_fleet: House }
const TRIP_TONE: Record<Trip['kind'], 'sky' | 'steel' | 'ok' | 'muted'> = { delivery: 'sky', receipt: 'steel', transfer: 'ok', booking: 'muted' }
const TRIP_LABEL: Record<Trip['kind'], string> = { delivery: 'Delivery', receipt: 'Receipt', transfer: 'Transfer', booking: 'Booking' }
const CHANNEL_LABEL: Record<string, string> = { whatsapp: 'WhatsApp', call: 'Phone call', either: 'Either' }

function Stars({ value, onChange, size = 12 }: { value: number | null | undefined; onChange?: (v: number | null) => void; size?: number }) {
  if (!onChange && !value) return null
  return (
    <span className="inline-flex items-center gap-0.5" aria-label={value ? `${value} of 5` : 'Not rated'}>
      {[1, 2, 3, 4, 5].map((i) =>
        onChange ? (
          <button key={i} type="button" aria-label={`${i} star${i === 1 ? '' : 's'}`} onClick={() => onChange(value === i ? null : i)} className="p-0.5">
            <Star size={size} className={cn(i <= (value ?? 0) ? 'fill-current text-warn' : 'text-fg-4')} />
          </button>
        ) : (
          <Star key={i} size={size} className={cn(i <= (value ?? 0) ? 'fill-current text-warn' : 'text-fg-4')} />
        ),
      )}
    </span>
  )
}

/** Transporters, their vehicles and rate cards, and vehicle bookings. */
export function Transporters() {
  const [params, setParams] = useSearchParams()
  const view = (params.get('view') as 'transporters' | 'bookings') ?? 'transporters'
  const selected = params.get('id')
  const [search, setSearch] = useState('')
  const [bookingFilter, setBookingFilter] = useState<'open' | 'all'>('open')
  const query = useDebounced(search)
  const list = useQuery({ queryKey: ['transporters', 'list', query], queryFn: () => transporters.list({ search: query || undefined, include_inactive: true }) })
  const bookings = useQuery({ queryKey: ['transport-bookings'], queryFn: () => transporters.bookings() })
  const [sheet, setSheet] = useState<null | { kind: 'transporter'; editing?: TransporterFull } | { kind: 'booking'; transporterId?: string }>(null)
  const set = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params)
    Object.entries(patch).forEach(([k, v]) => (v === null ? next.delete(k) : next.set(k, v)))
    setParams(next, { replace: true })
  }
  const items = [...(list.data?.items ?? [])].sort((a, b) => Number(b.is_active) - Number(a.is_active))
  const allBookings = bookings.data?.items ?? []
  const openBookings = allBookings.filter((b) => ['draft', 'requested', 'confirmed'].includes(b.status))
  const shownBookings = (bookingFilter === 'open' ? openBookings : allBookings).filter((b) => {
    if (!query) return true
    const q = query.toLowerCase()
    return [b.number, b.transporter, b.from_place, b.to_place, b.vehicle_number, b.reference_number].some((x) => x?.toLowerCase().includes(q))
  })
  useEffect(() => {
    if (selected || window.innerWidth < 1024) return
    if (view === 'transporters' && items.length) set({ id: items[0].id })
    if (view === 'bookings' && shownBookings.length) set({ id: shownBookings[0].id })
  }, [view, items.length, shownBookings.length]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <SplitView
        showDetail={Boolean(selected)}
        onBack={() => set({ id: null })}
        list={
          <ListPane
            title="Transporters"
            count={view === 'transporters' ? items.length : shownBookings.length}
            actions={
              <>
                <PageGuide
                  title="Transporters"
                  points={[
                    { icon: Truck, text: 'Keep each transporter with their vehicles, drivers and rate card. Deliveries, receipts and transfers that name them show as trips.' },
                    { icon: Calculator, text: 'The rate card estimates freight for a route, vehicle and load, and compares transporters when you book.' },
                    { icon: MessageCircle, text: 'A booking asks for a vehicle on their channel (WhatsApp or a call). Confirm it with the agreed amount and vehicle number.' },
                    { icon: Wallet, text: 'Freight charged on trips is what you owe them; payments bring it down. Freight bills post to their Tally ledger.' },
                  ]}
                />
                <Button small kind="primary" icon={<Plus size={14} />} onClick={() => setSheet(view === 'transporters' ? { kind: 'transporter' } : { kind: 'booking' })}>
                  New
                </Button>
              </>
            }
            filters={
              <>
                <Segmented
                  value={view}
                  onChange={(v) => set({ view: v, id: null })}
                  options={[
                    { value: 'transporters', label: 'Transporters' },
                    { value: 'bookings', label: 'Bookings', count: openBookings.length || undefined },
                  ]}
                />
                <SearchBox value={search} onChange={setSearch} placeholder={view === 'transporters' ? 'Name, area, vehicle or phone' : 'Booking, transporter, place'} />
                {view === 'bookings' ? (
                  <Segmented
                    value={bookingFilter}
                    onChange={setBookingFilter}
                    options={[
                      { value: 'open', label: 'Open', count: openBookings.length },
                      { value: 'all', label: 'All', count: allBookings.length },
                    ]}
                  />
                ) : null}
              </>
            }
          >
            {view === 'transporters' ? (
              list.isPending ? (
                <Spinner />
              ) : items.length ? (
                items.map((t) => <TransporterRow key={t.id} t={t} selected={selected === t.id} onSelect={() => set({ id: t.id })} />)
              ) : (
                <Empty
                  icon={<Truck size={20} />}
                  title={search ? 'No transporters match' : 'No transporters yet'}
                  action={
                    <Button kind="primary" small onClick={() => setSheet({ kind: 'transporter' })}>
                      New transporter
                    </Button>
                  }
                />
              )
            ) : bookings.isPending ? (
              <Spinner />
            ) : shownBookings.length ? (
              shownBookings.map((b) => (
                <ListRow key={b.id} group="bk" selected={selected === b.id} onSelect={() => set({ id: b.id })}>
                  <div className="flex items-center gap-2">
                    <span className="text-[13.5px] font-semibold">{b.number}</span>
                    <BookingBadge status={b.status} />
                    <span className="num ml-auto text-[12.5px] font-semibold">{bookingAmount(b)}</span>
                  </div>
                  <div className="mt-0.5 truncate text-[12px] text-fg-3">
                    {b.transporter ?? 'No transporter yet'}
                    {b.vehicle_label ? ` · ${b.vehicle_label}` : ''}
                  </div>
                  <div className="mt-0.5 flex items-center gap-1 truncate text-[12px] text-fg-3">
                    {b.from_place || '—'} <ArrowRight size={11} className="shrink-0" /> {b.to_place || '—'}
                    {b.needed_at ? ` · ${fmtDateTime(b.needed_at)}` : ''}
                  </div>
                </ListRow>
              ))
            ) : (
              <Empty
                icon={<CalendarClock size={20} />}
                title={bookingFilter === 'open' ? 'No open bookings' : 'No bookings yet'}
                action={
                  <Button kind="primary" small onClick={() => setSheet({ kind: 'booking' })}>
                    Book a vehicle
                  </Button>
                }
              />
            )}
          </ListPane>
        }
      >
        {!selected ? (
          <Empty className="h-full" icon={<Truck size={22} />} title={view === 'transporters' ? 'Choose a transporter' : 'Choose a booking'} />
        ) : view === 'transporters' ? (
          <TransporterView key={selected} id={selected} onEdit={(t) => setSheet({ kind: 'transporter', editing: t })} onBook={() => setSheet({ kind: 'booking', transporterId: selected })} />
        ) : (
          <BookingView key={selected} booking={allBookings.find((b) => b.id === selected)} loading={bookings.isPending} onOpenTransporter={(id) => set({ view: 'transporters', id })} />
        )}
      </SplitView>
      <TransporterSheet open={sheet?.kind === 'transporter'} editing={sheet?.kind === 'transporter' ? sheet.editing : undefined} onClose={() => setSheet(null)} onSaved={(id) => set({ view: 'transporters', id })} />
      <BookingSheet open={sheet?.kind === 'booking'} transporterId={sheet?.kind === 'booking' ? sheet.transporterId : undefined} onClose={() => setSheet(null)} onSaved={(b) => set({ view: 'bookings', id: b.id })} />
    </>
  )
}

function TransporterRow({ t, selected, onSelect }: { t: Transporter; selected: boolean; onSelect: () => void }) {
  const Icon = KIND_ICON[t.kind] ?? Truck
  return (
    <ListRow group="tp" selected={selected} onSelect={onSelect}>
      <div className="flex items-center gap-2.5">
        <span className="grid size-8 shrink-0 place-items-center rounded-full bg-white/7">
          <Icon size={15} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="truncate text-[13.5px] font-semibold">{t.name}</span>
            {!t.is_active ? <Badge>Closed</Badge> : null}
          </div>
          <div className="flex items-center gap-1.5 truncate text-[12px] text-fg-3">
            <span className="truncate">
              {t.kind_label} · {t.vehicle_count} vehicle{t.vehicle_count === 1 ? '' : 's'}
            </span>
            <Stars value={t.rating} size={10} />
          </div>
        </div>
        {n(t.balance) > 0 ? (
          <div className="text-right">
            <div className="num text-[12.5px] font-semibold">{fmtMoney(t.balance)}</div>
            <div className="text-[11px] text-fg-3">owed</div>
          </div>
        ) : null}
      </div>
    </ListRow>
  )
}

function TransporterView({ id, onEdit, onBook }: { id: string; onEdit: (t: TransporterFull) => void; onBook: () => void }) {
  const data = useQuery({ queryKey: ['transporters', id], queryFn: () => transporters.get(id) })
  const update = useAction(transporters.update, { success: 'Saved' })
  const confirm = useConfirm()
  const [tab, setTab] = useState('profile')
  const [paying, setPaying] = useState(false)
  if (data.isPending) return <Spinner />
  if (!data.data) return <Empty title="This transporter could not be loaded" />
  const t = data.data
  const Icon = KIND_ICON[t.kind] ?? Truck
  return (
    <>
      <InspectorHeader
        eyebrow={`${t.kind_label}${t.code ? ` · ${t.code}` : ''}`}
        title={
          <span key={t.name} className="flex min-w-0 items-center gap-3">
            <span className="icon-disc grid size-[34px] shrink-0 place-items-center rounded-full">
              <Icon size={16} />
            </span>
            <span className="min-w-0 truncate">{t.name}</span>
          </span>
        }
        badges={
          <>
            {!t.is_active ? <Badge>Closed</Badge> : null}
            {t.rating ? <Stars value={t.rating} /> : null}
          </>
        }
        meta={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            {t.phone ? <PhoneLink phone={t.phone} /> : null}
            {t.contact_person ? <span>{t.contact_person}</span> : null}
            {t.booking_channel ? <span>Books by {CHANNEL_LABEL[t.booking_channel] ?? t.booking_channel}</span> : null}
            {t.service_areas ? <span className="truncate">{t.service_areas}</span> : null}
          </span>
        }
        actions={
          <>
            <Button icon={<Pencil size={14} />} onClick={() => onEdit(t)}>
              Edit
            </Button>
            <Button icon={<IndianRupee size={14} />} onClick={() => setPaying(true)}>
              Record payment
            </Button>
            <Button
              kind="ghost"
              icon={t.is_active ? <Ban size={14} /> : <RotateCcw size={14} />}
              onClick={async () => {
                if (!t.is_active) return update.mutate({ id, is_active: true })
                const answer = await confirm.ask({ title: `Close ${t.name}?`, body: 'Their trips and statement stay. They no longer appear when choosing a transporter.', confirm: 'Close', danger: true })
                if (answer.ok) update.mutate({ id, is_active: false })
              }}
            >
              {t.is_active ? 'Close' : 'Reopen'}
            </Button>
            <Button kind="primary" icon={<Truck size={14} />} disabled={!t.is_active} onClick={onBook}>
              Book a vehicle
            </Button>
          </>
        }
      />
      <FigureStrip
        items={[
          { label: 'Owed', value: fmtMoney(t.statement?.balance ?? t.balance), tone: n(t.statement?.balance ?? t.balance) > 0 ? 'sky' : undefined, hint: t.payment_terms_days ? `${t.payment_terms_days} day terms` : 'freight not yet paid' },
          { label: 'Overdue', value: fmtMoney(t.statement?.overdue ?? 0), tone: n(t.statement?.overdue) > 0 ? 'bad' : undefined, hint: 'past their terms' },
          { label: 'Trips', value: String(t.trips.length) },
          { label: 'Vehicles', value: String(t.vehicles.length), hint: t.vehicle_types.map((v) => VEHICLE_LABEL[v as keyof typeof VEHICLE_LABEL] ?? v).join(', ') || undefined },
          { label: 'Rate lines', value: String(t.rates.length) },
        ]}
      />
      <Tabs
        value={tab}
        onChange={setTab}
        className="min-h-0 flex-1"
        tabs={[
          { value: 'profile', label: 'Profile' },
          { value: 'vehicles', label: 'Vehicles', count: t.vehicles.length },
          { value: 'rates', label: 'Rate card', count: t.rates.length },
          { value: 'trips', label: 'Trips', count: t.trips.length },
          { value: 'bookings', label: 'Bookings', count: t.bookings.length },
          { value: 'statement', label: 'Statement' },
        ]}
      >
        <TabPanel value="profile">
          <DetailsCard t={t} />
          <PartyProfile kind="transporter" id={id} />
        </TabPanel>
        <TabPanel value="vehicles">
          <Vehicles t={t} />
        </TabPanel>
        <TabPanel value="rates">
          <RateCard t={t} />
        </TabPanel>
        <TabPanel value="trips">
          <Trips trips={t.trips} />
        </TabPanel>
        <TabPanel value="bookings">
          <Section
            title="Bookings"
            actions={
              <Button small icon={<Plus size={13} />} disabled={!t.is_active} onClick={onBook}>
                Book a vehicle
              </Button>
            }
          >
            <BookingTable items={t.bookings} />
          </Section>
        </TabPanel>
        <TabPanel value="statement">
          <Statement id={id} />
        </TabPanel>
      </Tabs>
      <PaySheet open={paying} t={t} onClose={() => setPaying(false)} />
      {confirm.element}
    </>
  )
}

function DetailsCard({ t }: { t: TransporterFull }) {
  const rows: [string, ReactNode][] = [
    ['GSTIN', t.gstin],
    ['PAN', t.pan],
    ['Tally ledger', t.tally_ledger_name],
    ['Payment terms', t.payment_terms_days != null ? `${t.payment_terms_days} days` : null],
    ['Booking channel', t.booking_channel ? CHANNEL_LABEL[t.booking_channel] ?? t.booking_channel : null],
    ['Service areas', t.service_areas],
    ['Contact person', t.contact_person],
    ['Email', t.email],
    ['Address', t.address],
  ]
  return (
    <Section title="Details">
      <div className="card grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-x-6 gap-y-3 p-4">
        {rows.map(([label, value]) => (
          <div key={label} className="min-w-0">
            <div className="text-[11.5px] text-fg-3">{label}</div>
            <div className="text-[13px] break-words">{value || <span className="text-fg-4">—</span>}</div>
          </div>
        ))}
        {t.notes ? (
          <div className="col-span-full">
            <div className="text-[11.5px] text-fg-3">Notes</div>
            <p className="text-[13px] whitespace-pre-line">{t.notes}</p>
          </div>
        ) : null}
      </div>
    </Section>
  )
}

/* ---------------------------------------------------------------- vehicles */

function Vehicles({ t }: { t: TransporterFull }) {
  const [editing, setEditing] = useState<null | { vehicle?: Vehicle }>(null)
  const confirm = useConfirm()
  const remove = useAction(transporters.removeVehicle, { success: 'Vehicle removed' })
  return (
    <Section
      title="Vehicles"
      hint="Their trucks and tempos, with drivers to call."
      actions={
        <Button small icon={<Plus size={13} />} onClick={() => setEditing({})}>
          Add vehicle
        </Button>
      }
    >
      {t.vehicles.length ? (
        <div className="overflow-x-auto">
          <table className="grid-table min-w-[620px]">
            <thead>
              <tr>
                <th>Vehicle</th>
                <th>Type</th>
                <th className="r">Capacity</th>
                <th>Driver</th>
                <th className="w-[80px]" />
              </tr>
            </thead>
            <tbody>
              {t.vehicles.map((v) => (
                <tr key={v.id} className={cn(!v.is_active && 'opacity-55')}>
                  <td>
                    <div className="num text-[13px] font-semibold">{v.number}</div>
                    {v.notes ? <div className="text-[11.5px] text-fg-3">{v.notes}</div> : null}
                    {!v.is_active ? <Badge>Not in use</Badge> : null}
                  </td>
                  <td className="text-[13px]">{v.vehicle_label}</td>
                  <td className="r num">{v.capacity_kg != null && n(v.capacity_kg) > 0 ? `${fmtQty(v.capacity_kg)} kg` : '—'}</td>
                  <td className="text-[12.5px]">
                    <div>{v.driver_name ?? '—'}</div>
                    <PhoneLink phone={v.driver_phone} />
                  </td>
                  <td>
                    <div className="flex justify-end gap-1">
                      <Button small kind="ghost" iconOnly aria-label="Edit vehicle" onClick={() => setEditing({ vehicle: v })}>
                        <Pencil size={13} />
                      </Button>
                      <Button
                        small
                        kind="ghost"
                        iconOnly
                        aria-label="Remove vehicle"
                        onClick={async () => {
                          const answer = await confirm.ask({ title: `Remove ${v.number}?`, confirm: 'Remove', danger: true })
                          if (answer.ok) remove.mutate({ id: t.id, vehicleId: v.id })
                        }}
                      >
                        <Trash2 size={13} />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty icon={<Truck size={20} />} title="No vehicles yet" body="Add their vehicles so bookings and trips can name them." />
      )}
      <VehicleSheet transporterId={t.id} open={editing !== null} vehicle={editing?.vehicle} onClose={() => setEditing(null)} />
      {confirm.element}
    </Section>
  )
}

function VehicleSheet({ transporterId, open, vehicle, onClose }: { transporterId: string; open: boolean; vehicle?: Vehicle; onClose: () => void }) {
  const meta = useTransporterMeta()
  const blank = { number: '', vehicle_type: 'lcv', capacity_kg: '', driver_name: '', driver_phone: '', notes: '', is_active: true }
  const [form, setForm] = useState(blank)
  useEffect(() => {
    if (open)
      setForm(
        vehicle
          ? {
              number: vehicle.number,
              vehicle_type: vehicle.vehicle_type,
              capacity_kg: vehicle.capacity_kg != null ? String(vehicle.capacity_kg) : '',
              driver_name: vehicle.driver_name ?? '',
              driver_phone: vehicle.driver_phone ?? '',
              notes: vehicle.notes ?? '',
              is_active: vehicle.is_active,
            }
          : blank,
      )
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps
  const save = useAction(
    () => {
      const body: VehicleIn = { ...form, capacity_kg: form.capacity_kg || null, driver_name: form.driver_name || null, driver_phone: form.driver_phone || null, notes: form.notes || null }
      return vehicle ? transporters.updateVehicle({ id: transporterId, vehicleId: vehicle.id, ...body }) : transporters.addVehicle({ id: transporterId, ...body })
    },
    { success: 'Vehicle saved', quiet: true },
  )
  const set = (key: 'number' | 'vehicle_type' | 'capacity_kg' | 'driver_name' | 'driver_phone' | 'notes') => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const value = e.target.value
    setForm((f) => ({ ...f, [key]: value }))
  }
  return (
    <Sheet
      open={open}
      onClose={onClose}
      width={560}
      title={vehicle ? `Edit ${vehicle.number}` : 'Add vehicle'}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button kind="primary" busy={save.isPending} disabled={!form.number.trim()} onClick={() => save.mutate(undefined, { onSuccess: onClose })}>
            Save
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-2 gap-4 max-md:grid-cols-1">
        {save.error ? (
          <div className="col-span-full">
            <Notice tone="bad">{errorText(save.error)}</Notice>
          </div>
        ) : null}
        <Field label="Vehicle number">
          {(props) => <input {...props} autoFocus className="field" value={form.number} onChange={set('number')} placeholder="GJ01AB1234" />}
        </Field>
        <Field label="Type">
          {(props) => (
            <select {...props} className="field" value={form.vehicle_type} onChange={set('vehicle_type')}>
              {Object.entries(meta.vehicles).map(([k, label]) => (
                <option key={k} value={k}>
                  {label}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Capacity (kg)" optional>
          {(props) => <input {...props} className="field field-num" inputMode="decimal" value={form.capacity_kg} onChange={set('capacity_kg')} />}
        </Field>
        <Field label="Driver" optional>
          {(props) => <input {...props} className="field" value={form.driver_name} onChange={set('driver_name')} />}
        </Field>
        <Field label="Driver phone" optional>
          {(props) => <input {...props} className="field" inputMode="tel" value={form.driver_phone} onChange={set('driver_phone')} />}
        </Field>
        <Field label="Notes" optional>
          {(props) => <input {...props} className="field" value={form.notes} onChange={set('notes')} />}
        </Field>
        <label className="col-span-full flex items-center gap-2 text-[13px]">
          <input type="checkbox" checked={form.is_active} onChange={(e) => { const v = e.target.checked; setForm((f) => ({ ...f, is_active: v })) }} />
          In use
        </label>
      </div>
    </Sheet>
  )
}

/* ---------------------------------------------------------------- rate card */

const routeOf = (r: { from_place: string | null; to_place: string | null }) => (r.from_place || r.to_place ? `${r.from_place || 'Anywhere'} → ${r.to_place || 'Anywhere'}` : 'Any route')

function RateCard({ t }: { t: TransporterFull }) {
  const [editing, setEditing] = useState<null | { rate?: RateLine }>(null)
  const confirm = useConfirm()
  const remove = useAction(transporters.removeRate, { success: 'Rate line removed' })
  const groups = new Map<string, RateLine[]>()
  for (const r of t.rates) {
    const key = routeOf(r)
    groups.set(key, [...(groups.get(key) ?? []), r])
  }
  return (
    <>
      <Section
        title="Rate card"
        hint="What they charge per route and vehicle. Used to estimate freight and compare transporters."
        actions={
          <Button small icon={<Plus size={13} />} onClick={() => setEditing({})}>
            Add rate
          </Button>
        }
      >
        {t.rates.length ? (
          <div className="overflow-x-auto">
            <table className="grid-table min-w-[720px]">
              <thead>
                <tr>
                  <th>Vehicle</th>
                  <th>Basis</th>
                  <th className="r">Rate</th>
                  <th className="r">Min charge</th>
                  <th>Valid</th>
                  <th className="w-[80px]" />
                </tr>
              </thead>
              <tbody>
                {[...groups.entries()].map(([route, rates]) => (
                  <RateGroup
                    key={route}
                    route={route}
                    rates={rates}
                    onEdit={(rate) => setEditing({ rate })}
                    onRemove={async (rate) => {
                      const answer = await confirm.ask({ title: 'Remove this rate line?', body: `${route} · ${rate.vehicle_label ?? 'Any vehicle'}`, confirm: 'Remove', danger: true })
                      if (answer.ok) remove.mutate({ id: t.id, rateId: rate.id })
                    }}
                  />
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty icon={<ClipboardList size={20} />} title="No rates yet" body="Add what they charge for a route and vehicle." />
        )}
      </Section>
      <Section title="Estimate freight" hint="From this transporter's rate card.">
        <Estimator transporterId={t.id} />
      </Section>
      <RateSheet transporterId={t.id} open={editing !== null} rate={editing?.rate} onClose={() => setEditing(null)} />
      {confirm.element}
    </>
  )
}

function RateGroup({ route, rates, onEdit, onRemove }: { route: string; rates: RateLine[]; onEdit: (r: RateLine) => void; onRemove: (r: RateLine) => void }) {
  return (
    <>
      <tr>
        <td colSpan={6} className="bg-white/[0.03]">
          <span className="flex items-center gap-1.5 text-[12.5px] font-semibold">
            <Route size={13} /> {route}
          </span>
        </td>
      </tr>
      {rates.map((r) => (
        <tr key={r.id} className={cn(!r.is_active && 'opacity-55')}>
          <td className="text-[13px]">
            {r.vehicle_label ?? 'Any vehicle'}
            {r.loading_included ? <div className="text-[11.5px] text-fg-3">Loading included</div> : null}
            {r.notes ? <div className="text-[11.5px] text-fg-3">{r.notes}</div> : null}
          </td>
          <td className="text-[13px]">{r.basis_label}</td>
          <td className="r num font-semibold">{fmtMoney(r.rate)}</td>
          <td className="r num">{r.min_charge != null && n(r.min_charge) > 0 ? fmtMoney(r.min_charge) : '—'}</td>
          <td className="text-[12px] text-fg-3">
            {r.valid_from || r.valid_until ? `${r.valid_from ? fmtDate(r.valid_from) : '…'} – ${r.valid_until ? fmtDate(r.valid_until) : '…'}` : 'Always'}
            {!r.is_active ? <div>Off</div> : null}
          </td>
          <td>
            <div className="flex justify-end gap-1">
              <Button small kind="ghost" iconOnly aria-label="Edit rate" onClick={() => onEdit(r)}>
                <Pencil size={13} />
              </Button>
              <Button small kind="ghost" iconOnly aria-label="Remove rate" onClick={() => onRemove(r)}>
                <Trash2 size={13} />
              </Button>
            </div>
          </td>
        </tr>
      ))}
    </>
  )
}

function Estimator({ transporterId }: { transporterId: string }) {
  const meta = useTransporterMeta()
  const [form, setForm] = useState({ from_place: '', to_place: '', vehicle_type: '', weight_kg: '', units: '', km: '', hours: '' })
  const q = useDebounced(form)
  const any = Object.values(q).some(Boolean)
  const est = useQuery({
    queryKey: ['transporters', 'estimate', transporterId, q],
    queryFn: () => transporters.estimate({ ...Object.fromEntries(Object.entries(q).filter(([, v]) => v)), transporter_id: transporterId }),
    enabled: any,
  })
  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const value = e.target.value
    setForm((f) => ({ ...f, [key]: value }))
  }
  return (
    <div className="card space-y-3 p-4">
      <div className="grid grid-cols-[repeat(auto-fit,minmax(130px,1fr))] gap-2">
        <input className="field field-sm" aria-label="From" placeholder="From" value={form.from_place} onChange={set('from_place')} />
        <input className="field field-sm" aria-label="To" placeholder="To" value={form.to_place} onChange={set('to_place')} />
        <select className="field field-sm" aria-label="Vehicle type" value={form.vehicle_type} onChange={set('vehicle_type')}>
          <option value="">Any vehicle</option>
          {Object.entries(meta.vehicles).map(([k, label]) => (
            <option key={k} value={k}>
              {label}
            </option>
          ))}
        </select>
        <input className="field field-sm field-num" inputMode="decimal" aria-label="Weight in kg" placeholder="Weight kg" value={form.weight_kg} onChange={set('weight_kg')} />
        <input className="field field-sm field-num" inputMode="decimal" aria-label="Units" placeholder="Units" value={form.units} onChange={set('units')} />
        <input className="field field-sm field-num" inputMode="decimal" aria-label="Kilometres" placeholder="Km" value={form.km} onChange={set('km')} />
        <input className="field field-sm field-num" inputMode="decimal" aria-label="Hours" placeholder="Hours" value={form.hours} onChange={set('hours')} />
      </div>
      {!any ? (
        <p className="text-[12px] text-fg-3">Enter a route, vehicle or load to see what it would cost.</p>
      ) : est.isPending ? (
        <Spinner />
      ) : est.data?.items.length ? (
        <div className="divide-y divide-white/6">
          {est.data.items.map((r) => (
            <div key={r.rate_id} className="flex flex-wrap items-center gap-x-3 gap-y-0.5 py-2 text-[12.5px]">
              <span className="font-medium">{r.route}</span>
              <span className="text-fg-3">
                {r.vehicle_label ?? 'Any vehicle'} · {fmtMoney(r.rate)} {meta.bases[r.basis]?.toLowerCase() ?? r.basis}
              </span>
              {r.note ? <span className="text-[11.5px] text-fg-3">{r.note}</span> : null}
              <span className="num ml-auto text-[14px] font-semibold">{r.amount != null ? fmtMoney(r.amount) : '—'}</span>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-[12px] text-fg-3">No rate line matches.</p>
      )}
    </div>
  )
}

const today = () => new Date().toISOString().slice(0, 10)

function RateSheet({ transporterId, open, rate, onClose }: { transporterId: string; open: boolean; rate?: RateLine; onClose: () => void }) {
  const meta = useTransporterMeta()
  const blank = { from_place: '', to_place: '', vehicle_type: '', basis: 'trip', rate: '', min_charge: '', loading_included: false, valid_from: '', valid_until: '', notes: '', is_active: true }
  const [form, setForm] = useState(blank)
  useEffect(() => {
    if (open)
      setForm(
        rate
          ? {
              from_place: rate.from_place ?? '',
              to_place: rate.to_place ?? '',
              vehicle_type: rate.vehicle_type ?? '',
              basis: rate.basis,
              rate: String(rate.rate),
              min_charge: rate.min_charge != null ? String(rate.min_charge) : '',
              loading_included: rate.loading_included,
              valid_from: rate.valid_from?.slice(0, 10) ?? '',
              valid_until: rate.valid_until?.slice(0, 10) ?? '',
              notes: rate.notes ?? '',
              is_active: rate.is_active,
            }
          : blank,
      )
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps
  const save = useAction(
    () => {
      const body: RateIn = {
        ...form,
        from_place: form.from_place || null,
        to_place: form.to_place || null,
        vehicle_type: form.vehicle_type || null,
        min_charge: form.min_charge || null,
        valid_from: form.valid_from || null,
        valid_until: form.valid_until || null,
        notes: form.notes || null,
      }
      return rate ? transporters.updateRate({ id: transporterId, rateId: rate.id, ...body }) : transporters.addRate({ id: transporterId, ...body })
    },
    { success: 'Rate saved', quiet: true },
  )
  const set = (key: 'from_place' | 'to_place' | 'vehicle_type' | 'basis' | 'rate' | 'min_charge' | 'valid_from' | 'valid_until' | 'notes') => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const value = e.target.value
    setForm((f) => ({ ...f, [key]: value }))
  }
  return (
    <Sheet
      open={open}
      onClose={onClose}
      width={620}
      title={rate ? 'Edit rate' : 'Add rate'}
      subtitle="Leave a place empty to match any."
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button kind="primary" busy={save.isPending} disabled={!(n(form.rate) > 0)} onClick={() => save.mutate(undefined, { onSuccess: onClose })}>
            Save
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-2 gap-4 max-md:grid-cols-1">
        {save.error ? (
          <div className="col-span-full">
            <Notice tone="bad">{errorText(save.error)}</Notice>
          </div>
        ) : null}
        <Field label="From" optional>
          {(props) => <input {...props} autoFocus className="field" value={form.from_place} onChange={set('from_place')} placeholder="e.g. Changodar" />}
        </Field>
        <Field label="To" optional>
          {(props) => <input {...props} className="field" value={form.to_place} onChange={set('to_place')} placeholder="e.g. Sanand" />}
        </Field>
        <Field label="Vehicle type" optional>
          {(props) => (
            <select {...props} className="field" value={form.vehicle_type} onChange={set('vehicle_type')}>
              <option value="">Any vehicle</option>
              {Object.entries(meta.vehicles).map(([k, label]) => (
                <option key={k} value={k}>
                  {label}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Charged">
          {(props) => (
            <select {...props} className="field" value={form.basis} onChange={set('basis')}>
              {Object.entries(meta.bases).map(([k, label]) => (
                <option key={k} value={k}>
                  {label}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Rate">
          {(props) => <input {...props} className="field field-num" inputMode="decimal" placeholder="₹" value={form.rate} onChange={set('rate')} />}
        </Field>
        <Field label="Minimum charge" optional>
          {(props) => <input {...props} className="field field-num" inputMode="decimal" placeholder="₹" value={form.min_charge} onChange={set('min_charge')} />}
        </Field>
        <Field label="Valid from" optional>
          {(props) => <input {...props} type="date" className="field" value={form.valid_from} onChange={set('valid_from')} />}
        </Field>
        <Field label="Valid until" optional>
          {(props) => <input {...props} type="date" className="field" value={form.valid_until} onChange={set('valid_until')} />}
        </Field>
        <Field label="Notes" optional className="col-span-full">
          {(props) => <input {...props} className="field" value={form.notes} onChange={set('notes')} />}
        </Field>
        <label className="flex items-center gap-2 text-[13px]">
          <input type="checkbox" checked={form.loading_included} onChange={(e) => { const v = e.target.checked; setForm((f) => ({ ...f, loading_included: v })) }} />
          Loading included
        </label>
        <label className="flex items-center gap-2 text-[13px]">
          <input type="checkbox" checked={form.is_active} onChange={(e) => { const v = e.target.checked; setForm((f) => ({ ...f, is_active: v })) }} />
          In use
        </label>
      </div>
    </Sheet>
  )
}

/* ---------------------------------------------------------------- trips, bookings, statement */

function Trips({ trips }: { trips: Trip[] }) {
  if (!trips.length) return <Empty icon={<Truck size={20} />} title="No trips yet" body="Deliveries, receipts and transfers that name this transporter show here." />
  return (
    <Section>
      <div className="overflow-x-auto">
        <table className="grid-table min-w-[640px]">
          <thead>
            <tr>
              <th>Date</th>
              <th>Kind</th>
              <th>Number</th>
              <th>Vehicle</th>
              <th>LR</th>
              <th className="r">Amount</th>
            </tr>
          </thead>
          <tbody>
            {trips.map((trip) => (
              <tr key={`${trip.kind}-${trip.id}`}>
                <td className="text-[12.5px]">{fmtDate(trip.date)}</td>
                <td>
                  <Badge tone={TRIP_TONE[trip.kind] ?? 'muted'}>{TRIP_LABEL[trip.kind] ?? trip.kind}</Badge>
                </td>
                <td className="num text-[13px] font-medium">{trip.number}</td>
                <td className="num text-[12.5px]">{trip.vehicle ?? '—'}</td>
                <td className="num text-[12.5px]">{trip.lr_number ?? '—'}</td>
                <td className="r num">
                  {trip.amount != null && n(trip.amount) ? fmtMoney(trip.amount) : '—'}
                  {trip.charge ? <div className="text-[11px] text-fg-3">{trip.charge}</div> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  )
}

function BookingTable({ items }: { items: Booking[] }) {
  const [, setParams] = useSearchParams()
  if (!items.length) return <Empty icon={<CalendarClock size={20} />} title="No bookings yet" />
  return (
    <div className="overflow-x-auto">
      <table className="grid-table min-w-[760px]">
        <thead>
          <tr>
            <th>Booking</th>
            <th>Route</th>
            <th>Vehicle</th>
            <th>Status</th>
            <th className="r">Amount</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {items.map((b) => (
            <tr key={b.id} className="cursor-pointer hover:bg-white/[0.03]" onClick={() => setParams({ view: 'bookings', id: b.id })}>
              <td>
                <div className="text-[13px] font-semibold">{b.number}</div>
                <div className="text-[11.5px] text-fg-3">{b.needed_at ? `needed ${fmtDateTime(b.needed_at)}` : fmtDate(b.created_at)}</div>
              </td>
              <td className="text-[12.5px]">
                {b.from_place || '—'} → {b.to_place || '—'}
                {b.reference_number ? <div className="text-[11.5px] text-fg-3">for {b.reference_number}</div> : null}
              </td>
              <td className="text-[12.5px]">
                {b.vehicle_number ?? b.vehicle_label ?? '—'}
                {b.vehicle_number && b.vehicle_label ? <div className="text-[11.5px] text-fg-3">{b.vehicle_label}</div> : null}
              </td>
              <td>
                <BookingBadge status={b.status} />
              </td>
              <td className="r num">{bookingAmount(b)}</td>
              <td>
                <BookingActions booking={b} small />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Statement({ id }: { id: string }) {
  const data = useQuery({ queryKey: ['transporters', id, 'statement'], queryFn: () => transporters.statement(id) })
  if (data.isPending) return <Spinner />
  if (!data.data) return <Empty title="Statement could not be loaded" />
  const { summary, entries } = data.data
  return (
    <Section>
      <div className="mb-4 grid grid-cols-[repeat(auto-fit,minmax(140px,1fr))] gap-3">
        {[
          ['Billed', summary.billed],
          ['Paid', summary.paid],
          ['Balance', summary.balance],
          ['Overdue', summary.overdue],
        ].map(([label, value]) => (
          <div key={label as string} className="card p-3">
            <div className="text-[11.5px] text-fg-3">{label}</div>
            <div className={cn('num text-[17px] font-semibold', label === 'Overdue' && n(value) > 0 && 'text-bad')}>{fmtMoney(value)}</div>
          </div>
        ))}
      </div>
      {entries.length ? (
        <div className="overflow-x-auto">
          <table className="grid-table min-w-[640px]">
            <thead>
              <tr>
                <th>Date</th>
                <th>Entry</th>
                <th className="r">Charged</th>
                <th className="r">Paid</th>
                <th className="r">Balance</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e, i) => (
                <tr key={`${e.id ?? i}-${i}`}>
                  <td className="text-[12.5px]">{fmtDate(e.date)}</td>
                  <td>
                    <div className="text-[13px] font-medium">
                      {e.kind}
                      {e.number ? <span className="num ml-1.5 text-fg-2">{e.number}</span> : null}
                    </div>
                    {e.detail ? <div className="text-[11.5px] text-fg-3">{e.detail}</div> : null}
                  </td>
                  <td className="r num">{n(e.debit) ? fmtMoney(e.debit) : ''}</td>
                  <td className="r num">{n(e.credit) ? fmtMoney(e.credit) : ''}</td>
                  <td className="r num font-semibold">{fmtMoney(e.balance)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty icon={<ReceiptText size={20} />} title="Nothing on the statement yet" />
      )}
    </Section>
  )
}

/* ---------------------------------------------------------------- booking view */

function BookingView({ booking, loading, onOpenTransporter }: { booking?: Booking; loading: boolean; onOpenTransporter: (id: string) => void }) {
  if (loading) return <Spinner />
  if (!booking) return <Empty title="Booking not found" />
  const b = booking
  const facts: [string, ReactNode][] = [
    ['Transporter', b.transporter_id ? (
      <button className="text-sky hover:underline" onClick={() => onOpenTransporter(b.transporter_id!)}>
        {b.transporter}
      </button>
    ) : 'Not chosen'],
    ['Purpose', b.purpose],
    ['For', b.reference_number],
    ['Needed at', b.needed_at ? fmtDateTime(b.needed_at) : null],
    ['Vehicle type', b.vehicle_label],
    ['Load', b.load],
    ['Weight', b.weight_kg != null && n(b.weight_kg) ? `${fmtQty(b.weight_kg)} kg` : null],
    ['Vehicle number', b.vehicle_number],
    ['Driver phone', b.driver_phone ? <PhoneLink phone={b.driver_phone} /> : null],
    ['Requested by', b.requested_by ? { person: 'A person', system: 'Automation', tai: 'Assistant', pai: 'Assistant' }[b.requested_by] : null],
    ['Channel', b.channel ? CHANNEL_LABEL[b.channel] ?? b.channel : null],
    ['Confirmed', b.confirmed_at ? fmtDateTime(b.confirmed_at) : null],
  ]
  return (
    <>
      <InspectorHeader
        eyebrow="Vehicle booking"
        title={b.number}
        badges={<BookingBadge status={b.status} />}
        meta={`${b.from_place || '—'} → ${b.to_place || '—'} · created ${fmtDateTime(b.created_at)}`}
        actions={<BookingActions booking={b} />}
      />
      <FigureStrip
        items={[
          { label: 'Estimate', value: b.estimate != null ? fmtMoney(b.estimate) : '—', hint: 'from the rate card' },
          { label: 'Agreed amount', value: b.agreed_amount != null && n(b.agreed_amount) ? fmtMoney(b.agreed_amount) : '—', tone: b.agreed_amount != null && n(b.agreed_amount) ? 'sky' : undefined },
          { label: 'Status', value: BOOKING_STATUS[b.status]?.label ?? b.status },
        ]}
      />
      <div className="min-h-0 flex-1 overflow-y-auto pb-20">
        <Section title="Details">
          <div className="card grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-x-6 gap-y-3 p-4">
            {facts.map(([label, value]) => (
              <div key={label} className="min-w-0">
                <div className="text-[11.5px] text-fg-3">{label}</div>
                <div className="text-[13px] break-words">{value || <span className="text-fg-4">—</span>}</div>
              </div>
            ))}
          </div>
        </Section>
        {b.reply ? (
          <Section title="Their reply">
            <div className="card flex gap-2.5 p-4 text-[13px]">
              <MessageCircle size={15} className="mt-0.5 shrink-0 text-fg-3" />
              <p className="whitespace-pre-line">{b.reply}</p>
            </div>
          </Section>
        ) : null}
        {b.notes ? (
          <Section title="Notes">
            <p className="text-[13px] whitespace-pre-line text-fg-2">{b.notes}</p>
          </Section>
        ) : null}
      </div>
    </>
  )
}

/* ---------------------------------------------------------------- payment */

const METHODS = [
  ['bank', 'Bank'],
  ['upi', 'UPI'],
  ['cash', 'Cash'],
  ['cheque', 'Cheque'],
  ['card', 'Card'],
  ['other', 'Other'],
] as const

function PaySheet({ open, t, onClose }: { open: boolean; t: TransporterFull; onClose: () => void }) {
  const owed = n(t.statement?.balance ?? t.balance)
  const [form, setForm] = useState({ amount: '', method: 'bank' as (typeof METHODS)[number][0], reference: '', paid_on: today(), notes: '' })
  useEffect(() => {
    if (open) setForm({ amount: owed > 0 ? String(owed) : '', method: 'bank', reference: '', paid_on: today(), notes: '' })
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps
  const save = useAction(
    () => transporters.pay({ transporter_id: t.id, amount: form.amount, method: form.method, reference: form.reference || null, notes: form.notes || null, paid_on: form.paid_on || null }),
    { success: 'Payment recorded', quiet: true },
  )
  return (
    <Sheet
      open={open}
      onClose={onClose}
      width={520}
      title={`Pay ${t.name}`}
      subtitle={owed > 0 ? `You owe ${fmtMoney(owed)}.` : 'Nothing owed right now; this is recorded as an advance.'}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button kind="primary" icon={<IndianRupee size={14} />} busy={save.isPending} disabled={!(n(form.amount) > 0)} onClick={() => save.mutate(undefined, { onSuccess: onClose })}>
            Record payment
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {save.error ? <Notice tone="bad">{errorText(save.error)}</Notice> : null}
        <div className="grid grid-cols-2 gap-4 max-md:grid-cols-1">
          <Field label="Amount">
            {(props) => <input {...props} autoFocus className="field field-num" inputMode="decimal" placeholder="₹" value={form.amount} onChange={(e) => { const v = e.target.value; setForm((f) => ({ ...f, amount: v })) }} />}
          </Field>
          <Field label="Date">
            {(props) => <input {...props} type="date" className="field" value={form.paid_on} onChange={(e) => { const v = e.target.value; setForm((f) => ({ ...f, paid_on: v })) }} />}
          </Field>
        </div>
        <div>
          <div className="label">Method</div>
          <div className="flex flex-wrap gap-1.5">
            {METHODS.map(([k, label]) => (
              <button key={k} type="button" onClick={() => setForm((f) => ({ ...f, method: k }))} className={cn('h-8 rounded-full px-3 text-[12.5px] font-semibold', form.method === k ? 'brand-fill' : 'bg-ink-700 text-fg-2')}>
                {label}
              </button>
            ))}
          </div>
        </div>
        <Field label="Reference" optional hint="UTR, cheque number or receipt.">
          {(props) => <input {...props} className="field" value={form.reference} onChange={(e) => { const v = e.target.value; setForm((f) => ({ ...f, reference: v })) }} />}
        </Field>
        <Field label="Notes" optional>
          {(props) => <input {...props} className="field" value={form.notes} onChange={(e) => { const v = e.target.value; setForm((f) => ({ ...f, notes: v })) }} />}
        </Field>
      </div>
    </Sheet>
  )
}

/* ---------------------------------------------------------------- create / edit */

type VRow = { key: string; number: string; vehicle_type: string; capacity_kg: string; driver_name: string; driver_phone: string }
type RRow = { key: string; from_place: string; to_place: string; vehicle_type: string; basis: string; rate: string; min_charge: string }
const rowKey = () => Math.random().toString(36).slice(2)
const newV = (): VRow => ({ key: rowKey(), number: '', vehicle_type: 'lcv', capacity_kg: '', driver_name: '', driver_phone: '' })
const newR = (): RRow => ({ key: rowKey(), from_place: '', to_place: '', vehicle_type: '', basis: 'trip', rate: '', min_charge: '' })

const blankForm = {
  name: '',
  code: '',
  kind: 'company',
  contact_person: '',
  phone: '',
  email: '',
  address: '',
  gstin: '',
  pan: '',
  tally_ledger_name: '',
  service_areas: '',
  payment_terms_days: '',
  booking_channel: 'whatsapp' as 'whatsapp' | 'call' | 'either',
  rating: null as number | null,
  notes: '',
}
type FormKey = Exclude<keyof typeof blankForm, 'rating' | 'booking_channel'>

function TransporterSheet({ open, editing, onClose, onSaved }: { open: boolean; editing?: TransporterFull; onClose: () => void; onSaved: (id: string) => void }) {
  const meta = useTransporterMeta()
  const [form, setForm] = useState(blankForm)
  const [vehicles, setVehicles] = useState<VRow[]>([])
  const [rates, setRates] = useState<RRow[]>([])
  useEffect(() => {
    if (!open) return
    setForm(
      editing
        ? {
            name: editing.name,
            code: editing.code ?? '',
            kind: editing.kind,
            contact_person: editing.contact_person ?? '',
            phone: editing.phone ?? '',
            email: editing.email ?? '',
            address: editing.address ?? '',
            gstin: editing.gstin ?? '',
            pan: editing.pan ?? '',
            tally_ledger_name: editing.tally_ledger_name ?? '',
            service_areas: editing.service_areas ?? '',
            payment_terms_days: editing.payment_terms_days != null ? String(editing.payment_terms_days) : '',
            booking_channel: editing.booking_channel ?? 'whatsapp',
            rating: editing.rating,
            notes: editing.notes ?? '',
          }
        : blankForm,
    )
    setVehicles([])
    setRates([])
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps
  const save = useAction(
    () => {
      const opt = (v: string) => v.trim() || null
      const body: TransporterIn = {
        name: form.name.trim(),
        code: opt(form.code) ?? undefined,
        kind: form.kind,
        contact_person: opt(form.contact_person),
        phone: opt(form.phone),
        email: opt(form.email),
        address: opt(form.address),
        gstin: opt(form.gstin),
        pan: opt(form.pan),
        tally_ledger_name: opt(form.tally_ledger_name),
        service_areas: opt(form.service_areas),
        payment_terms_days: form.payment_terms_days ? Math.round(n(form.payment_terms_days)) : null,
        booking_channel: form.booking_channel,
        rating: form.rating,
        notes: opt(form.notes),
      }
      if (editing) return transporters.update({ id: editing.id, ...body })
      return transporters.create({
        ...body,
        vehicles: vehicles
          .filter((v) => v.number.trim())
          .map((v) => ({ number: v.number.trim(), vehicle_type: v.vehicle_type, capacity_kg: v.capacity_kg || null, driver_name: opt(v.driver_name), driver_phone: opt(v.driver_phone) })),
        rates: rates
          .filter((r) => n(r.rate) > 0)
          .map((r) => ({ from_place: opt(r.from_place), to_place: opt(r.to_place), vehicle_type: r.vehicle_type || null, basis: r.basis, rate: r.rate, min_charge: r.min_charge || null })),
      })
    },
    { success: (t) => `${t.name} saved`, quiet: true },
  )
  const set = (key: FormKey) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => {
    const value = e.target.value
    setForm((f) => ({ ...f, [key]: value }))
  }
  const setV = (key: string, patch: Partial<VRow>) => setVehicles((vs) => vs.map((v) => (v.key === key ? { ...v, ...patch } : v)))
  const setR = (key: string, patch: Partial<RRow>) => setRates((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)))
  const vehicleOptions = Object.entries(meta.vehicles)
  return (
    <Sheet
      open={open}
      onClose={onClose}
      width={860}
      title={editing ? `Edit ${editing.name}` : 'New transporter'}
      subtitle={editing ? undefined : 'Contacts, phone numbers and addresses can be added on their Profile after saving.'}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button kind="primary" busy={save.isPending} disabled={!form.name.trim()} onClick={() => save.mutate(undefined, { onSuccess: (t) => (onClose(), onSaved(t.id)) })}>
            Save
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-6 gap-4">
        {save.error ? (
          <div className="col-span-6">
            <Notice tone="bad">{errorText(save.error)}</Notice>
          </div>
        ) : null}
        <Field label="Name" className="col-span-4 max-md:col-span-6">
          {(props) => <input {...props} className="field" autoFocus value={form.name} onChange={set('name')} placeholder="e.g. Shree Ram Roadlines" />}
        </Field>
        <Field label="Code" optional className="col-span-2 max-md:col-span-6" hint="Made from the name if empty.">
          {(props) => <input {...props} className="field" value={form.code} onChange={set('code')} />}
        </Field>
        <div className="col-span-6">
          <div className="label">Kind</div>
          <div className="grid grid-cols-3 gap-2 max-md:grid-cols-2">
            {Object.entries(meta.kinds).map(([k, label]) => {
              const Icon = KIND_ICON[k] ?? Truck
              return (
                <button key={k} type="button" onClick={() => setForm((f) => ({ ...f, kind: k }))} className={cn('flex items-center gap-2 rounded-xl px-3 py-2.5 text-[13px] font-semibold', form.kind === k ? 'brand-fill' : 'bg-ink-700 text-fg-2')}>
                  <Icon size={15} className="shrink-0" /> <span className="truncate">{label}</span>
                </button>
              )
            })}
          </div>
        </div>
        <Field label="Contact person" optional className="col-span-2 max-md:col-span-6">
          {(props) => <input {...props} className="field" value={form.contact_person} onChange={set('contact_person')} />}
        </Field>
        <Field label="Phone" optional className="col-span-2 max-md:col-span-6">
          {(props) => <input {...props} className="field" inputMode="tel" value={form.phone} onChange={set('phone')} />}
        </Field>
        <Field label="Email" optional className="col-span-2 max-md:col-span-6">
          {(props) => <input {...props} className="field" type="email" value={form.email} onChange={set('email')} />}
        </Field>
        <Field label="Address" optional className="col-span-6">
          {(props) => <input {...props} className="field" value={form.address} onChange={set('address')} />}
        </Field>
        <Field label="Service areas" optional className="col-span-6" hint="Places and routes they run, e.g. Ahmedabad, Sanand, Mehsana.">
          {(props) => <input {...props} className="field" value={form.service_areas} onChange={set('service_areas')} />}
        </Field>
        <Field label="GSTIN" optional className="col-span-2 max-md:col-span-6">
          {(props) => <input {...props} className="field uppercase" value={form.gstin} onChange={set('gstin')} />}
        </Field>
        <Field label="PAN" optional className="col-span-2 max-md:col-span-6">
          {(props) => <input {...props} className="field uppercase" value={form.pan} onChange={set('pan')} />}
        </Field>
        <Field label="Payment terms (days)" optional className="col-span-2 max-md:col-span-6">
          {(props) => <input {...props} className="field field-num" inputMode="numeric" value={form.payment_terms_days} onChange={set('payment_terms_days')} />}
        </Field>
        <Field label="Tally ledger name" optional className="col-span-3 max-md:col-span-6" hint="Freight bills post to this ledger in Tally">
          {(props) => <input {...props} className="field" value={form.tally_ledger_name} onChange={set('tally_ledger_name')} />}
        </Field>
        <div className="col-span-3 max-md:col-span-6">
          <div className="label">Book by</div>
          <Segmented
            value={form.booking_channel}
            onChange={(v) => setForm((f) => ({ ...f, booking_channel: v }))}
            options={[
              { value: 'whatsapp', label: 'WhatsApp' },
              { value: 'call', label: 'Call' },
              { value: 'either', label: 'Either' },
            ]}
          />
        </div>
        <div className="col-span-6">
          <div className="label">Rating</div>
          <Stars value={form.rating} size={20} onChange={(v) => setForm((f) => ({ ...f, rating: v }))} />
        </div>
        <Field label="Notes" optional className="col-span-6">
          {(props) => <textarea {...props} className="field min-h-[64px] py-2" value={form.notes} onChange={set('notes')} />}
        </Field>

        {!editing ? (
          <>
            <div className="col-span-6">
              <div className="label flex items-center gap-1.5">
                <Truck size={13} /> Vehicles
              </div>
              <div className="space-y-2">
                {vehicles.map((v) => (
                  <div key={v.key} className="flex flex-wrap items-center gap-2">
                    <input className="field field-sm w-[130px]" aria-label="Vehicle number" placeholder="GJ01AB1234" value={v.number} onChange={(e) => setV(v.key, { number: e.target.value })} />
                    <select className="field field-sm w-[120px]" aria-label="Vehicle type" value={v.vehicle_type} onChange={(e) => setV(v.key, { vehicle_type: e.target.value })}>
                      {vehicleOptions.map(([k, label]) => (
                        <option key={k} value={k}>
                          {label}
                        </option>
                      ))}
                    </select>
                    <input className="field field-sm field-num w-[100px]" inputMode="decimal" aria-label="Capacity in kg" placeholder="Capacity kg" value={v.capacity_kg} onChange={(e) => setV(v.key, { capacity_kg: e.target.value })} />
                    <input className="field field-sm min-w-[110px] flex-1" aria-label="Driver" placeholder="Driver" value={v.driver_name} onChange={(e) => setV(v.key, { driver_name: e.target.value })} />
                    <input className="field field-sm w-[120px]" inputMode="tel" aria-label="Driver phone" placeholder="Driver phone" value={v.driver_phone} onChange={(e) => setV(v.key, { driver_phone: e.target.value })} />
                    <button className="grid size-7 place-items-center rounded-full text-fg-3 hover:bg-white/8" aria-label="Remove vehicle" onClick={() => setVehicles((vs) => vs.filter((x) => x.key !== v.key))}>
                      <Trash2 size={13} />
                    </button>
                  </div>
                ))}
              </div>
              <Button small className="mt-2" icon={<Plus size={13} />} onClick={() => setVehicles((vs) => [...vs, newV()])}>
                Add vehicle
              </Button>
            </div>
            <div className="col-span-6">
              <div className="label flex items-center gap-1.5">
                <Route size={13} /> Rate card
              </div>
              <div className="space-y-2">
                {rates.map((r) => (
                  <div key={r.key} className="flex flex-wrap items-center gap-2">
                    <input className="field field-sm min-w-[100px] flex-1" aria-label="From" placeholder="From" value={r.from_place} onChange={(e) => setR(r.key, { from_place: e.target.value })} />
                    <input className="field field-sm min-w-[100px] flex-1" aria-label="To" placeholder="To" value={r.to_place} onChange={(e) => setR(r.key, { to_place: e.target.value })} />
                    <select className="field field-sm w-[120px]" aria-label="Vehicle type" value={r.vehicle_type} onChange={(e) => setR(r.key, { vehicle_type: e.target.value })}>
                      <option value="">Any vehicle</option>
                      {vehicleOptions.map(([k, label]) => (
                        <option key={k} value={k}>
                          {label}
                        </option>
                      ))}
                    </select>
                    <select className="field field-sm w-[110px]" aria-label="Charged" value={r.basis} onChange={(e) => setR(r.key, { basis: e.target.value })}>
                      {Object.entries(meta.bases).map(([k, label]) => (
                        <option key={k} value={k}>
                          {label}
                        </option>
                      ))}
                    </select>
                    <input className="field field-sm field-num w-[90px]" inputMode="decimal" aria-label="Rate" placeholder="Rate ₹" value={r.rate} onChange={(e) => setR(r.key, { rate: e.target.value })} />
                    <input className="field field-sm field-num w-[90px]" inputMode="decimal" aria-label="Minimum charge" placeholder="Min ₹" value={r.min_charge} onChange={(e) => setR(r.key, { min_charge: e.target.value })} />
                    <button className="grid size-7 place-items-center rounded-full text-fg-3 hover:bg-white/8" aria-label="Remove rate" onClick={() => setRates((rs) => rs.filter((x) => x.key !== r.key))}>
                      <Trash2 size={13} />
                    </button>
                  </div>
                ))}
              </div>
              <Button small className="mt-2" icon={<Plus size={13} />} onClick={() => setRates((rs) => [...rs, newR()])}>
                Add rate
              </Button>
            </div>
          </>
        ) : null}
        {editing?.phone ? (
          <div className="col-span-6 flex items-center gap-1.5 text-[12px] text-fg-3">
            <Phone size={12} /> More phone numbers, emails and contacts are on the Profile tab.
          </div>
        ) : null}
      </div>
    </Sheet>
  )
}
