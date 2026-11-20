import { ApiError, http, request } from './client'

/** Marketing: campaigns, content, audiences, consent, channels, automations,
 *  analytics and the agents. */

export type Channel = 'instagram' | 'whatsapp'
export type CampaignStatus = 'draft' | 'review' | 'approved' | 'running' | 'completed' | 'paused' | 'cancelled'
export type ContentStatus = 'draft' | 'scheduled' | 'publishing' | 'published' | 'sending' | 'sent' | 'failed' | 'cancelled'

export interface Funnel {
  audience: number
  skipped: number
  failed: number
  queued: number
  sent: number
  delivered: number
  read: number
  replied: number
}
export interface Media {
  id: string
  url: string
  public_url: string | null
  width: number
  height: number
  size: number
  source: 'upload' | 'card' | 'ai'
  name: string | null
  prompt: string | null
  campaign_id: string | null
  created_at: string
}
export interface Content {
  id: string
  campaign_id: string
  channel: Channel
  caption: string | null
  hashtags: string[]
  template_name: string | null
  template_language: string | null
  variables: string[]
  media: Media | null
  scheduled_at: string | null
  status: ContentStatus
  ai_generated: boolean
  version: number
  attempts: number
  error: string | null
  external_id: string | null
  permalink: string | null
  published_at: string | null
  metrics: Record<string, number>
  synced_at: string | null
  preview?: { values: string[]; text: string; template: string | null; header: string | null; footer: string | null }
  campaign?: string
}
export interface AudienceDefinition {
  group_ids?: string[]
  rules?: { field: string; op: string; value: string | number }[]
  match?: 'all' | 'any'
  products?: { ids: string[]; mode: 'bought' | 'not_bought'; within_days?: number | null }
  categories?: { names: string[]; mode: 'bought' | 'not_bought'; within_days?: number | null }
  occasion?: { kind: 'birthday' | 'anniversary'; within_days: number }
  open_enquiry?: boolean
  only?: string[]
  include?: string[]
  exclude?: string[]
}
export interface Campaign {
  id: string
  code: string
  name: string
  objective: string
  objective_label: string
  status: CampaignStatus
  channels: Channel[]
  audience_id: string | null
  audience: AudienceDefinition
  product_ids: string[]
  offer: string | null
  brief: string | null
  starts_at: string | null
  ends_at: string | null
  budget: number | null
  spend: number | null
  created_by: string | null
  opportunity_id: string | null
  submitted_at: string | null
  approved_by: string | null
  approved_at: string | null
  completed_at: string | null
  notes: string | null
  created_at: string
  updated_at: string
  funnel: Funnel
  conversions: { orders: number; enquiries: number; revenue: number }
  cost: number
  roi: number | null
  instagram: Record<string, number>
  content_count: number
  next_at: string | null
  health: { level: 'ok' | 'warn' | 'bad' | 'muted'; label: string; why: string }
  // Full view only
  audience_summary?: string
  audience_count?: number
  audience_name?: string | null
  contents?: Content[]
  products?: { id: string; name: string; sku: string; unit: string; stock: number; mrp: number | null }[]
  checks?: { level: 'block' | 'warn'; text: string }[]
}
export interface Opportunity {
  id: string
  kind: string
  kind_label: string
  title: string
  why: string
  data: Record<string, unknown>
  product_ids: string[]
  products: string[]
  audience: AudienceDefinition
  audience_summary: string
  channels: Channel[]
  objective: string
  score: number
  value_estimate: number | null
  status: string
  source: string
  campaign_id: string | null
  created_at: string
}
export interface MarketingEvent {
  id: string
  at: string
  actor: string
  kind: string
  level: 'info' | 'success' | 'warning' | 'error'
  message: string
  data: Record<string, unknown>
  campaign_id: string | null
  campaign: string | null
}
export interface CalendarItem {
  id: string
  campaign_id: string
  campaign: string
  campaign_status: string
  channel: Channel
  status: ContentStatus
  at: string
  title: string
  thumb: string | null
}
export interface Insight {
  headline: string
  points: string[]
  recommendations: string[]
  at: string
}
export interface Dashboard {
  kpis: {
    revenue: number
    orders: number
    enquiries: number
    spend: number
    roi: number | null
    sent: number
    read: number
    replied: number
    reach: number
    engagement_rate: number | null
    active_campaigns: number
    waiting_approval: number
  }
  series: SeriesPoint[]
  channels: { channel: Channel; reach: number; engaged: number; replies: number; revenue: number | null }[]
  consent: { opted_in: number; opted_out: number; customers: number }
  campaigns: Campaign[]
  opportunities: Opportunity[]
  upcoming: CalendarItem[]
  connections: {
    instagram: { connected: boolean; username: string | null; error: string | null; quota: number; used: number }
    whatsapp: { connected: boolean; approved_templates: number }
  }
  comments_waiting: number
  problems: MarketingEvent[]
  insight: Insight | null
}
export interface SeriesPoint {
  day: string
  sent: number
  read: number
  revenue: number
  reach: number
}
export interface Analytics {
  days: number
  funnel: Funnel
  orders: number
  enquiries: number
  revenue: number
  spend: number
  roi: number | null
  instagram: Record<string, number | null>
  channels: Dashboard['channels']
  series: SeriesPoint[]
  best_hours: { hour: number; read_rate: number; sent: number }[]
  campaigns: (Funnel & { id: string; name: string; status: CampaignStatus; channels: Channel[]; objective: string; orders: number; enquiries: number; revenue: number; cost: number; roi: number | null; read_rate: number | null })[]
}
export interface Audience {
  id: string
  name: string
  description: string | null
  definition: AudienceDefinition
  summary: string
  is_active: boolean
  last_count: number | null
}
export interface AudiencePreview {
  count: number
  summary?: string
  reach: Record<string, { reachable: number; blocked: Record<string, number> }>
  sample: { customer_id: string; name: string; phone: string | null; segment: string | null; spend_12m: number | null; days_since_last_order: number | null; whatsapp_consent: boolean }[]
}
export interface RuleField {
  key: string
  label: string
  type: 'number' | 'choice'
  default: number | string
  choices?: string[]
}
export interface Rule {
  id: string
  name: string
  trigger: string
  trigger_label: string
  conditions: Record<string, number | string>
  action: string
  action_label: string
  action_config: { channels?: Channel[]; image?: 'card' | 'ai' | 'none'; offer?: string | null; audience_id?: string | null }
  approval: string
  cooldown_days: number
  is_active: boolean
  last_run_at: string | null
  last_result: string | null
  runs: number
}
export interface Template {
  id: string
  name: string
  language: string
  category: string
  status: string
  body: string
  header: string | null
  footer: string | null
  variable_count: number
  reason: string | null
  synced_at: string | null
}
export interface Comment {
  id: string
  username: string | null
  text: string
  commented_at: string | null
  reply_text: string | null
  reply_status: 'none' | 'draft' | 'sent' | 'failed'
  replied_at: string | null
  hidden: boolean
  intent: string | null
  post: { id: string; campaign_id: string; permalink: string | null; caption: string } | null
}
export interface ConsentRow {
  customer_id: string
  name: string
  phone: string | null
  email: string | null
  status: 'opted_in' | 'opted_out' | 'unknown'
  source: string | null
  evidence: string | null
  at: string | null
  by: string | null
  birthday: string | null
  anniversary: string | null
}
export interface Setting {
  name: string
  enabled: boolean
  config: Record<string, unknown>
  credentials: Record<string, { set: boolean; hint: string | null }>
}
export interface CampaignIn {
  name?: string
  objective?: string
  channels?: Channel[]
  audience_id?: string | null
  audience?: AudienceDefinition
  product_ids?: string[]
  offer?: string | null
  brief?: string | null
  starts_at?: string | null
  ends_at?: string | null
  budget?: number | null
  spend?: number | null
}
export interface ContentIn {
  channel?: Channel
  caption?: string | null
  hashtags?: string[]
  template_name?: string | null
  template_language?: string | null
  variables?: string[]
  media_id?: string | null
  scheduled_at?: string | null
}

