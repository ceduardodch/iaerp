import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarClock, DollarSign, FileText, History, Mail, MessageSquare, Pencil, Receipt, ShoppingCart } from 'lucide-react'
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
  fetchAllLeads,
  idempotencyKey,
  type AccountItem,
  type AccountItemStatus,
  type AgingBucket,
  type ArtifactDownload,
  type BankStatementImport,
  type BillingProposal,
  type AgingSummary,
  type CollectionPolicy,
  type CollectionContactInput,
  type CollectionHistoryEntry,
  type CollectionsHistory,
  type CollectionsBreakdown,
  type CommercialContract,
  type ContractArtifactDownload,
  type ContractEmailSync,
  type ContractVersion,
  type AwsConsumptionCut,
  type DiscountInput,
  type DocumentArtifact,
  type DashboardTax,
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
  type MetaAdsIntegration,
  type SocialCampaignPolicy,
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
  ErpDataTable,
  ErpEmptyState,
  ErpFormPanel,
  ErpPageHeader,
  ErpPanel,
  ErpStatusBadge,
  ErpToolbar,
} from './components/erp'
import {
  ErpLineChart,
  ErpOrdinalColumns,
  ErpCompareBars,
  ErpStackedBars,
  ErpStatTile,
} from './components/charts'
import { ErpCombobox } from './components/erp/ErpCombobox'
import { ErpModal } from './components/erp/ErpModal'
import { ErpConfirmDialog } from './components/erp/ErpConfirmDialog'
import { AnalyticClassificationPicker } from './components/analytics/AnalyticClassificationPicker'
import { AnalyticClassificationSettings } from './components/analytics/AnalyticClassificationSettings'
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
const PurchasesPage = lazy(() =>
  import('./components/purchases').then((module) => ({ default: module.PurchasesPage })),
)
// Nómina la usa quien tiene personal en planilla, no todos los tenants: mismo criterio de code-splitting.
const PayrollPage = lazy(() =>
  import('./components/payroll').then((module) => ({ default: module.PayrollPage })),
)
// Bandeja de acción: revisión agregada de cobranza + prospección, poco usada
// frente al arranque normal, misma razón de code-splitting que las de arriba.
const ActionQueuePage = lazy(() =>
  import('./components/action-queue').then((module) => ({ default: module.ActionQueuePage })),
)
import { InvoiceSpreadsheet } from './components/InvoiceSpreadsheet'
import { Sidebar, type Section } from './components/Sidebar'
import { ErrorBoundary } from './components/ErrorBoundary'
import { SectionLoadingSkeleton } from './components/LoadingSkeleton'
import { useToast } from './components/Toast'

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

/** Tramos tal como los nombra el servidor (`AgingSummary`), no el chip local. */
type ServerAgingBucket = AgingSummary['buckets'][number]['bucket']

const BUCKET_LABELS: Record<ServerAgingBucket, string> = {
  CURRENT: 'Al día',
  '1-15': '1-15',
  '16-30': '16-30',
  '31-60': '31-60',
  '61-90': '61-90',
  '90+': '90+',
}
const BUCKET_ORDER: ServerAgingBucket[] = ['CURRENT', '1-15', '16-30', '31-60', '61-90', '90+']

function monthLabel(year: number, month: number, style: 'short' | 'long' = 'short'): string {
  return new Date(year, month - 1, 1).toLocaleDateString('es-EC', {
    month: style,
    year: style === 'short' ? '2-digit' : 'numeric',
  })
}

/**
 * Variación porcentual contra el periodo anterior.
 *
 * Devuelve ``undefined`` cuando no hay base con qué comparar: un porcentaje
 * sobre cero no significa nada y mostrar "+100 %" porque antes no había nada
 * sería inventar una mejora.
 */
function percentChange(current: number, previous: number): number | undefined {
  if (previous <= 0) return undefined
  return ((current - previous) / previous) * 100
}

function SectionHeading({ index, title, subtitle }: { index: number; title: string; subtitle: string }) {
  return (
    <div className="dash-section-head">
      <span className="dash-section-num" aria-hidden="true">{index}</span>
      <h2>{title}</h2>
      <span className="dash-section-sub">{subtitle}</span>
    </div>
  )
}

