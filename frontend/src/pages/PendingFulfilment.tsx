import { useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { CommitmentRow, IncomingSource } from '../api/types'
import {
  ActionMenu,
  AsyncBlock,
  Avatar,
  Button,
  Card,
  CardFacts,
  CardGrid,
  EmptyState,
  FulfilmentMix,
  LinkButton,
  Meter,
  Page,
  Pagination,
  Quantity,
  RecordCard,
  SearchField,
  Segmented,
  Stat,
  TableScroll,
  Toolbar,
  ViewSwitch,
  useToast,
} from '../components/ui'
import { DeliverDialog } from '../components/DeliverDialog'
import { ReceiveDialog } from '../components/ReceiveDialog'
import { PurchaseOrderForm } from './PurchaseOrders'
import { DeliveryIcon, GoodsReceiptIcon, PurchaseOrderIcon, SuccessIcon, ViewIcon } from '../components/icons'
import { daysSince } from '../lib/validation'
import { formatAmount, formatDateTime, formatMoney, formatQuantity } from '../lib/format'
import { usePaging, useViewMode } from '../lib/paging'
import { useAsync, useDebounced } from '../lib/useAsync'

type Filter = 'all' | 'ready' | 'incoming' | 'awaiting' | 'partial'
const FILTERS: Filter[] = ['all', 'ready', 'incoming', 'awaiting', 'partial']

function age(isoDate: string) {
  const days = daysSince(isoDate)
  if (days <= 0) return { label: 'under a day', className: 'age' }
  const label = days === 1 ? '1 day' : `${days} days`
  return { label, className: days >= 30 ? 'age age--stale' : days >= 7 ? 'age age--old' : 'age' }
}

interface LineHandlers {
  deliver: (row: CommitmentRow) => void
  receive: (row: CommitmentRow, source: IncomingSource) => void
  buy: (row: CommitmentRow) => void
  open: (row: CommitmentRow) => void
}

/**
 * What can be done next for one order line. A line can be ready, on order and
 * short all at once, so it gets exactly one button -- the most useful next
 * step: deliver what is here, else book in what is coming, else buy what is
 * missing -- and a menu with every action that applies, quantities included.
 */
function LineActions({ row, on }: { row: CommitmentRow; on: LineHandlers }) {
  const ready = Number(row.quantity_deliverable)
  const incoming = Number(row.quantity_incoming)
  const short = Number(row.quantity_unallocated)
  const unit = row.unit_of_measure
  const firstSource = row.incoming_sources[0]

  const primary =
    ready > 0
      ? { label: 'Deliver', icon: <DeliveryIcon size={13} />, run: () => on.deliver(row), hint: `Deliver the ${formatQuantity(row.quantity_deliverable)} ${unit} that are ready` }
      : incoming > 0 && firstSource
        ? { label: 'Receive', icon: <GoodsReceiptIcon size={13} />, run: () => on.receive(row, firstSource), hint: `Book in goods from ${firstSource.po_number}` }
        : short > 0
          ? { label: 'Buy', icon: <PurchaseOrderIcon size={13} />, run: () => on.buy(row), hint: `Raise a purchase order for the ${formatQuantity(row.quantity_unallocated)} ${unit} short` }
          : null

  const items = [
    ...(ready > 0
      ? [{ label: `Deliver ${formatQuantity(row.quantity_deliverable)} ready`, icon: <DeliveryIcon size={15} />, onSelect: () => on.deliver(row) }]
      : []),
    ...row.incoming_sources.map((source) => ({
      label: `Receive ${formatQuantity(source.quantity)} from ${source.po_number}`,
      icon: <GoodsReceiptIcon size={15} />,
      onSelect: () => on.receive(row, source),
    })),
    ...(short > 0
      ? [{ label: `Buy ${formatQuantity(row.quantity_unallocated)} short`, icon: <PurchaseOrderIcon size={15} />, onSelect: () => on.buy(row) }]
      : []),
    { label: `Open ${row.order_number}`, icon: <ViewIcon size={15} />, onSelect: () => on.open(row), separatorBefore: true },
  ]

  return (
    <span className="line-actions">
      {primary ? (
        <Button size="sm" variant="tinted" icon={primary.icon} title={primary.hint} onClick={primary.run}>
          {primary.label}
        </Button>
      ) : null}
      <ActionMenu label={`Actions for ${row.order_number}, ${row.product_sku}`} items={items} />
    </span>
  )
}

export default function PendingFulfilmentPage() {
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const filterParam = params.get('filter') as Filter | null
  const filter: Filter = filterParam && FILTERS.includes(filterParam) ? filterParam : 'all'
  const [view, setView] = useState<'lines' | 'customers'>('lines')
  const [search, setSearch] = useState('')
  const debouncedSearch = useDebounced(search)
  const navigate = useNavigate()
  const [delivering, setDelivering] = useState<CommitmentRow | null>(null)
  const [receiving, setReceiving] = useState<{ row: CommitmentRow; source: IncomingSource } | null>(null)
  const [buying, setBuying] = useState<CommitmentRow | null>(null)
  const handlers: LineHandlers = {
    deliver: setDelivering,
    receive: (row, source) => setReceiving({ row, source }),
    buy: setBuying,
    open: (row) => navigate(`/orders/${row.order_id}`),
  }
  const [mode, setMode] = useViewMode('fulfilment')
  const paging = usePaging('fulfilment', [filter, view, debouncedSearch])

  function setFilter(next: Filter) {
    setParams(
      (current) => {
        const updated = new URLSearchParams(current)
        if (next === 'all') updated.delete('filter')
        else updated.set('filter', next)
        return updated
      },
      { replace: true },
    )
  }

  const { data, loading, error, reload } = useAsync(
    () => api.fulfilment.commitments({ search: debouncedSearch || undefined }),
    [debouncedSearch],
  )

  const counts = useMemo(() => {
    const rows = data?.rows ?? []
    return {
      all: rows.length,
      ready: rows.filter((row) => Number(row.quantity_deliverable) > 0).length,
      incoming: rows.filter((row) => Number(row.quantity_incoming) > 0).length,
      awaiting: rows.filter((row) => Number(row.quantity_unallocated) > 0).length,
      partial: rows.filter((row) => row.fulfilment_status === 'PARTIALLY_DELIVERED').length,
    }
  }, [data])

  const rows = useMemo(() => {
    const all = data?.rows ?? []
    if (filter === 'ready') return all.filter((row) => Number(row.quantity_deliverable) > 0)
    if (filter === 'incoming') return all.filter((row) => Number(row.quantity_incoming) > 0)
    if (filter === 'awaiting') return all.filter((row) => Number(row.quantity_unallocated) > 0)
    if (filter === 'partial') return all.filter((row) => row.fulfilment_status === 'PARTIALLY_DELIVERED')
    return all
  }, [data, filter])
  const pageRows = rows.slice(paging.offset, paging.offset + paging.limit)
  const customerRows = (data?.customers ?? []).slice(paging.offset, paging.offset + paging.limit)

  return (
    <Page>
      <Toolbar
        title="Fulfilment"
        subtitle="Promised goods still to load, oldest order first — and whether they are in stock"
        actions={
          <LinkButton to="/goods-receipts" icon={<GoodsReceiptIcon size={15} />}>
            Receive goods
          </LinkButton>
        }
      >
        <SearchField value={search} onChange={setSearch} placeholder="Search" />
        <Segmented
          label="Show"
          value={filter}
          onChange={setFilter}
          options={[
            { value: 'all', label: 'All', count: counts.all },
            { value: 'ready', label: 'Ready', count: counts.ready },
            { value: 'incoming', label: 'On order', count: counts.incoming },
            { value: 'awaiting', label: 'Short', count: counts.awaiting },
            { value: 'partial', label: 'Part sent', count: counts.partial },
          ]}
        />
        <div className="grow" />
        <Segmented
          label="Group by"
          small
          value={view}
          onChange={setView}
          options={[
            { value: 'lines', label: 'Lines' },
            { value: 'customers', label: 'Customers' },
          ]}
        />
        <ViewSwitch value={mode} onChange={setMode} />
      </Toolbar>

      <AsyncBlock loading={loading} error={error} data={data} onRetry={reload} skeleton="spinner">
        {(report) => (
          <div className="stack">
            <div className="stat-grid">
              <Stat
                label="To deliver"
                value={formatQuantity(report.totals.quantity_outstanding)}
                hint={`${report.totals.customer_count} customer${report.totals.customer_count === 1 ? '' : 's'} · ${formatMoney(report.totals.outstanding_value)}`}
              />
              <Stat
                label="Ready to deliver"
                value={formatQuantity(report.totals.quantity_deliverable)}
                hint="in stock, truck not gone yet"
                dot="var(--stock-reserved)"
              />
              <Stat
                label="On order"
                value={formatQuantity(report.totals.quantity_incoming)}
                hint="bought, not arrived yet"
                dot="var(--stock-owed)"
              />
              <Stat
                label="Short"
                value={formatQuantity(report.totals.quantity_unallocated)}
                hint="nothing bought for it yet"
                dot="var(--stock-short)"
                tone={Number(report.totals.quantity_unallocated) > 0 ? 'alert' : undefined}
              />
            </div>

            {view === 'lines' && mode === 'grid' && rows.length > 0 ? (
              <div className="collection">
                <CardGrid busy={loading}>
                  {pageRows.map((row) => {
                    const waiting = age(row.order_created_at)
                    return (
                      <RecordCard
                        key={row.order_item_id}
                        to={`/orders/${row.order_id}`}
                        openLabel={`Open ${row.order_number}`}
                        tone={Number(row.quantity_unallocated) > 0 ? 'alert' : undefined}
                        leading={<Avatar name={row.customer_name} seed={row.customer_id} />}
                        title={row.customer_name}
                        subtitle={<span className="mono">{row.order_number}</span>}
                        footer={
                          <>
                            <span className="cell-clip">
                              {row.product_name} · <span className="mono">{row.product_sku}</span>
                            </span>
                            <span className="grow" />
                            <LineActions row={row} on={handlers} />
                          </>
                        }
                      >
                        <div>
                            <FulfilmentMix
                            delivered={row.quantity_delivered}
                            ready={row.quantity_reserved}
                            onOrder={row.quantity_incoming}
                            short={row.quantity_unallocated}
                        />
                        </div>
                        <CardFacts
                          items={[
                            { label: 'To deliver', value: formatQuantity(row.quantity_outstanding) },
                            { label: 'Ready', value: formatQuantity(row.quantity_reserved) },
                            {
                              label: Number(row.quantity_unallocated) > 0 ? 'Short' : 'On order',
                              value:
                                Number(row.quantity_unallocated) > 0
                                  ? formatQuantity(row.quantity_unallocated)
                                  : Number(row.quantity_incoming) > 0
                                    ? formatQuantity(row.quantity_incoming)
                                    : '—',
                              tone:
                                Number(row.quantity_unallocated) > 0
                                  ? 'is-alert'
                                  : Number(row.quantity_incoming) > 0
                                    ? undefined
                                    : 'is-muted',
                            },
                          ]}
                        />
                        <div>
                          <Meter
                            total={Number(row.quantity_ordered)}
                            segments={[
                              { value: Number(row.quantity_delivered), className: 'bar__delivered', label: 'Delivered' },
                              { value: Number(row.quantity_reserved), className: 'bar__reserved', label: 'Ready' },
                              { value: Number(row.quantity_incoming), className: 'bar__owed', label: 'On order' },
                              { value: Number(row.quantity_unallocated), className: 'bar__short', label: 'Short' },
                            ]}
                          />
                          <div className="meter-caption">
                            <span>
                              {formatQuantity(row.quantity_delivered)} of {formatQuantity(row.quantity_ordered)} delivered
                            </span>
                            <span className={waiting.className}>waiting {waiting.label}</span>
                          </div>
                        </div>
                      </RecordCard>
                    )
                  })}
                </CardGrid>
                <Card flush>
                  <Pagination paging={paging} total={rows.length} noun="lines" />
                </Card>
              </div>
            ) : view === 'lines' ? (
              <Card flush>
                {rows.length === 0 ? (
                  <EmptyState
                    icon={<SuccessIcon size={22} />}
                    title={filter === 'all' ? 'Nothing left to deliver' : 'No lines match this filter'}
                    body={
                      filter === 'all'
                        ? 'Every order has been delivered or cancelled.'
                        : 'Try another filter, or clear the search.'
                    }
                  />
                ) : (
                  <TableScroll>
                    <table className="table">
                      <thead>
                        <tr>
                          <th>Customer · order</th>
                          <th>Product</th>
                          <th className="num">Ordered</th>
                          <th className="num">To deliver</th>
                          <th>Where it stands</th>
                          <th className="col-actions" />
                        </tr>
                      </thead>
                      <tbody>
                        {pageRows.map((row) => {
                          const waiting = age(row.order_created_at)
                          return (
                            <tr key={row.order_item_id}>
                              <td>
                                <Link className="cell-link" to={`/customers/${row.customer_id}`}>
                                  {row.customer_name}
                                </Link>
                                <span className="cell-sub">
                                  <Link to={`/orders/${row.order_id}`} className="mono">
                                    {row.order_number}
                                  </Link>{' '}
                                  · <span className={waiting.className}>waiting {waiting.label}</span>
                                </span>
                              </td>
                              <td>
                                <span className="cell-primary">{row.product_name}</span>
                                <span className="cell-sub">
                                  <span className="mono">{row.product_sku}</span> · {row.unit_of_measure}
                                </span>
                              </td>
                              <td className="num">{formatQuantity(row.quantity_ordered)}</td>
                              <td className="num">
                                <span className="q-strong">{formatQuantity(row.quantity_outstanding)}</span>
                                <span className="cell-sub">{formatAmount(row.outstanding_value)}</span>
                              </td>
                              <td>
                                <FulfilmentMix
                                  delivered={row.quantity_delivered}
                                  ready={row.quantity_reserved}
                                  onOrder={row.quantity_incoming}
                                  short={row.quantity_unallocated}
                                />
                              </td>
                              <td className="col-actions">
                                <LineActions row={row} on={handlers} />
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </TableScroll>
                )}
                <Pagination paging={paging} total={rows.length} noun="lines" />
              </Card>
            ) : (
              <Card flush>
                {report.customers.length === 0 ? (
                  <EmptyState icon={<SuccessIcon size={22} />} title="Nothing left to deliver" />
                ) : (
                  <TableScroll>
                    <table className="table">
                      <thead>
                        <tr>
                          <th>Customer</th>
                          <th>Waiting since</th>
                          <th className="num">Orders</th>
                          <th className="num">To deliver</th>
                          <th className="num">Ready</th>
                          <th className="num">On order</th>
                          <th className="num">Short</th>
                          <th className="num">Value</th>
                        </tr>
                      </thead>
                      <tbody>
                        {customerRows.map((row) => (
                          <tr key={row.customer_id}>
                            <td>
                              <Link className="cell-link" to={`/customers/${row.customer_id}`}>
                                {row.customer_name}
                              </Link>
                              <span className="cell-sub">
                                {row.line_count} line{row.line_count === 1 ? '' : 's'}
                              </span>
                            </td>
                            <td className="nowrap">{formatDateTime(row.oldest_order_at)}</td>
                            <td className="num">{row.order_count}</td>
                            <td className="num q-strong">{formatQuantity(row.quantity_outstanding)}</td>
                            <td className="num">
                              <Quantity value={row.quantity_reserved} tone="reserved" />
                            </td>
                            <td className="num">
                              <Quantity value={row.quantity_incoming} tone="owed" />
                            </td>
                            <td className="num">
                              <Quantity value={row.quantity_unallocated} tone="awaiting" />
                            </td>
                            <td className="num">{formatAmount(row.outstanding_value)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </TableScroll>
                )}
                <Pagination paging={paging} total={report.customers.length} noun="customers" />
              </Card>
            )}

            <div className="legend">
              <span>
                <i style={{ background: 'var(--stock-reserved)' }} /> Ready: in stock, load it on the truck
              </span>
              <span>
                <i style={{ background: 'var(--stock-owed)' }} /> On order: bought from a supplier, not arrived yet
              </span>
              <span>
                <i style={{ background: 'var(--stock-short)' }} /> Short: sold, nothing bought for it yet
              </span>
            </div>
          </div>
        )}
      </AsyncBlock>

      {delivering ? (
        <DeliverDialog
          orderId={delivering.order_id}
          orderNumber={delivering.order_number}
          focusItemId={delivering.order_item_id}
          onClose={() => setDelivering(null)}
          onDelivered={(result) => {
            setDelivering(null)
            toast.success(
              `${result.delivery_number} recorded`,
              Number(result.order_outstanding_after) > 0
                ? `${formatQuantity(result.total_delivered)} to ${result.customer_name} · ${formatQuantity(result.order_outstanding_after)} still to deliver`
                : `${formatQuantity(result.total_delivered)} to ${result.customer_name} · order complete`,
            )
            reload()
          }}
        />
      ) : null}

      {receiving ? (
        <ReceiveDialog
          row={{
            ...receiving.row,
            // The source picked in the menu is offered first.
            incoming_sources: [
              receiving.source,
              ...receiving.row.incoming_sources.filter(
                (entry) => entry.purchase_order_item_id !== receiving.source.purchase_order_item_id,
              ),
            ],
          }}
          onClose={() => setReceiving(null)}
          onReceived={(result) => {
            setReceiving(null)
            toast.success(
              `${result.receipt_number} booked in`,
              `${formatQuantity(result.total_received)} from ${result.supplier_name} · ${formatQuantity(result.total_allocated)} now ready to deliver`,
            )
            reload()
          }}
        />
      ) : null}

      {buying ? (
        <PurchaseOrderForm
          initialSupplierId={buying.last_supplier_id ?? undefined}
          initialLines={[{ productId: buying.product_id, quantity: String(Number(buying.quantity_unallocated)) }]}
          initialSettlement={{
            [buying.product_id]: { [buying.order_item_id]: String(Number(buying.quantity_unallocated)) },
          }}
          subtitle={`For ${buying.customer_name}'s ${formatQuantity(buying.quantity_unallocated)} ${buying.unit_of_measure} short on ${buying.order_number}. Change anything before placing it.`}
          onClose={() => setBuying(null)}
          onCreated={(order) => {
            setBuying(null)
            toast.success(
              `${order.po_number} ${order.status === 'DRAFT' ? 'saved as a draft' : 'placed'}`,
              order.status === 'DRAFT' ? 'Place it to settle the customer.' : `With ${order.supplier.name}.`,
            )
            reload()
          }}
        />
      ) : null}
    </Page>
  )
}
