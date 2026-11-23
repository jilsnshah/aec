import { http } from './client'

/** Automation flows (Settings -> Automation), approvals and the outbox. */

export type Actor = 'system' | 'person' | 'tai' | 'pai'
export type Mode = 'auto' | 'limits' | 'approval' | 'off'
export type Category = 'trigger' | 'communicate' | 'decide' | 'record' | 'person'

export interface StepType {
  key: string
  flow: 'sales' | 'purchase'
  label: string
  category: Category
  actors: Actor[]
  default_actor: Actor
  live: boolean
  description: string
  limit_fields: string[]
  ai: boolean
  channels: string[]
  timing: Record<string, unknown> | null
  modes: Mode[]
  config_fields: ConfigField[]
  /** The agent that carries out this step (null for system and people steps). */
  agent?: string | null
  agent_label?: string | null
}
export interface ConfigField {
  key: string
  label: string
  type: 'number' | 'text' | 'textarea' | 'select' | 'multiselect' | 'toggle' | 'time' | 'days' | 'group' | 'section'
  default?: unknown
  options?: [string, string][]
  source?: 'categories' | 'suppliers' | 'customer_groups' | 'segments' | 'warehouses'
  unit?: string
  help?: string
  fields?: ConfigField[]
}
export interface Limit {
  field: string
  op: string
  value: string | number
}
export interface StepData {
  step: string
  title: string
  actors: Actor[]
  mode: Mode
  limits: Limit[]
  ai: { model: string; instructions: string } | null
  channels: string[]
  timing: Record<string, unknown> | null
  config?: Record<string, unknown> | null
  notes: string
  [key: string]: unknown
}
export interface FlowNode {
  id: string
  type: 'step'
  position: { x: number; y: number }
  data: StepData
}
export interface FlowEdge {
  id: string
  source: string
  target: string
  label?: string | null
}
export interface Flow {
  key: 'sales' | 'purchase'
  name: string
  nodes: FlowNode[]
  edges: FlowEdge[]
  updated_at: string | null
  updated_by: string | null
  customised: boolean
}
export interface Library {
  steps: StepType[]
  actors: Actor[]
  modes: Mode[]
  limit_fields: Record<string, { label: string; unit?: string; choices?: string[] }>
}
export interface Outbound {
  id: string
  channel: string
  to: string
  subject: string | null
  body: string
  status: string
  error: string | null
  author: string
  created_at: string
  sent_at: string | null
}
export interface HeldOrder {
  id: string
  customer_id: string
  customer: string
  channel: string
  sender: string
  items: { product_id: string; quantity: number; discount_percent: number }[]
  total: number
  note: string | null
  created_at: string
}

export interface ActivityRow {
  id: string
  step: string
  kind: string
  status: string
  summary: string | null
  party_type: string | null
  party_id: string | null
  subject_type: string | null
  subject_id: string | null
  created_at: string
}
export interface AgentProfile {
  key: string
  label: string
  name: string
  voice: string | null
  instructions: string
  job: string
  mediums: ('text' | 'phone')[]
  parked: boolean
  steps: { key: string; label: string }[]
}
export interface AgentCatalogue {
  agents: AgentProfile[]
  others: { key: string; label: string; job: string }[]
  voices: string[]
}

export const automation = {
  agents: () => http.get<AgentCatalogue>('/api/automation/agents'),
  saveAgents: (profiles: Record<string, { name: string; voice: string; instructions: string }>) => http.put<AgentCatalogue>('/api/automation/agents', { profiles }),
  library: () => http.get<Library>('/api/automation/library'),
  flow: (key: string) => http.get<Flow>(`/api/automation/flows/${key}`),
  save: ({ key, nodes, edges }: { key: string; nodes: FlowNode[]; edges: FlowEdge[] }) => http.put<Flow>(`/api/automation/flows/${key}`, { nodes, edges }),
  reset: (key: string) => http.post<Flow>(`/api/automation/flows/${key}/reset`),
  approvals: () => http.get<{ messages: Outbound[]; failed: Outbound[]; orders: HeldOrder[] }>('/api/automation/approvals'),
  messages: () => http.get<{ items: Outbound[] }>('/api/automation/messages'),
  approve: ({ id, body }: { id: string; body?: string }) => http.post<Outbound>(`/api/automation/messages/${id}/approve`, { body }),
  discard: (id: string) => http.post<Outbound>(`/api/automation/messages/${id}/discard`),
  placeDraft: (id: string) => http.post<{ order_number: string }>(`/api/automation/drafts/${id}/place`),
  discardDraft: (id: string) => http.post<{ ok: boolean }>(`/api/automation/drafts/${id}/discard`),
  run: (what: string) => http.post<Record<string, unknown>>(`/api/automation/run/${what}`),
  preview: (what: 'purchase' | 'outreach') => http.get<{ items: Record<string, unknown>[] }>(`/api/automation/preview/${what}`),
  activity: (step?: string) => http.get<{ items: ActivityRow[] }>('/api/automation/activity', { step }),
  feedback: () => http.get<{ average: number | null; complaints: number; items: { id: string; customer: string; customer_id: string; rating: number | null; comment: string | null; complaint: boolean; task_id: string | null; created_at: string }[] }>('/api/automation/feedback'),
}
