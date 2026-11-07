import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import { useAuth } from '../lib/auth'
import { useTheme, type ThemeChoice } from '../lib/theme'
import { CommandPalette } from './CommandPalette'
import {
  DarkThemeIcon,
  LightThemeIcon,
  MenuIcon,
  SearchIcon,
  SystemThemeIcon,
  PasswordIcon,
  SignOutIcon,
} from './icons'
import { LogoMark } from './Logo'
import { NAV, titleForPath } from './navigation'
import { Button, Kbd, Notice } from './primitives'
import { Avatar } from './collection'
import { ActionMenu, Dialog, DialogCancel } from './overlays'
import { Field } from './forms'
import { useToast } from './toast'

const IS_MAC = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)

const THEMES: { value: ThemeChoice; label: string; icon: typeof SystemThemeIcon }[] = [
  { value: 'light', label: 'Light', icon: LightThemeIcon },
  { value: 'system', label: 'Match system', icon: SystemThemeIcon },
  { value: 'dark', label: 'Dark', icon: DarkThemeIcon },
]

/** Live counts beside the navigation items that represent work waiting. */
interface Counts {
  owed: number
  awaiting: boolean
}

export default function Layout() {
  const location = useLocation()
  const [theme, setTheme] = useTheme()
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [counts, setCounts] = useState<Counts | null>(null)

  // Close the mobile drawer whenever the route changes.
  useEffect(() => setDrawerOpen(false), [location.pathname])

  // Refresh the sidebar's work counts as the user moves around.
  useEffect(() => {
    let cancelled = false
    api.inventory
      .summary()
      .then((summary) => {
        if (cancelled) return
        setCounts({
          owed: summary.open_orders,
          awaiting: Number(summary.total_unallocated_quantity) > 0,
        })
      })
      .catch(() => {
        // A count is a convenience; the pages report their own errors.
        if (!cancelled) setCounts(null)
      })
    return () => {
      cancelled = true
    }
  }, [location.pathname])

  // ⌘K opens the command menu; / jumps to the page's search field.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setPaletteOpen((open) => !open)
        return
      }
      const target = event.target as HTMLElement
      const typing =
        target.closest('input, textarea, select, [contenteditable="true"]') !== null
      if (event.key === '/' && !typing && !paletteOpen) {
        const search = document.querySelector<HTMLInputElement>('[data-page-search]')
        if (search) {
          event.preventDefault()
          search.focus()
          search.select()
        }
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [paletteOpen])

  return (
    <div className={`shell${drawerOpen ? ' is-drawer-open' : ''}`}>
      <a className="skip-link" href="#main">
        Skip to content
      </a>

      <nav className="sidebar" aria-label="Main">
        <NavLink to="/" className="sidebar__brand" aria-label="AEC — Overview">
          <LogoMark size={30} />
          <span>
            <span className="sidebar__brand-name">AEC</span>
            <span className="sidebar__brand-sub">
              Business Manager
            </span>
          </span>
        </NavLink>

        <button type="button" className="sidebar__search" onClick={() => setPaletteOpen(true)}>
          <SearchIcon size={14} aria-hidden="true" />
          <span>Search</span>
          <Kbd>{IS_MAC ? '⌘K' : 'Ctrl K'}</Kbd>
        </button>

        {NAV.map((section, index) => (
          <div className="sidebar__section" key={section.heading ?? index}>
            {section.heading ? <div className="sidebar__heading">{section.heading}</div> : null}
            <div className="sidebar__nav">
              {section.items.map((item) => {
                const Icon = item.icon
                const showCount = item.to === '/pending-fulfilment' && counts && counts.owed > 0
                return (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.end}
                    className={({ isActive }) => `sidebar__link${isActive ? ' is-active' : ''}`}
                  >
                    <Icon size={17} strokeWidth={1.75} className="sidebar__icon" aria-hidden="true" />
                    {item.label}
                    {showCount ? (
                      <span
                        className={`sidebar__count${counts?.awaiting ? ' sidebar__count--alert' : ''}`}
                        title={`${counts?.owed} order(s) still to deliver`}
                      >
                        {counts?.owed}
                      </span>
                    ) : null}
                  </NavLink>
                )
              })}
            </div>
          </div>
        ))}

        <div className="sidebar__footer">
          <UserMenu />
          <div className="theme-switch" role="group" aria-label="Appearance">
            {THEMES.map((option) => {
              const Icon = option.icon
              return (
                <button
                  key={option.value}
                  type="button"
                  aria-pressed={theme === option.value}
                  aria-label={option.label}
                  title={option.label}
                  onClick={() => setTheme(option.value)}
                >
                  <Icon size={14} aria-hidden="true" />
                </button>
              )
            })}
          </div>
        </div>
      </nav>

      <div className="shell__scrim" onClick={() => setDrawerOpen(false)} aria-hidden="true" />

      <div className="main">
        <div className="mobile-bar">
          <Button
            variant="ghost"
            iconOnly
            icon={<MenuIcon size={19} />}
            aria-label="Open navigation"
            onClick={() => setDrawerOpen(true)}
          />
          <span className="mobile-bar__title">{titleForPath(location.pathname)}</span>
          <Button
            variant="ghost"
            iconOnly
            icon={<SearchIcon size={18} />}
            aria-label="Search"
            onClick={() => setPaletteOpen(true)}
          />
        </div>
        <main id="main">
          <Outlet />
        </main>
      </div>

      {paletteOpen ? (
        <CommandPalette onClose={() => setPaletteOpen(false)} onTheme={setTheme} />
      ) : null}
    </div>
  )
}

/** Who is signed in, with changing the password and signing out. */
function UserMenu() {
  const { user, signOut } = useAuth()
  const [changing, setChanging] = useState(false)
  if (!user) return null
  return (
    <div className="user-row">
      <Avatar name={user.username} seed={user.username} size="sm" />
      <span className="user-row__name">{user.username}</span>
      <ActionMenu
        label="Account"
        items={[
          { label: 'Change password', icon: <PasswordIcon size={15} />, onSelect: () => setChanging(true) },
          { label: 'Sign out', icon: <SignOutIcon size={15} />, onSelect: () => void signOut(), separatorBefore: true },
        ]}
      />
      {changing ? <ChangePassword onClose={() => setChanging(false)} /> : null}
    </div>
  )
}

function ChangePassword({ onClose }: { onClose: () => void }) {
  const toast = useToast()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    setBusy(true)
    setError(null)
    try {
      await api.auth.changePassword(current, next)
      toast.success('Password changed', 'Other devices have been signed out.')
      onClose()
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : String(cause))
      setBusy(false)
    }
  }

  return (
    <Dialog
      title="Change password"
      onClose={onClose}
      busy={busy}
      footer={
        <>
          <DialogCancel />
          <Button variant="primary" busy={busy} disabled={!current || next.length < 10} onClick={submit}>
            Change password
          </Button>
        </>
      }
    >
      <div className="stack">
        {error ? <Notice kind="error">{error}</Notice> : null}
        <Field label="Current password">
          {(props) => <input {...props} type="password" autoComplete="current-password" value={current} onChange={(event) => setCurrent(event.target.value)} />}
        </Field>
        <Field label="New password" hint="At least 10 characters.">
          {(props) => <input {...props} type="password" autoComplete="new-password" value={next} onChange={(event) => setNext(event.target.value)} />}
        </Field>
      </div>
    </Dialog>
  )
}
