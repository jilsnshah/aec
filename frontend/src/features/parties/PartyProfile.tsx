import { useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Building2, Check, ExternalLink, Fingerprint, Mail, MapPin, MessageCircle, Phone, Plus, Star, Trash2, UserRound, Users } from 'lucide-react'
import { errorText } from '@/api/client'
import { useAction } from '@/api/queries'
import { parties, type PartyAddress, type PartyKind, type PartyProfile as Profile } from '@/api/parties'
import { cn } from '@/lib/cn'
import { Avatar, Badge, Button, Empty, Notice, Spinner } from '@/ui/core'

const wa = (phone: string) => `https://wa.me/${phone.replace(/\D/g, '').replace(/^(\d{10})$/, '91$1')}`
const ADDRESS_KIND: Record<PartyAddress['kind'], string> = { billing: 'Billing', site: 'Delivery site', office: 'Office', warehouse: 'Warehouse' }

/** Everything about a customer or supplier as a party: tax identity, people,
 *  every phone number and email, and every address and delivery site. */
export function PartyProfile({ kind, id }: { kind: PartyKind; id: string }) {
  const data = useQuery({ queryKey: ['parties', kind, id], queryFn: () => parties.profile(kind, id) })
  if (data.isPending) return <Spinner />
  if (!data.data) return <Empty title="Profile could not be loaded" />
  const p = data.data
  return (
    <div className="space-y-4 p-6 pb-24 max-md:p-4">
      <Identity profile={p} />
      <Points kind={kind} profile={p} />
      <Contacts kind={kind} profile={p} />
      <Addresses kind={kind} profile={p} />
    </div>
  )
}

function Card({ icon, title, hint, action, children }: { icon: ReactNode; title: string; hint?: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="card overflow-hidden">
      <header className="flex items-center gap-2.5 px-4 pt-3.5 pb-2">
        <span className="icon-disc size-7">{icon}</span>
        <div className="min-w-0 flex-1">
          <div className="text-[13.5px] font-semibold">{title}</div>
          {hint ? <div className="text-[11.5px] text-fg-3">{hint}</div> : null}
        </div>
        {action}
      </header>
      <div className="px-4 pb-4">{children}</div>
    </section>
  )
}

function Identity({ profile }: { profile: Profile }) {
  const rows = [
    ['GSTIN', profile.gstin],
    ['PAN', profile.pan],
    ['Tally ledger', profile.tally_ledger_name ?? `${profile.name} (set on first sync)`],
  ]
  return (
    <Card icon={<Fingerprint size={14} />} title="Identity" hint="GSTIN must be unique; change it under Edit details.">
      <div className="grid grid-cols-3 gap-3 max-md:grid-cols-1">
        {rows.map(([label, value]) => (
          <div key={label} className="rounded-xl bg-white/5 px-3 py-2">
            <div className="text-[11.5px] text-fg-3">{label}</div>
            <div className={cn('num truncate text-[13px] font-semibold', !value && 'font-normal text-fg-4')} data-selectable>
              {value || 'Not set'}
            </div>
          </div>
        ))}
      </div>
    </Card>
  )
}

