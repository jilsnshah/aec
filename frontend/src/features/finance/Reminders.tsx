import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { BellRing, CheckCircle2, Copy, MessageCircle, Phone } from 'lucide-react'
import { toast } from 'sonner'
import { useAction } from '@/api/queries'
import { reminders, type ReminderRow } from '@/api/records'
import { cn } from '@/lib/cn'
import { fmtAgo, fmtMoney } from '@/lib/format'
import { Badge, Button, Empty, Spinner } from '@/ui/core'
import { AiStrip } from '@/ui/smart'

const wa = (phone: string | null, text: string) => (phone ? `https://wa.me/${phone.replace(/\D/g, '').replace(/^(\d{10})$/, '91$1')}?text=${encodeURIComponent(text)}` : `https://wa.me/?text=${encodeURIComponent(text)}`)

/** Overdue customers at the right reminder level, with the message ready to send. */
export function RemindersView() {
  const data = useQuery({ queryKey: ['finance', 'reminders'], queryFn: reminders.due })
  const [open, setOpen] = useState<string | null>(null)
  if (data.isPending) return <Spinner />
  const d = data.data
  if (!d || !d.customers.length) return <Empty icon={<CheckCircle2 size={20} />} title="Nobody to remind" body="No customer has an overdue invoice." />
  const finals = d.customers.filter((r) => r.level === 3)
  const never = d.customers.filter((r) => !r.reminders_sent)
  return (
    <div className="space-y-4">
      <AiStrip
        title="Collections"
        insights={[
          { icon: BellRing, text: <><b>{fmtMoney(d.total_overdue)}</b> overdue across {d.customers.length} customers.</> },
          ...(never.length ? [{ icon: MessageCircle, text: <><b>{never.length}</b> have not been reminded yet.</> }] : []),
          ...(finals.length ? [{ icon: Phone, text: <><b>{finals.length}</b> are more than 45 days late — call them.</> }] : []),
        ]}
        prompts={[{ label: 'Plan collections', question: 'Use payment_reminders and receivables: in what order should I chase customers today, what should I say to each, and whose new orders should be held?' }]}
      />
      <div className="flex flex-wrap gap-2 text-[12px] text-fg-3">
        {d.levels.map((level) => (
          <span key={level.level} className="flex items-center gap-1.5">
            <LevelBadge level={level.level as 1 | 2 | 3} name={level.name} /> from {level.from_days} day{level.from_days === 1 ? '' : 's'} late
          </span>
        ))}
      </div>
      <div className="space-y-2">
        {d.customers.map((row) => (
          <ReminderCard key={row.customer_id} row={row} expanded={open === row.customer_id} onToggle={() => setOpen(open === row.customer_id ? null : row.customer_id)} />
        ))}
      </div>
    </div>
  )
}

function LevelBadge({ level, name }: { level: 1 | 2 | 3; name: string }) {
  return <Badge tone={level === 3 ? 'bad' : level === 2 ? 'sky' : 'muted'}>{name}</Badge>
}

function ReminderCard({ row, expanded, onToggle }: { row: ReminderRow; expanded: boolean; onToggle: () => void }) {
  const navigate = useNavigate()
  const sent = useAction(reminders.sent, { success: 'Reminder logged; follow-up planned' })
  return (
    <div className={cn('card p-4', row.level === 3 && 'ring-2 ring-[#0b0b0c] dark:ring-white/40')}>
      <div className="flex flex-wrap items-center gap-3">
        <button onClick={() => navigate(`/customers/${row.customer_id}?tab=account`)} className="min-w-0 flex-1 text-left">
          <div className="flex items-center gap-2">
            <span className="truncate text-[14px] font-semibold">{row.name}</span>
            <LevelBadge level={row.level} name={row.level_name} />
          </div>
          <div className="text-[12px] text-fg-3">
            {row.invoices} invoice{row.invoices === 1 ? '' : 's'} · oldest {row.oldest_days} days late · {row.last_reminded ? `reminded ${fmtAgo(row.last_reminded)} (${row.reminders_sent}×)` : 'never reminded'}
          </div>
        </button>
        <span className="num text-[17px] font-semibold">{fmtMoney(row.overdue)}</span>
        <div className="flex gap-1.5">
          <Button small kind="ghost" onClick={onToggle}>
            {expanded ? 'Hide' : 'Message'}
          </Button>
          {row.phone ? (
            <a className="btn btn-sm" href={`tel:${row.phone}`} onClick={() => sent.mutate({ id: row.customer_id, channel: 'call' })}>
              <Phone size={13} /> Call
            </a>
          ) : null}
          <a className="btn btn-sm btn-primary" href={wa(row.phone, row.message)} target="_blank" rel="noreferrer" onClick={() => sent.mutate({ id: row.customer_id, channel: 'whatsapp' })}>
            <MessageCircle size={13} /> WhatsApp
          </a>
        </div>
      </div>
      {expanded ? (
        <div className="mt-3 rounded-xl bg-white/5 p-3">
          <pre className="font-[inherit] text-[12.5px] whitespace-pre-wrap text-fg-2" data-selectable>
            {row.message}
          </pre>
          <div className="mt-2 flex gap-2">
            <Button small icon={<Copy size={13} />} onClick={() => navigator.clipboard.writeText(row.message).then(() => toast.success('Copied'))}>
              Copy
            </Button>
            <Button small kind="ghost" onClick={() => sent.mutate({ id: row.customer_id, channel: 'email' })}>
              Mark sent by email
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  )
}
