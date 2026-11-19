import { AnimatePresence, motion } from 'motion/react'
import { Plus, X } from 'lucide-react'
import { api } from '@/api/endpoints'
import { useList } from '@/api/queries'
import type { CustomerListRow, ProductOut, SupplierListRow } from '@/api/types'
import { cn } from '@/lib/cn'
import { fmtAmount, fmtMoney, fmtQty, isQty, n } from '@/lib/format'
import { Picker, type PickOption } from './pickers'

export interface Line {
  key: string
  product_id: string
  quantity: string
  /** Discount % for sales and enquiries. */
  discount: string
  /** Unit cost for purchases. */
  cost: string
}

export const newLine = (patch: Partial<Line> = {}): Line => ({ key: Math.random().toString(36).slice(2), product_id: '', quantity: '1', discount: '0', cost: '', ...patch })

/** Every active product, for pickers. */
export function useProducts() {
  const query = useList('products', api.products.list, { limit: 500, sort_by: 'name', sort_dir: 'asc' as const })
  const items = query.data?.items ?? []
  return { items, byId: new Map(items.map((product) => [product.id, product])), loading: query.isPending }
}
export function useCustomers() {
  const query = useList('customers', api.customers.list, { limit: 500 })
  return query.data?.items ?? ([] as CustomerListRow[])
}
export function useSuppliers() {
  const query = useList('suppliers', api.suppliers.list, { limit: 500 })
  return query.data?.items ?? ([] as SupplierListRow[])
}

export const productOption = (product: ProductOut): PickOption => ({
  value: product.id,
  label: product.name,
  detail: `${product.sku} · ${product.unit_of_measure}`,
  trail: <span className={cn('num text-[11.5px]', n(product.stock) < 0 ? 'text-bad' : 'text-fg-3')}>{fmtQty(product.stock)} stock</span>,
})

type Mode = 'sale' | 'purchase'

export function lineTotal(line: Line, product: ProductOut | undefined, mode: Mode) {
  const qty = n(line.quantity)
  if (mode === 'purchase') return qty * n(line.cost)
  const mrp = n(product?.mrp)
  return qty * mrp * (1 - n(line.discount) / 100)
}

export function lineErrors(lines: Line[], mode: Mode): string[] {
  const errors: string[] = []
  if (!lines.some((line) => line.product_id)) errors.push('Add at least one product.')
  lines.forEach((line, index) => {
    if (!line.product_id) return
    if (!isQty(line.quantity) || n(line.quantity) <= 0) errors.push(`Line ${index + 1}: enter a quantity above zero.`)
    if (mode === 'sale' && (Number.isNaN(Number(line.discount)) || n(line.discount) < 0 || n(line.discount) > 100)) errors.push(`Line ${index + 1}: discount must be 0–100%.`)
    if (mode === 'purchase' && (line.cost.trim() === '' || Number.isNaN(Number(line.cost)) || n(line.cost) < 0)) errors.push(`Line ${index + 1}: enter a unit cost.`)
  })
  return errors
}

/** Products, quantities and prices for an order, enquiry or purchase. */
export function LineEditor({ lines, onChange, mode }: { lines: Line[]; onChange: (lines: Line[]) => void; mode: Mode }) {
  const products = useProducts()
  const options = products.items.map(productOption)
  const update = (key: string, patch: Partial<Line>) => onChange(lines.map((line) => (line.key === key ? { ...line, ...patch } : line)))
  const columns = mode === 'sale' ? 'minmax(0,1fr) 84px 96px 74px 104px 28px' : 'minmax(0,1fr) 84px 110px 110px 28px'

  return (
    <div className="min-w-[600px] overflow-hidden rounded-xl bg-ink-900 ring-1 ring-white/7 ring-inset">
      <div className="eyebrow grid items-center gap-2.5 border-b border-white/7 px-3 py-2" style={{ gridTemplateColumns: columns }}>
        <span>Product</span>
        <span className="text-right">Qty</span>
        {mode === 'sale' ? (
          <>
            <span className="text-right">MRP</span>
            <span className="text-right">Disc %</span>
          </>
        ) : (
          <span className="text-right">Unit cost</span>
        )}
        <span className="text-right">Total</span>
        <span />
      </div>
      <AnimatePresence initial={false}>
        {lines.map((line) => {
          const product = products.byId.get(line.product_id)
          return (
            <motion.div
              key={line.key}
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.22 }}
              className="border-b border-white/5 last:border-0"
            >
              <div className="grid items-center gap-2.5 px-3 py-2" style={{ gridTemplateColumns: columns }}>
                <Picker
                  small
                  value={line.product_id}
                  options={options}
                  placeholder="Choose a product…"
                  onChange={(value) => {
                    const chosen = products.byId.get(value)
                    update(line.key, { product_id: value, cost: mode === 'purchase' && !line.cost && chosen ? String(n(chosen.last_purchase_price ?? chosen.average_cost) || '') : line.cost })
                  }}
                />
                <input className="field field-sm field-num" inputMode="decimal" value={line.quantity} aria-invalid={line.product_id && !isQty(line.quantity) ? true : undefined} onChange={(event) => update(line.key, { quantity: event.target.value })} />
                {mode === 'sale' ? (
                  <>
                    <span className="num text-right text-[12.5px] text-fg-3">{product ? fmtAmount(product.mrp) : '—'}</span>
                    <input className="field field-sm field-num" inputMode="decimal" value={line.discount} onChange={(event) => update(line.key, { discount: event.target.value })} />
                  </>
                ) : (
                  <input className="field field-sm field-num" inputMode="decimal" placeholder="0.00" value={line.cost} onChange={(event) => update(line.key, { cost: event.target.value })} />
                )}
                <span className="num text-right text-[13px] font-medium">{line.product_id ? fmtAmount(lineTotal(line, product, mode)) : '—'}</span>
                <button
                  type="button"
                  className="grid size-7 place-items-center rounded-md text-fg-4 transition hover:bg-white/8 hover:text-fg disabled:opacity-30"
                  disabled={lines.length === 1}
                  onClick={() => onChange(lines.filter((item) => item.key !== line.key))}
                  aria-label="Remove line"
                >
                  <X size={14} />
                </button>
              </div>
              {product ? (
                <div className="flex gap-3 px-3 pb-2 text-[11.5px] text-fg-3">
                  <span>
                    Stock <b className={cn('num font-medium', n(product.stock) < 0 ? 'text-bad' : 'text-fg-2')}>{fmtQty(product.stock)}</b> {product.unit_of_measure}
                  </span>
                  {n(product.on_order_quantity) > 0 ? <span>· {fmtQty(product.on_order_quantity)} to receive</span> : null}
                  {mode === 'sale' && n(line.quantity) > Math.max(0, n(product.stock)) ? <span className="text-warn">· {fmtQty(n(line.quantity) - Math.max(0, n(product.stock)))} will be short</span> : null}
                  {mode === 'purchase' && product.last_purchase_price ? <span>· last paid {fmtMoney(product.last_purchase_price)}</span> : null}
                </div>
              ) : null}
            </motion.div>
          )
        })}
      </AnimatePresence>
      <button type="button" onClick={() => onChange([...lines, newLine()])} className="flex h-10 w-full items-center gap-2 px-3 text-[12.5px] font-medium text-sky transition hover:bg-white/[0.03]">
        <Plus size={14} /> Add product
      </button>
    </div>
  )
}
