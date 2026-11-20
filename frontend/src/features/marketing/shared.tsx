import { useMemo, useState, type ReactNode } from 'react'
import { Instagram, MessageCircle, type LucideIcon } from 'lucide-react'
import { STATUS_LABEL, type CampaignStatus, type Channel, type Funnel, type SeriesPoint } from '@/api/marketing'
import { cn } from '@/lib/cn'
import { fmtCompactMoney, fmtShortDate } from '@/lib/format'
import { Badge } from '@/ui/core'

export const CHANNEL: Record<Channel, { label: string; icon: LucideIcon }> = {
  instagram: { label: 'Instagram', icon: Instagram },
  whatsapp: { label: 'WhatsApp', icon: MessageCircle },
}

export function ChannelChips({ channels, className }: { channels: Channel[]; className?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-1', className)}>
      {channels.map((c) => {
        const Icon = CHANNEL[c].icon
        return (
          <span key={c} title={CHANNEL[c].label} className="grid size-5 place-items-center rounded-full bg-white/7">
            <Icon size={11} aria-label={CHANNEL[c].label} />
          </span>
        )
      })}
    </span>
  )
}

export function StatusBadge({ status }: { status: CampaignStatus }) {
  const s = STATUS_LABEL[status]
  return (
    <Badge tone={s.tone} dot={status === 'running' || status === 'review'}>
      {s.label}
    </Badge>
  )
}

export const pct = (part: number, whole: number) => (whole ? `${Math.round((part / whole) * 100)}%` : '—')

/** Kpi tile: a label, a big number and a quiet hint. */
export function Kpi({ icon: Icon, label, value, hint, tone }: { icon: LucideIcon; label: string; value: ReactNode; hint?: ReactNode; tone?: 'ok' | 'warn' | 'bad' }) {
  return (
    <div className="card flex min-w-0 flex-col gap-1 p-4">
      <div className="flex items-center gap-2 text-[12px] font-medium text-fg-3">
        <span className="icon-disc grid size-7 place-items-center rounded-full bg-white/7">
          <Icon size={13} />
        </span>
        {label}
      </div>
      <div className={cn('num text-[24px] leading-tight font-semibold tracking-[-0.02em]', tone === 'bad' && 'text-bad', tone === 'warn' && 'text-warn', tone === 'ok' && 'text-ok')}>
        {value}
      </div>
      {hint ? <div className="truncate text-[11.5px] text-fg-3">{hint}</div> : null}
    </div>
  )
}

/** The message funnel as stepped bars: each step's share of the one before. */
export function FunnelBars({ funnel, extra }: { funnel: Funnel; extra?: { label: string; value: number }[] }) {
  const steps = [
    { label: 'Sent', value: funnel.sent },
    { label: 'Delivered', value: funnel.delivered },
    { label: 'Read', value: funnel.read },
    { label: 'Replied', value: funnel.replied },
    ...(extra ?? []),
  ]
  const top = Math.max(1, steps[0].value)
  return (
    <div className="space-y-2">
      {steps.map((step, i) => (
        <div key={step.label} className="grid grid-cols-[84px_1fr_92px] items-center gap-3 text-[12.5px]">
          <span className="text-fg-3">{step.label}</span>
          <div className="h-2.5 overflow-hidden rounded-full bg-white/7" role="img" aria-label={`${step.label}: ${step.value}`}>
            <div className="h-full rounded-full bg-sky" style={{ width: `${Math.max(step.value ? 2 : 0, (step.value / top) * 100)}%`, opacity: 1 - i * 0.12 }} />
          </div>
          <span className="num text-right font-semibold">
            {step.value.toLocaleString('en-IN')}
            {i > 0 ? <span className="ml-1.5 text-[11px] font-normal text-fg-3">{pct(step.value, steps[i - 1].value)}</span> : null}
          </span>
        </div>
      ))}
    </div>
  )
}

