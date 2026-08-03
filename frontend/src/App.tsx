import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarClock, DollarSign, History, Mail } from 'lucide-react'
import {
  lazy,
  startTransition,
  Suspense,
  useDeferredValue,
  useMemo,
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
  type BankStatementImport,
  type BillingProposal,
  type CollectionPolicy,
  type CollectionsBreakdown,
  type CommercialContract,
  type ContractArtifactDownload,
  type ContractEmailSync,
  type ContractVersion,
  type AwsConsumptionCut,
  type DiscountInput,
  type DocumentArtifact,
  type EmissionPoint,
  type EvolutionWhatsAppIntegration,
  type Establishment,
  type FiscalSettings,
  type InvoiceLineInput,
  type InvoiceEmailResult,
  type InvoiceEmailPreview,
  type InvoiceEmailTemplate,
  type InvoicePreview,
  type IntegrationStatus,
  type Lead,
  type Operation,
  type OrganizationProfile,
  type Party,
  type PaymentInput,
  type Product,
  type ReminderInput,
  type ReceivableDueDateUpdate,
  type ReceivableMovement,
  type RetentionInput,
  type RetentionBatch,
  type RetentionXmlPreview,
  type SalesDocument,
  type SalesDocumentStatus,
  type TaxCategory,
  type TaxCategoryInput,
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
import { ErpCombobox } from './components/erp/ErpCombobox'
import { ErpModal } from './components/erp/ErpModal'
// Code-splitting (Sprint 7): la sección CRM arrastra dependencias pesadas
// (@dnd-kit + framer-motion) y es la menos usada en el arranque; se carga
// bajo demanda para reducir el bundle inicial.
const LeadsPage = lazy(() =>
  import('./components/crm').then((module) => ({ default: module.LeadsPage })),
)
// La sección tributaria también se carga bajo demanda: solo la usa quien declara.
const TaxPage = lazy(() =>
  import('./components/tax').then((module) => ({ default: module.TaxPage })),
)
import { InvoiceSpreadsheet } from './components/InvoiceSpreadsheet'
import { Sidebar } from './components/Sidebar'
import { ErrorBoundary } from './components/ErrorBoundary'
import { SectionLoadingSkeleton } from './components/LoadingSkeleton'
import { useToast } from './components/Toast'

type Section = 'overview' | 'parties' | 'catalogs' | 'invoices' | 'receivables' | 'organization' | 'contracts' | 'crm' | 'tax'

const amountFormatter = new Intl.NumberFormat('es-EC', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

function formatAmount(value: string | number): string {
  const amount = Number(value)
  return Number.isFinite(amount) ? amountFormatter.format(amount) : '0,00'
}

function formatPercent(value: string | number): string {
  return `${formatAmount(value)} %`
}

function PdfPreviewModal({
  title,
  artifact,
  onClose,
}: {
  title: string
  artifact: Pick<ArtifactDownload, 'downloadUrl' | 'fileName'>
  onClose: () => void
}) {
  return (
    <ErpModal title={title} size="lg" onClose={onClose}>
      <iframe className="pdf-preview-frame" src={artifact.downloadUrl} title={artifact.fileName} />
      <div className="erp-form-actions pdf-preview-actions">
        <ErpButton variant="secondary" onClick={() => window.open(artifact.downloadUrl, '_blank', 'noopener,noreferrer')}>
          Abrir en otra pestaña
        </ErpButton>
        <ErpButton variant="primary" onClick={onClose}>Cerrar</ErpButton>
      </div>
    </ErpModal>
  )
}

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
  const { authError, loginOidc } = useAuth()
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
          Indica tu empresa antes de autenticarte. Tu sesión quedará ligada
          únicamente a esa organización.
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
              autoCapitalize="none"
              autoComplete="organization"
              spellCheck={false}
              required
            />
          </label>
          {authError || error ? (
            <p className="form-error" role="alert">{error || authError}</p>
          ) : null}
          <button className="primary-button" type="submit" disabled={submitting}>
            {submitting ? 'Redirigiendo…' : 'Continuar con Keycloak'}
          </button>
        </form>
        <p className="fine-print">
          Usa el alias que te entregó el administrador de IAERP.
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
  token,
}: {
  context: TenantContext
  token: string
}) {
  const [invoicesQuery, receivablesQuery, leadsQuery] = useQueries({
    queries: [
      { queryKey: ['invoices', 'overview'], queryFn: () => apiRequest<SalesDocument[]>(token, '/invoices') },
      { queryKey: ['receivables', 'overview'], queryFn: () => apiRequest<AccountItem[]>(token, '/receivables') },
      { queryKey: ['crm', 'leads', 'overview'], queryFn: () => apiRequest<Lead[]>(token, '/crm/leads') },
    ],
  })
  const invoices = invoicesQuery.data ?? []
  const receivables = receivablesQuery.data ?? []
  const leads = leadsQuery.data ?? []
  const today = todayInFiscalTimezone().slice(0, 7)
  const outstanding = receivables.reduce((sum, item) => sum + Number(item.openAmount), 0)
  const overdue = receivables.filter((item) => item.status === 'OVERDUE').reduce((sum, item) => sum + Number(item.openAmount), 0)
  const monthlyInvoices = invoices.filter((invoice) =>
    invoice.issueDate.startsWith(today) && invoice.type === 'INVOICE' && invoice.status === 'AUTHORIZED',
  ).length
  const openPipeline = leads.filter((lead) => !['WON', 'LOST'].includes(lead.status)).reduce((sum, lead) => sum + Number(lead.estimatedValue ?? 0), 0)
  return (
    <>
      <ErpPageHeader
        eyebrow="Pulso operativo"
        title={context.name}
        subtitle="El pulso de cobranza, emisión y oportunidades de tu empresa."
        meta={<span className="date-chip">RUC {context.ruc}</span>}
      />
      <section className="metric-grid" aria-label="Indicadores operativos">
        <article className="metric-card">
          <span className="metric-label">Por cobrar</span>
          <strong>${formatAmount(outstanding)}</strong>
          <p>{receivables.length} cuentas activas.</p>
        </article>
        <article className="metric-card">
          <span className="metric-label">Vencido</span>
          <strong className={overdue > 0 ? 'metric-danger' : ''}>${formatAmount(overdue)}</strong>
          <p>Saldo que requiere seguimiento.</p>
        </article>
        <article className="metric-card">
          <span className="metric-label">Facturas autorizadas del mes</span>
          <strong>{monthlyInvoices}</strong>
          <p>No incluye rechazos ni documentos no autorizados.</p>
        </article>
        <article className="metric-card">
          <span className="metric-label">Pipeline abierto</span>
          <strong className="metric-success">${formatAmount(openPipeline)}</strong>
          <p>{leads.filter((lead) => !['WON', 'LOST'].includes(lead.status)).length} oportunidades CRM activas.</p>
        </article>
      </section>
      <section className="readiness-panel">
        <div>
          <p className="section-number">Próximo hito</p>
          <h2>Preparación fiscal</h2>
        </div>
        <ol className="readiness-list">
          <li><span>✓</span> Verificar establecimiento y punto de emisión</li>
          <li><span>✓</span> Completar catálogo y contactos</li>
          <li><span>✓</span> Cargar certificado de firma de forma segura</li>
        </ol>
      </section>
    </>
  )
}

