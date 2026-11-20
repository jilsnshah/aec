import { useQuery } from '@tanstack/react-query'
import { ChevronDown } from 'lucide-react'
import { useState } from 'react'
import { http } from '@/api/client'
import type { ConfigField } from '@/api/automation'
import { cn } from '@/lib/cn'

type Values = Record<string, unknown>
const SEGMENTS: [string, string][] = [['champion', 'Champions'], ['loyal', 'Loyal'], ['occasional', 'Occasional'], ['at_risk', 'At risk'], ['dormant', 'Dormant'], ['new', 'New']]

/** Options for a multiselect, loaded from the business's own data. */
function useSource(source?: ConfigField['source']): [string, string][] {
  const query = useQuery({
    queryKey: ['config-source', source],
    enabled: Boolean(source) && source !== 'segments',
    staleTime: 60_000,
    queryFn: async (): Promise<[string, string][]> => {
      if (source === 'categories') return (await http.get<{ name: string }[]>('/api/products/categories')).filter((c) => c.name !== '(none)').map((c) => [c.name, c.name])
      if (source === 'suppliers') return (await http.get<{ items: { id: string; name: string }[] }>('/api/suppliers', { limit: 500 })).items.map((s) => [s.id, s.name])
      if (source === 'customer_groups') return (await http.get<{ items: { id: string; name: string }[] }>('/api/customer-groups')).items.map((g) => [g.id, g.name])
      if (source === 'warehouses') return (await http.get<{ items: { id: string; name: string; kind: string }[] }>('/api/warehouses')).items.filter((w) => w.kind !== 'transit').map((w) => [w.id, w.name])
      return []
    },
  })
  return source === 'segments' ? SEGMENTS : query.data ?? []
}

function Chips({ options, value, onChange }: { options: [string, string][]; value: string[]; onChange: (value: string[]) => void }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map(([key, label]) => {
        const on = value.includes(key)
        return (
          <button key={key} type="button" onClick={() => onChange(on ? value.filter((v) => v !== key) : [...value, key])} className={cn('h-[26px] rounded-full px-2.5 text-[11.5px] font-semibold', on ? 'brand-fill' : 'bg-ink-700 text-fg-2')}>
            {label}
          </button>
        )
      })}
      {!options.length ? <span className="text-[11.5px] text-fg-3">Nothing to choose yet.</span> : null}
    </div>
  )
}

function Field({ field, value, onChange }: { field: ConfigField; value: unknown; onChange: (value: unknown) => void }) {
  const options = useSource(field.source)
  const label = (
    <span className="text-[12px] font-medium">
      {field.label}
      {field.help ? <span className="block text-[11px] font-normal text-fg-3">{field.help}</span> : null}
    </span>
  )
  if (field.type === 'toggle')
    return (
      <label className="flex items-start gap-2 text-[12.5px]">
        <input type="checkbox" className="mt-0.5" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
        {label}
      </label>
    )
  if (field.type === 'number')
    return (
      <label className="flex items-center gap-2">
        <span className="min-w-0 flex-1">{label}</span>
        <input className="field field-sm field-num w-[84px]" inputMode="decimal" aria-label={field.label} value={String(value ?? '')} onChange={(e) => onChange(e.target.value === '' ? 0 : Number(e.target.value))} />
        {field.unit ? <span className="w-[64px] text-[11px] text-fg-3">{field.unit}</span> : null}
      </label>
    )
  if (field.type === 'time')
    return (
      <label className="flex items-center gap-2">
        <span className="min-w-0 flex-1">{label}</span>
        <input type="time" className="field field-sm w-[110px]" aria-label={field.label} value={String(value ?? '')} onChange={(e) => onChange(e.target.value)} />
      </label>
    )
  if (field.type === 'select')
    return (
      <label className="block space-y-1">
        {label}
        <select className="field field-sm" aria-label={field.label} value={String(value ?? '')} onChange={(e) => onChange(e.target.value)}>
          {(field.options ?? []).map(([key, text]) => (
            <option key={key} value={key}>
              {text}
            </option>
          ))}
        </select>
      </label>
    )
  if (field.type === 'days' || field.type === 'multiselect')
    return (
      <div className="space-y-1">
        {label}
        <Chips options={field.type === 'days' ? field.options ?? [] : options} value={Array.isArray(value) ? (value as string[]) : []} onChange={onChange} />
      </div>
    )
  if (field.type === 'textarea')
    return (
      <label className="block space-y-1">
        {label}
        <textarea className="field font-[inherit] text-[12.5px]" rows={3} value={String(value ?? '')} onChange={(e) => onChange(e.target.value)} />
      </label>
    )
  return (
    <label className="block space-y-1">
      {label}
      <input className="field field-sm" aria-label={field.label} value={String(value ?? '')} onChange={(e) => onChange(e.target.value)} />
    </label>
  )
}

function Group({ field, value, onChange }: { field: ConfigField; value: Values; onChange: (value: Values) => void }) {
  const on = Boolean(value.enabled)
  return (
    <div className={cn('rounded-xl p-2.5 transition', on ? 'bg-ink-700/70 ring-1 ring-blue/30' : 'bg-white/[0.03]')}>
      <label className="flex items-start gap-2 text-[12.5px] font-semibold">
        <input type="checkbox" className="mt-0.5" checked={on} onChange={(e) => onChange({ ...value, enabled: e.target.checked })} />
        <span>
          {field.label}
          {field.help ? <span className="block text-[11px] font-normal text-fg-3">{field.help}</span> : null}
        </span>
      </label>
      {on && field.fields?.length ? (
        <div className="mt-2 space-y-2 pl-5">
          {field.fields.map((sub) => (
            <Field key={sub.key} field={sub} value={value[sub.key]} onChange={(v) => onChange({ ...value, [sub.key]: v })} />
          ))}
        </div>
      ) : null}
    </div>
  )
}

/** A step's settings, drawn from the fields the step publishes. */
export function ConfigForm({ fields, value, onChange }: { fields: ConfigField[]; value: Values; onChange: (value: Values) => void }) {
  return (
    <div className="space-y-3">
      {fields.map((field) => {
        if (field.type === 'section') return <Section key={field.key} field={field} value={(value[field.key] as Values) ?? {}} onChange={(v) => onChange({ ...value, [field.key]: v })} />
        if (field.type === 'group') return <Group key={field.key} field={field} value={(value[field.key] as Values) ?? {}} onChange={(v) => onChange({ ...value, [field.key]: v })} />
        return <Field key={field.key} field={field} value={value[field.key]} onChange={(v) => onChange({ ...value, [field.key]: v })} />
      })}
    </div>
  )
}

function Section({ field, value, onChange }: { field: ConfigField; value: Values; onChange: (value: Values) => void }) {
  const [open, setOpen] = useState(true)
  return (
    <div className="rounded-xl border border-white/7">
      <button type="button" className="flex w-full items-center gap-2 px-3 py-2 text-left text-[12.5px] font-semibold" onClick={() => setOpen(!open)}>
        <span className="flex-1">{field.label}</span>
        <ChevronDown size={14} className={cn('transition', !open && '-rotate-90')} />
      </button>
      {open ? (
        <div className="px-3 pb-3">
          <ConfigForm fields={field.fields ?? []} value={value} onChange={onChange} />
        </div>
      ) : null}
    </div>
  )
}
