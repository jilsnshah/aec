import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { AssignCustomer } from './AssignCustomer'
import { groups } from '@/api/groups'
import { BadgePercent } from 'lucide-react'
import { CheckCircle2, FileText, UserRoundX, Link2, Flame, Hourglass, Layers, Mail, MessageCircle, MessageSquareQuote, MoreHorizontal, Pencil, Phone, Plus, ShieldCheck, Sparkles, Target, ThumbsDown, Trophy, XCircle } from 'lucide-react'
import type { ReactNode } from 'react'
import { records } from '@/api/records'
import { useAssistant } from '@/features/assistant/store'
import { AiStrip, HoldPanel, PageGuide, QuickChips, WarningList, holdFrom, type Chip } from '@/ui/smart'
import { errorText } from '@/api/client'
import { useQuery } from '@tanstack/react-query'
import { insights } from '@/api/insights'
import { api } from '@/api/endpoints'
import { useAction, useList, useOne } from '@/api/queries'
import { fmtAmount, fmtDate, fmtDateTime, fmtMoney, fmtPercent, fmtQty, n, plural } from '@/lib/format'
import { useDebounced, useRecordRoute } from '@/lib/route'
import { EnquiryBadge } from '@/lib/status'
import { Badge, Button, Empty, Notice, SearchBox, Spinner } from '@/ui/core'
import { Menu, useConfirm } from '@/ui/overlays'
import { FigureStrip, InspectorHeader, ListPane, ListRow, ListSkeleton, Section, SplitView } from '@/ui/split'
import { EnquirySheet } from './EnquirySheet'

type EnquiryChip = 'OPEN' | 'unknown' | 'hot' | 'ageing' | 'whatsapp' | 'CONVERTED' | 'LOST' | 'all'

function SourceBadge({ source, detail }: { source: string; detail: string | null }) {
  if (source === 'whatsapp') return <Badge tone="sky" title={detail ?? undefined}><MessageCircle size={11} /> WhatsApp</Badge>
  if (source === 'email') return <Badge tone="steel" title={detail ?? undefined}><Mail size={11} /> Email</Badge>
  if (source === 'link') return <Badge tone="sky" title="Sent from the customer's own link"><Link2 size={11} /> Their link</Badge>
  if (source === 'phone') return <Badge tone="steel" title={detail ?? undefined}><Phone size={11} /> Phone call</Badge>
  return null
}