function PartiesPage({
  parties,
  token,
  onOpenContracts,
}: {
  parties: Party[]
  token: string
  onOpenContracts: (partyId: string) => void
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
      phone: FormDataEntryValue | null
      address: FormDataEntryValue | null
      paymentTermsDays: FormDataEntryValue | null
      expectedIvaWithholdingRate: FormDataEntryValue | null
      expectedIncomeWithholdingRate: FormDataEntryValue | null
      withholdingProfileValidFrom: FormDataEntryValue | null
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
          phone: data.phone || null,
          address: data.address || null,
          paymentTermsDays: data.paymentTermsDays === '' ? null : Number(data.paymentTermsDays),
          expectedIvaWithholdingRate: data.expectedIvaWithholdingRate === '' ? null : String(data.expectedIvaWithholdingRate),
          expectedIncomeWithholdingRate: data.expectedIncomeWithholdingRate === '' ? null : String(data.expectedIncomeWithholdingRate),
          withholdingProfileValidFrom: data.withholdingProfileValidFrom || null,
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
        phone: data.get('phone'),
        address: data.get('address'),
        paymentTermsDays: data.get('paymentTermsDays'),
        expectedIvaWithholdingRate: data.get('expectedIvaWithholdingRate'),
        expectedIncomeWithholdingRate: data.get('expectedIncomeWithholdingRate'),
        withholdingProfileValidFrom: data.get('withholdingProfileValidFrom'),
      },
    )
  }

  if (editor !== undefined) {
    return (
      <>
        <ErpPageHeader
          eyebrow={editor ? 'Edición de contacto' : 'Nuevo contacto'}
          title={editor ? editor.name : 'Nuevo contacto'}
          subtitle="Completa los datos tributarios y de contacto usados por facturación y cartera."
        />
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
            <label>Tipo<select name="identificationType" defaultValue={editor?.identificationType ?? 'RUC'}><option>RUC</option><option>CEDULA</option><option>PASSPORT</option><option>FINAL_CONSUMER</option></select></label>
            <label>Número<input name="identificationNumber" defaultValue={editor?.identificationNumber} required /></label>
          </div>
          <label>Rol<select name="role" defaultValue={editor?.roles[0] ?? 'CUSTOMER'}><option value="CUSTOMER">Cliente</option><option value="SUPPLIER">Proveedor</option></select></label>
          <div className="field-row">
            <label>Correo<input name="email" type="email" defaultValue={editor?.email ?? ''} /></label>
            <label>WhatsApp<input name="phone" type="tel" defaultValue={editor?.phone ?? ''} placeholder="+593991041297" pattern="\+5939[0-9]{8}" title="Usa el formato +593991041297" /></label>
          </div>
          <label>Dirección<textarea name="address" rows={3} defaultValue={editor?.address ?? ''} /></label>
          <label>Condición de pago predeterminada<select name="paymentTermsDays" defaultValue={editor?.paymentTermsDays ?? ''}><option value="">Usar valor de la empresa</option><option value="0">Contado</option><option value="15">15 días</option><option value="30">30 días</option><option value="45">45 días</option><option value="60">60 días</option><option value="90">90 días</option></select></label>
          <fieldset className="invoice-lines">
            <legend>Perfil esperado de retención</legend>
            <p className="fine-print">Solo ayuda a calcular el cobro esperado. Registra una retención únicamente con su comprobante.</p>
            <div className="field-row">
              <label>IVA %<input name="expectedIvaWithholdingRate" type="number" min="0" max="100" step="0.01" defaultValue={editor?.expectedIvaWithholdingRate ?? ''} /></label>
              <label>Renta %<input name="expectedIncomeWithholdingRate" type="number" min="0" max="100" step="0.01" defaultValue={editor?.expectedIncomeWithholdingRate ?? ''} /></label>
            </div>
            <label>Vigente desde<input name="withholdingProfileValidFrom" type="date" defaultValue={editor?.withholdingProfileValidFrom ?? ''} /></label>
          </fieldset>
        </ErpFormPanel>
      </>
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
      <section className="split-layout erp-list-only">
        <ErpPanel title="Clientes y proveedores" count={filtered.length}>
          <div className="table-wrap" tabIndex={0} aria-label="Listado de contactos">
            <table className="erp-responsive-table">
              <thead><tr><th>Nombre</th><th>Identificación</th><th>Contacto</th><th>Dirección</th><th>Rol</th><th>Acciones</th></tr></thead>
              <tbody>
                {filtered.map((party) => (
                  <tr key={party.id}>
                    <td><strong>{party.name}</strong><small>{party.email ?? 'Sin correo'}</small></td>
                    <td>{party.identificationNumber}</td>
                    <td>{party.phone ?? 'Sin teléfono'}</td>
                    <td>{party.address ?? 'Sin dirección'}</td>
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
                        {party.roles.includes('CUSTOMER') ? (
                          <ErpButton variant="ghost" onClick={() => onOpenContracts(party.id)}>
                            Contratos
                          </ErpButton>
                        ) : null}
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
      </section>
    </>
  )
}

function ContractsPage({
  parties,
  products,
  taxes,
  establishments,
  emissionPoints,
  token,
  initialPartyId,
}: {
  parties: Party[]
  products: Product[]
  taxes: TaxCategory[]
  establishments: Establishment[]
  emissionPoints: EmissionPoint[]
  token: string
  initialPartyId?: string
}) {
  const queryClient = useQueryClient()
  const customers = parties.filter((party) => party.roles.includes('CUSTOMER'))
  const [partyId, setPartyId] = useState(initialPartyId ?? '')
  const [selected, setSelected] = useState<CommercialContract | null>(null)
  const [creating, setCreating] = useState(false)
  const [newPartyId, setNewPartyId] = useState(initialPartyId ?? '')
  const [pdfPreview, setPdfPreview] = useState<ContractArtifactDownload | null>(null)
  const [syncResult, setSyncResult] = useState<{ versionId: string; result: ContractEmailSync } | null>(null)
  const wonLeadsQuery = useQuery({
    queryKey: ['crm', 'leads', 'WON'],
    queryFn: () => apiRequest<Lead[]>(token, '/crm/leads?status=WON'),
  })
  const contractsQuery = useQuery({
    queryKey: ['commercial', 'contracts', partyId],
    queryFn: () => apiRequest<CommercialContract[]>(token, `/commercial/contracts${partyId ? `?party_id=${partyId}` : ''}`),
  })
  const currentContract = contractsQuery.data?.find((contract) => contract.id === selected?.id) ?? selected
  const versionsQuery = useQuery({
    queryKey: ['commercial', 'contracts', selected?.id, 'versions'],
    queryFn: () => apiRequest<ContractVersion[]>(token, `/commercial/contracts/${selected?.id}/versions`),
    enabled: Boolean(selected),
  })
  const proposalsQuery = useQuery({
    queryKey: ['commercial', 'billing-proposals', selected?.id],
    queryFn: () => apiRequest<BillingProposal[]>(token, `/commercial/billing-proposals?contract_id=${selected?.id}`),
    enabled: Boolean(selected),
  })
  const awsCutsQuery = useQuery({
    queryKey: ['commercial', 'aws-cuts', currentContract?.partyId],
    queryFn: () => apiRequest<AwsConsumptionCut[]>(token, `/commercial/aws-consumption-cuts?party_id=${currentContract?.partyId}`),
    enabled: currentContract?.serviceType === 'AWS_MONTHLY',
  })
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['commercial', 'contracts'] })
    void queryClient.invalidateQueries({ queryKey: ['commercial', 'contracts', selected?.id, 'versions'] })
    void queryClient.invalidateQueries({ queryKey: ['commercial', 'billing-proposals', selected?.id] })
  }
  const createContract = useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      apiRequest<CommercialContract>(token, '/commercial/contracts', {
        method: 'POST', headers: { 'Idempotency-Key': idempotencyKey('web-contract') }, body: JSON.stringify(data),
      }),
    onSuccess: (contract) => {
      setCreating(false)
      setSelected(contract)
      setPartyId(contract.partyId)
      return queryClient.invalidateQueries({ queryKey: ['commercial', 'contracts'] })
    },
  })
  const createVersion = useMutation({
    mutationFn: (data: Record<string, unknown>) => apiRequest<ContractVersion>(token, `/commercial/contracts/${selected?.id}/versions`, {
      method: 'POST', headers: { 'Idempotency-Key': idempotencyKey('web-contract-version') }, body: JSON.stringify(data),
    }),
    onSuccess: refresh,
  })
  const uploadContractPdf = useMutation({
    mutationFn: async ({ versionId, file, kind }: { versionId: string; file: File; kind: 'sent' | 'signed' }) => {
      const form = new FormData()
      form.append('file', file)
      return apiRequest<ContractVersion>(token, `/commercial/contracts/${selected?.id}/versions/${versionId}/${kind}-pdf`, {
        method: 'POST', headers: { 'Idempotency-Key': idempotencyKey(`web-contract-${kind}-pdf`) }, body: form,
      })
    },
    onSuccess: refresh,
  })
  const downloadPdf = useMutation({
    mutationFn: ({ versionId, kind }: { versionId: string; kind: 'sent' | 'signed' }) => apiRequest<ContractArtifactDownload>(token, `/commercial/contracts/${selected?.id}/versions/${versionId}/${kind}-pdf?inline=true`),
    onSuccess: setPdfPreview,
  })
  const sendEmail = useMutation({
    mutationFn: ({ versionId, subject, message }: { versionId: string; subject: string; message: string }) => apiRequest<ContractVersion>(token, `/commercial/contracts/${selected?.id}/versions/${versionId}/email`, {
      method: 'POST', headers: { 'Idempotency-Key': idempotencyKey('web-contract-email') }, body: JSON.stringify({ subject, message }),
    }),
    onSuccess: refresh,
  })
  const syncEmail = useMutation({
    mutationFn: (versionId: string) => apiRequest<ContractEmailSync>(token, `/commercial/contracts/${selected?.id}/versions/${versionId}/email-sync`, {
      method: 'POST', headers: { 'Idempotency-Key': idempotencyKey('web-contract-email-sync') },
    }),
    onSuccess: (result, versionId) => { setSyncResult({ versionId, result }); refresh() },
  })
  const versionAction = useMutation({
    mutationFn: ({ versionId, action }: { versionId: string; action: 'confirm-firmaec' | 'activate' }) => apiRequest<ContractVersion>(token, `/commercial/contracts/${selected?.id}/versions/${versionId}/${action}`, {
      method: 'POST', headers: { 'Idempotency-Key': idempotencyKey(`web-contract-${action}`) },
    }),
    onSuccess: refresh,
  })
  const createAwsCut = useMutation({
    mutationFn: (data: Record<string, unknown>) => apiRequest<AwsConsumptionCut>(token, '/commercial/aws-consumption-cuts', {
      method: 'POST', headers: { 'Idempotency-Key': idempotencyKey('web-aws-cut') }, body: JSON.stringify(data),
    }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['commercial', 'aws-cuts', currentContract?.partyId] }),
  })
  const uploadAwsEvidence = useMutation({
    mutationFn: async ({ cutId, file }: { cutId: string; file: File }) => {
      const form = new FormData(); form.append('file', file)
      return apiRequest<AwsConsumptionCut>(token, `/commercial/aws-consumption-cuts/${cutId}/evidence`, {
        method: 'POST', headers: { 'Idempotency-Key': idempotencyKey('web-aws-evidence') }, body: form,
      })
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['commercial', 'aws-cuts'] }),
  })
  const confirmAwsCut = useMutation({
    mutationFn: (cutId: string) => apiRequest<AwsConsumptionCut>(token, `/commercial/aws-consumption-cuts/${cutId}/confirm`, {
      method: 'POST', headers: { 'Idempotency-Key': idempotencyKey('web-aws-confirm') },
    }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['commercial', 'aws-cuts'] }),
  })
  const prepareBilling = useMutation({
    mutationFn: (data: Record<string, unknown>) => apiRequest<BillingProposal>(token, `/commercial/contracts/${selected?.id}/prepare-billing`, {
      method: 'POST', headers: { 'Idempotency-Key': idempotencyKey('web-contract-billing') }, body: JSON.stringify(data),
    }),
    onSuccess: refresh,
  })
  const uploadReport = useMutation({
    mutationFn: async ({ proposalId, file }: { proposalId: string; file: File }) => {
      const form = new FormData(); form.append('file', file)
      return apiRequest<BillingProposal>(token, `/commercial/billing-proposals/${proposalId}/report`, {
        method: 'POST', headers: { 'Idempotency-Key': idempotencyKey('web-billing-report') }, body: form,
      })
    },
    onSuccess: refresh,
  })
  const proposalAction = useMutation({
    mutationFn: ({ proposalId, action }: { proposalId: string; action: 'report/approve' | 'create-invoice-draft' }) => apiRequest<BillingProposal | SalesDocument>(token, `/commercial/billing-proposals/${proposalId}/${action}`, {
      method: 'POST', headers: { 'Idempotency-Key': idempotencyKey(`web-proposal-${action}`) },
    }),
    onSuccess: refresh,
  })

  function submitContract(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    createContract.mutate({
      partyId: String(data.get('partyId')),
      contractNumber: String(data.get('contractNumber')).trim(),
      title: String(data.get('title')).trim(),
      serviceType: String(data.get('serviceType')),
      sourceLeadId: data.get('sourceLeadId') || null,
      parentContractId: data.get('parentContractId') || null,
      reportRequired: data.get('reportRequired') === 'on',
      collectionEnabled: data.get('collectionEnabled') === 'on',
    })
  }
  function submitVersion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    const product = products.find((item) => item.id === String(data.get('productId')))
    const tax = taxes.find((item) => item.id === product?.taxCategoryId)
    const invoiceRule = {
      type: currentContract?.serviceType,
      establishmentId: String(data.get('establishmentId')),
      emissionPointId: String(data.get('emissionPointId')),
      productId: product?.id,
      taxCode: tax?.sriCode,
      description: String(data.get('description') || currentContract?.title || '').trim(),
      currency: 'USD',
    }
    let pricingRules: Array<Record<string, unknown>> = []
    if (currentContract?.serviceType === 'FIXED_MONTHLY') pricingRules = [{ ...invoiceRule, amount: String(data.get('amount')) }]
    if (currentContract?.serviceType === 'AWS_MONTHLY') pricingRules = [invoiceRule]
    if (currentContract?.serviceType === 'MILESTONE') {
      const baseAmount = String(data.get('baseAmount'))
      pricingRules = String(data.get('milestones')).split(',').map((part, index) => {
        const value = part.trim()
        return value.endsWith('%')
          ? { ...invoiceRule, label: `Hito ${index + 1}`, percentage: value.slice(0, -1), baseAmount }
          : { ...invoiceRule, label: `Hito ${index + 1}`, amount: value }
      }).filter((rule) => ('amount' in rule && Boolean(rule.amount)) || ('percentage' in rule && Boolean(rule.percentage)))
    }
    createVersion.mutate({
      validFrom: String(data.get('validFrom')),
      validTo: String(data.get('validTo')) || null,
      paymentTermsDays: Number(data.get('paymentTermsDays')),
      renewalNoticeDays: data.get('renewalNoticeDays') === '' ? null : Number(data.get('renewalNoticeDays')),
      pricingRules,
      amendsVersionId: versionsQuery.data?.[0]?.id ?? null,
    })
  }
  function submitPdf(event: FormEvent<HTMLFormElement>, versionId: string, kind: 'sent' | 'signed') {
    event.preventDefault()
    const file = new FormData(event.currentTarget).get('file')
    if (file instanceof File && file.size > 0) uploadContractPdf.mutate({ versionId, file, kind })
  }
  const activeVersion = versionsQuery.data?.find((version) => version.status === 'ACTIVE')
  const billingNeedsConfig = currentContract?.serviceType !== 'ACCESSORY' && currentContract?.serviceType !== 'ONE_OFF'
  const error = createContract.error ?? createVersion.error ?? uploadContractPdf.error ?? sendEmail.error ?? syncEmail.error ?? versionAction.error ?? createAwsCut.error ?? uploadAwsEvidence.error ?? confirmAwsCut.error ?? prepareBilling.error ?? uploadReport.error ?? proposalAction.error

  if (creating) return (
    <>
      <ErpPageHeader eyebrow="Comercial" title="Nuevo contrato" subtitle="Crea el registro comercial antes de agregar versiones o el PDF firmado." />
      <ErpFormPanel eyebrow="Contrato" title="Datos del contrato" submitLabel="Guardar contrato" pending={createContract.isPending} error={createContract.error?.message} onSubmit={submitContract} onCancel={() => setCreating(false)}>
        <label>Cliente<select name="partyId" value={newPartyId} onChange={(event) => { setNewPartyId(event.target.value); setPartyId(event.target.value) }} required><option value="" disabled>Selecciona un cliente</option>{customers.map((party) => <option key={party.id} value={party.id}>{party.name}</option>)}</select></label>
        <label>Oportunidad ganada (opcional)<select name="sourceLeadId" defaultValue=""><option value="">Sin vínculo</option>{(wonLeadsQuery.data ?? []).filter((lead) => lead.partyId === newPartyId).map((lead) => <option key={lead.id} value={lead.id}>{lead.title}</option>)}</select></label>
        <label>Número de contrato<input name="contractNumber" maxLength={80} required placeholder="CT-2026-001" /></label>
        <label>Nombre o asunto<input name="title" maxLength={200} required placeholder="Servicios administrados AWS" /></label>
        <label>Tipo de servicio<select name="serviceType" defaultValue="FIXED_MONTHLY"><option value="FIXED_MONTHLY">Mensual fijo</option><option value="AWS_MONTHLY">AWS por consumo</option><option value="MILESTONE">Por hitos</option><option value="ACCESSORY">Documento accesorio</option></select></label>
        <label>Contrato principal (solo accesorios)<select name="parentContractId" defaultValue=""><option value="">No aplica</option>{(contractsQuery.data ?? []).filter((contract) => contract.partyId === newPartyId && contract.serviceType !== 'ACCESSORY').map((contract) => <option key={contract.id} value={contract.id}>{contract.contractNumber} · {contract.title}</option>)}</select></label>
        <label className="checkbox-field"><input name="reportRequired" type="checkbox" /> Exige informe mensual antes de enviar la factura</label>
        <label className="checkbox-field"><input name="collectionEnabled" type="checkbox" /> Permitir mensajes de cobranza</label>
      </ErpFormPanel>
    </>
  )

  if (selected && currentContract) return (
    <>
      <ErpPageHeader eyebrow="Contrato comercial" title={currentContract.title} subtitle={`Contrato ${currentContract.contractNumber}. El PDF se prepara fuera de IAERP y cada envío queda fijo.`} actions={<ErpButton variant="secondary" onClick={() => setSelected(null)}>Volver al listado</ErpButton>} />
      <section className="split-layout">
        <ErpPanel title="Versiones" count={versionsQuery.data?.length ?? 0}>
          {versionsQuery.isPending ? <p>Cargando versiones…</p> : null}
          {(versionsQuery.data ?? []).map((version) => (
            <article key={version.id} className="contract-version">
              <div><strong>Versión {version.versionNumber}</strong><p>{version.validFrom}{version.validTo ? ` a ${version.validTo}` : ' en adelante'} · {version.paymentTermsDays} días de pago</p></div>
              <ErpStatusBadge tone={version.status === 'SIGNED' || version.status === 'ACTIVE' ? 'success' : 'warning'}>{version.status === 'ACTIVE' ? 'Activo' : version.status === 'SIGNED' ? 'Firmado' : version.status === 'PENDING_SIGNATURE' ? 'Esperando firma' : version.status === 'EXPIRED' ? 'Vencido' : 'Borrador'}</ErpStatusBadge>
              {!version.sentArtifactSha256 ? <form className="inline-form" onSubmit={(event) => submitPdf(event, version.id, 'sent')}><label>PDF terminado<input name="file" type="file" accept="application/pdf,.pdf" required /></label><ErpButton variant="secondary" type="submit" disabled={uploadContractPdf.isPending}>Guardar PDF</ErpButton></form> : null}
              {version.sentArtifactSha256 ? <div className="inline-form"><span className="fine-print">PDF enviado · SHA-256 {version.sentArtifactSha256.slice(0, 12)}…</span><ErpButton variant="ghost" onClick={() => downloadPdf.mutate({ versionId: version.id, kind: 'sent' })}>Ver enviado</ErpButton></div> : null}
              {version.status === 'DRAFT' && version.sentArtifactSha256 ? <form className="vertical-form" onSubmit={(event) => { event.preventDefault(); const data = new FormData(event.currentTarget); sendEmail.mutate({ versionId: version.id, subject: String(data.get('subject')), message: String(data.get('message')) }) }}><label>Asunto<input name="subject" defaultValue={`Contrato ${currentContract.contractNumber} para revisión`} required /></label><label>Mensaje<textarea name="message" defaultValue="Adjuntamos el contrato para su revisión. Por favor responda en este mismo hilo con el PDF firmado." required /></label><ErpButton variant="primary" type="submit" disabled={sendEmail.isPending}>Enviar por Gmail</ErpButton></form> : null}
              {version.gmailThreadId && !version.firmaecConfirmedAt ? <div className="inline-form"><ErpButton variant="secondary" onClick={() => syncEmail.mutate(version.id)} disabled={syncEmail.isPending}>Revisar respuesta en Gmail</ErpButton>{syncResult?.versionId === version.id ? <span role="status">{syncResult.result.signedPdfReceived ? 'PDF firmado recibido' : syncResult.result.replyDetected ? 'Hay respuesta, aún sin PDF nuevo' : 'Sin respuesta nueva'}</span> : null}</div> : null}
              {!version.signedArtifactSha256 && version.status === 'PENDING_SIGNATURE' ? <form className="inline-form" onSubmit={(event) => submitPdf(event, version.id, 'signed')}><label>O cargar PDF recibido<input name="file" type="file" accept="application/pdf,.pdf" required /></label><ErpButton variant="secondary" type="submit" disabled={uploadContractPdf.isPending}>Guardar firmado</ErpButton></form> : null}
              {version.signedArtifactSha256 ? <><p className="fine-print">PDF firmado · SHA-256 {version.signedArtifactSha256.slice(0, 12)}… · {version.signaturePrecheckStatus === 'SIGNATURE_FOUND' ? 'firma técnica encontrada' : 'la revisión técnica no encontró firma'}</p><div className="inline-form"><ErpButton variant="ghost" onClick={() => downloadPdf.mutate({ versionId: version.id, kind: 'signed' })}>Ver firmado</ErpButton>{!version.firmaecConfirmedAt ? <ErpButton variant="secondary" onClick={() => versionAction.mutate({ versionId: version.id, action: 'confirm-firmaec' })}>Ya validé en FirmaEC</ErpButton> : null}{version.status === 'SIGNED' ? <ErpButton variant="primary" onClick={() => versionAction.mutate({ versionId: version.id, action: 'activate' })}>Activar contrato</ErpButton> : null}</div></> : null}
            </article>
          ))}
          {versionsQuery.error ? <p className="form-error" role="alert">{versionsQuery.error.message}</p> : null}
          {downloadPdf.error ? <p className="form-error" role="alert">{downloadPdf.error.message}</p> : null}
        </ErpPanel>
        <ErpFormPanel eyebrow="Nueva versión" title="Vigencia y cobro" submitLabel="Agregar versión" pending={createVersion.isPending} error={createVersion.error?.message} onSubmit={submitVersion} onCancel={() => setSelected(null)}>
          <label>Vigente desde<input name="validFrom" type="date" defaultValue={todayInFiscalTimezone()} required /></label>
          <label>Vigente hasta (opcional)<input name="validTo" type="date" /></label>
          <div className="field-row"><label>Pago en días<input name="paymentTermsDays" type="number" min="0" max="365" defaultValue="30" required /></label><label>Aviso de renovación (días)<input name="renewalNoticeDays" type="number" min="0" max="365" /></label></div>
          {billingNeedsConfig ? <><label>Establecimiento<select name="establishmentId" required><option value="">Selecciona</option>{establishments.map((item) => <option key={item.id} value={item.id}>{item.code} · {item.name}</option>)}</select></label><label>Punto de emisión<select name="emissionPointId" required><option value="">Selecciona</option>{emissionPoints.map((item) => <option key={item.id} value={item.id}>{item.code}</option>)}</select></label><label>Servicio del catálogo<select name="productId" required><option value="">Selecciona</option>{products.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label>Texto de la factura<input name="description" defaultValue={currentContract.title} required /></label></> : null}
          {currentContract.serviceType === 'FIXED_MONTHLY' ? <label>Valor mensual USD<input name="amount" type="number" min="0" step="0.01" required /></label> : null}
          {currentContract.serviceType === 'MILESTONE' ? <><label>Hitos separados por coma<input name="milestones" placeholder="40%, 20%, 40%" required /></label><label>Valor total para porcentajes<input name="baseAmount" type="number" min="0" step="0.01" required /></label></> : null}
          {currentContract.serviceType === 'AWS_MONTHLY' ? <p className="fine-print">El valor se tomará del corte mensual de StreamOne revisado.</p> : null}
          <p className="fine-print">Esta versión es comercial. No crea ni emite una factura SRI.</p>
        </ErpFormPanel>
      </section>
      {currentContract.serviceType === 'AWS_MONTHLY' ? <ErpPanel title="Cortes AWS" count={awsCutsQuery.data?.length ?? 0}><form className="inline-form" onSubmit={(event) => { event.preventDefault(); const data = new FormData(event.currentTarget); createAwsCut.mutate({ partyId: currentContract.partyId, periodStart: data.get('periodStart'), periodEnd: data.get('periodEnd'), source: 'XLSX_UPLOAD', totalCost: data.get('totalCost'), currency: 'USD', reconciliationSummary: { source: 'StreamOne', totalEnteredManually: true } }) }}><label>Desde<input name="periodStart" type="date" required /></label><label>Hasta<input name="periodEnd" type="date" required /></label><label>Total conciliado<input name="totalCost" type="number" min="0" step="0.01" required /></label><ErpButton variant="secondary" type="submit">Crear corte</ErpButton></form>{(awsCutsQuery.data ?? []).map((cut) => <article className="contract-version" key={cut.id}><strong>{cut.periodStart} a {cut.periodEnd} · ${cut.totalCost}</strong><span>{cut.status}</span>{!cut.evidenceSha256 ? <form className="inline-form" onSubmit={(event) => { event.preventDefault(); const file = new FormData(event.currentTarget).get('file'); if (file instanceof File) uploadAwsEvidence.mutate({ cutId: cut.id, file }) }}><label>Reporte privado<input name="file" type="file" accept=".csv,.xls,.xlsx,.pdf" required /></label><ErpButton variant="secondary" type="submit">Guardar reporte</ErpButton></form> : null}{cut.status === 'RECONCILED' ? <ErpButton variant="primary" onClick={() => confirmAwsCut.mutate(cut.id)}>Confirmar total revisado</ErpButton> : null}</article>)}</ErpPanel> : null}
      {currentContract.status === 'ACTIVE' && activeVersion && billingNeedsConfig ? <ErpFormPanel eyebrow="Facturación" title="Preparar cobro" submitLabel="Preparar para revisar" pending={prepareBilling.isPending} error={prepareBilling.error?.message} onSubmit={(event) => { event.preventDefault(); const data = new FormData(event.currentTarget); prepareBilling.mutate({ periodStart: data.get('periodStart'), periodEnd: data.get('periodEnd'), pricingRuleIndex: Number(data.get('pricingRuleIndex') || 0), awsConsumptionCutId: data.get('awsConsumptionCutId') || null, manualTotal: data.get('manualTotal') || null }) }} onCancel={() => undefined}><label>Período desde<input name="periodStart" type="date" required /></label><label>Período hasta<input name="periodEnd" type="date" required /></label>{currentContract.serviceType === 'MILESTONE' ? <label>Hito<select name="pricingRuleIndex">{activeVersion.pricingRules.map((rule, index) => <option key={index} value={index}>{String(rule.label ?? `Hito ${index + 1}`)}</option>)}</select></label> : null}{currentContract.serviceType === 'AWS_MONTHLY' ? <><label>Corte revisado<select name="awsConsumptionCutId" required><option value="">Selecciona</option>{(awsCutsQuery.data ?? []).filter((cut) => cut.status === 'REVIEWED').map((cut) => <option key={cut.id} value={cut.id}>{cut.periodStart} · ${cut.totalCost}</option>)}</select></label><label>Total escrito y conciliado<input name="manualTotal" type="number" min="0" step="0.01" required /></label></> : null}<p className="fine-print">Esto crea una tarea para revisar, no una factura.</p></ErpFormPanel> : null}
      <ErpPanel title="Cobros preparados" count={proposalsQuery.data?.length ?? 0}>{(proposalsQuery.data ?? []).map((proposal) => <article className="contract-version" key={proposal.id}><div><strong>{proposal.periodStart ?? proposal.issueDate} · ${proposal.totalAmount}</strong><p>{proposal.billingType} · {proposal.collectionEnabled ? 'Cobranza permitida' : 'Sin cobranza'}</p></div><ErpStatusBadge tone={proposal.status === 'CONVERTED' ? 'success' : 'warning'}>{proposal.status === 'CONVERTED' ? 'Borrador creado' : 'Por revisar'}</ErpStatusBadge>{proposal.reportRequired && !proposal.reportSha256 ? <form className="inline-form" onSubmit={(event) => { event.preventDefault(); const file = new FormData(event.currentTarget).get('file'); if (file instanceof File) uploadReport.mutate({ proposalId: proposal.id, file }) }}><label>Informe mensual PDF<input name="file" type="file" accept="application/pdf,.pdf" required /></label><ErpButton variant="secondary" type="submit">Guardar informe</ErpButton></form> : null}{proposal.reportSha256 && !proposal.reportApprovedAt ? <ErpButton variant="secondary" onClick={() => proposalAction.mutate({ proposalId: proposal.id, action: 'report/approve' })}>Aprobar informe</ErpButton> : null}{proposal.status === 'READY_FOR_REVIEW' ? <ErpButton variant="primary" onClick={() => proposalAction.mutate({ proposalId: proposal.id, action: 'create-invoice-draft' })}>Crear borrador</ErpButton> : null}</article>)}{!proposalsQuery.isPending && (proposalsQuery.data ?? []).length === 0 ? <ErpEmptyState title="No hay cobros preparados" description="Cuando el contrato esté activo, prepara el período que vas a facturar." /> : null}</ErpPanel>
      {error ? <p className="form-error" role="alert">{error.message}</p> : null}
      {pdfPreview ? <PdfPreviewModal title="Documento del contrato" artifact={pdfPreview} onClose={() => setPdfPreview(null)} /> : null}
    </>
  )

  return (
    <>
      <ErpPageHeader eyebrow="Comercial" title="Contratos" subtitle="PDF, firma, vigencia y cobros en un solo lugar. Las cláusulas se preparan fuera de IAERP." actions={<ErpButton variant="primary" onClick={() => { setNewPartyId(partyId); setCreating(true) }}>Nuevo contrato</ErpButton>} />
      <ErpToolbar ariaLabel="Filtros de contratos"><label>Cliente<select value={partyId} onChange={(event) => setPartyId(event.target.value)}><option value="">Todos los clientes</option>{customers.map((party) => <option key={party.id} value={party.id}>{party.name}</option>)}</select></label></ErpToolbar>
      <ErpPanel title="Listado comercial" count={contractsQuery.data?.length ?? 0}>
        <div className="table-wrap" tabIndex={0} aria-label="Listado de contratos"><table className="erp-responsive-table"><thead><tr><th>Contrato</th><th>Cliente</th><th>Tipo</th><th>Estado</th><th>Acciones</th></tr></thead><tbody>{(contractsQuery.data ?? []).map((contract) => <tr key={contract.id}><td><strong>{contract.contractNumber}</strong><small>{contract.title}</small></td><td>{parties.find((party) => party.id === contract.partyId)?.name ?? 'Cliente'}</td><td>{contract.serviceType === 'AWS_MONTHLY' ? 'AWS' : contract.serviceType === 'FIXED_MONTHLY' ? 'Mensual fijo' : contract.serviceType === 'MILESTONE' ? 'Hitos' : 'Accesorio'}</td><td><ErpStatusBadge tone={contract.status === 'SIGNED' || contract.status === 'ACTIVE' ? 'success' : 'warning'}>{contract.status === 'ACTIVE' ? 'Activo' : contract.status === 'SIGNED' ? 'Firmado' : contract.status === 'PENDING_SIGNATURE' ? 'Esperando firma' : 'Borrador'}</ErpStatusBadge></td><td><ErpActionCell><ErpButton variant="ghost" onClick={() => setSelected(contract)}>Abrir</ErpButton></ErpActionCell></td></tr>)}</tbody></table>{!contractsQuery.isPending && (contractsQuery.data ?? []).length === 0 ? <ErpEmptyState title="No hay contratos" description="Crea un contrato para un cliente y agrega su primera versión." action={<ErpButton variant="primary" onClick={() => setCreating(true)}>Nuevo contrato</ErpButton>} /> : null}</div>
        {contractsQuery.error ? <p className="form-error" role="alert">{contractsQuery.error.message}</p> : null}
      </ErpPanel>
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
  const [catalogView, setCatalogView] = useState<'products' | 'taxes'>('products')
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

  if (catalogView === 'taxes') {
    return <TaxCategoriesPage taxes={taxes} token={token} onBack={() => setCatalogView('products')} />
  }

  if (editor !== undefined) {
    if (taxes.length === 0) {
      return (
        <>
          <ErpPageHeader
            eyebrow="Catálogos"
            title="Primero crea una categoría tributaria"
            subtitle="Cada producto necesita una categoría vigente para calcular y reportar sus impuestos correctamente."
          />
          <ErpEmptyState
            title="No hay categorías tributarias vigentes"
            description="Crea una categoría con su código SRI, tarifa y fecha de vigencia antes de registrar el producto."
            action={<ErpButton variant="primary" onClick={() => setCatalogView('taxes')}>Crear categoría tributaria</ErpButton>}
          />
        </>
      )
    }
    return (
      <>
        <ErpPageHeader
          eyebrow={editor ? 'Edición de producto' : 'Nuevo producto'}
          title={editor ? editor.name : 'Nuevo producto'}
          subtitle="Define precio e impuesto; el servidor conservará la precisión para los cálculos fiscales."
        />
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
          <label>Categoría tributaria<select name="taxCategoryId" defaultValue={editor?.taxCategoryId ?? taxes[0]?.id} required>{taxes.map((tax) => <option key={tax.id} value={tax.id}>{tax.name} · {formatPercent(tax.rate)}</option>)}</select></label>
        </ErpFormPanel>
      </>
    )
  }

  return (
    <>
      <ErpPageHeader
        eyebrow="Catálogos"
        title="Productos y servicios"
        subtitle="Productos y servicios con precio e impuestos vigentes."
        actions={
          <>
            <ErpButton variant="secondary" onClick={() => setCatalogView('taxes')}>Categorías tributarias</ErpButton>
            <ErpButton variant="primary" onClick={() => setEditor(null)}>Nuevo producto</ErpButton>
          </>
        }
      />
      <ErpToolbar>
        <label className="search-field">
          <span>Buscar producto</span>
          <input value={query} onChange={(event) => setQuery(event.target.value)} />
        </label>
        <ErpStatusBadge>{products.length} activos</ErpStatusBadge>
      </ErpToolbar>
      <section className="split-layout erp-list-only">
        <ErpPanel title="Catálogo" count={filtered.length}>
          <div className="product-grid" aria-label="Productos">
            {filtered.map((product, index) => (
              <article className="product-card" key={product.id}>
                <span>{String(index + 1).padStart(2, '0')}</span>
                <h2>{product.name}</h2>
                <p>{product.code ?? 'Sin código interno'}</p>
                <strong>${formatAmount(product.unitPrice)}</strong>
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
      </section>
    </>
  )
}

function TaxCategoriesPage({
  taxes,
  token,
  onBack,
}: {
  taxes: TaxCategory[]
  token: string
  onBack: () => void
}) {
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)
  const createTaxCategory = useMutation({
    mutationFn: (data: TaxCategoryInput) =>
      apiRequest<TaxCategory>(token, '/tax-categories', {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey('web-tax-category') },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      setCreating(false)
      return queryClient.invalidateQueries({ queryKey: ['taxes'] })
    },
  })

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    createTaxCategory.mutate({
      sriCode: String(data.get('sriCode')).trim(),
      name: String(data.get('name')).trim(),
      rate: String(data.get('rate')),
      validFrom: String(data.get('validFrom')),
    })
  }

  if (creating) {
    return (
      <>
        <ErpPageHeader eyebrow="Catálogos" title="Nueva categoría tributaria" subtitle="Registra la tarifa con su vigencia; los comprobantes ya emitidos conservan su cálculo original." />
        <ErpFormPanel
          eyebrow="Dato fiscal maestro"
          title="Categoría tributaria"
          pending={createTaxCategory.isPending}
          error={createTaxCategory.error?.message}
          onSubmit={submit}
          onCancel={() => setCreating(false)}
        >
          <div className="field-row">
            <label>Código SRI<input name="sriCode" maxLength={20} placeholder="4" required /></label>
            <label>Tarifa (%)<input name="rate" type="number" min="0" max="100" step="0.000001" placeholder="15" required /></label>
          </div>
          <label>Nombre<input name="name" maxLength={120} placeholder="IVA 15%" required /></label>
          <label>Vigente desde<input name="validFrom" type="date" defaultValue={new Date().toISOString().slice(0, 10)} required /></label>
        </ErpFormPanel>
      </>
    )
  }

  return (
    <>
      <ErpPageHeader
        eyebrow="Catálogos"
        title="Categorías tributarias"
        subtitle="Tarifas disponibles al crear productos y servicios."
        actions={
          <>
            <ErpButton variant="secondary" onClick={onBack}>Productos y servicios</ErpButton>
            <ErpButton variant="primary" onClick={() => setCreating(true)}>Nueva categoría</ErpButton>
          </>
        }
      />
      <section className="split-layout erp-list-only">
        <ErpPanel title="Tarifas vigentes" count={taxes.length}>
          <div className="table-wrap" tabIndex={0} aria-label="Listado de categorías tributarias">
            <table className="erp-responsive-table">
              <thead><tr><th>Código SRI</th><th>Nombre</th><th>Tarifa</th><th>Vigente desde</th></tr></thead>
              <tbody>
                {taxes.map((tax) => (
                  <tr key={tax.id}>
                    <td>{tax.sriCode}</td>
                    <td><strong>{tax.name}</strong></td>
                    <td>{formatPercent(tax.rate)}</td>
                    <td>{new Date(`${tax.validFrom}T00:00:00`).toLocaleDateString('es-EC')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {taxes.length === 0 ? <ErpEmptyState title="No hay categorías tributarias" description="Registra la primera tarifa para habilitar la creación de productos." action={<ErpButton variant="primary" onClick={() => setCreating(true)}>Nueva categoría</ErpButton>} /> : null}
          </div>
        </ErpPanel>
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
  NOT_AUTHORIZED: 'NO AUTORIZADA',
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
  NOT_AUTHORIZED: 'danger',
  REJECTED: 'danger',
  FAILED: 'danger',
  VOIDED: 'danger',
}

function InvoiceStatusBadge({ status }: { status: SalesDocumentStatus }) {
  return <ErpStatusBadge tone={invoiceStatusTone[status]}>{invoiceStatusLabels[status]}</ErpStatusBadge>
}

function CollectionStatusBadge({ status }: { status: AccountItemStatus | null | undefined }) {
  if (!status) return <span className="fine-print">—</span>
  const labels: Record<AccountItemStatus, string> = {
    OPEN: 'Pendiente', PARTIAL: 'Parcial', OVERDUE: 'Vencida', SETTLED: '✓ Pagada', VOIDED: 'Anulada',
  }
  const tones: Record<AccountItemStatus, 'neutral' | 'success' | 'warning' | 'danger'> = {
    OPEN: 'neutral', PARTIAL: 'warning', OVERDUE: 'danger', SETTLED: 'success', VOIDED: 'danger',
  }
  return <ErpStatusBadge tone={tones[status]}>{labels[status]}</ErpStatusBadge>
}

const sriTransmissionStatusLabels: Record<string, string> = {
  PENDING: 'PENDIENTE DE ENVÍO',
  RECEIVED: 'RECIBIDA POR SRI',
  PENDING_AUTHORIZATION: 'EN PROCESO DE AUTORIZACIÓN',
  AUTHORIZED: 'AUTORIZADA',
  NOT_AUTHORIZED: 'NO AUTORIZADA',
  REJECTED: 'RECHAZADA',
  FAILED: 'ERROR DE TRANSMISIÓN',
}

function sriTransmissionStatusLabel(status: string) {
  return sriTransmissionStatusLabels[status] ?? 'ESTADO PENDIENTE DE CLASIFICACIÓN'
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

function addDays(dateValue: string, days: number): string {
  if (!dateValue) return ''
  const date = new Date(`${dateValue}T12:00:00Z`)
  if (Number.isNaN(date.getTime())) return ''
  date.setUTCDate(date.getUTCDate() + (Number.isFinite(days) ? days : 0))
  return date.toISOString().slice(0, 10)
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
  defaultPaymentTermsDays,
  onCreated,
  onCancel,
}: {
  token: string
  customers: Party[]
  products: Product[]
  taxes: TaxCategory[]
  establishments: Establishment[]
  emissionPoints: EmissionPoint[]
  defaultPaymentTermsDays: number
  onCreated: (invoiceId: string) => void
  onCancel: () => void
}) {
  const queryClient = useQueryClient()
  const { notify } = useToast()
  const [customerId, setCustomerId] = useState(customers[0]?.id ?? '')
  const [establishmentId, setEstablishmentId] = useState(establishments[0]?.id ?? '')
  const [emissionPointId, setEmissionPointId] = useState(
    emissionPoints.find((point) => point.establishmentId === establishments[0]?.id)?.id ?? '',
  )
  const [issueDate, setIssueDate] = useState(todayInFiscalTimezone)
  const [lines, setLines] = useState<DraftLine[]>([emptyDraftLine()])
  const initialCustomer = customers.find((customer) => customer.id === customerId)
  const [paymentTermsDays, setPaymentTermsDays] = useState(
    initialCustomer?.paymentTermsDays ?? defaultPaymentTermsDays ?? 0,
  )

  // Origen de la condición de pago aplicada (Sprint 6, HU-17): override del
  // cliente vs. valor predeterminado de la empresa. Se deriva del cliente
  // seleccionado (initialCustomer se recomputa en cada render con customerId).
  const paymentTermsFromCustomer = initialCustomer?.paymentTermsDays != null

  const availableEmissionPoints = emissionPoints.filter(
    (point) => point.establishmentId === establishmentId,
  )
  // La identificación va como pista buscable: dos clientes pueden llamarse casi
  // igual y el RUC es lo que los distingue.
  const customerOptions = useMemo(
    () =>
      customers.map((customer) => ({
        value: customer.id,
        label: customer.name,
        hint: customer.identificationNumber,
      })),
    [customers],
  )
  const previewPayload = JSON.stringify({
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
  const deferredPreviewPayload = useDeferredValue(previewPayload)
  const previewQuery = useQuery({
    queryKey: ['invoice-preview', deferredPreviewPayload],
    queryFn: () => apiRequest<InvoicePreview>(token, '/invoices/preview', {
      method: 'POST',
      body: deferredPreviewPayload,
    }),
    enabled: lines.every((line) => Boolean(
      line.description && line.taxCode && Number(line.quantity) > 0 && Number(line.unitPrice) >= 0,
    )),
  })
  const previewIsCurrent = deferredPreviewPayload === previewPayload && !previewQuery.isFetching

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
    mutationFn: async (payload: {
      customerId: string
      establishmentId: string
      emissionPointId: string
      issueDate: string
      lines: InvoiceLineInput[]
    }) => {
      const authoritativePreview = await apiRequest<InvoicePreview>(token, '/invoices/preview', {
        method: 'POST',
        body: JSON.stringify({ issueDate: payload.issueDate, lines: payload.lines }),
      })
      return apiRequest<SalesDocument>(token, '/invoices', {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey('web-invoice') },
        body: JSON.stringify({
          customerId: payload.customerId,
          establishmentId: payload.establishmentId,
          emissionPointId: payload.emissionPointId,
          issueDate: payload.issueDate,
          installments: [{
            dueDate: addDays(payload.issueDate, paymentTermsDays),
            amount: authoritativePreview.total,
          }],
          lines: payload.lines,
        }),
      })
    },
    onSuccess: (invoice) => {
      void queryClient.invalidateQueries({ queryKey: ['invoices'] })
      notify(`Factura ${invoice.sequential} creada`, 'success')
      onCreated(invoice.id)
    },
    onError: (error) => {
      notify(error instanceof Error ? error.message : 'No se pudo crear la factura', 'error')
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
        <ErpCombobox
          ariaLabel="Cliente"
          placeholder="Buscar por nombre o identificación…"
          options={customerOptions}
          value={customerId}
          onChange={(nextId) => {
            setCustomerId(nextId)
            setPaymentTermsDays(customers.find((customer) => customer.id === nextId)?.paymentTermsDays ?? defaultPaymentTermsDays)
          }}
          required
        />
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
      <div className="field-row">
        <label>
          Condición de pago
          <select value={paymentTermsDays} onChange={(event) => setPaymentTermsDays(Number(event.target.value))}>
            <option value={0}>Contado</option>
            <option value={15}>15 días</option>
            <option value={30}>30 días</option>
            <option value={45}>45 días</option>
            <option value={60}>60 días</option>
            <option value={90}>90 días</option>
          </select>
        </label>
        <label>
          Vencimiento
          <input value={addDays(issueDate, paymentTermsDays)} readOnly />
        </label>
      </div>
      <p
        className={`payment-terms-source ${paymentTermsFromCustomer ? 'is-customer' : 'is-company'}`}
        data-terms-source={paymentTermsFromCustomer ? 'customer' : 'company'}
      >
        {paymentTermsFromCustomer
          ? 'Aplicando la condición de pago configurada para este cliente.'
          : 'Aplicando la condición de pago predeterminada de la empresa.'}
      </p>
      <InvoiceSpreadsheet
        lines={lines}
        products={products}
        taxes={taxes}
        preview={previewQuery.data}
        previewPending={!previewIsCurrent}
        onProductChange={onProductChange}
        onUpdateLine={updateLine}
        onAddLine={() => setLines((current) => [...current, emptyDraftLine()])}
        onRemoveLine={(key) => setLines((current) => current.filter((item) => item.key !== key))}
      />
      <section className="invoice-live-preview" aria-live="polite">
        <p className="section-number">Cálculo en vivo</p>
        {!previewIsCurrent ? <small>Validando con el servidor…</small> : null}
        {previewQuery.error ? <p className="form-error">{previewQuery.error.message}</p> : null}
        {previewQuery.data ? (
          <dl className="invoice-totals">
            {Array.from(previewQuery.data.lines.reduce((groups, line) => {
              groups.set(line.taxRate, (groups.get(line.taxRate) ?? 0) + Number(line.baseAmount))
              return groups
            }, new Map<string, number>())).map(([rate, base]) => <div key={rate}><dt>Subtotal IVA {formatPercent(rate)}</dt><dd>${formatAmount(base)}</dd></div>)}
            <div><dt>Subtotal</dt><dd>${formatAmount(previewQuery.data.subtotal)}</dd></div>
            <div><dt>IVA total</dt><dd>${formatAmount(previewQuery.data.taxTotal)}</dd></div>
            <div className="invoice-grand-total"><dt>Total</dt><dd>${formatAmount(previewQuery.data.total)}</dd></div>
          </dl>
        ) : <p className="fine-print">Completa la primera línea para calcular los valores.</p>}
      </section>
      <p className="fine-print">El servidor valida impuestos, redondeos y total antes de crear el borrador.</p>
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
      <p className="fine-print">Factura {invoice.sequential} · Total acreditable ${formatAmount(invoice.total)}</p>
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
  customers,
  establishments,
  emissionPoints,
  onClose,
  onOpenCreditNote,
  onDuplicated,
}: {
  token: string
  invoiceId: string
  customers: Party[]
  establishments: Establishment[]
  emissionPoints: EmissionPoint[]
  onClose: () => void
  onOpenCreditNote: (invoice: SalesDocument) => void
  onDuplicated: (invoiceId: string) => void
}) {
  const queryClient = useQueryClient()
  const [ridePreview, setRidePreview] = useState<ArtifactDownload | null>(null)
  const [emailing, setEmailing] = useState(false)
  const [emailRecipient, setEmailRecipient] = useState('')
  const [sentEmail, setSentEmail] = useState<InvoiceEmailResult | null>(null)
  const [archiving, setArchiving] = useState(false)
  const [archiveReason, setArchiveReason] = useState('Prueba de emisión SRI; comprobante no autorizado.')
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
  const emailPreviewQuery = useQuery({
    queryKey: ['invoices', invoiceId, 'email-preview'],
    queryFn: () => apiRequest<InvoiceEmailPreview>(token, `/invoices/${invoiceId}/email-preview`),
    enabled: emailing && invoiceQuery.data?.status === 'AUTHORIZED',
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

  const updateCollection = useMutation({
    mutationFn: (enabled: boolean) =>
      apiRequest<SalesDocument>(token, `/invoices/${invoiceId}/collection-policy`, {
        method: 'PUT',
        headers: { 'Idempotency-Key': idempotencyKey('web-invoice-collection') },
        body: JSON.stringify({ enabled }),
      }),
    onSuccess: (updated) => {
      queryClient.setQueryData(['invoices', invoiceId], updated)
      void queryClient.invalidateQueries({ queryKey: ['invoices'] })
    },
  })

  const duplicateInvoice = useMutation({
    mutationFn: () =>
      apiRequest<SalesDocument>(token, `/invoices/${invoiceId}/duplicate`, {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey('web-duplicate-invoice') },
      }),
    onSuccess: (duplicate) => {
      void queryClient.invalidateQueries({ queryKey: ['invoices'] })
      onDuplicated(duplicate.id)
    },
  })

  const archiveInvoice = useMutation({
    mutationFn: () =>
      apiRequest<SalesDocument>(token, `/invoices/${invoiceId}/archive`, {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey('web-archive-invoice') },
        body: JSON.stringify({ reason: archiveReason.trim() }),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['invoices'] })
      onClose()
    },
  })

  const emailInvoice = useMutation({
    mutationFn: () => apiRequest<InvoiceEmailResult>(token, `/invoices/${invoiceId}/email`, {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey('web-email-invoice') },
      body: JSON.stringify({ recipient: emailRecipient.trim() }),
    }),
    onSuccess: (result) => {
      setSentEmail(result)
      setEmailing(false)
    },
  })

  async function downloadArtifact(artifactId: string) {
    const download = await apiRequest<ArtifactDownload>(
      token,
      `/invoices/${invoiceId}/artifacts/${artifactId}/download`,
    )
    window.open(download.downloadUrl, '_blank', 'noopener,noreferrer')
  }

  const previewRide = useMutation({
    mutationFn: (artifactId: string) => apiRequest<ArtifactDownload>(
      token,
      `/invoices/${invoiceId}/artifacts/${artifactId}/download?inline=true`,
    ),
    onSuccess: setRidePreview,
  })

  if (invoiceQuery.isPending) {
    return (
      <section className="form-panel erp-form-panel erp-full-page-form" aria-busy="true">
        <p>Cargando factura…</p>
      </section>
    )
  }

  if (invoiceQuery.error || !invoiceQuery.data) {
    return (
      <section className="form-panel erp-form-panel erp-full-page-form">
        <p className="form-error" role="alert">
          {invoiceQuery.error?.message ?? 'No se pudo cargar la factura'}
        </p>
        <ErpButton variant="secondary" onClick={onClose}>Cancelar</ErpButton>
      </section>
    )
  }

  const invoice = invoiceQuery.data
  const customer = customers.find((item) => item.id === invoice.partyId)
  const establishment = establishments.find((item) => item.id === invoice.establishmentId)
  const emissionPoint = emissionPoints.find((item) => item.id === invoice.emissionPointId)
  const transmission = invoice.sriTransmission
  const canIssue = invoice.status === 'DRAFT'
  const canCreditNote = invoice.type === 'INVOICE' && invoice.status === 'AUTHORIZED'
  const taxBreakdown = Array.from(
    invoice.lines.reduce((groups, line) => {
      const current = groups.get(line.taxRate) ?? { base: 0, tax: 0 }
      current.base += Number(line.baseAmount)
      current.tax += Number(line.taxAmount)
      groups.set(line.taxRate, current)
      return groups
    }, new Map<string, { base: number; tax: number }>()),
  ).sort(([left], [right]) => Number(right) - Number(left))

  return (
    <section className="form-panel erp-form-panel erp-full-page-form invoice-detail" aria-labelledby="invoice-detail-title">
      <p className="section-number">Detalle</p>
      <h2 id="invoice-detail-title">Factura {invoice.sequential}</h2>
      <InvoiceStatusBadge status={invoice.status} />
      <dl className="invoice-summary invoice-metadata">
        <div><dt>Cliente</dt><dd>{customer?.name ?? 'No disponible'}</dd></div>
        <div><dt>Identificación</dt><dd>{customer?.identificationNumber ?? 'No disponible'}</dd></div>
        <div><dt>Dirección</dt><dd>{customer?.address ?? 'No registrada'}</dd></div>
        <div><dt>Fecha</dt><dd>{invoice.issueDate}</dd></div>
        <div><dt>Establecimiento</dt><dd>{establishment ? `${establishment.code} · ${establishment.name}` : 'No disponible'}</dd></div>
        <div><dt>Punto de emisión</dt><dd>{emissionPoint?.code ?? 'No disponible'}</dd></div>
        <div><dt>Condición de pago</dt><dd>{invoice.installments?.[0]?.dueDate === invoice.issueDate ? 'Contado' : 'Crédito'}</dd></div>
        <div><dt>Vencimiento</dt><dd>{invoice.installments?.[0]?.dueDate ?? invoice.issueDate}</dd></div>
        <div><dt>Retenciones aplicadas</dt><dd>{Number(invoice.retentionTotal) > 0 ? `$${formatAmount(invoice.retentionTotal)}` : 'Sin retención registrada'}</dd></div>
        {invoice.accessKey ? <div><dt>Clave de acceso</dt><dd>{invoice.accessKey}</dd></div> : null}
      </dl>

      <section aria-labelledby="invoice-lines-title">
        <p className="section-number" id="invoice-lines-title">Detalle de productos y servicios</p>
        <div className="table-wrap" tabIndex={0} aria-label="Líneas de la factura">
          <table className="invoice-detail-table">
            <thead>
              <tr><th>Cant.</th><th>Descripción</th><th>P. unitario</th><th>Descuento</th><th>Base</th><th>IVA</th><th>Valor IVA</th><th>Total</th></tr>
            </thead>
            <tbody>
              {invoice.lines.map((line) => (
                <tr key={line.id}>
                  <td>{formatAmount(line.quantity)}</td>
                  <td><strong>{line.description}</strong></td>
                  <td>${formatAmount(line.unitPrice)}</td>
                  <td>${formatAmount(line.discount)}</td>
                  <td>${formatAmount(line.baseAmount)}</td>
                  <td>{formatPercent(line.taxRate)}</td>
                  <td>${formatAmount(line.taxAmount)}</td>
                  <td>${formatAmount(Number(line.baseAmount) + Number(line.taxAmount))}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <dl className="invoice-totals">
          {taxBreakdown.map(([rate, values]) => (
            <div key={`subtotal-${rate}`}><dt>Subtotal IVA {formatPercent(rate)}</dt><dd>${formatAmount(values.base)}</dd></div>
          ))}
          <div data-testid="invoice-subtotal"><dt>Subtotal</dt><dd>${formatAmount(invoice.subtotal)}</dd></div>
          {taxBreakdown.filter(([, values]) => values.tax > 0).map(([rate, values]) => (
            <div key={`tax-${rate}`}><dt>IVA {formatPercent(rate)}</dt><dd>${formatAmount(values.tax)}</dd></div>
          ))}
          <div data-testid="invoice-tax"><dt>IVA total</dt><dd>${formatAmount(invoice.tax)}</dd></div>
          <div className="invoice-grand-total" data-testid="invoice-total"><dt>Total</dt><dd>${formatAmount(invoice.total)}</dd></div>
        </dl>
      </section>

      <section aria-labelledby="sri-status-title">
        <p className="section-number" id="sri-status-title">Estado SRI</p>
        {transmission ? (
          <dl className="invoice-summary">
            <div><dt>Estado</dt><dd>{sriTransmissionStatusLabel(transmission.status)}</dd></div>
            {transmission.message ? <div><dt>Mensaje</dt><dd>{transmission.message}</dd></div> : null}
            {transmission.authorizationNumber ? (
              <div><dt>Número de autorización</dt><dd>{transmission.authorizationNumber}</dd></div>
            ) : null}
          </dl>
        ) : (
          <p className="fine-print">Sin intentos de transmisión todavía.</p>
        )}
      </section>

      {invoice.status === 'DRAFT' ? (
        <section aria-labelledby="invoice-collection-title">
          <p className="section-number" id="invoice-collection-title">Cobranza</p>
          <label className="checkbox-field">
            <input
              type="checkbox"
              checked={invoice.collectionEnabled}
              disabled={updateCollection.isPending}
              onChange={(event) => updateCollection.mutate(event.target.checked)}
            />
            Permitir mensajes de cobranza para esta factura
          </label>
          <p className="fine-print">Los servicios puntuales empiezan apagados. También se respeta la política general y la decisión del cliente.</p>
        </section>
      ) : null}

      {issueInvoice.error ? (
        <p className="form-error" role="alert">{issueInvoice.error.message}</p>
      ) : null}
      {duplicateInvoice.error ? (
        <p className="form-error" role="alert">{duplicateInvoice.error.message}</p>
      ) : null}
      {archiveInvoice.error ? (
        <p className="form-error" role="alert">{archiveInvoice.error.message}</p>
      ) : null}
      {emailInvoice.error ? (
        <p className="form-error" role="alert">{emailInvoice.error.message}</p>
      ) : null}
      {updateCollection.error ? (
        <p className="form-error" role="alert">{updateCollection.error.message}</p>
      ) : null}
      {sentEmail ? (
        <p className="form-success" role="status">
          Factura enviada a {sentEmail.recipient} con RIDE y XML.
        </p>
      ) : null}
      {previewRide.error ? (
        <p className="form-error" role="alert">{previewRide.error.message}</p>
      ) : null}

      <section aria-labelledby="invoice-artifacts-title">
        <p className="section-number" id="invoice-artifacts-title">Artefactos</p>
        {artifactsQuery.data && artifactsQuery.data.length > 0 ? (
          <ul className="establishment-list">
            {Object.values(artifactsQuery.data.reduce<Record<string, DocumentArtifact>>((latest, artifact) => {
              const current = latest[artifact.artifactType]
              if (!current || artifact.version > current.version) latest[artifact.artifactType] = artifact
              return latest
            }, {})).map((artifact) => (
              <li key={artifact.id}>
                <span>{artifact.artifactType === 'xml-signed' ? 'XML' : 'RIDE'}</span>
                <div>
                  <strong>{artifact.artifactType === 'xml-signed' ? 'XML firmado' : 'RIDE PDF vigente'}</strong>
                  {artifact.artifactType === 'ride-pdf' ? (
                    <ErpButton
                      variant="ghost"
                      onClick={() => {
                        if (!previewRide.isPending) previewRide.mutate(artifact.id)
                      }}
                    >
                      Ver RIDE
                    </ErpButton>
                  ) : null}
                  <ErpButton variant="ghost" onClick={() => void downloadArtifact(artifact.id)}>
                    {artifact.artifactType === 'xml-signed' ? 'Descargar XML firmado' : 'Descargar RIDE PDF'}
                  </ErpButton>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="fine-print">Los archivos estarán disponibles después de firmar la factura.</p>
        )}
      </section>

      {ridePreview ? (
        <PdfPreviewModal title="RIDE autorizado" artifact={ridePreview} onClose={() => setRidePreview(null)} />
      ) : null}

      {archiving ? (
        <ErpModal title="Archivar comprobante de prueba" size="sm" onClose={() => setArchiving(false)}>
          <p className="fine-print">Se ocultará de Facturas y Cartera. El XML, RIDE, respuesta SRI y auditoría se conservarán.</p>
          <label>
            Motivo de archivo
            <textarea value={archiveReason} onChange={(event) => setArchiveReason(event.target.value)} minLength={3} maxLength={500} required />
          </label>
          <div className="erp-form-actions">
            <ErpButton variant="secondary" onClick={() => setArchiving(false)} disabled={archiveInvoice.isPending}>Cancelar</ErpButton>
            <ErpButton variant="danger" disabled={archiveInvoice.isPending || archiveReason.trim().length < 3} onClick={() => archiveInvoice.mutate()}>
              {archiveInvoice.isPending ? 'Archivando…' : 'Archivar'}
            </ErpButton>
          </div>
        </ErpModal>
      ) : null}

      {emailing ? (
        <ErpModal title="Enviar factura por correo" size="sm" onClose={() => setEmailing(false)}>
          <p className="fine-print">
            Se enviarán el RIDE PDF y el XML firmado vigentes. Nada saldrá hasta que confirmes aquí.
          </p>
          <label>
            Correo del destinatario
            <input
              type="email"
              value={emailRecipient}
              onChange={(event) => setEmailRecipient(event.target.value)}
              required
              autoFocus
            />
          </label>
          {emailPreviewQuery.isPending ? <p className="fine-print">Preparando vista previa…</p> : null}
          {emailPreviewQuery.error ? (
            <p className="form-error" role="alert">{emailPreviewQuery.error.message}</p>
          ) : null}
          {emailPreviewQuery.data ? (
            <section className="invoice-email-preview" aria-label="Vista previa del correo">
              <dl>
                <div><dt>Remitente</dt><dd>{emailPreviewQuery.data.senderAddress ? `${emailPreviewQuery.data.senderName ? `${emailPreviewQuery.data.senderName} · ` : ''}${emailPreviewQuery.data.senderAddress}` : 'Cuenta de Google conectada'}</dd></div>
                <div><dt>Asunto</dt><dd>{emailPreviewQuery.data.subject}</dd></div>
                <div><dt>Fecha límite de pago</dt><dd>{emailPreviewQuery.data.dueDate}</dd></div>
                <div><dt>Plazo</dt><dd>{emailPreviewQuery.data.paymentTermsDays === 0 ? 'Pago inmediato' : `${emailPreviewQuery.data.paymentTermsDays} días`}</dd></div>
              </dl>
              <p className="invoice-email-message">{emailPreviewQuery.data.message}</p>
              <p className="fine-print">
                Adjuntos: {emailPreviewQuery.data.attachmentNames.join(' · ')}
              </p>
            </section>
          ) : null}
          <div className="erp-form-actions">
            <ErpButton variant="secondary" onClick={() => setEmailing(false)} disabled={emailInvoice.isPending}>Cancelar</ErpButton>
            <ErpButton
              variant="primary"
              disabled={emailInvoice.isPending || emailPreviewQuery.isPending || !emailRecipient.trim()}
              onClick={() => emailInvoice.mutate()}
            >
              {emailInvoice.isPending ? 'Enviando…' : 'Confirmar envío'}
            </ErpButton>
          </div>
        </ErpModal>
      ) : null}

      {invoice.status === 'AUTHORIZED' ? (
        <section className="invoice-delivery-panel" aria-labelledby="invoice-delivery-title">
          <div>
            <p className="section-number" id="invoice-delivery-title">Entrega al cliente</p>
            <h3>Enviar factura autorizada</h3>
            <p>
              El correo incluye el plazo y la fecha límite de pago. Se adjuntan el RIDE PDF y el XML firmado.
            </p>
          </div>
          <ErpButton
            variant="primary"
            onClick={() => {
              setEmailRecipient(emailPreviewQuery.data?.recipient ?? customer?.email ?? '')
              setSentEmail(null)
              setEmailing(true)
            }}
          >
            <Mail size={18} aria-hidden="true" /> Preparar correo
          </ErpButton>
        </section>
      ) : null}

      <div className="erp-form-actions">
        <ErpButton variant="secondary" onClick={onClose}>Volver al listado</ErpButton>
        {canCreditNote ? (
          <ErpButton variant="secondary" onClick={() => onOpenCreditNote(invoice)}>
            Nota de crédito
          </ErpButton>
        ) : null}
        <ErpButton
          variant="secondary"
          disabled={duplicateInvoice.isPending}
          onClick={() => duplicateInvoice.mutate()}
        >
          {duplicateInvoice.isPending ? 'Duplicando…' : 'Duplicar'}
        </ErpButton>
        {invoice.status === 'REJECTED' || invoice.status === 'NOT_AUTHORIZED' ? (
          <ErpButton variant="danger" onClick={() => setArchiving(true)}>Archivar</ErpButton>
        ) : null}
        <ErpButton
          variant="primary"
          disabled={!canIssue || issueInvoice.isPending}
          onClick={() => issueInvoice.mutate()}
        >
          {issueInvoice.isPending ? 'Emitiendo…' : 'Emitir'}
        </ErpButton>
      </div>
    </section>
  )
}

function InvoicesPage({
  token,
  customers,
  products,
  taxes,
  establishments,
  emissionPoints,
  defaultPaymentTermsDays,
}: {
  token: string
  customers: Party[]
  products: Product[]
  taxes: TaxCategory[]
  establishments: Establishment[]
  emissionPoints: EmissionPoint[]
  defaultPaymentTermsDays: number
}) {
  const queryClient = useQueryClient()
  const [panel, setPanel] = useState<InvoicePanel | undefined>(undefined)
  const [archiveTarget, setArchiveTarget] = useState<SalesDocument | null>(null)
  const [archiveReason, setArchiveReason] = useState('Prueba de emisión SRI; comprobante no autorizado.')
  const lastTriggerRef = useRef<HTMLElement | null>(null)
  const invoicesQuery = useQuery({
    queryKey: ['invoices'],
    queryFn: () => apiRequest<SalesDocument[]>(token, '/invoices'),
  })
  const invoices = invoicesQuery.data ?? []
  const invoiceMonths = invoices.reduce<Record<string, SalesDocument[]>>((groups, invoice) => {
    const key = invoice.issueDate.slice(0, 7)
    ;(groups[key] ??= []).push(invoice)
    return groups
  }, {})
  const invoiceMonthEntries = Object.entries(invoiceMonths).sort(([left], [right]) => right.localeCompare(left))
  const partiesById = new Map(customers.map((party) => [party.id, party]))
  const archiveInvoice = useMutation({
    mutationFn: () => {
      if (!archiveTarget) throw new Error('No hay comprobante seleccionado para archivar.')
      return apiRequest<SalesDocument>(token, `/invoices/${archiveTarget.id}/archive`, {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey('web-archive-invoice') },
        body: JSON.stringify({ reason: archiveReason.trim() }),
      })
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['invoices'] })
      setArchiveTarget(null)
    },
  })

  function openPanel(next: InvoicePanel, trigger?: HTMLElement) {
    lastTriggerRef.current = trigger ?? null
    setPanel(next)
  }

  function closePanel() {
    setPanel(undefined)
    lastTriggerRef.current?.focus()
  }

  if (panel?.view === 'new') {
    return (
      <>
        <ErpPageHeader eyebrow="Facturación electrónica" title="Nueva factura" subtitle="Crea el borrador; los totales serán calculados y validados por el servidor." />
        <NewInvoiceForm token={token} customers={customers} products={products} taxes={taxes} establishments={establishments} emissionPoints={emissionPoints} defaultPaymentTermsDays={defaultPaymentTermsDays} onCreated={(invoiceId) => setPanel({ view: 'detail', id: invoiceId })} onCancel={closePanel} />
      </>
    )
  }
  if (panel?.view === 'detail') {
    return <InvoiceDetail key={panel.id} token={token} invoiceId={panel.id} customers={customers} establishments={establishments} emissionPoints={emissionPoints} onClose={closePanel} onOpenCreditNote={(invoice) => setPanel({ view: 'credit-note', invoice })} onDuplicated={(invoiceId) => setPanel({ view: 'detail', id: invoiceId })} />
  }
  if (panel?.view === 'credit-note') {
    return (
      <>
        <ErpPageHeader eyebrow="Facturación electrónica" title="Nueva nota de crédito" subtitle={`Documento relacionado con la factura ${panel.invoice.sequential}.`} />
        <CreditNoteForm token={token} invoice={panel.invoice} onCreated={() => setPanel({ view: 'detail', id: panel.invoice.id })} onCancel={() => setPanel({ view: 'detail', id: panel.invoice.id })} />
      </>
    )
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
      <section className="split-layout erp-list-only">
        <ErpPanel title="Documentos" count={invoices.length}>
          <div className="invoice-month-list" aria-label="Listado de facturas">
            {invoiceMonthEntries.map(([month, monthInvoices], index) => <details key={month} className="invoice-month-accordion" open={index === 0}>
              <summary>
                <span className="invoice-month-title">{new Date(`${month}-01T12:00:00`).toLocaleDateString('es-EC', { month: 'long', year: 'numeric' })}</span>
                <span className="invoice-month-summary">{monthInvoices.length} factura{monthInvoices.length === 1 ? '' : 's'} · ${formatAmount(monthInvoices.reduce((total, invoice) => total + Number(invoice.total), 0))}</span>
              </summary>
            <div className="table-wrap" tabIndex={0} aria-label={`Facturas de ${month}`}>
              <table className="erp-responsive-table">
              <thead>
                <tr>
                  <th>Número</th>
                  <th>Cliente</th>
                  <th>Fecha</th>
                  <th>Estado</th>
                  <th>Cobro</th>
                  <th>Retenciones</th>
                  <th>Total</th>
                  <th>Acciones</th>
                </tr>
              </thead>
              <tbody>
                {monthInvoices.map((invoice) => (
                  <tr key={invoice.id}>
                    <td><strong>{invoice.sequential}</strong></td>
                    <td>{partiesById.get(invoice.partyId)?.name ?? '—'}</td>
                    <td>{invoice.issueDate}</td>
                    <td><InvoiceStatusBadge status={invoice.status} /></td>
                    <td><CollectionStatusBadge status={invoice.collectionStatus} /></td>
                    <td><ErpStatusBadge tone={Number(invoice.retentionTotal) > 0 ? 'success' : 'neutral'}>{Number(invoice.retentionTotal) > 0 ? `$${formatAmount(invoice.retentionTotal)}` : 'Sin retención'}</ErpStatusBadge></td>
                    <td>${formatAmount(invoice.total)}</td>
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
                        {invoice.status === 'REJECTED' || invoice.status === 'NOT_AUTHORIZED' ? (
                          <ErpButton variant="danger" onClick={() => setArchiveTarget(invoice)}>
                            Archivar
                          </ErpButton>
                        ) : null}
                      </ErpActionCell>
                    </td>
                  </tr>
                ))}
              </tbody>
              </table>
            </div>
            </details>)}
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
      </section>
      {archiveTarget ? (
        <ErpModal title={`Archivar comprobante ${archiveTarget.sequential}`} size="sm" onClose={() => setArchiveTarget(null)}>
          <p className="fine-print">Se ocultará de Facturas y conservará XML, RIDE, respuesta SRI y auditoría.</p>
          <label>
            Motivo de archivo
            <textarea value={archiveReason} onChange={(event) => setArchiveReason(event.target.value)} minLength={3} maxLength={500} required />
          </label>
          {archiveInvoice.error ? <p className="form-error" role="alert">{archiveInvoice.error.message}</p> : null}
          <div className="erp-form-actions">
            <ErpButton variant="secondary" onClick={() => setArchiveTarget(null)} disabled={archiveInvoice.isPending}>Cancelar</ErpButton>
            <ErpButton variant="danger" onClick={() => archiveInvoice.mutate()} disabled={archiveInvoice.isPending || archiveReason.trim().length < 3}>
              {archiveInvoice.isPending ? 'Archivando…' : 'Archivar'}
            </ErpButton>
          </div>
        </ErpModal>
      ) : null}
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

type ReceivablePanel =
  | { view: 'payment'; receivable: AccountItem }
  | { view: 'reminder'; receivable: AccountItem }
  | { view: 'due-date'; receivable: AccountItem }
  | { view: 'history'; receivable: AccountItem }
  | { view: 'retention-batch' }
  | { view: 'bank-statement' }

function emptyRetention(): RetentionInput & { key: string } {
  return { key: crypto.randomUUID(), kind: 'RETENTION_IVA', amount: '0.00', reason: '', documentReference: '' }
}

function emptyDiscount(): DiscountInput & { key: string } {
  return { key: crypto.randomUUID(), amount: '0.00', reason: '' }
}

function BatchRetentionImportForm({
  token,
  onRegistered,
  onCancel,
}: {
  token: string
  onRegistered: () => void
  onCancel: () => void
}) {
  const [files, setFiles] = useState<File[]>([])
  const [preview, setPreview] = useState<RetentionBatch | null>(null)
  const [registered, setRegistered] = useState(false)

  function batchFormData(apply: boolean) {
    const formData = new FormData()
    files.forEach((file) => formData.append('files', file))
    formData.append('apply', String(apply))
    return formData
  }

  const previewBatch = useMutation({
    mutationFn: () => {
      if (files.length === 0) throw new Error('Selecciona al menos un XML de retención.')
      return apiRequest<RetentionBatch>(token, '/receivables/retention-batch', {
        method: 'POST',
        body: batchFormData(false),
      })
    },
    onSuccess: (result) => {
      setPreview(result)
      setRegistered(false)
    },
  })
  const registerBatch = useMutation({
    mutationFn: () => apiRequest<RetentionBatch>(token, '/receivables/retention-batch', {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey('web-retention-batch') },
      body: batchFormData(true),
    }),
    onSuccess: (result) => {
      setPreview(result)
      setRegistered(true)
      onRegistered()
    },
  })
  const matched = preview?.items.filter((item) => item.status === 'MATCHED') ?? []

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    previewBatch.mutate()
  }

  return (
    <ErpFormPanel
      eyebrow="Cobranzas"
      title="Cargar retenciones XML"
      submitLabel="Revisar XML"
      pendingLabel="Revisando…"
      pending={previewBatch.isPending}
      error={previewBatch.error?.message}
      onSubmit={submit}
      onCancel={onCancel}
    >
      <p className="fine-print">Carga hasta 50 XML autorizados por SRI. No guardamos los archivos: leemos sus datos, los cruzamos con la factura y solo registramos los que confirmes.</p>
      <label>
        XML de comprobantes de retención
        <input
          type="file"
          accept=".xml,text/xml,application/xml"
          multiple
          onChange={(event) => {
            setFiles(Array.from(event.target.files ?? []))
            setPreview(null)
            setRegistered(false)
          }}
        />
      </label>
      {files.length > 0 ? <p className="fine-print">{files.length} archivo{files.length === 1 ? '' : 's'} seleccionado{files.length === 1 ? '' : 's'}.</p> : null}
      {preview ? (
        <section className="retention-batch-results" aria-live="polite">
          <div className="retention-batch-heading">
            <h3>Resultado de la revisión</h3>
            <span>{matched.length} listo{matched.length === 1 ? '' : 's'} · {preview.items.length - matched.length} a revisar</span>
          </div>
          <div className="table-wrap" tabIndex={0} aria-label="Resultado de XML de retención">
            <table className="erp-responsive-table">
              <thead><tr><th>Archivo</th><th>Factura</th><th>Emisión</th><th>Retención</th><th>Valor</th><th>Resultado</th></tr></thead>
              <tbody>
                {preview.items.map((item) => (
                  <tr key={item.fileName}>
                    <td>{item.fileName}</td>
                    <td>{item.invoiceSequential ?? item.supportingDocument ?? '—'}</td>
                    <td>{item.issueDate ?? '—'}</td>
                    <td>{item.authorizationNumber ?? '—'}</td>
                    <td>${formatAmount(item.total)}</td>
                    <td><ErpStatusBadge tone={item.status === 'MATCHED' ? 'success' : 'warning'}>{item.detail}</ErpStatusBadge></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {registerBatch.error ? <p className="form-error" role="alert">{registerBatch.error.message}</p> : null}
          {registered ? <p className="fine-print">Las retenciones mostradas como registradas ya redujeron el saldo de su factura. Las restantes no se modificaron.</p> : null}
          {!registered ? (
            <ErpButton variant="primary" disabled={matched.length === 0 || registerBatch.isPending} onClick={() => registerBatch.mutate()}>
              {registerBatch.isPending ? 'Registrando…' : `Registrar ${matched.length} retención${matched.length === 1 ? '' : 'es'}`}
            </ErpButton>
          ) : null}
        </section>
      ) : null}
    </ErpFormPanel>
  )
}

function BankStatementImportForm({
  token,
  onRegistered,
  onCancel,
}: {
  token: string
  onRegistered: () => void
  onCancel: () => void
}) {
  const [period, setPeriod] = useState(() => {
    const previousMonth = new Date()
    previousMonth.setDate(1)
    previousMonth.setMonth(previousMonth.getMonth() - 1)
    return `${previousMonth.getFullYear()}-${String(previousMonth.getMonth() + 1).padStart(2, '0')}`
  })
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<BankStatementImport | null>(null)
  const [registered, setRegistered] = useState(false)

  function statementFormData(apply: boolean) {
    if (!file) throw new Error('Selecciona el TXT del banco.')
    const formData = new FormData()
    formData.append('file', file)
    formData.append('period', period)
    formData.append('apply', String(apply))
    return formData
  }

  const previewStatement = useMutation({
    mutationFn: () => apiRequest<BankStatementImport>(token, '/receivables/bank-statement', {
      method: 'POST',
      body: statementFormData(false),
    }),
    onSuccess: (result) => {
      setPreview(result)
      setRegistered(false)
    },
  })
  const registerMatches = useMutation({
    mutationFn: () => apiRequest<BankStatementImport>(token, '/receivables/bank-statement', {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey('web-bank-statement') },
      body: statementFormData(true),
    }),
    onSuccess: (result) => {
      setPreview(result)
      setRegistered(true)
      onRegistered()
    },
  })

  return (
    <ErpFormPanel
      eyebrow="Cobranzas"
      title="Conciliar estado bancario"
      submitLabel="Revisar movimientos"
      pendingLabel="Revisando…"
      pending={previewStatement.isPending}
      error={previewStatement.error?.message}
      onSubmit={(event) => { event.preventDefault(); previewStatement.mutate() }}
      onCancel={onCancel}
    >
      <p className="fine-print">El TXT se procesa en memoria. Ignoramos débitos y solo proponemos abonos que saldan una única factura autorizada, con sus retenciones ya descontadas. Si existe un cobro manual sin referencia, el banco lo reemplaza mediante un reverso auditable. Nada se registra hasta que confirmes.</p>
      <label>
        Período a conciliar
        <input
          type="month"
          required
          value={period}
          onChange={(event) => {
            setPeriod(event.target.value)
            setPreview(null)
            setRegistered(false)
          }}
        />
      </label>
      <label>
        Estado de cuenta bancario
        <input
          type="file"
          accept=".txt,text/plain"
          required
          onChange={(event) => {
            setFile(event.target.files?.[0] ?? null)
            setPreview(null)
            setRegistered(false)
          }}
        />
      </label>
      {file ? <p className="fine-print">Archivo seleccionado: {file.name}</p> : null}
      {preview ? (
        <section className="retention-batch-results" aria-live="polite">
          <div className="retention-batch-heading">
            <h3>Resultado de la conciliación</h3>
            <span>{preview.matchedCount} coincidencia{preview.matchedCount === 1 ? '' : 's'} · {preview.manualCorrectionCount} {preview.manualCorrectionCount === 1 ? 'corrección' : 'correcciones'} · {preview.unmatchedCreditCount} abono{preview.unmatchedCreditCount === 1 ? '' : 's'} sin aplicar</span>
          </div>
          <p className="fine-print">Período {preview.period}. Se leyeron {preview.totalRows} movimientos: {preview.creditRows} abonos del período, {preview.outsidePeriodCreditCount} de otros meses, {preview.ignoredDebitCount} débitos ignorados y {preview.alreadyImportedCount} abono{preview.alreadyImportedCount === 1 ? '' : 's'} ya registrado{preview.alreadyImportedCount === 1 ? '' : 's'}.</p>
          {preview.matches.length > 0 ? (
            <div className="table-wrap" tabIndex={0} aria-label="Coincidencias del estado bancario">
              <table className="erp-responsive-table">
                <thead><tr><th>Fecha</th><th>Referencia bancaria</th><th>Factura</th><th>Original</th><th>Retenciones</th><th>Abono</th><th>Resultado</th></tr></thead>
                <tbody>
                  {preview.matches.map((match) => (
                    <tr key={match.transactionId}>
                      <td>{match.paymentDate}</td>
                      <td>{match.reference}</td>
                      <td>{match.invoiceSequential}</td>
                      <td>${formatAmount(match.originalAmount)}</td>
                      <td>${formatAmount(match.retentionTotal)}</td>
                      <td>${formatAmount(match.amount)}</td>
                      <td><ErpStatusBadge tone="success">{match.detail}</ErpStatusBadge></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          {preview.manualCorrections.length > 0 ? (
            <div className="table-wrap" tabIndex={0} aria-label="Correcciones de cobros manuales">
              <table className="erp-responsive-table">
                <thead><tr><th>Fecha banco</th><th>Referencia</th><th>Factura correcta</th><th>Factura manual</th><th>Valor</th><th>Resultado</th></tr></thead>
                <tbody>
                  {preview.manualCorrections.map((correction) => (
                    <tr key={`${correction.transactionId}-${correction.manualMovementId}`}>
                      <td>{correction.paymentDate}</td>
                      <td>{correction.reference}</td>
                      <td>{correction.targetInvoiceSequential}</td>
                      <td>{correction.manualInvoiceSequential}</td>
                      <td>${formatAmount(correction.amount)}</td>
                      <td><ErpStatusBadge tone={correction.status === 'CORRECTED' ? 'success' : 'warning'}>{correction.detail}</ErpStatusBadge></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          {preview.matches.length === 0 && preview.manualCorrections.length === 0 ? (
            <ErpEmptyState title="Sin coincidencias exactas" description="Los abonos dudosos o sin una factura única no modificaron Cartera." />
          ) : null}
          {registerMatches.error ? <p className="form-error" role="alert">{registerMatches.error.message}</p> : null}
          {registered ? <p className="fine-print">La conciliación terminó. Solo los cobros indicados como registrados modificaron Cartera.</p> : null}
          {!registered ? (
            <ErpButton variant="primary" disabled={(preview.matchedCount + preview.manualCorrectionCount) === 0 || registerMatches.isPending} onClick={() => registerMatches.mutate()}>
              {registerMatches.isPending ? 'Registrando…' : `Confirmar ${preview.matchedCount + preview.manualCorrectionCount} cambio${(preview.matchedCount + preview.manualCorrectionCount) === 1 ? '' : 's'}`}
            </ErpButton>
          ) : null}
        </section>
      ) : null}
    </ErpFormPanel>
  )
}

function ReceivableMovementHistory({
  token,
  receivable,
  onClose,
}: {
  token: string
  receivable: AccountItem
  onClose: () => void
}) {
  const movementsQuery = useQuery({
    queryKey: ['receivables', receivable.id, 'movements'],
    queryFn: () => apiRequest<ReceivableMovement[]>(token, `/receivables/${receivable.id}/movements`),
  })
  const movementLabels: Record<ReceivableMovement['movementType'], string> = {
    PAYMENT: 'Cobro',
    RETENTION: 'Retención',
    DISCOUNT: 'Descuento',
    CREDIT_NOTE: 'Nota de crédito',
    REVERSAL: 'Reverso',
  }

  return (
    <section className="form-panel erp-form-panel erp-full-page-form">
      <p className="section-number">Cobranzas</p>
      <h2>Movimientos de factura {receivable.invoiceSequential ?? '—'}</h2>
      <p className="fine-print">Cliente y factura se relacionan por esta cuenta por cobrar. Cada retención muestra su autorización SRI en la referencia.</p>
      {movementsQuery.isPending ? <p>Cargando movimientos…</p> : null}
      {movementsQuery.error ? <p className="form-error" role="alert">{movementsQuery.error.message}</p> : null}
      {movementsQuery.data ? (
        movementsQuery.data.length > 0 ? (
          <div className="table-wrap" tabIndex={0} aria-label="Movimientos de la factura">
            <table className="erp-responsive-table">
              <thead><tr><th>Fecha</th><th>Tipo</th><th>Valor</th><th>Referencia</th></tr></thead>
              <tbody>
                {movementsQuery.data.map((movement) => (
                  <tr key={movement.id}>
                    <td>{movement.effectiveDate
                      ? movement.effectiveDate.split('-').reverse().join('/')
                      : new Date(movement.createdAt).toLocaleString('es-EC')}</td>
                    <td><ErpStatusBadge tone={movement.movementType === 'RETENTION' ? 'success' : 'neutral'}>{movementLabels[movement.movementType]}</ErpStatusBadge></td>
                    <td>${formatAmount(movement.amount)}</td>
                    <td>{movement.supportReference ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <ErpEmptyState title="Sin movimientos" description="Todavía no se ha registrado ningún cobro, retención o descuento." />
      ) : null}
      <div className="erp-form-actions"><ErpButton variant="secondary" onClick={onClose}>Volver a Cartera</ErpButton></div>
    </section>
  )
}

function EditReceivableDueDateForm({
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
  const [dueDate, setDueDate] = useState(receivable.dueDate ?? '')
  const [reason, setReason] = useState('Corrección de condición de pago de factura histórica.')
  const updateDueDate = useMutation({
    mutationFn: () => apiRequest<AccountItem>(token, `/receivables/${receivable.id}/due-date`, {
      method: 'PUT',
      headers: { 'Idempotency-Key': idempotencyKey('web-receivable-due-date') },
      body: JSON.stringify({ dueDate, reason } satisfies ReceivableDueDateUpdate),
    }),
    onSuccess: onSaved,
  })
  return (
    <ErpFormPanel eyebrow="Cartera" title="Corregir vencimiento" submitLabel="Guardar vencimiento" pending={updateDueDate.isPending} error={updateDueDate.error?.message} onSubmit={(event) => { event.preventDefault(); updateDueDate.mutate() }} onCancel={onCancel}>
      <p className="fine-print">Corrige el plan comercial y la cartera. No modifica XML, autorización ni RIDE SRI.</p>
      <label>Nuevo vencimiento<input type="date" value={dueDate} onChange={(event) => setDueDate(event.target.value)} required /></label>
      <label>Motivo<textarea value={reason} onChange={(event) => setReason(event.target.value)} minLength={3} maxLength={500} required /></label>
    </ErpFormPanel>
  )
}

function RegisterPaymentForm({
  token,
  receivable,
  party,
  onSaved,
  onCancel,
}: {
  token: string
  receivable: AccountItem
  party: Party | undefined
  onSaved: (updated: AccountItem) => void
  onCancel: () => void
}) {
  const profileIsAvailable = party?.expectedIvaWithholdingRate != null || party?.expectedIncomeWithholdingRate != null
  const expectedIva = profileIsAvailable ? Number(receivable.originalAmount) * Number(party?.expectedIvaWithholdingRate ?? 0) / 100 : 0
  const expectedIncome = profileIsAvailable ? Number(receivable.originalAmount) * Number(party?.expectedIncomeWithholdingRate ?? 0) / 100 : 0
  const expectedRetentionTotal = expectedIva + expectedIncome
  const canPrefill = profileIsAvailable && Number(receivable.openAmount) === Number(receivable.originalAmount) && expectedRetentionTotal <= Number(receivable.openAmount)
  const [cashAmount, setCashAmount] = useState(() =>
    canPrefill ? (Number(receivable.openAmount) - expectedRetentionTotal).toFixed(2) : '0.00',
  )
  const [paymentDate, setPaymentDate] = useState(() => new Date().toISOString().slice(0, 10))
  const [method, setMethod] = useState<'' | PaymentInput['method']>('')
  const [reference, setReference] = useState('')
  const [retentions, setRetentions] = useState<Array<RetentionInput & { key: string }>>(() => {
    if (!canPrefill) return []
    const suggested: Array<RetentionInput & { key: string }> = []
    if (expectedIva > 0) {
      suggested.push({
        key: crypto.randomUUID(),
        kind: 'RETENTION_IVA',
        amount: expectedIva.toFixed(2),
        reason: `Perfil esperado de ${party?.name ?? 'cliente'}`,
        documentReference: '',
      })
    }
    if (expectedIncome > 0) {
      suggested.push({
        key: crypto.randomUUID(),
        kind: 'RETENTION_RENTA',
        amount: expectedIncome.toFixed(2),
        reason: `Perfil esperado de ${party?.name ?? 'cliente'}`,
        documentReference: '',
      })
    }
    return suggested
  })
  const [discounts, setDiscounts] = useState<Array<DiscountInput & { key: string }>>([])
  const [retentionXmlFile, setRetentionXmlFile] = useState<File | null>(null)

  const previewRetentionXml = useMutation({
    mutationFn: async () => {
      if (!retentionXmlFile) throw new Error('Selecciona el XML de retención autorizado.')
      const formData = new FormData()
      formData.append('file', retentionXmlFile)
      return apiRequest<RetentionXmlPreview>(token, `/receivables/${receivable.id}/retention-preview`, {
        method: 'POST',
        body: formData,
      })
    },
    onSuccess: (preview) => {
      const total = preview.retentions.reduce((sum, retention) => sum + Number(retention.amount), 0)
      setRetentions(preview.retentions.map((retention) => ({
        key: crypto.randomUUID(),
        kind: retention.kind,
        amount: retention.amount,
        reason: `Código SRI ${retention.sriRetentionCode}: ${retention.rate}% sobre $${retention.baseAmount}`,
        documentReference: preview.authorizationNumber,
      })))
      setCashAmount((Number(receivable.openAmount) - total).toFixed(2))
    },
  })

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
      <p className="fine-print">Saldo actual ${formatAmount(receivable.openAmount)}. El saldo final lo calcula el servidor.</p>
      {profileIsAvailable ? <div className="fine-print">Perfil esperado de {party?.name}: IVA {party?.expectedIvaWithholdingRate ?? '0'}% + renta {party?.expectedIncomeWithholdingRate ?? '0'}%. {canPrefill ? <>Valores y neto precargados. Revisa los montos y registra el comprobante de retención antes de guardar.</> : ' No se precarga porque este cobro es parcial o el saldo ya cambió.'}</div> : null}
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
        <legend>Leer XML de retención</legend>
        <p className="fine-print">Carga el XML autorizado por SRI. Validamos que pertenece a este cliente y a esta factura; luego puedes revisar y guardar el cobro.</p>
        <div className="field-row">
          <label>
            XML autorizado
            <input
              type="file"
              accept=".xml,text/xml,application/xml"
              onChange={(event) => setRetentionXmlFile(event.target.files?.[0] ?? null)}
            />
          </label>
          <div className="field-actions">
            <ErpButton
              variant="secondary"
              disabled={!retentionXmlFile || previewRetentionXml.isPending}
              onClick={() => previewRetentionXml.mutate()}
            >
              {previewRetentionXml.isPending ? 'Leyendo XML…' : 'Leer XML'}
            </ErpButton>
          </div>
        </div>
        {previewRetentionXml.error ? <p className="form-error">{previewRetentionXml.error.message}</p> : null}
        {previewRetentionXml.data ? <p className="fine-print">XML autorizado leído. Se cargaron {previewRetentionXml.data.retentions.length} retención(es); aún debes confirmar con Guardar.</p> : null}
      </fieldset>

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
              <label>
                Comprobante de retención
                <input
                  value={retention.documentReference}
                  minLength={3}
                  onChange={(event) => setRetentions((current) => current.map((item) => item.key === retention.key ? { ...item, documentReference: event.target.value } : item))}
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
  const [scheduledAt, setScheduledAt] = useState('')
  const [message, setMessage] = useState('')

  // Se lee la plantilla configurada solo para mostrar qué se va a enviar; el
  // servidor la vuelve a renderizar con los valores reales del receivable.
  const policyQuery = useQuery({
    queryKey: ['receivables', 'collection-policy'],
    queryFn: () => apiRequest<CollectionPolicy>(token, '/receivables/collection-policy'),
  })
  const policy = policyQuery.data

  const sendReminder = useMutation({
    mutationFn: () =>
      apiRequest<Operation>(token, `/receivables/${receivable.id}/reminders`, {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey('web-receivable-reminder') },
        body: JSON.stringify({
          channel,
          // El identificador solo etiqueta el envío en el historial: el texto
          // sale de la plantilla del tenant, no de este campo.
          templateId: channel === 'EMAIL' ? policy?.emailTemplateId : policy?.whatsappTemplateId,
          scheduledAt: scheduledAt ? new Date(scheduledAt).toISOString() : null,
          message: message || null,
        } satisfies ReminderInput),
      }),
    onSuccess: () => onSent(),
  })

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    sendReminder.mutate()
  }

  const missingBankDetails = channel === 'EMAIL' && policy !== undefined && !policy.paymentInstructions

  return (
    <ErpFormPanel
      eyebrow="Cobranza"
      title="Enviar correo de cobro"
      submitLabel={scheduledAt ? 'Programar' : 'Enviar ahora'}
      pendingLabel="Enviando…"
      pending={sendReminder.isPending}
      error={sendReminder.error?.message}
      onSubmit={submit}
      onCancel={onCancel}
    >
      <p className="fine-print">Saldo pendiente ${formatAmount(receivable.openAmount)}.</p>
      <label>
        Canal
        <select value={channel} onChange={(event) => setChannel(event.target.value as ReminderInput['channel'])} required>
          <option value="EMAIL">Correo electrónico</option>
          <option value="WHATSAPP">WhatsApp</option>
        </select>
      </label>
      {channel === 'EMAIL' && policy ? (
        <section className="reminder-template-preview" aria-label="Plantilla que se enviará">
          <p className="fine-print">
            Se envía con la plantilla configurada en <strong>Configuración → Cobranza</strong>.
          </p>
          <dl>
            <div><dt>Asunto</dt><dd>{policy.emailSubject}</dd></div>
            <div><dt>Cuerpo</dt><dd className="reminder-template-body">{message || policy.emailBody}</dd></div>
            <div>
              <dt>Datos para pago</dt>
              <dd className="reminder-template-body">
                {policy.paymentInstructions || 'Sin configurar'}
              </dd>
            </div>
          </dl>
        </section>
      ) : null}
      {missingBankDetails ? (
        <p className="form-warning" role="status">
          Aún no hay datos bancarios configurados: el correo saldrá sin cuenta a la cual
          transferir. Complétalos en Configuración → Cobranza → Datos para pago.
        </p>
      ) : null}
      <label>
        Mensaje personalizado
        <textarea
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          rows={4}
          placeholder="Opcional: reemplaza el cuerpo. El saldo y los datos de pago se agregan igual."
        />
      </label>
      <label>Programar para<input type="datetime-local" value={scheduledAt} onChange={(event) => setScheduledAt(event.target.value)} /></label>
    </ErpFormPanel>
  )
}

function CollectionPolicyEditor({
  policy,
  pending,
  error,
  onSave,
}: {
  policy: CollectionPolicy
  pending: boolean
  error?: string
  onSave: (policy: Omit<CollectionPolicy, 'updatedAt'>) => void
}) {
  const [enabled, setEnabled] = useState(policy.enabled)
  const [offsets, setOffsets] = useState(policy.offsetsDays.join(', '))
  const [channels, setChannels] = useState(policy.channels)
  const [sendHour, setSendHour] = useState(policy.sendHour)
  const [emailTemplateId, setEmailTemplateId] = useState(policy.emailTemplateId)
  const [whatsappTemplateId, setWhatsAppTemplateId] = useState(policy.whatsappTemplateId)
  const [emailSubject, setEmailSubject] = useState(policy.emailSubject)
  const [emailBody, setEmailBody] = useState(policy.emailBody)
  const [paymentInstructions, setPaymentInstructions] = useState(policy.paymentInstructions)

  function toggleChannel(channel: 'EMAIL' | 'WHATSAPP', checked: boolean) {
    setChannels((current) => checked
      ? Array.from(new Set([...current, channel]))
      : current.filter((item) => item !== channel))
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const offsetsDays = offsets
      .split(',')
      .map((value) => Number(value.trim()))
      .filter((value) => Number.isInteger(value) && value >= -365 && value <= 365)
    if (offsetsDays.length === 0 || channels.length === 0) return
    onSave({
      enabled,
      offsetsDays: Array.from(new Set(offsetsDays)).sort((left, right) => left - right),
      channels,
      sendHour,
      emailTemplateId,
      whatsappTemplateId,
      emailSubject,
      emailBody,
      paymentInstructions,
    })
  }

  return (
    <ErpPanel
      title="Cobranza programada"
      actions={<ErpStatusBadge tone={enabled ? 'success' : 'neutral'}>{enabled ? 'Activa' : 'Pausada'}</ErpStatusBadge>}
      className="collection-policy-panel"
    >
      <form className="collection-policy-form" onSubmit={submit}>
        <label className="collection-policy-toggle"><input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} /> Activar mensajes automáticos</label>
        <div className="field-row">
          <label>Hitos en días<input value={offsets} onChange={(event) => setOffsets(event.target.value)} placeholder="-3, 0, 3, 7, 15" required /></label>
          <label>Hora de envío<input type="number" min="0" max="23" value={sendHour} onChange={(event) => setSendHour(Number(event.target.value))} required /></label>
        </div>
        <fieldset className="collection-policy-channels">
          <legend>Canales</legend>
          <label><input type="checkbox" checked={channels.includes('EMAIL')} onChange={(event) => toggleChannel('EMAIL', event.target.checked)} /> Correo</label>
          <label><input type="checkbox" checked={channels.includes('WHATSAPP')} onChange={(event) => toggleChannel('WHATSAPP', event.target.checked)} /> WhatsApp</label>
        </fieldset>
        <div className="field-row">
          <label>Identificador de correo<input value={emailTemplateId} onChange={(event) => setEmailTemplateId(event.target.value)} required /></label>
          <label>Identificador de WhatsApp<input value={whatsappTemplateId} onChange={(event) => setWhatsAppTemplateId(event.target.value)} required /></label>
        </div>
        <label>Asunto del correo<input value={emailSubject} onChange={(event) => setEmailSubject(event.target.value)} required /></label>
        <label>Mensaje del correo<textarea value={emailBody} onChange={(event) => setEmailBody(event.target.value)} rows={6} required /></label>
        <label>Datos para pago<textarea value={paymentInstructions} onChange={(event) => setPaymentInstructions(event.target.value)} rows={4} placeholder="Banco, tipo y número de cuenta, titular y RUC" /></label>
        <p className="fine-print">Puedes usar {'{{cliente}}'}, {'{{empresa}}'}, {'{{saldo}}'}, {'{{vencimiento}}'}, {'{{dias_atraso}}'} y {'{{cuenta_bancaria}}'}. El correo agrega una tabla con saldo, vencimiento, días de atraso y datos para pago.</p>
        <p className="fine-print">Usa valores negativos antes del vencimiento, 0 el día de pago y positivos después.</p>
        {error ? <p className="form-error" role="alert">{error}</p> : null}
        <ErpButton variant="primary" type="submit" disabled={pending || channels.length === 0}>{pending ? 'Guardando…' : 'Guardar reglas'}</ErpButton>
      </form>
    </ErpPanel>
  )
}

function InvoiceEmailTemplateEditor({
  template,
  pending,
  error,
  onSave,
}: {
  template: InvoiceEmailTemplate
  pending: boolean
  error?: string
  onSave: (template: Pick<InvoiceEmailTemplate, 'subject' | 'body' | 'fromAddress' | 'fromName'>) => void
}) {
  const [subject, setSubject] = useState(template.subject)
  const [body, setBody] = useState(template.body)
  const [fromAddress, setFromAddress] = useState(template.fromAddress ?? '')
  const [fromName, setFromName] = useState(template.fromName ?? '')

  return (
    <form
      className="fiscal-panel-body"
      onSubmit={(event) => {
        event.preventDefault()
        onSave({
          subject: subject.trim(),
          body: body.trim(),
          fromAddress: fromAddress.trim() || null,
          fromName: fromName.trim() || null,
        })
      }}
    >
      <p className="fiscal-panel-copy">
        Esta plantilla se usa al entregar una factura autorizada. No corresponde a cobranza ni envía nada por sí sola.
      </p>
      <div className="field-row">
        <label>
          Correo remitente
          <input
            type="email"
            value={fromAddress}
            onChange={(event) => setFromAddress(event.target.value)}
            placeholder="contabilidad@empresa.com"
          />
        </label>
        <label>
          Nombre del remitente
          <input
            value={fromName}
            onChange={(event) => setFromName(event.target.value)}
            maxLength={200}
            placeholder="Contabilidad"
          />
        </label>
      </div>
      <p className="fine-print">
        El correo debe estar habilitado en Gmail como “Enviar como”. Si lo dejas vacío, se usa la cuenta conectada.
      </p>
      <label>
        Asunto
        <input value={subject} onChange={(event) => setSubject(event.target.value)} maxLength={500} required />
      </label>
      <label>
        Mensaje
        <textarea value={body} onChange={(event) => setBody(event.target.value)} rows={10} maxLength={5000} required />
      </label>
      <p className="fine-print">
        Datos disponibles: {template.availableVariables.join(', ')}. El plazo, vencimiento y total salen de la factura guardada.
      </p>
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      <ErpButton variant="primary" type="submit" disabled={pending || !subject.trim() || !body.trim()}>
        {pending ? 'Guardando…' : 'Guardar plantilla de factura'}
      </ErpButton>
    </form>
  )
}

/**
 * Cuánto del cobro entró en dinero y cuánto se fue en retenciones.
 *
 * Sin esta separación el total cobrado se lee como liquidez, y no lo es: la
 * retención es valor que el cliente retuvo y que se recupera ante el SRI, no en
 * caja. Los importes vienen calculados del servidor (`GET /receivables/collections`),
 * con la misma regla de movimientos activos que el saldo.
 */
function CollectionsBreakdownStrip({ breakdown }: { breakdown?: CollectionsBreakdown }) {
  if (!breakdown) return null

  return (
    <section aria-label="Desglose del cobro">
      <dl className="collections-breakdown">
        <div>
          <dt>Cobrado en dinero</dt>
          <dd>
            ${formatAmount(breakdown.cashAmount)}
            <small>{breakdown.cashCount} cobro(s) recibidos en banco o caja</small>
          </dd>
        </div>
        <div>
          <dt>Retenciones</dt>
          <dd>
            ${formatAmount(breakdown.retentionAmount)}
            <small>{breakdown.retentionCount} comprobante(s); se recuperan ante el SRI</small>
          </dd>
        </div>
        <div>
          <dt>Total saldado</dt>
          <dd>
            ${formatAmount(breakdown.settledAmount)}
            <small>{formatAmount(breakdown.retentionShare)} % del cobro fue retención</small>
          </dd>
        </div>
        {Number(breakdown.creditAmount) > 0 ? (
          <div>
            <dt>Notas de crédito y descuentos</dt>
            <dd>
              ${formatAmount(breakdown.creditAmount)}
              <small>Bajan la deuda sin que entre dinero</small>
            </dd>
          </div>
        ) : null}
      </dl>
    </section>
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
  const [statusFilter, setStatusFilter] = useState<'' | 'OUTSTANDING' | AccountItemStatus>('OUTSTANDING')
  const [panel, setPanel] = useState<ReceivablePanel | undefined>(undefined)
  const lastTriggerRef = useRef<HTMLElement | null>(null)
  const partiesById = new Map(parties.map((party) => [party.id, party]))
  const receivablesQuery = useQuery({
    queryKey: ['receivables', statusFilter],
    queryFn: () =>
      apiRequest<AccountItem[]>(
        token,
        statusFilter && statusFilter !== 'OUTSTANDING' ? `/receivables?status=${statusFilter}` : '/receivables',
      ),
  })
  const receivables = (receivablesQuery.data ?? []).filter((item) =>
    statusFilter === 'OUTSTANDING'
      ? ['OPEN', 'PARTIAL', 'OVERDUE'].includes(item.status)
      : true,
  )
  const collectionsQuery = useQuery({
    queryKey: ['receivables', 'collections'],
    queryFn: () => apiRequest<CollectionsBreakdown>(token, '/receivables/collections'),
  })

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
    closePanel()
  }

  if (panel?.view === 'payment') {
    return (
      <>
        <ErpPageHeader eyebrow="Cuentas por cobrar" title="Registrar cobro" subtitle={`Saldo actual: $${formatAmount(panel.receivable.openAmount)}`} />
        <RegisterPaymentForm key={panel.receivable.id} token={token} receivable={panel.receivable} party={partiesById.get(panel.receivable.partyId)} onSaved={applyUpdatedReceivable} onCancel={closePanel} />
      </>
    )
  }
  if (panel?.view === 'reminder') {
    return (
      <>
        <ErpPageHeader eyebrow="Cuentas por cobrar" title="Enviar correo de cobro" subtitle={`Saldo pendiente: $${formatAmount(panel.receivable.openAmount)}`} />
        <SendReminderForm key={panel.receivable.id} token={token} receivable={panel.receivable} onSent={closePanel} onCancel={closePanel} />
      </>
    )
  }
  if (panel?.view === 'due-date') {
    return (
      <>
        <ErpPageHeader eyebrow="Cuentas por cobrar" title="Corregir vencimiento" subtitle={`Vencimiento actual: ${panel.receivable.dueDate ?? 'Sin fecha'}`} />
        <EditReceivableDueDateForm key={panel.receivable.id} token={token} receivable={panel.receivable} onSaved={applyUpdatedReceivable} onCancel={closePanel} />
      </>
    )
  }
  if (panel?.view === 'history') {
    return (
      <>
        <ErpPageHeader eyebrow="Cuentas por cobrar" title="Movimientos" subtitle={`Factura ${panel.receivable.invoiceSequential ?? 'sin número disponible'}`} />
        <ReceivableMovementHistory token={token} receivable={panel.receivable} onClose={closePanel} />
      </>
    )
  }
  if (panel?.view === 'retention-batch') {
    return (
      <>
        <ErpPageHeader eyebrow="Cuentas por cobrar" title="Cargar retenciones" subtitle="Cruza cada XML autorizado con su factura y registra solo los comprobantes confirmados." />
        <BatchRetentionImportForm
          token={token}
          onRegistered={() => void queryClient.invalidateQueries({ queryKey: ['receivables'] })}
          onCancel={closePanel}
        />
      </>
    )
  }
  if (panel?.view === 'bank-statement') {
    return (
      <>
        <ErpPageHeader eyebrow="Cuentas por cobrar" title="Conciliar banco" subtitle="Registra únicamente abonos que cuadran de forma única con una factura autorizada." />
        <BankStatementImportForm
          token={token}
          onRegistered={() => void queryClient.invalidateQueries({ queryKey: ['receivables'] })}
          onCancel={closePanel}
        />
      </>
    )
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
            onChange={(event) => setStatusFilter(event.target.value as '' | 'OUTSTANDING' | AccountItemStatus)}
          >
            <option value="OUTSTANDING">Pendientes (abiertas, parciales y vencidas)</option>
            <option value="OPEN">Abierta</option>
            <option value="PARTIAL">Parcial</option>
            <option value="OVERDUE">Vencida</option>
            <option value="SETTLED">Saldada</option>
            <option value="VOIDED">Anulada</option>
            <option value="">Todos los estados</option>
          </select>
        </label>
        <ErpButton variant="primary" onClick={(event) => openPanel({ view: 'retention-batch' }, event.currentTarget)}>
          Cargar retenciones XML
        </ErpButton>
        <ErpButton variant="secondary" onClick={(event) => openPanel({ view: 'bank-statement' }, event.currentTarget)}>
          Cargar estado bancario
        </ErpButton>
      </ErpToolbar>
      <CollectionsBreakdownStrip breakdown={collectionsQuery.data} />
      <section className="split-layout erp-list-only">
        <ErpPanel title="Cuentas por cobrar" count={receivables.length}>
          <div className="table-wrap" tabIndex={0} aria-label="Listado de cuentas por cobrar">
            <table className="erp-responsive-table">
              <thead>
                <tr>
                  <th>Cliente</th>
                  <th>Factura</th>
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
                    <td>{receivable.invoiceSequential ?? '—'}</td>
                    <td>${formatAmount(receivable.originalAmount)}</td>
                    <td>${formatAmount(receivable.openAmount)}</td>
                    <td><ReceivableStatusBadge status={receivable.status} /></td>
                    <td><AgingChip dueDate={receivable.dueDate} /></td>
                    <td>
                      {/* Iconos y no texto: cuatro acciones escritas empujaban la
                          tabla a lo ancho y tapaban el saldo. El nombre completo
                          sigue disponible en aria-label y en el tooltip. */}
                      <ErpActionCell>
                        <ErpButton
                          variant="ghost"
                          className="erp-icon-button"
                          aria-label={`Registrar cobro para ${partiesById.get(receivable.partyId)?.name ?? receivable.partyId}`}
                          title="Registrar cobro"
                          onClick={(event) => openPanel({ view: 'payment', receivable }, event.currentTarget)}
                          disabled={receivable.status === 'SETTLED' || receivable.status === 'VOIDED'}
                        >
                          <DollarSign size={16} aria-hidden="true" />
                        </ErpButton>
                        <ErpButton
                          variant="ghost"
                          className="erp-icon-button"
                          aria-label={`Ver movimientos de ${partiesById.get(receivable.partyId)?.name ?? receivable.partyId}`}
                          title="Ver movimientos"
                          onClick={(event) => openPanel({ view: 'history', receivable }, event.currentTarget)}
                        >
                          <History size={16} aria-hidden="true" />
                        </ErpButton>
                        <ErpButton
                          variant="ghost"
                          className="erp-icon-button"
                          aria-label={`Enviar correo de cobro a ${partiesById.get(receivable.partyId)?.name ?? receivable.partyId}`}
                          title="Enviar correo de cobro"
                          onClick={(event) => openPanel({ view: 'reminder', receivable }, event.currentTarget)}
                          disabled={receivable.status === 'SETTLED' || receivable.status === 'VOIDED'}
                        >
                          <Mail size={16} aria-hidden="true" />
                        </ErpButton>
                        <ErpButton
                          variant="ghost"
                          className="erp-icon-button"
                          aria-label={`Editar vencimiento de ${partiesById.get(receivable.partyId)?.name ?? receivable.partyId}`}
                          title="Editar vencimiento"
                          onClick={(event) => openPanel({ view: 'due-date', receivable }, event.currentTarget)}
                          disabled={receivable.status === 'SETTLED' || receivable.status === 'VOIDED'}
                        >
                          <CalendarClock size={16} aria-hidden="true" />
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
      </section>
    </>
  )
}

function OrganizationPage({
  context,
  establishments,
  token,
}: {
  context: TenantContext
  establishments: Establishment[]
  token: string
}) {
  const queryClient = useQueryClient()
  const [settingsSection, setSettingsSection] = useState<'fiscal' | 'invoicing' | 'collections' | 'integrations'>('fiscal')
  const fiscalQuery = useQuery({
    queryKey: ['organization', 'fiscal-settings'],
    queryFn: () => apiRequest<FiscalSettings>(token, '/organization/fiscal-settings'),
  })
  const integrationsQuery = useQuery({
    queryKey: ['crm', 'integrations'],
    queryFn: () => apiRequest<IntegrationStatus>(token, '/crm/integrations'),
  })
  const collectionPolicyQuery = useQuery({
    queryKey: ['receivables', 'collection-policy'],
    queryFn: () => apiRequest<CollectionPolicy>(token, '/receivables/collection-policy'),
  })
  const invoiceEmailTemplateQuery = useQuery({
    queryKey: ['organization', 'invoice-email-template'],
    queryFn: () => apiRequest<InvoiceEmailTemplate>(token, '/organization/invoice-email-template'),
  })
  const updateInvoiceEmailTemplate = useMutation({
    mutationFn: (template: Pick<InvoiceEmailTemplate, 'subject' | 'body' | 'fromAddress' | 'fromName'>) =>
      apiRequest<InvoiceEmailTemplate>(token, '/organization/invoice-email-template', {
        method: 'PUT',
        headers: { 'Idempotency-Key': idempotencyKey('web-invoice-email-template') },
        body: JSON.stringify(template),
      }),
    onSuccess: (template) => queryClient.setQueryData(['organization', 'invoice-email-template'], template),
  })
  const updateCollectionPolicy = useMutation({
    mutationFn: (policy: Omit<CollectionPolicy, 'updatedAt'>) => apiRequest<CollectionPolicy>(token, '/receivables/collection-policy', {
      method: 'PUT',
      headers: { 'Idempotency-Key': idempotencyKey('web-collection-policy') },
      body: JSON.stringify(policy),
    }),
    onSuccess: (policy) => queryClient.setQueryData(['receivables', 'collection-policy'], policy),
  })
  const updateProfile = useMutation({
    mutationFn: (data: Omit<OrganizationProfile, 'tenantId'>) =>
      apiRequest<OrganizationProfile>(token, '/organization/profile', {
        method: 'PUT',
        headers: { 'Idempotency-Key': idempotencyKey('web-organization-profile') },
        body: JSON.stringify(data),
      }),
    onSuccess: (profile) => {
      queryClient.setQueryData<TenantContext>(['context'], (current) => current ? {
        ...current,
        name: profile.name,
        ruc: profile.ruc,
        defaultPaymentTermsDays: profile.defaultPaymentTermsDays,
      } : current)
    },
  })
  const connectGoogle = useMutation({
    mutationFn: () => apiRequest<{ authorizationUrl: string }>(token, '/crm/integrations/google/authorize', { method: 'POST' }),
    onSuccess: ({ authorizationUrl }) => window.location.assign(authorizationUrl),
  })
  const saveWhatsApp = useMutation({
    mutationFn: (data: object) => apiRequest<IntegrationStatus>(token, '/crm/integrations/whatsapp', { method: 'PUT', body: JSON.stringify(data) }),
    onSuccess: (status) => queryClient.setQueryData(['crm', 'integrations'], status),
  })
  const [evolutionWebhookUrl, setEvolutionWebhookUrl] = useState<string | null>(null)
  const [evolutionQrCode, setEvolutionQrCode] = useState<string | null>(null)
  const saveEvolutionWhatsApp = useMutation({
    mutationFn: (data: object) => apiRequest<EvolutionWhatsAppIntegration>(token, '/crm/integrations/whatsapp/evolution', { method: 'PUT', body: JSON.stringify(data) }),
    onSuccess: (integration) => {
      setEvolutionWebhookUrl(integration.webhookUrl)
      setEvolutionQrCode(integration.qrCode ?? null)
      queryClient.invalidateQueries({ queryKey: ['crm', 'integrations'] })
    },
  })
  const saveWhatsAppRouting = useMutation({
    mutationFn: (data: object) => apiRequest<IntegrationStatus>(token, '/crm/integrations/whatsapp/routing', { method: 'PUT', body: JSON.stringify(data) }),
    onSuccess: (status) => queryClient.setQueryData(['crm', 'integrations'], status),
  })
  const updateEnvironment = useMutation({
    mutationFn: (sriEnvironment: '1' | '2') =>
      apiRequest<FiscalSettings>(token, '/organization/fiscal-settings', {
        method: 'PUT',
        headers: { 'Idempotency-Key': idempotencyKey('web-fiscal-environment') },
        body: JSON.stringify({ sriEnvironment }),
      }),
    onSuccess: (settings) => {
      queryClient.setQueryData(['organization', 'fiscal-settings'], settings)
    },
  })
  const uploadCertificate = useMutation({
    mutationFn: (formData: FormData) =>
      apiRequest<FiscalSettings>(token, '/organization/signing-certificate', {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey('web-signing-certificate') },
        body: formData,
      }),
    onSuccess: (settings) => {
      queryClient.setQueryData(['organization', 'fiscal-settings'], settings)
    },
  })
  const uploadRideLogo = useMutation({
    mutationFn: (formData: FormData) =>
      apiRequest<FiscalSettings>(token, '/organization/ride-logo', {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey('web-ride-logo') },
        body: formData,
      }),
    onSuccess: (settings) => {
      queryClient.setQueryData(['organization', 'fiscal-settings'], settings)
    },
  })

  function submitCertificate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    uploadCertificate.mutate(new FormData(event.currentTarget))
  }

  function submitRideLogo(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    uploadRideLogo.mutate(new FormData(event.currentTarget))
  }

  function submitProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    updateProfile.mutate({
      name: String(data.get('name')),
      ruc: String(data.get('ruc')),
      defaultPaymentTermsDays: Number(data.get('defaultPaymentTermsDays') || 0),
    })
  }

  function submitWhatsApp(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    saveWhatsApp.mutate({
      businessAccountId: data.get('businessAccountId'),
      phoneNumberId: data.get('phoneNumberId'),
      displayPhoneNumber: data.get('displayPhoneNumber') || null,
      accessToken: data.get('accessToken'),
      appSecret: data.get('appSecret'),
      verifyToken: data.get('verifyToken'),
    })
  }

  function submitEvolutionWhatsApp(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    saveEvolutionWhatsApp.mutate({
      instanceName: data.get('instanceName'),
      displayPhoneNumber: data.get('displayPhoneNumber') || null,
    })
  }

  function submitWhatsAppRouting(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    saveWhatsAppRouting.mutate({
      crmProvider: data.get('crmProvider'),
      collectionsProvider: data.get('collectionsProvider'),
    })
  }

  const fiscal = fiscalQuery.data
  return (
    <>
      <ErpPageHeader
        eyebrow="Configuración fiscal"
        title="Empresa"
        subtitle="Datos del contribuyente y estructura de emisión."
        meta={<ErpStatusBadge tone="success">Tenant activo</ErpStatusBadge>}
      />
      <ErpToolbar ariaLabel="Secciones de empresa">
        <ErpButton variant={settingsSection === 'fiscal' ? 'primary' : 'secondary'} onClick={() => setSettingsSection('fiscal')}>Datos fiscales</ErpButton>
        <ErpButton variant={settingsSection === 'invoicing' ? 'primary' : 'secondary'} onClick={() => setSettingsSection('invoicing')}>Envío de facturas</ErpButton>
        <ErpButton variant={settingsSection === 'collections' ? 'primary' : 'secondary'} onClick={() => setSettingsSection('collections')}>Cobranza automática</ErpButton>
        <ErpButton variant={settingsSection === 'integrations' ? 'primary' : 'secondary'} onClick={() => setSettingsSection('integrations')}>Canales e integraciones</ErpButton>
      </ErpToolbar>
      <section className="company-grid company-grid-expanded">
        {settingsSection === 'fiscal' ? <>
        <article className="company-identity company-profile-editor">
          <p className="section-number">Contribuyente</p>
          <form onSubmit={submitProfile}>
            <label>Razón social<input name="name" defaultValue={context.name} required /></label>
            <label>RUC<input name="ruc" defaultValue={context.ruc} pattern="[0-9]{13}" required /></label>
            <label>Condición de pago general<select name="defaultPaymentTermsDays" defaultValue={context.defaultPaymentTermsDays}><option value="0">Contado</option><option value="15">15 días</option><option value="30">30 días</option><option value="45">45 días</option><option value="60">60 días</option><option value="90">90 días</option></select></label>
            {updateProfile.error ? <p className="form-error">{updateProfile.error.message}</p> : null}
            <ErpButton variant="primary" type="submit" disabled={updateProfile.isPending}>{updateProfile.isPending ? 'Guardando…' : 'Guardar datos de empresa'}</ErpButton>
          </form>
        </article>
        <ErpPanel title="Establecimientos" count={establishments.length}>
          <ul className="establishment-list">
            {establishments.map((item) => <li key={item.id}><span>{item.code}</span><div><strong>{item.name}</strong><small>{item.address}</small></div></li>)}
          </ul>
        </ErpPanel>
        <ErpPanel
          title="Ambiente SRI"
          actions={fiscal ? <ErpStatusBadge tone={fiscal.sriEnvironment === '2' ? 'warning' : 'neutral'}>{fiscal.sriEnvironment === '2' ? 'Producción' : 'Pruebas'}</ErpStatusBadge> : null}
          className="fiscal-settings-panel"
        >
          {fiscalQuery.isPending ? <p className="fiscal-panel-copy">Cargando configuración fiscal…</p> : null}
          {fiscalQuery.error ? <p className="form-error" role="alert">{fiscalQuery.error.message}</p> : null}
          {fiscal ? (
            <div className="fiscal-panel-body">
              <label>
                Ambiente de emisión
                <select
                  value={fiscal.sriEnvironment}
                  disabled={updateEnvironment.isPending}
                  onChange={(event) => updateEnvironment.mutate(event.target.value as '1' | '2')}
                >
                  <option value="1">1 · Pruebas</option>
                  <option value="2">2 · Producción</option>
                </select>
              </label>
              {fiscal.sriEnvironment === '2' ? (
                <p className="environment-warning">La empresa queda preparada para producción. Este entorno de staging bloqueará cualquier envío fiscal real.</p>
              ) : null}
              {updateEnvironment.error ? <p className="form-error" role="alert">{updateEnvironment.error.message}</p> : null}
            </div>
          ) : null}
        </ErpPanel>
        <ErpPanel title="Proveedor de facturación electrónica" className="fiscal-settings-panel">
          {fiscal ? (
            <div className="fiscal-panel-body">
              <p><strong>{fiscal.electronicInvoicingProviderName}</strong></p>
              <p className="fiscal-panel-copy">RUC del creador de IAERP: {fiscal.electronicInvoicingProviderRuc}</p>
              <p className="fine-print">Este dato pertenece a la plataforma; no cambia la razón social ni el RUC del emisor.</p>
            </div>
          ) : null}
        </ErpPanel>
        <ErpPanel
          title="Firma electrónica"
          actions={fiscal?.certificateConfigured ? <ErpStatusBadge tone="success">Configurada</ErpStatusBadge> : <ErpStatusBadge tone="warning">Pendiente</ErpStatusBadge>}
          className="fiscal-settings-panel"
        >
          <div className="fiscal-panel-body">
            {fiscal?.certificateConfigured ? (
              <dl className="certificate-details">
                <div><dt>Titular</dt><dd>{fiscal.certificateSubject ?? 'No disponible'}</dd></div>
                <div><dt>Vigencia</dt><dd>{fiscal.certificateValidTo ? new Date(fiscal.certificateValidTo).toLocaleDateString('es-EC') : 'No disponible'}</dd></div>
                <div><dt>Fingerprint SHA-256</dt><dd>{fiscal.certificateFingerprintSha256}</dd></div>
              </dl>
            ) : (
              <p className="fiscal-panel-copy">Carga el certificado PKCS#12 de esta empresa. La contraseña se cifra y nunca vuelve al navegador.</p>
            )}
            <form className="certificate-form" onSubmit={submitCertificate}>
              <label>Certificado (.p12 o .pfx)<input name="file" type="file" accept=".p12,.pfx,application/x-pkcs12" required /></label>
              <label>Contraseña del certificado<input name="password" type="password" autoComplete="new-password" required /></label>
              {uploadCertificate.error ? <p className="form-error" role="alert">{uploadCertificate.error.message}</p> : null}
              <ErpButton variant="primary" type="submit" disabled={uploadCertificate.isPending}>
                {uploadCertificate.isPending ? 'Validando y guardando…' : fiscal?.certificateConfigured ? 'Reemplazar certificado' : 'Guardar certificado'}
              </ErpButton>
            </form>
          </div>
        </ErpPanel>
        <ErpPanel
          title="Logo en factura (RIDE)"
          actions={fiscal?.rideLogoConfigured ? <ErpStatusBadge tone="success">Configurado</ErpStatusBadge> : <ErpStatusBadge tone="neutral">Opcional</ErpStatusBadge>}
          className="fiscal-settings-panel"
        >
          <div className="fiscal-panel-body">
            <p className="fiscal-panel-copy">Carga el logo que debe aparecer en los nuevos RIDE. Se almacena de forma privada y no modifica documentos ya emitidos.</p>
            <form className="certificate-form" onSubmit={submitRideLogo}>
              <label>Logo PNG o JPG (máx. 1 MB)<input name="file" type="file" accept="image/png,image/jpeg,.png,.jpg,.jpeg" required /></label>
              {uploadRideLogo.error ? <p className="form-error" role="alert">{uploadRideLogo.error.message}</p> : null}
              <ErpButton variant="primary" type="submit" disabled={uploadRideLogo.isPending}>
                {uploadRideLogo.isPending ? 'Validando y guardando…' : fiscal?.rideLogoConfigured ? 'Reemplazar logo' : 'Guardar logo'}
              </ErpButton>
            </form>
          </div>
        </ErpPanel>
        </> : null}
        {settingsSection === 'invoicing' ? (
          <ErpPanel title="Correo de entrega de factura" className="fiscal-settings-panel">
            {invoiceEmailTemplateQuery.isPending ? <p className="fiscal-panel-copy">Cargando plantilla…</p> : null}
            {invoiceEmailTemplateQuery.error ? <p className="form-error" role="alert">{invoiceEmailTemplateQuery.error.message}</p> : null}
            {invoiceEmailTemplateQuery.data ? (
              <InvoiceEmailTemplateEditor
                key={`${invoiceEmailTemplateQuery.data.subject}-${invoiceEmailTemplateQuery.data.body}`}
                template={invoiceEmailTemplateQuery.data}
                pending={updateInvoiceEmailTemplate.isPending}
                error={updateInvoiceEmailTemplate.error?.message}
                onSave={(template) => updateInvoiceEmailTemplate.mutate(template)}
              />
            ) : null}
          </ErpPanel>
        ) : null}
        {settingsSection === 'collections' ? <>
        <ErpPanel title="Automatizaciones de cobranza" className="fiscal-settings-panel">
          <p className="fiscal-panel-copy">Define aquí las plantillas, canales y reglas automáticas. La pantalla de Cartera queda reservada para gestionar saldos y cobros.</p>
          {collectionPolicyQuery.data && Array.isArray(collectionPolicyQuery.data.offsetsDays) && Array.isArray(collectionPolicyQuery.data.channels) ? (
            <CollectionPolicyEditor
              key={collectionPolicyQuery.data.updatedAt}
              policy={collectionPolicyQuery.data}
              pending={updateCollectionPolicy.isPending}
              error={updateCollectionPolicy.error?.message}
              onSave={(policy) => updateCollectionPolicy.mutate(policy)}
            />
          ) : null}
        </ErpPanel>
        </> : null}
        {settingsSection === 'integrations' ? <>
        <ErpPanel title="Google Workspace" actions={<ErpStatusBadge tone={integrationsQuery.data?.googleConnected ? 'success' : 'warning'}>{integrationsQuery.data?.googleConnected ? 'Conectado' : 'Pendiente'}</ErpStatusBadge>} className="fiscal-settings-panel">
          <div className="fiscal-panel-body">
            {integrationsQuery.data?.googleConnected ? <p>Cuenta conectada: <strong>{integrationsQuery.data.googleEmail}</strong></p> : <p className="fiscal-panel-copy">Conecta tu cuenta para enviar correos y sincronizar conversaciones del CRM.</p>}
            {!integrationsQuery.data?.googleConfigurationAvailable ? <p className="environment-warning">Faltan GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET y callback en Coolify.</p> : null}
            {connectGoogle.error ? <p className="form-error">{connectGoogle.error.message}</p> : null}
            <ErpButton variant="primary" disabled={!integrationsQuery.data?.googleConfigurationAvailable || connectGoogle.isPending} onClick={() => connectGoogle.mutate()}>{integrationsQuery.data?.googleConnected ? 'Reconectar Google' : 'Conectar Google Workspace'}</ErpButton>
          </div>
        </ErpPanel>
        <ErpPanel title="WhatsApp · Enrutamiento" actions={<ErpStatusBadge tone={integrationsQuery.data?.whatsappConnected || integrationsQuery.data?.whatsappEvolutionConnected ? 'success' : 'warning'}>{integrationsQuery.data?.whatsappConnected || integrationsQuery.data?.whatsappEvolutionConnected ? 'Configurado' : 'Pendiente'}</ErpStatusBadge>} className="fiscal-settings-panel">
          <form className="fiscal-panel-body" onSubmit={submitWhatsAppRouting}>
            <p className="fiscal-panel-copy">Elige el proveedor por uso. Puedes conservar Meta para cobranza y usar Evolution para CRM o soporte.</p>
            <label>Mensajes de CRM<select name="crmProvider" defaultValue={integrationsQuery.data?.whatsappCrmProvider ?? 'META'}><option value="META">Meta Cloud API</option><option value="EVOLUTION">Evolution API</option></select></label>
            <label>Recordatorios de cobranza<select name="collectionsProvider" defaultValue={integrationsQuery.data?.whatsappCollectionsProvider ?? 'META'}><option value="META">Meta Cloud API</option><option value="EVOLUTION">Evolution API</option></select></label>
            {saveWhatsAppRouting.error ? <p className="form-error">{saveWhatsAppRouting.error.message}</p> : null}
            <ErpButton variant="secondary" type="submit" disabled={saveWhatsAppRouting.isPending}>{saveWhatsAppRouting.isPending ? 'Guardando…' : 'Guardar enrutamiento'}</ErpButton>
          </form>
        </ErpPanel>
        <ErpPanel title="WhatsApp Business · Meta" actions={<ErpStatusBadge tone={integrationsQuery.data?.whatsappMetaConnected ? 'success' : 'warning'}>{integrationsQuery.data?.whatsappMetaConnected ? 'Conectado' : 'Pendiente'}</ErpStatusBadge>} className="fiscal-settings-panel">
          <form className="fiscal-panel-body" onSubmit={submitWhatsApp}>
            {integrationsQuery.data?.whatsappMetaConnected ? <p>Número activo: <strong>{integrationsQuery.data.whatsappPhone ?? 'Configurado'}</strong></p> : null}
            <label>WhatsApp Business Account ID<input name="businessAccountId" required /></label>
            <label>Phone Number ID<input name="phoneNumberId" required /></label>
            <label>Número visible<input name="displayPhoneNumber" placeholder="+593…" /></label>
            <label>Token permanente<input name="accessToken" type="password" autoComplete="new-password" required /></label>
            <label>Meta App Secret<input name="appSecret" type="password" autoComplete="new-password" required /></label>
            <label>Verify token<input name="verifyToken" type="password" minLength={16} required /></label>
            <p className="fine-print">Webhook: {window.location.origin}/api/v1/crm/webhooks/whatsapp</p>
            {saveWhatsApp.error ? <p className="form-error">{saveWhatsApp.error.message}</p> : null}
            <ErpButton variant="primary" type="submit" disabled={saveWhatsApp.isPending}>{saveWhatsApp.isPending ? 'Validando…' : 'Guardar conexión'}</ErpButton>
          </form>
        </ErpPanel>
        <ErpPanel title="WhatsApp · Evolution API" actions={<ErpStatusBadge tone={integrationsQuery.data?.whatsappEvolutionConnected ? 'success' : 'warning'}>{integrationsQuery.data?.whatsappEvolutionConnected ? 'Conectado' : 'Pendiente'}</ErpStatusBadge>} className="fiscal-settings-panel">
          <form className="fiscal-panel-body" onSubmit={submitEvolutionWhatsApp}>
            {!integrationsQuery.data?.evolutionConfigurationAvailable ? <p className="environment-warning">Falta configurar EVOLUTION_API_BASE_URL y PUBLIC_API_URL en Coolify.</p> : null}
            {integrationsQuery.data?.whatsappEvolutionConnected ? <p>Número activo: <strong>{integrationsQuery.data.whatsappEvolutionPhone ?? 'Configurado'}</strong></p> : null}
            <label>Nombre de instancia<input name="instanceName" pattern="[A-Za-z0-9_-]+" required /></label>
            <label>Número visible<input name="displayPhoneNumber" placeholder="+593…" /></label>
            <p className="fine-print">La clave de Evolution queda protegida en la plataforma. Al continuar se crea o recupera la instancia, configura el webhook y muestra el QR aquí.</p>
            {evolutionQrCode ? <div className="evolution-qr" role="status"><strong>Escanea este QR desde WhatsApp → Dispositivos vinculados.</strong><img src={evolutionQrCode} alt="Código QR para vincular WhatsApp con Evolution" /><small>El código vence pronto. Si vence, usa “Generar otro QR”.</small></div> : null}
            {evolutionWebhookUrl ? <p className="fine-print">Webhook configurado automáticamente.</p> : null}
            {saveEvolutionWhatsApp.error ? <p className="form-error">{saveEvolutionWhatsApp.error.message}</p> : null}
            <ErpButton variant="primary" type="submit" disabled={!integrationsQuery.data?.evolutionConfigurationAvailable || saveEvolutionWhatsApp.isPending}>{saveEvolutionWhatsApp.isPending ? 'Preparando QR…' : evolutionQrCode ? 'Generar otro QR' : 'Generar QR y conectar WhatsApp'}</ErpButton>
          </form>
        </ErpPanel>
        </> : null}
      </section>
    </>
  )
}

function Workspace() {
  const auth = useAuth()
  const [section, setSection] = useState<Section>('overview')
  const [navigationVersion, setNavigationVersion] = useState(0)
  const [contractPartyId, setContractPartyId] = useState<string | undefined>()
  const tokenQuery = useQueries({
    queries: [{
      queryKey: ['auth-token'],
      queryFn: auth.getToken,
      staleTime: 20_000,
      refetchInterval: 20_000,
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
      <Sidebar
        currentSection={section}
        onNavigate={(newSection) => {
          if (newSection !== 'contracts') setContractPartyId(undefined)
          startTransition(() => {
            setSection(newSection)
            setNavigationVersion((current) => current + 1)
          })
        }}
        organizationName={contextQuery.data.name}
        ruc={contextQuery.data.ruc}
      />
      <main id="main-content" tabIndex={-1}>
       <div key={`${section}-${navigationVersion}`} className="section-fade">
        {section === 'overview' ? <Overview context={contextQuery.data} token={token} /> : null}
        {section === 'parties' ? <PartiesPage parties={parties} token={token} onOpenContracts={(partyId) => { setContractPartyId(partyId); startTransition(() => setSection('contracts')) }} /> : null}
        {section === 'catalogs' ? <ProductsPage products={products} taxes={taxesQuery.data ?? []} token={token} /> : null}
        {section === 'invoices' ? (
          <InvoicesPage
            token={token}
            customers={parties.filter((party) => party.roles.includes('CUSTOMER'))}
            products={products}
            taxes={taxesQuery.data ?? []}
            establishments={establishmentsQuery.data ?? []}
            emissionPoints={emissionPointsQuery.data ?? []}
            defaultPaymentTermsDays={contextQuery.data.defaultPaymentTermsDays}
          />
        ) : null}
        {section === 'organization' ? <OrganizationPage context={contextQuery.data} establishments={establishmentsQuery.data ?? []} token={token} /> : null}
        {section === 'receivables' ? <ReceivablesPage token={token} parties={parties} /> : null}
        {section === 'contracts' ? <ContractsPage key={contractPartyId ?? 'all-contracts'} parties={parties} products={products} taxes={taxesQuery.data ?? []} establishments={establishmentsQuery.data ?? []} emissionPoints={emissionPointsQuery.data ?? []} token={token} initialPartyId={contractPartyId} /> : null}
        {section === 'crm' ? (
          <ErrorBoundary label="el CRM">
            <Suspense fallback={<SectionLoadingSkeleton label="Cargando CRM…" />}>
              <LeadsPage token={token} parties={parties} products={products} />
            </Suspense>
          </ErrorBoundary>
        ) : null}
        {section === 'tax' ? (
          <ErrorBoundary label="el módulo tributario">
            <Suspense fallback={<SectionLoadingSkeleton label="Cargando Tributario…" />}>
              <TaxPage token={token} />
            </Suspense>
          </ErrorBoundary>
        ) : null}
       </div>
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
