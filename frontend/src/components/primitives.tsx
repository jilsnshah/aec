import {
  forwardRef,
  useLayoutEffect,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type ReactNode,
} from 'react'
import { Link, type LinkProps } from 'react-router-dom'
import {
  ErrorIcon,
  InfoIcon,
  SearchIcon,
  SuccessIcon,
  WarningIcon,
} from './icons'

/* -------------------------------------------------------------------------- */
/* Buttons                                                                     */
/* -------------------------------------------------------------------------- */

export type ButtonVariant =
  | 'primary'
  | 'secondary'
  | 'tinted'
  | 'plain'
  | 'ghost'
  | 'destructive'
  | 'destructive-tinted'
export type ButtonSize = 'sm' | 'md' | 'lg'

interface ButtonLook {
  variant?: ButtonVariant
  size?: ButtonSize
  icon?: ReactNode
  iconOnly?: boolean
  block?: boolean
}

function buttonClass({ variant = 'secondary', size = 'md', iconOnly, block }: ButtonLook, extra?: string) {
  return [
    'btn',
    variant !== 'secondary' ? `btn--${variant}` : '',
    size !== 'md' ? `btn--${size}` : '',
    iconOnly ? 'btn--icon' : '',
    block ? 'btn--block' : '',
    extra ?? '',
  ]
    .filter(Boolean)
    .join(' ')
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, ButtonLook {
  busy?: boolean
}

/** The one button. Variants follow the platform: a single filled primary per
 *  view, gray secondary for everything else, plain for inline actions. */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant, size, icon, iconOnly, block, busy, className, children, disabled, type, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type ?? 'button'}
      className={buttonClass({ variant, size, iconOnly, block }, `${busy ? 'is-busy' : ''} ${className ?? ''}`)}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      {...rest}
    >
      {busy ? <Spinner /> : null}
      {icon}
      {children ? <span>{children}</span> : null}
    </button>
  )
})

export function LinkButton({
  variant,
  size,
  icon,
  iconOnly,
  block,
  className,
  children,
  ...rest
}: LinkProps & ButtonLook) {
  return (
    <Link className={buttonClass({ variant, size, iconOnly, block }, className)} {...rest}>
      {icon}
      {children ? <span>{children}</span> : null}
    </Link>
  )
}

/* -------------------------------------------------------------------------- */
/* Activity                                                                    */
/* -------------------------------------------------------------------------- */

/** The twelve-spoke activity indicator. */
export function Spinner({ large, label }: { large?: boolean; label?: string }) {
  return (
    <span
      className={`spinner${large ? ' spinner--lg' : ''}`}
      role={label ? 'status' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      {Array.from({ length: 12 }, (_, index) => (
        <i
          key={index}
          style={{
            transform: `rotate(${index * 30}deg)`,
            animationDelay: `${-1 + index / 12}s`,
          }}
        />
      ))}
    </span>
  )
}

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="loading" role="status">
      <Spinner />
      <span>{label}</span>
    </div>
  )
}

export function Skeleton({
  width = '100%',
  height = 12,
  radius,
}: {
  width?: number | string
  height?: number
  radius?: number
}) {
  return <span className="skeleton" style={{ width, height, borderRadius: radius }} aria-hidden="true" />
}

/* -------------------------------------------------------------------------- */
/* Badges, keys, chips                                                         */
/* -------------------------------------------------------------------------- */

export type Tone = 'gray' | 'blue' | 'green' | 'orange' | 'red' | 'indigo' | 'teal'

export function Badge({
  tone = 'gray',
  dot,
  large,
  children,
  title,
}: {
  tone?: Tone
  dot?: boolean
  large?: boolean
  children: ReactNode
  title?: string
}) {
  return (
    <span
      className={`badge${tone !== 'gray' ? ` badge--${tone}` : ''}${dot ? ' badge--dot' : ''}${
        large ? ' badge--lg' : ''
      }`}
      title={title}
    >
      {children}
    </span>
  )
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="kbd">{children}</kbd>
}

/* -------------------------------------------------------------------------- */
/* Notices                                                                     */
/* -------------------------------------------------------------------------- */

const NOTICE_ICON = {
  info: InfoIcon,
  success: SuccessIcon,
  warning: WarningIcon,
  error: ErrorIcon,
}

