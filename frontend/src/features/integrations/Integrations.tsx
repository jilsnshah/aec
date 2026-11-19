import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { AuditPane, ControlsPane } from './ControlsPane'
import { CompanyPane } from './CompanyPane'
import { ApprovalsPane, AutomationPane } from '@/features/automation/Automation'
import { Building2, Check, CheckCheck, Copy, FileText, History, Inbox, Mail, Workflow, MessageCircle, RefreshCw, ShieldCheck, Sparkles, Wand2 } from 'lucide-react'
import { toast } from 'sonner'
import { errorText } from '@/api/client'
import { api } from '@/api/endpoints'
import { useAction, useList } from '@/api/queries'
import type { IntegrationOut, IntegrationsOut } from '@/api/types'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ai as aiApi } from '@/api/ai'
import { cn } from '@/lib/cn'
import { fmtAgo, fmtDateTime } from '@/lib/format'
import { Badge, Button, Empty, Field, Notice, Spinner, Toggle } from '@/ui/core'
import { Segmented } from '@/ui/overlays'
import { HeaderArt } from '@/ui/art'

type FieldDef =
  | { key: string; label: string; kind?: 'text' | 'number' | 'secret'; hint?: string; placeholder?: string; wide?: boolean }
  | { key: string; label: string; kind: 'check'; hint?: string }
  | { key: string; label: string; kind: 'select'; options: { value: string; label: string }[]; hint?: string }
type Group = { title?: string; hint?: string; fields: FieldDef[] }

const WEBHOOK = () => `${window.location.origin}/api/integrations/whatsapp/webhook`

const FORMS: Record<'whatsapp' | 'email' | 'tally', Group[]> = {
  whatsapp: [
    {
      title: 'Receive messages',
      hint: "Meta's Cloud API sends each customer message here; AI reads it and opens an enquiry.",
      fields: [
        { key: 'phone_number_id', label: 'Phone number ID', hint: 'Meta for Developers › your app › WhatsApp › API Setup.' },
        { key: 'business_account_id', label: 'WhatsApp Business Account ID' },
        { key: 'verify_token', label: 'Verify token', hint: 'Any secret phrase. Paste the same one into Meta.' },
        { key: 'app_secret', label: 'App secret', kind: 'secret', hint: 'When set, only requests signed by Meta are accepted.' },
      ],
    },
    {
      title: 'Send invoices',
      hint: "Invoices from Tally go to the customer's WhatsApp as soon as Tally creates them.",
      fields: [
        { key: 'send_invoices', label: 'Send each invoice to the customer on WhatsApp', kind: 'check' },
        { key: 'access_token', label: 'Access token', kind: 'secret', hint: 'A permanent system-user token with whatsapp_business_messaging.' },
        { key: 'invoice_template', label: 'Invoice template name', placeholder: 'invoice_pdf', hint: 'A utility template with a document header.' },
        { key: 'send_order_confirmations', label: 'Send an order confirmation when an order is placed', kind: 'check' },
        { key: 'order_template', label: 'Order confirmation template name', placeholder: 'order_confirmed', hint: 'A utility text template; body variables: {{1}} customer, {{2}} order number, {{3}} total, {{4}} items.' },
        { key: 'template_language', label: 'Template language', placeholder: 'en' },
        { key: 'country_code', label: 'Default country code', placeholder: '91' },
        { key: 'graph_version', label: 'Graph API version', placeholder: 'v23.0' },
      ],
    },
  ],
  email: [
    {
      title: 'Mailbox',
      hint: 'Unread mail is read over IMAP and the enquiries in it are captured.',
      fields: [
        { key: 'imap_host', label: 'IMAP server', placeholder: 'imap.gmail.com' },
        { key: 'imap_port', label: 'Port', kind: 'number', hint: '993 for IMAP over SSL.' },
        { key: 'username', label: 'Email address', placeholder: 'sales@yourbusiness.com' },
        { key: 'password', label: 'Password', kind: 'secret', hint: 'For Gmail and Outlook, use an app password.' },
        { key: 'folder', label: 'Folder', placeholder: 'INBOX' },
        { key: 'poll_minutes', label: 'Check every (minutes)', kind: 'number' },
      ],
    },
    {
      title: 'Replies',
      hint: 'When TAI may answer by email (Settings › Automation), replies go out through this server with the same address and password.',
      fields: [
        { key: 'smtp_host', label: 'SMTP server', placeholder: 'smtp.gmail.com' },
        { key: 'smtp_port', label: 'Port', kind: 'number', hint: '465 for SSL, 587 for STARTTLS.' },
      ],
    },
  ],
  tally: [
    {
      title: 'Connection',
      hint: "TallyPrime's HTTP server: F1 › Settings › Connectivity › TallyPrime acts as Server (port 9000).",
      fields: [
        { key: 'server_url', label: 'Tally server address', placeholder: 'http://192.168.1.20:9000', wide: true },
        { key: 'company', label: 'Company name', hint: 'Exactly as it appears in Tally.' },
        { key: 'auth_token', label: 'Access token', kind: 'secret', hint: 'Only if a gateway in front of Tally asks for one.' },
      ],
    },
    {
      title: 'What to sync',
      fields: [
        { key: 'sync_sales_orders', label: 'Sales orders become Sales Order vouchers', kind: 'check' },
        { key: 'create_invoices', label: 'Create invoices in Tally (their numbers are used on the PDF)', kind: 'check' },
        { key: 'invoice_on', label: 'When to invoice', kind: 'select', options: [{ value: 'order', label: 'When the order is placed (whole order)' }, { value: 'delivery', label: 'On each delivery (what that truck carried)' }], hint: 'Invoicing on delivery bills partial deliveries correctly.' },
        { key: 'sync_purchase_orders', label: 'Placed purchase orders become Purchase Order vouchers', kind: 'check' },
      ],
    },
    {
      title: 'Ledgers and voucher types',
      hint: 'Must match the names in your Tally company. Parties and stock items are created if missing.',
      fields: [
        { key: 'sales_ledger', label: 'Sales ledger' },
        { key: 'purchase_ledger', label: 'Purchase ledger' },
        { key: 'customer_group', label: 'Customer group' },
        { key: 'supplier_group', label: 'Supplier group' },
        { key: 'godown', label: 'Godown' },
        { key: 'sales_order_type', label: 'Sales order voucher type' },
        { key: 'sales_invoice_type', label: 'Sales invoice voucher type' },
        { key: 'purchase_order_type', label: 'Purchase order voucher type' },
      ],
    },
    {
      title: 'GST',
      fields: [
        { key: 'tax_mode', label: 'Tax on invoices', kind: 'select', options: [{ value: 'none', label: 'No tax' }, { value: 'cgst_sgst', label: 'CGST + SGST (within state)' }, { value: 'igst', label: 'IGST (other state)' }] },
        { key: 'gst_rate', label: 'GST rate (%)', kind: 'number' },
        { key: 'cgst_ledger', label: 'CGST ledger' },
        { key: 'sgst_ledger', label: 'SGST ledger' },
        { key: 'igst_ledger', label: 'IGST ledger' },
      ],
    },
    {
      title: 'Seller details on the invoice PDF',
      fields: [
        { key: 'seller_name', label: 'Business name' },
        { key: 'seller_gstin', label: 'GSTIN' },
        { key: 'seller_phone', label: 'Phone' },
        { key: 'seller_address', label: 'Address', wide: true },
      ],
    },
  ],
}

