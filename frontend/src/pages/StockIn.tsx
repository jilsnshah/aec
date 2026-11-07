import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import type { PendingOrderRow, PendingOrders, Product, StockReceiptResult } from '../api/types'
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  Field,
  FormGrid,
  LinkButton,
  Loading,
  MetricStrip,
  Notice,
  Page,
  SearchField,
  SignedQuantity,
  StepCard,
  StockFigures,
  TableScroll,
  Toolbar,
  useToast,
} from '../components/ui'
import { CheckIcon, DeliveryIcon, ProductsIcon, ResetIcon, StockInIcon } from '../components/icons'
import { fromUnits, isValidQuantity, sumUnits, toUnits } from '../lib/decimal'
import { formatAmount, formatDateTime, formatMoney, formatQuantity, formatUnitPrice } from '../lib/format'
import { newIdempotencyKey } from '../lib/ids'
import { useAsync, useDebounced } from '../lib/useAsync'
import { daysSince } from '../lib/validation'

type Step = 'product' | 'quantity' | 'allocate'

function waitingFor(isoDate: string): { label: string; className: string } {
  const days = daysSince(isoDate)
  if (days <= 0) return { label: 'placed today', className: 'age' }
  const label = days === 1 ? 'waiting 1 day' : `waiting ${days} days`
  if (days >= 30) return { label, className: 'age age--stale' }
  if (days >= 7) return { label, className: 'age age--old' }
  return { label, className: 'age' }
}

