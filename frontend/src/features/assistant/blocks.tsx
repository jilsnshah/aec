import { useMemo, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { motion } from 'motion/react'
import {
  AlertTriangle,
  ArrowDown,
  ArrowRight,
  ArrowUp,
  Check,
  CheckCircle2,
  ChevronDown,
  Download,
  FileSpreadsheet,
  FileText,
  Loader2,
  ShieldAlert,
  X,
  XCircle,
} from 'lucide-react'
import type { ActionBlock, Block, ChartBlock, ColumnKind, FileBlock, Step, TableBlock } from '@/api/ai'
import { cn } from '@/lib/cn'
import { fmtCompactMoney, fmtMoney, fmtQty } from '@/lib/format'
import { Button } from '@/ui/core'

/* ---------------------------------------------------------------- text */

export function Markdown({ text }: { text: string }) {
  return (
    <div className="prose-chat">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) =>
            href && href.startsWith('/') && !href.startsWith('//') ? (
              <Link to={href} className="font-medium text-fg underline decoration-blue/60 decoration-2 underline-offset-2 hover:decoration-blue">
                {children}
              </Link>
            ) : (
              <a href={href} target="_blank" rel="noreferrer" className="underline">
                {children}
              </a>
            ),
          table: ({ children }) => (
            <div className="my-2 overflow-x-auto rounded-xl ring-1 ring-white/8">
              <table className="w-full text-[12.5px]">{children}</table>
            </div>
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  )
}

/* ---------------------------------------------------------------- values */

export function formatValue(value: unknown, kind: ColumnKind): string {
  if (value === null || value === undefined || value === '') return '—'
  if (kind === 'money' && typeof value === 'number') return fmtMoney(value)
  if (kind === 'percent' && typeof value === 'number') return `${value.toFixed(1)}%`
  if (kind === 'number' && typeof value === 'number') return fmtQty(value)
  if (kind === 'boolean') return value ? 'Yes' : 'No'
  if (kind === 'date' && typeof value === 'string') {
    const date = new Date(value)
    return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
  }
  if (Array.isArray(value)) return value.join(', ')
  return String(value)
}

/* ---------------------------------------------------------------- table */

export function TableView({ block }: { block: TableBlock }) {
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null)
  const [expanded, setExpanded] = useState(false)
  const rows = useMemo(() => {
    if (!sort) return block.rows
    return [...block.rows].sort((a, b) => {
      const x = a[sort.key]
      const y = b[sort.key]
      if (typeof x === 'number' && typeof y === 'number') return (x - y) * sort.dir
      return String(x ?? '').localeCompare(String(y ?? '')) * sort.dir
    })
  }, [block.rows, sort])
  const shown = expanded ? rows : rows.slice(0, 12)
  const numeric = (kind: ColumnKind) => kind === 'money' || kind === 'number' || kind === 'percent'
  return (
    <BlockFrame title={block.title} meta={`${block.total_rows} row${block.total_rows === 1 ? '' : 's'}${block.total_rows > block.rows.length ? ` · showing ${block.rows.length}` : ''}`}>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[480px] text-[12.5px]">
          <thead>
            <tr className="border-b border-white/8">
              {block.columns.map((column) => (
                <th key={column.key} className={cn('h-8 px-3 font-medium whitespace-nowrap text-fg-3', numeric(column.kind) ? 'text-right' : 'text-left')}>
                  <button
                    className="inline-flex items-center gap-1 hover:text-fg"
                    onClick={() => setSort((s) => (s?.key === column.key ? (s.dir === 1 ? { key: column.key, dir: -1 } : null) : { key: column.key, dir: numeric(column.kind) ? -1 : 1 }))}
                  >
                    {column.label}
                    {sort?.key === column.key ? sort.dir === 1 ? <ArrowUp size={11} /> : <ArrowDown size={11} /> : null}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((row, index) => (
              <tr key={index} className="border-b border-white/5 last:border-0 hover:bg-white/[0.03]">
                {block.columns.map((column) => {
                  const text = formatValue(row[column.key], column.kind)
                  const id = column.link ? row[column.link.id] : null
                  return (
                    <td key={column.key} className={cn('h-9 px-3 whitespace-nowrap', numeric(column.kind) ? 'num text-right' : 'max-w-[260px] truncate')}>
                      {column.link && id ? (
                        <Link to={`${column.link.route}${id}`} className="font-medium underline decoration-blue/50 decoration-2 underline-offset-2 hover:decoration-blue">
                          {text}
                        </Link>
                      ) : (
                        text
                      )}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > 12 ? (
        <button onClick={() => setExpanded((v) => !v)} className="flex h-8 w-full items-center justify-center gap-1 border-t border-white/6 text-[12px] font-medium text-fg-2 hover:text-fg">
          {expanded ? 'Show fewer' : `Show all ${rows.length}`} <ChevronDown size={13} className={cn('transition', expanded && 'rotate-180')} />
        </button>
      ) : null}
    </BlockFrame>
  )
}

function BlockFrame({ title, meta, children, className }: { title?: string; meta?: string; children: ReactNode; className?: string }) {
  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className={cn('card overflow-hidden', className)}>
      {title ? (
        <div className="flex items-baseline gap-2 border-b border-white/6 px-3.5 py-2.5">
          <div className="min-w-0 flex-1 truncate text-[13px] font-semibold">{title}</div>
          {meta ? <div className="text-[11.5px] text-fg-3">{meta}</div> : null}
        </div>
      ) : null}
      {children}
    </motion.div>
  )
}

/* ---------------------------------------------------------------- chart */

const SERIES = ['var(--color-blue)', 'var(--color-solid)', 'var(--color-peri)', 'var(--color-fg-3)']

function axis(value: number, unit: ChartBlock['unit']) {
  if (unit === 'money') return fmtCompactMoney(value)
  if (unit === 'percent') return `${Math.round(value)}%`
  return Math.abs(value) >= 1000 ? `${(value / 1000).toFixed(1)}k` : fmtQty(Math.round(value * 10) / 10)
}
function full(value: number, unit: ChartBlock['unit']) {
  if (unit === 'money') return fmtMoney(value)
  if (unit === 'percent') return `${value.toFixed(1)}%`
  return fmtQty(value)
}
function label(x: unknown) {
  const text = String(x ?? '')
  if (/^\d{4}-\d{2}-\d{2}/.test(text)) {
    const date = new Date(text)
    if (!Number.isNaN(date.getTime())) return date.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
  }
  return text
}

export function ChartView({ block }: { block: ChartBlock }) {
  const [hover, setHover] = useState<number | null>(null)
  const keys = block.series.map((s) => s.key)
  const meta = block.total_rows > block.rows.length ? `first ${block.rows.length} of ${block.total_rows}` : undefined
  return (
    <BlockFrame title={block.title} meta={meta}>
      <div className="px-3.5 pt-3 pb-2">
        {block.series.length > 1 || block.chart === 'pie' ? (
          <div className="mb-2 flex flex-wrap gap-3 text-[11.5px] text-fg-2">
            {(block.chart === 'pie' ? block.rows.slice(0, 8).map((row) => ({ key: String(row.x), label: label(row.x) })) : block.series).map((s, i) => (
              <span key={s.key} className="flex items-center gap-1.5">
                <span className="size-2.5 rounded-full" style={{ background: block.chart === 'pie' ? PIE[i % PIE.length] : SERIES[i % SERIES.length] }} />
                {s.label}
              </span>
            ))}
          </div>
        ) : null}
        {block.chart === 'pie' ? (
          <Pie block={block} hover={hover} setHover={setHover} />
        ) : block.chart === 'horizontal_bar' ? (
          <HBars block={block} keys={keys} hover={hover} setHover={setHover} />
        ) : (
          <Cartesian block={block} keys={keys} hover={hover} setHover={setHover} />
        )}
      </div>
    </BlockFrame>
  )
}

type ChartProps = { block: ChartBlock; keys?: string[]; hover: number | null; setHover: (i: number | null) => void }

function Tooltip({ block, index, keys }: { block: ChartBlock; index: number; keys: string[] }) {
  const row = block.rows[index]
  return (
    <div className="pointer-events-none rounded-xl bg-contrast px-3 py-2 text-[11.5px] text-on-contrast shadow-pop">
      <div className="font-semibold">{label(row.x)}</div>
      {keys.map((key, i) => (
        <div key={key} className="num flex items-center gap-1.5 opacity-90">
          <span className="size-2 rounded-full" style={{ background: SERIES[i % SERIES.length] }} />
          {block.series[i].label}: {full(Number(row[key] ?? 0), block.unit)}
        </div>
      ))}
    </div>
  )
}

function Cartesian({ block, keys = [], hover, setHover }: ChartProps) {
  const W = 640
  const H = 220
  const pad = { l: 52, r: 10, t: 10, b: 28 }
  const stacked = block.chart === 'stacked_bar'
  const values = block.rows.map((row) => (stacked ? keys.reduce((s, k) => s + Math.max(0, Number(row[k] ?? 0)), 0) : Math.max(...keys.map((k) => Number(row[k] ?? 0)))))
  const lows = block.rows.map((row) => Math.min(0, ...keys.map((k) => Number(row[k] ?? 0))))
  const top = Math.max(1, ...values) * 1.08
  const bottom = Math.min(0, ...lows)
  const y = (v: number) => pad.t + (H - pad.t - pad.b) * (1 - (v - bottom) / (top - bottom))
  const n = block.rows.length
  const slot = (W - pad.l - pad.r) / Math.max(1, n)
  const xc = (i: number) => pad.l + slot * i + slot / 2
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => bottom + (top - bottom) * t)
  const every = Math.max(1, Math.ceil(n / 8))
  const line = block.chart === 'line' || block.chart === 'area'
  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" onMouseLeave={() => setHover(null)}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} style={{ stroke: 'var(--hair)' }} strokeDasharray={t === 0 ? undefined : '3 4'} />
            <text x={pad.l - 6} y={y(t) + 3.5} textAnchor="end" className="fill-fg-4 text-[10px]">
              {axis(t, block.unit)}
            </text>
          </g>
        ))}
        {block.rows.map((row, i) =>
          i % every === 0 ? (
            <text key={i} x={xc(i)} y={H - 8} textAnchor="middle" className="fill-fg-3 text-[10px]">
              {label(row.x).slice(0, 12)}
            </text>
          ) : null,
        )}
        {line
          ? keys.map((key, k) => {
              const pts = block.rows.map((row, i) => [xc(i), y(Number(row[key] ?? 0))] as const)
              const d = pts.map(([px, py], i) => `${i ? 'L' : 'M'}${px},${py}`).join('')
              return (
                <g key={key}>
                  {block.chart === 'area' ? <path d={`${d}L${pts[pts.length - 1]?.[0]},${y(0)}L${pts[0]?.[0]},${y(0)}Z`} style={{ fill: SERIES[k % SERIES.length], opacity: 0.14 }} /> : null}
                  <motion.path d={d} fill="none" strokeWidth={2.2} strokeLinejoin="round" style={{ stroke: SERIES[k % SERIES.length] }} initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.9 }} />
                  {pts.map(([px, py], i) => (hover === i ? <circle key={i} cx={px} cy={py} r={4} style={{ fill: 'var(--color-ink-850)', stroke: SERIES[k % SERIES.length] }} strokeWidth={2} /> : null))}
                </g>
              )
            })
          : block.rows.map((row, i) => {
              const width = Math.min(34, slot * (stacked || keys.length === 1 ? 0.62 : 0.8 / keys.length))
              let base = 0
              return keys.map((key, k) => {
                const v = Number(row[key] ?? 0)
                const x0 = stacked || keys.length === 1 ? xc(i) - width / 2 : xc(i) - (width * keys.length) / 2 + width * k
                const from = stacked ? base : 0
                const to = stacked ? base + Math.max(0, v) : v
                base = to
                const yTop = y(Math.max(from, to))
                const h = Math.abs(y(from) - y(to))
                return (
                  <motion.rect
                    key={key}
                    x={x0}
                    width={Math.max(1, width - (stacked ? 0 : 2))}
                    rx={Math.min(6, width / 3)}
                    initial={{ y: y(0), height: 0 }}
                    animate={{ y: yTop, height: Math.max(0.5, h) }}
                    transition={{ duration: 0.7, delay: i * 0.02 }}
                    style={{ fill: SERIES[k % SERIES.length], opacity: hover === null || hover === i ? 1 : 0.45 }}
                  />
                )
              })
            })}
        {block.rows.map((_, i) => (
          <rect key={i} x={pad.l + slot * i} y={pad.t} width={slot} height={H - pad.t - pad.b} fill="transparent" onMouseEnter={() => setHover(i)} />
        ))}
        {hover !== null && line ? <line x1={xc(hover)} x2={xc(hover)} y1={pad.t} y2={H - pad.b} style={{ stroke: 'var(--hair)' }} /> : null}
      </svg>
      {hover !== null ? (
        <div className="absolute top-0" style={{ left: `${(xc(hover) / W) * 100}%`, transform: `translateX(${xc(hover) > W * 0.7 ? '-105%' : '8px'})` }}>
          <Tooltip block={block} index={hover} keys={keys} />
        </div>
      ) : null}
    </div>
  )
}