function Overview({
  context,
  token,
  onOpenAnnualTax,
}: {
  context: TenantContext
  token: string
  onOpenAnnualTax: () => void
}) {
  const canReadTax = context.scopes.includes('tax:read')
  const [annualPurchaseView, setAnnualPurchaseView] = useState<
    'DEDUCTIBLE' | 'NON_DEDUCTIBLE' | 'PENDING' | 'INTERNAL_REAL' | 'INTERNAL_DECLARATION_ONLY' | 'INTERNAL_PENDING'
  >('DEDUCTIBLE')
  const [incomeTaxScenario, setIncomeTaxScenario] = useState<'NONE' | '25'>('NONE')
  const [invoicesQuery, receivablesQuery, leadsQuery, taxDashboardQuery, agingQuery, historyQuery] = useQueries({
    queries: [
      { queryKey: ['invoices', 'overview'], queryFn: () => apiRequest<SalesDocument[]>(token, '/invoices') },
      { queryKey: ['receivables', 'overview'], queryFn: () => apiRequest<AccountItem[]>(token, '/receivables') },
      { queryKey: ['crm', 'leads', 'overview'], queryFn: () => fetchAllLeads(token) },
      { queryKey: ['tax', 'dashboard', incomeTaxScenario], queryFn: () => apiRequest<DashboardTax>(token, `/tax/dashboard${incomeTaxScenario === '25' ? '?income_tax_rate=25' : ''}`), enabled: canReadTax },
      { queryKey: ['receivables', 'aging'], queryFn: () => apiRequest<AgingSummary>(token, '/receivables/aging') },
      { queryKey: ['receivables', 'collections', 'monthly'], queryFn: () => apiRequest<CollectionsHistory>(token, '/receivables/collections/monthly?months=12') },
    ],
  })
  const invoices = invoicesQuery.data ?? []
  const receivables = receivablesQuery.data ?? []
  const leads = leadsQuery.data ?? []
  const taxDashboard = taxDashboardQuery.data
  const months = historyQuery.data?.months ?? []

  const today = todayInFiscalTimezone().slice(0, 7)
  const outstanding = receivables.reduce((sum, item) => sum + Number(item.openAmount), 0)
  const overdueItems = receivables.filter((item) => item.status === 'OVERDUE')
  const overdue = overdueItems.reduce((sum, item) => sum + Number(item.openAmount), 0)
  const monthlyInvoices = invoices.filter((invoice) =>
    invoice.issueDate.startsWith(today) && invoice.type === 'INVOICE' && invoice.status === 'AUTHORIZED',
  ).length
  const openLeads = leads.filter((lead) => !['WON', 'LOST'].includes(lead.status))
  const openPipeline = openLeads.reduce((sum, lead) => sum + Number(lead.estimatedValue ?? 0), 0)

  // Cobro: el mes en curso frente al anterior, ambos del servidor.
  const currentMonth = months.at(-1)
  const previousMonth = months.at(-2)
  const collectedNow = Number(currentMonth?.settledAmount ?? 0)
  const collectedDelta = percentChange(collectedNow, Number(previousMonth?.settledAmount ?? 0))
  const retainedNow = Number(currentMonth?.retentionAmount ?? 0)
  const retentionShare = collectedNow > 0 ? (retainedNow / collectedNow) * 100 : 0

  const agingBars = (agingQuery.data?.buckets ?? [])
    .slice()
    .sort((left, right) => BUCKET_ORDER.indexOf(left.bucket) - BUCKET_ORDER.indexOf(right.bucket))
    .map((bucket) => ({ label: BUCKET_LABELS[bucket.bucket], value: Number(bucket.total) }))

  const collectionRows = months.slice(-3).map((month) => ({
    label: monthLabel(month.year, month.month),
    parts: [Number(month.cashAmount), Number(month.retentionAmount)],
  }))

  const currentTax = taxDashboard?.currentMonth
  const annualTax = taxDashboard?.annual
  const annualPurchaseMetric = annualTax ? {
    DEDUCTIBLE: {
      label: 'Compras deducibles · IVA presentado',
      value: annualTax.declaredDeductiblePurchasesBase,
      note: `${annualTax.declaredMonthCount} mes(es) con IVA presentado; el corte se recalcula con los documentos.`,
    },
    NON_DEDUCTIBLE: {
      label: 'Compras no deducibles',
      value: annualTax.nonDeductiblePurchasesBase,
      note: 'No deducibles; no reducen el resultado fiscal.',
    },
    PENDING: {
      label: 'Compras tributarias por revisar',
      value: annualTax.pendingReviewPurchasesBase,
      note: `${annualTax.pendingReviewDocumentCount} documento(s) pendientes.`,
    },
    INTERNAL_REAL: {
      label: 'Gastos reales internos',
      value: annualTax.internalRealExpensesTotal,
      note: `${annualTax.internalRealExpenseCount} gasto(s), incluido IVA. Usa los tags para verlos por proyecto.`,
    },
    INTERNAL_DECLARATION_ONLY: {
      label: 'Solo tributarios',
      value: annualTax.internalDeclarationOnlyExpensesTotal,
      note: `${annualTax.internalDeclarationOnlyExpenseCount} gasto(s) excluidos del control interno.`,
    },
    INTERNAL_PENDING: {
      label: 'Control interno por revisar',
      value: annualTax.internalPendingExpensesTotal,
      note: `${annualTax.internalPendingExpenseCount} gasto(s) aún sin decidir.`,
    },
  }[annualPurchaseView] : null
  const trendPoints = taxDashboard?.trend ?? []
  // El año en curso es lo que se compara contra metas; la ventana móvil de 12
  // meses arrancaba en septiembre del año pasado y confundía la lectura.
  // En enero el año corriente tiene un solo punto y el gráfico se esconde, así
  // que ahí se conserva la ventana móvil en vez de mostrar nada.
  const currentYear = Number(todayInFiscalTimezone().slice(0, 4))
  const yearPoints = trendPoints.filter((point) => point.year === currentYear)
  const showCalendarYear = yearPoints.length > 1
  const salesTrend = (showCalendarYear ? yearPoints : trendPoints).map((point) => ({
    label: monthLabel(point.year, point.month),
    value: Math.max(Number(point.total), 0),
  }))

  return (
    <>
      <ErpPageHeader
        eyebrow="Pulso operativo"
        title={context.name}
        subtitle="El pulso de cobranza, emisión y oportunidades de tu empresa."
        meta={<span className="date-chip">RUC {context.ruc}</span>}
      />

      <SectionHeading index={1} title="Caja y cobranza" subtitle="¿Hay plata y quién me debe?" />

      <div className="dash-hero-row">
        <article className="dash-hero">
          <span className="erp-stat-label">Por cobrar</span>
          {/* Cifra guía del tablero: una sola por vista, en la misma tipografía
              sans que el resto. Sin tabular-nums, que a este tamaño separa los
              dígitos y hace ver flojo el número. */}
          <strong className="dash-hero-value">${formatAmount(outstanding)}</strong>
          <p className="erp-stat-foot">{receivables.length} cuentas en cartera.</p>
        </article>
        <div className="dash-tiles">
          <ErpStatTile
            label="Vencido"
            value={`$${formatAmount(overdue)}`}
            tone={overdue > 0 ? 'danger' : undefined}
            footnote={`${overdueItems.length} cuenta(s) pasadas de fecha.`}
          />
          <ErpStatTile
            label="Cobrado este mes"
            value={`$${formatAmount(collectedNow)}`}
            delta={collectedDelta === undefined ? undefined : { value: collectedDelta, goodWhen: 'up' }}
            spark={months.map((month) => Number(month.settledAmount))}
          />
          <ErpStatTile
            label="Se fue en retenciones"
            value={`${formatAmount(retentionShare)} %`}
            footnote={<>${formatAmount(retainedNow)} recuperables ante el SRI, no en caja.</>}
          />
        </div>
      </div>

      <section className="dash-grid-2">
        <ErpPanel title="Antigüedad del saldo" actions={<span className="dash-panel-note">Más oscuro = más vencido</span>}>
          {agingQuery.isPending ? <p aria-busy="true">Cargando antigüedad…</p> : null}
          {agingBars.length > 0 ? (
            <ErpOrdinalColumns bars={agingBars} label="Saldo abierto por tramo de antigüedad" emphasizeLast />
          ) : !agingQuery.isPending ? (
            <p className="fine-print">Sin saldo abierto que clasificar.</p>
          ) : null}
        </ErpPanel>
        <ErpPanel title="Cómo se cobró">
          {collectionRows.length > 0 ? (
            <>
              <ErpStackedBars
                rows={collectionRows}
                seriesNames={['Dinero recibido', 'Retención']}
                label="Cobro mensual dividido entre dinero recibido y retenciones"
              />
              <p className="fine-print">La retención baja el saldo pero no entra en caja.</p>
            </>
          ) : (
            <p className="fine-print">Aún no hay cobros registrados en el periodo.</p>
          )}
        </ErpPanel>
      </section>

      {canReadTax ? (
        <>
          <SectionHeading index={2} title="Tributario" subtitle="¿Qué debo declarar?" />
          <section className="dash-grid-2">
            <ErpPanel
              title={annualTax ? `Año fiscal ${annualTax.year}` : 'Año fiscal'}
              className="dash-annual-panel"
              actions={<div className="dash-annual-actions">
                <label>Ver compras<select value={annualPurchaseView} onChange={(event) => setAnnualPurchaseView(event.target.value as typeof annualPurchaseView)}><optgroup label="Tributario"><option value="DEDUCTIBLE">Para declaración · deducibles</option><option value="NON_DEDUCTIBLE">No deducibles</option><option value="PENDING">Pendientes tributarios</option></optgroup><optgroup label="Control interno"><option value="INTERNAL_REAL">Gastos reales</option><option value="INTERNAL_DECLARATION_ONLY">Solo tributarios</option><option value="INTERNAL_PENDING">Pendientes internos</option></optgroup></select></label>
                <label>Escenario renta<select value={incomeTaxScenario} onChange={(event) => setIncomeTaxScenario(event.target.value as 'NONE' | '25')}><option value="NONE">Sin tarifa</option><option value="25">25 % referencial</option></select></label>
                <ErpButton variant="ghost" onClick={onOpenAnnualTax}>Ver detalle anual</ErpButton>
              </div>}
            >
              {taxDashboardQuery.isPending ? <p aria-busy="true">Calculando avance anual…</p> : null}
              {taxDashboardQuery.error ? <p className="form-error" role="alert">No se pudo cargar el avance anual.</p> : null}
              {annualTax ? (
                <div className="dash-annual-summary" aria-label={`Resumen tributario del año ${annualTax.year}`}>
                  {annualPurchaseMetric ? <div aria-live="polite"><span>{annualPurchaseMetric.label}</span><strong>${formatAmount(Number(annualPurchaseMetric.value))}</strong><small>{annualPurchaseMetric.note}</small></div> : null}
                  <div>
                    <span>Resultado parcial · IVA presentado</span>
                    <strong>${formatAmount(Number(annualTax.declaredResultBeforeAdjustments))}</strong>
                    <small>No es la declaración anual de renta y puede cambiar con los documentos.</small>
                  </div>
                  <div>
                    <span>Renta estimada del año</span>
                    <strong>{annualTax.projectedEstimatedIncomeTax === null ? 'Elige una tarifa' : `$${formatAmount(Number(annualTax.projectedEstimatedIncomeTax))}`}</strong>
                    <small>{annualTax.estimateReason}</small>
                  </div>
                </div>
              ) : null}
              {annualTax?.preliminaryDocumentCount ? (
                <p className="dash-annual-warning" role="status">
                  Avance preliminar: faltan respaldos completos en {annualTax.preliminaryDocumentCount} comprobante(s).
                </p>
              ) : null}
            </ErpPanel>
            <ErpPanel
              title={currentTax ? `IVA estimado · ${monthLabel(currentTax.year, currentTax.month, 'long')}` : 'IVA estimado'}
              actions={currentTax ? <ErpStatusBadge tone={currentTax.isPreliminary ? 'warning' : 'success'}>{currentTax.isPreliminary ? 'Preliminar' : 'Respaldado'}</ErpStatusBadge> : undefined}
            >
              {taxDashboardQuery.isPending ? <p aria-busy="true">Cargando corte tributario…</p> : null}
              {taxDashboardQuery.error ? <p className="form-error" role="alert">No se pudo cargar el corte tributario.</p> : null}
              {currentTax ? (
                <div className="dash-tax">
                  <p className="dash-tax-figure">
                    <strong>${formatAmount(currentTax.ivaPayable)}</strong>
                    <span>a pagar</span>
                  </p>
                  <dl className="dash-tax-detail">
                    <div><dt>IVA generado</dt><dd>${formatAmount(currentTax.ivaGenerated)}</dd></div>
                    <div><dt>IVA de compras</dt><dd>− ${formatAmount(currentTax.ivaCredit)}</dd></div>
                    <div><dt>Retención de IVA</dt><dd>− ${formatAmount(currentTax.retainedIva)}</dd></div>
                    {Number(currentTax.ivaCreditBalance) > 0 ? (
                      <div><dt>Crédito a favor</dt><dd>${formatAmount(currentTax.ivaCreditBalance)}</dd></div>
                    ) : null}
                  </dl>
                </div>
              ) : null}
              {currentTax?.isPreliminary ? (
                <div className="tax-estimate-warning" role="alert">
                  <strong>Estimación, no declaración.</strong>
                  <ul>{currentTax.preliminaryReasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
                </div>
              ) : currentTax ? (
                <p className="fine-print">Calculado con la evidencia tributaria del periodo. Declarar y pagar aún exige revisión humana.</p>
              ) : null}
            </ErpPanel>
            <ErpPanel title="Ventas y compras del mes">
              {currentTax ? (
                <>
                  <ErpCompareBars
                    bars={[
                      { label: 'Ventas', value: Number(currentTax.authorizedSalesTotal) },
                      { label: 'Compras', value: Number(currentTax.purchasesTotal) },
                    ]}
                    label="Ventas autorizadas frente a compras del mes"
                  />
                  <p className="fine-print">
                    {currentTax.authorizedSalesCount} venta(s) autorizadas y {currentTax.purchaseCount} compra(s) con comprobante cargado.
                  </p>
                </>
              ) : null}
            </ErpPanel>
          </section>
        </>
      ) : null}

      <SectionHeading index={canReadTax ? 3 : 2} title="Comercial" subtitle="¿Cómo viene la venta?" />

      <ErpPanel
        title="Evolución de ventas emitidas"
        actions={
          <ErpStatusBadge>
            {showCalendarYear ? `Año ${currentYear}` : 'Últimos 12 meses'}
          </ErpStatusBadge>
        }
      >
        {taxDashboardQuery.isPending ? <p aria-busy="true">Cargando evolución…</p> : null}
        {salesTrend.length > 1 ? (
          <ErpLineChart
            points={salesTrend}
            label={`Ventas emitidas netas por mes, incluidos respaldos históricos, ${showCalendarYear ? `año ${currentYear}` : 'últimos doce meses'}`}
          />
        ) : !taxDashboardQuery.isPending ? (
          <p className="fine-print">Aún no hay suficientes meses para dibujar una tendencia.</p>
        ) : null}
      </ErpPanel>
      <div className="dash-tiles dash-tiles-pair">
        <ErpStatTile
          label="Facturas autorizadas del mes"
          value={String(monthlyInvoices)}
          footnote="No incluye rechazos ni documentos no autorizados."
        />
        <ErpStatTile
          label="Pipeline abierto"
          value={`$${formatAmount(openPipeline)}`}
          tone="success"
          footnote={`${openLeads.length} oportunidad(es) CRM activas.`}
        />
      </div>
    </>
  )
}

function PartiesPage({
  parties,
  token,
  onOpenContracts,
  onOpenPartySection,
}: {
  parties: Party[]
  token: string
  onOpenContracts: (partyId: string) => void
  /** Abre facturas, cartera o compras ya filtradas por este contacto. */
  onOpenPartySection: (partyId: string, destino: 'invoices' | 'receivables' | 'purchases') => void
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
          <ErpDataTable
            ariaLabel="Listado de contactos"
            rows={filtered}
            rowKey={(party) => party.id}
            emptyState={
              <ErpEmptyState
                title="No hay contactos"
                description="Crea el primer cliente o proveedor para comenzar."
                action={
                  <ErpButton variant="primary" onClick={() => setEditor(null)}>
                    Nuevo contacto
                  </ErpButton>
                }
              />
            }
            columns={[
              {
                header: 'Nombre',
                cell: (party) => <><strong>{party.name}</strong><small>{party.email ?? 'Sin correo'}</small></>,
              },
              { header: 'Identificación', cell: (party) => party.identificationNumber },
              { header: 'Contacto', cell: (party) => party.phone ?? 'Sin teléfono' },
              { header: 'Dirección', cell: (party) => party.address ?? 'Sin dirección' },
              {
                header: 'Rol',
                // `roles` vacío pintaba una etiqueta gris sin texto.
                cell: (party) => party.roles.length
                  ? <span className="tag">{party.roles.join(' / ')}</span>
                  : <span className="fine-print">Sin rol</span>,
              },
              {
                header: 'Acciones',
                cell: (party) => (
                  <ErpActionCell>
                    <ErpButton variant="icon" aria-label={`Editar ${party.name}`} title="Editar" onClick={() => setEditor(party)}>
                      <Pencil size={18} aria-hidden="true" />
                    </ErpButton>
                    {party.roles.includes('CUSTOMER') ? (
                      <>
                        <ErpButton variant="icon" aria-label={`Contratos de ${party.name}`} title="Contratos" onClick={() => onOpenContracts(party.id)}>
                          <FileText size={18} aria-hidden="true" />
                        </ErpButton>
                        <ErpButton variant="icon" aria-label={`Facturas de ${party.name}`} title="Facturas" onClick={() => onOpenPartySection(party.id, 'invoices')}>
                          <Receipt size={18} aria-hidden="true" />
                        </ErpButton>
                        <ErpButton variant="icon" aria-label={`Deudas de ${party.name}`} title="Deudas" onClick={() => onOpenPartySection(party.id, 'receivables')}>
                          <DollarSign size={18} aria-hidden="true" />
                        </ErpButton>
                      </>
                    ) : null}
                    {party.roles.includes('SUPPLIER') ? (
                      <ErpButton variant="icon" aria-label={`Compras a ${party.name}`} title="Compras" onClick={() => onOpenPartySection(party.id, 'purchases')}>
                        <ShoppingCart size={18} aria-hidden="true" />
                      </ErpButton>
                    ) : null}
                  </ErpActionCell>
                ),
              },
            ]}
          />
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
    queryFn: () => fetchAllLeads(token, 'status=WON'),
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
        <ErpDataTable
          ariaLabel="Listado de contratos"
          rows={contractsQuery.data ?? []}
          rowKey={(contract) => contract.id}
          emptyState={!contractsQuery.isPending ? <ErpEmptyState title="No hay contratos" description="Crea un contrato para un cliente y agrega su primera versión." action={<ErpButton variant="primary" onClick={() => setCreating(true)}>Nuevo contrato</ErpButton>} /> : null}
          columns={[
            { header: 'Contrato', cell: (contract) => <><strong>{contract.contractNumber}</strong><small>{contract.title}</small></> },
            { header: 'Cliente', cell: (contract) => parties.find((party) => party.id === contract.partyId)?.name ?? 'Cliente' },
            { header: 'Tipo', cell: (contract) => contract.serviceType === 'AWS_MONTHLY' ? 'AWS' : contract.serviceType === 'FIXED_MONTHLY' ? 'Mensual fijo' : contract.serviceType === 'MILESTONE' ? 'Hitos' : 'Accesorio' },
            { header: 'Estado', cell: (contract) => <ErpStatusBadge tone={contract.status === 'SIGNED' || contract.status === 'ACTIVE' ? 'success' : 'warning'}>{contract.status === 'ACTIVE' ? 'Activo' : contract.status === 'SIGNED' ? 'Firmado' : contract.status === 'PENDING_SIGNATURE' ? 'Esperando firma' : 'Borrador'}</ErpStatusBadge> },
            { header: 'Acciones', cell: (contract) => <ErpActionCell><ErpButton variant="ghost" onClick={() => setSelected(contract)}>Abrir</ErpButton></ErpActionCell> },
          ]}
        />
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
          <ErpDataTable
            ariaLabel="Listado de categorías tributarias"
            rows={taxes}
            rowKey={(tax) => tax.id}
            emptyState={<ErpEmptyState title="No hay categorías tributarias" description="Registra la primera tarifa para habilitar la creación de productos." action={<ErpButton variant="primary" onClick={() => setCreating(true)}>Nueva categoría</ErpButton>} />}
            columns={[
              { header: 'Código SRI', cell: (tax) => tax.sriCode },
              { header: 'Nombre', cell: (tax) => <strong>{tax.name}</strong> },
              { header: 'Tarifa', cell: (tax) => formatPercent(tax.rate) },
              { header: 'Vigente desde', cell: (tax) => new Date(`${tax.validFrom}T00:00:00`).toLocaleDateString('es-EC') },
            ]}
          />
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
  HISTORICAL_ISSUED: 'HISTÓRICA · XML FALTANTE',
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
  HISTORICAL_ISSUED: 'warning',
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
  | { view: 'historical' }
  | { view: 'detail'; id: string }
  | { view: 'credit-note'; invoice: SalesDocument }

function QuickCustomerModal({
  token,
  onCreated,
  onClose,
}: {
  token: string
  onCreated: (customer: Party) => void
  onClose: () => void
}) {
  const requestKey = useRef(idempotencyKey('web-invoice-quick-customer'))
  const [identificationType, setIdentificationType] = useState('RUC')
  const createCustomer = useMutation({
    mutationFn: (data: FormData) => apiRequest<Party>(token, '/parties', {
      method: 'POST',
      headers: { 'Idempotency-Key': requestKey.current },
      body: JSON.stringify({
        name: data.get('name'),
        identificationType: data.get('identificationType'),
        identificationNumber: data.get('identificationNumber'),
        roles: ['CUSTOMER'],
        email: data.get('email') || null,
        address: data.get('address') || null,
      }),
    }),
    onSuccess: onCreated,
  })

  return (
    <ErpModal title="Crear cliente" onClose={onClose} size="sm" initialFocusSelector='input[name="name"]' closeDisabled={createCustomer.isPending}>
      <form className="quick-master-form" onSubmit={(event) => {
        event.preventDefault()
        event.stopPropagation()
        createCustomer.mutate(new FormData(event.currentTarget))
      }}>
        <p className="fine-print">Guarda solo los datos necesarios para facturar. Luego podrás completar el contacto.</p>
        <div className="erp-form-fields">
          <label>Nombre o razón social<input name="name" required /></label>
          <div className="field-row">
            <label>Tipo<select name="identificationType" value={identificationType} onChange={(event) => setIdentificationType(event.target.value)}><option>RUC</option><option>CEDULA</option><option>PASSPORT</option><option>FINAL_CONSUMER</option></select></label>
            <label>Número<input key={identificationType} name="identificationNumber" required pattern={identificationType === 'RUC' ? '[0-9]{13}' : identificationType === 'CEDULA' ? '[0-9]{10}' : undefined} minLength={identificationType === 'PASSPORT' ? 3 : undefined} maxLength={30} defaultValue={identificationType === 'FINAL_CONSUMER' ? '9999999999999' : ''} readOnly={identificationType === 'FINAL_CONSUMER'} /></label>
          </div>
          <label>Correo<input name="email" type="email" /></label>
          <label>Dirección<textarea name="address" rows={2} /></label>
        </div>
        {createCustomer.error ? <p className="form-error" role="alert">{createCustomer.error.message}</p> : null}
        <div className="erp-form-actions">
          <ErpButton variant="secondary" onClick={onClose} disabled={createCustomer.isPending}>Cancelar</ErpButton>
          <ErpButton variant="primary" type="submit" disabled={createCustomer.isPending}>{createCustomer.isPending ? 'Creando…' : 'Crear y seleccionar'}</ErpButton>
        </div>
      </form>
    </ErpModal>
  )
}

function QuickProductModal({
  token,
  taxes,
  onCreated,
  onClose,
}: {
  token: string
  taxes: TaxCategory[]
  onCreated: (product: Product) => void
  onClose: () => void
}) {
  const requestKey = useRef(idempotencyKey('web-invoice-quick-product'))
  const createProduct = useMutation({
    mutationFn: (data: FormData) => apiRequest<Product>(token, '/products', {
      method: 'POST',
      headers: { 'Idempotency-Key': requestKey.current },
      body: JSON.stringify({
        name: data.get('name'),
        code: data.get('code') || null,
        unitPrice: data.get('unitPrice'),
        taxCategoryId: data.get('taxCategoryId'),
      }),
    }),
    onSuccess: onCreated,
  })

  return (
    <ErpModal title="Crear producto o servicio" onClose={onClose} size="sm" initialFocusSelector='input[name="name"]' closeDisabled={createProduct.isPending}>
      {taxes.length === 0 ? (
        <div className="quick-master-empty">
          <p role="alert">Primero debes crear una categoría tributaria en Catálogos.</p>
          <ErpButton variant="secondary" onClick={onClose}>Volver a la factura</ErpButton>
        </div>
      ) : (
        <form className="quick-master-form" onSubmit={(event) => {
          event.preventDefault()
          event.stopPropagation()
          createProduct.mutate(new FormData(event.currentTarget))
        }}>
          <p className="fine-print">El producto quedará guardado en el catálogo y seleccionado en esta factura.</p>
          <div className="erp-form-fields">
            <label>Nombre<input name="name" required /></label>
            <label>Código interno<input name="code" /></label>
            <div className="field-row">
              <label>Precio unitario<input name="unitPrice" type="number" min="0" step="0.000001" required /></label>
              <label>Impuesto<select name="taxCategoryId" defaultValue={taxes[0]?.id} required>{taxes.map((tax) => <option key={tax.id} value={tax.id}>{tax.name} · {formatPercent(tax.rate)}</option>)}</select></label>
            </div>
          </div>
          {createProduct.error ? <p className="form-error" role="alert">{createProduct.error.message}</p> : null}
          <div className="erp-form-actions">
            <ErpButton variant="secondary" onClick={onClose} disabled={createProduct.isPending}>Cancelar</ErpButton>
            <ErpButton variant="primary" type="submit" disabled={createProduct.isPending}>{createProduct.isPending ? 'Creando…' : 'Crear y agregar'}</ErpButton>
          </div>
        </form>
      )}
    </ErpModal>
  )
}

function EstablishmentEditorModal({
  token,
  establishment,
  onSaved,
  onClose,
}: {
  token: string
  establishment: Establishment
  onSaved: (establishment: Establishment) => void
  onClose: () => void
}) {
  const requestKey = useRef(idempotencyKey('web-establishment-update'))
  const updateEstablishment = useMutation({
    mutationFn: (data: FormData) => apiRequest<Establishment>(token, `/establishments/${establishment.id}`, {
      method: 'PUT',
      headers: { 'Idempotency-Key': requestKey.current },
      body: JSON.stringify({ name: data.get('name'), address: data.get('address') }),
    }),
    onSuccess: onSaved,
  })

  return (
    <ErpModal title={`Editar establecimiento ${establishment.code}`} onClose={onClose} size="sm" initialFocusSelector='textarea[name="address"]' closeDisabled={updateEstablishment.isPending}>
      <form className="quick-master-form" onSubmit={(event) => {
        event.preventDefault()
        event.stopPropagation()
        updateEstablishment.mutate(new FormData(event.currentTarget))
      }}>
        <p className="fine-print">Esta es la dirección fiscal del establecimiento que aparecerá en los próximos comprobantes. El código fiscal no cambia.</p>
        <div className="erp-form-fields">
          <label>Código fiscal<input value={establishment.code} readOnly /></label>
          <label>Nombre<input name="name" defaultValue={establishment.name} required /></label>
          <label>Dirección del establecimiento<textarea name="address" rows={3} defaultValue={establishment.address} required /></label>
        </div>
        {updateEstablishment.error ? <p className="form-error" role="alert">{updateEstablishment.error.message}</p> : null}
        <div className="erp-form-actions">
          <ErpButton variant="secondary" onClick={onClose} disabled={updateEstablishment.isPending}>Cancelar</ErpButton>
          <ErpButton variant="primary" type="submit" disabled={updateEstablishment.isPending}>{updateEstablishment.isPending ? 'Guardando…' : 'Guardar dirección'}</ErpButton>
        </div>
      </form>
    </ErpModal>
  )
}

function EstablishmentCreateModal({
  token,
  onCreated,
  onClose,
}: {
  token: string
  onCreated: (establishment: Establishment) => void
  onClose: () => void
}) {
  const requestKey = useRef(idempotencyKey('web-establishment-create'))
  const createEstablishment = useMutation({
    mutationFn: (data: FormData) => apiRequest<Establishment>(token, '/establishments', {
      method: 'POST',
      headers: { 'Idempotency-Key': requestKey.current },
      body: JSON.stringify({
        code: data.get('code'),
        name: data.get('name'),
        address: data.get('address'),
      }),
    }),
    onSuccess: onCreated,
  })

  return (
    <ErpModal title="Nuevo establecimiento" onClose={onClose} size="sm" initialFocusSelector='input[name="code"]' closeDisabled={createEstablishment.isPending}>
      <form className="quick-master-form" onSubmit={(event) => {
        event.preventDefault()
        event.stopPropagation()
        createEstablishment.mutate(new FormData(event.currentTarget))
      }}>
        <p className="fine-print">Usa el código registrado ante el SRI. Para la matriz suele ser 001 y no podrá cambiarse después.</p>
        <div className="erp-form-fields">
          <label>Código fiscal<input name="code" inputMode="numeric" pattern="[0-9]{3}" maxLength={3} placeholder="001" required /></label>
          <label>Nombre<input name="name" placeholder="Matriz" required /></label>
          <label>Dirección del establecimiento<textarea name="address" rows={3} required /></label>
        </div>
        {createEstablishment.error ? <p className="form-error" role="alert">{createEstablishment.error.message}</p> : null}
        <div className="erp-form-actions">
          <ErpButton variant="secondary" onClick={onClose} disabled={createEstablishment.isPending}>Cancelar</ErpButton>
          <ErpButton variant="primary" type="submit" disabled={createEstablishment.isPending}>{createEstablishment.isPending ? 'Creando…' : 'Crear establecimiento'}</ErpButton>
        </div>
      </form>
    </ErpModal>
  )
}

function EmissionPointCreateModal({
  token,
  establishments,
  onCreated,
  onClose,
}: {
  token: string
  establishments: Establishment[]
  onCreated: (emissionPoint: EmissionPoint) => void
  onClose: () => void
}) {
  const requestKey = useRef(idempotencyKey('web-emission-point-create'))
  const createEmissionPoint = useMutation({
    mutationFn: (data: FormData) => apiRequest<EmissionPoint>(token, '/emission-points', {
      method: 'POST',
      headers: { 'Idempotency-Key': requestKey.current },
      body: JSON.stringify({ establishmentId: data.get('establishmentId'), code: data.get('code') }),
    }),
    onSuccess: onCreated,
  })

  return (
    <ErpModal title="Nuevo punto de emisión" onClose={onClose} size="sm" initialFocusSelector='select[name="establishmentId"]' closeDisabled={createEmissionPoint.isPending}>
      <form className="quick-master-form" onSubmit={(event) => {
        event.preventDefault()
        event.stopPropagation()
        createEmissionPoint.mutate(new FormData(event.currentTarget))
      }}>
        <p className="fine-print">Usa el código autorizado por el SRI para este establecimiento. Para el primer punto suele ser 001 y no podrá cambiarse después.</p>
        <div className="erp-form-fields">
          <label>Establecimiento<select name="establishmentId" defaultValue={establishments[0]?.id} required>{establishments.map((item) => <option key={item.id} value={item.id}>{item.code} · {item.name}</option>)}</select></label>
          <label>Código del punto<input name="code" inputMode="numeric" pattern="[0-9]{3}" maxLength={3} placeholder="001" required /></label>
        </div>
        {createEmissionPoint.error ? <p className="form-error" role="alert">{createEmissionPoint.error.message}</p> : null}
        <div className="erp-form-actions">
          <ErpButton variant="secondary" onClick={onClose} disabled={createEmissionPoint.isPending}>Cancelar</ErpButton>
          <ErpButton variant="primary" type="submit" disabled={createEmissionPoint.isPending}>{createEmissionPoint.isPending ? 'Creando…' : 'Crear punto de emisión'}</ErpButton>
        </div>
      </form>
    </ErpModal>
  )
}

function NewInvoiceForm({
  token,
  customers,
  products,
  taxes,
  establishments,
  emissionPoints,
  defaultPaymentTermsDays,
  scopes,
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
  scopes: string[]
  onCreated: (invoiceId: string) => void
  onCancel: () => void
}) {
  const queryClient = useQueryClient()
  const { notify } = useToast()
  const [createdCustomers, setCreatedCustomers] = useState<Party[]>([])
  const [createdProducts, setCreatedProducts] = useState<Product[]>([])
  const [establishmentOverrides, setEstablishmentOverrides] = useState<Record<string, Establishment>>({})
  const [quickCreate, setQuickCreate] = useState<'customer' | 'product' | 'establishment' | null>(null)
  const availableCustomers = useMemo(
    () => Array.from(new Map([...customers, ...createdCustomers].map((item) => [item.id, item])).values()),
    [customers, createdCustomers],
  )
  const availableProducts = useMemo(
    () => Array.from(new Map([...products, ...createdProducts].map((item) => [item.id, item])).values()),
    [products, createdProducts],
  )
  const availableEstablishments = establishments.map((item) => establishmentOverrides[item.id] ?? item)
  const [customerId, setCustomerId] = useState(customers[0]?.id ?? '')
  const [establishmentId, setEstablishmentId] = useState(establishments[0]?.id ?? '')
  const [emissionPointId, setEmissionPointId] = useState(
    emissionPoints.find((point) => point.establishmentId === establishments[0]?.id)?.id ?? '',
  )
  const [issueDate, setIssueDate] = useState(todayInFiscalTimezone)
  const [lines, setLines] = useState<DraftLine[]>([emptyDraftLine()])
  const [analyticValueIds, setAnalyticValueIds] = useState<string[]>([])
  const initialCustomer = availableCustomers.find((customer) => customer.id === customerId)
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
      availableCustomers.map((customer) => ({
        value: customer.id,
        label: customer.name,
        hint: customer.identificationNumber,
      })),
    [availableCustomers],
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
    const product = availableProducts.find((item) => item.id === productId)
    updateLine(key, {
      productId,
      description: product?.name ?? '',
      unitPrice: product?.unitPrice ?? '0.00',
      taxCode: taxes.find((tax) => tax.id === product?.taxCategoryId)?.sriCode ?? product?.taxCategoryId ?? '',
    })
  }

  function addCreatedProduct(product: Product) {
    const taxCode = taxes.find((tax) => tax.id === product.taxCategoryId)?.sriCode ?? ''
    setCreatedProducts((current) => [...current, product])
    setLines((current) => {
      const emptyIndex = current.findIndex((line) => !line.productId)
      const nextLine = (line: DraftLine): DraftLine => ({
        ...line,
        productId: product.id,
        description: product.name,
        unitPrice: product.unitPrice,
        taxCode,
      })
      if (emptyIndex >= 0) return current.map((line, index) => index === emptyIndex ? nextLine(line) : line)
      return [...current, nextLine(emptyDraftLine())]
    })
    void queryClient.invalidateQueries({ queryKey: ['products'] })
    setQuickCreate(null)
    notify(`${product.name} creado y agregado`, 'success')
  }

  const createDraft = useMutation({
    mutationFn: async (payload: {
      customerId: string
      establishmentId: string
      emissionPointId: string
      issueDate: string
      lines: InvoiceLineInput[]
      analyticValueIds: string[]
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
          analyticValueIds: payload.analyticValueIds,
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
      analyticValueIds,
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
      <div className="quick-select-field">
        <div className="field-label-with-action"><span>Cliente</span>{scopes.includes('parties:write') ? <button type="button" onClick={() => setQuickCreate('customer')}>Crear cliente</button> : null}</div>
        <ErpCombobox
          ariaLabel="Cliente"
          placeholder="Buscar por nombre o identificación…"
          options={customerOptions}
          value={customerId}
          onChange={(nextId) => {
            setCustomerId(nextId)
            setPaymentTermsDays(availableCustomers.find((customer) => customer.id === nextId)?.paymentTermsDays ?? defaultPaymentTermsDays)
          }}
          required
        />
      </div>
      <AnalyticClassificationPicker token={token} valueIds={analyticValueIds} onChange={setAnalyticValueIds} />
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
            {availableEstablishments.map((establishment) => (
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
      {availableEstablishments.find((item) => item.id === establishmentId) ? (
        <div className="invoice-establishment-address">
          <span><strong>Dirección del establecimiento:</strong> {availableEstablishments.find((item) => item.id === establishmentId)?.address}</span>
          {scopes.includes('organization:write') ? <ErpButton variant="ghost" onClick={() => setQuickCreate('establishment')}>Editar dirección</ErpButton> : null}
        </div>
      ) : null}
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
        products={availableProducts}
        taxes={taxes}
        preview={previewQuery.data}
        previewPending={!previewIsCurrent}
        onProductChange={onProductChange}
        onUpdateLine={updateLine}
        onAddLine={() => setLines((current) => [...current, emptyDraftLine()])}
        onRemoveLine={(key) => setLines((current) => current.filter((item) => item.key !== key))}
        onCreateProduct={scopes.includes('products:write') ? () => setQuickCreate('product') : undefined}
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
      {quickCreate === 'customer' ? <QuickCustomerModal token={token} onClose={() => setQuickCreate(null)} onCreated={(customer) => {
        setCreatedCustomers((current) => [...current, customer])
        setCustomerId(customer.id)
        setPaymentTermsDays(customer.paymentTermsDays ?? defaultPaymentTermsDays)
        void queryClient.invalidateQueries({ queryKey: ['parties'] })
        setQuickCreate(null)
        notify(`${customer.name} creado y seleccionado`, 'success')
      }} /> : null}
      {quickCreate === 'product' ? <QuickProductModal token={token} taxes={taxes} onClose={() => setQuickCreate(null)} onCreated={addCreatedProduct} /> : null}
      {quickCreate === 'establishment' && availableEstablishments.find((item) => item.id === establishmentId) ? (
        <EstablishmentEditorModal
          token={token}
          establishment={availableEstablishments.find((item) => item.id === establishmentId)!}
          onClose={() => setQuickCreate(null)}
          onSaved={(establishment) => {
            setEstablishmentOverrides((current) => ({ ...current, [establishment.id]: establishment }))
            void queryClient.invalidateQueries({ queryKey: ['establishments'] })
            setQuickCreate(null)
            notify('Dirección de emisión actualizada', 'success')
          }}
        />
      ) : null}
    </ErpFormPanel>
  )
}

function HistoricalInvoicePdfForm({
  token,
  onCreated,
  onCancel,
}: {
  token: string
  onCreated: (invoiceId: string) => void
  onCancel: () => void
}) {
  const importPdf = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData()
      form.append('file', file)
      return apiRequest<SalesDocument>(token, '/invoices/historical-pdf', {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey('web-historical-invoice-pdf') },
        body: form,
      })
    },
    onSuccess: (invoice) => onCreated(invoice.id),
  })

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const file = new FormData(event.currentTarget).get('file')
    if (file instanceof File && file.size > 0) importPdf.mutate(file)
  }

  return (
    <ErpFormPanel
      eyebrow="Migración histórica"
      title="Cargar RIDE PDF"
      submitLabel="Crear venta histórica"
      pending={importPdf.isPending}
      error={importPdf.error?.message}
      onSubmit={submit}
      onCancel={onCancel}
    >
      <p className="fine-print">
        IAERP leerá el número, cliente, fecha y valores del PDF. La venta aparecerá en
        Facturas y reportes, pero quedará fuera del ATS, cartera y envío fiscal porque no
        existe XML.
      </p>
      <label>
        RIDE PDF de SkyFranquicias
        <input name="file" type="file" accept="application/pdf,.pdf" required />
      </label>
      <p className="fine-print">
        El cliente, establecimiento y punto de emisión deben existir. Cada PDF se valida
        por separado; IAERP no copiará fechas ni importes de otra factura.
      </p>
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
      {invoice.status === 'HISTORICAL_ISSUED' ? (
        <p className="form-warning" role="status">
          Venta histórica respaldada por este RIDE PDF. El XML no está disponible y el
          documento no entra al ATS ni a Cartera.
        </p>
      ) : null}
      <dl className="invoice-summary invoice-metadata">
        <div><dt>Cliente</dt><dd>{customer?.name ?? 'No disponible'}</dd></div>
        <div><dt>Identificación</dt><dd>{customer?.identificationNumber ?? 'No disponible'}</dd></div>
        <div><dt>Dirección</dt><dd>{customer?.address ?? 'No registrada'}</dd></div>
        <div><dt>Fecha</dt><dd>{invoice.issueDate}</dd></div>
        <div><dt>Establecimiento</dt><dd>{establishment ? `${establishment.code} · ${establishment.name}` : 'No disponible'}</dd></div>
        <div><dt>Punto de emisión</dt><dd>{emissionPoint?.code ?? 'No disponible'}</dd></div>
        <div><dt>Condición de pago</dt><dd>{invoice.status === 'HISTORICAL_ISSUED' ? 'No consta en el RIDE' : invoice.installments?.[0]?.dueDate === invoice.issueDate ? 'Contado' : 'Crédito'}</dd></div>
        <div><dt>Vencimiento</dt><dd>{invoice.status === 'HISTORICAL_ISSUED' ? 'No consta en el RIDE' : invoice.installments?.[0]?.dueDate ?? invoice.issueDate}</dd></div>
        <div><dt>Retenciones aplicadas</dt><dd>{Number(invoice.retentionTotal) > 0 ? `$${formatAmount(invoice.retentionTotal)}` : 'Sin retención registrada'}</dd></div>
        {invoice.accessKey ? <div><dt>Clave de acceso</dt><dd>{invoice.accessKey}</dd></div> : null}
        {invoice.status === 'HISTORICAL_ISSUED' && invoice.authorizationNumber ? <div><dt>Número de autorización</dt><dd>{invoice.authorizationNumber}</dd></div> : null}
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
        ) : invoice.status === 'HISTORICAL_ISSUED' ? (
          <p className="fine-print">Documento histórico: no se retransmite al SRI.</p>
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
        ) : invoice.status === 'HISTORICAL_ISSUED' ? (
          <p className="fine-print">El PDF histórico no está disponible.</p>
        ) : (
          <p className="fine-print">Los archivos estarán disponibles después de firmar la factura.</p>
        )}
      </section>

      {ridePreview ? (
        <PdfPreviewModal title={invoice.status === 'HISTORICAL_ISSUED' ? 'RIDE histórico' : 'RIDE autorizado'} artifact={ridePreview} onClose={() => setRidePreview(null)} />
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
        {invoice.status !== 'HISTORICAL_ISSUED' ? (
          <ErpButton
            variant="secondary"
            disabled={duplicateInvoice.isPending}
            onClick={() => duplicateInvoice.mutate()}
          >
            {duplicateInvoice.isPending ? 'Duplicando…' : 'Duplicar'}
          </ErpButton>
        ) : null}
        {invoice.status === 'REJECTED' || invoice.status === 'NOT_AUTHORIZED' ? (
          <ErpButton variant="danger" onClick={() => setArchiving(true)}>Archivar</ErpButton>
        ) : null}
        {invoice.status !== 'HISTORICAL_ISSUED' ? (
          <ErpButton
            variant="primary"
            disabled={!canIssue || issueInvoice.isPending}
            onClick={() => issueInvoice.mutate()}
          >
            {issueInvoice.isPending ? 'Emitiendo…' : 'Emitir'}
          </ErpButton>
        ) : null}
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
  scopes,
  partyFilterId,
}: {
  token: string
  customers: Party[]
  products: Product[]
  taxes: TaxCategory[]
  establishments: Establishment[]
  emissionPoints: EmissionPoint[]
  defaultPaymentTermsDays: number
  scopes: string[]
  /** Llega con valor al abrir Facturas desde la ficha de un cliente. */
  partyFilterId?: string
}) {
  const queryClient = useQueryClient()
  const [panel, setPanel] = useState<InvoicePanel | undefined>(undefined)
  const [archiveTarget, setArchiveTarget] = useState<SalesDocument | null>(null)
  const [archiveReason, setArchiveReason] = useState('Prueba de emisión SRI; comprobante no autorizado.')
  const lastTriggerRef = useRef<HTMLElement | null>(null)
  // El filtro se resuelve en el servidor: la lista viene acotada a 100, así
  // que filtrar en el navegador escondería facturas sin avisar.
  const invoicesQuery = useQuery({
    queryKey: ['invoices', partyFilterId ?? 'todas'],
    queryFn: () => apiRequest<SalesDocument[]>(
      token,
      partyFilterId ? `/invoices?partyId=${partyFilterId}` : '/invoices'
    ),
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
        <NewInvoiceForm token={token} customers={customers} products={products} taxes={taxes} establishments={establishments} emissionPoints={emissionPoints} defaultPaymentTermsDays={defaultPaymentTermsDays} scopes={scopes} onCreated={(invoiceId) => setPanel({ view: 'detail', id: invoiceId })} onCancel={closePanel} />
      </>
    )
  }
  if (panel?.view === 'historical') {
    return (
      <>
        <ErpPageHeader eyebrow="Migración histórica" title="Factura histórica" subtitle="Registra una venta desde su RIDE PDF sin inventar el XML." />
        <HistoricalInvoicePdfForm token={token} onCreated={(invoiceId) => setPanel({ view: 'detail', id: invoiceId })} onCancel={closePanel} />
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
          <>
            <ErpButton
              variant="secondary"
              onClick={(event) => openPanel({ view: 'historical' }, event.currentTarget)}
            >
              Cargar histórica
            </ErpButton>
            <ErpButton
              variant="primary"
              onClick={(event) => openPanel({ view: 'new' }, event.currentTarget)}
            >
              Nueva factura
            </ErpButton>
          </>
        }
      />
      <section className="split-layout erp-list-only">
        <ErpPanel title="Documentos" count={invoices.length}>
          <div className="month-group-list" aria-label="Listado de facturas">
            {invoiceMonthEntries.map(([month, monthInvoices], index) => <details key={month} className="month-group-accordion" open={index === 0}>
              <summary>
                <span className="month-group-title">{new Date(`${month}-01T12:00:00`).toLocaleDateString('es-EC', { month: 'long', year: 'numeric' })}</span>
                <span className="month-group-summary">{monthInvoices.length} factura{monthInvoices.length === 1 ? '' : 's'} · ${formatAmount(monthInvoices.reduce((total, invoice) => total + Number(invoice.total), 0))}</span>
              </summary>
            <ErpDataTable
          ariaLabel={`Facturas de ${month}`}
          rows={monthInvoices}
          rowKey={(invoice) => invoice.id}
          columns={[
            { header: 'Número', cell: (invoice) => (<><strong>{invoice.sequential}</strong></>) },
            { header: 'Cliente', cell: (invoice) => (<>{partiesById.get(invoice.partyId)?.name ?? '—'}</>) },
            { header: 'Fecha', cell: (invoice) => (<>{invoice.issueDate}</>) },
            { header: 'Estado', cell: (invoice) => (<><InvoiceStatusBadge status={invoice.status} /></>) },
            { header: 'Cobro', cell: (invoice) => (<><CollectionStatusBadge status={invoice.collectionStatus} /></>) },
            { header: 'Retenciones', cell: (invoice) => (<><ErpStatusBadge tone={Number(invoice.retentionTotal) > 0 ? 'success' : 'neutral'}>{Number(invoice.retentionTotal) > 0 ? `$${formatAmount(invoice.retentionTotal)}` : 'Sin retención'}</ErpStatusBadge></>) },
            { header: 'Clasificaciones', cell: (invoice) => (<>{(invoice.analyticAssignments ?? []).length ? (invoice.analyticAssignments ?? []).map((item) => <small key={item.classificationId}>{item.classificationName}: {item.path.map((part) => part.name).join(' / ')}</small>) : '—'}</>) },
            { header: 'Total', cell: (invoice) => (<>${formatAmount(invoice.total)}</>) },
            { header: 'Acciones', cell: (invoice) => (<><ErpActionCell>
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
                      </ErpActionCell></>) },
          ]}
        />
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

const agingLabels: Record<AgingBucket, string> = {
  CURRENT: 'Al día',
  '1-15': '1 a 15 días',
  '16-30': '16 a 30 días',
  '31-60': '31 a 60 días',
  '61-90': '61 a 90 días',
  '90+': 'Más de 90 días',
}

function AgingChip({
  aging,
  status,
}: {
  aging: AccountItem['aging']
  status: AccountItemStatus
}) {
  if (status === 'SETTLED' || status === 'VOIDED') {
    return <span className="fine-print">—</span>
  }
  if (!aging) return <span className="fine-print">Sin vencimiento</span>
  return (
    <ErpStatusBadge tone={aging.bucket === 'CURRENT' ? 'success' : aging.bucket === '90+' || aging.bucket === '61-90' ? 'danger' : 'warning'}>
      {agingLabels[aging.bucket]}
    </ErpStatusBadge>
  )
}

type ReceivablePanel =
  | { view: 'payment'; receivable: AccountItem }
  | { view: 'reminder'; receivable: AccountItem }
  | { view: 'due-date'; receivable: AccountItem }
  | { view: 'history'; receivable: AccountItem }
  | { view: 'collection-history'; receivable: AccountItem }
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
          <ErpDataTable
          ariaLabel="Resultado de XML de retención"
          rows={preview.items}
          rowKey={(item) => item.fileName}
          columns={[
            { header: 'Archivo', cell: (item) => (<>{item.fileName}</>) },
            { header: 'Factura', cell: (item) => (<>{item.invoiceSequential ?? item.supportingDocument ?? '—'}</>) },
            { header: 'Emisión', cell: (item) => (<>{item.issueDate ?? '—'}</>) },
            { header: 'Retención', cell: (item) => (<>{item.authorizationNumber ?? '—'}</>) },
            { header: 'Valor', cell: (item) => (<>${formatAmount(item.total)}</>) },
            { header: 'Resultado', cell: (item) => (<><ErpStatusBadge tone={item.status === 'MATCHED' ? 'success' : 'warning'}>{item.detail}</ErpStatusBadge></>) },
          ]}
        />
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
    mutationFn: () => apiRequest<BankStatementImport>(token, '/finance/bank-statements', {
      method: 'POST',
      body: statementFormData(false),
    }),
    onSuccess: (result) => {
      setPreview(result)
      setRegistered(false)
    },
  })
  const registerMatches = useMutation({
    mutationFn: () => apiRequest<BankStatementImport>(token, '/finance/bank-statements', {
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
      eyebrow="Bancos"
      title="Conciliar estado bancario"
      submitLabel="Revisar movimientos"
      pendingLabel="Revisando…"
      pending={previewStatement.isPending}
      error={previewStatement.error?.message}
      onSubmit={(event) => { event.preventDefault(); previewStatement.mutate() }}
      onCancel={onCancel}
    >
      <p className="fine-print">El mismo TXT cruza abonos con Cartera y débitos con Cuentas por pagar. Los cruces dudosos quedan para revisión y las reglas solo proponen gastos: nada se registra hasta que confirmes.</p>
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
            <span>{preview.matchedCount} cobro{preview.matchedCount === 1 ? '' : 's'} · {preview.payableMatchedCount ?? 0} pago{preview.payableMatchedCount === 1 ? '' : 's'} · {preview.ruleSuggestionCount ?? 0} gasto{preview.ruleSuggestionCount === 1 ? '' : 's'} sugerido{preview.ruleSuggestionCount === 1 ? '' : 's'}</span>
          </div>
          <p className="fine-print">Cuenta {preview.accountMasked ?? 'enmascarada'} · período {preview.period}. Se leyeron {preview.totalRows} movimientos: {preview.creditRows} abonos y {preview.debitRows ?? preview.ignoredDebitCount} débitos del período. Quedaron {preview.unmatchedCreditCount} abonos y {preview.unmatchedDebitCount ?? preview.ignoredDebitCount} débitos sin cruce.</p>
          {preview.matches.length > 0 ? (
            <ErpDataTable
          ariaLabel="Coincidencias del estado bancario"
          rows={preview.matches}
          rowKey={(match) => match.transactionId}
          columns={[
            { header: 'Fecha', cell: (match) => (<>{match.paymentDate}</>) },
            { header: 'Referencia bancaria', cell: (match) => (<>{match.reference}</>) },
            { header: 'Factura', cell: (match) => (<>{match.invoiceSequential}</>) },
            { header: 'Original', cell: (match) => (<>${formatAmount(match.originalAmount)}</>) },
            { header: 'Retenciones', cell: (match) => (<>${formatAmount(match.retentionTotal)}</>) },
            { header: 'Abono', cell: (match) => (<>${formatAmount(match.amount)}</>) },
            { header: 'Resultado', cell: (match) => (<><ErpStatusBadge tone="success">{match.detail}</ErpStatusBadge></>) },
          ]}
        />
          ) : null}
          {preview.manualCorrections.length > 0 ? (
            <ErpDataTable
          ariaLabel="Correcciones de cobros manuales"
          rows={preview.manualCorrections}
          rowKey={(correction) => `${correction.transactionId}-${correction.manualMovementId}`}
          columns={[
            { header: 'Fecha banco', cell: (correction) => (<>{correction.paymentDate}</>) },
            { header: 'Referencia', cell: (correction) => (<>{correction.reference}</>) },
            { header: 'Factura correcta', cell: (correction) => (<>{correction.targetInvoiceSequential}</>) },
            { header: 'Factura manual', cell: (correction) => (<>{correction.manualInvoiceSequential}</>) },
            { header: 'Valor', cell: (correction) => (<>${formatAmount(correction.amount)}</>) },
            { header: 'Resultado', cell: (correction) => (<><ErpStatusBadge tone={correction.status === 'CORRECTED' ? 'success' : 'warning'}>{correction.detail}</ErpStatusBadge></>) },
          ]}
        />
          ) : null}
          {(preview.debitMatches ?? []).length > 0 ? (
            <ErpDataTable
          ariaLabel="Pagos encontrados en el estado bancario"
          rows={(preview.debitMatches ?? [])}
          rowKey={(match) => `${match.transactionId}-${match.payableId}`}
          columns={[
            { header: 'Fecha', cell: (match) => (<>{match.paymentDate}</>) },
            { header: 'Débito', cell: (match) => (<>${formatAmount(match.allocatedAmount)}</>) },
            { header: 'Proveedor', cell: (match) => (<>{match.supplierName ?? 'Sin proveedor'}</>) },
            { header: 'Documento', cell: (match) => (<>{match.documentNumber ?? 'Gasto directo'}</>) },
            { header: 'Aplicación', cell: (match) => (<>{match.linksExistingPayment ? 'Enlazar evidencia' : 'Registrar pago'}</>) },
            { header: 'Resultado', cell: (match) => (<><ErpStatusBadge tone="success">{match.detail}</ErpStatusBadge></>) },
          ]}
        />
          ) : null}
          {(preview.debitSuggestions ?? []).length > 0 ? (
            <ErpDataTable
          ariaLabel="Débitos pendientes de revisión"
          rows={(preview.debitSuggestions ?? [])}
          rowKey={(suggestion) => suggestion.transactionId}
          columns={[
            { header: 'Fecha', cell: (suggestion) => (<>{suggestion.paymentDate}</>) },
            { header: 'Descripción', cell: (suggestion) => (<>{suggestion.description}</>) },
            { header: 'Valor', cell: (suggestion) => (<>${formatAmount(suggestion.amount)}</>) },
            { header: 'Regla', cell: (suggestion) => (<>{suggestion.ruleName ?? 'Sin regla'}</>) },
            { header: 'Resultado', cell: (suggestion) => (<><ErpStatusBadge tone="warning">{suggestion.detail}</ErpStatusBadge></>) },
          ]}
        />
          ) : null}
          {preview.matches.length === 0 && preview.manualCorrections.length === 0 && (preview.debitMatches ?? []).length === 0 && (preview.debitSuggestions ?? []).length === 0 ? (
            <ErpEmptyState title="Sin coincidencias exactas" description="Los movimientos dudosos no modificaron CxC ni CxP." />
          ) : null}
          {registerMatches.error ? <p className="form-error" role="alert">{registerMatches.error.message}</p> : null}
          {registered ? <p className="fine-print">La conciliación terminó. Solo los cobros indicados como registrados modificaron Cartera.</p> : null}
          {!registered ? (
            <ErpButton variant="primary" disabled={(preview.matchedCount + preview.manualCorrectionCount + (preview.payableMatchedCount ?? 0)) === 0 || registerMatches.isPending} onClick={() => registerMatches.mutate()}>
              {registerMatches.isPending ? 'Registrando…' : `Confirmar ${preview.matchedCount + preview.manualCorrectionCount + (preview.payableMatchedCount ?? 0)} cambio${(preview.matchedCount + preview.manualCorrectionCount + (preview.payableMatchedCount ?? 0)) === 1 ? '' : 's'}`}
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
          <ErpDataTable
          ariaLabel="Movimientos de la factura"
          rows={movementsQuery.data}
          rowKey={(movement) => movement.id}
          columns={[
            { header: 'Fecha', cell: (movement) => (<>{movement.effectiveDate
                      ? movement.effectiveDate.split('-').reverse().join('/')
                      : new Date(movement.createdAt).toLocaleString('es-EC')}</>) },
            { header: 'Tipo', cell: (movement) => (<><ErpStatusBadge tone={movement.movementType === 'RETENTION' ? 'success' : 'neutral'}>{movementLabels[movement.movementType]}</ErpStatusBadge></>) },
            { header: 'Valor', cell: (movement) => (<>${formatAmount(movement.amount)}</>) },
            { header: 'Referencia', cell: (movement) => (<>{movement.supportReference ?? '—'}</>) },
          ]}
        />
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
  const [resendReason, setResendReason] = useState('')
  const [collectionEnabled, setCollectionEnabled] = useState(receivable.collectionEnabled)
  const [collectionPermissionUpdated, setCollectionPermissionUpdated] = useState(false)
  const channelRef = useRef<HTMLSelectElement>(null)
  const queryClient = useQueryClient()

  // Se lee la plantilla configurada solo para mostrar qué se va a enviar; el
  // servidor la vuelve a renderizar con los valores reales del receivable.
  const policyQuery = useQuery({
    queryKey: ['receivables', 'collection-policy'],
    queryFn: () => apiRequest<CollectionPolicy>(token, '/receivables/collection-policy'),
  })
  const policy = policyQuery.data

  const updateCollection = useMutation({
    mutationFn: (enabled: boolean) =>
      apiRequest<AccountItem>(token, `/receivables/${receivable.id}/collection-policy`, {
        method: 'PUT',
        headers: { 'Idempotency-Key': idempotencyKey('web-receivable-collection') },
        body: JSON.stringify({ enabled }),
      }),
    onSuccess: (updated) => {
      setCollectionEnabled(updated.collectionEnabled)
      setCollectionPermissionUpdated(updated.collectionEnabled)
      void queryClient.invalidateQueries({ queryKey: ['receivables'] })
      requestAnimationFrame(() => channelRef.current?.focus())
    },
  })

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
          resendReason: resendReason || null,
        } satisfies ReminderInput),
      }),
    onSuccess: () => onSent(),
  })

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!policy?.enabled || !collectionEnabled) return
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
      submitDisabled={!policy?.enabled || !collectionEnabled || updateCollection.isPending}
      error={sendReminder.error?.message}
      onSubmit={submit}
      onCancel={onCancel}
    >
      <p className="fine-print">Saldo pendiente ${formatAmount(receivable.openAmount)}.</p>
      {policyQuery.error ? (
        <p className="form-error" role="alert">
          No se pudo leer la configuración de cobranza: {policyQuery.error.message}
        </p>
      ) : null}
      {policy && !policy.enabled ? (
        <p className="form-warning" role="alert">
          La cobranza general está pausada. Actívala en Empresa → Cobranza automática.
        </p>
      ) : null}
      {!collectionEnabled ? (
        <section className="form-warning" aria-labelledby="collection-permission-title">
          <strong id="collection-permission-title">Esta factura no permite mensajes de cobranza.</strong>
          <p>Activa el permiso para poder enviar o programar este correo.</p>
          <ErpButton
            variant="secondary"
            type="button"
            disabled={updateCollection.isPending}
            onClick={() => updateCollection.mutate(true)}
          >
            {updateCollection.isPending ? 'Activando…' : 'Permitir cobranza para esta factura'}
          </ErpButton>
          {updateCollection.error ? <p className="form-error" role="alert">{updateCollection.error.message}</p> : null}
        </section>
      ) : null}
      {collectionPermissionUpdated ? (
        <p className="form-success" role="status">Cobranza permitida. Ya puedes enviar o programar el correo.</p>
      ) : null}
      <label>
        Canal
        <select ref={channelRef} value={channel} onChange={(event) => setChannel(event.target.value as ReminderInput['channel'])} required>
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
        Programar para
        <input
          type="datetime-local"
          value={scheduledAt}
          onChange={(event) => {
            setScheduledAt(event.target.value)
            if (event.target.value) setMessage('')
          }}
        />
      </label>
      {scheduledAt ? (
        <p className="fine-print" role="status">Los correos programados usan la plantilla general configurada arriba.</p>
      ) : (
        <label>
          Mensaje personalizado
          <textarea
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            rows={4}
            placeholder="Opcional: reemplaza el cuerpo. El saldo y los datos de pago se agregan igual."
          />
        </label>
      )}
      <label>
        Motivo para reenviar
        <textarea value={resendReason} onChange={(event) => setResendReason(event.target.value)} rows={2} placeholder="Solo si ya hubo un envío igual." />
      </label>
    </ErpFormPanel>
  )
}

const collectionOutcomeLabels: Record<string, string> = {
  PENDING: 'Pendiente', SENT: 'Enviado', PROCESSING: 'En proceso', FAILED: 'Falló', SKIPPED: 'Omitido',
  CONTACTED: 'Contactado', PROMISE_TO_PAY: 'Prometió pagar', NO_RESPONSE: 'Sin respuesta', WRONG_CONTACT: 'Contacto incorrecto',
}

function CollectionHistoryPanel({ token, receivable, onClose }: { token: string; receivable: AccountItem; onClose: () => void }) {
  const [channel, setChannel] = useState<CollectionContactInput['channel']>('CALL')
  const [outcome, setOutcome] = useState<CollectionContactInput['outcome']>('CONTACTED')
  const [note, setNote] = useState('')
  const queryClient = useQueryClient()
  const historyQuery = useQuery({
    queryKey: ['receivables', receivable.id, 'collection-history'],
    queryFn: () => apiRequest<CollectionHistoryEntry[]>(token, `/receivables/${receivable.id}/collection-history`),
  })
  const createContact = useMutation({
    mutationFn: () => apiRequest<CollectionHistoryEntry>(token, `/receivables/${receivable.id}/contacts`, {
      method: 'POST', headers: { 'Idempotency-Key': idempotencyKey('web-collection-contact') },
      body: JSON.stringify({ channel, outcome, note: note || null } satisfies CollectionContactInput),
    }),
    onSuccess: () => { setNote(''); void queryClient.invalidateQueries({ queryKey: ['receivables', receivable.id, 'collection-history'] }) },
  })
  return <>
    <ErpFormPanel eyebrow="Cobranza" title="Registrar gestión" submitLabel="Guardar" pending={createContact.isPending} error={createContact.error?.message} onSubmit={(event) => { event.preventDefault(); createContact.mutate() }} onCancel={onClose}>
      <label>Canal<select value={channel} onChange={(event) => setChannel(event.target.value as CollectionContactInput['channel'])}><option value="CALL">Llamada</option><option value="EMAIL">Correo</option><option value="WHATSAPP">WhatsApp</option><option value="NOTE">Nota</option></select></label>
      <label>Resultado<select value={outcome} onChange={(event) => setOutcome(event.target.value as CollectionContactInput['outcome'])}><option value="CONTACTED">Contactado</option><option value="PROMISE_TO_PAY">Prometió pagar</option><option value="NO_RESPONSE">Sin respuesta</option><option value="WRONG_CONTACT">Contacto incorrecto</option><option value="PENDING">Pendiente</option></select></label>
      <label>Nota<textarea value={note} maxLength={1000} rows={3} onChange={(event) => setNote(event.target.value)} placeholder="Resumen breve, sin pegar el chat completo." /></label>
    </ErpFormPanel>
    <ErpPanel title="Historia de cobranza" count={historyQuery.data?.length ?? 0}>
      {historyQuery.isLoading ? <p className="fine-print">Cargando…</p> : null}
      {historyQuery.error ? <p className="form-warning" role="alert">{historyQuery.error.message}</p> : null}
      <ol className="collection-history-list">{(historyQuery.data ?? []).map((entry) => <li key={`${entry.kind}-${entry.id}`}><strong>{entry.kind === 'REMINDER' ? 'Envío' : 'Contacto'} · {entry.channel}</strong><span>{new Date(entry.occurredAt).toLocaleString('es-EC')}</span><p>{collectionOutcomeLabels[entry.outcome] ?? entry.outcome}{entry.deliveryStatus && entry.deliveryStatus !== 'UNKNOWN' ? ` · ${entry.deliveryStatus === 'READ' ? 'Leído' : entry.deliveryStatus === 'DELIVERED' ? 'Entregado' : entry.deliveryStatus === 'SENT' ? 'Enviado al proveedor' : entry.deliveryStatus}` : ''}</p>{entry.note ? <p className="fine-print">{entry.note}</p> : null}</li>)}</ol>
      {!historyQuery.isLoading && (historyQuery.data?.length ?? 0) === 0 ? <ErpEmptyState title="Sin gestiones" description="Registra la primera llamada, nota o envío desde Cobranza." /> : null}
    </ErpPanel>
  </>
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
  partyFilterId,
}: {
  token: string
  parties: Party[]
  /** Llega con valor al abrir Cartera desde la ficha de un contacto. */
  partyFilterId?: string
}) {
  const queryClient = useQueryClient()
  const [statusFilter, setStatusFilter] = useState<'' | 'OUTSTANDING' | AccountItemStatus>('OUTSTANDING')
  const [panel, setPanel] = useState<ReceivablePanel | undefined>(undefined)
  const lastTriggerRef = useRef<HTMLElement | null>(null)
  const partiesById = new Map(parties.map((party) => [party.id, party]))
  const receivablesQuery = useQuery({
    queryKey: ['receivables', statusFilter, partyFilterId ?? 'todos'],
    queryFn: () => {
      const params = new URLSearchParams()
      if (statusFilter && statusFilter !== 'OUTSTANDING') params.set('status', statusFilter)
      if (partyFilterId) params.set('partyId', partyFilterId)
      const consulta = params.toString()
      return apiRequest<AccountItem[]>(token, consulta ? `/receivables?${consulta}` : '/receivables')
    },
  })
  const receivables = (receivablesQuery.data ?? [])
    .filter((item) => statusFilter === 'OUTSTANDING'
      ? ['OPEN', 'PARTIAL', 'OVERDUE'].includes(item.status)
      : true)
    .slice()
    .sort((left, right) => (right.daysSinceInvoice ?? -1) - (left.daysSinceInvoice ?? -1))
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
  if (panel?.view === 'collection-history') {
    return (
      <>
        <ErpPageHeader eyebrow="Cuentas por cobrar" title="Historia de cobranza" subtitle={`Factura ${panel.receivable.invoiceSequential ?? 'sin número disponible'}`} />
        <CollectionHistoryPanel token={token} receivable={panel.receivable} onClose={closePanel} />
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
        <ErpPageHeader eyebrow="Cuentas por cobrar y pagar" title="Conciliar banco" subtitle="Una carga cruza abonos con CxC y débitos con CxP; los gastos sugeridos siempre requieren confirmación." />
        <BankStatementImportForm
          token={token}
          onRegistered={() => {
            void queryClient.invalidateQueries({ queryKey: ['receivables'] })
            void queryClient.invalidateQueries({ queryKey: ['payables'] })
          }}
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
          <ErpDataTable
            ariaLabel="Listado de cuentas por cobrar"
            rows={receivables}
            rowKey={(receivable) => receivable.id}
            emptyState={<ErpEmptyState
                title="No hay cuentas por cobrar"
                description="La cartera se genera automáticamente al autorizar una factura."
              />}
            columns={[
              { header: 'Cliente', cell: (receivable) => (<><strong>{partiesById.get(receivable.partyId)?.name ?? receivable.partyId}</strong></>) },
              { header: 'Factura', cell: (receivable) => (<>{receivable.invoiceSequential ?? '—'}</>) },
              { header: 'Monto original', cell: (receivable) => (<>${formatAmount(receivable.originalAmount)}</>) },
              { header: 'Saldo', cell: (receivable) => (<>${formatAmount(receivable.openAmount)}</>) },
              { header: 'Estado', cell: (receivable) => (<><ReceivableStatusBadge status={receivable.status} /></>) },
              { header: 'Días desde factura', cell: (receivable) => (<>{receivable.daysSinceInvoice === undefined || receivable.daysSinceInvoice === null ? '—' : `${receivable.daysSinceInvoice} días`}</>) },
              { header: 'Aging', cell: (receivable) => (<><AgingChip aging={receivable.aging} status={receivable.status} /></>) },
              { header: 'Acciones', cell: (receivable) => (<>{/* Iconos y no texto: cuatro acciones escritas empujaban la
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
                          aria-label={`Ver historia de cobranza de ${partiesById.get(receivable.partyId)?.name ?? receivable.partyId}`}
                          title="Historia de cobranza"
                          onClick={(event) => openPanel({ view: 'collection-history', receivable }, event.currentTarget)}
                        >
                          <MessageSquare size={16} aria-hidden="true" />
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
                      </ErpActionCell></>) },
            ]}
          />
        </ErpPanel>
      </section>
    </>
  )
}

function OrganizationPage({
  context,
  establishments,
  emissionPoints,
  token,
}: {
  context: TenantContext
  establishments: Establishment[]
  emissionPoints: EmissionPoint[]
  token: string
}) {
  const queryClient = useQueryClient()
  const { notify } = useToast()
  const [editingEstablishment, setEditingEstablishment] = useState<Establishment | null>(null)
  const [isCreatingEstablishment, setIsCreatingEstablishment] = useState(false)
  const [isCreatingEmissionPoint, setIsCreatingEmissionPoint] = useState(false)
  const [statusChange, setStatusChange] = useState<{ type: 'establishment'; item: Establishment } | { type: 'emissionPoint'; item: EmissionPoint } | null>(null)
  const [settingsSection, setSettingsSection] = useState<'fiscal' | 'invoicing' | 'collections' | 'integrations' | 'analytics'>('fiscal')
  const fiscalQuery = useQuery({
    queryKey: ['organization', 'fiscal-settings'],
    queryFn: () => apiRequest<FiscalSettings>(token, '/organization/fiscal-settings'),
  })
  const allEstablishmentsQuery = useQuery({
    queryKey: ['organization', 'establishments', 'all'],
    queryFn: () => apiRequest<Establishment[]>(token, '/establishments?include_inactive=true'),
  })
  const allEmissionPointsQuery = useQuery({
    queryKey: ['organization', 'emission-points', 'all'],
    queryFn: () => apiRequest<EmissionPoint[]>(token, '/emission-points?include_inactive=true'),
  })
  const updateMasterStatus = useMutation({
    mutationFn: ({ type, item }: { type: 'establishment'; item: Establishment } | { type: 'emissionPoint'; item: EmissionPoint }) => apiRequest<Establishment | EmissionPoint>(token, type === 'establishment' ? `/establishments/${item.id}` : `/emission-points/${item.id}`, {
      method: 'PUT', headers: { 'Idempotency-Key': idempotencyKey(`web-${type}-status`) }, body: JSON.stringify({ active: !item.active }),
    }),
    onSuccess: () => {
      setStatusChange(null)
      void queryClient.invalidateQueries({ queryKey: ['establishments'] })
      void queryClient.invalidateQueries({ queryKey: ['emission-points'] })
      void queryClient.invalidateQueries({ queryKey: ['organization', 'establishments'] })
      void queryClient.invalidateQueries({ queryKey: ['organization', 'emission-points'] })
    },
  })
  const integrationsQuery = useQuery({
    queryKey: ['crm', 'integrations'],
    queryFn: () => apiRequest<IntegrationStatus>(token, '/crm/integrations'),
  })
  const metaAdsQuery = useQuery({
    queryKey: ['crm', 'integrations', 'meta-ads'],
    queryFn: () => apiRequest<MetaAdsIntegration>(token, '/crm/integrations/meta-ads'),
  })
  const campaignPolicyQuery = useQuery({
    queryKey: ['crm', 'campaign-policy'],
    queryFn: () => apiRequest<SocialCampaignPolicy>(token, '/crm/campaigns/policy'),
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
  const saveMetaAds = useMutation({
    mutationFn: (data: object) => apiRequest<MetaAdsIntegration>(token, '/crm/integrations/meta-ads', {
      method: 'PUT',
      headers: { 'Idempotency-Key': idempotencyKey('web-meta-ads') },
      body: JSON.stringify(data),
    }),
    onSuccess: (integration) => queryClient.setQueryData(['crm', 'integrations', 'meta-ads'], integration),
  })
  const saveCampaignPolicy = useMutation({
    mutationFn: (data: object) => apiRequest<SocialCampaignPolicy>(token, '/crm/campaigns/policy', {
      method: 'PUT',
      headers: { 'Idempotency-Key': idempotencyKey('web-campaign-policy') },
      body: JSON.stringify(data),
    }),
    onSuccess: (policy) => queryClient.setQueryData(['crm', 'campaign-policy'], policy),
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

  function submitMetaAds(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    saveMetaAds.mutate({
      adAccountId: data.get('adAccountId'),
      pageId: data.get('pageId'),
      instagramActorId: data.get('instagramActorId') || null,
      defaultLeadFormId: data.get('defaultLeadFormId'),
      accessToken: data.get('accessToken'),
      appSecret: data.get('appSecret'),
      verifyToken: data.get('verifyToken'),
    })
  }

  function submitCampaignPolicy(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    saveCampaignPolicy.mutate({
      activationEnabled: data.get('activationEnabled') === 'on',
      dailyBudgetLimit: data.get('dailyBudgetLimit'),
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
  const managedEstablishments = allEstablishmentsQuery.data ?? establishments
  const managedEmissionPoints = allEmissionPointsQuery.data ?? emissionPoints
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
        <ErpButton variant={settingsSection === 'analytics' ? 'primary' : 'secondary'} onClick={() => setSettingsSection('analytics')}>Clasificaciones</ErpButton>
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
        <ErpPanel title="Establecimientos" count={managedEstablishments.length} actions={context.scopes.includes('organization:write') ? <ErpButton variant="secondary" onClick={() => setIsCreatingEstablishment(true)}>Nuevo establecimiento</ErpButton> : null}>
          <ul className="establishment-list">
            {managedEstablishments.map((item) => <li key={item.id}><span>{item.code}</span><div><strong>{item.name}</strong><small>{item.address}{item.active ? '' : ' · Inactivo'}</small></div>{context.scopes.includes('organization:write') ? <div className="erp-form-actions"><ErpButton variant="ghost" onClick={() => setEditingEstablishment(item)}>Editar</ErpButton><ErpButton variant={item.active ? 'danger' : 'secondary'} onClick={() => setStatusChange({ type: 'establishment', item })}>{item.active ? 'Desactivar' : 'Reactivar'}</ErpButton></div> : null}</li>)}
          </ul>
        </ErpPanel>
        <ErpPanel title="Puntos de emisión" count={managedEmissionPoints.length} actions={context.scopes.includes('organization:write') ? <ErpButton variant="secondary" onClick={() => setIsCreatingEmissionPoint(true)} disabled={establishments.length === 0}>Nuevo punto de emisión</ErpButton> : null}>
          {managedEmissionPoints.length === 0 ? <p className="fiscal-panel-copy">Crea un punto por cada establecimiento antes de emitir facturas.</p> : (
            <ul className="establishment-list">
              {managedEmissionPoints.map((item) => {
                const establishment = managedEstablishments.find((candidate) => candidate.id === item.establishmentId)
                return <li key={item.id}><span>{item.code}</span><div><strong>{item.code}</strong><small>{establishment ? `${establishment.code} · ${establishment.name}` : 'Establecimiento no disponible'}{item.active ? '' : ' · Inactivo'}</small></div>{context.scopes.includes('organization:write') ? <ErpButton variant={item.active ? 'danger' : 'secondary'} onClick={() => setStatusChange({ type: 'emissionPoint', item })}>{item.active ? 'Desactivar' : 'Reactivar'}</ErpButton> : null}</li>
              })}
            </ul>
          )}
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
        {statusChange ? <ErpConfirmDialog title={`${statusChange.item.active ? 'Desactivar' : 'Reactivar'} ${statusChange.type === 'establishment' ? 'establecimiento' : 'punto de emisión'}`} description={statusChange.item.active ? 'Los comprobantes ya emitidos se conservan. El registro dejará de aparecer al crear nuevos comprobantes.' : 'El registro volverá a estar disponible para nuevos comprobantes.'} confirmLabel={statusChange.item.active ? 'Desactivar' : 'Reactivar'} danger={statusChange.item.active} pending={updateMasterStatus.isPending} onConfirm={() => updateMasterStatus.mutate(statusChange)} onCancel={() => setStatusChange(null)} /> : null}
        {settingsSection === 'analytics' ? <AnalyticClassificationSettings token={token} /> : null}
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
        <ErpPanel title="Meta Ads · Facebook e Instagram" actions={<ErpStatusBadge tone={metaAdsQuery.data?.connected ? 'success' : 'warning'}>{metaAdsQuery.data?.connected ? 'Conectado' : 'Pendiente'}</ErpStatusBadge>} className="fiscal-settings-panel">
          <form className="fiscal-panel-body" onSubmit={submitMetaAds}>
            <p className="fiscal-panel-copy">Esta conexión permite crear campañas de formularios desde el CRM y recibir cada respuesta como lead nuevo.</p>
            {metaAdsQuery.data?.connected ? <p>Cuenta activa: <strong>{metaAdsQuery.data.adAccountId}</strong> · Página <strong>{metaAdsQuery.data.pageId}</strong></p> : null}
            <label>Ad Account ID<input name="adAccountId" defaultValue={metaAdsQuery.data?.adAccountId ?? ''} required /></label>
            <label>Page ID<input name="pageId" defaultValue={metaAdsQuery.data?.pageId ?? ''} required /></label>
            <label>Instagram Actor ID<input name="instagramActorId" defaultValue={metaAdsQuery.data?.instagramActorId ?? ''} /></label>
            <label>Formulario instantáneo por defecto<input name="defaultLeadFormId" defaultValue={metaAdsQuery.data?.defaultLeadFormId ?? ''} required /></label>
            <label>Token permanente<input name="accessToken" type="password" autoComplete="new-password" minLength={20} required /></label>
            <label>Meta App Secret<input name="appSecret" type="password" autoComplete="new-password" minLength={10} required /></label>
            <label>Verify token<input name="verifyToken" type="password" autoComplete="new-password" minLength={16} required /></label>
            {metaAdsQuery.data ? <p className="fine-print">Webhook de leads: {metaAdsQuery.data.webhookUrl}</p> : null}
            {saveMetaAds.error ? <p className="form-error">{saveMetaAds.error.message}</p> : null}
            <ErpButton variant="primary" type="submit" disabled={saveMetaAds.isPending}>{saveMetaAds.isPending ? 'Guardando…' : metaAdsQuery.data?.connected ? 'Actualizar conexión' : 'Guardar conexión'}</ErpButton>
          </form>
        </ErpPanel>
        <ErpPanel title="Control de gasto en campañas" actions={<ErpStatusBadge tone={campaignPolicyQuery.data?.activationEnabled ? 'warning' : 'neutral'}>{campaignPolicyQuery.data?.activationEnabled ? 'Habilitado' : 'Bloqueado'}</ErpStatusBadge>} className="fiscal-settings-panel">
          {campaignPolicyQuery.isPending ? <p className="fiscal-panel-copy">Cargando control de gasto…</p> : null}
          {campaignPolicyQuery.error ? <p className="form-error" role="alert">{campaignPolicyQuery.error.message}</p> : null}
          {campaignPolicyQuery.data ? <form key={`${campaignPolicyQuery.data.activationEnabled}-${campaignPolicyQuery.data.dailyBudgetLimit}`} className="fiscal-panel-body" onSubmit={submitCampaignPolicy}>
            <p className="fiscal-panel-copy">El interruptor bloquea toda activación. El tope suma el presupuesto diario de las campañas activas del tenant.</p>
            <label><input name="activationEnabled" type="checkbox" defaultChecked={campaignPolicyQuery.data.activationEnabled} /> Permitir que un propietario active gasto</label>
            <label>Tope diario total<input name="dailyBudgetLimit" type="number" min="0" max="10000" step="0.01" defaultValue={campaignPolicyQuery.data.dailyBudgetLimit} required /></label>
            <p className="fine-print">Presupuesto activo actual: {campaignPolicyQuery.data.activeDailyBudget}</p>
            {saveCampaignPolicy.error ? <p className="form-error" role="alert">{saveCampaignPolicy.error.message}</p> : null}
            <ErpButton variant="primary" type="submit" disabled={saveCampaignPolicy.isPending}>{saveCampaignPolicy.isPending ? 'Guardando…' : 'Guardar control de gasto'}</ErpButton>
          </form> : null}
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
      {editingEstablishment ? (
        <EstablishmentEditorModal
          token={token}
          establishment={editingEstablishment}
          onClose={() => setEditingEstablishment(null)}
          onSaved={() => {
            void queryClient.invalidateQueries({ queryKey: ['establishments'] })
            setEditingEstablishment(null)
            notify('Dirección del establecimiento actualizada', 'success')
          }}
        />
      ) : null}
      {isCreatingEstablishment ? (
        <EstablishmentCreateModal
          token={token}
          onClose={() => setIsCreatingEstablishment(false)}
          onCreated={() => {
            void queryClient.invalidateQueries({ queryKey: ['establishments'] })
            setIsCreatingEstablishment(false)
            notify('Establecimiento creado', 'success')
          }}
        />
      ) : null}
      {isCreatingEmissionPoint ? (
        <EmissionPointCreateModal
          token={token}
          establishments={establishments}
          onClose={() => setIsCreatingEmissionPoint(false)}
          onCreated={() => {
            void queryClient.invalidateQueries({ queryKey: ['emission-points'] })
            setIsCreatingEmissionPoint(false)
            notify('Punto de emisión creado', 'success')
          }}
        />
      ) : null}
    </>
  )
}

function Workspace() {
  const auth = useAuth()
  const [section, setSection] = useState<Section>('overview')
  const [navigationVersion, setNavigationVersion] = useState(0)
  const [contractPartyId, setContractPartyId] = useState<string | undefined>()
  // Contacto por el que vienen filtradas facturas, cartera o compras al llegar
  // desde su ficha. Se limpia al navegar a cualquier otra parte.
  const [partyFilterId, setPartyFilterId] = useState<string | undefined>()
  const [taxInitialTab, setTaxInitialTab] = useState<'month' | 'year'>('month')
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
          if (newSection === 'tax') setTaxInitialTab('month')
          setPartyFilterId(undefined)
          startTransition(() => {
            setSection(newSection)
            setNavigationVersion((current) => current + 1)
          })
          window.requestAnimationFrame(() => document.getElementById('main-content')?.focus())
        }}
        organizationName={contextQuery.data.name}
        ruc={contextQuery.data.ruc}
      />
      <main id="main-content" tabIndex={-1}>
       <div key={`${section}-${navigationVersion}`} className="section-fade">
        {/* Sin este aviso la lista aparece recortada sin explicación. */}
        {partyFilterId ? (
          <p className="party-filter-notice" role="status">
            <span>
              Viendo solo lo de <strong>{parties.find((party) => party.id === partyFilterId)?.name ?? 'este contacto'}</strong>
            </span>
            <ErpButton variant="secondary" onClick={() => setPartyFilterId(undefined)}>
              Ver todo
            </ErpButton>
          </p>
        ) : null}
        {section === 'overview' ? (
          <Overview
            context={contextQuery.data}
            token={token}
            onOpenAnnualTax={() => {
              setTaxInitialTab('year')
              startTransition(() => {
                setSection('tax')
                setNavigationVersion((current) => current + 1)
              })
              window.requestAnimationFrame(() => document.getElementById('main-content')?.focus())
            }}
          />
        ) : null}
        {section === 'parties' ? <PartiesPage parties={parties} token={token} onOpenContracts={(partyId) => { setContractPartyId(partyId); startTransition(() => setSection('contracts')) }} onOpenPartySection={(partyId, destino) => { setPartyFilterId(partyId); startTransition(() => setSection(destino)) }} /> : null}
        {section === 'catalogs' ? <ProductsPage products={products} taxes={taxesQuery.data ?? []} token={token} /> : null}
        {section === 'invoices' ? (
          <InvoicesPage
            partyFilterId={partyFilterId}
            token={token}
            customers={parties.filter((party) => party.roles.includes('CUSTOMER'))}
            products={products}
            taxes={taxesQuery.data ?? []}
            establishments={establishmentsQuery.data ?? []}
            emissionPoints={emissionPointsQuery.data ?? []}
            defaultPaymentTermsDays={contextQuery.data.defaultPaymentTermsDays}
            scopes={contextQuery.data.scopes}
          />
        ) : null}
        {section === 'purchases' ? (
          <ErrorBoundary label="Compras">
            <Suspense fallback={<SectionLoadingSkeleton label="Cargando compras…" />}>
              <PurchasesPage token={token} partyFilterId={partyFilterId} />
            </Suspense>
          </ErrorBoundary>
        ) : null}
        {section === 'organization' ? <OrganizationPage context={contextQuery.data} establishments={establishmentsQuery.data ?? []} emissionPoints={emissionPointsQuery.data ?? []} token={token} /> : null}
        {section === 'payroll' ? (
          <ErrorBoundary label="Nómina">
            <Suspense fallback={<SectionLoadingSkeleton label="Cargando nómina…" />}>
              <PayrollPage token={token} />
            </Suspense>
          </ErrorBoundary>
        ) : null}
        {section === 'receivables' ? <ReceivablesPage token={token} parties={parties} partyFilterId={partyFilterId} /> : null}
        {section === 'contracts' ? <ContractsPage key={contractPartyId ?? 'all-contracts'} parties={parties} products={products} taxes={taxesQuery.data ?? []} establishments={establishmentsQuery.data ?? []} emissionPoints={emissionPointsQuery.data ?? []} token={token} initialPartyId={contractPartyId} /> : null}
        {section === 'crm' ? (
          <ErrorBoundary label="el CRM">
            <Suspense fallback={<SectionLoadingSkeleton label="Cargando CRM…" />}>
              <LeadsPage token={token} parties={parties} products={products} />
            </Suspense>
          </ErrorBoundary>
        ) : null}
        {section === 'action-queue' ? (
          <ErrorBoundary label="la bandeja de acción">
            <Suspense fallback={<SectionLoadingSkeleton label="Cargando bandeja de acción…" />}>
              <ActionQueuePage
                token={token}
                scopes={contextQuery.data.scopes}
                onGoToSettings={() => {
                  startTransition(() => {
                    setSection('organization')
                    setNavigationVersion((current) => current + 1)
                  })
                }}
              />
            </Suspense>
          </ErrorBoundary>
        ) : null}
        {section === 'tax' ? (
          <ErrorBoundary label="el módulo tributario">
            <Suspense fallback={<SectionLoadingSkeleton label="Cargando Tributario…" />}>
              <TaxPage token={token} initialTab={taxInitialTab} />
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
