import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { finance } from '@/api/finance'
import { Account } from '@/features/finance/Account'
import { RecordTasks } from '@/features/tasks/RecordTasks'
import { useAssistant } from '@/features/assistant/store'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Archive, Mail, MapPin, MessageSquareQuote, MoreHorizontal, Pencil, Phone, Plus, Truck, Users, MessageCircle, Sparkles } from 'lucide-react'
import { api } from '@/api/endpoints'
import { useAction, useList, useOne } from '@/api/queries'
import { fmtDate, fmtMoney, fmtQty, n, plural } from '@/lib/format'
import { useDebounced, useRecordRoute } from '@/lib/route'
import { EnquiryBadge, OrderBadge } from '@/lib/status'
import { Avatar, Badge, Button, Empty, SearchBox, Spinner } from '@/ui/core'
import { Menu, Segmented, TabPanel, Tabs, useConfirm } from '@/ui/overlays'
import { FigureStrip, InspectorHeader, ListPane, ListRow, ListSkeleton, SplitView } from '@/ui/split'
import { EnquirySheet } from '@/features/enquiries/EnquirySheet'
import { OrderSheet } from '@/features/orders/OrderSheet'
import { PartySheet } from './PartySheet'

export function Customers() {
  const route = useRecordRoute('/customers')
  const [search, setSearch] = useState('')
  const [scope, setScope] = useState<'active' | 'all'>('active')
  const query = useDebounced(search)
  const list = useList('customers', api.customers.list, { search: query, include_inactive: scope === 'all', limit: 500 })
  const items = list.data?.items ?? []
  useEffect(() => {
    if (!route.id && items.length > 0 && window.innerWidth >= 1024 && !search) route.select(items[0].id)
  }, [route.id, items.length]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <SplitView
      showDetail={Boolean(route.id)}
      onBack={route.back}
      list={
        <ListPane
          title="Customers"
          count={list.data?.total}
          actions={
            <Button kind="ghost" small iconOnly onClick={route.openNew} aria-label="New customer">
              <Plus size={16} />
            </Button>
          }
          filters={
            <>
              <SearchBox value={search} onChange={setSearch} placeholder="Name, phone or email" />
              <Segmented value={scope} onChange={setScope} options={[{ value: 'active', label: 'Active' }, { value: 'all', label: 'Including archived' }]} />
            </>
          }
        >
          {list.isPending ? (
            <ListSkeleton />
          ) : items.length === 0 ? (
            <Empty icon={<Users size={20} />} title={search ? 'No customers match' : 'No customers yet'} action={<Button kind="primary" small onClick={route.openNew}>New customer</Button>} />
          ) : (
            items.map((customer) => (
              <ListRow key={customer.id} group="customers" selected={customer.id === route.id} onSelect={() => route.select(customer.id)}>
                <div className="flex items-center gap-3">
                  <Avatar name={customer.name} size={32} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-[13px] font-semibold">{customer.name}</span>
                      {!customer.is_active ? <Badge>Archived</Badge> : null}
                    </div>
                    <div className="truncate text-[12px] text-fg-3">{customer.phone ?? customer.email ?? 'No contact details'}</div>
                  </div>
                  <div className="text-right">
                    {n(customer.outstanding_quantity) > 0 ? (
                      <>
                        <div className="num text-[13px] font-semibold text-sky">{fmtQty(customer.outstanding_quantity)}</div>
                        <div className="text-[11px] text-fg-3">to deliver</div>
                      </>
                    ) : (
                      <div className="num text-[12px] text-fg-3">{fmtMoney(customer.ordered_value)}</div>
                    )}
                  </div>
                </div>
              </ListRow>
            ))
          )}
        </ListPane>
      }
    >
      {route.id ? <CustomerInspector id={route.id} /> : <Empty className="h-full" icon={<Users size={22} />} title="Choose a customer" />}
      <PartySheet kind="customer" open={route.isNew} onClose={route.closeNew} onSaved={route.select} />
    </SplitView>
  )
}

