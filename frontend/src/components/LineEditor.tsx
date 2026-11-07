import type { ReactNode } from 'react'
import type { Customer, Product, Supplier } from '../api/types'
import { CloseIcon, PlusIcon } from './icons'
import { Button } from './primitives'

/** A grid of editable line items: orders, enquiries and purchase orders all
 *  use it, so they look and behave identically. */
export function LineEditor({
  columns,
  headers,
  children,
  onAdd,
  addLabel = 'Add line',
  footer,
}: {
  /** CSS grid-template-columns; the last column holds the remove button. */
  columns: string
  headers: { label: string; align?: 'right' }[]
  children: ReactNode
  onAdd: () => void
  addLabel?: string
  footer?: ReactNode
}) {
  const style = { ['--line-cols' as string]: columns }
  return (
    <div className="line-editor" style={style}>
      <div className="line-editor__head" aria-hidden="true">
        {headers.map((header, index) => (
          <span key={index} style={header.align === 'right' ? { textAlign: 'right' } : undefined}>
            {header.label}
          </span>
        ))}
        <span />
      </div>
      {children}
      <div className="line-editor__foot">
        <Button variant="plain" size="sm" icon={<PlusIcon size={14} />} onClick={onAdd}>
          {addLabel}
        </Button>
        <div className="grow" />
        {footer}
      </div>
    </div>
  )
}

export function LineRow({
  children,
  onRemove,
  canRemove,
  removeLabel,
  meta,
  error,
}: {
  children: ReactNode
  onRemove: () => void
  canRemove: boolean
  removeLabel: string
  meta?: ReactNode
  error?: string | null
}) {
  return (
    <div className="line-editor__row">
      {children}
      <Button
        variant="ghost"
        size="sm"
        iconOnly
        icon={<CloseIcon size={14} />}
        aria-label={removeLabel}
        onClick={onRemove}
        disabled={!canRemove}
      />
      {meta || error ? (
        <div className="line-editor__meta">
          {meta}
          {error ? <span className="field__error">{error}</span> : null}
        </div>
      ) : null}
    </div>
  )
}

/** One cell; on narrow screens it gains its own label. */
export function LineCell({
  label,
  children,
  align,
}: {
  label: string
  children: ReactNode
  align?: 'right'
}) {
  return (
    <div style={align === 'right' ? { textAlign: 'right' } : undefined}>
      <span className="line-editor__label">{label}</span>
      {children}
    </div>
  )
}

export function ProductSelect({
  products,
  value,
  onChange,
  disabled,
  invalid,
  label,
  exclude,
}: {
  products: Product[]
  value: string
  onChange: (id: string, product: Product | undefined) => void
  disabled?: boolean
  invalid?: boolean
  label: string
  exclude?: string[]
}) {
  return (
    <select
      className="input"
      aria-label={label}
      aria-invalid={invalid || undefined}
      value={value}
      disabled={disabled}
      onChange={(event) =>
        onChange(
          event.target.value,
          products.find((product) => product.id === event.target.value),
        )
      }
    >
      <option value="">Choose a product…</option>
      {products
        .filter((product) => product.id === value || !exclude?.includes(product.id))
        .map((product) => (
          <option key={product.id} value={product.id}>
            {product.sku} — {product.name}
          </option>
        ))}
    </select>
  )
}

export function PartySelect<T extends Customer | Supplier>({
  parties,
  value,
  onChange,
  disabled,
  placeholder,
  ...props
}: {
  parties: T[]
  value: string
  onChange: (id: string) => void
  disabled?: boolean
  placeholder: string
  id?: string
  className?: string
  'aria-invalid'?: boolean
  'aria-describedby'?: string
}) {
  return (
    <select
      {...props}
      className="input"
      value={value}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value)}
    >
      <option value="">{placeholder}</option>
      {parties.map((party) => (
        <option key={party.id} value={party.id}>
          {'code' in party ? `${party.code} — ${party.name}` : party.name}
        </option>
      ))}
    </select>
  )
}
