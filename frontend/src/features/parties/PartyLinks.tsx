import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Building2, Plus, UserRound } from 'lucide-react'
import { parties } from '@/api/parties'

/** Who at the customer this is for, and which site it goes to. */
export function PartyLinks({ customerId, contactId, onContact, siteId, onSite }: { customerId: string; contactId: string; onContact: (id: string) => void; siteId: string; onSite: (id: string) => void }) {
  const profile = useQuery({ queryKey: ['parties', 'customer', customerId], enabled: Boolean(customerId), queryFn: () => parties.profile('customer', customerId) })
  const contacts = profile.data?.contacts ?? []
  const places = (profile.data?.addresses ?? []).filter((a) => a.kind === 'site' || a.kind === 'billing' || a.kind === 'office' || a.kind === 'warehouse')
  useEffect(() => {
    if (!profile.data) return
    if (!siteId) {
      const preferred = places.find((a) => a.kind === 'site' && a.is_default) ?? (places.filter((a) => a.kind === 'site').length === 1 ? places.find((a) => a.kind === 'site') : undefined)
      if (preferred) onSite(preferred.id)
    }
    if (!contactId) {
      const main = contacts.find((c) => c.is_primary)
      if (main) onContact(main.id)
    }
  }, [profile.data]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!customerId || !profile.data) return null
  return (
    <div className="grid grid-cols-2 gap-3 max-md:grid-cols-1">
      <label className="block">
        <span className="label flex items-center gap-1.5">
          <Building2 size={12} /> Deliver to
        </span>
        <select className="field" value={siteId} onChange={(e) => onSite(e.target.value)}>
          <option value="">Not chosen</option>
          {places.map((a) => (
            <option key={a.id} value={a.id}>
              {(a.label || (a.kind === 'billing' ? 'Billing address' : a.kind)) + ' · ' + [a.line, a.city].filter(Boolean).join(', ')}
            </option>
          ))}
        </select>
        <Link to={`/customers/${customerId}?tab=profile`} className="mt-1 inline-flex items-center gap-1 text-[11.5px] text-fg-3 hover:text-fg">
          <Plus size={11} /> Add a delivery site
        </Link>
      </label>
      <label className="block">
        <span className="label flex items-center gap-1.5">
          <UserRound size={12} /> Ordered by
        </span>
        <select className="field" value={contactId} onChange={(e) => onContact(e.target.value)}>
          <option value="">Not chosen</option>
          {contacts.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
              {c.role ? ` (${c.role})` : ''}
            </option>
          ))}
        </select>
      </label>
    </div>
  )
}
