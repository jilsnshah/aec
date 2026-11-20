import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { EyeOff, Instagram, MessageCircle, MessagesSquare, Plug, RefreshCw, Send, ShieldAlert } from 'lucide-react'
import { marketing, type Comment } from '@/api/marketing'
import { useAction } from '@/api/queries'
import { fmtAgo, fmtDateTime } from '@/lib/format'
import { Badge, Button, Empty, Field, Notice, Spinner, Toggle } from '@/ui/core'
import { Segmented } from '@/ui/overlays'
import { Page, Panel } from './shared'

export function Channels() {
  const [params, setParams] = useSearchParams()
  const tab = (params.get('tab') as 'instagram' | 'comments' | 'whatsapp') ?? 'instagram'
  const comments = useQuery({ queryKey: ['marketing', 'comments', 'open'], queryFn: () => marketing.comments('open') })
  return (
    <Page className="space-y-3">
      <Segmented
        className="w-fit"
        value={tab}
        onChange={(v) => setParams({ tab: v })}
        options={[
          { value: 'instagram', label: 'Instagram' },
          { value: 'comments', label: 'Comments', count: comments.data?.items.length || undefined },
          { value: 'whatsapp', label: 'WhatsApp' },
        ]}
      />
      {tab === 'instagram' ? <InstagramTab /> : tab === 'comments' ? <CommentsTab /> : <WhatsAppTab />}
    </Page>
  )
}

