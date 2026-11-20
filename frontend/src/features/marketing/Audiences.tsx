import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Cake, CheckCircle2, CircleSlash, Plus, ShieldCheck, Trash2, Users, X } from 'lucide-react'
import { groups } from '@/api/groups'
import { marketing, type Audience, type AudienceDefinition, type Channel } from '@/api/marketing'
import { useAction } from '@/api/queries'
import { cn } from '@/lib/cn'
import { fmtDate } from '@/lib/format'
import { Badge, Button, Empty, Field, Notice, SearchBox, Spinner } from '@/ui/core'
import { Segmented, Sheet, useConfirm } from '@/ui/overlays'
import { Picker } from '@/ui/pickers'
import { productOption, useCustomers, useProducts } from '@/ui/lines'
import { Page, Panel } from './shared'

const OPS = ['>=', '<=', '>', '<', '=', '!=']

/** Who to reach: a definition over the ERP's own figures, with a live count. */
export function AudienceBuilder({ value, onChange, channels }: { value: AudienceDefinition; onChange: (v: AudienceDefinition) => void; channels?: Channel[] }) {
  const fields = useQuery({ queryKey: ['marketing', 'audiences'], queryFn: marketing.audiences })
  const groupList = useQuery({ queryKey: ['customer-groups'], queryFn: groups.list })
  const products = useProducts()
  const customers = useCustomers()
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), 350)
    return () => clearTimeout(t)
  }, [value])
  const preview = useQuery({ queryKey: ['marketing', 'audience-preview', debounced, channels], queryFn: () => marketing.preview({ definition: debounced, channels: (channels ?? ['whatsapp']).filter((c) => c === 'whatsapp') as Channel[] }) })
  const categories = useMemo(() => [...new Set(products.items.map((p) => p.category).filter(Boolean) as string[])].sort(), [products.items])
  const set = (patch: Partial<AudienceDefinition>) => onChange(Object.fromEntries(Object.entries({ ...value, ...patch }).filter(([, v]) => v !== undefined)) as AudienceDefinition)
  const rules = value.rules ?? []
  const fieldList = fields.data?.fields ?? []
  const wa = preview.data?.reach.whatsapp
  return (
    <div className="space-y-3 rounded-[14px] border border-white/7 p-3.5">
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="In customer groups" optional>
          {(props) => (
            <div className="space-y-1.5">
              <Picker id={props.id} value="" onChange={(v) => v && set({ group_ids: [...new Set([...(value.group_ids ?? []), v])] })} options={(groupList.data?.items ?? []).map((g) => ({ value: g.id, label: g.name, detail: `${g.member_count} members` }))} placeholder="Add a group…" />
              <Chips items={(value.group_ids ?? []).map((id) => ({ id, label: groupList.data?.items.find((g) => g.id === id)?.name ?? 'Group' }))} onRemove={(id) => set({ group_ids: (value.group_ids ?? []).filter((x) => x !== id) || undefined })} />
            </div>
          )}
        </Field>
        <Field label="Bought these products" optional>
          {(props) => (
            <div className="space-y-1.5">
              <div className="flex gap-1.5">
                <div className="flex-1">
                  <Picker id={props.id} value="" onChange={(v) => v && set({ products: { mode: value.products?.mode ?? 'bought', within_days: value.products?.within_days ?? null, ids: [...new Set([...(value.products?.ids ?? []), v])] } })} options={products.items.map(productOption)} placeholder="Add a product…" />
                </div>
                {value.products ? <ModeToggle value={value.products.mode} onChange={(mode) => set({ products: { ...value.products!, mode } })} /> : null}
              </div>
              <Chips
                items={(value.products?.ids ?? []).map((id) => ({ id, label: products.byId.get(id)?.name ?? 'Product' }))}
                onRemove={(id) => {
                  const ids = (value.products?.ids ?? []).filter((x) => x !== id)
                  set({ products: ids.length ? { ...value.products!, ids } : undefined })
                }}
              />
              {value.products ? <WithinDays value={value.products.within_days ?? null} onChange={(within_days) => set({ products: { ...value.products!, within_days } })} /> : null}
            </div>
          )}
        </Field>
        <Field label="Bought from these categories" optional>
          {(props) => (
            <div className="space-y-1.5">
              <div className="flex gap-1.5">
                <div className="flex-1">
                  <Picker id={props.id} value="" onChange={(v) => v && set({ categories: { mode: value.categories?.mode ?? 'bought', within_days: value.categories?.within_days ?? null, names: [...new Set([...(value.categories?.names ?? []), v])] } })} options={categories.map((c) => ({ value: c, label: c }))} placeholder="Add a category…" />
                </div>
                {value.categories ? <ModeToggle value={value.categories.mode} onChange={(mode) => set({ categories: { ...value.categories!, mode } })} /> : null}
              </div>
              <Chips
                items={(value.categories?.names ?? []).map((id) => ({ id, label: id }))}
                onRemove={(id) => {
                  const names = (value.categories?.names ?? []).filter((x) => x !== id)
                  set({ categories: names.length ? { ...value.categories!, names } : undefined })
                }}
              />
            </div>
          )}
        </Field>
        <Field label="Occasion" optional>
          {(props) => (
            <div className="flex items-center gap-2">
              <Picker
                id={props.id}
                value={value.occasion?.kind ?? ''}
                onChange={(kind) => set({ occasion: kind ? { kind: kind as 'birthday' | 'anniversary', within_days: value.occasion?.within_days ?? 7 } : undefined })}
                options={[
                  { value: '', label: 'Any time' },
                  { value: 'birthday', label: 'Birthday coming up' },
                  { value: 'anniversary', label: 'Anniversary coming up' },
                ]}
              />
              {value.occasion ? (
                <label className="flex items-center gap-1.5 text-[12px] whitespace-nowrap text-fg-3">
                  within
                  <input className="field field-sm field-num w-14" value={value.occasion.within_days} onChange={(e) => set({ occasion: { ...value.occasion!, within_days: Number(e.target.value) || 0 } })} />
                  days
                </label>
              ) : null}
            </div>
          )}
        </Field>
      </div>
      <div>
        <div className="mb-1.5 flex items-center gap-2">
          <span className="label mb-0">Figures</span>
          {rules.length > 1 ? (
            <Segmented
              value={value.match ?? 'all'}
              onChange={(match) => set({ match })}
              options={[
                { value: 'all', label: 'All match' },
                { value: 'any', label: 'Any matches' },
              ]}
            />
          ) : null}
          <Button small kind="ghost" icon={<Plus size={12} />} onClick={() => set({ rules: [...rules, { field: 'days_since_last_order', op: '>=', value: 90 }] })}>
            Add
          </Button>
          <label className="ml-auto flex items-center gap-1.5 text-[12px]">
            <input type="checkbox" checked={Boolean(value.open_enquiry)} onChange={(e) => set({ open_enquiry: e.target.checked || undefined })} /> Has an open enquiry
          </label>
        </div>
        <div className="space-y-1.5">
          {rules.map((rule, i) => {
            const f = fieldList.find((x) => x.key === rule.field)
            return (
              <div key={i} className="flex flex-wrap items-center gap-1.5">
                <select className="field field-sm max-w-[260px]" value={rule.field} onChange={(e) => set({ rules: rules.map((r, j) => (j === i ? { ...r, field: e.target.value } : r)) })} aria-label="Figure">
                  {fieldList.map((x) => (
                    <option key={x.key} value={x.key}>
                      {x.label}
                    </option>
                  ))}
                </select>
                <select className="field field-sm w-16" value={rule.op} onChange={(e) => set({ rules: rules.map((r, j) => (j === i ? { ...r, op: e.target.value } : r)) })} aria-label="Comparison">
                  {(f && (f.type === 'choice' || f.type === 'text') ? ['=', '!='] : OPS).map((op) => (
                    <option key={op}>{op}</option>
                  ))}
                </select>
                {f?.type === 'choice' ? (
                  <select className="field field-sm w-36" value={String(rule.value)} onChange={(e) => set({ rules: rules.map((r, j) => (j === i ? { ...r, value: e.target.value } : r)) })} aria-label="Value">
                    {(f.choices ?? []).map((c) => (
                      <option key={c}>{c}</option>
                    ))}
                  </select>
                ) : (
                  <input className="field field-sm w-32" value={String(rule.value)} onChange={(e) => set({ rules: rules.map((r, j) => (j === i ? { ...r, value: e.target.value } : r)) })} aria-label="Value" />
                )}
                {f?.unit ? <span className="text-[12px] text-fg-3">{f.unit}</span> : null}
                <Button small kind="ghost" iconOnly aria-label="Remove" onClick={() => set({ rules: rules.filter((_, j) => j !== i).length ? rules.filter((_, j) => j !== i) : undefined })}>
                  <X size={13} />
                </Button>
              </div>
            )
          })}
        </div>
      </div>
      <Field label="Always leave out" optional>
        {(props) => (
          <div className="space-y-1.5">
            <Picker id={props.id} value="" onChange={(v) => v && set({ exclude: [...new Set([...(value.exclude ?? []), v])] })} options={customers.map((c) => ({ value: c.id, label: c.name }))} placeholder="Choose a customer to keep out…" />
            <Chips items={(value.exclude ?? []).map((id) => ({ id, label: customers.find((c) => c.id === id)?.name ?? 'Customer' }))} onRemove={(id) => set({ exclude: (value.exclude ?? []).filter((x) => x !== id) })} />
          </div>
        )}
      </Field>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-[10px] bg-white/4 px-3 py-2 text-[12.5px]" aria-live="polite">
        <span className="font-semibold">{preview.isFetching && !preview.data ? 'Counting…' : `${preview.data?.count ?? 0} customers`}</span>
        {wa ? (
          <span className="text-fg-3">
            {wa.reachable} can get WhatsApp offers
            {Object.keys(wa.blocked).length ? ` · ${Object.entries(wa.blocked).map(([why, n]) => `${n} ${why.toLowerCase()}`).join(' · ')}` : ''}
          </span>
        ) : null}
        <span className="text-fg-3">{preview.data?.summary}</span>
      </div>
    </div>
  )
}

