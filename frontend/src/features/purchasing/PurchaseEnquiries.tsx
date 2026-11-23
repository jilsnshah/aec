import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { CheckCircle2, Clock, FileQuestion, Phone, Plus, Scale, Send, ShoppingCart, Trash2, Trophy, XCircle } from 'lucide-react'
import { api } from '@/api/endpoints'
import { useAction, useList, useOne } from '@/api/queries'
import { purchaseEnquiries, type EnquiryStatus, type PurchaseEnquiry, type PurchaseOffer } from '@/api/purchaseEnquiries'
import { cn } from '@/lib/cn'
import { fmtDate, fmtDateTime, fmtMoney, fmtQty, plural } from '@/lib/format'
import { useRecordRoute } from '@/lib/route'
import { Badge, Button, Empty, Notice, Spinner } from '@/ui/core'
import { Sheet, useConfirm } from '@/ui/overlays'
import { Picker } from '@/ui/pickers'
import { QuickChips, type Chip } from '@/ui/smart'
import { FigureStrip, InspectorHeader, ListPane, ListRow, ListSkeleton, Section, SplitView } from '@/ui/split'

const STATUS: Record<EnquiryStatus, { label: string; tone: 'ok' | 'sky' | 'warn' | 'bad' | 'muted' }> = {
  draft: { label: 'Draft', tone: 'warn' },
  open: { label: 'Waiting for offers', tone: 'sky' },
  to_choose: { label: 'Pick an offer', tone: 'warn' },
  ordered: { label: 'Ordered', tone: 'ok' },
  decided: { label: 'No acceptable offer', tone: 'bad' },
  cancelled: { label: 'Cancelled', tone: 'muted' },
}
const OFFER: Record<PurchaseOffer['status'], string> = {
  to_ask: 'Not asked yet', asked: 'Asked', calling: 'On a call', replied: 'Offer in', declined: 'Cannot supply', no_reply: 'No reply',
}

type ChipKey = 'action' | 'open' | 'ordered' | 'all'

export function PurchaseEnquiries() {
  const route = useRecordRoute('/purchase-enquiries')
  const [chip, setChip] = useState<ChipKey>('action')
  const list = useList('purchase-enquiries', purchaseEnquiries.list, {})
  const all = list.data?.items ?? []
  const test = (key: ChipKey, e: PurchaseEnquiry) =>
    key === 'all' ? true : key === 'action' ? ['draft', 'to_choose', 'decided'].includes(e.status) : key === 'open' ? e.status === 'open' : e.status === 'ordered'
  const items = all.filter((e) => test(chip, e))
  const chips: Chip<ChipKey>[] = [
    { key: 'action', label: 'Needs you', icon: Trophy, count: all.filter((e) => test('action', e)).length, hot: all.some((e) => test('action', e)) },
    { key: 'open', label: 'Waiting for offers', icon: Clock, count: all.filter((e) => test('open', e)).length },
    { key: 'ordered', label: 'Ordered', icon: CheckCircle2, count: all.filter((e) => test('ordered', e)).length },
    { key: 'all', label: 'All', count: all.length },
  ]
  useEffect(() => {
    if (list.data && chip === 'action' && !all.some((e) => test('action', e))) setChip('all')
  }, [list.data]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!route.id && items.length > 0 && window.innerWidth >= 1024) route.select(items[0].id)
  }, [route.id, items.length]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <SplitView
      showDetail={Boolean(route.id)}
      onBack={route.back}
      list={
        <ListPane
          title="Purchase Enquiries"
          count={all.length}
          actions={
            <Button kind="primary" small icon={<Plus size={14} />} onClick={route.openNew} aria-label="New purchase enquiry">
              New
            </Button>
          }
          filters={<QuickChips chips={chips} value={chip} onChange={setChip} />}
        >
          {list.isPending ? (
            <ListSkeleton />
          ) : items.length === 0 ? (
            <Empty icon={<FileQuestion size={20} />} title="No purchase enquiries here"
              body="When stock runs short the automation sends an enquiry to your suppliers; you can also start one yourself."
              action={<Button kind="primary" small onClick={route.openNew}>New enquiry</Button>} />
          ) : (
            items.map((e) => {
              const offers = e.quotes.filter((q) => q.status === 'replied').length
              return (
                <ListRow key={e.id} group="purchase-enquiries" selected={e.id === route.id} onSelect={() => route.select(e.id)} alert={test('action', e)}>
                  <div className="flex items-baseline gap-2">
                    <span className="num text-[13px] font-semibold">{e.number}</span>
                    <span className="ml-auto text-[12px] text-fg-3">{fmtDate(e.created_at)}</span>
                  </div>
                  <div className="mt-0.5 truncate text-[12px] text-fg-2">{e.lines.map((l) => l.product).join(', ')}</div>
                  <div className="mt-2 flex items-center gap-1.5">
                    <Badge tone={STATUS[e.status].tone}>{STATUS[e.status].label}</Badge>
                    <span className="ml-auto text-[11.5px] text-fg-3">
                      {offers} of {plural(e.quotes.length, 'supplier')} offered
                    </span>
                  </div>
                </ListRow>
              )
            })
          )}
        </ListPane>
      }
    >
      {route.id ? <Inspector id={route.id} /> : <Empty className="h-full" icon={<Scale size={22} />} title="Choose a purchase enquiry" />}
      <NewEnquiry open={route.isNew} onClose={route.closeNew} onSaved={(e) => route.select(e.id)} />
    </SplitView>
  )
}

