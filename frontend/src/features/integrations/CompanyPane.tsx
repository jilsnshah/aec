import { useEffect, useState } from 'react'
import { Building2, Clock, CreditCard, FileText, MessageCircle, Phone, ScrollText, Sparkles, Truck, UserRound } from 'lucide-react'
import { api } from '@/api/endpoints'
import { useAction } from '@/api/queries'
import type { IntegrationsOut } from '@/api/types'
import { Button } from '@/ui/core'

const FIELDS = [
  { key: 'company_profile', label: 'About the business', icon: Building2, rows: 12, max: 30000,
    placeholder: 'Who you are, what you sell (brands, grades, sizes), who you sell to, areas you serve, what makes you different, common questions and their answers… Paste anything: brochure text, price notes, FAQs.' },
  { key: 'company_hours', label: 'Hours', icon: Clock, rows: 2, max: 2000, placeholder: 'Mon–Sat 9 am – 7 pm, Sunday closed. Yard open from 8 am for loading.' },
  { key: 'company_delivery', label: 'Delivery', icon: Truck, rows: 4, max: 4000, placeholder: 'Areas, minimum order for free delivery, charges, usual time (same day before 2 pm), unloading…' },
  { key: 'company_payment', label: 'Payment', icon: CreditCard, rows: 3, max: 4000, placeholder: 'UPI / bank details, credit for regular customers, cheques, advance for new customers…' },
  { key: 'company_policies', label: 'Policies', icon: ScrollText, rows: 4, max: 8000, placeholder: 'Returns, damaged goods, price validity, GST invoices, anything the assistant must never promise…' },
] as const

/** What the agents (TAI on WhatsApp and email, PAI on calls, the assistant)
 *  know about the business. */
export function CompanyPane({ data }: { data: IntegrationsOut }) {
  const config = data.ai.config as Record<string, unknown>
  const initial = () => ({
    ...Object.fromEntries(FIELDS.map((f) => [f.key, String(config[f.key] ?? '')])),
    agent_name: String(config.agent_name ?? 'Asha'),
    agent_tone: String(config.agent_tone ?? 'warm and brief'),
  })
  const [form, setForm] = useState<Record<string, string>>(initial)
  useEffect(() => setForm(initial()), [data]) // eslint-disable-line react-hooks/exhaustive-deps
  const save = useAction(() => api.integrations.update('ai', { config: form }), { success: 'Company knowledge saved' })
  const filled = FIELDS.filter((f) => form[f.key]?.trim()).length
  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <header className="flex flex-wrap items-center gap-4 border-b border-white/7 px-6 py-5">
        <span className="icon-disc size-11">
          <Sparkles size={18} />
        </span>
        <div className="min-w-[220px] flex-1">
          <h2 className="text-[18px] font-semibold tracking-[-0.02em]">Company knowledge</h2>
          <p className="text-[12.5px] text-fg-3">
            Everything the AI should know about the business. TAI (WhatsApp, email), PAI (phone calls) and the assistant answer from this and from live stock and prices, nothing else.
          </p>
        </div>
        <Button kind="primary" busy={save.isPending} onClick={() => save.mutate(undefined)}>
          Save
        </Button>
      </header>
      <div className="grid max-w-[1100px] grid-cols-[1fr_300px] gap-5 p-6 pb-24 max-xl:grid-cols-1">
        <div className="space-y-4">
          {FIELDS.map((field) => (
            <label key={field.key} className="card block p-4">
              <span className="flex items-center gap-2 text-[13.5px] font-semibold">
                <field.icon size={15} /> {field.label}
                <span className="ml-auto text-[11px] font-normal text-fg-3">
                  {form[field.key]?.length ?? 0} / {field.max.toLocaleString('en-IN')}
                </span>
              </span>
              <textarea
                className="field mt-2 font-[inherit]"
                rows={field.rows}
                maxLength={field.max}
                placeholder={field.placeholder}
                value={form[field.key] ?? ''}
                onChange={(e) => setForm({ ...form, [field.key]: e.target.value })}
              />
            </label>
          ))}
        </div>
        <aside className="space-y-4">
          <div className="card space-y-3 p-4">
            <div className="flex items-center gap-2 text-[13.5px] font-semibold">
              <UserRound size={15} /> How the agents introduce themselves
            </div>
            <label className="block">
              <span className="label">Name</span>
              <input className="field" value={form.agent_name} onChange={(e) => setForm({ ...form, agent_name: e.target.value })} />
            </label>
            <label className="block">
              <span className="label">Tone</span>
              <input className="field" value={form.agent_tone} onChange={(e) => setForm({ ...form, agent_tone: e.target.value })} placeholder="warm and brief" />
            </label>
            <p className="text-[11.5px] text-fg-3">They say they are the business's virtual assistant, and admit being an AI when asked. Language follows the customer: Gujarati, Hindi or English.</p>
          </div>
          <div className="pane-contrast space-y-2 rounded-2xl! p-4 text-[12.5px]">
            <div className="flex items-center gap-2 font-semibold">
              <FileText size={14} /> {filled} of {FIELDS.length} sections written
            </div>
            <p className="flex gap-2">
              <MessageCircle size={13} className="mt-0.5 shrink-0" /> TAI uses this on WhatsApp and email.
            </p>
            <p className="flex gap-2">
              <Phone size={13} className="mt-0.5 shrink-0" /> PAI uses it on calls.
            </p>
            <p className="opacity-75">What each agent may do (answer, quote, take orders) is set step by step in Settings → Automation.</p>
          </div>
        </aside>
      </div>
    </div>
  )
}
