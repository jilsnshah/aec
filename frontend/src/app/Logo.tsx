import { useId } from 'react'

/** The mark: a blue diamond on a black tile (white in dark mode). */
export function Logo({ size = 28, tile = 'fill-contrast' }: { size?: number; tile?: string }) {
  const id = useId().replace(/:/g, '')
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <defs>
        <linearGradient id={`g${id}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#5a9bff" />
          <stop offset="1" stopColor="#1a56ea" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="10" fill={tile === 'fill-contrast' ? `url(#g${id})` : undefined} className={tile === 'fill-contrast' ? undefined : tile} />
      <path d="M16 6.5 25.5 16 16 25.5 6.5 16Z" fill={tile === 'fill-contrast' ? '#fff' : `url(#g${id})`} />
      <path d="M16 11 21 16 16 21 11 16Z" fill={tile === 'fill-contrast' ? `url(#g${id})` : undefined} className={tile === 'fill-contrast' ? undefined : tile} />
      <path d="M16 13.6 18.4 16 16 18.4 13.6 16Z" fill={tile === 'fill-contrast' ? '#fff' : `url(#g${id})`} />
    </svg>
  )
}

/** The name as it appears in the top bar. */
export function Wordmark() {
  return (
    <div className="flex items-center gap-2.5">
      <Logo size={30} />
      <span className="text-[19px] font-bold tracking-[-0.035em]">AEC Desk</span>
    </div>
  )
}
