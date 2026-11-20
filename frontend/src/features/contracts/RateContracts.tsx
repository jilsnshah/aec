import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Ban, CalendarClock, Factory, FileSignature, Layers, Pencil, Plus, ShoppingCart, Trash2, Users } from 'lucide-react'
import { errorText } from '@/api/client'
import { contracts, type Contract, type ContractIn, type ContractItem, type ContractParty, type ContractStatus } from '@/api/contracts'
import { useAction } from '@/api/queries'
import type { ProductOut } from '@/api/types'
import { cn } from '@/lib/cn'
import { fmtDate, fmtMoney, fmtQty, n, plural } from '@/lib/format'
import { Badge, Button, Empty, Field, Notice, Spinner, type Tone } from '@/ui/core'
import { Segmented, Sheet, useConfirm } from '@/ui/overlays'
import { Picker } from '@/ui/pickers'
import { defaultUnit, productOption, unitsOf, useCustomers, useProducts, useSuppliers } from '@/ui/lines'
import { FigureStrip, InspectorHeader, ListPane, ListRow, Section, SplitView } from '@/ui/split'
import { PageGuide } from '@/ui/smart'

type Filter = 'supplier' | 'customer' | 'all'

const STATUS: Record<ContractStatus, { label: string; tone: Tone }> = {
  upcoming: { label: 'Upcoming', tone: 'steel' },
  active: { label: 'Active', tone: 'ok' },
  expiring: { label: 'Expiring', tone: 'warn' },
  expired: { label: 'Expired', tone: 'muted' },
  cancelled: { label: 'Cancelled', tone: 'muted' },
}

const running = (c: Contract) => c.status === 'active' || c.status === 'expiring'
const expiringSoon = (c: Contract) => running(c) && c.days_left !== null && c.days_left <= 15
const modeOf = (party: ContractParty) => (party === 'supplier' ? 'purchase' : 'sale') as 'purchase' | 'sale'

function daysLeftText(c: Contract) {
  if (c.status === 'cancelled') return 'Cancelled'
  if (c.status === 'expired') return `Ended ${fmtDate(c.valid_until)}`
  if (c.status === 'upcoming') return `Starts ${fmtDate(c.valid_from)}`
  if (c.days_left === null) return ''
  return c.days_left <= 0 ? 'Ends today' : `${plural(c.days_left, 'day')} left`
}

