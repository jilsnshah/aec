import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { CloseIcon, ErrorIcon, InfoIcon, SuccessIcon } from './icons'
import { Button } from './primitives'

type ToastKind = 'success' | 'error' | 'info'

interface ToastAction {
  label: string
  onClick: () => void
}

interface ToastItem {
  id: number
  kind: ToastKind
  title: string
  message?: ReactNode
  action?: ToastAction
  leaving?: boolean
}

interface ToastApi {
  success: (title: string, message?: ReactNode, action?: ToastAction) => void
  error: (title: string, message?: ReactNode, action?: ToastAction) => void
  info: (title: string, message?: ReactNode, action?: ToastAction) => void
}

const ToastContext = createContext<ToastApi | null>(null)

const ICONS = { success: SuccessIcon, error: ErrorIcon, info: InfoIcon }
const LIFETIME_MS = 5200
const LEAVE_MS = 180

/** Transient confirmation that something happened, without pushing the page
 *  around. Errors that belong to a form stay inline in that form. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([])
  const nextId = useRef(1)

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.map((toast) => (toast.id === id ? { ...toast, leaving: true } : toast)))
    window.setTimeout(() => setToasts((current) => current.filter((toast) => toast.id !== id)), LEAVE_MS)
  }, [])

  const push = useCallback(
    (kind: ToastKind, title: string, message?: ReactNode, action?: ToastAction) => {
      const id = nextId.current++
      // Keep the stack short: the oldest goes when a fourth arrives.
      setToasts((current) => [...current.slice(-2), { id, kind, title, message, action }])
      window.setTimeout(() => dismiss(id), kind === 'error' ? LIFETIME_MS * 1.6 : LIFETIME_MS)
    },
    [dismiss],
  )

  const api = useMemo<ToastApi>(
    () => ({
      success: (title, message, action) => push('success', title, message, action),
      error: (title, message, action) => push('error', title, message, action),
      info: (title, message, action) => push('info', title, message, action),
    }),
    [push],
  )

  return (
    <ToastContext.Provider value={api}>
      {children}
      {createPortal(
        <div className="toast-region" aria-live="polite" aria-relevant="additions">
          {toasts.map((toast) => {
            const Icon = ICONS[toast.kind]
            return (
              <div
                key={toast.id}
                className={`toast toast--${toast.kind}${toast.leaving ? ' is-leaving' : ''}`}
                role={toast.kind === 'error' ? 'alert' : 'status'}
              >
                <Icon size={19} className="toast__icon" aria-hidden="true" />
                <div className="toast__body">
                  <div className="toast__title">{toast.title}</div>
                  {toast.message ? <div className="toast__message">{toast.message}</div> : null}
                  {toast.action ? (
                    <div className="toast__action">
                      <Button
                        size="sm"
                        variant="tinted"
                        onClick={() => {
                          toast.action?.onClick()
                          dismiss(toast.id)
                        }}
                      >
                        {toast.action.label}
                      </Button>
                    </div>
                  ) : null}
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  iconOnly
                  className="toast__close"
                  icon={<CloseIcon size={14} />}
                  aria-label="Dismiss"
                  onClick={() => dismiss(toast.id)}
                />
              </div>
            )
          })}
        </div>,
        document.body,
      )}
    </ToastContext.Provider>
  )
}

export function useToast(): ToastApi {
  const api = useContext(ToastContext)
  if (!api) throw new Error('useToast must be used inside <ToastProvider>')
  return api
}
