import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import type { Supplier, SupplierDetail, SupplierListRow } from '../api/types'
import {
  ActionMenu,
  ArchivedBadge,
  Avatar,
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
  PurchaseStatusBadge,
  RecordCard,
  SearchField,
  Segmented,
  Sheet,
  SortHeader,
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
  PurchaseOrderIcon,
  RestoreIcon,
  SupplierIcon,
  ViewIcon,
} from '../components/icons'
import { downloadCsv, fileStamp } from '../lib/csv'
import { formatAmount, formatDate, formatDateTime, formatMoney, formatQuantity, formatRelative } from '../lib/format'
import { usePaging, useViewMode } from '../lib/paging'
import { useAsync, useDebounced } from '../lib/useAsync'
import { useCreateParam } from '../lib/useCreateParam'
import { isValidEmail } from '../lib/validation'

export default function SuppliersPage() {
  const toast = useToast()
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [scope, setScope] = useState<'active' | 'all'>('active')
  const [sort, setSort] = useState<Sort>({ by: 'name', dir: 'asc' })
  const debouncedSearch = useDebounced(search)
  const [view, setView] = useViewMode('suppliers')

  const filters = { search: debouncedSearch || undefined, include_inactive: scope === 'all' }
  const paging = usePaging('suppliers', [filters, sort])
  const state = useAsync(
    () =>
      api.suppliers.list({
        ...filters,
        sort_by: sort.by,
        sort_dir: sort.dir,
        limit: paging.limit,
        offset: paging.offset,
      }),
    [debouncedSearch, scope, sort.by, sort.dir, paging.limit, paging.offset],
  )
  const { data, reload } = state

  const [creating, setCreating] = useCreateParam()
  const [editing, setEditing] = useState<Supplier | null>(null)
  const [archiving, setArchiving] = useState<Supplier | null>(null)
  const [viewing, setViewing] = useState<Supplier | null>(null)

  async function restore(supplier: Supplier) {
    try {
      await api.suppliers.update(supplier.id, { is_active: true })
      toast.success(`${supplier.name} restored`)
      reload()
    } catch (cause) {
      toast.error('Could not restore', cause instanceof ApiError ? cause.message : String(cause))
    }
  }

  async function exportCsv() {
    const rows = await api.suppliers.all({ ...filters, sort_by: sort.by, sort_dir: sort.dir })
    downloadCsv(
      `suppliers-${fileStamp()}.csv`,
      [
        { header: 'Code', value: (row) => row.code },
        { header: 'Supplier', value: (row) => row.name },
        { header: 'Contact', value: (row) => row.contact_person },
        { header: 'Phone', value: (row) => row.phone },
        { header: 'Email', value: (row) => row.email },
        { header: 'Purchase orders', value: (row) => row.po_count },
        { header: 'Open orders', value: (row) => row.open_po_count },
        { header: 'Still due (qty)', value: (row) => row.on_order_quantity },
        { header: 'Still due (value)', value: (row) => row.on_order_value },
        { header: 'Last order', value: (row) => row.last_po_at },
        { header: 'Archived', value: (row) => (row.is_active ? 'No' : 'Yes') },
      ],
      rows,
    )
    toast.success('Export ready', `${rows.length} supplier${rows.length === 1 ? '' : 's'} downloaded as CSV.`)
  }

  function menu(supplier: SupplierListRow) {
    return (
      <ActionMenu
        label={`Actions for ${supplier.name}`}
        items={[
          { label: 'Purchase history', icon: <ViewIcon size={15} />, onSelect: () => setViewing(supplier) },
          {
            label: 'New purchase order',
            icon: <PurchaseOrderIcon size={15} />,
            disabled: !supplier.is_active,
            onSelect: () => navigate(`/purchase-orders?new=1&supplier=${supplier.id}`),
          },
          { label: 'Edit', icon: <EditIcon size={15} />, onSelect: () => setEditing(supplier) },
          supplier.is_active
            ? {
                label: 'Archive',
                icon: <ArchiveIcon size={15} />,
                destructive: true,
                separatorBefore: true,
                onSelect: () => setArchiving(supplier),
              }
            : {
                label: 'Restore',
                icon: <RestoreIcon size={15} />,
                separatorBefore: true,
                onSelect: () => restore(supplier),
              },
        ]}
      />
    )
  }

  return (
    <Page>
      <Toolbar
        title="Suppliers"
        count={data?.total}
        subtitle="Archived suppliers keep their purchase orders and receipts"
        actions={
          <>
            <ExportButton onExport={exportCsv} disabled={!data?.total} />
            <Button variant="primary" icon={<PlusIcon size={15} />} onClick={() => setCreating(true)}>
              New supplier
            </Button>
          </>
        }
      >
        <SearchField
          value={search}
          onChange={setSearch}
          placeholder="Search suppliers"
          label="Search suppliers"
        />
        <Segmented
          label="Which suppliers"
          value={scope}
          onChange={setScope}
          options={[
            { value: 'active', label: 'Active' },
            { value: 'all', label: 'Including archived' },
          ]}
        />
        <div className="grow" />
        <ViewSwitch value={view} onChange={setView} />
      </Toolbar>

      <Collection
        state={state}
        view={view}
        paging={paging}
        noun="suppliers"
        columns={6}
        empty={
          <EmptyState
            icon={<SupplierIcon size={22} />}
            title={search ? 'No matching suppliers' : 'No suppliers yet'}
            body={search ? `Nothing matches “${search}”.` : 'Add a supplier before raising a purchase order.'}
            action={
              search ? (
                <Button onClick={() => setSearch('')}>Clear search</Button>
              ) : (
                <Button variant="primary" onClick={() => setCreating(true)}>
                  New supplier
                </Button>
              )
            }
          />
        }
        table={(rows) => (
          <table className="table table--interactive">
            <thead>
              <tr>
                <SortHeader field="name" label="Supplier" sort={sort} onSort={setSort} />
                <th>Contact</th>
                <th className="num">Open orders</th>
                <th className="num">Still due</th>
                <th className="num">Orders placed</th>
                <th className="num">Last order</th>
                <th className="col-actions">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((supplier) => (
                <tr
                  key={supplier.id}
                  className={supplier.is_active ? undefined : 'is-muted'}
                  tabIndex={0}
                  onClick={(event) => {
                    if ((event.target as HTMLElement).closest('button, a')) return
                    setViewing(supplier)
                  }}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && event.target === event.currentTarget) setViewing(supplier)
                  }}
                >
                  <td>
                    <div className="cell-identity">
                      <Avatar name={supplier.name} seed={supplier.id} square />
                      <div>
                        <div className="row">
                          <span className="cell-primary">{supplier.name}</span>
                          {!supplier.is_active ? <ArchivedBadge /> : null}
                        </div>
                        <span className="cell-sub mono">{supplier.code}</span>
                      </div>
                    </div>
                  </td>
                  <td>
                    <span className="cell-primary">
                      {supplier.contact_person || <span className="q-muted">—</span>}
                    </span>
                    {supplier.phone || supplier.email ? (
                      <span className="cell-sub cell-clip">
                        {[supplier.phone, supplier.email].filter(Boolean).join(' · ')}
                      </span>
                    ) : null}
                  </td>
                  <td className="num">
                    {supplier.open_po_count || <span className="q-muted">—</span>}
                  </td>
                  <td className="num">
                    {Number(supplier.on_order_quantity) > 0 ? (
                      <>
                        <span className="q-strong">{formatQuantity(supplier.on_order_quantity)}</span>
                        <span className="cell-sub">{formatMoney(supplier.on_order_value)}</span>
                      </>
                    ) : (
                      <span className="q-muted">—</span>
                    )}
                  </td>
                  <td className="num">{supplier.po_count}</td>
                  <td className="num nowrap">
                    {supplier.last_po_at ? formatRelative(supplier.last_po_at) : <span className="q-muted">Never</span>}
                  </td>
                  <td className="col-actions">{menu(supplier)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        card={(supplier) => (
          <RecordCard
            key={supplier.id}
            onOpen={() => setViewing(supplier)}
            openLabel={`Purchase history for ${supplier.name}`}
            tone={supplier.is_active ? undefined : 'muted'}
            leading={<Avatar name={supplier.name} seed={supplier.id} square size="lg" />}
            title={supplier.name}
            subtitle={
              <>
                <span className="mono">{supplier.code}</span>
                {supplier.contact_person ? ` · ${supplier.contact_person}` : ''}
              </>
            }
            badge={!supplier.is_active ? <ArchivedBadge /> : undefined}
            actions={menu(supplier)}
            footer={
              <>
                <span className="cell-clip">
                  {[supplier.phone, supplier.email].filter(Boolean).join(' · ') || 'No contact details'}
                </span>
                <span className="grow" />
                <span className="nowrap">
                  {supplier.last_po_at ? `Last PO ${formatRelative(supplier.last_po_at)}` : 'No orders yet'}
                </span>
              </>
            }
          >
            <CardFacts
              items={[
                {
                  label: 'Open orders',
                  value: supplier.open_po_count || '—',
                  tone: supplier.open_po_count ? undefined : 'is-muted',
                },
                {
                  label: 'Still due',
                  value: Number(supplier.on_order_quantity) > 0 ? formatQuantity(supplier.on_order_quantity) : '—',
                  tone: Number(supplier.on_order_quantity) > 0 ? undefined : 'is-muted',
                },
                {
                  label: 'Due value',
                  value: Number(supplier.on_order_value) > 0 ? formatMoney(supplier.on_order_value) : '—',
                  tone: Number(supplier.on_order_value) > 0 ? undefined : 'is-muted',
                },
              ]}
            />
          </RecordCard>
        )}
      />

      {creating ? (
        <SupplierForm
          onClose={() => setCreating(false)}
          onSaved={(supplier) => {
            setCreating(false)
            toast.success(`${supplier.name} added`, `Code ${supplier.code}`)
            reload()
          }}
        />
      ) : null}
      {editing ? (
        <SupplierForm
          supplier={editing}
          onClose={() => setEditing(null)}
          onSaved={(supplier) => {
            setEditing(null)
            toast.success(`${supplier.name} updated`)
            reload()
          }}
        />
      ) : null}
      {archiving ? (
        <ArchiveSupplier
          supplier={archiving}
          onClose={() => setArchiving(null)}
          onDone={(supplier) => {
            setArchiving(null)
            toast.success(`${supplier.name} archived`, 'Its purchase history is unchanged.', {
              label: 'Undo',
              onClick: () => restore(supplier),
            })
            reload()
          }}
        />
      ) : null}
      {viewing ? (
        <SupplierInspector
          supplier={viewing}
          onClose={() => setViewing(null)}
          onEdit={() => setEditing(viewing)}
        />
      ) : null}
    </Page>
  )
}

interface FormState {
  code: string
  name: string
  contact_person: string
  phone: string
  email: string
  address: string
  notes: string
}

function SupplierForm({
  supplier,
  onClose,
  onSaved,
}: {
  supplier?: Supplier
  onClose: () => void
  onSaved: (supplier: Supplier) => void
}) {
  const [form, setForm] = useState<FormState>({
    code: supplier?.code ?? '',
    name: supplier?.name ?? '',
    contact_person: supplier?.contact_person ?? '',
    phone: supplier?.phone ?? '',
    email: supplier?.email ?? '',
    address: supplier?.address ?? '',
    notes: supplier?.notes ?? '',
  })
  const [touched, setTouched] = useState(false)
  const [saving, setSaving] = useState(false)
  const [serverError, setServerError] = useState<string | null>(null)

  const errors = useMemo(() => {
    const next: Partial<Record<keyof FormState, string>> = {}
    if (!form.name.trim()) next.name = 'Enter the supplier’s name.'
    if (supplier && !form.code.trim()) next.code = 'A supplier needs a code.'
    if (form.email.trim() && !isValidEmail(form.email)) next.email = 'Enter a valid email, or leave it blank.'
    return next
  }, [form, supplier])
  const show = (key: keyof FormState) => (touched ? errors[key] : undefined)

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
        code: form.code.trim() || null,
        name: form.name.trim(),
        contact_person: form.contact_person.trim() || null,
        phone: form.phone.trim() || null,
        email: form.email.trim() || null,
        address: form.address.trim() || null,
        notes: form.notes.trim() || null,
      }
      onSaved(
        supplier
          ? await api.suppliers.update(supplier.id, payload)
          : await api.suppliers.create(payload),
      )
    } catch (cause) {
      setServerError(cause instanceof ApiError ? cause.message : String(cause))
      setSaving(false)
    }
  }

  return (
    <Dialog
      title={supplier ? `Edit ${supplier.name}` : 'New supplier'}
      onClose={onClose}
      busy={saving}
      size="medium"
      footer={
        <>
          <DialogCancel />
          <Button type="submit" form="supplier-form" variant="primary" busy={saving}>
            {supplier ? 'Save changes' : 'Add supplier'}
          </Button>
        </>
      }
    >
      <form id="supplier-form" onSubmit={submit} noValidate className="stack stack--tight">
        {serverError ? <Notice kind="error">{serverError}</Notice> : null}
        <FormGrid>
          <Field label="Name" error={show('name')} span2>
            {(props) => (
              <input
                {...props}
                value={form.name}
                onChange={(event) => update('name', event.target.value)}
                data-autofocus=""
                placeholder="Northgate Mills"
              />
            )}
          </Field>
          <Field
            label="Code"
            error={show('code')}
            optional={!supplier}
            hint={supplier ? undefined : 'Leave blank to generate one'}
          >
            {(props) => (
              <input
                {...props}
                value={form.code}
                onChange={(event) => update('code', event.target.value)}
                autoComplete="off"
                placeholder="SUP-000001"
              />
            )}
          </Field>
          <Field label="Contact person" optional>
            {(props) => (
              <input
                {...props}
                value={form.contact_person}
                onChange={(event) => update('contact_person', event.target.value)}
              />
            )}
          </Field>
          <Field label="Phone" optional>
            {(props) => (
              <input
                {...props}
                type="tel"
                value={form.phone}
                onChange={(event) => update('phone', event.target.value)}
              />
            )}
          </Field>
          <Field label="Email" error={show('email')} optional>
            {(props) => (
              <input
                {...props}
                type="email"
                value={form.email}
                onChange={(event) => update('email', event.target.value)}
              />
            )}
          </Field>
          <Field label="Address" optional span2>
            {(props) => (
              <textarea
                {...props}
                value={form.address}
                onChange={(event) => update('address', event.target.value)}
              />
            )}
          </Field>
          <Field label="Notes" optional span2>
            {(props) => (
              <textarea
                {...props}
                value={form.notes}
                onChange={(event) => update('notes', event.target.value)}
              />
            )}
          </Field>
        </FormGrid>
      </form>
    </Dialog>
  )
}

