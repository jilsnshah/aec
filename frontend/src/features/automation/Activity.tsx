import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { CheckCircle2, Clock, MessageSquareWarning, Scale, Send, Star, XCircle } from 'lucide-react'
import { automation, type Rfq } from '@/api/automation'
import { useAction } from '@/api/queries'
import { cn } from '@/lib/cn'
import { fmtDateTime, fmtMoney, fmtQty } from '@/lib/format'
import { Badge, Button, Empty, Spinner } from '@/ui/core'
import { Segmented } from '@/ui/overlays'

const STEP: Record<string, string> = {
  'purchase.need_detected': 'Need detected',
  'purchase.ask_supplier': 'Asked supplier',
  'purchase.read_reply': 'Supplier replied',
  'purchase.compare_quotes': 'Compared offers',
  'purchase.approve_po': 'Purchase order',
  'purchase.send_po': 'Sent PO',
  'purchase.chase_delivery': 'Chased delivery',
  'sales.trigger_outreach': 'Reached out',
  'sales.after_sales': 'After-sales',
}
const TONE: Record<string, 'ok' | 'sky' | 'warn' | 'bad' | 'muted'> = { done: 'ok', sent: 'ok', replied: 'ok', held: 'warn', awaiting_reply: 'sky', failed: 'bad', skipped: 'muted' }

/** What the triggers did, supplier price requests and customer feedback. */
export function ActivityView() {
  const [tab, setTab] = useState<'log' | 'quotes' | 'feedback'>('log')
  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="sticky top-0 z-10 border-b border-white/7 bg-ink-850/95 px-5 py-3 backdrop-blur">
        <Segmented
          className="w-[420px] max-w-full"
          value={tab}
          onChange={setTab}
          options={[
            { value: 'log', label: 'What happened' },
            { value: 'quotes', label: 'Supplier quotes' },
            { value: 'feedback', label: 'Customer feedback' },
          ]}
        />
      </div>
      <div className="max-w-[1000px] p-5 pb-24">{tab === 'log' ? <Log /> : tab === 'quotes' ? <Quotes /> : <Feedback />}</div>
    </div>
  )
}

