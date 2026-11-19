import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { CheckCircle2, Mail, MessageCircle, MessageSquareQuote, MoreHorizontal, Pencil, Plus, ThumbsDown } from 'lucide-react'
import { api } from '@/api/endpoints'
import { useAction, useList, useOne } from '@/api/queries'
import { fmtAmount, fmtDate, fmtDateTime, fmtMoney, fmtPercent, fmtQty, n, plural } from '@/lib/format'
import { useDebounced, useRecordRoute } from '@/lib/route'
import { EnquiryBadge } from '@/lib/status'
import { Badge, Button, Empty, Notice, SearchBox, Spinner } from '@/ui/core'
import { Menu, Segmented, useConfirm } from '@/ui/overlays'
import { FigureStrip, InspectorHeader, ListPane, ListRow, ListSkeleton, Section, SplitView } from '@/ui/split'
import { EnquirySheet } from './EnquirySheet'

const FILTERS = [
  { value: 'OPEN', label: 'Open' },
  { value: 'CONVERTED', label: 'Won' },
  { value: 'LOST', label: 'Lost' },
  { value: 'all', label: 'All' },
]

function SourceBadge({ source, detail }: { source: string; detail: string | null }) {
  if (source === 'whatsapp') return <Badge tone="sky" title={detail ?? undefined}><MessageCircle size={11} /> WhatsApp</Badge>
  if (source === 'email') return <Badge tone="steel" title={detail ?? undefined}><Mail size={11} /> Email</Badge>
  return null
}

export function Enquiries() {
  const route = useRecordRoute('/enquiries')
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('all')
  const query = useDebounced(search)
  const list = useList('enquiries', api.enquiries.list, { search: query, status: status === 'all' ? undefined : status, limit: 200 })
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
          title="Enquiries"
          count={list.data?.total}
          actions={
            <Button kind="ghost" small iconOnly onClick={route.openNew} aria-label="New enquiry">
              <Plus size={16} />
            </Button>
          }
          filters={
            <>
              <SearchBox value={search} onChange={setSearch} placeholder="Enquiry, customer or product" />
              <Segmented value={status} onChange={setStatus} options={FILTERS} />
            </>
          }
        >
          {list.isPending ? (
            <ListSkeleton />
          ) : items.length === 0 ? (
            <Empty icon={<MessageSquareQuote size={20} />} title={search ? 'No enquiries match' : 'No enquiries here'} body="Enquiries also arrive from WhatsApp and email when AI is on." action={<Button kind="primary" small onClick={route.openNew}>New enquiry</Button>} />
          ) : (
            items.map((enquiry) => (
              <ListRow key={enquiry.id} group="enquiries" selected={enquiry.id === route.id} onSelect={() => route.select(enquiry.id)}>
                <div className="flex items-baseline gap-2">
                  <span className="num text-[13px] font-semibold">{enquiry.enquiry_number}</span>
                  <span className="num ml-auto text-[13px] font-medium">{fmtMoney(enquiry.total_amount)}</span>
                </div>
                <div className="mt-0.5 flex items-center gap-2 text-[12px] text-fg-3">
                  <span className="truncate">{enquiry.customer.name}</span>
                  <span className="ml-auto shrink-0">{fmtDate(enquiry.created_at)}</span>
                </div>
                <div className="mt-2 flex items-center gap-1.5">
                  <EnquiryBadge status={enquiry.status} />
                  <SourceBadge source={enquiry.source} detail={enquiry.source_detail} />
                  <span className="ml-auto text-[11.5px] text-fg-3">{plural(enquiry.item_count, 'product')}</span>
                </div>
              </ListRow>
            ))
          )}
        </ListPane>
      }
    >
      {route.id ? <EnquiryInspector id={route.id} /> : <Empty className="h-full" icon={<MessageSquareQuote size={22} />} title="Choose an enquiry" />}
      <EnquirySheet open={route.isNew} onClose={route.closeNew} onSaved={(enquiry) => route.select(enquiry.id)} />
    </SplitView>
  )
}

