import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import type { Product, PurchaseOrder, PurchaseOrderStatus, Supplier } from '../api/types'
import {
  Avatar,
  Button,
  CardFacts,
  Collection,
  Dialog,
  DialogCancel,
  EmptyState,
  ExportButton,
  Field,
  FormGrid,
  KeyValue,
  LinkButton,
  Meter,
  Notice,
  Page,
  PurchaseStatusBadge,
  RecordCard,
  SearchField,
  Segmented,
  Toolbar,
  ViewSwitch,
  useRowLink,
  useToast,
} from '../components/ui'
import { LineCell, LineEditor, LineRow, PartySelect, ProductSelect } from '../components/LineEditor'
import { ChevronIcon, GoodsReceiptIcon, PlusIcon, PurchaseOrderIcon } from '../components/icons'
import { downloadCsv, fileStamp } from '../lib/csv'
import { isValidQuantity, toUnits } from '../lib/decimal'
import {
  PO_STATUS_LABELS,
  formatAmount,
  formatDate,
  formatMoney,
  formatQuantity,
  formatRelative,
} from '../lib/format'
import { usePaging, useViewMode } from '../lib/paging'
import { useAsync, useDebounced } from '../lib/useAsync'
import { useCreateParam } from '../lib/useCreateParam'
import { isPositiveQuantity } from '../lib/validation'
import { SettleCustomers, useSettlement } from '../components/SettleCustomers'

type StatusFilter = 'ALL' | PurchaseOrderStatus

const OPEN_STATUSES = 'ORDERED,PARTIALLY_RECEIVED'

function isOverdue(order: PurchaseOrder) {
  if (!order.can_receive || !order.expected_delivery_date) return false
  const due = new Date(order.expected_delivery_date)
  due.setHours(23, 59, 59, 999)
  return due.getTime() < Date.now()
}

function ReceivedMeter({ order }: { order: PurchaseOrder }) {
  return (
    <Meter
      total={Number(order.total_ordered)}
      segments={[{ value: Number(order.total_received), className: 'bar__now', label: 'Received' }]}
    />
  )
}

function Expected({ order }: { order: PurchaseOrder }) {
  if (!order.expected_delivery_date) return <span className="q-muted">—</span>
  return (
    <span className={isOverdue(order) ? 'q-negative' : undefined}>
      {formatDate(order.expected_delivery_date)}
      {isOverdue(order) ? ' · overdue' : ''}
    </span>
  )
}

