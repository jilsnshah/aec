import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Ban, Crown, Eye, Plus, RefreshCw, Sparkles, Tags, Trash2, UserMinus, UserPlus, Users, Wand2 } from 'lucide-react'
import { errorText } from '@/api/client'
import { useAction } from '@/api/queries'
import { groups, type Group, type Rule } from '@/api/groups'
import { priceLists } from '@/api/records'
import { cn } from '@/lib/cn'
import { fmtAgo, fmtMoney } from '@/lib/format'
import { Badge, Button, Empty, Notice, Spinner } from '@/ui/core'
import { Picker } from '@/ui/pickers'
import { useCustomers } from '@/ui/lines'
import { ListPane, ListRow, SplitView } from '@/ui/split'
import { PageGuide, Stat } from '@/ui/smart'

const OP_LABEL: Record<string, string> = { '>=': 'at least', '<=': 'at most', '>': 'more than', '<': 'less than', '=': 'is', '!=': 'is not' }
const EXAMPLES: { name: string; rules: Rule[] }[] = [
  { name: 'Gold builders', rules: [{ field: 'spend_12m', op: '>=', value: 1000000 }, { field: 'years_with_us', op: '>=', value: 2 }, { field: 'oldest_overdue_days', op: '<=', value: 30 }] },
  { name: 'Regulars', rules: [{ field: 'orders_90d', op: '>=', value: 3 }] },
  { name: 'Win back', rules: [{ field: 'days_since_last_order', op: '>=', value: 90 }, { field: 'orders_total', op: '>=', value: 3 }] },
]

/** Customers grouped automatically by rules, each group with a price list. */
export function CustomerGroups() {
  const list = useQuery({ queryKey: ['customer-groups'], queryFn: groups.list })
  const [selected, setSelected] = useState<string | 'new' | null>(null)
  const [template, setTemplate] = useState<{ name: string; rules: Rule[] } | null>(null)
  const recalc = useAction(groups.recalculate, { success: 'Groups recalculated' })
  const items = list.data?.items ?? []
  useEffect(() => {
    if (!selected && items.length) setSelected(items[0].id)
  }, [items.length]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <SplitView
      showDetail={Boolean(selected)}
      onBack={() => setSelected(null)}
      list={
        <ListPane
          title="Groups"
          count={items.length}
          actions={
            <>
              <PageGuide
                title="Smart customer groups"
                points={[
                  { icon: Wand2, text: 'Rules pick the members: orders and spend in the last year, years with you, days since last order, money overdue, segment, city.' },
                  { icon: Tags, text: 'Link a price list to give the group its prices. A customer in several groups gets the best price for each product.' },
                  { icon: UserPlus, text: 'Add a customer by hand or keep one out; rules never undo that.' },
                  { icon: RefreshCw, text: 'Members are recalculated once a day, or now with Recalculate.' },
                ]}
              />
              <Button small kind="ghost" iconOnly busy={recalc.isPending} onClick={() => recalc.mutate(undefined)} aria-label="Recalculate all groups" title="Recalculate all groups">
                <RefreshCw size={14} />
              </Button>
              <Button kind="primary" small icon={<Plus size={14} />} onClick={() => (setTemplate(null), setSelected('new'))}>
                New
              </Button>
            </>
          }
        >
          {list.isPending ? (
            <Spinner />
          ) : !items.length ? (
            <div className="space-y-2 p-3">
              <Empty icon={<Users size={20} />} title="No groups yet" body="Start from an example:" />
              {EXAMPLES.map((example) => (
                <button key={example.name} onClick={() => (setTemplate(example), setSelected('new'))} className="card w-full p-3 text-left hover:shadow-[var(--shadow-lift)]">
                  <div className="text-[13px] font-semibold">{example.name}</div>
                  <div className="text-[12px] text-fg-3">{example.rules.map((r) => `${r.field.replace(/_/g, ' ')} ${OP_LABEL[r.op]} ${r.value}`).join(' · ')}</div>
                </button>
              ))}
            </div>
          ) : (
            items.map((group) => (
              <ListRow key={group.id} group="customer-groups" selected={group.id === selected} onSelect={() => setSelected(group.id)}>
                <div className="flex items-center gap-2">
                  <span className="truncate text-[13px] font-semibold">{group.name}</span>
                  {!group.is_active ? <Badge>Off</Badge> : null}
                  <span className="num ml-auto text-[12.5px] font-semibold">{group.member_count}</span>
                  <Users size={12} className="text-fg-3" />
                </div>
                <div className="mt-0.5 truncate text-[12px] text-fg-3">
                  {group.price_list_name ? `${group.price_list_name}` : 'No price list'} · {group.rules.length} rule{group.rules.length === 1 ? '' : 's'}
                </div>
              </ListRow>
            ))
          )}
        </ListPane>
      }
    >
      {selected === 'new' ? (
        <Editor key={'new' + (template?.name ?? '')} template={template} onSaved={(g) => setSelected(g.id)} />
      ) : selected ? (
        <GroupView key={selected} id={selected} onDeleted={() => setSelected(null)} />
      ) : (
        <Empty className="h-full" icon={<Users size={22} />} title="Choose a group" />
      )}
    </SplitView>
  )
}

