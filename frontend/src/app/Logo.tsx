import { useId } from 'react'

/** The mark: a light-blue diamond of four stacked tiles. */
export function Logo({ size = 28 }: { size?: number }) {
  const id = useId().replace(/:/g, '')
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <defs>
        <linearGradient id={`g${id}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#a8d8ff" />
          <stop offset="1" stopColor="#2f80ed" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill="#101216" />
      <rect x="0.5" y="0.5" width="31" height="31" rx="8.5" fill="none" stroke="rgba(255,255,255,0.1)" />
      <path d="M16 6.5 25.5 16 16 25.5 6.5 16Z" fill={`url(#g${id})`} />
      <path d="M16 11 21 16 16 21 11 16Z" fill="#101216" />
      <path d="M16 13.6 18.4 16 16 18.4 13.6 16Z" fill="#fff" />
    </svg>
  )
}