/** Rate contracts with suppliers and customers. */
export function RateContracts() {
  const list = useQuery({ queryKey: ['rate-contracts'], queryFn: () => contracts.list() })
  const [filter, setFilter] = useState<Filter>('all')
  const [selected, setSelected] = useState<string | null>(null)
  const [sheet, setSheet] = useState<null | { editing?: Contract }>(null)
  const all = list.data?.items ?? []
  const items = filter === 'all' ? all : all.filter((c) => c.party === filter)
  const soon = all.filter(expiringSoon)
  useEffect(() => {
    if (!selected && items.length && window.matchMedia('(min-width: 1024px)').matches) setSelected(items[0].id)
  }, [items.length, filter]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <SplitView
        showDetail={Boolean(selected)}
        onBack={() => setSelected(null)}
        list={
          <ListPane
            title="Rate contracts"
            count={items.length}
            actions={
              <>
                <PageGuide
                  title="Rate contracts"
                  points={[
                    { icon: Factory, text: 'A supplier contract fixes a rate for a period, e.g. a mill’s annual cement rate. New purchase orders to that supplier take the contract rate automatically.' },
                    { icon: Users, text: 'A customer contract is a project rate for a builder. It competes with the customer’s other prices; the best price wins on their quotes and orders.' },
                    { icon: Layers, text: 'Each line can apply from a minimum quantity (a slab) and carry a committed quantity. What is ordered against it within the dates is tracked as used.' },
                    { icon: CalendarClock, text: 'Contracts ending within 15 days are flagged so you can renew them in time.' },
                  ]}
                />
                <Button small kind="primary" icon={<Plus size={14} />} onClick={() => setSheet({})}>
                  New
                </Button>
              </>
            }
            filters={
              <Segmented
                value={filter}
                onChange={(v) => {
                  setFilter(v)
                  setSelected(null)
                }}
                options={[
                  { value: 'supplier', label: 'Suppliers', count: all.filter((c) => c.party === 'supplier').length },
                  { value: 'customer', label: 'Customers', count: all.filter((c) => c.party === 'customer').length },
                  { value: 'all', label: 'All' },
                ]}
              />
            }
          >
            {soon.length ? (
              <div className="px-1.5 pb-2">
                <Notice tone="warn" icon={<AlertTriangle size={15} />}>
                  <span className="font-semibold">Expiring soon:</span>{' '}
                  {soon.map((c, i) => (
                    <span key={c.id}>
                      {i ? ', ' : ''}
                      <button className="underline-offset-2 hover:underline" onClick={() => setSelected(c.id)}>
                        {c.number}
                      </button>{' '}
                      ({c.days_left !== null && c.days_left <= 0 ? 'today' : `${c.days_left} d`})
                    </span>
                  ))}
                </Notice>
              </div>
            ) : null}
            {list.isPending ? (
              <Spinner />
            ) : list.error ? (
              <Notice tone="bad">{errorText(list.error)}</Notice>
            ) : items.length ? (
              items.map((c) => (
                <ListRow key={c.id} group="rc" selected={selected === c.id} onSelect={() => setSelected(c.id)} alert={expiringSoon(c)}>
                  <div className="flex items-center gap-2">
                    <span className="text-[12px] font-semibold text-fg-3">{c.number}</span>
                    <Badge tone={STATUS[c.status].tone} dot={c.status === 'expiring'}>
                      {STATUS[c.status].label}
                    </Badge>
                    <span className={cn('ml-auto text-[11.5px] whitespace-nowrap', c.status === 'expiring' ? 'text-warn' : 'text-fg-3')}>{daysLeftText(c)}</span>
                  </div>
                  <div className="mt-0.5 truncate text-[13.5px] font-semibold">{c.title}</div>
                  <div className="flex items-center gap-1.5 truncate text-[12px] text-fg-3">
                    {c.party === 'supplier' ? <Factory size={12} className="shrink-0" /> : <Users size={12} className="shrink-0" />}
                    <span className="truncate">{c.party_name}</span>
                    <span>· {plural(c.items.length, 'line')}</span>
                  </div>
                </ListRow>
              ))
            ) : (
              <Empty icon={<FileSignature size={20} />} title="No rate contracts" body="Agree a rate for a period with a supplier or a customer with New." />
            )}
          </ListPane>
        }
      >
        {!selected ? (
          <Empty className="h-full" icon={<FileSignature size={22} />} title="Choose a contract" />
        ) : (
          <ContractView key={selected} id={selected} onEdit={(c) => setSheet({ editing: c })} />
        )}
      </SplitView>
      <ContractSheet
        open={sheet !== null}
        editing={sheet?.editing}
        defaultParty={filter === 'customer' ? 'customer' : 'supplier'}
        onClose={() => setSheet(null)}
        onSaved={(id) => setSelected(id)}
      />
    </>
  )
}

/* ------------------------------------------------------------------ detail */

