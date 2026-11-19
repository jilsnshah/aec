import { PartyLinks } from '@/features/parties/PartyLinks'
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { History, ShieldCheck, Sparkles, TrendingDown } from 'lucide-react'
import { errorText } from '@/api/client'
import { controlsApi, records } from '@/api/records'
import { usePriceList } from '@/features/pricing/usePriceList'
import { useDebounced } from '@/lib/route'
import { useAssistant } from '@/features/assistant/store'
import { HoldPanel, WarningList, holdFrom } from '@/ui/smart'
import { api } from '@/api/endpoints'
import { useAction } from '@/api/queries'
import type { OrderDetailOut } from '@/api/types'
import { fmtMoney, fmtQty, n } from '@/lib/format'
import { Button, Facts, Field, Notice } from '@/ui/core'
import { LineEditor, baseQty, factorOf, lineErrors, lineTotal, lineUnit, newLine, unitParam, useCustomers, useProducts, type Line } from '@/ui/lines'
import { Sheet } from '@/ui/overlays'
import { Picker } from '@/ui/pickers'

/** A new sales order: stock is taken the moment it is placed. */
export function OrderSheet({ open, onClose, onCreated, customerId, repeatFrom }: { open: boolean; onClose: () => void; onCreated?: (order: OrderDetailOut) => void; customerId?: string; repeatFrom?: string }) {
  const { ask } = useAssistant()
  const [message, setMessage] = useState('')
  const customers = useCustomers()
  const products = useProducts()
  const [customer, setCustomer] = useState('')
  const [lines, setLines] = useState<Line[]>([newLine()])
  const [notes, setNotes] = useState('')
  const [contactId, setContactId] = useState('')
  const [siteId, setSiteId] = useState('')
  const [tried, setTried] = useState(false)
  const create = useAction(({ body, approval }: { body: Parameters<typeof api.orders.create>[0]; approval?: string }) => api.orders.create(body, approval), { success: (order) => `${order.order_number} placed`, quiet: true })

  useEffect(() => {
    if (!open) return
    setCustomer(customerId ?? '')
    setLines([newLine()])
    setNotes('')
    setContactId('')
    setSiteId('')
    setTried(false)
    setMessage('')
    create.reset()
    if (repeatFrom) {
      api.orders.get(repeatFrom).then((order) => {
        setCustomer(order.customer_id)
        setLines(order.items.map((item) => newLine({ product_id: item.product_id, unit: lineUnit(item), quantity: String((n(item.quantity_ordered) - n(item.quantity_cancelled)) / n(item.unit_factor ?? 1)), discount: String(n(item.discount_percent)) })))
        setNotes(`Repeat of ${order.order_number}`)
      })
    }
  }, [open, repeatFrom]) // eslint-disable-line react-hooks/exhaustive-deps

  const errors = [...(customer ? [] : ['Choose a customer.']), ...lineErrors(lines, 'sale', products.byId)]
  const chosen = lines.filter((line) => line.product_id)
  const subtotal = chosen.reduce((sum, line) => sum + baseQty(line, products.byId.get(line.product_id)) * n(products.byId.get(line.product_id)?.mrp), 0)
  const total = chosen.reduce((sum, line) => sum + lineTotal(line, products.byId.get(line.product_id), 'sale'), 0)
  const short = chosen.reduce((sum, line) => sum + Math.max(0, baseQty(line, products.byId.get(line.product_id)) - Math.max(0, n(products.byId.get(line.product_id)?.stock))), 0)

  const draft = useDebounced(JSON.stringify({ customer, lines: chosen.map((line) => [line.product_id, line.quantity, line.unit, line.discount]) }), 400)
  const check = useQuery({
    queryKey: ['records', 'order-check', draft],
    enabled: open && chosen.length > 0,
    queryFn: () =>
      records.checkOrder({
        customer_id: customer || null,
        items: chosen.map((line) => ({ product_id: line.product_id, quantity_ordered: n(line.quantity), unit: unitParam(line), discount_percent: n(line.discount), unit_price: n(products.byId.get(line.product_id)?.mrp) * factorOf(line, products.byId.get(line.product_id)) })),
      }),
  })
  const gate = useQuery({
    queryKey: ['controls', 'check', draft],
    enabled: open && chosen.length > 0,
    queryFn: () =>
      controlsApi.check({
        customer_id: customer || null,
        items: chosen.map((line) => ({ product_id: line.product_id, quantity_ordered: n(line.quantity), unit: unitParam(line), discount_percent: n(line.discount), unit_price: n(products.byId.get(line.product_id)?.mrp) * factorOf(line, products.byId.get(line.product_id)) })),
      }),
  })
  const holds = gate.data?.holds ?? []
  const pricing = { data: usePriceList(open, customer, lines, setLines) }
  const warnings = check.data?.warnings ?? []
  const checkLines = check.data?.lines ?? []

  function submit(approval?: string) {
    setTried(true)
    if (errors.length > 0) return
    create.mutate(
      { approval, body: { customer_id: customer, contact_id: contactId || null, delivery_address_id: siteId || null, notes: notes || null, items: chosen.map((line) => ({ product_id: line.product_id, quantity_ordered: line.quantity, unit: unitParam(line), discount_percent: line.discount || '0', unit_price: null })) } },
      {
        onSuccess: (order) => {
          onClose()
          onCreated?.(order)
        },
      },
    )
  }

  return (
    <Sheet
      open={open}
      onClose={onClose}
      width={1000}
      title="New sales order"
      subtitle="Prices start at MRP; set a discount per line. Anything short waits for the next purchase."
      aside={
        <div className="space-y-5">
          <div>
            <div className="eyebrow mb-2">Order</div>
            <Facts
              items={[
                { label: 'Lines', value: chosen.length },
                { label: 'At MRP', value: fmtMoney(subtotal) },
                { label: 'Discount', value: subtotal - total > 0.005 ? `−${fmtMoney(subtotal - total)}` : '—' },
                { label: 'Total', value: fmtMoney(total), strong: true },
              ]}
            />
          </div>
          <div>
            <div className="eyebrow mb-2 flex items-center gap-1.5">
              <ShieldCheck size={12} /> Order check
            </div>
            {holds.length ? (
              <div className="mb-2 rounded-xl bg-[#0b0b0c] px-3 py-2 text-[12.5px] text-[#fff]">
                <b>Needs approval</b> ({gate.data?.mode === 'block' ? 'credit control is set to block' : 'pricing limits'}): an admin can approve it when placing.
              </div>
            ) : null}
            {chosen.length === 0 ? (
              <p className="text-[12px] text-fg-3">Credit limit, margin, discount and stock are checked as you add lines.</p>
            ) : warnings.length ? (
              <WarningList warnings={warnings} />
            ) : check.data ? (
              <Notice tone="ok" icon={<ShieldCheck size={14} />}>All clear: within credit, margins healthy, stock available.</Notice>
            ) : null}
            {short > 0 && !check.data ? <Notice tone="warn">{fmtQty(short)} units are not in stock. They will show as short until bought.</Notice> : null}
          </div>
          {checkLines.length ? (
            <div>
              <div className="eyebrow mb-2 flex items-center gap-1.5">
                <History size={12} /> Price and margin
              </div>
              <div className="space-y-2">
                {checkLines.map((line) => (
                  <div key={line.product_id} className="rounded-xl bg-white/5 px-3 py-2 text-[12px]">
                    <div className="flex justify-between gap-2 font-semibold">
                      <span className="truncate">{line.name}</span>
                      <span className={line.margin_percent !== null && line.margin_percent < 5 ? 'num font-bold underline' : 'num'}>{line.margin_percent !== null ? `${line.margin_percent}% margin` : 'no cost yet'}</span>
                    </div>
                    <div className="mt-0.5 flex justify-between gap-2 text-fg-3">
                      <span>
                        {line.last_price_to_customer ? (
                          <>
                            Last paid {fmtMoney(line.last_price_to_customer.net_price)}
                            {line.last_price_to_customer.net_price > line.net_price ? <TrendingDown size={11} className="ml-1 inline" /> : null}
                          </>
                        ) : customer ? (
                          'First time for this customer'
                        ) : (
                          `Usual discount ${line.usual_discount_percent ?? 0}%`
                        )}
                      </span>
                      <span className="num">{fmtQty(line.free_stock)} free</span>
                    </div>
                    <div className="mt-0.5 text-[11px] text-fg-3">
                      {pricing.data?.price_list_active ? pricing.data.lines.find((r) => r.product_id === line.product_id)?.rule : 'MRP'}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          <div className="rounded-2xl bg-white/5 p-3">
            <div className="flex items-center gap-1.5 text-[12.5px] font-semibold">
              <Sparkles size={13} /> Draft from a message
            </div>
            <p className="mt-0.5 text-[11.5px] text-fg-3">Paste a WhatsApp or email order; the assistant finds the customer and products and drafts it for you to confirm.</p>
            <textarea className="field mt-2 min-h-[64px] text-[12.5px]" placeholder="e.g. Send 20 bags cement and 5 tmt bars to Sharma ji" value={message} onChange={(event) => setMessage(event.target.value)} />
            <Button
              small
              kind="quiet"
              className="mt-2 w-full"
              icon={<Sparkles size={13} />}
              disabled={!message.trim()}
              onClick={() => {
                ask(`Draft a sales order from this customer message. Find the customer and each product, check stock, the customer's last prices and credit, then propose create_order for me to confirm:\n\n${message.trim()}`)
                onClose()
              }}
            >
              Draft with AI
            </Button>
          </div>
          <p className="text-[12px] text-fg-3">Before tax. The server confirms prices when the order is placed.</p>
        </div>
      }
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button kind="primary" busy={create.isPending} onClick={() => submit()}>
            Place order
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        {create.error && holdFrom(create.error) ? <HoldPanel error={create.error} busy={create.isPending} onApprove={(reason) => submit(reason)} /> : create.error ? <Notice tone="bad">{errorText(create.error)}</Notice> : null}
        {tried && errors.length > 0 ? <Notice tone="bad">{errors.join('\n')}</Notice> : null}
        <Field label="Customer">
          {(props) => (
            <Picker
              {...props}
              value={customer}
              onChange={setCustomer}
              invalid={tried && !customer}
              placeholder="Choose a customer…"
              options={customers.map((row) => ({ value: row.id, label: row.name, detail: row.phone ?? row.email ?? undefined }))}
            />
          )}
        </Field>
        <PartyLinks customerId={customer} contactId={contactId} onContact={setContactId} siteId={siteId} onSite={setSiteId} />
        <div>
          <div className="label">Products</div>
          <LineEditor lines={lines} onChange={setLines} mode="sale" />
        </div>
        <Field label="Notes" optional>
          {(props) => <textarea {...props} className="field" placeholder="Anything the customer asked for" value={notes} onChange={(event) => setNotes(event.target.value)} />}
        </Field>
      </div>
    </Sheet>
  )
}
