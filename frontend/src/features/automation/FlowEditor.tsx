import '@xyflow/react/dist/style.css'
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type DragEvent } from 'react'
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  addEdge,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Connection,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react'
import {
  AlarmClock,

  Bot,
  CheckCircle2,
  CircleDot,
  Cpu,
  GitBranch,
  GripVertical,
  Hand,
  LayoutList,
  Lock,
  MessageSquareText,
  PhoneCall,
  Plus,
  RotateCcw,
  Save,
  Search,
  ShieldCheck,
  Sparkles,
  Trash2,
  UserRound,
  Wand2,
  Zap,
  type LucideIcon,
} from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/endpoints'
import { useAction } from '@/api/queries'
import { automation, type ConfigField, type Actor, type Flow, type FlowNode, type Library, type Mode, type StepData, type StepType } from '@/api/automation'
import { errorText, http } from '@/api/client'
import { cn } from '@/lib/cn'
import { useTheme } from '@/app/theme'
import { Badge, Button, Notice, Spinner } from '@/ui/core'
import { ConfigForm } from './ConfigForm'

export const ACTOR: Record<Actor, { label: string; short: string; icon: LucideIcon; hint: string }> = {
  system: { label: 'System', short: 'System', icon: Cpu, hint: 'The app does it by rule' },
  person: { label: 'Person', short: 'Person', icon: UserRound, hint: 'Someone on the team' },
  tai: { label: 'AI by text', short: 'Text', icon: MessageSquareText, hint: 'The agent writes on WhatsApp and email (TAI)' },
  pai: { label: 'AI by phone', short: 'Phone', icon: PhoneCall, hint: 'The agent talks on phone calls (PAI)' },
}
export const MODE: Record<Mode, { label: string; icon: LucideIcon; hint: string }> = {
  auto: { label: 'Automatic', icon: Zap, hint: 'Runs on its own' },
  limits: { label: 'Auto within limits', icon: ShieldCheck, hint: 'On its own inside the limits, else a person' },
  approval: { label: 'Person approves', icon: Hand, hint: 'Prepared, then a person approves' },
  off: { label: 'Off', icon: Lock, hint: 'Not done' },
}
const CATEGORY: Record<string, { label: string; icon: LucideIcon }> = {
  trigger: { label: 'Triggers', icon: Zap },
  communicate: { label: 'Talk to customers and suppliers', icon: MessageSquareText },
  decide: { label: 'Decisions', icon: GitBranch },
  record: { label: 'Records', icon: CircleDot },
  person: { label: 'People', icon: UserRound },
}
const CHANNEL: Record<string, string> = { whatsapp: 'WhatsApp', email: 'Email', call: 'Phone call', link: 'Their link' }

const LibraryContext = createContext<Record<string, StepType>>({})
const OrderContext = createContext<Record<string, number>>({})

type StepNodeType = Node<StepData, 'step'>

