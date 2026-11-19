import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Sparkles } from 'lucide-react'
import { insights, type Period, type ProductIntel } from '@/api/insights'
import { cn } from '@/lib/cn'
import { fmtMoney } from '@/lib/format'
import { Button, Empty, Spinner } from '@/ui/core'
import { TableView } from '@/features/assistant/blocks'
import { useAssistant } from '@/features/assistant/store'

const QUADRANTS: { key: NonNullable<ProductIntel['quadrant']>; title: string; body: string }[] = [
  { key: 'star', title: 'Stars', body: 'High revenue, high margin. Never let them run out.' },
  { key: 'volume_low_margin', title: 'Volume, thin margin', body: 'Sell a lot but earn little. Check discounts and cost.' },
  { key: 'niche_high_margin', title: 'Niche, high margin', body: 'Earn well on little volume. Worth pushing.' },
  { key: 'weak', title: 'Weak', body: 'Low revenue, low margin. Review or drop.' },
]

/** Which products carry the business and which hold it back. */
export function ProductsTab({ period }: { period: Period }) {
  const navigate = useNavigate()
  const { ask } = useAssistant()
  const data = useQuery({ queryKey: ['insights', 'product-intel', period], queryFn: () => insights.products(period === 'week' || period === 'month' ? 'last_90' : period) })
  const [quadrant, setQuadrant] = useState<ProductIntel['quadrant'] | 'all'>('all')
  const rows = useMemo(() => (data.data?.products ?? []).filter((p) => quadrant === 'all' || p.quadrant === quadrant), [data.data, quadrant])
  if (data.isPending) return <Spinner />
  if (!data.data || !data.data.products.length) return <Empty title="No sales in this period" body="Product intelligence needs orders to compare." />
  const d = data.data
  const ids = (list: ProductIntel[]) => `/products?ids=${list.map((p) => p.product_id).join(',')}`
  const growing = d.products.filter((p) => p.growth === 'growing')
  const declining = d.products.filter((p) => p.growth === 'declining')
  return (
    <div className="space-y-4">
      <p className="text-[12.5px] text-fg-3">
        {d.start} to {d.end}, compared with the period before. Quadrants split products at the median revenue ({fmtMoney(d.median_revenue)}) and median margin ({d.median_margin_percent ?? '—'}%); they need delivered sales with cost.
      </p>
      <div className="grid grid-cols-4 gap-3 max-lg:grid-cols-2">
        {QUADRANTS.map((q) => {
          const members = d.products.filter((p) => p.quadrant === q.key)
          return (
            <button key={q.key} onClick={() => setQuadrant(quadrant === q.key ? 'all' : q.key)} className={cn('card lift p-4 text-left', quadrant === q.key && 'ring-2 ring-blue', q.key === 'star' && 'pane-contrast')}>
              <div className="flex items-baseline justify-between">
                <span className="text-[13px] font-semibold">{q.title}</span>
                <span className="num text-[22px] font-light">{members.length}</span>
              </div>
              <p className={cn('mt-1 text-[12px]', q.key === 'star' ? 'opacity-70' : 'text-fg-3')}>{q.body}</p>
            </button>
          )
        })}
      </div>
      <div className="flex flex-wrap gap-2">
        {growing.length ? <Button small onClick={() => navigate(ids(growing))}>Review {growing.length} growing products</Button> : null}
        {declining.length ? <Button small onClick={() => navigate(ids(declining))}>Review {declining.length} declining products</Button> : null}
        {d.weak_enquiry_conversion.length ? <Button small onClick={() => navigate(ids(d.weak_enquiry_conversion))}>{d.weak_enquiry_conversion.length} asked about but rarely bought</Button> : null}
        <Button small kind="quiet" icon={<Sparkles size={13} />} onClick={() => ask('Which products should we push, which should we fix (price, discount, cost), and which should we stop buying? Use product_intelligence and inventory_health and explain each with numbers.')}>
          What should I do with these?
        </Button>
      </div>
      <TableView
        block={{
          type: 'table',
          id: 'product-intel',
          title: quadrant === 'all' ? 'Every product sold' : QUADRANTS.find((q) => q.key === quadrant)?.title ?? '',
          dataset_id: '',
          columns: [
            { key: 'name', label: 'Product', kind: 'text', link: { id: 'product_id', route: '/products/' } },
            { key: 'abc_class', label: 'Class', kind: 'text' },
            { key: 'booked_value', label: 'Booked', kind: 'money' },
            { key: 'growth_percent', label: 'Growth', kind: 'percent' },
            { key: 'gross_profit', label: 'Profit', kind: 'money' },
            { key: 'margin_percent', label: 'Margin', kind: 'percent' },
            { key: 'discount', label: 'Discount given', kind: 'money' },
            { key: 'enquiries', label: 'Enquiries', kind: 'number' },
            { key: 'enquiry_conversion_percent', label: 'Won', kind: 'percent' },
            { key: 'short', label: 'Short', kind: 'number' },
          ],
          rows: rows as unknown as Record<string, unknown>[],
          total_rows: rows.length,
        }}
      />
      <div className="card p-4">
        <div className="text-[13px] font-semibold">Bought together</div>
        {d.bought_together === null ? (
          <p className="mt-1 text-[12.5px] text-fg-3">{d.bought_together_note}</p>
        ) : d.bought_together.length === 0 ? (
          <p className="mt-1 text-[12.5px] text-fg-3">No pair of products appears together in more than one order yet.</p>
        ) : (
          <div className="mt-2 space-y-1">
            {d.bought_together.map((pair) => (
              <div key={pair.a_id + pair.b_id} className="flex justify-between text-[12.5px]">
                <span>{pair.a} + {pair.b}</span>
                <span className="num text-fg-3">{pair.orders} orders</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
