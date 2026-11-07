import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import type { Product, ProductInventory } from '../api/types'
import {
  ActionMenu,
  ArchivedBadge,
  Avatar,
  Badge,
  Button,
  Card,
  CardFacts,
  Collection,
  ConfirmDialog,
  Dialog,
  DialogCancel,
  EmptyState,
  ExportButton,
  Field,
  FormGrid,
  KeyValue,
  LinkButton,
  Loading,
  Notice,
  Page,
  RecordCard,
  SearchField,
  Segmented,
  Sheet,
  SignedQuantity,
  SortHeader,
  StockFigures,
  TableScroll,
  Toolbar,
  ViewSwitch,
  useToast,
  type Sort,
} from '../components/ui'
import {
  ArchiveIcon,
  EditIcon,
  PlusIcon,
  ProductsIcon,
  RestoreIcon,
  StockInIcon,
  ViewIcon,
} from '../components/icons'
import { downloadCsv, fileStamp } from '../lib/csv'
import { isValidQuantity } from '../lib/decimal'
import {
  MOVEMENT_LABELS,
  formatAmount,
  formatDateTime,
  formatMoney,
  formatQuantity,
  formatUnitPrice,
} from '../lib/format'
import { usePaging, useViewMode } from '../lib/paging'
import { useAsync, useDebounced } from '../lib/useAsync'
import { useCreateParam } from '../lib/useCreateParam'

type Scope = 'active' | 'all'

/** Stock as the business counts it: in less promised, negative when short. */
function StockCell({ product }: { product: Product }) {
  const stock = Number(product.stock)
  return (
    <>
      <SignedQuantity value={product.stock} />
      <span className="cell-sub">
        {stock < 0
          ? `short by ${formatQuantity(String(-stock))}`
          : stock === 0
            ? 'none left'
            : `${product.unit_of_measure} free`}
      </span>
    </>
  )
}

function StockBadge({ product }: { product: Product }) {
  if (!product.is_active) return <ArchivedBadge />
  const stock = Number(product.stock)
  if (stock < 0) return <Badge tone="red" dot>Short</Badge>
  if (stock === 0) return <Badge tone="orange" dot>Out of stock</Badge>
  return null
}

