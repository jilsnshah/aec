import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Eye,
  IndianRupee,
  Lightbulb,
  Megaphone,
  MessageCircleReply,
  RefreshCw,
  ScanSearch,
  Send,
  Sparkles,
  Target,
  X,
} from 'lucide-react'
import { marketing, type Opportunity } from '@/api/marketing'
import { useAction } from '@/api/queries'
import { cn } from '@/lib/cn'
import { fmtAgo, fmtDateTime, fmtMoneyRound } from '@/lib/format'
import { Badge, Button, Empty, Spinner } from '@/ui/core'
import { CHANNEL, ChannelChips, DailyBars, Kpi, Page, Panel, StatusBadge, pct } from './shared'

const QUESTIONS = ['What should I promote this week?', 'Which customers are going quiet?', 'When should I send messages?', 'Which campaigns made money?']

export function MarketingHome() {
  const navigate = useNavigate()
  const data = useQuery({ queryKey: ['marketing', 'dashboard'], queryFn: marketing.dashboard, refetchInterval: 30000 })
  const scan = useAction(marketing.scan, { success: (r) => (r.found ? `Found ${r.found} new opportunit${r.found === 1 ? 'y' : 'ies'}` : 'Nothing new right now') })
  const analyse = useAction(marketing.analyse, { success: 'Review updated' })
  if (data.isPending) return <Spinner />
  if (!data.data) return <Empty title="Marketing could not load" body="Try again in a moment." />
  const d = data.data
  const k = d.kpis
  return (
    <Page>
      <div className="grid gap-3 xl:grid-cols-[1fr_360px]">
        <div className="min-w-0 space-y-3">
          <AskBar />
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 2xl:grid-cols-6">
            <Kpi icon={IndianRupee} label="Revenue from campaigns" value={fmtMoneyRound(k.revenue)} hint={`${k.orders} orders · ${k.enquiries} enquiries · 30 days`} />
            <Kpi icon={Target} label="Return on spend" value={k.roi === null ? '—' : `${k.roi.toFixed(1)}×`} hint={`${fmtMoneyRound(k.spend)} spent`} />
            <Kpi icon={Send} label="Messages sent" value={k.sent.toLocaleString('en-IN')} hint={`${pct(k.read, k.sent)} read`} />
            <Kpi icon={MessageCircleReply} label="Replies" value={k.replied.toLocaleString('en-IN')} hint={`${pct(k.replied, k.sent)} of sent`} />
            <Kpi icon={Eye} label="Instagram reach" value={k.reach.toLocaleString('en-IN')} hint={k.engagement_rate === null ? 'No posts measured yet' : `${(k.engagement_rate * 100).toFixed(1)}% engaged`} />
            <Kpi
              icon={Megaphone}
              label="Campaigns"
              value={k.active_campaigns}
              hint={k.waiting_approval ? `${k.waiting_approval} waiting for approval` : 'live or scheduled'}
              tone={k.waiting_approval ? 'warn' : undefined}
            />
          </div>

          <Panel
            title="Opportunities"
            icon={Lightbulb}
            actions={
              <Button small icon={<ScanSearch size={13} />} busy={scan.isPending} onClick={() => scan.mutate()}>
                Look again
              </Button>
            }
          >
            {d.opportunities.length ? (
              <div className="grid gap-2.5 lg:grid-cols-2">
                {d.opportunities.map((o) => (
                  <OpportunityCard key={o.id} o={o} onOpen={(id) => navigate(`/marketing/campaigns?id=${id}`)} />
                ))}
              </div>
            ) : (
              <Empty
                icon={<Lightbulb size={20} />}
                title="No open opportunities"
                body="The Strategist looks at stock, sales, batches, quiet customers and the festival calendar every day. Press Look again to check now."
              />
            )}
          </Panel>

          <Panel title="Campaigns in progress" icon={Megaphone} actions={<Button small kind="ghost" onClick={() => navigate('/marketing/campaigns')}>All campaigns</Button>}>
            {d.campaigns.length ? (
              <div className="divide-y divide-white/6">
                {d.campaigns.map((c) => (
                  <button key={c.id} onClick={() => navigate(`/marketing/campaigns?id=${c.id}`)} className="flex w-full items-center gap-3 py-2.5 text-left hover:bg-white/4">
                    <ChannelChips channels={c.channels} />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-[13.5px] font-semibold">{c.name}</div>
                      <div className="truncate text-[12px] text-fg-3">
                        {c.health.label}
                        {c.health.why ? ` · ${c.health.why}` : ''}
                      </div>
                    </div>
                    <span className="num hidden text-[12px] text-fg-3 sm:block">
                      {c.funnel.sent} sent · {c.conversions.orders} orders
                    </span>
                    <StatusBadge status={c.status} />
                  </button>
                ))}
              </div>
            ) : (
              <Empty icon={<Megaphone size={20} />} title="No campaigns running" body="Create one from an opportunity above, or start from scratch in Campaigns." />
            )}
          </Panel>

          <div className="grid gap-3 md:grid-cols-2">
            <div className="card p-4">
              <DailyBars points={d.series} measure="sent" label="Messages sent, by day" />
            </div>
            <div className="card p-4">
              <DailyBars points={d.series} measure="revenue" label="Revenue after campaigns, by day" money />
            </div>
          </div>
        </div>

        <aside className="min-w-0 space-y-3">
          <section className="pane-contrast relative overflow-hidden p-4">
            <div className="mb-2 flex items-center gap-2 text-[12px] font-semibold tracking-wide uppercase opacity-70">
              <Sparkles size={13} /> Weekly review
            </div>
            {d.insight ? (
              <>
                <p className="text-[15px] leading-snug font-semibold">{d.insight.headline}</p>
                <ul className="mt-2 space-y-1 text-[12.5px] opacity-85">
                  {d.insight.points.map((p) => (
                    <li key={p}>• {p}</li>
                  ))}
                </ul>
                {d.insight.recommendations.length ? (
                  <div className="mt-3 space-y-1.5">
                    {d.insight.recommendations.map((r) => (
                      <div key={r} className="flex gap-2 rounded-[10px] bg-white/10 px-2.5 py-2 text-[12.5px]">
                        <ArrowRight size={13} className="mt-0.5 shrink-0" /> {r}
                      </div>
                    ))}
                  </div>
                ) : null}
                <p className="mt-2 text-[11px] opacity-60">{fmtAgo(d.insight.at)}</p>
              </>
            ) : (
              <p className="text-[13px] opacity-80">The Analyst writes a short review every week: what worked, what did not, and what to do next.</p>
            )}
            <button onClick={() => analyse.mutate()} className="mt-3 inline-flex items-center gap-1.5 text-[12px] font-semibold opacity-80 hover:opacity-100">
              <RefreshCw size={12} className={cn(analyse.isPending && 'animate-spin')} /> Review now
            </button>
          </section>

          <Panel title="Channels" icon={Send}>
            <div className="space-y-2 text-[12.5px]">
              <Connection
                label="Instagram"
                ok={d.connections.instagram.connected && !d.connections.instagram.error}
                text={
                  d.connections.instagram.error
                    ? d.connections.instagram.error
                    : d.connections.instagram.connected
                      ? `@${d.connections.instagram.username || 'connected'} · ${d.connections.instagram.used}/${d.connections.instagram.quota || '—'} posts today`
                      : 'Not connected'
                }
                onClick={() => navigate('/marketing/channels')}
              />
              <Connection
                label="WhatsApp"
                ok={d.connections.whatsapp.connected && d.connections.whatsapp.approved_templates > 0}
                text={d.connections.whatsapp.connected ? `${d.connections.whatsapp.approved_templates} approved marketing template${d.connections.whatsapp.approved_templates === 1 ? '' : 's'}` : 'Not connected (Settings → WhatsApp)'}
                onClick={() => navigate('/marketing/channels?tab=whatsapp')}
              />
              <Connection
                label="Consent"
                ok={d.consent.opted_in > 0}
                text={`${d.consent.opted_in} of ${d.consent.customers} customers agreed to WhatsApp offers${d.consent.opted_out ? ` · ${d.consent.opted_out} opted out` : ''}`}
                onClick={() => navigate('/marketing/audiences?tab=consent')}
              />
              {d.comments_waiting ? (
                <Connection label="Comments" ok={false} text={`${d.comments_waiting} Instagram comment${d.comments_waiting === 1 ? '' : 's'} waiting for a reply`} onClick={() => navigate('/marketing/channels?tab=comments')} />
              ) : null}
            </div>
          </Panel>

          <Panel title="Coming up" icon={Send} actions={<Button small kind="ghost" onClick={() => navigate('/marketing/calendar')}>Calendar</Button>}>
            {d.upcoming.length ? (
              <div className="space-y-2">
                {d.upcoming.map((u) => {
                  const Icon = CHANNEL[u.channel].icon
                  return (
                    <button key={u.id} onClick={() => navigate(`/marketing/campaigns?id=${u.campaign_id}`)} className="flex w-full items-center gap-2.5 text-left">
                      {u.thumb ? <img src={u.thumb} alt="" className="size-9 rounded-[8px] object-cover" /> : <span className="grid size-9 place-items-center rounded-[8px] bg-white/7"><Icon size={14} /></span>}
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-[12.5px] font-semibold">{u.campaign}</div>
                        <div className="text-[11.5px] text-fg-3">{fmtDateTime(u.at)}</div>
                      </div>
                    </button>
                  )
                })}
              </div>
            ) : (
              <p className="text-[12.5px] text-fg-3">Nothing scheduled in the next two weeks.</p>
            )}
          </Panel>

          {d.problems.length ? (
            <Panel title="Needs attention" icon={AlertTriangle}>
              <div className="space-y-2">
                {d.problems.map((p) => (
                  <div key={p.id} className="text-[12.5px]">
                    <p className="font-medium">{p.message}</p>
                    <p className="text-[11.5px] text-fg-3">
                      {p.campaign ? `${p.campaign} · ` : ''}
                      {fmtAgo(p.at)}
                    </p>
                  </div>
                ))}
              </div>
            </Panel>
          ) : null}
        </aside>
      </div>
    </Page>
  )
}

