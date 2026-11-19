import * as RadixSwitch from '@radix-ui/react-switch'
import * as RadixTooltip from '@radix-ui/react-tooltip'
import { animate, motion, useMotionValue, useTransform } from 'motion/react'
import { forwardRef, useEffect, useId, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { Loader2, Search, X } from 'lucide-react'

/* ---------------------------------------------------------------- buttons */
type ButtonKind = 'default' | 'primary' | 'ghost' | 'quiet' | 'danger'
export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  kind?: ButtonKind
  small?: boolean
  icon?: ReactNode
  busy?: boolean
  iconOnly?: boolean
}
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { kind = 'default', small, icon, busy, iconOnly, className, children, disabled, type = 'button', ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || busy}
      className={cn('btn', kind !== 'default' && `btn-${kind}`, small && 'btn-sm', iconOnly && 'btn-icon', className)}
      {...rest}
    >
      {busy ? <Loader2 size={small ? 13 : 15} className="animate-spin" /> : icon}
      {children}
    </button>
  )
})

/* ---------------------------------------------------------------- tooltip */
export function Tip({ label, children, side = 'top' }: { label: ReactNode; children: ReactNode; side?: 'top' | 'right' | 'bottom' | 'left' }) {
  return (
    <RadixTooltip.Root delayDuration={350}>
      <RadixTooltip.Trigger asChild>{children}</RadixTooltip.Trigger>
      <RadixTooltip.Portal>
        <RadixTooltip.Content
          side={side}
          sideOffset={8}
          className="z-[200] rounded-lg bg-contrast px-2.5 py-1.5 text-[12px] font-medium text-on-contrast animate-fade"
        >
          {label}
        </RadixTooltip.Content>
      </RadixTooltip.Portal>
    </RadixTooltip.Root>
  )
}

/* ---------------------------------------------------------------- fields */
export function Field({
  label,
  hint,
  error,
  optional,
  className,
  children,
}: {
  label: ReactNode
  hint?: ReactNode
  error?: string | null
  optional?: boolean
  className?: string
  children: (props: { id: string; 'aria-invalid'?: boolean }) => ReactNode
}) {
  const id = useId()
  return (
    <div className={className}>
      <label htmlFor={id} className="label">
        {label}
        {optional ? <span className="ml-1.5 font-normal text-fg-4">Optional</span> : null}
      </label>
      {children({ id, 'aria-invalid': error ? true : undefined })}
      {error ? <p className="mt-1.5 text-[12px] font-medium text-bad">{error}</p> : hint ? <p className="mt-1.5 text-[12px] text-fg-3">{hint}</p> : null}
    </div>
  )
}

export function SearchBox({ value, onChange, placeholder = 'Search', autoFocus }: { value: string; onChange: (value: string) => void; placeholder?: string; autoFocus?: boolean }) {
  return (
    <div className="relative">
      <Search size={14} className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-fg-3" />
      <input
        className="field field-sm pr-7 pl-8"
        value={value}
        placeholder={placeholder}
        autoFocus={autoFocus}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Escape' && value) {
            event.stopPropagation()
            onChange('')
          }
        }}
      />
      {value ? (
        <button className="absolute top-1/2 right-1.5 grid size-5 -translate-y-1/2 place-items-center rounded-full text-fg-3 hover:bg-white/10 hover:text-fg" onClick={() => onChange('')} aria-label="Clear search">
          <X size={12} />
        </button>
      ) : null}
    </div>
  )
}

export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (value: boolean) => void; label: string }) {
  return (
    <RadixSwitch.Root
      checked={checked}
      onCheckedChange={onChange}
      aria-label={label}
      className="relative h-[22px] w-[38px] shrink-0 rounded-full bg-white/15 transition-colors data-[state=checked]:bg-blue"
    >
      <RadixSwitch.Thumb className="block size-[18px] translate-x-[2px] rounded-full bg-[#fff] shadow-[0_1px_3px_rgb(0_0_0/0.3)] transition-transform duration-200 data-[state=checked]:translate-x-[18px]" />
    </RadixSwitch.Root>
  )
}

/* ---------------------------------------------------------------- badges */
export type Tone = 'sky' | 'steel' | 'ok' | 'warn' | 'bad' | 'muted'
const TONE: Record<Tone, string> = {
  sky: 'bg-peri/25 text-sky ring-transparent',
  steel: 'bg-steel/14 text-steel ring-transparent',
  ok: 'bg-ok/15 text-ok ring-transparent',
  warn: 'bg-warn/15 text-warn ring-transparent',
  bad: 'bg-bad/13 text-bad ring-transparent',
  muted: 'bg-white/7 text-fg-2 ring-transparent',
}
export function Badge({ tone = 'muted', dot, children, title }: { tone?: Tone; dot?: boolean; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={cn('inline-flex h-[22px] shrink-0 items-center gap-1.5 rounded-full px-2.5 text-[11.5px] font-semibold whitespace-nowrap ring-1 ring-inset', TONE[tone])}>
      {dot ? <span className="size-1.5 rounded-full bg-current" /> : null}
      {children}
    </span>
  )
}

