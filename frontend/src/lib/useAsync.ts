import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../api/client'

export interface AsyncState<T> {
  data: T | null
  loading: boolean
  error: string | null
  reload: () => void
}

/** Run a fetch on mount and whenever `deps` change, with loading/error state. */
export function useAsync<T>(loader: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)
  const latest = useRef(0)

  useEffect(() => {
    const run = ++latest.current
    let cancelled = false
    setLoading(true)
    setError(null)
    loader()
      .then((result) => {
        // Ignore a response that a newer request has already superseded.
        if (cancelled || run !== latest.current) return
        setData(result)
      })
      .catch((cause: unknown) => {
        if (cancelled || run !== latest.current) return
        setError(cause instanceof ApiError ? cause.message : String(cause))
      })
      .finally(() => {
        if (cancelled || run !== latest.current) return
        setLoading(false)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])

  const reload = useCallback(() => setTick((value) => value + 1), [])
  return { data, loading, error, reload }
}

/** Debounce a rapidly changing value, for search boxes. */
export function useDebounced<T>(value: T, delayMs = 250): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delayMs)
    return () => window.clearTimeout(timer)
  }, [value, delayMs])
  return debounced
}