function EnquiryInspector({ id }: { id: string }) {
  const navigate = useNavigate()
  const enquiry = useOne('enquiries', api.enquiries.get, id)
  const [editing, setEditing] = useState(false)
  const confirm = useConfirm()
  const convert = useAction(() => api.enquiries.convert(id), { success: (result) => `Won — ${result.order.order_number} placed` })
  const lose = useAction((reason: string | null) => api.enquiries.markLost(id, reason), { success: 'Marked as lost' })

  if (enquiry.isPending) return <Spinner />
  if (!enquiry.data) return <Empty title="This enquiry could not be loaded" />
  const data = enquiry.data
  const open = data.status === 'OPEN'
  const pct = n(data.mrp_total) > 0 ? (n(data.discount_total) / n(data.mrp_total)) * 100 : 0

  async function askConvert() {
    const answer = await confirm.ask({ title: `Close ${data.enquiry_number} as won?`, body: `A sales order for ${fmtMoney(data.total_amount)} is placed at the agreed prices, and stock is taken at once.`, confirm: 'Place the order' })
    if (answer.ok) convert.mutate(undefined, { onSuccess: (result) => navigate(`/orders/${result.order.id}`) })
  }
  async function askLost() {
    const answer = await confirm.ask({ title: `Mark ${data.enquiry_number} as lost?`, confirm: 'Mark lost', danger: true, withReason: true })
    if (answer.ok) lose.mutate(answer.reason || null)
  }

  return (
    <>
      <InspectorHeader
        eyebrow="Enquiry"
        title={data.enquiry_number}
        badges={
          <>
            <EnquiryBadge status={data.status} />
            <SourceBadge source={data.source} detail={data.source_detail} />
          </>
        }
        meta={
          <>
            <Link to={`/customers/${data.customer_id}`} className="text-sky hover:text-sky-2">
              {data.customer.name}
            </Link>{' '}
            · opened {fmtDateTime(data.created_at)}
            {data.source_detail ? ` · from ${data.source_detail}` : ''}
          </>
        }
        actions={
          open ? (
            <>
              <Button icon={<Pencil size={14} />} onClick={() => setEditing(true)} disabled={!data.is_editable}>
                Edit
              </Button>
              <Button kind="primary" icon={<CheckCircle2 size={15} />} busy={convert.isPending} onClick={askConvert}>
                Convert to order
              </Button>
              <Menu
                trigger={
                  <Button iconOnly aria-label="More actions">
                    <MoreHorizontal size={16} />
                  </Button>
                }
                items={[{ label: 'Mark as lost', icon: <ThumbsDown size={14} />, onSelect: askLost, danger: true }]}
              />
            </>
          ) : data.sales_order_id ? (
            <Button kind="primary" onClick={() => navigate(`/orders/${data.sales_order_id}`)}>
              Open {data.sales_order_number}
            </Button>
          ) : null
        }
      />
      {data.status === 'CONVERTED' ? (
        <div className="shrink-0 px-6 pt-4">
          <Notice tone="ok">Won on {fmtDateTime(data.converted_at)} — became {data.sales_order_number}. The deal is read-only; the order holds the agreed prices.</Notice>
        </div>
      ) : data.status === 'LOST' ? (
        <div className="shrink-0 px-6 pt-4">
          <Notice tone="warn">Lost on {fmtDateTime(data.lost_at)}{data.lost_reason ? ` — ${data.lost_reason}` : ''}.</Notice>
        </div>
      ) : null}
      <FigureStrip
        items={[
          { label: 'At MRP', value: fmtMoney(data.mrp_total) },
          { label: 'Discount', value: Math.abs(n(data.discount_total)) > 0 ? `−${fmtMoney(Math.abs(n(data.discount_total)))}` : '—', hint: pct !== 0 ? `${Math.abs(pct).toFixed(1)}% off` : undefined },
          { label: 'Deal value', value: fmtMoney(data.total_amount), tone: 'sky', hint: 'before tax' },
          { label: 'Products', value: data.item_count },
        ]}
      />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <table className="grid-table">
          <thead>
            <tr>
              <th>Product</th>
              <th className="r">Quantity</th>
              <th className="r">MRP</th>
              <th className="r">Discount</th>
              <th className="r">Price</th>
              <th className="r">Total</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((item) => (
              <tr key={item.id}>
                <td>
                  <Link to={`/products/${item.product_id}`} className="text-[13px] font-medium hover:text-sky">
                    {item.product.name}
                  </Link>
                  <div className="text-[11.5px] text-fg-3">
                    {item.product.sku} · {item.product.unit_of_measure}
                  </div>
                </td>
                <td className="r num">{fmtQty(item.quantity)}</td>
                <td className="r num text-fg-3">{fmtAmount(item.mrp_snapshot)}</td>
                <td className="r num">{n(item.discount_percent) > 0 ? fmtPercent(item.discount_percent) : '—'}</td>
                <td className="r num">{fmtAmount(item.quoted_unit_price)}</td>
                <td className="r num font-medium">{fmtAmount(item.line_total)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {data.notes ? (
          <Section title="Notes">
            <p className="text-[13px] whitespace-pre-line text-fg-2" data-selectable>
              {data.notes}
            </p>
          </Section>
        ) : null}
      </div>
      <EnquirySheet open={editing} onClose={() => setEditing(false)} editing={data} />
      {confirm.element}
    </>
  )
}
