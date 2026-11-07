import { useState } from 'react'

/** A fresh idempotency key: lets the backend recognise a retried submission. */
export function newIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  return `key-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

/** One stable key for the lifetime of a form or dialog, so a double-click or a
 *  retried request cannot record the same operation twice. */
export function useIdempotencyKey(): [string, () => void] {
  const [key, setKey] = useState(newIdempotencyKey)
  return [key, () => setKey(newIdempotencyKey())]
}
