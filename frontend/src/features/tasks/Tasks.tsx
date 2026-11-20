import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { motion } from 'motion/react'
import { Bot, CalendarClock, Check, ListChecks, MoreHorizontal, Phone, PhoneCall, Plus, RotateCcw, Sparkles } from 'lucide-react'
import { api } from '@/api/endpoints'
import { useAction } from '@/api/queries'
import type { TaskOut } from '@/api/types'
import { cn } from '@/lib/cn'
import { HeaderArt } from '@/ui/art'
import { Button, Empty, Field, Spinner } from '@/ui/core'
import { Menu, Segmented, Sheet } from '@/ui/overlays'
import { Picker } from '@/ui/pickers'
import { useCustomers, useSuppliers } from '@/ui/lines'
import { useAssistant } from '@/features/assistant/store'

type Filter = 'open' | 'overdue' | 'today' | 'done'
const FILTERS: Record<Filter, { status?: string; due?: string }> = {
  open: { status: 'OPEN' },
  overdue: { status: 'OPEN', due: 'overdue' },
  today: { status: 'OPEN', due: 'today' },
  done: { status: 'DONE,CANCELLED' },
}

const day = (offset: number) => new Date(Date.now() + offset * 86_400_000).toISOString().slice(0, 10)

function dueText(task: TaskOut) {
  if (task.due_at) {
    const at = new Date(task.due_at)
    const sameDay = at.toISOString().slice(0, 10) === day(0)
    return (sameDay ? 'Today ' : at.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }) + ' ') + at.toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit' })
  }
  if (!task.due_date) return 'No date'
  const today = day(0)
  if (task.due_date === today) return 'Today'
  if (task.due_date === day(1)) return 'Tomorrow'
  const date = new Date(task.due_date + 'T00:00:00')
  return date.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })
}

const AI_STATUS: Record<string, string> = {
  scheduled: 'PAI will call',
  calling: 'PAI is calling',
  done: 'PAI called · done',
  no_answer: 'No answer',
  failed: 'PAI could not call',
  needs_person: 'PAI called · needs you',
}