/** Daily bars with a hover readout. One measure per chart: no second axis. */
export function DailyBars({ points, measure, label, money, className }: { points: SeriesPoint[]; measure: keyof Omit<SeriesPoint, 'day'>; label: string; money?: boolean; className?: string }) {
  const [hover, setHover] = useState<number | null>(null)
  const values = useMemo(() => points.map((p) => Number(p[measure]) || 0), [points, measure])
  const max = Math.max(1, ...values)
  const total = values.reduce((a, b) => a + b, 0)
  const fmt = (v: number) => (money ? fmtCompactMoney(v) : v.toLocaleString('en-IN'))
  const shown = hover === null ? null : points[hover]
  return (
    <div className={className}>
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <span className="text-[12.5px] font-semibold">{label}</span>
        <span className="num text-[12px] text-fg-3">{shown ? `${fmtShortDate(shown.day)} · ${fmt(values[hover!])}` : `${fmt(total)} in ${points.length} days`}</span>
      </div>
      <div className="flex h-24 items-end gap-[2px]" onMouseLeave={() => setHover(null)} role="img" aria-label={`${label}: ${fmt(total)} over ${points.length} days`}>
        {values.map((v, i) => (
          <div key={points[i].day} className="flex h-full flex-1 cursor-default items-end" onMouseEnter={() => setHover(i)}>
            <div
              className={cn('w-full rounded-t-[4px] transition-colors', hover === i ? 'bg-sky' : 'bg-sky/55')}
              style={{ height: `${v ? Math.max(4, (v / max) * 100) : 0}%` }}
            />
          </div>
        ))}
      </div>
      <div className="mt-1 flex justify-between text-[10.5px] text-fg-4">
        <span>{points.length ? fmtShortDate(points[0].day) : ''}</span>
        <span>{points.length ? fmtShortDate(points[points.length - 1].day) : ''}</span>
      </div>
    </div>
  )
}

/** A WhatsApp-style bubble showing exactly what the customer receives. */
export function PhonePreview({ text, image, footer, header }: { text: string; image?: string | null; footer?: string | null; header?: string | null }) {
  return (
    <div className="rounded-[22px] bg-[#e7ddd3] p-3 dark:bg-[#0b141a]">
      <div className="max-w-[300px] rounded-[12px] rounded-tl-[4px] bg-[#fff] p-2 text-[13px] leading-snug text-[#111b21] shadow-sm dark:bg-[#202c33] dark:text-[#e9edef]">
        {header === 'IMAGE' ? (
          image ? <img src={image} alt="" className="mb-2 aspect-[4/5] w-full rounded-[8px] object-cover" /> : <div className="mb-2 grid aspect-[4/5] place-items-center rounded-[8px] bg-black/10 text-[11px]">Image needed</div>
        ) : null}
        <p className="whitespace-pre-wrap">{text || 'Choose a template to see the message.'}</p>
        {footer ? <p className="mt-1 text-[11px] opacity-60">{footer}</p> : null}
        <div className="mt-2 border-t border-black/10 pt-1.5 text-center text-[12.5px] font-medium text-[#027eb5] dark:border-white/10 dark:text-[#53bdeb]">Stop promotions</div>
      </div>
    </div>
  )
}

/** An Instagram-style post preview. */
export function PostPreview({ image, caption, hashtags, username }: { image?: string | null; caption?: string | null; hashtags?: string[]; username?: string | null }) {
  return (
    <div className="overflow-hidden rounded-[14px] border border-white/8 bg-[#fff] text-[#111] dark:bg-[#000] dark:text-[#f5f5f5]">
      <div className="flex items-center gap-2 px-3 py-2 text-[12.5px] font-semibold">
        <span className="size-6 rounded-full bg-gradient-to-tr from-amber-400 via-pink-500 to-purple-600 p-[2px]">
          <span className="block size-full rounded-full bg-[#fff] dark:bg-[#000]" />
        </span>
        {username || 'your_business'}
      </div>
      {image ? <img src={image} alt="" className="aspect-[4/5] w-full object-cover" /> : <div className="grid aspect-[4/5] place-items-center bg-black/5 text-[12px] opacity-60">Add an image</div>}
      <div className="space-y-1 px-3 py-2.5 text-[12.5px] leading-snug">
        <p className="whitespace-pre-wrap">
          <span className="mr-1 font-semibold">{username || 'your_business'}</span>
          {caption || <span className="opacity-50">Caption…</span>}
        </p>
        {hashtags?.length ? <p className="text-[#00376b] dark:text-[#e0f1ff]">{hashtags.join(' ')}</p> : null}
      </div>
    </div>
  )
}

export function Panel({ title, icon: Icon, actions, children, className }: { title: ReactNode; icon?: LucideIcon; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cn('card p-4', className)}>
      <div className="mb-3 flex items-center gap-2">
        {Icon ? <Icon size={15} className="text-fg-3" /> : null}
        <h2 className="flex-1 text-[14px] font-semibold">{title}</h2>
        {actions}
      </div>
      {children}
    </section>
  )
}

/** ISO string for a <input type="datetime-local"> value (local time). */
export const toLocalInput = (iso: string | null | undefined) => {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (v: number) => String(v).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}
export const fromLocalInput = (value: string) => (value ? new Date(value).toISOString() : null)

/** A scrolling page body below the marketing header. */
export function Page({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('h-full overflow-y-auto px-6 pb-5 max-md:px-2', className)}>{children}</div>
}
