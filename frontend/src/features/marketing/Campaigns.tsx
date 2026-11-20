import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  AlertTriangle,
  Ban,
  ChevronDown,
  Info,
  CheckCircle2,
  Copy,
  ExternalLink,
  Image as ImageIcon,
  ImagePlus,
  Instagram,
  Megaphone,
  MessageCircle,
  MoreHorizontal,
  Pause,
  Pencil,
  Plus,
  Send,
  ShieldCheck,
  Sparkles,
  Trash2,
  Undo2,
  Upload,
  WandSparkles,
} from 'lucide-react'
import { marketing, CONTENT_LABEL, type Campaign, type CampaignIn, type Channel, type Content, type Media, type Template } from '@/api/marketing'
import { useAction } from '@/api/queries'
import { cn } from '@/lib/cn'
import { fmtAgo, fmtDate, fmtDateTime, fmtMoneyRound } from '@/lib/format'
import { Badge, Button, Empty, Field, Notice, SearchBox, Spinner } from '@/ui/core'
import { Menu, Segmented, Sheet, TabPanel, Tabs, useConfirm } from '@/ui/overlays'
import { Picker } from '@/ui/pickers'
import { productOption, useProducts } from '@/ui/lines'
import { ListPane, ListRow, Section, SplitView } from '@/ui/split'
import { AudienceBuilder } from './Audiences'
import { ChannelChips, FunnelBars, PhonePreview, PostPreview, StatusBadge, fromLocalInput, pct, toLocalInput } from './shared'

const FILTERS = [
  { value: 'active', label: 'Active', statuses: 'draft,review,approved,running,paused' },
  { value: 'done', label: 'Done', statuses: 'completed,cancelled' },
  { value: 'all', label: 'All', statuses: '' },
] as const
const EDITABLE = ['draft', 'review', 'paused']

export function Campaigns() {
  const [params, setParams] = useSearchParams()
  const selected = params.get('id')
  const filter = (params.get('show') as (typeof FILTERS)[number]['value']) ?? 'active'
  const [q, setQ] = useState('')
  const [creating, setCreating] = useState(false)
  const list = useQuery({
    queryKey: ['marketing', 'campaigns', filter, q],
    queryFn: () => marketing.campaigns({ status: FILTERS.find((f) => f.value === filter)?.statuses || undefined, q: q || undefined }),
  })
  const set = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params)
    Object.entries(patch).forEach(([k, v]) => (v === null ? next.delete(k) : next.set(k, v)))
    setParams(next, { replace: true })
  }
  const items = list.data?.items ?? []
  useEffect(() => {
    if (!selected && items.length && window.innerWidth >= 1024) set({ id: items[0].id })
  }, [items.length]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <>
      <SplitView
        listWidth={320}
        showDetail={Boolean(selected)}
        onBack={() => set({ id: null })}
        list={
          <ListPane
            title="Campaigns"
            count={items.length}
            actions={
              <Button small kind="primary" icon={<Plus size={14} />} onClick={() => setCreating(true)}>
                New
              </Button>
            }
            filters={
              <div className="space-y-2">
                <SearchBox value={q} onChange={setQ} placeholder="Name or code" />
                <Segmented value={filter} onChange={(v) => set({ show: v, id: null })} options={FILTERS.map((f) => ({ value: f.value, label: f.label }))} />
              </div>
            }
          >
            {list.isPending ? (
              <Spinner />
            ) : items.length ? (
              items.map((c) => (
                <ListRow key={c.id} group="mc" selected={selected === c.id} onSelect={() => set({ id: c.id })} alert={c.health.level === 'bad'}>
                  <div className="flex items-center gap-2">
                    <span className="min-w-0 flex-1 truncate text-[13.5px] font-semibold">{c.name}</span>
                    <StatusBadge status={c.status} />
                  </div>
                  <div className="mt-1 flex items-center gap-2 text-[12px] text-fg-3">
                    <ChannelChips channels={c.channels} />
                    <span className="truncate">{c.objective_label}</span>
                    <span className="num ml-auto shrink-0">
                      {c.funnel.sent ? `${c.funnel.sent} sent` : c.next_at ? fmtDate(c.next_at) : fmtAgo(c.updated_at)}
                      {c.conversions.revenue ? ` · ${fmtMoneyRound(c.conversions.revenue)}` : ''}
                    </span>
                  </div>
                </ListRow>
              ))
            ) : (
              <Empty icon={<Megaphone size={20} />} title="No campaigns here" body="Start one from an opportunity on the marketing home, or press New." />
            )}
          </ListPane>
        }
      >
        {selected ? <CampaignDetail key={selected} id={selected} onGone={() => set({ id: null })} /> : <Empty className="h-full" icon={<Megaphone size={22} />} title="Choose a campaign" />}
      </SplitView>
      <CampaignSheet open={creating} onClose={() => setCreating(false)} onSaved={(c) => set({ id: c.id, show: 'active' })} />
    </>
  )
}

// ---------------------------------------------------------------------------
// Detail
// ---------------------------------------------------------------------------

