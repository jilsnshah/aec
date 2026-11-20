import { useQuery } from '@tanstack/react-query'
import { warehouses, type Warehouse } from '@/api/warehouses'
import { Field } from '@/ui/core'

/** The warehouses stock can be put into or taken from (not 'In transit'). */
export function useWarehouses() {
  const query = useQuery({ queryKey: ['warehouses'], queryFn: warehouses.list, staleTime: 60_000 })
  const usable = (query.data?.items ?? []).filter((w) => w.kind !== 'transit' && w.is_active)
  return { usable, all: query.data?.items ?? [], byDefault: usable.find((w) => w.is_default), loading: query.isPending }
}

/** Pick a warehouse. Shown only once there is more than one; '' means the default. */
export function WarehouseSelect({
  value,
  onChange,
  label = 'Warehouse',
  hint,
  className,
  anyLabel,
  stockOf,
}: {
  value: string
  onChange: (value: string) => void
  label?: string
  hint?: string
  className?: string
  /** Offer "any" (e.g. deliver from wherever the oldest stock is). */
  anyLabel?: string
  /** Show how much of this product each warehouse holds. */
  stockOf?: Map<string, number>
}) {
  const { usable, byDefault } = useWarehouses()
  if (usable.length < 2) return null
  const describe = (w: Warehouse) => `${w.name}${w.is_default ? ' (default)' : ''}${stockOf ? ` · ${stockOf.get(w.id) ?? 0} here` : ''}`
  return (
    <Field label={label} hint={hint} className={className}>
      {(props) => (
        <select {...props} className="field" value={value} onChange={(e) => onChange(e.target.value)}>
          {anyLabel ? <option value="">{anyLabel}</option> : <option value="">{byDefault ? describe(byDefault) : 'Default'}</option>}
          {usable.filter((w) => anyLabel || !w.is_default).map((w) => (
            <option key={w.id} value={w.id}>
              {describe(w)}
            </option>
          ))}
        </select>
      )}
    </Field>
  )
}
