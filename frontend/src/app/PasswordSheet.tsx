import { useState } from 'react'
import { api } from '@/api/endpoints'
import { useAction } from '@/api/queries'
import { errorText } from '@/api/client'
import { Button, Field, Notice } from '@/ui/core'
import { Sheet } from '@/ui/overlays'

export function PasswordSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const change = useAction(api.auth.password, { success: 'Password changed. Other devices were signed out.', quiet: true })
  const close = () => {
    setCurrent('')
    setNext('')
    change.reset()
    onClose()
  }
  return (
    <Sheet
      open={open}
      onClose={close}
      width={460}
      title="Change password"
      subtitle="Other devices will be signed out."
      footer={
        <>
          <Button onClick={close}>Cancel</Button>
          <Button kind="primary" busy={change.isPending} disabled={!current || next.length < 10} onClick={() => change.mutate({ current_password: current, new_password: next }, { onSuccess: close })}>
            Change password
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {change.error ? <Notice tone="bad">{errorText(change.error)}</Notice> : null}
        <Field label="Current password">{(props) => <input {...props} className="field" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />}</Field>
        <Field label="New password" hint="At least 10 characters.">{(props) => <input {...props} className="field" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />}</Field>
      </div>
    </Sheet>
  )
}
