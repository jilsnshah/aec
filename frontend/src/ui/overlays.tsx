import * as Dialog from '@radix-ui/react-dialog'
import * as Dropdown from '@radix-ui/react-dropdown-menu'
import * as RadixTabs from '@radix-ui/react-tabs'
import { motion } from 'motion/react'
import { useState, type ReactNode } from 'react'
import { AlertTriangle, X } from 'lucide-react'
import { cn } from '@/lib/cn'
import { Button } from './core'

/* ---------------------------------------------------------------- sheet */
/** A sheet drops from under the title bar, like a macOS window sheet. It holds
 *  every create and edit form. */
export function Sheet({
  open,
  onClose,
  title,
  subtitle,
  width = 760,
  footer,
  aside,
  children,
}: {
  open: boolean
  onClose: () => void
  title: ReactNode
  subtitle?: ReactNode
  width?: number
  footer?: ReactNode
  /** A summary column on the right of the form. */
  aside?: ReactNode
  children: ReactNode
}) {
  return (
    <Dialog.Root open={open} onOpenChange={(next) => (next ? null : onClose())}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[100] bg-[var(--scrim)] backdrop-blur-[3px] data-[state=open]:animate-fade" />
        <Dialog.Content
          aria-describedby={undefined}
          className="fixed top-[52px] left-1/2 z-[101] flex max-h-[calc(100vh-72px)] w-[calc(100vw-32px)] -translate-x-1/2 flex-col overflow-hidden rounded-b-[24px] rounded-t-lg bg-ink-800 shadow-float outline-none data-[state=open]:animate-[sheet_380ms_var(--ease-spring)_both]"
          style={{ maxWidth: width }}
        >
                    <header className="flex items-start gap-3 border-b border-white/7 px-6 pt-5 pb-4">
            <div className="min-w-0 flex-1">
              <Dialog.Title className="text-[17px] font-semibold tracking-[-0.015em]">{title}</Dialog.Title>
              {subtitle ? <p className="mt-0.5 text-[13px] text-fg-3">{subtitle}</p> : null}
            </div>
            <Dialog.Close asChild>
              <Button kind="ghost" small iconOnly aria-label="Close">
                <X size={15} />
              </Button>
            </Dialog.Close>
          </header>
          <div className="flex min-h-0 flex-1">
            <div className="min-w-0 flex-1 overflow-x-auto overflow-y-auto px-6 py-5 max-md:px-4">{children}</div>
            {aside ? <aside className="w-[280px] shrink-0 overflow-y-auto border-l border-white/7 bg-ink-900/60 px-5 py-5 max-md:hidden">{aside}</aside> : null}
          </div>
          {footer ? <footer className="flex items-center justify-end gap-2 border-t border-white/7 bg-ink-900/60 px-6 py-3.5">{footer}</footer> : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

/* ---------------------------------------------------------------- confirm */
export function useConfirm() {
  const [state, setState] = useState<null | {
    title: string
    body?: ReactNode
    confirm: string
    danger?: boolean
    withReason?: boolean
    resolve: (value: { ok: boolean; reason: string }) => void
  }>(null)
  const [reason, setReason] = useState('')

  function ask(options: { title: string; body?: ReactNode; confirm: string; danger?: boolean; withReason?: boolean }) {
    setReason('')
    return new Promise<{ ok: boolean; reason: string }>((resolve) => setState({ ...options, resolve }))
  }
  function close(ok: boolean) {
    state?.resolve({ ok, reason })
    setState(null)
  }

  const element = (
    <Dialog.Root open={state !== null} onOpenChange={(next) => (next ? null : close(false))}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[110] bg-[var(--scrim)] backdrop-blur-[3px] data-[state=open]:animate-fade" />
        <Dialog.Content
          aria-describedby={undefined}
          className="fixed top-[22vh] left-1/2 z-[111] w-[calc(100vw-32px)] max-w-[420px] -translate-x-1/2 rounded-[22px] bg-ink-800 p-5 shadow-float outline-none data-[state=open]:animate-[pop_260ms_var(--ease-spring)_both]"
        >
          <div className="flex gap-3.5">
            <div className={cn('grid size-10 shrink-0 place-items-center rounded-xl', state?.danger ? 'bg-bad/12 text-bad' : 'bg-sky/12 text-sky')}>
              <AlertTriangle size={18} />
            </div>
            <div className="min-w-0 flex-1">
              <Dialog.Title className="text-[15px] font-semibold">{state?.title}</Dialog.Title>
              {state?.body ? <div className="mt-1 text-[13px] text-fg-2">{state.body}</div> : null}
              {state?.withReason ? (
                <input className="field mt-3" placeholder="Reason (optional)" value={reason} onChange={(event) => setReason(event.target.value)} autoFocus />
              ) : null}
            </div>
          </div>
          <div className="mt-5 flex justify-end gap-2">
            <Button onClick={() => close(false)}>Keep</Button>
            <Button kind={state?.danger ? 'danger' : 'primary'} onClick={() => close(true)} autoFocus={!state?.withReason}>
              {state?.confirm}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
  return { ask, element }
}

/* ---------------------------------------------------------------- menu */
export interface MenuItem {
  label: string
  icon?: ReactNode
  onSelect: () => void
  danger?: boolean
  disabled?: boolean
  separator?: boolean
  hint?: string
}
export function Menu({ trigger, items, align = 'end', side = 'bottom' }: { trigger: ReactNode; items: MenuItem[]; align?: 'start' | 'end'; side?: 'top' | 'bottom' | 'right' }) {
  return (
    <Dropdown.Root modal={false}>
      <Dropdown.Trigger asChild>{trigger}</Dropdown.Trigger>
      <Dropdown.Portal>
        <Dropdown.Content
          align={align}
          side={side}
          sideOffset={6}
          collisionPadding={10}
          className="z-[150] min-w-[210px] rounded-2xl bg-ink-750/95 p-1.5 shadow-pop backdrop-blur-xl data-[state=open]:animate-[pop_180ms_var(--ease-out-quint)_both]"
        >
          {items.map((item) => (
            <div key={item.label}>
              {item.separator ? <Dropdown.Separator className="mx-2 my-1.5 h-px bg-white/8" /> : null}
              <Dropdown.Item
                disabled={item.disabled}
                onSelect={item.onSelect}
                className={cn(
                  'flex h-8 items-center gap-2.5 rounded-lg px-2.5 text-[13px] outline-none data-[disabled]:opacity-40 data-[highlighted]:bg-white/8',
                  item.danger ? 'text-bad' : 'text-fg',
                )}
              >
                <span className={cn('grid w-4 place-items-center', item.danger ? 'text-bad' : 'text-fg-3')}>{item.icon}</span>
                <span className="flex-1">{item.label}</span>
                {item.hint ? <span className="text-[11.5px] text-fg-4">{item.hint}</span> : null}
              </Dropdown.Item>
            </div>
          ))}
        </Dropdown.Content>
      </Dropdown.Portal>
    </Dropdown.Root>
  )
}

/* ---------------------------------------------------------------- tabs */
/** Tabs with an underline that glides to the chosen tab. */
export function Tabs({
  value,
  onChange,
  tabs,
  children,
  className,
}: {
  value: string
  onChange: (value: string) => void
  tabs: { value: string; label: ReactNode; count?: number }[]
  children: ReactNode
  className?: string
}) {
  const [group] = useState(() => Math.random().toString(36).slice(2))
  return (
    <RadixTabs.Root value={value} onValueChange={onChange} className={cn('flex min-h-0 flex-col', className)}>
      <RadixTabs.List className="flex shrink-0 gap-1 border-b border-white/7 px-4">
        {tabs.map((tab) => (
          <RadixTabs.Trigger
            key={tab.value}
            value={tab.value}
            className="relative flex h-10 items-center gap-1.5 px-2.5 text-[13px] font-medium text-fg-3 transition-colors outline-none hover:text-fg data-[state=active]:text-fg"
          >
            {tab.label}
            {tab.count !== undefined ? <span className="num rounded-full bg-white/7 px-1.5 text-[11px] text-fg-2">{tab.count}</span> : null}
            {value === tab.value ? (
              <motion.span layoutId={`tab-${group}`} className="absolute inset-x-2 -bottom-px h-[2px] rounded-full bg-contrast" transition={{ type: 'spring', stiffness: 500, damping: 40 }} />
            ) : null}
          </RadixTabs.Trigger>
        ))}
      </RadixTabs.List>
      {children}
    </RadixTabs.Root>
  )
}
export const TabPanel = ({ value, children, className }: { value: string; children: ReactNode; className?: string }) => (
  <RadixTabs.Content value={value} className={cn('min-h-0 flex-1 overflow-x-auto overflow-y-auto outline-none animate-fade', className)}>
    {children}
  </RadixTabs.Content>
)

/* ---------------------------------------------------------------- segmented */
/** A compact segmented filter with a sliding thumb. */
export function Segmented<V extends string>({ value, onChange, options, className }: { value: V; onChange: (value: V) => void; options: { value: V; label: ReactNode; count?: number }[]; className?: string }) {
  const [group] = useState(() => Math.random().toString(36).slice(2))
  return (
    <div className={cn('flex rounded-full bg-ink-900 p-[3px] ring-1 ring-white/7 ring-inset', className)} role="radiogroup">
      {options.map((option) => (
        <button
          key={option.value}
          role="radio"
          aria-checked={value === option.value}
          onClick={() => onChange(option.value)}
          className={cn('relative flex h-[26px] flex-1 items-center justify-center gap-1.5 rounded-full px-3 text-[12px] font-semibold whitespace-nowrap transition-colors', value === option.value ? 'text-on-contrast' : 'text-fg-3 hover:text-fg')}
        >
          {value === option.value ? (
            <motion.span layoutId={`seg-${group}`} className="absolute inset-0 rounded-full bg-contrast shadow-[0_4px_10px_-4px_rgb(0_0_0/0.4)]" transition={{ type: 'spring', stiffness: 500, damping: 38 }} />
          ) : null}
          <span className="relative">{option.label}</span>
          {option.count !== undefined ? <span className={cn('num relative text-[10.5px]', value === option.value ? 'text-on-contrast/70' : 'text-fg-4')}>{option.count}</span> : null}
        </button>
      ))}
    </div>
  )
}