/** One step on the canvas: what it is, who does it, how much alone. */
function StepNode({ id, data, selected }: NodeProps<StepNodeType>) {
  const lib = useContext(LibraryContext)
  const number = useContext(OrderContext)[id]
  const type = lib[data.step]
  const ModeIcon = MODE[data.mode]?.icon ?? Zap
  const Cat = CATEGORY[type?.category ?? 'record']?.icon ?? CircleDot
  const off = data.mode === 'off'
  return (
    <div
      className={cn(
        'w-[300px] rounded-2xl border bg-ink-850 shadow-[var(--shadow-card)] transition-shadow',
        selected ? 'border-transparent ring-2 ring-blue shadow-[var(--shadow-lift)]' : 'border-[var(--card-border)]',
        off && 'opacity-55',
      )}
    >
      <Handle type="target" position={Position.Left} className="!size-3 !border-2 !border-[var(--c-ink-850)] !bg-fg-3" />
      <div className="flex items-start gap-2.5 p-3">
        <span className={cn('relative grid size-9 shrink-0 place-items-center rounded-xl', type?.category === 'trigger' ? 'icon-tile' : 'icon-disc')}>
          <Cat size={16} />
          {number ? <span className="absolute -top-1.5 -left-1.5 grid size-[18px] place-items-center rounded-full bg-[#0b0b0c] text-[10px] font-bold text-[#fff] ring-2 ring-[var(--c-ink-850)]">{number}</span> : null}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="truncate text-[13.5px] font-semibold">{data.title}</span>
            {type && !type.live ? (
              <span className="shrink-0 rounded-full bg-white/8 px-1.5 text-[10px] font-semibold text-fg-3" title="Settings are kept; the app cannot run this step yet">
                planned
              </span>
            ) : null}
          </div>
          {type?.agent_label && data.actors.some((a) => a === 'tai' || a === 'pai') ? (
            <div className="mt-0.5 flex items-center gap-1 truncate text-[11.5px] text-fg-3">
              <Bot size={11} className="shrink-0" /> {type.agent_label}
            </div>
          ) : null}
          <div className="mt-1.5 flex flex-wrap items-center gap-1">
            {data.actors.map((actor) => {
              const A = ACTOR[actor]
              return (
                <span key={actor} className={cn('inline-flex h-[22px] items-center gap-1 rounded-full px-2 text-[11px] font-semibold', actor === 'tai' || actor === 'pai' ? 'bg-blue/25' : 'bg-white/8')}>
                  <A.icon size={11} /> {A.short}
                </span>
              )
            })}
            <span className={cn('inline-flex h-[22px] items-center gap-1 rounded-full px-2 text-[11px] font-semibold', data.mode === 'auto' ? 'bg-[#0b0b0c] text-[#fff]' : data.mode === 'off' ? 'bg-white/6 text-fg-3' : 'bg-peri/45')}>
              <ModeIcon size={11} /> {MODE[data.mode]?.label}
            </span>
          </div>
          {data.limits.length || data.ai?.model || data.channels.length ? (
            <div className="mt-1.5 space-y-0.5 text-[11px] text-fg-3">
              {data.limits.length ? <div className="truncate">Limits: {data.limits.map((l) => `${l.field.replace(/_/g, ' ')} ${l.op} ${l.value}`).join(', ')}</div> : null}
              {data.channels.length ? <div className="truncate">{data.channels.map((c) => CHANNEL[c] ?? c).join(' · ')}</div> : null}
              {data.ai?.model ? <div className="truncate">Model: {data.ai.model}</div> : null}
            </div>
          ) : null}
        </div>
      </div>
      <Handle type="source" position={Position.Right} className="!size-3 !border-2 !border-[var(--c-ink-850)] !bg-blue" />
    </div>
  )
}

const nodeTypes = { step: StepNode }

function toRf(flow: Flow): { nodes: StepNodeType[]; edges: Edge[] } {
  return {
    nodes: flow.nodes.map((n) => ({ id: n.id, type: 'step', position: n.position, data: n.data })),
    edges: flow.edges.map((e) => ({ id: e.id, source: e.source, target: e.target, label: e.label ?? undefined })),
  }
}

/** The steps in the order the connections run, first step first. */
function sequence(nodes: StepNodeType[], edges: Edge[]): string[] {
  const linked = new Set(edges.flatMap((e) => [e.source, e.target]))
  const hasParent = new Set(edges.map((e) => e.target))
  const roots = nodes.filter((n) => linked.has(n.id) && !hasParent.has(n.id)).sort((a, b) => a.position.y - b.position.y || a.position.x - b.position.x)
  const order: string[] = []
  const seen = new Set<string>()
  for (const root of roots) {
    const queue = [root.id]
    while (queue.length) {
      const id = queue.shift()!
      if (seen.has(id)) continue
      seen.add(id)
      order.push(id)
      edges.filter((e) => e.source === id).forEach((e) => queue.push(e.target))
    }
  }
  nodes.forEach((n) => linked.has(n.id) && !seen.has(n.id) && order.push(n.id))
  return order
}

/** Lay the steps out in rows of four, left to right, in flow order. */
function arrange(nodes: StepNodeType[], edges: Edge[]): StepNodeType[] {
  const ordered = sequence(nodes, edges)
  nodes.forEach((n) => !ordered.includes(n.id) && ordered.push(n.id))
  const index = new Map(ordered.map((id, i) => [id, i]))
  return nodes.map((n) => {
    const i = index.get(n.id) ?? 0
    return { ...n, position: { x: (i % 4) * 340, y: Math.floor(i / 4) * 190 } }
  })
}

