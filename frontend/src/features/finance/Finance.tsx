import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { motion } from 'motion/react'
import { ArrowDownLeft, ArrowUpRight, Ban, CalendarPlus, IndianRupee, Sparkles, Wallet } from 'lucide-react'
import { toast } from 'sonner'
import { errorText } from '@/api/client'
import { api } from '@/api/endpoints'
import { BUCKETS, finance, type Ageing, type Bucket } from '@/api/finance'
import { cn } from '@/lib/cn'
import { fmtMoney } from '@/lib/format'
import { HeaderArt } from '@/ui/art'
import { Badge, Button, Empty, SearchBox, Spinner } from '@/ui/core'
import { Segmented, TabPanel, Tabs, useConfirm } from '@/ui/overlays'
import { TableView } from '@/features/assistant/blocks'
import { useAssistant } from '@/features/assistant/store'
import { PaymentSheet } from './PaymentSheet'

/** Money owed to the business and by it, and every payment. */
export function Finance() {
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') ?? 'receivables'
  const [recording, setRecording] = useState<{ direction: 'in' | 'out'; party?: string; amount?: number } | null>(() => {
    const record = params.get('record')
    return record === 'in' || record === 'out' ? { direction: record } : null
  })
  const { ask } = useAssistant()
  const receivables = useQuery({ queryKey: ['finance', 'receivables'], queryFn: finance.receivables })
  const payables = useQuery({ queryKey: ['finance', 'payables'], queryFn: finance.payables })
  return (
    <div className="flex h-full min-h-0 flex-col gap-4 px-6 pt-1 pb-5 max-md:gap-2 max-md:p-2">
      <header className="pane relative flex shrink-0 flex-wrap items-center gap-4 overflow-hidden px-5 py-4">
        <HeaderArt seed={13} />
        <span className="icon-tile relative size-11">
          <Wallet size={20} />
        </span>
        <div className="relative min-w-0 flex-1">
          <h1 className="text-[20px] font-semibold tracking-[-0.02em]">Finance</h1>
          <p className="text-[12.5px] text-fg-3">Who owes you, whom you owe, and every payment — from deliveries, goods received and money recorded.</p>
        </div>
        <div className="relative flex flex-wrap gap-2">
          <Button icon={<Sparkles size={14} />} onClick={() => ask('Plan collections: who owes us money, how overdue, who is over their credit limit, and in what order should we call them? Propose follow-ups for the top ones.')}>
            Plan collections
          </Button>
          <Button icon={<ArrowUpRight size={15} />} onClick={() => setRecording({ direction: 'out' })}>
            Money paid
          </Button>
          <Button kind="primary" icon={<ArrowDownLeft size={15} />} onClick={() => setRecording({ direction: 'in' })}>
            Money received
          </Button>
        </div>
      </header>
      <div className="grid shrink-0 grid-cols-4 gap-3 max-lg:grid-cols-2">
        <Stat label="Customers owe you" value={receivables.data?.totals.open} hint={receivables.data ? `${fmtMoney(receivables.data.totals.overdue)} overdue` : undefined} strong />
        <Stat label="Overdue from customers" value={receivables.data?.totals.overdue} hint={receivables.data ? `${receivables.data.overdue.length} invoices past due` : undefined} />
        <Stat label="You owe suppliers" value={payables.data?.totals.open} hint={payables.data ? `${fmtMoney(payables.data.totals.overdue)} overdue` : undefined} />
        <Stat label="Net position" value={receivables.data && payables.data ? receivables.data.totals.open - payables.data.totals.open : undefined} hint="owed to you less owed by you" />
      </div>
      <section className="pane flex min-h-0 flex-1 flex-col overflow-hidden">
        <Tabs
          value={tab}
          onChange={(value) => setParams({ tab: value })}
          tabs={[
            { value: 'receivables', label: 'Receivables', count: receivables.data?.parties.filter((p) => p.open > 0).length },
            { value: 'payables', label: 'Payables', count: payables.data?.parties.filter((p) => p.open > 0).length },
            { value: 'payments', label: 'Payments' },
          ]}
          className="min-h-0 flex-1"
        >
          <TabPanel value="receivables" className="p-5 pb-24">
            {receivables.data ? <AgeingView data={receivables.data} kind="customer" onRecord={(party, amount) => setRecording({ direction: 'in', party, amount })} /> : <Spinner />}
          </TabPanel>
          <TabPanel value="payables" className="p-5 pb-24">
            {payables.data ? <AgeingView data={payables.data} kind="supplier" onRecord={(party, amount) => setRecording({ direction: 'out', party, amount })} /> : <Spinner />}
          </TabPanel>
          <TabPanel value="payments" className="p-5 pb-24">
            <PaymentsView />
          </TabPanel>
        </Tabs>
      </section>
      <PaymentSheet open={recording !== null} onClose={() => setRecording(null)} direction={recording?.direction} partyId={recording?.party} suggested={recording?.amount} />
    </div>
  )
}