type SectionKey = 'automation' | 'approvals' | 'company' | 'ai' | 'whatsapp' | 'email' | 'tally' | 'controls' | 'audit' | 'messages' | 'syncs' | 'assistant_log'
const SECTIONS: { key: SectionKey; label: string; hint: string; icon: ReactNode; group: string }[] = [
  { key: 'ai', label: 'AI · Gemini', hint: 'Assistant and message reading', icon: <Sparkles size={16} />, group: 'Connections' },
  { key: 'whatsapp', label: 'WhatsApp', hint: 'Messages in, invoices out', icon: <MessageCircle size={16} />, group: 'Connections' },
  { key: 'email', label: 'Email', hint: 'Read a sales mailbox', icon: <Mail size={16} />, group: 'Connections' },
  { key: 'tally', label: 'Tally', hint: 'Vouchers and invoices', icon: <FileText size={16} />, group: 'Connections' },
  { key: 'automation', label: 'Automation', hint: 'Sales and purchase pipelines', icon: <Workflow size={16} />, group: 'Business rules' },
  { key: 'approvals', label: 'Approvals', hint: 'What the AI is waiting to send', icon: <CheckCheck size={16} />, group: 'Business rules' },
  { key: 'company', label: 'Company knowledge', hint: 'What the AI knows about you', icon: <Building2 size={16} />, group: 'Business rules' },
  { key: 'controls', label: 'Order controls', hint: 'Credit, discount and margin holds', icon: <ShieldCheck size={16} />, group: 'Business rules' },
  { key: 'audit', label: 'Audit log', hint: 'Approvals, adjustments, returns', icon: <History size={16} />, group: 'Activity' },
  { key: 'messages', label: 'Received messages', hint: 'What came in, what AI did', icon: <Inbox size={16} />, group: 'Activity' },
  { key: 'syncs', label: 'Tally sync log', hint: 'What went to Tally', icon: <RefreshCw size={16} />, group: 'Activity' },
  { key: 'assistant_log', label: 'Assistant activity', hint: 'Every tool the assistant ran', icon: <History size={16} />, group: 'Activity' },
]

