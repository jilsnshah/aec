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

export const automation = {
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
}