function Log() {
  const [step, setStep] = useState('')
  const data = useQuery({ queryKey: ['automation', 'activity', step], queryFn: () => automation.activity(step || undefined), refetchInterval: 30000 })
  return (
    <div className="space-y-3">
      <select className="field field-sm w-[240px]" value={step} onChange={(e) => setStep(e.target.value)} aria-label="Step">
        <option value="">Every step</option>
        {Object.entries(STEP).map(([key, label]) => (
          <option key={key} value={key}>
            {label}
          </option>
        ))}
      </select>
      {data.isPending ? (
        <Spinner />
      ) : !data.data?.items.length ? (
        <Empty icon={<Clock size={20} />} title="Nothing yet" body="Triggers write here every time they act: who was asked, what was bought, who was contacted." />
      ) : (
        <div className="card divide-y divide-white/6">
          {data.data.items.map((e) => (
            <div key={e.id} className="flex flex-wrap items-start gap-3 px-4 py-2.5 text-[12.5px]">
              <span className="w-[130px] shrink-0 text-fg-3">{fmtDateTime(e.created_at)}</span>
              <span className="w-[130px] shrink-0 font-semibold">{STEP[e.step] ?? e.step}</span>
              <Badge tone={TONE[e.status] ?? 'muted'}>{e.status.replace('_', ' ')}</Badge>
              <span className="min-w-[200px] flex-1 text-fg-2">{e.summary}</span>
              {e.subject_type === 'purchase_order' && e.subject_id ? (
                <Link className="text-sky" to={`/purchase-orders/${e.subject_id}`}>
                  Open PO
                </Link>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function Quotes() {
  const data = useQuery({ queryKey: ['automation', 'rfqs'], queryFn: automation.rfqs, refetchInterval: 30000 })
  if (data.isPending) return <Spinner />
  const items = data.data?.items ?? []
  if (!items.length) return <Empty icon={<Scale size={20} />} title="No price requests yet" body="When 'Need detected' finds something to buy, suppliers are asked and their offers show here." />
  return (
    <div className="space-y-4">
      {items.map((rfq) => (
        <RfqCard key={rfq.id} rfq={rfq} />
      ))}
    </div>
  )
}

function RfqCard({ rfq }: { rfq: Rfq }) {
  const decide = useAction(() => automation.decideRfq(rfq.id), { success: 'Decided' })
  const cancel = useAction(() => automation.cancelRfq(rfq.id), { success: 'Cancelled' })
  const [entering, setEntering] = useState<string | null>(null)
  const [prices, setPrices] = useState<Record<string, string>>({})
  const [days, setDays] = useState('')
  const record = useAction(() => automation.recordQuote({ id: rfq.id, supplier_id: entering!, prices, delivery_days: days ? Number(days) : null }), { success: 'Offer recorded' })
  return (
    <div className="card overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 px-4 pt-3.5 pb-2">
        <span className="text-[14px] font-semibold">{rfq.number}</span>
        <Badge tone={rfq.status === 'open' ? 'sky' : rfq.status === 'ordered' ? 'ok' : 'muted'}>{rfq.status}</Badge>
        <span className="text-[12px] text-fg-3">
          {fmtDateTime(rfq.created_at)}
          {rfq.reply_by && rfq.status === 'open' ? ` · decides by ${fmtDateTime(rfq.reply_by)}` : ''}
        </span>
        <span className="flex-1" />
        {rfq.status === 'open' ? (
          <>
            <Button small busy={decide.isPending} onClick={() => decide.mutate(undefined)}>
              Decide now
            </Button>
            <Button small kind="ghost" onClick={() => cancel.mutate(undefined)}>
              Cancel
            </Button>
          </>
        ) : null}
        {rfq.purchase_order_id ? (
          <Link className="text-[12.5px] text-sky" to={`/purchase-orders/${rfq.purchase_order_id}`}>
            Open PO
          </Link>
        ) : null}
      </div>
      <div className="overflow-x-auto">
        <table className="grid-table min-w-[640px]">
          <thead>
            <tr>
              <th>Supplier</th>
              <th>Status</th>
              {rfq.lines.map((l) => (
                <th key={l.id} className="r">
                  {l.product}
                  <div className="text-[10.5px] font-normal text-fg-3">
                    {fmtQty(l.quantity)} {l.unit}
                    {l.last_paid ? ` · last ${fmtMoney(l.last_paid)}` : ''}
                  </div>
                </th>
              ))}
              <th className="r">Days</th>
              <th className="r">Score</th>
            </tr>
          </thead>
          <tbody>
            {rfq.quotes.map((q) => (
              <tr key={q.id}>
                <td>
                  <div className="text-[13px] font-medium">{q.supplier}</div>
                  <div className="text-[11px] text-fg-3">{q.source}</div>
                </td>
                <td>
                  <span className={cn('inline-flex items-center gap-1 text-[12px]', q.status === 'replied' ? 'text-fg' : 'text-fg-3')}>
                    {q.status === 'replied' ? <CheckCircle2 size={12} /> : q.status === 'declined' || q.status === 'no_reply' ? <XCircle size={12} /> : <Send size={12} />}
                    {q.status.replace('_', ' ')}
                  </span>
                  {q.reply ? <div className="max-w-[220px] truncate text-[11px] text-fg-3" title={q.reply}>“{q.reply}”</div> : null}
                </td>
                {rfq.lines.map((l) => (
                  <td key={l.id} className="r num">
                    {q.prices[l.product_id] != null ? fmtMoney(q.prices[l.product_id]) : '—'}
                  </td>
                ))}
                <td className="r num">{q.delivery_days ?? '—'}</td>
                <td className="r num font-semibold">{q.score ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rfq.status === 'open' ? (
        <div className="flex flex-wrap items-center gap-2 border-t border-white/6 px-4 py-3 text-[12.5px]">
          <span className="text-fg-3">Offer by phone?</span>
          <select className="field field-sm w-[180px]" value={entering ?? ''} onChange={(e) => setEntering(e.target.value || null)} aria-label="Supplier">
            <option value="">Choose supplier…</option>
            {rfq.quotes.map((q) => (
              <option key={q.supplier_id} value={q.supplier_id}>
                {q.supplier}
              </option>
            ))}
          </select>
          {entering
            ? rfq.lines.map((l) => (
                <input key={l.id} className="field field-sm field-num w-[110px]" inputMode="decimal" placeholder={`${l.product.slice(0, 10)} ₹/${l.unit}`} aria-label={`Price ${l.product}`}
                  value={prices[l.product_id] ?? ''} onChange={(e) => {
                    const value = e.target.value
                    setPrices((p) => ({ ...p, [l.product_id]: value }))
                  }} />
              ))
            : null}
          {entering ? (
            <>
              <input className="field field-sm field-num w-[70px]" inputMode="numeric" placeholder="days" aria-label="Days" value={days} onChange={(e) => setDays(e.target.value)} />
              <Button small kind="primary" busy={record.isPending} onClick={() => record.mutate(undefined, { onSuccess: () => (setEntering(null), setPrices({}), setDays('')) })}>
                Record
              </Button>
            </>
          ) : null}
        </div>
      ) : null}
      {rfq.decision ? <pre className="border-t border-white/6 px-4 py-3 text-[11.5px] whitespace-pre-wrap text-fg-2">{rfq.decision}</pre> : null}
    </div>
  )
}

function Feedback() {
  const data = useQuery({ queryKey: ['automation', 'feedback'], queryFn: automation.feedback })
  if (data.isPending) return <Spinner />
  const d = data.data
  if (!d?.items.length) return <Empty icon={<Star size={20} />} title="No feedback yet" body="Turn on 'After-sales follow-up' in the sales flow to ask customers after delivery." />
  return (
    <div className="space-y-3">
      <div className="flex gap-3">
        <div className="card p-3.5">
          <div className="text-[11px] text-fg-3">Average rating</div>
          <div className="num text-[20px] font-semibold">{d.average ?? '—'} / 5</div>
        </div>
        <div className="card p-3.5">
          <div className="text-[11px] text-fg-3">Complaints</div>
          <div className="num text-[20px] font-semibold">{d.complaints}</div>
        </div>
      </div>
      <div className="card divide-y divide-white/6">
        {d.items.map((f) => (
          <div key={f.id} className="flex flex-wrap items-center gap-3 px-4 py-2.5 text-[12.5px]">
            <span className="w-[130px] text-fg-3">{fmtDateTime(f.created_at)}</span>
            <Link to={`/customers/${f.customer_id}`} className="w-[180px] truncate font-semibold hover:text-sky">
              {f.customer}
            </Link>
            <span className="w-[70px]">{f.rating ? `${f.rating} / 5` : '—'}</span>
            {f.complaint ? (
              <Badge tone="bad">
                <MessageSquareWarning size={11} /> Complaint
              </Badge>
            ) : null}
            <span className="min-w-[200px] flex-1 truncate text-fg-2">{f.comment}</span>
            {f.task_id ? (
              <Link className="text-sky" to="/tasks">
                Task
              </Link>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  )
}
