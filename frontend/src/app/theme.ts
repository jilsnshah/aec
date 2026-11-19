import { useEffect, useState } from 'react'

export type Theme = 'light' | 'dark'

const KEY = 'aec-theme'

function current(): Theme {
  return document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light'
}

/** Light or dark. The choice is kept on this computer; until one is made the
 *  system setting decides (index.html applies it before the first paint). */
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(current)
  useEffect(() => {
    const root = document.documentElement
    root.dataset.theme = theme
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#08090c' : '#dfe5f6')
  }, [theme])
  function choose(next: Theme) {
    try {
      localStorage.setItem(KEY, next)
    } catch {
      /* private window: the choice lasts for this visit only */
    }
    setTheme(next)
    window.dispatchEvent(new CustomEvent('aec:theme', { detail: next }))
  }
  useEffect(() => {
    const sync = (event: Event) => setTheme((event as CustomEvent<Theme>).detail)
    window.addEventListener('aec:theme', sync)
    return () => window.removeEventListener('aec:theme', sync)
  }, [])
  return { theme, setTheme: choose, toggle: () => choose(theme === 'dark' ? 'light' : 'dark') }
}
