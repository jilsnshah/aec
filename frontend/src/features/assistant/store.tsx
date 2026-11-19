import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ai, type ActionBlock, type Attachment, type Block, type ChatMessage, type PageContext, type Step, type StreamEvent } from '@/api/ai'
import { errorText } from '@/api/client'
import { moduleFor } from '@/app/nav'

/** One assistant for the whole window: the floating panel and the Assistant
 *  page show the same conversation and share one stream. */

export interface Draft {
  id: string | null
  content: string
  steps: Step[]
  blocks: Block[]
  error: string | null
}

interface AssistantState {
  open: boolean
  setOpen: (open: boolean) => void
  conversationId: string | null
  select: (id: string | null) => void
  newChat: () => void
  messages: ChatMessage[]
  loading: boolean
  draft: Draft | null
  busy: boolean
  send: (text: string, attachments: Attachment[]) => Promise<void>
  ask: (text: string) => void
  confirm: (actionId: string) => Promise<void>
  cancel: (actionId: string) => Promise<void>
  stop: () => void
  context: PageContext
}

const Context = createContext<AssistantState | null>(null)

const RECORD_TYPES: Record<string, string> = {
  orders: 'sales order',
  enquiries: 'enquiry',
  customers: 'customer',
  'purchase-orders': 'purchase order',
  receipts: 'goods receipt',
  suppliers: 'supplier',
  products: 'product',
}

/** Where the user is, for the assistant: the module and any selected record. */
export function usePageContext(): PageContext {
  const location = useLocation()
  return useMemo(() => {
    const parts = location.pathname.split('/').filter(Boolean)
    const module = moduleFor(location.pathname)
    const type = RECORD_TYPES[parts[0] ?? '']
    const product = new URLSearchParams(location.search).get('product')
    const record = type && parts[1] ? { type, id: parts[1] } : product ? { type: 'product', id: product } : null
    return { path: location.pathname + location.search, title: module.label, record }
  }, [location.pathname, location.search])
}

