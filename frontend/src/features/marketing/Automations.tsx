import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, Bot, Pencil, Play, Plus, ScanSearch, Trash2, Workflow } from 'lucide-react'
import { marketing, type Channel, type Rule } from '@/api/marketing'
import { useAction } from '@/api/queries'
import { cn } from '@/lib/cn'
import { fmtAgo } from '@/lib/format'
import { Badge, Button, Empty, Field, Notice, Spinner, Toggle } from '@/ui/core'
import { Segmented, Sheet, useConfirm } from '@/ui/overlays'
import { Picker } from '@/ui/pickers'
import { CHANNEL, Page, Panel } from './shared'

const AGENTS = [
  { name: 'Strategist', what: 'Looks across stock, sales, batches, quiet customers and the festival calendar; lists opportunities with the numbers behind them.' },
  { name: 'Creative', what: 'Writes captions, hashtags and WhatsApp messages from product details and your brand kit; draws cards or AI pictures.' },
  { name: 'Executor', what: 'Publishes and sends approved campaigns on time, checks consent and limits for every message, retries safely, logs everything.' },
  { name: 'Engagement', what: 'Marks replies, records opt-outs, sorts Instagram comments and drafts replies; buyers are handed to TAI.' },
  { name: 'Analyst', what: 'Counts orders and enquiries after campaigns and writes a weekly review with what to do next.' },
]

export function Automations() {
  const data = useQuery({ queryKey: ['marketing', 'rules'], queryFn: marketing.rules })
  const [editing, setEditing] = useState<Rule | 'new' | null>(null)
  const save = useAction(marketing.saveRule)
  const run = useAction(marketing.runRule, { success: (r) => (r.done.length ? `${r.rule}: ${r.done.join('; ')}` : `${r.rule}: nothing new right now`) })
  const remove = useAction(marketing.removeRule, { success: 'Deleted' })
  const scan = useAction(marketing.scan, { success: (r) => `Found ${r.found} new opportunit${r.found === 1 ? 'y' : 'ies'}` })
  const confirm = useConfirm()
  if (data.isPending) return <Spinner />
  const rules = data.data?.items ?? []
  return (
    <Page className="space-y-3">
      <div className="grid gap-3 xl:grid-cols-[1fr_360px]">
        <Panel
          title="Automations"
          icon={Workflow}
          actions={
            <Button small kind="primary" icon={<Plus size={13} />} onClick={() => setEditing('new')}>
              New automation
            </Button>
          }
        >
          <p className="mb-3 text-[12.5px] text-fg-3">When something happens in the business, the agents prepare the campaign. Drafts wait for your approval unless you allow an automation to run on its own (and Settings allow it).</p>
          {rules.length ? (
            <div className="space-y-2">
              {rules.map((r) => (
                <div key={r.id} className={cn('rounded-[14px] border border-white/7 p-3.5', !r.is_active && 'opacity-60')}>
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-[14px] font-semibold">{r.name}</h3>
                    {r.action === 'auto_campaign' ? <Badge tone="warn">Runs on its own</Badge> : null}
                    <div className="ml-auto flex items-center gap-1">
                      <Toggle checked={r.is_active} onChange={(is_active) => save.mutate({ ...r, is_active })} label="On" />
                      <Button small kind="ghost" iconOnly aria-label="Run now" busy={run.isPending} onClick={() => run.mutate(r.id)}>
                        <Play size={13} />
                      </Button>
                      <Button small kind="ghost" iconOnly aria-label="Edit" onClick={() => setEditing(r)}>
                        <Pencil size={13} />
                      </Button>
                      <Button
                        small
                        kind="ghost"
                        iconOnly
                        aria-label="Delete"
                        onClick={async () => {
                          const answer = await confirm.ask({ title: `Delete ${r.name}?`, confirm: 'Delete', danger: true })
                          if (answer.ok) remove.mutate(r.id)
                        }}
                      >
                        <Trash2 size={13} />
                      </Button>
                    </div>
                  </div>
                  <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[12.5px] text-fg-2">
                    <span className="rounded-full bg-white/7 px-2 py-0.5">When: {r.trigger_label.toLowerCase()}</span>
                    {Object.entries(r.conditions).map(([k, v]) => (
                      <span key={k} className="text-fg-3">
                        {k.replaceAll('_', ' ')} {String(v)}
                      </span>
                    ))}
                    <ArrowRight size={13} className="text-fg-3" />
                    <span className="rounded-full bg-white/7 px-2 py-0.5">{r.action_label}</span>
                    {(r.action_config.channels ?? []).map((c) => (
                      <span key={c} className="text-fg-3">
                        {CHANNEL[c].label}
                      </span>
                    ))}
                  </div>
                  <p className="mt-1.5 text-[11.5px] text-fg-3">
                    {r.last_run_at ? `Last looked ${fmtAgo(r.last_run_at)}: ${r.last_result ?? ''}` : 'Not run yet.'} Same customer not repeated within {r.cooldown_days} days.
                  </p>
                </div>
              ))}
            </div>
          ) : (
            <Empty icon={<Workflow size={20} />} title="No automations" />
          )}
        </Panel>
        <aside className="space-y-3">
          <Panel
            title="The agents"
            icon={Bot}
            actions={
              <Button small icon={<ScanSearch size={13} />} busy={scan.isPending} onClick={() => scan.mutate()}>
                Look now
              </Button>
            }
          >
            <ul className="space-y-2.5">
              {AGENTS.map((a) => (
                <li key={a.name} className="text-[12.5px]">
                  <span className="font-semibold">{a.name}.</span> <span className="text-fg-2">{a.what}</span>
                </li>
              ))}
            </ul>
            <p className="mt-3 text-[11.5px] text-fg-3">Agents never publish or send by themselves: only the Executor does, and only for approved campaigns.</p>
          </Panel>
        </aside>
      </div>
      <RuleSheet editing={editing} onClose={() => setEditing(null)} />
      {confirm.element}
    </Page>
  )
}

