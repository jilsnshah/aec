import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { motion } from 'motion/react'
import { ArrowRight, CheckCircle2, PackagePlus } from 'lucide-react'
import { errorText } from '@/api/client'
import { api } from '@/api/endpoints'
import { useAction } from '@/api/queries'
import type { StockReceiptResult } from '@/api/types'
import { cn } from '@/lib/cn'
import { fmtMoney, fmtQty, isQty, n } from '@/lib/format'
import { useDebounced } from '@/lib/route'
import { AllocationEditor, useAllocation, type Claimant } from '@/ui/allocate'
import { Button, Empty, Field, Notice, SearchBox } from '@/ui/core'
import { useProducts } from '@/ui/lines'
import { ListPane, ListRow, ListSkeleton, SplitView } from '@/ui/split'
import { HeaderArt } from '@/ui/art'

/** Stock that arrived without a purchase order. Waiting customers can be
 *  given theirs straight away. */
export function StockIn() {
  const [params, setParams] = useSearchParams()
  const products = useProducts()
  const [search, setSearch] = useState('')
  const productId = params.get('product') ?? ''
  const shown = products.items.filter((product) => `${product.name} ${product.sku}`.toLowerCase().includes(search.toLowerCase()))

  return (
    <SplitView
      showDetail={Boolean(productId)}
      onBack={() => setParams({})}
      list={
        <ListPane title="Stock In" filters={<SearchBox value={search} onChange={setSearch} placeholder="Find the product that arrived" />} footer="Receiving against a purchase order? Use Goods Receipts.">
          {products.loading ? (
            <ListSkeleton />
          ) : (
            shown.map((product) => (
              <ListRow key={product.id} group="stockin" selected={product.id === productId} onSelect={() => setParams({ product: product.id })} alert={n(product.stock) < 0}>
                <div className="flex items-center gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[13px] font-semibold">{product.name}</div>
                    <div className="text-[12px] text-fg-3">
                      {product.sku} · {product.unit_of_measure}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className={cn('num text-[13px] font-semibold', n(product.stock) < 0 && 'text-bad')}>{fmtQty(product.stock)}</div>
                    <div className="text-[11px] text-fg-3">stock</div>
                  </div>
                </div>
              </ListRow>
            ))
          )}
        </ListPane>
      }
    >
      {productId ? <Entry key={productId} productId={productId} /> : <Empty className="h-full" icon={<PackagePlus size={22} />} title="What arrived?" body="Choose the product on the left to record stock that came in without a purchase order." />}
    </SplitView>
  )
}

