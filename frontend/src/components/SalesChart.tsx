import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { DailySales } from '../api/types'
import { formatCompactMoney, formatMoney } from '../lib/format'
import { Segmented } from './primitives'

type Measure = 'booked' | 'delivered'

const HEIGHT = 220
const MARGIN = { top: 12, right: 8, bottom: 26, left: 52 }
const GAP = 2
const RADIUS = 4

const DAY_FORMAT = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' })
const LONG_DAY_FORMAT = new Intl.DateTimeFormat(undefined, {
  weekday: 'short',
  month: 'short',
  day: 'numeric',
})

/** A calendar day from the API ("2026-10-29") as a local date, not UTC. */
function parseDay(value: string): Date {
  const [year, month, day] = value.split('-').map(Number)
  return new Date(year, month - 1, day)
}

/** A round axis maximum and step: 0, 5K, 10K, 15K rather than 0, 4.3K, 8.7K. */
function niceScale(max: number, ticks = 4): { top: number; step: number } {
  if (max <= 0) return { top: ticks, step: 1 }
  const rough = max / ticks
  const magnitude = 10 ** Math.floor(Math.log10(rough))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((candidate) => candidate >= rough) ?? rough
  return { top: step * ticks, step }
}

/** A bar with rounded data-end and a square base on the axis. */
function barPath(x: number, y: number, width: number, height: number): string {
  const r = Math.min(RADIUS, width / 2, height)
  return [
    `M${x},${y + height}`,
    `V${y + r}`,
    `Q${x},${y} ${x + r},${y}`,
    `H${x + width - r}`,
    `Q${x + width},${y} ${x + width},${y + r}`,
    `V${y + height}`,
    'Z',
  ].join(' ')
}

/** Value booked or delivered per day: one series at a time, so one colour and
 *  one axis. Every bar answers on hover and to the arrow keys; a hidden table
 *  carries the same numbers for screen readers. */
