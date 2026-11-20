import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, ArrowDownLeft, ArrowUpRight, CalendarClock, Wallet } from 'lucide-react'
import type { ReactNode } from 'react'
import { errorText, http } from '@/api/client'
import { cn } from '@/lib/cn'
import { fmtDate, fmtMoney } from '@/lib/format'
import type { PortalStatement } from './types'
import { Empty, Loading } from './ui'

const KIND: Record<PortalStatement['entries'][number]['kind'], string> = {
  invoice: 'Invoice',
  payment: 'Payment',
  credit_note: 'Credit note',
  debit_note: 'Debit note',
}

export function AccountTab({ token }: { token: string }) {
  const data = useQuery({
    queryKey: ['public', token, 'statement'],
    queryFn: () => http.get<PortalStatement>(`/api/public/e/${token}/statement`),
    retry: false,
  })
  if (data.isPending) return <Loading />
  if (data.error) return <Empty text={errorText(data.error)} />
  const { summary, entries } = data.data
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-2">
        <Stat icon={<Wallet size={16} />} label="Open" value={fmtMoney(summary.open)} />
        <Stat icon={<AlertTriangle size={16} />} label="Overdue" value={fmtMoney(summary.overdue)} warn={summary.overdue > 0} />
        <Stat icon={<CalendarClock size={16} />} label="Terms" value={summary.payment_terms_days ? `${summary.payment_terms_days} days` : 'On delivery'} />
      </div>
      <div className="flex flex-wrap justify-between gap-2 text-[12.5px] text-fg-3">
        <span>Invoiced {fmtMoney(summary.invoiced)}</span>
        <span>Paid {fmtMoney(summary.paid)}</span>
      </div>
      {entries.length ? (
        <div className="card divide-y divide-[var(--card-border)]">
          {[...entries].reverse().map((e, i) => {
            const isDebit = e.debit > 0
            return (
              <div key={`${e.kind}-${e.number}-${i}`} className="flex items-center gap-3 p-3">
                <span className={cn('grid size-8 shrink-0 place-items-center rounded-full', isDebit ? 'bg-ink-700' : 'bg-ok/15 text-ok')}>
                  {isDebit ? <ArrowUpRight size={15} /> : <ArrowDownLeft size={15} />}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="break-words text-[13.5px] font-medium">
                    {KIND[e.kind] ?? e.kind} {e.number}
                  </div>
                  <div className="text-[12px] text-fg-3">
                    {fmtDate(e.date)}
                    {isDebit && e.due_date ? ` · due ${fmtDate(e.due_date)}` : ''}
                    {e.days_overdue && e.days_overdue > 0 ? <span className="text-warn"> · {e.days_overdue} days late</span> : null}
                  </div>
                </div>
                <div className="shrink-0 text-right">
                  <div className={cn('num text-[13.5px] font-semibold', !isDebit && 'text-ok')}>
                    {isDebit ? fmtMoney(e.debit) : `− ${fmtMoney(e.credit)}`}
                  </div>
                  <div className="num text-[11.5px] text-fg-3">Bal {fmtMoney(e.balance)}</div>
                </div>
              </div>
            )
          })}
        </div>
      ) : (
        <Empty text="Nothing on your account yet." />
      )}
    </div>
  )
}

function Stat({ icon, label, value, warn }: { icon: ReactNode; label: string; value: string; warn?: boolean }) {
  return (
    <div className={cn('card min-w-0 p-3', warn && 'ring-1 ring-warn')}>
      <div className={cn('flex items-center gap-1.5 text-[11.5px] text-fg-3', warn && 'text-warn')}>
        {icon} {label}
      </div>
      <div className={cn('num mt-1 truncate text-[14px] font-semibold', warn && 'text-warn')}>{value}</div>
    </div>
  )
}
