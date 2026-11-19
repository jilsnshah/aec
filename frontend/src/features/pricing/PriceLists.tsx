import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { BadgePercent, Layers, Plus, Tags, Trash2, Users } from 'lucide-react'
import { errorText } from '@/api/client'
import { useAction } from '@/api/queries'
import { priceLists, type PriceListRow } from '@/api/records'
import { cn } from '@/lib/cn'
import { fmtMoney } from '@/lib/format'
import { Badge, Button, Empty, Field, Notice, Spinner, Toggle } from '@/ui/core'
import { Picker } from '@/ui/pickers'
import { ListPane, ListRow, SplitView } from '@/ui/split'
import { PageGuide, Stat } from '@/ui/smart'
import { productOption, useProducts } from '@/ui/lines'

type Line = { key: string; product_id: string; min_quantity: string; mode: 'discount' | 'price'; value: string }
const newKey = () => Math.random().toString(36).slice(2)

/** Negotiated prices per customer group: a default discount plus product
 *  lines with quantity breaks. Customers on a list get these prices on new
 *  orders and quotes. */
export function PriceLists() {
  const lists = useQuery({ queryKey: ['price-lists'], queryFn: () => priceLists.list(true) })
  const [selected, setSelected] = useState<string | 'new' | null>(null)
  const items = lists.data?.items ?? []
  useEffect(() => {
    if (!selected && items.length) setSelected(items[0].id)
  }, [items.length]) // eslint-disable-line react-hooks/exhaustive-deps
  const current = items.find((row) => row.id === selected)
  return (
    <SplitView
      showDetail={Boolean(selected)}
      onBack={() => setSelected(null)}
      list={
        <ListPane
          title="Price Lists"
          count={items.length}
          actions={
            <>
              <PageGuide
                title="Price lists"
                points={[
                  { icon: Users, text: 'Put each customer on a list (Edit details on the customer). New orders and quotes for them start at these prices.' },
                  { icon: BadgePercent, text: 'A list has a default discount off MRP, and product lines with either a fixed price or a discount.' },
                  { icon: Layers, text: 'Quantity breaks: add the same product again with a higher minimum quantity for a better price.' },
                  { icon: Tags, text: 'Prices are a starting point; the order form shows margin and the order controls still apply.' },
                ]}
              />
              <Button kind="primary" small icon={<Plus size={14} />} onClick={() => setSelected('new')}>
                New
              </Button>
            </>
          }
        >
          {lists.isPending ? (
            <Spinner />
          ) : !items.length ? (
            <Empty icon={<Tags size={20} />} title="No price lists yet" body="Create one for dealers, contractors or builders." action={<Button kind="primary" small onClick={() => setSelected('new')}>New price list</Button>} />
          ) : (
            items.map((row) => (
              <ListRow key={row.id} group="price-lists" selected={row.id === selected} onSelect={() => setSelected(row.id)}>
                <div className="flex items-center gap-2">
                  <span className="truncate text-[13px] font-semibold">{row.name}</span>
                  {!row.is_active ? <Badge>Off</Badge> : null}
                  <span className="ml-auto num text-[12.5px] font-semibold">{row.discount_percent ? `${row.discount_percent}% off` : ''}</span>
                </div>
                <div className="mt-0.5 text-[12px] text-fg-3">
                  {row.items.length} product lines · {row.customers ?? 0} customers
                </div>
              </ListRow>
            ))
          )}
        </ListPane>
      }
    >
      {selected === 'new' ? (
        <Editor key="new" onSaved={(row) => setSelected(row.id)} />
      ) : current ? (
        <Editor key={current.id} list={current} onSaved={(row) => setSelected(row.id)} />
      ) : (
        <Empty className="h-full" icon={<Tags size={22} />} title="Choose a price list" />
      )}
    </SplitView>
  )
}

