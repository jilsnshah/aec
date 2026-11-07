import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { InventorySummary, PurchaseOrder } from '../api/types'
import {
  AsyncBlock,
  Card,
  EmptyState,
  LinkButton,
  MetricStrip,
  Page,
  PurchaseStatusBadge,
  Stat,
  StatusBadge,
  Toolbar,
} from '../components/ui'
import {
  ChevronIcon,
  DeliveryIcon,
  GoodsReceiptIcon,
  PlusIcon,
  PurchaseOrderIcon,
  SalesOrderIcon,
  SuccessIcon,
  WarningIcon,
} from '../components/icons'
import { SalesChart } from '../components/SalesChart'
import {
  formatAmount,
  formatDate,
  formatLongDate,
  formatMoney,
  formatPercent,
  formatQuantity,
  formatRelative,
} from '../lib/format'
import { useAsync } from '../lib/useAsync'

interface OverviewData {
  summary: InventorySummary
  awaitingDelivery: PurchaseOrder[]
}

export default function DashboardPage() {
  const { data, loading, error, reload } = useAsync<OverviewData>(async () => {
    const [summary, orders] = await Promise.all([
      api.inventory.summary(),
      api.purchaseOrders.all({ status: 'ORDERED,PARTIALLY_RECEIVED' }),
    ])
    return { summary, awaitingDelivery: orders.filter((order) => order.can_receive) }
  }, [])

  return (
    <Page>
      <Toolbar
        title="Overview"
        subtitle={formatLongDate()}
        actions={
          <>
            <LinkButton to="/goods-receipts" icon={<GoodsReceiptIcon size={15} />}>
              Receive goods
            </LinkButton>
            <LinkButton to="/orders?new=1" variant="primary" icon={<PlusIcon size={15} />}>
              New order
            </LinkButton>
          </>
        }
      />

      <AsyncBlock loading={loading} error={error} data={data} onRetry={reload} skeleton="spinner">
        {({ summary, awaitingDelivery }) => {
          const awaitingStock = Number(summary.total_unallocated_quantity)
          const shortProducts = summary.products_short.length
          return (
            <div className="stack">
              <div className="stat-grid">
                <Stat
                  label="To deliver"
                  value={formatQuantity(summary.total_pending_quantity)}
                  hint={`${summary.open_orders} open order${summary.open_orders === 1 ? '' : 's'}`}
                  dot="var(--stock-owed)"
                  to="/pending-fulfilment"
                />
                <Stat
                  label="Ready to deliver"
                  value={formatQuantity(summary.total_reserved_stock)}
                  hint="goods in hand, truck not gone yet"
                  dot="var(--stock-reserved)"
                  to="/pending-fulfilment?filter=ready"
                />
                <Stat
                  label="Short"
                  value={formatQuantity(summary.total_unallocated_quantity)}
                  hint="sold, nothing bought for it yet"
                  dot="var(--stock-short)"
                  tone={awaitingStock > 0 ? 'alert' : undefined}
                  to="/pending-fulfilment?filter=awaiting"
                />
                <Stat
                  label="Products short"
                  value={String(shortProducts)}
                  hint={shortProducts > 0 ? 'sold more than bought' : 'every product covers its orders'}
                  dot="var(--stock-short)"
                  tone={shortProducts > 0 ? 'alert' : undefined}
                  to="/products?sort=stock"
                />
              </div>

              <SalesChart series={summary.daily_sales} />

              <div className="columns">
                <Card
                  title="Needs attention"
                  subtitle="Shortfalls and deliveries still to come"
                  flush
                >
                  <AttentionList summary={summary} awaitingDelivery={awaitingDelivery} />
                </Card>
                <Card title="Recent activity" flush>
                  <ActivityList summary={summary} />
                </Card>
              </div>

              <div>
                <div className="section-label">
                  Trading
                  <span className="section-label__hint">
                    Revenue and cost count delivered goods only
                  </span>
                </div>
                <MetricStrip
                  items={[
                    {
                      label: 'Revenue delivered',
                      value: formatMoney(summary.revenue_delivered),
                      hint: `${formatAmount(summary.discounts_given)} in discounts`,
                    },
                    {
                      label: 'Cost of goods',
                      value: formatMoney(summary.cost_of_goods_sold),
                      hint: `${formatAmount(summary.purchase_spend)} spent on stock`,
                    },
                    {
                      label: 'Gross profit',
                      value: formatMoney(summary.gross_profit),
                      hint: `${formatPercent(summary.margin_percent)} margin`,
                      tone: Number(summary.gross_profit) < 0 ? 'negative' : 'positive',
                    },
                    {
                      label: 'Value in warehouse',
                      value: formatMoney(summary.total_stock_value),
                      hint: 'at what it cost',
                    },
                    {
                      label: 'Still to deliver',
                      value: formatMoney(summary.outstanding_order_value),
                      hint: 'value of open orders',
                      tone: 'owed',
                    },
                  ]}
                />
              </div>
            </div>
          )
        }}
      </AsyncBlock>
    </Page>
  )
}

