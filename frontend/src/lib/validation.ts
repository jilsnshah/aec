import { isValidQuantity, toUnits } from './decimal'

export function isValidPercent(value: string): boolean {
  if (value.trim() === '') return false
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed >= 0 && parsed <= 100
}

export function isPositiveQuantity(value: string): boolean {
  return isValidQuantity(value) && toUnits(value) > 0
}

export function isValidEmail(value: string): boolean {
  return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(value.trim())
}

/** Whole days between an ISO timestamp and now, for "waiting 12 days". */
export function daysSince(isoDate: string): number {
  return Math.floor((Date.now() - new Date(isoDate).getTime()) / 86_400_000)
}
