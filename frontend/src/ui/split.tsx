import { motion } from 'motion/react'
import { useState, type ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { ChevronLeft } from 'lucide-react'
import { Skeleton } from './core'

/** A record workspace: a list on the left, the chosen record on the right.
 *  On a narrow window only one shows at a time, with a way back to the list. */
export function SplitView({ list, children, listWidth = 380, showDetail, onBack }: { list: ReactNode; children: ReactNode; listWidth?: number; showDetail?: boolean; onBack?: () => void }) {
  return (
    <div className="flex h-full min-h-0 gap-3 p-3 pl-0 max-md:p-2">
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
      <header className="shrink-0 space-y-3 border-b border-white/7 px-4 pt-4 pb-3">
        <div className="flex items-center gap-2">
          <h1 className="text-[16px] font-semibold tracking-[-0.015em]">{title}</h1>
          {count !== undefined ? <span className="num rounded-full bg-white/7 px-2 py-px text-[11.5px] font-medium text-fg-2">{count}</span> : null}
          <div className="ml-auto flex items-center gap-1">{actions}</div>
        </div>
        {filters}
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto p-1.5">{children}</div>
      {footer ? <footer className="shrink-0 border-t border-white/7 px-4 py-2 text-[12px] text-fg-3">{footer}</footer> : null}
    </>
  )
}

/** One row in a list pane. The selection highlight glides between rows. */
export function ListRow({ selected, onSelect, group, children, alert }: { selected: boolean; onSelect: () => void; group: string; children: ReactNode; alert?: boolean }) {
  return (
    <button
      onClick={onSelect}
      className={cn('group relative block w-full rounded-[10px] px-3 py-2.5 text-left transition-colors', !selected && 'hover:bg-white/[0.035]')}
      aria-current={selected || undefined}
    >
      {selected ? (
        <motion.span
          layoutId={`row-${group}`}
          className="absolute inset-0 rounded-[10px] bg-sky/[0.09] ring-1 ring-sky/25 ring-inset"
          transition={{ type: 'spring', stiffness: 520, damping: 42 }}
        />
      ) : null}
      {alert ? <span className="absolute top-3 bottom-3 left-0 w-[2px] rounded-full bg-bad/80" /> : null}
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
  return (
    <header className="relative shrink-0 overflow-hidden border-b border-white/7 px-6 pt-5 pb-4 max-md:px-4">
      <div className="pointer-events-none absolute -top-24 right-[-10%] h-48 w-[60%] rounded-full bg-sky/[0.07] blur-3xl" />
      <div className="relative flex items-start gap-4 max-md:flex-col max-md:gap-3">
        <div className="min-w-0 flex-1">
          {eyebrow ? <div className="eyebrow mb-1.5">{eyebrow}</div> : null}
          <div className="flex flex-wrap items-center gap-2.5">
            <h2 className="text-[21px] font-semibold tracking-[-0.022em]" data-selectable>
              {title}
            </h2>
            {badges}
          </div>
          {meta ? <div className="mt-1 text-[13px] text-fg-3">{meta}</div> : null}
        </div>
        {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
      </div>
    </header>
  )
}

/** A strip of headline figures across the top of an inspector. */
export function FigureStrip({ items }: { items: { label: string; value: ReactNode; hint?: ReactNode; tone?: 'sky' | 'bad' | 'ok' | 'steel' }[] }) {
  return (
    <div className="grid shrink-0 grid-cols-[repeat(auto-fit,minmax(132px,1fr))] border-b border-white/7">
      {items.map((item) => (
        <div key={item.label} className="-ml-px border-l border-white/6 px-6 py-3.5 first:border-l-0">
          <div className="eyebrow">{item.label}</div>
          <div
            className={cn(
              'num mt-1 text-[20px] font-semibold tracking-[-0.02em] whitespace-nowrap',
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

/** A titled block inside an inspector tab. */
export function Section({ title, hint, actions, children, className }: { title?: ReactNode; hint?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cn('px-6 py-5', className)}>
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
