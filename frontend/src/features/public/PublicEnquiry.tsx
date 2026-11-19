import { useMemo, useState, type ReactNode } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { CheckCircle2, Minus, Plus, Search, Send, ShoppingBag } from 'lucide-react'
import { errorText, http } from '@/api/client'
import { cn } from '@/lib/cn'
import { fmtMoney } from '@/lib/format'

interface PageData {
  business: string
  customer: string
  products: { id: string; name: string; unit: string; category: string | null; mrp: number; price: number; in_stock: boolean }[]
}

/** A customer's own page, opened from their link: pick products and
 *  quantities, see their prices, and send an enquiry. No sign-in. */
export function PublicEnquiry({ token }: { token: string }) {
  const data = useQuery({ queryKey: ['public', token], queryFn: () => http.get<PageData>(`/api/public/e/${token}`), retry: false })
  const [qty, setQty] = useState<Record<string, number>>({})
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('')
  const [form, setForm] = useState({ name: '', phone: '', notes: '' })
  const send = useMutation({
    mutationFn: () =>
      http.post<{ enquiry_number: string; total: number }>(`/api/public/e/${token}`, {
        items: Object.entries(qty).filter(([, q]) => q > 0).map(([product_id, quantity]) => ({ product_id, quantity })),
        notes: form.notes || null,
        name: form.name || null,
        phone: form.phone || null,
      }),
  })
  const products = data.data?.products ?? []
  const categories = useMemo(() => [...new Set(products.map((p) => p.category).filter(Boolean))] as string[], [products])
  const shown = products.filter((p) => (!category || p.category === category) && (!search || p.name.toLowerCase().includes(search.toLowerCase())))
  const chosen = products.filter((p) => (qty[p.id] ?? 0) > 0)
  const total = chosen.reduce((sum, p) => sum + p.price * qty[p.id], 0)

  if (data.isPending) return <Shell><p className="py-20 text-center text-fg-3">Loading…</p></Shell>
  if (data.error || !data.data) return <Shell><p className="py-20 text-center text-[15px]">{errorText(data.error) || 'This link is not valid.'}</p></Shell>
  if (send.data)
    return (
      <Shell business={data.data.business}>
        <div className="card mx-auto mt-10 max-w-md p-8 text-center">
          <CheckCircle2 size={40} className="mx-auto" />
          <h1 className="mt-3 text-[22px] font-semibold">Enquiry sent</h1>
          <p className="mt-1 text-[14px] text-fg-2">
            Reference <b>{send.data.enquiry_number}</b> · about {fmtMoney(send.data.total)} before tax.
          </p>
          <p className="mt-2 text-[13px] text-fg-3">{data.data.business} will confirm price, stock and delivery shortly.</p>
          <button className="btn mt-5" onClick={() => (send.reset(), setQty({}))}>
            Send another
          </button>
        </div>
      </Shell>
    )
  return (
    <Shell business={data.data.business}>
      <div className="mx-auto max-w-3xl pb-40">
        <h1 className="text-[22px] font-semibold tracking-[-0.02em]">Hello, {data.data.customer}</h1>
        <p className="text-[13.5px] text-fg-3">Choose what you need and send an enquiry. Prices are your prices, before GST; we confirm stock and delivery.</p>
        <div className="mt-4 flex flex-wrap gap-2">
          <label className="field flex min-w-[220px] flex-1 items-center gap-2">
            <Search size={15} className="text-fg-3" />
            <input className="w-full bg-transparent outline-none" placeholder="Search products" value={search} onChange={(e) => setSearch(e.target.value)} />
          </label>
          {categories.length ? (
            <select className="field w-[180px]" value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Category">
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
                <div className="min-w-0 flex-1">
                  <div className="text-[14px] font-semibold">{p.name}</div>
                  <div className="text-[12.5px] text-fg-3">
                    <b className="text-fg">{fmtMoney(p.price)}</b> / {p.unit}
                    {p.price < p.mrp ? <span className="ml-1 line-through">{fmtMoney(p.mrp)}</span> : null}
                    <span className={cn('ml-2', p.in_stock ? 'text-fg-2' : '')}>· {p.in_stock ? 'In stock' : 'On request'}</span>
                  </div>
                </div>
                <div className="flex items-center gap-1.5">
                  <button className="grid size-9 place-items-center rounded-full bg-ink-700" aria-label={`Less ${p.name}`} onClick={() => setQty({ ...qty, [p.id]: Math.max(0, q - 1) })}>
                    <Minus size={15} />
                  </button>
                  <input
                    className="field w-[80px] text-center"
                    inputMode="decimal"
                    aria-label={`Quantity of ${p.name}`}
                    value={q || ''}
                    placeholder="0"
                    onChange={(e) => setQty({ ...qty, [p.id]: Math.max(0, Number(e.target.value) || 0) })}
                  />
                  <button className="grid size-9 place-items-center rounded-full bg-ink-700" aria-label={`More ${p.name}`} onClick={() => setQty({ ...qty, [p.id]: q + 1 })}>
                    <Plus size={15} />
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      </div>
      {chosen.length ? (
        <div className="fixed inset-x-0 bottom-0 border-t border-[var(--card-border)] bg-ink-850/95 p-3 backdrop-blur-xl">
          <div className="mx-auto max-w-3xl space-y-2">
            {send.error ? <p className="text-[13px] font-semibold">{errorText(send.error)}</p> : null}
            <div className="grid grid-cols-3 gap-2 max-md:grid-cols-1">
              <input className="field" placeholder="Your name (optional)" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              <input className="field" placeholder="Phone (optional)" inputMode="tel" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
              <input className="field" placeholder="Site / notes (optional)" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
            </div>
            <div className="flex items-center gap-3">
              <ShoppingBag size={18} />
              <span className="flex-1 text-[14px]">
                <b>{chosen.length}</b> product{chosen.length === 1 ? '' : 's'} · about <b>{fmtMoney(total)}</b>
              </span>
              <button className="btn btn-primary" disabled={send.isPending} onClick={() => send.mutate()}>
                <Send size={15} /> Send enquiry
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </Shell>
  )
}

function Shell({ business, children }: { business?: string; children: ReactNode }) {
  return (
    <div className="min-h-screen px-4 py-6 text-fg" style={{ background: "var(--c-canvas)" }}>
      <header className="mx-auto mb-5 flex max-w-3xl items-center gap-3">
        <span className="icon-tile size-10">
          <ShoppingBag size={18} />
        </span>
        <span className="text-[17px] font-semibold">{business ?? ''}</span>
      </header>
      {children}
    </div>
  )
}
