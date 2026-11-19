import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { CalendarClock, Check, ListChecks, Plus } from 'lucide-react'
import { api } from '@/api/endpoints'
import { useAction } from '@/api/queries'
import { cn } from '@/lib/cn'
import { Button, Empty } from '@/ui/core'

type Link = { customer_id?: string; enquiry_id?: string; sales_order_id?: string; supplier_id?: string; purchase_order_id?: string }

/** Follow-ups for one record: what is planned, done and overdue, with a quick
 *  way to plan the next one. */
export function RecordTasks({ link, suggestion }: { link: Link; suggestion: string }) {
  const tasks = useQuery({ queryKey: ['tasks', 'record', link], queryFn: () => api.tasks.list({ ...link, limit: 100 }) })
  const [title, setTitle] = useState('')
  const [due, setDue] = useState(new Date(Date.now() + 86_400_000).toISOString().slice(0, 10))
  const create = useAction(api.tasks.create, { success: 'Follow-up planned' })
  const update = useAction(({ id, status }: { id: string; status: 'OPEN' | 'DONE' }) => api.tasks.update(id, { status }))
  const items = tasks.data?.items ?? []
  return (
    <div className="space-y-3 p-5 pb-20">
      <form
        className="flex flex-wrap gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          const text = title.trim() || suggestion
          create.mutate({ title: text, due_date: due || null, ...link }, { onSuccess: () => setTitle('') })
        }}
      >
        <input className="field min-w-[220px] flex-1" placeholder={suggestion} value={title} onChange={(e) => setTitle(e.target.value)} />
        <input type="date" className="field w-[160px]" value={due} onChange={(e) => setDue(e.target.value)} />
        <Button kind="primary" type="submit" icon={<Plus size={14} />} busy={create.isPending}>
          Plan
        </Button>
      </form>
      {!items.length && !tasks.isPending ? (
        <Empty icon={<ListChecks size={20} />} title="No follow-ups yet" body="Plan a call, a reminder or a chase — it shows on Follow-ups and raises an alert when overdue." />
      ) : (
        <div className="card divide-y divide-white/6">
          {items.map((task) => (
            <div key={task.id} className="flex items-center gap-3 px-3 py-2.5">
              <button
                onClick={() => update.mutate({ id: task.id, status: task.status === 'OPEN' ? 'DONE' : 'OPEN' })}
                className={cn('grid size-5 place-items-center rounded-full ring-2', task.status === 'DONE' ? 'bg-solid text-on-brand ring-transparent' : 'ring-white/20 hover:ring-blue')}
                aria-label={task.status === 'OPEN' ? 'Mark done' : 'Reopen'}
              >
                {task.status === 'DONE' ? <Check size={11} strokeWidth={3} /> : null}
              </button>
              <span className={cn('min-w-0 flex-1 truncate text-[13px]', task.status !== 'OPEN' && 'text-fg-3 line-through')}>{task.title}</span>
              <span className={cn('flex items-center gap-1 text-[12px]', task.overdue ? 'font-semibold' : 'text-fg-3')}>
                <CalendarClock size={12} /> {task.overdue ? 'Overdue · ' : ''}
                {task.due_date ?? 'No date'}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
