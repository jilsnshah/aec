import { useState } from 'react'
import { ApiError, api } from '../api/client'
import { Button, Field, Notice } from '../components/ui'
import { LogoMark } from '../components/Logo'
import type { SignedInUser } from '../lib/auth'

export default function SignInPage({ onSignedIn }: { onSignedIn: (user: SignedInUser) => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      onSignedIn(await api.auth.login(username, password))
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : String(cause))
      setPassword('')
      setBusy(false)
    }
  }

  return (
    <main className="signin">
      <form className="signin__card" onSubmit={submit} noValidate>
        <div className="signin__brand">
          <LogoMark size={40} />
          <div>
            <h1 className="signin__title">AEC</h1>
            <p className="signin__subtitle">Business Manager</p>
          </div>
        </div>
        {error ? <Notice kind="error">{error}</Notice> : null}
        <Field label="Username">
          {(props) => (
            <input {...props} autoFocus autoComplete="username" autoCapitalize="none" spellCheck={false}
              value={username} onChange={(event) => setUsername(event.target.value)} />
          )}
        </Field>
        <Field label="Password">
          {(props) => (
            <input {...props} type="password" autoComplete="current-password"
              value={password} onChange={(event) => setPassword(event.target.value)} />
          )}
        </Field>
        <Button type="submit" variant="primary" block busy={busy} disabled={!username || !password}>
          Sign in
        </Button>
      </form>
    </main>
  )
}