export function Integrations() {
  const { section } = useParams()
  const navigate = useNavigate()
  const current = (SECTIONS.find((item) => item.key === section)?.key ?? 'ai') as SectionKey
  const data = useQuery({ queryKey: ['integrations'], queryFn: api.integrations.get })
  const wide = current === 'automation'
  const on: Partial<Record<SectionKey, boolean>> = data.data ? { ai: data.data.ai.enabled, whatsapp: data.data.whatsapp.enabled, email: data.data.email.enabled, tally: data.data.tally.enabled } : {}

  return (
    <div className="flex h-full min-h-0 gap-4 px-6 pt-1 pb-5 max-lg:flex-col max-md:gap-2 max-md:p-2">
      <nav className={cn('pane flex shrink-0 flex-col gap-5 overflow-y-auto p-3 max-lg:max-h-[220px] max-lg:w-full', wide ? 'w-[68px] [&_.nav-text]:hidden' : 'w-[290px]')}>
        <div className="nav-text px-2 pt-1">
          <h1 className="text-[16px] font-semibold tracking-[-0.015em]">Integrations</h1>
          <p className="text-[12px] text-fg-3">Turn WhatsApp and email into enquiries; keep Tally in step.</p>
        </div>
        {['Connections', 'Business rules', 'Activity'].map((group) => (
          <div key={group}>
            <div className={cn('eyebrow px-2 pb-2', wide && 'invisible h-2 overflow-hidden p-0')}>{group}</div>
            {SECTIONS.filter((item) => item.group === group).map((item) => (
              <button
                key={item.key}
                onClick={() => navigate(`/integrations/${item.key}`)}
                title={wide ? item.label : undefined}
                className={cn('relative flex w-full items-center gap-3 rounded-xl px-2.5 py-2.5 text-left transition-colors', current === item.key ? 'bg-peri/[0.18]' : 'hover:bg-white/[0.035]')}
              >
                <span className={cn('grid size-8 place-items-center rounded-full bg-peri/20', current === item.key ? 'text-sky' : 'text-fg-2')}>{item.icon}</span>
                <span className="nav-text min-w-0 flex-1">
                  <span className="block text-[13px] font-medium">{item.label}</span>
                  <span className="block truncate text-[11.5px] text-fg-3">{item.hint}</span>
                </span>
                {item.key in on && !wide ? <span className={cn('size-2 rounded-full', on[item.key] ? 'bg-sky' : 'bg-white/15')} title={on[item.key] ? 'On' : 'Off'} /> : null}
              </button>
            ))}
          </div>
        ))}
      </nav>
      <section className="pane flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden" key={current}>
        {data.isPending ? (
          <Spinner />
        ) : !data.data ? (
          <Empty title="Settings could not be loaded" />
        ) : current === 'ai' ? (
          <AiPane data={data.data} />
        ) : current === 'automation' ? (
          <AutomationPane />
        ) : current === 'approvals' ? (
          <ApprovalsPane />
        ) : current === 'company' ? (
          <CompanyPane data={data.data} />
        ) : current === 'controls' ? (
          <ControlsPane data={data.data} />
        ) : current === 'audit' ? (
          <AuditPane />
        ) : current === 'messages' ? (
          <MessagesPane />
        ) : current === 'syncs' ? (
          <SyncsPane />
        ) : current === 'assistant_log' ? (
          <ActivityPane />
        ) : (
          <ConnectionPane data={data.data} name={current} />
        )}
      </section>
    </div>
  )
}

function PaneHeader({ icon, title, body, integration, onToggle, busy, extra }: { icon: ReactNode; title: string; body: string; integration?: IntegrationOut; onToggle?: (value: boolean) => void; busy?: boolean; extra?: ReactNode }) {
  return (
    <header className="relative shrink-0 overflow-hidden border-b border-white/7 px-6 py-5">
      <HeaderArt seed={6} />
      <div className="relative flex items-center gap-4">
        <span className="grid size-11 place-items-center rounded-full bg-peri/25 text-sky">{icon}</span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h2 className="text-[18px] font-semibold tracking-[-0.02em]">{title}</h2>
            {integration ? <Badge tone={integration.enabled ? 'sky' : 'muted'} dot>{integration.enabled ? 'On' : 'Off'}</Badge> : null}
          </div>
          <p className="text-[12.5px] text-fg-3">{body}</p>
        </div>
        {extra}
        {integration && onToggle ? (
          <label className="flex items-center gap-2.5 text-[12.5px] text-fg-2">
            {busy ? <RefreshCw size={13} className="animate-spin" /> : null}
            <Toggle checked={integration.enabled} onChange={onToggle} label={`Turn ${title} ${integration.enabled ? 'off' : 'on'}`} />
          </label>
        ) : null}
      </div>
    </header>
  )
}

