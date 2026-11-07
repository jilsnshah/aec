import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import type { Enquiry, EnquiryConversionResult, Product } from '../api/types'
import {
  ActionMenu,
  AsyncBlock,
  Button,
  Card,
  CardBody,
  ConfirmDialog,
  Dialog,
  DialogCancel,
  EmptyState,
  EnquiryStatusBadge,
  KeyValue,
  LinkButton,
  Loading,
  Notice,
  Page,
  Quantity,
  SearchField,
  StatusBadge,
  TableScroll,
  Toolbar,
  useToast,
} from '../components/ui'
import {
  CheckIcon,
  CloseIcon,
  LostIcon,
  PlusIcon,
  SalesOrderIcon,
} from '../components/icons'
import { isValidQuantity, toUnits } from '../lib/decimal'
import {
  formatAmount,
  formatDateTime,
  formatMoney,
  formatPercent,
  formatQuantity,
  formatUnitPrice,
} from '../lib/format'
import { useAsync } from '../lib/useAsync'
import { isValidPercent } from '../lib/validation'

interface DraftLine {
  key: string
  productId: string
  sku: string
  name: string
  unit: string
  mrp: string
  quantity: string
  discountPercent: string
}

function toDraft(enquiry: Enquiry): DraftLine[] {
  return enquiry.items.map((item) => ({
    key: item.id,
    productId: item.product_id,
    sku: item.product.sku,
    name: item.product.name,
    unit: item.product.unit_of_measure,
    mrp: item.mrp_snapshot,
    quantity: item.quantity,
    discountPercent: item.discount_percent,
  }))
}

