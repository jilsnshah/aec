import { useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, api } from '../api/client'
import type { CommitmentRow, GoodsReceiptResult, IncomingSource, PurchaseOrder, ReceiptPreview } from '../api/types'
import { fromUnits, isValidQuantity, sumUnits, toUnits } from '../lib/decimal'
import { newIdempotencyKey } from '../lib/ids'
import { formatDate, formatQuantity, formatUnitPrice } from '../lib/format'
import { useAsync, useDebounced } from '../lib/useAsync'
import { Button, Dialog, DialogCancel, Field, FormGrid, Loading, Notice, Segmented, TableScroll } from './ui'
import { CheckIcon, GoodsReceiptIcon } from './icons'

/**
 * Book in goods for one purchase order line, from the line of a sales order
 * that is waiting for them. The goods go first to the customers the purchase
 * was settled for; anything more is offered to customers who are short. The
 * user can change who gets what before booking it in.
 */
export function ReceiveDialog({
  row,
  onClose,
  onReceived,
}: {
  row: CommitmentRow
  onClose: () => void
  onReceived: (result: GoodsReceiptResult) => void
}) {
  const sources = row.incoming_sources
  const [sourceId, setSourceId] = useState(sources[0]?.purchase_order_item_id ?? '')
  const source = sources.find((entry) => entry.purchase_order_item_id === sourceId) ?? sources[0]

  const order = useAsync<PurchaseOrder | null>(
    () => (source ? api.purchaseOrders.get(source.purchase_order_id) : Promise.resolve(null)),
    [source?.purchase_order_id],
  )
  const poLine = order.data?.items.find((item) => item.id === source?.purchase_order_item_id)

  const [quantity, setQuantity] = useState('')
  const [reference, setReference] = useState('')
  // Default to everything still due on the purchase order line.
  useEffect(() => {
    if (poLine) setQuantity(String(Number(poLine.quantity_remaining)))
  }, [poLine?.id])

  const quantityValid =
    isValidQuantity(quantity) &&
    toUnits(quantity) > 0 &&
    (!poLine || toUnits(quantity) <= toUnits(poLine.quantity_remaining))
  const debounced = useDebounced(quantity, 250)
  // Preview the settled-down value, and only once it is a real quantity.
  const debouncedValid = isValidQuantity(debounced) && toUnits(debounced) > 0
  const preview = useAsync<ReceiptPreview | null>(
    () =>
      source && quantityValid && debouncedValid && debounced === quantity
        ? api.goodsReceipts.preview({
            purchase_order_id: source.purchase_order_id,
            lines: [{ purchase_order_item_id: source.purchase_order_item_id, quantity: debounced }],
          })
        : Promise.resolve(null),
    [source?.purchase_order_item_id, debounced, quantityValid && debouncedValid && debounced === quantity],
  )
  const line = preview.data?.lines[0]

  // Who gets the goods: the server's proposal, which the user may change.
  const [amounts, setAmounts] = useState<Record<string, string>>({})
  useEffect(() => {
    if (!line) return
    setAmounts(
      Object.fromEntries(
        line.allocations.map((entry) => [
          entry.order_item_id,
          Number(entry.proposed_allocation) > 0 ? String(Number(entry.proposed_allocation)) : '',
        ]),
      ),
    )
  }, [line])

  const requiredUnits = line ? toUnits(line.required_allocation) : 0
  const allocatedUnits = sumUnits((line?.allocations ?? []).map((entry) => toUnits(amounts[entry.order_item_id] ?? '0') || 0))
  const remainingUnits = requiredUnits - allocatedUnits
  const rowErrors = useMemo(() => {
    const errors: Record<string, string> = {}
    for (const entry of line?.allocations ?? []) {
      const raw = amounts[entry.order_item_id] ?? ''
      if (raw.trim() === '') continue
      const units = toUnits(raw)
      if (!Number.isFinite(units) || units < 0) errors[entry.order_item_id] = 'Enter zero or more.'
      else if (units > toUnits(entry.quantity_eligible)) {
        errors[entry.order_item_id] = `Waiting for only ${formatQuantity(entry.quantity_eligible)}.`
      }
    }
    return errors
  }, [line, amounts])

  let blocker: string | null = null
  if (!quantityValid) {
    blocker = poLine
      ? `Enter between 0 and ${formatQuantity(poLine.quantity_remaining)}.`
      : 'Enter how much arrived.'
  } else if (!line) blocker = 'Checking who is waiting…'
  else if (Object.keys(rowErrors).length > 0) blocker = 'Fix the highlighted amounts.'
  else if (remainingUnits > 0) blocker = `Give ${formatQuantity(fromUnits(remainingUnits))} more to waiting customers.`
  else if (remainingUnits < 0) blocker = `Give ${formatQuantity(fromUnits(-remainingUnits))} less.`

  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const idempotencyKey = useRef(newIdempotencyKey())

  async function submit() {
    if (busy || blocker || !source || !line) return
    setBusy(true)
    setError(null)
    try {
      onReceived(
        await api.goodsReceipts.create({
          purchase_order_id: source.purchase_order_id,
          delivery_note_reference: reference.trim() || null,
          idempotency_key: idempotencyKey.current,
          lines: [
            {
              purchase_order_item_id: source.purchase_order_item_id,
              quantity,
              allocations: line.allocations
                .map((entry) => ({ order_item_id: entry.order_item_id, quantity: amounts[entry.order_item_id] || '0' }))
                .filter((entry) => toUnits(entry.quantity) > 0),
            },
          ],
        }),
      )
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : String(cause))
      setBusy(false)
    }
  }

  return (
    <Dialog
      title={`Receive ${row.product_name}`}
      subtitle={source ? `${source.po_number} · ${source.supplier_name}` : undefined}
      onClose={onClose}
      busy={busy}
      size="medium"
      footerLead={blocker ?? undefined}
      footer={
        <>
          <DialogCancel />
          <Button variant="primary" icon={<GoodsReceiptIcon size={15} />} busy={busy} disabled={Boolean(blocker)} onClick={submit}>
            Book in
          </Button>
        </>
      }
    >
      <div className="stack">
        {error ? <Notice kind="error">{error}</Notice> : null}
        {order.error ? <Notice kind="error">{order.error}</Notice> : null}

        {sources.length > 1 ? (
          <Segmented
            label="Purchase order"
            value={source?.purchase_order_item_id ?? ''}
            onChange={setSourceId}
            options={sources.map((entry: IncomingSource) => ({
              value: entry.purchase_order_item_id,
              label: entry.po_number,
            }))}
          />
        ) : null}

        {!poLine ? (
          <Loading label="Loading the purchase order…" />
        ) : (
          <>
            <p className="hint">
              {formatQuantity(poLine.quantity_remaining)} {row.unit_of_measure} still due on this purchase order at{' '}
              {formatUnitPrice(poLine.unit_cost)}
              {order.data?.expected_delivery_date ? `, expected ${formatDate(order.data.expected_delivery_date)}` : ''}.
              Stock does not change — it counted when the order was placed.
            </p>
            <FormGrid>
              <Field label={`Arrived (${row.unit_of_measure})`}>
                {(props) => (
                  <input
                    {...props}
                    className="input input--num"
                    type="number"
                    step="0.001"
                    min="0"
                    max={poLine.quantity_remaining}
                    inputMode="decimal"
                    value={quantity}
                    onChange={(event) => setQuantity(event.target.value)}
                  />
                )}
              </Field>
              <Field label="Supplier's delivery note" optional>
                {(props) => (
                  <input {...props} value={reference} placeholder="e.g. DC-4471" onChange={(event) => setReference(event.target.value)} />
                )}
              </Field>
            </FormGrid>
          </>
        )}

        {line && line.allocations.length > 0 ? (
          <div className="stack stack--tight">
            <div className="row row--between">
              <span className="section-label">Who gets it</span>
              {remainingUnits === 0 ? (
                <span className="chip chip--ok">
                  <CheckIcon size={13} strokeWidth={2.6} /> Balanced
                </span>
              ) : remainingUnits > 0 ? (
                <span className="chip chip--todo">{formatQuantity(fromUnits(remainingUnits))} left to give</span>
              ) : (
                <span className="chip chip--over">{formatQuantity(fromUnits(-remainingUnits))} over</span>
              )}
            </div>
            <TableScroll>
              <table className="table table--compact">
                <thead>
                  <tr>
                    <th>Customer · order</th>
                    <th className="num">On order</th>
                    <th className="num">Short</th>
                    <th className="num">Give</th>
                  </tr>
                </thead>
                <tbody>
                  {line.allocations.map((entry) => {
                    const value = amounts[entry.order_item_id] ?? ''
                    const rowError = rowErrors[entry.order_item_id]
                    const isThis = entry.order_item_id === row.order_item_id
                    return (
                      <tr key={entry.order_item_id} className={toUnits(value) > 0 ? 'is-highlighted' : undefined}>
                        <td>
                          <span className="cell-primary">
                            {entry.customer_name}
                            {isThis ? <span className="muted"> · this line</span> : null}
                          </span>
                          <span className="cell-sub mono">{entry.order_number}</span>
                        </td>
                        <td className="num">
                          {toUnits(entry.quantity_eligible) - toUnits(entry.quantity_unallocated) > 0 ? (
                            <span className="q-owed">
                              {formatQuantity(fromUnits(toUnits(entry.quantity_eligible) - toUnits(entry.quantity_unallocated)))}
                            </span>
                          ) : (
                            <span className="q-muted">—</span>
                          )}
                        </td>
                        <td className="num">
                          {toUnits(entry.quantity_unallocated) > 0 ? (
                            <span className="q-awaiting">{formatQuantity(entry.quantity_unallocated)}</span>
                          ) : (
                            <span className="q-muted">—</span>
                          )}
                        </td>
                        <td className="num">
                          <input
                            className="input input--sm input--num input--inline"
                            type="number"
                            step="0.001"
                            min="0"
                            max={entry.quantity_eligible}
                            inputMode="decimal"
                            placeholder="0"
                            aria-label={`Give to ${entry.customer_name}, ${entry.order_number}`}
                            aria-invalid={rowError ? true : undefined}
                            value={value}
                            onChange={(event) => setAmounts((current) => ({ ...current, [entry.order_item_id]: event.target.value }))}
                          />
                          {rowError ? <span className="field__error">{rowError}</span> : null}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </TableScroll>
            {line && toUnits(line.surplus_quantity) > 0 ? (
              <p className="hint">
                {formatQuantity(line.surplus_quantity)} {row.unit_of_measure} is not owed to anyone and goes into free
                stock.
              </p>
            ) : null}
          </div>
        ) : null}
      </div>
    </Dialog>
  )
}
