import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'motion/react'
import { ArrowUp, FileText, Image as ImageIcon, KeyRound, Loader2, Paperclip, Sheet, Sparkles, Square, X } from 'lucide-react'
import { ai, type Attachment, type ChatMessage } from '@/api/ai'
import { errorText } from '@/api/client'
import { cn } from '@/lib/cn'
import { Avatar } from '@/ui/core'
import { useAuth } from '@/app/auth'
import { BlockView, Markdown, Steps } from './blocks'
import { useAiStatus, useAssistant, type Draft } from './store'

const STARTERS = [
  { title: 'How is the business doing?', prompt: 'Give me a complete overview of how the business is performing this month compared with last month, and what I should act on.' },
  { title: 'What should I reorder?', prompt: 'Which products should we reorder now, how much, and roughly what will it cost? Show it as a table.' },
  { title: 'Which enquiries need attention?', prompt: 'Which open enquiries should we prioritise today, and which have gone without a follow-up?' },
  { title: 'Stock that is a liability', prompt: 'Which inventory items are becoming a liability — slow, dead or tying up capital — and what should we do about them?' },
  { title: 'Top customers', prompt: 'Who are our highest-value customers, and has anyone important gone quiet? Chart it.' },
  { title: 'Pending orders report', prompt: 'Generate a PDF report of all pending orders with what is ready, on order and short.' },
]

export function Chat({ compact = false }: { compact?: boolean }) {
  const { messages, draft, busy, send, confirm, cancel, stop, loading, conversationId, context } = useAssistant()
  const status = useAiStatus()
  const scroller = useRef<HTMLDivElement>(null)
  const pinned = useRef(true)

  useEffect(() => {
    const el = scroller.current
    if (el && pinned.current) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  }, [messages, draft])

  const mode = status.data?.mode
  const empty = !messages.length && !draft && !loading
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {mode === 'development' ? (
        <div className="mx-3 mt-2 rounded-xl bg-peri/25 px-3 py-2 text-[12px]">
          <b>Development mode.</b> No Gemini key is connected; replies are scripted and run real tools. <Link to="/integrations/ai" className="underline">Connect Gemini</Link>
        </div>
      ) : null}
      <div
        ref={scroller}
        onScroll={(event) => {
          const el = event.currentTarget
          pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
        }}
        className={cn('min-h-0 flex-1 overflow-y-auto', compact ? 'px-3 py-3' : 'px-6 py-6')}
      >
        <div className={cn('mx-auto flex flex-col gap-5', compact ? 'max-w-none' : 'max-w-[860px]')}>
          {mode === 'not_configured' && empty ? (
            <NotConnected />
          ) : empty ? (
            <Welcome compact={compact} onPick={(prompt) => void send(prompt, [])} recordHint={context.record ? `this ${context.record.type}` : null} />
          ) : null}
          {loading ? (
            <div className="flex justify-center py-10 text-fg-3">
              <Loader2 className="animate-spin" size={18} />
            </div>
          ) : null}
          {messages.map((message) => (
            <Message key={message.id} message={message} busy={busy} onConfirm={confirm} onCancel={cancel} />
          ))}
          {draft ? <DraftView draft={draft} busy={busy} onConfirm={confirm} onCancel={cancel} /> : null}
        </div>
      </div>
      <Composer compact={compact} busy={busy} onSend={send} onStop={stop} conversationId={conversationId} disabled={mode === 'not_configured'} />
    </div>
  )
}

function NotConnected() {
  return (
    <div className="pane-contrast relative mx-auto mt-6 max-w-[520px] overflow-hidden p-6 text-center">
      <span className="mx-auto grid size-12 place-items-center rounded-2xl bg-[rgb(255_255_255/0.6)]">
        <KeyRound size={20} />
      </span>
      <h3 className="mt-3 text-[18px] font-semibold">Connect Gemini to use the assistant</h3>
      <p className="mt-1 text-[13px] opacity-75">
        Add your Gemini API key in Settings. The key stays on the server, encrypted; it is never sent to the browser. Everything else in the app works without it.
      </p>
      <Link to="/integrations/ai" className="btn btn-primary mt-4">
        Open AI settings
      </Link>
    </div>
  )
}