function Chips({ items, onRemove }: { items: { id: string; label: string }[]; onRemove: (id: string) => void }) {
  if (!items.length) return null
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((x) => (
        <span key={x.id} className="inline-flex items-center gap-1 rounded-full bg-white/7 py-0.5 pr-1 pl-2.5 text-[12px] font-medium">
          {x.label}
          <button aria-label={`Remove ${x.label}`} onClick={() => onRemove(x.id)} className="grid size-5 place-items-center rounded-full hover:bg-white/10">
            <X size={11} />
          </button>
        </span>
      ))}
    </div>
  )
}

function ModeToggle({ value, onChange }: { value: 'bought' | 'not_bought'; onChange: (v: 'bought' | 'not_bought') => void }) {
  return (
    <Segmented
      value={value}
      onChange={onChange}
      options={[
        { value: 'bought', label: 'Bought' },
        { value: 'not_bought', label: 'Never' },
      ]}
    />
  )
}

function WithinDays({ value, onChange }: { value: number | null; onChange: (v: number | null) => void }) {
  return (
    <label className="flex items-center gap-1.5 text-[12px] text-fg-3">
      in the last
      <input className="field field-sm field-num w-16" value={value ?? ''} placeholder="any" onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value) || 0)} />
      days
    </label>
  )
}

