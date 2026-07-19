import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  startTransition,
  useDeferredValue,
  useRef,
  useState,
  type FormEvent,
} from 'react'

import {
  apiRequest,
  idempotencyKey,
  type AccountItem,
  type AccountItemStatus,
  type ArtifactDownload,
  type DiscountInput,
  type DocumentArtifact,
  type EmissionPoint,
  type Establishment,
  type InvoiceLineInput,
  type Operation,
  type Party,
  type PaymentInput,
  type Product,
  type ReminderInput,
  type RetentionInput,
  type SalesDocument,
  type SalesDocumentStatus,
  type TaxCategory,
  type TenantContext,
} from './api'
import { useAuth } from './auth'
import {
  ErpActionCell,
  ErpButton,
  ErpEmptyState,
  ErpFormPanel,
  ErpPageHeader,
  ErpPanel,
  ErpStatusBadge,
  ErpToolbar,
} from './components/erp'
import { LeadsPage } from './components/crm'

type Section = 'overview' | 'parties' | 'products' | 'invoices' | 'receivables' | 'organization' | 'crm'

const sections: Array<{ id: Section; label: string; eyebrow: string }> = [
  { id: 'overview', label: 'Resumen', eyebrow: '01' },
  { id: 'parties', label: 'Contactos', eyebrow: '02' },
  { id: 'products', label: 'Productos', eyebrow: '03' },
  { id: 'invoices', label: 'Facturas', eyebrow: '04' },
  { id: 'organization', label: 'Empresa', eyebrow: '05' },
  { id: 'receivables', label: 'Cartera', eyebrow: '06' },
  { id: 'crm', label: 'CRM', eyebrow: '07' },
]

function DevLogin() {
  const { loginDev } = useAuth()
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSubmitting(true)
    setError('')
    const data = new FormData(event.currentTarget)
    try {
      await loginDev(String(data.get('email')), String(data.get('tenantId')))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'No se pudo iniciar sesión')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="login-shell">
      <section className="login-story" aria-labelledby="login-title">
        <div className="brand-mark" aria-hidden="true">IA</div>
        <p className="kicker">IAERP / Ecuador</p>
        <h1 id="login-title">Decisiones financieras con contexto completo.</h1>
        <p className="login-copy">
          Facturación, cartera y obligaciones en una sola operación trazable,
          preparada para equipos y agentes.
        </p>
      </section>
      <section className="login-panel" aria-labelledby="access-title">
        <p className="section-number">Acceso local</p>
        <h2 id="access-title">Entrar al espacio de trabajo</h2>
        <form onSubmit={submit}>
          <label>
            Correo
            <input name="email" type="email" defaultValue="owner@iaerp.local" required />
          </label>
          <label>
            ID de empresa
            <input
              name="tenantId"
              defaultValue="11111111-1111-4111-8111-111111111111"
              required
            />
          </label>
          {error ? <p className="form-error" role="alert">{error}</p> : null}
          <button className="primary-button" type="submit" disabled={submitting}>
            {submitting ? 'Validando…' : 'Continuar'}
          </button>
        </form>
        <p className="fine-print">Solo visible cuando `VITE_AUTH_MODE=dev`.</p>
      </section>
    </main>
  )
}

function OidcLogin() {
  const { loginOidc } = useAuth()
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSubmitting(true)
    setError('')
    const data = new FormData(event.currentTarget)
    try {
      await loginOidc(String(data.get('organizationAlias')))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'No se pudo iniciar sesión')
      setSubmitting(false)
    }
  }

  return (
    <main className="login-shell">
      <section className="login-story" aria-labelledby="login-title">
        <div className="brand-mark" aria-hidden="true">IA</div>
        <p className="kicker">IAERP / Acceso seguro</p>
        <h1 id="login-title">Una empresa activa. Ningún dato cruzado.</h1>
        <p className="login-copy">
          Selecciona el alias de la empresa antes de autenticarte. El token
          quedará ligado únicamente a esa organización.
        </p>
      </section>
      <section className="login-panel" aria-labelledby="access-title">
        <p className="section-number">OAuth 2.1 + PKCE</p>
        <h2 id="access-title">Elegir empresa</h2>
        <form onSubmit={submit}>
          <label>
            Alias de empresa
            <input
              name="organizationAlias"
              defaultValue="iaerp-norte"
              pattern="[a-z0-9][a-z0-9-]{1,62}"
              autoComplete="organization"
              required
            />
          </label>
          {error ? <p className="form-error" role="alert">{error}</p> : null}
          <button className="primary-button" type="submit" disabled={submitting}>
            {submitting ? 'Redirigiendo…' : 'Continuar con Keycloak'}
          </button>
        </form>
        <p className="fine-print">
          Usa `iaerp-norte` o `iaerp-sur` para el entorno local.
        </p>
      </section>
    </main>
  )
}

function LoadingScreen() {
  return (
    <main className="loading-screen" aria-busy="true">
      <div className="brand-mark" aria-hidden="true">IA</div>
      <p>Preparando el espacio financiero…</p>
    </main>
  )
}

function Overview({
  context,
  parties,
  products,
}: {
  context: TenantContext
  parties: Party[]
  products: Product[]
}) {
  const customers = parties.filter((party) => party.roles.includes('CUSTOMER')).length
  const suppliers = parties.filter((party) => party.roles.includes('SUPPLIER')).length
  return (
    <>
      <ErpPageHeader
        eyebrow="Pulso operativo"
        title={context.name}
        subtitle="Resumen de preparación y datos maestros del tenant activo."
        meta={<span className="date-chip">RUC {context.ruc}</span>}
      />
      <section className="metric-grid" aria-label="Indicadores de datos maestros">
        <article className="metric-card metric-feature">
          <span className="metric-label">Preparación</span>
          <strong>{context.automationWritesEnabled ? 'Activa' : 'Supervisada'}</strong>
          <p>Escrituras autónomas {context.automationWritesEnabled ? 'habilitadas' : 'pausadas'}.</p>
        </article>
        <article className="metric-card">
          <span className="metric-label">Clientes</span>
          <strong>{customers.toString().padStart(2, '0')}</strong>
          <p>Contactos listos para facturar.</p>
        </article>
        <article className="metric-card">
          <span className="metric-label">Proveedores</span>
          <strong>{suppliers.toString().padStart(2, '0')}</strong>
          <p>Contrapartes registradas.</p>
        </article>
        <article className="metric-card">
          <span className="metric-label">Catálogo</span>
          <strong>{products.length.toString().padStart(2, '0')}</strong>
          <p>Productos con definición tributaria.</p>
        </article>
      </section>
      <section className="readiness-panel">
        <div>
          <p className="section-number">Próximo hito</p>
          <h2>Base fiscal lista para facturación</h2>
        </div>
        <ol className="readiness-list">
          <li><span>01</span> Verificar establecimiento y punto de emisión</li>
          <li><span>02</span> Completar catálogo y contactos</li>
          <li><span>03</span> Cargar certificado de firma de forma segura</li>
        </ol>
      </section>
    </>
  )
}

