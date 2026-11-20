import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { BarChart3, Clock, Eye, IndianRupee, MessageCircleReply, Send, Target } from 'lucide-react'
import { marketing } from '@/api/marketing'
import { fmtMoneyRound } from '@/lib/format'
import { Empty, Spinner } from '@/ui/core'
import { Segmented } from '@/ui/overlays'
import { CHANNEL, ChannelChips, DailyBars, FunnelBars, Kpi, Page, Panel, StatusBadge, pct } from './shared'

export function Analytics() {
  const navigate = useNavigate()
  const [days, setDays] = useState('30')
  const data = useQuery({ queryKey: ['marketing', 'analytics', days], queryFn: () => marketing.analytics(Number(days)) })
  if (data.isPending) return <Spinner />
  const a = data.data
  if (!a) return <Empty title="Could not load analytics" />
  return (
    <Page className="space-y-3">
      <Segmented
        className="w-fit"
        value={days}
        onChange={setDays}
        options={[
          { value: '7', label: '7 days' },
          { value: '30', label: '30 days' },
          { value: '90', label: '90 days' },
          { value: '365', label: 'Year' },
        ]}
      />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Kpi icon={IndianRupee} label="Revenue after campaigns" value={fmtMoneyRound(a.revenue)} hint={`${a.orders} orders`} />
        <Kpi icon={Target} label="Return on spend" value={a.roi === null ? '—' : `${a.roi.toFixed(1)}×`} hint={`${fmtMoneyRound(a.spend)} spent`} />
        <Kpi icon={Send} label="Delivered" value={a.funnel.delivered.toLocaleString('en-IN')} hint={`${pct(a.funnel.delivered, a.funnel.sent)} of sent`} />
        <Kpi icon={Eye} label="Read" value={pct(a.funnel.read, a.funnel.delivered)} hint={`${a.funnel.read} people`} />
        <Kpi icon={MessageCircleReply} label="Replies and enquiries" value={a.funnel.replied + a.enquiries} hint={`${a.funnel.replied} replies · ${a.enquiries} enquiries`} />
        <Kpi icon={Eye} label="Instagram reach" value={Number(a.instagram.reach ?? 0).toLocaleString('en-IN')} hint={`${a.instagram.posts ?? 0} posts`} />
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        <Panel title="WhatsApp funnel" icon={Send}>
          <FunnelBars funnel={a.funnel} extra={[{ label: 'Orders', value: a.orders }]} />
          <p className="mt-2 text-[11.5px] text-fg-3">An order counts when it comes from someone who got a message within the attribution window. Each order counts once, for the latest message before it.</p>
        </Panel>
        <Panel title="Channels side by side" icon={BarChart3}>
          <table className="grid-table">
            <thead>
              <tr>
                <th>Channel</th>
                <th className="r">Reached</th>
                <th className="r">Engaged</th>
                <th className="r">Replies</th>
                <th className="r">Revenue</th>
              </tr>
            </thead>
            <tbody>
              {a.channels.map((c) => (
                <tr key={c.channel}>
                  <td className="font-medium">{CHANNEL[c.channel].label}</td>
                  <td className="r num">{c.reach.toLocaleString('en-IN')}</td>
                  <td className="r num">
                    {c.engaged.toLocaleString('en-IN')} <span className="text-[11px] text-fg-3">{pct(c.engaged, c.reach)}</span>
                  </td>
                  <td className="r num">{c.replies}</td>
                  <td className="r num">{c.revenue === null ? <span className="text-fg-3">not traceable</span> : fmtMoneyRound(c.revenue)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-[11.5px] text-fg-3">Instagram does not say who saw a post, so its sales cannot be traced to customers; its reach and engagement are shown instead.</p>
        </Panel>
        <div className="card p-4">
          <DailyBars points={a.series} measure="sent" label="Messages sent" />
        </div>
        <div className="card p-4">
          <DailyBars points={a.series} measure="revenue" label="Revenue after campaigns" money />
        </div>
      </div>
      <div className="grid gap-3 lg:grid-cols-[1fr_320px]">
        <Panel title="Campaigns" icon={BarChart3}>
          {a.campaigns.length ? (
            <div className="overflow-x-auto">
              <table className="grid-table min-w-[760px]">
                <thead>
                  <tr>
                    <th>Campaign</th>
                    <th className="r">Sent</th>
                    <th className="r">Read</th>
                    <th className="r">Replies</th>
                    <th className="r">Orders</th>
                    <th className="r">Revenue</th>
                    <th className="r">Cost</th>
                    <th className="r">Return</th>
                  </tr>
                </thead>
                <tbody>
                  {a.campaigns.map((c) => (
                    <tr key={c.id} className="cursor-pointer hover:bg-white/4" onClick={() => navigate(`/marketing/campaigns?id=${c.id}&show=all`)}>
                      <td>
                        <div className="flex items-center gap-2">
                          <ChannelChips channels={c.channels} />
                          <span className="font-medium">{c.name}</span>
                          <StatusBadge status={c.status} />
                        </div>
                      </td>
                      <td className="r num">{c.sent}</td>
                      <td className="r num">{c.read_rate === null ? '—' : `${Math.round(c.read_rate * 100)}%`}</td>
                      <td className="r num">{c.replied}</td>
                      <td className="r num">{c.orders}</td>
                      <td className="r num">{fmtMoneyRound(c.revenue)}</td>
                      <td className="r num">{fmtMoneyRound(c.cost)}</td>
                      <td className="r num">{c.roi === null ? '—' : `${c.roi.toFixed(1)}×`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty title="No campaigns in this period" />
          )}
        </Panel>
        <Panel title="Best time to message" icon={Clock}>
          {a.best_hours.length ? (
            <div className="space-y-2">
              {a.best_hours.map((h) => (
                <div key={h.hour} className="grid grid-cols-[64px_1fr_48px] items-center gap-2 text-[12.5px]">
                  <span className="num">{`${String(h.hour).padStart(2, '0')}:00`}</span>
                  <div className="h-2 overflow-hidden rounded-full bg-white/7">
                    <div className="h-full rounded-full bg-sky" style={{ width: `${h.read_rate * 100}%` }} />
                  </div>
                  <span className="num text-right">{Math.round(h.read_rate * 100)}%</span>
                </div>
              ))}
              <p className="text-[11.5px] text-fg-3">Share of messages read, by the hour they were sent (at least 5 messages per hour).</p>
            </div>
          ) : (
            <p className="text-[12.5px] text-fg-3">Shown once enough messages have gone out.</p>
          )}
        </Panel>
      </div>
    </Page>
  )
}
