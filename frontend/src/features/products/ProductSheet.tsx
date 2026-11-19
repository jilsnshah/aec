import { useQuery } from '@tanstack/react-query'
import { Picker } from '@/ui/pickers'
import { useSuppliers } from '@/ui/lines'
import { useEffect, useState } from 'react'
import { errorText } from '@/api/client'
import { api } from '@/api/endpoints'
import { useAction } from '@/api/queries'
import type { ProductOut } from '@/api/types'
import { isQty, n } from '@/lib/format'
import { Button, Field, Notice } from '@/ui/core'
import { Sheet } from '@/ui/overlays'

const blank = { sku: '', name: '', unit: 'pcs', mrp: '', description: '', opening: '', cost: '', category: '', minimum: '', supplier: '', lead: '', brand: '', hsn: '', gst: '', weight: '' }
type Spec = { name: string; value: string }
const SPEC_IDEAS = ['Grade', 'Size', 'Thickness', 'Colour', 'Finish', 'Strength', 'Standard (IS)', 'Pack size', 'Shelf life', 'Use']

export function ProductSheet({ open, onClose, editing, onSaved }: { open: boolean; onClose: () => void; editing?: ProductOut; onSaved?: (id: string) => void }) {
  const [form, setForm] = useState(blank)
  const [tried, setTried] = useState(false)
  const [specs, setSpecs] = useState<Spec[]>([])
  const suppliers = useSuppliers()
  const categories = useQuery({ queryKey: ['products', 'categories'], queryFn: api.products.categories })
  const save = useAction(
    () => {
      const base = {
        sku: form.sku.trim(),
        name: form.name.trim(),
        unit_of_measure: form.unit.trim(),
        mrp: form.mrp,
        description: form.description.trim() || null,
        category: form.category.trim() || null,
        reorder_level: form.minimum.trim() || '0',
        preferred_supplier_id: form.supplier || null,
        lead_time_days: form.lead.trim() === '' ? null : Number(form.lead),
        brand: form.brand.trim() || null,
        hsn_code: form.hsn.trim() || null,
        gst_rate: form.gst.trim() === '' ? null : form.gst.trim(),
        weight_kg: form.weight.trim() === '' ? null : form.weight.trim(),
        specs: specs.filter((x) => x.name.trim() && x.value.trim()),
      }
      return editing ? api.products.update(editing.id, base) : api.products.create({ ...base, opening_stock: form.opening || '0', opening_unit_cost: form.cost || '0' })
    },
    { success: editing ? 'Product saved' : 'Product added', quiet: true },
  )
  useEffect(() => {
    if (!open) return
    setForm(editing ? { sku: editing.sku, name: editing.name, unit: editing.unit_of_measure, mrp: String(n(editing.mrp)), description: editing.description ?? '', opening: '', cost: '', category: editing.category ?? '', minimum: n(editing.reorder_level) ? String(n(editing.reorder_level)) : '', supplier: editing.preferred_supplier_id ?? '', lead: editing.lead_time_days == null ? '' : String(editing.lead_time_days), brand: editing.brand ?? '', hsn: editing.hsn_code ?? '', gst: editing.gst_rate == null ? '' : String(n(editing.gst_rate)), weight: editing.weight_kg == null ? '' : String(n(editing.weight_kg)) } : blank)
    setSpecs(editing ? ((editing.specs ?? []) as Spec[]).map((x) => ({ name: String(x.name), value: String(x.value) })) : [])
    setTried(false)
    save.reset()
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  const set = (key: keyof typeof blank) => (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const value = event.target.value
    setForm((current) => ({ ...current, [key]: value }))
  }
  const errors = {
    sku: form.sku.trim() ? null : 'A code is needed.',
    name: form.name.trim() ? null : 'A name is needed.',
    unit: form.unit.trim() ? null : 'A unit is needed.',
    mrp: form.mrp.trim() !== '' && !Number.isNaN(Number(form.mrp)) && n(form.mrp) >= 0 ? null : 'Enter the MRP.',
    opening: form.opening === '' || isQty(form.opening) ? null : 'Enter a quantity.',
    cost: form.cost === '' || (!Number.isNaN(Number(form.cost)) && n(form.cost) >= 0) ? null : 'Enter a cost.',
  }
  const valid = Object.values(errors).every((error) => !error)

  return (
    <Sheet
      open={open}
      onClose={onClose}
      width={640}
      title={editing ? `Edit ${editing.name}` : 'New product'}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            kind="primary"
            busy={save.isPending}
            onClick={() => {
              setTried(true)
              if (valid)
                save.mutate(undefined, {
                  onSuccess: (product) => {
                    onClose()
                    onSaved?.(product.id)
                  },
                })
            }}
          >
            {editing ? 'Save' : 'Add product'}
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-6 gap-4">
        {save.error ? (
          <div className="col-span-6">
            <Notice tone="bad">{errorText(save.error)}</Notice>
          </div>
        ) : null}
        <Field label="Name" className="col-span-4" error={tried ? errors.name : null}>
          {(props) => <input {...props} className="field" autoFocus value={form.name} onChange={set('name')} />}
        </Field>
        <Field label="Code (SKU)" className="col-span-2" error={tried ? errors.sku : null}>
          {(props) => <input {...props} className="field" value={form.sku} onChange={set('sku')} />}
        </Field>
        <Field label="Unit" className="col-span-2" error={tried ? errors.unit : null} hint="pcs, bags, kg…">
          {(props) => <input {...props} className="field" value={form.unit} onChange={set('unit')} />}
        </Field>
        <Field label="MRP" className="col-span-2" error={tried ? errors.mrp : null}>
          {(props) => <input {...props} className="field field-num" inputMode="decimal" placeholder="0.00" value={form.mrp} onChange={set('mrp')} />}
        </Field>
        <div className="col-span-2" />
        {!editing ? (
          <>
            <Field label="Opening stock" optional className="col-span-3" error={tried ? errors.opening : null}>
              {(props) => <input {...props} className="field field-num" inputMode="decimal" placeholder="0" value={form.opening} onChange={set('opening')} />}
            </Field>
            <Field label="Opening cost per unit" optional className="col-span-3" error={tried ? errors.cost : null}>
              {(props) => <input {...props} className="field field-num" inputMode="decimal" placeholder="0.00" value={form.cost} onChange={set('cost')} />}
            </Field>
          </>
        ) : null}
        <Field label="Category" optional className="col-span-2" hint="Groups products in reports.">
          {(props) => (
            <>
              <input {...props} className="field" list="product-categories" value={form.category} onChange={set('category')} placeholder="Cement, Steel…" />
              <datalist id="product-categories">
                {(categories.data ?? []).filter((c) => c.name !== '(none)').map((c) => (
                  <option key={c.name} value={c.name} />
                ))}
              </datalist>
            </>
          )}
        </Field>
        <Field label="Minimum stock" optional className="col-span-2" hint="Reorder before falling below this." error={tried && form.minimum.trim() !== '' && !(Number(form.minimum) >= 0) ? 'Enter a quantity.' : null}>
          {(props) => <input {...props} className="field field-num" inputMode="decimal" value={form.minimum} onChange={set('minimum')} placeholder="0" />}
        </Field>
        <Field label="Lead time (days)" optional className="col-span-2" hint="Order to arrival; else the supplier's.">
          {(props) => <input {...props} className="field field-num" inputMode="numeric" value={form.lead} onChange={set('lead')} placeholder="From supplier" />}
        </Field>
        <Field label="Preferred supplier" optional className="col-span-6" hint="Pre-filled when you buy this product from Insights or the product page.">
          {() => <Picker value={form.supplier} onChange={(value) => setForm({ ...form, supplier: value })} placeholder="None" options={suppliers.map((supplier) => ({ value: supplier.id, label: supplier.name, detail: supplier.code }))} />}
        </Field>
        <Field label="Brand" optional className="col-span-2">
          {(props) => <input {...props} className="field" value={form.brand} onChange={set('brand')} placeholder="UltraTech, Tata…" />}
        </Field>
        <Field label="HSN code" optional className="col-span-2" hint="For GST invoices and Tally.">
          {(props) => <input {...props} className="field" value={form.hsn} onChange={set('hsn')} placeholder="2523" />}
        </Field>
        <Field label="GST %" optional className="col-span-1" hint="Empty: Settings." error={tried && form.gst.trim() !== '' && !(Number(form.gst) >= 0 && Number(form.gst) <= 100) ? '0–100' : null}>
          {(props) => <input {...props} className="field field-num" inputMode="decimal" value={form.gst} onChange={set('gst')} placeholder="18" />}
        </Field>
        <Field label={`Weight (kg per ${form.unit || 'unit'})`} optional className="col-span-1" hint="Freight by weight.">
          {(props) => <input {...props} className="field field-num" inputMode="decimal" value={form.weight} onChange={set('weight')} placeholder="50" />}
        </Field>
        <Field label="Description" optional className="col-span-6" hint="What it is and what it is for. The AI uses this to describe it to customers.">
          {(props) => <textarea {...props} className="field" rows={3} value={form.description} onChange={set('description')} />}
        </Field>
        <div className="col-span-6">
          <div className="label">Details</div>
          <p className="mb-2 text-[11.5px] text-fg-3">Anything else about it: grade, size, thickness, colour, standard… The AI can tell customers these.</p>
          <div className="space-y-1.5">
            {specs.map((spec, i) => (
              <div key={i} className="flex items-center gap-2">
                <input className="field field-sm w-[180px]" aria-label="Detail name" placeholder="Grade" value={spec.name} onChange={(e) => setSpecs(specs.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />
                <input className="field field-sm min-w-0 flex-1" aria-label="Detail value" placeholder="OPC 53" value={spec.value} onChange={(e) => setSpecs(specs.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))} />
                <button type="button" className="grid size-7 place-items-center rounded-full text-fg-3 hover:bg-white/8" aria-label="Remove detail" onClick={() => setSpecs(specs.filter((_, j) => j !== i))}>
                  ×
                </button>
              </div>
            ))}
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {SPEC_IDEAS.filter((idea) => !specs.some((x) => x.name === idea)).map((idea) => (
              <button key={idea} type="button" onClick={() => setSpecs([...specs, { name: idea, value: '' }])} className="h-[26px] rounded-full bg-ink-700 px-2.5 text-[11.5px] text-fg-2 hover:text-fg">
                + {idea}
              </button>
            ))}
            <button type="button" onClick={() => setSpecs([...specs, { name: '', value: '' }])} className="h-[26px] rounded-full bg-ink-700 px-2.5 text-[11.5px] font-semibold">
              + Other
            </button>
          </div>
        </div>
      </div>
    </Sheet>
  )
}