function InstagramTab() {
  const settings = useQuery({ queryKey: ['marketing', 'settings'], queryFn: marketing.settings })
  const posts = useQuery({ queryKey: ['marketing', 'posts'], queryFn: marketing.posts })
  const [form, setForm] = useState({ ig_user_id: '', api_host: 'graph.facebook.com', token: '' })
  const ig = settings.data?.instagram
  useEffect(() => {
    if (ig) setForm({ ig_user_id: String(ig.config.ig_user_id ?? ''), api_host: String(ig.config.api_host ?? 'graph.facebook.com'), token: '' })
  }, [ig?.config.ig_user_id, ig?.config.api_host]) // eslint-disable-line react-hooks/exhaustive-deps
  const save = useAction(marketing.saveSettings, { success: 'Saved' })
  const check = useAction(marketing.instagramCheck, { success: (r) => `Connected as @${r.username} · ${r.quota.left} posts left today` })
  const sync = useAction(marketing.instagramSync, { success: (r) => `Updated ${r.posts} posts · ${r.comments} new comments` })
  if (settings.isPending) return <Spinner />
  const connected = Boolean(ig?.enabled && ig.credentials.access_token?.set)
  const error = String(ig?.config.last_error || '')
  const items = posts.data?.items ?? []
  return (
    <div className="grid gap-3 xl:grid-cols-[420px_1fr]">
      <Panel title="Connection" icon={Plug}>
        {connected && !error ? (
          <Notice tone="ok">
            Connected{ig?.config.username ? ` as @${String(ig.config.username)}` : ''}
            {ig?.config.followers ? ` · ${Number(ig.config.followers).toLocaleString('en-IN')} followers` : ''}
            {ig?.config.publish_quota ? ` · ${Number(ig.config.publish_used)}/${Number(ig.config.publish_quota)} posts used today` : ''}
          </Notice>
        ) : error ? (
          <Notice tone="bad">{error}</Notice>
        ) : (
          <Notice tone="sky">Use an Instagram Business or Creator account linked to a Facebook Page. In Meta’s developer app, give the token instagram_basic, instagram_content_publish, instagram_manage_comments and instagram_manage_insights.</Notice>
        )}
        <div className="mt-3 space-y-3">
          <Field label="Instagram account ID" hint="The numeric IG user id (Graph API Explorer: me/accounts → instagram_business_account).">
            {(props) => <input {...props} className="field" value={form.ig_user_id} onChange={(e) => setForm((f) => ({ ...f, ig_user_id: e.target.value }))} placeholder="17841400000000000" />}
          </Field>
          <Field label="Login type">
            {() => (
              <Segmented
                value={form.api_host}
                onChange={(api_host) => setForm((f) => ({ ...f, api_host }))}
                options={[
                  { value: 'graph.facebook.com', label: 'Facebook Login' },
                  { value: 'graph.instagram.com', label: 'Instagram Login' },
                ]}
              />
            )}
          </Field>
          <Field label="Access token" hint={ig?.credentials.access_token?.set ? `Saved (${ig.credentials.access_token.hint}). Leave empty to keep it.` : 'A long-lived token. It is stored encrypted and never shown again.'}>
            {(props) => <input {...props} type="password" autoComplete="off" className="field" value={form.token} onChange={(e) => setForm((f) => ({ ...f, token: e.target.value }))} />}
          </Field>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              kind="primary"
              busy={save.isPending}
              onClick={() =>
                save.mutate(
                  { name: 'instagram', enabled: true, config: { ig_user_id: form.ig_user_id, api_host: form.api_host }, credentials: form.token ? { access_token: form.token } : undefined },
                  { onSuccess: () => check.mutate() },
                )
              }
            >
              Save and check
            </Button>
            {connected ? (
              <>
                <Button icon={<RefreshCw size={13} />} busy={check.isPending} onClick={() => check.mutate()}>
                  Check
                </Button>
                <Toggle checked={Boolean(ig?.enabled)} onChange={(enabled) => save.mutate({ name: 'instagram', enabled })} label="Publishing on" />
              </>
            ) : null}
          </div>
        </div>
      </Panel>
      <Panel
        title="Posts"
        icon={Instagram}
        actions={
          connected ? (
            <Button small icon={<RefreshCw size={13} />} busy={sync.isPending} onClick={() => sync.mutate()}>
              Update numbers
            </Button>
          ) : undefined
        }
      >
        {items.length ? (
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 2xl:grid-cols-4">
            {items.map((p) => (
              <div key={p.id} className="overflow-hidden rounded-[12px] border border-white/7">
                {p.media ? <img src={p.media.url} alt="" className="aspect-[4/5] w-full object-cover" loading="lazy" /> : <div className="aspect-[4/5] bg-white/5" />}
                <div className="space-y-0.5 p-2.5 text-[12px]">
                  <div className="flex items-center gap-1.5">
                    <Badge tone={p.status === 'published' ? 'ok' : p.status === 'failed' ? 'bad' : 'sky'}>{p.status}</Badge>
                    <span className="truncate text-fg-3">{p.campaign}</span>
                  </div>
                  {p.status === 'published' ? (
                    <div className="num font-semibold">
                      {(p.metrics.reach ?? 0).toLocaleString('en-IN')} reached · {p.metrics.likes ?? 0} ♥ · {p.metrics.comments ?? 0} 💬
                    </div>
                  ) : null}
                  <div className="text-fg-3">{fmtDateTime(p.published_at || p.scheduled_at)}</div>
                  {p.permalink ? (
                    <a href={p.permalink} target="_blank" rel="noreferrer" className="font-medium text-sky">
                      Open
                    </a>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <Empty icon={<Instagram size={20} />} title="No posts yet" body="Posts made in campaigns appear here with their reach, likes and comments." />
        )}
      </Panel>
    </div>
  )
}

const INTENT: Record<string, { label: string; tone: 'sky' | 'ok' | 'warn' | 'bad' | 'muted' }> = {
  buying: { label: 'Wants to buy', tone: 'ok' },
  question: { label: 'Question', tone: 'sky' },
  praise: { label: 'Praise', tone: 'muted' },
  complaint: { label: 'Complaint', tone: 'bad' },
  spam: { label: 'Spam', tone: 'warn' },
  other: { label: 'Comment', tone: 'muted' },
}

function CommentsTab() {
  const [show, setShow] = useState<'open' | 'all'>('open')
  const data = useQuery({ queryKey: ['marketing', 'comments', show], queryFn: () => marketing.comments(show === 'open' ? 'open' : undefined) })
  if (data.isPending) return <Spinner />
  const items = data.data?.items ?? []
  return (
    <Panel
      title="Instagram comments"
      icon={MessagesSquare}
      actions={
        <Segmented
          value={show}
          onChange={setShow}
          options={[
            { value: 'open', label: 'Waiting' },
            { value: 'all', label: 'All' },
          ]}
        />
      }
    >
      <p className="mb-3 text-[12.5px] text-fg-3">The Engagement agent sorts comments and drafts replies. Nothing is posted until you press Reply. People who want to buy are pointed to WhatsApp, where TAI takes the enquiry.</p>
      {items.length ? (
        <div className="divide-y divide-white/6">
          {items.map((c) => (
            <CommentRow key={c.id} c={c} />
          ))}
        </div>
      ) : (
        <Empty icon={<MessagesSquare size={20} />} title="No comments waiting" />
      )}
    </Panel>
  )
}

function CommentRow({ c }: { c: Comment }) {
  const [text, setText] = useState(c.reply_text ?? '')
  const reply = useAction(marketing.reply, { success: 'Reply posted' })
  const hide = useAction(marketing.hide, { success: (r) => (r.hidden ? 'Hidden from the post' : 'Shown again') })
  const intent = INTENT[c.intent ?? 'other'] ?? INTENT.other
  return (
    <div className="grid gap-3 py-3 md:grid-cols-[1fr_1fr]">
      <div>
        <div className="flex items-center gap-2 text-[12.5px]">
          <span className="font-semibold">@{c.username ?? 'someone'}</span>
          <Badge tone={intent.tone}>{intent.label}</Badge>
          {c.hidden ? <Badge>Hidden</Badge> : null}
          <span className="text-fg-3">{fmtAgo(c.commented_at)}</span>
        </div>
        <p className="mt-1 text-[13.5px]">{c.text}</p>
        {c.post ? <p className="mt-1 truncate text-[11.5px] text-fg-3">On: {c.post.caption || 'a post'}</p> : null}
      </div>
      <div className="space-y-1.5">
        {c.reply_status === 'sent' ? (
          <p className="rounded-[10px] bg-white/5 p-2.5 text-[13px]">
            <span className="font-semibold">You:</span> {c.reply_text} <span className="text-[11.5px] text-fg-3">· {fmtAgo(c.replied_at)}</span>
          </p>
        ) : (
          <>
            <textarea className="field min-h-[64px]" value={text} onChange={(e) => setText(e.target.value)} placeholder="Write a reply…" aria-label="Reply" />
            <div className="flex gap-2">
              <Button small kind="primary" icon={<Send size={12} />} busy={reply.isPending} disabled={!text.trim()} onClick={() => reply.mutate({ id: c.id, text })}>
                Reply
              </Button>
              <Button small icon={<EyeOff size={12} />} busy={hide.isPending} onClick={() => hide.mutate({ id: c.id, hidden: !c.hidden })}>
                {c.hidden ? 'Show' : 'Hide'}
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function WhatsAppTab() {
  const navigate = useNavigate()
  const templates = useQuery({ queryKey: ['marketing', 'templates'], queryFn: marketing.templates })
  const home = useQuery({ queryKey: ['marketing', 'dashboard'], queryFn: marketing.dashboard })
  const sync = useAction(marketing.syncTemplates, { success: (r) => `Synced ${r.synced} templates from Meta` })
  const items = templates.data?.items ?? []
  const wa = home.data?.connections.whatsapp
  return (
    <div className="grid gap-3 xl:grid-cols-[380px_1fr]">
      <Panel title="Connection" icon={MessageCircle}>
        {wa?.connected ? (
          <Notice tone="ok">WhatsApp Cloud API is connected. The same number TAI answers on sends the broadcasts.</Notice>
        ) : (
          <Notice tone="warn">Connect WhatsApp in Settings → WhatsApp (phone number ID, business account ID and access token).</Notice>
        )}
        <ul className="mt-3 space-y-2 text-[12.5px] text-fg-2">
          <li className="flex gap-2">
            <ShieldAlert size={14} className="mt-0.5 shrink-0" /> Offers go only to customers who agreed (Audiences → Consent), at most the number per week set in Settings, never at night.
          </li>
          <li className="flex gap-2">
            <ShieldAlert size={14} className="mt-0.5 shrink-0" /> Meta limits how many offers one person gets from all businesses; messages it holds back are shown as “not delivered” and are not retried.
          </li>
          <li className="flex gap-2">
            <ShieldAlert size={14} className="mt-0.5 shrink-0" /> Replying STOP opts the customer out at once; they get a confirmation.
          </li>
        </ul>
        <Button className="mt-3" onClick={() => navigate('/integrations/whatsapp')}>
          WhatsApp settings
        </Button>
      </Panel>
      <Panel
        title="Templates"
        icon={MessagesSquare}
        actions={
          <>
            <Button small icon={<RefreshCw size={13} />} busy={sync.isPending} onClick={() => sync.mutate()}>
              Sync from Meta
            </Button>
            <Button small kind="primary" onClick={() => navigate('/marketing/studio')}>
              New template
            </Button>
          </>
        }
      >
        {templates.isPending ? (
          <Spinner />
        ) : items.length ? (
          <div className="overflow-x-auto">
            <table className="grid-table min-w-[640px]">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Kind</th>
                  <th>Status</th>
                  <th>Message</th>
                </tr>
              </thead>
              <tbody>
                {items.map((t) => (
                  <tr key={t.id}>
                    <td className="font-medium">
                      {t.name} <span className="text-[11px] text-fg-3">{t.language}</span>
                    </td>
                    <td>{t.category.toLowerCase()}</td>
                    <td>
                      <Badge tone={t.status === 'APPROVED' ? 'ok' : t.status === 'REJECTED' ? 'bad' : 'warn'}>{t.status.toLowerCase()}</Badge>
                      {t.reason ? <div className="text-[11px] text-fg-3">{t.reason}</div> : null}
                    </td>
                    <td className="max-w-[420px] text-[12px] text-fg-2">
                      {t.header === 'IMAGE' ? <Badge>image</Badge> : null} {t.body}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty icon={<MessagesSquare size={20} />} title="No templates synced" body="Sync to read the templates on your WhatsApp Business account, or create a marketing template in AI Studio." />
        )}
      </Panel>
    </div>
  )
}