function Connection({ label, ok, text, onClick }: { label: string; ok: boolean; text: string; onClick: () => void }) {
  return (
    <button onClick={onClick} className="flex w-full items-start gap-2 rounded-[10px] p-1.5 text-left hover:bg-white/5">
      {ok ? <CheckCircle2 size={15} className="mt-px shrink-0 text-ok" /> : <AlertTriangle size={15} className="mt-px shrink-0 text-warn" />}
      <span>
        <span className="font-semibold">{label}</span> <span className="text-fg-3">{text}</span>
      </span>
    </button>
  )
}

export function OpportunityCard({ o, onOpen }: { o: Opportunity; onOpen: (campaignId: string) => void }) {
  const accept = useAction(marketing.accept, { success: 'Draft campaign ready to review' })
  const dismiss = useAction(marketing.dismiss)
  return (
    <div className="flex flex-col gap-2 rounded-[14px] border border-white/7 bg-white/3 p-3.5">
      <div className="flex items-center gap-2">
        <Badge tone="sky">{o.kind_label}</Badge>
        <ChannelChips channels={o.channels} />
        {o.value_estimate ? <span className="num ml-auto text-[12px] font-semibold">{fmtMoneyRound(o.value_estimate)}</span> : null}
      </div>
      <h3 className="text-[14px] leading-snug font-semibold">{o.title}</h3>
      <p className="text-[12.5px] leading-relaxed text-fg-2">{o.why}</p>
      <p className="text-[11.5px] text-fg-3">
        <span className="font-semibold">Who:</span> {o.audience_summary}
      </p>
      <div className="mt-auto flex gap-2 pt-1">
        <Button small kind="primary" icon={<Sparkles size={13} />} busy={accept.isPending} onClick={() => accept.mutate({ id: o.id }, { onSuccess: (c) => onOpen(c.id) })}>
          Create campaign
        </Button>
        <Button small kind="ghost" icon={<X size={13} />} busy={dismiss.isPending} onClick={() => dismiss.mutate(o.id)}>
          Not now
        </Button>
      </div>
    </div>
  )
}

