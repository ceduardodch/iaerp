import { useMutation, useQueries, useQueryClient } from '@tanstack/react-query'
import {
  startTransition,
  useDeferredValue,
  useState,
  type FormEvent,
} from 'react'

import {
  apiRequest,
  idempotencyKey,
  type Establishment,
  type Party,
  type Product,
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

type Section = 'overview' | 'parties' | 'products' | 'organization'

const sections: Array<{ id: Section; label: string; eyebrow: string }> = [
  { id: 'overview', label: 'Resumen', eyebrow: '01' },
  { id: 'parties', label: 'Contactos', eyebrow: '02' },
  { id: 'products', label: 'Productos', eyebrow: '03' },
  { id: 'organization', label: 'Empresa', eyebrow: '04' },
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
    ],
  })
  const [contextQuery, partiesQuery, productsQuery, taxesQuery, establishmentsQuery] = results
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
        {section === 'organization' ? <OrganizationPage context={contextQuery.data} establishments={establishmentsQuery.data ?? []} /> : null}
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
