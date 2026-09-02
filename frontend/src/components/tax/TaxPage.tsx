import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'

import {
  apiRequest,
  idempotencyKey,
  type DashboardTax,
  type TaxBulkResult,
  type AnalyticClassification,
  type TaxDocumentDossier,
  type TaxAnnex,
  type TaxFiscalDocument,
  type TaxIvaSummary,
  type TaxOwnDocumentsResult,
  type TaxPeriod,
  type TaxXmlRecoveryJob,
} from '../../api'
import { ErpButton, ErpDataTable, ErpEmptyState, ErpMetricGrid, ErpPageHeader, ErpPanel, ErpStatusBadge } from '../erp'
import './TaxPage.css'

const MONTHS = [
  'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
  'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre',
]

const STATUS_LABELS: Record<string, string> = {
  PENDIENTE_DESCARGA: 'Pendiente de bajar del SRI',
  EVIDENCIA_INCOMPLETA: 'Evidencia incompleta',
  LISTO_REVISAR: 'Listo para revisar',
  LISTO_DECLARAR: 'Listo para declarar',
  DECLARADO: 'Declarado',
}

const STATUS_TONES: Record<string, 'neutral' | 'success' | 'warning' | 'danger'> = {
  PENDIENTE_DESCARGA: 'neutral',
  EVIDENCIA_INCOMPLETA: 'warning',
  LISTO_REVISAR: 'warning',
  LISTO_DECLARAR: 'success',
  DECLARADO: 'success',
}

function monthName(month: number): string {
  return MONTHS[month - 1] ?? String(month)
}

function formatDashboardCurrency(value: string): string {
  const match = /^(-?)(\d+)(?:\.(\d{1,2}))?$/.exec(value)
  if (!match) return `$${value}`
  const sign = match[1] ?? ''
  const integer = match[2] ?? '0'
  const decimal = match[3] ?? ''
  const grouped = integer.replace(/\B(?=(\d{3})+(?!\d))/g, '.')
  return `${sign}$${grouped},${decimal.padEnd(2, '0')}`
}

const MOVEMENT_LABELS: Record<string, string> = {
  PAYMENT: 'Cobro',
  RETENTION: 'Retención aplicada',
  DISCOUNT: 'Descuento',
  CREDIT_NOTE: 'Nota de crédito',
  REVERSAL: 'Reverso',
}

const DOCUMENT_TYPE_LABELS: Record<string, string> = {
  FACTURA: 'Factura',
  RETENCION: 'Retención',
  NOTA_CREDITO: 'Nota de crédito',
  NOTA_DEBITO: 'Nota de débito',
  LIQUIDACION: 'Liquidación',
}

type TaxTab = 'month' | 'year' | 'retentions'

type HistoricalTaxCandidate = {
  id: string
  documentNumber: string
  accessKey: string
  issueDate: string
  customerName: string
  subtotal: string
  taxTotal: string
  total: string
  approved: boolean
  xmlOriginalMissing: boolean
}

/**
 * Historia del comprobante: qué retención le hicieron, qué cobros entraron (con
 * su referencia bancaria si vinieron del extracto) y cuánto falta.
 */
function DossierView({ dossier }: { dossier: TaxDocumentDossier }) {
  return (
    <div className="tax-dossier">
      <ul className="tax-dossier-tree">
        <li className="tax-dossier-root">
          <strong>{dossier.docType}</strong> {dossier.accessKey ?? ''} · ${dossier.total}
        </li>

        {dossier.retentions.map((retention) => (
          <li key={retention.accessKey ?? retention.issueDate}>
            <span className="tax-dossier-label">Retención</span> {retention.issueDate}
            {retention.issuerName ? ` · ${retention.issuerName}` : ''}
            <br />
            <small>
              IVA ${retention.ivaAmount} · Renta ${retention.incomeTaxAmount}
            </small>
          </li>
        ))}

        {dossier.movements.map((movement, index) => (
          <li key={`${movement.movementType}-${index}`}>
            <span className="tax-dossier-label">
              {MOVEMENT_LABELS[movement.movementType] ?? movement.movementType}
            </span>{' '}
            ${movement.amount}
            {movement.bankReference ? (
              <>
                <br />
                <small>Banco · {movement.bankReference}</small>
              </>
            ) : movement.reference ? (
              <>
                <br />
                <small>Ref. {movement.reference}</small>
              </>
            ) : null}
          </li>
        ))}
      </ul>

      <dl className="tax-dossier-summary">
        <div>
          <dt>Retención IVA</dt><dd>${dossier.retainedIva}</dd>
        </div>
        <div>
          <dt>Retención renta</dt><dd>${dossier.retainedIncomeTax}</dd>
        </div>
        {dossier.docType !== 'RETENCION' ? (
          <div className="tax-dossier-net">
            <dt>Neto esperado</dt><dd>${dossier.expectedNet}</dd>
          </div>
        ) : null}
        {dossier.receivableId ? (
          <>
            <div><dt>Cobrado</dt><dd>${dossier.collectedAmount}</dd></div>
            <div><dt>Pendiente</dt><dd>${dossier.outstandingAmount}</dd></div>
          </>
        ) : null}
      </dl>

      {dossier.notes.map((note) => (
        <p key={note} className="fine-print">{note}</p>
      ))}
    </div>
  )
}

/**
 * Sección tributaria (ADR 0012): evidencia del SRI por periodo y valores listos
 * para copiar al formulario. Nada se calcula en el cliente; todo viene del
 * servidor con la trazabilidad de los documentos que respaldan cada cifra.
 */
