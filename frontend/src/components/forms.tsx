import { useId, type ReactNode } from 'react'
import { ErrorIcon } from './icons'

export interface FieldControlProps {
  id: string
  'aria-invalid'?: boolean
  'aria-describedby'?: string
  className: string
}

/** A labelled control. Wires the label, hint and error to the input so
 *  assistive technology reads them together. */
export function Field({
  label,
  error,
  hint,
  optional,
  span2,
  children,
}: {
  label: ReactNode
  error?: string | null
  hint?: ReactNode
  optional?: boolean
  span2?: boolean
  children: (props: FieldControlProps) => ReactNode
}) {
  const id = useId()
  const describedBy = error ? `${id}-error` : hint ? `${id}-hint` : undefined
  return (
    <div className={`field${span2 ? ' span-2' : ''}`}>
      <label className="field__label" htmlFor={id}>
        {label}
        {optional ? <span className="field__optional">Optional</span> : null}
      </label>
      {children({
        id,
        'aria-invalid': error ? true : undefined,
        'aria-describedby': describedBy,
        className: 'input',
      })}
      {error ? (
        <div className="field__error" id={`${id}-error`}>
          <ErrorIcon size={13} aria-hidden="true" />
          {error}
        </div>
      ) : hint ? (
        <div className="field__hint" id={`${id}-hint`}>
          {hint}
        </div>
      ) : null}
    </div>
  )
}

export function FormGrid({ children }: { children: ReactNode }) {
  return <div className="form-grid">{children}</div>
}
