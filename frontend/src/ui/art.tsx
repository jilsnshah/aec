import { useMemo } from 'react'
import { cn } from '@/lib/cn'

/** The window's backdrop: soft colour fields that drift very slowly, under a
 *  fine grain. Cards are frosted glass, so the colour shows faintly through. */
export function Backdrop() {
  return (
    <div className="pointer-events-none fixed inset-0 -z-10 overflow-hidden" aria-hidden="true">
      <div className="absolute -top-[22%] -right-[12%] h-[75vh] w-[55vw] rounded-full bg-[var(--blob-1)] blur-[90px] animate-aurora" />
      <div className="absolute top-[38%] -left-[18%] h-[70vh] w-[50vw] rounded-full bg-[var(--blob-2)] blur-[100px] animate-aurora [animation-delay:-7s]" />
      <div className="absolute -bottom-[30%] left-[30%] h-[60vh] w-[45vw] rounded-full bg-[var(--blob-3)] blur-[110px] animate-aurora [animation-delay:-13s]" />
      <Contours className="absolute -top-[18%] -right-[8%] h-[95vh] w-[95vh] text-[var(--contour)]" rings={16} seed={2} />
      <div className="grain absolute inset-0" />
    </div>
  )
}

/** Topographic contour lines: concentric rings with a gentle, fixed wobble.
 *  Pure decoration, drawn in currentColor. */
export function Contours({ className, rings = 12, seed = 1, strokeWidth = 1 }: { className?: string; rings?: number; seed?: number; strokeWidth?: number }) {
  const paths = useMemo(() => {
    const out: string[] = []
    const steps = 96
    for (let ring = 0; ring < rings; ring++) {
      const base = 14 + ring * (84 / rings)
      const points: [number, number][] = []
      for (let step = 0; step < steps; step++) {
        const angle = (step / steps) * Math.PI * 2
        const wobble =
          Math.sin(angle * 3 + seed + ring * 0.35) * 0.55 +
          Math.sin(angle * 5 - seed * 1.7 - ring * 0.22) * 0.3 +
          Math.sin(angle * 2 + seed * 0.6) * 0.45
        const radius = base + wobble * (2.2 + ring * 0.42)
        points.push([100 + Math.cos(angle) * radius, 100 + Math.sin(angle) * radius])
      }
      const mid = (a: [number, number], b: [number, number]) => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]
      let d = ''
      for (let i = 0; i < steps; i++) {
        const current = points[i]
        const next = points[(i + 1) % steps]
        const [mx, my] = mid(current, next)
        if (i === 0) {
          const [sx, sy] = mid(points[steps - 1], current)
          d += `M${sx.toFixed(2)} ${sy.toFixed(2)}`
        }
        d += `Q${current[0].toFixed(2)} ${current[1].toFixed(2)} ${mx.toFixed(2)} ${my.toFixed(2)}`
      }
      out.push(d + 'Z')
    }
    return out
  }, [rings, seed])
  return (
    <svg viewBox="0 0 200 200" className={cn('pointer-events-none', className)} aria-hidden="true" fill="none" stroke="currentColor" strokeWidth={strokeWidth} vectorEffect="non-scaling-stroke">
      {paths.map((d, index) => (
        <path key={index} d={d} vectorEffect="non-scaling-stroke" opacity={0.35 + (index / rings) * 0.65} />
      ))}
    </svg>
  )
}

/** A soft pool of light in one corner of a surface. */
export function Glow({ className }: { className?: string }) {
  return <div className={cn('pointer-events-none absolute rounded-full blur-3xl', className)} aria-hidden="true" />
}

/** Contour art fading in from the right edge of a header. */
export function HeaderArt({ seed = 3 }: { seed?: number }) {
  return (
    <div className="pointer-events-none absolute inset-y-0 right-0 w-[55%] [mask-image:linear-gradient(90deg,transparent,black_55%)]" aria-hidden="true">
      <Contours className="absolute top-1/2 -right-[12%] size-[560px] -translate-y-1/2 text-peri/45" rings={14} seed={seed} />
      <div className="absolute -top-16 right-[8%] h-40 w-64 rounded-full bg-peri/20 blur-3xl" />
    </div>
  )
}
