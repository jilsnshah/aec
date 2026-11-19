import { Command } from 'cmdk'
import { motion } from 'motion/react'
import { Suspense, useEffect, useState, type ReactNode } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, KeyRound, LogOut, Moon, Plus, Search, Sun } from 'lucide-react'
import { api } from '@/api/endpoints'
import { useSummary } from '@/api/queries'
import { cn } from '@/lib/cn'
import { Avatar, Button, Tip } from '@/ui/core'
import { Menu } from '@/ui/overlays'
import { Backdrop } from '@/ui/art'
import { AssistantDock } from '@/features/assistant/Assistant'
import { AssistantProvider, useAssistant } from '@/features/assistant/store'
import { AlertsBell } from '@/features/insights/AlertsBell'
import { useAuth } from './auth'
import { Wordmark } from './Logo'
import { GROUPS, MODULES, moduleFor, type Module } from './nav'
import { PasswordSheet } from './PasswordSheet'
import { useTheme } from './theme'

const CREATE = [
  { label: 'Sales order', to: '/orders?new=1', hint: 'O' },
  { label: 'Enquiry', to: '/enquiries?new=1', hint: 'E' },
  { label: 'Purchase order', to: '/purchase-orders?new=1', hint: 'P' },
  { label: 'Goods receipt', to: '/receipts?new=1', hint: 'R' },
  { label: 'Customer', to: '/customers?new=1' },
  { label: 'Supplier', to: '/suppliers?new=1' },
  { label: 'Product', to: '/products?new=1' },
]

/** The window: a top bar with the brand, pill navigation and tools, then the workspace. */
export function Shell() {
  const [palette, setPalette] = useState(false)
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setPalette((open) => !open)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <AssistantProvider>
      <div className="relative isolate flex h-full flex-col">
        <Backdrop />
        <TopBar onSearch={() => setPalette(true)} />
        <main className="min-h-0 min-w-0 flex-1">
          <Suspense fallback={null}>
            <Page />
          </Suspense>
        </main>
        <Palette open={palette} onClose={() => setPalette(false)} />
        <AssistantDock />
        <AssistantShortcut />
      </div>
    </AssistantProvider>
  )
}

/** Each module eases in when opened; moving between records inside a module
 *  does not replay it. */
function Page() {
  const { pathname } = useLocation()
  return (
    <motion.div key={moduleFor(pathname).to} className="h-full" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}>
      <Outlet />
    </motion.div>
  )
}

/** ⌘J / Ctrl J opens or closes the assistant from anywhere. */
function AssistantShortcut() {
  const { open, setOpen } = useAssistant()
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'j') {
        event.preventDefault()
        setOpen(!open)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, setOpen])
  return null
}

const round = 'pane grid size-10 shrink-0 place-items-center rounded-full! text-fg-2 transition hover:text-fg active:scale-95'

function TopBar({ onSearch }: { onSearch: () => void }) {
  const navigate = useNavigate()
  const { theme, toggle } = useTheme()
  const isMac = typeof navigator !== 'undefined' && /Mac/.test(navigator.platform)
  return (
    <header className="relative z-20 flex shrink-0 flex-wrap items-center gap-x-4 gap-y-3 px-6 pt-4 pb-4 max-md:px-3 max-md:pt-3 max-md:pb-2">
      <div className="w-[190px] shrink-0 max-2xl:w-auto max-2xl:pr-1 max-[1600px]:[&_span]:hidden max-[1279px]:[&_span]:inline">
        <Wordmark />
      </div>
      <Nav />
      <div className="ml-auto flex shrink-0 items-center gap-2 max-2xl:pl-2 max-md:gap-1.5 max-md:pl-0">
        <Tip label={<>Search <span className="opacity-60">{isMac ? '⌘K' : 'Ctrl K'}</span></>} side="bottom">
          <button onClick={onSearch} className={round} aria-label="Search">
            <Search size={17} />
          </button>
        </Tip>
        <AlertsBell className={round} />
        <Tip label={theme === 'dark' ? 'Light mode' : 'Dark mode'} side="bottom">
          <button onClick={toggle} className={cn(round, 'max-[1600px]:hidden max-[1279px]:grid')} aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}>
            <motion.span key={theme} initial={{ rotate: -60, opacity: 0 }} animate={{ rotate: 0, opacity: 1 }} transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}>
              {theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}
            </motion.span>
          </button>
        </Tip>
        <Menu
          trigger={
            <Button kind="primary" className="h-10 px-4" icon={<Plus size={15} strokeWidth={2.4} />}>
              <span className="max-md:hidden">New</span> <ChevronDown size={13} className="-mr-1 opacity-60 max-md:hidden" />
            </Button>
          }
          items={CREATE.map((item, index) => ({ label: item.label, onSelect: () => navigate(item.to), separator: index === 4 }))}
        />
        <AccountMenu />
      </div>
    </header>
  )
}