export function AssistantProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient()
  const location = useLocation()
  const context = usePageContext()
  const [open, setOpen] = useState(false)
  const [conversationId, setConversationId] = useState<string | null>(() => {
    try {
      return localStorage.getItem('aec-chat')
    } catch {
      return null
    }
  })
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [draft, setDraft] = useState<Draft | null>(null)
  const [busy, setBusy] = useState(false)
  const abort = useRef<AbortController | null>(null)
  const queued = useRef<string | null>(null)

  const detail = useQuery({
    queryKey: ['ai', 'conversation', conversationId],
    queryFn: () => ai.conversation(conversationId as string),
    enabled: Boolean(conversationId),
    retry: false,
  })
  useEffect(() => {
    if (detail.data) setMessages(detail.data.messages)
  }, [detail.data])
  useEffect(() => {
    if (detail.isError) select(null)
  }, [detail.isError]) // eslint-disable-line react-hooks/exhaustive-deps

  const select = useCallback((id: string | null) => {
    abort.current?.abort()
    setConversationId(id)
    setMessages([])
    setDraft(null)
    setBusy(false)
    try {
      if (id) localStorage.setItem('aec-chat', id)
      else localStorage.removeItem('aec-chat')
    } catch {
      /* private window */
    }
  }, [])

  const handle = useCallback(
    (event: StreamEvent) => {
      switch (event.event) {
        case 'user_message':
          setMessages((list) => [...list.filter((m) => !m.id.startsWith('local-')), event.data])
          break
        case 'message_start':
          setDraft({ id: event.data.message_id, content: '', steps: [], blocks: [], error: null })
          break
        case 'token':
          setDraft((d) => (d ? { ...d, content: d.content + event.data.text } : d))
          break
        case 'tool_start':
          setDraft((d) => (d ? { ...d, steps: [...d.steps, { ...event.data, ok: undefined }], content: d.content && !d.content.endsWith('\n\n') ? d.content + '\n\n' : d.content } : d))
          break
        case 'tool_end':
          setDraft((d) => {
            if (!d) return d
            const steps = [...d.steps]
            const index = steps.map((s) => s.tool).lastIndexOf(event.data.tool)
            if (index >= 0 && steps[index].ok === undefined) steps[index] = event.data
            else steps.push(event.data)
            return { ...d, steps }
          })
          break
        case 'block':
          setDraft((d) => (d ? { ...d, blocks: [...d.blocks, event.data] } : d))
          break
        case 'action_update':
          setMessages((list) =>
            list.map((message) => ({
              ...message,
              blocks: message.blocks.map((block) =>
                block.type === 'action' && block.action_id === event.data.action_id
                  ? ({ ...block, status: event.data.status, error: event.data.error ?? block.error, result: event.data.result ?? block.result, link: event.data.link ?? block.link } as ActionBlock)
                  : block,
              ),
            })),
          )
          if (event.data.status === 'done') client.invalidateQueries({ predicate: (query) => query.queryKey[0] !== 'ai' })
          break
        case 'error':
          setDraft((d) => (d ? { ...d, error: event.data.message } : { id: null, content: '', steps: [], blocks: [], error: event.data.message }))
          break
        case 'message_end':
          setMessages((list) => [...list.filter((m) => m.id !== event.data.id), event.data])
          setDraft(null)
          break
      }
    },
    [client],
  )

  const finish = useCallback(() => {
    setBusy(false)
    client.invalidateQueries({ queryKey: ['ai', 'conversations'] })
    client.invalidateQueries({ queryKey: ['ai', 'conversation', conversationId] })
  }, [client, conversationId])

  const send = useCallback(
    async (text: string, attachments: Attachment[]) => {
      if (busy) return
      let id = conversationId
      setBusy(true)
      try {
        if (!id) {
          const created = await ai.create()
          id = created.id
          setConversationId(id)
          try {
            localStorage.setItem('aec-chat', id)
          } catch {
            /* private window */
          }
          client.setQueryData(['ai', 'conversation', id], { id, title: created.title, updated_at: created.updated_at, messages: [], pending_actions: [] })
        }
        setMessages((list) => [...list, { id: `local-${Date.now()}`, role: 'user', content: text, blocks: [], steps: [], attachments, context }])
        setDraft({ id: null, content: '', steps: [], blocks: [], error: null })
        abort.current = new AbortController()
        await ai.send(id, { text, attachments: attachments.map((a) => a.id), context }, handle, abort.current.signal)
      } catch (error) {
        setDraft((d) => ({ ...(d ?? { id: null, content: '', steps: [], blocks: [] }), error: errorText(error) }))
      } finally {
        setBusy(false)
        client.invalidateQueries({ queryKey: ['ai', 'conversations'] })
        if (id) client.invalidateQueries({ queryKey: ['ai', 'conversation', id] })
      }
    },
    [busy, conversationId, client, context, handle],
  )

  const confirm = useCallback(
    async (actionId: string) => {
      setBusy(true)
      try {
        abort.current = new AbortController()
        await ai.confirm(actionId, handle, abort.current.signal)
      } catch (error) {
        toast.error(errorText(error))
      } finally {
        finish()
        client.invalidateQueries({ predicate: (query) => query.queryKey[0] !== 'ai' })
      }
    },
    [handle, finish, client],
  )

  const cancel = useCallback(
    async (actionId: string) => {
      try {
        await ai.cancel(actionId)
        handle({ event: 'action_update', data: { action_id: actionId, status: 'cancelled' } })
      } catch (error) {
        toast.error(errorText(error))
      }
    },
    [handle],
  )

  const stop = useCallback(() => {
    abort.current?.abort()
    setBusy(false)
    setDraft((d) => (d ? { ...d, error: d.error ?? 'Stopped. The assistant may still finish in the background.' } : d))
  }, [])

  const newChat = useCallback(() => select(null), [select])

  // ask(): open the assistant with a prompt from anywhere (Insights, alerts…).
  const ask = useCallback(
    (text: string) => {
      if (!location.pathname.startsWith('/assistant')) setOpen(true)
      queued.current = text
      select(null)
    },
    [location.pathname, select],
  )
  useEffect(() => {
    if (queued.current && !conversationId && !busy) {
      const text = queued.current
      queued.current = null
      void send(text, [])
    }
  }, [conversationId, busy, send])

  const value = useMemo<AssistantState>(
    () => ({ open, setOpen, conversationId, select, newChat, messages, loading: detail.isFetching && !messages.length, draft, busy, send, ask, confirm, cancel, stop, context }),
    [open, conversationId, select, newChat, messages, detail.isFetching, draft, busy, send, ask, confirm, cancel, stop, context],
  )
  return <Context.Provider value={value}>{children}</Context.Provider>
}

export function useAssistant() {
  const value = useContext(Context)
  if (!value) throw new Error('useAssistant needs AssistantProvider')
  return value
}

export function useAiStatus() {
  return useQuery({ queryKey: ['ai', 'status'], queryFn: ai.status, staleTime: 30_000 })
}
