import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import type { OrderDetail } from '../api/types'
import {
  ActionMenu,
  AsyncBlock,
  Badge,
  Button,
  Card,
  CardBody,
  ConfirmDialog,
  EmptyState,
  KeyValue,
  LinkButton,
  MetricStrip,
  Notice,
  Page,
  Quantity,
  StatusBadge,
  TableScroll,
  Toolbar,
  useToast,
} from '../components/ui'
import { DeliverDialog } from '../components/DeliverDialog'
import { CancelIcon, DeliveryIcon, GoodsReceiptIcon, PurchaseOrderIcon } from '../components/icons'
import {
  ALLOCATION_SOURCE_LABELS,
  formatAmount,
  formatDateTime,
  formatMoney,
  formatPercent,
  formatQuantity,
  formatUnitPrice,
} from '../lib/format'
import { useAsync } from '../lib/useAsync'

type CancelMode = 'full' | 'remaining'

function totalsOf(order: OrderDetail) {
  return order.items.reduce(
    (acc, item) => ({
      ordered: acc.ordered + Number(item.quantity_ordered),
      delivered: acc.delivered + Number(item.quantity_fulfilled),
      reserved: acc.reserved + Number(item.quantity_reserved),
      awaiting: acc.awaiting + Number(item.quantity_unallocated),
      incoming: acc.incoming + Number(item.quantity_incoming),
      owed: acc.owed + Number(item.quantity_pending),
      cancelled: acc.cancelled + Number(item.quantity_cancelled),
    }),
    { ordered: 0, delivered: 0, reserved: 0, awaiting: 0, incoming: 0, owed: 0, cancelled: 0 },
  )
}