function GroupView({ id, onDeleted }: { id: string; onDeleted: () => void }) {
  const data = useQuery({ queryKey: ['customer-groups', id], queryFn: () => groups.get(id) })
  if (data.isPending) return <Spinner />
  if (!data.data) return <Empty title="Group not found" />
  return <Editor group={data.data} onSaved={() => undefined} onDeleted={onDeleted} />
}

function Editor({ group, template, onSaved, onDeleted }: { group?: Group; template?: { name: string; rules: Rule[] } | null; onSaved: (g: Group) => void; onDeleted?: () => void }) {
  const fields = useQuery({ queryKey: ['customer-groups', 'fields'], queryFn: groups.fields })
  const lists = useQuery({ queryKey: ['price-lists'], queryFn: () => priceLists.list(true) })
  const customers = useCustomers()
  const [name, setName] = useState(group?.name ?? template?.name ?? '')
  const [description, setDescription] = useState(group?.description ?? '')
  const [match, setMatch] = useState<'all' | 'any'>(group?.match ?? 'all')
  const [rules, setRules] = useState<Rule[]>(group?.rules ?? template?.rules ?? [{ field: 'orders_12m', op: '>=', value: 3 }])
  const [listId, setListId] = useState(group?.price_list_id ?? '')
  const [active, setActive] = useState(group?.is_active ?? true)
  const [addId, setAddId] = useState('')
  const body = { name, description: description || null, match, rules, price_list_id: listId || null, is_active: active }
  const save = useAction(() => (group ? groups.update({ id: group.id, ...body }) : groups.create(body)), { success: 'Group saved', quiet: true })
  const preview = useAction(() => groups.preview({ rules, match }), { quiet: true })
  const member = useAction(groups.setMember)
  const remove = useAction(async () => {
    if (group) await groups.remove(group.id)
  }, { success: 'Group deleted' })
  const fieldOf = (key: string) => fields.data?.fields.find((f) => f.key === key)
  const update = (index: number, patch: Partial<Rule>) => setRules(rules.map((r, i) => (i === index ? { ...r, ...patch } : r)))
  const members = group?.members ?? []
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex shrink-0 flex-wrap items-center gap-3 border-b border-white/7 px-7 py-5 max-md:px-4">
        <span className="icon-tile size-12">
          <Users size={22} />
        </span>
        <div className="min-w-[200px] flex-1">
          <div className="eyebrow">Customer group</div>
          <h2 className="truncate text-[22px] font-semibold tracking-[-0.02em]">{name || 'New group'}</h2>
        </div>
        {group && onDeleted ? (
          <Button kind="ghost" icon={<Trash2 size={14} />} onClick={() => remove.mutate(undefined, { onSuccess: onDeleted })}>
            Delete
          </Button>
        ) : null}
        <Button icon={<Eye size={14} />} busy={preview.isPending} onClick={() => preview.mutate(undefined)}>
          Preview
        </Button>
        <Button kind="primary" busy={save.isPending} disabled={!name.trim()} onClick={() => save.mutate(undefined, { onSuccess: onSaved })}>
          Save
        </Button>
      </header>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-7 pb-24 max-md:p-4">
        {save.error ? <Notice tone="bad">{errorText(save.error)}</Notice> : null}
        {group ? (
          <div className="grid grid-cols-[repeat(auto-fit,minmax(190px,1fr))] gap-3">
            <Stat strong icon={Users} label="Members" value={group.member_count} hint={group.last_computed_at ? `updated ${fmtAgo(group.last_computed_at)}` : 'not calculated'} />
            <Stat icon={Tags} label="Price list" value={group.price_list_name ?? 'None'} hint={group.price_list_discount ? `${group.price_list_discount}% off everything` : 'linked prices'} />
            <Stat icon={Wand2} label="Rules" value={group.rules.length} hint={group.match === 'all' ? 'all must match' : 'any can match'} />
          </div>
        ) : null}
        <div className="grid grid-cols-2 gap-3 max-md:grid-cols-1">
          <label className="block">
            <span className="label">Name</span>
            <input className="field" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Gold builders" />
          </label>
          <label className="block">
            <span className="label">Price list for members</span>
            <select className="field" value={listId} onChange={(e) => setListId(e.target.value)}>
              <option value="">None (group only)</option>
              {(lists.data?.items ?? []).map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                  {l.discount_percent ? ` (${l.discount_percent}% off)` : ''}
                </option>
              ))}
            </select>
          </label>
          <label className="col-span-2 block max-md:col-span-1">
            <span className="label">Description</span>
            <input className="field" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Who this is for" />
          </label>
        </div>
        <section className="card p-4">
          <div className="flex flex-wrap items-center gap-2">
            <span className="icon-disc size-7">
              <Wand2 size={14} />
            </span>
            <span className="text-[13.5px] font-semibold">Customers who match</span>
            <div className="flex gap-1">
              {(['all', 'any'] as const).map((m) => (
                <button key={m} onClick={() => setMatch(m)} className={cn('h-[28px] rounded-full px-3 text-[12px] font-semibold', match === m ? 'brand-fill' : 'bg-ink-700 text-fg-2')}>
                  {m === 'all' ? 'all of' : 'any of'}
                </button>
              ))}
            </div>
            <span className="text-[13px] text-fg-3">these rules</span>
            <span className="flex-1" />
            <label className="flex items-center gap-1.5 text-[12.5px]">
              <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} /> Active
            </label>
          </div>
          <div className="mt-3 space-y-2">
            {rules.map((rule, index) => {
              const field = fieldOf(rule.field)
              return (
                <div key={index} className="flex flex-wrap items-center gap-2 rounded-xl bg-white/5 p-2">
                  <select className="field field-sm min-w-[220px] flex-1" value={rule.field} onChange={(e) => update(index, { field: e.target.value, value: '' })} aria-label="Field">
                    {(fields.data?.fields ?? []).map((f) => (
                      <option key={f.key} value={f.key}>
                        {f.label}
                      </option>
                    ))}
                  </select>
                  <select className="field field-sm w-[130px]" value={rule.op} onChange={(e) => update(index, { op: e.target.value })} aria-label="Comparison">
                    {(field?.type === 'choice' || field?.type === 'text' ? ['=', '!='] : ['>=', '<=', '>', '<', '=', '!=']).map((op) => (
                      <option key={op} value={op}>
                        {OP_LABEL[op]}
                      </option>
                    ))}
                  </select>
                  {field?.type === 'choice' ? (
                    <select className="field field-sm w-[150px]" value={String(rule.value)} onChange={(e) => update(index, { value: e.target.value })} aria-label="Value">
                      <option value="">Choose…</option>
                      {field.choices?.map((c) => (
                        <option key={c} value={c}>
                          {c.replace('_', ' ')}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input className="field field-sm w-[150px] text-right" value={String(rule.value)} inputMode={field?.type === 'text' ? 'text' : 'decimal'} onChange={(e) => update(index, { value: e.target.value })} aria-label="Value" />
                  )}
                  <span className="w-[60px] text-[12px] text-fg-3">{field?.unit ?? ''}</span>
                  <button className="grid size-7 place-items-center rounded-full text-fg-3 hover:bg-white/8" aria-label="Remove rule" onClick={() => setRules(rules.filter((_, i) => i !== index))}>
                    <Trash2 size={13} />
                  </button>
                </div>
              )
            })}
            <Button small icon={<Plus size={13} />} onClick={() => setRules([...rules, { field: 'spend_12m', op: '>=', value: '' }])}>
              Add rule
            </Button>
          </div>
        </section>
        {preview.error ? <Notice tone="bad">{errorText(preview.error)}</Notice> : null}
        {preview.data ? (
          <section className="card overflow-hidden">
            <div className="flex items-center gap-2 px-4 pt-3.5 pb-2 text-[13px] font-semibold">
              <Sparkles size={14} /> {preview.data.count} of {preview.data.of} customers match
            </div>
            <div className="overflow-x-auto">
              <table className="grid-table min-w-[620px]">
                <thead>
                  <tr>
                    <th>Customer</th>
                    <th className="r">Orders (12 mo)</th>
                    <th className="r">Spend (12 mo)</th>
                    <th className="r">Years</th>
                    <th className="r">Overdue</th>
                    <th>Segment</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.data.customers.map((row) => (
                    <tr key={row.customer_id}>
                      <td className="text-[13px] font-medium">
                        <Link to={`/customers/${row.customer_id}`} className="hover:underline">
                          {row.name}
                        </Link>
                      </td>
                      <td className="r num">{row.orders_12m}</td>
                      <td className="r num">{fmtMoney(row.spend_12m)}</td>
                      <td className="r num">{row.years_with_us.toFixed(1)}</td>
                      <td className="r num">{row.overdue ? fmtMoney(row.overdue) : '—'}</td>
                      <td>
                        <Badge>{row.segment.replace('_', ' ')}</Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        ) : null}
        {group ? (
          <section className="card p-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className="icon-disc size-7">
                <Crown size={14} />
              </span>
              <span className="flex-1 text-[13.5px] font-semibold">Members</span>
              <div className="w-[260px] max-md:w-full">
                <Picker value={addId} onChange={setAddId} placeholder="Add a customer by hand…" options={customers.filter((c) => c.is_active).map((c) => ({ value: c.id, label: c.name }))} />
              </div>
              <Button small icon={<UserPlus size={13} />} disabled={!addId} onClick={() => member.mutate({ id: group.id, customerId: addId, source: 'manual' }, { onSuccess: () => setAddId('') })}>
                Add
              </Button>
            </div>
            <div className="mt-3 divide-y divide-white/6">
              {members.length ? (
                members.map((m) => (
                  <div key={m.customer_id} className={cn('flex items-center gap-2 py-2 text-[13px]', m.source === 'excluded' && 'opacity-60')}>
                    <Link to={`/customers/${m.customer_id}`} className="min-w-0 flex-1 truncate font-medium hover:underline">
                      {m.name}
                    </Link>
                    <Badge tone={m.source === 'manual' ? 'sky' : m.source === 'excluded' ? 'bad' : 'muted'}>{m.source === 'rule' ? 'by rules' : m.source === 'manual' ? 'added by hand' : 'kept out'}</Badge>
                    {m.source === 'rule' ? (
                      <Button small kind="ghost" icon={<Ban size={12} />} onClick={() => member.mutate({ id: group.id, customerId: m.customer_id, source: 'excluded' })}>
                        Keep out
                      </Button>
                    ) : (
                      <Button small kind="ghost" icon={<UserMinus size={12} />} onClick={() => member.mutate({ id: group.id, customerId: m.customer_id, source: null })}>
                        Undo
                      </Button>
                    )}
                  </div>
                ))
              ) : (
                <p className="py-2 text-[12.5px] text-fg-3">Nobody matches yet.</p>
              )}
            </div>
          </section>
        ) : null}
      </div>
    </div>
  )
}