/* ---------------------------------------------------------------- numbers */
/** A number that counts up to its value when it first appears or changes. */
export function CountUp({ value, format }: { value: number; format: (value: number) => string }) {
  const motionValue = useMotionValue(0)
  const text = useTransform(motionValue, (latest) => format(latest))
  useEffect(() => {
    const controls = animate(motionValue, value, { duration: 0.9, ease: [0.22, 1, 0.36, 1] })
    return () => controls.stop()
  }, [value, motionValue])
  return <motion.span className="num">{text}</motion.span>
}

export interface MeterPart {
  value: number
  color: string
  label: string
}
/** A stacked bar: how a quantity splits between states. */
export function Meter({ parts, total, className }: { parts: MeterPart[]; total?: number; className?: string }) {
  const sum = total ?? parts.reduce((acc, part) => acc + part.value, 0)
  return (
    <div className={cn('flex h-1.5 w-full gap-[2px] overflow-hidden rounded-full bg-white/7', className)} role="img" aria-label={parts.map((part) => `${part.label} ${part.value}`).join(', ')}>
      {sum > 0
        ? parts
            .filter((part) => part.value > 0)
            .map((part, index) => (
              <motion.span
                key={part.label}
                className="h-full first:rounded-l-full last:rounded-r-full"
                style={{ background: part.color }}
                initial={{ width: 0 }}
                animate={{ width: `${(part.value / sum) * 100}%` }}
                transition={{ duration: 0.7, delay: index * 0.06, ease: [0.22, 1, 0.36, 1] }}
              />
            ))
        : null}
    </div>
  )
}

/* ---------------------------------------------------------------- placeholders */
export function Empty({ icon, title, body, action, className }: { icon?: ReactNode; title: string; body?: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div className={cn('flex flex-col items-center justify-center px-6 py-12 text-center animate-fade', className)}>
      {icon ? <div className="mb-4 grid size-12 place-items-center rounded-full bg-peri/20 text-sky">{icon}</div> : null}
      <div className="text-[14.5px] font-semibold">{title}</div>
      {body ? <p className="mt-1 max-w-[42ch] text-[13px] text-fg-3">{body}</p> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return <span className={cn('skeleton block h-3', className)} />
}

export function Spinner({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-12 text-[13px] text-fg-3">
      <Loader2 size={16} className="animate-spin" />
      {label}
    </div>
  )
}

export function Notice({ tone = 'sky', children, icon }: { tone?: 'sky' | 'warn' | 'bad' | 'ok'; children: ReactNode; icon?: ReactNode }) {
  const tones = {
    sky: 'bg-sky/8 ring-sky/18 text-fg',
    warn: 'bg-warn/8 ring-warn/20 text-fg',
    bad: 'bg-bad/8 ring-bad/22 text-fg',
    ok: 'bg-ok/8 ring-ok/20 text-fg',
  }
  return (
    <div className={cn('flex items-start gap-2.5 rounded-lg px-3 py-2.5 text-[13px] whitespace-pre-line ring-1 ring-inset animate-fade', tones[tone])}>
      {icon ? <span className="mt-px shrink-0 opacity-90">{icon}</span> : null}
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  )
}

export function Avatar({ name, size = 30 }: { name: string; size?: number }) {
  const letters = name
    .replace(/^demo\s+/i, '')
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join('')
  return (
    <span
      className="grid shrink-0 place-items-center rounded-full bg-peri/30 font-semibold text-sky"
      style={{ width: size, height: size, fontSize: size * 0.36 }}
      aria-hidden="true"
    >
      {letters || '?'}
    </span>
  )
}

/** A row of label / value pairs. */
export function Facts({ items, className }: { items: { label: string; value: ReactNode; strong?: boolean }[]; className?: string }) {
  return (
    <dl className={cn('divide-y divide-white/6', className)}>
      {items.map((item) => (
        <div key={item.label} className={cn('flex items-baseline justify-between gap-4 py-2.5', item.strong && 'font-semibold')}>
          <dt className={cn('text-[13px]', item.strong ? 'text-fg' : 'text-fg-3')}>{item.label}</dt>
          <dd className="num text-right text-[13px]">{item.value}</dd>
        </div>
      ))}
    </dl>
  )
}
