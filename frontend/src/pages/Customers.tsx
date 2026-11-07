import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import type { Customer, CustomerListRow } from '../api/types'
import {
  ActionMenu,
  ArchivedBadge,
  Avatar,
  Button,
  CardFacts,
  Collection,
  ConfirmDialog,
  Dialog,
  DialogCancel,
  EmptyState,
  ExportButton,
  Field,
  FormGrid,
  Notice,
  Page,
  RecordCard,
  SearchField,
  Segmented,
  SortHeader,
  Toolbar,
  ViewSwitch,
  useRowLink,
  useToast,
  type Sort,
} from '../components/ui'
import {
  ArchiveIcon,
  ChevronIcon,
  CustomersIcon,
  EditIcon,
  PlusIcon,
  RestoreIcon,
  SalesOrderIcon,
} from '../components/icons'
import { downloadCsv, fileStamp } from '../lib/csv'
import { formatDate, formatMoney, formatQuantity, formatRelative } from '../lib/format'
import { usePaging, useViewMode } from '../lib/paging'
import { useAsync, useDebounced } from '../lib/useAsync'
import { useCreateParam } from '../lib/useCreateParam'
import { isValidEmail } from '../lib/validation'

export default function CustomersPage() {
  const toast = useToast()
  const navigate = useNavigate()
  const rowLink = useRowLink()
  const [search, setSearch] = useState('')
  const [scope, setScope] = useState<'active' | 'all'>('active')
  const [sort, setSort] = useState<Sort>({ by: 'name', dir: 'asc' })
  const debouncedSearch = useDebounced(search)
  const [view, setView] = useViewMode('customers')

  const filters = { search: debouncedSearch || undefined, include_inactive: scope === 'all' }
  const paging = usePaging('customers', [filters, sort])
  const state = useAsync(
    () =>
      api.customers.list({
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
  const [editing, setEditing] = useState<Customer | null>(null)
  const [archiving, setArchiving] = useState<Customer | null>(null)

  async function restore(customer: Customer) {
    try {
      await api.customers.update(customer.id, { is_active: true })
      toast.success(`${customer.name} restored`)
      reload()
    } catch (cause) {
      toast.error('Could not restore', cause instanceof ApiError ? cause.message : String(cause))
    }
  }

  async function exportCsv() {
    const rows = await api.customers.all({ ...filters, sort_by: sort.by, sort_dir: sort.dir })
    downloadCsv(
      `customers-${fileStamp()}.csv`,
      [
        { header: 'Customer', value: (row) => row.name },
        { header: 'Phone', value: (row) => row.phone },
        { header: 'Email', value: (row) => row.email },
        { header: 'Address', value: (row) => row.address },
        { header: 'Orders', value: (row) => row.order_count },
        { header: 'Open orders', value: (row) => row.open_order_count },
        { header: 'Ordered value', value: (row) => row.ordered_value },
        { header: 'To deliver quantity', value: (row) => row.outstanding_quantity },
        { header: 'To deliver value', value: (row) => row.outstanding_value },
        { header: 'Last order', value: (row) => row.last_order_at },
        { header: 'Customer since', value: (row) => row.created_at },
        { header: 'Archived', value: (row) => (row.is_active ? 'No' : 'Yes') },
      ],
      rows,
    )
    toast.success('Export ready', `${rows.length} customer${rows.length === 1 ? '' : 's'} downloaded as CSV.`)
  }

  function menu(customer: CustomerListRow) {
    return (
      <ActionMenu
        label={`Actions for ${customer.name}`}
        items={[
          {
            label: 'New order',
            icon: <SalesOrderIcon size={15} />,
            onSelect: () => navigate(`/orders?new=1&customer=${customer.id}`),
            disabled: !customer.is_active,
          },
          {
            label: 'Edit',
            icon: <EditIcon size={15} />,
            onSelect: () => setEditing(customer),
          },
          customer.is_active
            ? {
                label: 'Archive',
                icon: <ArchiveIcon size={15} />,
                destructive: true,
                separatorBefore: true,
                onSelect: () => setArchiving(customer),
              }
            : {
                label: 'Restore',
                icon: <RestoreIcon size={15} />,
                separatorBefore: true,
                onSelect: () => restore(customer),
              },
        ]}
      />
    )
  }

  const contact = (customer: CustomerListRow) =>
    [customer.phone, customer.email].filter(Boolean).join(' · ') || 'No contact details'

  return (
    <Page>
      <Toolbar
        title="Customers"
        count={data?.total}
        subtitle="Orders stay linked to a customer even after it is archived"
        actions={
          <>
            <ExportButton onExport={exportCsv} disabled={!data?.total} />
            <Button variant="primary" icon={<PlusIcon size={15} />} onClick={() => setCreating(true)}>
              New customer
            </Button>
          </>
        }
      >
        <SearchField
          value={search}
          onChange={setSearch}
          placeholder="Search customers"
          label="Search customers"
        />
        <Segmented
          label="Which customers"
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
        noun="customers"
        columns={6}
        empty={
          <EmptyState
            icon={<CustomersIcon size={22} />}
            title={search ? 'No matching customers' : 'No customers yet'}
            body={
              search
                ? `Nothing matches “${search}”.`
                : 'Add a customer before taking their first enquiry or order.'
            }
            action={
              search ? (
                <Button onClick={() => setSearch('')}>Clear search</Button>
              ) : (
                <Button variant="primary" onClick={() => setCreating(true)}>
                  New customer
                </Button>
              )
            }
          />
        }
        table={(rows) => (
          <table className="table table--interactive">
            <thead>
              <tr>
                <SortHeader field="name" label="Customer" sort={sort} onSort={setSort} />
                <th>Contact</th>
                <th className="num">Open orders</th>
                <th className="num">To deliver</th>
                <th className="num">Ordered value</th>
                <th className="num">Last order</th>
                <SortHeader field="created_at" label="Since" sort={sort} onSort={setSort} numeric />
                <th className="col-actions">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((customer) => (
                <tr
                  key={customer.id}
                  className={customer.is_active ? undefined : 'is-muted'}
                  {...rowLink(`/customers/${customer.id}`)}
                >
                  <td>
                    <div className="cell-identity">
                      <Avatar name={customer.name} seed={customer.id} />
                      <div>
                        <div className="row">
                          <span className="cell-primary">{customer.name}</span>
                          {!customer.is_active ? <ArchivedBadge /> : null}
                        </div>
                        {customer.address ? (
                          <span className="cell-sub cell-clip">{customer.address}</span>
                        ) : null}
                      </div>
                    </div>
                  </td>
                  <td>
                    <span className="cell-primary">{customer.phone || <span className="q-muted">—</span>}</span>
                    {customer.email ? <span className="cell-sub cell-clip">{customer.email}</span> : null}
                  </td>
                  <td className="num">
                    {customer.open_order_count > 0 ? (
                      customer.open_order_count
                    ) : (
                      <span className="q-muted">—</span>
                    )}
                  </td>
                  <td className="num">
                    {Number(customer.outstanding_quantity) > 0 ? (
                      <>
                        <span className="q-strong">{formatQuantity(customer.outstanding_quantity)}</span>
                        <span className="cell-sub">{formatMoney(customer.outstanding_value)}</span>
                      </>
                    ) : (
                      <span className="q-muted">—</span>
                    )}
                  </td>
                  <td className="num">{formatMoney(customer.ordered_value)}</td>
                  <td className="num nowrap">
                    {customer.last_order_at ? formatRelative(customer.last_order_at) : <span className="q-muted">Never</span>}
                  </td>
                  <td className="num nowrap">{formatDate(customer.created_at)}</td>
                  <td className="col-actions">
                    <div className="row row--end gap-1">
                      {menu(customer)}
                      <ChevronIcon size={15} className="row-chevron" aria-hidden="true" />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        card={(customer) => (
          <RecordCard
            key={customer.id}
            to={`/customers/${customer.id}`}
            tone={customer.is_active ? undefined : 'muted'}
            leading={<Avatar name={customer.name} seed={customer.id} size="lg" />}
            title={customer.name}
            subtitle={contact(customer)}
            badge={!customer.is_active ? <ArchivedBadge /> : undefined}
            actions={menu(customer)}
            footer={
              <>
                <span>
                  {customer.last_order_at
                    ? `Last order ${formatRelative(customer.last_order_at)}`
                    : 'No orders yet'}
                </span>
                <span className="grow" />
                <span>Since {formatDate(customer.created_at)}</span>
              </>
            }
          >
            <CardFacts
              items={[
                {
                  label: 'Open orders',
                  value: customer.open_order_count || '—',
                  tone: customer.open_order_count ? undefined : 'is-muted',
                },
                {
                  label: 'To deliver',
                  value: Number(customer.outstanding_quantity) > 0 ? formatQuantity(customer.outstanding_quantity) : '—',
                  tone: Number(customer.outstanding_quantity) > 0 ? undefined : 'is-muted',
                },
                { label: 'Ordered value', value: formatMoney(customer.ordered_value) },
              ]}
            />
          </RecordCard>
        )}
      />

      {creating ? (
        <CustomerForm
          onClose={() => setCreating(false)}
          onSaved={(customer) => {
            setCreating(false)
            toast.success(`${customer.name} added`, undefined, {
              label: 'Open',
              onClick: () => navigate(`/customers/${customer.id}`),
            })
            reload()
          }}
        />
      ) : null}

      {editing ? (
        <CustomerForm
          customer={editing}
          onClose={() => setEditing(null)}
          onSaved={(customer) => {
            setEditing(null)
            toast.success(`${customer.name} updated`)
            reload()
          }}
        />
      ) : null}

      {archiving ? (
        <ArchiveCustomer
          customer={archiving}
          onClose={() => setArchiving(null)}
          onDone={(customer) => {
            setArchiving(null)
            toast.success(`${customer.name} archived`, 'Their order history is unchanged.', {
              label: 'Undo',
              onClick: () => restore(customer),
            })
            reload()
          }}
        />
      ) : null}
    </Page>
  )
}

interface FormState {
  name: string
  phone: string
  email: string
  address: string
  notes: string
}

export function CustomerForm({
  customer,
  onClose,
  onSaved,
}: {
  customer?: Customer
  onClose: () => void
  onSaved: (customer: Customer) => void
}) {
  const [form, setForm] = useState<FormState>({
    name: customer?.name ?? '',
    phone: customer?.phone ?? '',
    email: customer?.email ?? '',
    address: customer?.address ?? '',
    notes: customer?.notes ?? '',
  })
  const [touched, setTouched] = useState(false)
  const [saving, setSaving] = useState(false)
  const [serverError, setServerError] = useState<string | null>(null)

  const errors = useMemo(() => {
    const next: Partial<Record<keyof FormState, string>> = {}
    if (!form.name.trim()) next.name = 'Enter the customer’s name.'
    if (form.email.trim() && !isValidEmail(form.email)) next.email = 'Enter a valid email, or leave it blank.'
    return next
  }, [form])
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
        name: form.name.trim(),
        phone: form.phone.trim() || null,
        email: form.email.trim() || null,
        address: form.address.trim() || null,
        notes: form.notes.trim() || null,
      }
      onSaved(
        customer
          ? await api.customers.update(customer.id, payload)
          : await api.customers.create(payload),
      )
    } catch (cause) {
      setServerError(cause instanceof ApiError ? cause.message : String(cause))
      setSaving(false)
    }
  }

  return (
    <Dialog
      title={customer ? `Edit ${customer.name}` : 'New customer'}
      onClose={onClose}
      busy={saving}
      size="medium"
      footer={
        <>
          <DialogCancel />
          <Button type="submit" form="customer-form" variant="primary" busy={saving}>
            {customer ? 'Save changes' : 'Add customer'}
          </Button>
        </>
      }
    >
      <form id="customer-form" onSubmit={submit} noValidate className="stack stack--tight">
        {serverError ? <Notice kind="error">{serverError}</Notice> : null}
        <FormGrid>
          <Field label="Name" error={show('name')} span2>
            {(props) => (
              <input
                {...props}
                value={form.name}
                onChange={(event) => update('name', event.target.value)}
                data-autofocus=""
                placeholder="ABC Traders"
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

function ArchiveCustomer({
  customer,
  onClose,
  onDone,
}: {
  customer: Customer
  onClose: () => void
  onDone: (customer: Customer) => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function confirm() {
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      onDone(await api.customers.archive(customer.id))
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : String(cause))
      setBusy(false)
    }
  }

  return (
    <ConfirmDialog
      title={`Archive ${customer.name}?`}
      confirmLabel="Archive"
      destructive
      busy={busy}
      error={error}
      onCancel={onClose}
      onConfirm={confirm}
      icon={<ArchiveIcon size={19} />}
      message={
        <p>
          They will no longer appear when taking new orders. Existing orders, what is still to deliver to them and
          their delivery history are all kept.
        </p>
      }
    />
  )
}
