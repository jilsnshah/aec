import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import type {
  GoodsReceiptResult,
  PurchaseOrder,
  ReceiptPreview,
  ReceiptPreviewLine,
} from '../api/types'
import {
  AsyncBlock,
  Avatar,
  Badge,
  Button,
  Card,
  CardFacts,
  Collection,
  ConfirmDialog,
  EmptyState,
  ExportButton,
  Field,
  FormGrid,
  LinkButton,
  Loading,
  MetricStrip,
  Notice,
  Page,
  PurchaseStatusBadge,
  RecordCard,
  SearchField,
  Segmented,
  SignedQuantity,
  StepCard,
  Switch,
  TableScroll,
  Toolbar,
  ViewSwitch,
  useToast,
} from '../components/ui'
import {
  CheckIcon,
  DeliveryIcon,
  GoodsReceiptIcon,
  ResetIcon,
} from '../components/icons'
import { fromUnits, isValidQuantity, sumUnits, toUnits } from '../lib/decimal'
import {
  formatAmount,
  formatDateTime,
  formatMoney,
  formatQuantity,
  formatRelative,
  formatUnitPrice,
} from '../lib/format'
import { downloadCsv, fileStamp } from '../lib/csv'
import { usePaging, useViewMode } from '../lib/paging'
import { newIdempotencyKey } from '../lib/ids'
import { useAsync, useDebounced } from '../lib/useAsync'

/** What the operator has typed for one purchase order line. */
interface LineEntry {
  quantity: string
  unitCost: string
  overReason: string
  /** order_item_id -> quantity, once a preview has seeded it. */
  allocations: Record<string, string>
  customised: boolean
}

const BLANK_ENTRY: LineEntry = {
  quantity: '',
  unitCost: '',
  overReason: '',
  allocations: {},
  customised: false,
}

/** The allocation arithmetic for one receipt line, mirroring the backend. */
interface LineAllocationState {
  allocatedUnits: number
  requiredUnits: number
  remainingUnits: number
  rowErrors: Record<string, string>
  stockAfterUnits: number
}

export default function GoodsReceiptsPage() {
  const [params, setParams] = useSearchParams()
  // The tab lives in the URL, so History (and its page) can be linked to.
  const view: 'receive' | 'history' = params.get('tab') === 'history' ? 'history' : 'receive'
  function setView(next: 'receive' | 'history') {
    setParams(
      (current) => {
        const updated = new URLSearchParams(current)
        updated.delete('page')
        if (next === 'history') updated.set('tab', 'history')
        else updated.delete('tab')
        return updated
      },
      { replace: true },
    )
  }

  return (
    <Page>
      <Toolbar
        title="Goods Receipts"
        subtitle="Book in what arrived. The customers this purchase was bought for get it first."
      >
        <Segmented
          label="View"
          value={view}
          onChange={setView}
          options={[
            { value: 'receive', label: 'New receipt' },
            { value: 'history', label: 'History' },
          ]}
        />
      </Toolbar>
      {view === 'receive' ? (
        <ReceiveWorkflow
          poId={params.get('po') ?? ''}
          onChoosePo={(id) =>
            setParams(
              (current) => {
                const next = new URLSearchParams(current)
                if (id) next.set('po', id)
                else next.delete('po')
                return next
              },
              { replace: true },
            )
          }
        />
      ) : (
        <ReceiptHistory />
      )}
    </Page>
  )
}

