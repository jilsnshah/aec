import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { PackageCheck, PackageX, Undo2 } from 'lucide-react'
import { errorText } from '@/api/client'
import { useAction } from '@/api/queries'
import { returns } from '@/api/records'
import { cn } from '@/lib/cn'
import { fmtMoney, fmtQty } from '@/lib/format'
import { Button, Facts, Field, Notice, Spinner } from '@/ui/core'
import { Sheet } from '@/ui/overlays'

/** Goods a customer sent back: credit their account, and put sellable goods
 *  back on the shelf at the cost they left at. */
export function ReturnSheet({ orderId, orderNumber, open, onClose }: { orderId: string; orderNumber: string; open: boolean; onClose: () => void }) {
  const data = useQuery({ queryKey: ['returns', 'returnable', orderId], queryFn: () => returns.returnable(orderId), enabled: open })
  const [qty, setQty] = useState<Record<string, string>>({})
  const [restock, setRestock] = useState<Record<string, boolean>>({})
  const [reason, setReason] = useState('excess')
  const [note, setNote] = useState('')
  const create = useAction(returns.create, { success: (r) => `${r.number}: ${fmtMoney(r.amount)} credited`, quiet: true })
  useEffect(() => {
    if (open) (setQty({}), setRestock({}), setNote(''), create.reset())
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps
  const lines = data.data?.lines ?? []
  const chosen = lines.filter((line) => Number(qty[line.order_item_id] || 0) > 0)
  const credit = chosen.reduce((sum, line) => sum + Number(qty[line.order_item_id]) * line.unit_price_net, 0)
  const tooMuch = chosen.find((line) => Number(qty[line.order_item_id]) > line.returnable)
  return (
    <Sheet
      open={open}
      onClose={onClose}
      width={860}
      title={`Return goods on ${orderNumber}`}
      subtitle="The value is credited to the customer's account. Goods in sellable condition go back into stock."
      aside={
        <div className="space-y-4">
          <div className="eyebrow">Credit note</div>
          <Facts
            items={[
              { label: 'Lines', value: chosen.length },
              { label: 'Back to stock', value: chosen.filter((line) => restock[line.order_item_id] !== false).length },
              { label: 'Credit', value: fmtMoney(credit), strong: true },
            ]}
          />
          <p className="text-[12px] text-fg-3">The credit settles the customer's oldest open invoices first. Revenue and profit for this period fall by the return.</p>
        </div>
      }
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            kind="primary"
            icon={<Undo2 size={14} />}
            busy={create.isPending}
            disabled={!chosen.length || Boolean(tooMuch)}
            onClick={() =>
              create.mutate(
                { orderId, reason, note: note || undefined, lines: chosen.map((line) => ({ order_item_id: line.order_item_id, quantity: qty[line.order_item_id], restock: restock[line.order_item_id] !== false })) },
                { onSuccess: onClose },
              )
            }
          >
            Record return
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        {create.error ? <Notice tone="bad">{errorText(create.error)}</Notice> : null}
        {tooMuch ? <Notice tone="bad">Only {fmtQty(tooMuch.returnable)} of {tooMuch.product_name} can be returned.</Notice> : null}
        <Field label="Reason">
          {(props) => (
            <select {...props} className="field" value={reason} onChange={(e) => setReason(e.target.value)}>
              {Object.entries(data.data?.reasons ?? {}).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          )}
        </Field>
        {data.isPending ? (
          <Spinner />
        ) : (
          <table className="grid-table">
            <thead>
              <tr>
                <th>Product</th>
                <th className="r">Delivered</th>
                <th className="r">Returnable</th>
                <th className="r w-[120px]">Returning</th>
                <th>Condition</th>
              </tr>
            </thead>
            <tbody>
              {lines.map((line) => {
                const good = restock[line.order_item_id] !== false
                return (
                  <tr key={line.order_item_id}>
                    <td>
                      <div className="text-[13px] font-medium">{line.product_name}</div>
                      <div className="text-[11.5px] text-fg-3">{fmtMoney(line.unit_price_net)} each</div>
                    </td>
                    <td className="r num">{fmtQty(line.delivered)}</td>
                    <td className="r num">{fmtQty(line.returnable)}</td>
                    <td className="r">
                      <input
                        inputMode="decimal"
                        aria-label={`Return ${line.product_name}`}
                        disabled={line.returnable <= 0}
                        className="field field-sm w-[100px] text-right"
                        placeholder="0"
                        value={qty[line.order_item_id] ?? ''}
                        onChange={(e) => setQty({ ...qty, [line.order_item_id]: e.target.value })}
                      />
                    </td>
                    <td>
                      <button
                        onClick={() => setRestock({ ...restock, [line.order_item_id]: !good })}
                        className={cn('inline-flex h-[28px] items-center gap-1.5 rounded-full px-2.5 text-[12px] font-semibold', good ? 'bg-blue/25' : 'bg-[#0b0b0c] text-[#fff]')}
                      >
                        {good ? <PackageCheck size={13} /> : <PackageX size={13} />} {good ? 'Back to stock' : 'Damaged'}
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
        <Field label="Note" optional>
          {(props) => <input {...props} className="field" placeholder="What the customer said" value={note} onChange={(e) => setNote(e.target.value)} />}
        </Field>
      </div>
    </Sheet>
  )
}
