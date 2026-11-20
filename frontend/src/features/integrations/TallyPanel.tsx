import { useQuery } from '@tanstack/react-query'
import { FileCheck2, QrCode, RefreshCw, Search, Truck } from 'lucide-react'
import { http } from '@/api/client'
import { api } from '@/api/endpoints'
import { useAction, useList } from '@/api/queries'
import { fmtDateTime } from '@/lib/format'
import { Badge, Button, Empty, Spinner } from '@/ui/core'

const KIND: Record<string, string> = {
  sales_order: 'Sales order',
  sales_invoice: 'Sales invoice',
  delivery_invoice: 'Invoice for a delivery',
  purchase_order: 'Purchase order',
  stock_transfer: 'Stock journal (transfer)',
  purchase_return: 'Debit note (return)',
}
const STATUS: Record<string, ['sky' | 'ok' | 'bad' | 'muted', string]> = { pending: ['sky', 'Waiting'], synced: ['ok', 'In Tally'], failed: ['bad', 'Failed'] }
const NOTIFY: Record<string, string> = { sent: 'Sent on WhatsApp', failed: 'WhatsApp failed', pending: 'Sending on WhatsApp', skipped: 'Not sent' }
const STATUTORY = new Set(['sales_invoice', 'delivery_invoice', 'stock_transfer', 'purchase_return'])

interface Doc {
  id: string
  kind: string
  reference: string
  status: string
  tally_number: string | null
  error: string | null
  synced_at: string | null
  irn: string | null
  irn_ack_no: string | null
  irn_ack_date: string | null
  has_qr: boolean
  eway_bill_no: string | null
  eway_bill_date: string | null
  checked_at: string | null
}

/** What has gone to Tally for one order (and its deliveries): the vouchers,
 *  whether the invoice reached the customer, and the e-invoice (IRN) and
 *  e-way bill Tally generated for them. */
export function TallyPanel({ entityId }: { entityId: string }) {
  const syncs = useList('tally-syncs', api.integrations.syncs, { entity_id: entityId, limit: 20 })
  const docs = useQuery({ queryKey: ['tally-documents', entityId], queryFn: () => http.get<{ items: Doc[] }>(`/api/integrations/orders/${entityId}/tally-documents`) })
  const retry = useAction(api.integrations.retrySync, { success: 'Sent to Tally again' })
  const check = useAction((id: string) => http.post<{ found: number; irn: string | null; eway_bill_no: string | null }>(`/api/integrations/tally/statutory/refresh?sync_id=${id}`), {
    success: (r) => (r.irn || r.eway_bill_no ? 'Found in Tally' : 'Not generated in Tally yet'),
  })
  if (syncs.isPending || docs.isPending) return <Spinner />
  const notify = new Map((syncs.data?.items ?? []).map((row) => [row.id, row]))
  const rows = docs.data?.items ?? []
  if (rows.length === 0) return <Empty title="Not sent to Tally" body="When Tally is connected, this order and its invoice are sent automatically." />
  return (
    <div className="space-y-2 p-4">
      {rows.map((row) => {
        const [tone, label] = STATUS[row.status] ?? ['muted', row.status]
        const extra = notify.get(row.id)
        const statutory = STATUTORY.has(row.kind) && row.status === 'synced'
        return (
          <div key={row.id} className="card p-4">
            <div className="flex items-center gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2 text-[13px] font-medium">
                  {KIND[row.kind] ?? row.kind}
                  <span className="text-fg-3">{row.reference}</span>
                  <Badge tone={tone} dot>
                    {label}
                  </Badge>
                </div>
                <div className="mt-0.5 text-[12px] text-fg-3">
                  {row.tally_number ? `Tally no. ${row.tally_number} · ` : ''}
                  {row.synced_at ? fmtDateTime(row.synced_at) : extra ? `${extra.attempts} attempt${extra.attempts === 1 ? '' : 's'}` : ''}
                  {(row.kind === 'sales_invoice' || row.kind === 'delivery_invoice') && extra?.notify_status ? ` · ${NOTIFY[extra.notify_status] ?? extra.notify_status}` : ''}
                </div>
                {row.error ? <div className="mt-1 text-[12px] text-bad">{row.error}</div> : null}
                {extra?.notify_error ? <div className="mt-1 text-[12px] text-warn">{extra.notify_error}</div> : null}
              </div>
              {row.status === 'failed' ? (
                <Button small icon={<RefreshCw size={13} />} busy={retry.isPending} onClick={() => retry.mutate(row.id)}>
                  Retry
                </Button>
              ) : null}
            </div>
            {statutory ? (
              <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-white/6 pt-3 text-[12px]">
                {row.irn ? (
                  <Badge tone="ok" title={row.irn}>
                    <FileCheck2 size={12} /> e-Invoice · Ack {row.irn_ack_no ?? '—'}
                    {row.has_qr ? <QrCode size={12} /> : null}
                  </Badge>
                ) : (
                  <Badge>No e-invoice yet</Badge>
                )}
                {row.eway_bill_no ? (
                  <Badge tone="ok">
                    <Truck size={12} /> E-way bill {row.eway_bill_no}
                  </Badge>
                ) : (
                  <Badge>No e-way bill yet</Badge>
                )}
                <span className="flex-1 text-fg-3">{row.checked_at ? `Checked ${fmtDateTime(row.checked_at)}` : 'Generate them in Tally; they are picked up automatically.'}</span>
                {!row.irn || !row.eway_bill_no ? (
                  <Button small kind="ghost" icon={<Search size={12} />} busy={check.isPending} onClick={() => check.mutate(row.id)}>
                    Check Tally now
                  </Button>
                ) : null}
              </div>
            ) : null}
          </div>
        )
      })}
    </div>
  )
}
