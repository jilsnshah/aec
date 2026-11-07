import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { BackIcon, CheckIcon, RefreshIcon } from './icons'
import { Button, Loading, Notice } from './primitives'
import { TableSkeleton } from './table'

const APP_NAME = 'AEC'

/** The page frame. Each route mounts a fresh one, which plays the entry motion. */
export function Page({ children }: { children: ReactNode }) {
  return <div className="page">{children}</div>
}

/** The sticky page toolbar: title on the left, actions on the right, filters
 *  underneath. It frosts and gains a hairline once content scrolls beneath it. */
export function Toolbar({
  title,
  count,
  subtitle,
  badge,
  back,
  actions,
  children,
  documentTitle,
}: {
  title: ReactNode
  count?: number
  subtitle?: ReactNode
  badge?: ReactNode
  back?: { to: string; label: string }
  actions?: ReactNode
  children?: ReactNode
  /** Plain-text title for the browser tab, when `title` is not a string. */
  documentTitle?: string
}) {
  const sentinel = useRef<HTMLDivElement>(null)
  const header = useRef<HTMLElement>(null)
  const [stuck, setStuck] = useState(false)

  // Publish the toolbar's real height so sticky side panels sit just below it.
  useLayoutEffect(() => {
    const node = header.current
    if (!node) return
    const publish = () => {
      const mobileBar = window.matchMedia('(max-width: 960px)').matches ? 48 : 0
      document.documentElement.style.setProperty('--toolbar-offset', `${node.offsetHeight + mobileBar}px`)
    }
    publish()
    const observer = new ResizeObserver(publish)
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    const node = sentinel.current
    if (!node) return
    const observer = new IntersectionObserver(([entry]) => setStuck(!entry.isIntersecting), {
      threshold: 0,
    })
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  const tabTitle = documentTitle ?? (typeof title === 'string' ? title : undefined)
  useEffect(() => {
    if (tabTitle) document.title = `${tabTitle} — ${APP_NAME}`
  }, [tabTitle])

  return (
    <>
      <div ref={sentinel} aria-hidden="true" style={{ height: 1, marginBottom: -1 }} />
      <header ref={header} className={`toolbar${stuck ? ' is-stuck' : ''}`}>
        {back ? (
          <Link to={back.to} className="toolbar__back">
            <BackIcon size={16} aria-hidden="true" />
            {back.label}
          </Link>
        ) : null}
        <div className="toolbar__row">
          <div className="toolbar__titles">
            <div className="toolbar__title">
              <h1 className="t-title">{title}</h1>
              {count !== undefined ? <span className="toolbar__count">{count}</span> : null}
              {badge}
            </div>
            {subtitle ? <div className="toolbar__subtitle">{subtitle}</div> : null}
          </div>
          {actions ? <div className="toolbar__actions">{actions}</div> : null}
        </div>
        {children ? <div className="toolbar__controls">{children}</div> : null}
      </header>
    </>
  )
}

/** Loading, error and empty handling for anything fetched, so every list and
 *  panel behaves the same way. The first load shows a skeleton shaped like the
 *  content; later refreshes keep the old content on screen. */
export function AsyncBlock<T>({
  loading,
  error,
  data,
  isEmpty,
  empty,
  onRetry,
  skeleton = 'table',
  columns,
  children,
}: {
  loading: boolean
  error: string | null
  data: T | null
  isEmpty?: (data: T) => boolean
  empty?: ReactNode
  onRetry?: () => void
  skeleton?: 'table' | 'spinner'
  columns?: number
  children: (data: T) => ReactNode
}) {
  if (error && data === null) {
    return (
      <div className="card__body">
        <Notice
          kind="error"
          title="This could not be loaded"
          actions={
            onRetry ? (
              <Button size="sm" icon={<RefreshIcon size={14} />} onClick={onRetry}>
                Try again
              </Button>
            ) : undefined
          }
        >
          {error}
        </Notice>
      </div>
    )
  }
  if (loading && data === null) {
    return skeleton === 'table' ? <TableSkeleton columns={columns} /> : <Loading />
  }
  if (data === null) return null
  if (isEmpty && isEmpty(data)) return <>{empty}</>
  return <>{children(data)}</>
}

/** One numbered step of a workflow. Completed steps collapse to a summary that
 *  can be reopened. */
export function StepCard({
  index,
  title,
  summary,
  active,
  done,
  locked,
  onToggle,
  children,
  flush,
  trailing,
}: {
  index: number
  title: string
  summary?: ReactNode
  active: boolean
  done?: boolean
  locked?: boolean
  onToggle?: () => void
  children: ReactNode
  flush?: boolean
  trailing?: ReactNode
}) {
  const open = active && !locked
  const collapsible = Boolean(onToggle)
  return (
    <section
      className={`step${active ? ' is-active' : ''}${done ? ' is-done' : ''}${locked ? ' is-locked' : ''}`}
    >
      <button
        type="button"
        className="step__head"
        onClick={onToggle}
        disabled={locked || !collapsible}
        aria-expanded={collapsible ? open : undefined}
      >
        <span className="step__index" aria-hidden="true">
          {done && !active ? <CheckIcon size={14} strokeWidth={2.6} /> : index}
        </span>
        <span className="step__text">
          <span className="step__title">{title}</span>
          {summary ? <span className="step__summary">{summary}</span> : null}
        </span>
        {trailing}
        {collapsible && !locked ? (
          <span className="step__change">{open ? 'Done' : 'Change'}</span>
        ) : null}
      </button>
      {open || !collapsible ? (
        <div className={`step__body${flush ? ' step__body--flush' : ''}`}>{children}</div>
      ) : null}
    </section>
  )
}
