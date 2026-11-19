import * as Popover from '@radix-ui/react-popover'
import { useQuery } from '@tanstack/react-query'
import { useRef, useState, type ReactNode } from 'react'
import { ai } from '@/api/ai'
import { useNavigate } from 'react-router-dom'
import {
  AlertOctagon,
  AlertTriangle,
  ArrowUpRight,
  Ban,
  CheckCircle2,
  CircleDollarSign,
  CircleHelp,
  ClipboardList,
  History,
  Info,
  Lightbulb,
  ListChecks,
  Loader2,
  MessageSquareQuote,
  PackageCheck,
  PackageMinus,
  PackagePlus,
  ScanLine,
  ShoppingCart,
  Sparkles,
  ThumbsDown,
  Trophy,
  Truck,
  type LucideIcon,
} from 'lucide-react'
import { records, type EventKind, type OrderPayment, type OrderWarning, type TimelineFor } from '@/api/records'
import { cn } from '@/lib/cn'
import { fmtAgo, fmtDateTime, fmtMoney } from '@/lib/format'
import { useAssistant } from '@/features/assistant/store'
import { Badge, Empty, Spinner } from './core'

/* ------------------------------------------------------------ quick chips */
export interface Chip<K extends string = string> {
  key: K
  label: string
  count?: number
  icon?: LucideIcon
  hot?: boolean
}

/** Quick filters with counts: one tap narrows the list. Hot chips (something
 *  needs doing) carry a dot. */
export function QuickChips<K extends string>({ chips, value, onChange }: { chips: Chip<K>[]; value: K; onChange: (key: K) => void }) {
  return (
    <div className="-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-0.5 [scrollbar-width:none]">
      {chips.map((chip) => {
        const Icon = chip.icon
        const active = chip.key === value
        return (
          <button
            key={chip.key}
            onClick={() => onChange(chip.key)}
            className={cn(
              'relative inline-flex h-[30px] shrink-0 items-center gap-1.5 rounded-full px-3 text-[12px] font-semibold whitespace-nowrap transition-colors',
              active ? 'brand-fill' : 'bg-ink-700 text-fg-2 ring-1 ring-inset ring-[var(--hair)] hover:bg-ink-600 hover:text-fg',
            )}
            aria-pressed={active}
          >
            {Icon ? <Icon size={13} strokeWidth={2.2} /> : null}
            {chip.label}
            {chip.count !== undefined ? (
              <span className={cn('num rounded-full px-1.5 text-[10.5px] leading-[16px]', active ? 'bg-white/20' : 'bg-white/8 text-fg-3')}>{chip.count}</span>
            ) : null}
            {chip.hot && !active ? <span className="absolute -top-0.5 -right-0.5 size-2 rounded-full bg-blue ring-2 ring-[var(--c-ink-850)]" /> : null}
          </button>
        )
      })}
    </div>
  )
}

/* ------------------------------------------------------------ AI strip */
export interface Insight {
  icon?: LucideIcon
  text: ReactNode
  /** A filter or page to open. */
  onClick?: () => void
}

/** A sky-blue panel with what the data says about this page, and questions the
 *  assistant can answer about it. Facts come from the caller's figures. */
