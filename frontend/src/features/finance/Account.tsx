import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowDownLeft, ArrowUpRight, Receipt } from 'lucide-react'
import { finance } from '@/api/finance'
import { cn } from '@/lib/cn'
import { fmtMoney } from '@/lib/format'
import { Badge, Button, Empty, Spinner } from '@/ui/core'
import { PaymentSheet } from './PaymentSheet'

/** A customer's or supplier's account: what was invoiced, what was paid, what
 *  is open and overdue, with a running balance. */
export function Account({ party, id }: { party: 'customer' | 'supplier'; id: string }) {
  const statement = useQuery({ queryKey: ['finance', 'statement', party, id], queryFn: () => finance.statement(party === 'customer' ? 'customers' : 'suppliers', id) })
  const [recording, setRecording] = useState(false)
  if (statement.isPending) return <Spinner />
  if (!statement.data) return <Empty title="The account could not be loaded" />
  const { summary, entries } = statement.data
  const customer = party === 'customer'
  return (
    <div className="space-y-4 p-5 pb-20">
      <div className="flex flex-wrap items-center gap-2">
        <div className="grid flex-1 grid-cols-4 gap-2 max-md:grid-cols-2">
          {(
            [
              [customer ? 'Invoiced' : 'Billed', summary.invoiced],
              ['Paid', summary.paid],
              ['Open', summary.open],
              ['Overdue', summary.overdue],
            ] as const
          ).map(([label, value]) => (
            <div key={label} className={cn('card px-3 py-2.5', label === 'Overdue' && value > 0 && 'ring-2 ring-solid/60')}>
              <div className="text-[11.5px] text-fg-3">{label}</div>
              <div className="num text-[17px] font-semibold">{fmtMoney(value)}</div>
            </div>
          ))}
        </div>
        <Button kind="primary" icon={customer ? <ArrowDownLeft size={14} /> : <ArrowUpRight size={14} />} onClick={() => setRecording(true)}>
          {customer ? 'Money received' : 'Money paid'}
        </Button>
      </div>
      <div className="flex flex-wrap gap-3 text-[12px] text-fg-3">
        <span>Terms: {summary.payment_terms_days ? `${summary.payment_terms_days} days` : 'due on delivery'}</span>
        {customer ? (
          <span>
            Credit limit: {summary.credit_limit == null ? 'none' : fmtMoney(summary.credit_limit)}
            {summary.over_credit_limit ? <span className="ml-1.5"><Badge tone="bad">Over limit</Badge></span> : null}
          </span>
        ) : null}
        {summary.advance > 0 ? <span>Advance held: {fmtMoney(summary.advance)}</span> : null}
        <span>Payments settle the oldest {customer ? 'invoices' : 'bills'} first.</span>
      </div>
      {entries.length === 0 ? (
        <Empty icon={<Receipt size={20} />} title="Nothing on the account yet" body={customer ? 'Invoices appear when goods are delivered.' : 'Bills appear when goods are received.'} />
      ) : (
        <div className="card overflow-x-auto">
          <table className="grid-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Document</th>
                <th>Order</th>
                <th>Due</th>
                <th className="r">{customer ? 'Invoiced' : 'Billed'}</th>
                <th className="r">Paid</th>
                <th className="r">Balance</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => (
                <tr key={entry.kind + entry.id}>
                  <td className="text-fg-2">{entry.date}</td>
                  <td>
                    <span className="font-medium">{entry.number}</span>
                    {entry.kind === 'payment' ? <span className="ml-1.5 text-[11.5px] text-fg-3 capitalize">{entry.method}{entry.reference ? ` · ${entry.reference}` : ''}</span> : null}
                    {entry.kind !== 'payment' && (entry.open ?? 0) > 0 ? (
                      <span className="ml-1.5">{(entry.days_overdue ?? 0) > 0 ? <Badge tone="bad">{entry.days_overdue} d late</Badge> : <Badge tone="sky">Open</Badge>}</span>
                    ) : null}
                  </td>
                  <td>
                    {entry.order_number ? (
                      <Link to={`${customer ? '/orders/' : '/purchase-orders/'}${entry.order_id}`} className="hover:underline">
                        {entry.order_number}
                      </Link>
                    ) : (
                      '—'
                    )}
                  </td>
                  <td className="text-fg-3">{entry.due_date ?? '—'}</td>
                  <td className="r num">{entry.debit ? fmtMoney(entry.debit) : ''}</td>
                  <td className="r num">{entry.credit ? fmtMoney(entry.credit) : ''}</td>
                  <td className="r num font-semibold">{fmtMoney(entry.balance)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <PaymentSheet open={recording} onClose={() => setRecording(false)} direction={customer ? 'in' : 'out'} partyId={id} suggested={summary.open} />
    </div>
  )
}