function Points({ kind, profile }: { kind: PartyKind; profile: Profile }) {
  const [adding, setAdding] = useState(false)
  const [form, setForm] = useState({ kind: 'phone' as 'phone' | 'email', value: '', label: '', contact_id: '', is_whatsapp: true })
  const add = useAction(() => parties.addPoint(kind, profile.id, { ...form, contact_id: form.contact_id || null }), { success: 'Added', quiet: true })
  const update = useAction(({ pointId, body }: { pointId: string; body: Record<string, unknown> }) => parties.updatePoint(kind, profile.id, pointId, body))
  const contactName = (contactId: string | null) => profile.contacts.find((c) => c.id === contactId)?.name
  return (
    <Card
      icon={<Phone size={14} />}
      title="Phone numbers and emails"
      hint="Each number or email belongs to this party only, so WhatsApp, email and calls always find it."
      action={
        <Button small icon={<Plus size={13} />} onClick={() => setAdding(!adding)}>
          Add
        </Button>
      }
    >
      {adding ? (
        <div className="mb-3 space-y-2 rounded-xl bg-white/5 p-3">
          {add.error ? <Notice tone="bad">{errorText(add.error)}</Notice> : null}
          <div className="flex flex-wrap gap-2">
            {(['phone', 'email'] as const).map((k) => (
              <button key={k} onClick={() => setForm({ ...form, kind: k, is_whatsapp: k === 'phone' })} className={cn('h-[30px] rounded-full px-3 text-[12px] font-semibold', form.kind === k ? 'brand-fill' : 'bg-ink-700 text-fg-2')}>
                {k === 'phone' ? 'Phone' : 'Email'}
              </button>
            ))}
            <input className="field field-sm min-w-[180px] flex-1" placeholder={form.kind === 'phone' ? '98250 12345' : 'name@company.com'} value={form.value} onChange={(e) => setForm({ ...form, value: e.target.value })} />
            <input className="field field-sm w-[130px]" placeholder="Label (site, office)" value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} />
            <select className="field field-sm w-[150px]" value={form.contact_id} onChange={(e) => setForm({ ...form, contact_id: e.target.value })} aria-label="Contact">
              <option value="">Whole business</option>
              {profile.contacts.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
            {form.kind === 'phone' ? (
              <label className="flex items-center gap-1.5 text-[12px]">
                <input type="checkbox" checked={form.is_whatsapp} onChange={(e) => setForm({ ...form, is_whatsapp: e.target.checked })} /> WhatsApp
              </label>
            ) : null}
            <Button small kind="primary" busy={add.isPending} disabled={!form.value.trim()} onClick={() => add.mutate(undefined, { onSuccess: () => (setForm({ ...form, value: '', label: '' }), setAdding(false)) })}>
              Save
            </Button>
          </div>
        </div>
      ) : null}
      {!profile.points.length ? (
        <p className="text-[12.5px] text-fg-3">No numbers or emails yet.</p>
      ) : (
        <div className="divide-y divide-white/6">
          {profile.points.map((point) => (
            <div key={point.id} className="flex flex-wrap items-center gap-2.5 py-2">
              {point.kind === 'phone' ? <Phone size={14} className="text-fg-3" /> : <Mail size={14} className="text-fg-3" />}
              <a href={point.kind === 'phone' ? `tel:${point.value}` : `mailto:${point.value}`} className="num text-[13px] font-medium hover:underline" data-selectable>
                {point.value}
              </a>
              {point.label ? <Badge>{point.label}</Badge> : null}
              {point.is_whatsapp ? (
                <Badge tone="ok">
                  <MessageCircle size={11} /> WhatsApp
                </Badge>
              ) : null}
              {point.is_primary ? (
                <Badge tone="sky">
                  <Star size={11} /> Primary
                </Badge>
              ) : null}
              {contactName(point.contact_id) ? <span className="text-[12px] text-fg-3">· {contactName(point.contact_id)}</span> : null}
              <span className="flex-1" />
              {point.kind === 'phone' && point.is_whatsapp ? (
                <a className="btn btn-sm btn-ghost" href={wa(point.value)} target="_blank" rel="noreferrer" aria-label="WhatsApp">
                  <MessageCircle size={13} />
                </a>
              ) : null}
              {!point.is_primary ? (
                <Button small kind="ghost" onClick={() => update.mutate({ pointId: point.id, body: { is_primary: true } })}>
                  Make primary
                </Button>
              ) : null}
              <button className="grid size-7 place-items-center rounded-full text-fg-3 hover:bg-white/8" aria-label={`Remove ${point.value}`} onClick={() => update.mutate({ pointId: point.id, body: { is_active: false } })}>
                <Trash2 size={13} />
              </button>
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

function Contacts({ kind, profile }: { kind: PartyKind; profile: Profile }) {
  const [form, setForm] = useState({ name: '', role: '' })
  const add = useAction(() => parties.addContact(kind, profile.id, form), { success: 'Contact added', quiet: true })
  const update = useAction(({ contactId, body }: { contactId: string; body: Record<string, unknown> }) => parties.updateContact(kind, profile.id, contactId, body))
  return (
    <Card icon={<Users size={14} />} title="People" hint="Owner, site engineers, accounts: each can have their own numbers above.">
      <div className="divide-y divide-white/6">
        {profile.contacts.map((contact) => {
          const numbers = profile.points.filter((p) => p.contact_id === contact.id)
          return (
            <div key={contact.id} className="flex items-center gap-3 py-2">
              <Avatar name={contact.name} size={30} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 text-[13px] font-medium">
                  {contact.name}
                  {contact.is_primary ? (
                    <Badge tone="sky">
                      <Star size={11} /> Main
                    </Badge>
                  ) : null}
                </div>
                <div className="truncate text-[12px] text-fg-3">
                  {contact.role ?? 'No role'}
                  {numbers.length ? ` · ${numbers.map((n) => n.value).join(', ')}` : ''}
                </div>
              </div>
              {!contact.is_primary ? (
                <Button small kind="ghost" onClick={() => update.mutate({ contactId: contact.id, body: { is_primary: true } })}>
                  Make main
                </Button>
              ) : null}
              <button className="grid size-7 place-items-center rounded-full text-fg-3 hover:bg-white/8" aria-label={`Remove ${contact.name}`} onClick={() => update.mutate({ contactId: contact.id, body: { is_active: false } })}>
                <Trash2 size={13} />
              </button>
            </div>
          )
        })}
      </div>
      {add.error ? <Notice tone="bad">{errorText(add.error)}</Notice> : null}
      <div className="mt-2 flex flex-wrap gap-2">
        <input className="field field-sm min-w-[160px] flex-1" placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        <input className="field field-sm w-[180px]" placeholder="Role (site engineer, accounts)" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} />
        <Button small icon={<UserRound size={13} />} busy={add.isPending} disabled={!form.name.trim()} onClick={() => add.mutate(undefined, { onSuccess: () => setForm({ name: '', role: '' }) })}>
          Add person
        </Button>
      </div>
    </Card>
  )
}

function Addresses({ kind, profile }: { kind: PartyKind; profile: Profile }) {
  const blank = { kind: (kind === 'customer' ? 'site' : 'warehouse') as PartyAddress['kind'], label: '', line: '', city: '', pincode: '', map_url: '' }
  const [form, setForm] = useState(blank)
  const [adding, setAdding] = useState(false)
  const add = useAction(() => parties.addAddress(kind, profile.id, form), { success: 'Address added', quiet: true })
  const update = useAction(({ addressId, body }: { addressId: string; body: Record<string, unknown> }) => parties.updateAddress(kind, profile.id, addressId, body))
  return (
    <Card
      icon={<MapPin size={14} />}
      title={kind === 'customer' ? 'Addresses and delivery sites' : 'Addresses'}
      hint={kind === 'customer' ? 'Choose a site on each order or quote so deliveries go to the right place.' : undefined}
      action={
        <Button small icon={<Plus size={13} />} onClick={() => setAdding(!adding)}>
          Add
        </Button>
      }
    >
      {adding ? (
        <div className="mb-3 space-y-2 rounded-xl bg-white/5 p-3">
          {add.error ? <Notice tone="bad">{errorText(add.error)}</Notice> : null}
          <div className="flex flex-wrap gap-1.5">
            {(Object.keys(ADDRESS_KIND) as PartyAddress['kind'][]).map((k) => (
              <button key={k} onClick={() => setForm({ ...form, kind: k })} className={cn('h-[30px] rounded-full px-3 text-[12px] font-semibold', form.kind === k ? 'brand-fill' : 'bg-ink-700 text-fg-2')}>
                {ADDRESS_KIND[k]}
              </button>
            ))}
          </div>
          <div className="grid grid-cols-2 gap-2 max-md:grid-cols-1">
            <input className="field field-sm" placeholder={form.kind === 'site' ? 'Site name, e.g. Tower A, Sector 21' : 'Label'} value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} />
            <input className="field field-sm" placeholder="Address" value={form.line} onChange={(e) => setForm({ ...form, line: e.target.value })} />
            <input className="field field-sm" placeholder="City" value={form.city} onChange={(e) => setForm({ ...form, city: e.target.value })} />
            <input className="field field-sm" placeholder="PIN code" value={form.pincode} onChange={(e) => setForm({ ...form, pincode: e.target.value })} />
            <input className="field field-sm col-span-2 max-md:col-span-1" placeholder="Google Maps link (optional)" value={form.map_url} onChange={(e) => setForm({ ...form, map_url: e.target.value })} />
          </div>
          <Button small kind="primary" busy={add.isPending} disabled={!form.line.trim()} onClick={() => add.mutate(undefined, { onSuccess: () => (setForm(blank), setAdding(false)) })}>
            Save address
          </Button>
        </div>
      ) : null}
      {!profile.addresses.length ? (
        <p className="text-[12.5px] text-fg-3">No addresses yet.</p>
      ) : (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-2">
          {profile.addresses.map((address) => (
            <div key={address.id} className="rounded-xl bg-white/5 p-3">
              <div className="flex items-center gap-1.5">
                {address.kind === 'site' ? <Building2 size={13} /> : <MapPin size={13} />}
                <span className="truncate text-[13px] font-semibold">{address.label || ADDRESS_KIND[address.kind]}</span>
                <Badge>{ADDRESS_KIND[address.kind]}</Badge>
                {address.is_default ? (
                  <Badge tone="sky">
                    <Check size={11} /> Default
                  </Badge>
                ) : null}
              </div>
              <p className="mt-1 text-[12.5px] text-fg-2" data-selectable>
                {[address.line, address.city, address.state, address.pincode].filter(Boolean).join(', ')}
              </p>
              <div className="mt-2 flex gap-1.5">
                {address.map_url ? (
                  <a className="btn btn-sm btn-ghost" href={address.map_url} target="_blank" rel="noreferrer">
                    <ExternalLink size={12} /> Map
                  </a>
                ) : null}
                {!address.is_default ? (
                  <Button small kind="ghost" onClick={() => update.mutate({ addressId: address.id, body: { is_default: true } })}>
                    Make default
                  </Button>
                ) : null}
                <Button small kind="ghost" icon={<Trash2 size={12} />} onClick={() => update.mutate({ addressId: address.id, body: { is_active: false } })}>
                  Remove
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

/** Every number and email, plus delivery sites, for a record's side panel. */
export function PartyContactsAside({ kind, id }: { kind: PartyKind; id: string }) {
  const data = useQuery({ queryKey: ['parties', kind, id], queryFn: () => parties.profile(kind, id) })
  const p = data.data
  if (!p) return null
  const name = (contactId: string | null) => p.contacts.find((c) => c.id === contactId)?.name
  const sites = p.addresses.filter((a) => a.kind === 'site')
  return (
    <div className="space-y-2">
      {p.points.map((point) => (
        <div key={point.id} className="flex items-center gap-2 text-[13px]">
          {point.kind === 'phone' ? <Phone size={13} className="shrink-0 text-fg-3" /> : <Mail size={13} className="shrink-0 text-fg-3" />}
          <a href={point.kind === 'phone' ? `tel:${point.value}` : `mailto:${point.value}`} className="min-w-0 truncate hover:underline" data-selectable>
            {point.value}
          </a>
          <span className="truncate text-[11px] text-fg-3">{[name(point.contact_id), point.label].filter(Boolean).join(' · ')}</span>
          {point.kind === 'phone' && point.is_whatsapp ? (
            <a href={wa(point.value)} target="_blank" rel="noreferrer" className="ml-auto text-fg-3 hover:text-fg" aria-label="WhatsApp">
              <MessageCircle size={13} />
            </a>
          ) : null}
        </div>
      ))}
      {sites.length ? (
        <div className="pt-1">
          <div className="eyebrow pb-1">Delivery sites</div>
          {sites.map((site) => (
            <div key={site.id} className="flex gap-2 py-0.5 text-[12.5px]">
              <Building2 size={13} className="mt-0.5 shrink-0 text-fg-3" />
              <span className="min-w-0">
                <span className="font-medium">{site.label || 'Site'}</span>
                <span className="block truncate text-fg-3">{[site.line, site.city].filter(Boolean).join(', ')}</span>
              </span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}
