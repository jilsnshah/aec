import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { createPortal } from 'react-dom'
import { CloseIcon, MoreIcon, WarningIcon } from './icons'
import { Button, Notice, type ButtonVariant } from './primitives'

/* -------------------------------------------------------------------------- */
/* Overlay plumbing                                                            */
/* -------------------------------------------------------------------------- */

/** Exit animations run for this long before an overlay unmounts. */
const EXIT_MS = 170

/** Overlays open in a stack; only the topmost one reacts to Escape. */
const stack: string[] = []
let scrollLocks = 0

function useOverlayLayer(onEscape: () => void) {
  const id = useId()
  const escape = useRef(onEscape)
  escape.current = onEscape

  useEffect(() => {
    stack.push(id)
    scrollLocks += 1
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape' && stack[stack.length - 1] === id) {
        event.stopPropagation()
        escape.current()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      const index = stack.indexOf(id)
      if (index >= 0) stack.splice(index, 1)
      scrollLocks -= 1
      if (scrollLocks <= 0) {
        scrollLocks = 0
        document.body.style.overflow = previousOverflow === 'hidden' ? '' : previousOverflow
      }
    }
  }, [id])
}

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

/** Keep Tab inside the overlay, focus something sensible on open, and give
 *  focus back to whatever had it when the overlay closes. */
function useFocusTrap(container: React.RefObject<HTMLElement>) {
  useLayoutEffect(() => {
    const root = container.current
    if (!root) return
    const previous = document.activeElement as HTMLElement | null

    const preferred =
      root.querySelector<HTMLElement>('[data-autofocus]') ??
      root.querySelector<HTMLElement>('input:not([type="hidden"]):not([disabled]), select, textarea') ??
      root.querySelector<HTMLElement>('.dialog__footer .btn--primary, .dialog__footer .btn--destructive') ??
      root.querySelector<HTMLElement>(FOCUSABLE)
    preferred?.focus({ preventScroll: true })

    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== 'Tab' || !root) return
      const items = Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (element) => element.offsetParent !== null,
      )
      if (items.length === 0) return
      const first = items[0]
      const last = items[items.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    root.addEventListener('keydown', onKeyDown)
    return () => {
      root.removeEventListener('keydown', onKeyDown)
      previous?.focus?.({ preventScroll: true })
    }
  }, [container])
}

function Portal({ children }: { children: ReactNode }) {
  return createPortal(children, document.body)
}

/** Play the exit animation, then tell the owner to unmount. */
function useAnimatedClose(onClose: () => void, locked?: boolean) {
  const [closing, setClosing] = useState(false)
  const timer = useRef<number>()
  useEffect(() => () => window.clearTimeout(timer.current), [])
  const close = useCallback(() => {
    if (locked || closing) return
    setClosing(true)
    timer.current = window.setTimeout(onClose, EXIT_MS)
  }, [locked, closing, onClose])
  return { closing, close }
}

/* -------------------------------------------------------------------------- */
/* Dialog                                                                      */
/* -------------------------------------------------------------------------- */

const DialogContext = createContext<{ close: () => void; busy: boolean }>({
  close: () => undefined,
  busy: false,
})

/** Close the surrounding dialog with its exit animation. */
export function useDialog() {
  return useContext(DialogContext)
}

/** A Cancel button that closes the surrounding dialog. */
export function DialogCancel({ children = 'Cancel' }: { children?: ReactNode }) {
  const { close, busy } = useDialog()
  return (
    <Button onClick={close} disabled={busy}>
      {children}
    </Button>
  )
}