function HBars({ block, keys = [], hover, setHover }: ChartProps) {
  const key = keys[0]
  const peak = Math.max(1, ...block.rows.map((row) => Number(row[key] ?? 0)))
  return (
    <div className="space-y-1.5 pb-1">
      {block.rows.slice(0, 25).map((row, i) => {
        const v = Number(row[key] ?? 0)
        return (
          <div key={i} className="grid grid-cols-[minmax(0,34%)_1fr_auto] items-center gap-2.5 text-[12px]" onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
            <span className="truncate text-fg-2">{label(row.x)}</span>
            <span className="relative h-5 overflow-hidden rounded-md bg-white/[0.05]">
              <motion.span
                className="absolute inset-y-0 left-0 rounded-md"
                style={{ background: i === 0 ? 'var(--color-blue)' : 'var(--color-peri)', opacity: hover === null || hover === i ? 1 : 0.5 }}
                initial={{ width: 0 }}
                animate={{ width: `${Math.max(0, (v / peak) * 100)}%` }}
                transition={{ duration: 0.7, delay: i * 0.03 }}
              />
            </span>
            <span className="num w-[92px] text-right font-medium">{full(v, block.unit)}</span>
          </div>
        )
      })}
    </div>
  )
}

const PIE = ['var(--color-blue)', 'var(--color-solid)', 'var(--color-peri)', 'var(--color-fg-3)', 'var(--color-blue-2)', 'var(--color-fg-4)', 'var(--color-peri-2)', 'var(--color-sky-2)']

