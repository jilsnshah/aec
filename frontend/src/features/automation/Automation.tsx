import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Check, Inbox, Mail, MessageCircle, Package, Send, Trash2, Workflow } from 'lucide-react'
import { automation, type Outbound } from '@/api/automation'
import { useAction } from '@/api/queries'
import { fmtAgo, fmtMoney } from '@/lib/format'
import { Badge, Button, Empty, Spinner } from '@/ui/core'
import { Segmented } from '@/ui/overlays'
import { FlowEditor } from './FlowEditor'
import { ActivityView } from './Activity'

/** Settings -> Automation: the sales and purchase pipelines, step by step. */
export function AutomationPane() {
  const [flow, setFlow] = useState<'sales' | 'purchase' | 'activity'>('sales')
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex shrink-0 flex-wrap items-center gap-3 border-b border-white/7 px-5 py-4">
        <span className="icon-disc size-10">
          <Workflow size={17} />
        </span>
        <div className="min-w-[220px] flex-1">
          <h2 className="text-[17px] font-semibold tracking-[-0.02em]">Automation</h2>
          <p className="text-[12px] text-fg-3">Drag steps in, connect them, and click a step to choose who does it (System, Person, TAI, PAI), how much on its own, its limits and its AI model.</p>
        </div>
        <Segmented
          className="w-[380px] max-w-full"
          value={flow}
          onChange={setFlow}
          options={[
            { value: 'sales', label: 'Sales flow' },
            { value: 'purchase', label: 'Purchase flow' },
            { value: 'activity', label: 'Activity' },
          ]}
        />
      </header>
      {flow === 'activity' ? <ActivityView /> : <FlowEditor flowKey={flow} />}
    </div>
  )
}

const CHANNEL_ICON: Record<string, typeof Mail> = { whatsapp: MessageCircle, email: Mail }

/** What the agents prepared and a person must approve. */
export function ApprovalsPane() {
  const data = useQuery({ queryKey: ['automation', 'approvals'], queryFn: automation.approvals, refetchInterval: 20000 })
  if (data.isPending) return <Spinner />
  const { messages = [], failed = [], orders = [] } = data.data ?? {}
  const total = messages.length + failed.length + orders.length
  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <header className="flex flex-wrap items-center gap-3 border-b border-white/7 px-6 py-5">
        <span className="icon-disc size-11">
          <Inbox size={18} />
        </span>
        <div className="min-w-[220px] flex-1">
          <h2 className="text-[18px] font-semibold tracking-[-0.02em]">Approvals</h2>
          <p className="text-[12.5px] text-fg-3">Replies and orders the AI prepared on steps set to "Person approves" or outside their limits.</p>
        </div>
        <Badge tone={total ? 'sky' : 'muted'}>{total} waiting</Badge>
      </header>
      <div className="max-w-[900px] space-y-6 p-6 pb-24">
        {!total ? <Empty icon={<Check size={20} />} title="Nothing waiting" body="When TAI or PAI prepares something that needs a person, it shows up here." /> : null}
        {orders.length ? (
          <Group title="Orders to place" icon={<Package size={14} />}>
            {orders.map((order) => (
              <HeldOrderCard key={order.id} order={order} />
            ))}
          </Group>
        ) : null}
        {messages.length ? (
          <Group title="Replies to send" icon={<Send size={14} />}>
            {messages.map((m) => (
              <MessageCard key={m.id} message={m} />
            ))}
          </Group>
        ) : null}
        {failed.length ? (
          <Group title="Could not be sent" icon={<AlertTriangle size={14} />}>
            {failed.map((m) => (
              <MessageCard key={m.id} message={m} />
            ))}
          </Group>
        ) : null}
      </div>
    </div>
  )
}

function Group({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <section>
      <div className="mb-2 flex items-center gap-2 text-[13.5px] font-semibold">
        {icon} {title}
      </div>
      <div className="space-y-2.5">{children}</div>
    </section>
  )
}

function MessageCard({ message }: { message: Outbound }) {
  const [body, setBody] = useState(message.body)
  const approve = useAction(() => automation.approve({ id: message.id, body }), { success: 'Sent' })
  const discard = useAction(() => automation.discard(message.id), { success: 'Discarded' })
  const Icon = CHANNEL_ICON[message.channel] ?? MessageCircle
  return (
    <div className="card space-y-2 p-4">
      <div className="flex flex-wrap items-center gap-2 text-[12.5px]">
        <Icon size={14} />
        <b className="min-w-0 truncate">{message.to}</b>
        {message.subject ? <span className="min-w-0 truncate text-fg-3">· {message.subject}</span> : null}
        <span className="ml-auto text-fg-3">
          {message.author} · {fmtAgo(message.created_at)}
        </span>
      </div>
      {message.error ? <p className="text-[12px] font-semibold">Error: {message.error}</p> : null}
      <textarea className="field font-[inherit] text-[13px]" rows={Math.min(8, Math.max(3, body.split('\n').length + 1))} value={body} onChange={(e) => setBody(e.target.value)} aria-label="Reply" />
      <div className="flex gap-2">
        <Button small kind="primary" icon={<Send size={13} />} busy={approve.isPending} onClick={() => approve.mutate(undefined)}>
          {message.status === 'failed' ? 'Try again' : 'Approve and send'}
        </Button>
        <Button small kind="ghost" icon={<Trash2 size={13} />} busy={discard.isPending} onClick={() => discard.mutate(undefined)}>
          Discard
        </Button>
      </div>
    </div>
  )
}

function HeldOrderCard({ order }: { order: { id: string; customer: string; channel: string; sender: string; items: unknown[]; total: number; note: string | null; created_at: string } }) {
  const place = useAction(() => automation.placeDraft(order.id), { success: (r) => `Order ${r.order_number} placed` })
  const discard = useAction(() => automation.discardDraft(order.id), { success: 'Discarded' })
  return (
    <div className="card flex flex-wrap items-center gap-3 p-4">
      <span className="icon-disc size-9">
        <Package size={15} />
      </span>
      <div className="min-w-[200px] flex-1">
        <div className="text-[14px] font-semibold">{order.customer}</div>
        <div className="text-[12px] text-fg-3">
          {order.items.length} line{order.items.length === 1 ? '' : 's'} · {fmtMoney(order.total)} · via {order.channel} from {order.sender} · {fmtAgo(order.created_at)}
        </div>
        {order.note ? <div className="mt-1 text-[12px]">Held because: {order.note}</div> : null}
      </div>
      <Button small kind="primary" icon={<Check size={13} />} busy={place.isPending} onClick={() => place.mutate(undefined)}>
        Place order
      </Button>
      <Button small kind="ghost" icon={<Trash2 size={13} />} busy={discard.isPending} onClick={() => discard.mutate(undefined)}>
        Discard
      </Button>
    </div>
  )
}