function CampaignDetail({ id, onGone }: { id: string; onGone: () => void }) {
  const data = useQuery({ queryKey: ['marketing', 'campaign', id], queryFn: () => marketing.campaign(id), refetchInterval: 15000 })
  const [tab, setTab] = useState('content')
  const [editing, setEditing] = useState(false)
  const [writing, setWriting] = useState(false)
  const [checksOpen, setChecksOpen] = useState(false)
  const confirm = useConfirm()
  const submit = useAction(marketing.submit, { success: (c) => (c.status === 'review' ? 'Sent for approval' : 'Saved') })
  const approve = useAction(marketing.approve, { success: 'Approved: it goes out on schedule' })
  const reject = useAction(marketing.reject, { success: 'Sent back to draft' })
  const pause = useAction(marketing.pause, { success: 'Paused' })
  const cancel = useAction(marketing.cancel, { success: 'Cancelled' })
  const duplicate = useAction(marketing.duplicate, { success: 'Copied as a new draft' })
  const remove = useAction(marketing.remove, { success: 'Deleted' })
  const [, setParams] = useSearchParams()
  if (data.isPending) return <Spinner />
  if (!data.data) return <Empty title="Campaign not found" />
  const c = data.data
  const editable = EDITABLE.includes(c.status)
  const unique = (c.checks ?? []).filter((x, i, all) => all.findIndex((y) => y.text === x.text) === i)
  const blocks = unique.filter((x) => x.level === 'block')
  const warns = unique.filter((x) => x.level === 'warn')

  const actions = (
    <div className="flex flex-wrap items-center gap-2">
      {c.status === 'draft' || c.status === 'paused' ? (
        <>
          <Button icon={<WandSparkles size={14} />} onClick={() => setWriting(true)}>
            Write with AI
          </Button>
          <Button kind="primary" icon={<Send size={14} />} busy={submit.isPending} disabled={blocks.length > 0} onClick={() => submit.mutate(c.id)} title={blocks[0]?.text}>
            Send for approval
          </Button>
        </>
      ) : null}
      {c.status === 'review' ? (
        <>
          <Button
            icon={<Undo2 size={14} />}
            busy={reject.isPending}
            onClick={async () => {
              const answer = await confirm.ask({ title: 'Send back to draft?', body: 'Say what to change; it is kept in the activity log.', confirm: 'Send back', withReason: true })
              if (answer.ok) reject.mutate({ id: c.id, reason: answer.reason })
            }}
          >
            Send back
          </Button>
          <Button
            kind="primary"
            icon={<ShieldCheck size={14} />}
            busy={approve.isPending}
            onClick={async () => {
              const answer = await confirm.ask({
                title: 'Approve and schedule?',
                body: `${c.contents?.length ?? 0} item(s) go out at their scheduled times${c.channels.includes('whatsapp') ? `; WhatsApp only to customers who agreed to offers (${c.funnel.audience || 'audience'} checked at send time)` : ''}.`,
                confirm: 'Approve',
              })
              if (answer.ok) approve.mutate(c.id)
            }}
          >
            Approve
          </Button>
        </>
      ) : null}
      {c.status === 'approved' || c.status === 'running' ? (
        <Button icon={<Pause size={14} />} busy={pause.isPending} onClick={() => pause.mutate(c.id)}>
          Pause
        </Button>
      ) : null}
      <Menu
        trigger={
          <Button iconOnly aria-label="More actions">
            <MoreHorizontal size={16} />
          </Button>
        }
        items={[
          ...(editable ? [{ label: 'Edit plan', icon: <Pencil size={14} />, onSelect: () => setEditing(true) }] : []),
          { label: 'Duplicate', icon: <Copy size={14} />, onSelect: () => duplicate.mutate(c.id, { onSuccess: (copy) => setParams({ id: copy.id }) }) },
          ...(['completed', 'cancelled'].includes(c.status)
            ? []
            : [
                {
                  label: 'Cancel campaign',
                  icon: <Ban size={14} />,
                  danger: true,
                  onSelect: async () => {
                    const answer = await confirm.ask({ title: 'Cancel this campaign?', body: 'Nothing more goes out. What was already sent stays in the results.', confirm: 'Cancel campaign', danger: true })
                    if (answer.ok) cancel.mutate(c.id)
                  },
                },
              ]),
          ...(['draft', 'cancelled'].includes(c.status) && !c.funnel.audience
            ? [
                {
                  label: 'Delete',
                  icon: <Trash2 size={14} />,
                  danger: true,
                  onSelect: async () => {
                    const answer = await confirm.ask({ title: 'Delete this campaign?', confirm: 'Delete', danger: true })
                    if (answer.ok) remove.mutate(c.id, { onSuccess: onGone })
                  },
                },
              ]
            : []),
        ]}
      />
    </div>
  )

  const showChecks = ['draft', 'review', 'paused'].includes(c.status)
  const stats = [
    `${c.funnel.audience || c.audience_count || 0} people`,
    c.funnel.sent ? `${c.funnel.sent} sent · ${pct(c.funnel.read, c.funnel.delivered)} read` : null,
    c.instagram.reach ? `${c.instagram.reach.toLocaleString('en-IN')} reached` : null,
    c.conversions.orders || c.conversions.enquiries ? `${c.conversions.orders} orders · ${c.conversions.enquiries} enquiries` : null,
    c.conversions.revenue ? fmtMoneyRound(c.conversions.revenue) : null,
  ].filter(Boolean)
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="shrink-0 border-b border-white/7 px-5 pt-3.5 pb-3 max-md:px-3">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <h2 className="truncate text-[17px] font-semibold tracking-[-0.01em]" title={c.name}>
              {c.name}
            </h2>
            <StatusBadge status={c.status} />
            <ChannelChips channels={c.channels} className="max-sm:hidden" />
          </div>
          {actions}
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1.5 text-[12px] text-fg-3">
          <span>
            {c.objective_label} · {c.code}
          </span>
          {stats.map((x) => (
            <span key={x as string} className="before:mr-2 before:content-['·']">
              {x}
            </span>
          ))}
          {c.health.level !== 'muted' && !showChecks ? (
            <Badge tone={c.health.level === 'bad' ? 'bad' : c.health.level === 'warn' ? 'warn' : 'ok'} title={c.health.why}>
              {c.health.label}
            </Badge>
          ) : null}
          {showChecks ? (
            <button
              onClick={() => setChecksOpen((v) => !v)}
              aria-expanded={checksOpen}
              className={cn(
                'ml-auto inline-flex h-6 items-center gap-1.5 rounded-full px-2.5 text-[11.5px] font-semibold',
                blocks.length ? 'bg-bad/12 text-bad' : warns.length ? 'bg-warn/12 text-warn' : 'bg-ok/12 text-ok',
              )}
            >
              {blocks.length ? <AlertTriangle size={12} /> : <CheckCircle2 size={12} />}
              {blocks.length ? `${blocks.length} to fix before approval` : warns.length ? `Ready · ${warns.length} note${warns.length === 1 ? '' : 's'}` : 'Ready for approval'}
              {blocks.length || warns.length ? <ChevronDown size={12} className={cn('transition-transform', checksOpen && 'rotate-180')} /> : null}
            </button>
          ) : null}
        </div>
        {showChecks && checksOpen && (blocks.length || warns.length) ? (
          <ul className="mt-2.5 space-y-1 rounded-[12px] bg-white/4 p-2.5 text-[12.5px]">
            {[...blocks, ...warns].map((x) => (
              <li key={x.text} className="flex gap-2">
                {x.level === 'block' ? <AlertTriangle size={13} className="mt-0.5 shrink-0 text-bad" /> : <Info size={13} className="mt-0.5 shrink-0 text-fg-3" />}
                <span className={x.level === 'block' ? 'font-medium' : 'text-fg-2'}>{x.text}</span>
              </li>
            ))}
          </ul>
        ) : null}
      </header>
      <Tabs
        value={tab}
        onChange={setTab}
        className="min-h-0 flex-1"
        tabs={[
          { value: 'content', label: 'Content', count: c.contents?.length },
          { value: 'plan', label: 'Plan' },
          { value: 'audience', label: 'Audience' },
          { value: 'results', label: 'Results' },
          { value: 'activity', label: 'Activity' },
        ]}
      >
        <TabPanel value="content" className="p-5 max-md:p-3">
          <ContentTab c={c} editable={editable} onWrite={() => setWriting(true)} />
        </TabPanel>
        <TabPanel value="plan" className="p-5 max-md:p-3">
          <PlanTab c={c} onEdit={editable ? () => setEditing(true) : undefined} />
        </TabPanel>
        <TabPanel value="audience" className="p-5 max-md:p-3">
          <AudienceTab c={c} />
        </TabPanel>
        <TabPanel value="results" className="p-5 max-md:p-3">
          <ResultsTab c={c} />
        </TabPanel>
        <TabPanel value="activity" className="p-5 max-md:p-3">
          <ActivityTab id={c.id} />
        </TabPanel>
      </Tabs>
      <CampaignSheet open={editing} onClose={() => setEditing(false)} editing={c} onSaved={() => setEditing(false)} />
      <WriteSheet open={writing} onClose={() => setWriting(false)} campaign={c} />
      {confirm.element}
    </div>
  )
}