// ---------------------------------------------------------------------------
// Page: saved audiences and consent
// ---------------------------------------------------------------------------

export function Audiences() {
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') === 'consent' ? 'consent' : 'audiences'
  return (
    <Page className="space-y-3">
      <Segmented
        className="w-fit"
        value={tab}
        onChange={(v) => setParams({ tab: v })}
        options={[
          { value: 'audiences', label: 'Saved audiences' },
          { value: 'consent', label: 'Consent and occasions' },
        ]}
      />
      {tab === 'audiences' ? <SavedAudiences /> : <Consent />}
    </Page>
  )
}

function SavedAudiences() {
  const data = useQuery({ queryKey: ['marketing', 'audiences'], queryFn: marketing.audiences })
  const [editing, setEditing] = useState<Audience | 'new' | null>(null)
  const confirm = useConfirm()
  const remove = useAction(marketing.removeAudience, { success: 'Deleted' })
  if (data.isPending) return <Spinner />
  const items = data.data?.items ?? []
  return (
    <>
      <Panel
        title="Saved audiences"
        icon={Users}
        actions={
          <Button small kind="primary" icon={<Plus size={13} />} onClick={() => setEditing('new')}>
            New audience
          </Button>
        }
      >
        <p className="mb-3 text-[12.5px] text-fg-3">Audiences stay live: the count changes as customers buy, go quiet or join groups. Campaigns check who is in them at send time.</p>
        {items.length ? (
          <div className="grid gap-2.5 md:grid-cols-2 xl:grid-cols-3">
            {items.map((a) => (
              <div key={a.id} className="flex flex-col gap-1.5 rounded-[14px] border border-white/7 p-3.5">
                <div className="flex items-center gap-2">
                  <h3 className="flex-1 truncate text-[14px] font-semibold">{a.name}</h3>
                  <span className="num rounded-full bg-white/7 px-2 text-[12px] font-semibold">{a.last_count ?? '—'}</span>
                </div>
                <p className="text-[12.5px] text-fg-3">{a.summary}</p>
                <div className="mt-auto flex gap-1.5 pt-1">
                  <Button small onClick={() => setEditing(a)}>
                    Edit
                  </Button>
                  <Button
                    small
                    kind="ghost"
                    iconOnly
                    aria-label="Delete"
                    onClick={async () => {
                      const answer = await confirm.ask({ title: `Delete ${a.name}?`, body: 'Campaigns using it keep their own copy of who it was for.', confirm: 'Delete', danger: true })
                      if (answer.ok) remove.mutate(a.id)
                    }}
                  >
                    <Trash2 size={13} />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <Empty icon={<Users size={20} />} title="No saved audiences" body="Save the groups of customers you reach often: cement buyers in Ahmedabad, contractors gone quiet, birthdays this week." />
        )}
      </Panel>
      <AudienceSheet editing={editing} onClose={() => setEditing(null)} />
      {confirm.element}
    </>
  )
}

function AudienceSheet({ editing, onClose }: { editing: Audience | 'new' | null; onClose: () => void }) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [definition, setDefinition] = useState<AudienceDefinition>({})
  const save = useAction(marketing.saveAudience, { success: 'Audience saved' })
  useEffect(() => {
    if (!editing) return
    setName(editing === 'new' ? '' : editing.name)
    setDescription(editing === 'new' ? '' : (editing.description ?? ''))
    setDefinition(editing === 'new' ? {} : editing.definition)
  }, [editing])
  return (
    <Sheet
      open={Boolean(editing)}
      onClose={onClose}
      title={editing === 'new' ? 'New audience' : 'Edit audience'}
      width={860}
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button kind="primary" busy={save.isPending} disabled={!name.trim()} onClick={() => save.mutate({ id: editing && editing !== 'new' ? editing.id : undefined, name, description, definition }, { onSuccess: onClose })}>
            Save
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Name">{(props) => <input {...props} className="field" autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="Contractors gone quiet" />}</Field>
          <Field label="Note" optional>
            {(props) => <input {...props} className="field" value={description} onChange={(e) => setDescription(e.target.value)} />}
          </Field>
        </div>
        <AudienceBuilder value={definition} onChange={setDefinition} />
      </div>
    </Sheet>
  )
}

const SOURCES = [
  { value: 'manual', label: 'Told us in person or on the phone' },
  { value: 'form', label: 'Signed a form' },
  { value: 'whatsapp_reply', label: 'Said yes on WhatsApp' },
  { value: 'order', label: 'Ticked yes when ordering' },
  { value: 'import', label: 'Imported list with consent' },
]

function Consent() {
  const [status, setStatus] = useState<'all' | 'opted_in' | 'opted_out' | 'unknown'>('all')
  const [q, setQ] = useState('')
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [recording, setRecording] = useState<null | 'opted_in' | 'opted_out'>(null)
  const [occasion, setOccasion] = useState<null | { id: string; name: string; birthday: string; anniversary: string }>(null)
  const data = useQuery({ queryKey: ['marketing', 'consents', status, q], queryFn: () => marketing.consents({ status: status === 'all' ? undefined : status, q: q || undefined }) })
  const items = data.data?.items ?? []
  const totals = data.data?.totals ?? {}
  const toggle = (id: string) => setPicked((old) => {
    const next = new Set(old)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
  })
  return (
    <>
      <Panel title="WhatsApp marketing consent" icon={ShieldCheck}>
        <Notice tone="sky">
          WhatsApp allows offers only to people who agreed to receive them. Record how each customer agreed. Anyone who replies STOP is opted out at once, and the app never sends them offers again unless they agree again.
        </Notice>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Segmented
            value={status}
            onChange={setStatus}
            options={[
              { value: 'all', label: 'Everyone' },
              { value: 'opted_in', label: 'Agreed', count: totals.opted_in ?? 0 },
              { value: 'unknown', label: 'Not asked', count: totals.unknown ?? 0 },
              { value: 'opted_out', label: 'Opted out', count: totals.opted_out ?? 0 },
            ]}
          />
          <div className="w-60">
            <SearchBox value={q} onChange={setQ} placeholder="Name or phone" />
          </div>
          {picked.size ? (
            <div className="ml-auto flex gap-2">
              <Button small kind="primary" icon={<CheckCircle2 size={13} />} onClick={() => setRecording('opted_in')}>
                Record agreed ({picked.size})
              </Button>
              <Button small icon={<CircleSlash size={13} />} onClick={() => setRecording('opted_out')}>
                Opt out ({picked.size})
              </Button>
            </div>
          ) : null}
        </div>
        <div className="mt-3 overflow-x-auto">
          {data.isPending ? (
            <Spinner />
          ) : (
            <table className="grid-table min-w-[720px]">
              <thead>
                <tr>
                  <th className="w-8">
                    <input type="checkbox" aria-label="Choose all" checked={items.length > 0 && items.every((i) => picked.has(i.customer_id))} onChange={(e) => setPicked(e.target.checked ? new Set(items.map((i) => i.customer_id)) : new Set())} />
                  </th>
                  <th>Customer</th>
                  <th>Phone</th>
                  <th>WhatsApp offers</th>
                  <th>How</th>
                  <th>Occasions</th>
                </tr>
              </thead>
              <tbody>
                {items.map((r) => (
                  <tr key={r.customer_id}>
                    <td>
                      <input type="checkbox" aria-label={`Choose ${r.name}`} checked={picked.has(r.customer_id)} onChange={() => toggle(r.customer_id)} />
                    </td>
                    <td className="font-medium">{r.name}</td>
                    <td className={cn('num', !r.phone && 'text-fg-4')}>{r.phone || 'none'}</td>
                    <td>{r.status === 'opted_in' ? <Badge tone="ok">Agreed</Badge> : r.status === 'opted_out' ? <Badge tone="bad">Opted out</Badge> : <Badge>Not asked</Badge>}</td>
                    <td className="max-w-[260px] truncate text-[12px] text-fg-3" title={r.evidence ?? ''}>
                      {r.source ? `${r.source.replace('_', ' ')}${r.evidence ? `: ${r.evidence}` : ''} · ${fmtDate(r.at)}` : '—'}
                    </td>
                    <td>
                      <button className="inline-flex items-center gap-1 text-[12px] text-fg-2 hover:text-fg" onClick={() => setOccasion({ id: r.customer_id, name: r.name, birthday: r.birthday ?? '', anniversary: r.anniversary ?? '' })}>
                        <Cake size={12} />
                        {r.birthday || r.anniversary ? [r.birthday && `B ${fmtDate(r.birthday)}`, r.anniversary && `A ${fmtDate(r.anniversary)}`].filter(Boolean).join(' · ') : 'Add'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </Panel>
      <ConsentSheet ids={[...picked]} status={recording} onClose={(done) => { setRecording(null); if (done) setPicked(new Set()) }} />
      <OccasionSheet value={occasion} onClose={() => setOccasion(null)} />
    </>
  )
}

function ConsentSheet({ ids, status, onClose }: { ids: string[]; status: null | 'opted_in' | 'opted_out'; onClose: (done: boolean) => void }) {
  const [source, setSource] = useState('manual')
  const [evidence, setEvidence] = useState('')
  const save = useAction(marketing.setConsent, { success: (r) => `${r.updated} updated` })
  useEffect(() => {
    setEvidence('')
    setSource('manual')
  }, [status])
  return (
    <Sheet
      open={Boolean(status)}
      onClose={() => onClose(false)}
      title={status === 'opted_in' ? `Record that ${ids.length} customer${ids.length === 1 ? '' : 's'} agreed` : `Opt out ${ids.length} customer${ids.length === 1 ? '' : 's'}`}
      width={560}
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button onClick={() => onClose(false)}>Cancel</Button>
          <Button kind="primary" busy={save.isPending} disabled={status === 'opted_in' && source === 'manual' && !evidence.trim()} onClick={() => save.mutate({ customer_ids: ids, status: status!, source, evidence: evidence || undefined }, { onSuccess: () => onClose(true) })}>
            Save
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        {status === 'opted_in' ? (
          <Field label="How they agreed">
            {(props) => <Picker id={props.id} value={source} onChange={setSource} options={SOURCES} />}
          </Field>
        ) : null}
        <Field label={status === 'opted_in' ? 'Details' : 'Reason'} optional={status !== 'opted_in' || source !== 'manual'} hint="Kept with the record, e.g. 'asked at the counter on 12 Nov' or 'form no. 214'.">
          {(props) => <input {...props} className="field" value={evidence} onChange={(e) => setEvidence(e.target.value)} />}
        </Field>
      </div>
    </Sheet>
  )
}

function OccasionSheet({ value, onClose }: { value: null | { id: string; name: string; birthday: string; anniversary: string }; onClose: () => void }) {
  const [birthday, setBirthday] = useState('')
  const [anniversary, setAnniversary] = useState('')
  const save = useAction(marketing.setOccasions, { success: 'Saved' })
  useEffect(() => {
    setBirthday(value?.birthday ?? '')
    setAnniversary(value?.anniversary ?? '')
  }, [value])
  return (
    <Sheet
      open={Boolean(value)}
      onClose={onClose}
      title={`Occasions for ${value?.name ?? ''}`}
      subtitle="Used for greetings: the Birthday wishes automation picks them up."
      width={520}
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button kind="primary" busy={save.isPending} onClick={() => save.mutate({ id: value!.id, birthday, anniversary }, { onSuccess: onClose })}>
            Save
          </Button>
        </div>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Birthday" optional>{(props) => <input {...props} type="date" className="field" value={birthday} onChange={(e) => setBirthday(e.target.value)} />}</Field>
        <Field label="Anniversary" optional>{(props) => <input {...props} type="date" className="field" value={anniversary} onChange={(e) => setAnniversary(e.target.value)} />}</Field>
      </div>
    </Sheet>
  )
}
