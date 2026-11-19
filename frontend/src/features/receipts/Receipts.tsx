import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { PackageOpen, Plus } from 'lucide-react'
import { api } from '@/api/endpoints'
import { useList, useOne } from '@/api/queries'
import { fmtAmount, fmtDate, fmtDateTime, fmtMoney, fmtQty, n, plural } from '@/lib/format'
import { useDebounced, useRecordRoute } from '@/lib/route'
import { PurchaseBadge } from '@/lib/status'
import { Badge, Button, Empty, SearchBox, Spinner } from '@/ui/core'
import { FigureStrip, InspectorHeader, ListPane, ListRow, ListSkeleton, Section, SplitView } from '@/ui/split'
import { ReceiveSheet } from './ReceiveSheet'

export function Receipts() {
  const route = useRecordRoute('/receipts')
  const [search, setSearch] = useState('')
  const query = useDebounced(search)
  const list = useList('goods-receipts', api.goodsReceipts.list, { search: query, limit: 200 })
  const items = list.data?.items ?? []
  useEffect(() => {
    if (!route.id && items.length > 0 && window.innerWidth >= 1024 && !search && !route.isNew) route.select(items[0].id)
  }, [route.id, items.length]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <SplitView
      showDetail={Boolean(route.id)}
      onBack={route.back}
      list={
        <ListPane
          title="Goods Receipts"
          count={list.data?.total}
          actions={
            <Button kind="primary" small icon={<Plus size={14} />} onClick={route.openNew}>
              Receive
            </Button>
          }
          filters={<SearchBox value={search} onChange={setSearch} placeholder="Receipt, PO, supplier or note" />}
        >
          {list.isPending ? (
            <ListSkeleton />
          ) : items.length === 0 ? (
            <Empty icon={<PackageOpen size={20} />} title="No deliveries booked in" body="Receive goods against a purchase order when the supplier's truck arrives." action={<Button kind="primary" small onClick={route.openNew}>Receive goods</Button>} />
          ) : (
            items.map((row) => (
              <ListRow key={row.id} group="receipts" selected={row.id === route.id} onSelect={() => route.select(row.id)}>
                <div className="flex items-baseline gap-2">
                  <span className="num text-[13px] font-semibold">{row.receipt_number}</span>
                  <span className="num ml-auto text-[13px] font-medium">{fmtMoney(row.total_cost)}</span>
                </div>
                <div className="mt-0.5 flex items-center gap-2 text-[12px] text-fg-3">
                  <span className="truncate">
                    {row.po_number} · {row.supplier_name}
                  </span>
                  <span className="ml-auto shrink-0">{fmtDate(row.created_at)}</span>
                </div>
                <div className="mt-1.5 flex items-center gap-2 text-[11.5px] text-fg-3">
                  <span>{plural(row.line_count, 'line')} · {fmtQty(row.total_quantity)} units</span>
                  {row.lines.some((line) => line.is_over_receipt) ? <Badge tone="warn">Over-receipt</Badge> : null}
                </div>
              </ListRow>
            ))
          )}
        </ListPane>
      }
    >
      {route.id ? <ReceiptInspector id={route.id} /> : <Empty className="h-full" icon={<PackageOpen size={22} />} title="Choose a receipt" body="Or receive a new delivery." />}
      <ReceiveSheet open={route.isNew} onClose={route.closeNew} poId={route.param('po') ?? undefined} onDone={(result) => route.select(result.receipt_id)} />
    </SplitView>
  )
}

function ReceiptInspector({ id }: { id: string }) {
  const receipt = useOne('goods-receipts', api.goodsReceipts.get, id)
  if (receipt.isPending) return <Spinner />
  if (!receipt.data) return <Empty title="This receipt could not be loaded" />
  const data = receipt.data
  return (
    <>
      <InspectorHeader
        eyebrow="Goods receipt"
        title={data.receipt_number}
        badges={<PurchaseBadge status={data.po_status} />}
        meta={
          <>
            <Link to={`/purchase-orders/${data.purchase_order_id}`} className="text-sky hover:text-sky-2">
              {data.po_number}
            </Link>{' '}
            ·{' '}
            <Link to={`/suppliers/${data.supplier_id}`} className="text-sky hover:text-sky-2">
              {data.supplier_name}
            </Link>{' '}
            · {fmtDateTime(data.created_at)}
            {data.delivery_note_reference ? ` · note ${data.delivery_note_reference}` : ''}
          </>
        }
      />
      <FigureStrip
        items={[
          { label: 'Received', value: fmtQty(data.total_received) },
          { label: 'To customers', value: fmtQty(data.total_allocated), tone: n(data.total_allocated) > 0 ? 'sky' : undefined },
          { label: 'Free stock', value: fmtQty(data.total_surplus) },
          { label: 'Cost', value: fmtMoney(data.total_cost) },
        ]}
      />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="space-y-3 p-4">
          {data.lines.map((line) => (
            <div key={line.goods_receipt_item_id} className="card overflow-hidden">
              <div className="flex items-start gap-3 px-[18px] pt-4 pb-3">
                <div className="min-w-0 flex-1">
                  <Link to={`/products/${line.product_id}`} className="text-[14px] font-semibold hover:text-sky">
                    {line.product_name}
                  </Link>
                  <div className="text-[12px] text-fg-3">
                    {line.product_sku} · {fmtQty(line.quantity_received)} {line.unit_of_measure} at {fmtAmount(line.unit_cost)} · {fmtQty(line.quantity_remaining_on_po)} still due on the PO
                  </div>
                  {line.is_over_receipt ? <div className="mt-1 text-[12px] text-warn">More than ordered: {line.over_receipt_reason}</div> : null}
                </div>
                <div className="text-right">
                  <div className="num text-[15px] font-semibold">{fmtMoney(line.total_cost)}</div>
                  <div className="text-[11.5px] text-fg-3">stock now {fmtQty(line.stock_after)}</div>
                </div>
              </div>
              {line.allocations.length > 0 ? (
                <table className="grid-table border-t border-white/6">
                  <thead>
                    <tr>
                      <th>Went to</th>
                      <th className="r">Given</th>
                      <th className="r">Ready now</th>
                      <th className="r">Still owed</th>
                    </tr>
                  </thead>
                  <tbody>
                    {line.allocations.map((allocation) => (
                      <tr key={allocation.order_item_id}>
                        <td>
                          <div className="text-[13px] font-medium">{allocation.customer_name}</div>
                          <Link to={`/orders/${allocation.order_id}`} className="num text-[11.5px] text-sky hover:text-sky-2">
                            {allocation.order_number}
                          </Link>
                        </td>
                        <td className="r num font-semibold text-sky">{fmtQty(allocation.quantity_allocated)}</td>
                        <td className="r num">{fmtQty(allocation.quantity_reserved)}</td>
                        <td className="r num">{fmtQty(allocation.quantity_outstanding)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div className="border-t border-white/6 px-[18px] py-3 text-[12.5px] text-fg-3">Nobody was waiting; all of it went into free stock.</div>
              )}
            </div>
          ))}
        </div>
        {data.notes ? (
          <Section title="Note">
            <p className="text-[13px] text-fg-2">{data.notes}</p>
          </Section>
        ) : null}
      </div>
    </>
  )
}
