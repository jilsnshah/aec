import { useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { priceLists } from '@/api/records'
import { useDebounced } from '@/lib/route'
import type { Line } from '@/ui/lines'

/** Apply the customer's price list to each line's discount, unless the user
 *  typed a discount by hand. Returns the resolved prices and rules. */
export function usePriceList(open: boolean, customer: string, lines: Line[], setLines: (update: (current: Line[]) => Line[]) => void) {
  const chosen = lines.filter((line) => line.product_id)
  const key = useDebounced(JSON.stringify({ customer, lines: chosen.map((line) => [line.product_id, line.quantity]) }), 300)
  const pricing = useQuery({
    queryKey: ['price-lists', 'resolve', key],
    enabled: open && Boolean(customer) && chosen.length > 0,
    queryFn: () => priceLists.resolve({ customer_id: customer, lines: chosen.map((line) => ({ product_id: line.product_id, quantity: line.quantity || '1' })) }),
  })
  const auto = useRef<Record<string, string>>({})
  useEffect(() => {
    const resolved = pricing.data?.lines
    if (!resolved || !pricing.data?.price_list_active) return
    setLines((current) =>
      current.map((line) => {
        const hit = resolved.find((r) => r.product_id === line.product_id)
        if (!hit) return line
        const value = String(hit.discount_percent)
        const untouched = line.discount === '0' || line.discount === '' || line.discount === auto.current[line.key]
        if (!untouched || line.discount === value) return line
        auto.current[line.key] = value
        return { ...line, discount: value }
      }),
    )
  }, [pricing.data]) // eslint-disable-line react-hooks/exhaustive-deps
  return pricing.data
}
