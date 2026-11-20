import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Bot, MessageSquareText, PhoneCall, Save } from 'lucide-react'
import { automation, type AgentProfile } from '@/api/automation'
import { useAction } from '@/api/queries'
import { cn } from '@/lib/cn'
import { Badge, Button, Field, Spinner } from '@/ui/core'

type Edits = Record<string, { name: string; voice: string; instructions: string }>

/** Who does which job: one agent per job, working by text and/or phone. */
export function AgentsView() {
  const data = useQuery({ queryKey: ['automation', 'agents'], queryFn: automation.agents })
  const [edits, setEdits] = useState<Edits>({})
  const save = useAction(automation.saveAgents, { success: 'Agents saved' })
  useEffect(() => {
    if (!data.data) return
    setEdits(Object.fromEntries(data.data.agents.map((a) => [a.key, { name: a.name, voice: a.voice ?? '', instructions: a.instructions }])))
  }, [data.data])
  if (data.isPending || !data.data) return <Spinner />
  const set = (key: string, patch: Partial<Edits[string]>) => setEdits((old) => ({ ...old, [key]: { ...old[key], ...patch } }))
  const dirty = data.data.agents.some((a) => {
    const e = edits[a.key]
    return e && (e.name !== a.name || e.voice !== (a.voice ?? '') || e.instructions !== a.instructions)
  })
  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-1 pb-4">
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <p className="min-w-[260px] flex-1 text-[12.5px] text-fg-3">
          Each job has its own agent with its own instructions and tools. <b>Text</b> (TAI) and <b>Phone</b> (PAI) are only how an agent reaches people: WhatsApp/email, or a call.
          Turn them on per step in the flows.
        </p>
        <Button kind="primary" icon={<Save size={14} />} disabled={!dirty} busy={save.isPending} onClick={() => save.mutate(edits)}>
          Save
        </Button>
      </div>
      <div className="grid gap-3 lg:grid-cols-2 2xl:grid-cols-3">
        {data.data.agents.map((a) => (
          <AgentCard key={a.key} a={a} edit={edits[a.key]} voices={data.data!.voices} onChange={(patch) => set(a.key, patch)} />
        ))}
      </div>
      <h3 className="mt-6 mb-2 text-[13px] font-semibold">Agents inside the app</h3>
      <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
        {data.data.others.map((o) => (
          <div key={o.key} className="rounded-[12px] border border-white/7 px-3.5 py-2.5 text-[12.5px]">
            <span className="font-semibold">{o.label}.</span> <span className="text-fg-2">{o.job}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function AgentCard({ a, edit, voices, onChange }: { a: AgentProfile; edit?: Edits[string]; voices: string[]; onChange: (patch: Partial<Edits[string]>) => void }) {
  if (!edit) return null
  return (
    <section className={cn('card flex flex-col gap-3 p-4', a.parked && 'opacity-60')}>
      <div className="flex items-start gap-2.5">
        <span className="icon-disc grid size-9 shrink-0 place-items-center rounded-xl bg-white/7">
          <Bot size={16} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <h3 className="text-[14px] font-semibold">{a.label}</h3>
            {a.parked ? <Badge>Parked</Badge> : null}
            {a.mediums.includes('text') ? (
              <Badge tone="sky">
                <MessageSquareText size={11} /> Text
              </Badge>
            ) : null}
            {a.mediums.includes('phone') ? (
              <Badge tone="sky">
                <PhoneCall size={11} /> Phone
              </Badge>
            ) : null}
          </div>
          <p className="mt-1 text-[12.5px] leading-relaxed text-fg-2">{a.job}</p>
        </div>
      </div>
      {a.steps.length ? <p className="text-[11.5px] text-fg-3">Steps: {a.steps.map((s) => s.label).join(' · ')}</p> : <p className="text-[11.5px] text-fg-3">Runs the follow-ups you give to the AI.</p>}
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Introduces itself as">{(props) => <input {...props} className="field" value={edit.name} onChange={(e) => onChange({ name: e.target.value })} />}</Field>
        {a.mediums.includes('phone') ? (
          <Field label="Voice">
            {(props) => (
              <select {...props} className="field" value={edit.voice} onChange={(e) => onChange({ voice: e.target.value })}>
                <option value="">Default</option>
                {voices.map((v) => (
                  <option key={v}>{v}</option>
                ))}
              </select>
            )}
          </Field>
        ) : null}
      </div>
      <Field label="Extra instructions" optional hint="Added to the agent's own instructions on every message or call.">
        {(props) => (
          <textarea
            {...props}
            className="field min-h-[70px]"
            value={edit.instructions}
            onChange={(e) => onChange({ instructions: e.target.value })}
            placeholder={a.key === 'purchasing' ? 'Always ask for the mill test certificate. Prefer suppliers who deliver within 2 days.' : 'Keep it short; mention free delivery above 100 bags.'}
          />
        )}
      </Field>
    </section>
  )
}