function AiPane({ data }: { data: IntegrationsOut }) {
  const ai = data.ai
  const keySet = Boolean(ai.credentials.api_key?.set)
  const models = useQuery({ queryKey: ['ai', 'models', keySet], queryFn: aiApi.models })
  const status = useQuery({ queryKey: ['ai', 'status'], queryFn: aiApi.status })
  const [key, setKey] = useState('')
  const [model, setModel] = useState(String(ai.config.model ?? ''))
  const [custom, setCustom] = useState(false)
  const [assistant, setAssistant] = useState(Boolean(ai.config.assistant ?? true))
  const [policy, setPolicy] = useState<'confirm_all' | 'confirm_significant'>((ai.config.change_policy as 'confirm_all') ?? 'confirm_all')
  const [temperature, setTemperature] = useState(Number(ai.config.temperature ?? 0.2))
  useEffect(() => {
    setModel(String(ai.config.model ?? ''))
    setAssistant(Boolean(ai.config.assistant ?? true))
    setPolicy((ai.config.change_policy as 'confirm_all') ?? 'confirm_all')
    setTemperature(Number(ai.config.temperature ?? 0.2))
  }, [ai.config])
  const list = models.data ?? data.models
  useEffect(() => {
    if (list.length && model && !list.some((item) => item.id === model)) setCustom(true)
  }, [list, model])
  const dirty =
    key.trim() !== '' ||
    model !== String(ai.config.model ?? '') ||
    assistant !== Boolean(ai.config.assistant ?? true) ||
    policy !== (ai.config.change_policy ?? 'confirm_all') ||
    temperature !== Number(ai.config.temperature ?? 0.2)
  const client = useQueryClient()
  const save = useAction(
    (args: { enabled?: boolean; removeKey?: boolean } = {}) =>
      api.integrations.update('ai', {
        enabled: args.enabled,
        config: { model, assistant, change_policy: policy, temperature },
        credentials: args.removeKey ? { api_key: '' } : key.trim() ? { api_key: key.trim() } : {},
      }),
    { success: 'AI settings saved' },
  )
  const test = useAction(api.integrations.testAi, { quiet: true })
  const chosen = list.find((item) => item.id === model)
  const source = data.ai_credential_source
  const saveAndRefresh = (args: { enabled?: boolean; removeKey?: boolean } = {}) =>
    save.mutate(args, {
      onSuccess: () => {
        setKey('')
        client.invalidateQueries({ queryKey: ['ai'] })
      },
    })
  return (
    <>
      <PaneHeader
        icon={<Sparkles size={20} />}
        title="AI · Gemini"
        body="Powers the assistant, and can read WhatsApp and email messages into enquiries. Your key stays on the server."
        integration={ai}
        busy={save.isPending}
        onToggle={(value) => saveAndRefresh({ enabled: value })}
        extra={<span className="text-[11.5px] text-fg-3">Switch: read messages into enquiries</span>}
      />
      <div className="min-h-0 flex-1 space-y-6 overflow-y-auto p-6">
        <section className="max-w-[760px] space-y-3">
          <h3 className="text-[14px] font-semibold">Connection</h3>
          <div className="flex items-center gap-2 text-[12.5px]">
            <span className={cn('size-2 rounded-full', status.data?.mode === 'live' ? 'bg-blue' : 'bg-fg-4')} />
            {status.data?.mode === 'live'
              ? source === 'settings'
                ? 'Connected with the key saved here.'
                : "Connected with the server's own Vertex AI credentials. A key saved here takes over."
              : status.data?.mode === 'development'
                ? 'Not connected — development mode is on, so the assistant runs a labelled script.'
                : 'Not connected. Add a Gemini API key to switch the assistant on.'}
          </div>
          <Field
            label="Gemini API key"
            hint={
              <>
                Create one at <a className="underline" href="https://aistudio.google.com/apikey" target="_blank" rel="noreferrer">aistudio.google.com/apikey</a>. It is encrypted on the server and never shown again — not even to you.
              </>
            }
          >
            {(props) => (
              <div className="flex gap-2">
                <input
                  {...props}
                  className="field font-mono"
                  type="password"
                  autoComplete="off"
                  spellCheck={false}
                  placeholder={keySet ? `Saved key ${ai.credentials.api_key?.hint ?? ''} — paste a new one to replace it` : 'Paste your Gemini API key'}
                  value={key}
                  onChange={(event) => setKey(event.target.value)}
                />
                {keySet ? (
                  <Button kind="danger" onClick={() => saveAndRefresh({ removeKey: true, enabled: false })} busy={save.isPending}>
                    Remove
                  </Button>
                ) : null}
              </div>
            )}
          </Field>
          <div className="grid grid-cols-2 gap-4 max-md:grid-cols-1">
            <Field label="Model" hint={custom ? 'Any Gemini model id your key can use.' : chosen?.hint || (keySet ? 'Listed from your key.' : undefined)}>
              {(props) =>
                custom ? (
                  <div className="flex gap-2">
                    <input {...props} className="field font-mono" value={model} placeholder="gemini-…" onChange={(event) => setModel(event.target.value.trim())} />
                    <Button onClick={() => { setCustom(false); setModel(list[0]?.id ?? '') }}>List</Button>
                  </div>
                ) : (
                  <select {...props} className="field" value={model} onChange={(event) => (event.target.value === '__custom' ? setCustom(true) : setModel(event.target.value))}>
                    {list.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.label}
                      </option>
                    ))}
                    <option value="__custom">Other model…</option>
                  </select>
                )
              }
            </Field>
            <Field label={`Creativity (temperature ${temperature.toFixed(1)})`} hint="Lower is more precise; 0.2 suits business data.">
              {(props) => <input {...props} type="range" min={0} max={1} step={0.1} value={temperature} onChange={(event) => setTemperature(Number(event.target.value))} className="mt-2 w-full accent-[var(--c-blue)]" />}
            </Field>
          </div>
        </section>
        <section className="max-w-[760px] space-y-3">
          <h3 className="text-[14px] font-semibold">Assistant</h3>
          <label className="card flex items-center gap-3 p-3.5">
            <Toggle checked={assistant} onChange={setAssistant} label="Assistant on" />
            <span className="min-w-0 flex-1">
              <span className="block text-[13px] font-medium">Assistant available to everyone</span>
              <span className="block text-[12px] text-fg-3">The floating button and the Assistant page. Each person sees only their own chats.</span>
            </span>
          </label>
          <Field label="Before changing data">
            {() => (
              <div className="grid grid-cols-2 gap-2 max-md:grid-cols-1">
                {(
                  [
                    ['confirm_all', 'Ask before every change', 'You confirm each change on a card. Recommended.'],
                    ['confirm_significant', 'Ask only for money, stock and cancellations', 'Contact details, notes and follow-ups are saved straight away; orders, purchases, receipts, deliveries and cancellations still wait for you.'],
                  ] as const
                ).map(([value, title, body]) => (
                  <button key={value} onClick={() => setPolicy(value)} className={cn('card p-3 text-left transition', policy === value && 'ring-2 ring-blue')}>
                    <div className="text-[13px] font-semibold">{title}</div>
                    <div className="mt-0.5 text-[12px] text-fg-3">{body}</div>
                  </button>
                ))}
              </div>
            )}
          </Field>
        </section>
        {test.data ? <Notice tone="ok">{`${test.data.model} answered: “${test.data.reply}”`}</Notice> : test.error ? <Notice tone="bad">{errorText(test.error)}</Notice> : null}
      </div>
      <footer className="flex shrink-0 items-center gap-2 border-t border-white/7 py-3.5 pr-24 pl-6 max-md:pr-20">
        <Button icon={<Wand2 size={14} />} busy={test.isPending} onClick={() => test.mutate(undefined)} disabled={dirty || status.data?.mode !== 'live'}>
          Test connection
        </Button>
        {dirty ? <span className="text-[12px] text-fg-3">Save before testing.</span> : null}
        <span className="flex-1" />
        <Button kind="primary" busy={save.isPending} disabled={!dirty || !model} onClick={() => saveAndRefresh()}>
          Save
        </Button>
      </footer>
    </>
  )
}