function CustomerInspector({ id }: { id: string }) {
  const navigate = useNavigate()
  const customer = useOne('customers', api.customers.get, id)
  const enquiries = useList('enquiries', api.enquiries.list, { customer_id: id, limit: 100 })
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') ?? 'owed'
  const setTab = (value: string) => setParams({ tab: value }, { replace: true })
  const { ask } = useAssistant()
  const account = useQuery({ queryKey: ['finance', 'statement', 'customer', id], queryFn: () => finance.statement('customers', id) })
  const [sheet, setSheet] = useState<null | 'edit' | 'order' | 'enquiry'>(null)
  const confirm = useConfirm()
  const archive = useAction(() => api.customers.archive(id), { success: 'Customer archived' })

  if (customer.isPending) return <Spinner />
  if (!customer.data) return <Empty title="This customer could not be loaded" />
  const data = customer.data
  const outstanding = data.outstanding.reduce((sum, line) => sum + n(line.pending_quantity), 0)
  const value = data.orders.filter((order) => order.status !== 'CANCELLED').reduce((sum, order) => sum + n(order.total_amount), 0)
  const open = data.orders.filter((order) => order.status === 'PENDING' || order.status === 'PARTIALLY_FULFILLED').length

  return (
    <>
      <InspectorHeader
        eyebrow={data.is_active ? 'Customer' : 'Customer · archived'}
        title={
          <span className="flex items-center gap-3">
            <Avatar name={data.name} size={34} />
            {data.name}
          </span>
        }
        meta={`Customer since ${fmtDate(data.created_at)}`}
        actions={
          <>
            <Button icon={<MessageSquareQuote size={14} />} onClick={() => setSheet('enquiry')} disabled={!data.is_active}>
              Enquiry
            </Button>
            <Button kind="primary" icon={<Plus size={14} />} onClick={() => setSheet('order')} disabled={!data.is_active}>
              New order
            </Button>
            <Menu
              trigger={
                <Button iconOnly aria-label="More actions">
                  <MoreHorizontal size={16} />
                </Button>
              }
              items={[
                { label: 'Edit details', icon: <Pencil size={14} />, onSelect: () => setSheet('edit') },
                { label: 'Show on fulfilment board', icon: <Truck size={14} />, onSelect: () => navigate(`/fulfilment?customer=${id}`), disabled: outstanding === 0 },
                {
                  label: 'Archive',
                  icon: <Archive size={14} />,
                  danger: true,
                  separator: true,
                  disabled: !data.is_active,
                  onSelect: async () => {
                    const answer = await confirm.ask({ title: `Archive ${data.name}?`, body: 'Their orders and history stay. They no longer appear when choosing a customer.', confirm: 'Archive', danger: true })
                    if (answer.ok) archive.mutate(undefined)
                  },
                },
              ]}
            />
          </>
        }
      />
      <FigureStrip
        items={[
          { label: 'Orders', value: data.orders.length, hint: `${open} open` },
          { label: 'To deliver', value: fmtQty(outstanding), tone: outstanding > 0 ? 'sky' : undefined, hint: 'units across orders' },
          { label: 'Ordered value', value: fmtMoney(value), hint: 'before tax' },
          { label: 'Enquiries', value: enquiries.data?.total ?? '—' },
          {
            label: 'Owes you',
            value: account.data ? fmtMoney(account.data.summary.open) : '—',
            tone: account.data && account.data.summary.overdue > 0 ? 'bad' : undefined,
            hint: account.data ? (account.data.summary.overdue > 0 ? `${fmtMoney(account.data.summary.overdue)} overdue` : account.data.summary.payment_terms_days ? `${account.data.summary.payment_terms_days}-day terms` : 'due on delivery') : undefined,
          },
        ]}
      />
      <div className="flex min-h-0 flex-1">
        <Tabs
          value={tab}
          onChange={setTab}
          className="min-w-0 flex-1"
          tabs={[
            { value: 'owed', label: 'To deliver', count: data.outstanding.length },
            { value: 'orders', label: 'Orders', count: data.orders.length },
            { value: 'enquiries', label: 'Enquiries', count: enquiries.data?.total },
            { value: 'account', label: 'Account' },
            { value: 'followups', label: 'Follow-ups' },
          ]}
        >
          <TabPanel value="owed">
            {data.outstanding.length === 0 ? (
              <Empty icon={<Truck size={20} />} title="Nothing to deliver" body="Every order for this customer has been delivered." />
            ) : (
              <table className="grid-table">
                <thead>
                  <tr>
                    <th>Product</th>
                    <th className="r">To deliver</th>
                  </tr>
                </thead>
                <tbody>
                  {data.outstanding.map((line) => (
                    <tr key={line.product_id}>
                      <td>
                        <Link to={`/products/${line.product_id}`} className="text-[13px] font-medium hover:text-sky">
                          {line.product_name}
                        </Link>
                        <div className="text-[11.5px] text-fg-3">{line.product_sku}</div>
                      </td>
                      <td className="r num font-semibold text-sky">
                        {fmtQty(line.pending_quantity)} <span className="font-normal text-fg-3">{line.unit_of_measure}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </TabPanel>
          <TabPanel value="orders">
            {data.orders.length === 0 ? (
              <Empty title="No orders yet" />
            ) : (
              <table className="grid-table">
                <thead>
                  <tr>
                    <th>Order</th>
                    <th>Status</th>
                    <th className="r">Lines</th>
                    <th className="r">Value</th>
                  </tr>
                </thead>
                <tbody>
                  {data.orders.map((order) => (
                    <tr key={order.id} className="cursor-pointer" onClick={() => navigate(`/orders/${order.id}`)}>
                      <td>
                        <div className="num text-[13px] font-medium">{order.order_number}</div>
                        <div className="text-[11.5px] text-fg-3">{fmtDate(order.created_at)}</div>
                      </td>
                      <td>
                        <OrderBadge status={order.status} />
                      </td>
                      <td className="r num">{order.items.length}</td>
                      <td className="r num">{fmtMoney(order.total_amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </TabPanel>
          <TabPanel value="enquiries">
            {(enquiries.data?.items ?? []).length === 0 ? (
              <Empty title="No enquiries" />
            ) : (
              <table className="grid-table">
                <thead>
                  <tr>
                    <th>Enquiry</th>
                    <th>Status</th>
                    <th className="r">Value</th>
                  </tr>
                </thead>
                <tbody>
                  {enquiries.data?.items.map((enquiry) => (
                    <tr key={enquiry.id} className="cursor-pointer" onClick={() => navigate(`/enquiries/${enquiry.id}`)}>
                      <td>
                        <div className="num text-[13px] font-medium">{enquiry.enquiry_number}</div>
                        <div className="text-[11.5px] text-fg-3">
                          {fmtDate(enquiry.created_at)} · {plural(enquiry.item_count, 'product')}
                        </div>
                      </td>
                      <td>
                        <EnquiryBadge status={enquiry.status} />
                      </td>
                      <td className="r num">{fmtMoney(enquiry.total_amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </TabPanel>
          <TabPanel value="account">
            <Account party="customer" id={id} />
          </TabPanel>
          <TabPanel value="followups">
            <RecordTasks link={{ customer_id: id }} suggestion={`Call ${data.name}`} />
          </TabPanel>
        </Tabs>
        <aside className="w-[270px] shrink-0 space-y-4 overflow-y-auto border-l border-white/7 p-5 max-xl:hidden">
          <div className="eyebrow">Contact</div>
          <Contact icon={<Phone size={14} />} value={data.phone} href={data.phone ? `tel:${data.phone}` : undefined} />
          {data.phone ? (
            <a className="btn btn-sm w-full" href={`https://wa.me/${data.phone.replace(/\D/g, '').replace(/^(\d{10})$/, '91$1')}`} target="_blank" rel="noreferrer">
              <MessageCircle size={13} /> WhatsApp
            </a>
          ) : null}
          <Contact icon={<Mail size={14} />} value={data.email} href={data.email ? `mailto:${data.email}` : undefined} />
          <Contact icon={<MapPin size={14} />} value={data.address} />
          <Button
            small
            kind="quiet"
            className="w-full"
            icon={<Sparkles size={13} />}
            onClick={() => ask(`Give me a full picture of customer ${data.name} (id ${id}): what they buy, how often, what they owe and whether it is overdue, open enquiries and orders, and what I should do next with them.`)}
          >
            Ask AI about {data.name.split(' ')[0]}
          </Button>
          {data.notes ? (
            <>
              <div className="eyebrow pt-2">Notes</div>
              <p className="text-[12.5px] whitespace-pre-line text-fg-2" data-selectable>
                {data.notes}
              </p>
            </>
          ) : null}
        </aside>
      </div>
      <PartySheet kind="customer" open={sheet === 'edit'} onClose={() => setSheet(null)} editing={data} />
      <OrderSheet open={sheet === 'order'} onClose={() => setSheet(null)} customerId={id} onCreated={(order) => navigate(`/orders/${order.id}`)} />
      <EnquirySheet open={sheet === 'enquiry'} onClose={() => setSheet(null)} customerId={id} onSaved={(enquiry) => navigate(`/enquiries/${enquiry.id}`)} />
      {confirm.element}
    </>
  )
}

export function Contact({ icon, value, href }: { icon: React.ReactNode; value: string | null; href?: string }) {
  return (
    <div className="flex items-start gap-2.5 text-[13px]">
      <span className="mt-0.5 text-fg-3">{icon}</span>
      {value ? (
        href ? (
          <a href={href} className="min-w-0 break-words text-fg hover:text-sky" data-selectable>
            {value}
          </a>
        ) : (
          <span className="min-w-0 whitespace-pre-line break-words text-fg-2" data-selectable>
            {value}
          </span>
        )
      ) : (
        <span className="text-fg-4">—</span>
      )}
    </div>
  )
}