function Stat({ label, value, hint, strong }: { label: string; value?: number; hint?: string; strong?: boolean }) {
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className={cn('rounded-[18px] p-4', strong ? 'pane-contrast' : 'pane')}>
      <div className={cn('text-[12px] font-medium', strong ? 'opacity-70' : 'text-fg-3')}>{label}</div>
      <div className="num mt-1 text-[26px] leading-none font-light tracking-[-0.035em]">{value === undefined ? '—' : fmtMoney(value)}</div>
      {hint ? <div className={cn('mt-2 text-[11.5px]', strong ? 'opacity-70' : 'text-fg-3')}>{hint}</div> : null}
    </motion.div>
  )
}

function AgeingView({ data, kind, onRecord }: { data: Ageing; kind: 'customer' | 'supplier'; onRecord: (party: string, amount: number) => void }) {
  const [bucket, setBucket] = useState<Bucket | null>(null)
  const client = useQueryClient()
  const total = Object.values(data.totals.buckets).reduce((a, b) => a + b, 0)
  const parties = useMemo(
    () => data.parties.filter((p) => (p.open > 0 || p.advance > 0) && (!bucket || p.buckets[bucket] > 0)).sort((a, b) => (bucket ? b.buckets[bucket] - a.buckets[bucket] : 0)),
    [data, bucket],
  )
  const route = kind === 'customer' ? '/customers/' : '/suppliers/'

  async function followUp(party: (typeof parties)[number]) {
    try {
      const tomorrow = new Date(Date.now() + 86_400_000).toISOString().slice(0, 10)
      await api.tasks.create({
        title: kind === 'customer' ? `Collect ${fmtMoney(party.overdue || party.open)} from ${party.name}` : `Pay ${party.name} ${fmtMoney(party.overdue || party.open)}`,
        due_date: tomorrow,
        priority: party.overdue > 0 ? 'HIGH' : 'NORMAL',
        customer_id: kind === 'customer' ? party.party_id : null,
        supplier_id: kind === 'supplier' ? party.party_id : null,
      })
      toast.success('Follow-up planned for tomorrow')
      client.invalidateQueries({ queryKey: ['tasks'] })
    } catch (error) {
      toast.error(errorText(error))
    }
  }

  if (!data.parties.length) return <Empty icon={<IndianRupee size={22} />} title={kind === 'customer' ? 'Nobody owes you anything' : 'You owe nothing'} body={kind === 'customer' ? 'Invoices appear when goods are delivered.' : 'Bills appear when goods are received.'} />
  return (
    <div className="space-y-4">
      <div className="card p-4">
        <div className="mb-2 flex items-baseline justify-between">
          <span className="text-[13px] font-semibold">By age past the due date</span>
          <span className="text-[11.5px] text-fg-3">{bucket ? 'Showing one age band — click it again to clear' : 'Click a band to see who is in it'}</span>
        </div>
        <div className="flex h-10 gap-1 overflow-hidden rounded-xl">
          {BUCKETS.map((b, i) => {
            const value = data.totals.buckets[b.key]
            if (!value) return null
            return (
              <button
                key={b.key}
                onClick={() => setBucket(bucket === b.key ? null : b.key)}
                style={{ width: `${(value / total) * 100}%`, background: ['var(--color-peri)', 'var(--color-blue-2)', 'var(--color-blue)', 'var(--color-fg-3)', 'var(--color-solid)'][i], opacity: bucket && bucket !== b.key ? 0.3 : 1 }}
                className="min-w-[6px] transition-opacity"
                title={`${b.label}: ${fmtMoney(value)}`}
              />
            )
          })}
        </div>
        <div className="mt-2 grid grid-cols-5 gap-2 text-[11.5px] max-md:grid-cols-2">
          {BUCKETS.map((b, i) => (
            <button key={b.key} onClick={() => setBucket(bucket === b.key ? null : b.key)} className={cn('rounded-lg px-2 py-1 text-left hover:bg-white/[0.04]', bucket === b.key && 'ring-2 ring-blue')}>
              <span className="flex items-center gap-1.5 text-fg-3">
                <span className="size-2 rounded-full" style={{ background: ['var(--color-peri)', 'var(--color-blue-2)', 'var(--color-blue)', 'var(--color-fg-3)', 'var(--color-solid)'][i] }} />
                {b.label}
              </span>
              <span className="num font-semibold">{fmtMoney(data.totals.buckets[b.key])}</span>
            </button>
          ))}
        </div>
      </div>
      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="grid-table">
            <thead>
              <tr>
                <th>{kind === 'customer' ? 'Customer' : 'Supplier'}</th>
                <th className="r">Open</th>
                <th className="r">Overdue</th>
                <th className="r">Oldest</th>
                <th className="r">Terms</th>
                {kind === 'customer' ? <th className="r">Credit limit</th> : null}
                <th />
              </tr>
            </thead>
            <tbody>
              {parties.map((party) => (
                <tr key={party.party_id}>
                  <td>
                    <Link to={`${route}${party.party_id}?tab=account`} className="font-medium underline decoration-blue/50 decoration-2 underline-offset-2">
                      {party.name}
                    </Link>
                    {party.advance > 0 ? <span className="ml-2 text-[11.5px] text-fg-3">advance {fmtMoney(party.advance)}</span> : null}
                  </td>
                  <td className="r num">{fmtMoney(party.open)}</td>
                  <td className={cn('r num', party.overdue > 0 && 'font-semibold')}>{party.overdue ? fmtMoney(party.overdue) : '—'}</td>
                  <td className="r num text-fg-2">{party.oldest_overdue_days ? `${party.oldest_overdue_days} d` : '—'}</td>
                  <td className="r num text-fg-3">{party.payment_terms_days} d</td>
                  {kind === 'customer' ? (
                    <td className="r">
                      {party.credit_limit == null ? <span className="text-fg-4">—</span> : party.over_credit_limit ? <Badge tone="bad">Over {fmtMoney(party.credit_limit)}</Badge> : <span className="num text-fg-2">{fmtMoney(party.credit_limit)}</span>}
                    </td>
                  ) : null}
                  <td className="r whitespace-nowrap">
                    <div className="flex justify-end gap-1">
                      <Button small kind="quiet" icon={<CalendarPlus size={13} />} onClick={() => void followUp(party)}>
                        Follow up
                      </Button>
                      <Button small icon={kind === 'customer' ? <ArrowDownLeft size={13} /> : <ArrowUpRight size={13} />} onClick={() => onRecord(party.party_id, party.open)}>
                        {kind === 'customer' ? 'Received' : 'Paid'}
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      {data.overdue.length ? (
        <TableView
          block={{
            type: 'table',
            id: 'overdue',
            title: kind === 'customer' ? 'Overdue invoices (deliveries)' : 'Overdue bills (goods received)',
            dataset_id: '',
            columns: [
              { key: 'number', label: kind === 'customer' ? 'Delivery' : 'Receipt', kind: 'text', link: null },
              { key: 'party_name', label: kind === 'customer' ? 'Customer' : 'Supplier', kind: 'text', link: { id: 'party_id', route } },
              { key: 'order_number', label: 'Order', kind: 'text', link: { id: 'order_id', route: kind === 'customer' ? '/orders/' : '/purchase-orders/' } },
              { key: 'due_date', label: 'Due', kind: 'date', link: null },
              { key: 'days_overdue', label: 'Days late', kind: 'number', link: null },
              { key: 'open', label: 'Open', kind: 'money', link: null },
            ],
            rows: data.overdue as unknown as Record<string, unknown>[],
            total_rows: data.overdue.length,
          }}
        />
      ) : null}
    </div>
  )
}

function PaymentsView() {
  const [direction, setDirection] = useState<'all' | 'in' | 'out'>('all')
  const [search, setSearch] = useState('')
  const confirm = useConfirm()
  const client = useQueryClient()
  const list = useQuery({
    queryKey: ['finance', 'payments', direction, search],
    queryFn: () => finance.payments({ direction: direction === 'all' ? undefined : direction, search: search || undefined, include_voided: true, limit: 200 }),
  })

  async function voidPayment(id: string, number: string) {
    const answer = await confirm.ask({ title: `Void ${number}?`, body: 'It stays on record, marked void, and no longer settles anything.', confirm: 'Void payment', danger: true, withReason: true })
    if (!answer.ok) return
    try {
      await finance.void(id, answer.reason || null)
      toast.success(`${number} voided`)
      client.invalidateQueries()
    } catch (error) {
      toast.error(errorText(error))
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Segmented
          value={direction}
          onChange={setDirection}
          options={[
            { value: 'all', label: 'All' },
            { value: 'in', label: 'Received' },
            { value: 'out', label: 'Paid' },
          ]}
        />
        <div className="w-[280px] max-md:w-full">
          <SearchBox value={search} onChange={setSearch} placeholder="Number, reference or party" />
        </div>
      </div>
      {list.isPending ? (
        <Spinner />
      ) : !list.data?.items.length ? (
        <Empty icon={<Wallet size={22} />} title="No payments yet" body="Record money received from customers and paid to suppliers to track who owes what." />
      ) : (
        <div className="card overflow-x-auto">
          <table className="grid-table">
            <thead>
              <tr>
                <th>Number</th>
                <th>Date</th>
                <th>Party</th>
                <th>Method</th>
                <th>Reference</th>
                <th className="r">Amount</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {list.data.items.map((p) => (
                <tr key={p.id} className={p.voided ? 'opacity-50' : undefined}>
                  <td className="font-medium">
                    {p.direction === 'in' ? <ArrowDownLeft size={13} className="mr-1 inline" /> : <ArrowUpRight size={13} className="mr-1 inline" />}
                    {p.number}
                    {p.voided ? <span className="ml-2"><Badge tone="muted">Void</Badge></span> : null}
                  </td>
                  <td className="text-fg-2">{p.paid_on}</td>
                  <td>
                    <Link to={p.customer_id ? `/customers/${p.customer_id}?tab=account` : `/suppliers/${p.supplier_id}?tab=account`} className="hover:underline">
                      {p.party_name}
                    </Link>
                  </td>
                  <td className="text-fg-2 capitalize">{p.method}</td>
                  <td className="max-w-[200px] truncate text-fg-3">{p.voided ? `Void: ${p.void_reason}` : p.reference ?? '—'}</td>
                  <td className="r num font-semibold">{fmtMoney(p.amount)}</td>
                  <td className="r">
                    {!p.voided ? (
                      <Button small kind="ghost" iconOnly aria-label={`Void ${p.number}`} onClick={() => void voidPayment(p.id, p.number)}>
                        <Ban size={13} />
                      </Button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {confirm.element}
    </div>
  )
}
