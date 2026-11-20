import { useMemo, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { CheckCircle2, Minus, Plus, Search, Send, ShoppingBag } from 'lucide-react'
import { errorText, http } from '@/api/client'
import { cn } from '@/lib/cn'
import { fmtMoney } from '@/lib/format'
import type { PageData, SentEnquiry } from './types'

/** Pick products and quantities at the customer's own prices, and send an enquiry. */
export function OrderTab({ token, data }: { token: string; data: PageData }) {
  const [qty, setQty] = useState<Record<string, number>>({})
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('')
  const [form, setForm] = useState({ name: '', phone: '', notes: '' })
  const send = useMutation({
    mutationFn: () =>
      http.post<SentEnquiry>(`/api/public/e/${token}`, {
        items: Object.entries(qty)
          .filter(([, q]) => q > 0)
          .map(([product_id, quantity]) => ({ product_id, quantity })),
        notes: form.notes || null,
        name: form.name || null,
        phone: form.phone || null,
      }),
  })
  const products = data.products
  const categories = useMemo(() => [...new Set(products.map((p) => p.category).filter(Boolean))] as string[], [products])
  const shown = products.filter((p) => (!category || p.category === category) && (!search || p.name.toLowerCase().includes(search.toLowerCase())))
  const chosen = products.filter((p) => (qty[p.id] ?? 0) > 0)
  const total = chosen.reduce((sum, p) => sum + p.price * qty[p.id], 0)

  if (send.data)
    return (
      <div className="card mx-auto mt-6 max-w-md p-8 text-center">
        <CheckCircle2 size={40} className="mx-auto text-ok" />
        <h2 className="mt-3 text-[22px] font-semibold">Enquiry sent</h2>
        <p className="mt-1 text-[14px] text-fg-2">
          Reference <b>{send.data.enquiry_number}</b> · about {fmtMoney(send.data.total)} before tax.
        </p>
        <p className="mt-2 text-[13px] text-fg-3">{data.business} will confirm price, stock and delivery shortly.</p>
        <button
          className="btn mt-5"
          onClick={() => {
            send.reset()
            setQty(() => ({}))
          }}
        >
          Send another
        </button>
      </div>
    )

  return (
    <>
      <div className="pb-48">
        <p className="text-[13.5px] text-fg-3">Choose what you need and send an enquiry. Prices are your prices, before GST; we confirm stock and delivery.</p>
        <div className="mt-3 flex flex-wrap gap-2">
          <label className="field flex min-w-0 flex-1 basis-[200px] items-center gap-2">
            <Search size={15} className="shrink-0 text-fg-3" />
            <input className="w-full min-w-0 bg-transparent outline-none" placeholder="Search products" value={search} onChange={(e) => setSearch(e.target.value)} />
          </label>
          {categories.length ? (
            <select className="field min-w-0 flex-1 basis-[160px] sm:max-w-[200px]" value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Category">
              <option value="">All categories</option>
              {categories.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          ) : null}
        </div>
        <div className="mt-3 space-y-2">
          {shown.map((p) => {
            const q = qty[p.id] ?? 0
            return (
              <div key={p.id} className={cn('card flex flex-wrap items-center gap-3 p-3', q > 0 && 'ring-2 ring-blue')}>
                <div className="min-w-0 flex-1 basis-[160px]">
                  <div className="break-words text-[14px] font-semibold">{p.name}</div>
                  <div className="text-[12.5px] text-fg-3">
                    <b className="text-fg">{fmtMoney(p.price)}</b> / {p.unit}
                    {p.price < p.mrp ? <span className="ml-1 line-through">{fmtMoney(p.mrp)}</span> : null}
                    <span className={cn('ml-2', p.in_stock ? 'text-ok' : '')}>· {p.in_stock ? 'In stock' : 'On request'}</span>
                  </div>
                </div>
                <div className="ml-auto flex items-center gap-1.5">
                  <button
                    className="grid size-9 place-items-center rounded-full bg-ink-700"
                    aria-label={`Less ${p.name}`}
                    onClick={() => setQty((prev) => ({ ...prev, [p.id]: Math.max(0, (prev[p.id] ?? 0) - 1) }))}
                  >
                    <Minus size={15} />
                  </button>
                  <input
                    className="field w-[72px] text-center"
                    inputMode="decimal"
                    aria-label={`Quantity of ${p.name}`}
                    value={q || ''}
                    placeholder="0"
                    onChange={(e) => {
                      const value = Math.max(0, Number(e.target.value) || 0)
                      setQty((prev) => ({ ...prev, [p.id]: value }))
                    }}
                  />
                  <button
                    className="grid size-9 place-items-center rounded-full bg-ink-700"
                    aria-label={`More ${p.name}`}
                    onClick={() => setQty((prev) => ({ ...prev, [p.id]: (prev[p.id] ?? 0) + 1 }))}
                  >
                    <Plus size={15} />
                  </button>
                </div>
              </div>
            )
          })}
          {!shown.length ? <p className="py-10 text-center text-[13.5px] text-fg-3">No products match.</p> : null}
        </div>
      </div>
      {chosen.length ? (
        <div className="fixed inset-x-0 bottom-0 z-20 border-t border-[var(--card-border)] bg-ink-850/95 p-3 backdrop-blur-xl">
          <div className="mx-auto max-w-3xl space-y-2">
            {send.error ? <p className="text-[13px] font-semibold text-bad">{errorText(send.error)}</p> : null}
            <div className="grid grid-cols-3 gap-2 max-md:grid-cols-1">
              <input
                className="field"
                placeholder="Your name (optional)"
                value={form.name}
                onChange={(e) => {
                  const name = e.target.value
                  setForm((prev) => ({ ...prev, name }))
                }}
              />
              <input
                className="field"
                placeholder="Phone (optional)"
                inputMode="tel"
                value={form.phone}
                onChange={(e) => {
                  const phone = e.target.value
                  setForm((prev) => ({ ...prev, phone }))
                }}
              />
              <input
                className="field"
                placeholder="Site / notes (optional)"
                value={form.notes}
                onChange={(e) => {
                  const notes = e.target.value
                  setForm((prev) => ({ ...prev, notes }))
                }}
              />
            </div>
            <div className="flex items-center gap-3">
              <ShoppingBag size={18} className="shrink-0" />
              <span className="min-w-0 flex-1 text-[14px]">
                <b>{chosen.length}</b> product{chosen.length === 1 ? '' : 's'} · about <b>{fmtMoney(total)}</b>
              </span>
              <button className="btn btn-primary shrink-0" disabled={send.isPending} onClick={() => send.mutate()}>
                <Send size={15} /> Send
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  )
}
