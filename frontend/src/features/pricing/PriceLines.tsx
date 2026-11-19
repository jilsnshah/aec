import { BadgePercent, Plus, Tags, Trash2 } from 'lucide-react'
import type { PriceListItemRow } from '@/api/records'
import { cn } from '@/lib/cn'
import { fmtMoney } from '@/lib/format'
import { Button } from '@/ui/core'
import { Picker } from '@/ui/pickers'
import { productOption, useProducts } from '@/ui/lines'

export type PriceLine = { key: string; product_id: string; min_quantity: string; mode: 'discount' | 'price'; value: string }
export const lineKey = () => Math.random().toString(36).slice(2)

export function toLines(items: PriceListItemRow[]): PriceLine[] {
  return items.map((i) => ({ key: lineKey(), product_id: i.product_id, min_quantity: String(i.min_quantity), mode: i.price !== null ? 'price' : 'discount', value: String(i.price ?? i.discount_percent ?? '') }))
}

export function fromLines(lines: PriceLine[]) {
  return lines
    .filter((l) => l.product_id && l.value !== '')
    .map((l) => ({ product_id: l.product_id, min_quantity: l.min_quantity || '0', price: l.mode === 'price' ? l.value : null, discount_percent: l.mode === 'discount' ? l.value : null }))
}

/** A flat discount off MRP. */
export function DiscountCard({ title, hint, value, onChange }: { title: string; hint: string; value: string; onChange: (value: string) => void }) {
  return (
    <section className="card p-4">
      <div className="flex flex-wrap items-center gap-3">
        <span className="icon-disc size-8">
          <BadgePercent size={15} />
        </span>
        <div className="min-w-[200px] flex-1">
          <div className="text-[13.5px] font-semibold">{title}</div>
          <div className="text-[11.5px] text-fg-3">{hint}</div>
        </div>
        <label className="flex items-center gap-1.5 text-[13px]">
          <input className="field field-sm w-[90px] text-right" inputMode="decimal" value={value} onChange={(e) => onChange(e.target.value)} placeholder="0" aria-label={title} />%
        </label>
      </div>
    </section>
  )
}

/** Product prices: a fixed price or a discount off MRP, from a quantity. */
export function PriceLines({ title, empty, lines, setLines }: { title: string; empty: string; lines: PriceLine[]; setLines: (lines: PriceLine[]) => void }) {
  const products = useProducts()
  const update = (k: string, patch: Partial<PriceLine>) => setLines(lines.map((l) => (l.key === k ? { ...l, ...patch } : l)))
  return (
    <section className="card overflow-hidden">
      <div className="flex items-center gap-2 px-4 pt-3.5 pb-2">
        <span className="icon-disc size-7">
          <Tags size={14} />
        </span>
        <span className="flex-1 text-[13.5px] font-semibold">{title}</span>
        <Button small icon={<Plus size={13} />} onClick={() => setLines([...lines, { key: lineKey(), product_id: '', min_quantity: '0', mode: 'price', value: '' }])}>
          Add product
        </Button>
      </div>
      {lines.length ? (
        <div className="overflow-x-auto">
          <table className="grid-table min-w-[700px]">
            <thead>
              <tr>
                <th>Product</th>
                <th className="r w-[100px]">From qty</th>
                <th className="w-[200px]">Rule</th>
                <th className="r w-[110px]">Value</th>
                <th className="r">Net</th>
                <th className="w-[40px]" />
              </tr>
            </thead>
            <tbody>
              {lines.map((line) => {
                const product = products.byId.get(line.product_id)
                const mrp = Number(product?.mrp ?? 0)
                const net = line.value === '' ? null : line.mode === 'price' ? Number(line.value) : mrp * (1 - Number(line.value) / 100)
                return (
                  <tr key={line.key}>
                    <td className="min-w-[200px]">
                      <Picker value={line.product_id} onChange={(v) => update(line.key, { product_id: v })} options={products.items.map(productOption)} placeholder="Choose a product…" />
                    </td>
                    <td className="r">
                      <input className="field field-sm w-[80px] text-right" inputMode="decimal" value={line.min_quantity} onChange={(e) => update(line.key, { min_quantity: e.target.value })} aria-label="From quantity" />
                    </td>
                    <td>
                      <div className="flex gap-1">
                        {(['price', 'discount'] as const).map((mode) => (
                          <button key={mode} onClick={() => update(line.key, { mode })} className={cn('h-[28px] rounded-full px-2.5 text-[12px] font-semibold whitespace-nowrap', line.mode === mode ? 'brand-fill' : 'bg-ink-700 text-fg-2')}>
                            {mode === 'price' ? 'Fixed price' : '% off MRP'}
                          </button>
                        ))}
                      </div>
                    </td>
                    <td className="r">
                      <input className="field field-sm w-[90px] text-right" inputMode="decimal" value={line.value} onChange={(e) => update(line.key, { value: e.target.value })} placeholder={line.mode === 'price' ? '₹' : '%'} aria-label="Value" />
                    </td>
                    <td className="r num font-semibold">{net !== null && product ? fmtMoney(net) : '—'}</td>
                    <td>
                      <button className="grid size-7 place-items-center rounded-full text-fg-3 hover:bg-white/8" aria-label="Remove" onClick={() => setLines(lines.filter((l) => l.key !== line.key))}>
                        <Trash2 size={13} />
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="px-4 pb-4 text-[12.5px] text-fg-3">{empty}</p>
      )}
    </section>
  )
}