export default function PurchaseOrdersPage() {
  const toast = useToast()
  const navigate = useNavigate()
  const rowLink = useRowLink()
  const [params] = useSearchParams()
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState<StatusFilter>('ALL')
  const debouncedSearch = useDebounced(search)
  const [creating, setCreating] = useCreateParam()
  const [view, setView] = useViewMode('purchase-orders')

  const filters = {
    search: debouncedSearch || undefined,
    status: status === 'ALL' ? undefined : status,
  }
  const paging = usePaging('purchase-orders', [filters])
  const state = useAsync(
    () => api.purchaseOrders.list({ ...filters, limit: paging.limit, offset: paging.offset }),
    [debouncedSearch, status, paging.limit, paging.offset],
  )
  const data = state.data
  // How many are still to arrive, across every page.
  const open = useAsync(() => api.purchaseOrders.list({ status: OPEN_STATUSES, limit: 1 }), [data])
  const awaiting = open.data?.total ?? 0
  const filtered = Boolean(search || status !== 'ALL')

  async function exportCsv() {
    const rows = await api.purchaseOrders.all(filters)
    downloadCsv(
      `purchase-orders-${fileStamp()}.csv`,
      [
        { header: 'PO', value: (row) => row.po_number },
        { header: 'Raised', value: (row) => row.created_at },
        { header: 'Supplier', value: (row) => row.supplier.name },
        { header: 'Status', value: (row) => PO_STATUS_LABELS[row.status] ?? row.status },
        { header: 'Expected', value: (row) => row.expected_delivery_date },
        { header: 'Ordered', value: (row) => row.total_ordered },
        { header: 'Received', value: (row) => row.total_received },
        { header: 'Remaining', value: (row) => row.total_remaining },
        { header: 'Value', value: (row) => row.total_cost },
      ],
      rows,
    )
    toast.success('Export ready', `${rows.length} purchase order${rows.length === 1 ? '' : 's'} downloaded as CSV.`)
  }

  return (
    <Page>
      <Toolbar
        title="Purchase Orders"
        count={data?.total}
        subtitle={
          awaiting > 0
            ? `${awaiting} order${awaiting === 1 ? '' : 's'} still awaiting delivery`
            : 'Placing an order adds to stock at once and settles anyone short'
        }
        actions={
          <>
            <ExportButton onExport={exportCsv} disabled={!data?.total} />
            <LinkButton to="/goods-receipts" icon={<GoodsReceiptIcon size={15} />}>
              Receive goods
            </LinkButton>
            <Button variant="primary" icon={<PlusIcon size={15} />} onClick={() => setCreating(true)}>
              New purchase order
            </Button>
          </>
        }
      >
        <SearchField
          value={search}
          onChange={setSearch}
          placeholder="Search purchase orders"
          label="Search purchase orders"
        />
        <Segmented
          label="Status"
          value={status}
          onChange={setStatus}
          options={[
            { value: 'ALL', label: 'All' },
            { value: 'DRAFT', label: 'Draft' },
            { value: 'ORDERED', label: 'Ordered' },
            { value: 'PARTIALLY_RECEIVED', label: 'Part received' },
            { value: 'RECEIVED', label: 'Received' },
            { value: 'CANCELLED', label: 'Cancelled' },
          ]}
        />
        <div className="grow" />
        <ViewSwitch value={view} onChange={setView} />
      </Toolbar>

      <Collection
        state={state}
        view={view}
        paging={paging}
        noun="purchase orders"
        columns={7}
        empty={
          <EmptyState
            icon={<PurchaseOrderIcon size={22} />}
            title={filtered ? 'No purchase orders match' : 'No purchase orders yet'}
            body={
              filtered
                ? 'Try a different search or status.'
                : 'Raise a purchase order when you need to buy stock from a supplier.'
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
                  New purchase order
                </Button>
              )
            }
          />
        }
        table={(rows) => (
          <table className="table table--interactive">
            <thead>
              <tr>
                <th>Order</th>
                <th>Supplier</th>
                <th>Status</th>
                <th className="col-progress">Received</th>
                <th>Expected</th>
                <th className="num">Value</th>
                <th className="col-actions" />
              </tr>
            </thead>
            <tbody>
              {rows.map((order) => (
                <tr
                  key={order.id}
                  className={order.status === 'CANCELLED' ? 'is-muted' : undefined}
                  {...rowLink(`/purchase-orders/${order.id}`)}
                >
                  <td>
                    <span className="cell-primary mono">{order.po_number}</span>
                    <span className="cell-sub">Raised {formatRelative(order.created_at)}</span>
                  </td>
                  <td>
                    <div className="cell-identity">
                      <Avatar name={order.supplier.name} seed={order.supplier.id} square size="sm" />
                      <div>
                        <span className="cell-primary">{order.supplier.name}</span>
                        <span className="cell-sub cell-clip">
                          {order.items.map((item) => item.product.sku).join(', ')}
                        </span>
                      </div>
                    </div>
                  </td>
                  <td>
                    <PurchaseStatusBadge status={order.status} />
                  </td>
                  <td className="col-progress">
                    <ReceivedMeter order={order} />
                    <span className="cell-sub">
                      {formatQuantity(order.total_received)} of {formatQuantity(order.total_ordered)}
                      {Number(order.total_remaining) > 0 && order.status !== 'CANCELLED'
                        ? ` · ${formatQuantity(order.total_remaining)} to come`
                        : ''}
                    </span>
                  </td>
                  <td className="nowrap">
                    <Expected order={order} />
                  </td>
                  <td className="num">{formatAmount(order.total_cost)}</td>
                  <td className="col-actions">
                    <div className="row row--end gap-2">
                      {order.can_receive ? (
                        <LinkButton size="sm" variant="tinted" to={`/goods-receipts?po=${order.id}`}>
                          Receive
                        </LinkButton>
                      ) : null}
                      <ChevronIcon size={15} className="row-chevron" aria-hidden="true" />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        card={(order) => (
          <RecordCard
            key={order.id}
            to={`/purchase-orders/${order.id}`}
            tone={order.status === 'CANCELLED' ? 'muted' : isOverdue(order) ? 'alert' : undefined}
            leading={<Avatar name={order.supplier.name} seed={order.supplier.id} square />}
            title={order.supplier.name}
            subtitle={
              <>
                <span className="mono">{order.po_number}</span> · {formatRelative(order.created_at)}
              </>
            }
            badge={<PurchaseStatusBadge status={order.status} />}
            footer={
              <>
                <span className="nowrap">
                  Expected <Expected order={order} />
                </span>
                <span className="grow" />
                {order.can_receive ? (
                  <LinkButton size="sm" variant="tinted" to={`/goods-receipts?po=${order.id}`}>
                    Receive
                  </LinkButton>
                ) : null}
              </>
            }
          >
            <CardFacts
              items={[
                { label: 'Value', value: formatMoney(order.total_cost) },
                { label: 'Ordered', value: formatQuantity(order.total_ordered) },
                {
                  label: 'To come',
                  value:
                    Number(order.total_remaining) > 0 && order.status !== 'CANCELLED'
                      ? formatQuantity(order.total_remaining)
                      : '—',
                  tone: Number(order.total_remaining) > 0 && order.status !== 'CANCELLED' ? undefined : 'is-muted',
                },
              ]}
            />
            <div>
              <ReceivedMeter order={order} />
              <div className="meter-caption">
                <span>
                  {formatQuantity(order.total_received)} of {formatQuantity(order.total_ordered)} received
                </span>
                <span>{order.item_count} line{order.item_count === 1 ? '' : 's'}</span>
              </div>
            </div>
          </RecordCard>
        )}
      />

      {creating ? (
        <PurchaseOrderForm
          initialSupplierId={params.get('supplier') ?? ''}
          onClose={() => setCreating(false)}
          onCreated={(order) => {
            setCreating(false)
            toast.success(
              `${order.po_number} ${order.status === 'DRAFT' ? 'saved as a draft' : 'placed'}`,
              order.status === 'DRAFT' ? 'Place it with the supplier when ready.' : 'Receive the goods when they arrive.',
            )
            navigate(`/purchase-orders/${order.id}`)
          }}
        />
      ) : null}
    </Page>
  )
}

interface LineState {
  key: number
  productId: string
  quantity: string
  unitCost: string
}

let nextKey = 1
const blankLine = (): LineState => ({ key: nextKey++, productId: '', quantity: '1', unitCost: '' })

/** The new purchase order form. Other screens open it prefilled -- e.g.
 *  Fulfilment's "Buy" passes the short product, the quantity and who to
 *  settle -- and everything stays editable. */
export function PurchaseOrderForm({
  initialSupplierId,
  initialLines,
  initialSettlement,
  subtitle,
  onClose,
  onCreated,
}: {
  initialSupplierId?: string
  initialLines?: { productId: string; quantity: string }[]
  /** product id -> sales order line id -> quantity to settle */
  initialSettlement?: Record<string, Record<string, string>>
  subtitle?: string
  onClose: () => void
  onCreated: (order: PurchaseOrder) => void
}) {
  const suppliers = useAsync<Supplier[]>(() => api.suppliers.all(), [])
  const products = useAsync<Product[]>(() => api.products.all(), [])
  const [supplierId, setSupplierId] = useState(initialSupplierId ?? '')
  const [expected, setExpected] = useState('')
  const [notes, setNotes] = useState('')
  const [lines, setLines] = useState<LineState[]>(() =>
    initialLines?.length
      ? initialLines.map((line) => ({ ...blankLine(), productId: line.productId, quantity: line.quantity }))
      : [blankLine()],
  )
  // Prefilled lines take the last price paid once the products have loaded.
  useEffect(() => {
    if (!products.data) return
    setLines((current) =>
      current.map((line) =>
        line.productId && line.unitCost === ''
          ? { ...line, unitCost: products.data?.find((product) => product.id === line.productId)?.last_purchase_price ?? '' }
          : line,
      ),
    )
  }, [products.data])
  const [touched, setTouched] = useState(false)
  const [saving, setSaving] = useState<'draft' | 'order' | null>(null)
  const [serverError, setServerError] = useState<string | null>(null)

  const productsById = useMemo(
    () => new Map((products.data ?? []).map((product) => [product.id, product])),
    [products.data],
  )

  const lineErrors = lines.map((line) => {
    if (!line.productId) return 'Choose a product.'
    if (!isPositiveQuantity(line.quantity)) return 'Quantity must be more than zero.'
    if (line.unitCost.trim() !== '' && !isValidQuantity(line.unitCost)) return 'Cost must be zero or more.'
    return null
  })
  const supplierError = supplierId ? null : 'Choose a supplier.'
  const valid = !supplierError && lineErrors.every((entry) => entry === null)
  // Placing the order settles customers who are short; the user picks who.
  const settlement = useSettlement(
    lines.map((line) => ({ productId: line.productId, quantity: line.quantity })),
    initialSettlement,
  )
  const total = lines.reduce((sum, line) => sum + (Number(line.quantity) || 0) * (Number(line.unitCost) || 0), 0)

  function update(key: number, changes: Partial<LineState>) {
    setLines((current) => current.map((line) => (line.key === key ? { ...line, ...changes } : line)))
  }

  async function submit(confirm: boolean) {
    setTouched(true)
    if (!valid || saving) return
    // The footer already says what is left to settle.
    if (confirm && settlement.blockers.length > 0) return
    setSaving(confirm ? 'order' : 'draft')
    setServerError(null)
    try {
      onCreated(
        await api.purchaseOrders.create({
          supplier_id: supplierId,
          expected_delivery_date: expected ? new Date(expected).toISOString() : null,
          notes: notes.trim() || null,
          confirm,
          settlements: confirm ? settlement.settlements() : undefined,
          items: lines.map((line) => ({
            product_id: line.productId,
            quantity_ordered: line.quantity,
            unit_cost: line.unitCost || '0',
          })),
        }),
      )
    } catch (cause) {
      setServerError(cause instanceof ApiError ? cause.message : String(cause))
      setSaving(null)
    }
  }

  const loading = suppliers.loading || products.loading

  return (
    <Dialog
      title="New purchase order"
      subtitle={
        subtitle ??
        'Placing the order adds it to stock straight away and settles anyone who is short. A draft changes nothing.'
      }
      onClose={onClose}
      busy={Boolean(saving)}
      size="wide"
      footerLead={settlement.blockers[0] ?? `Expected value ${formatMoney(total)}`}
      footer={
        <>
          <DialogCancel />
          <Button onClick={() => submit(false)} busy={saving === 'draft'} disabled={loading || saving === 'order'}>
            Save draft
          </Button>
          <Button variant="primary" onClick={() => submit(true)} busy={saving === 'order'} disabled={loading || saving === 'draft'}>
            Place order
          </Button>
        </>
      }
    >
      <div className="stack">
        {serverError ? <Notice kind="error">{serverError}</Notice> : null}
        {suppliers.error || products.error ? <Notice kind="error">{suppliers.error || products.error}</Notice> : null}
        {!suppliers.loading && (suppliers.data?.length ?? 0) === 0 ? (
          <Notice kind="info">There are no active suppliers yet. Add one first.</Notice>
        ) : null}

        <FormGrid>
          <Field label="Supplier" error={touched ? supplierError : undefined}>
            {(props) => (
              <PartySelect
                {...props}
                parties={suppliers.data ?? []}
                value={supplierId}
                onChange={setSupplierId}
                disabled={suppliers.loading}
                placeholder="Choose a supplier…"
              />
            )}
          </Field>
          <Field label="Expected delivery" optional>
            {(props) => (
              <input {...props} type="date" value={expected} onChange={(event) => setExpected(event.target.value)} />
            )}
          </Field>
        </FormGrid>

        <LineEditor
          columns="minmax(0, 2.6fr) 104px 128px 128px 32px"
          headers={[
            { label: 'Product' },
            { label: 'Quantity', align: 'right' },
            { label: 'Cost per unit', align: 'right' },
            { label: 'Line cost', align: 'right' },
          ]}
          onAdd={() => setLines((current) => [...current, blankLine()])}
          addLabel="Add product"
        >
          {lines.map((line, index) => {
            const product = productsById.get(line.productId)
            const error = touched ? lineErrors[index] : null
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
                      {/* A confirmed purchase counts as stock at once, and
                          settles whoever is short, oldest order first. */}
                      <span>
                        Stock{' '}
                        <span className={Number(product.stock) < 0 ? 'q-negative' : undefined}>
                          {formatQuantity(product.stock)}
                        </span>
                        {toUnits(line.quantity) > 0 ? (
                          <> → {formatQuantity((toUnits(product.stock) + toUnits(line.quantity)) / 1000)}</>
                        ) : null}
                      </span>
                      {Number(product.stock) < 0 ? (
                        <span className="q-awaiting">
                          {toUnits(line.quantity) > 0
                            ? `settles ${formatQuantity(
                                Math.min(toUnits(line.quantity), -toUnits(product.stock)) / 1000,
                              )} of ${formatQuantity(String(-Number(product.stock)))} short`
                            : `${formatQuantity(String(-Number(product.stock)))} short`}
                        </span>
                      ) : null}
                      {product.last_purchase_price ? <span>last paid {formatAmount(product.last_purchase_price)}</span> : null}
                    </>
                  ) : null
                }
              >
                <LineCell label="Product">
                  <ProductSelect
                    label={`Product for line ${index + 1}`}
                    products={products.data ?? []}
                    value={line.productId}
                    disabled={products.loading}
                    invalid={Boolean(error && !line.productId)}
                    exclude={lines.filter((entry) => entry.key !== line.key).map((entry) => entry.productId)}
                    onChange={(id, chosen) => update(line.key, { productId: id, unitCost: chosen?.last_purchase_price ?? '' })}
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
                <LineCell label="Cost per unit" align="right">
                  <input
                    className="input input--num"
                    type="number"
                    step="0.0001"
                    min="0"
                    inputMode="decimal"
                    aria-label={`Cost per unit for line ${index + 1}`}
                    placeholder="0.00"
                    value={line.unitCost}
                    onChange={(event) => update(line.key, { unitCost: event.target.value })}
                  />
                </LineCell>
                <LineCell label="Line cost" align="right">
                  <div className="line-editor__total">
                    {product ? formatAmount((Number(line.quantity) || 0) * (Number(line.unitCost) || 0)) : <span className="q-muted">—</span>}
                  </div>
                </LineCell>
              </LineRow>
            )
          })}
        </LineEditor>

        <SettleCustomers settlement={settlement} />

        <div className="split">
          <div>
            <Field label="Notes" optional>
              {(props) => (
                <textarea
                  {...props}
                  value={notes}
                  onChange={(event) => setNotes(event.target.value)}
                  placeholder="Delivery instructions, agreed terms…"
                />
              )}
            </Field>
          </div>
          <div className="totals">
            <KeyValue stacked items={[{ label: 'Expected value', value: formatMoney(total), total: true }]} />
          </div>
        </div>
      </div>
    </Dialog>
  )
}
