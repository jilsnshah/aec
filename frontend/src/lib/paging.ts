import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

export const PAGE_SIZES = [25, 50, 100] as const
const DEFAULT_PAGE_SIZE = 25

function readStored(key: string): string | null {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

function writeStored(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value)
  } catch {
    // Private windows may refuse storage; the preference just is not kept.
  }
}

export interface Paging {
  /** 1-based page number. */
  page: number
  pageSize: number
  limit: number
  offset: number
  setPage: (page: number, options?: { replace?: boolean }) => void
  setPageSize: (size: number) => void
}

/** Server-side paging for one listing. The page lives in the URL (`?page=3`),
 *  so it survives reloads and Back; the page size is remembered per listing.
 *  Changing any of `filters` returns to the first page. */
export function usePaging(key: string, filters: unknown[]): Paging {
  const [params, setParams] = useSearchParams()
  const page = Math.max(1, Math.floor(Number(params.get('page'))) || 1)
  const [pageSize, setSize] = useState(() => {
    const stored = Number(readStored(`aec-page-size:${key}`))
    return (PAGE_SIZES as readonly number[]).includes(stored) ? stored : DEFAULT_PAGE_SIZE
  })

  const setPage = useCallback(
    (next: number, options?: { replace?: boolean }) => {
      setParams(
        (current) => {
          const updated = new URLSearchParams(current)
          if (next <= 1) updated.delete('page')
          else updated.set('page', String(next))
          return updated
        },
        { replace: options?.replace ?? false },
      )
    },
    [setParams],
  )

  const filterKey = JSON.stringify(filters)
  const previousFilters = useRef(filterKey)
  useEffect(() => {
    if (previousFilters.current === filterKey) return
    previousFilters.current = filterKey
    setPage(1, { replace: true })
  }, [filterKey, setPage])

  const setPageSize = useCallback(
    (size: number) => {
      writeStored(`aec-page-size:${key}`, String(size))
      setSize(size)
      setPage(1, { replace: true })
    },
    [key, setPage],
  )

  return { page, pageSize, limit: pageSize, offset: (page - 1) * pageSize, setPage, setPageSize }
}

export type ViewMode = 'list' | 'grid'

/** List or grid, remembered per listing. Phones start on the grid, which
 *  reads better than a sideways-scrolling table. */
export function useViewMode(key: string): [ViewMode, (mode: ViewMode) => void] {
  const [mode, setMode] = useState<ViewMode>(() => {
    const stored = readStored(`aec-view:${key}`)
    if (stored === 'list' || stored === 'grid') return stored
    return window.matchMedia?.('(max-width: 680px)').matches ? 'grid' : 'list'
  })
  const update = useCallback(
    (next: ViewMode) => {
      writeStored(`aec-view:${key}`, next)
      setMode(next)
    },
    [key],
  )
  return [mode, update]
}