const del = (path: string) => request<void>('DELETE', path)

async function upload(file: File, campaignId?: string): Promise<Media> {
  const form = new FormData()
  form.append('file', file)
  if (campaignId) form.append('campaign_id', campaignId)
  const response = await fetch('/api/marketing/media/upload', { method: 'POST', credentials: 'include', body: form })
  if (!response.ok) {
    let message = `Upload failed (${response.status}).`
    try {
      const body = await response.json()
      message = body?.message ?? body?.detail ?? message
    } catch {
      /* keep the generic message */
    }
    throw new ApiError(response.status, String(message))
  }
  return response.json()
}

const M = '/api/marketing'

export const marketing = {
  dashboard: () => http.get<Dashboard>(`${M}/dashboard`),
  opportunities: (status = 'new') => http.get<{ items: Opportunity[] }>(`${M}/opportunities`, { status }),
  scan: () => http.post<{ found: number; items: Opportunity[] }>(`${M}/opportunities/scan`),
  accept: ({ id, image = 'card' }: { id: string; image?: 'card' | 'ai' | 'none' }) => http.post<Campaign>(`${M}/opportunities/${id}/accept`, { image }),
  dismiss: (id: string) => http.post<Opportunity>(`${M}/opportunities/${id}/dismiss`),
  ask: (question: string) => http.post<{ answer: string; actions: { label: string; opportunity_id: string | null }[]; ai: boolean }>(`${M}/ask`, { question }),
  analyse: () => http.post<Insight>(`${M}/analyse`),
  events: (params: { campaign_id?: string; level?: string; limit?: number } = {}) => http.get<{ items: MarketingEvent[] }>(`${M}/events`, params),
  tick: () => http.post<{ published: number; broadcasts_started: number; sent: number }>(`${M}/tick`),

  campaigns: (params: { status?: string; channel?: string; objective?: string; q?: string } = {}) =>
    http.get<{ items: Campaign[]; objectives: Record<string, string> }>(`${M}/campaigns`, params),
  campaign: (id: string) => http.get<Campaign>(`${M}/campaigns/${id}`),
  create: (body: CampaignIn) => http.post<Campaign>(`${M}/campaigns`, body),
  update: ({ id, ...body }: CampaignIn & { id: string }) => http.put<Campaign>(`${M}/campaigns/${id}`, body),
  remove: (id: string) => del(`${M}/campaigns/${id}`),
  audienceOf: (id: string) => http.get<AudiencePreview>(`${M}/campaigns/${id}/audience`),
  generate: ({ id, ...body }: { id: string; channels?: Channel[]; instructions?: string; image?: 'card' | 'ai' | 'none' }) =>
    http.post<Campaign>(`${M}/campaigns/${id}/generate`, body),
  submit: (id: string) => http.post<Campaign>(`${M}/campaigns/${id}/submit`),
  approve: (id: string) => http.post<Campaign>(`${M}/campaigns/${id}/approve`),
  reject: ({ id, reason }: { id: string; reason?: string }) => http.post<Campaign>(`${M}/campaigns/${id}/reject`, { reason }),
  pause: (id: string) => http.post<Campaign>(`${M}/campaigns/${id}/pause`),
  cancel: (id: string) => http.post<Campaign>(`${M}/campaigns/${id}/cancel`),
  duplicate: (id: string) => http.post<Campaign>(`${M}/campaigns/${id}/duplicate`),
  sends: (id: string) => http.get<{ items: { id: string; customer_id: string; customer: string; to: string | null; status: string; skip_reason: string | null; error: string | null; sent_at: string | null; delivered_at: string | null; read_at: string | null; replied_at: string | null }[] }>(`${M}/campaigns/${id}/sends`),
  conversions: (id: string) => http.get<{ items: { id: string; customer: string | null; order_id: string | null; order_number: string | null; enquiry_id: string | null; value: number; why: string; at: string }[] }>(`${M}/campaigns/${id}/conversions`),

  addContent: ({ campaignId, ...body }: ContentIn & { campaignId: string }) => http.post<Content>(`${M}/campaigns/${campaignId}/contents`, body),
  updateContent: ({ id, ...body }: ContentIn & { id: string }) => http.put<Content>(`${M}/contents/${id}`, body),
  removeContent: (id: string) => del(`${M}/contents/${id}`),
  rewrite: ({ id, instructions }: { id: string; instructions: string }) => http.post<Content>(`${M}/contents/${id}/rewrite`, { instructions }),

  media: (campaignId?: string) => http.get<{ items: Media[] }>(`${M}/media`, { campaign_id: campaignId }),
  upload,
  card: (body: { headline: string; subline?: string; price?: string; badge?: string; points?: string[]; cta?: string; size?: string; campaign_id?: string; product_id?: string }) =>
    http.post<Media>(`${M}/media/card`, body),
  productCard: (body: { product_id: string; offer?: string; campaign_id?: string }) => http.post<Media>(`${M}/media/product-card`, body),
  image: (body: { prompt: string; campaign_id?: string }) => http.post<Media>(`${M}/media/generate`, body),

  audiences: () => http.get<{ items: Audience[]; fields: { key: string; label: string; unit?: string; type: string; choices?: string[] }[] }>(`${M}/audiences`),
  preview: (body: { definition: AudienceDefinition; channels?: Channel[] }) => http.post<AudiencePreview>(`${M}/audiences/preview`, body),
  saveAudience: ({ id, ...body }: { id?: string; name: string; description?: string | null; definition: AudienceDefinition }) =>
    id ? http.put<Audience>(`${M}/audiences/${id}`, body) : http.post<Audience>(`${M}/audiences`, body),
  removeAudience: (id: string) => del(`${M}/audiences/${id}`),

  consents: (params: { channel?: string; status?: string; q?: string } = {}) => http.get<{ items: ConsentRow[]; totals: Record<string, number> }>(`${M}/consents`, params),
  setConsent: (body: { customer_ids: string[]; channel?: string; status: 'opted_in' | 'opted_out'; source?: string; evidence?: string }) =>
    http.post<{ updated: number }>(`${M}/consents`, body),
  setOccasions: ({ id, ...body }: { id: string; birthday?: string; anniversary?: string }) => http.put<unknown>(`${M}/customers/${id}/occasions`, body),
  customer: (id: string) => http.get<{ consent: Record<string, { status: string; source: string; evidence: string | null; at: string; by: string | null }>; birthday: string | null; anniversary: string | null; messages: { campaign_id: string; campaign: string; status: string; skip_reason: string | null; sent_at: string | null; read_at: string | null; replied_at: string | null }[] }>(`${M}/customers/${id}`),

  calendar: (start: string, end: string) => http.get<{ items: CalendarItem[] }>(`${M}/calendar`, { start, end }),
  analytics: (days = 30) => http.get<Analytics>(`${M}/analytics`, { days }),

  settings: () => http.get<{ marketing: Setting; instagram: Setting; ai: boolean }>(`${M}/settings`),
  saveSettings: ({ name, ...body }: { name: 'marketing' | 'instagram'; enabled?: boolean; config?: Record<string, unknown>; credentials?: Record<string, string | null> }) =>
    http.put<Setting>(`/api/integrations/${name}`, body),
  instagramCheck: () => http.post<{ username: string; name: string; followers: number; quota: { total: number; used: number; left: number } }>(`${M}/instagram/check`),
  instagramSync: () => http.post<{ posts: number; comments: number }>(`${M}/instagram/sync`),
  posts: () => http.get<{ items: Content[] }>(`${M}/instagram/posts`),
  comments: (status?: string) => http.get<{ items: Comment[] }>(`${M}/instagram/comments`, { status }),
  reply: ({ id, text }: { id: string; text: string }) => http.post<Comment>(`${M}/instagram/comments/${id}/reply`, { text }),
  hide: ({ id, hidden }: { id: string; hidden: boolean }) => http.post<Comment>(`${M}/instagram/comments/${id}/hide`, { hidden }),

  templates: () => http.get<{ items: Template[] }>(`${M}/whatsapp/templates`),
  syncTemplates: () => http.post<{ synced: number }>(`${M}/whatsapp/templates/sync`),
  createTemplate: (body: { name: string; body: string; examples: string[]; language?: string; footer?: string; header_text?: string }) =>
    http.post<Template>(`${M}/whatsapp/templates`, body),
  suggestTemplate: (purpose: string) => http.post<{ name: string; body: string; examples: string[]; footer: string; note?: string }>(`${M}/whatsapp/templates/suggest`, { purpose }),

  rules: () => http.get<{ items: Rule[]; triggers: { key: string; label: string; fields: RuleField[]; per_customer: boolean }[]; actions: { key: string; label: string }[] }>(`${M}/rules`),
  saveRule: ({ id, ...body }: Partial<Rule> & { id?: string }) => (id ? http.put<Rule>(`${M}/rules/${id}`, body) : http.post<Rule>(`${M}/rules`, body)),
  removeRule: (id: string) => del(`${M}/rules/${id}`),
  runRule: (id: string) => http.post<{ rule: string; done: string[] }>(`${M}/rules/${id}/run`),
}

export const STATUS_LABEL: Record<CampaignStatus, { label: string; tone: 'muted' | 'sky' | 'ok' | 'warn' | 'bad' | 'steel' }> = {
  draft: { label: 'Draft', tone: 'muted' },
  review: { label: 'Waiting approval', tone: 'warn' },
  approved: { label: 'Scheduled', tone: 'sky' },
  running: { label: 'Live', tone: 'ok' },
  completed: { label: 'Completed', tone: 'steel' },
  paused: { label: 'Paused', tone: 'warn' },
  cancelled: { label: 'Cancelled', tone: 'muted' },
}
export const CONTENT_LABEL: Record<ContentStatus, string> = {
  draft: 'Draft',
  scheduled: 'Scheduled',
  publishing: 'Publishing…',
  published: 'Posted',
  sending: 'Sending…',
  sent: 'Sent',
  failed: 'Failed',
  cancelled: 'Cancelled',
}
