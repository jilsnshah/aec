import { RefreshCw } from 'lucide-react'
import { api } from '@/api/endpoints'
import { useAction, useList } from '@/api/queries'
import { fmtDateTime } from '@/lib/format'
import { Badge, Button, Empty, Spinner } from '@/ui/core'

const KIND: Record<string, string> = { sales_order: 'Sales order', sales_invoice: 'Sales invoice', purchase_order: 'Purchase order' }
const STATUS: Record<string, ['sky' | 'ok' | 'bad' | 'muted', string]> = { pending: ['sky', 'Waiting'], synced: ['ok', 'In Tally'], failed: ['bad', 'Failed'] }
const NOTIFY: Record<string, string> = { sent: 'Sent on WhatsApp', failed: 'WhatsApp failed', pending: 'Sending on WhatsApp', skipped: 'Not sent' }

/** What has gone to Tally for one order, and whether the invoice reached the customer. */
export function TallyPanel({ entityId }: { entityId: string }) {
  const syncs = useList('tally-syncs', api.integrations.syncs, { entity_id: entityId, limit: 20 })
  const retry = useAction(api.integrations.retrySync, { success: 'Sent to Tally again' })
  if (syncs.isPending) return <Spinner />
  const rows = syncs.data?.items ?? []
  if (rows.length === 0) return <Empty title="Not sent to Tally" body="When Tally is connected, this order and its invoice are sent automatically." />
  return (
    <div className="space-y-2 p-4">
      {rows.map((row) => {
        const [tone, label] = STATUS[row.status] ?? ['muted', row.status]
        return (
          <div key={row.id} className="card flex items-center gap-3 p-4">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 text-[13px] font-medium">
                {KIND[row.kind] ?? row.kind}
                <Badge tone={tone} dot>
                  {label}
                </Badge>
              </div>
              <div className="mt-0.5 text-[12px] text-fg-3">
                {row.tally_number ? `Tally no. ${row.tally_number} · ` : ''}
                {row.synced_at ? fmtDateTime(row.synced_at) : `${row.attempts} attempt${row.attempts === 1 ? '' : 's'}`}
                {row.kind === 'sales_invoice' && row.notify_status ? ` · ${NOTIFY[row.notify_status] ?? row.notify_status}` : ''}
              </div>
              {row.error ? <div className="mt-1 text-[12px] text-bad">{row.error}</div> : null}
              {row.notify_error ? <div className="mt-1 text-[12px] text-warn">{row.notify_error}</div> : null}
            </div>
            {row.status === 'failed' ? (
              <Button small icon={<RefreshCw size={13} />} busy={retry.isPending} onClick={() => retry.mutate(row.id)}>
                Retry
              </Button>
            ) : null}
          </div>
        )
      })}
    </div>
  )
}