export function Notice({
  kind = 'info',
  title,
  children,
  actions,
}: {
  kind?: 'info' | 'success' | 'warning' | 'error'
  title?: string
  children?: ReactNode
  actions?: ReactNode
}) {
  const Icon = NOTICE_ICON[kind]
  return (
    <div className={`notice notice--${kind}`} role={kind === 'error' ? 'alert' : 'status'}>
      <Icon size={17} className="notice__icon" aria-hidden="true" />
      <div className="notice__body">
        {title ? <div className="notice__title">{title}</div> : null}
        {children ? <div>{children}</div> : null}
        {actions ? <div className="notice__actions">{actions}</div> : null}
      </div>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Empty states                                                                */
/* -------------------------------------------------------------------------- */

export function EmptyState({
  icon,
  title,
  body,
  action,
  compact,
}: {
  icon?: ReactNode
  title: string
  body?: ReactNode
  action?: ReactNode
  compact?: boolean
}) {
  return (
    <div className={`empty${compact ? ' empty--compact' : ''}`}>
      {icon ? <div className="empty__icon">{icon}</div> : null}
      <div className="empty__title">{title}</div>
      {body ? <p className="empty__body">{body}</p> : null}
      {action ? <div className="empty__actions">{action}</div> : null}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Cards                                                                       */
/* -------------------------------------------------------------------------- */

export function Card({
  title,
  subtitle,
  actions,
  children,
  flush,
  footer,
  className,
  id,
}: {
  title?: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
  children?: ReactNode
  flush?: boolean
  footer?: ReactNode
  className?: string
  id?: string
}) {
  return (
    <section className={`card${flush ? ' card--flush' : ''}${className ? ` ${className}` : ''}`} id={id}>
      {title || actions ? (
        <header className="card__header">
          <div className="card__titles">
            {title ? <h2 className="card__title">{title}</h2> : null}
            {subtitle ? <div className="card__subtitle">{subtitle}</div> : null}
          </div>
          {actions ? <div className="btn-group">{actions}</div> : null}
        </header>
      ) : null}
      {children}
      {footer ? <footer className="card__footer">{footer}</footer> : null}
    </section>
  )
}

export function CardBody({ children, tight }: { children: ReactNode; tight?: boolean }) {
  return <div className={`card__body${tight ? ' card__body--tight' : ''}`}>{children}</div>
}

/* -------------------------------------------------------------------------- */
/* Search                                                                      */
/* -------------------------------------------------------------------------- */

/** A search field. `/` anywhere on the page focuses it (see Layout). */
export function SearchField({
  value,
  onChange,
  placeholder = 'Search',
  label,
  width,
}: {
  value: string
  onChange: (value: string) => void
  placeholder?: string
  label?: string
  width?: number | string
}) {
  const input = useRef<HTMLInputElement>(null)
  return (
    <div className="search-field" style={width ? { width } : undefined}>
      <SearchIcon size={15} className="search-field__icon" aria-hidden="true" />
      <input
        ref={input}
        type="search"
        className="input"
        data-page-search=""
        placeholder={placeholder}
        aria-label={label ?? placeholder}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Escape' && value) {
            event.stopPropagation()
            onChange('')
          }
        }}
      />
      {value ? (
        <button
          type="button"
          className="search-field__clear"
          aria-label="Clear search"
          onClick={() => {
            onChange('')
            input.current?.focus()
          }}
        >
          <svg width="8" height="8" viewBox="0 0 8 8" aria-hidden="true">
            <path d="M1 1l6 6M7 1L1 7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </button>
      ) : null}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Segmented control                                                           */
/* -------------------------------------------------------------------------- */

export interface SegmentOption<T extends string> {
  value: T
  label: ReactNode
  count?: number
  title?: string
}

/** The platform segmented control, with a thumb that slides between options. */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
  small,
}: {
  value: T
  onChange: (value: T) => void
  options: SegmentOption<T>[]
  label: string
  small?: boolean
}) {
  const container = useRef<HTMLDivElement>(null)
  const [thumb, setThumb] = useState<{ left: number; width: number } | null>(null)

  useLayoutEffect(() => {
    const root = container.current
    if (!root) return
    const measure = () => {
      const active = root.querySelector<HTMLButtonElement>('[aria-checked="true"]')
      if (!active) return setThumb(null)
      setThumb({ left: active.offsetLeft, width: active.offsetWidth })
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(root)
    return () => observer.disconnect()
  }, [value, options.length])

  function onKeyDown(event: React.KeyboardEvent) {
    const index = options.findIndex((option) => option.value === value)
    if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
      event.preventDefault()
      const step = event.key === 'ArrowRight' ? 1 : -1
      const next = options[(index + step + options.length) % options.length]
      onChange(next.value)
      container.current
        ?.querySelector<HTMLButtonElement>(`[data-value="${CSS.escape(next.value)}"]`)
        ?.focus()
    }
  }

  return (
    <div
      ref={container}
      className={`segmented${small ? ' segmented--sm' : ''}`}
      role="radiogroup"
      aria-label={label}
      onKeyDown={onKeyDown}
    >
      {thumb ? (
        <span
          className="segmented__thumb"
          style={{ width: thumb.width, transform: `translateX(${thumb.left}px)` }}
          aria-hidden="true"
        />
      ) : null}
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          data-value={option.value}
          aria-checked={option.value === value}
          tabIndex={option.value === value ? 0 : -1}
          className="segmented__item"
          title={option.title}
          onClick={() => onChange(option.value)}
        >
          {option.label}
          {option.count !== undefined ? (
            <span className="segmented__count">{option.count}</span>
          ) : null}
        </button>
      ))}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Toggles                                                                     */
