import { useMemo, useState } from 'react'
import { ApiError, api } from '../api/client'
import type { DeliveryResult, OrderFulfilment } from '../api/types'
import { fromUnits, isValidQuantity, sumUnits, toUnits } from '../lib/decimal'
import { ALLOCATION_SOURCE_LABELS, formatQuantity } from '../lib/format'
import { useIdempotencyKey } from '../lib/ids'
import { useAsync } from '../lib/useAsync'
import { DeliveryIcon, GoodsReceiptIcon } from './icons'
import { Dialog, DialogCancel } from './overlays'
import { Button, EmptyState, LinkButton, Loading, Notice } from './primitives'
import { Field, FormGrid } from './forms'
import { TableScroll } from './table'

/** Hand reserved stock to a customer. The dialog is the review step: it shows
 *  exactly what will leave, and the action button says how much. */
export function DeliverDialog({
  orderId,
  orderNumber,
  focusItemId,
  onClose,
  onDelivered,
}: {
  orderId: string
  orderNumber: string
  /** Prefill only this line; otherwise every deliverable line is prefilled. */
  focusItemId?: string
  onClose: () => void
  onDelivered: (result: DeliveryResult) => void
}) {
  const fulfilment = useAsync<OrderFulfilment>(() => api.fulfilment.order(orderId), [orderId])
  const [quantities, setQuantities] = useState<Record<string, string>>({})
  const [reference, setReference] = useState('')
  const [notes, setNotes] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [idempotencyKey] = useIdempotencyKey()

  const deliverable = useMemo(
    () => (fulfilment.data?.lines ?? []).filter((line) => Number(line.quantity_deliverable) > 0),
    [fulfilment.data],
  )

  function quantityFor(itemId: string, max: string) {
    const typed = quantities[itemId]
    if (typed !== undefined) return typed
    return !focusItemId || focusItemId === itemId ? max : '0'
  }

  const rowErrors: Record<string, string> = {}
  for (const line of deliverable) {
    const raw = quantityFor(line.order_item_id, line.quantity_deliverable)
    if (raw.trim() === '') continue
    if (!isValidQuantity(raw)) rowErrors[line.order_item_id] = 'Enter zero or more.'
    else if (toUnits(raw) > toUnits(line.quantity_deliverable)) {
      rowErrors[line.order_item_id] = `Only ${formatQuantity(line.quantity_deliverable)} is in stock for this line.`
    }
  }
  const totalUnits = sumUnits(
    deliverable.map((line) => toUnits(quantityFor(line.order_item_id, line.quantity_deliverable)) || 0),
  )
  const canSubmit = Object.keys(rowErrors).length === 0 && totalUnits > 0 && !saving

  async function submit() {
    if (!canSubmit) return
    setSaving(true)
    setError(null)
    try {
      onDelivered(
        await api.fulfilment.deliver(orderId, {
          reference: reference.trim() || null,
          notes: notes.trim() || null,
          idempotency_key: idempotencyKey,
          lines: deliverable
            .map((line) => ({
              order_item_id: line.order_item_id,
              quantity: quantityFor(line.order_item_id, line.quantity_deliverable),
            }))
            .filter((line) => toUnits(line.quantity) > 0),
        }),
      )
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : String(cause))
      setSaving(false)
    }
  }

  const amount = formatQuantity(fromUnits(totalUnits))

  return (
    <Dialog
      title={`Deliver against ${orderNumber}`}
      subtitle={fulfilment.data ? `To ${fulfilment.data.customer_name}` : undefined}
      onClose={onClose}
      busy={saving}
      size="medium"
      footerLead={totalUnits > 0 ? 'Stock leaves inventory. This cannot be undone.' : undefined}
      footer={
        <>
          <DialogCancel />
          <Button
            variant="primary"
            icon={<DeliveryIcon size={15} />}
            onClick={submit}
            busy={saving}
            disabled={!canSubmit}
          >
            {totalUnits > 0 ? `Deliver ${amount}` : 'Deliver'}
          </Button>
        </>
      }
    >
      <div className="stack stack--tight">
        {error ? <Notice kind="error" title="The delivery was not recorded">{error}</Notice> : null}
        {fulfilment.error ? <Notice kind="error">{fulfilment.error}</Notice> : null}
        {fulfilment.loading && !fulfilment.data ? <Loading /> : null}

        {fulfilment.data && deliverable.length === 0 ? (
          <EmptyState
            compact
            icon={<GoodsReceiptIcon size={22} />}
            title="Nothing is in stock for this order yet"
            body="When stock arrives, waiting orders are served first, oldest order first."
            action={
              <LinkButton to="/goods-receipts" variant="tinted">
                Receive goods
              </LinkButton>
            }
          />
        ) : null}

        {deliverable.length > 0 ? (
          <>
            <div className="card card--inset">
              <TableScroll>
                <table className="table table--compact">
                  <thead>
                    <tr>
                      <th>Product</th>
                      <th className="num">To deliver</th>
                      <th className="num">Ready</th>
                      <th className="num">Deliver now</th>
                    </tr>
                  </thead>
                  <tbody>
                    {deliverable.map((line) => {
                      const rowError = rowErrors[line.order_item_id]
                      const sources = line.reservations
                        .filter((entry) => Number(entry.quantity_open) > 0)
                        .map(
                          (entry) =>
                            `${formatQuantity(entry.quantity_open)} ${(
                              ALLOCATION_SOURCE_LABELS[entry.source] ?? entry.source
                            ).toLowerCase()}`,
                        )
                      return (
                        <tr key={line.order_item_id}>
                          <td>
                            <span className="cell-primary">{line.product_name}</span>
                            <span className="cell-sub">
                              <span className="mono">{line.product_sku}</span>
                              {sources.length ? ` · ${sources.join('; ')}` : ''}
                            </span>
                          </td>
                          <td className="num">{formatQuantity(line.quantity_outstanding)}</td>
                          <td className="num">
                            <span className="q-reserved">{formatQuantity(line.quantity_reserved)}</span>
                          </td>
                          <td className="num">
                            <input
                              className="input input--sm input--num input--inline"
                              type="number"
                              step="0.001"
                              min="0"
                              max={line.quantity_deliverable}
                              inputMode="decimal"
                              aria-label={`Deliver ${line.product_sku}`}
                              aria-invalid={rowError ? true : undefined}
                              value={quantityFor(line.order_item_id, line.quantity_deliverable)}
                              onChange={(event) =>
                                setQuantities((current) => ({
                                  ...current,
                                  [line.order_item_id]: event.target.value,
                                }))
                              }
                            />
                            {rowError ? <div className="field__error">{rowError}</div> : null}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </TableScroll>
            </div>
            <FormGrid>
              <Field label="Reference" optional>
                {(props) => (
                  <input
                    {...props}
                    value={reference}
                    onChange={(event) => setReference(event.target.value)}
                    placeholder="Van 3, courier docket…"
                  />
                )}
              </Field>
              <Field label="Note" optional>
                {(props) => (
                  <input {...props} value={notes} onChange={(event) => setNotes(event.target.value)} />
                )}
              </Field>
            </FormGrid>
          </>
        ) : null}
      </div>
    </Dialog>
  )
}
