import { useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, ClipboardCheck, History, Minus, PackageSearch, Plus, Scale, Sparkles, TrendingDown, TrendingUp } from 'lucide-react'
import { api } from '@/api/endpoints'
import { useAction } from '@/api/queries'
import { stock, type AdjustmentLineIn } from '@/api/records'
import { cn } from '@/lib/cn'
import { fmtDate, fmtDateTime, fmtMoney, fmtQty } from '@/lib/format'
import { Badge, Button, Empty, Field, Notice, SearchBox, Spinner } from '@/ui/core'
import { Sheet, TabPanel, Tabs, useConfirm } from '@/ui/overlays'
import { HeaderArt } from '@/ui/art'
import { AiStrip, PageGuide, Stat } from '@/ui/smart'
import { useWarehouses } from './WarehouseSelect'

const REASONS: { value: string; label: string; sign: 1 | -1 | 0 }[] = [
  { value: 'damaged', label: 'Damaged', sign: -1 },
  { value: 'lost', label: 'Lost or stolen', sign: -1 },
  { value: 'expired', label: 'Expired', sign: -1 },
  { value: 'sample', label: 'Sample or own use', sign: -1 },
  { value: 'found', label: 'Found', sign: 1 },
  { value: 'correction', label: 'Correction', sign: 0 },
]

/** Physical stock count: what the books say, what is on the shelf, and the
 *  difference valued at cost — posted in one go. Plus every adjustment made. */
export function StockCount() {
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') ?? 'count'
  return (
    <div className="flex h-full min-h-0 flex-col gap-4 px-6 pt-1 pb-5 max-md:gap-2 max-md:p-2">
      <header className="pane relative flex shrink-0 flex-wrap items-center gap-4 overflow-hidden px-5 py-4">
        <HeaderArt seed={9} />
        <span className="icon-tile relative size-11">
          <ClipboardCheck size={20} />
        </span>
        <div className="relative min-w-0 flex-1">
          <h1 className="flex items-center gap-1.5 text-[20px] font-semibold tracking-[-0.02em]">
            Stock count
            <PageGuide
              title="Counting and adjusting stock"
              points={[
                { icon: PackageSearch, text: 'Count what is on the shelf and type it in. Only products whose count differs from the books are adjusted.' },
                { icon: Scale, text: 'Each difference is valued at FIFO cost, so you see what was lost or found in rupees before posting.' },
                { icon: AlertTriangle, text: 'If the shelf holds less than is set aside for customers, the newest orders become short first.' },
                { icon: History, text: 'Damage, loss, samples and found stock can be recorded one product at a time from the product page.' },
              ]}
            />
          </h1>
          <p className="text-[12.5px] text-fg-3">Check the books against the shelf, record damage and loss, and see what it cost.</p>
        </div>
      </header>
      <section className="pane flex min-h-0 flex-1 flex-col overflow-hidden">
        <Tabs
          value={tab}
          onChange={(value) => setParams({ tab: value })}
          className="min-h-0 flex-1"
          tabs={[
            { value: 'count', label: 'Count' },
            { value: 'history', label: 'Adjustments' },
          ]}
        >
          <TabPanel value="count">
            <CountSheet onDone={() => setParams({ tab: 'history' })} />
          </TabPanel>
          <TabPanel value="history">
            <HistoryView />
          </TabPanel>
        </Tabs>
      </section>
    </div>
  )
}

