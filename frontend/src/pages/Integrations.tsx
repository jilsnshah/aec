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
      onSaved={reload}
      extraActions={
        <Button onClick={test} busy={testing} disabled={!integration.credentials.api_key?.set}>
          Test connection
        </Button>
      }
    >
      {(form, set) => (
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
          <Field
            label="Anthropic API key"
            hint={
              <>
                Create one at{' '}
                <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noreferrer">
                  console.anthropic.com
                </a>
                . Stored encrypted; never shown again.
              </>
            }
          >
            {(props) => (
              <input
                {...props}
                type="password"
                autoComplete="off"
                placeholder={credentialPlaceholder(integration, 'api_key', 'sk-ant-…')}
                value={form.api_key}
                onChange={(event) => set('api_key', event.target.value)}
              />
            )}
          </Field>
        </FormGrid>
      )}
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

function WhatsAppSection({ data, reload }: { data: Integrations; reload: () => void }) {
  const integration = data.whatsapp
  const url = webhookUrl()
  const local = /\/\/(localhost|127\.)/.test(url)
  return (
    <IntegrationCard
      integration={integration}
      fields={['phone_number_id', 'business_account_id', 'verify_token']}
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
          </FormGrid>
        </>
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
            <MessagesSection />
          </div>
        )}
      </AsyncBlock>
    </Page>
  )
}