let counter = 0
const newId = () => `n${Date.now().toString(36)}${(counter++).toString(36)}`

function Canvas({ flowKey, library }: { flowKey: 'sales' | 'purchase'; library: Library }) {
  const flow = useQuery({ queryKey: ['automation', 'flow', flowKey], queryFn: () => automation.flow(flowKey) })
  const lib = useMemo(() => Object.fromEntries(library.steps.map((s) => [s.key, s])), [library])
  const [nodes, setNodes, onNodesChange] = useNodesState<StepNodeType>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [dirty, setDirty] = useState(false)
  const wrapper = useRef<HTMLDivElement>(null)
  const { screenToFlowPosition, fitView } = useReactFlow()
  const { theme } = useTheme()
  useEffect(() => {
    if (!flow.data) return
    const rf = toRf(flow.data)
    setNodes(rf.nodes)
    setEdges(rf.edges)
    setDirty(false)
    setTimeout(() => fitView({ padding: 0.12, maxZoom: 1 }), 50)
  }, [flow.data]) // eslint-disable-line react-hooks/exhaustive-deps
  const save = useAction(
    () =>
      automation.save({
        key: flowKey,
        nodes: nodes.map((n) => ({ id: n.id, type: 'step', position: n.position, data: n.data }) as FlowNode),
        edges: edges.map((e) => ({ id: e.id, source: e.source, target: e.target, label: typeof e.label === 'string' ? e.label : null })),
      }),
    { success: 'Flow saved', quiet: true },
  )
  const reset = useAction(() => automation.reset(flowKey), { success: 'Back to the default flow' })
  const touch = () => setDirty(true)
  const onConnect = useCallback((c: Connection) => (setEdges((eds) => addEdge({ ...c, id: `e${Date.now()}` }, eds)), setDirty(true)), [setEdges])
  const onDrop = useCallback(
    (event: DragEvent) => {
      event.preventDefault()
      const key = event.dataTransfer.getData('application/aec-step')
      const type = lib[key]
      if (!type) return
      const position = screenToFlowPosition({ x: event.clientX, y: event.clientY })
      const id = newId()
      const data: StepData = {
        step: key,
        title: type.label,
        actors: [type.default_actor],
        mode: type.modes.includes('auto') && type.modes.length === 4 ? 'approval' : type.modes[0],
        limits: [],
        ai: type.ai ? { model: '', instructions: '' } : null,
        channels: [...type.channels],
        timing: type.timing ? { ...type.timing } : null,
        config: type.config_fields?.length ? configDefaults(type.config_fields) : null,
        notes: '',
      }
      setNodes((ns) => [...ns, { id, type: 'step', position, data }])
      setSelected(id)
      setDirty(true)
    },
    [lib, screenToFlowPosition, setNodes],
  )
  const update = (id: string, patch: Partial<StepData>) => {
    setNodes((ns) => ns.map((n) => (n.id === id ? { ...n, data: { ...n.data, ...patch } } : n)))
    setDirty(true)
  }
  const remove = (id: string) => {
    setNodes((ns) => ns.filter((n) => n.id !== id))
    setEdges((es) => es.filter((e) => e.source !== id && e.target !== id))
    setSelected(null)
    setDirty(true)
  }
  const current = nodes.find((n) => n.id === selected)
  const numbers = useMemo(() => Object.fromEntries(sequence(nodes, edges).map((id, i) => [id, i + 1])), [nodes, edges])
  const counts = useMemo(() => {
    const out = { auto: 0, ai: 0, person: 0 }
    nodes.forEach((n) => {
      if (n.data.mode === 'auto' || n.data.mode === 'limits') out.auto += 1
      if (n.data.actors.some((a) => a === 'tai' || a === 'pai')) out.ai += 1
      if (n.data.mode === 'approval' || n.data.actors.includes('person')) out.person += 1
    })
    return out
  }, [nodes])

  if (flow.isPending) return <Spinner />
  return (
    <LibraryContext.Provider value={lib}>
      <OrderContext.Provider value={numbers}>
      <div className="flex min-h-0 flex-1">
        <Palette flowKey={flowKey} library={library} />
        <div className="relative min-w-0 flex-1" ref={wrapper} onDragOver={(e) => (e.preventDefault(), (e.dataTransfer.dropEffect = 'move'))} onDrop={onDrop}>
          <div className="pointer-events-none absolute inset-x-3 top-3 z-10 flex flex-wrap items-start gap-2 [&>*]:pointer-events-auto">
          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
            <span className={cn('rounded-full bg-ink-850/90 px-3 py-1.5 text-[12px] shadow-[var(--shadow-card)] backdrop-blur', current && 'max-2xl:hidden')}>
              <b>{nodes.length}</b> steps · <Zap size={11} className="inline" /> {counts.auto} automatic · <Bot size={11} className="inline" /> {counts.ai} with AI · <Hand size={11} className="inline" /> {counts.person} with a person
            </span>
            {dirty ? <Badge tone="sky">Unsaved changes</Badge> : flow.data?.updated_by ? <Badge>Saved by {flow.data.updated_by}</Badge> : <Badge>Default flow</Badge>}
          </div>
          <div className="flex shrink-0 gap-2">
            <Button small icon={<LayoutList size={13} />} onClick={() => (setNodes((ns) => arrange(ns, edges)), setDirty(true), setTimeout(() => fitView({ padding: 0.12, maxZoom: 1 }), 50))}>
              Arrange
            </Button>
            <Button small icon={<RotateCcw size={13} />} onClick={() => reset.mutate(undefined)}>
              Default
            </Button>
            <Button small kind="primary" icon={<Save size={13} />} busy={save.isPending} disabled={!dirty} onClick={() => save.mutate(undefined, { onSuccess: () => setDirty(false) })}>
              Save
            </Button>
          </div>
          </div>
          {save.error ? (
            <div className="absolute top-14 left-3 z-10 max-w-[520px]">
              <Notice tone="bad">{errorText(save.error)}</Notice>
            </div>
          ) : null}
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={(changes) => (onNodesChange(changes), changes.some((c) => c.type === 'position' && c.dragging === false) && touch())}
            onEdgesChange={(changes) => (onEdgesChange(changes), changes.some((c) => c.type === 'remove') && touch())}
            onConnect={onConnect}
            onNodeClick={(_, node) => setSelected(node.id)}
            onPaneClick={() => setSelected(null)}
            defaultEdgeOptions={{ type: 'smoothstep', markerEnd: { type: MarkerType.ArrowClosed }, style: { strokeWidth: 2 } }}
            colorMode={theme === 'dark' ? 'dark' : 'light'}
            deleteKeyCode={['Backspace', 'Delete']}
            proOptions={{ hideAttribution: true }}
            fitView
          >
            <Background variant={BackgroundVariant.Dots} gap={22} size={1.4} />
            <Controls showInteractive={false} />
            <MiniMap pannable zoomable style={{ width: 150, height: 100 }} className="!rounded-xl max-xl:!hidden" />
          </ReactFlow>
        </div>
        {current ? <Inspector key={current.id} node={current} type={lib[current.data.step]} library={library} onChange={(patch) => update(current.id, patch)} onRemove={() => remove(current.id)} onClose={() => setSelected(null)} dirty={dirty} /> : null}
      </div>
      </OrderContext.Provider>
    </LibraryContext.Provider>
  )
}

