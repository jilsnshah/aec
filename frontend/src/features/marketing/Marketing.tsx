import { lazy, Suspense } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  BarChart3,
  CalendarDays,
  LayoutDashboard,
  Megaphone,
  Radio,
  Settings2,
  Users,
  WandSparkles,
  Workflow,
  type LucideIcon,
} from 'lucide-react'
import { cn } from '@/lib/cn'
import { Spinner } from '@/ui/core'

const MarketingHome = lazy(() => import('./Home').then((m) => ({ default: m.MarketingHome })))
const Campaigns = lazy(() => import('./Campaigns').then((m) => ({ default: m.Campaigns })))
const Calendar = lazy(() => import('./Calendar').then((m) => ({ default: m.Calendar })))
const Studio = lazy(() => import('./Studio').then((m) => ({ default: m.Studio })))
const Audiences = lazy(() => import('./Audiences').then((m) => ({ default: m.Audiences })))
const Channels = lazy(() => import('./Channels').then((m) => ({ default: m.Channels })))
const Automations = lazy(() => import('./Automations').then((m) => ({ default: m.Automations })))
const Analytics = lazy(() => import('./Analytics').then((m) => ({ default: m.Analytics })))
const MarketingSettings = lazy(() => import('./Settings').then((m) => ({ default: m.MarketingSettings })))

export const VIEWS: { key: string; label: string; icon: LucideIcon; hint: string }[] = [
  { key: '', label: 'Home', icon: LayoutDashboard, hint: 'Opportunities, live campaigns and results' },
  { key: 'campaigns', label: 'Campaigns', icon: Megaphone, hint: 'Plan, approve, run and measure' },
  { key: 'calendar', label: 'Calendar', icon: CalendarDays, hint: 'Posts and broadcasts by date' },
  { key: 'studio', label: 'AI Studio', icon: WandSparkles, hint: 'Creatives, copy and images' },
  { key: 'audiences', label: 'Audiences', icon: Users, hint: 'Who to reach, and their consent' },
  { key: 'channels', label: 'Channels', icon: Radio, hint: 'Instagram and WhatsApp' },
  { key: 'automations', label: 'Automations', icon: Workflow, hint: 'When something happens, do something' },
  { key: 'analytics', label: 'Analytics', icon: BarChart3, hint: 'What worked and what it earned' },
  { key: 'settings', label: 'Settings', icon: Settings2, hint: 'Brand kit and sending rules' },
]

/** The marketing module: one page with a section bar. */
export function Marketing() {
  const { view = '' } = useParams()
  const navigate = useNavigate()
  const current = VIEWS.find((v) => v.key === view) ?? VIEWS[0]
  return (
    <div className="flex h-full min-h-0 flex-col gap-3 pt-1 max-md:gap-2">
      <header className="pane relative mx-6 flex shrink-0 items-center gap-3 overflow-hidden py-2 pr-2 pl-3 max-md:mx-2">
        <span className="icon-tile relative size-9 shrink-0" title={current.hint}>
          <Megaphone size={17} />
        </span>
        <h1 className="relative shrink-0 text-[16px] font-semibold tracking-[-0.01em] max-sm:hidden">Marketing</h1>
        <nav className="no-scrollbar relative flex min-w-0 flex-1 gap-0.5 overflow-x-auto sm:justify-end" aria-label="Marketing sections">
          {VIEWS.map((v) => {
            const active = v.key === current.key
            return (
              <button
                key={v.key}
                onClick={() => navigate(v.key ? `/marketing/${v.key}` : '/marketing')}
                aria-current={active ? 'page' : undefined}
                title={`${v.label}: ${v.hint}`}
                className={cn(
                  'flex h-8 shrink-0 items-center gap-1.5 rounded-full px-3 text-[12.5px] font-semibold transition-colors',
                  active ? 'brand-fill text-on-brand' : 'text-fg-3 hover:bg-white/7 hover:text-fg',
                )}
              >
                <v.icon size={14} />
                <span className={cn(!active && 'hidden lg:inline')}>{v.label}</span>
              </button>
            )
          })}
        </nav>
      </header>
      <div className="min-h-0 flex-1">
        <Suspense fallback={<Spinner />}>
          {current.key === '' ? <MarketingHome /> : null}
          {current.key === 'campaigns' ? <Campaigns /> : null}
          {current.key === 'calendar' ? <Calendar /> : null}
          {current.key === 'studio' ? <Studio /> : null}
          {current.key === 'audiences' ? <Audiences /> : null}
          {current.key === 'channels' ? <Channels /> : null}
          {current.key === 'automations' ? <Automations /> : null}
          {current.key === 'analytics' ? <Analytics /> : null}
          {current.key === 'settings' ? <MarketingSettings /> : null}
        </Suspense>
      </div>
    </div>
  )
}
