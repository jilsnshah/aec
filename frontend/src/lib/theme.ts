import { useEffect, useState } from 'react'

export type ThemeChoice = 'light' | 'dark' | 'system'

const STORAGE_KEY = 'aec-theme'

function read(): ThemeChoice {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (stored === 'light' || stored === 'dark' || stored === 'system') return stored
  } catch {
    // Storage can be unavailable (private mode, blocked site data); fall back.
  }
  return 'system'
}

function apply(choice: ThemeChoice) {
  const root = document.documentElement
  if (choice === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', choice)
}

/** Light, dark, or follow the operating system — remembered per browser. */
export function useTheme(): [ThemeChoice, (choice: ThemeChoice) => void] {
  const [choice, setChoice] = useState<ThemeChoice>(read)

  useEffect(() => {
    apply(choice)
    try {
      window.localStorage.setItem(STORAGE_KEY, choice)
    } catch {
      // Not persisting is fine; the choice still applies to this session.
    }
  }, [choice])

  return [choice, setChoice]
}
