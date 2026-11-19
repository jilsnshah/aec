import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Archive, Building2, Mail, MapPin, MoreHorizontal, Pencil, Phone, Plus, UserRound } from 'lucide-react'
import { api } from '@/api/endpoints'
import { useAction, useList, useOne } from '@/api/queries'
import { fmtDate, fmtMoney, fmtQty, n } from '@/lib/format'
import { useDebounced, useRecordRoute } from '@/lib/route'
import { PurchaseBadge } from '@/lib/status'
import { Avatar, Badge, Button, Empty, Meter, SearchBox, Spinner } from '@/ui/core'
import { Menu, Segmented, TabPanel, Tabs, useConfirm } from '@/ui/overlays'
import { FigureStrip, InspectorHeader, ListPane, ListRow, ListSkeleton, SplitView } from '@/ui/split'
import { Contact } from '@/features/customers/Customers'
import { PartySheet } from '@/features/customers/PartySheet'
import { PurchaseSheet } from '@/features/purchasing/PurchaseSheet'

export function Suppliers() {
  const route = useRecordRoute('/suppliers')
  const [search, setSearch] = useState('')
  const [scope, setScope] = useState<'active' | 'all'>('active')
  const query = useDebounced(search)
  const list = useList('suppliers', api.suppliers.list, { search: query, include_inactive: scope === 'all', limit: 500 })
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
          title="Suppliers"
          count={list.data?.total}
          actions={
            <Button kind="ghost" small iconOnly onClick={route.openNew} aria-label="New supplier">
              <Plus size={16} />
            </Button>
          }
          filters={
            <>
              <SearchBox value={search} onChange={setSearch} placeholder="Name, code or contact" />
              <Segmented value={scope} onChange={setScope} options={[{ value: 'active', label: 'Active' }, { value: 'all', label: 'Including archived' }]} />
            </>
          }
        >
          {list.isPending ? (
            <ListSkeleton />
          ) : items.length === 0 ? (
            <Empty icon={<Building2 size={20} />} title={search ? 'No suppliers match' : 'No suppliers yet'} action={<Button kind="primary" small onClick={route.openNew}>New supplier</Button>} />
          ) : (
            items.map((supplier) => (
              <ListRow key={supplier.id} group="suppliers" selected={supplier.id === route.id} onSelect={() => route.select(supplier.id)}>
                <div className="flex items-center gap-3">
                  <Avatar name={supplier.name} size={32} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-[13px] font-semibold">{supplier.name}</span>
                      {!supplier.is_active ? <Badge>Archived</Badge> : null}
                    </div>
                    <div className="truncate text-[12px] text-fg-3">
                      {supplier.code}
                      {supplier.contact_person ? ` · ${supplier.contact_person}` : ''}
                    </div>
                  </div>
                  {n(supplier.on_order_quantity) > 0 ? (
                    <div className="text-right">
                      <div className="num text-[13px] font-semibold text-sky">{fmtQty(supplier.on_order_quantity)}</div>
                      <div className="text-[11px] text-fg-3">still due</div>
                    </div>
                  ) : null}
                </div>
              </ListRow>
            ))
          )}
        </ListPane>
      }
    >
      {route.id ? <SupplierInspector id={route.id} /> : <Empty className="h-full" icon={<Building2 size={22} />} title="Choose a supplier" />}
      <PartySheet kind="supplier" open={route.isNew} onClose={route.closeNew} onSaved={route.select} />
    </SplitView>
  )
}

