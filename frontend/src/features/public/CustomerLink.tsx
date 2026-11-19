import { useQuery } from '@tanstack/react-query'
import { Copy, Link2, Link2Off, MessageCircle, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { http } from '@/api/client'
import { useAction } from '@/api/queries'
import { Button } from '@/ui/core'

/** The customer's own enquiry page: make, share, replace or switch off. */
export function CustomerLink({ customerId, name, phone }: { customerId: string; name: string; phone: string | null }) {
  const link = useQuery({ queryKey: ['enquiry-link', customerId], queryFn: () => http.get<{ enabled: boolean; path: string | null }>(`/api/customers/${customerId}/enquiry-link`) })
  const set = useAction((enabled: boolean) => http.post<{ enabled: boolean; path: string | null }>(`/api/customers/${customerId}/enquiry-link`, { enabled }), { success: (r) => (r.enabled ? 'New link ready' : 'Link switched off') })
  const url = link.data?.path ? `${window.location.origin}${link.data.path}` : null
  const message = url ? `Hello ${name}, you can send us your requirements any time here, with your prices: ${url}` : ''
  return (
    <div className="space-y-2">
      <div className="eyebrow flex items-center gap-1.5">
        <Link2 size={12} /> Enquiry link
      </div>
      {url ? (
        <>
          <p className="truncate rounded-lg bg-white/5 px-2.5 py-1.5 text-[12px] text-fg-2" title={url} data-selectable>
            {url}
          </p>
          <div className="flex flex-wrap gap-1.5">
            <Button small icon={<Copy size={12} />} onClick={() => navigator.clipboard.writeText(url).then(() => toast.success('Link copied'))}>
              Copy
            </Button>
            <a className="btn btn-sm" href={`https://wa.me/${(phone ?? '').replace(/\D/g, '').replace(/^(\d{10})$/, '91$1')}?text=${encodeURIComponent(message)}`} target="_blank" rel="noreferrer">
              <MessageCircle size={12} /> Send
            </a>
            <Button small kind="ghost" iconOnly aria-label="Replace link" title="Replace link (the old one stops working)" onClick={() => set.mutate(true)}>
              <RefreshCw size={12} />
            </Button>
            <Button small kind="ghost" iconOnly aria-label="Switch off link" title="Switch off" onClick={() => set.mutate(false)}>
              <Link2Off size={12} />
            </Button>
          </div>
        </>
      ) : (
        <Button small className="w-full" icon={<Link2 size={12} />} busy={set.isPending} onClick={() => set.mutate(true)}>
          Create a link for {name.split(' ')[0]}
        </Button>
      )}
      <p className="text-[11px] text-fg-3">They see your products with their prices and send enquiries straight in.</p>
    </div>
  )
}
