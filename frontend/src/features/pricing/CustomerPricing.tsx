import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { BadgePercent, Plus, Tags, Trash2, UserMinus, UserPlus, UsersRound } from 'lucide-react'
import { errorText } from '@/api/client'
import { useAction } from '@/api/queries'
import { groups } from '@/api/groups'
import { cn } from '@/lib/cn'
import { fmtMoney } from '@/lib/format'
import { Badge, Button, Notice, Spinner } from '@/ui/core'
import { Picker } from '@/ui/pickers'
import { productOption, useProducts } from '@/ui/lines'

type Line = { key: string; product_id: string; min_quantity: string; mode: 'discount' | 'price'; value: string }
const key = () => Math.random().toString(36).slice(2)

/** What this customer pays: their own discount and product prices, plus their
 *  price list and groups. The best of all of them is used on each line. */
export function CustomerPricing({ customerId }: { customerId: string }) {
  const data = useQuery({ queryKey: ['customer-pricing', customerId], queryFn: () => groups.pricing(customerId) })
  const products = useProducts()
  const allGroups = useQuery({ queryKey: ['customer-groups'], queryFn: groups.list })
  const member = useAction(groups.setMember, { success: 'Groups updated' })
  const [groupId, setGroupId] = useState('')
  const [discount, setDiscount] = useState('')
  const [lines, setLines] = useState<Line[]>([])
  useEffect(() => {
    if (!data.data) return
    setDiscount(data.data.discount_percent ? String(data.data.discount_percent) : '')
    setLines(data.data.own_items.map((i) => ({ key: key(), product_id: i.product_id, min_quantity: String(i.min_quantity), mode: i.price !== null ? 'price' : 'discount', value: String(i.price ?? i.discount_percent ?? '') })))
  }, [data.data])
  const save = useAction(
    () =>
      groups.setPricing({
        customerId,
        discount_percent: discount || null,
        items: lines.filter((l) => l.product_id && l.value !== '').map((l) => ({ product_id: l.product_id, min_quantity: l.min_quantity || '0', price: l.mode === 'price' ? l.value : null, discount_percent: l.mode === 'discount' ? l.value : null })),
      }),
    { success: 'Pricing saved', quiet: true },
  )
  if (data.isPending) return <Spinner />
  const p = data.data
  const update = (k: string, patch: Partial<Line>) => setLines(lines.map((l) => (l.key === k ? { ...l, ...patch } : l)))
  return (
    <div className="space-y-4 p-6 pb-24 max-md:p-4">
      <div className="rounded-2xl bg-peri/35 px-4 py-3 text-[12.5px]">
        On each order or quote line this customer gets the <b>best</b> of: their own price for that product, their own discount, their price list, and the price lists of every group they are in.
      </div>
      {save.error ? <Notice tone="bad">{errorText(save.error)}</Notice> : null}
      <section className="card p-4">
        <div className="flex flex-wrap items-center gap-3">
          <span className="icon-disc size-8">
            <BadgePercent size={15} />
          </span>
          <div className="min-w-[200px] flex-1">
            <div className="text-[13.5px] font-semibold">Discount for this customer</div>
            <div className="text-[11.5px] text-fg-3">Off MRP on everything. Leave empty for none.</div>
          </div>
          <label className="flex items-center gap-1.5 text-[13px]">
            <input className="field field-sm w-[90px] text-right" inputMode="decimal" value={discount} onChange={(e) => setDiscount(e.target.value)} placeholder="0" />%
          </label>
        </div>
      </section>
      <section className="card overflow-hidden">
        <div className="flex items-center gap-2 px-4 pt-3.5 pb-2">
          <span className="icon-disc size-7">
            <Tags size={14} />
          </span>
          <span className="flex-1 text-[13.5px] font-semibold">Own product prices</span>
          <Button small icon={<Plus size={13} />} onClick={() => setLines([...lines, { key: key(), product_id: '', min_quantity: '0', mode: 'price', value: '' }])}>
            Add product
          </Button>
        </div>
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
                      <input className="field field-sm w-[80px] text-right" inputMode="decimal" value={line.min_quantity} onChange={(e) => update(line.key, { min_quantity: e.target.value })} />
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
                      <input className="field field-sm w-[90px] text-right" inputMode="decimal" value={line.value} onChange={(e) => update(line.key, { value: e.target.value })} placeholder={line.mode === 'price' ? '₹' : '%'} />
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
        {!lines.length ? <p className="px-4 pb-4 text-[12.5px] text-fg-3">No special prices for this customer.</p> : null}
      </section>
      <section className="card p-4">
        <div className="flex items-center gap-2">
          <span className="icon-disc size-7">
            <UsersRound size={14} />
          </span>
          <span className="text-[13.5px] font-semibold">Price list and groups</span>
        </div>
        <div className="mt-2 space-y-1.5 text-[13px]">
          <div>
            Price list: {p?.price_list ? <Link to="/price-lists" className="font-semibold hover:underline">{p.price_list.name}</Link> : <span className="text-fg-3">none (set under Edit details)</span>}
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="text-[12.5px] font-semibold">Groups</span>
          <span className="flex-1" />
          <div className="w-[240px] max-md:w-full">
            <Picker value={groupId} onChange={setGroupId} placeholder="Add to a group…" options={(allGroups.data?.items ?? []).filter((g) => !p?.groups.some((m) => m.id === g.id)).map((g) => ({ value: g.id, label: g.name }))} />
          </div>
          <Button small icon={<UserPlus size={13} />} disabled={!groupId} onClick={() => member.mutate({ id: groupId, customerId, source: 'manual' }, { onSuccess: () => setGroupId('') })}>
            Add
          </Button>
        </div>
        <div className="mt-1 divide-y divide-white/6">
          {p?.groups.length ? (
            p.groups.map((g) => (
              <div key={g.id} className="flex items-center gap-2 py-1.5 text-[13px]">
                <Link to="/customer-groups" className="min-w-0 flex-1 truncate font-semibold hover:underline">
                  {g.name}
                  {g.price_list_name ? <span className="font-normal text-fg-3"> · {g.price_list_name}</span> : null}
                </Link>
                <Badge tone={g.source === 'manual' ? 'sky' : 'muted'}>{g.source === 'rule' ? 'by rules' : 'by hand'}</Badge>
                <Button small kind="ghost" icon={<UserMinus size={12} />} onClick={() => member.mutate({ id: g.id, customerId, source: g.source === 'rule' ? 'excluded' : null })}>
                  Remove
                </Button>
              </div>
            ))
          ) : (
            <p className="py-1.5 text-[12.5px] text-fg-3">Not in any group.</p>
          )}
          {p?.kept_out.map((g) => (
            <div key={g.id} className="flex items-center gap-2 py-1.5 text-[13px] text-fg-3">
              <span className="min-w-0 flex-1 truncate">{g.name} · removed by hand</span>
              <Button small kind="ghost" onClick={() => member.mutate({ id: g.id, customerId, source: null })}>
                Let back in
              </Button>
            </div>
          ))}
        </div>
      </section>
      <div className="flex justify-end">
        <Button kind="primary" busy={save.isPending} onClick={() => save.mutate(undefined)}>
          Save pricing
        </Button>
      </div>
    </div>
  )
}
