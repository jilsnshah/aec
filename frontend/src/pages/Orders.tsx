import { useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import type { Customer, Order, OrderDetail, OrderStatus, Product } from '../api/types'
import {
  Avatar,
  Badge,
  Button,
  CardFacts,
  Collection,
  Dialog,
  DialogCancel,
  EmptyState,
  ExportButton,
  Field,
  KeyValue,
  Meter,
  Notice,
  Page,
  RecordCard,
  SearchField,
  Segmented,
  SortHeader,
  StatusBadge,
  Toolbar,
  ViewSwitch,
  useRowLink,
  useToast,
  type Sort,
} from '../components/ui'
import { LineCell, LineEditor, LineRow, PartySelect, ProductSelect } from '../components/LineEditor'
import { ChevronIcon, CloseIcon, PlusIcon, SalesOrderIcon } from '../components/icons'
import { downloadCsv, fileStamp } from '../lib/csv'
import { isValidQuantity, toUnits } from '../lib/decimal'
import {
  STATUS_LABELS,
  formatAmount,
  formatDateTime,
  formatMoney,
  formatQuantity,
  formatRelative,
} from '../lib/format'
import { usePaging, useViewMode } from '../lib/paging'
import { useAsync, useDebounced } from '../lib/useAsync'
import { useCreateParam } from '../lib/useCreateParam'
import { isPositiveQuantity, isValidPercent } from '../lib/validation'

type StatusFilter = 'ALL' | OrderStatus

const STATUS_OPTIONS: { value: StatusFilter; label: string }[] = [
  { value: 'ALL', label: 'All' },
  { value: 'PENDING', label: 'Pending' },
  { value: 'PARTIALLY_FULFILLED', label: 'Partly delivered' },
  { value: 'FULFILLED', label: 'Delivered' },
  { value: 'CANCELLED', label: 'Cancelled' },
]

function sum(values: string[]) {
  return values.reduce((total, value) => total + Number(value), 0)
}

/** Order-level quantities, summed across its lines. */
function orderFigures(order: Order) {
  const ordered = sum(order.items.map((item) => item.quantity_ordered))
  const delivered = sum(order.items.map((item) => item.quantity_fulfilled))
  const reserved = sum(order.items.map((item) => item.quantity_reserved))
  const owed = sum(order.items.map((item) => item.quantity_pending))
  const awaiting = sum(order.items.map((item) => item.quantity_unallocated))
  const incoming = sum(order.items.map((item) => item.quantity_incoming))
  const cancelled = sum(order.items.map((item) => item.quantity_cancelled))
  return { ordered, delivered, reserved, owed, awaiting, incoming, cancelled }
}

function FulfilmentMeter({ order }: { order: Order }) {
  const f = orderFigures(order)
  return (
    <Meter
      total={f.ordered}
      segments={[
        { value: f.delivered, className: 'bar__delivered', label: 'Delivered' },
        { value: f.reserved, className: 'bar__reserved', label: 'Ready to deliver' },
        { value: f.incoming, className: 'bar__owed', label: 'On order' },
        { value: f.awaiting, className: 'bar__short', label: 'Short' },
        { value: f.cancelled, className: 'bar__cancelled', label: 'Cancelled' },
      ]}
    />
  )
}

function fulfilmentCaption(order: Order) {
  const f = orderFigures(order)
  if (order.status === 'CANCELLED') return 'Cancelled'
  if (f.owed === 0) return `All ${formatQuantity(String(f.delivered))} delivered`
  const parts = [`${formatQuantity(String(f.delivered))} of ${formatQuantity(String(f.ordered))} delivered`]
  if (f.awaiting > 0) parts.push(`${formatQuantity(String(f.awaiting))} short`)
  else if (f.incoming > 0) parts.push(`${formatQuantity(String(f.incoming))} on order`)
  else if (f.reserved > 0) parts.push(`${formatQuantity(String(f.reserved))} ready to deliver`)
  return parts.join(' · ')
}

export default function OrdersPage() {
  const toast = useToast()
  const navigate = useNavigate()
  const rowLink = useRowLink()
  const [params, setParams] = useSearchParams()
  const customerFilter = params.get('customer') ?? ''
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState<StatusFilter>('ALL')
  const [sort, setSort] = useState<Sort>({ by: 'created_at', dir: 'desc' })
  const debouncedSearch = useDebounced(search)
  const [creating, setCreating] = useCreateParam()
  const [view, setView] = useViewMode('orders')

  const filters = {
    search: debouncedSearch || undefined,
    status: status === 'ALL' ? undefined : status,
    customer_id: customerFilter || undefined,
  }
  const paging = usePaging('orders', [filters, sort])

  const state = useAsync(
    () =>
      api.orders.list({
        ...filters,
        sort_by: sort.by,
        sort_dir: sort.dir,
        limit: paging.limit,
        offset: paging.offset,
      }),
    [debouncedSearch, status, customerFilter, sort.by, sort.dir, paging.limit, paging.offset],
  )
  const data = state.data

  const filterName = customerFilter ? data?.items[0]?.customer.name : undefined
  const filtered = Boolean(search || status !== 'ALL')

  function clearCustomer() {
    setParams(
      (current) => {
        const next = new URLSearchParams(current)
        next.delete('customer')
        return next
      },
      { replace: true },
    )
  }

  async function exportCsv() {
    const rows = await api.orders.all({ ...filters, sort_by: sort.by, sort_dir: sort.dir })
    downloadCsv(
      `sales-orders-${fileStamp()}.csv`,
      [
        { header: 'Order', value: (order) => order.order_number },
        { header: 'Placed', value: (order) => order.created_at },
        { header: 'Customer', value: (order) => order.customer.name },
        { header: 'Status', value: (order) => STATUS_LABELS[order.status] ?? order.status },
        { header: 'Products', value: (order) => order.items.map((item) => item.product.sku).join(' ') },
        { header: 'Ordered', value: (order) => orderFigures(order).ordered },
        { header: 'Delivered', value: (order) => orderFigures(order).delivered },
        { header: 'Ready to deliver', value: (order) => orderFigures(order).reserved },
        { header: 'On order', value: (order) => orderFigures(order).incoming },
        { header: 'Short', value: (order) => orderFigures(order).awaiting },
        { header: 'To deliver', value: (order) => orderFigures(order).owed },
        { header: 'Discount', value: (order) => order.discount_amount },
        { header: 'Total', value: (order) => order.total_amount },
      ],
      rows,
    )
    toast.success('Export ready', `${rows.length} order${rows.length === 1 ? '' : 's'} downloaded as CSV.`)
  }

  return (
    <Page>
      <Toolbar
        title="Sales Orders"
        count={data?.total}
        subtitle="An order takes its stock the moment it is placed; delivery records when the truck leaves"
        actions={
          <>
            <ExportButton onExport={exportCsv} disabled={!data?.total} />
            <Button variant="primary" icon={<PlusIcon size={15} />} onClick={() => setCreating(true)}>
              New order
            </Button>
          </>
        }
      >
        <SearchField
          value={search}
          onChange={setSearch}
          placeholder="Search orders"
          label="Search orders"
        />
        <Segmented label="Status" value={status} onChange={setStatus} options={STATUS_OPTIONS} />
        {customerFilter && !creating ? (
          <Badge tone="blue" large>
            {filterName ?? 'One customer'}
            <button
              type="button"
              className="chip-close"
              aria-label="Show all customers"
              onClick={clearCustomer}
            >
              <CloseIcon size={12} />
            </button>
          </Badge>
        ) : null}
        <div className="grow" />
        <ViewSwitch value={view} onChange={setView} />
      </Toolbar>

      <Collection
        state={state}
        view={view}
        paging={paging}
        noun="orders"
        columns={7}
        empty={
          <EmptyState
            icon={<SalesOrderIcon size={22} />}
            title={filtered ? 'No orders match' : 'No sales orders yet'}
            body={
              filtered
                ? 'Try a different search or status.'
                : 'Record what a customer has asked for. Its stock is taken straight away.'
            }
            action={
              filtered ? (
                <Button
                  onClick={() => {
                    setSearch('')
                    setStatus('ALL')
                  }}
                >
                  Clear filters
                </Button>
              ) : (
                <Button variant="primary" onClick={() => setCreating(true)}>
                  New order
                </Button>
              )
            }
          />
        }
        table={(rows) => (
          <table className="table table--interactive">
            <thead>
              <tr>
                <SortHeader field="order_number" label="Order" sort={sort} onSort={setSort} />
                <th>Customer</th>
                <th>Status</th>
                <th className="col-progress">Fulfilment</th>
                <th className="num">To deliver</th>
                <SortHeader field="total_amount" label="Value" sort={sort} onSort={setSort} numeric />
                <SortHeader field="created_at" label="Placed" sort={sort} onSort={setSort} numeric />
                <th className="col-shrink" />
              </tr>
            </thead>
            <tbody>
              {rows.map((order) => {
                const f = orderFigures(order)
                return (
                  <tr key={order.id} {...rowLink(`/orders/${order.id}`)}>
                    <td>
                      <span className="cell-primary mono">{order.order_number}</span>
                      <span className="cell-sub">
                        {order.items.length} line{order.items.length === 1 ? '' : 's'}
                        {order.enquiry_id ? ' · from enquiry' : ''}
                      </span>
                    </td>
                    <td>
                      <div className="cell-identity">
                        <Avatar name={order.customer.name} seed={order.customer.id} size="sm" />
                        <div>
                          <span className="cell-primary">{order.customer.name}</span>
                          <span className="cell-sub cell-clip">
                            {order.items.map((item) => item.product.sku).join(', ')}
                          </span>
                        </div>
                      </div>
                    </td>
                    <td>
                      <StatusBadge status={order.status} />
                    </td>
                    <td className="col-progress">
                      <FulfilmentMeter order={order} />
                      <span className="cell-sub">{fulfilmentCaption(order)}</span>
                    </td>
                    <td className="num">
                      {f.owed > 0 ? (
                        <span className="q-strong">{formatQuantity(String(f.owed))}</span>
                      ) : (
                        <span className="q-muted">—</span>
                      )}
                    </td>
                    <td className="num">
                      {formatMoney(order.total_amount)}
                      {Number(order.discount_amount) > 0 ? (
                        <span className="cell-sub">−{formatAmount(order.discount_amount)}</span>
                      ) : null}
                    </td>
                    <td className="num nowrap">
                      <span title={formatDateTime(order.created_at)}>{formatRelative(order.created_at)}</span>
                    </td>
                    <td className="col-shrink">
                      <ChevronIcon size={15} className="row-chevron" aria-hidden="true" />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
        card={(order) => {
          const f = orderFigures(order)
          return (
            <RecordCard
              key={order.id}
              to={`/orders/${order.id}`}
              tone={order.status === 'CANCELLED' ? 'muted' : undefined}
              leading={<Avatar name={order.customer.name} seed={order.customer.id} />}
              title={order.customer.name}
              subtitle={
                <>
                  <span className="mono">{order.order_number}</span> · {formatRelative(order.created_at)}
                </>
              }
              badge={<StatusBadge status={order.status} />}
              footer={
                <>
                  <span className="cell-clip">
                    {order.items.length} line{order.items.length === 1 ? '' : 's'} ·{' '}
                    {order.items.map((item) => item.product.sku).join(', ')}
                  </span>
                </>
              }
            >
              <CardFacts
                items={[
                  { label: 'Value', value: formatMoney(order.total_amount) },
                  { label: 'Ordered', value: formatQuantity(String(f.ordered)) },
                  {
                    label: 'To deliver',
                    value: f.owed > 0 ? formatQuantity(String(f.owed)) : '—',
                    tone: f.owed > 0 ? undefined : 'is-muted',
                  },
                ]}
              />
              <div>
                <FulfilmentMeter order={order} />
                <div className="meter-caption">
                  <span>{fulfilmentCaption(order)}</span>
                </div>
              </div>
            </RecordCard>
          )
        }}
      />

      {creating ? (
        <OrderForm
          initialCustomerId={customerFilter}
          onClose={() => setCreating(false)}
          onCreated={(order) => {
            setCreating(false)
            const reserved = sum(order.items.map((item) => item.quantity_reserved))
            const awaiting = sum(order.items.map((item) => item.quantity_unallocated))
            const incoming = sum(order.items.map((item) => item.quantity_incoming))
            const parts = [`${formatQuantity(reserved)} ready to deliver`]
            if (incoming > 0) parts.push(`${formatQuantity(incoming)} on order`)
            if (awaiting > 0) parts.push(`${formatQuantity(awaiting)} short`)
            toast.success(
              `${order.order_number} created`,
              incoming > 0 || awaiting > 0
                ? `${parts.join(', ')}.`
                : 'All of it is in stock — ready to deliver.',
            )
            navigate(`/orders/${order.id}`)
          }}
        />
      ) : null}
    </Page>
  )
}

/* -------------------------------------------------------------------------- */

interface LineState {
  key: number
  productId: string
  quantity: string
  /** Blank means "use the product's MRP", resolved by the backend. */
  unitPrice: string
  discountPercent: string
}

let nextKey = 1
const blankLine = (): LineState => ({
  key: nextKey++,
  productId: '',
  quantity: '1',
  unitPrice: '',
  discountPercent: '0',
})

function OrderForm({
  initialCustomerId,
  onClose,
  onCreated,
}: {
  initialCustomerId?: string
  onClose: () => void
  onCreated: (order: OrderDetail) => void
}) {
  const customers = useAsync<Customer[]>(() => api.customers.all(), [])
  const products = useAsync<Product[]>(() => api.products.all(), [])

  const [customerId, setCustomerId] = useState(initialCustomerId ?? '')
  const [notes, setNotes] = useState('')
  const [lines, setLines] = useState<LineState[]>([blankLine()])
  const [touched, setTouched] = useState(false)
  const [saving, setSaving] = useState(false)
  const [serverError, setServerError] = useState<string | null>(null)

  const productsById = useMemo(
    () => new Map((products.data ?? []).map((product) => [product.id, product])),
    [products.data],
  )

  const lineErrors = lines.map((line) => {
    if (!line.productId) return 'Choose a product.'
    if (!isPositiveQuantity(line.quantity)) return 'Quantity must be more than zero.'
    if (line.unitPrice.trim() !== '' && !isValidQuantity(line.unitPrice)) return 'Price must be zero or more.'
    if (!isValidPercent(line.discountPercent)) return 'Discount must be 0–100%.'
    return null
  })
  const customerError = customerId ? null : 'Choose a customer.'
  const valid = !customerError && lineErrors.every((entry) => entry === null)

  /** Mirrors the backend's arithmetic, for a live preview only. */
  function money(line: LineState) {
    const product = productsById.get(line.productId)
    const listPrice = line.unitPrice.trim() !== '' ? Number(line.unitPrice) : Number(product?.mrp ?? 0)
    const quantity = Number(line.quantity) || 0
    const discount = Number(line.discountPercent) || 0
    const gross = listPrice * quantity
    const total = listPrice * (1 - discount / 100) * quantity
    return { gross, total, discount: gross - total }
  }
  const totals = lines.reduce(
    (acc, line) => {
      const value = money(line)
      return { gross: acc.gross + value.gross, discount: acc.discount + value.discount, total: acc.total + value.total }
    },
    { gross: 0, discount: 0, total: 0 },
  )

  function update(key: number, changes: Partial<LineState>) {
    setLines((current) => current.map((line) => (line.key === key ? { ...line, ...changes } : line)))
  }

  async function submit() {
    setTouched(true)
    if (!valid || saving) return
    setSaving(true)
    setServerError(null)
    try {
      onCreated(
        await api.orders.create({
          customer_id: customerId,
          notes: notes.trim() || null,
          items: lines.map((line) => ({
            product_id: line.productId,
            quantity_ordered: line.quantity,
            unit_price: line.unitPrice.trim() === '' ? null : line.unitPrice,
            discount_percent: line.discountPercent || '0',
          })),
        }),
      )
    } catch (cause) {
      setServerError(cause instanceof ApiError ? cause.message : String(cause))
      setSaving(false)
    }
  }

  const loadError = customers.error || products.error
  const noCustomers = !customers.loading && (customers.data?.length ?? 0) === 0
  const noProducts = !products.loading && (products.data?.length ?? 0) === 0

  return (
    <Dialog
      title="New sales order"
      subtitle="Stock is taken straight away; anything short waits for the next receipt."
      onClose={onClose}
      busy={saving}
      size="wide"
      footerLead={`${lines.length} line${lines.length === 1 ? '' : 's'} · ${formatMoney(totals.total)}`}
      footer={
        <>
          <DialogCancel />
          <Button variant="primary" onClick={submit} busy={saving} disabled={customers.loading || products.loading}>
            Create order
          </Button>
        </>
      }
    >
      <div className="stack">
        {serverError ? <Notice kind="error">{serverError}</Notice> : null}
        {loadError ? <Notice kind="error">{loadError}</Notice> : null}
        {noCustomers ? <Notice kind="info">There are no active customers yet. Add one first.</Notice> : null}
        {noProducts ? <Notice kind="info">There are no active products yet. Add one first.</Notice> : null}

        <Field label="Customer" error={touched ? customerError : undefined}>
          {(props) => (
            <PartySelect
              {...props}
              parties={customers.data ?? []}
              value={customerId}
              onChange={setCustomerId}
              disabled={customers.loading}
              placeholder="Choose a customer…"
            />
          )}
        </Field>

        <LineEditor
          columns="minmax(0, 2.4fr) 92px 116px 92px 120px 32px"
          headers={[
            { label: 'Product' },
            { label: 'Quantity', align: 'right' },
            { label: 'Price', align: 'right' },
            { label: 'Discount %', align: 'right' },
            { label: 'Line total', align: 'right' },
          ]}
          onAdd={() => setLines((current) => [...current, blankLine()])}
          addLabel="Add product"
        >
          {lines.map((line, index) => {
            const product = productsById.get(line.productId)
            const error = touched ? lineErrors[index] : null
            const value = money(line)
            // Stock as the business counts it: this order takes its units the
            // moment it is placed, so "after" can drop below zero.
            const stockAfter = product
              ? (toUnits(product.stock) - (toUnits(line.quantity) || 0)) / 1000
              : 0
            return (
              <LineRow
                key={line.key}
                canRemove={lines.length > 1}
                removeLabel={`Remove line ${index + 1}`}
                onRemove={() => setLines((current) => current.filter((entry) => entry.key !== line.key))}
                error={error}
                meta={
                  product ? (
                    <>
                      <span>
                        Stock {formatQuantity(product.stock)} {product.unit_of_measure}
                        {toUnits(line.quantity) > 0 ? <> → {formatQuantity(stockAfter)}</> : null}
                      </span>
                      {stockAfter < 0 && toUnits(line.quantity) > 0 ? (
                        <span className="q-owed">
                          {formatQuantity(-Math.max(stockAfter, -(toUnits(line.quantity) / 1000)))} short — buy more
                        </span>
                      ) : null}
                    </>
                  ) : null
                }
              >
                <LineCell label="Product">
                  <ProductSelect
                    label={`Product for line ${index + 1}`}
                    products={products.data ?? []}
                    value={line.productId}
                    invalid={Boolean(error && !line.productId)}
                    disabled={products.loading}
                    onChange={(id, chosen) => update(line.key, { productId: id, unitPrice: chosen?.mrp ?? '' })}
                  />
                </LineCell>
                <LineCell label="Quantity" align="right">
                  <input
                    className="input input--num"
                    type="number"
                    step="0.001"
                    min="0"
                    inputMode="decimal"
                    aria-label={`Quantity for line ${index + 1}`}
                    value={line.quantity}
                    onChange={(event) => update(line.key, { quantity: event.target.value })}
                  />
                </LineCell>
                <LineCell label="Price" align="right">
                  <input
                    className="input input--num"
                    type="number"
                    step="0.01"
                    min="0"
                    inputMode="decimal"
                    aria-label={`Price for line ${index + 1}`}
                    placeholder={product?.mrp ?? 'MRP'}
                    value={line.unitPrice}
                    onChange={(event) => update(line.key, { unitPrice: event.target.value })}
                  />
                </LineCell>
                <LineCell label="Discount %" align="right">
                  <input
                    className="input input--num"
                    type="number"
                    step="0.01"
                    min="0"
                    max="100"
                    inputMode="decimal"
                    aria-label={`Discount for line ${index + 1}`}
                    value={line.discountPercent}
                    onChange={(event) => update(line.key, { discountPercent: event.target.value })}
                  />
                </LineCell>
                <LineCell label="Line total" align="right">
                  <div className="line-editor__total">
                    {product ? formatAmount(value.total) : <span className="q-muted">—</span>}
                    {value.discount > 0 ? <span className="cell-sub">−{formatAmount(value.discount)}</span> : null}
                  </div>
                </LineCell>
              </LineRow>
            )
          })}
        </LineEditor>

        <div className="split">
          <div>
            <Field label="Notes" optional>
              {(props) => (
                <textarea {...props} value={notes} onChange={(event) => setNotes(event.target.value)} />
              )}
            </Field>
          </div>
          <div className="totals">
            <KeyValue
              stacked
              items={[
                { label: 'Subtotal', value: formatAmount(totals.gross) },
                {
                  label: 'Discount',
                  value: totals.discount > 0 ? <span className="q-negative">−{formatAmount(totals.discount)}</span> : '—',
                },
                { label: 'Order total', value: formatMoney(totals.total), total: true },
              ]}
            />
            <p className="hint text-right mt-1">
              Before tax · confirmed by the server on save
            </p>
          </div>
        </div>
      </div>
    </Dialog>
  )
}