function AccountMenu() {
  const { user, signOut } = useAuth()
  const { theme, setTheme } = useTheme()
  const [changing, setChanging] = useState(false)
  if (!user) return null
  return (
    <>
      <Menu
        trigger={
          <button className="flex items-center gap-1.5 rounded-full p-0.5 pr-2 text-fg-3 transition hover:text-fg" aria-label="Account">
            <Avatar name={user.username} size={38} className="shadow-[0_6px_14px_-6px_rgb(0_0_0/0.45)]" />
            <ChevronDown size={14} />
          </button>
        }
        items={[
          { label: theme === 'dark' ? 'Light mode' : 'Dark mode', icon: theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />, onSelect: () => setTheme(theme === 'dark' ? 'light' : 'dark') },
          { label: 'Change password', icon: <KeyRound size={14} />, onSelect: () => setChanging(true) },
          { label: 'Sign out', icon: <LogOut size={14} />, onSelect: () => void signOut(), separator: true },
        ]}
      />
      <PasswordSheet open={changing} onClose={() => setChanging(false)} />
    </>
  )
}

/** The modules as pills. Sales, buying and stock pages sit in menus so the
 *  bar stays one row; the active pill glides to whatever is open. */
function Nav() {
  const summary = useSummary()
  const location = useLocation()
  const open = summary.data?.open_orders ?? 0
  const short = Number(summary.data?.total_unallocated_quantity ?? 0) > 0
  const current = moduleFor(location.pathname)
  const main = MODULES.filter((module) => module.group === 'main')
  const settings = MODULES.filter((module) => module.group === 'settings')
  return (
    <nav
      className="no-scrollbar mx-auto flex min-w-0 items-center gap-0.5 overflow-x-auto rounded-full bg-ink-850/70 p-1 shadow-pane backdrop-blur-xl max-[1279px]:order-last max-[1279px]:mx-0 max-[1279px]:w-full"
      aria-label="Modules"
    >
      {main.slice(0, 4).map((module) => (
        <NavItem key={module.to} module={module} badge={module.to === '/fulfilment' && open > 0 ? { count: open, alert: short } : undefined} />
      ))}
      {GROUPS.map((group) => (
        <GroupPill key={group.key} group={group} current={current} />
      ))}
      {[...main.slice(4), ...settings].map((module) => (
        <NavItem key={module.to} module={module} />
      ))}
    </nav>
  )
}

const pill = 'group relative flex h-9 shrink-0 items-center gap-1.5 rounded-full px-[11px] text-[12.5px] font-medium whitespace-nowrap min-[1600px]:px-3.5 min-[1600px]:text-[13px]'

function ActivePill() {
  return <motion.span layoutId="nav" className="brand-fill absolute inset-0 rounded-full" transition={{ type: 'spring', stiffness: 480, damping: 40 }} />
}

function NavItem({ module, badge }: { module: Module; badge?: { count: number; alert: boolean } }) {
  const Icon = module.icon
  return (
    <NavLink to={module.to} end={module.to === '/'} className={pill}>
      {({ isActive }) => (
        <>
          {isActive ? <ActivePill /> : null}
          <Icon size={15} strokeWidth={isActive ? 2.2 : 1.8} className={cn('relative shrink-0 transition-colors', isActive ? 'text-on-brand' : 'text-fg-3 group-hover:text-fg')} />
          <span className={cn('relative transition-colors', isActive ? 'text-on-brand' : 'text-fg-2 group-hover:text-fg')}>{module.short}</span>
          {badge ? (
            <span className={cn('num relative min-w-[18px] rounded-full px-1.5 text-center text-[10.5px] leading-[18px] font-semibold', isActive ? 'bg-on-brand text-solid' : badge.alert ? 'bg-blue text-[#0b0b0c]' : 'bg-white/10 text-fg-2')}>
              {badge.count}
            </span>
          ) : null}
        </>
      )}
    </NavLink>
  )
}

function GroupPill({ group, current }: { group: (typeof GROUPS)[number]; current: Module }) {
  const navigate = useNavigate()
  const members = MODULES.filter((module) => module.group === group.key)
  const active = current.group === group.key
  const Icon = active ? current.icon : group.icon
  return (
    <Menu
      align="start"
      trigger={
        <button className={pill} aria-label={`${group.label} menu`}>
          {active ? <ActivePill /> : null}
          <Icon size={15} strokeWidth={active ? 2.2 : 1.8} className={cn('relative shrink-0 transition-colors', active ? 'text-on-brand' : 'text-fg-3 group-hover:text-fg')} />
          <span className={cn('relative transition-colors', active ? 'text-on-brand' : 'text-fg-2 group-hover:text-fg')}>{active ? current.short : group.label}</span>
          <ChevronDown size={13} className={cn('relative -mr-0.5 transition-colors', active ? 'text-on-brand/70' : 'text-fg-4 group-hover:text-fg-3')} />
        </button>
      }
      items={members.map((module) => {
        const ModuleIcon = module.icon
        return { label: module.label, icon: <ModuleIcon size={14} />, hint: module.hint, onSelect: () => navigate(module.to) }
      })}
    />
  )
}

