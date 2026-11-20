import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Download, Images, LayoutTemplate, MessageSquareText, Send, Sparkles, WandSparkles } from 'lucide-react'
import { marketing, type Media } from '@/api/marketing'
import { useAction } from '@/api/queries'
import { fmtAgo } from '@/lib/format'
import { Badge, Button, Empty, Field, Notice, Spinner } from '@/ui/core'
import { Segmented } from '@/ui/overlays'
import { Picker } from '@/ui/pickers'
import { productOption, useProducts } from '@/ui/lines'
import { Page, Panel, PhonePreview } from './shared'

/** Make creatives, pictures and WhatsApp templates. Copy for a campaign is
 *  written inside the campaign (Write with AI), where the plan is known. */
export function Studio() {
  const settings = useQuery({ queryKey: ['marketing', 'settings'], queryFn: marketing.settings })
  const [result, setResult] = useState<Media | null>(null)
  return (
    <Page className="space-y-3">
      {settings.data && !settings.data.ai ? (
        <Notice tone="warn">Gemini is not connected (Settings → AI). Cards work without it; AI pictures and AI writing need it.</Notice>
      ) : null}
      <div className="grid gap-3 xl:grid-cols-[1fr_420px]">
        <div className="space-y-3">
          <CardMaker onMade={setResult} />
          <ImageMaker onMade={setResult} />
          <TemplateWriter />
        </div>
        <aside className="space-y-3">
          <Panel title="Result" icon={Images}>
            {result ? (
              <div className="space-y-2">
                <img src={result.url} alt={result.name ?? ''} className="w-full rounded-[12px]" />
                <div className="flex items-center gap-2 text-[12px] text-fg-3">
                  <Badge>{result.source === 'ai' ? 'AI picture' : result.source === 'card' ? 'Designed card' : 'Upload'}</Badge>
                  {result.width}×{result.height}
                  <a className="ml-auto inline-flex items-center gap-1 font-medium text-sky" href={result.url} download>
                    <Download size={12} /> Download
                  </a>
                </div>
                <p className="text-[12px] text-fg-3">Saved to the library: pick it from any Instagram post or WhatsApp image.</p>
              </div>
            ) : (
              <p className="text-[12.5px] text-fg-3">What you make appears here.</p>
            )}
          </Panel>
          <Library />
        </aside>
      </div>
    </Page>
  )
}

function CardMaker({ onMade }: { onMade: (m: Media) => void }) {
  const products = useProducts()
  const [product, setProduct] = useState('')
  const [form, setForm] = useState({ headline: '', subline: '', price: '', badge: '', points: '', cta: 'Order on WhatsApp', size: 'portrait' })
  const card = useAction(marketing.card, { success: 'Card drawn' })
  const productCard = useAction(marketing.productCard, { success: 'Card drawn' })
  const set = (patch: Partial<typeof form>) => setForm((f) => ({ ...f, ...patch }))
  return (
    <Panel title="Promotional card" icon={LayoutTemplate}>
      <p className="mb-3 text-[12.5px] text-fg-3">A clean card in your brand colours (Settings). Choose a product to fill it from the catalogue, or write your own.</p>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="From a product" optional className="md:col-span-2">
          {(props) => (
            <div className="flex gap-2">
              <div className="flex-1">
                <Picker id={props.id} value={product} onChange={setProduct} options={products.items.map(productOption)} placeholder="Choose a product…" />
              </div>
              <Button kind="primary" icon={<Sparkles size={13} />} disabled={!product} busy={productCard.isPending} onClick={() => productCard.mutate({ product_id: product, offer: form.subline || undefined }, { onSuccess: onMade })}>
                Draw
              </Button>
            </div>
          )}
        </Field>
        <Field label="Headline">{(props) => <input {...props} className="field" value={form.headline} onChange={(e) => set({ headline: e.target.value })} placeholder="Diwali stock-up offer" />}</Field>
        <Field label="Line under it" optional>{(props) => <input {...props} className="field" value={form.subline} onChange={(e) => set({ subline: e.target.value })} placeholder="Free delivery above 100 bags" />}</Field>
        <Field label="Price" optional>{(props) => <input {...props} className="field" value={form.price} onChange={(e) => set({ price: e.target.value })} placeholder="₹385/bag" />}</Field>
        <Field label="Badge" optional>{(props) => <input {...props} className="field" value={form.badge} onChange={(e) => set({ badge: e.target.value })} placeholder="Limited stock" />}</Field>
        <Field label="Points" optional hint="One per line, up to four.">
          {(props) => <textarea {...props} className="field min-h-[78px]" value={form.points} onChange={(e) => set({ points: e.target.value })} placeholder={'OPC 53 grade\nFresh November batch'} />}
        </Field>
        <div className="space-y-3">
          <Field label="Button">{(props) => <input {...props} className="field" value={form.cta} onChange={(e) => set({ cta: e.target.value })} />}</Field>
          <Field label="Shape">
            {() => (
              <Segmented
                value={form.size}
                onChange={(size) => set({ size })}
                options={[
                  { value: 'portrait', label: 'Feed 4:5' },
                  { value: 'square', label: 'Square' },
                  { value: 'landscape', label: 'Wide' },
                ]}
              />
            )}
          </Field>
        </div>
      </div>
      <Button
        className="mt-3"
        kind="primary"
        icon={<LayoutTemplate size={14} />}
        disabled={!form.headline.trim()}
        busy={card.isPending}
        onClick={() =>
          card.mutate(
            {
              headline: form.headline,
              subline: form.subline || undefined,
              price: form.price || undefined,
              badge: form.badge || undefined,
              points: form.points.split('\n').map((p) => p.trim()).filter(Boolean),
              cta: form.cta || undefined,
              size: form.size,
            },
            { onSuccess: onMade },
          )
        }
      >
        Draw card
      </Button>
    </Panel>
  )
}

