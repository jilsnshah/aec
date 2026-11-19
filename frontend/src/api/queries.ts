import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { errorText } from './client'
import { api } from './endpoints'

/** Every read in the app goes through these hooks, keyed so that one
 *  invalidation refreshes everything a change could affect. */
export const keys = {
  summary: ['summary'] as const,
  commitments: (q: object) => ['commitments', q] as const,
  list: (resource: string, q: object) => [resource, 'list', q] as const,
  one: (resource: string, id: string) => [resource, 'one', id] as const,
}

export function useSummary() {
  return useQuery({ queryKey: keys.summary, queryFn: api.summary })
}

export function useCommitments(q: Parameters<typeof api.commitments>[0] = {}) {
  return useQuery({ queryKey: keys.commitments(q), queryFn: () => api.commitments(q), placeholderData: keepPreviousData })
}

type Lister<Q, R> = (q: Q) => Promise<R>
export function useList<Q extends object, R>(resource: string, fn: Lister<Q, R>, q: Q, enabled = true) {
  return useQuery({ queryKey: keys.list(resource, q), queryFn: () => fn(q), placeholderData: keepPreviousData, enabled })
}

export function useOne<R>(resource: string, fn: (id: string) => Promise<R>, id: string | undefined) {
  return useQuery({ queryKey: keys.one(resource, id ?? ''), queryFn: () => fn(id as string), enabled: Boolean(id) })
}

/** A write. Stock, orders and purchases all move together, so a successful
 *  write refreshes every cached read; errors surface as a toast unless the
 *  caller shows them itself. */
export function useAction<V, R>(fn: (vars: V) => Promise<R>, options: { success?: string | ((result: R) => string); quiet?: boolean } = {}) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: (result) => {
      client.invalidateQueries()
      if (options.success) toast.success(typeof options.success === 'function' ? options.success(result) : options.success)
    },
    onError: (error) => {
      if (!options.quiet) toast.error(errorText(error))
    },
  })
}