/** Step types to drag onto the canvas. */
function Palette({ flowKey, library }: { flowKey: string; library: Library }) {
  const steps = library.steps.filter((s) => s.flow === flowKey)
  return (
    <aside className="w-[250px] shrink-0 overflow-y-auto border-r border-white/7 p-3 max-lg:hidden">
      <div className="mb-2 flex items-center gap-1.5 px-1 text-[12px] font-semibold text-fg-2">
        <Plus size={13} /> Drag a step onto the flow
      </div>
      {Object.entries(CATEGORY).map(([key, cat]) => {
        const items = steps.filter((s) => s.category === key)
        if (!items.length) return null
        return (
          <div key={key} className="mb-3">
            <div className="eyebrow px-1 pb-1.5">{cat.label}</div>
            <div className="space-y-1.5">
              {items.map((step) => (
                <div
                  key={step.key}
                  draggable
                  onDragStart={(e) => (e.dataTransfer.setData('application/aec-step', step.key), (e.dataTransfer.effectAllowed = 'move'))}
                  className="group flex cursor-grab items-center gap-2 rounded-xl border border-[var(--card-border)] bg-ink-850 px-2.5 py-2 text-[12.5px] shadow-[var(--shadow-card)] active:cursor-grabbing"
                  title={step.description}
                >
                  <GripVertical size={13} className="text-fg-4 group-hover:text-fg-2" />
                  <span className="min-w-0 flex-1 truncate font-medium">{step.label}</span>
                  {!step.live ? <span className="text-[10px] text-fg-3">planned</span> : null}
                </div>
              ))}
            </div>
          </div>
        )
      })}
    </aside>
  )
}

