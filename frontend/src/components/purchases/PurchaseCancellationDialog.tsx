import { useRef, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiRequest, idempotencyKey, type PurchaseDocument, type TaxEvidence } from '../../api'
import { ErpButton } from '../erp'
import { ErpModal } from '../erp/ErpModal'

function fiscalToday() {
  return new Date().toLocaleDateString('en-CA', { timeZone: 'America/Guayaquil' })
}

export function PurchaseCancellationDialog({ token, document, onClose, onSaved }: {
  token: string
  document: PurchaseDocument
  onClose: () => void
  onSaved: () => void
}) {
  const queryClient = useQueryClient()
  const [effectiveDate, setEffectiveDate] = useState(fiscalToday)
  const [reason, setReason] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [confirmed, setConfirmed] = useState(false)
  const [fileError, setFileError] = useState('')
  const requestKey = useRef(idempotencyKey('web-purchase-cancellation'))
  const uploadKey = useRef(idempotencyKey('web-purchase-cancellation-evidence'))
  const uploadedEvidence = useRef<TaxEvidence | null>(null)
  const save = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error('Selecciona el respaldo de la anulación.')
      if (!uploadedEvidence.current) {
        const body = new FormData()
        body.append('file', file)
        body.append('origin', 'SRI_CANCELLATION')
        uploadedEvidence.current = await apiRequest<TaxEvidence>(token, '/tax/evidence', {
          method: 'POST', headers: { 'Idempotency-Key': uploadKey.current }, body,
        })
      }
      return apiRequest<PurchaseDocument>(token, `/tax/purchases/${document.id}/cancellation`, {
        method: 'POST',
        headers: { 'Idempotency-Key': requestKey.current },
        body: JSON.stringify({ effectiveDate, reason: reason.trim(), evidenceId: uploadedEvidence.current.id, sriStatus: 'ANULADO' }),
      })
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['payables'] })
      void queryClient.invalidateQueries({ queryKey: ['tax'] })
      onSaved()
    },
  })
  function changeRequest() {
    requestKey.current = idempotencyKey('web-purchase-cancellation')
    save.reset()
  }
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!confirmed || !file || fileError || reason.trim().length < 3) return
    save.mutate()
  }
  return <ErpModal title="Registrar anulación de compra" onClose={onClose} closeDisabled={save.isPending} initialFocusSelector='input[name="cancellationDate"]'>
    <form className="purchase-rule-form purchase-cancellation-form" onSubmit={submit} aria-describedby="purchase-cancellation-description">
      <p id="purchase-cancellation-description">Registra una anulación ya realizada en el SRI. Este paso no envía una solicitud de anulación al SRI.</p>
      <p><strong>{document.documentNumber ?? 'Sin número'}</strong> · {document.supplierName ?? 'Sin proveedor'}</p>
      <p className="fine-print">La compra queda en el historial y deja de contar entre las vigentes. Si tiene pagos, retenciones, notas de crédito o un período declarado, IAERP pedirá revisar esos vínculos antes de guardar.</p>
      <label>Fecha de anulación en el SRI<input name="cancellationDate" type="date" required min={document.issueDate} max={fiscalToday()} value={effectiveDate} disabled={save.isPending} onChange={(event) => { setEffectiveDate(event.target.value); changeRequest() }} /></label>
      <label>Motivo de la anulación<textarea required minLength={3} maxLength={500} value={reason} disabled={save.isPending} onChange={(event) => { setReason(event.target.value); changeRequest() }} /></label>
      <label>Respaldo de la anulación<input type="file" required disabled={save.isPending} aria-describedby="purchase-cancellation-file-help" onChange={(event) => {
        const selected = event.target.files?.[0] ?? null
        setFile(selected)
        setFileError(selected && (!selected.size || selected.size > 25 * 1024 * 1024) ? 'El respaldo debe tener contenido y pesar hasta 25 MB.' : '')
        uploadedEvidence.current = null
        uploadKey.current = idempotencyKey('web-purchase-cancellation-evidence')
        changeRequest()
      }} /></label><small id="purchase-cancellation-file-help">Adjunta la constancia o captura que muestre el estado Anulado en el SRI. Máximo 25 MB.</small>
      {fileError ? <p className="form-error" role="alert">{fileError}</p> : null}
      <label className="purchase-cancellation-confirm"><input type="checkbox" required checked={confirmed} disabled={save.isPending} onChange={(event) => { setConfirmed(event.target.checked); changeRequest() }} /><span>Confirmo que la factura consta ANULADA en el SRI</span></label>
      {save.error ? <p className="form-error" role="alert">{save.error.message}</p> : null}
      <div className="erp-form-actions">
        <ErpButton variant="secondary" onClick={onClose} disabled={save.isPending}>Cancelar</ErpButton>
        <ErpButton variant="primary" type="submit" disabled={save.isPending || !confirmed || !file || Boolean(fileError) || reason.trim().length < 3}>{save.isPending ? 'Guardando…' : 'Guardar'}</ErpButton>
      </div>
    </form>
  </ErpModal>
}

export function PurchaseCancellationDetails({ token, document }: { token: string; document: PurchaseDocument }) {
  const cancellation = document.cancellation
  const evidence = useQuery({
    queryKey: ['tax', 'evidence-download', cancellation?.evidenceId],
    queryFn: () => apiRequest<{ url: string }>(token, `/tax/evidence/${cancellation!.evidenceId}/download`),
    enabled: Boolean(cancellation),
  })
  if (!cancellation) return <p>La compra está anulada. Conserva su documento y su historial.</p>
  return <>
    <p><strong>Anulación registrada</strong> · {cancellation.effectiveDate}</p>
    <p>{cancellation.reason}</p>
    <p className="fine-print">El documento original se conserva. No cuenta entre las compras vigentes.</p>
    {evidence.data ? <a href={evidence.data.url} target="_blank" rel="noopener noreferrer">Ver respaldo de la anulación</a> : null}
    {evidence.error ? <p className="form-error" role="alert">No se pudo abrir el respaldo: {evidence.error.message}</p> : null}
  </>
}