export default function StockInPage() {
  const toast = useToast()
  const products = useAsync<Product[]>(() => api.products.all(), [])

  const [productId, setProductId] = useState('')
  const [productSearch, setProductSearch] = useState('')
  const [quantity, setQuantity] = useState('')
  const [unitCost, setUnitCost] = useState('')
  const [supplierRef, setSupplierRef] = useState('')
  const [note, setNote] = useState('')
  const [reopened, setReopened] = useState<Step | null>(null)
  // The quantity step stays open until the operator moves on, so typing the
  // first digit does not whisk the price and reference fields away.
  const [quantityConfirmed, setQuantityConfirmed] = useState(false)

  const debouncedQuantity = useDebounced(quantity, 300)
  const quantityValid = isValidQuantity(quantity) && toUnits(quantity) > 0
  // The purchase price is what makes profit real, so it is required; zero is
  // allowed but must be typed on purpose.
  const costValid = isValidQuantity(unitCost)
  const totalSpend = quantityValid && costValid ? Number(quantity) * Number(unitCost) : 0
  const previewQuantity =
    isValidQuantity(debouncedQuantity) && toUnits(debouncedQuantity) > 0 ? debouncedQuantity : undefined

  const preview = useAsync<PendingOrders | null>(
    () => (productId ? api.products.pendingOrders(productId, previewQuantity) : Promise.resolve(null)),
    [productId, previewQuantity],
  )

  const [allocations, setAllocations] = useState<Record<string, string>>({})
  const [customised, setCustomised] = useState(false)
  const seedKey = useRef('')

  // Re-seed from the server's FIFO proposal when the product or quantity changes.
  useEffect(() => {
    const data = preview.data
    if (!data) return
    const key = `${data.product_id}:${data.receipt_quantity ?? ''}`
    if (seedKey.current === key) return
    seedKey.current = key
    const seeded: Record<string, string> = {}
    for (const row of data.items) seeded[row.order_item_id] = row.proposed_allocation
    setAllocations(seeded)
    setCustomised(false)
  }, [preview.data])

  const [confirming, setConfirming] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [result, setResult] = useState<StockReceiptResult | null>(null)
  const idempotencyKey = useRef(newIdempotencyKey())

  const data = preview.data
  const selected = (products.data ?? []).find((product) => product.id === productId)

  const receiptUnits = quantityValid ? toUnits(quantity) : 0
  const stockUnits = data ? toUnits(data.stock) : 0
  const unallocatedUnits = data ? toUnits(data.unallocated_quantity) : 0
  const requiredUnits = Math.min(receiptUnits, unallocatedUnits)

  const rowErrors = useMemo(() => {
    const errors: Record<string, string> = {}
    for (const row of data?.items ?? []) {
      const raw = allocations[row.order_item_id] ?? '0'
      if (raw.trim() === '') continue
      const units = toUnits(raw)
      if (!Number.isFinite(units) || units < 0) errors[row.order_item_id] = 'Enter zero or more.'
      else if (units > toUnits(row.quantity_unallocated)) {
        errors[row.order_item_id] = `Only ${formatQuantity(row.quantity_unallocated)} awaits stock.`
      }
    }
    return errors
  }, [data, allocations])

  const allocatedUnits = sumUnits((data?.items ?? []).map((row) => toUnits(allocations[row.order_item_id] ?? '0') || 0))
  const remainingUnits = requiredUnits - allocatedUnits

  // The whole receipt lands in stock; who it goes to first moves nothing.
  const afterStockUnits = stockUnits + receiptUnits
  const afterWaitingUnits = unallocatedUnits - allocatedUnits

  const blockers: string[] = []
  if (!productId) blockers.push('Choose a product.')
  else if (!quantityValid) blockers.push('Enter how much arrived.')
  if (productId && !costValid) blockers.push('Enter the purchase price per unit — 0 if it was free.')
  if (Object.keys(rowErrors).length > 0) blockers.push('Fix the highlighted amounts.')
  if (data && quantityValid && remainingUnits > 0) {
    blockers.push(`Assign ${formatQuantity(fromUnits(remainingUnits))} more — waiting orders are served before new stock is free.`)
  }
  if (data && quantityValid && remainingUnits < 0) {
    blockers.push(`Assign ${formatQuantity(fromUnits(-remainingUnits))} less — more than this receipt covers.`)
  }
  const canSubmit = blockers.length === 0 && !preview.loading && !submitting

  const quantityReady = quantityValid && costValid
  const activeStep: Step =
    reopened ?? (!productId ? 'product' : !(quantityReady && quantityConfirmed) ? 'quantity' : 'allocate')

  function confirmQuantity() {
    if (!quantityReady) return
    setQuantityConfirmed(true)
    setReopened(null)
  }

  function chooseProduct(id: string) {
    const product = (products.data ?? []).find((entry) => entry.id === id)
    setProductId(id)
    setQuantity('')
    // Offer the last price paid; the operator confirms or changes it.
    setUnitCost(product?.last_purchase_price ?? '')
    setSupplierRef('')
    setNote('')
    setAllocations({})
    seedKey.current = ''
    setSubmitError(null)
    setQuantityConfirmed(false)
    setReopened(null)
  }

  function setRow(orderItemId: string, value: string) {
    setCustomised(true)
    setAllocations((current) => ({ ...current, [orderItemId]: value }))
  }

  /** As much as this line can take: its unallocated quantity, capped so the
   *  total never overshoots what must be allocated. */
  function fillRowToMax(row: PendingOrderRow) {
    const current = toUnits(allocations[row.order_item_id] ?? '0') || 0
    const headroom = requiredUnits - (allocatedUnits - current)
    setRow(row.order_item_id, fromUnits(Math.max(0, Math.min(toUnits(row.quantity_unallocated), headroom))))
  }

  function applyFifo() {
    const seeded: Record<string, string> = {}
    for (const row of data?.items ?? []) seeded[row.order_item_id] = row.proposed_allocation
    setAllocations(seeded)
    setCustomised(false)
  }

  function clearAll() {
    const cleared: Record<string, string> = {}
    for (const row of data?.items ?? []) cleared[row.order_item_id] = '0'
    setAllocations(cleared)
    setCustomised(true)
  }

  function startOver() {
    setResult(null)
    setProductId('')
    setProductSearch('')
    setQuantity('')
    setUnitCost('')
    setSupplierRef('')
    setNote('')
    setAllocations({})
    seedKey.current = ''
    setQuantityConfirmed(false)
    setReopened(null)
  }

  async function submit() {
    if (!canSubmit || !data) return
    setSubmitting(true)
    setSubmitError(null)
    try {
      const receipt = await api.inventory.receiveStock({
        product_id: productId,
        quantity,
        unit_cost: unitCost || '0',
        supplier_reference: supplierRef.trim() || null,
        note: note.trim() || null,
        // Send the distribution on screen; the backend re-validates it.
        allocations: data.items.map((row) => ({
          order_item_id: row.order_item_id,
          quantity: allocations[row.order_item_id] || '0',
        })),
        idempotency_key: idempotencyKey.current,
      })
      setResult(receipt)
      setConfirming(false)
      idempotencyKey.current = newIdempotencyKey()
      toast.success(
        `${receipt.receipt_number} recorded`,
        `${formatQuantity(receipt.receipt_quantity)} in · ${formatQuantity(receipt.allocated_total)} to waiting orders`,
      )
      products.reload()
    } catch (cause) {
      setSubmitError(cause instanceof ApiError ? cause.message : String(cause))
      setConfirming(false)
    } finally {
      setSubmitting(false)
    }
  }

  const unit = selected?.unit_of_measure ?? 'units'
  const hasWaiting = Boolean(data && data.items.length > 0)

  return (
    <Page>
      <Toolbar
        title="Stock In"
        subtitle="Stock that arrived without a purchase order. Waiting customers are served first."
        actions={
          <LinkButton to="/goods-receipts" variant="plain">
            Receiving against a PO? Use Goods Receipts
          </LinkButton>
        }
      />

      {result ? (
        <ReceiptDone result={result} onStartOver={startOver} />
      ) : (
        <div className="columns columns--main-aside">
          <div className="stack stack--tight">
            {submitError ? (
              <Notice kind="error" title="Rejected — nothing was saved">
                {submitError}
              </Notice>
            ) : null}

            <StepCard
              index={1}
              title="Product"
              active={activeStep === 'product'}
              done={Boolean(productId)}
              summary={selected ? `${selected.sku} — ${selected.name}` : 'Choose what arrived'}
              onToggle={() => setReopened(activeStep === 'product' ? null : 'product')}
            >
              <ProductPicker
                products={products.data ?? []}
                loading={products.loading}
                error={products.error}
                search={productSearch}
                onSearch={setProductSearch}
                selectedId={productId}
                onSelect={chooseProduct}
              />
            </StepCard>

            <StepCard
              index={2}
              title="Quantity and price"
              locked={!productId}
              active={activeStep === 'quantity'}
              done={quantityValid && costValid}
              summary={
                quantityValid && costValid
                  ? `${formatQuantity(quantity)} ${unit} at ${formatUnitPrice(unitCost)} · ${formatMoney(totalSpend)}`
                  : 'How much arrived, and what it cost'
              }
              onToggle={() => {
                if (activeStep !== 'quantity') setReopened('quantity')
                else if (quantityReady) confirmQuantity()
              }}
            >
              <form
                className="stack stack--tight"
                onSubmit={(event) => {
                  event.preventDefault()
                  confirmQuantity()
                }}
              >
                <FormGrid>
                  <Field
                    label={`Quantity received (${unit})`}
                    error={quantity !== '' && !quantityValid ? 'Enter a quantity greater than zero.' : undefined}
                  >
                    {(props) => (
                      <input
                        {...props}
                        className="input input--hero"
                        type="number"
                        step="0.001"
                        min="0"
                        inputMode="decimal"
                        data-autofocus=""
                        autoFocus
                        placeholder="0"
                        value={quantity}
                        onChange={(event) => setQuantity(event.target.value)}
                      />
                    )}
                  </Field>
                  <Field
                    label={`Purchase price per ${unit}`}
                    error={unitCost !== '' && !costValid ? 'Enter zero or more.' : undefined}
                    hint={
                      selected?.last_purchase_price
                        ? `Last paid ${formatUnitPrice(selected.last_purchase_price)}`
                        : 'No previous price on record'
                    }
                  >
                    {(props) => (
                      <input
                        {...props}
                        className="input input--hero"
                        type="number"
                        step="0.0001"
                        min="0"
                        inputMode="decimal"
                        placeholder="0.00"
                        value={unitCost}
                        onChange={(event) => setUnitCost(event.target.value)}
                      />
                    )}
                  </Field>
                  <Field label="Supplier / invoice" optional>
                    {(props) => (
                      <input {...props} value={supplierRef} onChange={(event) => setSupplierRef(event.target.value)} placeholder="Northgate Mills · INV-9912" />
                    )}
                  </Field>
                  <Field label="Note" optional>
                    {(props) => (
                      <input {...props} value={note} onChange={(event) => setNote(event.target.value)} placeholder="Lorry number, condition…" />
                    )}
                  </Field>
                </FormGrid>
                <div className="row row--end">
                  <Button type="submit" variant="primary" disabled={!quantityReady}>
                    Continue
                  </Button>
                </div>
              </form>
            </StepCard>

            {productId ? (
              <StepCard
                index={3}
                title="Assign to waiting customers"
                active={activeStep === 'allocate'}
                done={quantityValid && remainingUnits === 0 && Object.keys(rowErrors).length === 0}
                summary={
                  !data
                    ? 'Checking who is waiting…'
                    : hasWaiting
                      ? `${data.items.length} line${data.items.length === 1 ? '' : 's'} waiting · ${formatQuantity(data.unallocated_quantity)} ${unit} short`
                      : 'Nobody is waiting for this product'
                }
                flush
              >
                {preview.error ? (
                  <div className="card__body">
                    <Notice kind="error">{preview.error}</Notice>
                  </div>
                ) : preview.loading && !data ? (
                  <Loading label="Checking who is waiting…" />
                ) : !data ? null : !hasWaiting ? (
                  <EmptyState
                    compact
                    title="Nobody is waiting for this product"
                    body={quantityValid ? `All ${formatQuantity(quantity)} ${unit} go into stock.` : 'The whole receipt goes into stock.'}
                  />
                ) : (
                  <>
                    <div className="card__toolbar">
                      {quantityValid ? (
                        <>
                          {remainingUnits === 0 ? (
                            <span className="chip chip--ok">
                              <CheckIcon size={13} strokeWidth={2.6} /> Balanced
                            </span>
                          ) : remainingUnits > 0 ? (
                            <span className="chip chip--todo">{formatQuantity(fromUnits(remainingUnits))} left to assign</span>
                          ) : (
                            <span className="chip chip--over">{formatQuantity(fromUnits(-remainingUnits))} over</span>
                          )}
                          <span className="hint">of {formatQuantity(fromUnits(requiredUnits))} required</span>
                          <div className="grow" />
                          <Button size="sm" variant="plain" icon={<ResetIcon size={13} />} onClick={applyFifo} disabled={!customised}>
                            FIFO
                          </Button>
                          <Button size="sm" variant="plain" onClick={clearAll} disabled={allocatedUnits === 0}>
                            Clear
                          </Button>
                        </>
                      ) : (
                        <span className="hint">Enter a quantity to assign to these orders.</span>
                      )}
                    </div>
                    <TableScroll>
                      <table className="table">
                        <thead>
                          <tr>
                            <th className="col-shrink">#</th>
                            <th>Customer · order</th>
                            <th className="num">To deliver</th>
                            <th className="num">Short</th>
                            <th className="num">Assign</th>
                            <th className="col-effect">Effect</th>
                          </tr>
                        </thead>
                        <tbody>
                          {data.items.map((row, index) => (
                            <AllocationRow
                              key={row.order_item_id}
                              row={row}
                              index={index}
                              value={allocations[row.order_item_id] ?? '0'}
                              error={rowErrors[row.order_item_id]}
                              disabled={!quantityValid}
                              onChange={(value) => setRow(row.order_item_id, value)}
                              onMax={() => fillRowToMax(row)}
                            />
                          ))}
                        </tbody>
                      </table>
                    </TableScroll>
                    <div className="card__footer">
                      <div className="legend">
                        <span><i style={{ background: 'var(--stock-delivered)' }} /> Delivered</span>
                        <span><i style={{ background: 'var(--stock-reserved)' }} /> Ready to deliver</span>
                        <span><i style={{ background: 'var(--stock-available)' }} /> Assigning now</span>
                        <span><i style={{ background: 'var(--stock-owed)' }} /> Still waiting</span>
                      </div>
                    </div>
                  </>
                )}
              </StepCard>
            ) : null}
          </div>

          <aside className="aside-sticky">
            <Card>
              <Headline productChosen={Boolean(productId)} quantityValid={quantityValid} hasWaiting={hasWaiting} remaining={remainingUnits} required={requiredUnits} />
              {data ? (
                <div className="hide-when-docked">
                  <table className="before-after">
                    <thead>
                      <tr>
                        <th />
                        <th>Now</th>
                        <th className="arrow" />
                        <th>After</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr>
                        <td>Stock</td>
                        <td className="num"><SignedQuantity value={data.stock} /></td>
                        <td className="arrow">→</td>
                        <td className="num q-strong"><SignedQuantity value={fromUnits(afterStockUnits)} /></td>
                      </tr>
                      <tr>
                        <td>Customers waiting</td>
                        <td className="num">{formatQuantity(data.unallocated_quantity)}</td>
                        <td className="arrow">→</td>
                        <td className="num">{formatQuantity(fromUnits(Math.max(0, afterWaitingUnits)))}</td>
                      </tr>
                      {quantityValid && costValid ? (
                        <tr>
                          <td>Spend</td>
                          <td />
                          <td />
                          <td className="num q-strong">{formatMoney(totalSpend)}</td>
                        </tr>
                      ) : null}
                    </tbody>
                  </table>
                </div>
              ) : null}
              {blockers.length > 1 ? (
                <div className="card__body card__body--tight hide-when-docked">
                  <ul className="hint blocker-list">
                    {blockers.slice(1, 4).map((reason) => (
                      <li key={reason}>{reason}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
              <div className="card__footer">
                <Button variant="primary" block icon={<StockInIcon size={15} />} disabled={!canSubmit} busy={submitting} onClick={() => setConfirming(true)}>
                  Record receipt
                </Button>
              </div>
            </Card>
          </aside>
        </div>
      )}

      {confirming && data ? (
        <ConfirmDialog
          title="Record this stock receipt?"
          confirmLabel="Record receipt"
          busy={submitting}
          onCancel={() => setConfirming(false)}
          onConfirm={submit}
          icon={<StockInIcon size={19} />}
          message={
            <>
              <p>
                <strong>
                  {formatQuantity(quantity)} {data.unit_of_measure}
                </strong>{' '}
                of {data.product_name} at {formatUnitPrice(unitCost || 0)} each — {formatMoney(totalSpend)}.
              </p>
              <p>
                {allocatedUnits > 0
                  ? `${formatQuantity(fromUnits(allocatedUnits))} goes to waiting customers first; stock becomes ${formatQuantity(fromUnits(afterStockUnits))}.`
                  : `Nobody is waiting; stock becomes ${formatQuantity(fromUnits(afterStockUnits))}.`}{' '}
                Stock movements are permanent.
              </p>
            </>
          }
        />
      ) : null}
    </Page>
  )
}

function Headline({
  productChosen,
  quantityValid,
  hasWaiting,
  remaining,
  required,
}: {
  productChosen: boolean
  quantityValid: boolean
  hasWaiting: boolean
  remaining: number
  required: number
}) {
  if (!productChosen || !quantityValid) {
    return (
      <div className="summary-hero">
        <div className="summary-hero__icon" aria-hidden="true">
          <StockInIcon size={20} />
        </div>
        <div className="summary-hero__label">New receipt</div>
        <div className="summary-hero__hint">{productChosen ? 'Enter how much arrived' : 'Choose a product to begin'}</div>
      </div>
    )
  }
  if (!hasWaiting || required === 0) {
    return (
      <div className="summary-hero is-ok">
        <div className="summary-hero__label">Nobody waiting</div>
        <div className="summary-hero__value">
          <CheckIcon size={30} strokeWidth={2.6} />
        </div>
        <div className="summary-hero__hint">All of it goes into stock</div>
      </div>
    )
  }
  const state = remaining === 0 ? 'is-ok' : remaining > 0 ? 'is-todo' : 'is-over'
  return (
    <div className={`summary-hero ${state}`}>
      <div className="summary-hero__label">{remaining === 0 ? 'Ready to record' : 'Left to assign'}</div>
      <div className="summary-hero__value">
        {remaining === 0 ? <CheckIcon size={30} strokeWidth={2.6} /> : formatQuantity(fromUnits(Math.abs(remaining)))}
      </div>
      <div className="summary-hero__hint">
        {remaining === 0
          ? `${formatQuantity(fromUnits(required))} goes to waiting orders`
          : remaining > 0
            ? `${formatQuantity(fromUnits(required))} must go to waiting orders`
            : 'More than this receipt covers'}
      </div>
    </div>
  )
}

function ProductPicker({
  products,
  loading,
  error,
  search,
  onSearch,
  selectedId,
  onSelect,
}: {
  products: Product[]
  loading: boolean
  error: string | null
  search: string
  onSearch: (value: string) => void
  selectedId: string
  onSelect: (id: string) => void
}) {
  const term = search.trim().toLowerCase()
  // Products short of commitments come first: they are why this screen is open.
  const sorted = useMemo(
    () =>
      products
        .filter((product) => !term || product.sku.toLowerCase().includes(term) || product.name.toLowerCase().includes(term))
        .sort((a, b) => {
          const aShort = Number(a.stock) < 0
          const bShort = Number(b.stock) < 0
          if (aShort !== bShort) return aShort ? -1 : 1
          if (aShort && bShort) return Number(a.stock) - Number(b.stock)
          return a.name.localeCompare(b.name)
        }),
    [products, term],
  )

  if (error) return <Notice kind="error">{error}</Notice>
  if (loading && products.length === 0) return <Loading label="Loading products…" />
  if (products.length === 0) {
    return (
      <EmptyState
        compact
        icon={<ProductsIcon size={22} />}
        title="No active products"
        action={
          <LinkButton to="/products?new=1" variant="tinted">
            Add a product
          </LinkButton>
        }
      />
    )
  }

  return (
    <>
      <SearchField value={search} onChange={onSearch} placeholder="Search code or name" width="100%" label="Search products" />
      <div className="picker" role="radiogroup" aria-label="Product">
        {sorted.length === 0 ? (
          <EmptyState compact title={`Nothing matches “${search}”`} />
        ) : (
          sorted.map((product) => {
            const short = Number(product.stock) < 0
            return (
              <label key={product.id} className={`picker__row${product.id === selectedId ? ' is-selected' : ''}`}>
                <input
                  className="picker__radio"
                  type="radio"
                  name="stockin-product"
                  value={product.id}
                  checked={product.id === selectedId}
                  onChange={() => onSelect(product.id)}
                />
                <span>
                  <span className="row gap-2">
                    <span className="cell-primary">{product.name}</span>
                    {short ? <Badge tone="red">Short</Badge> : null}
                  </span>
                  <span className="cell-sub">
                    <span className="mono">{product.sku}</span> · {product.unit_of_measure}
                  </span>
                </span>
                <span className="picker__figures">
                  <span>
                    <b className={short ? 'q-negative' : undefined}>{formatQuantity(product.stock)}</b>stock
                  </span>
                </span>
              </label>
            )
          })
        )}
      </div>
    </>
  )
}

function AllocationRow({
  row,
  index,
  value,
  error,
  disabled,
  onChange,
  onMax,
}: {
  row: PendingOrderRow
  index: number
  value: string
  error?: string
  disabled: boolean
  onChange: (value: string) => void
  onMax: () => void
}) {
  const ordered = toUnits(row.quantity_ordered) || 1
  const delivered = toUnits(row.quantity_fulfilled) || 0
  const reserved = toUnits(row.quantity_reserved) || 0
  const unallocated = toUnits(row.quantity_unallocated) || 0
  const typed = Math.max(0, Math.min(toUnits(value) || 0, unallocated))
  const stillAwaiting = unallocated - typed
  const pct = (units: number) => `${(units / ordered) * 100}%`
  const age = waitingFor(row.order_created_at)

  return (
    <tr className={typed > 0 ? 'is-highlighted' : undefined}>
      <td className="col-shrink muted">{index + 1}</td>
      <td>
        <Link className="cell-link" to={`/customers/${row.customer_id}`}>
          {row.customer_name}
        </Link>
        <span className="cell-sub">
          <Link to={`/orders/${row.order_id}`} className="mono">
            {row.order_number}
          </Link>{' '}
          · <span className={age.className}>{age.label}</span>
        </span>
      </td>
      <td className="num">{formatQuantity(row.quantity_pending)}</td>
      <td className="num q-awaiting">{formatQuantity(row.quantity_unallocated)}</td>
      <td className="num">
        <div className="row row--end gap-1">
          <input
            className="input input--sm input--num input--inline"
            type="number"
            step="0.001"
            min="0"
            max={row.quantity_unallocated}
            inputMode="decimal"
            aria-label={`Assign to ${row.customer_name}, ${row.order_number}`}
            aria-invalid={error ? true : undefined}
            value={value}
            disabled={disabled}
            onChange={(event) => onChange(event.target.value)}
          />
          <Button size="sm" variant="plain" onClick={onMax} disabled={disabled} title="As much as this receipt allows">
            Max
          </Button>
        </div>
        {error ? <span className="field__error">{error}</span> : null}
      </td>
      <td>
        <span className="cell-sub">
          {typed > 0 ? (
            stillAwaiting > 0 ? (
              <>+{formatQuantity(fromUnits(typed))} · {formatQuantity(fromUnits(stillAwaiting))} still waiting</>
            ) : (
              <span className="q-available">+{formatQuantity(fromUnits(typed))} · fully covered</span>
            )
          ) : (
            'nothing assigned now'
          )}
        </span>
        <div className="bar mt-1">
          <span className="bar__delivered" style={{ width: pct(delivered) }} />
          <span className="bar__reserved" style={{ width: pct(reserved) }} />
          <span className="bar__now" style={{ width: pct(typed) }} />
          <span className="bar__owed" style={{ width: pct(stillAwaiting) }} />
        </div>
      </td>
    </tr>
  )
}

function ReceiptDone({ result, onStartOver }: { result: StockReceiptResult; onStartOver: () => void }) {
  return (
    <div className="stack">
      <Card>
        <div className="done">
          <div className="done__mark" aria-hidden="true">
            <CheckIcon size={20} strokeWidth={3} />
          </div>
          <div className="grow">
            <div className="done__title">
              <span className="mono">{result.receipt_number}</span> recorded
            </div>
            <div className="done__meta">
              {formatQuantity(result.receipt_quantity)} {result.unit_of_measure} of {result.product_name} at{' '}
              {formatUnitPrice(result.unit_cost)} · {formatDateTime(result.created_at)}
              {result.supplier_reference ? ` · ${result.supplier_reference}` : ''}
            </div>
          </div>
        </div>
      </Card>

      <StockFigures
        stock={result.stock_after}
        toDeliver={result.pending_quantity_after}
        unit={result.unit_of_measure}
      />
      <MetricStrip
        items={[
          { label: 'Spent', value: formatMoney(result.total_cost), hint: `${formatQuantity(result.receipt_quantity)} at ${formatUnitPrice(result.unit_cost)}` },
          { label: 'To waiting orders', value: formatQuantity(result.allocated_total), tone: 'reserved' },
          { label: 'Into free stock', value: formatQuantity(result.surplus_quantity), tone: 'positive' },
          { label: 'Value in warehouse', value: formatMoney(result.stock_value_after), hint: `avg ${formatUnitPrice(result.average_cost_after)}` },
        ]}
      />

      <Card title="Went to" subtitle={result.allocations.length ? undefined : 'Nobody was waiting'} flush>
        {result.allocations.length === 0 ? (
          <EmptyState compact title="Nobody was waiting" body="The whole receipt went into stock." />
        ) : (
          <TableScroll>
            <table className="table table--compact">
              <thead>
                <tr>
                  <th>Customer</th>
                  <th>Order</th>
                  <th className="num">Assigned now</th>
                  <th className="num">To deliver</th>
                  <th className="num">Still waiting</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {result.allocations.map((row) => (
                  <tr key={row.order_item_id}>
                    <td>
                      <Link className="cell-link" to={`/customers/${row.customer_id}`}>
                        {row.customer_name}
                      </Link>
                    </td>
                    <td>
                      <Link to={`/orders/${row.order_id}`} className="mono">
                        {row.order_number}
                      </Link>
                    </td>
                    <td className="num q-strong">+{formatQuantity(row.quantity_allocated)}</td>
                    <td className="num q-owed">{formatQuantity(row.quantity_pending)}</td>
                    <td className="num">
                      {Number(row.quantity_unallocated) > 0 ? <span className="q-awaiting">{formatQuantity(row.quantity_unallocated)}</span> : <span className="q-muted">—</span>}
                    </td>
                    <td>
                      {Number(row.quantity_unallocated) > 0 ? <Badge tone="red">Still short</Badge> : <Badge tone="green">Ready to deliver</Badge>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableScroll>
        )}
      </Card>

      <div className="btn-group">
        {result.allocations.length > 0 ? (
          <LinkButton to="/pending-fulfilment?filter=ready" variant="primary" icon={<DeliveryIcon size={15} />}>
            Deliver now
          </LinkButton>
        ) : null}
        <Button onClick={onStartOver}>Record another</Button>
        <LinkButton to={`/products?open=${result.product_id}`} variant="plain">
          View {result.product_sku}
        </LinkButton>
        <span className="hint">{formatAmount(result.total_cost)} added to stock value</span>
      </div>
    </div>
  )
}
