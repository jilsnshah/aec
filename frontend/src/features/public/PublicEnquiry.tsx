import { useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, FileText, Package, ShoppingBag, ShoppingCart, Wallet } from 'lucide-react'
import { errorText, http } from '@/api/client'
import { cn } from '@/lib/cn'
import { fmtMoney } from '@/lib/format'
import { AccountTab } from './AccountTab'
import { InvoicesTab } from './InvoicesTab'
import { MyOrdersTab } from './MyOrdersTab'
import { OrderTab } from './OrderTab'
import type { PageData } from './types'

type Tab = 'order' | 'orders' | 'invoices' | 'account'

const TABS: { id: Tab; label: string; icon: ReactNode }[] = [
  { id: 'order', label: 'Order', icon: <ShoppingCart size={17} /> },
  { id: 'orders', label: 'My orders', icon: <Package size={17} /> },
  { id: 'invoices', label: 'Invoices', icon: <FileText size={17} /> },
  { id: 'account', label: 'Account', icon: <Wallet size={17} /> },
]

/** A customer's own page, opened from their link: order at their prices,
 *  follow orders and deliveries, download invoices, see their account.
 *  No sign-in; everything is scoped to the link's customer. */
export function PublicEnquiry({ token }: { token: string }) {
  const data = useQuery({ queryKey: ['public', token], queryFn: () => http.get<PageData>(`/api/public/e/${token}`), retry: false })
  const [tab, setTab] = useState<Tab>('order')

  if (data.isPending)
    return (
      <Shell>
        <p className="py-20 text-center text-fg-3">Loading…</p>
      </Shell>
    )
  if (data.error || !data.data)
    return (
      <Shell>
        <p className="py-20 text-center text-[15px]">{errorText(data.error) || 'This link is not valid.'}</p>
      </Shell>
    )

  const page = data.data
  const summary = page.customer_summary
  return (
    <Shell business={page.business}>
      <div className="mb-3">
        <h1 className="break-words text-[21px] font-semibold tracking-[-0.02em]">Hello, {page.customer}</h1>
        {summary ? (
          <div className="mt-2 grid grid-cols-2 gap-2">
            <button className="card min-w-0 p-3 text-left" onClick={() => setTab(() => 'account')}>
              <div className="text-[11.5px] text-fg-3">To pay</div>
              <div className="num truncate text-[16px] font-semibold">{fmtMoney(summary.amount_open)}</div>
              <div className="text-[11.5px] text-fg-3">
                {summary.open_orders} open order{summary.open_orders === 1 ? '' : 's'}
              </div>
            </button>
            <button
              className={cn('card min-w-0 p-3 text-left', summary.overdue > 0 && 'ring-1 ring-warn')}
              onClick={() => setTab(() => 'account')}
            >
              <div className={cn('flex items-center gap-1 text-[11.5px] text-fg-3', summary.overdue > 0 && 'text-warn')}>
                {summary.overdue > 0 ? <AlertTriangle size={12} /> : null} Overdue
              </div>
              <div className={cn('num truncate text-[16px] font-semibold', summary.overdue > 0 && 'text-warn')}>{fmtMoney(summary.overdue)}</div>
              <div className="text-[11.5px] text-fg-3">{summary.payment_terms_days ? `${summary.payment_terms_days}-day terms` : 'Pay on delivery'}</div>
            </button>
          </div>
        ) : null}
      </div>

      <nav className="sticky top-0 z-10 -mx-4 mb-4 bg-[var(--c-canvas)] px-4 py-2 backdrop-blur-xl" aria-label="Sections">
        <div className="grid grid-cols-4 gap-1 rounded-2xl bg-ink-800 p-1">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(() => t.id)}
              aria-current={tab === t.id ? 'page' : undefined}
              className={cn(
                'flex min-w-0 flex-col items-center gap-0.5 rounded-xl px-1 py-1.5 text-[11.5px] font-medium sm:flex-row sm:justify-center sm:gap-1.5 sm:text-[13px]',
                tab === t.id ? 'bg-contrast text-on-contrast shadow-sm' : 'text-fg-3',
              )}
            >
              {t.icon}
              <span className="truncate">{t.label}</span>
            </button>
          ))}
        </div>
      </nav>

      {tab === 'order' ? <OrderTab token={token} data={page} /> : null}
      {tab === 'orders' ? <MyOrdersTab token={token} /> : null}
      {tab === 'invoices' ? <InvoicesTab token={token} /> : null}
      {tab === 'account' ? <AccountTab token={token} /> : null}
    </Shell>
  )
}

function Shell({ business, children }: { business?: string; children: ReactNode }) {
  return (
    <div className="min-h-screen overflow-x-clip px-4 py-5 text-fg" style={{ background: 'var(--c-canvas)' }}>
      <div className="mx-auto max-w-3xl">
        <header className="mb-4 flex items-center gap-3">
          <span className="icon-tile size-10 shrink-0">
            <ShoppingBag size={18} />
          </span>
          <span className="min-w-0 truncate text-[17px] font-semibold">{business ?? ''}</span>
        </header>
        {children}
      </div>
    </div>
  )
}
