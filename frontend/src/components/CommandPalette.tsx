import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { ThemeChoice } from '../lib/theme'
import {
  CustomerIcon,
  DarkThemeIcon,
  DeliveryIcon,
  GoodsReceiptIcon,
  LightThemeIcon,
  PackageIcon,
  PlusIcon,
  SalesOrderIcon,
  SearchIcon,
  StockInIcon,
  SystemThemeIcon,
} from './icons'
import { NAV_ITEMS } from './navigation'
import { Kbd, Spinner } from './primitives'

interface Command {
  id: string
  group: string
  label: string
  hint?: string
  icon: ReactNode
  keywords?: string
  run: () => void
}

/** ⌘K: jump to any screen, start any common task, or open a record by number. */
export function CommandPalette({
  onClose,
  onTheme,
}: {
  onClose: () => void
  onTheme: (choice: ThemeChoice) => void
}) {
  const navigate = useNavigate()
  const input = useRef<HTMLInputElement>(null)
  const list = useRef<HTMLDivElement>(null)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const [records, setRecords] = useState<Command[]>([])
  const [searching, setSearching] = useState(false)

  function go(to: string) {
    onClose()
    navigate(to)
  }

  const commands = useMemo<Command[]>(() => {
    const create = (id: string, label: string, to: string, keywords: string): Command => ({
      id,
      group: 'Create',
      label,
      icon: <PlusIcon size={17} />,
      keywords,
      run: () => go(to),
    })
    const appearance = (choice: ThemeChoice, label: string, icon: ReactNode): Command => ({
      id: `theme:${choice}`,
      group: 'Appearance',
      label,
      icon,
      keywords: 'theme mode appearance',
      run: () => {
        onTheme(choice)
        onClose()
      },
    })

    return [
      ...NAV_ITEMS.map((item): Command => {
        const Icon = item.icon
        return {
          id: `nav:${item.to}`,
          group: 'Go to',
          label: item.label,
          icon: <Icon size={17} />,
          keywords: item.keywords,
          run: () => go(item.to),
        }
      }),
      create('new:order', 'New sales order', '/orders?new=1', 'create so'),
      create('new:enquiry', 'New enquiry', '/enquiries?new=1', 'create quote'),
      create('new:po', 'New purchase order', '/purchase-orders?new=1', 'create po buy'),
      create('new:product', 'New product', '/products?new=1', 'create sku'),
      create('new:customer', 'New customer', '/customers?new=1', 'create client'),
      create('new:supplier', 'New supplier', '/suppliers?new=1', 'create vendor'),
      {
        id: 'do:receive',
        group: 'Do',
        label: 'Receive goods against a purchase order',
        icon: <GoodsReceiptIcon size={17} />,
        keywords: 'gr arrival delivery supplier',
        run: () => go('/goods-receipts'),
      },
      {
        id: 'do:deliver',
        group: 'Do',
        label: 'Deliver to customers',
        icon: <DeliveryIcon size={17} />,
        keywords: 'dispatch ship fulfil',
        run: () => go('/pending-fulfilment?filter=ready'),
      },
      {
        id: 'do:stockin',
        group: 'Do',
        label: 'Record ad-hoc stock in',
        icon: <StockInIcon size={17} />,
        keywords: 'receipt grn',
        run: () => go('/stock-in'),
      },
      appearance('light', 'Use light appearance', <LightThemeIcon size={17} />),
      appearance('dark', 'Use dark appearance', <DarkThemeIcon size={17} />),
      appearance('system', 'Match system appearance', <SystemThemeIcon size={17} />),
    ]
    // The navigate function is stable for the palette's lifetime.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Records: look up orders, customers and products by what is typed.
  useEffect(() => {
    const term = query.trim()
    if (term.length < 2) {
      setRecords([])
      setSearching(false)
      return
    }
    let cancelled = false
    setSearching(true)
    const timer = window.setTimeout(() => {
      Promise.allSettled([
        api.orders.list({ search: term, limit: 4 }),
        api.customers.list({ search: term, limit: 3 }),
        api.products.list({ search: term, limit: 3 }),
      ]).then(([orders, customers, products]) => {
        if (cancelled) return
        const found: Command[] = []
        if (orders.status === 'fulfilled') {
          for (const order of orders.value.items) {
            found.push({
              id: `order:${order.id}`,
              group: 'Records',
              label: `${order.order_number} · ${order.customer.name}`,
              hint: 'Sales order',
              icon: <SalesOrderIcon size={17} />,
              run: () => go(`/orders/${order.id}`),
            })
          }
        }
        if (customers.status === 'fulfilled') {
          for (const customer of customers.value.items) {
            found.push({
              id: `customer:${customer.id}`,
              group: 'Records',
              label: customer.name,
              hint: 'Customer',
              icon: <CustomerIcon size={17} />,
              run: () => go(`/customers/${customer.id}`),
            })
          }
        }
        if (products.status === 'fulfilled') {
          for (const product of products.value.items) {
            found.push({
              id: `product:${product.id}`,
              group: 'Records',
              label: `${product.sku} · ${product.name}`,
              hint: 'Product',
              icon: <PackageIcon size={17} />,
              run: () => go(`/products?open=${product.id}`),
            })
          }
        }
        setRecords(found)
        setSearching(false)
      })
    }, 180)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query])

  const visible = useMemo(() => {
    // Every word typed must appear somewhere, in any order: "new order" finds
    // "New sales order".
    const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
    const matched = words.length
      ? commands.filter((command) => {
          const haystack = `${command.label} ${command.keywords ?? ''} ${command.group}`.toLowerCase()
          return words.every((word) => haystack.includes(word))
        })
      : commands.filter((command) => command.group !== 'Appearance')
    return [...matched, ...records]
  }, [commands, records, query])

  useEffect(() => setActive(0), [query, records.length])

  useEffect(() => {
    input.current?.focus()
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = previous
    }
  }, [])

  useEffect(() => {
    list.current
      ?.querySelector<HTMLElement>(`[data-index="${active}"]`)
      ?.scrollIntoView({ block: 'nearest' })
  }, [active])

  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setActive((index) => Math.min(index + 1, Math.max(visible.length - 1, 0)))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActive((index) => Math.max(index - 1, 0))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      visible[active]?.run()
    } else if (event.key === 'Escape') {
      event.preventDefault()
      onClose()
    }
  }

  let lastGroup = ''
  return createPortal(
    <div
      className="command-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className="command" role="dialog" aria-modal="true" aria-label="Command menu">
        <div className="command__input-row">
          <SearchIcon size={19} aria-hidden="true" />
          <input
            ref={input}
            className="command__input"
            placeholder="Search screens, actions, orders, customers, products…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={onKeyDown}
            role="combobox"
            aria-expanded="true"
            aria-controls="command-list"
            aria-activedescendant={visible[active] ? `command-${visible[active].id}` : undefined}
          />
          {searching ? <Spinner /> : <Kbd>esc</Kbd>}
        </div>
        <div className="command__list" id="command-list" role="listbox" ref={list}>
          {visible.length === 0 ? (
            <div className="command__empty">
              {searching ? 'Searching…' : `Nothing matches “${query}”.`}
            </div>
          ) : (
            visible.map((command, index) => {
              const heading = command.group !== lastGroup ? command.group : null
              lastGroup = command.group
              return (
                <div key={command.id}>
                  {heading ? <div className="command__group">{heading}</div> : null}
                  <button
                    type="button"
                    id={`command-${command.id}`}
                    role="option"
                    aria-selected={index === active}
                    data-index={index}
                    className={`command__item${index === active ? ' is-active' : ''}`}
                    onMouseMove={() => setActive(index)}
                    onClick={() => command.run()}
                  >
                    {command.icon}
                    <span className="truncate">{command.label}</span>
                    {command.hint ? <span className="command__hint">{command.hint}</span> : null}
                  </button>
                </div>
              )
            })
          )}
        </div>
        <div className="command__footer">
          <span>
            <Kbd>↑</Kbd> <Kbd>↓</Kbd> to move
          </span>
          <span>
            <Kbd>↵</Kbd> to open
          </span>
          <span>
            <Kbd>esc</Kbd> to close
          </span>
        </div>
      </div>
    </div>,
    document.body,
  )
}
