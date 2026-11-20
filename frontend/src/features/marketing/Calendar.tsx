import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { marketing, CONTENT_LABEL, type CalendarItem } from '@/api/marketing'
import { cn } from '@/lib/cn'
import { Button, Spinner } from '@/ui/core'
import { CHANNEL, Page } from './shared'

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const key = (d: Date) => `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`

/** Every post and broadcast, by day: what is planned and what went out. */
export function Calendar() {
  const navigate = useNavigate()
  const [month, setMonth] = useState(() => {
    const d = new Date()
    return new Date(d.getFullYear(), d.getMonth(), 1)
  })
  const start = useMemo(() => {
    const d = new Date(month)
    d.setDate(1 - ((d.getDay() + 6) % 7))
    return d
  }, [month])
  const end = useMemo(() => new Date(start.getFullYear(), start.getMonth(), start.getDate() + 42), [start])
  const data = useQuery({ queryKey: ['marketing', 'calendar', start.toISOString()], queryFn: () => marketing.calendar(start.toISOString(), end.toISOString()) })
  const byDay = useMemo(() => {
    const map = new Map<string, CalendarItem[]>()
    for (const item of data.data?.items ?? []) {
      const k = key(new Date(item.at))
      map.set(k, [...(map.get(k) ?? []), item])
    }
    return map
  }, [data.data])
  const today = key(new Date())
  const days = Array.from({ length: 42 }, (_, i) => new Date(start.getFullYear(), start.getMonth(), start.getDate() + i))
  return (
    <Page>
      <section className="card p-4">
        <div className="mb-3 flex items-center gap-2">
          <h2 className="flex-1 text-[16px] font-semibold">{month.toLocaleDateString('en-IN', { month: 'long', year: 'numeric' })}</h2>
          <Button small iconOnly aria-label="Previous month" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))}>
            <ChevronLeft size={15} />
          </Button>
          <Button small onClick={() => setMonth(new Date(new Date().getFullYear(), new Date().getMonth(), 1))}>
            Today
          </Button>
          <Button small iconOnly aria-label="Next month" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))}>
            <ChevronRight size={15} />
          </Button>
        </div>
        {data.isPending ? (
          <Spinner />
        ) : (
          <div className="overflow-x-auto">
            <div className="grid min-w-[760px] grid-cols-7 gap-px overflow-hidden rounded-[12px] bg-white/7">
              {DAYS.map((d) => (
                <div key={d} className="bg-ink-800 px-2 py-1.5 text-[11.5px] font-semibold text-fg-3">
                  {d}
                </div>
              ))}
              {days.map((d) => {
                const items = byDay.get(key(d)) ?? []
                const inMonth = d.getMonth() === month.getMonth()
                return (
                  <div key={key(d)} className={cn('min-h-[104px] bg-ink-800 p-1.5', !inMonth && 'opacity-45')}>
                    <div className={cn('mb-1 grid size-6 place-items-center rounded-full text-[11.5px] font-semibold', key(d) === today ? 'brand-fill text-on-brand' : 'text-fg-3')}>{d.getDate()}</div>
                    <div className="space-y-1">
                      {items.slice(0, 3).map((item) => {
                        const Icon = CHANNEL[item.channel].icon
                        return (
                          <button
                            key={item.id}
                            onClick={() => navigate(`/marketing/campaigns?id=${item.campaign_id}`)}
                            title={`${item.campaign} · ${CONTENT_LABEL[item.status]} · ${new Date(item.at).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}`}
                            className={cn(
                              'flex w-full items-center gap-1 rounded-[6px] px-1.5 py-1 text-left text-[11px] font-medium',
                              item.status === 'failed' ? 'bg-bad/15' : item.status === 'published' || item.status === 'sent' ? 'bg-white/7' : 'bg-sky/12',
                            )}
                          >
                            <Icon size={10} className="shrink-0" />
                            <span className="truncate">{item.campaign}</span>
                          </button>
                        )
                      })}
                      {items.length > 3 ? <div className="px-1 text-[10.5px] text-fg-3">+{items.length - 3} more</div> : null}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )}
        <div className="mt-3 flex flex-wrap gap-4 text-[11.5px] text-fg-3">
          <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-sky/40" /> Planned</span>
          <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-white/20" /> Went out</span>
          <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-bad/40" /> Failed</span>
        </div>
      </section>
    </Page>
  )
}
