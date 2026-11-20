import { useQuery } from '@tanstack/react-query'
import { Download, FileText } from 'lucide-react'
import { errorText, http } from '@/api/client'
import { fmtDate, fmtMoney } from '@/lib/format'
import type { PortalInvoice } from './types'
import { Empty, Loading } from './ui'

export function InvoicesTab({ token }: { token: string }) {
  const data = useQuery({
    queryKey: ['public', token, 'invoices'],
    queryFn: () => http.get<{ invoices: PortalInvoice[] }>(`/api/public/e/${token}/invoices`),
    retry: false,
  })
  if (data.isPending) return <Loading />
  if (data.error) return <Empty text={errorText(data.error)} />
  if (!data.data.invoices.length) return <Empty icon={<FileText size={22} />} text="No invoices yet. Invoices appear here once they are made." />
  return (
    <div className="space-y-2">
      {data.data.invoices.map((inv) => (
        <a key={inv.id} href={inv.download} target="_blank" rel="noreferrer" className="card flex items-center gap-3 p-3">
          <span className="icon-tile size-10 shrink-0">
            <FileText size={17} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="break-words text-[14px] font-semibold">{inv.number}</div>
            <div className="text-[12.5px] text-fg-3">
              {fmtDate(inv.date)}
              {inv.order_number ? ` · ${inv.order_number}` : ''}
              {inv.eway_bill_number ? ` · E-way ${inv.eway_bill_number}` : ''}
            </div>
          </div>
          <div className="shrink-0 text-right">
            {inv.amount != null ? <div className="num text-[13.5px] font-semibold">{fmtMoney(inv.amount)}</div> : null}
            <span className="inline-flex items-center gap-1 text-[12px] text-blue">
              <Download size={13} /> PDF
            </span>
          </div>
        </a>
      ))}
      <p className="pt-1 text-[12px] text-fg-3">Amounts are before GST; the PDF shows the full invoice.</p>
    </div>
  )
}
