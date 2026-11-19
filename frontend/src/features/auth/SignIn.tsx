import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { motion } from 'motion/react'
import { ArrowRight } from 'lucide-react'
import { errorText } from '@/api/client'
import { api } from '@/api/endpoints'
import { Logo } from '@/app/Logo'
import { Aurora } from '@/ui/Aurora'
import { Button, Field, Notice } from '@/ui/core'

export function SignIn() {
  const client = useQueryClient()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      client.setQueryData(['me'], await api.auth.login({ username, password }))
    } catch (cause) {
      setError(errorText(cause))
      setPassword('')
      setBusy(false)
    }
  }

  return (
    <main className="relative grid h-full place-items-center overflow-hidden bg-ink-950 px-4">
      <Aurora />
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(rgb(255_255_255/0.025)_1px,transparent_1px),linear-gradient(90deg,rgb(255_255_255/0.025)_1px,transparent_1px)] bg-[size:56px_56px] [mask-image:radial-gradient(ellipse_at_center,black_20%,transparent_70%)]" />
      <motion.form
        onSubmit={submit}
        noValidate
        initial={{ opacity: 0, y: 14, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
        className="relative w-full max-w-[380px] rounded-2xl bg-ink-850/80 p-8 shadow-[0_40px_120px_-30px_rgb(0_0_0/0.9),0_0_0_1px_rgb(255_255_255/0.08)] backdrop-blur-xl"
      >
        <div className="pointer-events-none absolute inset-x-8 top-0 h-px bg-gradient-to-r from-transparent via-sky/50 to-transparent" />
        <Logo size={40} />
        <h1 className="mt-5 text-[22px] font-semibold tracking-[-0.022em]">Sign in to AEC Desk</h1>
        <p className="mt-1 text-[13px] text-fg-3">Sales, purchasing and stock for your business.</p>
        <div className="mt-6 space-y-4">
          {error ? <Notice tone="bad">{error}</Notice> : null}
          <Field label="Username">
            {(props) => <input {...props} className="field h-10" autoFocus autoComplete="username" autoCapitalize="none" spellCheck={false} value={username} onChange={(e) => setUsername(e.target.value)} />}
          </Field>
          <Field label="Password">
            {(props) => <input {...props} className="field h-10" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />}
          </Field>
          <Button type="submit" kind="primary" className="mt-2 h-10 w-full" busy={busy} disabled={!username || !password}>
            Continue <ArrowRight size={15} />
          </Button>
        </div>
      </motion.form>
      <p className="absolute bottom-6 text-[11.5px] text-fg-4">AEC Desk · Business Manager</p>
    </main>
  )
}
