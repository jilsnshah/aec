import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { UserMinus, UserPlus, UsersRound } from 'lucide-react'
import { errorText } from '@/api/client'
import { useAction } from '@/api/queries'
import { groups } from '@/api/groups'
import { Badge, Button, Notice, Spinner } from '@/ui/core'
import { Picker } from '@/ui/pickers'
import { DiscountCard, PriceLines, fromLines, toLines, type PriceLine } from './PriceLines'

/** What this customer pays: their own discount and product prices, plus their
 *  groups. The best of all of them is used on each line. */
export function CustomerPricing({ customerId }: { customerId: string }) {
  const data = useQuery({ queryKey: ['customer-pricing', customerId], queryFn: () => groups.pricing(customerId) })
  const allGroups = useQuery({ queryKey: ['customer-groups'], queryFn: groups.list })
  const member = useAction(groups.setMember, { success: 'Groups updated' })
  const [groupId, setGroupId] = useState('')
  const [discount, setDiscount] = useState('')
  const [lines, setLines] = useState<PriceLine[]>([])
  useEffect(() => {
    if (!data.data) return
    setDiscount(data.data.discount_percent ? String(data.data.discount_percent) : '')
    setLines(toLines(data.data.own_items))
  }, [data.data])
  const save = useAction(
    () =>
      groups.setPricing({
        customerId,
        discount_percent: discount || null,
        items: fromLines(lines),
      }),
    { success: 'Pricing saved', quiet: true },
  )
  if (data.isPending) return <Spinner />
  const p = data.data
  return (
    <div className="space-y-4 p-6 pb-24 max-md:p-4">
      <div className="rounded-2xl bg-peri/35 px-4 py-3 text-[12.5px]">
        On each order or quote line this customer gets the <b>best</b> of: their own price for that product, their own discount, and the prices of every group they are in.
      </div>
      {save.error ? <Notice tone="bad">{errorText(save.error)}</Notice> : null}
      <DiscountCard title="Discount for this customer" hint="Off MRP on everything. Leave empty for none." value={discount} onChange={setDiscount} />
      <PriceLines title="Own product prices" empty="No special prices for this customer." lines={lines} setLines={setLines} />
      <section className="card p-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="icon-disc size-7">
            <UsersRound size={14} />
          </span>
          <span className="flex-1 text-[13.5px] font-semibold">Groups</span>
          <div className="w-[240px] max-md:w-full">
            <Picker value={groupId} onChange={setGroupId} placeholder="Add to a group…" options={(allGroups.data?.items ?? []).filter((g) => !p?.groups.some((m) => m.id === g.id)).map((g) => ({ value: g.id, label: g.name }))} />
          </div>
          <Button small icon={<UserPlus size={13} />} disabled={!groupId} onClick={() => member.mutate({ id: groupId, customerId, source: 'manual' }, { onSuccess: () => setGroupId('') })}>
            Add
          </Button>
        </div>
        <div className="mt-1 divide-y divide-white/6">
          {p?.groups.length ? (
            p.groups.map((g) => (
              <div key={g.id} className="flex items-center gap-2 py-1.5 text-[13px]">
                <Link to="/customer-groups" className="min-w-0 flex-1 truncate font-semibold hover:underline">
                  {g.name}
                </Link>
                <Badge tone={g.source === 'manual' ? 'sky' : 'muted'}>{g.source === 'rule' ? 'by rules' : 'by hand'}</Badge>
                <Button small kind="ghost" icon={<UserMinus size={12} />} onClick={() => member.mutate({ id: g.id, customerId, source: g.source === 'rule' ? 'excluded' : null })}>
                  Remove
                </Button>
              </div>
            ))
          ) : (
            <p className="py-1.5 text-[12.5px] text-fg-3">Not in any group.</p>
          )}
          {p?.kept_out.map((g) => (
            <div key={g.id} className="flex items-center gap-2 py-1.5 text-[13px] text-fg-3">
              <span className="min-w-0 flex-1 truncate">{g.name} · removed by hand</span>
              <Button small kind="ghost" onClick={() => member.mutate({ id: g.id, customerId, source: null })}>
                Let back in
              </Button>
            </div>
          ))}
        </div>
      </section>
      <div className="flex justify-end">
        <Button kind="primary" busy={save.isPending} onClick={() => save.mutate(undefined)}>
          Save pricing
        </Button>
      </div>
    </div>
  )
}
