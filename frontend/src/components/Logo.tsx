/** The product mark: three rising stock bars on the accent squircle. */
export function LogoMark({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" className="logo-mark">
      <defs>
        <linearGradient id="logo-fill" x1="0" y1="0" x2="0.4" y2="1">
          <stop offset="0" stopColor="#4c9bff" />
          <stop offset="1" stopColor="#0058d0" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="8.5" fill="url(#logo-fill)" />
      <rect x="7.5" y="16" width="4.4" height="9" rx="2.2" fill="#fff" fillOpacity="0.62" />
      <rect x="13.8" y="11.5" width="4.4" height="13.5" rx="2.2" fill="#fff" fillOpacity="0.82" />
      <rect x="20.1" y="7" width="4.4" height="18" rx="2.2" fill="#fff" />
    </svg>
  )
}
