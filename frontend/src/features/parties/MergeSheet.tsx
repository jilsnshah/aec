import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, ExternalLink, GitMerge, ShieldAlert } from 'lucide-react'
import { Link } from 'react-router-dom'
import { errorText } from '@/api/client'
import { useAction } from '@/api/queries'
import { parties, type PartyKind } from '@/api/parties'
import { useDebounced } from '@/lib/route'
import { Button, Notice } from '@/ui/core'
import { Sheet } from '@/ui/overlays'
import { Picker } from '@/ui/pickers'
import { useCustomers, useSuppliers } from '@/ui/lines'

/** Merge a duplicate record into this one: everything moves here and the
 *  duplicate is archived. */
export function MergeSheet({ kind, id, name, open, onClose }: { kind: PartyKind; id: string; name: string; open: boolean; onClose: () => void }) {
  const customers = useCustomers()
  const suppliers = useSuppliers()
  const options = (kind === 'customer' ? customers : suppliers).filter((row) => row.id !== id)
  const [other, setOther] = useState('')
  const similar = useQuery({ queryKey: ['parties', 'duplicates', kind, id, name], enabled: open, queryFn: () => parties.duplicates(kind, { name, exclude_id: id }) })
  const merge = useAction(() => parties.merge(kind, id, other), { success: 'Merged', quiet: true })
  const chosen = options.find((row) => row.id === other)
  return (
    <Sheet
      open={open}
      onClose={onClose}
      width={620}
      title={`Merge a duplicate into ${name}`}
      subtitle="The duplicate's orders, enquiries, payments, returns, calls, follow-ups, people, numbers and addresses move here; the duplicate is archived."
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button kind="primary" icon={<GitMerge size={14} />} busy={merge.isPending} disabled={!other} onClick={() => merge.mutate(undefined, { onSuccess: onClose })}>
            Merge {chosen ? `"${chosen.name}"` : ''} into {name}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {merge.error ? <Notice tone="bad">{errorText(merge.error)}</Notice> : null}
        {similar.data?.similar.length ? (
          <div>
            <div className="eyebrow mb-2">Looks like the same {kind}</div>
            <div className="flex flex-wrap gap-1.5">
              {similar.data.similar.map((hit) => (
                <button key={hit.id} onClick={() => setOther(hit.id)} className="inline-flex h-[30px] items-center gap-1.5 rounded-full bg-peri/40 px-3 text-[12px] font-semibold">
                  <AlertTriangle size={12} /> {hit.name}
                </button>
              ))}
            </div>
          </div>
        ) : null}
        <div>
          <div className="label">Duplicate to merge</div>
          <Picker value={other} onChange={setOther} placeholder={`Choose the duplicate ${kind}…`} options={options.map((row) => ({ value: row.id, label: row.name, detail: row.phone ?? undefined }))} />
        </div>
        {chosen ? (
          <Notice tone="warn" icon={<ShieldAlert size={14} />}>
            {chosen.name} will be archived and everything it has moves to {name}. This is recorded in the audit log and cannot be undone automatically.
          </Notice>
        ) : null}
      </div>
    </Sheet>
  )
}

/** Shown while a new customer or supplier is typed: records that share a
 *  number, email or GSTIN (blocking) or have a similar name. */
export function DuplicateWarning({ kind, name, phone, email, gstin, excludeId }: { kind: PartyKind; name: string; phone: string; email: string; gstin?: string; excludeId?: string }) {
  const key = useDebounced(JSON.stringify({ name, phone, email, gstin }), 400)
  const query = JSON.parse(key) as { name: string; phone: string; email: string; gstin?: string }
  const data = useQuery({
    queryKey: ['parties', 'duplicates', kind, key, excludeId],
    enabled: Boolean(query.name.trim().length > 2 || query.phone.trim() || query.email.trim() || query.gstin?.trim()),
    queryFn: () => parties.duplicates(kind, { name: query.name || undefined, phone: query.phone || undefined, email: query.email || undefined, gstin: query.gstin || undefined, exclude_id: excludeId }),
  })
  const hits = [...(data.data?.blocking ?? []).map((h) => ({ ...h, blocking: true })), ...(data.data?.similar ?? []).map((h) => ({ ...h, blocking: false }))]
  if (!hits.length) return null
  return (
    <div className="col-span-2 space-y-1.5">
      {hits.map((hit) => (
        <div key={hit.id + hit.reason} className={hit.blocking ? 'flex items-center gap-2 rounded-xl bg-[#0b0b0c] px-3 py-2 text-[12.5px] text-[#fff]' : 'flex items-center gap-2 rounded-xl bg-peri/40 px-3 py-2 text-[12.5px]'}>
          {hit.blocking ? <ShieldAlert size={14} /> : <AlertTriangle size={14} />}
          <span className="flex-1">{hit.blocking ? hit.reason[0].toUpperCase() + hit.reason.slice(1) : `Possibly the same as ${hit.name}`}</span>
          <Link to={`/${hit.kind}s/${hit.id}`} className="inline-flex items-center gap-1 font-semibold underline-offset-2 hover:underline">
            Open <ExternalLink size={12} />
          </Link>
        </div>
      ))}
    </div>
  )
}
