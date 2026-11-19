import { Command } from 'cmdk'
import { motion } from 'motion/react'
import { Suspense, useEffect, useState, type ReactNode } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, KeyRound, LogOut, Plus, Search } from 'lucide-react'
import { api } from '@/api/endpoints'
import { useSummary } from '@/api/queries'
import { cn } from '@/lib/cn'
import { Avatar, Button, Tip } from '@/ui/core'
import { Menu } from '@/ui/overlays'
import { useAuth } from './auth'
import { Logo } from './Logo'
import { MODULES, moduleFor, type Module } from './nav'
import { PasswordSheet } from './PasswordSheet'

const CREATE = [
  { label: 'Sales order', to: '/orders?new=1', hint: 'O' },
  { label: 'Enquiry', to: '/enquiries?new=1', hint: 'E' },
  { label: 'Purchase order', to: '/purchase-orders?new=1', hint: 'P' },
  { label: 'Goods receipt', to: '/receipts?new=1', hint: 'R' },
  { label: 'Customer', to: '/customers?new=1' },
  { label: 'Supplier', to: '/suppliers?new=1' },
  { label: 'Product', to: '/products?new=1' },
]

/** The window: a frosted title bar, the module dock, and the workspace. */
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
    <div className="flex h-full flex-col bg-ink-950">
      <TitleBar onSearch={() => setPalette(true)} />
      <div className="flex min-h-0 flex-1 max-md:flex-col-reverse">
        <Dock />
        <main className="min-h-0 min-w-0 flex-1">
          <Suspense fallback={null}>
            <Outlet />
          </Suspense>
        </main>
      </div>
      <Palette open={palette} onClose={() => setPalette(false)} />
    </div>
  )
}

