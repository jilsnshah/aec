import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { PendingOrders } from '../api/types'
import { fromUnits, sumUnits, toUnits } from '../lib/decimal'
import { formatDateTime, formatQuantity } from '../lib/format'
import { useAsync } from '../lib/useAsync'
import { Button, Card, Loading, Notice, TableScroll } from './ui'
import { CheckIcon } from './icons'

/** One product being bought, and how much of it is free to settle with. */
export interface SettleLine {
  productId: string
  /** Units of this purchase not yet promised to anybody. */
  quantity: string
}

interface ProductState {
  data: PendingOrders
  requiredUnits: number
  allocatedUnits: number
  remainingUnits: number
  rowErrors: Record<string, string>
}

/**
 * A purchase counts as stock the moment it is placed, so it must settle
 * customers who are short: exactly `min(quantity bought, quantity short)` per
 * product. Who gets it and how much each is the user's choice; every amount
 * starts at zero.
 */
export function useSettlement(
  lines: SettleLine[],
  /** product id -> sales order line id -> quantity, to start from */
  initialAmounts?: Record<string, Record<string, string>>,
) {
  const key = lines
    .filter((line) => line.productId)
    .map((line) => line.productId)
    .sort()
    .join(',')
  const waiting = useAsync<PendingOrders[]>(
    () =>
      Promise.all(
        key ? key.split(',').map((productId) => api.products.pendingOrders(productId)) : [],
      ),
    [key],
  )
  // product id -> order item id -> typed quantity
  const [amounts, setAmounts] = useState<Record<string, Record<string, string>>>(initialAmounts ?? {})

  const products = useMemo(() => {
    const quantityByProduct = new Map<string, number>()
    for (const line of lines) {
      if (!line.productId) continue
      const units = toUnits(line.quantity)
      quantityByProduct.set(
        line.productId,
        (quantityByProduct.get(line.productId) ?? 0) + (Number.isFinite(units) ? units : 0),
      )
    }
    const states: ProductState[] = []
    for (const data of waiting.data ?? []) {
      if (data.items.length === 0) continue
      const typed = amounts[data.product_id] ?? {}
      const rowErrors: Record<string, string> = {}
      for (const row of data.items) {
        const raw = typed[row.order_item_id] ?? ''
        if (raw.trim() === '') continue
        const units = toUnits(raw)
        if (!Number.isFinite(units) || units < 0) rowErrors[row.order_item_id] = 'Enter zero or more.'
        else if (units > toUnits(row.quantity_unallocated)) {
          rowErrors[row.order_item_id] = `Only ${formatQuantity(row.quantity_unallocated)} is short.`
        }
      }
      const shortUnits = sumUnits(data.items.map((row) => toUnits(row.quantity_unallocated)))
      const requiredUnits = Math.min(quantityByProduct.get(data.product_id) ?? 0, shortUnits)
      const allocatedUnits = sumUnits(
        data.items.map((row) => toUnits(typed[row.order_item_id] ?? '0') || 0),
      )
      states.push({
        data,
        requiredUnits,
        allocatedUnits,
        remainingUnits: requiredUnits - allocatedUnits,
        rowErrors,
      })
    }
    return states.filter((state) => state.requiredUnits > 0)
  }, [waiting.data, amounts, lines])

  function setRow(productId: string, orderItemId: string, value: string) {
    setAmounts((current) => ({
      ...current,
      [productId]: { ...(current[productId] ?? {}), [orderItemId]: value },
    }))
  }

  /** A shortcut only: spread the required amount over the oldest orders. */
  function fillOldestFirst(state: ProductState) {
    let left = state.requiredUnits
    const next: Record<string, string> = {}
    for (const row of state.data.items) {
      const take = Math.max(0, Math.min(left, toUnits(row.quantity_unallocated)))
      next[row.order_item_id] = fromUnits(take)
      left -= take
    }
    setAmounts((current) => ({ ...current, [state.data.product_id]: next }))
  }

  function clear(productId: string) {
    setAmounts((current) => ({ ...current, [productId]: {} }))
  }

  const blockers: string[] = []
  for (const state of products) {
    const sku = state.data.product_sku
    if (Object.keys(state.rowErrors).length > 0) blockers.push(`${sku}: fix the highlighted amounts.`)
    else if (state.remainingUnits > 0) {
      blockers.push(`${sku}: settle ${formatQuantity(fromUnits(state.remainingUnits))} more for short customers.`)
    } else if (state.remainingUnits < 0) {
      blockers.push(`${sku}: settle ${formatQuantity(fromUnits(-state.remainingUnits))} less.`)
    }
  }

  /** The request body: who each product settles, as the user chose. */
  function settlements() {
    return products.map((state) => ({
      product_id: state.data.product_id,
      allocations: state.data.items
        .map((row) => ({
          order_item_id: row.order_item_id,
          quantity: (amounts[state.data.product_id] ?? {})[row.order_item_id] ?? '0',
        }))
        .filter((entry) => toUnits(entry.quantity) > 0),
    }))
  }

  return {
    loading: waiting.loading,
    error: waiting.error,
    products,
    amounts,
    setRow,
    fillOldestFirst,
    clear,
    blockers,
    settlements,
  }
}