export function TaxPage({
  token,
  initialTab = 'month',
}: {
  token: string
  initialTab?: TaxTab
}) {
  const queryClient = useQueryClient()
  const [selectedPeriodId, setSelectedPeriodId] = useState<string | null>(null)
  const [copiedField, setCopiedField] = useState<string | null>(null)
  const [generatedAnnex, setGeneratedAnnex] = useState<TaxAnnex | null>(null)
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const [applyRetentions, setApplyRetentions] = useState(false)
  const [openDossierId, setOpenDossierId] = useState<string | null>(null)
  const [exceptionEvidence, setExceptionEvidence] = useState<Record<string, string>>({})
  const [groupByClassificationId, setGroupByClassificationId] = useState('')
  const [incomeTaxScenario, setIncomeTaxScenario] = useState<'NONE' | '25'>('NONE')
  const evidenceInputRef = useRef<HTMLInputElement>(null)

  const periodsQuery = useQuery({
    queryKey: ['tax', 'periods'],
    queryFn: () => apiRequest<TaxPeriod[]>(token, '/tax/periods'),
  })

  const periods = useMemo(
    () => (periodsQuery.data ?? []).filter((period) => period.obligationType === 'IVA'),
    [periodsQuery.data],
  )
  const activePeriodId = selectedPeriodId ?? periods[0]?.id ?? null
  const activePeriod = periods.find((period) => period.id === activePeriodId) ?? null

  const dashboardAsOf = activePeriod
    ? `${activePeriod.year}-${String(activePeriod.month).padStart(2, '0')}-01`
    : undefined
  const dashboardParameters = new URLSearchParams()
  if (dashboardAsOf) dashboardParameters.set('as_of', dashboardAsOf)
  if (incomeTaxScenario === '25') dashboardParameters.set('income_tax_rate', '25')
  const dashboardQueryString = dashboardParameters.toString()
  const dashboardQuery = useQuery({
    queryKey: ['tax', 'dashboard', dashboardAsOf, incomeTaxScenario],
    queryFn: () => apiRequest<DashboardTax>(
      token,
      `/tax/dashboard${dashboardQueryString ? `?${dashboardQueryString}` : ''}`,
    ),
  })

  useEffect(() => {
    if (initialTab !== 'year' || dashboardQuery.isPending) return
    window.requestAnimationFrame(() => {
      document.querySelector('#tax-section-year')?.scrollIntoView({ block: 'start' })
    })
  }, [dashboardQuery.isPending, initialTab])

  const ivaQuery = useQuery({
    queryKey: ['tax', 'iva', activePeriodId],
    queryFn: () => apiRequest<TaxIvaSummary>(token, `/tax/periods/${activePeriodId}/iva`),
    enabled: Boolean(activePeriodId),
  })

  const documentsQuery = useQuery({
    queryKey: ['tax', 'documents', activePeriodId],
    queryFn: () =>
      apiRequest<TaxFiscalDocument[]>(token, `/tax/periods/${activePeriodId}/documents`),
    enabled: Boolean(activePeriodId),
  })

  const classificationsQuery = useQuery({
    queryKey: ['analytic-classifications'],
    queryFn: () => apiRequest<AnalyticClassification[]>(token, '/analytic-classifications'),
  })

  const historicalCandidatesQuery = useQuery({
    queryKey: ['tax', 'historical-tax-candidates', activePeriodId],
    queryFn: () => apiRequest<HistoricalTaxCandidate[]>(
      token,
      `/tax/periods/${activePeriodId}/historical-tax-candidates`,
    ),
    enabled: Boolean(activePeriodId),
  })

  const xmlRecoveryQuery = useQuery({
    queryKey: ['tax', 'xml-recovery', activePeriodId],
    queryFn: () => apiRequest<TaxXmlRecoveryJob | null>(
      token,
      `/tax/periods/${activePeriodId}/xml-recovery`,
    ),
    enabled: Boolean(activePeriodId),
    refetchInterval: (query) => {
      const job = query.state.data
      return job?.status === 'QUEUED' || job?.status === 'RUNNING' ? 3000 : false
    },
  })

  const recoveryMissingDocuments = useMemo(() => {
    const unresolvedIds = new Set(
      (xmlRecoveryQuery.data?.items ?? [])
        .filter((item) => item.status === 'UNAVAILABLE' || item.status === 'FAILED')
        .map((item) => item.documentId),
    )
    return (documentsQuery.data ?? []).filter((document) => unresolvedIds.has(document.id))
  }, [documentsQuery.data, xmlRecoveryQuery.data?.items])

  useEffect(() => {
    if (xmlRecoveryQuery.data?.status === 'COMPLETED') {
      void queryClient.invalidateQueries({
        predicate: (query) => query.queryKey[0] === 'tax' && query.queryKey[1] !== 'xml-recovery',
      })
    }
  }, [queryClient, xmlRecoveryQuery.data?.completedAt, xmlRecoveryQuery.data?.status])

  // Carga en bloque: primero se revisa (no escribe), luego se confirma.
  function bulkFormData(files: File[], apply: boolean): FormData {
    const body = new FormData()
    for (const file of files) body.append('files', file)
    body.append('apply', apply ? 'true' : 'false')
    if (apply && applyRetentions) body.append('applyRetentions', 'true')
    return body
  }

  const previewBulk = useMutation({
    mutationFn: (files: File[]) =>
      apiRequest<TaxBulkResult>(token, '/tax/evidence/bulk', {
        method: 'POST',
        body: bulkFormData(files, false),
      }),
  })

  const applyBulk = useMutation({
    mutationFn: (files: File[]) =>
      apiRequest<TaxBulkResult>(token, '/tax/evidence/bulk', {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey('tax-bulk') },
        body: bulkFormData(files, true),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['tax'] })
    },
  })

  const bulkResult = applyBulk.data ?? previewBulk.data ?? null

  // Historia del comprobante: se pide solo cuando el usuario despliega la fila.
  const dossierQuery = useQuery({
    queryKey: ['tax', 'dossier', openDossierId],
    queryFn: () =>
      apiRequest<TaxDocumentDossier>(token, `/tax/documents/${openDossierId}/dossier`),
    enabled: Boolean(openDossierId),
  })

  const generateAts = useMutation({
    mutationFn: (periodId: string) => apiRequest<TaxAnnex>(token, `/tax/periods/${periodId}/ats`, {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey('tax-ats') },
    }),
    onSuccess: (annex) => {
      setGeneratedAnnex(annex)
    },
  })

  const approveHistoricalException = useMutation({
    mutationFn: ({ candidateId, evidenceReference }: { candidateId: string; evidenceReference: string }) =>
      apiRequest<TaxFiscalDocument>(
        token,
        `/tax/periods/${activePeriodId}/historical-tax-candidates/${candidateId}/approve`,
        {
          method: 'POST',
          headers: { 'Idempotency-Key': idempotencyKey('tax-historical-exception') },
          body: JSON.stringify({ confirmed: true, evidenceReference }),
        },
      ),
    onSuccess: () => {
      setGeneratedAnnex(null)
      void queryClient.invalidateQueries({ queryKey: ['tax'] })
    },
  })

  function confirmHistoricalException(candidate: HistoricalTaxCandidate) {
    const evidenceReference = exceptionEvidence[candidate.id]?.trim() ?? ''
    if (evidenceReference.length < 8) return
    const confirmed = window.confirm(
      `¿Aprobar la factura ${candidate.documentNumber} solo para IVA y ATS?\n\n` +
      'El XML original seguirá marcado como faltante. No se enviará la factura al SRI ni se tocará Cartera.',
    )
    if (confirmed) approveHistoricalException.mutate({ candidateId: candidate.id, evidenceReference })
  }

  // Trae las ventas desde las facturas que IAERP ya emitió y autorizó, para no
  // tener que descargarlas del portal y volverlas a subir.
  const importIssued = useMutation({
    mutationFn: (periodId: string) =>
      apiRequest<TaxOwnDocumentsResult>(token, `/tax/periods/${periodId}/import-issued`, {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey('tax-import-issued') },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['tax'] })
    },
  })

  const recoverXml = useMutation({
    mutationFn: (periodId: string) =>
      apiRequest<TaxXmlRecoveryJob>(token, `/tax/periods/${periodId}/xml-recovery`, {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey('tax-xml-recovery') },
      }),
    onSuccess: (job) => {
      queryClient.setQueryData(['tax', 'xml-recovery', job.taxPeriodId], job)
      void queryClient.invalidateQueries({ queryKey: ['tax'] })
    },
  })

  const updatePeriodStatus = useMutation({
    mutationFn: ({ periodId, targetStatus }: { periodId: string; targetStatus: 'LISTO_DECLARAR' | 'DECLARADO' }) =>
      apiRequest<TaxPeriod>(token, `/tax/periods/${periodId}/status`, {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey('tax-period-status') },
        body: JSON.stringify({ targetStatus, confirmed: true }),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['tax'] })
    },
  })

  function confirmPeriodStatus(targetStatus: 'LISTO_DECLARAR' | 'DECLARADO') {
    if (!activePeriodId) return
    const message = targetStatus === 'DECLARADO'
      ? '¿Confirmas que esta declaración ya fue presentada al SRI?'
      : '¿Confirmas que revisaste la evidencia y los valores del periodo?'
    if (window.confirm(message)) {
      updatePeriodStatus.mutate({ periodId: activePeriodId, targetStatus })
    }
  }

  const issuesQuery = useQuery({
    queryKey: ['tax', 'annex-issues', generatedAnnex?.id],
    queryFn: () => apiRequest<Array<{ id: string; status: string; severity: string; lineNumber?: number | null; columnNumber?: number | null; message: string }>>(
      token,
      `/tax/annexes/${generatedAnnex?.id}/issues`,
    ),
    enabled: Boolean(generatedAnnex?.id),
  })

  async function copyValue(field: string, value: string) {
    try {
      await navigator.clipboard.writeText(value)
      setCopiedField(field)
      window.setTimeout(() => setCopiedField(null), 1500)
    } catch {
      // Si el navegador bloquea el portapapeles, el valor sigue visible.
    }
  }

  function confirmReviewedValue(fieldCode: string) {
    const message = fieldCode === '564'
      ? 'Confirma que el crédito tributario coincide con tu contabilidad o con el factor de proporcionalidad del SRI antes de copiarlo.'
      : 'Confirma que estas compras dan derecho a crédito tributario y no corresponden a activos fijos ni a compras sin derecho a crédito antes de copiar el valor.'
    return window.confirm(message)
  }

  const summary = ivaQuery.data
  const pasteFields = summary?.fields.filter((field) => field.isPaste) ?? []
  const controlFields = summary?.fields.filter((field) => !field.isPaste) ?? []

  // Los periodos se agrupan por año, como pidió el usuario.
  const periodsByYear = useMemo(() => {
    const grouped = new Map<number, TaxPeriod[]>()
    for (const period of periods) {
      const list = grouped.get(period.year) ?? []
      list.push(period)
      grouped.set(period.year, list)
    }
    return [...grouped.entries()].sort((a, b) => b[0] - a[0])
  }, [periods])

  const documentGroups = useMemo(() => {
    const documents = documentsQuery.data ?? []
    const definitions = [
      {
        key: 'sales',
        title: 'Ventas emitidas',
        description: 'Facturas y notas emitidas por la empresa.',
        matches: (document: TaxFiscalDocument) => document.direction === 'EMITIDO' && document.docType !== 'RETENCION',
      },
      {
        key: 'purchases',
        title: 'Compras recibidas',
        description: 'Facturas, liquidaciones y notas recibidas de proveedores.',
        matches: (document: TaxFiscalDocument) => document.direction === 'RECIBIDO' && document.docType !== 'RETENCION',
      },
      {
        key: 'retentions',
        title: 'Retenciones recibidas',
        description: 'Retención de IVA y retención de renta, siempre separadas en el detalle.',
        matches: (document: TaxFiscalDocument) => document.direction === 'RECIBIDO' && document.docType === 'RETENCION',
      },
    ]
    const assigned = new Set<string>()
    const groups = definitions.map((definition) => {
      const items = documents.filter((document) => definition.matches(document))
      items.forEach((document) => assigned.add(document.id))
      return { ...definition, items }
    })
    const otherItems = documents.filter((document) => !assigned.has(document.id))
    if (otherItems.length > 0) {
      groups.push({
        key: 'other',
        title: 'Otros documentos',
        description: 'Documentos que requieren una clasificación distinta.',
        matches: () => false,
        items: otherItems,
      })
    }
    return groups
  }, [documentsQuery.data])

  const visibleDocumentGroups = useMemo(() => {
    if (!groupByClassificationId) return documentGroups
    const classification = (classificationsQuery.data ?? []).find((item) => item.id === groupByClassificationId)
    if (!classification) return documentGroups
    const groups = new Map<string, TaxFiscalDocument[]>()
    documentGroups.flatMap((group) => group.items).forEach((document) => {
      const assignment = (document.analyticAssignments ?? []).find(
        (item) => item.classificationId === groupByClassificationId,
      )
      const name = assignment ? assignment.path.map((part) => part.name).join(' / ') : 'Sin clasificar'
      groups.set(name, [...(groups.get(name) ?? []), document])
    })
    return [...groups.entries()].map(([name, items]) => ({
      key: `${classification.id}-${name}`,
      title: name,
      description: `${classification.name} · agrupación de solo lectura para revisar el periodo.`,
      matches: () => false,
      items,
    }))
  }, [classificationsQuery.data, documentGroups, groupByClassificationId])

  return (
    <>
      <ErpPageHeader
        eyebrow="Obligaciones SRI"
        title="Tributario"
        subtitle="Separa los documentos de meses con IVA presentado de los meses aún abiertos."
      />

      <nav className="tax-onepage-nav" aria-label="Secciones de Tributario">
        <a href="#tax-income-pulse">Renta del año</a>
        <a href="#tax-section-month">Mes y declaración</a>
        <a href="#tax-section-year">Detalle anual</a>
        <a href="#tax-section-retentions">Retenciones</a>
      </nav>

      <section id="tax-income-pulse" className="tax-income-pulse" aria-label="Renta estimada">
        <ErpPanel title={`Renta estimada · ${dashboardQuery.data?.annual.year ?? activePeriod?.year ?? ''}`}>
          {dashboardQuery.isPending ? <p className="fine-print" aria-busy="true">Calculando el avance anual…</p> : null}
          {dashboardQuery.error ? <p className="form-error" role="alert">{dashboardQuery.error.message}</p> : null}
          {dashboardQuery.data?.annual ? (
            <>
              <div className="tax-income-heading">
                <div>
                  <span>Corte documental</span>
                  <strong>{dashboardQuery.data.annual.declaredMonthCount} mes(es) con IVA presentado</strong>
                </div>
                <ErpStatusBadge tone={dashboardQuery.data.annual.declaredMonthCount > 0 ? 'success' : 'warning'}>
                  {dashboardQuery.data.annual.lastDeclaredMonth
                    ? `Hasta ${monthName(dashboardQuery.data.annual.lastDeclaredMonth)}`
                    : 'Sin IVA presentado'}
                </ErpStatusBadge>
                <label>
                  Escenario de renta
                  <select value={incomeTaxScenario} onChange={(event) => setIncomeTaxScenario(event.target.value as 'NONE' | '25')}>
                    <option value="NONE">Sin tarifa</option>
                    <option value="25">25 % referencial</option>
                  </select>
                </label>
              </div>
              <ErpMetricGrid ariaLabel="Corte documental y proyección anual">
                <article className="metric-card">
                  <span>Resultado parcial de meses con IVA presentado</span>
                  <strong>{formatDashboardCurrency(dashboardQuery.data.annual.declaredResultBeforeAdjustments)}</strong>
                  <p>Ventas menos compras deducibles de esos meses; es un cálculo vivo, no la declaración anual de renta.</p>
                </article>
                <article className="metric-card">
                  <span>Impuesto referencial sobre meses con IVA presentado</span>
                  <strong>{dashboardQuery.data.annual.declaredEstimatedIncomeTax === null ? 'Elige una tarifa' : formatDashboardCurrency(dashboardQuery.data.annual.declaredEstimatedIncomeTax)}</strong>
                  <p>{dashboardQuery.data.annual.estimateReason}</p>
                </article>
                <article className="metric-card tax-income-projection">
                  <span>{dashboardQuery.data.annual.projectedEstimatedBalance === null ? 'Resultado proyectado antes de ajustes' : 'Saldo estimado del año'}</span>
                  <strong>{dashboardQuery.data.annual.projectedEstimatedBalance === null
                    ? formatDashboardCurrency(dashboardQuery.data.annual.resultBeforeAdjustments)
                    : formatDashboardCurrency(dashboardQuery.data.annual.projectedEstimatedBalance)}</strong>
                  <p>{dashboardQuery.data.annual.projectedEstimatedBalance === null
                    ? 'Incluye meses abiertos; falta elegir una tarifa y hacer la conciliación.'
                    : 'Impuesto del escenario menos retenciones registradas. Positivo: posible pago; negativo: posible saldo a favor.'}</p>
                </article>
              </ErpMetricGrid>
              <div className="tax-income-formula" role="note">
                <span>Meses con IVA presentado</span>
                <strong>{formatDashboardCurrency(dashboardQuery.data.annual.declaredSalesBase)}</strong>
                <span>ventas −</span>
                <strong>{formatDashboardCurrency(dashboardQuery.data.annual.declaredDeductiblePurchasesBase)}</strong>
                <span>compras deducibles =</span>
                <strong>{formatDashboardCurrency(dashboardQuery.data.annual.declaredResultBeforeAdjustments)}</strong>
              </div>
            </>
          ) : null}
        </ErpPanel>
      </section>

      <section id="tax-section-month" className="tax-onepage-section" aria-labelledby="tax-month-title">
        <h2 id="tax-month-title" className="tax-section-title">Mes y declaración</h2>

      <ErpPanel title="Cargar comprobantes del SRI">
        <div className="tax-upload">
          <label>
            Archivos del mes (XML, TXT o ZIP · hasta 50)
            <input
              ref={evidenceInputRef}
              type="file"
              accept=".xml,.txt,.zip,.pdf"
              multiple
              onChange={(event) => {
                setSelectedFiles(Array.from(event.target.files ?? []))
                previewBulk.reset()
                applyBulk.reset()
              }}
            />
          </label>
          <p className="fine-print">
            Puedes elegir juntos los reportes de facturas, notas de crédito y retenciones.
            IAERP usará sus claves para buscar cada XML autorizado.
          </p>
          <ErpButton
            variant="primary"
            disabled={selectedFiles.length === 0 || previewBulk.isPending}
            onClick={() => previewBulk.mutate(selectedFiles)}
          >
            {previewBulk.isPending ? 'Revisando…' : 'Revisar carga'}
          </ErpButton>
        </div>
        {selectedFiles.length > 0 ? (
          <p className="fine-print">
            {selectedFiles.length} archivo{selectedFiles.length === 1 ? '' : 's'} seleccionado
            {selectedFiles.length === 1 ? '' : 's'}. Se revisa primero; nada se guarda hasta
            que confirmes.
          </p>
        ) : null}
        {previewBulk.error ? (
          <p className="form-error" role="alert">{previewBulk.error.message}</p>
        ) : null}
        {applyBulk.error ? (
          <p className="form-error" role="alert">{applyBulk.error.message}</p>
        ) : null}

        {bulkResult ? (
          <div className="tax-bulk" aria-live="polite">
            <p className="tax-subhead">
              {applyBulk.data ? 'Carga confirmada' : 'Previo: esto es lo que se cargará'}
            </p>
            <p className="fine-print">
              {Object.entries(bulkResult.periods)
                .map(([period, count]) => `${period}: ${count} comprobante(s)`)
                .join(' · ') || 'Sin comprobantes reconocidos.'}
              {bulkResult.errors > 0 ? ` · ${bulkResult.errors} con problema` : ''}
            </p>
            <ErpDataTable
          ariaLabel="Detalle de la carga"
          rows={bulkResult.items}
          rowKey={(item, index) => `${item.filename}-${item.accessKey ?? index}`}
          columns={[
            { header: 'Archivo', cell: (item) => (<>{item.filename}
                        {item.sourceArchive ? (
                          <small> · en {item.sourceArchive}</small>
                        ) : null}</>) },
            { header: 'Tipo', cell: (item) => (<>{item.docType ?? '—'}</>) },
            { header: 'Sentido', cell: (item) => (<>{item.direction === 'EMITIDO' ? '↑ Emitido' : item.direction === 'RECIBIDO' ? '↓ Recibido' : '—'}</>) },
            { header: 'Emisión', cell: (item) => (<>{item.issueDate ?? '—'}</>) },
            { header: 'Periodo', cell: (item) => (<>{item.periodYear && item.periodMonth
                          ? `${monthName(item.periodMonth)} ${item.periodYear}`
                          : '—'}</>) },
            { header: 'Contraparte', cell: (item) => (<>{item.counterpartyName ?? item.counterpartyIdentification ?? '—'}</>) },
            { header: 'Total', cell: (item) => (<>{item.total ?? '—'}</>) },
            { header: 'Estado', cell: (item) => (<>{item.status === 'ERROR' ? (
                          <ErpStatusBadge tone="danger">{item.error ?? 'Error'}</ErpStatusBadge>
                        ) : item.status === 'DUPLICADO' ? (
                          <ErpStatusBadge tone="neutral">Ya cargado · se validará de nuevo</ErpStatusBadge>
                        ) : (
                          <ErpStatusBadge tone="success">Listo</ErpStatusBadge>
                        )}</>) },
          ]}
        />

            {applyBulk.data ? (
              <p className="tax-ingest-result" role="status">
                Registrados: {applyBulk.data.created} nuevo(s) · {applyBulk.data.updated}{' '}
                actualizado(s)
                {applyBulk.data.retentionsApplied > 0
                  ? ` · ${applyBulk.data.retentionsApplied} retención(es) aplicada(s) a cartera`
                  : ''}
              </p>
            ) : (
              <div className="tax-bulk-actions">
                {bulkResult.retentionCount > 0 ? (
                  <label className="tax-checkbox">
                    <input
                      type="checkbox"
                      checked={applyRetentions}
                      onChange={(event) => setApplyRetentions(event.target.checked)}
                    />
                    Aplicar {bulkResult.retentionCount} retención(es) a cartera
                  </label>
                ) : null}
                <ErpButton
                  variant="primary"
                  disabled={applyBulk.isPending}
                  onClick={() => applyBulk.mutate(selectedFiles)}
                >
                  {applyBulk.isPending ? 'Cargando…' : 'Confirmar carga'}
                </ErpButton>
              </div>
            )}
            {bulkResult.notes.map((note) => (
              <p key={note} className="fine-print">{note}</p>
            ))}
          </div>
        ) : null}

        <p className="fine-print">
          Cada archivo se clasifica por su contenido y se ubica en el periodo de su fecha
          real de emisión. Los PDF se guardan como respaldo, pero sus valores no se leen:
          para el detalle carga el XML autorizado.
        </p>
      </ErpPanel>

      <section className="split-layout erp-list-only">
        <ErpPanel title="Periodos" count={periods.length}>
          {periods.length === 0 ? (
            <ErpEmptyState
              title="Sin periodos"
              description="Carga un archivo del SRI: el periodo se crea con la fecha real de emisión de los comprobantes."
            />
          ) : (
            <div className="tax-periods">
              {periodsByYear.map(([year, yearPeriods]) => (
                <div key={year} className="tax-year-group">
                  {/* Clase propia: `.section-number` está oculta por el rediseño. */}
                  <p className="tax-year-label">{year}</p>
                  <div className="tax-period-list">
                    {yearPeriods
                      .sort((a, b) => b.month - a.month)
                      .map((period) => (
                        <button
                          key={period.id}
                          type="button"
                          className={`tax-period ${period.id === activePeriodId ? 'active' : ''}`}
                          aria-pressed={period.id === activePeriodId}
                          onClick={() => setSelectedPeriodId(period.id)}
                        >
                          <strong>{monthName(period.month)}</strong>
                          <ErpStatusBadge tone={STATUS_TONES[period.status] ?? 'neutral'}>
                            {STATUS_LABELS[period.status] ?? period.status}
                          </ErpStatusBadge>
                        </button>
                      ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </ErpPanel>
      </section>

      {summary ? (
        <>
          {importIssued.data ? (
            <div className="tax-ingest-result" role="status">
              <p>
                Ventas propias importadas: {importIssued.data.created} nueva(s) ·{' '}
                {importIssued.data.updated} actualizada(s)
                {importIssued.data.skipped > 0 ? ` · ${importIssued.data.skipped} sin importar` : ''}
              </p>
              {importIssued.data.notes.map((note) => (
                <p key={note} className="fine-print">{note}</p>
              ))}
            </div>
          ) : null}
          {importIssued.error ? (
            <p className="form-error" role="alert">{importIssued.error.message}</p>
          ) : null}

          {summary.isPreliminary ? (
            <div className="tax-readiness tax-readiness-pending" role="alert">
              <div>
                <strong>Aún no está listo para declarar.</strong>
                <p>
                  El listado TXT sirve para comprobar el total, pero solo los XML autorizados
                  separan la base con IVA, tarifa 0 %, exenta y no objeto.
                </p>
                <ul>
                  {summary.preliminaryReasons.map((reason) => (
                    <li key={reason}>{reason}</li>
                  ))}
                </ul>
              </div>
              {summary.pendingPurchaseCount > 0 ? (
                <div className="tax-readiness-actions">
                  <ErpButton
                    variant="primary"
                    disabled={
                      recoverXml.isPending ||
                      xmlRecoveryQuery.data?.status === 'QUEUED' ||
                      xmlRecoveryQuery.data?.status === 'RUNNING'
                    }
                    onClick={() => activePeriodId && recoverXml.mutate(activePeriodId)}
                  >
                    {recoverXml.isPending || xmlRecoveryQuery.data?.status === 'QUEUED'
                      ? 'Preparando…'
                      : xmlRecoveryQuery.data?.status === 'RUNNING'
                        ? 'Buscando XML…'
                        : 'Completar XML desde el SRI'}
                  </ErpButton>
                  <ErpButton
                    variant="secondary"
                    onClick={() => {
                      evidenceInputRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
                      evidenceInputRef.current?.focus()
                    }}
                  >
                    Cargar XML o ZIP
                  </ErpButton>
                </div>
              ) : null}
            </div>
          ) : (
            <div className="tax-readiness tax-readiness-ready" role="status">
              <strong>Desglose por tarifa completo.</strong>
              <p>Ya puedes revisar los casilleros y el crédito tributario antes de declarar.</p>
            </div>
          )}

          {recoverXml.error ? (
            <p className="form-error" role="alert">{recoverXml.error.message}</p>
          ) : null}
          {xmlRecoveryQuery.data ? (
            <div className="tax-recovery-status" role="status" aria-live="polite">
              <strong>
                {xmlRecoveryQuery.data.status === 'COMPLETED'
                  ? 'Búsqueda en el SRI terminada.'
                  : 'Buscando comprobantes autorizados en el SRI…'}
              </strong>
              <p>
                {xmlRecoveryQuery.data.processedCount} de {xmlRecoveryQuery.data.totalCount} revisados
                {' · '}{xmlRecoveryQuery.data.recoveredCount} recuperados
                {' · '}{xmlRecoveryQuery.data.unavailableCount} no disponibles
                {' · '}{xmlRecoveryQuery.data.failedCount} con error
              </p>
              {xmlRecoveryQuery.data.status === 'COMPLETED' &&
              (xmlRecoveryQuery.data.unavailableCount > 0 || xmlRecoveryQuery.data.failedCount > 0) ? (
                <>
                  <p className="fine-print">
                    Puedes volver a intentar o cargar a mano el XML/ZIP de estos comprobantes.
                  </p>
                  <details className="tax-recovery-missing">
                    <summary>Ver {recoveryMissingDocuments.length} comprobante(s) pendientes</summary>
                    <ul>
                      {recoveryMissingDocuments.map((document) => (
                        <li key={document.id}>
                          <strong>{DOCUMENT_TYPE_LABELS[document.docType] ?? document.docType}</strong>
                          {' · '}{document.issueDate}
                          {' · '}{document.counterpartyName ?? document.counterpartyIdentification ?? 'Sin proveedor'}
                          {' · $'}{document.total}
                        </li>
                      ))}
                    </ul>
                  </details>
                </>
              ) : null}
              {xmlRecoveryQuery.data.status === 'COMPLETED' &&
              xmlRecoveryQuery.data.totalCount === 0 ? (
                <p className="fine-print">
                  No se hallaron claves válidas para consultar. Carga los XML o un ZIP desde el SRI.
                </p>
              ) : null}
            </div>
          ) : null}

          {(historicalCandidatesQuery.data ?? []).length > 0 ? (
            <ErpPanel title="Excepciones ATS · XML original faltante">
              <p className="fine-print">
                Solo para facturas reales autorizadas con RIDE verificado. La aprobación no crea un XML SRI,
                no reenvía la factura y no afecta Cartera.
              </p>
              <div className="tax-document-list">
                {historicalCandidatesQuery.data?.map((candidate) => (
                  <article className="tax-document-card" key={candidate.id}>
                    <header className="tax-document-header">
                      <div>
                        <span className="tax-document-direction">Emitido</span>
                        <h3>Factura · {candidate.issueDate}</h3>
                        <p>{candidate.customerName} · {candidate.documentNumber}</p>
                      </div>
                      <ErpStatusBadge tone={candidate.approved ? 'success' : 'warning'}>
                        {candidate.approved ? 'Aprobada para ATS' : 'XML original faltante'}
                      </ErpStatusBadge>
                    </header>
                    <dl className="tax-document-amounts">
                      <div><dt>Base</dt><dd>${candidate.subtotal}</dd></div>
                      <div><dt>IVA</dt><dd>${candidate.taxTotal}</dd></div>
                      <div className="tax-document-total"><dt>Total</dt><dd>${candidate.total}</dd></div>
                    </dl>
                    {!candidate.approved ? (
                      <div className="tax-exception-approval">
                        <label htmlFor={`exception-${candidate.id}`}>
                          Respaldo de transferencia bancaria
                        </label>
                        <input
                          id={`exception-${candidate.id}`}
                          value={exceptionEvidence[candidate.id] ?? ''}
                          placeholder="Ej.: estado bancario, fecha, referencia y valor neto"
                          onChange={(event) => setExceptionEvidence((current) => ({
                            ...current,
                            [candidate.id]: event.target.value,
                          }))}
                        />
                        <ErpButton
                          variant="primary"
                          disabled={approveHistoricalException.isPending || (exceptionEvidence[candidate.id]?.trim().length ?? 0) < 8}
                          onClick={() => confirmHistoricalException(candidate)}
                        >
                          Aprobar excepción IVA/ATS
                        </ErpButton>
                      </div>
                    ) : null}
                  </article>
                ))}
              </div>
              {approveHistoricalException.error ? (
                <p className="form-error" role="alert">{approveHistoricalException.error.message}</p>
              ) : null}
            </ErpPanel>
          ) : null}

          <ErpPanel
            title={`Formulario 104 · ${monthName(summary.month)} ${summary.year}`}
            actions={<>
              <ErpStatusBadge tone={summary.isPreliminary ? 'warning' : 'success'}>
                {summary.documentCount} comprobante(s)
              </ErpStatusBadge>
              <ErpButton
                variant="secondary"
                disabled={importIssued.isPending || !activePeriodId}
                onClick={() => activePeriodId && importIssued.mutate(activePeriodId)}
              >
                {importIssued.isPending ? 'Importando ventas…' : 'Importar mis ventas'}
              </ErpButton>
              <ErpButton
                variant="secondary"
                disabled={generateAts.isPending || !activePeriodId}
                onClick={() => activePeriodId && generateAts.mutate(activePeriodId)}
              >
                {generateAts.isPending ? 'Generando ATS…' : 'Generar ATS'}
              </ErpButton>
            </>}
          >
            <p className="fine-print">
              {summary.isPreliminary
                ? 'Valores parciales de control. Completa los XML antes de copiar al formulario.'
                : 'Valores con punto decimal y dos decimales, listos para copiar al formulario.'}
            </p>
            {generateAts.error ? (
              <p className="form-error" role="alert">{generateAts.error.message}</p>
            ) : null}
            {updatePeriodStatus.error ? (
              <p className="form-error" role="alert">{updatePeriodStatus.error.message}</p>
            ) : null}
            {activePeriod?.status === 'LISTO_REVISAR' ? (
              <ErpButton
                variant="primary"
                disabled={updatePeriodStatus.isPending}
                onClick={() => confirmPeriodStatus('LISTO_DECLARAR')}
              >
                Marcar listo para declarar
              </ErpButton>
            ) : null}
            {activePeriod?.status === 'LISTO_DECLARAR' ? (
              <ErpButton
                variant="primary"
                disabled={updatePeriodStatus.isPending}
                onClick={() => confirmPeriodStatus('DECLARADO')}
              >
                Confirmar como declarado
              </ErpButton>
            ) : null}
            {generatedAnnex ? (
              <div className="tax-ingest-result" role="status">
                <p>
                  ATS v{generatedAnnex.version} generado.{' '}
                  {generatedAnnex.downloadUrl ? (
                    <a href={generatedAnnex.downloadUrl}>Descargar ZIP</a>
                  ) : null}
                </p>
                {(issuesQuery.data ?? []).length > 0 ? (
                  <ul>
                    {issuesQuery.data?.map((issue) => (
                      <li key={issue.id}>
                        {issue.severity} {issue.lineNumber ? `línea ${issue.lineNumber}` : ''}: {issue.message} ({issue.status})
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="fine-print">Sin errores del SRI registrados todavía.</p>
                )}
              </div>
            ) : null}
            <ErpDataTable
          ariaLabel="Campos para copiar"
          rows={pasteFields}
          rowKey={(field) => field.fieldCode}
          columns={[
            { header: 'Campo', cell: (field) => (<><strong>{field.fieldCode}</strong></>) },
            { header: 'Concepto', cell: (field) => (<>{field.label}
                        {field.needsReview ? (
                          <small className="tax-review"> · revisar criterio tributario</small>
                        ) : null}</>) },
            { header: 'Valor', cell: (field) => (<>{field.value}</>) },
            { header: 'Respaldo', cell: (field) => (<>{field.documentCount} doc.</>) },
            { header: 'Acción', cell: (field) => (<><ErpButton
                          variant="ghost"
                          aria-label={`Copiar campo ${field.fieldCode}`}
                          disabled={summary.isPreliminary}
                          onClick={() => {
                            if (field.needsReview && !confirmReviewedValue(field.fieldCode)) return
                            void copyValue(field.fieldCode, field.value)
                          }}
                        >
                          {copiedField === field.fieldCode
                            ? 'Copiado'
                            : field.needsReview ? 'Revisar y copiar' : 'Copiar'}
                        </ErpButton></>) },
          ]}
        />

            {controlFields.length > 0 ? (
              <>
                <p className="tax-subhead">Solo control (el SRI los calcula)</p>
                <ErpDataTable
          ariaLabel="Campos de control"
          rows={controlFields}
          rowKey={(field) => field.fieldCode}
          columns={[
            { header: 'Campo', cell: (field) => (<>{field.fieldCode}</>) },
            { header: 'Concepto', cell: (field) => (<>{field.label}
                            {field.needsReview ? (
                              <small className="tax-review"> · revisar criterio tributario</small>
                            ) : null}</>) },
            { header: 'Valor', cell: (field) => (<>{field.value}</>) },
          ]}
        />
              </>
            ) : null}
          </ErpPanel>

          <ErpPanel title="Resumen del periodo">
            <dl className="tax-summary">
              <div><dt>Ventas brutas</dt><dd>${summary.amounts.ventasBrutas ?? '0.00'}</dd></div>
              <div><dt>IVA generado</dt><dd>${summary.amounts.ivaGenerado ?? '0.00'}</dd></div>
              <div><dt>Compras gravadas con IVA</dt><dd>${summary.amounts.comprasGravadasBase ?? '0.00'}</dd></div>
              <div><dt>Compras con tarifa 0 %</dt><dd>${summary.amounts.comprasTarifaCeroBase ?? '0.00'}</dd></div>
              <div><dt>Compras exentas de IVA</dt><dd>${summary.amounts.comprasExentasBase ?? '0.00'}</dd></div>
              <div><dt>Compras no objeto de IVA</dt><dd>${summary.amounts.comprasNoObjetoBase ?? '0.00'}</dd></div>
              <div><dt>Crédito tributario</dt><dd>${summary.amounts.ivaCreditoTributario ?? '0.00'}</dd></div>
              {summary.pendingPurchaseCount > 0 ? (
                <div className="tax-apart">
                  <dt>Compras pendientes de XML ({summary.pendingPurchaseCount})</dt>
                  <dd>${summary.pendingPurchaseTotal}</dd>
                </div>
              ) : null}
              <div><dt>Retenciones de IVA</dt><dd>${summary.amounts.retencionesIvaRecibidas ?? '0.00'}</dd></div>
              <div className="tax-apart">
                <dt>Retenciones de renta (no entran al IVA)</dt>
                <dd>${summary.amounts.retencionesRentaRecibidas ?? '0.00'}</dd>
              </div>
              <div className="tax-total">
                <dt>{Number(summary.amounts.creditoAFavor ?? '0') > 0 ? 'Crédito a favor' : 'Saldo a pagar'}</dt>
                <dd>
                  $
                  {Number(summary.amounts.creditoAFavor ?? '0') > 0
                    ? summary.amounts.creditoAFavor
                    : (summary.amounts.saldoAPagar ?? '0.00')}
                </dd>
              </div>
            </dl>
          </ErpPanel>

          <ErpPanel title="Documentos usados" count={documentsQuery.data?.length ?? 0}>
            {(classificationsQuery.data ?? []).length ? <label className="tax-group-select">Agrupar por tag<select value={groupByClassificationId} onChange={(event) => setGroupByClassificationId(event.target.value)}><option value="">Tipo de comprobante</option>{classificationsQuery.data?.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label> : null}
            <div className="tax-document-groups" aria-label="Documentos del periodo agrupados">
              {visibleDocumentGroups.filter((group) => group.items.length > 0).map((group) => (
                <details className="tax-document-group" key={group.key}>
                  <summary>
                    <span>
                      <strong>{group.title}</strong>
                      <small>{group.description}</small>
                    </span>
                    <span className="tax-document-group-metrics">
                      {group.items.length} doc. · ${group.items.reduce((total, document) => total + Number(document.total), 0).toFixed(2)}
                    </span>
                  </summary>
                  <div className="tax-document-list">
                  {group.items.map((document) => (
                <article className="tax-document-card" key={document.id}>
                  <header className="tax-document-header">
                    <div>
                      <span className="tax-document-direction">
                        {document.direction === 'EMITIDO' ? 'Emitido' : 'Recibido'}
                      </span>
                      <h3>{DOCUMENT_TYPE_LABELS[document.docType] ?? document.docType} · {document.issueDate}</h3>
                      <p>{document.counterpartyName ?? document.counterpartyIdentification ?? 'Sin contraparte'}</p>
                      {(document.analyticAssignments ?? []).length ? <p className="tax-document-tags">{document.analyticAssignments.map((assignment) => `${assignment.classificationName}: ${assignment.path.map((part) => part.name).join(' / ')}`).join(' · ')}</p> : null}
                    </div>
                    {document.isPreliminary ? (
                      <ErpStatusBadge tone="warning">Preliminar</ErpStatusBadge>
                    ) : (
                      <ErpStatusBadge tone="success">Confirmado</ErpStatusBadge>
                    )}
                  </header>

                  <dl className="tax-document-amounts">
                    <div><dt>Base</dt><dd>${document.subtotal}</dd></div>
                    <div><dt>IVA</dt><dd>${document.taxTotal}</dd></div>
                    <div className="tax-document-total"><dt>Total</dt><dd>${document.total}</dd></div>
                  </dl>

                  <div className="tax-document-identifiers">
                    <div>
                      <span>ID IAERP</span>
                      <code>{document.id}</code>
                      <ErpButton
                        variant="ghost"
                        aria-label={`Copiar ID IAERP ${document.id}`}
                        onClick={() => void copyValue(`document-${document.id}`, document.id)}
                      >
                        {copiedField === `document-${document.id}` ? 'Copiado' : 'Copiar ID'}
                      </ErpButton>
                    </div>
                    <div>
                      <span>Clave SRI</span>
                      <code>{document.accessKey ?? 'Sin clave en la evidencia'}</code>
                    </div>
                    <div>
                      <span>Forma de pago</span>
                      <strong>
                        {(document.paymentMethods ?? []).map((method) => (
                          method === '20' ? 'Transferencia' : `Código ${method}`
                        )).join(', ') || 'Sin respaldo XML'}
                      </strong>
                    </div>
                  </div>

                  <div className="tax-document-actions">
                    <ErpButton
                      variant="ghost"
                      aria-expanded={openDossierId === document.id}
                      aria-label={`Ver historia del comprobante ${document.accessKey ?? document.id}`}
                      onClick={() =>
                        setOpenDossierId(openDossierId === document.id ? null : document.id)
                      }
                    >
                      {openDossierId === document.id ? 'Ocultar historia' : 'Ver historia'}
                    </ErpButton>
                  </div>
                  {openDossierId === document.id ? (
                    <div className="tax-document-dossier">
                      {dossierQuery.isPending ? (
                        <p className="fine-print">Cargando historia…</p>
                      ) : dossierQuery.data ? (
                        <DossierView dossier={dossierQuery.data} />
                      ) : (
                        <p className="form-error">
                          {dossierQuery.error?.message ?? 'No se pudo cargar la historia.'}
                        </p>
                      )}
                    </div>
                  ) : null}
                </article>
                  ))}
                  </div>
                </details>
              ))}
              {(documentsQuery.data ?? []).length === 0 ? (
                <ErpEmptyState
                  title="Sin comprobantes"
                  description="Carga los XML o el TXT del portal para este periodo."
                />
              ) : null}
            </div>
          </ErpPanel>
        </>
      ) : null}
      </section>

        <section id="tax-section-year" className="tax-onepage-section" aria-labelledby="tax-year-title">
          <h2 id="tax-year-title" className="tax-section-title">Detalle del año fiscal</h2>
          <ErpPanel title={`Año fiscal ${dashboardQuery.data?.annual.year ?? activePeriod?.year ?? ''}`}>
            {dashboardQuery.isPending ? <p className="fine-print">Calculando el avance anual…</p> : null}
            {dashboardQuery.error ? <p className="form-error" role="alert">{dashboardQuery.error.message}</p> : null}
            {dashboardQuery.data?.annual ? (
              <>
                <p className="fine-print">Este corte usa documentos de meses con IVA marcado como presentado. Se recalcula si cambian los documentos o su clasificación y no sustituye la declaración anual de renta.</p>
                <ErpMetricGrid ariaLabel="Resumen del año fiscal">
                  <article className="metric-card"><span>Ventas · meses con IVA presentado</span><strong>{formatDashboardCurrency(dashboardQuery.data.annual.declaredSalesBase)}</strong></article>
                  <article className="metric-card"><span>Compras deducibles · meses con IVA presentado</span><strong>{formatDashboardCurrency(dashboardQuery.data.annual.declaredDeductiblePurchasesBase)}</strong></article>
                  <article className="metric-card"><span>Impuesto del escenario</span><strong>{dashboardQuery.data.annual.declaredEstimatedIncomeTax === null ? 'Elige una tarifa' : formatDashboardCurrency(dashboardQuery.data.annual.declaredEstimatedIncomeTax)}</strong></article>
                  <article className="metric-card"><span>Proyección del resultado</span><strong>{formatDashboardCurrency(dashboardQuery.data.annual.resultBeforeAdjustments)}</strong></article>
                  <article className="metric-card"><span>Compras no deducibles</span><strong>{formatDashboardCurrency(dashboardQuery.data.annual.nonDeductiblePurchasesBase)}</strong></article>
                  <article className="metric-card tax-annual-attention">
                    <span>Compras por revisar</span>
                    <strong>{formatDashboardCurrency(dashboardQuery.data.annual.pendingReviewPurchasesBase)}</strong>
                    <p>{dashboardQuery.data.annual.pendingReviewDocumentCount} documento(s)</p>
                  </article>
                </ErpMetricGrid>
                <ErpDataTable
                  ariaLabel={`Avance mensual del año fiscal ${dashboardQuery.data.annual.year}`}
                  rows={dashboardQuery.data.annual.months}
                  rowKey={(month) => String(month.month)}
                  columns={[
                    { header: 'Mes', mobileLabel: 'Mes', cell: (month) => <>{monthName(month.month)}</> },
                    { header: 'Estado', mobileLabel: 'Estado', cell: (month) => <ErpStatusBadge tone={month.isDeclared ? 'success' : 'neutral'}>{month.isDeclared ? 'IVA presentado' : 'Mes abierto'}</ErpStatusBadge> },
                    { header: 'Ventas', mobileLabel: 'Ventas', cell: (month) => <>{formatDashboardCurrency(month.salesBase)}</> },
                    { header: 'Compras deducibles', mobileLabel: 'Compras deducibles', cell: (month) => <>{formatDashboardCurrency(month.deductiblePurchasesBase)}</> },
                    { header: 'Retención de renta', mobileLabel: 'Retención de renta', cell: (month) => <>{formatDashboardCurrency(month.incomeTaxWithheld)}</> },
                  ]}
                />
                <div className="tax-annual-limitations" role="note" aria-label="Límites del cálculo anual">
                  <strong>Qué falta para estimar el impuesto</strong>
                  <ul>{dashboardQuery.data.annual.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
                </div>
              </>
            ) : null}
          </ErpPanel>
        </section>

        <section id="tax-section-retentions" className="tax-onepage-section tax-retention-panel" aria-labelledby="tax-retentions-title">
          <h2 id="tax-retentions-title" className="tax-section-title">Retenciones</h2>
          <ErpPanel title="Retenciones y posible saldo a favor">
            {dashboardQuery.isPending ? <p className="fine-print">Revisando retenciones…</p> : null}
            {dashboardQuery.error ? <p className="form-error" role="alert">{dashboardQuery.error.message}</p> : null}
            {dashboardQuery.data?.annual ? (
              <>
                <ErpMetricGrid ariaLabel="Retenciones acumuladas">
                  <article className="metric-card"><span>Retenciones de renta registradas en el año</span><strong>{formatDashboardCurrency(dashboardQuery.data.annual.incomeTaxWithheld)}</strong></article>
                  <article className="metric-card"><span>Retenciones de IVA acumuladas</span><strong>{formatDashboardCurrency(dashboardQuery.data.annual.ivaWithheld)}</strong></article>
                </ErpMetricGrid>
                <div className="tax-refund-guidance" role="status">
                  <ErpStatusBadge tone={dashboardQuery.data.annual.refundStatus === 'REVIEW_AT_ANNUAL_CLOSE' ? 'warning' : 'neutral'}>
                    {dashboardQuery.data.annual.refundStatus === 'REVIEW_AT_ANNUAL_CLOSE' ? 'Revisar al cierre anual' : 'Sin crédito registrado'}
                  </ErpStatusBadge>
                  <p>{dashboardQuery.data.annual.refundMessage}</p>
                </div>
                {dashboardQuery.data.annual.preliminaryDocumentCount > 0 ? (
                  <p className="form-warning" role="alert">
                    Cálculo incompleto: {dashboardQuery.data.annual.preliminaryDocumentCount} comprobante(s)
                    preliminar(es) aún no tienen respaldo completo. Carga sus XML antes de evaluar un saldo a favor.
                  </p>
                ) : null}
                <div className="tax-refund-steps">
                  <article>
                    <strong>Renta</strong>
                    <p>Las retenciones son crédito contra el impuesto anual. Si exceden el impuesto causado, podría existir pago en exceso.</p>
                  </article>
                  <article>
                    <strong>IVA</strong>
                    <p>Se revisa por separado. La devolución depende de que el crédito por retenciones no pueda compensarse y de los respaldos exigidos.</p>
                  </article>
                </div>
              </>
            ) : null}
          </ErpPanel>
        </section>
    </>
  )
}