function ArchiveSupplier({
  supplier,
  onClose,
  onDone,
}: {
  supplier: Supplier
  onClose: () => void
  onDone: (supplier: Supplier) => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function confirm() {
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      onDone(await api.suppliers.archive(supplier.id))
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : String(cause))
      setBusy(false)
    }
  }

  return (
    <ConfirmDialog
      title={`Archive ${supplier.name}?`}
      confirmLabel="Archive"
      destructive
      busy={busy}
      error={error}
      onCancel={onClose}
      onConfirm={confirm}
      icon={<ArchiveIcon size={19} />}
      message={
        <p>
          It will no longer be offered for new purchase orders. Existing orders, goods receipts and
          stock movements are kept.
        </p>
      }
    />
  )
}

function SupplierInspector({
  supplier,
  onClose,
  onEdit,
}: {
  supplier: Supplier
  onClose: () => void
  onEdit: () => void
}) {
  const { data, loading, error } = useAsync<SupplierDetail>(
    () => api.suppliers.get(supplier.id),
    [supplier.id],
  )
  const [tab, setTab] = useState<'orders' | 'receipts'>('orders')

  return (
    <Sheet
      title={supplier.name}
      subtitle={<span className="mono">{supplier.code}</span>}
      onClose={onClose}
      actions={
        <>
          <Button size="sm" icon={<EditIcon size={14} />} onClick={onEdit}>
            Edit
          </Button>
          {supplier.is_active ? (
            <LinkButton
              size="sm"
              variant="primary"
              icon={<PlusIcon size={14} />}
              to={`/purchase-orders?new=1&supplier=${supplier.id}`}
            >
              Order
            </LinkButton>
          ) : null}
        </>
      }
    >
      {loading && !data ? <Loading /> : null}
      {error ? <Notice kind="error">{error}</Notice> : null}
      {data ? (
        <div className="stack">
          <Card>
            <div className="card__body">
              <KeyValue
                items={[
                  { label: 'Contact', value: data.contact_person || '—' },
                  { label: 'Phone', value: data.phone || '—' },
                  {
                    label: 'Email',
                    value: data.email ? <a href={`mailto:${data.email}`}>{data.email}</a> : '—',
                  },
                  { label: 'Status', value: data.is_active ? 'Active' : 'Archived' },
                ]}
              />
              {data.address ? <p className="t-callout mt-3">{data.address}</p> : null}
              {data.notes ? <p className="t-callout muted mt-2">{data.notes}</p> : null}
            </div>
          </Card>

          <Segmented
            label="History"
            small
            value={tab}
            onChange={setTab}
            options={[
              { value: 'orders', label: 'Purchase orders', count: data.purchase_orders.length },
              { value: 'receipts', label: 'Goods receipts', count: data.goods_receipts.length },
            ]}
          />

          <Card flush>
            {tab === 'orders' ? (
              data.purchase_orders.length === 0 ? (
                <EmptyState compact title="Nothing ordered from this supplier yet" />
              ) : (
                <TableScroll>
                  <table className="table table--compact">
                    <thead>
                      <tr>
                        <th>Order</th>
                        <th>Status</th>
                        <th className="num">Received</th>
                        <th className="num">Value</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.purchase_orders.map((row) => (
                        <tr key={row.id}>
                          <td>
                            <Link className="cell-link mono" to={`/purchase-orders/${row.id}`}>
                              {row.po_number}
                            </Link>
                            <span className="cell-sub">{formatDate(row.created_at)}</span>
                          </td>
                          <td>
                            <PurchaseStatusBadge status={row.status} />
                          </td>
                          <td className="num">
                            {formatQuantity(row.total_received)}
                            <span className="cell-sub">of {formatQuantity(row.total_ordered)}</span>
                          </td>
                          <td className="num">{formatAmount(row.total_cost)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </TableScroll>
              )
            ) : data.goods_receipts.length === 0 ? (
              <EmptyState compact title="Nothing received from this supplier yet" />
            ) : (
              <TableScroll>
                <table className="table table--compact">
                  <thead>
                    <tr>
                      <th>Receipt</th>
                      <th>Against</th>
                      <th className="num">Quantity</th>
                      <th className="num">Cost</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.goods_receipts.map((row) => (
                      <tr key={row.id}>
                        <td>
                          <span className="mono cell-primary">{row.receipt_number}</span>
                          <span className="cell-sub">{formatDateTime(row.created_at)}</span>
                        </td>
                        <td>
                          <Link className="cell-link mono" to={`/purchase-orders/${row.purchase_order_id}`}>
                            {row.po_number}
                          </Link>
                          {row.delivery_note_reference ? (
                            <span className="cell-sub">{row.delivery_note_reference}</span>
                          ) : null}
                        </td>
                        <td className="num">{formatQuantity(row.total_quantity)}</td>
                        <td className="num">{formatAmount(row.total_cost)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableScroll>
            )}
          </Card>
        </div>
      ) : null}
    </Sheet>
  )
}