function AttentionList({
  summary,
  awaitingDelivery,
}: {
  summary: InventorySummary
  awaitingDelivery: PurchaseOrder[]
}) {
  const short = summary.products_short.slice(0, 5)
  const incoming = awaitingDelivery.slice(0, 4)

  if (short.length === 0 && incoming.length === 0) {
    return (
      <EmptyState
        compact
        icon={<SuccessIcon size={22} />}
        title="Nothing needs you right now"
        body="Every product covers its commitments and no purchase order is outstanding."
      />
    )
  }

  return (
    <div className="list">
      {short.map((row) => (
        <Link key={row.product_id} to="/pending-fulfilment?filter=awaiting" className="list-row">
          <span className="list-row__icon list-row__icon--red">
            <WarningIcon size={16} />
          </span>
          <span className="list-row__main">
            <span className="list-row__title">
              {row.name}
            </span>
            <span className="list-row__meta">
              <span className="mono">{row.sku}</span> · buy {formatQuantity(String(-Number(row.stock)))} more to cover orders
            </span>
          </span>
          <span className="list-row__trail q-negative">
            short {formatQuantity(String(-Number(row.stock)))} {row.unit_of_measure}
          </span>
          <ChevronIcon size={15} className="row-chevron" />
        </Link>
      ))}
      {incoming.map((order) => (
        <Link key={order.id} to={`/purchase-orders/${order.id}`} className="list-row">
          <span className="list-row__icon list-row__icon--orange">
            <PurchaseOrderIcon size={16} />
          </span>
          <span className="list-row__main">
            <span className="list-row__title">
              <span className="mono">{order.po_number}</span> · {order.supplier.name}
            </span>
            <span className="list-row__meta">
              {formatQuantity(order.total_remaining)} still to arrive
              {order.expected_delivery_date
                ? ` · expected ${formatDate(order.expected_delivery_date)}`
                : ''}
            </span>
          </span>
          <span className="list-row__trail">
            <PurchaseStatusBadge status={order.status} />
          </span>
          <ChevronIcon size={15} className="row-chevron" />
        </Link>
      ))}
    </div>
  )
}

function ActivityList({ summary }: { summary: InventorySummary }) {
  const events = [
    ...summary.recent_orders.map((order) => ({
      key: `o-${order.id}`,
      at: order.created_at,
      to: `/orders/${order.id}`,
      icon: <SalesOrderIcon size={16} />,
      tone: 'blue',
      title: (
        <>
          <span className="mono">{order.order_number}</span> · {order.customer_name}
        </>
      ),
      meta: `${order.line_count} line${order.line_count === 1 ? '' : 's'} · ${formatMoney(
        order.total_amount,
      )}`,
      trail: <StatusBadge status={order.status} />,
    })),
    ...summary.recent_receipts.map((receipt) => ({
      key: `r-${receipt.id}`,
      at: receipt.created_at,
      to: '/stock-in',
      icon: <DeliveryIcon size={16} />,
      tone: 'green',
      title: (
        <>
          <span className="mono">{receipt.receipt_number}</span> · {receipt.product_name}
        </>
      ),
      meta: `${formatQuantity(receipt.quantity)} ${receipt.unit_of_measure} in · ${formatQuantity(
        receipt.allocated_quantity,
      )} to waiting orders`,
      trail: <span className="t-footnote muted">{formatAmount(receipt.total_cost)}</span>,
    })),
  ]
    .sort((a, b) => new Date(b.at).getTime() - new Date(a.at).getTime())
    .slice(0, 8)

  if (events.length === 0) {
    return (
      <EmptyState
        compact
        icon={<SalesOrderIcon size={22} />}
        title="No activity yet"
        body="Orders and stock receipts will appear here as they happen."
      />
    )
  }

  return (
    <div className="list">
      {events.map((event) => (
        <Link key={event.key} to={event.to} className="list-row">
          <span className={`list-row__icon list-row__icon--${event.tone}`}>{event.icon}</span>
          <span className="list-row__main">
            <span className="list-row__title">
              {event.title}
            </span>
            <span className="list-row__meta">
              {formatRelative(event.at)} · {event.meta}
            </span>
          </span>
          <span className="list-row__trail">{event.trail}</span>
        </Link>
      ))}
    </div>
  )
}
