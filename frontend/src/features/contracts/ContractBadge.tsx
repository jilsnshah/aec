import { useQuery } from '@tanstack/react-query'
import { FileSignature } from 'lucide-react'
import { contracts, type ContractRate } from '@/api/contracts'
import { fmtDate, fmtMoney } from '@/lib/format'

const EMPTY: Record<string, ContractRate> = {}

/** The running contract rates with a supplier, by product id (rate per base unit). */
export function useContractRates(supplierId?: string): Record<string, ContractRate> {
  const query = useQuery({
    queryKey: ['contract-rates', supplierId],
    queryFn: () => contracts.supplierRates(supplierId as string),
    enabled: Boolean(supplierId),
    staleTime: 60_000,
  })
  return query.data?.rates ?? EMPTY
}

/** "Contract RC-xxx · ₹rate" when the product has a running contract rate with the supplier. */
export function ContractBadge({ productId, supplierId }: { productId?: string; supplierId?: string }) {
  const rates = useContractRates(supplierId)
  const hit = productId ? rates[productId] : undefined
  if (!hit) return null
  return (
    <span
      title={`Contract rate until ${fmtDate(hit.valid_until)}`}
      className="inline-flex h-[20px] shrink-0 items-center gap-1 rounded-full bg-ok/15 px-2 text-[11px] font-semibold whitespace-nowrap text-ok"
    >
      <FileSignature size={11} />
      Contract {hit.contract} · {fmtMoney(hit.rate)}
    </span>
  )
}
