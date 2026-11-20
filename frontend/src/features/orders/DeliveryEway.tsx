import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Check, Pencil, Truck } from 'lucide-react'
import { errorText, http } from '@/api/client'
import { useAction } from '@/api/queries'
import { fmtMoney } from '@/lib/format'
import { Badge, Button, Notice } from '@/ui/core'

interface Row {
  id: string
  delivery_number: string
  value: string | number
  vehicle_number: string | null
  lr_number: string | null
  transporter_name: string | null
  eway_bill_number: string | null
}

/** Rs 50,000: the usual value above which goods on the road need an e-way bill (states may set more). */
export const EWAY_LIMIT = 50000

/** Transport and e-way bill for one delivery: from Tally when it generates
 *  one, or typed in here. */
export function DeliveryEway({ orderId, deliveryId }: { orderId: string; deliveryId: string }) {
  const rows = useQuery({ queryKey: ['deliveries', 'order', orderId], queryFn: () => http.get<{ items: Row[] }>('/api/deliveries', { order_id: orderId, limit: 100 }) })
  const row = rows.data?.items.find((r) => r.id === deliveryId)
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState('')
  const save = useAction(() => http.put(`/api/deliveries/${deliveryId}/eway-bill`, { eway_bill_number: value || null }), { success: 'E-way bill saved', quiet: true })
  if (!row) return null
  const needed = Number(row.value) > EWAY_LIMIT && !row.eway_bill_number
  return (
    <div className="mt-2 space-y-2 border-t border-white/6 pt-2 text-[12px]">
      <div className="flex flex-wrap items-center gap-2">
        {row.transporter_name || row.vehicle_number ? (
          <span className="flex items-center gap-1 text-fg-2">
            <Truck size={12} /> {[row.transporter_name, row.vehicle_number, row.lr_number ? `LR ${row.lr_number}` : null].filter(Boolean).join(' · ')}
          </span>
        ) : null}
        <span className="text-fg-3">Value {fmtMoney(row.value)}</span>
        <span className="flex-1" />
        {editing ? (
          <>
            <input
              className="field field-sm w-[150px]"
              inputMode="numeric"
              placeholder="12-digit number"
              aria-label="E-way bill number"
              value={value}
              onChange={(e) => {
                const next = e.target.value
                setValue(next)
              }}
            />
            <Button small kind="primary" icon={<Check size={12} />} busy={save.isPending} onClick={() => save.mutate(undefined, { onSuccess: () => setEditing(false) })}>
              Save
            </Button>
          </>
        ) : row.eway_bill_number ? (
          <Badge tone="ok">
            E-way bill {row.eway_bill_number}
            <button aria-label="Change e-way bill" onClick={() => (setValue(row.eway_bill_number ?? ''), setEditing(true))}>
              <Pencil size={11} />
            </button>
          </Badge>
        ) : (
          <Button small kind="ghost" icon={needed ? <AlertTriangle size={12} /> : <Pencil size={12} />} onClick={() => (setValue(''), setEditing(true))}>
            {needed ? 'E-way bill needed' : 'Add e-way bill'}
          </Button>
        )}
      </div>
      {needed && !editing ? <div className="text-warn">Over ₹50,000 on the road: generate the e-way bill in Tally (picked up automatically) or enter it here.</div> : null}
      {save.error ? <Notice tone="bad">{errorText(save.error)}</Notice> : null}
    </div>
  )
}
