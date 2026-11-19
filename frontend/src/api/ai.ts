import { ApiError, SIGNED_OUT, http } from './client'

/** The assistant's API. Replies stream as Server-Sent Events over a POST, so
 *  they are read with fetch rather than EventSource. */

export type AiMode = 'live' | 'development' | 'not_configured'
export interface AiStatus {
  mode: AiMode
  assistant_enabled: boolean
  model: string
  credential_source: 'settings' | 'server' | null
  change_policy: 'confirm_all' | 'confirm_significant'
}
export interface Conversation {
  id: string
  title: string
  updated_at: string
  created_at?: string
  messages: number
}
export interface Attachment {
  id: string
  filename: string
  mime_type: string
  size: number
}
export interface Step {
  tool: string
  label: string
  args?: Record<string, unknown>
  kind?: 'read' | 'change' | 'analysis' | 'output'
  ok?: boolean
  error?: string | null
  dataset_id?: string
  rows?: number | null
  pending?: boolean
  auto?: boolean
  action_id?: string
}
export type ColumnKind = 'money' | 'number' | 'percent' | 'date' | 'text' | 'boolean'
export interface TableBlock {
  type: 'table'
  id: string
  title: string
  dataset_id: string
  columns: { key: string; label: string; kind: ColumnKind; link?: { id: string; route: string } | null }[]
  rows: Record<string, unknown>[]
  total_rows: number
}
export interface ChartBlock {
  type: 'chart'
  id: string
  chart: 'bar' | 'horizontal_bar' | 'stacked_bar' | 'line' | 'area' | 'pie'
  title: string
  x: { key: string; label: string }
  series: { key: string; label: string }[]
  unit: 'money' | 'number' | 'percent'
  rows: Record<string, unknown>[]
  total_rows: number
}
export interface FileBlock {
  type: 'file'
  id: string
  file_id: string
  filename: string
  mime_type: string
  size: number
  url: string
  format: string
}
export interface LinkBlock {
  type: 'link'
  id: string
  path: string
  label: string
}
export type ActionStatus = 'pending' | 'running' | 'done' | 'failed' | 'cancelled'
export interface ActionBlock {
  type: 'action'
  id: string
  action_id: string
  tool: string
  label: string
  risk: 'write' | 'financial' | 'destructive'
  summary: string
  details: { fields: { label: string; value: string }[]; lines: Record<string, string>[] }
  status: ActionStatus
  result?: string | null
  error?: string | null
  link?: { path: string; label: string } | null
}
export type Block = TableBlock | ChartBlock | FileBlock | LinkBlock | ActionBlock

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  blocks: Block[]
  steps: Step[]
  attachments: Attachment[]
  context?: PageContext | null
  error?: string | null
  created_at?: string | null
}
export interface PageContext {
  path: string
  title?: string
  record?: { type: string; id: string; label?: string } | null
}
export interface ConversationDetail {
  id: string
  title: string
  updated_at: string
  messages: ChatMessage[]
  pending_actions: string[]
}
export interface Capabilities {
  groups: Record<string, { name: string; label: string; risk: string; description: string }[]>
  tool_count: number
}

export type StreamEvent =
  | { event: 'user_message'; data: ChatMessage }
  | { event: 'message_start'; data: { message_id: string; mode: AiMode } }
  | { event: 'token'; data: { text: string } }
  | { event: 'tool_start'; data: Step }
  | { event: 'tool_end'; data: Step }
  | { event: 'block'; data: Block }
  | { event: 'action_update'; data: { action_id: string; status: ActionStatus; error?: string | null; result?: string | null; link?: ActionBlock['link'] } }
  | { event: 'error'; data: { message: string; message_id?: string } }
  | { event: 'message_end'; data: ChatMessage }
  | { event: 'idle'; data: { pending: number } }

async function stream(path: string, body: unknown, onEvent: (event: StreamEvent) => void, signal?: AbortSignal) {
  let response: Response
  try {
    response = await fetch(path, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify(body ?? {}),
      signal,
    })
  } catch (error) {
    if ((error as Error).name === 'AbortError') return
    throw new ApiError(0, 'The server could not be reached.')
  }
  if (response.status === 401) window.dispatchEvent(new Event(SIGNED_OUT))
  if (!response.ok || !response.body) {
    let message = `Request failed (${response.status}).`
    try {
      const payload = await response.json()
      message = payload?.message ?? (typeof payload?.detail === 'string' ? payload.detail : message)
    } catch {
      /* keep the generic message */
    }
    throw new ApiError(response.status, message)
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let index: number
    while ((index = buffer.indexOf('\n\n')) >= 0) {
      const chunk = buffer.slice(0, index)
      buffer = buffer.slice(index + 2)
      let event = ''
      let data = ''
      for (const line of chunk.split('\n')) {
        if (line.startsWith('event: ')) event = line.slice(7)
        else if (line.startsWith('data: ')) data += line.slice(6)
      }
      if (event && data) {
        try {
          onEvent({ event, data: JSON.parse(data) } as StreamEvent)
        } catch {
          /* ignore a malformed event */
        }
      }
    }
  }
}

export const ai = {
  status: () => http.get<AiStatus>('/api/ai/status'),
  models: () => http.get<{ id: string; label: string; hint: string; provider: string }[]>('/api/ai/models'),
  capabilities: () => http.get<Capabilities>('/api/ai/capabilities'),
  conversations: () => http.get<Conversation[]>('/api/ai/conversations'),
  conversation: (id: string) => http.get<ConversationDetail>(`/api/ai/conversations/${id}`),
  create: (title?: string) => http.post<Conversation>('/api/ai/conversations', { title }),
  rename: (id: string, title: string) => http.patch<Conversation>(`/api/ai/conversations/${id}`, { title }),
  remove: (id: string) => fetch(`/api/ai/conversations/${id}`, { method: 'DELETE', credentials: 'include' }),
  send: (id: string, body: { text: string; attachments: string[]; context?: PageContext | null }, onEvent: (e: StreamEvent) => void, signal?: AbortSignal) =>
    stream(`/api/ai/conversations/${id}/messages`, body, onEvent, signal),
  confirm: (actionId: string, onEvent: (e: StreamEvent) => void, signal?: AbortSignal) => stream(`/api/ai/actions/${actionId}/confirm`, {}, onEvent, signal),
  cancel: (actionId: string) => http.post<{ status: string }>(`/api/ai/actions/${actionId}/cancel`),
  upload: async (file: File, conversationId?: string): Promise<Attachment> => {
    const form = new FormData()
    form.append('file', file)
    if (conversationId) form.append('conversation_id', conversationId)
    const response = await fetch('/api/ai/files', { method: 'POST', body: form, credentials: 'include' })
    if (!response.ok) {
      let message = `Upload failed (${response.status}).`
      try {
        const payload = await response.json()
        message = payload?.message ?? message
      } catch {
        /* keep */
      }
      throw new ApiError(response.status, message)
    }
    return response.json()
  },
  activity: () =>
    http.get<{ id: string; user: string | null; tool: string; route: string | null; ok: boolean; status_code: number | null; error: string | null; duration_ms: number; created_at: string }[]>(
      '/api/ai/activity',
    ),
}
