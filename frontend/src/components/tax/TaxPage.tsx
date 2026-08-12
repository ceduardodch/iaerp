import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'

import {
  apiRequest,
  idempotencyKey,
  type TaxBulkResult,
  type AnalyticClassification,
  type TaxDocumentDossier,
  type TaxAnnex,
  type TaxFiscalDocument,
  type TaxIvaSummary,
  type TaxOwnDocumentsResult,
  type TaxPeriod,
} from '../../api'
import { ErpButton, ErpEmptyState, ErpPageHeader, ErpPanel, ErpStatusBadge } from '../erp'
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
export function TaxPage({ token }: { token: string }) {
  const queryClient = useQueryClient()
  const [selectedPeriodId, setSelectedPeriodId] = useState<string | null>(null)
  const [copiedField, setCopiedField] = useState<string | null>(null)
  const [generatedAnnex, setGeneratedAnnex] = useState<TaxAnnex | null>(null)
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const [applyRetentions, setApplyRetentions] = useState(false)
  const [openDossierId, setOpenDossierId] = useState<string | null>(null)
  const [exceptionEvidence, setExceptionEvidence] = useState<Record<string, string>>({})
  const [groupByClassificationId, setGroupByClassificationId] = useState('')

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
        subtitle="Carga la evidencia del SRI y obtén los valores listos para declarar."
      />

      <ErpPanel title="Cargar comprobantes del SRI">
        <div className="tax-upload">
          <label>
            Archivos del mes (XML, TXT o ZIP · hasta 50)
            <input
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
            <div className="table-wrap" tabIndex={0} aria-label="Detalle de la carga">
              <table className="erp-responsive-table">
                <thead>
                  <tr>
                    <th>Archivo</th><th>Tipo</th><th>Sentido</th>
                    <th>Emisión</th><th>Periodo</th><th>Contraparte</th>
                    <th>Total</th><th>Estado</th>
                  </tr>
                </thead>
                <tbody>
                  {bulkResult.items.map((item, index) => (
                    <tr key={`${item.filename}-${item.accessKey ?? index}`}>
                      <td>
                        {item.filename}
                        {item.sourceArchive ? (
                          <small> · en {item.sourceArchive}</small>
                        ) : null}
                      </td>
                      <td>{item.docType ?? '—'}</td>
                      <td>{item.direction === 'EMITIDO' ? '↑ Emitido' : item.direction === 'RECIBIDO' ? '↓ Recibido' : '—'}</td>
                      <td>{item.issueDate ?? '—'}</td>
                      <td>
                        {item.periodYear && item.periodMonth
                          ? `${monthName(item.periodMonth)} ${item.periodYear}`
                          : '—'}
                      </td>
                      <td>{item.counterpartyName ?? item.counterpartyIdentification ?? '—'}</td>
                      <td className="tax-value">{item.total ?? '—'}</td>
                      <td>
                        {item.status === 'ERROR' ? (
                          <ErpStatusBadge tone="danger">{item.error ?? 'Error'}</ErpStatusBadge>
                        ) : item.status === 'DUPLICADO' ? (
                          <ErpStatusBadge tone="neutral">Ya cargado · se validará de nuevo</ErpStatusBadge>
                        ) : (
                          <ErpStatusBadge tone="success">Listo</ErpStatusBadge>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

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
            <div className="tax-warning" role="alert">
              <strong>Datos preliminares.</strong>
              <ul>
                {summary.preliminaryReasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
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
              Valores con punto decimal y dos decimales, listos para copiar al formulario.
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
            <div className="table-wrap" tabIndex={0} aria-label="Campos para copiar">
              <table className="erp-responsive-table">
                <thead>
                  <tr>
                    <th>Campo</th>
                    <th>Concepto</th>
                    <th>Valor</th>
                    <th>Respaldo</th>
                    <th>Acción</th>
                  </tr>
                </thead>
                <tbody>
                  {pasteFields.map((field) => (
                    <tr key={field.fieldCode}>
                      <td><strong>{field.fieldCode}</strong></td>
                      <td>
                        {field.label}
                        {field.needsReview ? (
                          <small className="tax-review"> · confirmar código</small>
                        ) : null}
                      </td>
                      <td className="tax-value">{field.value}</td>
                      <td>{field.documentCount} doc.</td>
                      <td>
                        <ErpButton
                          variant="ghost"
                          aria-label={`Copiar campo ${field.fieldCode}`}
                          onClick={() => void copyValue(field.fieldCode, field.value)}
                        >
                          {copiedField === field.fieldCode ? 'Copiado' : 'Copiar'}
                        </ErpButton>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {controlFields.length > 0 ? (
              <>
                <p className="tax-subhead">Solo control (el SRI los calcula)</p>
                <div className="table-wrap" tabIndex={0} aria-label="Campos de control">
                  <table className="erp-responsive-table">
                    <thead>
                      <tr><th>Campo</th><th>Concepto</th><th>Valor</th></tr>
                    </thead>
                    <tbody>
                      {controlFields.map((field) => (
                        <tr key={field.fieldCode}>
                          <td>{field.fieldCode}</td>
                          <td>
                            {field.label}
                            {field.needsReview ? (
                              <small className="tax-review"> · confirmar código</small>
                            ) : null}
                          </td>
                          <td className="tax-value">{field.value}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            ) : null}
          </ErpPanel>

          <ErpPanel title="Resumen del periodo">
            <dl className="tax-summary">
              <div><dt>Ventas brutas</dt><dd>${summary.amounts.ventasBrutas ?? '0.00'}</dd></div>
              <div><dt>IVA generado</dt><dd>${summary.amounts.ivaGenerado ?? '0.00'}</dd></div>
              <div><dt>Compras con IVA</dt><dd>${summary.amounts.comprasGravadasBase ?? '0.00'}</dd></div>
              <div><dt>Compras sin IVA</dt><dd>${summary.amounts.comprasTarifaCeroBase ?? '0.00'}</dd></div>
              <div><dt>Crédito tributario</dt><dd>${summary.amounts.ivaCreditoTributario ?? '0.00'}</dd></div>
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
    </>
  )
}