export default function EnquiryDetailPage() {
  const { enquiryId = '' } = useParams()
  const toast = useToast()
  const { data, loading, error, reload } = useAsync(() => api.enquiries.get(enquiryId), [enquiryId])

  const [draft, setDraft] = useState<DraftLine[]>([])
  const [notes, setNotes] = useState('')
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState<'convert' | 'lost' | null>(null)
  const [converted, setConverted] = useState<EnquiryConversionResult | null>(null)
  const [adding, setAdding] = useState(false)

  useEffect(() => {
    if (!data) return
    setDraft(toDraft(data))
    setNotes(data.notes ?? '')
    setDirty(false)
  }, [data])

  const editable = Boolean(data?.is_editable) && !converted

  const lineErrors = draft.map((line) => {
    if (!isValidQuantity(line.quantity) || toUnits(line.quantity) <= 0) return 'Quantity must be more than zero.'
    if (!isValidPercent(line.discountPercent)) return 'Discount must be 0–100%.'
    return null
  })
  const hasErrors = lineErrors.some(Boolean)

  function money(line: DraftLine) {
    const mrp = Number(line.mrp) || 0
    const quantity = Number(line.quantity) || 0
    const price = mrp * (1 - (Number(line.discountPercent) || 0) / 100)
    return { price, gross: mrp * quantity, total: price * quantity }
  }
  const totals = draft.reduce(
    (acc, line) => {
      const value = money(line)
      return { gross: acc.gross + value.gross, total: acc.total + value.total }
    },
    { gross: 0, total: 0 },
  )

  function updateLine(key: string, changes: Partial<DraftLine>) {
    setDirty(true)
    setDraft((current) => current.map((line) => (line.key === key ? { ...line, ...changes } : line)))
  }

  function addProduct(product: Product) {
    setAdding(false)
    setDirty(true)
    setDraft((current) => [
      ...current,
      {
        key: `new-${product.id}`,
        productId: product.id,
        sku: product.sku,
        name: product.name,
        unit: product.unit_of_measure,
        mrp: product.mrp,
        quantity: '1',
        discountPercent: '0',
      },
    ])
  }

  async function save() {
    if (!data || saving || hasErrors || draft.length === 0) return
    setSaving(true)
    setActionError(null)
    try {
      await api.enquiries.update(data.id, {
        notes: notes.trim() || null,
        items: draft.map((line) => ({
          product_id: line.productId,
          quantity: line.quantity,
          discount_percent: line.discountPercent || '0',
        })),
      })
      toast.success('Enquiry saved', 'Prices recalculated by the server.')
      reload()
    } catch (cause) {
      setActionError(cause instanceof ApiError ? cause.message : String(cause))
    } finally {
      setSaving(false)
    }
  }

  async function convert() {
    if (!data || saving) return
    setSaving(true)
    setActionError(null)
    try {
      const result = await api.enquiries.convert(data.id)
      setConverted(result)
      setConfirming(null)
      toast.success(`${result.order.order_number} created`, `From ${result.enquiry.enquiry_number}`)
      reload()
    } catch (cause) {
      setActionError(cause instanceof ApiError ? cause.message : String(cause))
      setConfirming(null)
    } finally {
      setSaving(false)
    }
  }

  async function markLost(reason: string) {
    if (!data || saving) return
    setSaving(true)
    setActionError(null)
    try {
      await api.enquiries.markLost(data.id, reason || undefined)
      setConfirming(null)
      toast.info(`${data.enquiry_number} marked lost`, 'No order was created and no stock moved.')
      reload()
    } catch (cause) {
      setActionError(cause instanceof ApiError ? cause.message : String(cause))
      setConfirming(null)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Page>
      <Toolbar
        back={{ to: '/enquiries', label: 'Enquiries' }}
        title={<span className="mono">{data?.enquiry_number ?? 'Enquiry'}</span>}
        documentTitle={data?.enquiry_number ?? 'Enquiry'}
        badge={data ? <EnquiryStatusBadge status={data.status} /> : undefined}
        subtitle={
          data ? (
            <>
              <Link to={`/customers/${data.customer_id}`}>{data.customer.name}</Link> · opened{' '}
              {formatDateTime(data.created_at)}
            </>
          ) : undefined
        }
        actions={
          editable ? (
            <>
              {dirty ? (
                <Button onClick={save} busy={saving} disabled={hasErrors || draft.length === 0}>
                  Save changes
                </Button>
              ) : null}
              <Button
                variant="primary"
                icon={<CheckIcon size={15} />}
                onClick={() => setConfirming('convert')}
                disabled={saving || dirty || hasErrors || draft.length === 0}
                title={dirty ? 'Save your changes first' : undefined}
              >
                Close deal
              </Button>
              <ActionMenu
                variant="secondary"
                size="md"
                label="More enquiry actions"
                items={[
                  {
                    label: 'Mark as lost',
                    icon: <LostIcon size={15} />,
                    destructive: true,
                    onSelect: () => setConfirming('lost'),
                  },
                ]}
              />
            </>
          ) : data?.sales_order_id ? (
            <LinkButton to={`/orders/${data.sales_order_id}`} variant="primary" icon={<SalesOrderIcon size={15} />}>
              Open {data.sales_order_number}
            </LinkButton>
          ) : undefined
        }
      />

      <AsyncBlock loading={loading} error={error} data={data} onRetry={reload} skeleton="spinner">
        {(enquiry) => (
          <div className="stack">
            {actionError ? (
              <Notice kind="error" title="That did not go through">
                {actionError}
              </Notice>
            ) : null}

            {converted ? <ConversionSummary result={converted} /> : null}

            {!enquiry.is_editable && !converted ? (
              enquiry.status === 'CONVERTED' ? (
                <Notice kind="success" title={`Won — became ${enquiry.sales_order_number}`}>
                  Closed {formatDateTime(enquiry.converted_at)}. The deal is read-only; the order holds
                  the agreed prices.
                </Notice>
              ) : (
                <Notice kind="warning" title="Lost">
                  {formatDateTime(enquiry.lost_at)}
                  {enquiry.lost_reason ? ` — ${enquiry.lost_reason}` : ''}. No order was created.
                </Notice>
              )
            ) : null}

            <div className="columns columns--main-aside">
              <div className="stack">
                <Card
                  title="Deal"
                  subtitle={editable ? 'MRP is fixed by the product master — negotiate with the discount' : undefined}
                  actions={
                    editable ? (
                      <Button size="sm" variant="tinted" icon={<PlusIcon size={14} />} onClick={() => setAdding(true)}>
                        Add product
                      </Button>
                    ) : undefined
                  }
                  flush
                >
                  {draft.length === 0 ? (
                    <EmptyState compact title="No products" body="Add at least one product before closing the deal." />
                  ) : (
                    <TableScroll>
                      <table className="table">
                        <thead>
                          <tr>
                            <th>Product</th>
                            <th className="num">MRP</th>
                            <th className="num">Quantity</th>
                            <th className="num">Discount</th>
                            <th className="num">Price</th>
                            <th className="num">Total</th>
                            {editable ? <th className="col-actions" /> : null}
                          </tr>
                        </thead>
                        <tbody>
                          {draft.map((line, index) => {
                            const value = money(line)
                            const rowError = lineErrors[index]
                            return (
                              <tr key={line.key}>
                                <td>
                                  <span className="cell-primary">{line.name}</span>
                                  <span className="cell-sub">
                                    <span className="mono">{line.sku}</span> · {line.unit}
                                  </span>
                                  {rowError ? <span className="field__error">{rowError}</span> : null}
                                </td>
                                <td className="num muted">{formatUnitPrice(line.mrp)}</td>
                                <td className="num">
                                  {editable ? (
                                    <input
                                      className="input input--sm input--num input--qty"
                                      type="number"
                                      step="0.001"
                                      min="0"
                                      inputMode="decimal"
                                      aria-label={`Quantity of ${line.sku}`}
                                      aria-invalid={rowError ? true : undefined}
                                      value={line.quantity}
                                      onChange={(event) => updateLine(line.key, { quantity: event.target.value })}
                                    />
                                  ) : (
                                    formatQuantity(line.quantity)
                                  )}
                                </td>
                                <td className="num">
                                  {editable ? (
                                    <div className="row row--end gap-1">
                                      <input
                                        className="input input--sm input--num input--pct"
                                        type="number"
                                        step="0.01"
                                        min="0"
                                        max="100"
                                        inputMode="decimal"
                                        aria-label={`Discount on ${line.sku}`}
                                        aria-invalid={rowError ? true : undefined}
                                        value={line.discountPercent}
                                        onChange={(event) =>
                                          updateLine(line.key, { discountPercent: event.target.value })
                                        }
                                      />
                                      <span className="muted">%</span>
                                    </div>
                                  ) : Number(line.discountPercent) > 0 ? (
                                    formatPercent(line.discountPercent)
                                  ) : (
                                    <span className="q-muted">—</span>
                                  )}
                                </td>
                                <td className="num">{formatUnitPrice(value.price)}</td>
                                <td className="num">
                                  <span className="cell-primary">{formatAmount(value.total)}</span>
                                  {value.gross > value.total ? (
                                    <span className="cell-sub">−{formatAmount(value.gross - value.total)}</span>
                                  ) : null}
                                </td>
                                {editable ? (
                                  <td className="col-actions">
                                    <Button
                                      variant="ghost"
                                      size="sm"
                                      iconOnly
                                      icon={<CloseIcon size={14} />}
                                      aria-label={`Remove ${line.sku}`}
                                      disabled={draft.length === 1}
                                      onClick={() => {
                                        setDirty(true)
                                        setDraft((current) => current.filter((entry) => entry.key !== line.key))
                                      }}
                                    />
                                  </td>
                                ) : null}
                              </tr>
                            )
                          })}
                        </tbody>
                      </table>
                    </TableScroll>
                  )}
                </Card>

                <Card title="Notes">
                  <CardBody>
                    {editable ? (
                      <textarea
                        className="input"
                        aria-label="Enquiry notes"
                        value={notes}
                        onChange={(event) => {
                          setNotes(event.target.value)
                          setDirty(true)
                        }}
                        placeholder="Anything else the customer asked for."
                      />
                    ) : (
                      <p className="t-callout pre-line">
                        {enquiry.notes || <span className="muted">No notes.</span>}
                      </p>
                    )}
                  </CardBody>
                </Card>
              </div>

              <div className="aside-sticky">
                <Card>
                  <div className="summary-hero">
                    <div className="summary-hero__label">Deal value</div>
                    <div className="summary-hero__value">{formatMoney(totals.total)}</div>
                    <div className="summary-hero__hint">before tax · {draft.length} product{draft.length === 1 ? '' : 's'}</div>
                  </div>
                  <div className="card__body hide-when-docked">
                    <KeyValue
                      stacked
                      items={[
                        { label: 'At MRP', value: formatAmount(totals.gross) },
                        {
                          label: 'Discount given',
                          value:
                            totals.gross > totals.total ? (
                              <span className="q-negative">−{formatAmount(totals.gross - totals.total)}</span>
                            ) : (
                              '—'
                            ),
                        },
                        { label: 'Last updated', value: formatDateTime(enquiry.updated_at) },
                      ]}
                    />
                  </div>
                  {editable ? (
                    <div className="card__footer card__footer--stack">
                      {dirty ? (
                        <Notice kind="warning">Save your changes before closing, so the order uses these prices.</Notice>
                      ) : null}
                      <Button
                        variant="primary"
                        block
                        icon={<CheckIcon size={15} />}
                        onClick={() => setConfirming('convert')}
                        disabled={saving || dirty || hasErrors || draft.length === 0}
                      >
                        Close deal & create order
                      </Button>
                    </div>
                  ) : null}
                </Card>
              </div>
            </div>

            {adding ? (
              <AddProductDialog
                existing={draft.map((line) => line.productId)}
                onClose={() => setAdding(false)}
                onPick={addProduct}
              />
            ) : null}

            {confirming === 'convert' ? (
              <ConfirmDialog
                title="Close the deal?"
                confirmLabel="Create sales order"
                busy={saving}
                onCancel={() => setConfirming(null)}
                onConfirm={convert}
                icon={<CheckIcon size={19} />}
                message={
                  <>
                    <p>
                      A sales order for <strong>{enquiry.customer.name}</strong> will be created at{' '}
                      <strong>{formatMoney(enquiry.total_amount)}</strong> before tax, across{' '}
                      {enquiry.items.length} product{enquiry.items.length === 1 ? '' : 's'}.
                    </p>
                    <p>
                      Stock is taken straight away; anything short waits for the next receipt. This
                      enquiry then becomes read-only.
                    </p>
                  </>
                }
              />
            ) : null}

            {confirming === 'lost' ? (
              <MarkLostDialog
                enquiryNumber={enquiry.enquiry_number}
                busy={saving}
                onCancel={() => setConfirming(null)}
                onConfirm={markLost}
              />
            ) : null}
          </div>
        )}
      </AsyncBlock>
    </Page>
  )
}

function AddProductDialog({
  existing,
  onClose,
  onPick,
}: {
  existing: string[]
  onClose: () => void
  onPick: (product: Product) => void
}) {
  const products = useAsync<Product[]>(() => api.products.all(), [])
  const [search, setSearch] = useState('')
  const available = useMemo(() => {
    const term = search.trim().toLowerCase()
    return (products.data ?? []).filter(
      (product) =>
        !existing.includes(product.id) &&
        (!term || product.sku.toLowerCase().includes(term) || product.name.toLowerCase().includes(term)),
    )
  }, [products.data, existing, search])

  return (
    <Dialog title="Add a product" onClose={onClose} footer={<DialogCancel>Done</DialogCancel>}>
      <SearchField value={search} onChange={setSearch} placeholder="Search code or name" width="100%" />
      {products.error ? <Notice kind="error">{products.error}</Notice> : null}
      <div className="picker">
        {products.loading && !products.data ? (
          <Loading />
        ) : available.length === 0 ? (
          <EmptyState compact title="No other products to add" />
        ) : (
          available.map((product) => (
            <button key={product.id} type="button" className="picker__row" onClick={() => onPick(product)}>
              <span>
                <span className="cell-primary">{product.name}</span>
                <span className="cell-sub">
                  <span className="mono">{product.sku}</span> · {product.unit_of_measure}
                </span>
              </span>
              <span className="picker__figures">
                <span>
                  <b>{formatAmount(product.mrp)}</b>MRP
                </span>
                <span>
                  <b className={Number(product.stock) < 0 ? 'q-negative' : undefined}>
                    {formatQuantity(product.stock)}
                  </b>
                  stock
                </span>
              </span>
            </button>
          ))
        )}
      </div>
    </Dialog>
  )
}

function MarkLostDialog({
  enquiryNumber,
  busy,
  onCancel,
  onConfirm,
}: {
  enquiryNumber: string
  busy: boolean
  onCancel: () => void
  onConfirm: (reason: string) => void
}) {
  const [reason, setReason] = useState('')
  return (
    <ConfirmDialog
      title={`Mark ${enquiryNumber} as lost?`}
      confirmLabel="Mark as lost"
      destructive
      busy={busy}
      onCancel={onCancel}
      onConfirm={() => onConfirm(reason.trim())}
      icon={<LostIcon size={19} />}
      message={
        <>
          <p>It closes without an order. No stock moves, and it becomes read-only.</p>
          <div className="field mt-3">
            <label className="field__label" htmlFor="lost-reason">
              Reason <span className="field__optional">Optional</span>
            </label>
            <textarea
              id="lost-reason"
              className="input"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              disabled={busy}
              placeholder="Went with another supplier on price"
            />
          </div>
        </>
      }
    />
  )
}

function ConversionSummary({ result }: { result: EnquiryConversionResult }) {
  const { order } = result
  const awaiting = order.items.reduce((total, item) => total + Number(item.quantity_unallocated), 0)
  return (
    <Card>
      <div className="done">
        <div className="done__mark" aria-hidden="true">
          <CheckIcon size={20} strokeWidth={3} />
        </div>
        <div className="grow">
          <div className="done__title">
            Deal closed — <span className="mono">{order.order_number}</span> created
          </div>
          <div className="done__meta">
            {formatMoney(order.total_amount)} before tax ·{' '}
            {awaiting > 0 ? `${formatQuantity(awaiting)} short` : 'all covered'}
          </div>
        </div>
        <StatusBadge status={order.status} />
        <LinkButton to={`/orders/${order.id}`} variant="primary">
          Open order
        </LinkButton>
      </div>
      <TableScroll>
        <table className="table table--compact">
          <thead>
            <tr>
              <th>Product</th>
              <th className="num">Ordered</th>
              <th className="num">Ready</th>
              <th className="num">Short</th>
              <th className="num">Price</th>
              <th className="num">Total</th>
            </tr>
          </thead>
          <tbody>
            {order.items.map((item) => (
              <tr key={item.id}>
                <td>
                  {item.product.name}
                  <span className="cell-sub mono">{item.product.sku}</span>
                </td>
                <td className="num">{formatQuantity(item.quantity_ordered)}</td>
                <td className="num">
                  <Quantity value={item.quantity_reserved} tone="reserved" />
                </td>
                <td className="num">
                  <Quantity value={item.quantity_unallocated} tone="awaiting" />
                </td>
                <td className="num">{formatUnitPrice(item.unit_price_net)}</td>
                <td className="num">{formatAmount(Number(item.unit_price_net) * Number(item.quantity_ordered))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableScroll>
    </Card>
  )
}