function Inspector({ id }: { id: string }) {
  const enquiry = useOne('purchase-enquiries', purchaseEnquiries.get, id)
  const suppliers = useList('suppliers', api.suppliers.list, { limit: 500 })
  const confirm = useConfirm()
  const [adding, setAdding] = useState('')
  const send = useAction(() => purchaseEnquiries.send(id), { success: 'Enquiry sent to the suppliers' })
  const add = useAction((supplier_id: string) => purchaseEnquiries.addSupplier({ id, supplier_id }), { success: 'Supplier added' })
  const remove = useAction((supplier_id: string) => purchaseEnquiries.removeSupplier({ id, supplier_id }), { success: 'Supplier removed' })
  const compare = useAction(() => purchaseEnquiries.compare(id), { success: 'Offers compared' })
  const order = useAction((supplier_id: string | null) => purchaseEnquiries.order({ id, supplier_id }), {
    success: (e) => `${e.orders.map((o) => o.po_number).join(', ')} placed and sent`,
  })
  const cancel = useAction(() => purchaseEnquiries.cancel(id), { success: 'Cancelled' })

  if (enquiry.isPending) return <Spinner />
  if (!enquiry.data) return <Empty title="This enquiry could not be loaded" />
  const e = enquiry.data
  const collecting = e.status === 'draft' || e.status === 'open'
  const canOrder = ['open', 'to_choose', 'decided'].includes(e.status)
  const offers = e.quotes.filter((q) => q.status === 'replied')
  const best = offers.length ? offers.reduce((a, b) => ((b.score ?? -1) > (a.score ?? -1) ? b : a)) : null
  const asked = new Set(e.quotes.map((q) => q.supplier_id))

  async function orderFrom(q: PurchaseOffer | null) {
    const answer = await confirm.ask({
      title: q ? `Order from ${q.supplier}?` : 'Order the recommended offers?',
      body: q ? `A purchase order for ${fmtMoney(q.total)} is created at their offer and sent to them.` : 'One purchase order per chosen supplier is created at their offers and sent.',
      confirm: 'Create and send PO',
    })
    if (answer.ok) order.mutate(q ? q.supplier_id : null)
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <InspectorHeader
        eyebrow="Purchase enquiry"
        title={e.number}
        badges={<Badge tone={STATUS[e.status].tone}>{STATUS[e.status].label}</Badge>}
        meta={
          <>
            {fmtDateTime(e.created_at)} · {e.created_by === 'system' ? `raised by automation (${e.reason})` : 'started by hand'}
            {e.reply_by && e.status === 'open' ? ` · offers compared at ${fmtDateTime(e.reply_by)}` : ''}
          </>
        }
        actions={
          <>
            {e.status === 'draft' ? (
              <Button kind="primary" small icon={<Send size={14} />} busy={send.isPending} onClick={() => send.mutate(undefined)}>
                Send enquiry
              </Button>
            ) : null}
            {e.status === 'open' ? (
              <Button small busy={compare.isPending} onClick={() => compare.mutate(undefined)}>
                Compare now
              </Button>
            ) : null}
            {canOrder && best ? (
              <Button kind="primary" small icon={<ShoppingCart size={14} />} busy={order.isPending} onClick={() => void orderFrom(null)}>
                Order recommended
              </Button>
            ) : null}
            {e.status !== 'ordered' && e.status !== 'cancelled' ? (
              <Button small kind="ghost" onClick={() => cancel.mutate(undefined)}>
                Cancel
              </Button>
            ) : null}
          </>
        }
      />
      <div className="space-y-5 p-5 pb-24">
        <FigureStrip
          items={[
            { label: 'Products', value: e.lines.length },
            { label: 'Suppliers asked', value: e.quotes.length },
            { label: 'Offers in', value: offers.length, tone: offers.length ? 'ok' : undefined },
            { label: 'Best offer', value: best ? fmtMoney(best.total) : '—', hint: best?.supplier, tone: 'sky' },
          ]}
        />
        {e.status === 'draft' ? <Notice tone="warn">Nobody has been asked yet. Check the suppliers, then send the enquiry.</Notice> : null}
        {e.status === 'to_choose' ? <Notice tone="warn">The offers are in. Pick one to order: a purchase order is created only then.</Notice> : null}
        {e.status === 'decided' ? <Notice tone="bad">No offer was within the price rule. You can still order from a supplier below.</Notice> : null}
        {e.orders.length ? (
          <Section title="Purchase orders">
            <div className="card divide-y divide-white/6">
              {e.orders.map((o) => (
                <Link key={o.id} to={`/purchase-orders/${o.id}`} className="flex items-center gap-3 px-4 py-2.5 text-[13px] hover:bg-white/3">
                  <span className="num font-semibold">{o.po_number}</span>
                  <span className="text-fg-2">{o.supplier}</span>
                  <span className="num ml-auto">{fmtMoney(o.total)}</span>
                </Link>
              ))}
            </div>
          </Section>
        ) : null}
        <Section title="Offers" hint="Prices are per unit, before GST unless the supplier said otherwise.">
          <div className="card overflow-x-auto">
            <table className="grid-table min-w-[680px]">
              <thead>
                <tr>
                  <th>Supplier</th>
                  {e.lines.map((l) => (
                    <th key={l.id} className="r">
                      {l.product}
                      <div className="text-[10.5px] font-normal text-fg-3">
                        {fmtQty(l.quantity)} {l.unit}
                        {l.last_paid ? ` · last ${fmtMoney(l.last_paid)}` : ''}
                      </div>
                    </th>
                  ))}
                  <th className="r">Days</th>
                  <th className="r">Total</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {e.quotes.map((q) => (
                  <tr key={q.id} className={cn(best?.id === q.id && 'bg-sky/5')}>
                    <td>
                      <div className="flex items-center gap-1.5 text-[13px] font-medium">
                        {q.supplier}
                        {best?.id === q.id ? <Badge tone="sky">Best</Badge> : null}
                        {e.chosen_quote_id === q.id ? <Badge tone="ok">Ordered</Badge> : null}
                      </div>
                      <div className="mt-0.5 flex items-center gap-1 text-[11.5px] text-fg-3">
                        {q.status === 'replied' ? <CheckCircle2 size={11} /> : q.status === 'declined' || q.status === 'no_reply' ? <XCircle size={11} /> : q.channel === 'call' ? <Phone size={11} /> : <Send size={11} />}
                        {OFFER[q.status] ?? q.status}
                        {q.channel ? ` · ${q.channel}` : ''}
                        {q.call_attempts ? ` · ${plural(q.call_attempts, 'call')}` : ''}
                      </div>
                      {q.reply ? <div className="max-w-[260px] truncate text-[11px] text-fg-3" title={q.reply}>“{q.reply}”</div> : null}
                    </td>
                    {e.lines.map((l) => (
                      <td key={l.id} className="r num">
                        {q.prices[l.product_id] != null ? fmtMoney(q.prices[l.product_id]) : '—'}
                        {q.available?.[l.product_id] != null ? (
                          <div className={cn('text-[11px]', q.available[l.product_id] < l.quantity ? 'text-warn' : 'text-fg-3')}>
                            {fmtQty(q.available[l.product_id])} of {fmtQty(l.quantity)} available
                          </div>
                        ) : null}
                      </td>
                    ))}
                    <td className="r num">{q.delivery_days ?? '—'}</td>
                    <td className="r num font-semibold">{q.total ? fmtMoney(q.total) : '—'}</td>
                    <td className="r">
                      {canOrder && q.status === 'replied' && Object.keys(q.prices).length ? (
                        <Button small kind={best?.id === q.id ? 'primary' : 'default'} busy={order.isPending} onClick={() => void orderFrom(q)}>
                          Order from them
                        </Button>
                      ) : e.status === 'draft' ? (
                        <Button small kind="ghost" icon={<Trash2 size={13} />} aria-label={`Remove ${q.supplier}`} onClick={() => remove.mutate(q.supplier_id)} />
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {collecting ? (
            <div className="mt-3 flex items-center gap-2">
              <div className="w-[280px]">
                <Picker small value={adding} onChange={setAdding} placeholder="Ask another supplier…"
                  options={(suppliers.data?.items ?? []).filter((s) => !asked.has(s.id)).map((s) => ({ value: s.id, label: s.name, detail: s.phone ?? undefined }))} />
              </div>
              <Button small disabled={!adding} busy={add.isPending} onClick={() => add.mutate(adding, { onSuccess: () => setAdding('') })}>
                Add
              </Button>
            </div>
          ) : null}
          {canOrder ? <OfferByHand enquiry={e} /> : null}
        </Section>
        {e.decision ? (
          <Section title="How the offers compared">
            <pre className="card px-4 py-3 text-[12px] whitespace-pre-wrap text-fg-2">{e.decision}</pre>
          </Section>
        ) : null}
      </div>
    </div>
  )
}

/** A supplier phoned their price in, or the reply was unclear: type it in. */
function OfferByHand({ enquiry }: { enquiry: PurchaseEnquiry }) {
  const [supplier, setSupplier] = useState('')
  const [prices, setPrices] = useState<Record<string, string>>({})
  const [days, setDays] = useState('')
  const record = useAction(() => purchaseEnquiries.recordOffer({ id: enquiry.id, supplier_id: supplier, prices, delivery_days: days ? Number(days) : null }), {
    success: 'Offer recorded',
  })
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2 text-[12.5px]">
      <span className="text-fg-3">Offer by phone?</span>
      <select className="field field-sm w-[200px]" value={supplier} onChange={(ev) => setSupplier(ev.target.value)} aria-label="Supplier">
        <option value="">Choose supplier…</option>
        {enquiry.quotes.map((q) => (
          <option key={q.supplier_id} value={q.supplier_id}>
            {q.supplier}
          </option>
        ))}
      </select>
      {supplier
        ? enquiry.lines.map((l) => (
            <input key={l.id} className="field field-sm field-num w-[120px]" inputMode="decimal" placeholder={`₹ per ${l.unit}`} aria-label={`Price for ${l.product}`}
              value={prices[l.product_id] ?? ''} onChange={(ev) => {
                const value = ev.target.value
                setPrices((p) => ({ ...p, [l.product_id]: value }))
              }} />
          ))
        : null}
      {supplier ? (
        <>
          <input className="field field-sm field-num w-[80px]" inputMode="numeric" placeholder="days" aria-label="Delivery days" value={days} onChange={(ev) => setDays(ev.target.value)} />
          <Button small kind="primary" busy={record.isPending} onClick={() => record.mutate(undefined, { onSuccess: () => (setSupplier(''), setPrices({}), setDays('')) })}>
            Record offer
          </Button>
        </>
      ) : null}
    </div>
  )
}

function NewEnquiry({ open, onClose, onSaved }: { open: boolean; onClose: () => void; onSaved: (e: PurchaseEnquiry) => void }) {
  const products = useList('products', api.products.list, { limit: 1000 }, open)
  const suppliers = useList('suppliers', api.suppliers.list, { limit: 500 }, open)
  const [lines, setLines] = useState<{ product_id: string; quantity: string }[]>([{ product_id: '', quantity: '' }])
  const [chosen, setChosen] = useState<string[]>([])
  const [picking, setPicking] = useState('')
  const save = useAction((send: boolean) => purchaseEnquiries.create({ lines: lines.filter((l) => l.product_id && Number(l.quantity) > 0), supplier_ids: chosen, send }), {
    success: (e) => (e.status === 'draft' ? `${e.number} saved as a draft` : `${e.number} sent to ${plural(e.quotes.length, 'supplier')}`),
  })
  const valid = lines.some((l) => l.product_id && Number(l.quantity) > 0)
  const done = (e: PurchaseEnquiry) => {
    setLines([{ product_id: '', quantity: '' }])
    setChosen([])
    onSaved(e)
    onClose()
  }
  const productOptions = (products.data?.items ?? []).map((p) => ({ value: p.id, label: p.name, detail: p.sku }))
  const supplierName = (id: string) => suppliers.data?.items.find((s) => s.id === id)?.name ?? id
  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="New purchase enquiry"
      subtitle="Ask suppliers for their offer. No purchase order is made until you pick one."
      footer={
        <>
          <Button kind="ghost" onClick={onClose}>Cancel</Button>
          <Button disabled={!valid} busy={save.isPending} onClick={() => save.mutate(false, { onSuccess: done })}>Save draft</Button>
          <Button kind="primary" disabled={!valid} busy={save.isPending} icon={<Send size={14} />} onClick={() => save.mutate(true, { onSuccess: done })}>
            Send enquiry
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        <Section title="What to buy">
          <div className="space-y-2">
            {lines.map((line, index) => (
              <div key={index} className="flex items-center gap-2">
                <div className="flex-1">
                  <Picker small value={line.product_id} options={productOptions} placeholder="Product…"
                    onChange={(value) => setLines((all) => all.map((l, i) => (i === index ? { ...l, product_id: value } : l)))} />
                </div>
                <input className="field field-sm field-num w-[110px]" inputMode="decimal" placeholder="Quantity" aria-label="Quantity" value={line.quantity}
                  onChange={(ev) => {
                    const value = ev.target.value
                    setLines((all) => all.map((l, i) => (i === index ? { ...l, quantity: value } : l)))
                  }} />
                <Button small kind="ghost" icon={<Trash2 size={13} />} aria-label="Remove line" disabled={lines.length === 1}
                  onClick={() => setLines((all) => all.filter((_, i) => i !== index))} />
              </div>
            ))}
            <Button small kind="ghost" icon={<Plus size={13} />} onClick={() => setLines((all) => [...all, { product_id: '', quantity: '' }])}>
              Add product
            </Button>
          </div>
        </Section>
        <Section title="Suppliers to ask" hint="Leave empty to use the usual and best past suppliers (Settings → Automation → Choose suppliers).">
          <div className="flex flex-wrap gap-1.5">
            {chosen.map((id) => (
              <Badge key={id} tone="sky">
                {supplierName(id)}
                <button type="button" className="ml-1 text-fg-3 hover:text-fg" aria-label={`Remove ${supplierName(id)}`} onClick={() => setChosen((c) => c.filter((x) => x !== id))}>
                  ×
                </button>
              </Badge>
            ))}
          </div>
          <div className="mt-2 w-[300px]">
            <Picker small value={picking} placeholder="Add a supplier…"
              options={(suppliers.data?.items ?? []).filter((s) => !chosen.includes(s.id)).map((s) => ({ value: s.id, label: s.name, detail: s.phone ?? undefined }))}
              onChange={(value) => {
                if (value) setChosen((c) => [...c, value])
                setPicking('')
              }} />
          </div>
        </Section>
      </div>
    </Sheet>
  )
}
