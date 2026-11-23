import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Clock, MessageSquareWarning, Scale, Star } from 'lucide-react'
import { automation } from '@/api/automation'
import { fmtDateTime } from '@/lib/format'
import { Badge, Empty, Spinner } from '@/ui/core'
import { Segmented } from '@/ui/overlays'

const STEP: Record<string, string> = {
  'purchase.need_detected': 'Need detected',
  'purchase.choose_supplier': 'Chose suppliers',
  'purchase.ask_supplier': 'Purchase enquiry',
  'purchase.compare_quotes': 'Picked the offer',
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
            { value: 'quotes', label: 'Supplier offers' },
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
  return (
    <Empty icon={<Scale size={20} />} title="Supplier offers moved"
      body="Purchase enquiries, every supplier's offer and the button to order now live in Buying → Purchase Enquiries."
      action={<Link className="text-sky" to="/purchase-enquiries">Open Purchase Enquiries</Link>} />
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
