import * as Popover from '@radix-ui/react-popover'
import { Command } from 'cmdk'
import { useState, type ReactNode } from 'react'
import { Check, ChevronsUpDown } from 'lucide-react'
import { cn } from '@/lib/cn'

export interface PickOption {
  value: string
  label: string
  detail?: string
  trail?: ReactNode
  keywords?: string
}

/** A searchable chooser: a field that opens a filtered list. */
export function Picker({
  value,
  onChange,
  options,
  placeholder = 'Choose…',
  emptyText = 'Nothing matches.',
  small,
  invalid,
  disabled,
  id,
}: {
  value: string
  onChange: (value: string) => void
  options: PickOption[]
  placeholder?: string
  emptyText?: string
  small?: boolean
  invalid?: boolean
  disabled?: boolean
  id?: string
}) {
  const [open, setOpen] = useState(false)
  const chosen = options.find((option) => option.value === value)
  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild disabled={disabled}>
        <button
          id={id}
          type="button"
          aria-invalid={invalid || undefined}
          className={cn('field flex items-center gap-2 text-left', small && 'field-sm', !chosen && 'text-fg-4')}
        >
          <span className="min-w-0 flex-1 truncate">
            {chosen ? (
              <>
                {chosen.label}
                {chosen.detail ? <span className="ml-2 text-fg-3">{chosen.detail}</span> : null}
              </>
            ) : (
              placeholder
            )}
          </span>
          <ChevronsUpDown size={13} className="shrink-0 text-fg-3" />
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="start"
          sideOffset={6}
          collisionPadding={12}
          className="z-[180] w-[max(var(--radix-popover-trigger-width),340px)] overflow-hidden rounded-xl bg-ink-750 shadow-[0_24px_60px_-12px_rgb(0_0_0/0.85),0_0_0_1px_rgb(255_255_255/0.09)] data-[state=open]:animate-[pop_160ms_var(--ease-out-quint)_both]"
        >
          <Command>
            <Command.Input autoFocus placeholder="Search…" className="h-10 w-full border-b border-white/8 bg-transparent px-3.5 text-[13px] outline-none placeholder:text-fg-4" />
            <Command.List className="max-h-[300px] overflow-y-auto p-1.5">
              <Command.Empty className="py-6 text-center text-[12.5px] text-fg-3">{emptyText}</Command.Empty>
              {options.map((option) => (
                <Command.Item
                  key={option.value}
                  value={`${option.label} ${option.detail ?? ''} ${option.keywords ?? ''} ${option.value}`}
                  onSelect={() => {
                    onChange(option.value)
                    setOpen(false)
                  }}
                  className="flex min-h-9 items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-[13px] data-[selected=true]:bg-white/8"
                >
                  <Check size={14} className={cn('shrink-0 text-sky', option.value === value ? 'opacity-100' : 'opacity-0')} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate">{option.label}</span>
                    {option.detail ? <span className="block truncate text-[11.5px] text-fg-3">{option.detail}</span> : null}
                  </span>
                  {option.trail}
                </Command.Item>
              ))}
            </Command.List>
          </Command>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}