export function SalesChart({ series }: { series: DailySales[] }) {
  const [measure, setMeasure] = useState<Measure>('booked')
  const [active, setActive] = useState<number | null>(null)
  const frame = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)

  useLayoutEffect(() => {
    const node = frame.current
    if (!node) return
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  const values = useMemo(
    () => series.map((day) => Number(measure === 'booked' ? day.booked_value : day.delivered_value)),
    [series, measure],
  )
  const total = values.reduce((sum, value) => sum + value, 0)
  const orders = series.reduce((sum, day) => sum + day.orders, 0)
  const tradingDays = values.filter((value) => value > 0).length
  const { top, step } = niceScale(Math.max(...values, 0))

  const plotWidth = Math.max(0, width - MARGIN.left - MARGIN.right)
  const plotHeight = HEIGHT - MARGIN.top - MARGIN.bottom
  const band = series.length ? plotWidth / series.length : 0
  const barWidth = Math.max(1, band - GAP)
  const y = (value: number) => MARGIN.top + plotHeight - (value / top) * plotHeight
  const ticks = Array.from({ length: Math.round(top / step) + 1 }, (_, index) => index * step)

  const label = measure === 'booked' ? 'Booked' : 'Delivered'
  const hovered = active !== null ? series[active] : null

  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
      event.preventDefault()
      const delta = event.key === 'ArrowRight' ? 1 : -1
      setActive((current) => {
        const start = current ?? (delta > 0 ? -1 : series.length)
        return Math.min(series.length - 1, Math.max(0, start + delta))
      })
    } else if (event.key === 'Escape') {
      setActive(null)
    }
  }

  return (
    <section className="card chart-card">
      <header className="chart-card__head">
        <div>
          <h2 className="card__title">Sales</h2>
          <p className="chart-card__hero">{formatMoney(total)}</p>
          <p className="chart-card__sub">
            {label.toLowerCase()} in the last {series.length} days
            {measure === 'booked'
              ? ` · ${orders} order${orders === 1 ? '' : 's'}`
              : ` · ${tradingDays} day${tradingDays === 1 ? '' : 's'} with deliveries`}
          </p>
        </div>
        <Segmented
          label="Measure"
          small
          value={measure}
          onChange={(next) => {
            setMeasure(next)
            setActive(null)
          }}
          options={[
            { value: 'booked', label: 'Booked', title: 'Value of orders placed, before tax' },
            { value: 'delivered', label: 'Delivered', title: 'Value of goods handed over' },
          ]}
        />
      </header>

      <div className="chart" ref={frame}>
        {width > 0 ? (
          <svg
            width={width}
            height={HEIGHT}
            role="img"
            aria-label={`${label} value per day for the last ${series.length} days, ${formatMoney(total)} in total. Use the arrow keys to read each day.`}
            tabIndex={0}
            onKeyDown={onKeyDown}
            onBlur={() => setActive(null)}
            onPointerLeave={() => setActive(null)}
          >
            {ticks.map((tick) => (
              <g key={tick}>
                <line
                  className={tick === 0 ? 'chart__baseline' : 'chart__grid'}
                  x1={MARGIN.left}
                  x2={width - MARGIN.right}
                  y1={y(tick)}
                  y2={y(tick)}
                />
                <text className="chart__tick" x={MARGIN.left - 10} y={y(tick)} dy="0.32em" textAnchor="end">
                  {tick === 0 ? '0' : formatCompactMoney(tick)}
                </text>
              </g>
            ))}

            {series.map((day, index) => {
              const value = values[index]
              const x = MARGIN.left + index * band + GAP / 2
              const height = (value / top) * plotHeight
              const isLast = index === series.length - 1
              const showLabel = isLast || (series.length - 1 - index) % 7 === 0
              return (
                <g key={day.date}>
                  {value > 0 ? (
                    <path
                      className={`chart__bar${active === index ? ' is-active' : ''}${active !== null && active !== index ? ' is-dimmed' : ''}`}
                      d={barPath(x, y(value), barWidth, Math.max(height, 1))}
                      style={{ animationDelay: `${index * 12}ms` }}
                    />
                  ) : null}
                  {showLabel ? (
                    <text
                      className="chart__tick"
                      x={x + barWidth / 2}
                      y={HEIGHT - 6}
                      textAnchor={isLast ? 'end' : 'middle'}
                    >
                      {isLast ? 'Today' : DAY_FORMAT.format(parseDay(day.date))}
                    </text>
                  ) : null}
                  {/* The hit area is the whole day's column, not the painted bar. */}
                  <rect
                    className="chart__hit"
                    x={MARGIN.left + index * band}
                    y={MARGIN.top}
                    width={band}
                    height={plotHeight}
                    onPointerEnter={() => setActive(index)}
                    onPointerMove={() => setActive(index)}
                  />
                </g>
              )
            })}
          </svg>
        ) : (
          <div style={{ height: HEIGHT }} />
        )}

        {hovered && active !== null ? (
          <div
            className="chart__tooltip"
            role="status"
            style={{
              left: Math.min(
                Math.max(MARGIN.left + active * band + band / 2, 84),
                Math.max(84, width - 84),
              ),
              top: Math.max(y(values[active]) - 10, MARGIN.top + 40),
            }}
          >
            <strong>{formatMoney(values[active])}</strong>
            <span>
              {label} · {LONG_DAY_FORMAT.format(parseDay(hovered.date))}
            </span>
            {measure === 'booked' ? (
              <span>
                {hovered.orders} order{hovered.orders === 1 ? '' : 's'}
              </span>
            ) : null}
          </div>
        ) : null}
      </div>

      <table className="visually-hidden">
        <caption>{label} value per day</caption>
        <thead>
          <tr>
            <th>Day</th>
            <th>{label}</th>
            <th>Orders</th>
          </tr>
        </thead>
        <tbody>
          {series.map((day, index) => (
            <tr key={day.date}>
              <td>{LONG_DAY_FORMAT.format(parseDay(day.date))}</td>
              <td>{formatMoney(values[index])}</td>
              <td>{day.orders}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
