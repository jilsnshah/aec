import { motion } from 'motion/react'
import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { useLocation } from 'react-router-dom'
import {
  AlertTriangle,
  BadgePercent,
  Boxes,
  CalendarClock,
  ChevronLeft,
  CircleDollarSign,
  ClipboardList,
  Coins,
  Hash,
  IndianRupee,
  MessageSquareQuote,
  PackageCheck,
  PackageOpen,
  PiggyBank,
  ReceiptText,
  ShoppingCart,
  Tag,
  TrendingUp,
  Truck,
  Users,
  Warehouse,
  type LucideIcon,
} from 'lucide-react'
import { moduleFor } from '@/app/nav'
import { Skeleton } from './core'
import { HeaderArt } from './art'

/** A record workspace: a list on the left, the chosen record on the right.
 *  On a narrow window only one shows at a time, with a way back to the list. */
export function SplitView({ list, children, listWidth = 380, showDetail, onBack }: { list: ReactNode; children: ReactNode; listWidth?: number; showDetail?: boolean; onBack?: () => void }) {
  return (
    <div className="flex h-full min-h-0 gap-4 px-6 pt-1 pb-5 max-md:gap-2 max-md:p-2">
      <section className={cn('pane flex min-h-0 shrink-0 flex-col overflow-hidden max-lg:w-full! max-lg:shrink', showDetail && 'max-lg:hidden')} style={{ width: listWidth }}>
        {list}
      </section>
      <section className={cn('pane flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden', !showDetail && 'max-lg:hidden')}>
        {onBack ? (
          <button onClick={onBack} className="flex h-10 shrink-0 items-center gap-1 border-b border-white/7 px-4 text-[13px] font-medium text-sky lg:hidden">
            <ChevronLeft size={16} /> Back to list
          </button>
        ) : null}
        {children}
      </section>
    </div>
  )
}

/** The list column: a header with title, count and actions, filters, then rows. */
export function ListPane({
  title,
  count,
  actions,
  filters,
  children,
  footer,
}: {
  title: string
  count?: number
  actions?: ReactNode
  filters?: ReactNode
  children: ReactNode
  footer?: ReactNode
}) {
  return (
    <>
      <header className="shrink-0 space-y-3 px-5 pt-5 pb-3">
        <div className="flex items-center gap-2.5">
          <ModuleTile size={34} />
          <h1 className="text-[18px] font-semibold tracking-[-0.02em]">{title}</h1>
          {count !== undefined ? <span className="num rounded-full bg-white/7 px-2 py-px text-[11.5px] font-medium text-fg-2">{count}</span> : null}
          <div className="ml-auto flex items-center gap-1">{actions}</div>
        </div>
        {filters}
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">{children}</div>
      {footer ? <footer className="shrink-0 border-t border-white/7 px-4 py-2 text-[12px] text-fg-3">{footer}</footer> : null}
    </>
  )
}

/** One row in a list pane. The selection highlight glides between rows. */
export function ListRow({ selected, onSelect, group, children, alert }: { selected: boolean; onSelect: () => void; group: string; children: ReactNode; alert?: boolean }) {
  return (
    <button
      onClick={onSelect}
      className={cn('group relative block w-full rounded-[14px] px-3.5 py-2.5 text-left transition-colors', !selected && 'hover:bg-white/[0.04]')}
      aria-current={selected || undefined}
    >
      {selected ? (
        <motion.span
          layoutId={`row-${group}`}
          className="absolute inset-0 rounded-[14px] bg-peri/[0.17] shadow-[inset_0_0_0_1px_color-mix(in_oklab,var(--c-peri)_40%,transparent),0_8px_20px_-14px_var(--c-blue)]"
          transition={{ type: 'spring', stiffness: 520, damping: 42 }}
        />
      ) : null}
      {alert ? <span className="absolute top-3.5 bottom-3.5 left-0.5 w-[3px] rounded-full bg-bad/80" /> : null}
      <span className="relative block">{children}</span>
    </button>
  )
}

export function ListSkeleton({ rows = 8 }: { rows?: number }) {
  return (
    <div className="space-y-1 p-1.5">
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="space-y-2 rounded-[10px] px-3 py-3">
          <Skeleton className="w-2/3" />
          <Skeleton className="h-2.5 w-1/3" />
        </div>
      ))}
    </div>
  )
}

/** The inspector's top: what the record is, its state and what can be done. */
export function InspectorHeader({ eyebrow, title, badges, actions, meta }: { eyebrow?: ReactNode; title: ReactNode; badges?: ReactNode; actions?: ReactNode; meta?: ReactNode }) {
  // A name too long to fit beside the actions even at the smallest size takes
  // the whole row, and the actions move below it.
  const [crowded, setCrowded] = useState(false)
  const key = typeof title === 'string' ? title : String((title as { key?: string } | null)?.key ?? '')
  useLayoutEffect(() => setCrowded(false), [key])
  return (
    <header className="relative shrink-0 overflow-hidden border-b border-white/7 px-7 pt-6 pb-5 max-md:px-4">
      <HeaderArt seed={String(title).length % 7} />
            <div className="relative flex flex-wrap items-start gap-4 max-md:gap-3">
        <span className="max-md:hidden">
          <ModuleTile size={52} />
        </span>
        <div className={cn('min-w-[240px] flex-1', crowded && 'basis-[calc(100%-68px)] max-md:basis-full')}>
          {eyebrow ? <div className="eyebrow mb-1.5">{eyebrow}</div> : null}
          <div className="flex min-w-0 items-center gap-2.5">
            <FitTitle onCrowded={() => setCrowded(true)}>{title}</FitTitle>
            {badges ? <div className="flex shrink-0 items-center gap-2">{badges}</div> : null}
          </div>
          {meta ? <div className="mt-1 text-[13px] text-fg-3">{meta}</div> : null}
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
    </header>
  )
}

