import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState, type FormEvent } from 'react'

import {
  apiRequest,
  idempotencyKey,
  type TaxEvidence,
  type TaxAnnex,
  type TaxFiscalDocument,
  type TaxIngestResult,
  type TaxIvaSummary,
  type TaxPeriod,
} from '../../api'
import { ErpButton, ErpEmptyState, ErpPageHeader, ErpPanel, ErpStatusBadge } from '../erp'

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

  const uploadEvidence = useMutation({
    mutationFn: async (file: File) => {
      const body = new FormData()
      body.append('file', file)
      body.append('origin', 'PORTAL_SRI')
      const evidence = await apiRequest<TaxEvidence>(token, '/tax/evidence', {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey('tax-evidence') },
        body,
      })
      // La ingesta es un paso aparte: guardar la evidencia nunca se pierde
      // aunque el archivo no se pueda interpretar.
      const result = await apiRequest<TaxIngestResult>(
        token,
        `/tax/evidence/${evidence.id}/ingest`,
        {
          method: 'POST',
          headers: { 'Idempotency-Key': idempotencyKey('tax-ingest') },
        },
      )
      return { evidence, result }
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['tax'] })
    },
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

  function submitEvidence(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const input = event.currentTarget.elements.namedItem('file') as HTMLInputElement | null
    const file = input?.files?.[0]
    if (file) uploadEvidence.mutate(file)
  }

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

  return (
    <>
      <ErpPageHeader
        eyebrow="Obligaciones SRI"
        title="Tributario"
        subtitle="Carga la evidencia del SRI y obtén los valores listos para declarar."
      />

      <ErpPanel title="Cargar evidencia del SRI">
        <form className="tax-upload" onSubmit={submitEvidence}>
          <label>
            Archivo del SRI (XML, TXT o ZIP)
            <input name="file" type="file" accept=".xml,.txt,.zip,.pdf" required />
          </label>
          <ErpButton variant="primary" type="submit" disabled={uploadEvidence.isPending}>
            {uploadEvidence.isPending ? 'Procesando…' : 'Cargar y procesar'}
          </ErpButton>
        </form>
        {uploadEvidence.error ? (
          <p className="form-error" role="alert">{uploadEvidence.error.message}</p>
        ) : null}
        {uploadEvidence.data ? (
          <div className="tax-ingest-result" role="status">
            <p>
              {uploadEvidence.data.evidence.duplicate
                ? 'El archivo ya estaba cargado; no se duplicó.'
                : `Archivo guardado (${uploadEvidence.data.evidence.fileType}).`}{' '}
              Comprobantes nuevos: {uploadEvidence.data.result.created} · actualizados:{' '}
              {uploadEvidence.data.result.updated}
              {uploadEvidence.data.result.preliminary > 0
                ? ` · preliminares: ${uploadEvidence.data.result.preliminary}`
                : ''}
            </p>
            {uploadEvidence.data.result.notes.map((note) => (
              <p key={note} className="fine-print">{note}</p>
            ))}
          </div>
        ) : null}
        <p className="fine-print">
          Los PDF se guardan como respaldo, pero sus valores no se leen automáticamente:
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

          <ErpPanel
            title={`Formulario 104 · ${monthName(summary.month)} ${summary.year}`}
            actions={<>
              <ErpStatusBadge tone={summary.isPreliminary ? 'warning' : 'success'}>
                {summary.documentCount} comprobante(s)
              </ErpStatusBadge>
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
            <div className="table-wrap" tabIndex={0} aria-label="Documentos del periodo">
              <table className="erp-responsive-table">
                <thead>
                  <tr>
                    <th>Fecha</th><th>Tipo</th><th>Contraparte</th>
                    <th>Base</th><th>IVA</th><th>Total</th><th>Pago</th><th>Estado</th>
                  </tr>
                </thead>
                <tbody>
                  {(documentsQuery.data ?? []).map((document) => (
                    <tr key={document.id}>
                      <td>{document.issueDate}</td>
                      <td>{document.direction === 'EMITIDO' ? '↑' : '↓'} {document.docType}</td>
                      <td>{document.counterpartyName ?? document.counterpartyIdentification ?? '—'}</td>
                      <td>${document.subtotal}</td>
                      <td>${document.taxTotal}</td>
                      <td>${document.total}</td>
                      <td>
                        {(document.paymentMethods ?? []).map((method) => (
                          method === '20' ? 'Transferencia' : `Código ${method}`
                        )).join(', ') || 'Sin respaldo XML'}
                      </td>
                      <td>
                        {document.isPreliminary ? (
                          <ErpStatusBadge tone="warning">Preliminar</ErpStatusBadge>
                        ) : (
                          <ErpStatusBadge tone="success">Confirmado</ErpStatusBadge>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
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