function ActivityPane() {
  const data = useQuery({ queryKey: ['ai', 'activity'], queryFn: aiApi.activity, refetchInterval: 15_000 })
  return (
    <>
      <PaneHeader icon={<History size={20} />} title="Assistant activity" body="Every tool the assistant ran: who asked, which part of the app it used, and how it ended." />
      <div className="min-h-0 flex-1 overflow-y-auto">
        {data.isPending ? (
          <Spinner />
        ) : !data.data?.length ? (
          <Empty title="Nothing yet" body="When the assistant reads or changes anything, it is recorded here." />
        ) : (
          <table className="grid-table">
            <thead>
              <tr>
                <th>When</th>
                <th>User</th>
                <th>Tool</th>
                <th>Route</th>
                <th>Result</th>
                <th className="r">Time</th>
              </tr>
            </thead>
            <tbody>
              {data.data.map((row) => (
                <tr key={row.id}>
                  <td className="text-[12px] text-fg-3">{fmtAgo(row.created_at)}</td>
                  <td className="text-[12.5px]">{row.user ?? '—'}</td>
                  <td className="text-[12.5px] font-medium">{row.tool.replace(/_/g, ' ')}</td>
                  <td className="font-mono text-[11.5px] text-fg-3">{row.route}</td>
                  <td className="max-w-[320px] truncate text-[12.5px]">{row.ok ? <Badge tone="sky" dot>OK</Badge> : <span title={row.error ?? ''}><Badge tone="bad" dot>{row.status_code ?? 'Error'}</Badge> <span className="text-fg-3">{row.error}</span></span>}</td>
                  <td className="r num text-[12px] text-fg-3">{row.duration_ms} ms</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  )
}

const ICONS = { whatsapp: <MessageCircle size={20} />, email: <Mail size={20} />, tally: <FileText size={20} /> }
const TITLES = { whatsapp: 'WhatsApp', email: 'Email', tally: 'Tally' }
const BODIES = {
  whatsapp: 'Receive customer messages from your WhatsApp Business number through Meta’s Cloud API.',
  email: 'Read unread mail from a mailbox and capture the enquiries in it.',
  tally: 'Send sales and purchase orders to TallyPrime as vouchers, and invoice each sale.',
}

function ConnectionPane({ data, name }: { data: IntegrationsOut; name: 'whatsapp' | 'email' | 'tally' }) {
  const integration = data[name]
  const groups = FORMS[name]
  const fields = groups.flatMap((group) => group.fields)
  const initial = useMemo(() => {
    const form: Record<string, string> = {}
    for (const field of fields) {
      if (field.kind === 'secret') form[field.key] = ''
      else form[field.key] = integration.config[field.key] == null ? '' : String(integration.config[field.key])
    }
    return form
  }, [integration]) // eslint-disable-line react-hooks/exhaustive-deps
  const [form, setForm] = useState(initial)
  useEffect(() => setForm(initial), [initial])
  const dirty = Object.keys(form).some((key) => form[key] !== initial[key])

  const save = useAction(
    (enabled?: boolean) => {
      const config: Record<string, unknown> = {}
      const credentials: Record<string, string> = {}
      for (const field of fields) {
        if (field.kind === 'secret') {
          if (form[field.key]) credentials[field.key] = form[field.key]
        } else if (field.kind === 'check') config[field.key] = form[field.key] === 'true'
        else if (field.kind === 'number') config[field.key] = form[field.key] === '' ? null : Number(form[field.key])
        else config[field.key] = form[field.key]
      }
      return api.integrations.update(name, { enabled, config, credentials })
    },
    { success: `${TITLES[name]} saved` },
  )
  const testTally = useAction(api.integrations.testTally, { quiet: true })
  const checkMail = useAction(api.integrations.checkEmail, { success: (result) => `${result.new_messages} new message${result.new_messages === 1 ? '' : 's'}` })
  const template = useAction(api.integrations.template, { quiet: true })
  const credentials = integration.credentials as Record<string, { set: boolean; hint: string | null }>
  const set = (key: string, value: string) => setForm((current) => ({ ...current, [key]: value }))

  return (
    <>
      <PaneHeader icon={ICONS[name]} title={TITLES[name]} body={BODIES[name]} integration={integration} busy={save.isPending} onToggle={(value) => save.mutate(value)} />
      <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-6">
        {name === 'whatsapp' && integration.enabled && !data.ai.enabled ? (
          <div className="pt-5">
            <Notice tone="warn">Messages are being received, but AI is off, so nobody reads them yet.</Notice>
          </div>
        ) : null}
        {name === 'email' && integration.config.last_error ? (
          <div className="pt-5">
            <Notice tone="bad">Last check failed: {String(integration.config.last_error)}</Notice>
          </div>
        ) : null}
        {name === 'whatsapp' ? (
          <div className="pt-5">
            <div className="label">Webhook URL</div>
            <CopyField value={WEBHOOK()} />
            <p className="mt-1.5 text-[12px] text-fg-3">Paste this into Meta with the verify token below. Meta can only reach a public HTTPS address.</p>
          </div>
        ) : null}
        {groups.map((group) => (
          <section key={group.title} className="border-b border-white/6 py-5 last:border-0">
            {group.title ? <h3 className="text-[13.5px] font-semibold">{group.title}</h3> : null}
            {group.hint ? <p className="mt-0.5 mb-4 text-[12px] text-fg-3">{group.hint}</p> : <div className="mb-3" />}
            <div className="grid max-w-[820px] grid-cols-2 gap-x-4 gap-y-4 max-md:grid-cols-1">
              {group.fields.map((field) =>
                field.kind === 'check' ? (
                  <label key={field.key} className="col-span-2 flex items-center gap-3 text-[13px]">
                    <Toggle checked={form[field.key] === 'true'} onChange={(value) => set(field.key, String(value))} label={field.label} />
                    {field.label}
                  </label>
                ) : field.kind === 'select' ? (
                  <Field key={field.key} label={field.label} hint={field.hint}>
                    {(props) => (
                      <select {...props} className="field" value={form[field.key]} onChange={(event) => set(field.key, event.target.value)}>
                        {field.options.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    )}
                  </Field>
                ) : (
                  <Field key={field.key} label={field.label} hint={field.hint} className={'wide' in field && field.wide ? 'col-span-2' : undefined}>
                    {(props) =>
                      field.key === 'verify_token' ? (
                        <div className="flex gap-2">
                          <input {...props} className="field" value={form[field.key]} onChange={(event) => set(field.key, event.target.value)} />
                          <Button onClick={() => set(field.key, crypto.randomUUID().replace(/-/g, ''))}>Generate</Button>
                        </div>
                      ) : (
                        <input
                          {...props}
                          className={cn('field', field.kind === 'number' && 'field-num')}
                          type={field.kind === 'secret' ? 'password' : 'text'}
                          inputMode={field.kind === 'number' ? 'decimal' : undefined}
                          autoComplete={field.kind === 'secret' ? 'new-password' : 'off'}
                          placeholder={field.kind === 'secret' ? (credentials[field.key]?.set ? `Saved (${credentials[field.key].hint ?? 'set'}) — type to replace` : 'Not set') : field.placeholder}
                          value={form[field.key]}
                          onChange={(event) => set(field.key, event.target.value)}
                        />
                      )
                    }
                  </Field>
                ),
              )}
            </div>
          </section>
        ))}
        {testTally.data ? (
          <Notice tone={testTally.data.company_found ? 'ok' : 'warn'}>
            {testTally.data.company_found ? 'Connected. The company was found.' : `Connected, but the company was not found. Open companies: ${testTally.data.companies.join(', ') || 'none'}.`}
          </Notice>
        ) : testTally.error ? (
          <Notice tone="bad">{errorText(testTally.error)}</Notice>
        ) : null}
        {template.data ? <Notice tone={template.data.status === 'APPROVED' ? 'ok' : 'warn'}>Template “{template.data.template}”: {template.data.status}</Notice> : template.error ? <Notice tone="bad">{errorText(template.error)}</Notice> : null}
      </div>
      <footer className="flex shrink-0 items-center gap-2 border-t border-white/7 px-6 py-3.5">
        {name === 'tally' ? (
          <Button icon={<RefreshCw size={14} />} busy={testTally.isPending} onClick={() => testTally.mutate(undefined)}>
            Test connection
          </Button>
        ) : null}
        {name === 'email' ? (
          <>
            <Button icon={<Inbox size={14} />} busy={checkMail.isPending} onClick={() => checkMail.mutate(undefined)} disabled={!integration.enabled}>
              Check inbox now
            </Button>
            <span className="text-[12px] text-fg-3">{integration.config.last_checked_at ? `Checked ${fmtAgo(String(integration.config.last_checked_at))}` : 'Not checked yet'}</span>
          </>
        ) : null}
        {name === 'whatsapp' ? (
          <Button icon={<Check size={14} />} busy={template.isPending} onClick={() => template.mutate(undefined)}>
            Check template
          </Button>
        ) : null}
        <span className="flex-1" />
        <Button onClick={() => setForm(initial)} disabled={!dirty}>
          Revert
        </Button>
        <Button kind="primary" busy={save.isPending} disabled={!dirty} onClick={() => save.mutate(undefined)}>
          Save
        </Button>
      </footer>
    </>
  )
}

function CopyField({ value }: { value: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="flex max-w-[820px] gap-2">
      <input className="field num" readOnly value={value} data-selectable />
      <Button
        icon={copied ? <Check size={14} /> : <Copy size={14} />}
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(value)
            setCopied(true)
            window.setTimeout(() => setCopied(false), 1600)
          } catch {
            toast.error('Copy failed — select the address and copy it by hand.')
          }
        }}
      >
        {copied ? 'Copied' : 'Copy'}
      </Button>
    </div>
  )
}

const OUTCOME: Record<string, ['ok' | 'warn' | 'bad' | 'muted' | 'sky', string]> = {
  enquiry_created: ['ok', 'Enquiry opened'],
  not_enquiry: ['muted', 'Not an enquiry'],
  no_match: ['warn', 'No matching products'],
  failed: ['bad', 'Failed'],
  pending: ['sky', 'Reading…'],
  skipped: ['muted', 'AI was off'],
}

function MessagesPane() {
  const [channel, setChannel] = useState('all')
  const messages = useList('messages', api.integrations.messages, { channel: channel === 'all' ? undefined : channel, limit: 100 })
  const retry = useAction(api.integrations.retryMessage, { success: 'Read again' })
  const rows = messages.data?.items ?? []
  return (
    <>
      <PaneHeader
        icon={<Inbox size={20} />}
        title="Received messages"
        body="Everything that came in on WhatsApp and email, and what the AI did with it."
        extra={
          <Segmented
            value={channel}
            onChange={setChannel}
            options={[
              { value: 'all', label: 'All' },
              { value: 'whatsapp', label: 'WhatsApp' },
              { value: 'email', label: 'Email' },
            ]}
          />
        }
      />
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-4">
        {messages.isPending ? (
          <Spinner />
        ) : rows.length === 0 ? (
          <Empty icon={<Inbox size={20} />} title="No messages yet" body="When WhatsApp or email is on, messages appear here." />
        ) : (
          rows.map((message) => {
            const [tone, label] = OUTCOME[message.status] ?? ['muted', message.status]
            return (
              <article key={message.id} className="card flex gap-3.5 p-4">
                <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-ink-700 text-fg-2 ring-1 ring-white/8">{message.channel === 'whatsapp' ? <MessageCircle size={16} /> : <Mail size={16} />}</span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-[13px] font-semibold">{message.sender_name ?? message.sender}</span>
                    <span className="text-[12px] text-fg-3">{message.sender_name ? message.sender : ''}</span>
                    <span className="ml-auto text-[11.5px] text-fg-3">{fmtDateTime(message.received_at)}</span>
                  </div>
                  {message.subject ? <div className="mt-0.5 text-[12.5px] font-medium text-fg-2">{message.subject}</div> : null}
                  <p className="mt-1 line-clamp-3 text-[13px] text-fg-2" data-selectable>
                    {message.body}
                  </p>
                  <div className="mt-2.5 flex flex-wrap items-center gap-2">
                    <Badge tone={tone} dot>
                      {label}
                    </Badge>
                    {message.enquiry_id ? (
                      <Link to={`/enquiries/${message.enquiry_id}`} className="num text-[12px] font-medium text-sky hover:text-sky-2">
                        {message.enquiry_number}
                      </Link>
                    ) : null}
                    {message.summary ? <span className="text-[12px] text-fg-3">{message.summary}</span> : null}
                    {message.error ? <span className="text-[12px] text-bad">{message.error}</span> : null}
                    {['failed', 'skipped'].includes(message.status) ? (
                      <Button small className="ml-auto" icon={<RefreshCw size={12} />} onClick={() => retry.mutate(message.id)} busy={retry.isPending && retry.variables === message.id}>
                        Read again
                      </Button>
                    ) : null}
                  </div>
                </div>
              </article>
            )
          })
        )}
      </div>
    </>
  )
}

const KIND: Record<string, string> = { sales_order: 'Sales order', sales_invoice: 'Sales invoice', purchase_order: 'Purchase order' }
function SyncsPane() {
  const [status, setStatus] = useState('all')
  const syncs = useList('tally-syncs', api.integrations.syncs, { status: status === 'all' ? undefined : status, limit: 200 })
  const retry = useAction(api.integrations.retrySync, { success: 'Sent to Tally again' })
  const rows = syncs.data?.items ?? []
  return (
    <>
      <PaneHeader
        icon={<RefreshCw size={20} />}
        title="Tally sync log"
        body="Every order and invoice sent to Tally, and whether the invoice reached the customer."
        extra={
          <Segmented
            value={status}
            onChange={setStatus}
            options={[
              { value: 'all', label: 'All' },
              { value: 'pending', label: 'Waiting' },
              { value: 'failed', label: 'Failed' },
              { value: 'synced', label: 'Done' },
            ]}
          />
        }
      />
      <div className="min-h-0 flex-1 overflow-y-auto">
        {syncs.isPending ? (
          <Spinner />
        ) : rows.length === 0 ? (
          <Empty icon={<RefreshCw size={20} />} title="Nothing sent to Tally" body="When Tally is on, orders appear here as they sync." />
        ) : (
          <table className="grid-table">
            <thead>
              <tr>
                <th>Record</th>
                <th>Status</th>
                <th>Tally no.</th>
                <th>Invoice to customer</th>
                <th className="r" />
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>
                    <div className="num text-[13px] font-medium">{row.reference}</div>
                    <div className="text-[11.5px] text-fg-3">
                      {KIND[row.kind] ?? row.kind} · {fmtAgo(row.created_at)}
                    </div>
                  </td>
                  <td>
                    <Badge tone={row.status === 'synced' ? 'ok' : row.status === 'failed' ? 'bad' : 'sky'} dot>
                      {row.status === 'synced' ? 'In Tally' : row.status === 'failed' ? 'Failed' : 'Waiting'}
                    </Badge>
                    {row.error ? <div className="mt-1 max-w-[320px] truncate text-[11.5px] text-bad" title={row.error}>{row.error}</div> : null}
                  </td>
                  <td className="num text-[13px]">{row.tally_number ?? '—'}</td>
                  <td className="text-[12.5px] text-fg-2">{row.kind === 'sales_invoice' ? (row.notify_status === 'sent' ? `Sent ${fmtAgo(row.notified_at)}` : row.notify_error ?? row.notify_status) : '—'}</td>
                  <td className="r">
                    {row.status === 'failed' ? (
                      <Button small icon={<RefreshCw size={12} />} onClick={() => retry.mutate(row.id)}>
                        Retry
                      </Button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  )
}