function ReceiveWorkflow({ poId, onChoosePo }: { poId: string; onChoosePo: (id: string) => void }) {
  const toast = useToast()
  const orders = useAsync<PurchaseOrder[]>(() => api.purchaseOrders.all({ status: 'ORDERED,PARTIALLY_RECEIVED' }), [])
  const receivable = useMemo(() => (orders.data ?? []).filter((order) => order.can_receive), [orders.data])
  const order = (orders.data ?? []).find((row) => row.id === poId)

  const [entries, setEntries] = useState<Record<string, LineEntry>>({})
  const [deliveryNote, setDeliveryNote] = useState('')
  const [notes, setNotes] = useState('')
  const [allowOver, setAllowOver] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [result, setResult] = useState<GoodsReceiptResult | null>(null)
  const idempotencyKey = useRef(newIdempotencyKey())
  const seedKey = useRef('')

  // A different purchase order starts a fresh receipt.
  useEffect(() => {
    setEntries({})
    setDeliveryNote('')
    setNotes('')
    setAllowOver(false)
    setSubmitError(null)
    seedKey.current = ''
  }, [poId])

  const requestedLines = useMemo(
    () =>
      Object.entries(entries)
        .filter(([, entry]) => isValidQuantity(entry.quantity) && toUnits(entry.quantity) > 0)
        .map(([itemId, entry]) => ({
          purchase_order_item_id: itemId,
          quantity: entry.quantity,
          unit_cost: entry.unitCost.trim() === '' ? null : entry.unitCost,
        })),
    [entries],
  )
  const debouncedLines = useDebounced(JSON.stringify(requestedLines), 350)

  const preview = useAsync<ReceiptPreview | null>(() => {
    const lines = JSON.parse(debouncedLines) as typeof requestedLines
    if (!poId || lines.length === 0) return Promise.resolve(null)
    return api.goodsReceipts.preview({ purchase_order_id: poId, lines })
  }, [poId, debouncedLines])

  // Seed each line's allocation boxes from the server's FIFO proposal.
  useEffect(() => {
    const data = preview.data
    if (!data) return
    const key = JSON.stringify(data.lines.map((line) => [line.purchase_order_item_id, line.quantity_receiving]))
    if (seedKey.current === key) return
    seedKey.current = key
    setEntries((current) => {
      const next = { ...current }
      for (const line of data.lines) {
        const entry = next[line.purchase_order_item_id]
        if (!entry || entry.customised) continue
        const seeded: Record<string, string> = {}
        for (const row of line.allocations) seeded[row.order_item_id] = row.proposed_allocation
        next[line.purchase_order_item_id] = { ...entry, allocations: seeded }
      }
      return next
    })
  }, [preview.data])

  function updateEntry(itemId: string, changes: Partial<LineEntry>) {
    setEntries((current) => ({ ...current, [itemId]: { ...BLANK_ENTRY, ...current[itemId], ...changes } }))
  }

  function setAllocation(itemId: string, orderItemId: string, value: string) {
    setEntries((current) => {
      const entry = current[itemId]
      if (!entry) return current
      return {
        ...current,
        [itemId]: { ...entry, customised: true, allocations: { ...entry.allocations, [orderItemId]: value } },
      }
    })
  }

  function resetAllocation(line: ReceiptPreviewLine) {
    const seeded: Record<string, string> = {}
    for (const row of line.allocations) seeded[row.order_item_id] = row.proposed_allocation
    updateEntry(line.purchase_order_item_id, { allocations: seeded, customised: false })
  }

  function lineState(line: ReceiptPreviewLine): LineAllocationState {
    const allocations = entries[line.purchase_order_item_id]?.allocations ?? {}
    const allocatedUnits = sumUnits(line.allocations.map((row) => toUnits(allocations[row.order_item_id] ?? '0') || 0))
    const requiredUnits = toUnits(line.required_allocation)
    const rowErrors: Record<string, string> = {}
    for (const row of line.allocations) {
      const raw = allocations[row.order_item_id] ?? '0'
      if (raw.trim() === '') continue
      const units = toUnits(raw)
      if (!Number.isFinite(units) || units < 0) rowErrors[row.order_item_id] = 'Enter zero or more.'
      else if (units > toUnits(row.quantity_eligible)) {
        rowErrors[row.order_item_id] = `This order is waiting for only ${formatQuantity(row.quantity_eligible)}.`
      }
    }
    return {
      allocatedUnits,
      requiredUnits,
      remainingUnits: requiredUnits - allocatedUnits,
      rowErrors,
      stockAfterUnits: toUnits(line.stock_after),
    }
  }

  const blockers: string[] = []
  if (!poId) blockers.push('Choose the purchase order this delivery is for.')
  else if (requestedLines.length === 0) blockers.push('Enter how much of at least one line arrived.')
  if (preview.data) {
    for (const line of preview.data.lines) {
      const state = lineState(line)
      if (Object.keys(state.rowErrors).length > 0) {
        blockers.push(`${line.product_sku}: fix the highlighted amounts.`)
      } else if (state.remainingUnits > 0) {
        blockers.push(`${line.product_sku}: assign ${formatQuantity(fromUnits(state.remainingUnits))} more to waiting customers.`)
      } else if (state.remainingUnits < 0) {
        blockers.push(`${line.product_sku}: assign ${formatQuantity(fromUnits(-state.remainingUnits))} less.`)
      }
      if (line.is_over_receipt) {
        if (!allowOver) blockers.push(`${line.product_sku}: more than the order still owes — allow an over-receipt.`)
        else if (!(entries[line.purchase_order_item_id]?.overReason ?? '').trim()) {
          blockers.push(`${line.product_sku}: give a reason for the over-receipt.`)
        }
      }
    }
  }
  const ready = blockers.length === 0 && !preview.loading && Boolean(preview.data)

  async function submit() {
    if (!ready || !preview.data || submitting) return
    setSubmitting(true)
    setSubmitError(null)
    try {
      const receipt = await api.goodsReceipts.create({
        purchase_order_id: poId,
        delivery_note_reference: deliveryNote.trim() || null,
        notes: notes.trim() || null,
        allow_over_receipt: allowOver,
        idempotency_key: idempotencyKey.current,
        lines: preview.data.lines.map((line) => {
          const entry = entries[line.purchase_order_item_id]
          return {
            purchase_order_item_id: line.purchase_order_item_id,
            quantity: line.quantity_receiving,
            unit_cost: !entry || entry.unitCost.trim() === '' ? null : entry.unitCost,
            over_receipt_reason: entry?.overReason.trim() || null,
            // Always send what is on screen; the backend re-validates it.
            allocations: line.allocations.map((row) => ({
              order_item_id: row.order_item_id,
              quantity: entry?.allocations[row.order_item_id] || '0',
            })),
          }
        }),
      })
      setResult(receipt)
      setConfirming(false)
      idempotencyKey.current = newIdempotencyKey()
      toast.success(
        `${receipt.receipt_number} recorded`,
        `${formatQuantity(receipt.total_received)} in · ${formatQuantity(receipt.total_allocated)} to waiting customers`,
      )
      orders.reload()
    } catch (cause) {
      setSubmitError(cause instanceof ApiError ? cause.message : String(cause))
      setConfirming(false)
    } finally {
      setSubmitting(false)
    }
  }

  if (result) {
    return (
      <ReceiptDone
        result={result}
        onAnother={() => {
          setResult(null)
          onChoosePo('')
        }}
      />
    )
  }

  if (orders.loading && !orders.data) return <Loading />
  if (orders.error) return <Notice kind="error">{orders.error}</Notice>
  if (receivable.length === 0) {
    return (
      <Card>
        <EmptyState
          icon={<GoodsReceiptIcon size={22} />}
          title="No purchase orders are awaiting delivery"
          body="Only a placed purchase order with something still outstanding can receive goods."
          action={
            <LinkButton to="/purchase-orders?new=1" variant="primary">
              Raise a purchase order
            </LinkButton>
          }
        />
      </Card>
    )
  }

  const data = preview.data
  return (
    <div className="columns columns--main-aside">
      <div className="stack stack--tight">
        {submitError ? (
          <Notice kind="error" title="Rejected — nothing was saved">
            {submitError}
          </Notice>
        ) : null}

        <StepCard
          index={1}
          title="Which delivery is this?"
          active={!order}
          done={Boolean(order)}
          summary={order ? `${order.po_number} · ${order.supplier.name}` : 'Choose the purchase order'}
        >
          <FormGrid>
            <Field label="Purchase order" span2>
              {(props) => (
                <select {...props} value={poId} onChange={(event) => onChoosePo(event.target.value)}>
                  <option value="">Choose a purchase order…</option>
                  {receivable.map((row) => (
                    <option key={row.id} value={row.id}>
                      {row.po_number} — {row.supplier.name} · {formatQuantity(row.total_remaining)} outstanding
                    </option>
                  ))}
                </select>
              )}
            </Field>
            {order ? (
              <>
                <Field label="Supplier’s delivery note" optional>
                  {(props) => (
                    <input {...props} value={deliveryNote} onChange={(event) => setDeliveryNote(event.target.value)} placeholder="DN-7741" />
                  )}
                </Field>
                <Field label="Note" optional>
                  {(props) => (
                    <input {...props} value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Condition on arrival, driver…" />
                  )}
                </Field>
              </>
            ) : null}
          </FormGrid>
        </StepCard>

        {order ? (
          <StepCard
            index={2}
            title="What arrived?"
            active={requestedLines.length === 0}
            done={requestedLines.length > 0}
            summary={
              requestedLines.length > 0
                ? `${requestedLines.length} line${requestedLines.length === 1 ? '' : 's'} receiving`
                : 'Leave a line blank if none of it came'
            }
            trailing={<PurchaseStatusBadge status={order.status} />}
            flush
          >
            <TableScroll>
              <table className="table">
                <thead>
                  <tr>
                    <th>Product</th>
                    <th className="num">Ordered</th>
                    <th className="num">Received</th>
                    <th className="num">Outstanding</th>
                    <th className="num">Arrived now</th>
                    <th className="num">Cost / unit</th>
                  </tr>
                </thead>
                <tbody>
                  {order.items.map((item) => {
                    const entry = entries[item.id]
                    const typed = entry?.quantity ?? ''
                    const over = isValidQuantity(typed) && toUnits(typed) > toUnits(item.quantity_remaining)
                    const done = Number(item.quantity_remaining) <= 0
                    return (
                      <tr key={item.id} className={done ? 'is-muted' : undefined}>
                        <td>
                          <span className="cell-primary">{item.product.name}</span>
                          <span className="cell-sub">
                            <span className="mono">{item.product.sku}</span> · {item.product.unit_of_measure}
                          </span>
                        </td>
                        <td className="num">{formatQuantity(item.quantity_ordered)}</td>
                        <td className="num">{formatQuantity(item.quantity_received)}</td>
                        <td className="num">
                          {done ? <Badge tone="green">Complete</Badge> : <span className="q-strong">{formatQuantity(item.quantity_remaining)}</span>}
                        </td>
                        <td className="num">
                          <input
                            className="input input--sm input--num input--inline"
                            type="number"
                            step="0.001"
                            min="0"
                            inputMode="decimal"
                            aria-label={`Quantity of ${item.product.sku} that arrived`}
                            aria-invalid={over && !allowOver ? true : undefined}
                            placeholder="0"
                            value={typed}
                            onChange={(event) => updateEntry(item.id, { quantity: event.target.value })}
                          />
                          {over ? (
                            <span className={allowOver ? 'cell-sub q-owed' : 'field__error'}>more than outstanding</span>
                          ) : null}
                        </td>
                        <td className="num">
                          <input
                            className="input input--sm input--num input--inline"
                            type="number"
                            step="0.0001"
                            min="0"
                            inputMode="decimal"
                            aria-label={`Cost per unit of ${item.product.sku}`}
                            placeholder={item.unit_cost}
                            value={entry?.unitCost ?? ''}
                            onChange={(event) => updateEntry(item.id, { unitCost: event.target.value })}
                          />
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </TableScroll>
            <div className="card__footer">
              <Switch
                checked={allowOver}
                onChange={setAllowOver}
                label="Allow receiving more than the order still owes"
                description="Each over-received line needs a reason, which is stored with it."
              />
            </div>
          </StepCard>
        ) : null}

        {order && requestedLines.length > 0 ? (
          <StepCard
            index={3}
            title="Give to waiting customers"
            active
            summary="FIFO is proposed — adjust it if you need to, the rules still hold"
            flush
          >
            <AsyncBlock loading={preview.loading} error={preview.error} data={data} onRetry={preview.reload} skeleton="spinner">
              {(current) =>
                current === null ? (
                  <EmptyState compact title="Enter a quantity to see the allocation" />
                ) : (
                  <div>
                    {current.lines.map((line) => (
                      <AllocationLine
                        key={line.purchase_order_item_id}
                        line={line}
                        state={lineState(line)}
                        allocations={entries[line.purchase_order_item_id]?.allocations ?? {}}
                        customised={entries[line.purchase_order_item_id]?.customised ?? false}
                        overReason={entries[line.purchase_order_item_id]?.overReason ?? ''}
                        allowOver={allowOver}
                        onAllocate={(orderItemId, value) => setAllocation(line.purchase_order_item_id, orderItemId, value)}
                        onReset={() => resetAllocation(line)}
                        onReason={(value) => updateEntry(line.purchase_order_item_id, { overReason: value })}
                      />
                    ))}
                  </div>
                )
              }
            </AsyncBlock>
          </StepCard>
        ) : null}
      </div>

      <aside className="aside-sticky">
        <Card>
          <SummaryHeadline data={data} blockers={blockers} lineState={lineState} />
          {data ? (
            <div className="hide-when-docked">
              <table className="before-after">
                <tbody>
                  <tr>
                    <td>Receiving</td>
                    <td className="num">{formatQuantity(data.total_receiving)}</td>
                  </tr>
                  <tr>
                    <td>To waiting customers</td>
                    <td className="num q-reserved">{formatQuantity(data.total_required_allocation)}</td>
                  </tr>
                  <tr>
                    <td>Into free stock</td>
                    <td className="num q-available">{formatQuantity(data.total_surplus)}</td>
                  </tr>
                  <tr>
                    <td>Purchase cost</td>
                    <td className="num">{formatMoney(data.total_cost)}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          ) : null}
          {blockers.length > 0 && poId ? (
            <div className="card__body card__body--tight hide-when-docked">
              <ul className="hint blocker-list">
                {blockers.slice(0, 4).map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            </div>
          ) : null}
          <div className="card__footer">
            <Button
              variant="primary"
              block
              icon={<CheckIcon size={15} />}
              disabled={!ready}
              busy={submitting}
              onClick={() => setConfirming(true)}
            >
              Confirm receipt
            </Button>
          </div>
        </Card>
      </aside>

      {confirming && data ? (
        <ConfirmDialog
          title="Book in this delivery?"
          confirmLabel="Confirm receipt"
          busy={submitting}
          onCancel={() => setConfirming(false)}
          onConfirm={submit}
          icon={<GoodsReceiptIcon size={19} />}
          message={
            <>
              <p>
                <strong>{formatQuantity(data.total_receiving)}</strong> units against {data.po_number} from{' '}
                {data.supplier_name}, costing {formatMoney(data.total_cost)}.
              </p>
              <p>
                {formatQuantity(data.total_required_allocation)} goes to waiting customers first and{' '}
                {formatQuantity(data.total_surplus)} goes into free stock. Stock movements are permanent.
              </p>
            </>
          }
        />
      ) : null}
    </div>
  )
}

function SummaryHeadline({
  data,
  blockers,
  lineState,
}: {
  data: ReceiptPreview | null
  blockers: string[]
  lineState: (line: ReceiptPreviewLine) => LineAllocationState
}) {
  if (!data) {
    return (
      <div className="summary-hero">
        <div className="summary-hero__icon" aria-hidden="true">
          <GoodsReceiptIcon size={20} />
        </div>
        <div className="summary-hero__label">New receipt</div>
        <div className="summary-hero__hint">{blockers[0] ?? 'Enter what arrived'}</div>
      </div>
    )
  }
  const remaining = data.lines.reduce((total, line) => total + lineState(line).remainingUnits, 0)
  const state = blockers.length === 0 ? 'is-ok' : remaining < 0 ? 'is-over' : 'is-todo'
  return (
    <div className={`summary-hero ${state}`}>
      <div className="summary-hero__label">
        {blockers.length === 0 ? 'Ready to book in' : remaining !== 0 ? 'Left to assign' : 'Needs attention'}
      </div>
      <div className="summary-hero__value">
        {blockers.length === 0 ? <CheckIcon size={30} strokeWidth={2.6} /> : formatQuantity(fromUnits(Math.abs(remaining)))}
      </div>
      <div className="summary-hero__hint">
        {blockers.length === 0
          ? `${formatQuantity(data.total_receiving)} in · ${formatQuantity(data.total_required_allocation)} to waiting orders`
          : blockers[0]}
      </div>
    </div>
  )
}

function AllocationLine({
  line,
  state,
  allocations,
  customised,
  overReason,
  allowOver,
  onAllocate,
  onReset,
  onReason,
}: {
  line: ReceiptPreviewLine
  state: LineAllocationState
  allocations: Record<string, string>
  customised: boolean
  overReason: string
  allowOver: boolean
  onAllocate: (orderItemId: string, value: string) => void
  onReset: () => void
  onReason: (value: string) => void
}) {
  return (
    <div className="alloc-group">
      <div className="card__toolbar">
        <div className="grow">
          <span className="cell-primary">{line.product_name}</span>{' '}
          <span className="muted t-footnote">
            <span className="mono">{line.product_sku}</span> · {formatQuantity(line.quantity_receiving)}{' '}
            {line.unit_of_measure} at {formatUnitPrice(line.unit_cost)}
          </span>
        </div>
        {state.remainingUnits === 0 ? (
          <span className="chip chip--ok">
            <CheckIcon size={13} strokeWidth={2.6} /> Balanced
          </span>
        ) : state.remainingUnits > 0 ? (
          <span className="chip chip--todo">{formatQuantity(fromUnits(state.remainingUnits))} left</span>
        ) : (
          <span className="chip chip--over">{formatQuantity(fromUnits(-state.remainingUnits))} over</span>
        )}
        {customised ? (
          <Button size="sm" variant="plain" icon={<ResetIcon size={13} />} onClick={onReset}>
            FIFO
          </Button>
        ) : null}
      </div>

      {line.is_over_receipt && allowOver ? (
        <div className="card__body card__body--tight">
          <Field label="Reason for receiving more than ordered">
            {(props) => (
              <input {...props} value={overReason} onChange={(event) => onReason(event.target.value)} placeholder="Supplier shipped a full case" />
            )}
          </Field>
        </div>
      ) : null}

      {line.allocations.length === 0 ? (
        <EmptyState
          compact
          title="Nobody is waiting for this product"
          body={`All ${formatQuantity(line.quantity_receiving)} ${line.unit_of_measure} go into stock.`}
        />
      ) : (
        <TableScroll>
          <table className="table table--compact">
            <thead>
              <tr>
                <th className="col-shrink">#</th>
                <th>Customer · order</th>
                <th className="num">To deliver</th>
                <th className="num">Ready</th>
                <th className="num">Waiting</th>
                <th className="num">Give now</th>
              </tr>
            </thead>
            <tbody>
              {line.allocations.map((row, index) => {
                const typed = allocations[row.order_item_id] ?? '0'
                const rowError = state.rowErrors[row.order_item_id]
                return (
                  <tr key={row.order_item_id} className={toUnits(typed) > 0 ? 'is-highlighted' : undefined}>
                    <td className="col-shrink muted">{index + 1}</td>
                    <td>
                      <Link className="cell-link" to={`/customers/${row.customer_id}`}>
                        {row.customer_name}
                      </Link>
                      <span className="cell-sub">
                        <Link to={`/orders/${row.order_id}`} className="mono">
                          {row.order_number}
                        </Link>{' '}
                        · {formatDateTime(row.order_created_at)}
                      </span>
                    </td>
                    <td className="num">{formatQuantity(row.quantity_outstanding)}</td>
                    <td className="num q-reserved">{formatQuantity(row.quantity_reserved)}</td>
                    <td className="num q-owed">{formatQuantity(row.quantity_eligible)}</td>
                    <td className="num">
                      <input
                        className="input input--sm input--num input--inline"
                        type="number"
                        step="0.001"
                        min="0"
                        max={row.quantity_eligible}
                        inputMode="decimal"
                        aria-label={`Assign to ${row.customer_name}, ${row.order_number}`}
                        aria-invalid={rowError ? true : undefined}
                        value={typed}
                        onChange={(event) => onAllocate(row.order_item_id, event.target.value)}
                      />
                      {rowError ? <span className="field__error">{rowError}</span> : null}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </TableScroll>
      )}
      <div className="card__body card__body--tight">
        <div className="legend">
          <span>
            Stock <SignedQuantity value={line.stock} />
            {state.stockAfterUnits === toUnits(line.stock) ? (
              <> — unchanged, it was counted when the purchase order was placed</>
            ) : (
              <>
                {' '}→ <b><SignedQuantity value={fromUnits(state.stockAfterUnits)} /></b> (more than ordered)
              </>
            )}
          </span>
        </div>
      </div>
    </div>
  )
}

function ReceiptDone({ result, onAnother }: { result: GoodsReceiptResult; onAnother: () => void }) {
  return (
    <div className="stack">
      <Card>
        <div className="done">
          <div className="done__mark" aria-hidden="true">
            <CheckIcon size={20} strokeWidth={3} />
          </div>
          <div className="grow">
            <div className="done__title">
              <span className="mono">{result.receipt_number}</span> booked in
            </div>
            <div className="done__meta">
              {formatQuantity(result.total_received)} units against{' '}
              <Link to={`/purchase-orders/${result.purchase_order_id}`} className="mono">
                {result.po_number}
              </Link>{' '}
              from {result.supplier_name} · {formatMoney(result.total_cost)}
              {result.delivery_note_reference ? ` · ${result.delivery_note_reference}` : ''}
            </div>
          </div>
          <PurchaseStatusBadge status={result.po_status} />
        </div>
      </Card>

      <MetricStrip
        items={[
          { label: 'Received', value: formatQuantity(result.total_received), dot: 'var(--stock-physical)' },
          {
            label: 'To waiting customers',
            value: formatQuantity(result.total_allocated),
            tone: 'reserved',
            dot: 'var(--stock-reserved)',
          },
          {
            label: 'Into free stock',
            value: formatQuantity(result.total_surplus),
            tone: 'positive',
            dot: 'var(--stock-available)',
          },
          { label: 'Cost', value: formatMoney(result.total_cost) },
        ]}
      />

      {result.lines.map((line) => (
        <Card
          key={line.goods_receipt_item_id}
          title={line.product_name}
          subtitle={
            <>
              <span className="mono">{line.product_sku}</span> · {formatQuantity(line.quantity_received)} at{' '}
              {formatUnitPrice(line.unit_cost)} · {formatQuantity(line.quantity_remaining_on_po)} still due on the PO
            </>
          }
          actions={line.is_over_receipt ? <Badge tone="orange">Over-receipt · {line.over_receipt_reason}</Badge> : undefined}
          flush
        >
          {line.allocations.length === 0 ? (
            <EmptyState compact title="Nobody was waiting" body="All of it went into stock." />
          ) : (
            <TableScroll>
              <table className="table table--compact">
                <thead>
                  <tr>
                    <th>Customer</th>
                    <th>Order</th>
                    <th className="num">Assigned now</th>
                    <th className="num">Ready in total</th>
                    <th className="num">To deliver</th>
                  </tr>
                </thead>
                <tbody>
                  {line.allocations.map((row) => (
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
                      <td className="num q-reserved">{formatQuantity(row.quantity_reserved)}</td>
                      <td className="num q-owed">{formatQuantity(row.quantity_outstanding)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableScroll>
          )}
          <div className="card__footer">
            <div className="legend">
              <span>
                Stock <SignedQuantity value={line.stock_after} /> {line.unit_of_measure}
              </span>
            </div>
          </div>
        </Card>
      ))}

      <div className="btn-group">
        <LinkButton to="/pending-fulfilment?filter=ready" variant="primary" icon={<DeliveryIcon size={15} />}>
          Deliver now
        </LinkButton>
        <Button onClick={onAnother}>Record another receipt</Button>
        <LinkButton to={`/purchase-orders/${result.purchase_order_id}`} variant="plain">
          Open purchase order
        </LinkButton>
      </div>
    </div>
  )
}

function ReceiptHistory() {
  const toast = useToast()
  const [search, setSearch] = useState('')
  const debounced = useDebounced(search)
  const [view, setView] = useViewMode('goods-receipts')
  const filters = { search: debounced || undefined }
  const paging = usePaging('goods-receipts', [filters])
  const state = useAsync(
    () => api.goodsReceipts.list({ ...filters, limit: paging.limit, offset: paging.offset }),
    [debounced, paging.limit, paging.offset],
  )

  async function exportCsv() {
    const rows = await api.goodsReceipts.all(filters)
    downloadCsv(
      `goods-receipts-${fileStamp()}.csv`,
      [
        { header: 'Receipt', value: (row) => row.receipt_number },
        { header: 'Received', value: (row) => row.created_at },
        { header: 'Supplier', value: (row) => row.supplier_name },
        { header: 'PO', value: (row) => row.po_number },
        { header: 'Delivery note', value: (row) => row.delivery_note_reference },
        { header: 'Products', value: (row) => row.lines.map((line) => line.product_sku).join(' ') },
        { header: 'Quantity', value: (row) => row.total_quantity },
        { header: 'Cost', value: (row) => row.total_cost },
        { header: 'Over-receipt', value: (row) => (row.lines.some((line) => line.is_over_receipt) ? 'Yes' : 'No') },
      ],
      rows,
    )
    toast.success('Export ready', `${rows.length} receipt${rows.length === 1 ? '' : 's'} downloaded as CSV.`)
  }

  return (
    <div className="stack stack--tight">
      <div className="row gap-2 history-bar">
        <SearchField value={search} onChange={setSearch} placeholder="Search receipts" />
        <div className="grow" />
        <ExportButton onExport={exportCsv} disabled={!state.data?.total} />
        <ViewSwitch value={view} onChange={setView} />
      </div>
      <Collection
        state={state}
        view={view}
        paging={paging}
        noun="receipts"
        columns={6}
        empty={
          <EmptyState
            icon={<GoodsReceiptIcon size={22} />}
            title={search ? 'No matching receipts' : 'No goods receipts yet'}
            body={search ? 'Try a receipt number, supplier or delivery note.' : 'Receipts appear here once goods are booked in.'}
          />
        }
        table={(rows) => (
          <table className="table">
            <thead>
              <tr>
                <th>Receipt</th>
                <th>Supplier</th>
                <th>Against</th>
                <th>Products</th>
                <th className="num">Quantity</th>
                <th className="num">Cost</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>
                    <span className="cell-primary mono">{row.receipt_number}</span>
                    <span className="cell-sub" title={formatDateTime(row.created_at)}>
                      {formatRelative(row.created_at)}
                    </span>
                  </td>
                  <td>
                    <div className="cell-identity">
                      <Avatar name={row.supplier_name} seed={row.supplier_id} square size="sm" />
                      <span className="cell-primary">{row.supplier_name}</span>
                    </div>
                  </td>
                  <td>
                    <Link to={`/purchase-orders/${row.purchase_order_id}`} className="mono">
                      {row.po_number}
                    </Link>
                    {row.delivery_note_reference ? <span className="cell-sub">{row.delivery_note_reference}</span> : null}
                  </td>
                  <td className="muted">
                    {row.lines.map((line) => line.product_sku).join(', ')}
                    {row.lines.some((line) => line.is_over_receipt) ? (
                      <>
                        {' '}
                        <Badge tone="orange">Over-receipt</Badge>
                      </>
                    ) : null}
                  </td>
                  <td className="num">{formatQuantity(row.total_quantity)}</td>
                  <td className="num">{formatAmount(row.total_cost)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        card={(row) => (
          <RecordCard
            key={row.id}
            to={`/purchase-orders/${row.purchase_order_id}`}
            openLabel={`${row.receipt_number}, open ${row.po_number}`}
            leading={<Avatar name={row.supplier_name} seed={row.supplier_id} square />}
            title={row.supplier_name}
            subtitle={
              <>
                <span className="mono">{row.receipt_number}</span> · {formatRelative(row.created_at)}
              </>
            }
            badge={row.lines.some((line) => line.is_over_receipt) ? <Badge tone="orange">Over-receipt</Badge> : undefined}
            footer={
              <>
                <span className="mono">{row.po_number}</span>
                {row.delivery_note_reference ? <span>· {row.delivery_note_reference}</span> : null}
              </>
            }
          >
            <CardFacts
              items={[
                { label: 'Quantity', value: formatQuantity(row.total_quantity) },
                { label: 'Cost', value: formatMoney(row.total_cost) },
                { label: 'Lines', value: row.line_count },
              ]}
            />
            <span className="cell-sub cell-clip">{row.lines.map((line) => line.product_sku).join(', ')}</span>
          </RecordCard>
        )}
      />
    </div>
  )
}
