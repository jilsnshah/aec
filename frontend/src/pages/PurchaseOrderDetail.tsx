import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import type { PurchaseOrder } from '../api/types'
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
  KeyValue,
  LinkButton,
  MetricStrip,
  Notice,
  Page,
  PurchaseStatusBadge,
  TableScroll,
  Toolbar,
  useToast,
} from '../components/ui'
import { CancelIcon, CheckIcon, GoodsReceiptIcon, PlaceOrderIcon } from '../components/icons'
import {
  formatAmount,
  formatDate,
  formatDateTime,
  formatMoney,
  formatQuantity,
  formatUnitPrice,
} from '../lib/format'
import { useAsync } from '../lib/useAsync'
import { SettleCustomers, useSettlement } from '../components/SettleCustomers'
import { TallyStatus } from '../components/TallyStatus'

export default function PurchaseOrderDetailPage() {
  const { poId = '' } = useParams()
  const toast = useToast()
  const { data, loading, error, reload } = useAsync(() => api.purchaseOrders.get(poId), [poId])
  const [action, setAction] = useState<'confirm' | 'cancel' | 'settle' | null>(null)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  async function cancel(reason?: string) {
    if (busy || !data) return
    setBusy(true)
    setActionError(null)
    try {
      await api.purchaseOrders.cancel(data.id, reason || undefined)
      toast.success(`${data.po_number} cancelled`, 'Anything already received stays received.')
      setAction(null)
      reload()
    } catch (cause) {
      setActionError(cause instanceof ApiError ? cause.message : String(cause))
      setAction(null)
    } finally {
      setBusy(false)
    }
  }

  const cancellable = data && data.status !== 'CANCELLED' && data.status !== 'RECEIVED'
  const toSettle = data ? data.items.reduce((sum, item) => sum + Number(item.settle_required), 0) : 0

  return (
    <Page>
      <Toolbar
        back={{ to: '/purchase-orders', label: 'Purchase Orders' }}
        title={<span className="mono">{data?.po_number ?? 'Purchase order'}</span>}
        documentTitle={data?.po_number ?? 'Purchase order'}
        badge={data ? <PurchaseStatusBadge status={data.status} /> : undefined}
        subtitle={data ? `${data.supplier.name} · raised ${formatDateTime(data.created_at)}` : undefined}
        actions={
          data ? (
            <>
              {data.status === 'DRAFT' ? (
                <Button variant="primary" icon={<PlaceOrderIcon size={15} />} onClick={() => setAction('confirm')}>
                  Place order
                </Button>
              ) : null}
              {toSettle > 0 ? (
                <Button icon={<PlaceOrderIcon size={15} />} onClick={() => setAction('settle')}>
                  Settle {formatQuantity(toSettle)}
                </Button>
              ) : null}
              {data.can_receive ? (
                <LinkButton variant="primary" icon={<GoodsReceiptIcon size={15} />} to={`/goods-receipts?po=${data.id}`}>
                  Receive goods
                </LinkButton>
              ) : null}
              {cancellable ? (
                <ActionMenu
                  variant="secondary"
                  size="md"
                  label="More purchase order actions"
                  items={[
                    {
                      label: 'Cancel order',
                      icon: <CancelIcon size={15} />,
                      destructive: true,
                      onSelect: () => setAction('cancel'),
                    },
                  ]}
                />
              ) : null}
            </>
          ) : undefined
        }
      />

      <AsyncBlock loading={loading} error={error} data={data} onRetry={reload} skeleton="spinner">
        {(order) => {
          const progress =
            Number(order.total_ordered) > 0 ? (Number(order.total_received) / Number(order.total_ordered)) * 100 : 0
          return (
            <div className="stack">
              {actionError ? <Notice kind="error">{actionError}</Notice> : null}
              {order.status === 'CANCELLED' ? (
                <Notice kind="warning" title="Cancelled">
                  {formatDateTime(order.cancelled_at)}
                  {order.cancellation_reason ? ` — ${order.cancellation_reason}` : ''}. Anything already received
                  stays received.
                </Notice>
              ) : null}
              {toSettle > 0 ? (
                <Notice kind="warning" title="Customers are short">
                  {formatQuantity(toSettle)} of this order is promised to nobody while customers are short — usually
                  because a sale or another purchase was cancelled. Choose who gets it.
                </Notice>
              ) : null}
              {order.status === 'DRAFT' ? (
                <Notice kind="info" title="Draft">
                  Not yet sent to the supplier. Place it before any goods can be received against it.
                </Notice>
              ) : null}

              <MetricStrip
                items={[
                  { label: 'Ordered', value: formatQuantity(order.total_ordered) },
                  {
                    label: 'Received',
                    value: formatQuantity(order.total_received),
                    hint: `${Math.round(progress)}% of the order`,
                    tone: progress >= 100 ? 'positive' : undefined,
                  },
                  {
                    label: 'Still to arrive',
                    value: formatQuantity(order.total_remaining),
                    tone: Number(order.total_remaining) > 0 && order.status !== 'CANCELLED' ? 'owed' : undefined,
                  },
                  { label: 'Order value', value: formatMoney(order.total_cost), hint: 'at the ordered cost' },
                ]}
              />

              <div className="columns columns--main-aside">
                <div className="stack">
                  <Card title="Lines" flush>
                    <TableScroll>
                      <table className="table">
                        <thead>
                          <tr>
                            <th>Product</th>
                            <th className="num">Cost</th>
                            <th className="num">Ordered</th>
                            <th className="num">Received</th>
                            <th className="num">Remaining</th>
                            <th className="col-progress">Progress</th>
                            <th className="num">Line cost</th>
                          </tr>
                        </thead>
                        <tbody>
                          {order.items.map((item) => {
                            const pct = Math.min(
                              100,
                              (Number(item.quantity_received) / (Number(item.quantity_ordered) || 1)) * 100,
                            )
                            return (
                              <tr key={item.id}>
                                <td>
                                  <span className="cell-primary">{item.product.name}</span>
                                  <span className="cell-sub">
                                    <span className="mono">{item.product.sku}</span> · {item.product.unit_of_measure}
                                  </span>
                                </td>
                                <td className="num">{formatUnitPrice(item.unit_cost)}</td>
                                <td className="num">{formatQuantity(item.quantity_ordered)}</td>
                                <td className="num">{formatQuantity(item.quantity_received)}</td>
                                <td className="num">
                                  {Number(item.quantity_remaining) > 0 ? (
                                    <>
                                      <span className="q-strong">{formatQuantity(item.quantity_remaining)}</span>
                                      {Number(item.quantity_assigned) > 0 ? (
                                        <span className="cell-sub">
                                          {formatQuantity(item.quantity_assigned)} for waiting customers
                                        </span>
                                      ) : null}
                                    </>
                                  ) : (
                                    <span className="q-available">
                                      <CheckIcon size={14} className="icon-inline" /> Complete
                                    </span>
                                  )}
                                </td>
                                <td>
                                  <div className="bar">
                                    <span className="bar__now" style={{ width: `${pct}%` }} />
                                  </div>
                                </td>
                                <td className="num">{formatAmount(item.line_cost)}</td>
                              </tr>
                            )
                          })}
                        </tbody>
                      </table>
                    </TableScroll>
                  </Card>

                  <TallyStatus entityId={order.id} />

                  <Card title="Goods receipts" subtitle={`${order.receipts.length} delivery drop${order.receipts.length === 1 ? '' : 's'}`} flush>
                    {order.receipts.length === 0 ? (
                      <EmptyState
                        compact
                        icon={<GoodsReceiptIcon size={22} />}
                        title="Nothing received yet"
                        body="When a delivery arrives, record it here. Waiting customer orders are served first, automatically."
                        action={
                          order.can_receive ? (
                            <LinkButton variant="tinted" to={`/goods-receipts?po=${order.id}`}>
                              Receive goods
                            </LinkButton>
                          ) : null
                        }
                      />
                    ) : (
                      <TableScroll>
                        <table className="table table--compact">
                          <thead>
                            <tr>
                              <th>Receipt</th>
                              <th>Received</th>
                              <th>Delivery note</th>
                              <th className="num">Quantity</th>
                            </tr>
                          </thead>
                          <tbody>
                            {order.receipts.map((receipt) => (
                              <tr key={receipt.id}>
                                <td className="mono cell-primary">{receipt.receipt_number}</td>
                                <td className="nowrap">{formatDateTime(receipt.created_at)}</td>
                                <td className="muted">{receipt.delivery_note_reference || '—'}</td>
                                <td className="num">{formatQuantity(receipt.total_quantity)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </TableScroll>
                    )}
                  </Card>
                </div>

                <Card title="Details">
                  <CardBody>
                    <KeyValue
                      stacked
                      items={[
                        { label: 'Supplier', value: order.supplier.name },
                        { label: 'Code', value: <span className="mono">{order.supplier.code}</span> },
                        { label: 'Placed', value: order.ordered_at ? formatDateTime(order.ordered_at) : 'Not yet' },
                        {
                          label: 'Expected',
                          value: order.expected_delivery_date ? formatDate(order.expected_delivery_date) : '—',
                        },
                        { label: 'Value', value: formatMoney(order.total_cost), total: true },
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
          )
        }}
      </AsyncBlock>

      {(action === 'confirm' || action === 'settle') && data ? (
        <SettleDialog
          order={data}
          mode={action}
          onClose={() => setAction(null)}
          onDone={(message) => {
            setAction(null)
            toast.success(message.title, message.body)
            reload()
          }}
        />
      ) : null}
      {action === 'cancel' && data ? (
        <CancelPurchaseOrder order={data} busy={busy} onCancel={() => setAction(null)} onConfirm={(reason) => cancel(reason)} />
      ) : null}
    </Page>
  )
}

function CancelPurchaseOrder({
  order,
  busy,
  onCancel,
  onConfirm,
}: {
  order: PurchaseOrder
  busy: boolean
  onCancel: () => void
  onConfirm: (reason: string) => void
}) {
  const [reason, setReason] = useState('')
  return (
    <ConfirmDialog
      title={`Cancel ${order.po_number}?`}
      confirmLabel="Cancel order"
      destructive
      busy={busy}
      onCancel={onCancel}
      onConfirm={() => onConfirm(reason.trim())}
      icon={<CancelIcon size={19} />}
      message={
        <>
          <p>
            No further goods can be received against it. The {formatQuantity(order.total_received)} already received
            stays received, and the order is kept for the record.
          </p>
          <div className="field mt-3">
            <label className="field__label" htmlFor="po-cancel-reason">
              Reason <span className="field__optional">Optional</span>
            </label>
            <textarea
              id="po-cancel-reason"
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


/** Placing an order, or settling what it has free: the user chooses which
 *  short customers get how much. */
function SettleDialog({
  order,
  mode,
  onClose,
  onDone,
}: {
  order: PurchaseOrder
  mode: 'confirm' | 'settle'
  onClose: () => void
  onDone: (message: { title: string; body: string }) => void
}) {
  const settlement = useSettlement(
    order.items.map((item) => ({
      productId: item.product_id,
      quantity: mode === 'confirm' ? item.quantity_ordered : item.quantity_free,
    })),
  )
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    if (busy) return
    // The footer already says what is left to settle.
    if (settlement.blockers.length > 0) return
    setBusy(true)
    setError(null)
    try {
      const body = { settlements: settlement.settlements() }
      if (mode === 'confirm') {
        await api.purchaseOrders.confirm(order.id, body)
        onDone({
          title: `${order.po_number} placed`,
          body: `With ${order.supplier.name}. It counts as stock now; receive the goods when they arrive.`,
        })
      } else {
        await api.purchaseOrders.settle(order.id, body)
        onDone({ title: 'Customers settled', body: `From ${order.po_number}.` })
      }
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : String(cause))
      setBusy(false)
    }
  }

  const nobodyShort = !settlement.loading && settlement.products.length === 0
  return (
    <Dialog
      title={mode === 'confirm' ? `Place ${order.po_number}?` : `Settle from ${order.po_number}`}
      subtitle={
        mode === 'confirm'
          ? `Ordered with ${order.supplier.name}. It counts as stock the moment it is placed.`
          : 'Give what this order has free to customers who are short.'
      }
      onClose={onClose}
      busy={busy}
      size={nobodyShort ? undefined : 'wide'}
      footerLead={settlement.blockers[0]}
      footer={
        <>
          <DialogCancel />
          <Button variant="primary" icon={<PlaceOrderIcon size={15} />} busy={busy} onClick={submit} disabled={settlement.loading}>
            {mode === 'confirm' ? 'Place order' : 'Settle'}
          </Button>
        </>
      }
    >
      <div className="stack">
        {error ? <Notice kind="error">{error}</Notice> : null}
        {nobodyShort ? (
          <p>Nobody is short of these products, so there is nothing to settle.</p>
        ) : (
          <SettleCustomers settlement={settlement} />
        )}
      </div>
    </Dialog>
  )
}