export type Settlement = ReturnType<typeof useSettlement>

/** The tables where the user types how much each short customer gets. */
export function SettleCustomers({ settlement }: { settlement: Settlement }) {
  if (settlement.error) return <Notice kind="error">{settlement.error}</Notice>
  if (settlement.loading && settlement.products.length === 0) return <Loading label="Checking who is short…" />
  if (settlement.products.length === 0) return null

  return (
    <div className="stack">
      {settlement.products.map((state) => {
        const { data } = state
        const typed = settlement.amounts[data.product_id] ?? {}
        return (
          <Card
            key={data.product_id}
            flush
            title={`Settle short customers · ${data.product_name}`}
            subtitle={`This purchase must settle ${formatQuantity(fromUnits(state.requiredUnits))} ${data.unit_of_measure}. You choose who gets it.`}
          >
            <div className="card__toolbar">
              {state.remainingUnits === 0 ? (
                <span className="chip chip--ok">
                  <CheckIcon size={13} strokeWidth={2.6} /> Settled
                </span>
              ) : state.remainingUnits > 0 ? (
                <span className="chip chip--todo">
                  {formatQuantity(fromUnits(state.remainingUnits))} left to settle
                </span>
              ) : (
                <span className="chip chip--over">{formatQuantity(fromUnits(-state.remainingUnits))} over</span>
              )}
              <div className="grow" />
              <Button size="sm" variant="plain" onClick={() => settlement.fillOldestFirst(state)}>
                Fill oldest first
              </Button>
              <Button size="sm" variant="plain" onClick={() => settlement.clear(data.product_id)} disabled={state.allocatedUnits === 0}>
                Clear
              </Button>
            </div>
            <TableScroll>
              <table className="table table--compact">
                <thead>
                  <tr>
                    <th>Customer · order</th>
                    <th className="num">Short</th>
                    <th className="num">Settle</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((row) => {
                    const value = typed[row.order_item_id] ?? ''
                    const error = state.rowErrors[row.order_item_id]
                    return (
                      <tr key={row.order_item_id} className={toUnits(value) > 0 ? 'is-highlighted' : undefined}>
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
                        <td className="num q-awaiting">{formatQuantity(row.quantity_unallocated)}</td>
                        <td className="num">
                          <input
                            className="input input--sm input--num input--inline"
                            type="number"
                            step="0.001"
                            min="0"
                            max={row.quantity_unallocated}
                            inputMode="decimal"
                            placeholder="0"
                            aria-label={`Settle for ${row.customer_name}, ${row.order_number}`}
                            aria-invalid={error ? true : undefined}
                            value={value}
                            onChange={(event) => settlement.setRow(data.product_id, row.order_item_id, event.target.value)}
                          />
                          {error ? <span className="field__error">{error}</span> : null}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </TableScroll>
          </Card>
        )
      })}
    </div>
  )
}
