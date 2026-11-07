import type { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { SortAscIcon, SortDescIcon, SortIcon } from './icons'
import { Skeleton } from './primitives'

export interface Sort {
  by: string
  dir: 'asc' | 'desc'
}

export function SortHeader({
  field,
  label,
  sort,
  onSort,
  numeric,
}: {
  field: string
  label: string
  sort: Sort
  onSort: (sort: Sort) => void
  numeric?: boolean
}) {
  const active = sort.by === field
  const Icon = !active ? SortIcon : sort.dir === 'asc' ? SortAscIcon : SortDescIcon
  return (
    <th
      className={numeric ? 'num' : undefined}
      aria-sort={active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}
    >
      <button
        type="button"
        className={`sort-button${active ? ' is-active' : ''}`}
        onClick={() => onSort({ by: field, dir: active && sort.dir === 'asc' ? 'desc' : 'asc' })}
      >
        {label}
        <Icon size={12} aria-hidden="true" />
      </button>
    </th>
  )
}

/** Placeholder rows shaped like the real ones, while the first load is in flight. */
export function TableSkeleton({ columns = 5, rows = 6 }: { columns?: number; rows?: number }) {
  return (
    <div className="table-scroll" aria-busy="true" aria-label="Loading">
      <table className="table">
        <tbody>
          {Array.from({ length: rows }, (_, row) => (
            <tr key={row}>
              {Array.from({ length: columns }, (_, column) => (
                <td key={column}>
                  <Skeleton width={column === 0 ? '62%' : `${36 + ((row + column) % 3) * 14}%`} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Make a whole table row open a page, while still letting links, buttons and
 *  inputs inside it do their own thing. */
export function useRowLink() {
  const navigate = useNavigate()
  return (to: string) => ({
    onClick: (event: React.MouseEvent) => {
      const target = event.target as HTMLElement
      if (target.closest('a, button, input, select, textarea, label')) return
      if (event.metaKey || event.ctrlKey) {
        window.open(to, '_blank')
        return
      }
      navigate(to)
    },
    onKeyDown: (event: React.KeyboardEvent) => {
      if (event.key === 'Enter' && event.target === event.currentTarget) navigate(to)
    },
    tabIndex: 0,
    role: 'link' as const,
  })
}

export function TableScroll({ children }: { children: ReactNode }) {
  return <div className="table-scroll">{children}</div>
}