function PartiesPage({
  parties,
  token,
}: {
  parties: Party[]
  token: string
}) {
  const queryClient = useQueryClient()
  const [query, setQuery] = useState('')
  const [editor, setEditor] = useState<Party | null | undefined>(undefined)
  const deferredQuery = useDeferredValue(query.toLocaleLowerCase())
  const filtered = parties.filter((party) =>
    `${party.name} ${party.identificationNumber}`.toLocaleLowerCase().includes(deferredQuery),
  )
  const createParty = useMutation({
    mutationFn: (data: {
      id?: string
      name: FormDataEntryValue | null
      identificationType: FormDataEntryValue | null
      identificationNumber: FormDataEntryValue | null
      role: FormDataEntryValue | null
      email: FormDataEntryValue | null
    }) =>
      apiRequest<Party>(token, data.id ? `/parties/${data.id}` : '/parties', {
        method: data.id ? 'PUT' : 'POST',
        headers: { 'Idempotency-Key': idempotencyKey('web-party') },
        body: JSON.stringify({
          name: data.name,
          identificationType: data.identificationType,
          identificationNumber: data.identificationNumber,
          roles: [data.role],
          email: data.email || null,
        }),
      }),
    onSuccess: () => {
      setEditor(undefined)
      return queryClient.invalidateQueries({ queryKey: ['parties'] })
    },
  })

  function submitParty(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const data = new FormData(form)
    createParty.mutate(
      {
        id: editor?.id,
        name: data.get('name'),
        identificationType: data.get('identificationType'),
        identificationNumber: data.get('identificationNumber'),
        role: data.get('role'),
        email: data.get('email'),
      },
    )
  }

  return (
    <>
      <ErpPageHeader
        eyebrow="Datos maestros"
        title="Contactos"
        subtitle="Clientes y proveedores compartidos por facturación y cartera."
        actions={
          <ErpButton variant="primary" onClick={() => setEditor(null)}>
            Nuevo contacto
          </ErpButton>
        }
      />
      <ErpToolbar>
        <label className="search-field">
          <span>Buscar contacto</span>
          <input value={query} onChange={(event) => setQuery(event.target.value)} />
        </label>
      </ErpToolbar>
      <section className={`split-layout ${editor === undefined ? 'erp-list-only' : ''}`}>
        <ErpPanel title="Clientes y proveedores" count={filtered.length}>
          <div className="table-wrap">
            <table className="erp-responsive-table">
              <thead><tr><th>Nombre</th><th>Identificación</th><th>Rol</th><th>Acciones</th></tr></thead>
              <tbody>
                {filtered.map((party) => (
                  <tr key={party.id}>
                    <td><strong>{party.name}</strong><small>{party.email ?? 'Sin correo'}</small></td>
                    <td>{party.identificationNumber}</td>
                    <td><span className="tag">{party.roles.join(' / ')}</span></td>
                    <td>
                      <ErpActionCell>
                        <ErpButton
                          variant="ghost"
                          aria-label={`Editar ${party.name}`}
                          onClick={() => setEditor(party)}
                        >
                          Editar
                        </ErpButton>
                      </ErpActionCell>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {filtered.length === 0 ? (
              <ErpEmptyState
                title="No hay contactos"
                description="Crea el primer cliente o proveedor para comenzar."
                action={
                  <ErpButton variant="primary" onClick={() => setEditor(null)}>
                    Nuevo contacto
                  </ErpButton>
                }
              />
            ) : null}
          </div>
        </ErpPanel>
        {editor !== undefined ? (
          <ErpFormPanel
            key={editor?.id ?? 'new-party'}
            eyebrow={editor ? 'Edición' : 'Nuevo registro'}
            title={editor ? 'Editar contacto' : 'Nuevo contacto'}
            pending={createParty.isPending}
            error={createParty.error?.message}
            onSubmit={submitParty}
            onCancel={() => setEditor(undefined)}
          >
            <label>Nombre o razón social<input name="name" defaultValue={editor?.name} required /></label>
            <div className="field-row">
              <label>Tipo<select name="identificationType" defaultValue={editor?.identificationType ?? 'RUC'}><option>RUC</option><option>CEDULA</option><option>PASSPORT</option></select></label>
              <label>Número<input name="identificationNumber" defaultValue={editor?.identificationNumber} required /></label>
            </div>
            <label>Rol<select name="role" defaultValue={editor?.roles[0] ?? 'CUSTOMER'}><option value="CUSTOMER">Cliente</option><option value="SUPPLIER">Proveedor</option></select></label>
            <label>Correo<input name="email" type="email" defaultValue={editor?.email ?? ''} /></label>
          </ErpFormPanel>
        ) : null}
      </section>
    </>
  )
}

function ProductsPage({
  products,
  taxes,
  token,
}: {
  products: Product[]
  taxes: TaxCategory[]
  token: string
}) {
  const queryClient = useQueryClient()
  const [query, setQuery] = useState('')
  const [editor, setEditor] = useState<Product | null | undefined>(undefined)
  const deferredQuery = useDeferredValue(query.toLocaleLowerCase())
  const filtered = products.filter((product) =>
    `${product.name} ${product.code ?? ''}`.toLocaleLowerCase().includes(deferredQuery),
  )
  const createProduct = useMutation({
    mutationFn: (data: {
      id?: string
      name: FormDataEntryValue | null
      code: FormDataEntryValue | null
      unitPrice: FormDataEntryValue | null
      taxCategoryId: FormDataEntryValue | null
    }) =>
      apiRequest<Product>(token, data.id ? `/products/${data.id}` : '/products', {
        method: data.id ? 'PUT' : 'POST',
        headers: { 'Idempotency-Key': idempotencyKey('web-product') },
        body: JSON.stringify({
          name: data.name,
          code: data.code || null,
          unitPrice: data.unitPrice,
          taxCategoryId: data.taxCategoryId,
        }),
      }),
    onSuccess: () => {
      setEditor(undefined)
      return queryClient.invalidateQueries({ queryKey: ['products'] })
    },
  })

  function submitProduct(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const data = new FormData(form)
    createProduct.mutate(
      {
        id: editor?.id,
        name: data.get('name'),
        code: data.get('code'),
        unitPrice: data.get('unitPrice'),
        taxCategoryId: data.get('taxCategoryId'),
      },
    )
  }

  return (
    <>
      <ErpPageHeader
        eyebrow="Catálogo comercial"
        title="Productos"
        subtitle="Productos y servicios con precio e impuestos vigentes."
        actions={
          <ErpButton variant="primary" onClick={() => setEditor(null)}>
            Nuevo producto
          </ErpButton>
        }
      />
      <ErpToolbar>
        <label className="search-field">
          <span>Buscar producto</span>
          <input value={query} onChange={(event) => setQuery(event.target.value)} />
        </label>
        <ErpStatusBadge>{products.length} activos</ErpStatusBadge>
      </ErpToolbar>
      <section className={`split-layout ${editor === undefined ? 'erp-list-only' : ''}`}>
        <ErpPanel title="Catálogo" count={filtered.length}>
          <div className="product-grid" aria-label="Productos">
            {filtered.map((product, index) => (
              <article className="product-card" key={product.id}>
                <span>{String(index + 1).padStart(2, '0')}</span>
                <h2>{product.name}</h2>
                <p>{product.code ?? 'Sin código interno'}</p>
                <strong>${Number(product.unitPrice).toFixed(2)}</strong>
                <ErpButton
                  variant="ghost"
                  aria-label={`Editar ${product.name}`}
                  onClick={() => setEditor(product)}
                >
                  Editar
                </ErpButton>
              </article>
            ))}
            {filtered.length === 0 ? (
              <ErpEmptyState
                title="No hay productos"
                description="Crea el primer producto o servicio del catálogo."
                action={
                  <ErpButton variant="primary" onClick={() => setEditor(null)}>
                    Nuevo producto
                  </ErpButton>
                }
              />
            ) : null}
          </div>
        </ErpPanel>
        {editor !== undefined ? (
          <ErpFormPanel
            key={editor?.id ?? 'new-product'}
            eyebrow={editor ? 'Edición' : 'Nuevo registro'}
            title={editor ? 'Editar producto' : 'Nuevo producto'}
            pending={createProduct.isPending}
            error={createProduct.error?.message}
            onSubmit={submitProduct}
            onCancel={() => setEditor(undefined)}
          >
            <label>Nombre<input name="name" defaultValue={editor?.name} required /></label>
            <label>Código interno<input name="code" defaultValue={editor?.code ?? ''} /></label>
            <label>Precio unitario<input name="unitPrice" type="number" min="0" step="0.000001" defaultValue={editor?.unitPrice} required /></label>
            <label>Categoría tributaria<select name="taxCategoryId" defaultValue={editor?.taxCategoryId ?? taxes[0]?.id} required>{taxes.map((tax) => <option key={tax.id} value={tax.id}>{tax.name} · {tax.rate}%</option>)}</select></label>
          </ErpFormPanel>
        ) : null}
      </section>
    </>
  )
}

const invoiceStatusLabels: Record<SalesDocumentStatus, string> = {
  DRAFT: 'BORRADOR',
  READY: 'LISTA',
  SIGNED: 'FIRMADA',
  RECEIVED: 'ENVIADA',
  PENDING_AUTHORIZATION: 'ENVIADA',
  AUTHORIZED: 'AUTORIZADA',
  REJECTED: 'RECHAZADA',
  FAILED: 'FALLIDA',
  VOIDED: 'NO AUTORIZADA',
}

const invoiceStatusTone: Record<SalesDocumentStatus, 'neutral' | 'success' | 'warning' | 'danger'> = {
  DRAFT: 'neutral',
  READY: 'neutral',
  SIGNED: 'warning',
  RECEIVED: 'warning',
  PENDING_AUTHORIZATION: 'warning',
  AUTHORIZED: 'success',
  REJECTED: 'danger',
  FAILED: 'danger',
  VOIDED: 'danger',
}

function InvoiceStatusBadge({ status }: { status: SalesDocumentStatus }) {
  return <ErpStatusBadge tone={invoiceStatusTone[status]}>{invoiceStatusLabels[status]}</ErpStatusBadge>
}

type DraftLine = {
  key: string
  productId: string
  description: string
  quantity: string
  unitPrice: string
  discount: string
  taxCode: string
}

function emptyDraftLine(): DraftLine {
  return {
    key: crypto.randomUUID(),
    productId: '',
    description: '',
    quantity: '1',
    unitPrice: '0.00',
    discount: '0.00',
    taxCode: '',
  }
}

function todayInFiscalTimezone(): string {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/Guayaquil',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date())
  const values = Object.fromEntries(parts.map(({ type, value }) => [type, value]))
  return `${values.year}-${values.month}-${values.day}`
}

type InvoicePanel =
  | { view: 'new' }
  | { view: 'detail'; id: string }
  | { view: 'credit-note'; invoice: SalesDocument }

function NewInvoiceForm({
  token,
  customers,
  products,
  taxes,
  establishments,
  emissionPoints,
  onCreated,
  onCancel,
}: {
  token: string
  customers: Party[]
  products: Product[]
  taxes: TaxCategory[]
  establishments: Establishment[]
  emissionPoints: EmissionPoint[]
  onCreated: (invoiceId: string) => void
  onCancel: () => void
}) {
  const queryClient = useQueryClient()
  const [customerId, setCustomerId] = useState(customers[0]?.id ?? '')
  const [establishmentId, setEstablishmentId] = useState(establishments[0]?.id ?? '')
  const [emissionPointId, setEmissionPointId] = useState(
    emissionPoints.find((point) => point.establishmentId === establishments[0]?.id)?.id ?? '',
  )
  const [issueDate, setIssueDate] = useState(todayInFiscalTimezone)
  const [lines, setLines] = useState<DraftLine[]>([emptyDraftLine()])

  const availableEmissionPoints = emissionPoints.filter(
    (point) => point.establishmentId === establishmentId,
  )

  function updateLine(key: string, patch: Partial<DraftLine>) {
    setLines((current) => current.map((line) => (line.key === key ? { ...line, ...patch } : line)))
  }

  function onProductChange(key: string, productId: string) {
    const product = products.find((item) => item.id === productId)
    updateLine(key, {
      productId,
      description: product?.name ?? '',
      unitPrice: product?.unitPrice ?? '0.00',
      taxCode: taxes.find((tax) => tax.id === product?.taxCategoryId)?.sriCode ?? product?.taxCategoryId ?? '',
    })
  }

  const createDraft = useMutation({
    mutationFn: (payload: {
      customerId: string
      establishmentId: string
      emissionPointId: string
      issueDate: string
      lines: InvoiceLineInput[]
    }) =>
      apiRequest<SalesDocument>(token, '/invoices', {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey('web-invoice') },
        body: JSON.stringify({
          customerId: payload.customerId,
          establishmentId: payload.establishmentId,
          emissionPointId: payload.emissionPointId,
          issueDate: payload.issueDate,
          // Sin plan de pago: el backend crea una sola cuota al contado por el
          // total. La UI nunca calcula el total, asi que no puede declarar
          // cuotas que cuadren; las omite y deja que el backend las derive.
          installments: [],
          lines: payload.lines,
        }),
      }),
    onSuccess: (invoice) => {
      void queryClient.invalidateQueries({ queryKey: ['invoices'] })
      onCreated(invoice.id)
    },
  })

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    createDraft.mutate({
      customerId,
      establishmentId,
      emissionPointId,
      issueDate,
      lines: lines.map((line) => ({
        productId: line.productId || null,
        description: line.description,
        quantity: line.quantity,
        unitPrice: line.unitPrice,
        discount: line.discount || '0.00',
        taxCode: line.taxCode,
      })),
    })
  }

  return (
    <ErpFormPanel
      eyebrow="Nuevo registro"
      title="Nueva factura"
      submitLabel="Guardar"
      pending={createDraft.isPending}
      error={createDraft.error?.message}
      onSubmit={submit}
      onCancel={onCancel}
    >
      <label>
        Cliente
        <select value={customerId} onChange={(event) => setCustomerId(event.target.value)} required>
          {customers.map((customer) => (
            <option key={customer.id} value={customer.id}>{customer.name}</option>
          ))}
        </select>
      </label>
      <div className="field-row">
        <label>
          Establecimiento
          <select
            value={establishmentId}
            onChange={(event) => {
              setEstablishmentId(event.target.value)
              setEmissionPointId('')
            }}
            required
          >
            {establishments.map((establishment) => (
              <option key={establishment.id} value={establishment.id}>{establishment.code}</option>
            ))}
          </select>
        </label>
        <label>
          Punto de emisión
          <select value={emissionPointId} onChange={(event) => setEmissionPointId(event.target.value)} required>
            <option value="" disabled>Seleccionar…</option>
            {availableEmissionPoints.map((point) => (
              <option key={point.id} value={point.id}>{point.code}</option>
            ))}
          </select>
        </label>
      </div>
      <label>
        Fecha de emisión
        <input type="date" value={issueDate} onChange={(event) => setIssueDate(event.target.value)} required />
      </label>
      <fieldset className="invoice-lines">
        <legend>Líneas</legend>
        {lines.map((line, index) => (
          <div className="invoice-line-row" key={line.key}>
            <label>
              {`Producto ${index + 1}`}
              <select
                value={line.productId}
                onChange={(event) => onProductChange(line.key, event.target.value)}
                required
              >
                <option value="" disabled>Seleccionar…</option>
                {products.map((product) => (
                  <option key={product.id} value={product.id}>{product.name}</option>
                ))}
              </select>
            </label>
            <div className="field-row">
              <label>
                Cantidad
                <input
                  type="number"
                  min="0.000001"
                  step="0.000001"
                  value={line.quantity}
                  onChange={(event) => updateLine(line.key, { quantity: event.target.value })}
                  required
                />
              </label>
              <label>
                Precio unitario
                <input
                  type="number"
                  min="0"
                  step="0.000001"
                  value={line.unitPrice}
                  onChange={(event) => updateLine(line.key, { unitPrice: event.target.value })}
                  required
                />
              </label>
            </div>
            <label>
              Descuento
              <input
                type="number"
                min="0"
                step="0.01"
                value={line.discount}
                onChange={(event) => updateLine(line.key, { discount: event.target.value })}
              />
            </label>
            {lines.length > 1 ? (
              <ErpButton
                variant="ghost"
                aria-label={`Quitar línea ${index + 1}`}
                onClick={() => setLines((current) => current.filter((item) => item.key !== line.key))}
              >
                Quitar línea
              </ErpButton>
            ) : null}
          </div>
        ))}
        <ErpButton variant="secondary" onClick={() => setLines((current) => [...current, emptyDraftLine()])}>
          Agregar línea
        </ErpButton>
      </fieldset>
      <p className="fine-print">Los totales e impuestos los calcula el servidor al guardar el borrador.</p>
    </ErpFormPanel>
  )
}

function CreditNoteForm({
  token,
  invoice,
  onCreated,
  onCancel,
}: {
  token: string
  invoice: SalesDocument
  onCreated: () => void
  onCancel: () => void
}) {
  const queryClient = useQueryClient()
  const [reason, setReason] = useState('')
  const [amounts, setAmounts] = useState<Record<string, string>>(() =>
    Object.fromEntries(invoice.lines.map((line) => [line.id, line.unitPrice])),
  )

  const createCreditNote = useMutation({
    mutationFn: () =>
      apiRequest<Operation>(token, '/credit-notes', {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey('web-credit-note') },
        body: JSON.stringify({
          invoiceId: invoice.id,
          reason,
          lines: invoice.lines.map((line) => ({
            productId: line.productId,
            description: line.description,
            quantity: line.quantity,
            unitPrice: amounts[line.id] ?? line.unitPrice,
            discount: '0.00',
            taxCode: line.taxCode,
          })),
        }),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['invoices'] })
      onCreated()
    },
  })

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    createCreditNote.mutate()
  }

  return (
    <ErpFormPanel
      eyebrow="Compensación"
      title="Nota de crédito"
      submitLabel="Guardar"
      pending={createCreditNote.isPending}
      error={createCreditNote.error?.message}
      onSubmit={submit}
      onCancel={onCancel}
    >
      <p className="fine-print">Factura {invoice.sequential} · Total acreditable ${invoice.total}</p>
      <label>
        Motivo
        <input value={reason} onChange={(event) => setReason(event.target.value)} minLength={3} required />
      </label>
      <fieldset className="invoice-lines">
        <legend>Líneas precargadas</legend>
        {invoice.lines.map((line) => (
          <div className="invoice-line-row" key={line.id}>
            <label>
              {line.description}
              <input
                type="number"
                min="0"
                step="0.000001"
                value={amounts[line.id] ?? line.unitPrice}
                onChange={(event) =>
                  setAmounts((current) => ({ ...current, [line.id]: event.target.value }))
                }
                aria-label={`Monto editable para ${line.description}`}
                required
              />
            </label>
          </div>
        ))}
      </fieldset>
    </ErpFormPanel>
  )
}