function ContractView({ id, onEdit }: { id: string; onEdit: (c: Contract) => void }) {
  const query = useQuery({ queryKey: ['rate-contracts', id], queryFn: () => contracts.get(id) })
  const products = useProducts()
  const cancel = useAction(contracts.cancel, { success: (c) => `${c.number} cancelled` })
  const confirm = useConfirm()
  const c = query.data
  if (query.error) return <div className="p-6"><Notice tone="bad">{errorText(query.error)}</Notice></div>
  if (!c) return <Spinner />
  const committedLines = c.items.filter((i) => i.committed_quantity !== null && n(i.committed_quantity) > 0)
  const overall = committedLines.length ? committedLines.reduce((s, i) => s + Math.min(1, n(i.used_quantity) / n(i.committed_quantity)), 0) / committedLines.length : null
  const editable = c.status !== 'cancelled' && c.status !== 'expired'
  return (
    <>
      <InspectorHeader
        eyebrow={`${c.number} · ${c.party === 'supplier' ? 'Supplier contract' : 'Customer contract'}`}
        title={c.title}
        badges={<Badge tone={STATUS[c.status].tone} dot={c.status === 'expiring'}>{STATUS[c.status].label}</Badge>}
        meta={[c.party_name, `${fmtDate(c.valid_from)} – ${fmtDate(c.valid_until)}`, c.reference ? `Ref ${c.reference}` : null].filter(Boolean).join(' · ')}
        actions={
          editable ? (
            <>
              <Button icon={<Pencil size={14} />} onClick={() => onEdit(c)}>
                Edit
              </Button>
              <Button
                kind="ghost"
                icon={<Ban size={14} />}
                busy={cancel.isPending}
                onClick={async () => {
                  const answer = await confirm.ask({
                    title: `Cancel ${c.number}?`,
                    body: `${c.party === 'supplier' ? 'New purchase orders to' : 'Quotes and orders for'} ${c.party_name} will stop using these rates. Orders already placed keep their prices.`,
                    confirm: 'Cancel contract',
                    danger: true,
                  })
                  if (answer.ok) cancel.mutate(c.id)
                }}
              >
                Cancel contract
              </Button>
            </>
          ) : null
        }
      />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <FigureStrip
          items={[
            { label: 'Lines', value: String(c.items.length), hint: c.party === 'supplier' ? 'products at contract rate' : 'products at project rate' },
            {
              label: 'Days left',
              value: c.status === 'upcoming' ? '—' : c.status === 'cancelled' || c.status === 'expired' ? '0' : String(Math.max(0, c.days_left ?? 0)),
              tone: c.status === 'expiring' ? 'bad' : c.status === 'active' ? 'ok' : undefined,
              hint: c.status === 'upcoming' ? `starts ${fmtDate(c.valid_from)}` : `until ${fmtDate(c.valid_until)}`,
            },
            {
              label: 'Committed used',
              value: overall === null ? '—' : `${Math.round(overall * 100)}%`,
              tone: overall !== null && overall > 0.9 ? 'bad' : 'sky',
              hint: committedLines.length ? `average of ${plural(committedLines.length, 'committed line')}` : 'no committed quantities',
            },
          ]}
        />
        <Section title="Lines" hint={c.party === 'supplier' ? 'Rates per base unit; new purchase orders take these automatically.' : 'Best price wins against the customer’s other prices.'}>
          {c.items.length ? (
            <div className="overflow-x-auto">
              <table className="grid-table min-w-[760px]">
                <thead>
                  <tr>
                    <th>Product</th>
                    <th className="r">Rate</th>
                    <th className="r">Slab from</th>
                    <th className="r">Committed</th>
                    <th className="r">Used</th>
                    <th className="w-[140px]">Progress</th>
                    <th className="r">Left</th>
                  </tr>
                </thead>
                <tbody>
                  {c.items.map((item) => (
                    <LineRow key={item.id} item={item} product={products.byId.get(item.product_id)} party={c.party} />
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty title="No lines" />
          )}
        </Section>
        {c.terms ? (
          <Section title="Terms">
            <p className="text-[13px] whitespace-pre-wrap text-fg-2">{c.terms}</p>
          </Section>
        ) : null}
      </div>
      {confirm.element}
    </>
  )
}

function LineRow({ item, product, party }: { item: ContractItem; product?: ProductOut; party: ContractParty }) {
  const pct = item.used_percent === null ? null : n(item.used_percent)
  const perBase = item.rate !== null ? n(item.rate) : item.discount_percent !== null && item.mrp !== null ? n(item.mrp) * (1 - n(item.discount_percent) / 100) : null
  const bigger = product ? defaultUnit(product, modeOf(party)) : ''
  const factor = bigger ? unitsOf(product, modeOf(party)).find((u) => u.name === bigger)?.factor ?? 1 : 1
  return (
    <tr>
      <td>
        <div className="text-[13px] font-medium">{item.product}</div>
        {item.discount_percent !== null ? <div className="text-[11.5px] text-fg-3">{fmtQty(item.discount_percent)}% off MRP {item.mrp !== null ? `(${fmtMoney(item.mrp)})` : ''}</div> : null}
      </td>
      <td className="r">
        {perBase !== null ? (
          <>
            <div className="num text-[13px] font-semibold whitespace-nowrap">
              {fmtMoney(perBase)} <span className="font-normal text-fg-3">/ {item.unit}</span>
            </div>
            {factor !== 1 ? (
              <div className="num text-[11.5px] whitespace-nowrap text-fg-3">
                {fmtMoney(perBase * factor)} / {bigger}
              </div>
            ) : null}
          </>
        ) : (
          '—'
        )}
      </td>
      <td className="r num">{n(item.min_quantity) > 0 ? `${fmtQty(item.min_quantity)} ${item.unit}` : '—'}</td>
      <td className="r num">{item.committed_quantity !== null ? `${fmtQty(item.committed_quantity)} ${item.unit}` : '—'}</td>
      <td className="r num">{fmtQty(item.used_quantity)}</td>
      <td>
        {pct !== null ? (
          <div className="flex items-center gap-2">
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/8">
              <div className={cn('h-full rounded-full', pct > 90 ? 'bg-warn' : 'bg-sky')} style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} />
            </div>
            <span className={cn('num w-[38px] text-right text-[11.5px]', pct > 90 ? 'font-semibold text-warn' : 'text-fg-3')}>{Math.round(pct)}%</span>
          </div>
        ) : (
          <span className="text-[11.5px] text-fg-4">No commitment</span>
        )}
      </td>
      <td className="r num">{item.left_quantity !== null ? fmtQty(item.left_quantity) : '—'}</td>
    </tr>
  )
}

/* ------------------------------------------------------------------- sheet */

interface FormLine {
  key: string
  product_id: string
  unit: string
  by: 'rate' | 'percent'
  rate: string
  percent: string
  min: string
  committed: string
}
const newFormLine = (): FormLine => ({ key: Math.random().toString(36).slice(2), product_id: '', unit: '', by: 'rate', rate: '', percent: '', min: '', committed: '' })
const isoDay = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const yearOn = () => {
  const d = new Date()
  d.setFullYear(d.getFullYear() + 1)
  return isoDay(d)
}
const num = (v: string) => v.trim() !== '' && !Number.isNaN(Number(v))

function ContractSheet({ open, editing, defaultParty, onClose, onSaved }: { open: boolean; editing?: Contract; defaultParty: ContractParty; onClose: () => void; onSaved: (id: string) => void }) {
  const products = useProducts()
  const suppliers = useSuppliers()
  const customers = useCustomers()
  const empty = { party: defaultParty, partyId: '', title: '', from: isoDay(new Date()), until: yearOn(), reference: '', terms: '' }
  const [form, setForm] = useState(empty)
  const [lines, setLines] = useState<FormLine[]>([newFormLine()])
  useEffect(() => {
    if (!open) return
    setForm(
      editing
        ? {
            party: editing.party,
            partyId: (editing.party === 'supplier' ? editing.supplier_id : editing.customer_id) ?? '',
            title: editing.title,
            from: editing.valid_from.slice(0, 10),
            until: editing.valid_until.slice(0, 10),
            reference: editing.reference ?? '',
            terms: editing.terms ?? '',
          }
        : empty,
    )
    setLines(
      editing?.items.length
        ? editing.items.map((i) => ({
            key: i.id,
            product_id: i.product_id,
            unit: '',
            by: i.rate === null && i.discount_percent !== null ? 'percent' : 'rate',
            rate: i.rate !== null ? String(n(i.rate)) : '',
            percent: i.discount_percent !== null ? String(n(i.discount_percent)) : '',
            min: n(i.min_quantity) > 0 ? String(n(i.min_quantity)) : '',
            committed: i.committed_quantity !== null ? String(n(i.committed_quantity)) : '',
          }))
        : [newFormLine()],
    )
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  const mode = modeOf(form.party)
  const partyOptions = useMemo(
    () => (form.party === 'supplier' ? suppliers : customers).map((p) => ({ value: p.id, label: p.name })),
    [form.party, suppliers, customers],
  )
  const update = (key: string, patch: Partial<FormLine>) => setLines((ls) => ls.map((l) => (l.key === key ? { ...l, ...patch } : l)))
  const chosen = lines.filter((l) => l.product_id)
  const errors = [
    form.partyId ? null : `Choose a ${form.party}.`,
    form.title.trim() ? null : 'Give the contract a title.',
    !form.from || !form.until ? 'Enter both dates.' : form.until < form.from ? 'The end date is before the start date.' : null,
    chosen.length ? null : 'Add at least one product.',
    ...chosen.flatMap((l, idx) => {
      const out: string[] = []
      const label = products.byId.get(l.product_id)?.name ?? `Line ${idx + 1}`
      if (l.by === 'rate' && (!num(l.rate) || n(l.rate) <= 0)) out.push(`${label}: enter a rate.`)
      if (l.by === 'percent' && (!num(l.percent) || n(l.percent) < 0 || n(l.percent) > 100)) out.push(`${label}: % off MRP must be 0–100.`)
      if (l.min.trim() && (!num(l.min) || n(l.min) < 0)) out.push(`${label}: slab must be a quantity.`)
      if (l.committed.trim() && (!num(l.committed) || n(l.committed) <= 0)) out.push(`${label}: committed quantity must be above zero.`)
      return out
    }),
  ].filter(Boolean) as string[]
  const dupes = chosen.length !== new Set(chosen.map((l) => `${l.product_id}|${l.min}`)).size

  const body = (): ContractIn => ({
    ...(editing ? {} : form.party === 'supplier' ? { supplier_id: form.partyId } : { customer_id: form.partyId }),
    title: form.title.trim(),
    valid_from: form.from,
    valid_until: form.until,
    reference: form.reference.trim() || null,
    terms: form.terms.trim() || null,
    items: chosen.map((l) => ({
      product_id: l.product_id,
      unit: l.unit || null,
      rate: l.by === 'rate' ? l.rate.trim() : null,
      discount_percent: l.by === 'percent' ? l.percent.trim() : null,
      min_quantity: l.min.trim() || null,
      committed_quantity: l.committed.trim() || null,
    })),
  })
  const save = useAction(() => (editing ? contracts.update({ id: editing.id, ...body() }) : contracts.create(body())), {
    success: (c) => `${c.number} saved`,
    quiet: true,
  })

  return (
    <Sheet
      open={open}
      onClose={onClose}
      width={1000}
      title={editing ? `Edit ${editing.number}` : 'New rate contract'}
      subtitle={form.party === 'supplier' ? 'New purchase orders to this supplier take these rates automatically.' : 'These rates compete with the customer’s other prices; the best price wins.'}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            kind="primary"
            icon={<FileSignature size={14} />}
            busy={save.isPending}
            disabled={errors.length > 0}
            onClick={() =>
              save.mutate(undefined, {
                onSuccess: (c) => {
                  onClose()
                  onSaved(c.id)
                },
              })
            }
          >
            {editing ? 'Save' : 'Create contract'}
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        {save.error ? <Notice tone="bad">{errorText(save.error)}</Notice> : null}
        <div className="grid grid-cols-[auto_1fr] items-end gap-3 max-md:grid-cols-1">
          <Field label="With">
            {() => (
              <Segmented
                className={cn('w-[220px]', editing && 'pointer-events-none opacity-60')}
                value={form.party}
                onChange={(v) => setForm((f) => ({ ...f, party: v, partyId: '' }))}
                options={[
                  { value: 'supplier', label: 'Supplier' },
                  { value: 'customer', label: 'Customer' },
                ]}
              />
            )}
          </Field>
          <Field label={form.party === 'supplier' ? 'Supplier' : 'Customer'}>
            {(props) => (
              <Picker
                id={props.id}
                invalid={props['aria-invalid']}
                disabled={Boolean(editing)}
                value={form.partyId}
                placeholder={`Choose a ${form.party}…`}
                options={partyOptions}
                onChange={(v) => setForm((f) => ({ ...f, partyId: v }))}
              />
            )}
          </Field>
        </div>
        <div className="grid grid-cols-[2fr_1fr_1fr] gap-3 max-md:grid-cols-1">
          <Field label="Title">
            {(props) => <input {...props} className="field" placeholder={form.party === 'supplier' ? 'Cement annual rate 2026–27' : 'Tower B project rate'} value={form.title} onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))} />}
          </Field>
          <Field label="Valid from">
            {(props) => <input {...props} type="date" className="field" value={form.from} onChange={(e) => setForm((f) => ({ ...f, from: e.target.value }))} />}
          </Field>
          <Field label="Valid until">
            {(props) => <input {...props} type="date" className="field" value={form.until} onChange={(e) => setForm((f) => ({ ...f, until: e.target.value }))} />}
          </Field>
        </div>
        <div className="grid grid-cols-[1fr_2fr] gap-3 max-md:grid-cols-1">
          <Field label="Reference" optional>
            {(props) => <input {...props} className="field" placeholder="Their letter / PO / tender no." value={form.reference} onChange={(e) => setForm((f) => ({ ...f, reference: e.target.value }))} />}
          </Field>
          <Field label="Terms" optional>
            {(props) => <textarea {...props} rows={2} className="field min-h-[38px] py-2" placeholder="Delivery, payment, price escalation…" value={form.terms} onChange={(e) => setForm((f) => ({ ...f, terms: e.target.value }))} />}
          </Field>
        </div>

        <div>
          <div className="label">Products</div>
          <div className="space-y-2">
            {lines.map((line) => {
              const product = products.byId.get(line.product_id)
              const units = unitsOf(product, mode)
              const unitName = line.unit || product?.unit_of_measure || 'unit'
              const factor = line.unit ? units.find((u) => u.name === line.unit)?.factor ?? 1 : 1
              const mrp = n(product?.mrp) * factor
              return (
                <div key={line.key} className="flex flex-wrap items-center gap-2 rounded-[14px] bg-white/[0.03] p-2">
                  <div className="min-w-[220px] flex-[2_1_220px]">
                    <Picker
                      small
                      value={line.product_id}
                      placeholder="Choose a product…"
                      options={products.items.map(productOption)}
                      onChange={(v) => update(line.key, { product_id: v, unit: defaultUnit(products.byId.get(v), mode) })}
                    />
                  </div>
                  {units.length > 1 ? (
                    <select className="field field-sm w-[96px]" aria-label="Unit" value={line.unit} onChange={(e) => update(line.key, { unit: e.target.value })}>
                      {units.map((u) => (
                        <option key={u.name} value={u.base ? '' : u.name}>
                          {u.name}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <span className="w-[96px] truncate text-[12.5px] text-fg-3">{product?.unit_of_measure ?? ''}</span>
                  )}
                  <Segmented
                    className="w-[124px]"
                    value={line.by}
                    onChange={(v) => update(line.key, { by: v })}
                    options={[
                      { value: 'rate', label: '₹ Rate' },
                      { value: 'percent', label: '% off' },
                    ]}
                  />
                  {line.by === 'rate' ? (
                    <input className="field field-sm field-num w-[110px]" inputMode="decimal" aria-label={`Rate per ${unitName}`} placeholder={`₹ / ${unitName}`} value={line.rate} onChange={(e) => update(line.key, { rate: e.target.value })} />
                  ) : (
                    <input className="field field-sm field-num w-[110px]" inputMode="decimal" aria-label="Percent off MRP" placeholder="% off MRP" value={line.percent} onChange={(e) => update(line.key, { percent: e.target.value })} />
                  )}
                  <input className="field field-sm field-num w-[96px]" inputMode="decimal" aria-label={`Slab from quantity (${unitName})`} title="Applies from this quantity (slab)" placeholder="Slab from" value={line.min} onChange={(e) => update(line.key, { min: e.target.value })} />
                  <input className="field field-sm field-num w-[104px]" inputMode="decimal" aria-label={`Committed quantity (${unitName})`} title="Committed quantity over the contract" placeholder="Committed" value={line.committed} onChange={(e) => update(line.key, { committed: e.target.value })} />
                  <span className="min-w-[120px] flex-1 text-[11.5px] text-fg-3">
                    {product ? (
                      line.by === 'percent' && mrp > 0 && num(line.percent) ? (
                        <>= {fmtMoney(mrp * (1 - n(line.percent) / 100))} / {unitName}</>
                      ) : mrp > 0 ? (
                        <>MRP {fmtMoney(mrp)} / {unitName}</>
                      ) : null
                    ) : null}
                  </span>
                  <button
                    className="grid size-7 place-items-center rounded-full text-fg-3 hover:bg-white/8 disabled:opacity-30"
                    disabled={lines.length === 1}
                    aria-label="Remove line"
                    onClick={() => setLines((ls) => ls.filter((l) => l.key !== line.key))}
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              )
            })}
          </div>
          <Button small className="mt-2" icon={<Plus size={13} />} onClick={() => setLines((ls) => [...ls, newFormLine()])}>
            Add product
          </Button>
          <p className="mt-2 text-[12px] text-fg-3">
            <ShoppingCart size={12} className="mr-1 inline" />
            Slab and committed quantities are in the line’s unit. Leave the slab empty to apply from the first unit.
          </p>
        </div>
        {dupes ? <Notice tone="warn">The same product appears twice with the same slab.</Notice> : null}
        {errors.length ? (
          <div className="space-y-1 text-[12px] text-bad">
            {errors.map((e) => (
              <div key={e}>{e}</div>
            ))}
          </div>
        ) : null}
      </div>
    </Sheet>
  )
}
