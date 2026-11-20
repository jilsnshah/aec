import type { ReactNode } from 'react'

export function Loading() {
  return <p className="py-16 text-center text-fg-3">Loading…</p>
}

export function Empty({ text, icon }: { text: string; icon?: ReactNode }) {
  return (
    <div className="card p-8 text-center text-[13.5px] text-fg-3">
      {icon ? <span className="icon-tile mx-auto mb-3 size-11">{icon}</span> : null}
      {text}
    </div>
  )
}
