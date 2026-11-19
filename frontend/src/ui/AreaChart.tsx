import { motion } from 'motion/react'
import { useId, useLayoutEffect, useMemo, useRef, useState } from 'react'

export interface Point {
  label: string
  date: Date
  value: number
  extra?: string
}

function niceTop(max: number) {
  if (max <= 0) return { top: 4, step: 1 }
  const rough = max / 4
  const magnitude = 10 ** Math.floor(Math.log10(rough))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((candidate) => candidate >= rough) ?? rough
  return { top: step * 4, step }
}

/** Monotone cubic path through the points, so the curve never overshoots. */
function smoothPath(points: [number, number][]) {
  if (points.length < 2) return ''
  const slopes: number[] = []
  for (let i = 0; i < points.length - 1; i++) slopes.push((points[i + 1][1] - points[i][1]) / (points[i + 1][0] - points[i][0]))
  const tangents = points.map((_, i) => {
    if (i === 0) return slopes[0]
    if (i === points.length - 1) return slopes[slopes.length - 1]
    if (slopes[i - 1] * slopes[i] <= 0) return 0
    return (slopes[i - 1] + slopes[i]) / 2
  })
  // Fritsch–Carlson: limit tangents so no segment overshoots its ends.
  for (let i = 0; i < slopes.length; i++) {
    if (slopes[i] === 0) {
      tangents[i] = 0
      tangents[i + 1] = 0
      continue
    }
    const a = tangents[i] / slopes[i]
    const b = tangents[i + 1] / slopes[i]
    const h = a * a + b * b
    if (h > 9) {
      const t = 3 / Math.sqrt(h)
      tangents[i] = t * a * slopes[i]
      tangents[i + 1] = t * b * slopes[i]
    }
  }
  let d = `M${points[0][0]},${points[0][1]}`
  for (let i = 0; i < points.length - 1; i++) {
    const [x0, y0] = points[i]
    const [x1, y1] = points[i + 1]
    const dx = (x1 - x0) / 3
    d += ` C${x0 + dx},${y0 + tangents[i] * dx} ${x1 - dx},${y1 - tangents[i + 1] * dx} ${x1},${y1}`
  }
  return d
}

/** One series over time: a light-blue line over a soft fill that draws in.
 *  Hovering shows the day's figure. */
export function AreaChart({ points, format, tick }: { points: Point[]; format: (value: number) => string; tick: (value: number) => string }) {
  const frame = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ width: 0, height: 0 })
  const [hover, setHover] = useState<number | null>(null)
  const id = useId().replace(/:/g, '')

  useLayoutEffect(() => {
    const node = frame.current
    if (!node) return
    const observer = new ResizeObserver(([entry]) => setSize({ width: entry.contentRect.width, height: entry.contentRect.height }))
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  const margin = { top: 12, right: 12, bottom: 24, left: 46 }
  const { top, step } = niceTop(Math.max(...points.map((point) => point.value), 0))
  const plotW = Math.max(0, size.width - margin.left - margin.right)
  const plotH = Math.max(0, size.height - margin.top - margin.bottom)
  const x = (index: number) => margin.left + (points.length <= 1 ? 0 : (index / (points.length - 1)) * plotW)
  const y = (value: number) => margin.top + plotH - (value / top) * plotH

  const { line, area } = useMemo(() => {
    const coords = points.map((point, index) => [x(index), y(point.value)] as [number, number])
    const path = smoothPath(coords)
    return { line: path, area: path ? `${path} L${x(points.length - 1)},${margin.top + plotH} L${x(0)},${margin.top + plotH} Z` : '' }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [points, plotW, plotH, top])

  const ticks = Array.from({ length: Math.round(top / step) + 1 }, (_, index) => index * step)
  const labelEvery = Math.max(1, Math.ceil(points.length / 6))

  function onMove(event: React.MouseEvent<SVGRectElement>) {
    const box = event.currentTarget.getBoundingClientRect()
    const ratio = (event.clientX - box.left) / box.width
    setHover(Math.max(0, Math.min(points.length - 1, Math.round(ratio * (points.length - 1)))))
  }

  const active = hover !== null ? points[hover] : null
  return (
    <div ref={frame} className="relative h-full w-full">
      {size.width > 0 ? (
        <svg width={size.width} height={size.height} className="block overflow-visible">
          <defs>
            <linearGradient id={`fill${id}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="#7cc4ff" stopOpacity="0.28" />
              <stop offset="1" stopColor="#7cc4ff" stopOpacity="0" />
            </linearGradient>
          </defs>
          {ticks.map((value) => (
            <g key={value}>
              <line x1={margin.left} x2={size.width - margin.right} y1={y(value)} y2={y(value)} stroke="rgba(255,255,255,0.06)" strokeDasharray={value === 0 ? undefined : '2 4'} />
              <text x={margin.left - 10} y={y(value)} dy="0.32em" textAnchor="end" className="num fill-fg-4 text-[10.5px]">
                {tick(value)}
              </text>
            </g>
          ))}
          {points.map((point, index) =>
            index % labelEvery === 0 || index === points.length - 1 ? (
              <text key={point.label} x={x(index)} y={size.height - 6} textAnchor={index === 0 ? 'start' : index === points.length - 1 ? 'end' : 'middle'} className="fill-fg-4 text-[10.5px]">
                {index === points.length - 1 ? 'Today' : point.label}
              </text>
            ) : null,
          )}
          <motion.path key={`a${top}${points.length}`} d={area} fill={`url(#fill${id})`} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.9, delay: 0.3 }} />
          <motion.path
            key={`l${top}${points.length}`}
            d={line}
            fill="none"
            stroke="#7cc4ff"
            strokeWidth={2}
            strokeLinecap="round"
            initial={{ pathLength: 0 }}
            animate={{ pathLength: 1 }}
            transition={{ duration: 1.2, ease: [0.22, 1, 0.36, 1] }}
          />
          {active && hover !== null ? (
            <g pointerEvents="none">
              <line x1={x(hover)} x2={x(hover)} y1={margin.top} y2={margin.top + plotH} stroke="rgba(255,255,255,0.18)" />
              <circle cx={x(hover)} cy={y(active.value)} r={4.5} fill="#08090b" stroke="#7cc4ff" strokeWidth={2} />
            </g>
          ) : null}
          <rect x={margin.left} y={margin.top} width={plotW} height={plotH} fill="transparent" onMouseMove={onMove} onMouseLeave={() => setHover(null)} />
        </svg>
      ) : null}
      {active && hover !== null ? (
        <div
          className="pointer-events-none absolute z-10 min-w-[140px] -translate-x-1/2 -translate-y-full rounded-lg bg-ink-700/95 px-3 py-2 text-[12px] shadow-[0_10px_30px_rgb(0_0_0/0.5),0_0_0_1px_rgb(255_255_255/0.08)] backdrop-blur"
          style={{ left: Math.min(Math.max(x(hover), 80), size.width - 80), top: y(active.value) - 12 }}
        >
          <div className="text-fg-3">{active.date.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })}</div>
          <div className="num text-[15px] font-semibold">{format(active.value)}</div>
          {active.extra ? <div className="text-fg-3">{active.extra}</div> : null}
        </div>
      ) : null}
    </div>
  )
}