function RuleSheet({ editing, onClose }: { editing: Rule | 'new' | null; onClose: () => void }) {
  const catalogue = useQuery({ queryKey: ['marketing', 'rules'], queryFn: marketing.rules })
  const audiences = useQuery({ queryKey: ['marketing', 'audiences'], queryFn: marketing.audiences, enabled: Boolean(editing) })
  const [form, setForm] = useState<Partial<Rule>>({})
  const save = useAction(marketing.saveRule, { success: 'Automation saved' })
  useEffect(() => {
    if (!editing) return
    setForm(editing === 'new' ? { name: '', trigger: 'inactive_customers', conditions: {}, action: 'draft_campaign', action_config: { channels: ['whatsapp'], image: 'card' }, cooldown_days: 30, is_active: true } : editing)
  }, [editing])
  const trigger = catalogue.data?.triggers.find((t) => t.key === form.trigger)
  const cfg = form.action_config ?? {}
  const set = (patch: Partial<Rule>) => setForm((f) => ({ ...f, ...patch }))
  const toggle = (ch: Channel) => set({ action_config: { ...cfg, channels: cfg.channels?.includes(ch) ? cfg.channels.filter((x) => x !== ch) : [...(cfg.channels ?? []), ch] } })
  return (
    <Sheet
      open={Boolean(editing)}
      onClose={onClose}
      title={editing === 'new' ? 'New automation' : 'Edit automation'}
      width={720}
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button kind="primary" busy={save.isPending} disabled={!form.name?.trim()} onClick={() => save.mutate({ ...form, id: editing && editing !== 'new' ? editing.id : undefined }, { onSuccess: onClose })}>
            Save
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <Field label="Name">{(props) => <input {...props} className="field" autoFocus value={form.name ?? ''} onChange={(e) => set({ name: e.target.value })} placeholder="Win back quiet contractors" />}</Field>
        <Field label="When">
          {(props) => <Picker id={props.id} value={form.trigger ?? ''} onChange={(t) => set({ trigger: t, conditions: {} })} options={(catalogue.data?.triggers ?? []).map((t) => ({ value: t.key, label: t.label }))} />}
        </Field>
        {trigger?.fields.length ? (
          <div className="grid gap-3 sm:grid-cols-2">
            {trigger.fields.map((f) => (
              <Field key={f.key} label={f.label}>
                {(props) =>
                  f.type === 'choice' ? (
                    <select {...props} className="field" value={String(form.conditions?.[f.key] ?? f.default)} onChange={(e) => set({ conditions: { ...form.conditions, [f.key]: e.target.value } })}>
                      {(f.choices ?? []).map((c) => (
                        <option key={c}>{c}</option>
                      ))}
                    </select>
                  ) : (
                    <input {...props} className="field field-num" inputMode="decimal" value={String(form.conditions?.[f.key] ?? f.default)} onChange={(e) => set({ conditions: { ...form.conditions, [f.key]: e.target.value } })} />
                  )
                }
              </Field>
            ))}
          </div>
        ) : null}
        <Field label="Then">
          {(props) => <Picker id={props.id} value={form.action ?? 'draft_campaign'} onChange={(a) => set({ action: a })} options={(catalogue.data?.actions ?? []).map((a) => ({ value: a.key, label: a.label }))} />}
        </Field>
        {form.action === 'auto_campaign' ? (
          <Notice tone="warn">
            Runs without waiting only when Settings → Marketing has automatic approval on and the audience is within its limit. Otherwise the campaign waits for approval. Consent, the weekly limit and quiet hours always apply.
          </Notice>
        ) : null}
        {form.action !== 'suggest' && form.action !== 'create_task' ? (
          <>
            <Field label="Channels">
              {() => (
                <div className="flex gap-2">
                  {(['whatsapp', 'instagram'] as Channel[]).map((ch) => (
                    <button key={ch} onClick={() => toggle(ch)} aria-pressed={cfg.channels?.includes(ch)} className={cn('h-9 rounded-full px-3.5 text-[12.5px] font-semibold ring-1 ring-inset', cfg.channels?.includes(ch) ? 'brand-fill text-on-brand ring-transparent' : 'text-fg-2 ring-white/10')}>
                      {CHANNEL[ch].label}
                    </button>
                  ))}
                </div>
              )}
            </Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Image">
                {() => (
                  <Segmented
                    value={cfg.image ?? 'card'}
                    onChange={(image) => set({ action_config: { ...cfg, image } })}
                    options={[
                      { value: 'card', label: 'Card' },
                      { value: 'ai', label: 'AI picture' },
                      { value: 'none', label: 'None' },
                    ]}
                  />
                )}
              </Field>
              <Field label="Only this audience" optional hint="Otherwise the people the trigger finds.">
                {(props) => (
                  <Picker
                    id={props.id}
                    value={cfg.audience_id ?? ''}
                    onChange={(v) => set({ action_config: { ...cfg, audience_id: v || null } })}
                    options={[{ value: '', label: 'Whoever the trigger finds' }, ...(audiences.data?.items ?? []).map((a) => ({ value: a.id, label: a.name, detail: a.summary }))]}
                  />
                )}
              </Field>
            </div>
            <Field label="Standing offer" optional hint="Used in every campaign this automation makes. The AI never invents offers.">
              {(props) => <input {...props} className="field" value={cfg.offer ?? ''} onChange={(e) => set({ action_config: { ...cfg, offer: e.target.value } })} placeholder="5% off your next order this month" />}
            </Field>
          </>
        ) : null}
        <Field label="Do not repeat for the same customer within (days)">
          {(props) => <input {...props} className="field field-num max-w-[140px]" inputMode="numeric" value={form.cooldown_days ?? 30} onChange={(e) => set({ cooldown_days: Number(e.target.value) || 0 })} />}
        </Field>
      </div>
    </Sheet>
  )
}