function Pie({ block, hover, setHover }: ChartProps) {
  const key = block.series[0].key
  const rows = block.rows.slice(0, 8)
  const total = rows.reduce((s, row) => s + Math.max(0, Number(row[key] ?? 0)), 0) || 1
  let angle = -Math.PI / 2
  const arcs = rows.map((row, i) => {
    const share = Math.max(0, Number(row[key] ?? 0)) / total
    const start = angle
    angle += share * Math.PI * 2
    const large = share > 0.5 ? 1 : 0
    const r = hover === i ? 84 : 80
    const p = (a: number, rad: number) => [100 + Math.cos(a) * rad, 100 + Math.sin(a) * rad]
    const [x1, y1] = p(start, r)
    const [x2, y2] = p(angle, r)
    const [x3, y3] = p(angle, 46)
    const [x4, y4] = p(start, 46)
    const d = share >= 0.999 ? `M100,${100 - r}A${r},${r} 0 1 1 99.9,${100 - r}Z` : `M${x1},${y1}A${r},${r} 0 ${large} 1 ${x2},${y2}L${x3},${y3}A46,46 0 ${large} 0 ${x4},${y4}Z`
    return { d, share, i }
  })
  const active = hover ?? 0
  return (
    <div className="flex items-center gap-6">
      <svg viewBox="0 0 200 200" className="w-[180px] shrink-0">
        {arcs.map((arc) => (
          <path key={arc.i} d={arc.d} style={{ fill: PIE[arc.i % PIE.length] }} onMouseEnter={() => setHover(arc.i)} onMouseLeave={() => setHover(null)} />
        ))}
        <text x="100" y="98" textAnchor="middle" className="fill-fg text-[15px] font-semibold">
          {Math.round((arcs[active]?.share ?? 0) * 100)}%
        </text>
        <text x="100" y="114" textAnchor="middle" className="fill-fg-3 text-[9px]">
          {label(rows[active]?.x).slice(0, 18)}
        </text>
      </svg>
      <div className="min-w-0 flex-1 space-y-1 text-[12px]">
        {rows.map((row, i) => (
          <div key={i} className={cn('flex justify-between gap-3', hover === i && 'font-semibold')}>
            <span className="truncate text-fg-2">{label(row.x)}</span>
            <span className="num">{full(Number(row[key] ?? 0), block.unit)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------- files and links */

export function FileCard({ block }: { block: FileBlock }) {
  const Icon = block.format === 'pdf' ? FileText : FileSpreadsheet
  return (
    <motion.a
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      href={block.url}
      target="_blank"
      rel="noreferrer"
      className="card lift flex items-center gap-3 p-3"
    >
      <span className="icon-tile size-11">
        <Icon size={20} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px] font-semibold">{block.filename}</span>
        <span className="block text-[11.5px] text-fg-3">
          {block.format.toUpperCase()} · {(block.size / 1024).toFixed(block.size > 102400 ? 0 : 1)} KB · built from live data
        </span>
      </span>
      <span className="grid size-9 place-items-center rounded-full bg-white/[0.06] text-fg-2">
        <Download size={16} />
      </span>
    </motion.a>
  )
}

/* ---------------------------------------------------------------- actions */

const RISK = {
  write: { label: 'Change', tone: 'bg-white/[0.07] text-fg-2' },
  financial: { label: 'Money or stock', tone: 'bg-peri/30 text-fg' },
  destructive: { label: 'Cannot be undone', tone: 'bg-solid text-on-brand' },
} as const

export function ActionCard({ block, onConfirm, onCancel, busy }: { block: ActionBlock; onConfirm: () => void; onCancel: () => void; busy: boolean }) {
  const risk = RISK[block.risk] ?? RISK.write
  const pending = block.status === 'pending'
  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className={cn('card overflow-hidden', pending && 'ring-2 ring-blue/50')}>
      <div className="flex items-start gap-3 px-3.5 pt-3.5">
        <span className={cn('grid size-9 shrink-0 place-items-center rounded-full', block.risk === 'destructive' ? 'bg-solid text-on-brand' : 'icon-disc')}>
          {block.risk === 'destructive' ? <ShieldAlert size={16} /> : <Check size={16} />}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[13px] font-semibold">{block.label}</span>
            <span className={cn('rounded-full px-2 py-0.5 text-[10.5px] font-semibold', risk.tone)}>{risk.label}</span>
          </div>
          <p className="mt-0.5 text-[13px] text-fg-2">{block.summary}</p>
        </div>
      </div>
      {block.details.fields.length || block.details.lines.length ? (
        <div className="mx-3.5 mt-3 rounded-xl bg-white/[0.035] px-3 py-2 text-[12px]">
          {block.details.fields.map((field) => (
            <div key={field.label} className="flex justify-between gap-4 py-0.5">
              <span className="text-fg-3">{field.label}</span>
              <span className="truncate text-right font-medium">{field.value}</span>
            </div>
          ))}
          {block.details.lines.length ? (
            <div className="mt-1 space-y-1 border-t border-white/6 pt-1.5">
              {block.details.lines.map((line, index) => (
                <div key={index} className="flex flex-wrap gap-x-3 text-fg-2">
                  {Object.entries(line).map(([key, value]) => (
                    <span key={key}>
                      <span className="text-fg-4">{key}</span> {value}
                    </span>
                  ))}
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
      <div className="flex items-center gap-2 px-3.5 py-3">
        {pending ? (
          <>
            <Button kind="primary" small icon={<Check size={14} />} onClick={onConfirm} disabled={busy}>
              Confirm
            </Button>
            <Button small kind="ghost" icon={<X size={14} />} onClick={onCancel} disabled={busy}>
              Cancel
            </Button>
            <span className="ml-auto text-[11.5px] text-fg-3">Nothing changes until you confirm.</span>
          </>
        ) : block.status === 'running' ? (
          <span className="flex items-center gap-2 text-[12.5px] text-fg-2">
            <Loader2 size={14} className="animate-spin" /> Making the change…
          </span>
        ) : block.status === 'done' ? (
          <span className="flex min-w-0 flex-1 items-center gap-2 text-[12.5px] font-medium">
            <CheckCircle2 size={15} className="text-blue" /> {block.result ?? 'Done.'}
            {block.link ? (
              <Link to={block.link.path} className="ml-auto flex items-center gap-1 text-fg-2 hover:text-fg">
                Open {block.link.label} <ArrowRight size={13} />
              </Link>
            ) : null}
          </span>
        ) : block.status === 'failed' ? (
          <span className="flex items-start gap-2 text-[12.5px]">
            <XCircle size={15} className="mt-px shrink-0" /> <span>Not done: {block.error}</span>
          </span>
        ) : (
          <span className="text-[12.5px] text-fg-3">Cancelled. Nothing was changed.</span>
        )}
      </div>
    </motion.div>
  )
}

/* ---------------------------------------------------------------- steps */

export function Steps({ steps, live }: { steps: Step[]; live?: boolean }) {
  const [open, setOpen] = useState(false)
  if (!steps.length) return null
  const running = steps.some((s) => s.ok === undefined)
  const failed = steps.filter((s) => s.ok === false).length
  return (
    <div className="text-[12px]">
      <button onClick={() => setOpen((v) => !v)} className="flex items-center gap-1.5 text-fg-3 hover:text-fg-2">
        {running && live ? <Loader2 size={12} className="animate-spin" /> : failed ? <AlertTriangle size={12} /> : <CheckCircle2 size={12} />}
        {running && live ? `Working: ${steps[steps.length - 1].label}…` : `Used ${steps.length} tool${steps.length === 1 ? '' : 's'}${failed ? ` · ${failed} failed` : ''}`}
        <ChevronDown size={12} className={cn('transition', open && 'rotate-180')} />
      </button>
      {open ? (
        <ul className="mt-1.5 space-y-1 border-l border-white/10 pl-3">
          {steps.map((step, index) => (
            <li key={index} className="flex items-center gap-2 text-fg-2">
              {step.ok === undefined ? <Loader2 size={11} className="animate-spin" /> : step.ok ? <Check size={11} /> : <X size={11} />}
              <span className="font-medium">{step.label}</span>
              {step.rows !== undefined && step.rows !== null ? <span className="text-fg-4">· {step.rows} rows</span> : null}
              {step.pending ? <span className="text-fg-4">· waiting for you</span> : null}
              {step.auto ? <span className="text-fg-4">· made automatically</span> : null}
              {step.error ? <span className="truncate text-fg-4">· {step.error}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

export function BlockView({ block, onConfirm, onCancel, busy }: { block: Block; onConfirm: (id: string) => void; onCancel: (id: string) => void; busy: boolean }) {
  switch (block.type) {
    case 'table':
      return <TableView block={block} />
    case 'chart':
      return <ChartView block={block} />
    case 'file':
      return <FileCard block={block} />
    case 'link':
      return (
        <Link to={block.path} className="btn btn-sm w-fit">
          {block.label} <ArrowRight size={13} />
        </Link>
      )
    case 'action':
      return <ActionCard block={block} busy={busy} onConfirm={() => onConfirm(block.action_id)} onCancel={() => onCancel(block.action_id)} />
  }
}