function PlanTab({ c, onEdit }: { c: Campaign; onEdit?: () => void }) {
  return (
    <div className="max-w-3xl space-y-4">
      <Section title="Plan" actions={onEdit ? <Button small icon={<Pencil size={13} />} onClick={onEdit}>Edit</Button> : undefined}>
        <dl className="grid grid-cols-[150px_1fr] gap-x-4 gap-y-2.5 text-[13px] max-sm:grid-cols-1">
          <dt className="text-fg-3">Goal</dt>
          <dd>{c.objective_label}</dd>
          <dt className="text-fg-3">Offer</dt>
          <dd>{c.offer || '—'}</dd>
          <dt className="text-fg-3">Products</dt>
          <dd>{c.products?.length ? c.products.map((p) => `${p.name} (${p.stock} ${p.unit} in stock)`).join(', ') : '—'}</dd>
          <dt className="text-fg-3">Who</dt>
          <dd>{c.audience_summary}</dd>
          <dt className="text-fg-3">When</dt>
          <dd>
            {c.starts_at ? fmtDateTime(c.starts_at) : 'When approved'}
            {c.ends_at ? ` → ${fmtDateTime(c.ends_at)}` : ''}
          </dd>
          <dt className="text-fg-3">Budget</dt>
          <dd>{c.budget !== null ? `${fmtMoneyRound(c.budget)} (spent ${fmtMoneyRound(c.cost)})` : `${fmtMoneyRound(c.cost)} spent so far`}</dd>
          {c.brief ? (
            <>
              <dt className="text-fg-3">Why</dt>
              <dd className="leading-relaxed text-fg-2">{c.brief}</dd>
            </>
          ) : null}
        </dl>
      </Section>
    </div>
  )
}