export function Dialog({
  title,
  subtitle,
  onClose,
  children,
  footer,
  footerLead,
  size = 'default',
  busy,
}: {
  title: string
  subtitle?: ReactNode
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
  footerLead?: ReactNode
  size?: 'default' | 'medium' | 'wide'
  /** While true the dialog cannot be dismissed, so a request is never orphaned. */
  busy?: boolean
}) {
  const panel = useRef<HTMLDivElement>(null)
  const titleId = useId()
  const { closing, close } = useAnimatedClose(onClose, busy)
  useOverlayLayer(close)
  useFocusTrap(panel)

  return (
    <Portal>
      <DialogContext.Provider value={{ close, busy: Boolean(busy) }}>
        <div
          className={`dialog-backdrop${closing ? ' is-closing' : ''}`}
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) close()
          }}
        >
          <div
            ref={panel}
            className={`dialog${size !== 'default' ? ` dialog--${size}` : ''}`}
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
          >
            <header className="dialog__header">
              <div className="dialog__titles">
                <h2 className="dialog__title" id={titleId}>
                  {title}
                </h2>
                {subtitle ? <div className="dialog__subtitle">{subtitle}</div> : null}
              </div>
              <Button
                variant="ghost"
                size="sm"
                iconOnly
                className="dialog__close"
                icon={<CloseIcon size={16} />}
                aria-label="Close"
                onClick={close}
                disabled={busy}
              />
            </header>
            <div className="dialog__body">{children}</div>
            {footer ? (
              <footer className="dialog__footer">
                {footerLead ? <div className="dialog__footer-lead">{footerLead}</div> : null}
                {footer}
              </footer>
            ) : null}
          </div>
        </div>
      </DialogContext.Provider>
    </Portal>
  )
}

/** A compact macOS-style alert for consequential, irreversible actions. */
export function ConfirmDialog({
  title,
  message,
  confirmLabel,
  destructive,
  busy,
  error,
  onConfirm,
  onCancel,
  icon,
}: {
  title: string
  message: ReactNode
  confirmLabel: string
  destructive?: boolean
  busy?: boolean
  error?: string | null
  onConfirm: () => void
  onCancel: () => void
  icon?: ReactNode
}) {
  const panel = useRef<HTMLDivElement>(null)
  const titleId = useId()
  const { closing, close } = useAnimatedClose(onCancel, busy)
  useOverlayLayer(close)
  useFocusTrap(panel)

  return (
    <Portal>
      <div
        className={`dialog-backdrop dialog-backdrop--alert${closing ? ' is-closing' : ''}`}
        onMouseDown={(event) => {
          if (event.target === event.currentTarget) close()
        }}
      >
        <div
          ref={panel}
          className="dialog dialog--alert"
          role="alertdialog"
          aria-modal="true"
          aria-labelledby={titleId}
        >
          <header className="dialog__header">
            <div
              className={`dialog__alert-icon${destructive ? ' dialog__alert-icon--destructive' : ''}`}
              aria-hidden="true"
            >
              {icon ?? <WarningIcon size={19} />}
            </div>
            <div className="dialog__titles">
              <h2 className="dialog__title" id={titleId}>
                {title}
              </h2>
            </div>
          </header>
          <div className="dialog__body">
            {error ? (
              <div className="mb-3">
                <Notice kind="error">{error}</Notice>
              </div>
            ) : null}
            {message}
          </div>
          <footer className="dialog__footer">
            <Button onClick={close} disabled={busy}>
              Cancel
            </Button>
            <Button
              variant={(destructive ? 'destructive' : 'primary') as ButtonVariant}
              onClick={onConfirm}
              busy={busy}
              data-autofocus=""
            >
              {confirmLabel}
            </Button>
          </footer>
        </div>
      </div>
    </Portal>
  )
}

/* -------------------------------------------------------------------------- */
/* Sheet: a side inspector                                                     */
/* -------------------------------------------------------------------------- */

