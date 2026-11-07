/** Fixed-point helpers.
 *
 *  Quantities are exchanged with the backend as decimal strings with three
 *  decimal places. Adding them as JS floats drifts (0.1 + 0.2 !== 0.3), and the
 *  stock-in screen has to compare an allocation total against a required total
 *  exactly. So every quantity is converted to an integer number of thousandths,
 *  summed there, and converted back only for display.
 */
const SCALE = 1000

/** Parse a decimal string into whole thousandths. Returns NaN for junk. */
export function toUnits(value: string | number | null | undefined): number {
  if (value === null || value === undefined || value === '') return NaN
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return NaN
  return Math.round(parsed * SCALE)
}

/** Render whole thousandths back as a decimal string. */
export function fromUnits(units: number): string {
  if (!Number.isFinite(units)) return '0'
  return (units / SCALE).toFixed(3)
}

export function sumUnits(values: number[]): number {
  return values.reduce((total, value) => total + (Number.isFinite(value) ? value : 0), 0)
}

/** True when the string is a well-formed, non-negative quantity. */
export function isValidQuantity(value: string): boolean {
  if (value.trim() === '') return false
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed >= 0
}
