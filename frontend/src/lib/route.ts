import { useEffect, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'

/** A module's place in the URL: which record is selected, and whether the
 *  "new" sheet is open. Selecting a record never leaves the workspace. */
export function useRecordRoute(base: string) {
  const { id } = useParams()
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  return {
    id,
    select: (next: string) => navigate(`${base}/${next}${window.location.search}`, { replace: false }),
    back: () => navigate(base),
    isNew: params.get('new') === '1',
    param: (key: string) => params.get(key),
    openNew: () => setParams((current) => (current.set('new', '1'), current)),
    closeNew: () =>
      setParams((current) => {
        current.delete('new')
        return current
      }, { replace: true }),
  }
}

export function useDebounced<T>(value: T, delay = 250) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay)
    return () => window.clearTimeout(timer)
  }, [value, delay])
  return debounced
}