function TitleBar({ onSearch }: { onSearch: () => void }) {
  const location = useLocation()
  const navigate = useNavigate()
  const module = moduleFor(location.pathname)
  const isMac = typeof navigator !== 'undefined' && /Mac/.test(navigator.platform)
  return (
    <header className="relative z-20 flex h-[52px] shrink-0 items-center gap-4 border-b border-white/[0.06] bg-ink-900/80 px-4 backdrop-blur-xl max-md:gap-2 max-md:px-3">
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-px bg-gradient-to-r from-transparent via-sky/20 to-transparent" />
      <div className="flex w-[260px] items-center gap-3 max-lg:w-auto">
        <Logo size={26} />
        <div className="leading-tight">
          <div className="text-[13px] font-semibold tracking-[-0.01em]">AEC Desk</div>
          <div className="text-[11px] text-fg-3">{module.label}</div>
        </div>
      </div>
      <button
        onClick={onSearch}
        className="mx-auto flex h-8 w-full max-w-[460px] items-center gap-2.5 rounded-lg max-md:mr-0 max-md:w-8 max-md:justify-center max-md:px-0 bg-white/[0.045] px-3 text-[13px] text-fg-3 ring-1 ring-white/[0.07] transition hover:bg-white/[0.07] hover:text-fg-2"
      >
        <Search size={14} />
        <span className="flex-1 text-left max-md:hidden">Search orders, customers, products or jump to…</span>
        <kbd className="rounded bg-white/8 px-1.5 py-px font-sans text-[11px] text-fg-3 max-md:hidden">{isMac ? '⌘K' : 'Ctrl K'}</kbd>
      </button>
      <div className="flex w-[260px] items-center justify-end gap-2 max-lg:w-auto">
        <Menu
          trigger={
            <Button kind="primary" small icon={<Plus size={14} strokeWidth={2.4} />}>
              New <ChevronDown size={13} className="-mr-1 opacity-70" />
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
  const [changing, setChanging] = useState(false)
  if (!user) return null
  return (
    <>
      <Menu
        trigger={
          <button className="flex items-center gap-2 rounded-full py-0.5 pr-2.5 pl-0.5 text-[12.5px] text-fg-2 ring-1 ring-white/8 transition hover:bg-white/5 hover:text-fg" aria-label="Account">
            <Avatar name={user.username} size={26} />
            <span className="max-md:hidden">{user.username}</span>
          </button>
        }
        items={[
          { label: 'Change password', icon: <KeyRound size={14} />, onSelect: () => setChanging(true) },
          { label: 'Sign out', icon: <LogOut size={14} />, onSelect: () => void signOut(), separator: true },
        ]}
      />
      <PasswordSheet open={changing} onClose={() => setChanging(false)} />
    </>
  )
}

const GROUPS: Module['group'][] = ['main', 'sales', 'buying', 'stock']

function Dock() {
  const summary = useSummary()
  const open = summary.data?.open_orders ?? 0
  const short = Number(summary.data?.total_unallocated_quantity ?? 0) > 0
  return (
    <nav className="flex w-[76px] shrink-0 flex-col items-center gap-1 py-3 max-md:w-full max-md:flex-row max-md:gap-0 max-md:overflow-x-auto max-md:border-t max-md:border-white/7 max-md:bg-ink-900/90 max-md:px-1 max-md:py-1" aria-label="Modules">
      {GROUPS.map((group, index) => (
        <div key={group} className="flex w-full flex-col items-center gap-1 max-md:w-auto max-md:flex-row max-md:gap-0">
          {index > 0 ? <div className="my-1.5 h-px w-8 bg-white/8 max-md:hidden" /> : null}
          {MODULES.filter((module) => module.group === group).map((module) => (
            <DockItem key={module.to} module={module} badge={module.to === '/fulfilment' && open > 0 ? { count: open, alert: short } : undefined} />
          ))}
        </div>
      ))}
      <div className="mt-auto flex w-full flex-col items-center max-md:mt-0 max-md:w-auto">
        {MODULES.filter((module) => module.group === 'settings').map((module) => (
          <DockItem key={module.to} module={module} />
        ))}
      </div>
    </nav>
  )
}

function DockItem({ module, badge }: { module: Module; badge?: { count: number; alert: boolean } }) {
  const Icon = module.icon
  return (
    <Tip label={module.label} side="right">
      <NavLink to={module.to} end={module.to === '/'} className="group relative flex w-[64px] shrink-0 flex-col items-center gap-1 rounded-xl py-2 max-md:w-[62px] max-md:py-1.5">
        {({ isActive }) => (
          <>
            {isActive ? (
              <motion.span layoutId="dock" className="absolute inset-0 rounded-xl bg-sky/[0.1] ring-1 ring-sky/20 ring-inset" transition={{ type: 'spring', stiffness: 480, damping: 40 }} />
            ) : null}
            <span className={cn('relative transition-colors', isActive ? 'text-sky' : 'text-fg-3 group-hover:text-fg')}>
              <Icon size={19} strokeWidth={1.7} />
              {badge ? (
                <span className={cn('num absolute -top-1.5 -right-3 min-w-[17px] rounded-full px-1 text-center text-[10px] leading-[16px] font-semibold', badge.alert ? 'bg-blue text-white' : 'bg-white/15 text-fg')}>
                  {badge.count}
                </span>
              ) : null}
            </span>
            <span className={cn('relative text-[10.5px] font-medium transition-colors', isActive ? 'text-fg' : 'text-fg-3 group-hover:text-fg-2')}>{module.short}</span>
          </>
        )}
      </NavLink>
    </Tip>
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
    <Command.Item key={value} value={value} onSelect={onSelect} className="flex h-10 items-center gap-3 rounded-lg px-3 text-[13.5px] text-fg data-[selected=true]:bg-white/8">
      {children}
    </Command.Item>
  )
  const group = 'pt-2 [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:pt-2 [&_[cmdk-group-heading]]:pb-1.5 [&_[cmdk-group-heading]]:text-[10.5px] [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:tracking-[0.08em] [&_[cmdk-group-heading]]:text-fg-4 [&_[cmdk-group-heading]]:uppercase'

  return (
    <div className="fixed inset-0 z-[160] flex justify-center bg-black/50 pt-[13vh] backdrop-blur-[3px] animate-fade" onMouseDown={onClose}>
      <Command
        label="Command menu"
        shouldFilter={true}
        onMouseDown={(event) => event.stopPropagation()}
        onKeyDown={(event) => event.key === 'Escape' && onClose()}
        className="h-fit w-[640px] max-w-[calc(100vw-32px)] overflow-hidden rounded-2xl bg-ink-800 shadow-[0_40px_100px_-20px_rgb(0_0_0/0.9),0_0_0_1px_rgb(255_255_255/0.09)] animate-[pop_220ms_var(--ease-out-quint)_both]"
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

const ReceiptIcon = () => <span className="grid size-5 place-items-center rounded bg-sky/12 text-[10px] font-bold text-sky">#</span>
