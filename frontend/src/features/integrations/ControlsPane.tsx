import { useEffect, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { BadgePercent, Ban, CalendarClock, History, PauseCircle, ShieldCheck, TrendingDown, Wallet } from 'lucide-react'
import { api } from '@/api/endpoints'
import { useAction } from '@/api/queries'
import { controlsApi } from '@/api/records'
import type { IntegrationsOut } from '@/api/types'
import { cn } from '@/lib/cn'
import { fmtDateTime } from '@/lib/format'
import { Badge, Button, Empty, Spinner, Toggle } from '@/ui/core'

type Config = { credit_check: 'off' | 'warn' | 'block'; block_on_overdue: boolean; overdue_grace_days: number; max_discount_percent: number; min_margin_percent: number; block_below_cost: boolean; automation_paused: boolean }

/** Business rules checked whenever an order is placed (credit, discount,
 *  margin), and who may approve exceptions. */
export function ControlsPane({ data }: { data: IntegrationsOut }) {
  const saved = data.controls.config as unknown as Config
  const [config, setConfig] = useState<Config>(saved)
  useEffect(() => setConfig(saved), [data]) // eslint-disable-line react-hooks/exhaustive-deps
  const save = useAction(() => api.integrations.update('controls', { config: config as unknown as Record<string, unknown> }), { success: 'Controls saved' })
  const set = <K extends keyof Config>(key: K, value: Config[K]) => setConfig((current) => ({ ...current, [key]: value }))
  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <header className="border-b border-white/7 px-6 py-5">
        <div className="flex items-center gap-4">
          <span className="icon-disc size-11">
            <ShieldCheck size={18} />
          </span>
          <div className="flex-1">
            <h2 className="text-[18px] font-semibold tracking-[-0.02em]">Order controls</h2>
            <p className="text-[12.5px] text-fg-3">Checked every time an order is placed or an enquiry is won. A held order needs an admin's approval with a reason, which is kept in the audit log.</p>
          </div>
          <Button kind="primary" busy={save.isPending} onClick={() => save.mutate(undefined)}>
            Save
          </Button>
        </div>
      </header>
      <div className="max-w-[760px] space-y-4 p-6 pb-24">
        <Rule icon={<PauseCircle size={16} />} title="Automation paused" body="While on, nothing acts on its own: no purchase, sales or marketing automation, no agents, no AI messages or calls. Everything is recorded by hand. Tally sync keeps running.">
          <Toggle checked={Boolean(config.automation_paused)} onChange={(v) => set('automation_paused', v)} label="Automation paused" />
        </Rule>
        <Rule icon={<Wallet size={16} />} title="Credit limit" body="Owed now + orders not yet delivered + this order, against the customer's credit limit (set on the customer).">
          <div className="flex gap-1.5">
            {(['off', 'warn', 'block'] as const).map((mode) => (
              <button key={mode} onClick={() => set('credit_check', mode)} className={cn('h-[32px] rounded-full px-3.5 text-[12.5px] font-semibold', config.credit_check === mode ? 'brand-fill' : 'bg-ink-700 text-fg-2')}>
                {mode === 'block' ? 'Hold for approval' : mode === 'warn' ? 'Warn only' : 'Off'}
              </button>
            ))}
          </div>
        </Rule>
        <Rule icon={<CalendarClock size={16} />} title="Overdue invoices" body="Also hold orders for customers with invoices overdue longer than the grace period (applies when credit is set to hold).">
          <div className="flex items-center gap-3">
            <Toggle checked={config.block_on_overdue} onChange={(v) => set('block_on_overdue', v)} label="Hold on overdue" />
            <label className="flex items-center gap-2 text-[12.5px] text-fg-2">
              Grace
              <input className="field field-sm w-[70px] text-right" inputMode="numeric" value={config.overdue_grace_days} onChange={(e) => set('overdue_grace_days', Number(e.target.value) || 0)} />
              days
            </label>
          </div>
        </Rule>
        <Rule icon={<BadgePercent size={16} />} title="Maximum discount" body="A line discounted more than this needs approval. 0 means no limit.">
          <label className="flex items-center gap-2 text-[12.5px]">
            <input className="field field-sm w-[80px] text-right" inputMode="decimal" value={config.max_discount_percent} onChange={(e) => set('max_discount_percent', Number(e.target.value) || 0)} />%
          </label>
        </Rule>
        <Rule icon={<TrendingDown size={16} />} title="Minimum margin" body="A line earning less than this margin over its FIFO cost needs approval. 0 means no limit.">
          <label className="flex items-center gap-2 text-[12.5px]">
            <input className="field field-sm w-[80px] text-right" inputMode="decimal" value={config.min_margin_percent} onChange={(e) => set('min_margin_percent', Number(e.target.value) || 0)} />%
          </label>
        </Rule>
        <Rule icon={<Ban size={16} />} title="Selling below cost" body="Hold any line priced below what the stock cost. Leave off if you sometimes clear old stock at a loss on purpose.">
          <Toggle checked={config.block_below_cost} onChange={(v) => set('block_below_cost', v)} label="Hold below cost" />
        </Rule>
        <p className="text-[12px] text-fg-3">Like NetSuite's credit holds, Zoho Books' restrict mode and ERPNext's credit controller: warnings appear while the order is typed; holds stop it until approved.</p>
      </div>
    </div>
  )
}

function Rule({ icon, title, body, children }: { icon: ReactNode; title: string; body: string; children: ReactNode }) {
  return (
    <div className="card flex items-center gap-4 p-4 max-md:flex-col max-md:items-start">
      <span className="grid size-9 shrink-0 place-items-center rounded-full bg-peri/30">{icon}</span>
      <div className="min-w-0 flex-1">
        <div className="text-[13.5px] font-semibold">{title}</div>
        <p className="text-[12px] text-fg-3">{body}</p>
      </div>
      {children}
    </div>
  )
}

const ACTION_LABEL: Record<string, string> = {
  control_override: 'Approved on hold',
  stock_count: 'Stock count',
  stock_adjustment: 'Stock adjusted',
  sales_return: 'Return',
  payment_void: 'Payment voided',
}

/** Who did what: approvals, stock corrections, returns, voids. */
export function AuditPane() {
  const data = useQuery({ queryKey: ['audit'], queryFn: () => controlsApi.audit({ limit: 300 }) })
  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <header className="border-b border-white/7 px-6 py-5">
        <div className="flex items-center gap-4">
          <span className="icon-disc size-11">
            <History size={18} />
          </span>
          <div>
            <h2 className="text-[18px] font-semibold tracking-[-0.02em]">Audit log</h2>
            <p className="text-[12.5px] text-fg-3">Every approval of a held order, stock count and adjustment, return and voided payment — who, when and why. Nothing here can be edited.</p>
          </div>
        </div>
      </header>
      {data.isPending ? (
        <Spinner />
      ) : !data.data?.events.length ? (
        <Empty icon={<History size={20} />} title="Nothing recorded yet" />
      ) : (
        <table className="grid-table">
          <thead>
            <tr>
              <th>When</th>
              <th>Who</th>
              <th>What</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody>
            {data.data.events.map((event) => (
              <tr key={event.id}>
                <td className="text-[12.5px] whitespace-nowrap">{fmtDateTime(event.at)}</td>
                <td className="text-[12.5px]">{event.user ?? 'system'}</td>
                <td>
                  <Badge tone={event.action === 'control_override' ? 'bad' : 'muted'}>{ACTION_LABEL[event.action] ?? event.action}</Badge>
                </td>
                <td className="text-[12.5px] text-fg-2">{event.summary}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
