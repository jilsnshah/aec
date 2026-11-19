import { motion } from 'motion/react'
import { useEffect, useMemo, useState } from 'react'
import { Check } from 'lucide-react'
import { cn } from '@/lib/cn'
import { fmtDate, fmtQty, n } from '@/lib/format'

export interface Claimant {
  id: string
  name: string
  reference: string
  date: string
  /** The most this customer can take. */
  capacity: number
  /** What the server would propose; used for "oldest first". */
  proposed?: number
}

/** Fill the oldest claims first, up to the required total. */
export function oldestFirst(claimants: Claimant[], required: number, prefer?: string): Record<string, string> {
  let left = required
  const out: Record<string, string> = {}
  const ordered = [...claimants].sort((a, b) => (a.id === prefer ? -1 : b.id === prefer ? 1 : a.date.localeCompare(b.date)))
  for (const claimant of ordered) {
    const take = Math.min(left, claimant.capacity)
    out[claimant.id] = take > 0 ? String(Math.round(take * 1000) / 1000) : ''
    left -= take
  }
  return out
}

/** The starting split: the server's proposal when it has one that adds up,
 *  otherwise the preferred customer and then the oldest orders. */
function initial(claimants: Claimant[], required: number, prefer?: string): Record<string, string> {
  const proposed = claimants.reduce((sum, claimant) => sum + (claimant.proposed ?? 0), 0)
  if (!prefer && claimants.some((claimant) => claimant.proposed !== undefined) && Math.abs(proposed - required) < 1e-9) {
    return Object.fromEntries(claimants.map((claimant) => [claimant.id, claimant.proposed ? String(claimant.proposed) : '']))
  }
  return oldestFirst(claimants, required, prefer)
}

export function useAllocation(claimants: Claimant[], required: number, prefer?: string) {
  const signature = claimants.map((claimant) => `${claimant.id}:${claimant.capacity}`).join('|') + `#${required}`
  const [amounts, setAmounts] = useState<Record<string, string>>(() => initial(claimants, required, prefer))
  useEffect(() => setAmounts(initial(claimants, required, prefer)), [signature]) // eslint-disable-line react-hooks/exhaustive-deps
  const assigned = useMemo(() => Object.values(amounts).reduce((sum, value) => sum + n(value), 0), [amounts])
  const over = claimants.find((claimant) => n(amounts[claimant.id]) > claimant.capacity + 1e-9)
  const balanced = Math.abs(assigned - required) < 1e-9 && !over
  const allocations = claimants.filter((claimant) => n(amounts[claimant.id]) > 0).map((claimant) => ({ order_item_id: claimant.id, quantity: amounts[claimant.id] }))
  return {
    amounts,
    set: (id: string, value: string) => setAmounts((current) => ({ ...current, [id]: value })),
    fillOldest: () => setAmounts(oldestFirst(claimants, required)),
    clear: () => setAmounts({}),
    assigned,
    balanced,
    over,
    allocations,
  }
}

/** Choose which waiting customers get a quantity. The total must equal what
 *  the rule requires; the split is the user's choice. */
export function AllocationEditor({
  claimants,
  required,
  unit,
  state,
  title = 'Who gets it',
}: {
  claimants: Claimant[]
  required: number
  unit?: string
  state: ReturnType<typeof useAllocation>
  title?: string
}) {
  if (claimants.length === 0 || required <= 0) return null
  const progress = Math.min(1, required > 0 ? state.assigned / required : 0)
  return (
    <div className="overflow-hidden rounded-xl bg-ink-900 ring-1 ring-white/7 ring-inset">
      <div className="flex items-center gap-3 px-4 pt-3.5 pb-3">
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-semibold">{title}</div>
          <div className="text-[12px] text-fg-3">
            Give exactly <span className="num font-medium text-fg-2">{fmtQty(required)}{unit ? ` ${unit}` : ''}</span> to customers who are short. You choose the split.
          </div>
        </div>
        <span
          className={cn(
            'num inline-flex h-6 items-center gap-1 rounded-full px-2.5 text-[12px] font-semibold ring-1 ring-inset',
            state.balanced ? 'bg-ok/12 text-ok ring-ok/20' : state.assigned > required || state.over ? 'bg-bad/12 text-bad ring-bad/22' : 'bg-sky/10 text-sky ring-sky/20',
          )}
        >
          {state.balanced ? <Check size={12} /> : null}
          {fmtQty(state.assigned)} / {fmtQty(required)}
        </span>
      </div>
      <div className="mx-4 h-1 overflow-hidden rounded-full bg-white/7">
        <motion.div className={cn('h-full rounded-full', state.assigned > required ? 'bg-bad' : 'bg-sky')} animate={{ width: `${progress * 100}%` }} transition={{ type: 'spring', stiffness: 260, damping: 30 }} />
      </div>
      <div className="mt-2 flex justify-end gap-3 px-4 text-[12px]">
        <button className="font-medium text-sky hover:text-sky-2" onClick={state.fillOldest} type="button">
          Oldest first
        </button>
        <button className="font-medium text-fg-3 hover:text-fg" onClick={state.clear} type="button">
          Clear
        </button>
      </div>
      <table className="grid-table mt-1">
        <thead>
          <tr>
            <th>Customer · order</th>
            <th className="r">Short</th>
            <th className="r w-[120px]">Give</th>
          </tr>
        </thead>
        <tbody>
          {claimants.map((claimant) => {
            const over = n(state.amounts[claimant.id]) > claimant.capacity + 1e-9
            return (
              <tr key={claimant.id}>
                <td>
                  <div className="text-[13px] font-medium">{claimant.name}</div>
                  <div className="text-[11.5px] text-fg-3">
                    {claimant.reference} · {fmtDate(claimant.date)}
                  </div>
                </td>
                <td className="r num text-bad">{fmtQty(claimant.capacity)}</td>
                <td className="r">
                  <input
                    className="field field-sm field-num"
                    inputMode="decimal"
                    placeholder="0"
                    aria-invalid={over || undefined}
                    value={state.amounts[claimant.id] ?? ''}
                    onChange={(event) => state.set(claimant.id, event.target.value)}
                  />
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
