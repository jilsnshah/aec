import { useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'

/** Keep a page's "create" dialog in the URL as `?new=1`.
 *
 *  That makes it deep-linkable, and lets the command palette open it from
 *  anywhere in the app. */
export function useCreateParam(): [boolean, (open: boolean) => void] {
  const [params, setParams] = useSearchParams()
  const open = params.get('new') === '1'
  const setOpen = useCallback(
    (next: boolean) => {
      setParams(
        (current) => {
          const updated = new URLSearchParams(current)
          if (next) updated.set('new', '1')
          else updated.delete('new')
          return updated
        },
        { replace: true },
      )
    },
    [setParams],
  )
  return [open, setOpen]
}
