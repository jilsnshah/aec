import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'motion/react'
import { History, Maximize2, MessageSquarePlus, Pencil, Sparkles, Trash2, X } from 'lucide-react'
import { ai } from '@/api/ai'
import { cn } from '@/lib/cn'
import { fmtAgo } from '@/lib/format'
import { Button, Empty, Tip } from '@/ui/core'
import { Menu, useConfirm } from '@/ui/overlays'
import { Chat, useModelName } from './Chat'
import { useAiStatus, useAssistant } from './store'

/* ---------------------------------------------------------------- floating */

/** The bottom-right button and the chat panel it opens, on every page except
 *  the Assistant page itself. ⌘J toggles it. */
export function AssistantDock() {
  const { open, setOpen, newChat, conversationId, select } = useAssistant()
  const location = useLocation()
  const navigate = useNavigate()
  const status = useAiStatus()
  const modelName = useModelName()
  const list = useQuery({ queryKey: ['ai', 'conversations'], queryFn: ai.conversations, enabled: open })
  if (location.pathname.startsWith('/assistant')) return null
  return (
    <>
      <AnimatePresence>
        {open ? (
          <motion.section
            initial={{ opacity: 0, y: 24, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 24, scale: 0.97 }}
            transition={{ type: 'spring', stiffness: 380, damping: 32 }}
            className="pane fixed right-5 bottom-24 z-[90] flex h-[min(720px,calc(100vh-140px))] w-[min(460px,calc(100vw-24px))] origin-bottom-right flex-col overflow-hidden shadow-float max-md:right-3 max-md:bottom-20"
            aria-label="Assistant"
          >
            <header className="flex h-14 shrink-0 items-center gap-2 border-b border-white/7 px-3">
              <span className="icon-tile size-8 rounded-[11px]!">
                <Sparkles size={15} />
              </span>
              <div className="min-w-0 flex-1 leading-tight">
                <div className="text-[13.5px] font-semibold">Assistant</div>
                <div className="truncate text-[11px] text-fg-3">
                  {status.data?.mode === 'live' ? modelName : status.data?.mode === 'development' ? 'Development mode' : 'Not connected'}
                </div>
              </div>
              <Menu
                trigger={
                  <Button kind="ghost" small iconOnly aria-label="Conversations">
                    <History size={15} />
                  </Button>
                }
                items={
                  (list.data ?? []).length
                    ? (list.data ?? []).slice(0, 12).map((item) => ({ label: item.title, hint: fmtAgo(item.updated_at), onSelect: () => select(item.id) }))
                    : [{ label: 'No earlier chats', onSelect: () => undefined, disabled: true }]
                }
              />
              <Tip label="New chat">
                <Button kind="ghost" small iconOnly aria-label="New chat" onClick={newChat} disabled={!conversationId}>
                  <MessageSquarePlus size={15} />
                </Button>
              </Tip>
              <Tip label="Open full screen">
                <Button kind="ghost" small iconOnly aria-label="Open full screen" onClick={() => { setOpen(false); navigate(conversationId ? `/assistant/${conversationId}` : '/assistant') }}>
                  <Maximize2 size={14} />
                </Button>
              </Tip>
              <Button kind="ghost" small iconOnly aria-label="Close assistant" onClick={() => setOpen(false)}>
                <X size={15} />
              </Button>
            </header>
            <Chat compact />
          </motion.section>
        ) : null}
      </AnimatePresence>
      <motion.button
        onClick={() => setOpen(!open)}
        whileHover={{ scale: 1.05 }}
        whileTap={{ scale: 0.95 }}
        className="fixed right-5 bottom-5 z-[91] grid size-14 place-items-center rounded-full text-on-brand shadow-float max-md:right-3 max-md:bottom-3 max-md:size-12"
        style={{ background: 'var(--c-brand)' }}
        aria-label={open ? 'Close assistant' : 'Open assistant'}
        aria-expanded={open}
      >
        <span className="pointer-events-none absolute inset-0 rounded-full ring-4 ring-blue/25" />
        <AnimatePresence mode="wait" initial={false}>
          <motion.span key={open ? 'x' : 's'} initial={{ rotate: -90, opacity: 0 }} animate={{ rotate: 0, opacity: 1 }} exit={{ rotate: 90, opacity: 0 }} transition={{ duration: 0.18 }}>
            {open ? <X size={22} /> : <Sparkles size={22} />}
          </motion.span>
        </AnimatePresence>
      </motion.button>
    </>
  )
}

