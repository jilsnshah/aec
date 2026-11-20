import { useQuery } from '@tanstack/react-query'
import { BASIS_LABEL, KIND_LABEL, VEHICLE_LABEL, transporters, type TransporterMeta } from '@/api/transporters'
import { fmtMoney, n } from '@/lib/format'
import { Picker } from '@/ui/pickers'

/** Active transporters (react-query key ['transporters']). */
export function useTransporters() {
  return useQuery({ queryKey: ['transporters'], queryFn: () => transporters.list(), staleTime: 30_000 })
}

/** Labels for kinds, vehicle types and rate bases, with fallbacks until loaded. */
export function useTransporterMeta(): TransporterMeta {
  const meta = useQuery({ queryKey: ['transporters', 'meta'], queryFn: transporters.meta, staleTime: 10 * 60_000 })
  return {
    kinds: { ...KIND_LABEL, ...(meta.data?.kinds ?? {}) },
    vehicles: { ...VEHICLE_LABEL, ...(meta.data?.vehicles ?? {}) },
    bases: { ...BASIS_LABEL, ...(meta.data?.bases ?? {}) },
  }
}

/** Choose a transporter: name, kind and what we owe them. */
export function TransporterPicker({ value, onChange, placeholder = 'Choose a transporter…' }: { value: string; onChange: (id: string) => void; placeholder?: string }) {
  const list = useTransporters()
  const options = (list.data?.items ?? [])
    .filter((t) => t.is_active || t.id === value)
    .map((t) => ({
      value: t.id,
      label: t.name,
      detail: [t.kind_label, t.phone, t.service_areas].filter(Boolean).join(' · '),
      keywords: `${t.code} ${t.phone ?? ''} ${t.service_areas ?? ''}`,
      trail: n(t.balance) > 0 ? <span className="num shrink-0 text-[11.5px] text-fg-3">owe {fmtMoney(t.balance)}</span> : undefined,
    }))
  return <Picker value={value} onChange={onChange} options={options} placeholder={list.isPending ? 'Loading…' : placeholder} emptyText="No transporters match." />
}