export default function OrderDetailPage() {
  const { orderId = '' } = useParams()
  const toast = useToast()
  const { data, loading, error, reload } = useAsync(() => api.orders.get(orderId), [orderId])
  const [cancelling, setCancelling] = useState<CancelMode | null>(null)
  const [delivering, setDelivering] = useState(false)

  const totals = data ? totalsOf(data) : null
  const open = data ? data.status !== 'CANCELLED' : false

  const menuItems = data && totals && open
    ? [
        totals.delivered > 0
          ? {
              label: `Cancel remaining ${formatQuantity(totals.owed)}`,
              icon: <CancelIcon size={15} />,
              destructive: true,
              disabled: totals.owed <= 0,
              onSelect: () => setCancelling('remaining' as const),
            }
          : {
              label: 'Cancel order',
              icon: <CancelIcon size={15} />,
              destructive: true,
              onSelect: () => setCancelling('full' as const),
            },
      ]
    : []

  return (
    <Page>
      <Toolbar
        back={{ to: '/orders', label: 'Sales Orders' }}
        title={<span className="mono">{data?.order_number ?? 'Order'}</span>}
        documentTitle={data?.order_number ?? 'Order'}
        badge={data ? <StatusBadge status={data.status} /> : undefined}
        subtitle={
          data ? (
            <>
              <Link to={`/customers/${data.customer_id}`}>{data.customer.name}</Link> · placed{' '}
              {formatDateTime(data.created_at)}
              {data.enquiry_number ? (
                <>
                  {' '}
                  · from <Link to={`/enquiries/${data.enquiry_id}`} className="mono">{data.enquiry_number}</Link>
                </>
              ) : null}
            </>
          ) : undefined
        }
        actions={
          data && totals ? (
            <>
              {totals.awaiting > 0 && open ? (
                <LinkButton to="/purchase-orders?new=1" icon={<PurchaseOrderIcon size={15} />}>
                  Buy stock
                </LinkButton>
              ) : totals.incoming > 0 && open ? (
                <LinkButton to="/goods-receipts" icon={<GoodsReceiptIcon size={15} />}>
                  Receive goods
                </LinkButton>
              ) : null}
              {totals.reserved > 0 && open ? (
                <Button variant="primary" icon={<DeliveryIcon size={15} />} onClick={() => setDelivering(true)}>
                  Deliver {formatQuantity(totals.reserved)}
                </Button>
              ) : null}
              {menuItems.length > 0 ? (
                <ActionMenu variant="secondary" size="md" label="More order actions" items={menuItems} />
              ) : null}
            </>
          ) : undefined
        }
      />

      <AsyncBlock loading={loading} error={error} data={data} onRetry={reload} skeleton="spinner">
        {(order) => {
          const t = totalsOf(order)
          const money = order.financials?.totals
          return (
            <div className="stack">
              {order.status === 'CANCELLED' ? (
                <Notice kind="warning" title="This order was cancelled">
                  {order.cancelled_at ? `On ${formatDateTime(order.cancelled_at)}. ` : ''}It is kept
                  for the record; nothing more can be delivered against it.
                </Notice>
              ) : null}

              <MetricStrip
                items={[
                  { label: 'Ordered', value: formatQuantity(t.ordered) },
                  { label: 'Delivered', value: formatQuantity(t.delivered), dot: 'var(--stock-delivered)' },
                  {
                    label: 'Ready to deliver',
                    value: formatQuantity(t.reserved),
                    hint: 'in stock, truck not gone yet',
                    tone: t.reserved > 0 ? 'reserved' : undefined,
                    dot: 'var(--stock-reserved)',
                  },
                  {
                    label: 'On order',
                    value: formatQuantity(t.incoming),
                    hint: 'bought, not arrived yet',
                    tone: t.incoming > 0 ? 'owed' : undefined,
                    dot: 'var(--stock-owed)',
                  },
                  {
                    label: 'Short',
                    value: formatQuantity(t.awaiting),
                    hint: t.awaiting > 0 ? 'nothing bought for it yet' : 'all covered',
                    tone: t.awaiting > 0 ? 'negative' : undefined,
                    dot: 'var(--stock-short)',
                  },
                  { label: 'Order value', value: formatMoney(order.total_amount), hint: 'before tax' },
                ]}
              />

              <Card title="Lines" flush>
                <TableScroll>
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Product</th>
                        <th className="num">Price</th>
                        <th className="num">Ordered</th>
                        <th className="num">Delivered</th>
                        <th className="num">Ready</th>
                        <th className="num">On order</th>
                        <th className="num">Short</th>
                        <th className="num">To deliver</th>
                        <th className="col-progress">Progress</th>
                        <th className="num">Total</th>
                      </tr>
                    </thead>
                    <tbody>
                      {order.items.map((item) => {
                        const ordered = Number(item.quantity_ordered) || 1
                        const pct = (value: string) => `${(Number(value) / ordered) * 100}%`
                        return (
                          <tr key={item.id}>
                            <td>
                              <span className="cell-primary">{item.product.name}</span>
                              <span className="cell-sub">
                                <span className="mono">{item.product.sku}</span> · {item.product.unit_of_measure}
                              </span>
                            </td>
                            <td className="num">
                              {formatUnitPrice(item.unit_price_net)}
                              {Number(item.discount_percent) > 0 ? (
                                <span className="cell-sub">
                                  {formatPercent(item.discount_percent)} off {formatAmount(item.unit_price)}
                                </span>
                              ) : item.mrp_snapshot && item.mrp_snapshot !== item.unit_price ? (
                                <span className="cell-sub">MRP {formatAmount(item.mrp_snapshot)}</span>
                              ) : null}
                            </td>
                            <td className="num">{formatQuantity(item.quantity_ordered)}</td>
                            <td className="num">
                              <Quantity value={item.quantity_fulfilled} />
                            </td>
                            <td className="num">
                              <Quantity value={item.quantity_reserved} tone="reserved" />
                            </td>
                            <td className="num">
                              <Quantity value={item.quantity_incoming} tone="owed" />
                            </td>
                            <td className="num">
                              <Quantity value={item.quantity_unallocated} tone="awaiting" />
                            </td>
                            <td className="num">
                              <Quantity value={item.quantity_pending} tone="strong" />
                              {Number(item.quantity_cancelled) > 0 ? (
                                <span className="cell-sub">{formatQuantity(item.quantity_cancelled)} cancelled</span>
                              ) : null}
                            </td>
                            <td>
                              <div
                                className="bar"
                                title={`${formatQuantity(item.quantity_fulfilled)} delivered, ${formatQuantity(item.quantity_reserved)} ready, ${formatQuantity(item.quantity_incoming)} on order, ${formatQuantity(item.quantity_unallocated)} short`}
                              >
                                <span className="bar__delivered" style={{ width: pct(item.quantity_fulfilled) }} />
                                <span className="bar__reserved" style={{ width: pct(item.quantity_reserved) }} />
                                <span className="bar__owed" style={{ width: pct(item.quantity_incoming) }} />
                                <span className="bar__short" style={{ width: pct(item.quantity_unallocated) }} />
                                <span className="bar__cancelled" style={{ width: pct(item.quantity_cancelled) }} />
                              </div>
                            </td>
                            <td className="num cell-primary">
                              {formatAmount(Number(item.unit_price_net) * Number(item.quantity_ordered))}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </TableScroll>
                <div className="card__footer">
                  <div className="legend">
                    <span><i style={{ background: 'var(--stock-delivered)' }} /> Delivered</span>
                    <span><i style={{ background: 'var(--stock-reserved)' }} /> Ready to deliver</span>
                    <span><i style={{ background: 'var(--stock-owed)' }} /> On order</span>
                    <span><i style={{ background: 'var(--stock-short)' }} /> Short</span>
                    <span><i style={{ background: 'var(--fill-3)' }} /> Cancelled</span>
                  </div>
                </div>
              </Card>

              <div className="columns columns--main-aside">
                <div className="stack">
                  <Card title="Delivered stock" subtitle="Where every delivered unit came from, and what it cost" flush>
                    {order.allocations.length === 0 ? (
                      <EmptyState
                        compact
                        title="Nothing delivered yet"
                        body={
                          t.reserved > 0
                            ? 'Goods are in stock and ready to load.'
                            : 'When stock arrives this order is served first, oldest order first.'
                        }
                      />
                    ) : (
                      <TableScroll>
                        <table className="table table--compact">
                          <thead>
                            <tr>
                              <th>When</th>
                              <th>Product</th>
                              <th>Stock source</th>
                              <th className="num">Quantity</th>
                              <th className="num">Cost of goods</th>
                            </tr>
                          </thead>
                          <tbody>
                            {order.allocations.map((allocation) => (
                              <tr key={allocation.allocation_id}>
                                <td className="nowrap">{formatDateTime(allocation.created_at)}</td>
                                <td>
                                  {allocation.product_name}
                                  <span className="cell-sub mono">{allocation.product_sku}</span>
                                </td>
                                <td className="muted">
                                  {ALLOCATION_SOURCE_LABELS[allocation.source] ?? allocation.source}
                                </td>
                                <td className="num">{formatQuantity(allocation.quantity)}</td>
                                <td className="num">{formatAmount(allocation.cost_amount)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </TableScroll>
                    )}
                  </Card>

                  {order.cancellations.length > 0 ? (
                    <Card title="Cancellations" flush>
                      <TableScroll>
                        <table className="table table--compact">
                          <thead>
                            <tr>
                              <th>When</th>
                              <th>What</th>
                              <th className="num">Quantity</th>
                              <th>Reason</th>
                            </tr>
                          </thead>
                          <tbody>
                            {order.cancellations.map((row) => (
                              <tr key={row.id}>
                                <td className="nowrap">{formatDateTime(row.created_at)}</td>
                                <td>{row.kind === 'FULL' ? 'Whole order' : 'Undelivered remainder'}</td>
                                <td className="num">{formatQuantity(row.quantity_cancelled)}</td>
                                <td className="muted">{row.reason ?? '—'}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </TableScroll>
                    </Card>
                  ) : null}
                </div>

                <div className="stack">
                  {money ? (
                    <Card title="Bill and profit" subtitle="Profit counts delivered goods only">
                      <CardBody>
                        <KeyValue
                          stacked
                          items={[
                            { label: 'Subtotal', value: formatAmount(money.subtotal_amount) },
                            {
                              label: 'Discount',
                              value:
                                Number(money.discount_amount) > 0 ? (
                                  <span className="q-negative">−{formatAmount(money.discount_amount)}</span>
                                ) : (
                                  '—'
                                ),
                            },
                            { label: 'Order total', value: formatMoney(money.total_amount), total: true },
                            { label: 'Delivered', value: formatAmount(money.delivered_amount) },
                            { label: 'Cost of goods', value: formatAmount(money.cost_of_goods_sold) },
                            {
                              label: 'Gross profit',
                              value: (
                                <span className={Number(money.gross_profit) < 0 ? 'q-negative' : 'q-available'}>
                                  {formatAmount(money.gross_profit)}
                                </span>
                              ),
                            },
                            {
                              label: 'Margin',
                              value: Number(money.delivered_amount) > 0 ? formatPercent(money.margin_percent) : '—',
                            },
                            { label: 'Still to deliver', value: formatAmount(money.pending_amount) },
                          ]}
                        />
                      </CardBody>
                    </Card>
                  ) : null}

                  <Card title="Details">
                    <CardBody>
                      <KeyValue
                        stacked
                        items={[
                          {
                            label: 'Customer',
                            value: <Link to={`/customers/${order.customer_id}`}>{order.customer.name}</Link>,
                          },
                          { label: 'Placed', value: formatDateTime(order.created_at) },
                          { label: 'Updated', value: formatDateTime(order.updated_at) },
                          {
                            label: 'Source',
                            value: order.enquiry_number ? (
                              <Link to={`/enquiries/${order.enquiry_id}`}>
                                <Badge tone="indigo">{order.enquiry_number}</Badge>
                              </Link>
                            ) : (
                              'Entered directly'
                            ),
                          },
                        ]}
                      />
                      {order.notes ? (
                        <p className="t-callout muted mt-3 pre-line">
                          {order.notes}
                        </p>
                      ) : null}
                    </CardBody>
                  </Card>
                </div>
              </div>
            </div>
          )
        }}
      </AsyncBlock>

      {delivering && data ? (
        <DeliverDialog
          orderId={data.id}
          orderNumber={data.order_number}
          onClose={() => setDelivering(false)}
          onDelivered={(result) => {
            setDelivering(false)
            toast.success(
              `${result.delivery_number} recorded`,
              Number(result.order_outstanding_after) > 0
                ? `${formatQuantity(result.total_delivered)} delivered · ${formatQuantity(result.order_outstanding_after)} still to deliver`
                : `${formatQuantity(result.total_delivered)} delivered · order complete`,
            )
            reload()
          }}
        />
      ) : null}

      {cancelling && data ? (
        <CancelOrder
          order={data}
          mode={cancelling}
          onClose={() => setCancelling(null)}
          onDone={(message) => {
            setCancelling(null)
            toast.success(message)
            reload()
          }}
        />
      ) : null}
    </Page>
  )
}

function CancelOrder({
  order,
  mode,
  onClose,
  onDone,
}: {
  order: OrderDetail
  mode: CancelMode
  onClose: () => void
  onDone: (message: string) => void
}) {
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const t = totalsOf(order)

  async function confirm() {
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      if (mode === 'full') {
        await api.orders.cancel(order.id, reason.trim() || undefined)
        onDone(`${order.order_number} cancelled`)
      } else {
        await api.orders.cancelRemaining(order.id, reason.trim() || undefined)
        onDone(`Remainder of ${order.order_number} cancelled`)
      }
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : String(cause))
      setBusy(false)
    }
  }

  return (
    <ConfirmDialog
      title={mode === 'full' ? `Cancel ${order.order_number}?` : 'Cancel what is still to deliver?'}
      confirmLabel={mode === 'full' ? 'Cancel order' : 'Cancel remainder'}
      destructive
      busy={busy}
      error={error}
      onCancel={onClose}
      onConfirm={confirm}
      icon={<CancelIcon size={19} />}
      message={
        <>
          <p>
            {mode === 'full'
              ? 'Nothing has been delivered, so the whole order can be cancelled. It stays on record.'
              : `${formatQuantity(t.owed)} still to deliver will be cancelled. The ${formatQuantity(t.delivered)} already delivered is not reversed.`}
            {t.reserved > 0 ? ` ${formatQuantity(t.reserved)} reserved goes back into available stock.` : ''}
          </p>
          <div className="field mt-3">
            <label className="field__label" htmlFor="cancel-reason">
              Reason <span className="field__optional">Optional</span>
            </label>
            <textarea
              id="cancel-reason"
              className="input"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              disabled={busy}
            />
          </div>
        </>
      }
    />
  )
}
