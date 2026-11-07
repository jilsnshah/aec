import { useEffect, useState, type CSSProperties, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import type { Page } from '../api/types'
import { PAGE_SIZES, type Paging, type ViewMode } from '../lib/paging'
import { BackIcon, ChevronIcon, ExportIcon, GridViewIcon, ListViewIcon, RefreshIcon } from './icons'
import { Button, Card, Notice, Segmented, Skeleton } from './primitives'
import { TableScroll, TableSkeleton } from './table'

/* -------------------------------------------------------------------------- */
/* Pager                                                                       */
/* -------------------------------------------------------------------------- */

/** Page numbers to show: always the first and last, the current page and its
 *  neighbours, with gaps where pages are skipped. */
function pageList(current: number, last: number): (number | 'gap')[] {
  if (last <= 7) return Array.from({ length: last }, (_, index) => index + 1)
  const wanted = new Set([1, last, current - 1, current, current + 1])
  if (current <= 4) [2, 3, 4, 5].forEach((page) => wanted.add(page))
  if (current >= last - 3) [last - 4, last - 3, last - 2, last - 1].forEach((page) => wanted.add(page))
  const pages = [...wanted].filter((page) => page >= 1 && page <= last).sort((a, b) => a - b)
  const result: (number | 'gap')[] = []
  pages.forEach((page, index) => {
    if (index > 0 && page - pages[index - 1] > 1) result.push('gap')
    result.push(page)
  })
  return result
}

/** The footer under every listing: where you are, how many rows a page shows,
 *  and the way to the other pages. */
export function Pagination({
  paging,
  total,
  noun,
  busy,
}: {
  paging: Paging
  total: number | undefined
  /** Plural name of the rows, e.g. "orders". */
  noun: string
  busy?: boolean
}) {
  const { page, pageSize, setPageSize } = paging
  // Moving to another page starts reading from the top of the list.
  const setPage = (next: number, options?: { replace?: boolean }) => {
    paging.setPage(next, options)
    if (options?.replace) return
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    window.scrollTo({ top: 0, behavior: reduce ? 'auto' : 'smooth' })
  }
  const last = total ? Math.max(1, Math.ceil(total / pageSize)) : 1

  // A page beyond the end (rows were archived, filters narrowed) moves back.
  useEffect(() => {
    if (total !== undefined && total > 0 && page > last) paging.setPage(last, { replace: true })
  }, [total, page, last, paging.setPage])

  if (!total) return null
  const from = (page - 1) * pageSize + 1
  const to = Math.min(page * pageSize, total)

  return (
    <div className={`pager${busy ? ' is-busy' : ''}`}>
      <p className="pager__range" aria-live="polite">
        {total <= pageSize ? (
          <>
            <strong>{total.toLocaleString()}</strong> {noun}
          </>
        ) : (
          <>
            <strong>
              {from.toLocaleString()}–{to.toLocaleString()}
            </strong>{' '}
            of <strong>{total.toLocaleString()}</strong> {noun}
          </>
        )}
      </p>
      <label className="pager__size">
        <span>Rows per page</span>
        <select
          className="input input--sm"
          value={pageSize}
          onChange={(event) => setPageSize(Number(event.target.value))}
        >
          {PAGE_SIZES.map((size) => (
            <option key={size} value={size}>
              {size}
            </option>
          ))}
        </select>
      </label>
      {last > 1 ? (
        <nav className="pager__pages" aria-label="Pages">
          <button
            type="button"
            className="pager__step"
            onClick={() => setPage(page - 1)}
            disabled={page <= 1}
            aria-label="Previous page"
          >
            <BackIcon size={16} />
          </button>
          {pageList(page, last).map((entry, index) =>
            entry === 'gap' ? (
              <span key={`gap-${index}`} className="pager__gap" aria-hidden="true">
                …
              </span>
            ) : (
              <button
                key={entry}
                type="button"
                className={`pager__page${entry === page ? ' is-current' : ''}`}
                aria-current={entry === page ? 'page' : undefined}
                aria-label={`Page ${entry}`}
                onClick={() => setPage(entry)}
              >
                {entry}
              </button>
            ),
          )}
          <button
            type="button"
            className="pager__step"
            onClick={() => setPage(page + 1)}
            disabled={page >= last}
            aria-label="Next page"
          >
            <ChevronIcon size={16} />
          </button>
        </nav>
      ) : null}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* View switch and export                                                      */
/* -------------------------------------------------------------------------- */

export function ViewSwitch({ value, onChange }: { value: ViewMode; onChange: (mode: ViewMode) => void }) {
  return (
    <Segmented
      label="View"
      small
      value={value}
      onChange={onChange}
      options={[
        { value: 'list', label: <ListViewIcon size={15} aria-label="List" />, title: 'List view' },
        { value: 'grid', label: <GridViewIcon size={15} aria-label="Grid" />, title: 'Grid view' },
      ]}
    />
  )
}

/** Downloads every row matching the current filters, not just this page. */
export function ExportButton({ onExport, disabled }: { onExport: () => Promise<void>; disabled?: boolean }) {
  const [busy, setBusy] = useState(false)
  return (
    <Button
      icon={<ExportIcon size={15} />}
      busy={busy}
      disabled={disabled}
      title="Download every matching row as CSV"
      onClick={async () => {
        setBusy(true)
        try {
          await onExport()
        } finally {
          setBusy(false)
        }
      }}
    >
      Export
    </Button>
  )
}

/* -------------------------------------------------------------------------- */
/* Identity                                                                    */
/* -------------------------------------------------------------------------- */

function hueFor(seed: string): number {
  let hash = 0
  for (let index = 0; index < seed.length; index += 1) {
    hash = (hash * 31 + seed.charCodeAt(index)) | 0
  }
  return Math.abs(hash) % 360
}

export function initials(name: string): string {
  const words = name
    .replace(/[^\p{L}\p{N}\s]/gu, ' ')
    .split(/\s+/)
    .filter(Boolean)
  if (words.length === 0) return '?'
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase()
  return (words[0][0] + words[1][0]).toUpperCase()
}

/** A person's or company's initials on a colour derived from their name, so
 *  the same customer always looks the same. */
export function Avatar({
  name,
  seed,
  size = 'md',
  square,
}: {
  name: string
  seed?: string
  size?: 'sm' | 'md' | 'lg'
  /** Companies and things are squircles; people are round. */
  square?: boolean
}) {
  return (
    <span
      className={`avatar avatar--${size}${square ? ' avatar--square' : ''}`}
      style={{ '--avatar-hue': hueFor(seed ?? name) } as CSSProperties}
      aria-hidden="true"
    >
      {initials(name)}
    </span>
  )
}

/* -------------------------------------------------------------------------- */
/* Cards                                                                       */
/* -------------------------------------------------------------------------- */

export function CardGrid({ children, busy }: { children: ReactNode; busy?: boolean }) {
  return <div className={`card-grid${busy ? ' is-busy' : ''}`}>{children}</div>
}

/** One record in a grid. The whole card opens the record (a stretched link),
 *  while buttons inside it stay independently clickable. */
export function RecordCard({
  to,
  onOpen,
  openLabel,
  leading,
  title,
  subtitle,
  badge,
  actions,
  children,
  footer,
  tone,
}: {
  to?: string
  onOpen?: () => void
  openLabel?: string
  leading?: ReactNode
  title: ReactNode
  subtitle?: ReactNode
  badge?: ReactNode
  actions?: ReactNode
  children?: ReactNode
  footer?: ReactNode
  tone?: 'alert' | 'muted'
}) {
  const opener = to ? (
    <Link to={to} className="record-card__link" aria-label={openLabel}>
      {title}
    </Link>
  ) : onOpen ? (
    <button type="button" className="record-card__link" onClick={onOpen} aria-label={openLabel}>
      {title}
    </button>
  ) : (
    title
  )
  return (
    <article className={`record-card${to || onOpen ? ' is-interactive' : ''}${tone ? ` record-card--${tone}` : ''}`}>
      <header className="record-card__head">
        {leading}
        <div className="record-card__titles">
          <h3 className="record-card__title">{opener}</h3>
          {subtitle ? <div className="record-card__subtitle">{subtitle}</div> : null}
        </div>
        {badge || actions ? (
          <div className="record-card__aside">
            {badge}
            {actions ? <div className="record-card__actions">{actions}</div> : null}
          </div>
        ) : null}
      </header>
      {children ? <div className="record-card__body">{children}</div> : null}
      {footer ? <footer className="record-card__foot">{footer}</footer> : null}
    </article>
  )
}

/** Label/value pairs laid out in a compact grid inside a card. */
export function CardFacts({ items }: { items: { label: ReactNode; value: ReactNode; tone?: string }[] }) {
  return (
    <dl className="card-facts">
      {items.map((item, index) => (
        <div key={index} className="card-facts__item">
          <dt>{item.label}</dt>
          <dd className={item.tone}>{item.value}</dd>
        </div>
      ))}
    </dl>
  )
}

/** A thin stacked bar: e.g. delivered / reserved / awaiting of an order. */
export function Meter({
  segments,
  total,
  label,
}: {
  segments: { value: number; className: string; label: string }[]
  total: number
  label?: string
}) {
  const safeTotal = total > 0 ? total : 1
  return (
    <div
      className="bar meter"
      role="img"
      aria-label={label ?? segments.map((segment) => `${segment.label} ${segment.value}`).join(', ')}
    >
      {segments.map((segment) =>
        segment.value > 0 ? (
          <span
            key={segment.label}
            className={segment.className}
            style={{ width: `${Math.min(100, (segment.value / safeTotal) * 100)}%` }}
          />
        ) : null,
      )}
    </div>
  )
}

export function CardGridSkeleton({ count = 6 }: { count?: number }) {
  return (
    <div className="card-grid" aria-busy="true" aria-label="Loading">
      {Array.from({ length: count }, (_, index) => (
        <div key={index} className="record-card record-card--skeleton">
          <div className="record-card__head">
            <Skeleton width={36} height={36} radius={10} />
            <div className="record-card__titles">
              <Skeleton width="60%" height={14} />
              <Skeleton width="40%" height={11} />
            </div>
          </div>
          <div className="record-card__body">
            <Skeleton width="100%" height={44} />
          </div>
        </div>
      ))}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Collection                                                                  */
/* -------------------------------------------------------------------------- */

/** A paged listing shown as a table or as cards. Owns the shared states —
 *  first load, error, empty, refreshing — and the pager, so every list in the
 *  app behaves identically. Later page loads keep the current rows on screen,
 *  dimmed, rather than flashing a skeleton. */
export function Collection<T>({
  state,
  view,
  paging,
  noun,
  columns = 6,
  empty,
  table,
  card,
}: {
  state: { data: Page<T> | null; loading: boolean; error: string | null; reload: () => void }
  view: ViewMode
  paging: Paging
  noun: string
  columns?: number
  empty: ReactNode
  /** The table for list view: thead and tbody for the given rows. */
  table: (rows: T[]) => ReactNode
  card: (row: T) => ReactNode
}) {
  const { data, loading, error, reload } = state

  if (error && data === null) {
    return (
      <Card>
        <Notice
          kind="error"
          title="This could not be loaded"
          actions={
            <Button size="sm" icon={<RefreshIcon size={14} />} onClick={reload}>
              Try again
            </Button>
          }
        >
          {error}
        </Notice>
      </Card>
    )
  }

  if (data === null) {
    return view === 'grid' ? (
      <CardGridSkeleton />
    ) : (
      <Card flush>
        <TableSkeleton columns={columns} />
      </Card>
    )
  }

  if (data.total === 0) return <Card flush>{empty}</Card>

  const busy = loading
  const pager = <Pagination paging={paging} total={data.total} noun={noun} busy={busy} />

  if (view === 'grid') {
    return (
      <div className="collection">
        <CardGrid busy={busy}>{data.items.map(card)}</CardGrid>
        <Card flush>{pager}</Card>
      </div>
    )
  }

  return (
    <Card flush>
      <div className={busy ? 'is-refreshing' : undefined}>
        <TableScroll>{table(data.items)}</TableScroll>
      </div>
      {pager}
    </Card>
  )
}