/** Follow-ups: calls to make, quotes to chase, suppliers to push. */
export function Tasks() {
  const [params, setParams] = useSearchParams()
  const filter = (params.get('show') as Filter) ?? 'open'
  const [creating, setCreating] = useState(params.get('new') === '1')
  const { ask } = useAssistant()
  const counts = useQuery({ queryKey: ['tasks', 'counts'], queryFn: api.tasks.counts })
  const list = useQuery({ queryKey: ['tasks', 'list', filter], queryFn: () => api.tasks.list({ ...FILTERS[filter], limit: 200 }) })
  const update = useAction(({ id, body }: { id: string; body: Parameters<typeof api.tasks.update>[1] }) => api.tasks.update(id, body))
  const items = list.data?.items ?? []
  return (
    <div className="flex h-full min-h-0 flex-col gap-4 px-6 pt-1 pb-5 max-md:gap-2 max-md:p-2">
      <header className="pane relative flex shrink-0 flex-wrap items-center gap-4 overflow-hidden px-5 py-4">
        <HeaderArt seed={11} />
        <span className="icon-tile relative size-11">
          <ListChecks size={20} />
        </span>
        <div className="relative min-w-0 flex-1">
          <h1 className="text-[20px] font-semibold tracking-[-0.02em]">Follow-ups</h1>
          <p className="text-[12.5px] text-fg-3">
            {counts.data ? `${counts.data.open} open · ${counts.data.overdue} overdue · ${counts.data.due_today} due today` : 'Calls to make, quotes to chase, suppliers to push.'}
          </p>
        </div>
        <div className="relative flex flex-wrap items-center gap-2">
          <Segmented
            value={filter}
            onChange={(value) => setParams({ show: value })}
            options={[
              { value: 'open', label: 'Open', count: counts.data?.open },
              { value: 'overdue', label: 'Overdue', count: counts.data?.overdue },
              { value: 'today', label: 'Today', count: counts.data?.due_today },
              { value: 'done', label: 'Done' },
            ]}
          />
          <Button icon={<Sparkles size={14} />} onClick={() => ask('Look at our open enquiries, waiting orders and late purchases, and propose the follow-ups we should plan this week — who, what and when.')}>
            Suggest follow-ups
          </Button>
          <Button kind="primary" icon={<Plus size={15} />} onClick={() => setCreating(true)}>
            New follow-up
          </Button>
        </div>
      </header>
      <section className="pane min-h-0 flex-1 overflow-y-auto p-2">
        {list.isPending ? (
          <Spinner />
        ) : !items.length ? (
          <Empty
            className="h-full"
            icon={<ListChecks size={22} />}
            title={filter === 'done' ? 'Nothing finished yet' : 'Nothing to follow up'}
            body={filter === 'done' ? undefined : 'Plan a call or a chase, or let the assistant suggest follow-ups from stale quotes and late orders.'}
          />
        ) : (
          items.map((task, index) => (
            <motion.div
              key={task.id}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: Math.min(index, 12) * 0.02 }}
              className="group flex items-center gap-3 rounded-[14px] px-3 py-2.5 hover:bg-white/[0.035]"
            >
              <button
                onClick={() => update.mutate({ id: task.id, body: { status: task.status === 'OPEN' ? 'DONE' : 'OPEN' } })}
                className={cn('grid size-6 shrink-0 place-items-center rounded-full ring-2 transition', task.status === 'DONE' ? 'bg-solid text-on-brand ring-transparent' : 'ring-white/20 hover:ring-blue')}
                aria-label={task.status === 'OPEN' ? `Mark ${task.title} done` : `Reopen ${task.title}`}
              >
                {task.status === 'DONE' ? <Check size={13} strokeWidth={3} /> : null}
              </button>
              <div className="min-w-0 flex-1">
                <div className={cn('flex items-center gap-1.5 truncate text-[13.5px] font-medium', task.status !== 'OPEN' && 'text-fg-3 line-through')}>
                  {task.kind === 'call' ? <Phone size={12} className="shrink-0" /> : null}
                  <span className="truncate">{task.title}</span>
                  {task.doer === 'pai' || task.ai_status ? (
                    <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-blue/20 px-2 py-px text-[10.5px] font-semibold no-underline">
                      <Bot size={10} /> {AI_STATUS[task.ai_status ?? 'scheduled'] ?? task.ai_status}
                    </span>
                  ) : null}
                </div>
                {task.ai_result ? <div className="truncate text-[12px] text-fg-2">{task.ai_result}</div> : null}
                <div className="flex flex-wrap items-center gap-x-2 text-[12px] text-fg-3">
                  {task.customer_id ? <Link className="hover:text-fg" to={`/customers/${task.customer_id}`}>{task.customer_name}</Link> : null}
                  {task.enquiry_id ? <Link className="hover:text-fg" to={`/enquiries/${task.enquiry_id}`}>{task.enquiry_number}</Link> : null}
                  {task.sales_order_id ? <Link className="hover:text-fg" to={`/orders/${task.sales_order_id}`}>{task.order_number}</Link> : null}
                  {task.supplier_id ? <Link className="hover:text-fg" to={`/suppliers/${task.supplier_id}`}>{task.supplier_name}</Link> : null}
                  {task.purchase_order_id ? <Link className="hover:text-fg" to={`/purchase-orders/${task.purchase_order_id}`}>{task.po_number}</Link> : null}
                  {task.notes ? <span className="truncate">{task.notes}</span> : null}
                  {task.source === 'assistant' ? <span className="flex items-center gap-1"><Sparkles size={11} /> by assistant</span> : null}
                </div>
              </div>
              {task.priority === 'HIGH' ? <span className="rounded-full bg-solid px-2 py-0.5 text-[10.5px] font-semibold text-on-brand">High</span> : null}
              <span className={cn('flex w-[110px] items-center justify-end gap-1 text-right text-[12px]', task.overdue ? 'font-semibold text-fg' : 'text-fg-3')}>
                <CalendarClock size={12} /> {task.overdue ? `Overdue · ${dueText(task)}` : dueText(task)}
              </span>
              <span className="w-[70px] truncate text-right text-[12px] text-fg-3">{task.doer === 'pai' ? 'PAI' : task.assignee ?? '—'}</span>
              <Menu
                trigger={
                  <Button kind="ghost" small iconOnly aria-label="More">
                    <MoreHorizontal size={15} />
                  </Button>
                }
                items={[
                  { label: 'Due today', icon: <CalendarClock size={14} />, onSelect: () => update.mutate({ id: task.id, body: { due_date: day(0) } }) },
                  { label: 'Due tomorrow', icon: <CalendarClock size={14} />, onSelect: () => update.mutate({ id: task.id, body: { due_date: day(1) } }) },
                  { label: 'Due next week', icon: <CalendarClock size={14} />, onSelect: () => update.mutate({ id: task.id, body: { due_date: day(7) } }) },
                  task.status === 'OPEN'
                    ? { label: 'Cancel follow-up', icon: <RotateCcw size={14} />, onSelect: () => update.mutate({ id: task.id, body: { status: 'CANCELLED' } }), separator: true, danger: true }
                    : { label: 'Reopen', icon: <RotateCcw size={14} />, onSelect: () => update.mutate({ id: task.id, body: { status: 'OPEN' } }), separator: true },
                ]}
              />
            </motion.div>
          ))
        )}
      </section>
      <TaskSheet
        open={creating}
        onClose={() => {
          setCreating(false)
          if (params.get('new')) setParams({ show: filter })
        }}
      />
    </div>
  )
}

function TaskSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const customers = useCustomers()
  const suppliers = useSuppliers()
  const users = useQuery({ queryKey: ['tasks', 'assignees'], queryFn: api.tasks.assignees, enabled: open })
  const [title, setTitle] = useState('')
  const [due, setDue] = useState(day(1))
  const [priority, setPriority] = useState<'LOW' | 'NORMAL' | 'HIGH'>('NORMAL')
  const [customer, setCustomer] = useState('')
  const [supplier, setSupplier] = useState('')
  const [assignee, setAssignee] = useState('')
  const [notes, setNotes] = useState('')
  const [kind, setKind] = useState<'todo' | 'call'>('todo')
  const [at, setAt] = useState(() => new Date(Date.now() + 3600_000).toISOString().slice(0, 16))
  const [instructions, setInstructions] = useState('')
  const [phone, setPhone] = useState('')
  const create = useAction(api.tasks.create, { success: (t) => (t.doer === 'pai' ? 'PAI will make the call at that time' : 'Follow-up planned') })
  const pai = assignee === 'pai'

  function reset() {
    setTitle('')
    setNotes('')
    setCustomer('')
    setSupplier('')
    setPriority('NORMAL')
    setDue(day(1))
    setKind('todo')
    setInstructions('')
    setPhone('')
    setAssignee('')
  }

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="New follow-up"
      subtitle="Something to do by a date, linked to who it is about."
      width={560}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            kind="primary"
            busy={create.isPending}
            disabled={!title.trim()}
            onClick={() =>
              create.mutate(
                {
                  title: title.trim(),
                  due_date: kind === 'call' ? null : due || null,
                  due_at: kind === 'call' && at ? new Date(at).toISOString() : null,
                  priority,
                  notes: notes || null,
                  customer_id: customer || null,
                  supplier_id: supplier || null,
                  assignee_id: pai ? null : assignee || null,
                  kind: pai ? 'call' : kind,
                  doer: pai ? 'pai' : 'person',
                  instructions: instructions || null,
                  call_phone: phone || null,
                },
                { onSuccess: () => { reset(); onClose() } },
              )
            }
          >
            Plan it
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-2 gap-4 max-md:grid-cols-1">
        <Field label="What has to be done" className="col-span-2 max-md:col-span-1">
          {(props) => <input {...props} className="field" autoFocus placeholder="Call Mixwell about the steel quote" value={title} onChange={(e) => setTitle(e.target.value)} />}
        </Field>
        <Field label="Type">
          {() => (
            <Segmented
              value={pai ? 'call' : kind}
              onChange={(v) => setKind(v)}
              options={[
                { value: 'todo', label: 'To-do' },
                { value: 'call', label: (<><PhoneCall size={12} /> Call</>) },
              ]}
            />
          )}
        </Field>
        {kind === 'call' || pai ? (
          <Field label="When" hint={pai ? 'PAI rings at exactly this time.' : undefined}>
            {(props) => <input {...props} type="datetime-local" className="field" value={at} onChange={(e) => setAt(e.target.value)} />}
          </Field>
        ) : (
          <Field label="Due">
            {(props) => <input {...props} type="date" className="field" value={due} onChange={(e) => setDue(e.target.value)} />}
          </Field>
        )}
        <Field label="Priority">
          {() => (
            <Segmented
              value={priority}
              onChange={setPriority}
              options={[
                { value: 'LOW', label: 'Low' },
                { value: 'NORMAL', label: 'Normal' },
                { value: 'HIGH', label: 'High' },
              ]}
            />
          )}
        </Field>
        <Field label="Customer" optional>
          {() => <Picker value={customer} onChange={setCustomer} placeholder="Choose a customer…" options={customers.map((c) => ({ value: c.id, label: c.name, detail: c.phone ?? undefined }))} />}
        </Field>
        <Field label="Supplier" optional>
          {() => <Picker value={supplier} onChange={setSupplier} placeholder="Choose a supplier…" options={suppliers.map((s) => ({ value: s.id, label: s.name, detail: s.code }))} />}
        </Field>
        <Field label="Who does it" optional hint={pai ? 'PAI, the sales AI agent, makes the call and reports back here.' : undefined}>
          {() => (
            <Picker
              value={assignee}
              onChange={(v) => (setAssignee(v), v === 'pai' && setKind('call'))}
              placeholder="Anyone"
              options={[{ value: 'pai', label: 'PAI · sales AI agent', detail: 'calls at the set time' }, ...(users.data ?? []).map((u) => ({ value: u.id, label: u.username }))]}
            />
          )}
        </Field>
        {kind === 'call' || pai ? (
          <>
            <Field label={pai ? 'Instructions for PAI' : 'What to say'} className="col-span-2 max-md:col-span-1" hint={pai ? 'What to say or find out. PAI also knows prices, stock and their orders, and can take an order.' : undefined}>
              {(props) => (
                <textarea {...props} className="field" rows={3} placeholder="Ask when the cheque for SO-2026-000012 will be ready. If they want more cement, quote today’s price." value={instructions}
                  onChange={(e) => setInstructions(e.target.value)} />
              )}
            </Field>
            <Field label="Number" optional hint="Empty uses the customer’s or supplier’s number.">
              {(props) => <input {...props} className="field" inputMode="tel" value={phone} onChange={(e) => setPhone(e.target.value)} />}
            </Field>
          </>
        ) : null}
        <Field label="Notes" optional className="col-span-2 max-md:col-span-1">
          {(props) => <textarea {...props} className="field" value={notes} onChange={(e) => setNotes(e.target.value)} />}
        </Field>
      </div>
    </Sheet>
  )
}