function CountSheet({ onDone }: { onDone: () => void }) {
  const [category, setCategory] = useState('')
  const [warehouse, setWarehouse] = useState('')
  const houses = useWarehouses()
  const [search, setSearch] = useState('')
  const [counted, setCounted] = useState<Record<string, string>>({})
  const [onlyEntered, setOnlyEntered] = useState(false)
  const confirm = useConfirm()
  const sheet = useQuery({ queryKey: ['stock', 'count-sheet', category, warehouse], queryFn: () => stock.countSheet(category || undefined, warehouse || undefined) })
  const categories = useQuery({ queryKey: ['products', 'categories'], queryFn: api.products.categories })
  const post = useAction(stock.post, { success: (r) => `${r.count_number}: ${r.adjusted} adjusted, ${r.matched} matched` })
  const rows = useMemo(
    () => (sheet.data?.products ?? []).filter((row) => (!search || `${row.name} ${row.sku}`.toLowerCase().includes(search.toLowerCase())) && (!onlyEntered || counted[row.product_id] !== undefined)),
    [sheet.data, search, onlyEntered, counted],
  )
  const entered = (sheet.data?.products ?? []).filter((row) => counted[row.product_id] !== undefined && counted[row.product_id] !== '' && !Number.isNaN(Number(counted[row.product_id])))
  const diffs = entered.map((row) => ({ row, diff: Number(counted[row.product_id]) - row.system_quantity }))
  const gains = diffs.filter((d) => d.diff > 0).reduce((sum, d) => sum + d.diff * d.row.average_cost, 0)
  const losses = diffs.filter((d) => d.diff < 0).reduce((sum, d) => sum + -d.diff * d.row.average_cost, 0)
  const belowReserved = diffs.filter((d) => Number(counted[d.row.product_id]) < d.row.reserved)

  async function submit() {
    const changed = diffs.filter((d) => Math.abs(d.diff) > 0.0005).length
    const answer = await confirm.ask({
      title: `Post count of ${entered.length} products?`,
      body: `${changed} differ from the books: ${fmtMoney(gains)} found, ${fmtMoney(losses)} lost at cost.${belowReserved.length ? ` ${belowReserved.length} fall below what is set aside, so the newest orders become short.` : ''} The ${entered.length - changed} that match are recorded as checked.`,
      confirm: 'Post count',
    })
    if (!answer.ok) return
    const lines: AdjustmentLineIn[] = entered.map((row) => ({ product_id: row.product_id, counted_quantity: counted[row.product_id], warehouse_id: warehouse || undefined }))
    post.mutate({ lines, as_count: true }, { onSuccess: () => (setCounted({}), onDone()) })
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-white/7 px-5 py-3">
        <div className="w-[240px] max-md:w-full">
          <SearchBox value={search} onChange={setSearch} placeholder="Product or code" />
        </div>
        <select className="field field-sm w-[180px]" value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Category">
          <option value="">All categories</option>
          {(categories.data ?? []).map((c) => (
            <option key={c.name} value={c.name}>
              {c.name}
            </option>
          ))}
        </select>
        {houses.usable.length > 1 ? (
          <select className="field field-sm w-[200px]" value={warehouse} onChange={(e) => (setWarehouse(e.target.value), setCounted({}))} aria-label="Warehouse">
            <option value="">All warehouses</option>
            {houses.usable.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>
        ) : null}
        <button className={cn('h-[30px] rounded-full px-3 text-[12px] font-semibold', onlyEntered ? 'brand-fill' : 'bg-ink-700 text-fg-2')} onClick={() => setOnlyEntered(!onlyEntered)}>
          Only counted ({entered.length})
        </button>
        <Button small kind="ghost" onClick={() => setCounted(Object.fromEntries((sheet.data?.products ?? []).map((row) => [row.product_id, String(row.system_quantity)])))}>
          Fill with book quantities
        </Button>
        <span className="flex-1" />
        <Button kind="primary" icon={<ClipboardCheck size={14} />} disabled={!entered.length} busy={post.isPending} onClick={submit}>
          Post count
        </Button>
      </div>
      <div className="grid shrink-0 grid-cols-4 gap-3 px-5 py-3 max-lg:grid-cols-2">
        <Stat strong icon={ClipboardCheck} label="Counted" value={`${entered.length} / ${sheet.data?.products.length ?? 0}`} hint="products with a count entered" />
        <Stat icon={TrendingUp} label="Found" value={fmtMoney(gains)} hint={`${diffs.filter((d) => d.diff > 0).length} products more than the books`} />
        <Stat icon={TrendingDown} label="Missing" value={fmtMoney(losses)} hint={`${diffs.filter((d) => d.diff < 0).length} products fewer than the books`} />
        <Stat icon={Scale} label="Net at cost" value={fmtMoney(gains - losses)} hint={belowReserved.length ? `${belowReserved.length} below what customers are owed` : 'valued at average cost'} />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto pb-20">
        {sheet.isPending ? (
          <Spinner />
        ) : !rows.length ? (
          <Empty icon={<PackageSearch size={20} />} title="No products to count" />
        ) : (
          <table className="grid-table">
            <thead>
              <tr>
                <th>Product</th>
                <th className="r">Books</th>
                <th className="r">Set aside</th>
                <th className="r w-[140px]">Counted</th>
                <th className="r">Difference</th>
                <th className="r">Value</th>
                <th className="r">Last counted</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const value = counted[row.product_id]
                const has = value !== undefined && value !== '' && !Number.isNaN(Number(value))
                const diff = has ? Number(value) - row.system_quantity : 0
                return (
                  <tr key={row.product_id} className={cn(has && Math.abs(diff) > 0.0005 && 'bg-peri/15')}>
                    <td>
                      <div className="text-[13px] font-medium">{row.name}</div>
                      <div className="text-[11.5px] text-fg-3">
                        {row.sku}
                        {row.category ? ` · ${row.category}` : ''}
                      </div>
                    </td>
                    <td className="r num">
                      {fmtQty(row.system_quantity)} <span className="text-fg-3">{row.unit}</span>
                    </td>
                    <td className="r num text-fg-3">{row.reserved ? fmtQty(row.reserved) : '—'}</td>
                    <td className="r">
                      <input
                        inputMode="decimal"
                        aria-label={`Counted ${row.name}`}
                        className="field field-sm w-[110px] text-right"
                        placeholder="—"
                        value={value ?? ''}
                        onChange={(e) =>
                          setCounted((current) => {
                            const next = { ...current }
                            if (e.target.value === '') delete next[row.product_id]
                            else next[row.product_id] = e.target.value
                            return next
                          })
                        }
                      />
                    </td>
                    <td className={cn('r num font-semibold', !has && 'text-fg-4')}>
                      {has ? (Math.abs(diff) < 0.0005 ? <Badge tone="ok">Matches</Badge> : `${diff > 0 ? '+' : ''}${fmtQty(diff)}`) : '—'}
                    </td>
                    <td className="r num">{has && Math.abs(diff) > 0.0005 ? fmtMoney(diff * row.average_cost) : '—'}</td>
                    <td className="r text-[12px] text-fg-3">{row.last_counted ? fmtDate(row.last_counted) : 'never'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
      {confirm.element}
    </div>
  )
}

function HistoryView() {
  const navigate = useNavigate()
  const [reason, setReason] = useState('')
  const data = useQuery({ queryKey: ['stock', 'adjustments', reason], queryFn: () => stock.adjustments({ reason: reason || undefined, limit: 300 }) })
  if (data.isPending) return <Spinner />
  const d = data.data
  if (!d || (!d.total && !reason)) return <Empty icon={<History size={20} />} title="No adjustments yet" body="Counts, damage, loss and stock found appear here with their value at cost." />
  const totalLoss = d.by_reason.filter((r) => r.value_change < 0).reduce((sum, r) => sum + r.value_change, 0)
  return (
    <div className="space-y-4 p-5 pb-20">
      <AiStrip
        title="Shrinkage"
        insights={[
          { icon: TrendingDown, text: <>Stock written off so far: <b>{fmtMoney(-totalLoss)}</b> at cost.</> },
          ...d.by_reason
            .slice()
            .sort((a, b) => a.value_change - b.value_change)
            .slice(0, 2)
            .map((r) => ({ icon: AlertTriangle, text: <>{r.label}: <b>{fmtMoney(r.value_change)}</b> over {r.count} adjustments.</>, onClick: () => setReason(r.reason) })),
        ]}
        prompts={[{ label: 'Where are we losing stock?', question: 'Where are we losing stock? Use list_stock_adjustments: which products and reasons cost the most, any pattern, and what to change.' }]}
      />
      <div className="flex flex-wrap gap-1.5">
        <button className={cn('h-[30px] rounded-full px-3 text-[12px] font-semibold', !reason ? 'brand-fill' : 'bg-ink-700 text-fg-2')} onClick={() => setReason('')}>
          All
        </button>
        {d.by_reason.map((r) => (
          <button key={r.reason} className={cn('h-[30px] rounded-full px-3 text-[12px] font-semibold', reason === r.reason ? 'brand-fill' : 'bg-ink-700 text-fg-2')} onClick={() => setReason(r.reason)}>
            {r.label} · {r.count}
          </button>
        ))}
      </div>
      <div className="card overflow-hidden">
        <table className="grid-table">
          <thead>
            <tr>
              <th>Adjustment</th>
              <th>Product</th>
              <th>Reason</th>
              <th className="r">Books → counted</th>
              <th className="r">Change</th>
              <th className="r">Value</th>
            </tr>
          </thead>
          <tbody>
            {d.items.map((a) => (
              <tr key={a.id} className="cursor-pointer" onClick={() => navigate(`/products/${a.product_id}`)}>
                <td>
                  <div className="num text-[13px] font-medium">{a.number}</div>
                  <div className="text-[11.5px] text-fg-3">
                    {fmtDateTime(a.created_at)}
                    {a.count_number ? ` · ${a.count_number}` : ''}
                  </div>
                </td>
                <td className="text-[13px]">{a.product_name}</td>
                <td>
                  <Badge tone={a.quantity_change < 0 ? 'bad' : 'sky'}>{a.reason_label}</Badge>
                  {a.note ? <div className="mt-0.5 text-[11.5px] text-fg-3">{a.note}</div> : null}
                  {a.released_to_short ? <div className="mt-0.5 text-[11.5px] font-semibold">{fmtQty(a.released_to_short)} became short</div> : null}
                </td>
                <td className="r num text-fg-3">
                  {fmtQty(a.system_quantity)} → {fmtQty(a.system_quantity + a.quantity_change)}
                </td>
                <td className="r num font-semibold">
                  {a.quantity_change > 0 ? '+' : ''}
                  {fmtQty(a.quantity_change)} {a.unit}
                </td>
                <td className="r num">{fmtMoney(a.value_change)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/** Record damage, loss, samples or stock found for one product. */
export function AdjustSheet({ open, onClose, product }: { open: boolean; onClose: () => void; product: { id: string; name: string; unit_of_measure: string; physical_stock: string } }) {
  const [reason, setReason] = useState('damaged')
  const [qty, setQty] = useState('')
  const [direction, setDirection] = useState<1 | -1>(-1)
  const [note, setNote] = useState('')
  const post = useAction(stock.post, { success: 'Stock adjusted' })
  const sign = REASONS.find((r) => r.value === reason)?.sign || direction
  const change = sign * Number(qty || 0)
  const after = Number(product.physical_stock) + change
  return (
    <Sheet
      open={open}
      onClose={onClose}
      width={520}
      title={`Adjust ${product.name}`}
      subtitle="For damage, loss, samples or stock found. To check many products, use Stock count."
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            kind="primary"
            busy={post.isPending}
            disabled={!qty || Number(qty) <= 0 || after < 0}
            onClick={() => post.mutate({ lines: [{ product_id: product.id, quantity_change: String(change), reason, note: note || undefined }] }, { onSuccess: () => (setQty(''), setNote(''), onClose()) })}
          >
            Post adjustment
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="Reason">
          {(props) => (
            <select {...props} className="field" value={reason} onChange={(e) => setReason(e.target.value)}>
              {REASONS.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
          )}
        </Field>
        {reason === 'correction' ? (
          <div className="flex gap-2">
            <Button kind={direction === -1 ? 'primary' : 'default'} icon={<Minus size={14} />} onClick={() => setDirection(-1)}>
              Remove
            </Button>
            <Button kind={direction === 1 ? 'primary' : 'default'} icon={<Plus size={14} />} onClick={() => setDirection(1)}>
              Add
            </Button>
          </div>
        ) : null}
        <Field label={`Quantity (${product.unit_of_measure})`}>{(props) => <input {...props} inputMode="decimal" className="field" value={qty} onChange={(e) => setQty(e.target.value)} />}</Field>
        <Field label="Note" optional>
          {(props) => <input {...props} className="field" placeholder="What happened" value={note} onChange={(e) => setNote(e.target.value)} />}
        </Field>
        {qty ? (
          after < 0 ? (
            <Notice tone="bad">Only {fmtQty(product.physical_stock)} in stock.</Notice>
          ) : (
            <Notice tone="sky" icon={<Sparkles size={14} />}>
              Stock goes from {fmtQty(product.physical_stock)} to {fmtQty(after)} {product.unit_of_measure}. Losses are valued at FIFO cost; if it drops below what is set aside, the newest orders become short.
            </Notice>
          )
        ) : null}
      </div>
    </Sheet>
  )
}