/** Everything about one step. */
function Inspector({ node, type, library, onChange, onRemove, onClose, dirty }: { node: StepNodeType; type?: StepType; library: Library; onChange: (patch: Partial<StepData>) => void; onRemove: () => void; onClose: () => void; dirty: boolean }) {
  const models = useQuery({ queryKey: ['integrations'], queryFn: api.integrations.get })
  if (!type) return null
  const d = node.data
  const toggleActor = (actor: Actor) => {
    const next = d.actors.includes(actor) ? d.actors.filter((a) => a !== actor) : [...d.actors, actor]
    if (next.length) onChange({ actors: next })
  }
  return (
    <aside className="w-[360px] shrink-0 overflow-y-auto border-l border-white/7 bg-ink-850/60 max-md:absolute max-md:inset-0 max-md:z-20 max-md:w-full max-md:bg-ink-850">
      <header className="flex items-start gap-2 border-b border-white/7 p-4">
        <div className="min-w-0 flex-1">
          <div className="eyebrow">{CATEGORY[type.category]?.label}</div>
          <input className="mt-1 w-full bg-transparent text-[17px] font-semibold outline-none" value={d.title} onChange={(e) => onChange({ title: e.target.value })} aria-label="Step title" />
          <p className="mt-1 text-[12px] text-fg-3">{type.description}</p>
          {type.agent_label ? (
            <p className="mt-2 inline-flex items-center gap-1.5 rounded-full bg-blue/20 px-2.5 py-1 text-[11.5px] font-semibold">
              <Bot size={12} /> Carried out by the {type.agent_label}
            </p>
          ) : null}
          {!type.live ? (
            <p className="mt-2 rounded-lg bg-peri/35 px-2.5 py-1.5 text-[11.5px]">Planned: these settings are kept, and the app will follow them when this step is built.</p>
          ) : (
            <p className="mt-2 flex items-center gap-1 text-[11.5px] text-fg-2">
              <CheckCircle2 size={12} /> Live: the app follows these settings now.
            </p>
          )}
        </div>
        <button onClick={onClose} className="rounded-full px-2 text-[18px] leading-none text-fg-3 hover:text-fg" aria-label="Close">
          ×
        </button>
      </header>
      <div className="space-y-5 p-4">
        <Section title="Who does it" hint={type.agent_label ? `Choose one or more. "AI by text" and "AI by phone" are how the ${type.agent_label} works: on WhatsApp/email, or on calls.` : 'Choose one or more.'}>
          <div className="grid grid-cols-2 gap-1.5">
            {(Object.keys(ACTOR) as Actor[]).map((actor) => {
              const A = ACTOR[actor]
              const allowed = type.actors.includes(actor)
              const on = d.actors.includes(actor)
              return (
                <button
                  key={actor}
                  disabled={!allowed}
                  onClick={() => toggleActor(actor)}
                  title={allowed ? A.hint : 'Not possible for this step'}
                  className={cn('flex items-center gap-1.5 rounded-xl px-2.5 py-2 text-left text-[12px] font-semibold transition', on ? 'brand-fill' : 'bg-ink-700 text-fg-2', !allowed && 'cursor-not-allowed opacity-35')}
                >
                  <A.icon size={13} /> {A.label}
                </button>
              )
            })}
          </div>
        </Section>
        <Section title="How much on its own">
          <div className="space-y-1.5">
            {type.modes.map((mode) => {
              const M = MODE[mode]
              return (
                <button key={mode} onClick={() => onChange({ mode })} className={cn('flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left', d.mode === mode ? 'brand-fill' : 'bg-ink-700')}>
                  <M.icon size={14} />
                  <span className="flex-1">
                    <span className="block text-[12.5px] font-semibold">{M.label}</span>
                    <span className={cn('block text-[11px]', d.mode === mode ? 'opacity-75' : 'text-fg-3')}>{M.hint}</span>
                  </span>
                </button>
              )
            })}
          </div>
        </Section>
        {type.limit_fields.length ? (
          <Section title="Limits" hint={d.mode === 'limits' ? 'Inside all of these it runs alone; otherwise a person decides.' : 'Used when the mode is "Auto within limits".'}>
            <div className="space-y-1.5">
              {d.limits.map((limit, i) => {
                const meta = library.limit_fields[limit.field]
                return (
                  <div key={i} className="flex items-center gap-1.5">
                    <select className="field field-sm min-w-0 flex-1" value={limit.field} onChange={(e) => onChange({ limits: d.limits.map((l, j) => (j === i ? { ...l, field: e.target.value, value: '' } : l)) })}>
                      {type.limit_fields.map((f) => (
                        <option key={f} value={f}>
                          {library.limit_fields[f]?.label ?? f}
                        </option>
                      ))}
                    </select>
                    <select className="field field-sm w-[64px]" value={limit.op} onChange={(e) => onChange({ limits: d.limits.map((l, j) => (j === i ? { ...l, op: e.target.value } : l)) })}>
                      {(meta?.choices ? ['=', '!='] : ['<=', '>=', '=', '!=']).map((op) => (
                        <option key={op}>{op}</option>
                      ))}
                    </select>
                    {meta?.choices ? (
                      <select className="field field-sm w-[96px]" value={String(limit.value)} onChange={(e) => onChange({ limits: d.limits.map((l, j) => (j === i ? { ...l, value: e.target.value } : l)) })}>
                        <option value="">…</option>
                        {meta.choices.map((c) => (
                          <option key={c}>{c}</option>
                        ))}
                      </select>
                    ) : (
                      <input className="field field-sm w-[96px] text-right" value={String(limit.value)} placeholder={meta?.unit} onChange={(e) => onChange({ limits: d.limits.map((l, j) => (j === i ? { ...l, value: e.target.value } : l)) })} />
                    )}
                    <button className="text-fg-3 hover:text-fg" aria-label="Remove limit" onClick={() => onChange({ limits: d.limits.filter((_, j) => j !== i) })}>
                      <Trash2 size={13} />
                    </button>
                  </div>
                )
              })}
              <Button small icon={<Plus size={12} />} onClick={() => onChange({ limits: [...d.limits, { field: type.limit_fields[0], op: '<=', value: '' }] })}>
                Add limit
              </Button>
            </div>
          </Section>
        ) : null}
        {type.ai && d.ai ? (
          <Section title="AI" hint="Which model does this step, and how it should behave.">
            <label className="block">
              <span className="label flex items-center gap-1">
                <Sparkles size={12} /> Model
              </span>
              <select className="field field-sm" value={d.ai.model} onChange={(e) => onChange({ ai: { ...d.ai!, model: e.target.value } })}>
                <option value="">Default (Settings → AI)</option>
                {(models.data?.models ?? []).map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="mt-2 block">
              <span className="label flex items-center gap-1">
                <Wand2 size={12} /> Instructions for this step
              </span>
              <textarea className="field font-[inherit] text-[12.5px]" rows={4} placeholder="e.g. Always mention free delivery above 100 bags. Never offer more than 2% off." value={d.ai.instructions} onChange={(e) => onChange({ ai: { ...d.ai!, instructions: e.target.value } })} />
            </label>
          </Section>
        ) : null}
        {type.channels.length ? (
          <Section title="Channels">
            <div className="flex flex-wrap gap-1.5">
              {type.channels.map((c) => {
                const on = d.channels.includes(c)
                return (
                  <button key={c} onClick={() => onChange({ channels: on ? d.channels.filter((x) => x !== c) : [...d.channels, c] })} className={cn('h-[30px] rounded-full px-3 text-[12px] font-semibold', on ? 'brand-fill' : 'bg-ink-700 text-fg-2')}>
                    {CHANNEL[c] ?? c}
                  </button>
                )
              })}
            </div>
          </Section>
        ) : null}
        {type.config_fields?.length ? (
          <Section title="Settings" hint="Saved with the flow; press Save on the canvas after changing.">
            <ConfigForm fields={type.config_fields} value={(d.config as Record<string, unknown>) ?? configDefaults(type.config_fields)} onChange={(config) => onChange({ config })} />
          </Section>
        ) : null}
        {RUNNABLE[type.key] ? <RunPanel what={RUNNABLE[type.key]} dirty={dirty} /> : null}
        {d.timing ? (
          <Section title="Timing">
            <div className="space-y-1.5">
              {Object.entries(d.timing).map(([k, v]) => {
                const set = (value: unknown) => onChange({ timing: { ...d.timing, [k]: value } })
                const choice = TIMING_CHOICES[k]
                if (k === 'transporter_id')
                  return d.timing?.choose === 'fixed' ? <TransporterChoice key={k} value={String(v ?? '')} onChange={set} /> : null
                if (choice)
                  return (
                    <label key={k} className="block">
                      <span className="label">{choice.label}</span>
                      <select className="field field-sm" value={String(v ?? '')} onChange={(e) => set(e.target.value)}>
                        {(choice.options[type.flow] ?? choice.options.any).map(([value, label]) => (
                          <option key={value} value={value}>
                            {label}
                          </option>
                        ))}
                      </select>
                    </label>
                  )
                return (
                  <label key={k} className="flex items-center gap-2 text-[12.5px]">
                    <AlarmClock size={13} className="text-fg-3" />
                    <span className="flex-1">{k.replace(/_/g, ' ')}</span>
                    <input className="field field-sm w-[80px] text-right" inputMode="numeric" value={String(v)} onChange={(e) => set(Number(e.target.value) || 0)} />
                  </label>
                )
              }              )}
            </div>
          </Section>
        ) : null}
        <Section title="Notes">
          <textarea className="field font-[inherit] text-[12.5px]" rows={2} value={d.notes} onChange={(e) => onChange({ notes: e.target.value })} placeholder="Anything the team should know about this step" />
        </Section>
        <Button kind="ghost" icon={<Trash2 size={13} />} onClick={onRemove}>
          Remove step
        </Button>
      </div>
    </aside>
  )
}

const VEHICLE_CHOICES: [string, string][] = [
  ['', 'Any vehicle'], ['tempo', 'Tempo'], ['pickup', 'Pickup'], ['lcv', 'LCV (407)'], ['6_wheeler', '6-wheeler'], ['10_wheeler', '10-wheeler'],
  ['12_wheeler', '12-wheeler'], ['14_wheeler', '14-wheeler'], ['trailer', 'Trailer'], ['tractor', 'Tractor'], ['container', 'Container'],
]
const TIMING_CHOICES: Record<string, { label: string; options: Record<string, [string, string][]> }> = {
  invoice_on: { label: 'When to invoice', options: { any: [['order', 'When the order is placed'], ['delivery', 'On each delivery']] } },
  when: {
    label: 'When to book',
    options: {
      sales: [['order_placed', 'As soon as the order is placed'], ['stock_ready', 'When all its stock is ready']],
      purchase: [['po_placed', 'When the purchase order is placed']],
      any: [['order_placed', 'As soon as the order is placed']],
    },
  },
  choose: { label: 'Which transporter', options: { any: [['cheapest', 'Cheapest on the rate card'], ['best_rated', 'Best rated that fits'], ['fixed', 'Always the same one']] } },
  vehicle_type: { label: 'Vehicle', options: { any: VEHICLE_CHOICES } },
}

/** Pick one transporter (for "always the same one"). */
function TransporterChoice({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const list = useQuery({ queryKey: ['transporters', 'options'], queryFn: () => http.get<{ items: { id: string; name: string; is_active: boolean }[] }>('/api/transporters') })
  return (
    <label className="block">
      <span className="label">Transporter</span>
      <select className="field field-sm" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Choose…</option>
        {(list.data?.items ?? []).map((t) => (
          <option key={t.id} value={t.id}>
            {t.name}
          </option>
        ))}
      </select>
    </label>
  )
}

/** Defaults of a step's settings, nested as stored. */
function configDefaults(fields: ConfigField[]): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const f of fields) {
    if (f.type === 'section') out[f.key] = configDefaults(f.fields ?? [])
    else if (f.type === 'group') out[f.key] = { enabled: Boolean(f.default), ...configDefaults(f.fields ?? []) }
    else out[f.key] = f.default
  }
  return out
}