function Entry({ productId }: { productId: string }) {
  const products = useProducts()
  const product = products.byId.get(productId)
  const [quantity, setQuantity] = useState('')
  const [cost, setCost] = useState('')
  const [reference, setReference] = useState('')
  const [note, setNote] = useState('')
  const [key, setKey] = useState(() => crypto.randomUUID())
  const [result, setResult] = useState<StockReceiptResult | null>(null)
  const record = useAction(api.stockReceipts.create, { success: (receipt) => `${receipt.receipt_number} · ${fmtQty(receipt.receipt_quantity)} in`, quiet: true })

  useEffect(() => {
    if (product && !cost) setCost(String(n(product.last_purchase_price ?? product.average_cost) || ''))
  }, [product?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const valid = isQty(quantity) && n(quantity) > 0
  const debounced = useDebounced(valid ? quantity : '', 300)
  const preview = useQuery({ queryKey: ['pending-orders', productId, debounced], queryFn: () => api.products.pendingOrders(productId, debounced || undefined) })
  const required = n(preview.data?.required_allocation)
  const claimants: Claimant[] = useMemo(
    () => (preview.data?.items ?? []).filter((row) => n(row.quantity_unallocated) > 0).map((row) => ({ id: row.order_item_id, name: row.customer_name, reference: row.order_number, date: row.order_created_at, capacity: n(row.quantity_unallocated), proposed: n(row.proposed_allocation) })),
    [preview.data],
  )
  const plan = useAllocation(claimants, debounced ? required : 0)
  const costValid = cost.trim() !== '' && !Number.isNaN(Number(cost)) && n(cost) >= 0
  const ready = valid && costValid && debounced === quantity && !preview.isFetching && (required === 0 || plan.balanced)

  function submit() {
    record.mutate(
      { product_id: productId, quantity, unit_cost: cost, supplier_reference: reference || null, note: note || null, allocations: required > 0 ? plan.allocations : null, idempotency_key: key },
      { onSuccess: setResult },
    )
  }

  if (!product) return null
  if (result) {
    return (
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="flex h-full flex-col items-center justify-center px-8 text-center">
        <motion.div initial={{ scale: 0.6 }} animate={{ scale: 1 }} transition={{ type: 'spring', stiffness: 380, damping: 18 }} className="grid size-14 place-items-center rounded-full bg-ok/15 text-ok ring-1 ring-ok/25">
          <CheckCircle2 size={28} />
        </motion.div>
        <h2 className="mt-4 text-[18px] font-semibold">{result.receipt_number} recorded</h2>
        <p className="mt-1 text-[13px] text-fg-3">
          {fmtQty(result.receipt_quantity)} {result.unit_of_measure} of {result.product_name} at {fmtMoney(result.unit_cost)} · stock now {fmtQty(result.stock_after)}
        </p>
        {result.allocations.length > 0 ? (
          <div className="card mt-5 w-full max-w-[460px] p-4 text-left">
            <div className="eyebrow mb-2">Given to waiting customers</div>
            {result.allocations.map((allocation) => (
              <div key={allocation.order_item_id} className="flex justify-between py-1.5 text-[13px]">
                <Link to={`/orders/${allocation.order_id}`} className="hover:text-sky">
                  {allocation.customer_name} <span className="text-fg-3">· {allocation.order_number}</span>
                </Link>
                <span className="num font-semibold text-sky">{fmtQty(allocation.quantity_allocated)}</span>
              </div>
            ))}
          </div>
        ) : null}
        <Button
          kind="primary"
          className="mt-6"
          onClick={() => {
            setResult(null)
            setQuantity('')
            setReference('')
            setNote('')
            setKey(crypto.randomUUID())
            record.reset()
          }}
        >
          Record another
        </Button>
      </motion.div>
    )
  }

  const data = preview.data
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="relative shrink-0 overflow-hidden border-b border-white/7 px-6 pt-5 pb-4">
        <HeaderArt seed={2} />
        <div className="eyebrow mb-1.5">Stock in · {product.sku}</div>
        <h2 className="text-[21px] font-semibold tracking-[-0.022em]">{product.name}</h2>
        <p className="mt-1 text-[13px] text-fg-3">Stock rises now. Customers who are short can be given theirs from it.</p>
      </header>
      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_300px] overflow-hidden max-md:grid-cols-1 max-md:overflow-y-auto">
        <div className="min-h-0 space-y-5 overflow-y-auto p-6">
          {record.error ? <Notice tone="bad">{errorText(record.error)}</Notice> : null}
          <div className="grid grid-cols-2 gap-4 max-md:grid-cols-1">
            <Field label={`Quantity received (${product.unit_of_measure})`} error={quantity && !valid ? 'Enter a quantity above zero.' : null}>
              {(props) => <input {...props} className="field field-num h-12 text-[20px] font-semibold" inputMode="decimal" placeholder="0" autoFocus value={quantity} onChange={(event) => setQuantity(event.target.value)} />}
            </Field>
            <Field label={`Cost per ${product.unit_of_measure}`} hint={product.last_purchase_price ? `Last paid ${fmtMoney(product.last_purchase_price)}` : undefined} error={!costValid && cost !== '' ? 'Enter a cost.' : null}>
              {(props) => <input {...props} className="field field-num h-12 text-[20px] font-semibold" inputMode="decimal" placeholder="0.00" value={cost} onChange={(event) => setCost(event.target.value)} />}
            </Field>
            <Field label="Supplier / invoice" optional>
              {(props) => <input {...props} className="field" placeholder="Northgate Mills · INV-9912" value={reference} onChange={(event) => setReference(event.target.value)} />}
            </Field>
            <Field label="Note" optional>
              {(props) => <input {...props} className="field" placeholder="Lorry number, condition…" value={note} onChange={(event) => setNote(event.target.value)} />}
            </Field>
          </div>
          {valid && required > 0 ? (
            <AllocationEditor claimants={claimants} required={required} unit={product.unit_of_measure} state={plan} />
          ) : valid && data && !preview.isFetching ? (
            <Notice tone="sky">Nobody is short of this product, so all of it goes into free stock.</Notice>
          ) : null}
        </div>
        <aside className="min-h-0 space-y-5 overflow-y-auto border-l border-white/7 bg-ink-900/40 p-5">
          <div className="eyebrow">Before → after</div>
          {[
            ['Stock', data?.stock, data?.stock_after ?? data?.stock],
            ['Customers short', data?.unallocated_quantity, valid && data ? String(n(data.unallocated_quantity) - required) : data?.unallocated_quantity],
            ['To deliver', data?.pending_quantity, data?.pending_after ?? data?.pending_quantity],
          ].map(([label, before, after]) => (
            <div key={label} className="flex items-center justify-between text-[13px]">
              <span className="text-fg-3">{label}</span>
              <span className="num flex items-center gap-2">
                <span className="text-fg-3">{fmtQty(before)}</span>
                <ArrowRight size={12} className="text-fg-4" />
                <span className={cn('font-semibold', label === 'Stock' && n(after) < 0 && 'text-bad')}>{fmtQty(after)}</span>
              </span>
            </div>
          ))}
          <div className="border-t border-white/7 pt-4">
            <div className="flex items-baseline justify-between">
              <span className="text-[13px] text-fg-3">Value</span>
              <span className="num text-[18px] font-semibold">{fmtMoney(n(quantity) * n(cost))}</span>
            </div>
          </div>
          <Button kind="primary" className="h-10 w-full" icon={<PackagePlus size={15} />} busy={record.isPending} disabled={!ready} onClick={submit}>
            Record stock in
          </Button>
          {valid && required > 0 && !plan.balanced ? <p className="text-[12px] text-fg-3">Give exactly {fmtQty(required)} to waiting customers first.</p> : null}
        </aside>
      </div>
    </div>
  )
}