export default function ProductsPage() {
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const [search, setSearch] = useState('')
  const [scope, setScope] = useState<Scope>('active')
  // ?sort=stock (from the Overview) puts the most short products first.
  const [sort, setSort] = useState<Sort>(() =>
    params.get('sort') === 'stock' ? { by: 'stock', dir: 'asc' } : { by: 'name', dir: 'asc' },
  )
  const debouncedSearch = useDebounced(search)
  const [mode, setMode] = useViewMode('products')

  const filters = { search: debouncedSearch || undefined, include_inactive: scope === 'all' }
  const paging = usePaging('products', [filters, sort])
  const state = useAsync(
    () =>
      api.products.list({
        ...filters,
        sort_by: sort.by,
        sort_dir: sort.dir,
        limit: paging.limit,
        offset: paging.offset,
      }),
    [debouncedSearch, scope, sort.by, sort.dir, paging.limit, paging.offset],
  )
  const { data, reload } = state
  // Shortfalls are counted across every product, not just this page.
  const summary = useAsync(() => api.inventory.summary(), [data])

  const [creating, setCreating] = useCreateParam()
  const [editing, setEditing] = useState<Product | null>(null)
  const [archiving, setArchiving] = useState<Product | null>(null)

  // The inspector is addressable as ?open=<id>, so the command menu can open
  // it; a product on another page is fetched on its own.
  const openId = params.get('open')
  const onPage = useMemo(
    () => (openId ? data?.items.find((product) => product.id === openId) ?? null : null),
    [openId, data],
  )
  const fetched = useAsync<Product | null>(
    () => (openId && !onPage ? api.products.get(openId) : Promise.resolve(null)),
    [openId, Boolean(onPage)],
  )
  const viewing = onPage ?? (fetched.data?.id === openId ? fetched.data : null)

  function view(product: Product | null) {
    setParams(
      (current) => {
        const next = new URLSearchParams(current)
        if (product) next.set('open', product.id)
        else next.delete('open')
        return next
      },
      { replace: true },
    )
  }

  async function restore(product: Product) {
    try {
      await api.products.update(product.id, { is_active: true })
      toast.success(`${product.sku} restored`, 'It can be ordered and received again.')
      reload()
    } catch (cause) {
      toast.error('Could not restore', cause instanceof ApiError ? cause.message : String(cause))
    }
  }

  async function exportCsv() {
    const rows = await api.products.all({ ...filters, sort_by: sort.by, sort_dir: sort.dir })
    downloadCsv(
      `products-${fileStamp()}.csv`,
      [
        { header: 'Code', value: (row) => row.sku },
        { header: 'Name', value: (row) => row.name },
        { header: 'Unit', value: (row) => row.unit_of_measure },
        { header: 'MRP', value: (row) => row.mrp },
        { header: 'Stock', value: (row) => row.stock },
        { header: 'To receive', value: (row) => row.on_order_quantity },
        { header: 'To deliver', value: (row) => row.pending_quantity },
        { header: 'Average cost', value: (row) => row.average_cost },
        { header: 'Stock value', value: (row) => row.stock_value },
        { header: 'Archived', value: (row) => (row.is_active ? 'No' : 'Yes') },
      ],
      rows,
    )
    toast.success('Export ready', `${rows.length} product${rows.length === 1 ? '' : 's'} downloaded as CSV.`)
  }

  function menu(product: Product) {
    return (
      <ActionMenu
        label={`Actions for ${product.sku}`}
        items={[
          { label: 'View details', icon: <ViewIcon size={15} />, onSelect: () => view(product) },
          { label: 'Edit', icon: <EditIcon size={15} />, onSelect: () => setEditing(product) },
          product.is_active
            ? {
                label: 'Archive',
                icon: <ArchiveIcon size={15} />,
                destructive: true,
                separatorBefore: true,
                onSelect: () => setArchiving(product),
              }
            : {
                label: 'Restore',
                icon: <RestoreIcon size={15} />,
                separatorBefore: true,
                onSelect: () => restore(product),
              },
        ]}
      />
    )
  }

  const short = summary.data?.products_short.length ?? 0

  return (
    <Page>
      <Toolbar
        title="Products"
        count={data?.total}
        subtitle={
          short > 0
            ? `${short} product${short === 1 ? ' has' : 's have'} sold more than was bought`
            : 'Stock is bought less sold — it changes when orders are placed, not when goods move'
        }
        actions={
          <>
            <ExportButton onExport={exportCsv} disabled={!data?.total} />
            <Button variant="primary" icon={<PlusIcon size={15} />} onClick={() => setCreating(true)}>
              New product
            </Button>
          </>
        }
      >
        <SearchField
          value={search}
          onChange={setSearch}
          placeholder="Search products"
          label="Search products by code or name"
        />
        <Segmented
          label="Which products"
          value={scope}
          onChange={setScope}
          options={[
            { value: 'active', label: 'Active' },
            { value: 'all', label: 'Including archived' },
          ]}
        />
        <div className="grow" />
        <ViewSwitch value={mode} onChange={setMode} />
      </Toolbar>

      <Collection
        state={state}
        view={mode}
        paging={paging}
        noun="products"
        columns={7}
        empty={
          <EmptyState
            icon={<ProductsIcon size={22} />}
            title={search ? 'No matching products' : 'No products yet'}
            body={
              search
                ? `Nothing matches “${search}”. Try a different code or name.`
                : 'Add your first product to start taking orders against it.'
            }
            action={
              search ? (
                <Button onClick={() => setSearch('')}>Clear search</Button>
              ) : (
                <Button variant="primary" onClick={() => setCreating(true)}>
                  New product
                </Button>
              )
            }
          />
        }
        table={(rows) => (
          <table className="table table--interactive">
            <thead>
              <tr>
                <SortHeader field="name" label="Product" sort={sort} onSort={setSort} />
                <SortHeader field="mrp" label="MRP" sort={sort} onSort={setSort} numeric />
                <SortHeader field="stock" label="Stock" sort={sort} onSort={setSort} numeric />
                <th className="num">To receive</th>
                <th className="num">To deliver</th>
                <th className="num">Avg cost</th>
                <th className="col-actions">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((product) => (
                <tr
                  key={product.id}
                  className={product.is_active ? undefined : 'is-muted'}
                  onClick={(event) => {
                    if ((event.target as HTMLElement).closest('button, a')) return
                    view(product)
                  }}
                  tabIndex={0}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && event.target === event.currentTarget) view(product)
                  }}
                >
                  <td>
                    <div className="cell-identity">
                      <Avatar name={product.name} seed={product.sku} square />
                      <div>
                        <div className="row">
                          <span className="cell-primary">{product.name}</span>
                          <StockBadge product={product} />
                        </div>
                        <span className="cell-sub">
                          <span className="mono">{product.sku}</span> · {product.unit_of_measure}
                        </span>
                      </div>
                    </div>
                  </td>
                  <td className="num">{formatAmount(product.mrp)}</td>
                  <td className="num q-strong">
                    <StockCell product={product} />
                  </td>
                  <td className="num">
                    {Number(product.on_order_quantity) > 0 ? (
                      formatQuantity(product.on_order_quantity)
                    ) : (
                      <span className="q-muted">—</span>
                    )}
                  </td>
                  <td className="num">
                    {Number(product.pending_quantity) > 0 ? (
                      formatQuantity(product.pending_quantity)
                    ) : (
                      <span className="q-muted">—</span>
                    )}
                  </td>
                  <td className="num">{formatUnitPrice(product.average_cost)}</td>
                  <td className="col-actions">{menu(product)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        card={(product) => (
          <RecordCard
            key={product.id}
            onOpen={() => view(product)}
            openLabel={`View ${product.name}`}
            tone={!product.is_active ? 'muted' : Number(product.stock) < 0 ? 'alert' : undefined}
            leading={<Avatar name={product.name} seed={product.sku} square size="lg" />}
            title={product.name}
            subtitle={
              <>
                <span className="mono">{product.sku}</span> · {product.unit_of_measure} · MRP{' '}
                {formatMoney(product.mrp)}
              </>
            }
            badge={<StockBadge product={product} />}
            actions={menu(product)}
            footer={
              <>
                <span>Avg cost {formatUnitPrice(product.average_cost)}</span>
                <span className="grow" />
                {product.last_purchase_price ? (
                  <span>Last paid {formatUnitPrice(product.last_purchase_price)}</span>
                ) : null}
              </>
            }
          >
            <CardFacts
              items={[
                {
                  label: 'Stock',
                  value: <SignedQuantity value={product.stock} unit={product.unit_of_measure} />,
                  tone: Number(product.stock) < 0 ? 'is-alert' : undefined,
                },
                {
                  label: 'To receive',
                  value: Number(product.on_order_quantity) > 0 ? formatQuantity(product.on_order_quantity) : '—',
                  tone: Number(product.on_order_quantity) > 0 ? undefined : 'is-muted',
                },
                {
                  label: 'To deliver',
                  value: Number(product.pending_quantity) > 0 ? formatQuantity(product.pending_quantity) : '—',
                  tone: Number(product.pending_quantity) > 0 ? undefined : 'is-muted',
                },
              ]}
            />
          </RecordCard>
        )}
      />

      {creating ? (
        <ProductForm
          onClose={() => setCreating(false)}
          onSaved={(product) => {
            setCreating(false)
            toast.success(`${product.sku} created`, product.name)
            reload()
          }}
        />
      ) : null}

      {editing ? (
        <ProductForm
          product={editing}
          onClose={() => setEditing(null)}
          onSaved={(product) => {
            setEditing(null)
            toast.success(`${product.sku} updated`)
            reload()
          }}
        />
      ) : null}

      {archiving ? (
        <ArchiveProduct
          product={archiving}
          onClose={() => setArchiving(null)}
          onDone={(product) => {
            setArchiving(null)
            toast.success(`${product.sku} archived`, 'Its history is unchanged.', {
              label: 'Undo',
              onClick: () => restore(product),
            })
            reload()
          }}
        />
      ) : null}

      {viewing ? (
        <ProductInspector
          product={viewing}
          onClose={() => view(null)}
          onEdit={() => setEditing(viewing)}
        />
      ) : null}
    </Page>
  )
}

/* -------------------------------------------------------------------------- */

interface FormState {
  sku: string
  name: string
  unit_of_measure: string
  mrp: string
  description: string
  opening_stock: string
  opening_unit_cost: string
}

const EMPTY_FORM: FormState = {
  sku: '',
  name: '',
  unit_of_measure: 'pcs',
  mrp: '',
  description: '',
  opening_stock: '0',
  opening_unit_cost: '0',
}

function validate(form: FormState, isEdit: boolean) {
  const errors: Partial<Record<keyof FormState, string>> = {}
  if (!form.sku.trim()) errors.sku = 'Enter a product code.'
  if (!form.name.trim()) errors.name = 'Enter a product name.'
  if (!form.unit_of_measure.trim()) errors.unit_of_measure = 'Enter a unit, such as pcs or kg.'
  if (!isValidQuantity(form.mrp)) errors.mrp = 'Enter an MRP of zero or more.'
  if (!isEdit && !isValidQuantity(form.opening_stock)) {
    errors.opening_stock = 'Enter zero or more.'
  }
  if (!isEdit && !isValidQuantity(form.opening_unit_cost)) {
    errors.opening_unit_cost = 'Enter zero or more.'
  }
  return errors
}

function ProductForm({
  product,
  onClose,
  onSaved,
}: {
  product?: Product
  onClose: () => void
  onSaved: (product: Product) => void
}) {
  const isEdit = Boolean(product)
  const [form, setForm] = useState<FormState>(
    product
      ? {
          sku: product.sku,
          name: product.name,
          unit_of_measure: product.unit_of_measure,
          mrp: product.mrp,
          description: product.description ?? '',
          opening_stock: '0',
          opening_unit_cost: '0',
        }
      : EMPTY_FORM,
  )
  const [touched, setTouched] = useState(false)
  const [saving, setSaving] = useState(false)
  const [serverError, setServerError] = useState<string | null>(null)

  const errors = useMemo(() => validate(form, isEdit), [form, isEdit])
  const show = (key: keyof FormState) => (touched ? errors[key] : undefined)
  const hasOpening = isValidQuantity(form.opening_stock) && Number(form.opening_stock) > 0

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((current) => ({ ...current, [key]: value }))
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setTouched(true)
    if (Object.keys(errors).length > 0 || saving) return
    setSaving(true)
    setServerError(null)
    try {
      const payload = {
        sku: form.sku.trim(),
        name: form.name.trim(),
        unit_of_measure: form.unit_of_measure.trim(),
        mrp: form.mrp,
        description: form.description.trim() || null,
      }
      const saved = product
        ? await api.products.update(product.id, payload)
        : await api.products.create({
            ...payload,
            opening_stock: form.opening_stock,
            opening_unit_cost: hasOpening ? form.opening_unit_cost : '0',
          })
      onSaved(saved)
    } catch (cause) {
      setServerError(cause instanceof ApiError ? cause.message : String(cause))
      setSaving(false)
    }
  }

  return (
    <Dialog
      title={isEdit ? `Edit ${product?.sku}` : 'New product'}
      subtitle={isEdit ? product?.name : 'Codes must be unique. MRP is the list price customers see.'}
      onClose={onClose}
      busy={saving}
      size="medium"
      footer={
        <>
          <DialogCancel />
          <Button type="submit" form="product-form" variant="primary" busy={saving}>
            {isEdit ? 'Save changes' : 'Create product'}
          </Button>
        </>
      }
    >
      <form id="product-form" onSubmit={submit} noValidate className="stack stack--tight">
        {serverError ? <Notice kind="error">{serverError}</Notice> : null}
        <FormGrid>
          <Field label="Product code" error={show('sku')}>
            {(props) => (
              <input
                {...props}
                value={form.sku}
                onChange={(event) => update('sku', event.target.value)}
                autoComplete="off"
                placeholder="WID-10"
                data-autofocus=""
              />
            )}
          </Field>
          <Field label="Unit" error={show('unit_of_measure')} hint="pcs, boxes, kg…">
            {(props) => (
              <input
                {...props}
                value={form.unit_of_measure}
                onChange={(event) => update('unit_of_measure', event.target.value)}
              />
            )}
          </Field>
          <Field label="Name" error={show('name')} span2>
            {(props) => (
              <input
                {...props}
                value={form.name}
                onChange={(event) => update('name', event.target.value)}
                placeholder="Widget, 10mm"
              />
            )}
          </Field>
          <Field label="MRP per unit" error={show('mrp')}>
            {(props) => (
              <input
                {...props}
                className="input input--num"
                type="number"
                step="0.01"
                min="0"
                inputMode="decimal"
                value={form.mrp}
                onChange={(event) => update('mrp', event.target.value)}
                placeholder="0.00"
              />
            )}
          </Field>
          {isEdit ? (
            <Field label="Stock" hint="Up when a purchase is placed, down when a sale is placed.">
              {(props) => (
                <input
                  {...props}
                  className="input input--num"
                  value={formatQuantity(product?.stock)}
                  readOnly
                  tabIndex={-1}
                />
              )}
            </Field>
          ) : (
            <Field label="Opening stock" error={show('opening_stock')} optional>
              {(props) => (
                <input
                  {...props}
                  className="input input--num"
                  type="number"
                  step="0.001"
                  min="0"
                  inputMode="decimal"
                  value={form.opening_stock}
                  onChange={(event) => update('opening_stock', event.target.value)}
                />
              )}
            </Field>
          )}
          {!isEdit && hasOpening ? (
            <Field
              label="Opening stock cost per unit"
              error={show('opening_unit_cost')}
              hint="What it cost to buy, so profit on it is real."
              span2
            >
              {(props) => (
                <input
                  {...props}
                  className="input input--num"
                  type="number"
                  step="0.0001"
                  min="0"
                  inputMode="decimal"
                  value={form.opening_unit_cost}
                  onChange={(event) => update('opening_unit_cost', event.target.value)}
                />
              )}
            </Field>
          ) : null}
          <Field label="Description" optional span2>
            {(props) => (
              <textarea
                {...props}
                value={form.description}
                onChange={(event) => update('description', event.target.value)}
              />
            )}
          </Field>
        </FormGrid>
      </form>
    </Dialog>
  )
}

function ArchiveProduct({
  product,
  onClose,
  onDone,
}: {
  product: Product
  onClose: () => void
  onDone: (product: Product) => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function confirm() {
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      onDone(await api.products.archive(product.id))
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : String(cause))
      setBusy(false)
    }
  }

  return (
    <ConfirmDialog
      title={`Archive ${product.sku}?`}
      confirmLabel="Archive"
      destructive
      busy={busy}
      error={error}
      onCancel={onClose}
      onConfirm={confirm}
      icon={<ArchiveIcon size={19} />}
      message={
        <>
          <p>
            {product.name} will no longer be offered on new orders. Its orders, stock movements and
            costs are kept exactly as they are.
          </p>
          {Number(product.pending_quantity) > 0 ? (
            <p>
              <strong className="q-owed">
                {formatQuantity(product.pending_quantity)} {product.unit_of_measure}
              </strong>{' '}
              is still to be delivered to customers; those orders stay open.
            </p>
          ) : null}
        </>
      }
    />
  )
}

