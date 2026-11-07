import { useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import type { Customer, Enquiry, EnquiryStatus, Product } from '../api/types'
import {
  Avatar,
  Button,
  CardFacts,
  Collection,
  Dialog,
  DialogCancel,
  EmptyState,
  EnquiryStatusBadge,
  EnquirySourceBadge,
  ExportButton,
  Field,
  KeyValue,
  Notice,
  Page,
  RecordCard,
  SearchField,
  Segmented,
  Toolbar,
  ViewSwitch,
  useRowLink,
  useToast,
} from '../components/ui'
import { LineCell, LineEditor, LineRow, PartySelect, ProductSelect } from '../components/LineEditor'
import { ChevronIcon, EnquiryIcon, PlusIcon } from '../components/icons'
import { downloadCsv, fileStamp } from '../lib/csv'
import {
  ENQUIRY_STATUS_LABELS,
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

type StatusFilter = 'ALL' | EnquiryStatus

function discountShare(enquiry: Enquiry) {
  const mrp = Number(enquiry.mrp_total)
  return mrp > 0 ? (Number(enquiry.discount_total) / mrp) * 100 : 0
}

export default function EnquiriesPage() {
  const toast = useToast()
  const navigate = useNavigate()
  const rowLink = useRowLink()
  const [params] = useSearchParams()
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState<StatusFilter>('ALL')
  const debouncedSearch = useDebounced(search)
  const [creating, setCreating] = useCreateParam()
  const [view, setView] = useViewMode('enquiries')

  const filters = {
    search: debouncedSearch || undefined,
    status: status === 'ALL' ? undefined : status,
  }
  const paging = usePaging('enquiries', [filters])
  const state = useAsync(
    () => api.enquiries.list({ ...filters, limit: paging.limit, offset: paging.offset }),
    [debouncedSearch, status, paging.limit, paging.offset],
  )
  const data = state.data
  const filtered = Boolean(search || status !== 'ALL')

  async function exportCsv() {
    const rows = await api.enquiries.all(filters)
    downloadCsv(
      `enquiries-${fileStamp()}.csv`,
      [
        { header: 'Enquiry', value: (row) => row.enquiry_number },
        { header: 'Opened', value: (row) => row.created_at },
        { header: 'Customer', value: (row) => row.customer.name },
        { header: 'Status', value: (row) => ENQUIRY_STATUS_LABELS[row.status] ?? row.status },
        { header: 'Products', value: (row) => row.items.map((item) => item.product.sku).join(' ') },
        { header: 'At MRP', value: (row) => row.mrp_total },
        { header: 'Discount', value: (row) => row.discount_total },
        { header: 'Deal value', value: (row) => row.total_amount },
        { header: 'Sales order', value: (row) => row.sales_order_number },
        { header: 'Lost reason', value: (row) => row.lost_reason },
      ],
      rows,
    )
    toast.success('Export ready', `${rows.length} enquir${rows.length === 1 ? 'y' : 'ies'} downloaded as CSV.`)
  }

  return (
    <Page>
      <Toolbar
        title="Enquiries"
        count={data?.total}
        subtitle="Negotiate a discount per product, then close the deal into an order"
        actions={
          <>
            <ExportButton onExport={exportCsv} disabled={!data?.total} />
            <Button variant="primary" icon={<PlusIcon size={15} />} onClick={() => setCreating(true)}>
              New enquiry
            </Button>
          </>
        }
      >
        <SearchField
          value={search}
          onChange={setSearch}
          placeholder="Search enquiries"
          label="Search enquiries"
        />
        <Segmented
          label="Status"
          value={status}
          onChange={setStatus}
          options={[
            { value: 'ALL', label: 'All' },
            { value: 'OPEN', label: 'Open' },
            { value: 'CONVERTED', label: 'Won' },
            { value: 'LOST', label: 'Lost' },
          ]}
        />
        <div className="grow" />
        <ViewSwitch value={view} onChange={setView} />
      </Toolbar>

      <Collection
        state={state}
        view={view}
        paging={paging}
        noun="enquiries"
        columns={6}
        empty={
          <EmptyState
            icon={<EnquiryIcon size={22} />}
            title={filtered ? 'No enquiries match' : 'No enquiries yet'}
            body={
              filtered
                ? 'Try a different search or status.'
                : 'When a customer asks for something, start an enquiry to price it.'
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
                  New enquiry
                </Button>
              )
            }
          />
        }
        table={(rows) => (
          <table className="table table--interactive">
            <thead>
              <tr>
                <th>Enquiry</th>
                <th>Customer</th>
                <th>Status</th>
                <th className="num">Products</th>
                <th className="num">Discount</th>
                <th className="num">Deal value</th>
                <th className="num">Opened</th>
                <th className="col-shrink" />
              </tr>
            </thead>
            <tbody>
              {rows.map((enquiry) => (
                <tr
                  key={enquiry.id}
                  className={enquiry.status === 'LOST' ? 'is-muted' : undefined}
                  {...rowLink(`/enquiries/${enquiry.id}`)}
                >
                  <td>
                    <span className="row gap-2">
                      <span className="cell-primary mono">{enquiry.enquiry_number}</span>
                      <EnquirySourceBadge source={enquiry.source} detail={enquiry.source_detail} />
                    </span>
                    {enquiry.sales_order_number ? (
                      <span className="cell-sub">
                        became{' '}
                        <Link to={`/orders/${enquiry.sales_order_id}`} className="mono">
                          {enquiry.sales_order_number}
                        </Link>
                      </span>
                    ) : null}
                  </td>
                  <td>
                    <div className="cell-identity">
                      <Avatar name={enquiry.customer.name} seed={enquiry.customer.id} size="sm" />
                      <div>
                        <span className="cell-primary">{enquiry.customer.name}</span>
                        <span className="cell-sub cell-clip">
                          {enquiry.items.map((item) => item.product.sku).join(', ')}
                        </span>
                      </div>
                    </div>
                  </td>
                  <td>
                    <EnquiryStatusBadge status={enquiry.status} />
                  </td>
                  <td className="num">{enquiry.item_count}</td>
                  <td className="num">
                    {Number(enquiry.discount_total) > 0 ? (
                      <>
                        −{formatAmount(enquiry.discount_total)}
                        <span className="cell-sub">{discountShare(enquiry).toFixed(1)}% off MRP</span>
                      </>
                    ) : (
                      <span className="q-muted">—</span>
                    )}
                  </td>
                  <td className="num q-strong">{formatMoney(enquiry.total_amount)}</td>
                  <td className="num nowrap">
                    <span title={formatDateTime(enquiry.created_at)}>{formatRelative(enquiry.created_at)}</span>
                  </td>
                  <td className="col-shrink">
                    <ChevronIcon size={15} className="row-chevron" aria-hidden="true" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        card={(enquiry) => (
          <RecordCard
            key={enquiry.id}
            to={`/enquiries/${enquiry.id}`}
            tone={enquiry.status === 'LOST' ? 'muted' : undefined}
            leading={<Avatar name={enquiry.customer.name} seed={enquiry.customer.id} />}
            title={enquiry.customer.name}
            subtitle={
              <>
                <span className="mono">{enquiry.enquiry_number}</span> · {formatRelative(enquiry.created_at)}{' '}
                <EnquirySourceBadge source={enquiry.source} detail={enquiry.source_detail} />
              </>
            }
            badge={<EnquiryStatusBadge status={enquiry.status} />}
            footer={
              enquiry.sales_order_number ? (
                <span>
                  Became <span className="mono">{enquiry.sales_order_number}</span>
                </span>
              ) : enquiry.status === 'LOST' ? (
                <span className="cell-clip">{enquiry.lost_reason || 'Marked lost'}</span>
              ) : (
                <span className="cell-clip">{enquiry.items.map((item) => item.product.sku).join(', ')}</span>
              )
            }
          >
            <CardFacts
              items={[
                { label: 'Deal value', value: formatMoney(enquiry.total_amount) },
                { label: 'Products', value: enquiry.item_count },
                {
                  label: 'Discount',
                  value: Number(enquiry.discount_total) > 0 ? `${discountShare(enquiry).toFixed(1)}%` : '—',
                  tone: Number(enquiry.discount_total) > 0 ? undefined : 'is-muted',
                },
              ]}
            />
          </RecordCard>
        )}
      />

      {creating ? (
        <EnquiryForm
          initialCustomerId={params.get('customer') ?? ''}
          onClose={() => setCreating(false)}
          onCreated={(enquiry) => {
            setCreating(false)
            toast.success(`${enquiry.enquiry_number} opened`, 'Set discounts, then close the deal.')
            navigate(`/enquiries/${enquiry.id}`)
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
  discountPercent: string
}

let nextKey = 1
const blankLine = (): LineState => ({ key: nextKey++, productId: '', quantity: '1', discountPercent: '0' })

function EnquiryForm({
  initialCustomerId,
  onClose,
  onCreated,
}: {
  initialCustomerId?: string
  onClose: () => void
  onCreated: (enquiry: Enquiry) => void
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
    if (!isValidPercent(line.discountPercent)) return 'Discount must be 0–100%.'
    return null
  })
  const customerError = customerId ? null : 'Choose a customer.'
  const valid = !customerError && lineErrors.every((entry) => entry === null)

  function value(line: LineState) {
    const mrp = Number(productsById.get(line.productId)?.mrp ?? 0)
    const quantity = Number(line.quantity) || 0
    const price = mrp * (1 - (Number(line.discountPercent) || 0) / 100)
    return { mrp, price, gross: mrp * quantity, total: price * quantity }
  }
  const totals = lines.reduce(
    (acc, line) => {
      const v = value(line)
      return { gross: acc.gross + v.gross, total: acc.total + v.total }
    },
    { gross: 0, total: 0 },
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
        await api.enquiries.create({
          customer_id: customerId,
          notes: notes.trim() || null,
          items: lines.map((line) => ({
            product_id: line.productId,
            quantity: line.quantity,
            discount_percent: line.discountPercent || '0',
          })),
        }),
      )
    } catch (cause) {
      setServerError(cause instanceof ApiError ? cause.message : String(cause))
      setSaving(false)
    }
  }

  return (
    <Dialog
      title="New enquiry"
      subtitle="MRP comes from the product master. Negotiate with the discount."
      onClose={onClose}
      busy={saving}
      size="wide"
      footerLead={`${formatMoney(totals.total)} before tax`}
      footer={
        <>
          <DialogCancel />
          <Button variant="primary" onClick={submit} busy={saving} disabled={customers.loading || products.loading}>
            Open enquiry
          </Button>
        </>
      }
    >
      <div className="stack">
        {serverError ? <Notice kind="error">{serverError}</Notice> : null}
        {customers.error || products.error ? (
          <Notice kind="error">{customers.error || products.error}</Notice>
        ) : null}

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
          columns="minmax(0, 2.4fr) 104px 92px 92px 120px 32px"
          headers={[
            { label: 'Product' },
            { label: 'MRP', align: 'right' },
            { label: 'Quantity', align: 'right' },
            { label: 'Discount %', align: 'right' },
            { label: 'Line total', align: 'right' },
          ]}
          onAdd={() => setLines((current) => [...current, blankLine()])}
          addLabel="Add product"
        >
          {lines.map((line, index) => {
            const product = productsById.get(line.productId)
            const v = value(line)
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
                    <span>
                      Stock {formatQuantity(product.stock)} {product.unit_of_measure}
                    </span>
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
                    onChange={(id) => update(line.key, { productId: id })}
                  />
                </LineCell>
                <LineCell label="MRP" align="right">
                  <div className="num muted">
                    {product ? formatAmount(product.mrp) : '—'}
                  </div>
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
                    {product ? formatAmount(v.total) : <span className="q-muted">—</span>}
                    {product && Number(line.discountPercent) > 0 ? (
                      <span className="cell-sub">{formatAmount(v.price)} each</span>
                    ) : null}
                  </div>
                </LineCell>
              </LineRow>
            )
          })}
        </LineEditor>

        <div className="split">
          <div>
            <Field label="Notes" optional hint="Anything else the customer asked for">
              {(props) => (
                <textarea
                  {...props}
                  value={notes}
                  onChange={(event) => setNotes(event.target.value)}
                  placeholder="Delivery in two batches. Call before dispatch."
                />
              )}
            </Field>
          </div>
          <div className="totals">
            <KeyValue
              stacked
              items={[
                { label: 'At MRP', value: formatAmount(totals.gross) },
                {
                  label: 'Discount',
                  value:
                    totals.gross - totals.total > 0 ? (
                      <span className="q-negative">−{formatAmount(totals.gross - totals.total)}</span>
                    ) : (
                      '—'
                    ),
                },
                { label: 'Enquiry total', value: formatMoney(totals.total), total: true },
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