const RUNNABLE: Record<string, string> = {
  'purchase.need_detected': 'purchase',
  'purchase.chase_delivery': 'chase',
  'purchase.ask_supplier': 'rfqs',
  'sales.trigger_outreach': 'outreach',
  'sales.after_sales': 'after_sales',
}

/** Try a trigger: see what it would pick now, or run it once. */
function RunPanel({ what, dirty }: { what: string; dirty: boolean }) {
  const canPreview = what === 'purchase' || what === 'outreach'
  const preview = useQuery({ queryKey: ['automation', 'preview', what], queryFn: () => automation.preview(what as 'purchase' | 'outreach'), enabled: false })
  const run = useAction(() => automation.run(what), { success: 'Ran once', quiet: true })
  const rows = preview.data?.items ?? []
  return (
    <Section title="Try it" hint={dirty ? 'Save the flow first: these use the saved settings.' : 'Uses the saved settings. Running does it for real.'}>
      <div className="flex flex-wrap gap-2">
        {canPreview ? (
          <Button small icon={<Search size={12} />} busy={preview.isFetching} disabled={dirty} onClick={() => preview.refetch()}>
            {what === 'purchase' ? 'What would it buy?' : 'Who would it contact?'}
          </Button>
        ) : null}
        <Button small kind="primary" icon={<Zap size={12} />} busy={run.isPending} disabled={dirty} onClick={() => run.mutate(undefined)}>
          Run now
        </Button>
      </div>
      {run.data ? <pre className="mt-2 rounded-lg bg-ink-700 p-2 text-[11px] whitespace-pre-wrap">{JSON.stringify(run.data, null, 1)}</pre> : null}
      {preview.data ? (
        <div className="mt-2 max-h-[260px] space-y-1.5 overflow-y-auto">
          {!rows.length ? <div className="text-[12px] text-fg-3">Nothing right now.</div> : null}
          {rows.slice(0, 30).map((r, i) => (
            <div key={i} className="rounded-lg bg-ink-700 px-2.5 py-1.5 text-[12px]">
              <div className="font-semibold">
                {String(r.product ?? r.customer)}
                {r.quantity != null ? ` · ${r.quantity} ${String(r.unit ?? '')}` : ''}
              </div>
              <div className="text-fg-3">{Array.isArray(r.why) ? (r.why as string[]).join(', ') : String(r.why ?? '')}</div>
              {r.message ? <div className="mt-1 text-fg-2">{String(r.message)}</div> : null}
            </div>
          ))}
        </div>
      ) : null}
    </Section>
  )
}

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section>
      <div className="text-[12.5px] font-semibold">{title}</div>
      {hint ? <div className="mb-1.5 text-[11px] text-fg-3">{hint}</div> : <div className="mb-1.5" />}
      {children}
    </section>
  )
}

export function FlowEditor({ flowKey }: { flowKey: 'sales' | 'purchase' }) {
  const library = useQuery({ queryKey: ['automation', 'library'], queryFn: automation.library })
  if (!library.data) return <Spinner />
  return (
    <ReactFlowProvider>
      <Canvas key={flowKey} flowKey={flowKey} library={library.data} />
    </ReactFlowProvider>
  )
}

