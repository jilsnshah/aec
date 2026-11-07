import { useEffect } from 'react'
import { ApiError, api } from '../api/client'
import type { TallySync } from '../api/types'
import { formatRelative } from '../lib/format'
import { useAsync } from '../lib/useAsync'
import { Badge, Button, Card, CardBody, useToast } from './ui'

const LABEL: Record<string, string> = {
  sales_order: 'Sales Order',
  sales_invoice: 'Invoice',
  purchase_order: 'Purchase Order',
}

/** Where one order stands in Tally, and whether its invoice reached the
 *  customer. Shows nothing when the order was never sent to Tally. */
export function TallyStatus({ entityId }: { entityId: string }) {
  const toast = useToast()
  const state = useAsync(() => api.integrations.tallySyncs({ entity_id: entityId }), [entityId])
  const rows: TallySync[] = state.data?.items ?? []
  const busy = rows.some((row) => row.status === 'pending' || row.notify_status === 'pending')
  useEffect(() => {
    if (!busy) return
    const timer = window.setTimeout(state.reload, 3000)
    return () => window.clearTimeout(timer)
  }, [busy, state.data])

  if (rows.length === 0) return null

  async function retry(id: string) {
    try {
      await api.integrations.retryTally(id)
      state.reload()
    } catch (cause) {
      toast.error('Could not retry', cause instanceof ApiError ? cause.message : String(cause))
    }
  }

  return (
    <Card title="Tally">
      <CardBody>
        <div className="stack stack--tight">
          {rows.map((row) => (
            <div key={row.id} className="tally-row">
              <div className="row row--between gap-2">
                <span className="cell-primary">{LABEL[row.kind]}</span>
                <Badge tone={row.status === 'synced' ? 'green' : row.status === 'failed' ? 'red' : 'blue'} dot>
                  {row.status === 'synced' ? row.tally_number ?? 'In Tally' : row.status === 'failed' ? 'Failed' : 'Sending…'}
                </Badge>
              </div>
              {row.error ? <span className="cell-sub q-negative">{row.error}</span> : null}
              {row.kind === 'sales_invoice' && row.status === 'synced' ? (
                <div className="row gap-2 cell-sub">
                  <a href={api.integrations.invoiceUrl(row.entity_id)} target="_blank" rel="noreferrer">
                    Invoice PDF
                  </a>
                  {row.notify_status === 'sent' ? (
                    <span>· WhatsApped to +{row.notify_to} {formatRelative(row.notified_at)}</span>
                  ) : row.notify_status === 'pending' ? (
                    <span>· sending on WhatsApp…</span>
                  ) : row.notify_status === 'failed' || row.notify_status === 'skipped' ? (
                    <span className="q-negative">· not sent: {row.notify_error}</span>
                  ) : null}
                </div>
              ) : null}
              {row.status === 'failed' ||
              (row.kind === 'sales_invoice' && (row.notify_status === 'failed' || row.notify_status === 'skipped')) ? (
                <Button size="sm" variant="plain" onClick={() => retry(row.id)}>
                  Retry
                </Button>
              ) : null}
            </div>
          ))}
        </div>
      </CardBody>
    </Card>
  )
}