function InvoiceDetail({
  token,
  invoiceId,
  onClose,
  onOpenCreditNote,
}: {
  token: string
  invoiceId: string
  onClose: () => void
  onOpenCreditNote: (invoice: SalesDocument) => void
}) {
  const queryClient = useQueryClient()
  const invoiceQuery = useQuery({
    queryKey: ['invoices', invoiceId],
    queryFn: () => apiRequest<SalesDocument>(token, `/invoices/${invoiceId}`),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'RECEIVED' || status === 'PENDING_AUTHORIZATION' || status === 'SIGNED'
        ? 4000
        : false
    },
  })
  const artifactsQuery = useQuery({
    queryKey: ['invoices', invoiceId, 'artifacts'],
    queryFn: () => apiRequest<DocumentArtifact[]>(token, `/invoices/${invoiceId}/artifacts`),
    enabled: Boolean(invoiceQuery.data),
  })

  const issueInvoice = useMutation({
    mutationFn: () =>
      apiRequest<Operation>(token, `/invoices/${invoiceId}/issue`, {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey('web-issue') },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['invoices'] })
      void invoiceQuery.refetch()
    },
  })

  async function downloadArtifact(artifactId: string) {
    const download = await apiRequest<ArtifactDownload>(
      token,
      `/invoices/${invoiceId}/artifacts/${artifactId}/download`,
    )
    window.open(download.downloadUrl, '_blank', 'noopener,noreferrer')
  }

  if (invoiceQuery.isPending) {
    return (
      <aside className="form-panel erp-form-panel" aria-busy="true">
        <p>Cargando factura…</p>
      </aside>
    )
  }

  if (invoiceQuery.error || !invoiceQuery.data) {
    return (
      <aside className="form-panel erp-form-panel">
        <p className="form-error" role="alert">
          {invoiceQuery.error?.message ?? 'No se pudo cargar la factura'}
        </p>
        <ErpButton variant="secondary" onClick={onClose}>Cancelar</ErpButton>
      </aside>
    )
  }

  const invoice = invoiceQuery.data
  const transmission = invoice.sriTransmission
  const canIssue = invoice.status === 'DRAFT'
  const canCreditNote = invoice.type === 'INVOICE' && invoice.status === 'AUTHORIZED'

  return (
    <aside className="form-panel erp-form-panel invoice-detail" aria-labelledby="invoice-detail-title">
      <p className="section-number">Detalle</p>
      <h2 id="invoice-detail-title">Factura {invoice.sequential}</h2>
      <InvoiceStatusBadge status={invoice.status} />
      <dl className="invoice-summary">
        <div><dt>Fecha</dt><dd>{invoice.issueDate}</dd></div>
        <div><dt>Subtotal</dt><dd>${invoice.subtotal}</dd></div>
        <div><dt>Impuesto</dt><dd>${invoice.tax}</dd></div>
        <div><dt>Total</dt><dd>${invoice.total}</dd></div>
        {invoice.accessKey ? <div><dt>Clave de acceso</dt><dd>{invoice.accessKey}</dd></div> : null}
      </dl>

      <section aria-labelledby="sri-status-title">
        <p className="section-number" id="sri-status-title">Estado SRI</p>
        {transmission ? (
          <dl className="invoice-summary">
            <div><dt>Estado</dt><dd>{transmission.status}</dd></div>
            {transmission.message ? <div><dt>Mensaje</dt><dd>{transmission.message}</dd></div> : null}
            {transmission.authorizationNumber ? (
              <div><dt>Número de autorización</dt><dd>{transmission.authorizationNumber}</dd></div>
            ) : null}
          </dl>
        ) : (
          <p className="fine-print">Sin intentos de transmisión todavía.</p>
        )}
      </section>

      {issueInvoice.error ? (
        <p className="form-error" role="alert">{issueInvoice.error.message}</p>
      ) : null}

      <section aria-labelledby="invoice-artifacts-title">
        <p className="section-number" id="invoice-artifacts-title">Artefactos</p>
        {artifactsQuery.data && artifactsQuery.data.length > 0 ? (
          <ul className="establishment-list">
            {artifactsQuery.data.map((artifact) => (
              <li key={artifact.id}>
                <span>{artifact.artifactType === 'xml-signed' ? 'XML' : 'RIDE'}</span>
                <div>
                  <strong>Versión {artifact.version}</strong>
                  <ErpButton variant="ghost" onClick={() => void downloadArtifact(artifact.id)}>
                    Descargar
                  </ErpButton>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="fine-print">Sin artefactos generados todavía.</p>
        )}
      </section>

      <div className="erp-form-actions">
        <ErpButton variant="secondary" onClick={onClose}>Cancelar</ErpButton>
        {canCreditNote ? (
          <ErpButton variant="secondary" onClick={() => onOpenCreditNote(invoice)}>
            Nota de crédito
          </ErpButton>
        ) : null}
        <ErpButton
          variant="primary"
          disabled={!canIssue || issueInvoice.isPending}
          onClick={() => issueInvoice.mutate()}
        >
          {issueInvoice.isPending ? 'Emitiendo…' : 'Emitir'}
        </ErpButton>
      </div>
    </aside>
  )
}

function InvoicesPage({
  token,
  customers,
  products,
  taxes,
  establishments,
  emissionPoints,
}: {
  token: string
  customers: Party[]
  products: Product[]
  taxes: TaxCategory[]
  establishments: Establishment[]
  emissionPoints: EmissionPoint[]
}) {
  const [panel, setPanel] = useState<InvoicePanel | undefined>(undefined)
  const lastTriggerRef = useRef<HTMLElement | null>(null)
  const invoicesQuery = useQuery({
    queryKey: ['invoices'],
    queryFn: () => apiRequest<SalesDocument[]>(token, '/invoices'),
  })
  const invoices = invoicesQuery.data ?? []
  const partiesById = new Map(customers.map((party) => [party.id, party]))

  function openPanel(next: InvoicePanel, trigger?: HTMLElement) {
    lastTriggerRef.current = trigger ?? null
    setPanel(next)
  }

  function closePanel() {
    setPanel(undefined)
    lastTriggerRef.current?.focus()
  }

  return (
    <>
      <ErpPageHeader
        eyebrow="Facturación electrónica"
        title="Facturas"
        subtitle="Emisión SRI, seguimiento de autorización y notas de crédito."
        actions={
          <ErpButton
            variant="primary"
            onClick={(event) => openPanel({ view: 'new' }, event.currentTarget)}
          >
            Nueva factura
          </ErpButton>
        }
      />
      <section className={`split-layout ${panel === undefined ? 'erp-list-only' : ''}`}>
        <ErpPanel title="Documentos" count={invoices.length}>
          <div className="table-wrap">
            <table className="erp-responsive-table">
              <thead>
                <tr>
                  <th>Número</th>
                  <th>Cliente</th>
                  <th>Fecha</th>
                  <th>Estado</th>
                  <th>Total</th>
                  <th>Acciones</th>
                </tr>
              </thead>
              <tbody>
                {invoices.map((invoice) => (
                  <tr key={invoice.id}>
                    <td><strong>{invoice.sequential}</strong></td>
                    <td>{partiesById.get(invoice.partyId)?.name ?? '—'}</td>
                    <td>{invoice.issueDate}</td>
                    <td><InvoiceStatusBadge status={invoice.status} /></td>
                    <td>${invoice.total}</td>
                    <td>
                      <ErpActionCell>
                        <ErpButton
                          variant="ghost"
                          aria-label={`Ver factura ${invoice.sequential}`}
                          onClick={(event) =>
                            openPanel({ view: 'detail', id: invoice.id }, event.currentTarget)
                          }
                        >
                          Ver
                        </ErpButton>
                      </ErpActionCell>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {invoices.length === 0 ? (
              <ErpEmptyState
                title="No hay facturas"
                description="Crea el primer borrador de factura para comenzar."
                action={
                  <ErpButton
                    variant="primary"
                    onClick={(event) => openPanel({ view: 'new' }, event.currentTarget)}
                  >
                    Nueva factura
                  </ErpButton>
                }
              />
            ) : null}
          </div>
        </ErpPanel>
        {panel?.view === 'new' ? (
          <NewInvoiceForm
            token={token}
            customers={customers}
            products={products}
            taxes={taxes}
            establishments={establishments}
            emissionPoints={emissionPoints}
            onCreated={(invoiceId) => setPanel({ view: 'detail', id: invoiceId })}
            onCancel={closePanel}
          />
        ) : null}
        {panel?.view === 'detail' ? (
          <InvoiceDetail
            key={panel.id}
            token={token}
            invoiceId={panel.id}
            onClose={closePanel}
            onOpenCreditNote={(invoice) => setPanel({ view: 'credit-note', invoice })}
          />
        ) : null}
        {panel?.view === 'credit-note' ? (
          <CreditNoteForm
            token={token}
            invoice={panel.invoice}
            onCreated={() => setPanel({ view: 'detail', id: panel.invoice.id })}
            onCancel={() => setPanel({ view: 'detail', id: panel.invoice.id })}
          />
        ) : null}
      </section>
    </>
  )
}

const receivableStatusLabels: Record<AccountItemStatus, string> = {
  OPEN: 'ABIERTA',
  PARTIAL: 'PARCIAL',
  OVERDUE: 'VENCIDA',
  SETTLED: 'SALDADA',
  VOIDED: 'ANULADA',
}

const receivableStatusTone: Record<AccountItemStatus, 'neutral' | 'success' | 'warning' | 'danger'> = {
  OPEN: 'neutral',
  PARTIAL: 'warning',
  OVERDUE: 'danger',
  SETTLED: 'success',
  VOIDED: 'danger',
}

function ReceivableStatusBadge({ status }: { status: AccountItemStatus }) {
  return <ErpStatusBadge tone={receivableStatusTone[status]}>{receivableStatusLabels[status]}</ErpStatusBadge>
}

type AgingBucket = 'AL_DIA' | '1-15' | '16-30' | '31-60' | '61-90' | '90+'

const agingLabels: Record<AgingBucket, string> = {
  AL_DIA: 'Al día',
  '1-15': '1 a 15 días',
  '16-30': '16 a 30 días',
  '31-60': '31 a 60 días',
  '61-90': '61 a 90 días',
  '90+': 'Más de 90 días',
}

function agingBucket(dueDate: string | null | undefined): AgingBucket | null {
  if (!dueDate) return null
  const daysOverdue = Math.floor((Date.now() - new Date(`${dueDate}T00:00:00`).getTime()) / 86_400_000)
  if (daysOverdue <= 0) return 'AL_DIA'
  if (daysOverdue <= 15) return '1-15'
  if (daysOverdue <= 30) return '16-30'
  if (daysOverdue <= 60) return '31-60'
  if (daysOverdue <= 90) return '61-90'
  return '90+'
}

function AgingChip({ dueDate }: { dueDate: string | null | undefined }) {
  const bucket = agingBucket(dueDate)
  if (!bucket) return <span className="fine-print">Sin vencimiento</span>
  return (
    <ErpStatusBadge tone={bucket === 'AL_DIA' ? 'success' : bucket === '90+' || bucket === '61-90' ? 'danger' : 'warning'}>
      {agingLabels[bucket]}
    </ErpStatusBadge>
  )
}

type ReceivablePanel = { view: 'payment'; receivable: AccountItem } | { view: 'reminder'; receivable: AccountItem }

function emptyRetention(): RetentionInput & { key: string } {
  return { key: crypto.randomUUID(), kind: 'RETENTION_IVA', amount: '0.00', reason: '', documentReference: '' }
}

function emptyDiscount(): DiscountInput & { key: string } {
  return { key: crypto.randomUUID(), amount: '0.00', reason: '' }
}

function RegisterPaymentForm({
  token,
  receivable,
  onSaved,
  onCancel,
}: {
  token: string
  receivable: AccountItem
  onSaved: (updated: AccountItem) => void
  onCancel: () => void
}) {
  const [cashAmount, setCashAmount] = useState('0.00')
  const [paymentDate, setPaymentDate] = useState(() => new Date().toISOString().slice(0, 10))
  const [method, setMethod] = useState<'' | PaymentInput['method']>('')
  const [reference, setReference] = useState('')
  const [retentions, setRetentions] = useState<Array<RetentionInput & { key: string }>>([])
  const [discounts, setDiscounts] = useState<Array<DiscountInput & { key: string }>>([])

  const registerPayment = useMutation({
    mutationFn: () =>
      apiRequest<AccountItem>(token, `/receivables/${receivable.id}/payments`, {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey('web-receivable-payment') },
        body: JSON.stringify({
          cashAmount,
          paymentDate,
          method: method || null,
          reference: reference || null,
          retentions: retentions.map(({ key: _key, ...retention }) => retention),
          discounts: discounts.map(({ key: _key, ...discount }) => discount),
        } satisfies PaymentInput),
      }),
    onSuccess: (updated) => onSaved(updated),
  })

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    registerPayment.mutate()
  }

  return (
    <ErpFormPanel
      eyebrow="Cobro"
      title="Registrar cobro"
      submitLabel="Guardar"
      pending={registerPayment.isPending}
      error={registerPayment.error?.message}
      onSubmit={submit}
      onCancel={onCancel}
    >
      <p className="fine-print">Saldo actual ${receivable.openAmount}. El saldo final lo calcula el servidor.</p>
      <div className="field-row">
        <label>
          Monto en efectivo
          <input
            type="number"
            min="0"
            step="0.01"
            value={cashAmount}
            onChange={(event) => setCashAmount(event.target.value)}
            required
          />
        </label>
        <label>
          Fecha de cobro
          <input
            type="date"
            value={paymentDate}
            onChange={(event) => setPaymentDate(event.target.value)}
            required
          />
        </label>
      </div>
      <div className="field-row">
        <label>
          Método
          <select value={method ?? ''} onChange={(event) => setMethod(event.target.value as PaymentInput['method'])}>
            <option value="">Sin especificar</option>
            <option value="TRANSFER">Transferencia</option>
            <option value="CHECK">Cheque</option>
            <option value="CASH">Efectivo</option>
            <option value="CARD">Tarjeta</option>
            <option value="OTHER">Otro</option>
          </select>
        </label>
        <label>
          Referencia
          <input value={reference} onChange={(event) => setReference(event.target.value)} />
        </label>
      </div>

      <fieldset className="invoice-lines">
        <legend>Retenciones</legend>
        {retentions.map((retention, index) => (
          <div className="invoice-line-row" key={retention.key}>
            <label>
              {`Tipo de retención ${index + 1}`}
              <select
                value={retention.kind}
                onChange={(event) =>
                  setRetentions((current) =>
                    current.map((item) =>
                      item.key === retention.key
                        ? { ...item, kind: event.target.value as RetentionInput['kind'] }
                        : item,
                    ),
                  )
                }
              >
                <option value="RETENTION_IVA">Retención IVA</option>
                <option value="RETENTION_RENTA">Retención Renta</option>
                <option value="OTHER">Otra</option>
              </select>
            </label>
            <div className="field-row">
              <label>
                Monto
                <input
                  type="number"
                  min="0.01"
                  step="0.01"
                  value={retention.amount}
                  onChange={(event) =>
                    setRetentions((current) =>
                      current.map((item) =>
                        item.key === retention.key ? { ...item, amount: event.target.value } : item,
                      ),
                    )
                  }
                  required
                />
              </label>
              <label>
                Motivo
                <input
                  value={retention.reason}
                  minLength={3}
                  onChange={(event) =>
                    setRetentions((current) =>
                      current.map((item) =>
                        item.key === retention.key ? { ...item, reason: event.target.value } : item,
                      ),
                    )
                  }
                  required
                />
              </label>
            </div>
            <ErpButton
              variant="ghost"
              aria-label={`Quitar retención ${index + 1}`}
              onClick={() => setRetentions((current) => current.filter((item) => item.key !== retention.key))}
            >
              Quitar retención
            </ErpButton>
          </div>
        ))}
        <ErpButton variant="secondary" onClick={() => setRetentions((current) => [...current, emptyRetention()])}>
          Agregar retención
        </ErpButton>
      </fieldset>

      <fieldset className="invoice-lines">
        <legend>Descuentos</legend>
        {discounts.map((discount, index) => (
          <div className="invoice-line-row" key={discount.key}>
            <div className="field-row">
              <label>
                {`Monto de descuento ${index + 1}`}
                <input
                  type="number"
                  min="0.01"
                  step="0.01"
                  value={discount.amount}
                  onChange={(event) =>
                    setDiscounts((current) =>
                      current.map((item) =>
                        item.key === discount.key ? { ...item, amount: event.target.value } : item,
                      ),
                    )
                  }
                  required
                />
              </label>
              <label>
                Motivo
                <input
                  value={discount.reason}
                  minLength={3}
                  onChange={(event) =>
                    setDiscounts((current) =>
                      current.map((item) =>
                        item.key === discount.key ? { ...item, reason: event.target.value } : item,
                      ),
                    )
                  }
                  required
                />
              </label>
            </div>
            <ErpButton
              variant="ghost"
              aria-label={`Quitar descuento ${index + 1}`}
              onClick={() => setDiscounts((current) => current.filter((item) => item.key !== discount.key))}
            >
              Quitar descuento
            </ErpButton>
          </div>
        ))}
        <ErpButton variant="secondary" onClick={() => setDiscounts((current) => [...current, emptyDiscount()])}>
          Agregar descuento
        </ErpButton>
      </fieldset>
    </ErpFormPanel>
  )
}

function SendReminderForm({
  token,
  receivable,
  onSent,
  onCancel,
}: {
  token: string
  receivable: AccountItem
  onSent: () => void
  onCancel: () => void
}) {
  const [channel, setChannel] = useState<ReminderInput['channel']>('EMAIL')
  const [templateId, setTemplateId] = useState('')

  const sendReminder = useMutation({
    mutationFn: () =>
      apiRequest<Operation>(token, `/receivables/${receivable.id}/reminders`, {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey('web-receivable-reminder') },
        body: JSON.stringify({ channel, templateId } satisfies ReminderInput),
      }),
    onSuccess: () => onSent(),
  })

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    sendReminder.mutate()
  }

  return (
    <ErpFormPanel
      eyebrow="Recordatorio"
      title="Enviar recordatorio"
      submitLabel="Enviar"
      pendingLabel="Enviando…"
      pending={sendReminder.isPending}
      error={sendReminder.error?.message}
      onSubmit={submit}
      onCancel={onCancel}
    >
      <p className="fine-print">Saldo pendiente ${receivable.openAmount}.</p>
      <label>
        Canal
        <select value={channel} onChange={(event) => setChannel(event.target.value as ReminderInput['channel'])} required>
          <option value="EMAIL">Correo electrónico</option>
          <option value="WHATSAPP">WhatsApp</option>
        </select>
      </label>
      <label>
        Plantilla
        <input
          value={templateId}
          onChange={(event) => setTemplateId(event.target.value)}
          placeholder="ID de plantilla"
          required
        />
      </label>
    </ErpFormPanel>
  )
}

function ReceivablesPage({
  token,
  parties,
}: {
  token: string
  parties: Party[]
}) {
  const queryClient = useQueryClient()
  const [statusFilter, setStatusFilter] = useState<'' | AccountItemStatus>('')
  const [panel, setPanel] = useState<ReceivablePanel | undefined>(undefined)
  const lastTriggerRef = useRef<HTMLElement | null>(null)
  const partiesById = new Map(parties.map((party) => [party.id, party]))

  const receivablesQuery = useQuery({
    queryKey: ['receivables', statusFilter],
    queryFn: () =>
      apiRequest<AccountItem[]>(
        token,
        statusFilter ? `/receivables?status=${statusFilter}` : '/receivables',
      ),
  })
  const receivables = receivablesQuery.data ?? []

  function openPanel(next: ReceivablePanel, trigger?: HTMLElement) {
    lastTriggerRef.current = trigger ?? null
    setPanel(next)
  }

  function closePanel() {
    setPanel(undefined)
    lastTriggerRef.current?.focus()
  }

  function applyUpdatedReceivable(updated: AccountItem) {
    queryClient.setQueryData<AccountItem[]>(['receivables', statusFilter], (current) =>
      current?.map((item) => (item.id === updated.id ? updated : item)) ?? current,
    )
    void queryClient.invalidateQueries({ queryKey: ['receivables'] })
    setPanel({ view: 'payment', receivable: updated })
  }

  return (
    <>
      <ErpPageHeader
        eyebrow="Cuentas por cobrar"
        title="Cartera"
        subtitle="Cartera trazable a la factura de origen, con saldo y aging calculados por el servidor."
      />
      <ErpToolbar>
        <label className="search-field">
          <span>Filtrar por estado</span>
          <select
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value as '' | AccountItemStatus)}
          >
            <option value="">Todos los estados</option>
            <option value="OPEN">Abierta</option>
            <option value="PARTIAL">Parcial</option>
            <option value="OVERDUE">Vencida</option>
            <option value="SETTLED">Saldada</option>
            <option value="VOIDED">Anulada</option>
          </select>
        </label>
      </ErpToolbar>
      <section className={`split-layout ${panel === undefined ? 'erp-list-only' : ''}`}>
        <ErpPanel title="Cuentas por cobrar" count={receivables.length}>
          <div className="table-wrap">
            <table className="erp-responsive-table">
              <thead>
                <tr>
                  <th>Cliente</th>
                  <th>Monto original</th>
                  <th>Saldo</th>
                  <th>Estado</th>
                  <th>Aging</th>
                  <th>Acciones</th>
                </tr>
              </thead>
              <tbody>
                {receivables.map((receivable) => (
                  <tr key={receivable.id}>
                    <td><strong>{partiesById.get(receivable.partyId)?.name ?? receivable.partyId}</strong></td>
                    <td>${receivable.originalAmount}</td>
                    <td>${receivable.openAmount}</td>
                    <td><ReceivableStatusBadge status={receivable.status} /></td>
                    <td><AgingChip dueDate={receivable.dueDate} /></td>
                    <td>
                      <ErpActionCell>
                        <ErpButton
                          variant="ghost"
                          aria-label={`Registrar cobro para ${partiesById.get(receivable.partyId)?.name ?? receivable.partyId}`}
                          onClick={(event) => openPanel({ view: 'payment', receivable }, event.currentTarget)}
                          disabled={receivable.status === 'SETTLED' || receivable.status === 'VOIDED'}
                        >
                          Registrar cobro
                        </ErpButton>
                        <ErpButton
                          variant="ghost"
                          aria-label={`Enviar recordatorio para ${partiesById.get(receivable.partyId)?.name ?? receivable.partyId}`}
                          onClick={(event) => openPanel({ view: 'reminder', receivable }, event.currentTarget)}
                          disabled={receivable.status === 'SETTLED' || receivable.status === 'VOIDED'}
                        >
                          Recordatorio
                        </ErpButton>
                      </ErpActionCell>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {receivables.length === 0 ? (
              <ErpEmptyState
                title="No hay cuentas por cobrar"
                description="La cartera se genera automáticamente al autorizar una factura."
              />
            ) : null}
          </div>
        </ErpPanel>
        {panel?.view === 'payment' ? (
          <RegisterPaymentForm
            key={panel.receivable.id}
            token={token}
            receivable={panel.receivable}
            onSaved={applyUpdatedReceivable}
            onCancel={closePanel}
          />
        ) : null}
        {panel?.view === 'reminder' ? (
          <SendReminderForm
            key={panel.receivable.id}
            token={token}
            receivable={panel.receivable}
            onSent={closePanel}
            onCancel={closePanel}
          />
        ) : null}
      </section>
    </>
  )
}

function OrganizationPage({
  context,
  establishments,
}: {
  context: TenantContext
  establishments: Establishment[]
}) {
  return (
    <>
      <ErpPageHeader
        eyebrow="Configuración fiscal"
        title="Empresa"
        subtitle="Datos del contribuyente y estructura de emisión."
        meta={<ErpStatusBadge tone="success">Tenant activo</ErpStatusBadge>}
      />
      <section className="company-grid">
        <article className="company-identity">
          <p className="section-number">Contribuyente</p>
          <h2>{context.name}</h2>
          <dl><div><dt>RUC</dt><dd>{context.ruc}</dd></div><div><dt>Roles</dt><dd>{context.roles.join(', ')}</dd></div></dl>
        </article>
        <ErpPanel title="Establecimientos" count={establishments.length}>
          <ul className="establishment-list">
            {establishments.map((item) => <li key={item.id}><span>{item.code}</span><div><strong>{item.name}</strong><small>{item.address}</small></div></li>)}
          </ul>
        </ErpPanel>
      </section>
    </>
  )
}

function Workspace() {
  const auth = useAuth()
  const [section, setSection] = useState<Section>('overview')
  const tokenQuery = useQueries({
    queries: [{
      queryKey: ['auth-token'],
      queryFn: auth.getToken,
      staleTime: 20_000,
    }],
  })[0]
  const token = tokenQuery.data ?? ''

  const results = useQueries({
    queries: [
      { queryKey: ['context'], queryFn: () => apiRequest<TenantContext>(token, '/context'), enabled: Boolean(token) },
      { queryKey: ['parties'], queryFn: () => apiRequest<Party[]>(token, '/parties'), enabled: Boolean(token) },
      { queryKey: ['products'], queryFn: () => apiRequest<Product[]>(token, '/products'), enabled: Boolean(token) },
      { queryKey: ['taxes'], queryFn: () => apiRequest<TaxCategory[]>(token, '/tax-categories'), enabled: Boolean(token) },
      { queryKey: ['establishments'], queryFn: () => apiRequest<Establishment[]>(token, '/establishments'), enabled: Boolean(token) },
      { queryKey: ['emission-points'], queryFn: () => apiRequest<EmissionPoint[]>(token, '/emission-points'), enabled: Boolean(token) },
    ],
  })
  const [contextQuery, partiesQuery, productsQuery, taxesQuery, establishmentsQuery, emissionPointsQuery] = results
  const loading = tokenQuery.isPending || results.some((result) => result.isPending)
  const error = tokenQuery.error ?? results.find((result) => result.error)?.error
  if (loading) return <LoadingScreen />

  if (error || !contextQuery.data) {
    return <main className="loading-screen"><h1>No pudimos abrir el espacio</h1><p role="alert">{error?.message ?? 'Contexto no disponible'}</p><button onClick={() => void auth.logout()}>Cerrar sesión</button></main>
  }

  const parties = partiesQuery.data ?? []
  const products = productsQuery.data ?? []
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Saltar al contenido</a>
      <aside className="sidebar">
        <div className="brand-lockup"><span className="brand-mark" aria-hidden="true">IA</span><div><strong>IAERP</strong><small>Finanzas aumentadas</small></div></div>
        <nav aria-label="Navegación principal">
          {sections.map((item) => (
            <button
              key={item.id}
              className={section === item.id ? 'active' : ''}
              aria-current={section === item.id ? 'page' : undefined}
              onClick={() => startTransition(() => setSection(item.id))}
            >
              <span>{item.eyebrow}</span>{item.label}
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <span className="avatar" aria-hidden="true">{auth.displayName.slice(0, 2).toUpperCase()}</span>
          <div><strong>{auth.displayName}</strong><button onClick={() => void auth.logout()}>Cerrar sesión</button></div>
        </div>
      </aside>
      <main id="main-content" tabIndex={-1}>
        {section === 'overview' ? <Overview context={contextQuery.data} parties={parties} products={products} /> : null}
        {section === 'parties' ? <PartiesPage parties={parties} token={token} /> : null}
        {section === 'products' ? <ProductsPage products={products} taxes={taxesQuery.data ?? []} token={token} /> : null}
        {section === 'invoices' ? (
          <InvoicesPage
            token={token}
            customers={parties.filter((party) => party.roles.includes('CUSTOMER'))}
            products={products}
            taxes={taxesQuery.data ?? []}
            establishments={establishmentsQuery.data ?? []}
            emissionPoints={emissionPointsQuery.data ?? []}
          />
        ) : null}
        {section === 'organization' ? <OrganizationPage context={contextQuery.data} establishments={establishmentsQuery.data ?? []} /> : null}
        {section === 'receivables' ? <ReceivablesPage token={token} parties={parties} /> : null}
        {section === 'crm' ? <LeadsPage /> : null}
      </main>
    </div>
  )
}

export default function App() {
  const auth = useAuth()
  if (auth.loading) return <LoadingScreen />
  if (auth.authenticated) return <Workspace />
  return auth.mode === 'dev' ? <DevLogin /> : <OidcLogin />
}