export function Enquiries() {
  const route = useRecordRoute('/enquiries')
  const [search, setSearch] = useState('')
  const [chip, setChip] = useState<EnquiryChip>('OPEN')
  const query = useDebounced(search)
  const list = useList('enquiries', api.enquiries.list, { search: query, limit: 500 })
  const funnel = useQuery({ queryKey: ['insights', 'enquiries'], queryFn: insights.enquiries })
  const priority = new Map((funnel.data?.priorities ?? []).map((row) => [row.enquiry_id, row]))
  const all = list.data?.items ?? []
  const test = (key: EnquiryChip, enquiry: (typeof all)[number]) => {
    const p = priority.get(enquiry.id)
    if (key === 'all') return true
    if (key === 'unknown') return enquiry.status === 'OPEN' && !enquiry.customer
    if (key === 'hot') return enquiry.status === 'OPEN' && (p?.score ?? 0) >= 60
    if (key === 'ageing') return enquiry.status === 'OPEN' && (p?.days_idle ?? 0) >= (funnel.data?.stale_days ?? 7)
    if (key === 'whatsapp') return enquiry.status === 'OPEN' && enquiry.source !== 'manual'
    return enquiry.status === key
  }
  const count = (key: EnquiryChip) => all.filter((enquiry) => test(key, enquiry)).length
  const items = all.filter((enquiry) => test(chip, enquiry)).sort((a, b) => (chip !== 'CONVERTED' && chip !== 'LOST' ? (priority.get(b.id)?.score ?? -1) - (priority.get(a.id)?.score ?? -1) : 0))
  const chips: Chip<EnquiryChip>[] = [
    { key: 'OPEN', label: 'Open', icon: Layers, count: count('OPEN') },
    { key: 'unknown', label: 'New senders', icon: UserRoundX, count: count('unknown'), hot: count('unknown') > 0 },
    { key: 'hot', label: 'Hot', icon: Flame, count: count('hot'), hot: count('hot') > 0 },
    { key: 'ageing', label: 'Going cold', icon: Hourglass, count: count('ageing'), hot: count('ageing') > 0 },
    { key: 'whatsapp', label: 'From messages', icon: MessageCircle, count: count('whatsapp') },
    { key: 'CONVERTED', label: 'Won', icon: Trophy, count: count('CONVERTED') },
    { key: 'LOST', label: 'Lost', icon: XCircle, count: count('LOST') },
    { key: 'all', label: 'All', count: all.length },
  ]
  const f = funnel.data
  useEffect(() => {
    if (list.data && chip === 'OPEN' && count('OPEN') === 0) setChip('all')
  }, [list.data]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    // A quick filter that hides the open record moves to the first one shown.
    if (route.id && items.length > 0 && !items.some((row) => row.id === route.id) && window.innerWidth >= 1024) route.select(items[0].id)
  }, [chip]) // eslint-disable-line react-hooks/exhaustive-deps
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
            <>
              <PageGuide
                title="Enquiries (quotes)"
                points={[
                  { icon: Target, text: 'Open enquiries are sorted by priority: value, stock on hand, how long they wait and whether the customer buys often. Hover P-score for reasons.' },
                  { icon: Hourglass, text: '"Going cold" means nobody has touched it for a week. Call or WhatsApp from the enquiry.' },
                  { icon: Sparkles, text: 'Use "Draft quote reply" to get a ready-to-send WhatsApp message with prices.' },
                  { icon: CheckCircle2, text: 'Convert to order places a sales order at the quoted prices and takes stock at once.' },
                ]}
              />
              <Button kind="primary" small icon={<Plus size={14} />} onClick={route.openNew} aria-label="New enquiry">
                New
              </Button>
            </>
          }
          filters={
            <>
              <SearchBox value={search} onChange={setSearch} placeholder="Enquiry, customer or product" />
              <QuickChips chips={chips} value={chip} onChange={setChip} />
            </>
          }
        >
          {!search && (chip === 'OPEN' || chip === 'all') && f ? (
            <AiStrip
              className="mx-1.5 mb-2"
              title="Pipeline"
              insights={
                [
                  { icon: Target, text: <><b>{fmtMoney(f.open_pipeline_value)}</b> in open quotes · win rate <b>{f.conversion_rate !== null ? `${f.conversion_rate}%` : '—'}</b>{f.average_days_to_convert !== null ? `, ${f.average_days_to_convert} days to win` : ''}.</> },
                  count('hot') ? { icon: Flame, text: <><b>{count('hot')} hot enquiries</b> worth chasing today.</>, onClick: () => setChip('hot') } : null,
                  count('ageing') ? { icon: Hourglass, text: <><b>{count('ageing')} going cold</b> — no follow-up in {f.stale_days}+ days.</>, onClick: () => setChip('ageing') } : null,
                  f.lost_reasons[0] ? { icon: XCircle, text: <>Most lost because: <b>{f.lost_reasons[0].reason}</b> ({f.lost_reasons[0].count}).</>, onClick: () => setChip('LOST') } : null,
                ].filter(Boolean) as { icon: typeof Layers; text: ReactNode; onClick?: () => void }[]
              }
              prompts={[
                { label: 'Which to chase?', question: 'Which open enquiries should I chase today, in order? Use enquiry_funnel priorities, check stock for each, and draft a short WhatsApp follow-up for the top three.' },
                { label: 'Why do we lose?', question: 'Why do we lose enquiries? Look at lost reasons, discounts and products, and suggest what to change.' },
              ]}
            />
          ) : null}
          {list.isPending ? (
            <ListSkeleton />
          ) : items.length === 0 ? (
            <Empty icon={<MessageSquareQuote size={20} />} title={search ? 'No enquiries match' : 'No enquiries here'} body="Enquiries also arrive from WhatsApp and email when AI is on." action={<Button kind="primary" small onClick={route.openNew}>New enquiry</Button>} />
          ) : (
            items.map((enquiry) => (
              <ListRow key={enquiry.id} group="enquiries" selected={enquiry.id === route.id} onSelect={() => route.select(enquiry.id)} alert={test('ageing', enquiry)}>
                <div className="flex items-baseline gap-2">
                  <span className="num text-[13px] font-semibold">{enquiry.enquiry_number}</span>
                  <span className="num ml-auto text-[13px] font-medium">{fmtMoney(enquiry.total_amount)}</span>
                </div>
                <div className="mt-0.5 flex items-center gap-2 text-[12px] text-fg-3">
                  <span className="truncate">{enquiry.customer?.name ?? enquiry.sender_name ?? enquiry.sender_phone ?? enquiry.sender_email ?? 'Unknown sender'}</span>
                  {!enquiry.customer ? <Badge tone="bad"><UserRoundX size={11} /> New sender</Badge> : null}
                  <span className="ml-auto shrink-0">{fmtDate(enquiry.created_at)}</span>
                </div>
                <div className="mt-2 flex items-center gap-1.5">
                  <EnquiryBadge status={enquiry.status} />
                  <SourceBadge source={enquiry.source} detail={enquiry.source_detail} />
                  {priority.get(enquiry.id) ? (
                    <span title={priority.get(enquiry.id)!.reasons.join('; ')}>
                      <Badge tone={priority.get(enquiry.id)!.score >= 60 ? 'bad' : priority.get(enquiry.id)!.score >= 35 ? 'sky' : 'muted'}>
                        {priority.get(enquiry.id)!.score >= 60 ? <Flame size={11} /> : <Target size={11} />} P{priority.get(enquiry.id)!.score}
                      </Badge>
                    </span>
                  ) : null}
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
  const contact = useOne('customers', api.customers.get, enquiry.data?.customer?.id ?? undefined)
  const [assigning, setAssigning] = useState<null | 'assign' | 'convert'>(null)
  const { ask } = useAssistant()
  const funnel = useQuery({ queryKey: ['insights', 'enquiries'], queryFn: insights.enquiries })
  const check = useQuery({
    queryKey: ['records', 'enquiry-check', id, enquiry.data?.updated_at],
    enabled: enquiry.data?.status === 'OPEN',
    queryFn: () =>
      records.checkOrder({
        customer_id: enquiry.data!.customer?.id ?? null,
        items: enquiry.data!.items.map((item) => ({ product_id: item.product_id, quantity_ordered: n(item.quantity), unit_price: n(item.mrp_snapshot), discount_percent: n(item.discount_percent) })),
      }),
  })
  const phone = contact.data?.phone ?? enquiry.data?.sender_phone ?? null
  const [editing, setEditing] = useState(false)
  const confirm = useConfirm()
  const convert = useAction((approval?: string) => api.enquiries.convert(id, approval), { success: (result) => `Won — ${result.order.order_number} placed`, quiet: true })
  const applyPrices = useAction(() => groups.applyPrices(id), { success: (r) => (r.changed.length ? `${r.changed.length} line${r.changed.length === 1 ? '' : 's'} re-priced: ` + r.changed.map((c) => `${c.product} ${c.from}% → ${c.to}%`).join(', ') : 'Already at the best prices') })
  const lose = useAction((reason: string | null) => api.enquiries.markLost(id, reason), { success: 'Marked as lost' })

  if (enquiry.isPending) return <Spinner />
  if (!enquiry.data) return <Empty title="This enquiry could not be loaded" />
  const data = enquiry.data
  const open = data.status === 'OPEN'
  const pct = n(data.mrp_total) > 0 ? (n(data.discount_total) / n(data.mrp_total)) * 100 : 0

  const who = data.customer?.name ?? data.sender_name ?? data.sender_phone ?? data.sender_email ?? 'Unknown sender'
  async function askConvert() {
    if (!data.customer) return setAssigning('convert')
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
            {data.customer ? (
              <Link to={`/customers/${data.customer_id}`} className="text-sky hover:text-sky-2">
                {data.customer.name}
              </Link>
            ) : (
              <span className="font-semibold text-fg">{who} (not a customer yet)</span>
            )}{' '}
            · opened {fmtDateTime(data.created_at)}
            {data.source_detail ? ` · from ${data.source_detail}` : ''}
          </>
        }
        actions={
          open ? (
            <>
              {phone ? (
                <>
                  <a className="btn btn-icon" href={`tel:${phone}`} aria-label="Call customer" title="Call">
                    <Phone size={15} />
                  </a>
                  <a className="btn btn-icon" href={`https://wa.me/${phone.replace(/\D/g, '').replace(/^(\d{10})$/, '91$1')}?text=${encodeURIComponent(`Hello ${who}, following up on your enquiry ${data.enquiry_number}.`)}`} target="_blank" rel="noreferrer" aria-label="WhatsApp customer" title="WhatsApp">
                    <MessageCircle size={15} />
                  </a>
                </>
              ) : null}
              <a className="btn" href={`/api/enquiries/${id}/quotation.pdf`} target="_blank" rel="noreferrer">
                <FileText size={14} /> Quote PDF
              </a>
              <Button kind="quiet" icon={<Sparkles size={14} />} onClick={() => ask(`Draft a WhatsApp quote reply to ${who} for enquiry ${data.enquiry_number} (id ${id}): list each product with quantity and quoted price, the total, availability from current stock, and a polite close. Keep it short and ready to send.`)}>
                Draft quote reply
              </Button>
              {data.customer ? (
                <Button icon={<BadgePercent size={14} />} busy={applyPrices.isPending} onClick={() => applyPrices.mutate(undefined)} title="Use the best of the customer's own prices, discount and group prices on every line">
                  Apply best prices
                </Button>
              ) : null}
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
                items={[
                  { label: 'Quotation PDF', icon: <FileText size={14} />, onSelect: () => window.open(`/api/enquiries/${id}/quotation.pdf`, '_blank') },
                  { label: 'Mark as lost', icon: <ThumbsDown size={14} />, onSelect: askLost, danger: true, separator: true },
                ]}
              />
            </>
          ) : data.sales_order_id ? (
            <Button kind="primary" onClick={() => navigate(`/orders/${data.sales_order_id}`)}>
              Open {data.sales_order_number}
            </Button>
          ) : null
        }
      />
      {!data.customer && open ? (
        <div className="shrink-0 px-6 pt-4">
          <div className="flex flex-wrap items-center gap-3 rounded-2xl bg-[#0b0b0c] px-4 py-3 text-[13px] text-[#fff]">
            <UserRoundX size={16} />
            <span className="min-w-0 flex-1">
              <b>New sender.</b> {[data.sender_name, data.sender_phone, data.sender_email].filter(Boolean).join(' · ') || 'No details'} is not on file. Choose or add the customer before it becomes an order.
            </span>
            <button onClick={() => setAssigning('assign')} className="btn btn-sm shrink-0 bg-blue! text-[#0b0b0c]!">
              <Link2 size={13} /> Assign customer
            </button>
          </div>
        </div>
      ) : null}
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
        {convert.error ? (
          <div className="px-6 pt-4">
            {holdFrom(convert.error) ? (
              <HoldPanel error={convert.error} busy={convert.isPending} onApprove={(reason) => convert.mutate(reason, { onSuccess: (result) => navigate(`/orders/${result.order.id}`) })} />
            ) : (
              <Notice tone="bad">{errorText(convert.error)}</Notice>
            )}
          </div>
        ) : null}
        {open ? <WinPanel priority={funnel.data?.priorities.find((row) => row.enquiry_id === id)} warnings={check.data?.warnings ?? []} checked={Boolean(check.data)} onAsk={() => ask(`What discount can I offer on enquiry ${data.enquiry_number} (id ${id}) and still keep a healthy margin? Use product_prices for cost and what ${who} paid before.`)} /> : null}
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
      <AssignCustomer
        enquiry={data}
        open={assigning !== null}
        onClose={() => setAssigning(null)}
        then={assigning === 'convert' ? 'Assign and continue' : undefined}
        onDone={() => {
          if (assigning === 'convert') convert.mutate(undefined, { onSuccess: (result) => navigate(`/orders/${result.order.id}`) })
        }}
      />
      {confirm.element}
    </>
  )
}

/** Why this enquiry matters and what to watch before quoting. */
function WinPanel({ priority, warnings, checked, onAsk }: { priority?: { score: number; reasons: string[]; in_stock: boolean; days_idle: number }; warnings: { level: 'critical' | 'warning' | 'info'; kind: string; text: string }[]; checked: boolean; onAsk: () => void }) {
  return (
    <div className="grid grid-cols-2 gap-3 px-6 pt-4 pb-2 max-lg:grid-cols-1">
      <div className="pane-contrast rounded-2xl! p-4">
        <div className="flex items-center gap-2">
          <span className="glass-tile size-8 rounded-[10px]!">{priority && priority.score >= 60 ? <Flame size={15} /> : <Target size={15} />}</span>
          <div>
            <div className="text-[12px] opacity-70">Priority</div>
            <div className="num text-[20px] leading-none font-semibold">{priority ? `${priority.score} / 100` : '—'}</div>
          </div>
        </div>
        <ul className="mt-3 space-y-1 text-[12.5px]">
          {(priority?.reasons ?? ['No priority yet']).map((reason) => (
            <li key={reason} className="flex gap-1.5">
              <CheckCircle2 size={13} className="mt-0.5 shrink-0 opacity-70" /> {reason}
            </li>
          ))}
        </ul>
      </div>
      <div className="card p-4">
        <div className="flex items-center gap-2 text-[13px] font-semibold">
          <ShieldCheck size={14} /> Before you quote
        </div>
        <div className="mt-2.5">
          {warnings.length ? <WarningList warnings={warnings} /> : checked ? <p className="text-[12.5px] text-fg-3">Margins, stock and credit look fine for these prices.</p> : <Spinner />}
        </div>
        <Button small kind="quiet" className="mt-3" icon={<Sparkles size={13} />} onClick={onAsk}>
          What discount can I give?
        </Button>
      </div>
    </div>
  )
}
