import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, BASE_URL, api } from '../api/client'
import type { InboundMessage, InboundStatus, Integration, Integrations } from '../api/types'
import {
  AsyncBlock,
  Badge,
  Button,
  Card,
  CardBody,
  EmptyState,
  Field,
  FormGrid,
  Notice,
  Page,
  Pagination,
  Segmented,
  Switch,
  TableScroll,
  Toolbar,
  useToast,
  type Tone,
} from '../components/ui'
import {
  AiIcon,
  DocumentIcon as TallyIcon,
  CheckIcon,
  CopyIcon,
  EmailIcon,
  InboxIcon,
  RefreshIcon,
  WhatsAppIcon,
} from '../components/icons'
import { formatDateTime, formatRelative } from '../lib/format'
import { usePaging } from '../lib/paging'
import { useAsync } from '../lib/useAsync'

const WEBHOOK_PATH = '/api/integrations/whatsapp/webhook'

/** The address Meta must call. In production the API and the app share an origin. */
function webhookUrl() {
  return new URL(WEBHOOK_PATH, BASE_URL || window.location.origin).toString()
}

type Form = Record<string, string>

function errorText(cause: unknown) {
  return cause instanceof ApiError ? cause.message : String(cause)
}

/** Settings as editable text, plus empty credential fields ("leave blank to keep"). */
function formOf(integration: Integration, fields: string[]): Form {
  const form: Form = {}
  for (const key of fields) form[key] = integration.config[key] == null ? '' : String(integration.config[key])
  for (const key of Object.keys(integration.credentials)) form[key] = ''
  return form
}

/** One integration: header with a switch, its settings, Save. Turning it on
 *  saves whatever is typed too, so it can be set up and switched on in one go. */
function IntegrationCard({
  integration,
  fields,
  icon,
  title,
  description,
  status,
  onSaved,
  children,
  extraActions,
}: {
  integration: Integration
  fields: string[]
  icon: ReactNode
  title: string
  description: string
  status?: { tone: Tone; label: string }
  onSaved: () => void
  children: (form: Form, set: (key: string, value: string) => void) => ReactNode
  extraActions?: ReactNode
}) {
  const toast = useToast()
  const initial = useMemo(() => formOf(integration, fields), [integration])
  const [form, setForm] = useState<Form>(initial)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => setForm(initial), [initial])

  const dirty = Object.keys(form).some((key) => form[key] !== initial[key])
  const set = (key: string, value: string) => setForm((current) => ({ ...current, [key]: value }))

  async function save(enabled?: boolean) {
    setBusy(true)
    setError(null)
    const config: Record<string, string> = {}
    const credentials: Record<string, string> = {}
    for (const key of fields) config[key] = form[key]
    for (const key of Object.keys(integration.credentials)) if (form[key]) credentials[key] = form[key]
    try {
      await api.integrations.update(integration.name, { enabled, config, credentials })
      toast.success(
        enabled === undefined ? `${title} saved` : `${title} switched ${enabled ? 'on' : 'off'}`,
      )
      onSaved()
    } catch (cause) {
      setError(errorText(cause))
    } finally {
      setBusy(false)
    }
  }

  const badge = status ?? (integration.enabled ? { tone: 'green' as Tone, label: 'On' } : { tone: 'gray' as Tone, label: 'Off' })
  return (
    <Card
      className="integration"
      title={
        <span className="integration__title">
          <span className={`integration__icon integration__icon--${integration.name}`} aria-hidden="true">
            {icon}
          </span>
          {title}
          <Badge tone={badge.tone} dot>
            {badge.label}
          </Badge>
        </span>
      }
      subtitle={description}
      actions={
        <Switch
          checked={integration.enabled}
          onChange={(next) => save(next)}
          label={integration.enabled ? 'On' : 'Off'}
        />
      }
      footer={
        <div className="integration__footer">
          {extraActions}
          <span className="grow" />
          <Button variant="primary" busy={busy} disabled={!dirty} onClick={() => save()}>
            Save
          </Button>
        </div>
      }
    >
      <CardBody>
        <div className="stack">
          {error ? <Notice kind="error">{error}</Notice> : null}
          {children(form, set)}
        </div>
      </CardBody>
    </Card>
  )
}

