import { useState } from 'react'
import * as Popover from '@radix-ui/react-popover'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Bell, ChevronRight, Sparkles } from 'lucide-react'
import { insights, type Severity } from '@/api/insights'
import { cn } from '@/lib/cn'
import { Empty, Tip } from '@/ui/core'
import { useAssistant } from '@/features/assistant/store'

export const SEVERITY_DOT: Record<Severity, string> = {
  critical: 'bg-solid',
  warning: 'bg-blue',
  info: 'bg-fg-4',
}

/** What needs attention, one click from anywhere. */
export function AlertsBell({ className }: { className?: string }) {
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const { ask } = useAssistant()
  const data = useQuery({ queryKey: ['insights', 'alerts'], queryFn: insights.alerts, refetchInterval: 120_000 })
  const urgent = (data.data?.counts.critical ?? 0) + (data.data?.counts.warning ?? 0)
  const alerts = data.data?.alerts ?? []
  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Tip label="Needs attention" side="bottom">
        <Popover.Trigger asChild>
          <button className={cn(className, 'relative')} aria-label={`Alerts${urgent ? `, ${urgent} need attention` : ''}`}>
            <Bell size={17} />
            {urgent ? (
              <span className="num absolute -top-0.5 -right-0.5 min-w-[18px] rounded-full bg-solid px-1 text-center text-[10px] leading-[18px] font-semibold text-on-brand">{urgent}</span>
            ) : null}
          </button>
        </Popover.Trigger>
      </Tip>
      <Popover.Portal>
        <Popover.Content align="end" sideOffset={8} collisionPadding={10} className="z-[150] w-[380px] max-w-[calc(100vw-20px)] overflow-hidden rounded-[20px] bg-ink-750 shadow-pop data-[state=open]:animate-[pop_180ms_var(--ease-out-quint)_both]">
          <div className="flex items-center justify-between border-b border-white/7 px-4 py-3">
            <div>
              <div className="text-[14px] font-semibold">Needs attention</div>
              <div className="text-[11.5px] text-fg-3">
                {data.data ? `${data.data.counts.critical ?? 0} urgent · ${data.data.counts.warning ?? 0} to act on · ${data.data.counts.info ?? 0} to know` : 'Checking…'}
              </div>
            </div>
            <Link to="/insights" onClick={() => setOpen(false)} className="text-[12px] font-medium text-fg-2 hover:text-fg">
              Insights
            </Link>
          </div>
          <div className="max-h-[400px] overflow-y-auto p-1.5">
            {data.data && !alerts.length ? <Empty title="All clear" body="Nothing needs attention right now." /> : null}
            {alerts.slice(0, 14).map((alert) => (
              <button
                key={alert.id}
                onClick={() => {
                  setOpen(false)
                  navigate(alert.link)
                }}
                className="group flex w-full items-start gap-2.5 rounded-[14px] px-2.5 py-2 text-left hover:bg-white/[0.05]"
              >
                <span className={cn('mt-1.5 size-2 shrink-0 rounded-full', SEVERITY_DOT[alert.severity])} />
                <span className="min-w-0 flex-1">
                  <span className="block text-[12.5px] leading-snug font-medium">{alert.title}</span>
                  <span className="block text-[11.5px] text-fg-3">{alert.detail}</span>
                </span>
                <ChevronRight size={14} className="mt-1 text-fg-4 group-hover:text-fg-2" />
              </button>
            ))}
          </div>
          <div className="border-t border-white/7 p-2">
            <button
              onClick={() => {
                setOpen(false)
                ask('Go through everything that needs attention right now. Group it by urgency, explain the impact of each, and propose what to do first — including follow-ups to create.')
              }}
              className="flex h-9 w-full items-center justify-center gap-2 rounded-full text-[12.5px] font-semibold hover:bg-white/[0.05]"
            >
              <Sparkles size={14} /> Ask the assistant to plan this
            </button>
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}