/* ---------------------------------------------------------------- full page */

export function AssistantPage() {
  const { conversationId, select, newChat, setOpen } = useAssistant()
  const { id } = useParams()
  const navigate = useNavigate()
  // The URL names the conversation; the shared store follows it.
  useEffect(() => {
    setOpen(false)
    if (id && id !== conversationId) select(id)
  }, [id]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (conversationId && conversationId !== id) navigate(`/assistant/${conversationId}`, { replace: true })
    if (!conversationId && id) navigate('/assistant', { replace: true })
  }, [conversationId]) // eslint-disable-line react-hooks/exhaustive-deps
  const client = useQueryClient()
  const list = useQuery({ queryKey: ['ai', 'conversations'], queryFn: ai.conversations })
  const confirm = useConfirm()
  const [renaming, setRenaming] = useState<string | null>(null)
  const [name, setName] = useState('')

  async function remove(id: string) {
    const answer = await confirm.ask({ title: 'Delete this chat?', body: 'Its messages and generated reports are removed. Changes already made in the app stay.', confirm: 'Delete', danger: true })
    if (!answer.ok) return
    await ai.remove(id)
    if (id === conversationId) newChat()
    client.invalidateQueries({ queryKey: ['ai', 'conversations'] })
  }

  return (
    <div className="flex h-full min-h-0 gap-4 px-6 pt-1 pb-5 max-lg:flex-col max-md:gap-2 max-md:p-2">
      <aside className="pane flex w-[290px] shrink-0 flex-col overflow-hidden max-lg:max-h-[200px] max-lg:w-full">
        <div className="flex items-center gap-2.5 px-4 pt-4 pb-3">
          <span className="icon-tile size-9">
            <Sparkles size={17} />
          </span>
          <div className="min-w-0 flex-1">
            <h1 className="text-[17px] font-semibold tracking-[-0.02em]">Assistant</h1>
            <p className="text-[11.5px] text-fg-3">Ask, analyse, report, act</p>
          </div>
        </div>
        <div className="px-3 pb-2">
          <Button kind="primary" className="w-full" icon={<MessageSquarePlus size={15} />} onClick={newChat}>
            New chat
          </Button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
          {list.data?.length === 0 ? <Empty title="No chats yet" body="Your conversations appear here." /> : null}
          {(list.data ?? []).map((item) => (
            <div key={item.id} className={cn('group relative flex items-center rounded-[14px] transition-colors', item.id === conversationId ? 'bg-peri/[0.17]' : 'hover:bg-white/[0.04]')}>
              {renaming === item.id ? (
                <form
                  className="flex-1 p-1.5"
                  onSubmit={async (event) => {
                    event.preventDefault()
                    if (name.trim()) await ai.rename(item.id, name.trim())
                    setRenaming(null)
                    client.invalidateQueries({ queryKey: ['ai'] })
                  }}
                >
                  <input autoFocus className="field field-sm" value={name} onChange={(e) => setName(e.target.value)} onBlur={() => setRenaming(null)} />
                </form>
              ) : (
                <Link to={`/assistant/${item.id}`} onClick={() => select(item.id)} className="min-w-0 flex-1 px-3 py-2.5">
                  <div className="truncate text-[13px] font-medium">{item.title}</div>
                  <div className="text-[11px] text-fg-3">{fmtAgo(item.updated_at)}</div>
                </Link>
              )}
              {renaming !== item.id ? (
                <div className="absolute right-1.5 hidden gap-0.5 group-hover:flex">
                  <Button kind="ghost" small iconOnly aria-label="Rename" onClick={() => { setRenaming(item.id); setName(item.title) }}>
                    <Pencil size={12} />
                  </Button>
                  <Button kind="ghost" small iconOnly aria-label="Delete" onClick={() => void remove(item.id)}>
                    <Trash2 size={12} />
                  </Button>
                </div>
              ) : null}
            </div>
          ))}
        </div>
      </aside>
      <section className="pane flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        <Chat />
      </section>
      {confirm.element}
    </div>
  )
}