function SupplierInspector({ id }: { id: string }) {
  const navigate = useNavigate()
  const supplier = useOne('suppliers', api.suppliers.get, id)
  const [tab, setTab] = useState('orders')
  const [sheet, setSheet] = useState<null | 'edit' | 'po'>(null)
  const confirm = useConfirm()
  const archive = useAction(() => api.suppliers.archive(id), { success: 'Supplier archived' })
  if (supplier.isPending) return <Spinner />
  if (!supplier.data) return <Empty title="This supplier could not be loaded" />
  const data = supplier.data
  const open = data.purchase_orders.filter((po) => ['DRAFT', 'ORDERED', 'PARTIALLY_RECEIVED'].includes(po.status))
  const due = open.reduce((sum, po) => sum + n(po.total_ordered) - n(po.total_received), 0)
  const spend = data.purchase_orders.filter((po) => po.status !== 'CANCELLED' && po.status !== 'DRAFT').reduce((sum, po) => sum + n(po.total_cost), 0)

  return (
    <>
      <InspectorHeader
        eyebrow={`Supplier · ${data.code}${data.is_active ? '' : ' · archived'}`}
        title={
          <span className="flex items-center gap-3">
            <Avatar name={data.name} size={34} />
            {data.name}
          </span>
        }
        meta={data.contact_person ? `Contact: ${data.contact_person}` : `Supplier since ${fmtDate(data.created_at)}`}
        actions={
          <>
            <Button kind="primary" icon={<Plus size={14} />} onClick={() => setSheet('po')} disabled={!data.is_active}>
              Purchase order
            </Button>
            <Menu
              trigger={
                <Button iconOnly aria-label="More actions">
                  <MoreHorizontal size={16} />
                </Button>
              }
              items={[
                { label: 'Edit details', icon: <Pencil size={14} />, onSelect: () => setSheet('edit') },
                {
                  label: 'Archive',
                  icon: <Archive size={14} />,
                  danger: true,
                  separator: true,
                  disabled: !data.is_active,
                  onSelect: async () => {
                    const answer = await confirm.ask({ title: `Archive ${data.name}?`, body: 'Their purchase orders and receipts stay. They no longer appear when choosing a supplier.', confirm: 'Archive', danger: true })
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
          { label: 'Purchase orders', value: data.purchase_orders.length, hint: `${open.length} open` },
          { label: 'Still due', value: fmtQty(due), tone: due > 0 ? 'sky' : undefined, hint: 'units to arrive' },
          { label: 'Bought', value: fmtMoney(spend), hint: 'placed orders' },
          { label: 'Deliveries', value: data.goods_receipts.length },
        ]}
      />
      <div className="flex min-h-0 flex-1">
        <Tabs
          value={tab}
          onChange={setTab}
          className="min-w-0 flex-1"
          tabs={[
            { value: 'orders', label: 'Purchase orders', count: data.purchase_orders.length },
            { value: 'receipts', label: 'Deliveries', count: data.goods_receipts.length },
          ]}
        >
          <TabPanel value="orders">
            {data.purchase_orders.length === 0 ? (
              <Empty title="No purchase orders yet" action={<Button kind="primary" small onClick={() => setSheet('po')}>New purchase order</Button>} />
            ) : (
              <table className="grid-table">
                <thead>
                  <tr>
                    <th>Order</th>
                    <th>Status</th>
                    <th className="w-[160px]">Received</th>
                    <th className="r">Value</th>
                  </tr>
                </thead>
                <tbody>
                  {data.purchase_orders.map((po) => (
                    <tr key={po.id} className="cursor-pointer" onClick={() => navigate(`/purchase-orders/${po.id}`)}>
                      <td>
                        <div className="num text-[13px] font-medium">{po.po_number}</div>
                        <div className="text-[11.5px] text-fg-3">{po.expected_delivery_date ? `expected ${fmtDate(po.expected_delivery_date)}` : fmtDate(po.created_at)}</div>
                      </td>
                      <td>
                        <PurchaseBadge status={po.status} />
                      </td>
                      <td>
                        <Meter parts={[{ label: 'Received', value: n(po.total_received), color: 'var(--color-blue)' }]} total={n(po.total_ordered)} />
                        <div className="num mt-1 text-[11px] text-fg-3">
                          {fmtQty(po.total_received)} of {fmtQty(po.total_ordered)}
                        </div>
                      </td>
                      <td className="r num">{fmtMoney(po.total_cost)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </TabPanel>
          <TabPanel value="receipts">
            {data.goods_receipts.length === 0 ? (
              <Empty title="Nothing delivered yet" />
            ) : (
              <table className="grid-table">
                <thead>
                  <tr>
                    <th>Receipt</th>
                    <th>Against</th>
                    <th className="r">Quantity</th>
                    <th className="r">Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {data.goods_receipts.map((receipt) => (
                    <tr key={receipt.id} className="cursor-pointer" onClick={() => navigate(`/receipts/${receipt.id}`)}>
                      <td>
                        <div className="num text-[13px] font-medium">{receipt.receipt_number}</div>
                        <div className="text-[11.5px] text-fg-3">
                          {fmtDate(receipt.created_at)}
                          {receipt.delivery_note_reference ? ` · ${receipt.delivery_note_reference}` : ''}
                        </div>
                      </td>
                      <td className="num text-[13px] text-fg-2">{receipt.po_number}</td>
                      <td className="r num">{fmtQty(receipt.total_quantity)}</td>
                      <td className="r num">{fmtMoney(receipt.total_cost)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </TabPanel>
        </Tabs>
        <aside className="w-[270px] shrink-0 space-y-4 overflow-y-auto border-l border-white/7 p-5 max-xl:hidden">
          <div className="eyebrow">Contact</div>
          <Contact icon={<UserRound size={14} />} value={data.contact_person} />
          <Contact icon={<Phone size={14} />} value={data.phone} href={data.phone ? `tel:${data.phone}` : undefined} />
          <Contact icon={<Mail size={14} />} value={data.email} href={data.email ? `mailto:${data.email}` : undefined} />
          <Contact icon={<MapPin size={14} />} value={data.address} />
          {data.notes ? (
            <>
              <div className="eyebrow pt-2">Notes</div>
              <p className="text-[12.5px] whitespace-pre-line text-fg-2">{data.notes}</p>
            </>
          ) : null}
        </aside>
      </div>
      <PartySheet kind="supplier" open={sheet === 'edit'} onClose={() => setSheet(null)} editing={data} />
      <PurchaseSheet open={sheet === 'po'} onClose={() => setSheet(null)} initial={{ supplier_id: id }} onSaved={(po) => navigate(`/purchase-orders/${po.id}`)} />
      {confirm.element}
    </>
  )
}