function AudienceTab({ c }: { c: Campaign }) {
  const data = useQuery({ queryKey: ['marketing', 'campaign-audience', c.id, c.updated_at], queryFn: () => marketing.audienceOf(c.id) })
  if (data.isPending) return <Spinner />
  const p = data.data
  if (!p) return null
  const wa = p.reach.whatsapp
  return (
    <div className="max-w-3xl space-y-4">
      <p className="text-[13px] text-fg-2">{c.audience_summary}</p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <div className="card p-3">
          <div className="text-[12px] text-fg-3">In the audience</div>
          <div className="num text-[22px] font-semibold">{p.count}</div>
        </div>
        {wa ? (
          <div className="card p-3">
            <div className="text-[12px] text-fg-3">Can get WhatsApp offers</div>
            <div className="num text-[22px] font-semibold">{wa.reachable}</div>
          </div>
        ) : null}
      </div>
      {wa && Object.keys(wa.blocked).length ? (
        <Section title="Not messaged, and why">
          <div className="space-y-1 text-[13px]">
            {Object.entries(wa.blocked).map(([why, count]) => (
              <div key={why} className="flex justify-between">
                <span>{why}</span>
                <span className="num font-semibold">{count}</span>
              </div>
            ))}
          </div>
          <p className="mt-2 text-[12px] text-fg-3">Record consent in Audiences → Consent. Promotions on WhatsApp go only to customers who agreed.</p>
        </Section>
      ) : null}
      <Section title={`People (${Math.min(p.sample.length, p.count)} of ${p.count})`}>
        <div className="overflow-x-auto">
          <table className="grid-table min-w-[520px]">
            <thead>
              <tr>
                <th>Customer</th>
                <th>Segment</th>
                <th className="r">Spend 12m</th>
                <th className="r">Last order</th>
                <th>WhatsApp</th>
              </tr>
            </thead>
            <tbody>
              {p.sample.map((s) => (
                <tr key={s.customer_id}>
                  <td className="font-medium">{s.name}</td>
                  <td>{s.segment ?? '—'}</td>
                  <td className="r num">{fmtMoneyRound(s.spend_12m ?? 0)}</td>
                  <td className="r num">{s.days_since_last_order === null ? 'Never' : `${s.days_since_last_order} days ago`}</td>
                  <td>{s.whatsapp_consent ? <Badge tone="ok">Agreed</Badge> : <Badge>No consent</Badge>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
    </div>
  )
}

function ResultsTab({ c }: { c: Campaign }) {
  const conv = useQuery({ queryKey: ['marketing', 'conversions', c.id, c.updated_at], queryFn: () => marketing.conversions(c.id) })
  const sends = useQuery({ queryKey: ['marketing', 'sends', c.id, c.updated_at], queryFn: () => marketing.sends(c.id) })
  const posts = (c.contents ?? []).filter((x) => x.channel === 'instagram' && x.status === 'published')
  return (
    <div className="max-w-5xl space-y-4">
      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 xl:grid-cols-5">
        {[
          { label: 'People', value: c.funnel.audience || c.audience_count || 0, hint: c.audience_name ?? 'in the audience' },
          { label: 'Sent', value: c.funnel.sent, hint: c.funnel.sent ? `${pct(c.funnel.read, c.funnel.delivered)} read` : 'nothing yet' },
          { label: 'Instagram reach', value: (c.instagram.reach || 0).toLocaleString('en-IN'), hint: `${c.instagram.likes || 0} likes · ${c.instagram.comments || 0} comments` },
          { label: 'Orders', value: c.conversions.orders, hint: `${c.conversions.enquiries} enquiries` },
          { label: 'Revenue', value: fmtMoneyRound(c.conversions.revenue), hint: c.roi === null ? `${fmtMoneyRound(c.cost)} cost` : `${c.roi.toFixed(1)}× return` },
        ].map((f) => (
          <div key={f.label} className="rounded-[12px] border border-white/7 px-3.5 py-3">
            <div className="text-[11.5px] text-fg-3">{f.label}</div>
            <div className="num text-[20px] font-semibold">{f.value}</div>
            <div className="truncate text-[11.5px] text-fg-3">{f.hint}</div>
          </div>
        ))}
      </div>
      {c.channels.includes('whatsapp') ? (
        <Section title="WhatsApp">
          <FunnelBars funnel={c.funnel} extra={[{ label: 'Orders', value: c.conversions.orders }]} />
          {c.funnel.skipped || c.funnel.failed ? (
            <p className="mt-2 text-[12px] text-fg-3">
              {c.funnel.skipped} skipped (no consent, opted out or capped) · {c.funnel.failed} not delivered
            </p>
          ) : null}
        </Section>
      ) : null}
      {posts.length ? (
        <Section title="Instagram">
          <div className="grid gap-3 sm:grid-cols-2">
            {posts.map((p) => (
              <div key={p.id} className="flex gap-3 rounded-[12px] border border-white/7 p-3">
                {p.media ? <img src={p.media.url} alt="" className="size-16 rounded-[8px] object-cover" /> : null}
                <div className="min-w-0 flex-1 text-[12.5px]">
                  <div className="num font-semibold">
                    {(p.metrics.reach ?? 0).toLocaleString('en-IN')} reached · {p.metrics.likes ?? 0} likes · {p.metrics.comments ?? 0} comments · {p.metrics.saved ?? 0} saves
                  </div>
                  <div className="text-fg-3">Posted {fmtDateTime(p.published_at)}{p.synced_at ? ` · updated ${fmtAgo(p.synced_at)}` : ''}</div>
                  {p.permalink ? (
                    <a className="mt-1 inline-flex items-center gap-1 font-medium text-sky" href={p.permalink} target="_blank" rel="noreferrer">
                      Open on Instagram <ExternalLink size={11} />
                    </a>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        </Section>
      ) : null}
      <Section title="Orders and enquiries counted" hint="An order or enquiry from someone who got a message counts within the attribution window (Settings).">
        {conv.data?.items.length ? (
          <table className="grid-table">
            <thead>
              <tr>
                <th>Customer</th>
                <th>What</th>
                <th>Why it counts</th>
                <th className="r">Value</th>
              </tr>
            </thead>
            <tbody>
              {conv.data.items.map((x) => (
                <tr key={x.id}>
                  <td>{x.customer ?? '—'}</td>
                  <td>{x.order_number ? `Order ${x.order_number}` : 'Enquiry'}</td>
                  <td className="text-fg-3">{x.why}</td>
                  <td className="r num">{x.value ? fmtMoneyRound(x.value) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-[12.5px] text-fg-3">None yet.</p>
        )}
      </Section>
      {sends.data?.items.length ? (
        <Section title="Every message">
          <div className="max-h-[420px] overflow-y-auto">
            <table className="grid-table">
              <thead>
                <tr>
                  <th>Customer</th>
                  <th>Status</th>
                  <th>When</th>
                </tr>
              </thead>
              <tbody>
                {sends.data.items.map((s) => (
                  <tr key={s.id}>
                    <td>{s.customer}</td>
                    <td>
                      <Badge tone={s.status === 'failed' ? 'bad' : s.status === 'skipped' ? 'muted' : s.status === 'replied' || s.status === 'read' ? 'ok' : 'sky'}>{s.status}</Badge>
                      {s.skip_reason || s.error ? <span className="ml-2 text-[11.5px] text-fg-3">{s.skip_reason || s.error}</span> : null}
                    </td>
                    <td className="text-fg-3">{fmtDateTime(s.replied_at || s.read_at || s.delivered_at || s.sent_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      ) : null}
    </div>
  )
}

function ActivityTab({ id }: { id: string }) {
  const data = useQuery({ queryKey: ['marketing', 'events', id], queryFn: () => marketing.events({ campaign_id: id }) })
  if (data.isPending) return <Spinner />
  const items = data.data?.items ?? []
  if (!items.length) return <Empty title="Nothing yet" />
  return (
    <ol className="max-w-3xl space-y-3">
      {items.map((e) => (
        <li key={e.id} className="flex gap-3 text-[13px]">
          <span className={cn('mt-1.5 size-2 shrink-0 rounded-full', e.level === 'error' ? 'bg-bad' : e.level === 'warning' ? 'bg-warn' : e.level === 'success' ? 'bg-ok' : 'bg-fg-4')} />
          <div>
            <p>{e.message}</p>
            <p className="text-[11.5px] text-fg-3">
              {e.actor} · {fmtDateTime(e.at)}
            </p>
          </div>
        </li>
      ))}
    </ol>
  )
}

// ---------------------------------------------------------------------------
// Content
// ---------------------------------------------------------------------------

function ContentTab({ c, editable, onWrite }: { c: Campaign; editable: boolean; onWrite: () => void }) {
  const add = useAction(marketing.addContent, { success: 'Added' })
  const contents = c.contents ?? []
  const [selected, setSelected] = useState<string | undefined>(contents[0]?.id)
  const known = contents.map((x) => x.id).join()
  useEffect(() => {
    if (!contents.some((x) => x.id === selected)) setSelected(contents[contents.length - 1]?.id)
  }, [known]) // eslint-disable-line react-hooks/exhaustive-deps
  const current = contents.find((x) => x.id === selected) ?? contents[0]
  if (!contents.length) {
    return (
      <Empty
        icon={<WandSparkles size={22} />}
        title="No content yet"
        body="Let the Creative agent write an Instagram post and a WhatsApp message from the plan, or add them yourself."
        action={
          editable ? (
            <div className="flex flex-wrap justify-center gap-2">
              <Button kind="primary" icon={<WandSparkles size={14} />} onClick={onWrite}>
                Write with AI
              </Button>
              <Button icon={<Instagram size={14} />} busy={add.isPending} onClick={() => add.mutate({ campaignId: c.id, channel: 'instagram' })}>
                Instagram post
              </Button>
              <Button icon={<MessageCircle size={14} />} busy={add.isPending} onClick={() => add.mutate({ campaignId: c.id, channel: 'whatsapp' })}>
                WhatsApp broadcast
              </Button>
            </div>
          ) : undefined
        }
      />
    )
  }
  return (
    <div className="grid gap-4 lg:grid-cols-[210px_minmax(0,1fr)]">
      <nav aria-label="Posts and messages" className="flex gap-2 overflow-x-auto pb-1 lg:sticky lg:top-0 lg:flex-col lg:self-start lg:overflow-visible lg:pb-0">
        {contents.map((x) => {
          const Icon = x.channel === 'instagram' ? Instagram : MessageCircle
          const active = x.id === current?.id
          return (
            <button
              key={x.id}
              onClick={() => setSelected(x.id)}
              aria-current={active ? 'true' : undefined}
              className={cn(
                'flex min-w-[190px] items-center gap-2.5 rounded-[12px] p-2 text-left ring-1 ring-inset transition-colors lg:min-w-0',
                active ? 'bg-white/8 ring-white/15' : 'ring-transparent hover:bg-white/4',
              )}
            >
              {x.media ? (
                <img src={x.media.url} alt="" className="size-10 shrink-0 rounded-[8px] object-cover" />
              ) : (
                <span className="grid size-10 shrink-0 place-items-center rounded-[8px] bg-white/7">
                  <Icon size={16} />
                </span>
              )}
              <span className="min-w-0">
                <span className="flex items-center gap-1 text-[12.5px] font-semibold">
                  <Icon size={11} className="shrink-0" />
                  {x.channel === 'instagram' ? 'Instagram post' : 'WhatsApp'}
                </span>
                <span className={cn('block truncate text-[11.5px]', x.status === 'failed' ? 'text-bad' : 'text-fg-3')}>
                  {CONTENT_LABEL[x.status]}
                  {x.scheduled_at && ['draft', 'scheduled'].includes(x.status) ? ` · ${fmtDate(x.scheduled_at)}` : ''}
                </span>
                <span className="block max-w-[150px] truncate text-[11.5px] text-fg-4">{(x.channel === 'instagram' ? x.caption : x.template_name ? `${x.template_name}` : x.caption) || 'Empty'}</span>
              </span>
            </button>
          )
        })}
        {editable ? (
          <Menu
            align="start"
            trigger={
              <Button small kind="ghost" icon={<Plus size={13} />} className="shrink-0 justify-start">
                Add
              </Button>
            }
            items={[
              { label: 'Write with AI', icon: <WandSparkles size={14} />, onSelect: onWrite },
              { label: 'Instagram post', icon: <Instagram size={14} />, onSelect: () => add.mutate({ campaignId: c.id, channel: 'instagram' }, { onSuccess: (n) => setSelected(n.id) }) },
              { label: 'WhatsApp broadcast', icon: <MessageCircle size={14} />, onSelect: () => add.mutate({ campaignId: c.id, channel: 'whatsapp' }, { onSuccess: (n) => setSelected(n.id) }) },
            ]}
          />
        ) : null}
      </nav>
      <div className="min-w-0">
        {current ? (
          current.channel === 'instagram' ? (
            <InstagramEditor key={current.id} c={c} content={current} editable={editable} />
          ) : (
            <WhatsAppEditor key={current.id} c={c} content={current} editable={editable} />
          )
        ) : null}
      </div>
    </div>
  )
}

function ContentHeader({ content, icon: Icon, title, onRemove, actions }: { content: Content; icon: typeof Instagram; title: string; onRemove?: () => void; actions?: ReactNode }) {
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2">
      <Icon size={16} />
      <h3 className="text-[14px] font-semibold">{title}</h3>
      <Badge tone={content.status === 'failed' ? 'bad' : content.status === 'published' || content.status === 'sent' ? 'ok' : content.status === 'draft' ? 'muted' : 'sky'}>
        {CONTENT_LABEL[content.status]}
      </Badge>
      {content.ai_generated ? (
        <Badge tone="sky">
          <Sparkles size={11} /> AI draft
        </Badge>
      ) : null}
      {content.scheduled_at && ['draft', 'scheduled'].includes(content.status) ? <span className="text-[12px] text-fg-3">{fmtDateTime(content.scheduled_at)}</span> : null}
      <span className="ml-auto" />
      {actions}
      {onRemove ? (
        <Button small kind="ghost" iconOnly aria-label="Remove" onClick={onRemove}>
          <Trash2 size={14} />
        </Button>
      ) : null}
    </div>
  )
}

function useRemove() {
  const confirm = useConfirm()
  const remove = useAction(marketing.removeContent, { success: 'Removed' })
  return {
    element: confirm.element,
    run: async (id: string) => {
      const answer = await confirm.ask({ title: 'Remove this content?', confirm: 'Remove', danger: true })
      if (answer.ok) remove.mutate(id)
    },
  }
}

function InstagramEditor({ c, content, editable: campaignEditable }: { c: Campaign; content: Content; editable: boolean }) {
  const editable = campaignEditable && ['draft', 'scheduled', 'failed'].includes(content.status)
  const [caption, setCaption] = useState(content.caption ?? '')
  const [tags, setTags] = useState(content.hashtags.join(' '))
  const [when, setWhen] = useState(toLocalInput(content.scheduled_at))
  const [picking, setPicking] = useState(false)
  const save = useAction(marketing.updateContent, { success: 'Saved' })
  const settings = useQuery({ queryKey: ['marketing', 'settings'], queryFn: marketing.settings })
  const remover = useRemove()
  useEffect(() => {
    setCaption(content.caption ?? '')
    setTags(content.hashtags.join(' '))
    setWhen(toLocalInput(content.scheduled_at))
  }, [content.version, content.id]) // eslint-disable-line react-hooks/exhaustive-deps
  const hashtags = tags.split(/[\s,]+/).filter(Boolean)
  const dirty = caption !== (content.caption ?? '') || tags !== content.hashtags.join(' ') || when !== toLocalInput(content.scheduled_at)
  return (
    <section className="card p-4">
      <ContentHeader
        content={content}
        icon={Instagram}
        title="Instagram post"
        onRemove={editable ? () => remover.run(content.id) : undefined}
        actions={
          editable ? (
            <Button kind="primary" small disabled={!dirty} busy={save.isPending} onClick={() => save.mutate({ id: content.id, caption, hashtags, scheduled_at: fromLocalInput(when) })}>
              {dirty ? 'Save changes' : 'Saved'}
            </Button>
          ) : null
        }
      />
      {content.error ? <Notice tone={content.status === 'failed' ? 'bad' : 'warn'}>{content.error}</Notice> : null}
      <div className="mt-2 grid gap-5 md:grid-cols-[260px_minmax(0,1fr)]">
        <div className="space-y-2 md:sticky md:top-0 md:self-start">
          <PostPreview image={content.media?.url} caption={caption} hashtags={hashtags} username={String(settings.data?.instagram.config.username || '') || null} />
          {editable ? (
            <Button small className="w-full" icon={<ImagePlus size={13} />} onClick={() => setPicking(true)}>
              {content.media ? 'Change image' : 'Add image'}
            </Button>
          ) : null}
        </div>
        <div className="space-y-3">
          {editable ? <RewriteBox id={content.id} /> : null}
          <Field label="Caption" hint={`${caption.length} / 2,200 · the first line shows before "more"`}>
            {(props) => <textarea {...props} className="field min-h-[150px]" value={caption} disabled={!editable} onChange={(e) => setCaption(e.target.value)} />}
          </Field>
          <Field label="Hashtags" hint={`${hashtags.length} / 30, separated by spaces`}>
            {(props) => <input {...props} className="field" value={tags} disabled={!editable} onChange={(e) => setTags(e.target.value)} placeholder="#cement #ahmedabad" />}
          </Field>
          <Field label="Post at" optional hint="Empty: as soon as the campaign is approved.">
            {(props) => <input {...props} type="datetime-local" className="field max-w-[260px]" value={when} disabled={!editable} onChange={(e) => setWhen(e.target.value)} />}
          </Field>
          {content.permalink ? (
            <a className="inline-flex items-center gap-1 text-[12.5px] font-medium text-sky" href={content.permalink} target="_blank" rel="noreferrer">
              Open on Instagram <ExternalLink size={11} />
            </a>
          ) : null}
        </div>
      </div>
      <MediaPicker open={picking} onClose={() => setPicking(false)} campaign={c} onPick={(m) => save.mutate({ id: content.id, media_id: m.id }, { onSuccess: () => setPicking(false) })} />
      {remover.element}
    </section>
  )
}

const SAMPLE = { '{first_name}': 'Ramesh', '{name}': 'Ramesh Patel', '{business}': 'your business', '{link}': 'https://…/e/…' }

function WhatsAppEditor({ c, content, editable: campaignEditable }: { c: Campaign; content: Content; editable: boolean }) {
  const editable = campaignEditable && ['draft', 'scheduled', 'failed'].includes(content.status)
  const templates = useQuery({ queryKey: ['marketing', 'templates'], queryFn: marketing.templates })
  const [template, setTemplate] = useState(content.template_name ?? '')
  const [values, setValues] = useState<string[]>(content.variables)
  const [when, setWhen] = useState(toLocalInput(content.scheduled_at))
  const [picking, setPicking] = useState(false)
  const save = useAction(marketing.updateContent, { success: 'Saved' })
  const remover = useRemove()
  const focused = useRef<number>(0)
  useEffect(() => {
    setTemplate(content.template_name ?? '')
    setValues(content.variables)
    setWhen(toLocalInput(content.scheduled_at))
  }, [content.version, content.id]) // eslint-disable-line react-hooks/exhaustive-deps
  const all = templates.data?.items ?? []
  const usable = all.filter((t) => t.category === 'MARKETING')
  const chosen: Template | undefined = all.find((t) => t.name === template)
  useEffect(() => {
    if (chosen && values.length !== chosen.variable_count) setValues(Array.from({ length: chosen.variable_count }, (_, i) => values[i] ?? ''))
  }, [chosen?.name]) // eslint-disable-line react-hooks/exhaustive-deps
  const product = c.products?.[0]?.name ?? 'our products'
  const fill = (v: string) =>
    Object.entries({ ...SAMPLE, '{product}': product, '{offer}': c.offer ?? '' }).reduce((text, [k, r]) => text.split(k).join(r), v)
  const text = chosen ? values.reduce((body, v, i) => body.split(`{{${i + 1}}}`).join(fill(v) || `{{${i + 1}}}`), chosen.body) : ''
  const dirty = template !== (content.template_name ?? '') || JSON.stringify(values) !== JSON.stringify(content.variables) || when !== toLocalInput(content.scheduled_at)
  const insert = (token: string) => setValues((old) => old.map((v, i) => (i === focused.current ? `${v}${v && !v.endsWith(' ') ? ' ' : ''}${token}` : v)))
  return (
    <section className="card p-4">
      <ContentHeader
        content={content}
        icon={MessageCircle}
        title="WhatsApp broadcast"
        onRemove={editable ? () => remover.run(content.id) : undefined}
        actions={
          editable ? (
            <Button
              kind="primary"
              small
              disabled={!dirty}
              busy={save.isPending}
              onClick={() => save.mutate({ id: content.id, template_name: template || null, template_language: chosen?.language ?? null, variables: values, scheduled_at: fromLocalInput(when) })}
            >
              {dirty ? 'Save changes' : 'Saved'}
            </Button>
          ) : null
        }
      />
      {content.error ? <Notice tone="bad">{content.error}</Notice> : null}
      <div className="mt-2 grid gap-5 md:grid-cols-[280px_minmax(0,1fr)]">
        <div className="space-y-2 md:sticky md:top-0 md:self-start">
          <PhonePreview text={text} image={content.media?.url} header={chosen?.header} footer={chosen?.footer} />
          <p className="text-[11.5px] text-fg-3">Shown for a sample customer (Ramesh). Each customer gets their own name and link.</p>
          {chosen?.header === 'IMAGE' && editable ? (
            <Button small className="w-full" icon={<ImageIcon size={13} />} onClick={() => setPicking(true)}>
              {content.media ? 'Change image' : 'Add image'}
            </Button>
          ) : null}
        </div>
        <div className="space-y-3">
          {!usable.length ? (
            <Notice tone="warn">
              No marketing templates yet. WhatsApp only allows approved templates for offers. Create one in Channels → WhatsApp (the AI can draft it), then sync.
            </Notice>
          ) : null}
          {editable && chosen ? <RewriteBox id={content.id} /> : null}
          <Field label="Template" hint={chosen ? `${chosen.status.toLowerCase()} · ${chosen.category.toLowerCase()} · ${chosen.language}` : 'Only approved marketing templates can be sent.'}>
            {(props) => (
              <Picker
                id={props.id}
                value={template}
                onChange={setTemplate}
                disabled={!editable}
                placeholder="Choose a template…"
                options={usable.map((t) => ({ value: t.name, label: t.name, detail: t.body.slice(0, 70), trail: <Badge tone={t.status === 'APPROVED' ? 'ok' : 'warn'}>{t.status.toLowerCase()}</Badge> }))}
              />
            )}
          </Field>
          {chosen
            ? values.map((v, i) => (
                <Field key={i} label={`Blank {{${i + 1}}}`}>
                  {(props) => (
                    <input
                      {...props}
                      className="field"
                      value={v}
                      disabled={!editable}
                      onFocus={() => (focused.current = i)}
                      onChange={(e) => {
                        const next = e.target.value
                        setValues((old) => old.map((x, j) => (j === i ? next : x)))
                      }}
                    />
                  )}
                </Field>
              ))
            : null}
          {chosen && editable ? (
            <div className="flex flex-wrap items-center gap-1.5 text-[12px]">
              <span className="text-fg-3">Insert per customer:</span>
              {['{first_name}', '{name}', '{product}', '{offer}', '{link}'].map((t) => (
                <button key={t} onClick={() => insert(t)} className="rounded-full bg-white/7 px-2 py-0.5 font-mono text-[11.5px] hover:bg-white/12">
                  {t}
                </button>
              ))}
            </div>
          ) : null}
          <Field label="Send at" optional hint="Empty: as soon as approved. Nothing goes out during quiet hours; it waits for the morning.">
            {(props) => <input {...props} type="datetime-local" className="field max-w-[260px]" value={when} disabled={!editable} onChange={(e) => setWhen(e.target.value)} />}
          </Field>
          {content.caption ? <p className="text-[12px] text-fg-3">Idea: {content.caption}</p> : null}
        </div>
      </div>
      <MediaPicker open={picking} onClose={() => setPicking(false)} campaign={c} onPick={(m) => save.mutate({ id: content.id, media_id: m.id }, { onSuccess: () => setPicking(false) })} />
      {remover.element}
    </section>
  )
}

function RewriteBox({ id }: { id: string }) {
  const [text, setText] = useState('')
  const rewrite = useAction(marketing.rewrite, { success: 'Rewritten' })
  const chips = ['Shorter', 'More urgent', 'In Hindi', 'In Gujarati', 'Friendlier']
  return (
    <div className="flex min-w-[260px] flex-1 flex-wrap items-center gap-1.5">
      <input className="field field-sm max-w-[220px]" value={text} onChange={(e) => setText(e.target.value)} placeholder="Ask AI to change it…" aria-label="How to rewrite" />
      <Button small icon={<Sparkles size={12} />} busy={rewrite.isPending} disabled={!text.trim()} onClick={() => rewrite.mutate({ id, instructions: text }, { onSuccess: () => setText('') })}>
        Rewrite
      </Button>
      {chips.map((chip) => (
        <button key={chip} onClick={() => rewrite.mutate({ id, instructions: chip })} className="rounded-full bg-white/6 px-2 py-0.5 text-[11.5px] font-medium text-fg-2 hover:bg-white/10">
          {chip}
        </button>
      ))}
    </div>
  )
}

/** Choose an image: a product card, an AI image, an upload or one from the library. */
export function MediaPicker({ open, onClose, campaign, onPick }: { open: boolean; onClose: () => void; campaign?: Campaign; onPick: (m: Media) => void }) {
  const [mode, setMode] = useState<'library' | 'card' | 'ai' | 'upload'>('card')
  const library = useQuery({ queryKey: ['marketing', 'media'], queryFn: () => marketing.media(), enabled: open })
  const products = useProducts()
  const [product, setProduct] = useState(campaign?.product_ids[0] ?? '')
  const [offer, setOffer] = useState(campaign?.offer ?? '')
  const [prompt, setPrompt] = useState('')
  const card = useAction(marketing.productCard)
  const custom = useAction(marketing.card)
  const image = useAction(marketing.image)
  const upload = useAction(({ file }: { file: File }) => marketing.upload(file, campaign?.id))
  const [headline, setHeadline] = useState(campaign?.name ?? '')
  const done = (m: Media) => onPick(m)
  return (
    <Sheet open={open} onClose={onClose} title="Choose an image" subtitle="Instagram shows images at 4:5; cards are drawn in your brand colours." width={820}>
      <div className="space-y-4">
        <Segmented
          value={mode}
          onChange={setMode}
          options={[
            { value: 'card', label: 'Product card' },
            { value: 'ai', label: 'AI image' },
            { value: 'upload', label: 'Upload' },
            { value: 'library', label: 'Library' },
          ]}
        />
        {mode === 'card' ? (
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Product" optional hint="Uses its name, brand, details and price.">
              {(props) => <Picker id={props.id} value={product} onChange={setProduct} options={products.items.map(productOption)} placeholder="Choose a product…" />}
            </Field>
            <Field label="Offer line" optional>
              {(props) => <input {...props} className="field" value={offer} onChange={(e) => setOffer(e.target.value)} placeholder="Free delivery above 100 bags" />}
            </Field>
            {!product ? (
              <Field label="Headline" className="sm:col-span-2">
                {(props) => <input {...props} className="field" value={headline} onChange={(e) => setHeadline(e.target.value)} placeholder="Happy Diwali" />}
              </Field>
            ) : null}
            <div className="sm:col-span-2">
              <Button
                kind="primary"
                icon={<Sparkles size={14} />}
                busy={card.isPending || custom.isPending}
                disabled={!product && !headline.trim()}
                onClick={() =>
                  product
                    ? card.mutate({ product_id: product, offer: offer || undefined, campaign_id: campaign?.id }, { onSuccess: done })
                    : custom.mutate({ headline, subline: offer || undefined, campaign_id: campaign?.id, cta: 'Order on WhatsApp' }, { onSuccess: done })
                }
              >
                Draw the card
              </Button>
            </div>
          </div>
        ) : null}
        {mode === 'ai' ? (
          <div className="space-y-3">
            <Field label="Describe the picture" hint="A photo idea, without text. The brand colours and tone are added for you. Needs Gemini (Settings → AI).">
              {(props) => <textarea {...props} className="field min-h-[90px]" value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="Neatly stacked cement bags at a construction site at sunrise" />}
            </Field>
            <Button kind="primary" icon={<WandSparkles size={14} />} busy={image.isPending} disabled={prompt.trim().length < 8} onClick={() => image.mutate({ prompt, campaign_id: campaign?.id }, { onSuccess: done })}>
              Make the image
            </Button>
          </div>
        ) : null}
        {mode === 'upload' ? (
          <label className="grid cursor-pointer place-items-center gap-2 rounded-[14px] border border-dashed border-white/15 p-10 text-center text-[13px] text-fg-3 hover:bg-white/4">
            <Upload size={20} />
            {upload.isPending ? 'Uploading…' : 'Choose a JPEG or PNG (up to 8 MB). It is cropped to Instagram’s shape if needed.'}
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp"
              className="sr-only"
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (file) upload.mutate({ file }, { onSuccess: done })
              }}
            />
          </label>
        ) : null}
        {mode === 'library' ? (
          library.data?.items.length ? (
            <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
              {library.data.items.map((m) => (
                <button key={m.id} onClick={() => done(m)} className="overflow-hidden rounded-[10px] ring-1 ring-white/8 hover:ring-2 hover:ring-sky">
                  <img src={m.url} alt={m.name ?? ''} className="aspect-[4/5] w-full object-cover" loading="lazy" />
                </button>
              ))}
            </div>
          ) : (
            <Empty title="No images yet" />
          )
        ) : null}
      </div>
    </Sheet>
  )
}

// ---------------------------------------------------------------------------
// Create / edit, and the AI writer
// ---------------------------------------------------------------------------

function CampaignSheet({ open, onClose, editing, onSaved }: { open: boolean; onClose: () => void; editing?: Campaign; onSaved: (c: Campaign) => void }) {
  const objectives = useQuery({ queryKey: ['marketing', 'campaigns', 'objectives'], queryFn: () => marketing.campaigns({ status: 'none' }), enabled: open })
  const audiences = useQuery({ queryKey: ['marketing', 'audiences'], queryFn: marketing.audiences, enabled: open })
  const products = useProducts()
  const [form, setForm] = useState<CampaignIn & { useSaved: boolean; write: boolean }>({ useSaved: false, write: true })
  useEffect(() => {
    if (!open) return
    setForm({
      name: editing?.name ?? '',
      objective: editing?.objective ?? 'sales',
      channels: editing?.channels ?? ['whatsapp', 'instagram'],
      audience_id: editing?.audience_id ?? null,
      audience: editing?.audience ?? {},
      product_ids: editing?.product_ids ?? [],
      offer: editing?.offer ?? '',
      brief: editing?.brief ?? '',
      starts_at: editing?.starts_at ?? null,
      ends_at: editing?.ends_at ?? null,
      budget: editing?.budget ?? null,
      spend: editing?.spend ?? null,
      useSaved: Boolean(editing?.audience_id),
      write: !editing,
    })
  }, [open, editing?.id]) // eslint-disable-line react-hooks/exhaustive-deps
  const create = useAction(marketing.create, { success: 'Campaign created' })
  const update = useAction(marketing.update, { success: 'Saved' })
  const generate = useAction(marketing.generate, { success: 'Content written — review it before approving' })
  const set = (patch: Partial<typeof form>) => setForm((f) => ({ ...f, ...patch }))
  const toggle = (ch: Channel) => setForm((f) => ({ ...f, channels: f.channels?.includes(ch) ? f.channels.filter((x) => x !== ch) : [...(f.channels ?? []), ch] }))
  const save = () => {
    const { useSaved, write, ...body } = form
    const payload: CampaignIn = { ...body, audience_id: useSaved ? body.audience_id : null, audience: useSaved ? {} : body.audience }
    if (editing) {
      update.mutate({ id: editing.id, ...payload }, { onSuccess: onSaved })
    } else {
      create.mutate(payload, {
        onSuccess: (c) => {
          onSaved(c)
          onClose()
          if (write) generate.mutate({ id: c.id })
        },
      })
    }
  }
  const chosen = form.product_ids ?? []
  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={editing ? 'Edit campaign' : 'New campaign'}
      subtitle="The goal, the products, who it is for and when. Content comes next."
      width={860}
      footer={
        <div className="flex w-full items-center gap-2">
          {!editing ? (
            <label className="flex items-center gap-2 text-[12.5px]">
              <input type="checkbox" checked={form.write} onChange={(e) => set({ write: e.target.checked })} /> Have AI write the content
            </label>
          ) : null}
          <Button className="ml-auto" onClick={onClose}>
            Cancel
          </Button>
          <Button kind="primary" busy={create.isPending || update.isPending} disabled={!form.name?.trim() || !form.channels?.length} onClick={save}>
            {editing ? 'Save' : 'Create'}
          </Button>
        </div>
      }
    >
      <div className="grid grid-cols-2 gap-4 max-md:grid-cols-1">
        <Field label="Name" className="col-span-2 max-md:col-span-1">
          {(props) => <input {...props} className="field" autoFocus value={form.name ?? ''} onChange={(e) => set({ name: e.target.value })} placeholder="Diwali cement offer" />}
        </Field>
        <Field label="Goal">
          {(props) => (
            <Picker
              id={props.id}
              value={form.objective ?? 'sales'}
              onChange={(v) => set({ objective: v })}
              options={Object.entries(objectives.data?.objectives ?? { sales: 'Sell more' }).map(([value, label]) => ({ value, label }))}
            />
          )}
        </Field>
        <Field label="Channels">
          {() => (
            <div className="flex gap-2">
              {(['whatsapp', 'instagram'] as Channel[]).map((ch) => (
                <button
                  key={ch}
                  onClick={() => toggle(ch)}
                  aria-pressed={form.channels?.includes(ch)}
                  className={cn('flex h-9 items-center gap-1.5 rounded-full px-3.5 text-[12.5px] font-semibold ring-1 ring-inset', form.channels?.includes(ch) ? 'brand-fill text-on-brand ring-transparent' : 'ring-white/10 text-fg-2')}
                >
                  {ch === 'whatsapp' ? <MessageCircle size={13} /> : <Instagram size={13} />}
                  {ch === 'whatsapp' ? 'WhatsApp' : 'Instagram'}
                </button>
              ))}
            </div>
          )}
        </Field>
        <Field label="Products" optional className="col-span-2 max-md:col-span-1" hint="What the campaign promotes; the AI describes them from their details.">
          {(props) => (
            <div className="space-y-2">
              <Picker id={props.id} value="" onChange={(v) => v && !chosen.includes(v) && set({ product_ids: [...chosen, v] })} options={products.items.map(productOption)} placeholder="Add a product…" />
              {chosen.length ? (
                <div className="flex flex-wrap gap-1.5">
                  {chosen.map((pid) => (
                    <span key={pid} className="inline-flex items-center gap-1 rounded-full bg-white/7 py-0.5 pr-1 pl-2.5 text-[12px] font-medium">
                      {products.byId.get(pid)?.name ?? 'Product'}
                      <button aria-label="Remove" onClick={() => set({ product_ids: chosen.filter((x) => x !== pid) })} className="grid size-5 place-items-center rounded-full hover:bg-white/10">
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
          )}
        </Field>
        <Field label="Offer" optional className="col-span-2 max-md:col-span-1" hint="Only what you really offer; the AI never invents discounts.">
          {(props) => <input {...props} className="field" value={form.offer ?? ''} onChange={(e) => set({ offer: e.target.value })} placeholder="Free delivery above 100 bags till Sunday" />}
        </Field>
        <Field label="Notes for the AI" optional className="col-span-2 max-md:col-span-1">
          {(props) => <textarea {...props} className="field min-h-[70px]" value={form.brief ?? ''} onChange={(e) => set({ brief: e.target.value })} placeholder="Contractors in Ahmedabad; mention fresh stock and quick delivery." />}
        </Field>
        <div className="col-span-2 space-y-2 max-md:col-span-1">
          <div className="flex items-center justify-between">
            <span className="label mb-0">Who it is for</span>
            <Segmented
              value={form.useSaved ? 'saved' : 'build'}
              onChange={(v) => set({ useSaved: v === 'saved' })}
              options={[
                { value: 'build', label: 'Build here' },
                { value: 'saved', label: 'Saved audience' },
              ]}
            />
          </div>
          {form.useSaved ? (
            <Picker value={form.audience_id ?? ''} onChange={(v) => set({ audience_id: v })} options={(audiences.data?.items ?? []).map((a) => ({ value: a.id, label: a.name, detail: a.summary }))} placeholder="Choose an audience…" />
          ) : (
            <AudienceBuilder value={form.audience ?? {}} onChange={(audience) => set({ audience })} channels={form.channels} />
          )}
        </div>
        <Field label="Starts" optional hint="Content without its own time goes out then.">
          {(props) => <input {...props} type="datetime-local" className="field" value={toLocalInput(form.starts_at)} onChange={(e) => set({ starts_at: fromLocalInput(e.target.value) })} />}
        </Field>
        <Field label="Ends" optional>
          {(props) => <input {...props} type="datetime-local" className="field" value={toLocalInput(form.ends_at)} onChange={(e) => set({ ends_at: fromLocalInput(e.target.value) })} />}
        </Field>
        <Field label="Budget (₹)" optional>
          {(props) => <input {...props} className="field field-num" inputMode="decimal" value={form.budget ?? ''} onChange={(e) => set({ budget: e.target.value === '' ? null : Number(e.target.value) })} />}
        </Field>
        <Field label="Other spend (₹)" optional hint="Printing, boosts, designer. Message costs are added for you.">
          {(props) => <input {...props} className="field field-num" inputMode="decimal" value={form.spend ?? ''} onChange={(e) => set({ spend: e.target.value === '' ? null : Number(e.target.value) })} />}
        </Field>
      </div>
    </Sheet>
  )
}

function WriteSheet({ open, onClose, campaign }: { open: boolean; onClose: () => void; campaign: Campaign }) {
  const [channels, setChannels] = useState<Channel[]>(campaign.channels)
  const [image, setImage] = useState<'card' | 'ai' | 'none'>('card')
  const [instructions, setInstructions] = useState('')
  const generate = useAction(marketing.generate, { success: 'Content written — review it before approving' })
  const settings = useQuery({ queryKey: ['marketing', 'settings'], queryFn: marketing.settings, enabled: open })
  useEffect(() => setChannels(campaign.channels), [campaign.id, open]) // eslint-disable-line react-hooks/exhaustive-deps
  const toggle = (ch: Channel) => setChannels((old) => (old.includes(ch) ? old.filter((x) => x !== ch) : [...old, ch]))
  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Write content with AI"
      subtitle="The Creative agent writes from the plan, the products' details and your brand kit. Everything stays a draft until approved."
      width={620}
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button kind="primary" icon={<WandSparkles size={14} />} busy={generate.isPending} disabled={!channels.length} onClick={() => generate.mutate({ id: campaign.id, channels, image, instructions: instructions || undefined }, { onSuccess: onClose })}>
            Write
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        {settings.data && !settings.data.ai ? <Notice tone="warn">Gemini is not connected, so the text comes from simple templates you can edit. Connect it in Settings → AI for real copywriting.</Notice> : null}
        <Field label="For">
          {() => (
            <div className="flex gap-2">
              {(['instagram', 'whatsapp'] as Channel[]).map((ch) => (
                <button key={ch} onClick={() => toggle(ch)} aria-pressed={channels.includes(ch)} className={cn('flex h-9 items-center gap-1.5 rounded-full px-3.5 text-[12.5px] font-semibold ring-1 ring-inset', channels.includes(ch) ? 'brand-fill text-on-brand ring-transparent' : 'ring-white/10 text-fg-2')}>
                  {ch === 'whatsapp' ? <MessageCircle size={13} /> : <Instagram size={13} />}
                  {ch === 'whatsapp' ? 'WhatsApp broadcast' : 'Instagram post'}
                </button>
              ))}
            </div>
          )}
        </Field>
        <Field label="Image">
          {() => (
            <Segmented
              value={image}
              onChange={setImage}
              options={[
                { value: 'card', label: 'Designed card' },
                { value: 'ai', label: 'AI picture' },
                { value: 'none', label: 'None' },
              ]}
            />
          )}
        </Field>
        <Field label="Anything to add" optional>
          {(props) => <textarea {...props} className="field min-h-[80px]" value={instructions} onChange={(e) => setInstructions(e.target.value)} placeholder="Mention the Navratri timing; keep it in simple English with a few Gujarati words." />}
        </Field>
        <p className="flex items-center gap-1.5 text-[12px] text-fg-3">
          <CheckCircle2 size={13} /> New drafts are added next to what is there; remove the ones you do not want.
        </p>
      </div>
    </Sheet>
  )
}