function Welcome({ compact, onPick, recordHint }: { compact: boolean; onPick: (prompt: string) => void; recordHint: string | null }) {
  const { user } = useAuth()
  return (
    <div className={cn('flex flex-col', compact ? 'pt-2' : 'pt-8')}>
      <div className="flex items-center gap-3">
        <span className="icon-tile size-11">
          <Sparkles size={20} />
        </span>
        <div>
          <h2 className={cn('font-light tracking-[-0.03em]', compact ? 'text-[22px]' : 'text-[30px]')}>Hi {user?.username}, what can I do?</h2>
          <p className="text-[13px] text-fg-3">
            I can read every part of the business, analyse it, make reports, and do the work — you confirm each change.
            {recordHint ? ` Ask about ${recordHint} too.` : ''}
          </p>
        </div>
      </div>
      <div className={cn('mt-5 grid gap-2', compact ? 'grid-cols-1' : 'grid-cols-2 max-md:grid-cols-1')}>
        {STARTERS.slice(0, compact ? 4 : 6).map((starter, index) => (
          <motion.button
            key={starter.title}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.04 * index }}
            onClick={() => onPick(starter.prompt)}
            className="card lift p-3 text-left"
          >
            <div className="text-[13px] font-semibold">{starter.title}</div>
            <div className="mt-0.5 line-clamp-2 text-[12px] text-fg-3">{starter.prompt}</div>
          </motion.button>
        ))}
      </div>
    </div>
  )
}

function Message({ message, busy, onConfirm, onCancel }: { message: ChatMessage; busy: boolean; onConfirm: (id: string) => void; onCancel: (id: string) => void }) {
  if (message.role === 'user') return <UserBubble message={message} />
  return (
    <AssistantBody steps={message.steps} content={message.content} error={message.error ?? null}>
      {message.blocks.map((block) => (
        <BlockView key={block.id} block={block} busy={busy} onConfirm={onConfirm} onCancel={onCancel} />
      ))}
    </AssistantBody>
  )
}

function DraftView({ draft, busy, onConfirm, onCancel }: { draft: Draft; busy: boolean; onConfirm: (id: string) => void; onCancel: (id: string) => void }) {
  return (
    <AssistantBody steps={draft.steps} content={draft.content} error={draft.error} live>
      {draft.blocks.map((block) => (
        <BlockView key={block.id} block={block} busy={busy} onConfirm={onConfirm} onCancel={onCancel} />
      ))}
      {!draft.content && !draft.blocks.length && !draft.error ? <Thinking /> : null}
    </AssistantBody>
  )
}

function Thinking() {
  return (
    <div className="flex items-center gap-1.5 py-1" aria-label="Thinking">
      {[0, 1, 2].map((i) => (
        <motion.span key={i} className="size-1.5 rounded-full bg-fg-3" animate={{ opacity: [0.3, 1, 0.3], y: [0, -2, 0] }} transition={{ duration: 1, repeat: Infinity, delay: i * 0.15 }} />
      ))}
    </div>
  )
}

function AssistantBody({ steps, content, error, live, children }: { steps: ChatMessage['steps']; content: string; error: string | null; live?: boolean; children?: ReactNode }) {
  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="flex gap-3">
      <span className="icon-tile mt-0.5 size-8 shrink-0 rounded-[11px]!">
        <Sparkles size={15} />
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-2.5">
        <Steps steps={steps} live={live} />
        {content ? <Markdown text={content} /> : null}
        {children}
        {error ? <div className="rounded-xl bg-white/[0.05] px-3 py-2 text-[12.5px] text-fg-2 ring-1 ring-white/8">⚠ {error}</div> : null}
      </div>
    </motion.div>
  )
}

function UserBubble({ message }: { message: ChatMessage }) {
  const { user } = useAuth()
  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="flex justify-end gap-2.5">
      <div className="flex max-w-[78%] flex-col items-end gap-1.5">
        {message.attachments.length ? (
          <div className="flex flex-wrap justify-end gap-1.5">
            {message.attachments.map((file) => (
              <FileChip key={file.id} file={file} />
            ))}
          </div>
        ) : null}
        {message.content ? <div className="rounded-[18px] rounded-br-md bg-contrast px-3.5 py-2 text-[13.5px] whitespace-pre-wrap text-on-contrast">{message.content}</div> : null}
      </div>
      <Avatar name={user?.username ?? 'You'} size={28} />
    </motion.div>
  )
}

function FileChip({ file, onRemove, uploading }: { file: Pick<Attachment, 'filename' | 'mime_type'>; onRemove?: () => void; uploading?: boolean }) {
  const Icon = file.mime_type.startsWith('image/') ? ImageIcon : file.mime_type.includes('sheet') || file.mime_type.includes('csv') ? Sheet : FileText
  return (
    <span className="flex h-8 max-w-[220px] items-center gap-1.5 rounded-full bg-white/[0.06] pr-1 pl-2.5 text-[12px] ring-1 ring-white/8">
      {uploading ? <Loader2 size={13} className="animate-spin" /> : <Icon size={13} />}
      <span className="truncate">{file.filename}</span>
      {onRemove ? (
        <button onClick={onRemove} className="grid size-6 place-items-center rounded-full hover:bg-white/10" aria-label={`Remove ${file.filename}`}>
          <X size={12} />
        </button>
      ) : null}
    </span>
  )
}