export function AiStrip({ title = 'What needs attention', insights, prompts, className, wide }: { title?: string; insights: Insight[]; prompts: { label: string; question: string }[]; className?: string; wide?: boolean }) {
  const { ask } = useAssistant()
  const shown = insights.filter(Boolean).slice(0, 4)
  return (
    <div className={cn('pane-contrast relative overflow-hidden rounded-[18px]! p-3.5', wide && 'flex flex-wrap items-center gap-x-5 gap-y-2 py-3', className)}>
      <div className="flex shrink-0 items-center gap-2">
        <span className="glass-tile size-7 rounded-[10px]!">
          <Sparkles size={14} />
        </span>
        <span className="text-[12.5px] font-semibold">{title}</span>
      </div>
      {shown.length ? (
        <ul className={wide ? 'flex min-w-0 flex-1 flex-wrap gap-x-5 gap-y-1' : 'mt-2.5 space-y-1.5'}>
          {shown.map((insight, index) => {
            const Icon = insight.icon ?? Lightbulb
            return (
              <li key={index}>
                <button
                  disabled={!insight.onClick}
                  onClick={insight.onClick}
                  className={cn('group flex w-full items-start gap-2 rounded-lg px-1 py-0.5 text-left text-[12.5px] leading-snug', insight.onClick && 'hover:bg-[#fff]/35')}
                >
                  <Icon size={13} className="mt-0.5 shrink-0 opacity-75" />
                  <span className="min-w-0 flex-1">{insight.text}</span>
                  {insight.onClick ? <ArrowUpRight size={13} className="mt-0.5 shrink-0 opacity-0 transition-opacity group-hover:opacity-70" /> : null}
                </button>
              </li>
            )
          })}
        </ul>
      ) : (
        <p className="mt-2 flex items-center gap-1.5 text-[12.5px] opacity-75">
          <CheckCircle2 size={13} /> Nothing urgent here.
        </p>
      )}
      {prompts.length ? (
        <div className={cn('flex flex-wrap gap-1.5', !wide && 'mt-3')}>
          {prompts.map((prompt) => (
            <button
              key={prompt.label}
              onClick={() => ask(prompt.question)}
              className="inline-flex h-[26px] items-center gap-1 rounded-full bg-[#0b0b0c] px-2.5 text-[11.5px] font-semibold text-[#fff] transition-transform hover:scale-[1.03]"
            >
              <Sparkles size={11} /> {prompt.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  )
}

/** A small "ask the assistant about this" button for inspectors. */
export function AskButton({ question, label = 'Ask AI' }: { question: string; label?: string }) {
  const { ask } = useAssistant()
  return (
    <button onClick={() => ask(question)} className="btn btn-quiet h-[34px]! gap-1.5!" title="Ask the assistant about this record">
      <Sparkles size={14} /> {label}
    </button>
  )
}

/* ------------------------------------------------------------ page guide */
/** A "?" beside a page title: what the page is for and how to use it. */
export function PageGuide({ title, points }: { title: string; points: { icon?: LucideIcon; text: ReactNode }[] }) {
  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button className="grid size-7 place-items-center rounded-full text-fg-3 transition-colors hover:bg-white/8 hover:text-fg" aria-label="How this page works">
          <CircleHelp size={16} />
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content sideOffset={8} align="start" className="z-50 w-[320px] rounded-2xl border border-[var(--card-border)] bg-ink-850 p-4 shadow-[var(--shadow-lift)] animate-fade">
          <div className="flex items-center gap-2">
            <span className="icon-disc size-7">
              <Lightbulb size={14} />
            </span>
            <span className="text-[13.5px] font-semibold">{title}</span>
          </div>
          <ul className="mt-3 space-y-2.5">
            {points.map((point, index) => {
              const Icon = point.icon ?? CheckCircle2
              return (
                <li key={index} className="flex gap-2.5 text-[12.5px] leading-snug text-fg-2">
                  <Icon size={14} className="mt-px shrink-0 text-fg-3" />
                  <span>{point.text}</span>
                </li>
              )
            })}
          </ul>
          <Popover.Arrow className="fill-[var(--c-ink-850)]" />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}

/* ------------------------------------------------------------ payments */
const PAY: Record<OrderPayment['status'], [string, 'ok' | 'sky' | 'muted' | 'bad']> = {
  paid: ['Paid', 'ok'],
  partly_paid: ['Part paid', 'sky'],
  unpaid: ['Unpaid', 'muted'],
  overdue: ['Overdue', 'bad'],
}
export function PayBadge({ payment }: { payment?: OrderPayment }) {
  if (!payment) return null
  const [label, tone] = PAY[payment.status]
  return (
    <Badge tone={tone} title={`${fmtMoney(payment.paid)} paid of ${fmtMoney(payment.invoiced)} delivered`}>
      <CircleDollarSign size={11} /> {payment.status === 'overdue' ? `${label} ${payment.days_overdue}d` : label}
    </Badge>
  )
}

export function useOrderPayments() {
  return useQuery({ queryKey: ['records', 'order-payments'], queryFn: records.orderPayments, staleTime: 30_000 })
}

/* ------------------------------------------------------------ warnings */
const WARN_ICON = { critical: AlertOctagon, warning: AlertTriangle, info: Info }
export function WarningList({ warnings }: { warnings: OrderWarning[] }) {
  if (!warnings.length) return null
  return (
    <div className="space-y-1.5">
      {warnings.map((warning, index) => {
        const Icon = WARN_ICON[warning.level]
        return (
          <div
            key={index}
            className={cn(
              'flex items-start gap-2 rounded-xl px-3 py-2 text-[12.5px] leading-snug',
              warning.level === 'critical' ? 'bg-[#0b0b0c] text-[#fff]' : warning.level === 'warning' ? 'bg-peri/45 text-fg' : 'bg-white/6 text-fg-2',
            )}
          >
            <Icon size={14} className="mt-px shrink-0" />
            <span>{warning.text}</span>
          </div>
        )
      })}
    </div>
  )
}

/* ------------------------------------------------------------ timeline */
const EVENT: Record<EventKind, LucideIcon> = {
  order: ShoppingCart,
  cancel: Ban,
  enquiry: MessageSquareQuote,
  won: Trophy,
  lost: ThumbsDown,
  delivery: Truck,
  payment: CircleDollarSign,
  purchase: ClipboardList,
  receipt: PackageCheck,
  in: PackagePlus,
  out: PackageMinus,
  task: ListChecks,
  done: CheckCircle2,
}

/** Everything that happened to a record, newest first, each with its icon. */
export function Timeline({ target }: { target: TimelineFor }) {
  const navigate = useNavigate()
  const data = useQuery({ queryKey: ['records', 'timeline', target], queryFn: () => records.timeline(target) })
  if (data.isPending) return <Spinner />
  const events = data.data?.events ?? []
  if (!events.length) return <Empty icon={<History size={20} />} title="No activity yet" body="Orders, deliveries, payments and follow-ups appear here as they happen." />
  return (
    <ol className="relative space-y-1 px-7 py-5 max-md:px-4">
      <span className="absolute top-8 bottom-8 left-[43px] w-px bg-white/10 max-md:left-[27px]" />
      {events.map((event, index) => {
        const Icon = EVENT[event.kind] ?? History
        const strong = event.kind === 'payment' || event.kind === 'won' || event.kind === 'delivery'
        return (
          <li key={index}>
            <button
              disabled={!event.link}
              onClick={() => event.link && navigate(event.link)}
              className={cn('relative flex w-full items-start gap-3 rounded-xl px-2 py-2 text-left', event.link && 'hover:bg-white/[0.04]')}
            >
              <span className={cn('relative z-[1] grid size-8 shrink-0 place-items-center rounded-full', strong ? 'icon-disc' : 'bg-ink-700 text-fg-2 ring-1 ring-[var(--hair)]')}>
                <Icon size={14} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-[13px] font-medium">{event.title}</span>
                <span className="block truncate text-[12px] text-fg-3">
                  {fmtDateTime(event.at)}
                  {event.detail ? ` · ${event.detail}` : ''}
                </span>
              </span>
              <span className="shrink-0 text-right">
                {event.amount !== null ? <span className="num block text-[13px] font-semibold">{fmtMoney(event.amount)}</span> : null}
                <span className="block text-[11px] text-fg-3">{fmtAgo(event.at)}</span>
              </span>
            </button>
          </li>
        )
      })}
    </ol>
  )
}

/* ------------------------------------------------------------ mini charts */
/** Bars for a short monthly series; the latest bar is blue. */
export function MiniBars({ values, labels, format }: { values: number[]; labels: string[]; format: (value: number) => string }) {
  const max = Math.max(1, ...values)
  return (
    <div className="flex h-[92px] items-end gap-1.5">
      {values.map((value, index) => (
        <div key={labels[index]} className="group relative flex h-full min-w-0 flex-1 flex-col justify-end">
          <div
            className={cn('w-full rounded-t-[4px] transition-opacity', index === values.length - 1 ? 'bg-blue' : 'bg-fg-4/60 group-hover:bg-fg-3')}
            style={{ height: `${Math.max(3, (value / max) * 100)}%` }}
          />
          <span className="mt-1 truncate text-center text-[10px] text-fg-3">{labels[index]}</span>
          <span className="pointer-events-none absolute -top-6 left-1/2 z-10 hidden -translate-x-1/2 rounded-md bg-[#0b0b0c] px-1.5 py-0.5 text-[10.5px] whitespace-nowrap text-[#fff] group-hover:block">
            {format(value)}
          </span>
        </div>
      ))}
    </div>
  )
}

/** A horizontal gauge: used share of a limit, black past 80%. */
export function Gauge({ percent, label }: { percent: number; label: ReactNode }) {
  const clamped = Math.max(0, Math.min(100, percent))
  return (
    <div>
      <div className="flex justify-between text-[11.5px] text-fg-3">
        <span>{label}</span>
        <span className="num font-semibold text-fg">{Math.round(percent)}%</span>
      </div>
      <div className="mt-1 h-2 overflow-hidden rounded-full bg-white/8">
        <div className={cn('h-full rounded-full', percent >= 80 ? 'bg-[#0b0b0c] dark:bg-[#fff]' : 'bg-blue')} style={{ width: `${clamped}%` }} />
      </div>
    </div>
  )
}

/** A compact figure with an icon, for record headers and side panels. */
export function Stat({ icon: Icon, label, value, hint, strong }: { icon: LucideIcon; label: string; value: ReactNode; hint?: ReactNode; strong?: boolean }) {
  return (
    <div className={cn('card flex items-start gap-3 p-3.5', strong && 'pane-contrast rounded-2xl!')}>
      <span className={cn('grid size-9 shrink-0 place-items-center rounded-full', strong ? 'glass-tile rounded-xl!' : 'icon-disc')}>
        <Icon size={16} />
      </span>
      <div className="min-w-0">
        <div className={cn('text-[11.5px] font-medium', strong ? 'opacity-70' : 'text-fg-3')}>{label}</div>
        <div className="num truncate text-[18px] font-semibold tracking-[-0.02em]">{value}</div>
        {hint ? <div className={cn('truncate text-[11px]', strong ? 'opacity-70' : 'text-fg-3')}>{hint}</div> : null}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------ scan */
/** Pick a photo or PDF (a supplier bill, a customer's order slip) and hand it
 *  to the assistant with an instruction. Nothing changes until confirmed. */
export function ScanButton({ label, prompt, small }: { label: string; prompt: string; small?: boolean }) {
  const { send, setOpen } = useAssistant()
  const [busy, setBusy] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  return (
    <>
      <input
        ref={input}
        type="file"
        accept="image/*,application/pdf"
        className="hidden"
        onChange={async (event) => {
          const file = event.target.files?.[0]
          event.target.value = ''
          if (!file) return
          setBusy(true)
          try {
            const uploaded = await ai.upload(file)
            if (!window.location.pathname.startsWith('/assistant')) setOpen(true)
            await send(prompt, [uploaded])
          } finally {
            setBusy(false)
          }
        }}
      />
      <button onClick={() => input.current?.click()} disabled={busy} className={cn('btn btn-quiet gap-1.5!', small && 'btn-sm')}>
        {busy ? <Loader2 size={14} className="animate-spin" /> : <ScanLine size={14} />} {label}
      </button>
    </>
  )
}
