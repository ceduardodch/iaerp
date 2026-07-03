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
      <header className="page-heading">
        <div>
          <p className="kicker">Pulso operativo</p>
          <h1>{context.name}</h1>
        </div>
        <p className="date-chip">RUC {context.ruc}</p>
      </header>
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
  const deferredQuery = useDeferredValue(query.toLocaleLowerCase())
  const filtered = parties.filter((party) =>
    `${party.name} ${party.identificationNumber}`.toLocaleLowerCase().includes(deferredQuery),
  )
  const createParty = useMutation({
    mutationFn: async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault()
      const form = event.currentTarget
      const data = new FormData(form)
      const result = await apiRequest<Party>(token, '/parties', {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey('web-party') },
        body: JSON.stringify({
          name: data.get('name'),
          identificationType: data.get('identificationType'),
          identificationNumber: data.get('identificationNumber'),
          roles: [data.get('role')],
          email: data.get('email') || null,
        }),
      })
      form.reset()
      return result
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['parties'] }),
  })

  return (
    <>
      <header className="page-heading">
        <div><p className="kicker">Datos maestros</p><h1>Contactos</h1></div>
        <label className="search-field">
          <span>Buscar contacto</span>
          <input value={query} onChange={(event) => setQuery(event.target.value)} />
        </label>
      </header>
      <section className="split-layout">
        <div className="data-panel">
          <div className="panel-heading">
            <h2>Clientes y proveedores</h2>
            <span>{filtered.length} registros</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Nombre</th><th>Identificación</th><th>Rol</th></tr></thead>
              <tbody>
                {filtered.map((party) => (
                  <tr key={party.id}>
                    <td><strong>{party.name}</strong><small>{party.email ?? 'Sin correo'}</small></td>
                    <td>{party.identificationNumber}</td>
                    <td><span className="tag">{party.roles.join(' / ')}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <aside className="form-panel" aria-labelledby="new-party-title">
          <p className="section-number">Nuevo registro</p>
          <h2 id="new-party-title">Agregar contacto</h2>
          <form onSubmit={(event) => createParty.mutate(event)}>
            <label>Nombre o razón social<input name="name" required /></label>
            <div className="field-row">
              <label>Tipo<select name="identificationType"><option>RUC</option><option>CEDULA</option><option>PASSPORT</option></select></label>
              <label>Número<input name="identificationNumber" required /></label>
            </div>
            <label>Rol<select name="role"><option value="CUSTOMER">Cliente</option><option value="SUPPLIER">Proveedor</option></select></label>
            <label>Correo<input name="email" type="email" /></label>
            {createParty.error ? <p className="form-error" role="alert">{createParty.error.message}</p> : null}
            <button className="primary-button" disabled={createParty.isPending}>Guardar contacto</button>
          </form>
        </aside>
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
  const createProduct = useMutation({
    mutationFn: async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault()
      const form = event.currentTarget
      const data = new FormData(form)
      const result = await apiRequest<Product>(token, '/products', {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey('web-product') },
        body: JSON.stringify({
          name: data.get('name'),
          code: data.get('code') || null,
          unitPrice: data.get('unitPrice'),
          taxCategoryId: data.get('taxCategoryId'),
        }),
      })
      form.reset()
      return result
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['products'] }),
  })
  return (
    <>
      <header className="page-heading">
        <div><p className="kicker">Catálogo comercial</p><h1>Productos</h1></div>
        <p className="date-chip">{products.length} ítems activos</p>
      </header>
      <section className="split-layout">
        <div className="product-grid" aria-label="Productos">
          {products.map((product, index) => (
            <article className="product-card" key={product.id}>
              <span>{String(index + 1).padStart(2, '0')}</span>
              <h2>{product.name}</h2>
              <p>{product.code ?? 'Sin código interno'}</p>
              <strong>${Number(product.unitPrice).toFixed(2)}</strong>
            </article>
          ))}
          {products.length === 0 ? <p className="empty-state">El catálogo todavía está vacío.</p> : null}
        </div>
        <aside className="form-panel" aria-labelledby="new-product-title">
          <p className="section-number">Nuevo ítem</p>
          <h2 id="new-product-title">Agregar producto</h2>
          <form onSubmit={(event) => createProduct.mutate(event)}>
            <label>Nombre<input name="name" required /></label>
            <label>Código interno<input name="code" /></label>
            <label>Precio unitario<input name="unitPrice" type="number" min="0" step="0.000001" required /></label>
            <label>Categoría tributaria<select name="taxCategoryId" required>{taxes.map((tax) => <option key={tax.id} value={tax.id}>{tax.name} · {tax.rate}%</option>)}</select></label>
            {createProduct.error ? <p className="form-error" role="alert">{createProduct.error.message}</p> : null}
            <button className="primary-button" disabled={createProduct.isPending}>Guardar producto</button>
          </form>
        </aside>
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
      <header className="page-heading">
        <div><p className="kicker">Configuración fiscal</p><h1>Empresa</h1></div>
        <span className="status-dot">Tenant activo</span>
      </header>
      <section className="company-grid">
        <article className="company-identity">
          <p className="section-number">Contribuyente</p>
          <h2>{context.name}</h2>
          <dl><div><dt>RUC</dt><dd>{context.ruc}</dd></div><div><dt>Roles</dt><dd>{context.roles.join(', ')}</dd></div></dl>
        </article>
        <div className="data-panel">
          <div className="panel-heading"><h2>Establecimientos</h2><span>{establishments.length}</span></div>
          <ul className="establishment-list">
            {establishments.map((item) => <li key={item.id}><span>{item.code}</span><div><strong>{item.name}</strong><small>{item.address}</small></div></li>)}
          </ul>
        </div>
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
  return auth.authenticated ? <Workspace /> : <DevLogin />
}