function ProductInspector({
  product,
  onClose,
  onEdit,
}: {
  product: Product
  onClose: () => void
  onEdit: () => void
}) {
  const { data, loading, error } = useAsync<ProductInventory>(
    () => api.products.inventory(product.id),
    [product.id],
  )
  const [tab, setTab] = useState<'batches' | 'movements'>('batches')

  useEffect(() => setTab('batches'), [product.id])

  return (
    <Sheet
      title={product.name}
      subtitle={
        <>
          <span className="mono">{product.sku}</span> · {product.unit_of_measure} · MRP{' '}
          {formatMoney(product.mrp)}
        </>
      }
      onClose={onClose}
      actions={
        <Button size="sm" icon={<EditIcon size={14} />} onClick={onEdit}>
          Edit
        </Button>
      }
    >
      {loading && !data ? <Loading /> : null}
      {error ? <Notice kind="error">{error}</Notice> : null}
      {data ? (
        <div className="stack">
          <StockFigures
            stock={data.stock}
            toReceive={data.on_order_quantity}
            toDeliver={data.pending_quantity}
            unit={data.unit_of_measure}
          />

          <Card>
            <div className="card__body">
              <KeyValue
                items={[
                  { label: 'Value in warehouse', value: formatMoney(data.stock_value) },
                  { label: 'Average cost', value: formatUnitPrice(data.average_cost) },
                  {
                    label: 'Last paid',
                    value: data.last_purchase_price ? formatUnitPrice(data.last_purchase_price) : '—',
                  },
                  { label: 'Status', value: data.is_active ? 'Active' : 'Archived' },
                ]}
              />
              {data.description ? (
                <p className="t-callout muted mt-3">
                  {data.description}
                </p>
              ) : null}
            </div>
          </Card>

          <div className="row row--between">
            <Segmented
              label="History"
              small
              value={tab}
              onChange={setTab}
              options={[
                { value: 'batches', label: 'Purchase batches', count: data.cost_layers.length },
                { value: 'movements', label: 'Movements', count: data.movements.length },
              ]}
            />
            <LinkButton to="/stock-in" size="sm" variant="tinted" icon={<StockInIcon size={14} />}>
              Stock in
            </LinkButton>
          </div>

          {tab === 'batches' ? (
            <Card flush>
              {data.cost_layers.length === 0 ? (
                <EmptyState compact title="No stock on hand to value" />
              ) : (
                <TableScroll>
                  <table className="table table--compact">
                    <thead>
                      <tr>
                        <th>Bought</th>
                        <th className="num">Cost</th>
                        <th className="num">Left</th>
                        <th className="num">Value</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.cost_layers.map((layer) => (
                        <tr key={layer.id}>
                          <td>
                            {formatDateTime(layer.created_at)}
                            <span className="cell-sub">
                              {MOVEMENT_LABELS[layer.source] ?? layer.source}
                            </span>
                          </td>
                          <td className="num">{formatUnitPrice(layer.unit_cost)}</td>
                          <td className="num">
                            {formatQuantity(layer.quantity_remaining)}
                            <span className="cell-sub">of {formatQuantity(layer.quantity)}</span>
                          </td>
                          <td className="num">
                            {formatAmount(
                              Number(layer.quantity_remaining) * Number(layer.unit_cost),
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </TableScroll>
              )}
            </Card>
          ) : (
            <Card flush>
              {data.movements.length === 0 ? (
                <EmptyState compact title="No stock movements yet" />
              ) : (
                <TableScroll>
                  <table className="table table--compact">
                    <thead>
                      <tr>
                        <th>When</th>
                        <th>Movement</th>
                        <th className="num">Change</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.movements.map((movement) => (
                        <tr key={movement.id}>
                          <td className="nowrap">{formatDateTime(movement.created_at)}</td>
                          <td>
                            {MOVEMENT_LABELS[movement.movement_type] ?? movement.movement_type}
                            {movement.note ? (
                              <span className="cell-sub cell-clip">
                                {movement.note}
                              </span>
                            ) : null}
                          </td>
                          <td className="num">
                            <SignedQuantity value={movement.quantity_change} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </TableScroll>
              )}
            </Card>
          )}

          {Number(data.ledger_balance) !== Number(data.physical_stock) ? (
            <Notice kind="error">The movement ledger does not agree with the stock record. Review the movements.</Notice>
          ) : null}
          <p className="hint">
            See <Link to="/pending-fulfilment">what is still to deliver</Link>.
          </p>
        </div>
      ) : null}
    </Sheet>
  )
}
