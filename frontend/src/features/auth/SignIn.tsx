import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { motion } from 'motion/react'
import { ArrowRight } from 'lucide-react'
import { errorText } from '@/api/client'
import { api } from '@/api/endpoints'
import { Logo } from '@/app/Logo'
import { Backdrop, Contours } from '@/ui/art'
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
    <main className="relative isolate grid h-full place-items-center overflow-y-auto px-4 py-6">
      <Backdrop />
      <motion.div
        initial={{ opacity: 0, y: 14, scale: 0.985 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.55, ease: [0.22, 1, 0.36, 1] }}
        className="grid w-full max-w-[880px] grid-cols-[1.05fr_1fr] gap-4 max-md:max-w-[400px] max-md:grid-cols-1"
      >
        <section className="pane-contrast relative flex min-h-[460px] [&>*:not(svg)]:relative flex-col justify-between overflow-hidden p-9 max-md:hidden">
          <Contours className="absolute -right-[30%] -bottom-[45%] size-[130%] text-[rgb(255_255_255/0.1)]" rings={14} seed={4} />
          <div className="flex items-center gap-2.5">
            <Logo size={30} tile="fill-[#fff]" />
            <span className="text-[19px] font-bold tracking-[-0.035em]">AEC Desk</span>
          </div>
          <div className="flex h-[150px] items-end gap-3" aria-hidden="true">
            {[52, 74, 60, 92, 70, 84].map((height, index) => (
              <motion.span
                key={index}
                className="relative flex-1 overflow-hidden rounded-[12px] bg-peri"
                initial={{ height: 0 }}
                animate={{ height: `${height}%` }}
                transition={{ duration: 0.9, delay: 0.2 + index * 0.07, ease: [0.22, 1, 0.36, 1] }}
              >
                <motion.span className="absolute inset-x-0 bottom-0 rounded-[12px] bg-blue" initial={{ height: 0 }} animate={{ height: `${30 + ((index * 17) % 35)}%` }} transition={{ duration: 0.9, delay: 0.6 + index * 0.07, ease: [0.22, 1, 0.36, 1] }} />
              </motion.span>
            ))}
          </div>
          <div>
            <h2 className="text-[26px] leading-tight font-semibold tracking-[-0.03em]">Sales, purchasing and stock in one place.</h2>
            <p className="mt-2 text-[13px] opacity-55">Know what is owed, what is ready and what to buy, every day.</p>
          </div>
        </section>
        <form onSubmit={submit} noValidate className="pane flex flex-col justify-center p-9 max-md:p-7">
          <div className="md:hidden">
            <Logo size={36} />
          </div>
          <h1 className="text-[26px] font-semibold tracking-[-0.03em] max-md:mt-5">Welcome back</h1>
          <p className="mt-1 text-[13px] text-fg-3">Sign in to continue to AEC Desk.</p>
          <div className="mt-7 space-y-4">
            {error ? <Notice tone="bad">{error}</Notice> : null}
            <Field label="Username">
              {(props) => <input {...props} className="field h-11" autoFocus autoComplete="username" autoCapitalize="none" spellCheck={false} value={username} onChange={(e) => setUsername(e.target.value)} />}
            </Field>
            <Field label="Password">
              {(props) => <input {...props} className="field h-11" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />}
            </Field>
            <Button type="submit" kind="primary" className="mt-3 h-11 w-full" busy={busy} disabled={!username || !password}>
              Continue <ArrowRight size={15} />
            </Button>
          </div>
        </form>
      </motion.div>
    </main>
  )
}
