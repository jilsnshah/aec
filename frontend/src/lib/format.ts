/** Numbers, money and dates as the business reads them (India, rupees). */

const money = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: 2, maximumFractionDigits: 2 })
const moneyRound = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 })
const amount = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const quantity = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 3 })
const compact = new Intl.NumberFormat('en-IN', { notation: 'compact', maximumFractionDigits: 1 })

export const n = (value: string | number | null | undefined) => {
  const parsed = typeof value === 'number' ? value : Number(value ?? 0)
  return Number.isFinite(parsed) ? parsed : 0
}

export const fmtMoney = (value: string | number | null | undefined) => money.format(n(value))
export const fmtMoneyRound = (value: string | number | null | undefined) => moneyRound.format(n(value))
export const fmtAmount = (value: string | number | null | undefined) => amount.format(n(value))
export const fmtQty = (value: string | number | null | undefined) => quantity.format(n(value))
export const fmtCompactMoney = (value: number) => `₹${compact.format(value)}`
export const fmtPercent = (value: string | number | null | undefined) => `${n(value).toFixed(1)}%`

const dateFormat = new Intl.DateTimeFormat('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
const shortDate = new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short' })
const dateTime = new Intl.DateTimeFormat('en-IN', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
const longDate = new Intl.DateTimeFormat('en-IN', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })

export const fmtDate = (value: string | null | undefined) => (value ? dateFormat.format(new Date(value)) : '—')
export const fmtShortDate = (value: string | Date) => shortDate.format(typeof value === 'string' ? new Date(value) : value)
export const fmtDateTime = (value: string | null | undefined) => (value ? dateTime.format(new Date(value)) : '—')
export const fmtToday = () => longDate.format(new Date())

export function fmtAgo(value: string | null | undefined): string {
  if (!value) return '—'
  const seconds = (Date.now() - new Date(value).getTime()) / 1000
  if (seconds < 60) return 'just now'
  const minutes = seconds / 60
  if (minutes < 60) return `${Math.floor(minutes)} min ago`
  const hours = minutes / 60
  if (hours < 24) return `${Math.floor(hours)} h ago`
  const days = hours / 24
  if (days < 30) return `${Math.floor(days)} d ago`
  return fmtDate(value)
}

export const daysSince = (value: string) => Math.floor((Date.now() - new Date(value).getTime()) / 86_400_000)

export const initials = (name: string) =>
  name
    .replace(/^demo\s+/i, '')
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join('') || '?'

export const plural = (count: number, word: string, many = `${word}s`) => `${count} ${count === 1 ? word : many}`

/** A typed quantity is valid when it is a non-negative number with at most three decimals. */
export const isQty = (value: string) => /^\d+(\.\d{1,3})?$/.test(value.trim())
