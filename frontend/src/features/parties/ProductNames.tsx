import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Barcode, MessageSquareQuote, Ruler, Tag, Trash2, Truck } from 'lucide-react'
import { errorText } from '@/api/client'
import { useAction } from '@/api/queries'
import { parties } from '@/api/parties'
import { cn } from '@/lib/cn'
import { Badge, Button, Empty, Notice, Spinner } from '@/ui/core'
import { useSuppliers } from '@/ui/lines'

const KINDS = [
  { value: 'alias', label: 'Name customers use', icon: MessageSquareQuote, placeholder: 'e.g. 8mm sariya, ultratech' },
  { value: 'barcode', label: 'Barcode', icon: Barcode, placeholder: 'Scan or type the barcode' },
  { value: 'supplier_code', label: "Supplier's code", icon: Truck, placeholder: "The supplier's item code" },
] as const

/** Every name and code a product goes by, and the units it is counted in. */
export function ProductNamesTab({ id, name }: { id: string; name: string }) {
  const data = useQuery({ queryKey: ['product-names', id], queryFn: () => parties.productNames(id) })
  const suppliers = useSuppliers()
  const [kind, setKind] = useState<(typeof KINDS)[number]['value']>('alias')
  const [value, setValue] = useState('')
  const [supplier, setSupplier] = useState('')
  const [unit, setUnit] = useState({ name: '', factor: '' })
  const add = useAction(() => parties.addAlias(id, { kind, value, supplier_id: kind === 'supplier_code' ? supplier : null }), { success: 'Added', quiet: true })
  const remove = useAction((aliasId: string) => parties.removeAlias(id, aliasId))
  const addUnit = useAction(() => parties.addUnit(id, unit), { success: 'Unit added', quiet: true })
  const removeUnit = useAction((unitId: string) => parties.removeUnit(id, unitId))
  if (data.isPending) return <Spinner />
  if (!data.data) return <Empty title="Could not load" />
  const d = data.data
  const current = KINDS.find((k) => k.value === kind)!
  return (
    <div className="space-y-4 p-6 pb-24 max-md:p-4">
      <section className="card p-4">
        <div className="flex items-center gap-2.5">
          <span className="icon-disc size-7">
            <Tag size={14} />
          </span>
          <div>
            <div className="text-[13.5px] font-semibold">Other names and codes</div>
            <div className="text-[11.5px] text-fg-3">WhatsApp messages, calls, the assistant and barcode scans all find {name} by these.</div>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {d.aliases.length ? (
            d.aliases.map((alias) => {
              const Icon = KINDS.find((k) => k.value === alias.kind)?.icon ?? Tag
              return (
                <span key={alias.id} className="inline-flex h-[30px] items-center gap-1.5 rounded-full bg-white/7 pr-1 pl-3 text-[12.5px]">
                  <Icon size={12} className="text-fg-3" />
                  <span className="font-medium" data-selectable>
                    {alias.value}
                  </span>
                  {alias.supplier_name ? <Badge>{alias.supplier_name}</Badge> : null}
                  <button className="grid size-6 place-items-center rounded-full text-fg-3 hover:bg-white/10" aria-label={`Remove ${alias.value}`} onClick={() => remove.mutate(alias.id)}>
                    <Trash2 size={11} />
                  </button>
                </span>
              )
            })
          ) : (
            <span className="text-[12.5px] text-fg-3">None yet. Add what customers actually call it.</span>
          )}
        </div>
        <div className="mt-3 space-y-2 rounded-xl bg-white/5 p-3">
          {add.error ? <Notice tone="bad">{errorText(add.error)}</Notice> : null}
          <div className="flex flex-wrap gap-1.5">
            {KINDS.map((k) => (
              <button key={k.value} onClick={() => setKind(k.value)} className={cn('inline-flex h-[30px] items-center gap-1.5 rounded-full px-3 text-[12px] font-semibold', kind === k.value ? 'brand-fill' : 'bg-ink-700 text-fg-2')}>
                <k.icon size={12} /> {k.label}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap gap-2">
            <input className="field field-sm min-w-[200px] flex-1" placeholder={current.placeholder} value={value} onChange={(e) => setValue(e.target.value)} />
            {kind === 'supplier_code' ? (
              <select className="field field-sm w-[200px]" value={supplier} onChange={(e) => setSupplier(e.target.value)} aria-label="Supplier">
                <option value="">Choose supplier…</option>
                {suppliers.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            ) : null}
            <Button small kind="primary" busy={add.isPending} disabled={!value.trim() || (kind === 'supplier_code' && !supplier)} onClick={() => add.mutate(undefined, { onSuccess: () => setValue('') })}>
              Add
            </Button>
          </div>
        </div>
      </section>
      <section className="card p-4">
        <div className="flex items-center gap-2.5">
          <span className="icon-disc size-7">
            <Ruler size={14} />
          </span>
          <div>
            <div className="text-[13.5px] font-semibold">Units</div>
            <div className="text-[11.5px] text-fg-3">
              Stock is kept in {d.base_unit}. Other units say how many {d.base_unit} they hold, so "2 tonnes" can be read as the right number of {d.base_unit}.
            </div>
          </div>
        </div>
        <div className="mt-3 space-y-1.5">
          <div className="flex items-center gap-2 rounded-xl bg-white/5 px-3 py-2 text-[13px]">
            <b>1 {d.base_unit}</b> <Badge tone="sky">Base unit</Badge>
          </div>
          {d.units.map((u) => (
            <div key={u.id} className="flex items-center gap-2 rounded-xl bg-white/5 px-3 py-2 text-[13px]">
              <b>1 {u.name}</b> = {u.factor} {d.base_unit}
              <span className="flex-1" />
              <button className="grid size-7 place-items-center rounded-full text-fg-3 hover:bg-white/8" aria-label={`Remove ${u.name}`} onClick={() => removeUnit.mutate(u.id)}>
                <Trash2 size={13} />
              </button>
            </div>
          ))}
        </div>
        {addUnit.error ? <div className="mt-2"><Notice tone="bad">{errorText(addUnit.error)}</Notice></div> : null}
        <div className="mt-3 flex flex-wrap items-center gap-2 text-[13px]">
          1
          <input className="field field-sm w-[120px]" placeholder="tonne" value={unit.name} onChange={(e) => setUnit({ ...unit, name: e.target.value })} />=
          <input className="field field-sm w-[90px] text-right" inputMode="decimal" placeholder="20" value={unit.factor} onChange={(e) => setUnit({ ...unit, factor: e.target.value })} />
          {d.base_unit}
          <Button small busy={addUnit.isPending} disabled={!unit.name.trim() || !unit.factor} onClick={() => addUnit.mutate(undefined, { onSuccess: () => setUnit({ name: '', factor: '' }) })}>
            Add unit
          </Button>
        </div>
      </section>
    </div>
  )
}