function credentialPlaceholder(integration: Integration, key: string, fallback: string) {
  const credential = integration.credentials[key]
  return credential?.set ? `Saved (${credential.hint ?? 'set'}) — type to replace` : fallback
}

/* -------------------------------------------------------------------------- */

function AiSection({ data, reload }: { data: Integrations; reload: () => void }) {
  const toast = useToast()
  const [testing, setTesting] = useState(false)
  const integration = data.ai

  async function test() {
    setTesting(true)
    try {
      const result = await api.integrations.testAi()
      toast.success('Connection works', `${result.model} answered.`)
    } catch (cause) {
      toast.error('Connection failed', errorText(cause))
    } finally {
      setTesting(false)
    }
  }

  return (
    <IntegrationCard
      integration={integration}
      fields={['model']}
      icon={<AiIcon size={18} />}
      title="AI"
      description="Reads each WhatsApp message and email, and records the sales enquiries in them. It never replies to customers."
      status={data.models.length === 0 ? { tone: 'orange', label: 'Not set up' } : undefined}
      onSaved={reload}
      extraActions={
        <Button onClick={test} busy={testing} disabled={data.models.length === 0}>
          Test connection
        </Button>
      }
    >
      {(form, set) =>
        data.models.length === 0 ? (
          <Notice kind="warning" title="Not set up on the server">
            The AI's credentials are managed by the administrator and have not been added yet.
          </Notice>
        ) : (
          <FormGrid>
            <Field label="Model" hint={data.models.find((model) => model.id === form.model)?.hint}>
              {(props) => (
                <select {...props} value={form.model} onChange={(event) => set('model', event.target.value)}>
                  {data.models.map((model) => (
                    <option key={model.id} value={model.id}>
                      {model.label}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            <Field label="Provider">
              {(props) => (
                <input {...props} readOnly value={data.providers.join(', ')} tabIndex={-1} />
              )}
            </Field>
            <p className="hint span-2">Credentials are managed by the administrator on the server.</p>
          </FormGrid>
        )
      }
    </IntegrationCard>
  )
}

function CopyField({ value }: { value: string }) {
  const [copied, setCopied] = useState(false)
  async function copy() {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1600)
    } catch {
      window.prompt('Copy the webhook URL', value)
    }
  }
  return (
    <div className="copy-field">
      <input className="input mono" readOnly value={value} onFocus={(event) => event.target.select()} aria-label="Webhook URL" />
      <Button icon={copied ? <CheckIcon size={14} /> : <CopyIcon size={14} />} onClick={copy}>
        {copied ? 'Copied' : 'Copy'}
      </Button>
    </div>
  )
}

function randomToken() {
  const bytes = new Uint8Array(18)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
}

/** A yes/no setting kept as text in the form ('true' / 'false'). */
function Check({ form, set, name, label, hint }: { form: Form; set: (key: string, value: string) => void; name: string; label: string; hint?: string }) {
  return (
    <label className="check-row span-2">
      <input type="checkbox" checked={form[name] === 'true'} onChange={(event) => set(name, String(event.target.checked))} />
      <span>
        <span className="check-row__label">{label}</span>
        {hint ? <span className="hint">{hint}</span> : null}
      </span>
    </label>
  )
}

function Section({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="form-section span-2">
      <span className="section-label">{title}</span>
      {hint ? <span className="hint">{hint}</span> : null}
    </div>
  )
}

function TextField({ form, set, name, label, hint, placeholder, mono, optional }: {
  form: Form; set: (key: string, value: string) => void; name: string; label: string
  hint?: ReactNode; placeholder?: string; mono?: boolean; optional?: boolean
}) {
  return (
    <Field label={label} hint={hint} optional={optional}>
      {(props) => (
        <input {...props} className={mono ? 'input mono' : 'input'} value={form[name]} placeholder={placeholder}
          onChange={(event) => set(name, event.target.value)} />
      )}
    </Field>
  )
}

function WhatsAppSection({ data, reload }: { data: Integrations; reload: () => void }) {
  const toast = useToast()
  const [checking, setChecking] = useState(false)
  const integration = data.whatsapp

  async function checkTemplate() {
    setChecking(true)
    try {
      const result = await api.integrations.templateStatus()
      const approved = result.status.includes('APPROVED')
      ;(approved ? toast.success : toast.error)(`Template "${result.template}"`, result.status === 'NOT_FOUND' ? 'Not found in your WhatsApp account.' : result.status)
    } catch (cause) {
      toast.error('Could not check the template', errorText(cause))
    } finally {
      setChecking(false)
    }
  }
  const url = webhookUrl()
  const local = /\/\/(localhost|127\.)/.test(url)
  return (
    <IntegrationCard
      integration={integration}
      fields={['phone_number_id', 'business_account_id', 'verify_token', 'send_invoices', 'invoice_template', 'template_language', 'country_code']}
      extraActions={
        <Button onClick={checkTemplate} busy={checking} disabled={!integration.credentials.access_token?.set || !integration.config.invoice_template}>
          Check template
        </Button>
      }
      icon={<WhatsAppIcon size={18} />}
      title="WhatsApp"
      description="Receive customer messages from your WhatsApp Business number through Meta's Cloud API."
      status={integration.enabled && !data.ai.enabled ? { tone: 'orange', label: 'On · AI off' } : undefined}
      onSaved={reload}
    >
      {(form, set) => (
        <>
          {integration.enabled && !data.ai.enabled ? (
            <Notice kind="warning">Messages are being received, but AI is off, so nobody reads them yet.</Notice>
          ) : null}
          <FormGrid>
            <Field label="Phone number ID" hint="Meta for Developers → your app → WhatsApp → API Setup.">
              {(props) => (
                <input {...props} className="input mono" value={form.phone_number_id} onChange={(event) => set('phone_number_id', event.target.value)} placeholder="e.g. 109876543210987" />
              )}
            </Field>
            <Field label="WhatsApp Business Account ID" optional>
              {(props) => (
                <input {...props} className="input mono" value={form.business_account_id} onChange={(event) => set('business_account_id', event.target.value)} placeholder="e.g. 102345678901234" />
              )}
            </Field>
            <Field label="Verify token" hint="Any secret phrase. Paste the same one into Meta.">
              {(props) => (
                <div className="copy-field">
                  <input {...props} className="input mono" value={form.verify_token} onChange={(event) => set('verify_token', event.target.value)} />
                  <Button onClick={() => set('verify_token', randomToken())}>Generate</Button>
                </div>
              )}
            </Field>
            <Field
              label="App secret"
              optional
              hint="Meta app → Settings → Basic. When set, only requests signed by Meta are accepted."
            >
              {(props) => (
                <input
                  {...props}
                  type="password"
                  autoComplete="off"
                  placeholder={credentialPlaceholder(integration, 'app_secret', 'Recommended')}
                  value={form.app_secret}
                  onChange={(event) => set('app_secret', event.target.value)}
                />
              )}
            </Field>
            <Field
              label="Webhook URL"
              span2
              hint={
                local
                  ? 'This is a local address. Meta can only reach a public HTTPS address, such as the deployed app.'
                  : "Meta for Developers → WhatsApp → Configuration → Webhook: paste this URL and the verify token, then subscribe to 'messages'."
              }
            >
              {() => <CopyField value={url} />}
            </Field>

            <Section title="Send invoices" hint="Invoices from Tally go to the customer's WhatsApp as soon as Tally creates them." />
            <Check form={form} set={set} name="send_invoices" label="Send each invoice to the customer on WhatsApp" />
            <Field
              label="Access token"
              hint="Meta Business settings → System users → generate a permanent token with whatsapp_business_messaging."
            >
              {(props) => (
                <input {...props} type="password" autoComplete="off"
                  placeholder={credentialPlaceholder(integration, 'access_token', 'EAAG…')}
                  value={form.access_token} onChange={(event) => set('access_token', event.target.value)} />
              )}
            </Field>
            <TextField form={form} set={set} name="invoice_template" label="Invoice template name" mono placeholder="invoice_pdf"
              hint={<>Utility template with a <b>Document</b> header and body “Hello {'{{1}}'}, your invoice {'{{2}}'} for {'{{3}}'} is attached.”</>} />
            <TextField form={form} set={set} name="template_language" label="Template language" mono placeholder="en" />
            <TextField form={form} set={set} name="country_code" label="Default country code" mono placeholder="91"
              hint="Added to 10-digit customer numbers." />
          </FormGrid>
        </>
      )}
    </IntegrationCard>
  )
}

const TALLY_FIELDS = [
  'server_url', 'company', 'sync_sales_orders', 'create_invoices', 'sync_purchase_orders',
  'customer_group', 'supplier_group', 'godown', 'sales_ledger', 'purchase_ledger',
  'sales_order_type', 'sales_invoice_type', 'purchase_order_type',
  'tax_mode', 'gst_rate', 'cgst_ledger', 'sgst_ledger', 'igst_ledger',
  'seller_name', 'seller_address', 'seller_gstin', 'seller_phone',
]

function TallySection({ data, reload }: { data: Integrations; reload: () => void }) {
  const toast = useToast()
  const [testing, setTesting] = useState(false)
  const integration = data.tally

  async function test() {
    setTesting(true)
    try {
      const result = await api.integrations.testTally()
      if (result.company_found) toast.success('Connected to Tally', `${integration.config.company} is open.`)
      else toast.error('Connected, but the company is not open', `Open in Tally: ${result.companies.join(', ') || 'none'}`)
    } catch (cause) {
      toast.error('Could not reach Tally', errorText(cause))
    } finally {
      setTesting(false)
    }
  }

  return (
    <IntegrationCard
      integration={integration}
      fields={TALLY_FIELDS}
      icon={<TallyIcon size={18} />}
      title="Tally"
      description="Sales and purchase orders go to TallyPrime as vouchers the moment they are placed; each sale is invoiced in Tally."
      onSaved={reload}
      extraActions={
        <Button onClick={test} busy={testing} disabled={!integration.config.server_url}>
          Test connection
        </Button>
      }
    >
      {(form, set) => (
        <FormGrid>
          <Section title="Connection" hint="TallyPrime's HTTP server: F1 → Settings → Connectivity → TallyPrime acts as Server (port 9000). Open its port only to this app." />
          <TextField form={form} set={set} name="server_url" label="Tally server address" mono placeholder="http://your-tally-host:9000" />
          <TextField form={form} set={set} name="company" label="Company name" hint="Exactly as it appears in Tally." />
          <Field label="Access token" optional hint="Only if a gateway or tunnel in front of Tally asks for one (sent as a bearer token).">
            {(props) => (
              <input {...props} type="password" autoComplete="off"
                placeholder={credentialPlaceholder(integration, 'auth_token', 'Not needed for a direct connection')}
                value={form.auth_token} onChange={(event) => set('auth_token', event.target.value)} />
            )}
          </Field>

          <Section title="What to sync" />
          <Check form={form} set={set} name="sync_sales_orders" label="Sales orders → Sales Order vouchers" />
          <Check form={form} set={set} name="create_invoices" label="Invoice each sales order in Tally (Sales voucher)" hint="Tally numbers the invoice; that number is used on the PDF sent to the customer." />
          <Check form={form} set={set} name="sync_purchase_orders" label="Placed purchase orders → Purchase Order vouchers" />

          <Section title="Ledgers and voucher types" hint="Must match the names in your Tally company. Customers, suppliers and stock items are created if missing." />
          <TextField form={form} set={set} name="sales_ledger" label="Sales ledger" />
          <TextField form={form} set={set} name="purchase_ledger" label="Purchase ledger" />
          <TextField form={form} set={set} name="customer_group" label="Group for new customers" />
          <TextField form={form} set={set} name="supplier_group" label="Group for new suppliers" />
          <TextField form={form} set={set} name="godown" label="Godown" />
          <TextField form={form} set={set} name="sales_order_type" label="Sales Order voucher type" />
          <TextField form={form} set={set} name="sales_invoice_type" label="Sales voucher type" hint="Set its numbering to Automatic in Tally." />
          <TextField form={form} set={set} name="purchase_order_type" label="Purchase Order voucher type" />

          <Section title="GST on invoices" />
          <Field label="Tax">
            {(props) => (
              <select {...props} value={form.tax_mode} onChange={(event) => set('tax_mode', event.target.value)}>
                <option value="none">No tax</option>
                <option value="cgst_sgst">CGST + SGST (within the state)</option>
                <option value="igst">IGST (other states)</option>
              </select>
            )}
          </Field>
          <Field label="GST rate (%)">
            {(props) => <input {...props} className="input input--num" inputMode="decimal" value={form.gst_rate} onChange={(event) => set('gst_rate', event.target.value)} disabled={form.tax_mode === 'none'} />}
          </Field>
          {form.tax_mode === 'cgst_sgst' ? (
            <>
              <TextField form={form} set={set} name="cgst_ledger" label="CGST ledger" />
              <TextField form={form} set={set} name="sgst_ledger" label="SGST ledger" />
            </>
          ) : form.tax_mode === 'igst' ? (
            <TextField form={form} set={set} name="igst_ledger" label="IGST ledger" />
          ) : null}

          <Section title="Your details on the invoice" />
          <TextField form={form} set={set} name="seller_name" label="Business name" />
          <TextField form={form} set={set} name="seller_gstin" label="GSTIN" mono optional />
          <TextField form={form} set={set} name="seller_address" label="Address" optional />
          <TextField form={form} set={set} name="seller_phone" label="Phone" optional />
        </FormGrid>
      )}
    </IntegrationCard>
  )
}


function EmailSection({ data, reload }: { data: Integrations; reload: () => void }) {
  const toast = useToast()
  const integration = data.email
  const [checking, setChecking] = useState(false)
  const lastChecked = integration.config.last_checked_at as string | null
  const lastError = integration.config.last_error as string | null

  async function checkNow() {
    setChecking(true)
    try {
      const result = await api.integrations.checkEmail()
      toast.success(
        result.new_messages ? `${result.new_messages} new email${result.new_messages === 1 ? '' : 's'}` : 'No new email',
        result.new_messages ? 'The AI is reading them now.' : undefined,
      )
    } catch (cause) {
      toast.error('Could not read the inbox', errorText(cause))
    } finally {
      setChecking(false)
      reload()
    }
  }

  return (
    <IntegrationCard
      integration={integration}
      fields={['imap_host', 'imap_port', 'username', 'folder', 'poll_minutes']}
      icon={<EmailIcon size={18} />}
      title="Email"
      description="Read unread mail from a mailbox over IMAP and capture the enquiries in it."
      status={integration.enabled && !data.ai.enabled ? { tone: 'orange', label: 'On · AI off' } : undefined}
      onSaved={reload}
      extraActions={
        <>
          <Button icon={<InboxIcon size={14} />} onClick={checkNow} busy={checking} disabled={!integration.credentials.password?.set}>
            Check inbox now
          </Button>
          <span className="hint">
            {lastError ? (
              <span className="q-negative">{lastError}</span>
            ) : lastChecked ? (
              <>Last checked {formatRelative(lastChecked)}</>
            ) : (
              'Not checked yet'
            )}
          </span>
        </>
      }
    >
      {(form, set) => (
        <FormGrid>
          <Field label="IMAP server" hint="Gmail: imap.gmail.com · Outlook: outlook.office365.com">
            {(props) => <input {...props} value={form.imap_host} onChange={(event) => set('imap_host', event.target.value)} placeholder="imap.example.com" />}
          </Field>
          <Field label="Port" hint="993 for IMAP over SSL.">
            {(props) => <input {...props} className="input input--num" inputMode="numeric" value={form.imap_port} onChange={(event) => set('imap_port', event.target.value)} />}
          </Field>
          <Field label="Email address">
            {(props) => <input {...props} type="email" autoComplete="off" value={form.username} onChange={(event) => set('username', event.target.value)} placeholder="sales@yourbusiness.com" />}
          </Field>
          <Field label="Password" hint="For Gmail and Outlook, use an app password.">
            {(props) => (
              <input
                {...props}
                type="password"
                autoComplete="new-password"
                placeholder={credentialPlaceholder(integration, 'password', 'App password')}
                value={form.password}
                onChange={(event) => set('password', event.target.value)}
              />
            )}
          </Field>
          <Field label="Folder">
            {(props) => <input {...props} value={form.folder} onChange={(event) => set('folder', event.target.value)} />}
          </Field>
          <Field label="Check every (minutes)">
            {(props) => <input {...props} className="input input--num" inputMode="numeric" value={form.poll_minutes} onChange={(event) => set('poll_minutes', event.target.value)} />}
          </Field>
        </FormGrid>
      )}
    </IntegrationCard>
  )
}

/* -------------------------------------------------------------------------- */

const OUTCOME: Record<InboundStatus, { tone: Tone; label: string }> = {
  pending: { tone: 'blue', label: 'Reading…' },
  enquiry_created: { tone: 'green', label: 'Enquiry' },
  not_enquiry: { tone: 'gray', label: 'Not an enquiry' },
  no_match: { tone: 'orange', label: 'No matching products' },
  failed: { tone: 'red', label: 'Failed' },
  skipped: { tone: 'gray', label: 'AI was off' },
}

type ChannelFilter = 'all' | 'whatsapp' | 'email'

function MessagesSection() {
  const toast = useToast()
  const [channel, setChannel] = useState<ChannelFilter>('all')
  const paging = usePaging('inbound-messages', [channel])
  const state = useAsync(
    () =>
      api.integrations.messages({
        channel: channel === 'all' ? undefined : channel,
        limit: paging.limit,
        offset: paging.offset,
      }),
    [channel, paging.limit, paging.offset],
  )
  const rows = state.data?.items ?? []
  const reading = rows.some((row) => row.status === 'pending')

  // While the AI is reading, look again shortly.
  useEffect(() => {
    if (!reading) return
    const timer = window.setTimeout(state.reload, 4000)
    return () => window.clearTimeout(timer)
  }, [reading, state.data])

  async function retry(message: InboundMessage) {
    try {
      await api.integrations.retry(message.id)
      toast.success('Sent back to the AI')
      state.reload()
    } catch (cause) {
      toast.error('Could not retry', errorText(cause))
    }
  }

  return (
    <Card
      flush
      title="Received messages"
      subtitle="Everything that came in on WhatsApp and email, and what the AI did with it"
      actions={
        <div className="row gap-2">
          <Segmented
            label="Channel"
            small
            value={channel}
            onChange={setChannel}
            options={[
              { value: 'all', label: 'All' },
              { value: 'whatsapp', label: 'WhatsApp' },
              { value: 'email', label: 'Email' },
            ]}
          />
          <Button size="sm" variant="plain" icon={<RefreshIcon size={14} />} onClick={state.reload}>
            Refresh
          </Button>
        </div>
      }
    >
      <AsyncBlock loading={state.loading} error={state.error} data={state.data} onRetry={state.reload} skeleton="spinner">
        {(page) =>
          page.items.length === 0 ? (
            <EmptyState
              compact
              icon={<InboxIcon size={22} />}
              title="Nothing received yet"
              body="Messages appear here as soon as WhatsApp or email delivers them."
            />
          ) : (
            <>
              <TableScroll>
                <table className="table">
                  <thead>
                    <tr>
                      <th>From</th>
                      <th>Message</th>
                      <th>Outcome</th>
                      <th className="num">Received</th>
                    </tr>
                  </thead>
                  <tbody>
                    {page.items.map((message) => {
                      const outcome = OUTCOME[message.status]
                      return (
                        <tr key={message.id}>
                          <td>
                            <div className="cell-identity">
                              <span className={`integration__icon integration__icon--${message.channel} integration__icon--sm`} aria-hidden="true">
                                {message.channel === 'whatsapp' ? <WhatsAppIcon size={14} /> : <EmailIcon size={14} />}
                              </span>
                              <div>
                                <span className="cell-primary">{message.sender_name || message.sender}</span>
                                {message.sender_name ? <span className="cell-sub">{message.sender}</span> : null}
                              </div>
                            </div>
                          </td>
                          <td className="inbound__message">
                            {message.subject ? <span className="cell-primary">{message.subject}</span> : null}
                            <span className="cell-sub inbound__body" title={message.body}>
                              {message.body}
                            </span>
                          </td>
                          <td className="inbound__outcome">
                            <div className="row gap-2">
                              <Badge tone={outcome.tone} dot>
                                {outcome.label}
                              </Badge>
                              {message.enquiry_id ? (
                                <Link className="mono" to={`/enquiries/${message.enquiry_id}`}>
                                  {message.enquiry_number}
                                </Link>
                              ) : null}
                              {message.status === 'failed' || message.status === 'skipped' ? (
                                <Button size="sm" variant="plain" onClick={() => retry(message)}>
                                  Retry
                                </Button>
                              ) : null}
                            </div>
                            {message.summary || message.error ? (
                              <span className={`cell-sub${message.error ? ' q-negative' : ''}`}>
                                {message.error ?? message.summary}
                              </span>
                            ) : null}
                          </td>
                          <td className="num nowrap">
                            <span title={formatDateTime(message.received_at)}>{formatRelative(message.received_at)}</span>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </TableScroll>
              <Pagination paging={paging} total={page.total} noun="messages" />
            </>
          )
        }
      </AsyncBlock>
    </Card>
  )
}

export default function IntegrationsPage() {
  const state = useAsync<Integrations>(() => api.integrations.get(), [])
  return (
    <Page>
      <Toolbar
        title="Integrations"
        subtitle="Let AI turn WhatsApp messages and emails into sales enquiries"
      />
      <AsyncBlock loading={state.loading} error={state.error} data={state.data} onRetry={state.reload} skeleton="spinner">
        {(data) => (
          <div className="stack">
            <AiSection data={data} reload={state.reload} />
            <div className="columns integrations__channels">
              <WhatsAppSection data={data} reload={state.reload} />
              <EmailSection data={data} reload={state.reload} />
            </div>
            <TallySection data={data} reload={state.reload} />
            <MessagesSection />
            <TallySyncSection />
          </div>
        )}
      </AsyncBlock>
    </Page>
  )
}

/* -------------------------------------------------------------------------- */

const KIND_LABEL: Record<string, string> = {
  sales_order: 'Sales Order',
  sales_invoice: 'Sales invoice',
  purchase_order: 'Purchase Order',
}
const SYNC_TONE: Record<string, Tone> = { pending: 'blue', synced: 'green', failed: 'red' }
const NOTIFY: Record<string, { tone: Tone; label: string } | undefined> = {
  pending: { tone: 'blue', label: 'Sending…' },
  sent: { tone: 'green', label: 'Sent' },
  failed: { tone: 'red', label: 'Not sent' },
  skipped: { tone: 'gray', label: 'Not sent' },
}

/** What has gone to Tally, and whether each invoice reached the customer. */
function TallySyncSection() {
  const toast = useToast()
  const paging = usePaging('tally-syncs', [])
  const state = useAsync(
    () => api.integrations.tallySyncs({ limit: paging.limit, offset: paging.offset }),
    [paging.limit, paging.offset],
  )
  const busy = (state.data?.items ?? []).some((row) => row.status === 'pending' || row.notify_status === 'pending')
  useEffect(() => {
    if (!busy) return
    const timer = window.setTimeout(state.reload, 4000)
    return () => window.clearTimeout(timer)
  }, [busy, state.data])

  async function retry(id: string) {
    try {
      await api.integrations.retryTally(id)
      toast.success('Trying again')
      state.reload()
    } catch (cause) {
      toast.error('Could not retry', errorText(cause))
    }
  }

  return (
    <Card
      flush
      title="Tally sync"
      subtitle="Every order sent to Tally, and every invoice sent to a customer"
      actions={
        <Button size="sm" variant="plain" icon={<RefreshIcon size={14} />} onClick={state.reload}>
          Refresh
        </Button>
      }
    >
      <AsyncBlock loading={state.loading} error={state.error} data={state.data} onRetry={state.reload} skeleton="spinner">
        {(page) =>
          page.items.length === 0 ? (
            <EmptyState
              compact
              icon={<TallyIcon size={22} />}
              title="Nothing sent to Tally yet"
              body="Orders appear here once Tally is switched on and an order is placed."
            />
          ) : (
            <>
              <TableScroll>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Document</th>
                      <th>Tally</th>
                      <th>Invoice on WhatsApp</th>
                      <th className="num">When</th>
                      <th className="col-actions" />
                    </tr>
                  </thead>
                  <tbody>
                    {page.items.map((row) => {
                      const notify = NOTIFY[row.notify_status]
                      const link = row.kind === 'purchase_order' ? `/purchase-orders/${row.entity_id}` : `/orders/${row.entity_id}`
                      const hasPdf = row.kind === 'sales_invoice' && row.status === 'synced'
                      const canRetry =
                        row.status === 'failed' ||
                        (row.kind === 'sales_invoice' && (row.notify_status === 'failed' || row.notify_status === 'skipped'))
                      return (
                        <tr key={row.id}>
                          <td>
                            <span className="cell-primary">{KIND_LABEL[row.kind]}</span>
                            <Link className="cell-sub mono" to={link}>
                              {row.reference}
                            </Link>
                          </td>
                          <td className="inbound__outcome">
                            <div className="row gap-2">
                              <Badge tone={SYNC_TONE[row.status]} dot>
                                {row.status === 'synced' ? 'In Tally' : row.status === 'pending' ? 'Sending…' : 'Failed'}
                              </Badge>
                              {row.tally_number ? <span className="mono">{row.tally_number}</span> : null}
                            </div>
                            {row.error ? <span className="cell-sub q-negative">{row.error}</span> : null}
                          </td>
                          <td className="inbound__outcome">
                            <div className="row gap-2">
                              {notify ? (
                                <Badge tone={notify.tone} dot>
                                  {notify.label}
                                </Badge>
                              ) : null}
                              {row.notify_to ? <span className="mono">+{row.notify_to}</span> : null}
                              {hasPdf ? (
                                <a href={api.integrations.invoiceUrl(row.entity_id)} target="_blank" rel="noreferrer">
                                  PDF
                                </a>
                              ) : null}
                              {!notify && !hasPdf ? <span className="q-muted">—</span> : null}
                            </div>
                            {row.notify_error ? <span className="cell-sub q-negative">{row.notify_error}</span> : null}
                          </td>
                          <td className="num nowrap">
                            <span title={formatDateTime(row.created_at)}>{formatRelative(row.created_at)}</span>
                          </td>
                          <td className="col-actions">
                            {canRetry ? (
                              <Button size="sm" variant="plain" onClick={() => retry(row.id)}>
                                Retry
                              </Button>
                            ) : null}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </TableScroll>
              <Pagination paging={paging} total={page.total} noun="documents" />
            </>
          )
        }
      </AsyncBlock>
    </Card>
  )
}