/** An icon for a headline figure, chosen from its label. */
const FIGURE_ICONS: [RegExp, LucideIcon][] = [
  [/short/i, AlertTriangle],
  [/profit/i, TrendingUp],
  [/margin/i, BadgePercent],
  [/discount/i, BadgePercent],
  [/avg cost|cost/i, Tag],
  [/stock value|warehouse value/i, PiggyBank],
  [/warehouse/i, Warehouse],
  [/ready|free stock/i, PackageCheck],
  [/on order|to receive|arriving|still to come|due|received/i, PackageOpen],
  [/deliver|sent/i, Truck],
  [/value|total|spend|mrp|amount/i, IndianRupee],
  [/stock|units|bought/i, Boxes],
  [/ordered|orders/i, ShoppingCart],
  [/purchase/i, ClipboardList],
  [/enquir/i, MessageSquareQuote],
  [/customer/i, Users],
  [/invoice|receipt/i, ReceiptText],
  [/paid|spent/i, Coins],
  [/days|date|age/i, CalendarClock],
  [/price/i, CircleDollarSign],
]
export const figureIcon = (label: string): LucideIcon => FIGURE_ICONS.find(([pattern]) => pattern.test(label))?.[1] ?? Hash

/** The current module's icon in a bright tile. */
export function ModuleTile({ size = 40 }: { size?: number }) {
  const { pathname } = useLocation()
  const Icon = moduleFor(pathname).icon
  return (
    <span className="icon-tile shrink-0" style={{ width: size, height: size, borderRadius: size * 0.34 }}>
      <Icon size={size * 0.46} strokeWidth={2} />
    </span>
  )
}

/** A strip of headline figures across the top of an inspector. */
export function FigureStrip({ items }: { items: { label: string; value: ReactNode; hint?: ReactNode; tone?: 'sky' | 'bad' | 'ok' | 'steel' }[] }) {
  return (
    <div className="grid shrink-0 grid-cols-[repeat(auto-fit,minmax(132px,1fr))] border-b border-white/7">
      {items.map((item) => (
        <div key={item.label} className="-ml-px border-l border-white/6 px-6 py-4 first:border-l-0">
          <div className="flex items-center gap-2">
            <FigureIcon label={item.label} tone={item.tone} />
            <span className="eyebrow truncate">{item.label}</span>
          </div>
          <div
            className={cn(
              'num mt-1 text-[24px] font-light tracking-[-0.03em] whitespace-nowrap',
              item.tone === 'sky' && 'text-sky',
              item.tone === 'bad' && 'text-bad',
              item.tone === 'ok' && 'text-ok',
              item.tone === 'steel' && 'text-steel',
            )}
          >
            {item.value}
          </div>
          {item.hint ? <div className="mt-0.5 truncate text-[11.5px] text-fg-3">{item.hint}</div> : null}
        </div>
      ))}
    </div>
  )
}

function FigureIcon({ label, tone }: { label: string; tone?: 'sky' | 'bad' | 'ok' | 'steel' }) {
  const Icon = figureIcon(label)
  return (
    <span className={cn('grid size-6 shrink-0 place-items-center rounded-full', tone === 'bad' ? 'bg-bad/12 text-bad' : tone === 'ok' ? 'bg-ok/12 text-ok' : 'icon-disc')}>
      <Icon size={12.5} strokeWidth={2} />
    </span>
  )
}

/** A titled block inside an inspector tab. */
export function Section({ title, hint, actions, children, className }: { title?: ReactNode; hint?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cn('px-7 py-5', className)}>
      {title ? (
        <div className="mb-3 flex items-end gap-3">
          <div className="min-w-0 flex-1">
            <h3 className="text-[13.5px] font-semibold">{title}</h3>
            {hint ? <p className="mt-0.5 text-[12px] text-fg-3">{hint}</p> : null}
          </div>
          {actions}
        </div>
      ) : null}
      {children}
    </section>
  )
}

export function useSelection(initial?: string) {
  return useState<string | undefined>(initial)
}


/** A record's name on one line: the font shrinks (24 → 14 px) until it fits
 *  the space it has, re-measured when that space changes; only then "…". */
export function FitTitle({ children, max = 24, min = 14, onCrowded }: { children: ReactNode; max?: number; min?: number; onCrowded?: () => void }) {
  const ref = useRef<HTMLHeadingElement>(null)
  const [size, setSize] = useState(max)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const fit = () => {
      el.classList.add('measuring')
      let next = max
      el.style.fontSize = `${next}px`
      while (el.scrollWidth > el.clientWidth + 1 && next > min) {
        next -= 1
        el.style.fontSize = `${next}px`
      }
      const tight = el.scrollWidth > el.clientWidth + 1
      el.classList.remove('measuring')
      setSize(next)
      if (tight) onCrowded?.()
    }
    fit()
    const observer = new ResizeObserver(fit)
    observer.observe(el.parentElement ?? el)
    return () => observer.disconnect()
  }, [children, max, min]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <h2
      ref={ref}
      className="min-w-0 overflow-hidden font-semibold tracking-[-0.025em] text-ellipsis whitespace-nowrap [&>span]:min-w-0 [&_span]:whitespace-nowrap [&.measuring_*]:!overflow-visible"
      style={{ fontSize: size, lineHeight: 1.25 }}
      title={typeof children === 'string' ? children : undefined}
      data-selectable
    >
      {children}
    </h2>
  )
}