function Editor({ list, onSaved }: { list?: PriceListRow; onSaved: (row: PriceListRow) => void }) {
  const products = useProducts()
  const [name, setName] = useState(list?.name ?? '')
  const [discount, setDiscount] = useState(String(list?.discount_percent ?? 0))
  const [active, setActive] = useState(list?.is_active ?? true)
  const [notes, setNotes] = useState(list?.notes ?? '')
  const [lines, setLines] = useState<Line[]>(
    (list?.items ?? []).map((item) => ({ key: newKey(), product_id: item.product_id, min_quantity: String(item.min_quantity), mode: item.price !== null ? 'price' : 'discount', value: String(item.price ?? item.discount_percent ?? '') })),
  )
  const body = {
    name,
    discount_percent: discount || '0',
    notes: notes || null,
    is_active: active,
    items: lines.filter((line) => line.product_id && line.value !== '').map((line) => ({ product_id: line.product_id, min_quantity: line.min_quantity || '0', price: line.mode === 'price' ? line.value : null, discount_percent: line.mode === 'discount' ? line.value : null })),
  }
  const save = useAction(() => (list ? priceLists.update({ id: list.id, ...body }) : priceLists.create(body)), { success: 'Price list saved', quiet: true })
  const update = (key: string, patch: Partial<Line>) => setLines((current) => current.map((line) => (line.key === key ? { ...line, ...patch } : line)))
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex shrink-0 flex-wrap items-center gap-3 border-b border-white/7 px-7 py-5 max-md:px-4">
        <span className="icon-tile size-12">
          <Tags size={22} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="eyebrow">Price list</div>
          <h2 className="text-[22px] font-semibold tracking-[-0.02em]">{name || 'New price list'}</h2>
        </div>
        <Button kind="primary" busy={save.isPending} disabled={!name.trim()} onClick={() => save.mutate(undefined, { onSuccess: onSaved })}>
          Save
        </Button>
      </header>
      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-7 pb-24 max-md:p-4">
        {save.error ? <Notice tone="bad">{errorText(save.error)}</Notice> : null}
        <div className="grid grid-cols-[repeat(auto-fit,minmax(190px,1fr))] gap-3">
          <Stat strong icon={Users} label="Customers on it" value={list?.customers ?? 0} hint="set on each customer" />
          <Stat icon={BadgePercent} label="Default discount" value={`${discount || 0}%`} hint="for products not listed" />
          <Stat icon={Layers} label="Product lines" value={body.items.length} hint="incl. quantity breaks" />
        </div>
        <div className="grid grid-cols-3 gap-3 max-md:grid-cols-1">
          <Field label="Name">{(props) => <input {...props} className="field" placeholder="e.g. Contractors" value={name} onChange={(e) => setName(e.target.value)} />}</Field>
          <Field label="Default discount %">{(props) => <input {...props} className="field field-num" inputMode="decimal" value={discount} onChange={(e) => setDiscount(e.target.value)} />}</Field>
          <label className="flex items-end gap-2 pb-2 text-[13px]">
            <Toggle checked={active} onChange={setActive} label="Active" /> Active
          </label>
        </div>
        <div className="card overflow-hidden">
          <div className="flex items-center justify-between px-4 pt-3.5 pb-2">
            <span className="text-[13px] font-semibold">Product prices</span>
            <Button small icon={<Plus size={13} />} onClick={() => setLines([...lines, { key: newKey(), product_id: '', min_quantity: '0', mode: 'discount', value: '' }])}>
              Add product
            </Button>
          </div>
          <div className="overflow-x-auto">
          <table className="grid-table min-w-[760px]">
            <thead>
              <tr>
                <th>Product</th>
                <th className="r w-[110px]">From qty</th>
                <th className="w-[210px]">Rule</th>
                <th className="r w-[120px]">Value</th>
                <th className="r">Net price</th>
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
                    <td className="min-w-[220px]">
                      <Picker value={line.product_id} onChange={(value) => update(line.key, { product_id: value })} options={products.items.map(productOption)} placeholder="Choose a product…" />
                      {product ? <div className="mt-0.5 text-[11.5px] text-fg-3">MRP {fmtMoney(mrp)}</div> : null}
                    </td>
                    <td className="r">
                      <input className="field field-sm w-[90px] text-right" inputMode="decimal" value={line.min_quantity} onChange={(e) => update(line.key, { min_quantity: e.target.value })} />
                    </td>
                    <td>
                      <div className="flex gap-1">
                        {(['discount', 'price'] as const).map((mode) => (
                          <button key={mode} onClick={() => update(line.key, { mode })} className={cn('h-[28px] rounded-full px-2.5 text-[12px] font-semibold whitespace-nowrap', line.mode === mode ? 'brand-fill' : 'bg-ink-700 text-fg-2')}>
                            {mode === 'discount' ? '% off MRP' : 'Fixed price'}
                          </button>
                        ))}
                      </div>
                    </td>
                    <td className="r">
                      <input className="field field-sm w-[100px] text-right" inputMode="decimal" placeholder={line.mode === 'price' ? '₹' : '%'} value={line.value} onChange={(e) => update(line.key, { value: e.target.value })} />
                    </td>
                    <td className="r num font-semibold">{net !== null && product ? fmtMoney(net) : '—'}</td>
                    <td>
                      <button className="grid size-7 place-items-center rounded-full text-fg-3 hover:bg-white/8" aria-label="Remove line" onClick={() => setLines(lines.filter((l) => l.key !== line.key))}>
                        <Trash2 size={13} />
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          </div>
          {!lines.length ? <p className="px-4 pb-4 text-[12.5px] text-fg-3">No product lines: every product gets the default discount.</p> : null}
        </div>
        <Field label="Notes" optional>
          {(props) => <textarea {...props} className="field" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />}
        </Field>
      </div>
    </div>
  )
}
