import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { CalendarHeart, Palette, Plus, ShieldCheck, Trash2 } from 'lucide-react'
import { marketing } from '@/api/marketing'
import { useAction } from '@/api/queries'
import { Button, Field, Notice, Spinner } from '@/ui/core'
import { Segmented } from '@/ui/overlays'
import { Page, Panel } from './shared'

interface Form {
  brand_name: string
  brand_tone: string
  brand_colors: string[]
  brand_hashtags: string
  brand_avoid: string
  brand_signature: string
  whatsapp_number: string
  approval: string
  auto_max_audience: string
  frequency_max: string
  frequency_days: string
  quiet_start: string
  quiet_end: string
  timezone: string
  send_per_minute: string
  attribution_days: string
  opt_out_words: string
  message_cost: string
  public_url: string
  image_model: string
  scan_hours: string
  analyst_weekday: string
  occasions: { name: string; date: string; lead_days: number }[]
}

const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

export function MarketingSettings() {
  const data = useQuery({ queryKey: ['marketing', 'settings'], queryFn: marketing.settings })
  const [form, setForm] = useState<Form | null>(null)
  const save = useAction(marketing.saveSettings, { success: 'Saved' })
  useEffect(() => {
    const c = data.data?.marketing.config
    if (!c) return
    const s = (k: string) => String(c[k] ?? '')
    setForm({
      brand_name: s('brand_name'),
      brand_tone: s('brand_tone'),
      brand_colors: (c.brand_colors as string[]) ?? ['#0B1220', '#38BDF8', '#FFFFFF'],
      brand_hashtags: ((c.brand_hashtags as string[]) ?? []).join(' '),
      brand_avoid: s('brand_avoid'),
      brand_signature: s('brand_signature'),
      whatsapp_number: s('whatsapp_number'),
      approval: s('approval') || 'approval',
      auto_max_audience: s('auto_max_audience'),
      frequency_max: s('frequency_max'),
      frequency_days: s('frequency_days'),
      quiet_start: s('quiet_start'),
      quiet_end: s('quiet_end'),
      timezone: s('timezone'),
      send_per_minute: s('send_per_minute'),
      attribution_days: s('attribution_days'),
      opt_out_words: ((c.opt_out_words as string[]) ?? []).join(', '),
      message_cost: s('message_cost'),
      public_url: s('public_url'),
      image_model: s('image_model'),
      scan_hours: s('scan_hours'),
      analyst_weekday: s('analyst_weekday'),
      occasions: (c.occasions as Form['occasions']) ?? [],
    })
  }, [data.data])
  if (data.isPending || !form) return <Spinner />
  const set = (patch: Partial<Form>) => setForm((f) => (f ? { ...f, ...patch } : f))
  const submit = () =>
    save.mutate({
      name: 'marketing',
      config: {
        ...form,
        brand_hashtags: form.brand_hashtags.split(/[\s,]+/).filter(Boolean),
        opt_out_words: form.opt_out_words.split(',').map((w) => w.trim()).filter(Boolean),
        auto_max_audience: Number(form.auto_max_audience),
        frequency_max: Number(form.frequency_max),
        frequency_days: Number(form.frequency_days),
        send_per_minute: Number(form.send_per_minute),
        attribution_days: Number(form.attribution_days),
        message_cost: Number(form.message_cost),
        scan_hours: Number(form.scan_hours),
        analyst_weekday: Number(form.analyst_weekday),
      },
    })
  return (
    <Page className="space-y-3">
      <div className="grid gap-3 xl:grid-cols-2">
        <Panel title="Brand kit" icon={Palette}>
          <p className="mb-3 text-[12.5px] text-fg-3">The Creative agent follows this for every caption, message and card.</p>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Business name on creatives">{(props) => <input {...props} className="field" value={form.brand_name} onChange={(e) => set({ brand_name: e.target.value })} />}</Field>
            <Field label="WhatsApp number to show" optional>{(props) => <input {...props} className="field" value={form.whatsapp_number} onChange={(e) => set({ whatsapp_number: e.target.value })} placeholder="+91 98250 00000" />}</Field>
            <Field label="Tone" className="sm:col-span-2">{(props) => <input {...props} className="field" value={form.brand_tone} onChange={(e) => set({ brand_tone: e.target.value })} />}</Field>
            <Field label="Colours" hint="Background, accent, and a third for text or details." className="sm:col-span-2">
              {() => (
                <div className="flex flex-wrap gap-3">
                  {form.brand_colors.map((c, i) => (
                    <label key={i} className="flex items-center gap-2 text-[12.5px]">
                      <input
                        type="color"
                        value={c}
                        aria-label={`Colour ${i + 1}`}
                        className="h-9 w-12 cursor-pointer rounded-[8px] border border-white/10 bg-transparent"
                        onChange={(e) => {
                          const next = e.target.value.toUpperCase()
                          setForm((f) => (f ? { ...f, brand_colors: f.brand_colors.map((x, j) => (j === i ? next : x)) } : f))
                        }}
                      />
                      <span className="num">{c}</span>
                    </label>
                  ))}
                </div>
              )}
            </Field>
            <Field label="Hashtags always used" optional>{(props) => <input {...props} className="field" value={form.brand_hashtags} onChange={(e) => set({ brand_hashtags: e.target.value })} placeholder="#LabdhiExim #Ahmedabad" />}</Field>
            <Field label="Sign-off" optional>{(props) => <input {...props} className="field" value={form.brand_signature} onChange={(e) => set({ brand_signature: e.target.value })} placeholder="Team Labdhi · since 1998" />}</Field>
            <Field label="Never say" optional className="sm:col-span-2" hint="Words, claims or competitors to keep out.">
              {(props) => <input {...props} className="field" value={form.brand_avoid} onChange={(e) => set({ brand_avoid: e.target.value })} placeholder="cheapest, guaranteed, competitor names" />}
            </Field>
          </div>
        </Panel>

        <Panel title="Sending rules" icon={ShieldCheck}>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Who approves" className="sm:col-span-2" hint="Automatic lets automations marked “runs on its own” go out without waiting, for small audiences only.">
              {() => (
                <Segmented
                  value={form.approval}
                  onChange={(approval) => set({ approval })}
                  options={[
                    { value: 'approval', label: 'A person approves every campaign' },
                    { value: 'auto', label: 'Allow automatic for small audiences' },
                  ]}
                />
              )}
            </Field>
            {form.approval === 'auto' ? (
              <Field label="Automatic only up to (customers)">{(props) => <input {...props} className="field field-num" value={form.auto_max_audience} onChange={(e) => set({ auto_max_audience: e.target.value })} />}</Field>
            ) : null}
            <Field label="At most (offers per customer)">{(props) => <input {...props} className="field field-num" value={form.frequency_max} onChange={(e) => set({ frequency_max: e.target.value })} />}</Field>
            <Field label="Per (days)">{(props) => <input {...props} className="field field-num" value={form.frequency_days} onChange={(e) => set({ frequency_days: e.target.value })} />}</Field>
            <Field label="Quiet from">{(props) => <input {...props} type="time" className="field" value={form.quiet_start} onChange={(e) => set({ quiet_start: e.target.value })} />}</Field>
            <Field label="Until">{(props) => <input {...props} type="time" className="field" value={form.quiet_end} onChange={(e) => set({ quiet_end: e.target.value })} />}</Field>
            <Field label="Opt-out words" className="sm:col-span-2" hint="A reply that is exactly one of these opts the customer out.">
              {(props) => <input {...props} className="field" value={form.opt_out_words} onChange={(e) => set({ opt_out_words: e.target.value })} />}
            </Field>
            <Field label="Messages per minute">{(props) => <input {...props} className="field field-num" value={form.send_per_minute} onChange={(e) => set({ send_per_minute: e.target.value })} />}</Field>
            <Field label="Cost per message (₹)" hint="For return on spend.">{(props) => <input {...props} className="field field-num" value={form.message_cost} onChange={(e) => set({ message_cost: e.target.value })} />}</Field>
            <Field label="Count orders within (days)" hint="After a message, for results.">{(props) => <input {...props} className="field field-num" value={form.attribution_days} onChange={(e) => set({ attribution_days: e.target.value })} />}</Field>
            <Field label="Time zone">{(props) => <input {...props} className="field" value={form.timezone} onChange={(e) => set({ timezone: e.target.value })} />}</Field>
          </div>
        </Panel>

        <Panel title="Festivals and seasons" icon={CalendarHeart}>
          <p className="mb-3 text-[12.5px] text-fg-3">The Strategist plans for these. Festival dates move each year; check them.</p>
          <div className="space-y-2">
            {form.occasions.map((o, i) => (
              <div key={i} className="flex flex-wrap items-center gap-2">
                <input className="field field-sm min-w-[160px] flex-1" value={o.name} aria-label="Occasion" onChange={(e) => set({ occasions: form.occasions.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)) })} />
                <input type="date" className="field field-sm w-40" value={o.date} aria-label="Date" onChange={(e) => set({ occasions: form.occasions.map((x, j) => (j === i ? { ...x, date: e.target.value } : x)) })} />
                <label className="flex items-center gap-1.5 text-[12px] text-fg-3">
                  plan
                  <input className="field field-sm field-num w-14" value={o.lead_days} aria-label="Days ahead" onChange={(e) => set({ occasions: form.occasions.map((x, j) => (j === i ? { ...x, lead_days: Number(e.target.value) || 1 } : x)) })} />
                  days ahead
                </label>
                <Button small kind="ghost" iconOnly aria-label="Remove" onClick={() => set({ occasions: form.occasions.filter((_, j) => j !== i) })}>
                  <Trash2 size={13} />
                </Button>
              </div>
            ))}
            <Button small icon={<Plus size={13} />} onClick={() => set({ occasions: [...form.occasions, { name: '', date: '', lead_days: 7 }] })}>
              Add occasion
            </Button>
          </div>
        </Panel>

        <Panel title="Technical" icon={ShieldCheck}>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Public address of this app" className="sm:col-span-2" hint="Instagram and WhatsApp fetch images from here (https). Example: https://erp.labdhi.in">
              {(props) => <input {...props} className="field" value={form.public_url} onChange={(e) => set({ public_url: e.target.value })} placeholder="https://" />}
            </Field>
            <Field label="Image model" hint="Gemini model that draws pictures.">{(props) => <input {...props} className="field" value={form.image_model} onChange={(e) => set({ image_model: e.target.value })} />}</Field>
            <Field label="Strategist looks every (hours)">{(props) => <input {...props} className="field field-num" value={form.scan_hours} onChange={(e) => set({ scan_hours: e.target.value })} />}</Field>
            <Field label="Weekly review on">
              {(props) => (
                <select {...props} className="field" value={form.analyst_weekday} onChange={(e) => set({ analyst_weekday: e.target.value })}>
                  {WEEKDAYS.map((d, i) => (
                    <option key={d} value={i}>
                      {d}
                    </option>
                  ))}
                </select>
              )}
            </Field>
          </div>
          {!form.public_url ? <Notice tone="warn">Without the public address, Instagram posts and WhatsApp image headers cannot go out.</Notice> : null}
        </Panel>
      </div>
      <div className="sticky bottom-0 flex justify-end py-2">
        <Button kind="primary" busy={save.isPending} onClick={submit}>
          Save settings
        </Button>
      </div>
    </Page>
  )
}