/* -------------------------------------------------------------------------- */

export function Switch({
  checked,
  onChange,
  label,
  description,
}: {
  checked: boolean
  onChange: (checked: boolean) => void
  label: string
  description?: string
}) {
  return (
    <label className="switch-row">
      <button
        type="button"
        role="switch"
        className="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
      >
        <span className="visually-hidden">{label}</span>
      </button>
      <span>
        <span>{label}</span>
        {description ? <span className="cell-sub">{description}</span> : null}
      </span>
    </label>
  )
}

export function Checkbox({
  checked,
  onChange,
  label,
}: {
  checked: boolean
  onChange: (checked: boolean) => void
  label: ReactNode
}) {
  return (
    <label className="checkbox">
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      {label}
    </label>
  )
}

/* -------------------------------------------------------------------------- */
/* Numbers                                                                     */
/* -------------------------------------------------------------------------- */

export function Stat({
  label,
  value,
  hint,
  dot,
  tone,
  to,
}: {
  label: string
  value: ReactNode
  hint?: ReactNode
  dot?: string
  tone?: 'alert' | 'positive'
  to?: string
}) {
  const body = (
    <>
      <div className="stat__label">
        {dot ? <span className="stat__dot" style={{ background: dot }} /> : null}
        {label}
      </div>
      <div className="stat__value">{value}</div>
      {hint ? <div className="stat__hint">{hint}</div> : null}
    </>
  )
  const className = `stat${tone ? ` stat--${tone}` : ''}`
  return to ? (
    <Link to={to} className={className}>
      {body}
    </Link>
  ) : (
    <div className={className}>{body}</div>
  )
}

export interface MetricItem {
  label: string
  value: ReactNode
  hint?: ReactNode
  tone?: 'accent' | 'positive' | 'negative' | 'reserved' | 'owed'
  dot?: string
}

/** A row of headline numbers, divided by hairlines. */
export function MetricStrip({ items }: { items: MetricItem[] }) {
  return (
    <div className="metric-strip">
      {items.map((item) => (
        <div key={item.label} className={`metric${item.tone ? ` metric--${item.tone}` : ''}`}>
          <div className="metric__label">
            {item.dot ? <span className="stat__dot" style={{ background: item.dot }} /> : null}
            {item.label}
          </div>
          <div className="metric__value">{item.value}</div>
          {item.hint ? <div className="metric__hint">{item.hint}</div> : null}
        </div>
      ))}
    </div>
  )
}

export function KeyValue({
  items,
  stacked,
}: {
  items: { label: string; value: ReactNode; total?: boolean }[]
  stacked?: boolean
}) {
  return (
    <dl className={`kv${stacked ? ' kv--stacked' : ''}`}>
      {items.map((item) => (
        <div key={item.label} className={item.total ? 'kv__total' : undefined}>
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
        </div>
      ))}
    </dl>
  )
}