function AskBar() {
  const navigate = useNavigate()
  const [question, setQuestion] = useState('')
  const ask = useAction(marketing.ask, { quiet: false })
  const accept = useAction(marketing.accept, { success: 'Draft campaign ready to review' })
  const send = (q: string) => {
    setQuestion(q)
    ask.mutate(q)
  }
  return (
    <section className="card p-4">
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (question.trim()) send(question.trim())
        }}
      >
        <div className="relative flex-1">
          <Sparkles size={15} className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-fg-3" />
          <input className="field pl-9" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask the Strategist: what to promote, to whom, when…" aria-label="Ask a marketing question" />
        </div>
        <Button kind="primary" type="submit" busy={ask.isPending}>
          Ask
        </Button>
      </form>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {QUESTIONS.map((q) => (
          <button key={q} onClick={() => send(q)} className="rounded-full bg-white/6 px-2.5 py-1 text-[12px] font-medium text-fg-2 hover:bg-white/10">
            {q}
          </button>
        ))}
      </div>
      {ask.data ? (
        <div className="mt-3 rounded-[12px] bg-white/4 p-3">
          <p className="text-[13px] leading-relaxed whitespace-pre-wrap">{ask.data.answer}</p>
          {ask.data.actions.some((a) => a.opportunity_id) ? (
            <div className="mt-2 flex flex-wrap gap-2">
              {ask.data.actions
                .filter((a) => a.opportunity_id)
                .map((a) => (
                  <Button key={a.label} small icon={<Sparkles size={12} />} busy={accept.isPending} onClick={() => accept.mutate({ id: a.opportunity_id! }, { onSuccess: (c) => navigate(`/marketing/campaigns?id=${c.id}`) })}>
                    {a.label}
                  </Button>
                ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  )
}
