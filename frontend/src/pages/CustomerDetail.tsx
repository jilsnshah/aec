import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import {
  ArchivedBadge,
  AsyncBlock,
  Button,
  Card,
  CardBody,
  EmptyState,
  KeyValue,
  LinkButton,
  MetricStrip,
  Page,
  StatusBadge,
  TableScroll,
  Toolbar,
  useRowLink,
  useToast,
} from '../components/ui'
import {
  ChevronIcon,
  EditIcon,
  EnquiryIcon,
  PlusIcon,
  SalesOrderIcon,
  SuccessIcon,
} from '../components/icons'
import { formatDate, formatDateTime, formatMoney, formatQuantity } from '../lib/format'
import { useAsync } from '../lib/useAsync'
import { CustomerForm } from './Customers'

export default function CustomerDetailPage() {
  const { customerId = '' } = useParams()
  const toast = useToast()
  const rowLink = useRowLink()
  const { data, loading, error, reload } = useAsync(
    () => api.customers.get(customerId),
    [customerId],
  )
  const [editing, setEditing] = useState(false)

  const totals = data
    ? data.orders.reduce(
        (acc, order) => ({
          value: acc.value + Number(order.total_amount),
          owed: acc.owed + order.items.reduce((sum, item) => sum + Number(item.quantity_pending), 0),
          open: acc.open + (order.status === 'PENDING' || order.status === 'PARTIALLY_FULFILLED' ? 1 : 0),
        }),
        { value: 0, owed: 0, open: 0 },
      )
    : null

  return (
    <Page>
      <Toolbar
        back={{ to: '/customers', label: 'Customers' }}
        title={data?.name ?? 'Customer'}
        badge={data && !data.is_active ? <ArchivedBadge /> : undefined}
        subtitle={data ? `Customer since ${formatDate(data.created_at)}` : undefined}
        actions={
          data ? (
            <>
              <Button icon={<EditIcon size={15} />} onClick={() => setEditing(true)}>
                Edit
              </Button>
              {data.is_active ? (
                <>
                  <LinkButton
                    to={`/enquiries?new=1&customer=${data.id}`}
                    icon={<EnquiryIcon size={15} />}
                  >
                    Enquiry
                  </LinkButton>
                  <LinkButton
                    to={`/orders?new=1&customer=${data.id}`}
                    variant="primary"
                    icon={<PlusIcon size={15} />}
                  >
                    New order
                  </LinkButton>
                </>
              ) : null}
            </>
          ) : undefined
        }
      />

      <AsyncBlock loading={loading} error={error} data={data} onRetry={reload} skeleton="spinner">
        {(customer) => (
          <div className="stack">
            {totals ? (
              <MetricStrip
                items={[
                  { label: 'Orders', value: customer.orders.length, hint: `${totals.open} open` },
                  {
                    label: 'To deliver',
                    value: formatQuantity(totals.owed),
                    hint: 'units across all orders',
                    tone: totals.owed > 0 ? 'owed' : undefined,
                  },
                  { label: 'Ordered value', value: formatMoney(totals.value), hint: 'before tax' },
                ]}
              />
            ) : null}

            <div className="columns columns--main-aside">
              <div className="stack">
                <Card title="To deliver" subtitle="What this customer is still waiting for, by product" flush>
                  {customer.outstanding.length === 0 ? (
                    <EmptyState
                      compact
                      icon={<SuccessIcon size={22} />}
                      title="Nothing outstanding"
                      body="Every order has been delivered or cancelled."
                    />
                  ) : (
                    <TableScroll>
                      <table className="table">
                        <thead>
                          <tr>
                            <th>Product</th>
                            <th className="num">To deliver</th>
                          </tr>
                        </thead>
                        <tbody>
                          {customer.outstanding.map((row) => (
                            <tr key={row.product_id}>
                              <td>
                                <span className="cell-primary">{row.product_name}</span>
                                <span className="cell-sub mono">{row.product_sku}</span>
                              </td>
                              <td className="num">
                                <span className="q-owed">
                                  {formatQuantity(row.pending_quantity)}
                                </span>{' '}
                                <span className="muted">{row.unit_of_measure}</span>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </TableScroll>
                  )}
                </Card>

                <Card title="Orders" subtitle={`${customer.orders.length} in total`} flush>
                  {customer.orders.length === 0 ? (
                    <EmptyState
                      compact
                      icon={<SalesOrderIcon size={22} />}
                      title="No orders yet"
                      action={
                        <LinkButton to={`/orders?new=1&customer=${customer.id}`} variant="tinted">
                          Create their first order
                        </LinkButton>
                      }
                    />
                  ) : (
                    <TableScroll>
                      <table className="table table--interactive">
                        <thead>
                          <tr>
                            <th>Order</th>
                            <th>Status</th>
                            <th className="num">Ordered</th>
                            <th className="num">To deliver</th>
                            <th className="num">Value</th>
                            <th className="col-shrink" />
                          </tr>
                        </thead>
                        <tbody>
                          {customer.orders.map((order) => {
                            const ordered = order.items.reduce(
                              (sum, item) => sum + Number(item.quantity_ordered),
                              0,
                            )
                            const owed = order.items.reduce(
                              (sum, item) => sum + Number(item.quantity_pending),
                              0,
                            )
                            return (
                              <tr key={order.id} {...rowLink(`/orders/${order.id}`)}>
                                <td>
                                  <Link to={`/orders/${order.id}`} className="cell-link mono">
                                    {order.order_number}
                                  </Link>
                                  <span className="cell-sub">{formatDateTime(order.created_at)}</span>
                                </td>
                                <td>
                                  <StatusBadge status={order.status} />
                                </td>
                                <td className="num">{formatQuantity(ordered)}</td>
                                <td className="num">
                                  {owed > 0 ? (
                                    <span className="q-owed">{formatQuantity(owed)}</span>
                                  ) : (
                                    <span className="q-muted">—</span>
                                  )}
                                </td>
                                <td className="num">{formatMoney(order.total_amount)}</td>
                                <td className="col-shrink">
                                  <ChevronIcon size={15} className="row-chevron" />
                                </td>
                              </tr>
                            )
                          })}
                        </tbody>
                      </table>
                    </TableScroll>
                  )}
                </Card>
              </div>

              <Card title="Contact">
                <CardBody>
                  <KeyValue
                    stacked
                    items={[
                      { label: 'Phone', value: customer.phone || '—' },
                      {
                        label: 'Email',
                        value: customer.email ? (
                          <a href={`mailto:${customer.email}`}>{customer.email}</a>
                        ) : (
                          '—'
                        ),
                      },
                      { label: 'Address', value: customer.address || '—' },
                    ]}
                  />
                  {customer.notes ? (
                    <p className="t-callout muted mt-3">
                      {customer.notes}
                    </p>
                  ) : null}
                </CardBody>
              </Card>
            </div>
          </div>
        )}
      </AsyncBlock>

      {editing && data ? (
        <CustomerForm
          customer={data}
          onClose={() => setEditing(false)}
          onSaved={(customer) => {
            setEditing(false)
            toast.success(`${customer.name} updated`)
            reload()
          }}
        />
      ) : null}
    </Page>
  )
}