const ACCEPT = '.pdf,.png,.jpg,.jpeg,.webp,.heic,.gif,.csv,.xlsx,.xlsm,.txt,.md,.json'

function Composer({ compact, busy, onSend, onStop, conversationId, disabled }: { compact: boolean; busy: boolean; onSend: (text: string, files: Attachment[]) => Promise<void>; onStop: () => void; conversationId: string | null; disabled: boolean }) {
  const [text, setText] = useState('')
  const [files, setFiles] = useState<Attachment[]>([])
  const [uploading, setUploading] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const input = useRef<HTMLTextAreaElement>(null)
  const picker = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const el = input.current
    if (!el) return
    el.style.height = '0px'
    el.style.height = `${Math.min(180, el.scrollHeight)}px`
  }, [text])

  async function add(list: FileList | File[]) {
    setError(null)
    for (const file of Array.from(list).slice(0, 6 - files.length)) {
      setUploading((u) => [...u, file.name])
      try {
        const uploaded = await ai.upload(file, conversationId ?? undefined)
        setFiles((f) => [...f, uploaded])
      } catch (err) {
        setError(errorText(err))
      } finally {
        setUploading((u) => u.filter((name) => name !== file.name))
      }
    }
  }

  function submit() {
    if (busy || disabled || uploading.length || (!text.trim() && !files.length)) return
    void onSend(text.trim(), files)
    setText('')
    setFiles([])
  }

  return (
    <div
      className={cn('shrink-0', compact ? 'px-3 pb-3' : 'px-6 pb-5')}
      onDragOver={(event) => {
        event.preventDefault()
        setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => {
        event.preventDefault()
        setDragging(false)
        if (event.dataTransfer.files.length) void add(event.dataTransfer.files)
      }}
    >
      <div className={cn('mx-auto rounded-[22px] bg-ink-850 p-2 shadow-pane ring-1 ring-white/8 transition', compact ? '' : 'max-w-[860px]', dragging && 'ring-2 ring-blue')}>
        {files.length || uploading.length ? (
          <div className="flex flex-wrap gap-1.5 px-1.5 pt-1 pb-2">
            {files.map((file) => (
              <FileChip key={file.id} file={file} onRemove={() => setFiles((f) => f.filter((item) => item.id !== file.id))} />
            ))}
            {uploading.map((name) => (
              <FileChip key={name} file={{ filename: name, mime_type: '' }} uploading />
            ))}
          </div>
        ) : null}
        <div className="flex items-end gap-1.5">
          <button
            onClick={() => picker.current?.click()}
            disabled={disabled}
            className="grid size-9 shrink-0 place-items-center rounded-full text-fg-3 transition hover:bg-white/[0.06] hover:text-fg disabled:opacity-40"
            aria-label="Attach files"
            title="Attach invoices, bills, photos or spreadsheets"
          >
            <Paperclip size={17} />
          </button>
          <input ref={picker} type="file" multiple accept={ACCEPT} className="hidden" onChange={(event) => event.target.files && void add(event.target.files)} />
          <textarea
            ref={input}
            rows={1}
            value={text}
            disabled={disabled}
            onChange={(event) => setText(event.target.value)}
            onPaste={(event) => {
              const pasted = Array.from(event.clipboardData.files)
              if (pasted.length) void add(pasted)
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault()
                submit()
              }
            }}
            placeholder={disabled ? 'Connect Gemini in Settings to start' : 'Ask anything, or tell me what to do… (attach a bill to enter it)'}
            className="max-h-[180px] min-h-9 flex-1 resize-none bg-transparent px-1 py-2 text-[13.5px] outline-none placeholder:text-fg-4"
          />
          {busy ? (
            <button onClick={onStop} className="grid size-9 shrink-0 place-items-center rounded-full bg-contrast text-on-contrast" aria-label="Stop">
              <Square size={13} fill="currentColor" />
            </button>
          ) : (
            <button
              onClick={submit}
              disabled={disabled || (!text.trim() && !files.length) || Boolean(uploading.length)}
              className="brand-fill grid size-9 shrink-0 place-items-center rounded-full transition disabled:opacity-30"
              aria-label="Send"
            >
              <ArrowUp size={17} strokeWidth={2.4} />
            </button>
          )}
        </div>
      </div>
      {error ? <p className="mt-1.5 text-center text-[12px] text-bad">{error}</p> : null}
      {!compact ? <p className="mt-2 text-center text-[11px] text-fg-4">The assistant works from your live data and asks before changing anything. Check important figures.</p> : null}
    </div>
  )
}