export function Sheet({
  title,
  subtitle,
  onClose,
  actions,
  children,
}: {
  title: ReactNode
  subtitle?: ReactNode
  onClose: () => void
  actions?: ReactNode
  children: ReactNode
}) {
  const panel = useRef<HTMLDivElement>(null)
  const titleId = useId()
  const { closing, close } = useAnimatedClose(onClose)
  useOverlayLayer(close)
  useFocusTrap(panel)

  return (
    <Portal>
      <div className={`sheet-backdrop${closing ? ' is-closing' : ''}`} onMouseDown={close} />
      <aside
        ref={panel}
        className={`sheet${closing ? ' is-closing' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <header className="sheet__header">
          <div className="dialog__titles">
            <h2 className="dialog__title" id={titleId}>
              {title}
            </h2>
            {subtitle ? <div className="dialog__subtitle">{subtitle}</div> : null}
          </div>
          {actions ? <div className="btn-group">{actions}</div> : null}
          <Button
            variant="ghost"
            size="sm"
            iconOnly
            icon={<CloseIcon size={16} />}
            aria-label="Close"
            onClick={close}
          />
        </header>
        <div className="sheet__body">{children}</div>
      </aside>
    </Portal>
  )
}

/* -------------------------------------------------------------------------- */
/* Menu                                                                        */
/* -------------------------------------------------------------------------- */

export interface MenuItem {
  label: string
  icon?: ReactNode
  onSelect: () => void
  destructive?: boolean
  disabled?: boolean
  separatorBefore?: boolean
}

/** An overflow menu: the "…" that keeps secondary actions out of the way. */
export function ActionMenu({
  items,
  label = 'More actions',
  variant = 'ghost',
  size = 'sm',
}: {
  items: MenuItem[]
  label?: string
  variant?: ButtonVariant
  size?: 'sm' | 'md'
}) {
  const trigger = useRef<HTMLButtonElement>(null)
  const menu = useRef<HTMLDivElement>(null)
  const [position, setPosition] = useState<{ top: number; right: number } | null>(null)
  const open = position !== null

  const hide = useCallback(() => setPosition(null), [])

  function toggle(event: React.MouseEvent) {
    // A menu inside a clickable table row must not also open the row.
    event.stopPropagation()
    if (open) return hide()
    const rect = trigger.current?.getBoundingClientRect()
    if (!rect) return
    setPosition({ top: rect.bottom + 4, right: window.innerWidth - rect.right })
  }

  useEffect(() => {
    if (!open) return
    menu.current?.querySelector<HTMLButtonElement>('.menu__item:not(:disabled)')?.focus()

    function onPointer(event: MouseEvent) {
      if (
        !menu.current?.contains(event.target as Node) &&
        !trigger.current?.contains(event.target as Node)
      ) {
        hide()
      }
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.stopPropagation()
        hide()
        trigger.current?.focus()
      }
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault()
        const buttons = Array.from(
          menu.current?.querySelectorAll<HTMLButtonElement>('.menu__item:not(:disabled)') ?? [],
        )
        const index = buttons.indexOf(document.activeElement as HTMLButtonElement)
        const next = event.key === 'ArrowDown' ? index + 1 : index - 1
        buttons[(next + buttons.length) % buttons.length]?.focus()
      }
    }
    document.addEventListener('mousedown', onPointer)
    document.addEventListener('keydown', onKey, true)
    window.addEventListener('scroll', hide, true)
    window.addEventListener('resize', hide)
    return () => {
      document.removeEventListener('mousedown', onPointer)
      document.removeEventListener('keydown', onKey, true)
      window.removeEventListener('scroll', hide, true)
      window.removeEventListener('resize', hide)
    }
  }, [open, hide])

  return (
    <>
      <Button
        ref={trigger}
        variant={variant}
        size={size}
        iconOnly
        icon={<MoreIcon size={16} />}
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={toggle}
      />
      {open ? (
        <Portal>
          <div
            ref={menu}
            className="menu"
            role="menu"
            style={{ top: position.top, right: position.right }}
            onClick={(event) => event.stopPropagation()}
          >
            {items.map((item) => (
              <div key={item.label}>
                {item.separatorBefore ? <div className="menu__separator" /> : null}
                <button
                  type="button"
                  role="menuitem"
                  className={`menu__item${item.destructive ? ' menu__item--destructive' : ''}`}
                  disabled={item.disabled}
                  onClick={() => {
                    hide()
                    item.onSelect()
                  }}
                >
                  {item.icon}
                  {item.label}
                </button>
              </div>
            ))}
          </div>
        </Portal>
      ) : null}
    </>
  )
}