function ImageMaker({ onMade }: { onMade: (m: Media) => void }) {
  const [prompt, setPrompt] = useState('')
  const image = useAction(marketing.image, { success: 'Picture made' })
  const ideas = ['Cement bags stacked at a site at sunrise', 'Steel TMT bars bundled in a clean yard', 'Diwali diyas beside paint buckets', 'A finished modern home with a happy family']
  return (
    <Panel title="AI picture" icon={WandSparkles}>
      <Field label="Describe the picture" hint="A photo idea without text; your brand colours and tone are added. Check the result before using it.">
        {(props) => <textarea {...props} className="field min-h-[80px]" value={prompt} onChange={(e) => setPrompt(e.target.value)} />}
      </Field>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {ideas.map((idea) => (
          <button key={idea} onClick={() => setPrompt(idea)} className="rounded-full bg-white/6 px-2.5 py-1 text-[12px] font-medium text-fg-2 hover:bg-white/10">
            {idea}
          </button>
        ))}
      </div>
      <Button className="mt-3" kind="primary" icon={<WandSparkles size={14} />} disabled={prompt.trim().length < 8} busy={image.isPending} onClick={() => image.mutate({ prompt }, { onSuccess: onMade })}>
        Make picture
      </Button>
    </Panel>
  )
}

function TemplateWriter() {
  const [purpose, setPurpose] = useState('')
  const [draft, setDraft] = useState<{ name: string; body: string; examples: string[]; footer: string } | null>(null)
  const suggest = useAction(marketing.suggestTemplate, { quiet: false })
  const create = useAction(marketing.createTemplate, { success: 'Sent to Meta for approval. It usually takes minutes to a day; sync templates to see the result.' })
  const blanks = draft ? [...new Set(draft.body.match(/\{\{\d+\}\}/g) ?? [])].length : 0
  const preview = draft ? draft.examples.reduce((b, ex, i) => b.split(`{{${i + 1}}}`).join(ex || `{{${i + 1}}}`), draft.body) : ''
  return (
    <Panel title="WhatsApp marketing template" icon={MessageSquareText}>
      <p className="mb-3 text-[12.5px] text-fg-3">
        Offers on WhatsApp must use a template Meta has approved. Make one general template (a blank for the name and one for the message) and reuse it for every campaign.
      </p>
      <div className="flex gap-2">
        <input className="field" value={purpose} onChange={(e) => setPurpose(e.target.value)} placeholder="What it is for: weekly offers, new stock alerts, festival greetings…" aria-label="Template purpose" />
        <Button icon={<Sparkles size={13} />} busy={suggest.isPending} disabled={purpose.trim().length < 2} onClick={() => suggest.mutate(purpose, { onSuccess: (d) => setDraft({ name: d.name, body: d.body, examples: d.examples, footer: d.footer }) })}>
          Draft it
        </Button>
      </div>
      {draft ? (
        <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_300px]">
          <div className="space-y-3">
            <Field label="Name" hint="Lowercase letters, numbers and underscores.">
              {(props) => <input {...props} className="field" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />}
            </Field>
            <Field label="Message" hint="{{1}}, {{2}}… are blanks filled per customer.">
              {(props) => <textarea {...props} className="field min-h-[110px]" value={draft.body} onChange={(e) => setDraft({ ...draft, body: e.target.value })} />}
            </Field>
            {Array.from({ length: blanks }, (_, i) => (
              <Field key={i} label={`Example for {{${i + 1}}}`} hint="Meta reads these to review the template.">
                {(props) => (
                  <input
                    {...props}
                    className="field"
                    value={draft.examples[i] ?? ''}
                    onChange={(e) => {
                      const examples = [...draft.examples]
                      examples[i] = e.target.value
                      setDraft({ ...draft, examples })
                    }}
                  />
                )}
              </Field>
            ))}
            <Field label="Footer" optional>{(props) => <input {...props} className="field" value={draft.footer} onChange={(e) => setDraft({ ...draft, footer: e.target.value })} />}</Field>
            <Button
              kind="primary"
              icon={<Send size={14} />}
              busy={create.isPending}
              onClick={() => create.mutate({ name: draft.name, body: draft.body, examples: draft.examples.slice(0, blanks), footer: draft.footer || undefined }, { onSuccess: () => setDraft(null) })}
            >
              Send to Meta for approval
            </Button>
          </div>
          <div>
            <PhonePreview text={preview} footer={draft.footer} />
            <p className="mt-2 text-[11.5px] text-fg-3">A “Stop promotions” button is added so customers can opt out in one tap.</p>
          </div>
        </div>
      ) : null}
    </Panel>
  )
}

function Library() {
  const data = useQuery({ queryKey: ['marketing', 'media'], queryFn: () => marketing.media() })
  return (
    <Panel title="Library" icon={Images}>
      {data.isPending ? (
        <Spinner />
      ) : data.data?.items.length ? (
        <div className="grid grid-cols-3 gap-2">
          {data.data.items.map((m) => (
            <a key={m.id} href={m.url} target="_blank" rel="noreferrer" title={`${m.name ?? ''} · ${fmtAgo(m.created_at)}`} className="overflow-hidden rounded-[10px] ring-1 ring-white/8 hover:ring-2 hover:ring-sky">
              <img src={m.url} alt={m.name ?? ''} className="aspect-[4/5] w-full object-cover" loading="lazy" />
            </a>
          ))}
        </div>
      ) : (
        <Empty title="Nothing yet" body="Cards, AI pictures and uploads collect here." />
      )}
    </Panel>
  )
}