/* ---------------------------------------------------------------- command palette */
function Palette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const term = query.trim()
  const search = useQuery({
    queryKey: ['palette', term],
    enabled: open && term.length >= 2,
    queryFn: async () => {
      const [orders, customers, products, purchases] = await Promise.all([
        api.orders.list({ search: term, limit: 4 }),
        api.customers.list({ search: term, limit: 3 }),
        api.products.list({ search: term, limit: 4 }),
        api.purchaseOrders.list({ search: term, limit: 3 }),
      ])
      return { orders: orders.items, customers: customers.items, products: products.items, purchases: purchases.items }
    },
  })
  useEffect(() => {
    if (!open) setQuery('')
  }, [open])
  if (!open) return null

  const go = (to: string) => {
    onClose()
    navigate(to)
  }
  const item = (value: string, onSelect: () => void, children: ReactNode) => (
    <Command.Item key={value} value={value} onSelect={onSelect} className="flex h-10 items-center gap-3 rounded-lg px-3 text-[13.5px] text-fg data-[selected=true]:bg-peri/20">
      {children}
    </Command.Item>
  )
  const group = 'pt-2 [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:pt-2 [&_[cmdk-group-heading]]:pb-1.5 [&_[cmdk-group-heading]]:text-[10.5px] [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:tracking-[0.08em] [&_[cmdk-group-heading]]:text-fg-4 [&_[cmdk-group-heading]]:uppercase'

  return (
    <div className="fixed inset-0 z-[160] flex justify-center bg-[var(--scrim)] pt-[13vh] backdrop-blur-[3px] animate-fade" onMouseDown={onClose}>
      <Command
        label="Command menu"
        shouldFilter={true}
        onMouseDown={(event) => event.stopPropagation()}
        onKeyDown={(event) => event.key === 'Escape' && onClose()}
        className="h-fit w-[640px] max-w-[calc(100vw-32px)] overflow-hidden rounded-[24px] bg-ink-800 shadow-float animate-[pop_220ms_var(--ease-out-quint)_both]"
      >
        <div className="flex items-center gap-3 border-b border-white/8 px-4">
          <Search size={16} className="text-fg-3" />
          <Command.Input autoFocus value={query} onValueChange={setQuery} placeholder="Type a command, order number, customer or product…" className="h-14 flex-1 bg-transparent text-[15px] outline-none placeholder:text-fg-4" />
        </div>
        <Command.List className="max-h-[420px] overflow-y-auto p-2">
          <Command.Empty className="py-10 text-center text-[13px] text-fg-3">{search.isFetching ? 'Searching…' : 'Nothing matches.'}</Command.Empty>
          {search.data ? (
            <Command.Group heading="Records" className={group}>
              {search.data.orders.map((order) => item(`${order.order_number} ${order.customer.name} ${term}`, () => go(`/orders/${order.id}`), <><ReceiptIcon />{order.order_number}<span className="text-fg-3">· {order.customer.name}</span></>))}
              {search.data.purchases.map((po) => item(`${po.po_number} ${po.supplier.name} ${term}`, () => go(`/purchase-orders/${po.id}`), <><ReceiptIcon />{po.po_number}<span className="text-fg-3">· {po.supplier.name}</span></>))}
              {search.data.customers.map((customer) => item(`${customer.name} ${customer.phone ?? ''} ${term}`, () => go(`/customers/${customer.id}`), <><Avatar name={customer.name} size={20} />{customer.name}</>))}
              {search.data.products.map((product) => item(`${product.sku} ${product.name} ${term}`, () => go(`/products/${product.id}`), <><span className="num w-[86px] truncate text-[12px] text-fg-3">{product.sku}</span>{product.name}</>))}
            </Command.Group>
          ) : null}
          <Command.Group heading="Go to" className={group}>
            {MODULES.map((module) => {
              const Icon = module.icon
              return item(`${module.label} ${module.keywords ?? ''}`, () => go(module.to), <><Icon size={16} className="text-fg-3" />{module.label}</>)
            })}
          </Command.Group>
          <Command.Group heading="Create" className={group}>
            {CREATE.map((entry) => item(`new ${entry.label}`, () => go(entry.to), <><Plus size={16} className="text-fg-3" />New {entry.label.toLowerCase()}</>))}
          </Command.Group>
        </Command.List>
      </Command>
    </div>
  )
}

const ReceiptIcon = () => <span className="grid size-5 place-items-center rounded-full bg-peri/25 text-[10px] font-bold text-sky">#</span>
