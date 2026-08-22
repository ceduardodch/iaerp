import { Fragment, useDeferredValue, useEffect, useRef, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  apiRequest,
  idempotencyKey,
  type BankStatementImport,
  type AnalyticClassification,
  type ExpenseRule,
  type Payable,
  type PayableMovement,
  type PurchaseDocument,
} from '../../api'
import {
  ErpButton,
  ErpEmptyState,
  ErpFormPanel,
  ErpPageHeader,
  ErpPanel,
  ErpStatusBadge,
  ErpTabs,
  ErpToolbar,
} from '../erp'
import { AnalyticClassificationPicker } from '../analytics/AnalyticClassificationPicker'
import { ErpConfirmDialog } from '../erp/ErpConfirmDialog'
import './PurchasesPage.css'

const amountFormatter = new Intl.NumberFormat('es-EC', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

function formatAmount(value: string | number): string {
  const amount = Number(value)
  return Number.isFinite(amount) ? amountFormatter.format(amount) : '0,00'
}

function today(): string {
  return new Date().toLocaleDateString('en-CA', { timeZone: 'America/Guayaquil' })
}

interface ExpenseDraft {
  supplierName?: string
  description?: string
  category?: string
  issueDate?: string
  total?: string
  paymentReference?: string
}

interface PurchaseFormProps {
  token: string
  draft?: ExpenseDraft
  onSaved: () => void
  onCancel: () => void
}

interface BulkReviewResultItem {
  documentId: string
  payableId: string | null
  status: 'REVIEWED' | 'PROTECTED' | 'SKIPPED' | 'FAILED'
  detail: string
}

interface BulkReviewResult {
  reviewedCount: number
  protectedCount: number
  skippedCount: number
  failedCount: number
  items: BulkReviewResultItem[]
}

interface BulkClassificationResult {
  updatedCount: number
  fiscalProtectedCount: number
  failedCount: number
  items: Array<{
    payableId: string
    status: 'UPDATED' | 'FAILED'
    detail: string
    fiscalUseProtected: boolean
  }>
}

function PurchaseForm({ token, draft, onSaved, onCancel }: PurchaseFormProps) {
  const [paymentTiming, setPaymentTiming] = useState<'PAID_NOW' | 'PAY_LATER'>('PAID_NOW')
  const [analyticValueIds, setAnalyticValueIds] = useState<string[]>([])
  const createPurchase = useMutation({
    mutationFn: (payload: Record<string, unknown>) => apiRequest<Payable>(token, '/payables', {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey('web-payable-create') },
      body: JSON.stringify(payload),
    }),
    onSuccess: onSaved,
  })

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const issueDate = String(form.get('issueDate'))
    const supportReference = String(form.get('supportReference') || '') || null
    createPurchase.mutate({
      supplierName: String(form.get('supplierName') || '') || null,
      description: String(form.get('description')),
      category: String(form.get('category')),
      documentType: String(form.get('documentType')),
      documentNumber: String(form.get('documentNumber') || '') || null,
      issueDate,
      dueDate: paymentTiming === 'PAY_LATER' ? String(form.get('dueDate')) : issueDate,
      total: String(form.get('total')),
      paymentTiming,
      paymentDate: paymentTiming === 'PAID_NOW' ? String(form.get('paymentDate')) : null,
      paymentMethod: paymentTiming === 'PAID_NOW' ? String(form.get('paymentMethod')) : null,
      paymentReference: String(form.get('paymentReference') || '') || null,
      taxClassification: String(form.get('taxClassification')),
      internalClassification: String(form.get('internalClassification')),
      evidenceStatus: supportReference ? 'ATTACHED' : 'NONE',
      supportReference,
      analyticValueIds,
    })
  }

  return (
    <ErpFormPanel
      eyebrow="Compras"
      title="Nueva compra"
      pending={createPurchase.isPending}
      error={createPurchase.error?.message}
      onSubmit={submit}
      onCancel={onCancel}
    >
      <p className="fine-print">Registra la operación ahora y completa el soporte después. Sin XML válido no se genera crédito IVA ni ATS.</p>
      <AnalyticClassificationPicker token={token} valueIds={analyticValueIds} onChange={setAnalyticValueIds} />
      <label>Descripción<input name="description" required minLength={2} defaultValue={draft?.description ?? ''} placeholder="Ej. Gasolina vehículo" /></label>
      <label>Proveedor opcional<input name="supplierName" defaultValue={draft?.supplierName ?? ''} placeholder="Nombre o comercio" /></label>
      <label>Categoría<input name="category" required defaultValue={draft?.category ?? 'Combustible'} /></label>
      <div className="purchase-form-grid">
        <label>Fecha<input name="issueDate" type="date" required defaultValue={draft?.issueDate ?? today()} /></label>
        <label>Total<input name="total" type="number" min="0.01" step="0.01" required defaultValue={draft?.total ?? ''} /></label>
      </div>
      <div className="purchase-form-grid">
        <label>Tipo de documento<select name="documentType" defaultValue="OTHER"><option value="OTHER">Sin factura / otro</option><option value="INVOICE">Factura</option><option value="LIQUIDATION">Liquidación</option><option value="DEBIT_NOTE">Nota de débito</option></select></label>
        <label>Número opcional<input name="documentNumber" /></label>
        <label>Clasificación fiscal<select name="taxClassification" defaultValue="DEDUCTIBLE_PENDING_REVIEW"><option value="DEDUCTIBLE_PENDING_REVIEW">Deducible · pendiente de revisión</option><option value="NON_DEDUCTIBLE">No deducible</option></select></label>
        <label>Control interno<select name="internalClassification" defaultValue="PENDING_REVIEW"><option value="PENDING_REVIEW">Pendiente de revisar</option><option value="REAL">Gasto real del negocio</option><option value="DECLARATION_ONLY">Solo tributario</option></select></label>
        <label>Soporte o referencia opcional<input name="supportReference" placeholder="Recibo, URL o referencia interna" /></label>
      </div>
      <fieldset className="purchase-payment-choice">
        <legend>¿Cómo queda el pago?</legend>
        <label><input type="radio" name="paymentTiming" checked={paymentTiming === 'PAID_NOW'} onChange={() => setPaymentTiming('PAID_NOW')} /> Pagado ahora</label>
        <label><input type="radio" name="paymentTiming" checked={paymentTiming === 'PAY_LATER'} onChange={() => setPaymentTiming('PAY_LATER')} /> Pagar después</label>
      </fieldset>
      {paymentTiming === 'PAID_NOW' ? (
        <div className="purchase-form-grid">
          <label>Fecha de pago<input name="paymentDate" type="date" required defaultValue={draft?.issueDate ?? today()} /></label>
          <label>Medio<select name="paymentMethod" defaultValue="TRANSFER"><option value="TRANSFER">Transferencia</option><option value="CARD">Tarjeta</option><option value="CASH">Efectivo</option><option value="CHECK">Cheque</option><option value="OTHER">Otro</option></select></label>
          <label className="purchase-grid-wide">Referencia opcional<input name="paymentReference" defaultValue={draft?.paymentReference ?? ''} /></label>
        </div>
      ) : <label>Vencimiento<input name="dueDate" type="date" required defaultValue={today()} /></label>}
    </ErpFormPanel>
  )
}

function SriPurchaseReview({ token, document, payable, onSaved, onCancel }: {
  token: string
  document: PurchaseDocument
  payable?: Payable
  onSaved: () => void
  onCancel: () => void
}) {
  const hasMovements = Boolean(payable && Number(payable.openAmount) !== Number(payable.total))
  const [taxClassification, setTaxClassification] = useState<
    '' | 'DEDUCTIBLE_CONFIRMED' | 'NON_DEDUCTIBLE'
  >('')
  const [internalClassification, setInternalClassification] = useState<
    '' | 'REAL' | 'DECLARATION_ONLY'
  >(payable?.internalClassification === 'REAL' || payable?.internalClassification === 'DECLARATION_ONLY' ? payable.internalClassification : '')
  const [paymentState, setPaymentState] = useState<'PAID' | 'SCHEDULED' | 'UNCONFIRMED' | 'KEEP_EXISTING'>(hasMovements ? 'KEEP_EXISTING' : 'UNCONFIRMED')
  const [analyticValueIds, setAnalyticValueIds] = useState<string[]>(
    (payable?.analyticAssignments ?? []).map((item) => item.valueId),
  )
  const startRef = useRef<HTMLDivElement>(null)
  const reviewIdempotencyKey = useRef(idempotencyKey('web-sri-purchase-review')).current
  useEffect(() => startRef.current?.focus(), [])
  const review = useMutation({
    mutationFn: (payload: Record<string, unknown>) => apiRequest<Payable>(token, '/payables/from-document/review', {
      method: 'POST',
      headers: { 'Idempotency-Key': reviewIdempotencyKey },
      body: JSON.stringify(payload),
    }),
    onSuccess: onSaved,
  })

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!taxClassification || !internalClassification) return
    const form = new FormData(event.currentTarget)
    review.mutate({
      documentId: document.id,
      taxClassification,
      internalClassification,
      analyticValueIds,
      paymentState,
      paymentDate: paymentState === 'PAID' ? String(form.get('paymentDate')) : null,
      paymentMethod: paymentState === 'PAID' ? String(form.get('paymentMethod')) : null,
      paymentReference: paymentState === 'PAID' ? String(form.get('paymentReference') || '') || null : null,
      scheduledDate: paymentState === 'SCHEDULED' ? String(form.get('scheduledDate')) : null,
    })
  }

  return <div className="purchase-review-focus" ref={startRef} tabIndex={-1} role="region" aria-label={`Revisión SRI de ${document.supplierName ?? 'compra sin proveedor'}`}>
    <ErpFormPanel
      eyebrow="Revisión SRI"
      title={document.supplierName ?? 'Compra sin proveedor'}
      submitLabel="Guardar revisión"
      pending={review.isPending}
      submitDisabled={!taxClassification || !internalClassification}
      error={review.error?.message}
      onSubmit={submit}
      onCancel={onCancel}
    >
      <dl className="purchase-sri-summary">
        <div><dt>Documento</dt><dd>{document.documentNumber ?? 'Sin número'}</dd></div>
        <div><dt>Emisión</dt><dd>{document.issueDate}</dd></div>
        <div><dt>Total</dt><dd>${formatAmount(document.total)}</dd></div>
        <div><dt>Respaldo</dt><dd>{document.isPreliminary ? 'Preliminar' : 'XML confirmado'}</dd></div>
      </dl>
      <fieldset className="purchase-review-options">
        <legend>Uso tributario</legend>
        <p className="fine-print">Esto clasifica la compra; no cambia el XML ni los valores descargados del SRI.</p>
        <label><input type="radio" name="taxClassification" checked={taxClassification === 'DEDUCTIBLE_CONFIRMED'} onChange={() => setTaxClassification('DEDUCTIBLE_CONFIRMED')} /><span><strong>Deducible para la declaración</strong><small>Entra al cálculo tributario con respaldo</small></span></label>
        <label><input type="radio" name="taxClassification" checked={taxClassification === 'NON_DEDUCTIBLE'} onChange={() => setTaxClassification('NON_DEDUCTIBLE')} /><span><strong>No deducible</strong><small>No reduce el resultado fiscal</small></span></label>
      </fieldset>
      <fieldset className="purchase-review-options">
        <legend>Control interno</legend>
        <p className="fine-print">Es independiente de la declaración. Usa los tags para asignar proyecto, sucursal o centro de costo.</p>
        <label><input type="radio" name="internalClassification" checked={internalClassification === 'REAL'} onChange={() => setInternalClassification('REAL')} /><span><strong>Gasto real del negocio</strong><small>Contará en el control interno por proyecto</small></span></label>
        <label><input type="radio" name="internalClassification" checked={internalClassification === 'DECLARATION_ONLY'} onChange={() => setInternalClassification('DECLARATION_ONLY')} /><span><strong>Solo tributario</strong><small>Se conserva para el SRI, pero no como costo interno</small></span></label>
      </fieldset>
      {!hasMovements ? <fieldset className="purchase-review-options">
        <legend>Estado del pago</legend>
        <label><input type="radio" name="paymentState" checked={paymentState === 'PAID'} onChange={() => setPaymentState('PAID')} /><span><strong>Ya pagado</strong><small>Registrar el pago completo</small></span></label>
        <label><input type="radio" name="paymentState" checked={paymentState === 'SCHEDULED'} onChange={() => setPaymentState('SCHEDULED')} /><span><strong>Pago previsto</strong><small>Guardar la fecha acordada</small></span></label>
        <label><input type="radio" name="paymentState" checked={paymentState === 'UNCONFIRMED'} onChange={() => setPaymentState('UNCONFIRMED')} /><span><strong>Sin fecha acordada</strong><small>Queda por pagar, sin inventar un vencimiento</small></span></label>
      </fieldset> : <fieldset className="purchase-review-existing"><legend>Pago ya registrado</legend><p>Se conserva el estado actual ({payable?.status === 'SETTLED' ? 'pagado' : `saldo $${formatAmount(payable?.openAmount ?? 0)}`}). Esta revisión solo decide el uso tributario.</p></fieldset>}
      {paymentState === 'PAID' ? (
        <div className="purchase-form-grid">
          <label>Fecha de pago<input name="paymentDate" type="date" required defaultValue={today()} /></label>
          <label>Medio<select name="paymentMethod" defaultValue="TRANSFER"><option value="TRANSFER">Transferencia</option><option value="CARD">Tarjeta</option><option value="CASH">Efectivo</option><option value="CHECK">Cheque</option><option value="OTHER">Otro</option></select></label>
          <label className="purchase-grid-wide">Referencia opcional<input name="paymentReference" /></label>
        </div>
      ) : null}
      {paymentState === 'SCHEDULED' ? <label>Fecha prevista de pago<input name="scheduledDate" type="date" required defaultValue={today()} /></label> : null}
      {!hasMovements ? <AnalyticClassificationPicker token={token} valueIds={analyticValueIds} onChange={setAnalyticValueIds} /> : (payable?.analyticAssignments ?? []).length ? <fieldset className="purchase-review-existing"><legend>Tags conservados</legend>{payable?.analyticAssignments.map((assignment) => <p key={assignment.classificationId}>{assignment.classificationName}: {assignment.path.map((part) => part.name).join(' / ')}</p>)}</fieldset> : null}
    </ErpFormPanel>
  </div>
}

function SriBulkReview({ token, documents, payablesByFiscalId, requestKey, onResult, onCancel }: {
  token: string
  documents: PurchaseDocument[]
  payablesByFiscalId: Map<string, Payable>
  requestKey: string
  onResult: (result: BulkReviewResult) => void
  onCancel: () => void
}) {
  const [taxClassification, setTaxClassification] = useState<'' | 'DEDUCTIBLE_CONFIRMED' | 'NON_DEDUCTIBLE'>('')
  const [internalClassification, setInternalClassification] = useState<'' | 'REAL' | 'DECLARATION_ONLY'>('')
  const [analyticMode, setAnalyticMode] = useState<'KEEP_EXISTING' | 'APPLY'>('KEEP_EXISTING')
  const [analyticValueIds, setAnalyticValueIds] = useState<string[]>([])
  const [paymentAction, setPaymentAction] = useState<'KEEP_EXISTING_OR_UNCONFIRMED' | 'PAID' | 'SCHEDULED'>('KEEP_EXISTING_OR_UNCONFIRMED')
  const [pendingPayload, setPendingPayload] = useState<Record<string, unknown> | null>(null)
  const startRef = useRef<HTMLDivElement>(null)
  useEffect(() => startRef.current?.focus(), [])
  const protectedDocuments = documents.filter((document) => {
    const payable = payablesByFiscalId.get(document.id)
    return payable && Number(payable.openAmount) !== Number(payable.total)
  })
  const editableDocuments = documents.filter((document) => !protectedDocuments.includes(document))
  const selectedTotal = documents.reduce((sum, document) => sum + Number(document.total), 0)
  const editableTotal = editableDocuments.reduce((sum, document) => sum + Number(document.total), 0)
  const preliminaryCount = documents.filter((document) => document.isPreliminary).length
  const purchaseLabel = documents.length === 1 ? 'compra' : 'compras'
  const review = useMutation({
    mutationFn: (payload: Record<string, unknown>) => apiRequest<BulkReviewResult>(token, '/payables/from-document/reviews', {
      method: 'POST',
      headers: { 'Idempotency-Key': requestKey },
      body: JSON.stringify(payload),
    }),
    onSuccess: onResult,
  })

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!taxClassification || !internalClassification) return
    const form = new FormData(event.currentTarget)
    const payload = {
      documentIds: documents.map((document) => document.id),
      taxClassification,
      internalClassification,
      analyticChange: { mode: analyticMode, valueIds: analyticMode === 'APPLY' ? analyticValueIds : [] },
      paymentAction,
      paymentDate: paymentAction === 'PAID' ? String(form.get('paymentDate')) : null,
      paymentMethod: paymentAction === 'PAID' ? String(form.get('paymentMethod')) : null,
      paymentReference: paymentAction === 'PAID' ? String(form.get('paymentReference') || '') || null : null,
      scheduledDate: paymentAction === 'SCHEDULED' ? String(form.get('scheduledDate')) : null,
    }
    if (paymentAction === 'PAID') {
      setPendingPayload(payload)
      return
    }
    review.mutate(payload)
  }

  return <div className="purchase-review-focus" ref={startRef} tabIndex={-1} role="region" aria-label={`Revisión masiva de ${documents.length} compras SRI`}>
    <ErpFormPanel
      eyebrow="Revisión masiva SRI"
      title={`${documents.length} ${purchaseLabel} ${documents.length === 1 ? 'seleccionada' : 'seleccionadas'}`}
      submitLabel={`Revisar ${documents.length} ${purchaseLabel}`}
      pending={review.isPending}
      submitDisabled={!taxClassification || !internalClassification || (analyticMode === 'APPLY' && analyticValueIds.length === 0)}
      error={review.error?.message}
      onSubmit={submit}
      onCancel={onCancel}
    >
      <dl className="purchase-sri-summary purchase-bulk-summary">
        <div><dt>Total seleccionado</dt><dd>${formatAmount(selectedTotal)}</dd></div>
        <div><dt>XML confirmados</dt><dd>{documents.length - preliminaryCount}</dd></div>
        <div><dt>Preliminares</dt><dd>{preliminaryCount}</dd></div>
        <div><dt>Protegidos</dt><dd>{protectedDocuments.length}</dd></div>
      </dl>
      {protectedDocuments.length ? <p className="purchase-bulk-protection" role="note">{protectedDocuments.length} {protectedDocuments.length === 1 ? 'compra tiene' : 'compras tienen'} movimientos. Solo cambiaremos sus marcas tributaria e interna; el pago y los tags actuales se conservan.</p> : null}
      <fieldset className="purchase-review-options">
        <legend>Uso tributario</legend>
        <label><input type="radio" name="bulkTaxClassification" checked={taxClassification === 'DEDUCTIBLE_CONFIRMED'} onChange={() => setTaxClassification('DEDUCTIBLE_CONFIRMED')} /><span><strong>Deducibles para la declaración</strong><small>Entran al cálculo tributario</small></span></label>
        <label><input type="radio" name="bulkTaxClassification" checked={taxClassification === 'NON_DEDUCTIBLE'} onChange={() => setTaxClassification('NON_DEDUCTIBLE')} /><span><strong>No deducibles</strong><small>No reducen el resultado fiscal</small></span></label>
      </fieldset>
      <fieldset className="purchase-review-options">
        <legend>Control interno</legend>
        <label><input type="radio" name="bulkInternalClassification" checked={internalClassification === 'REAL'} onChange={() => setInternalClassification('REAL')} /><span><strong>Gastos reales del negocio</strong><small>Contarán en el control interno y por proyectos</small></span></label>
        <label><input type="radio" name="bulkInternalClassification" checked={internalClassification === 'DECLARATION_ONLY'} onChange={() => setInternalClassification('DECLARATION_ONLY')} /><span><strong>Solo tributarios</strong><small>Se conservan para el SRI, no como costo interno</small></span></label>
      </fieldset>
      <fieldset className="purchase-review-options">
        <legend>Tags</legend>
        <label><input type="radio" name="bulkAnalyticMode" checked={analyticMode === 'KEEP_EXISTING'} onChange={() => setAnalyticMode('KEEP_EXISTING')} /><span><strong>No cambiar</strong><small>Conservar tags actuales; las compras nuevas quedan sin tag</small></span></label>
        <label><input type="radio" name="bulkAnalyticMode" checked={analyticMode === 'APPLY'} onChange={() => setAnalyticMode('APPLY')} /><span><strong>Aplicar los mismos tags</strong><small>Solo a compras sin movimientos</small></span></label>
      </fieldset>
      {analyticMode === 'APPLY' ? <><AnalyticClassificationPicker token={token} valueIds={analyticValueIds} onChange={setAnalyticValueIds} />{analyticValueIds.length === 0 ? <p className="fine-print">Selecciona al menos un tag para aplicar.</p> : null}</> : null}
      <fieldset className="purchase-review-options">
        <legend>Estado del pago</legend>
        <label><input type="radio" name="bulkPaymentAction" checked={paymentAction === 'KEEP_EXISTING_OR_UNCONFIRMED'} onChange={() => setPaymentAction('KEEP_EXISTING_OR_UNCONFIRMED')} /><span><strong>No registrar pagos</strong><small>Las nuevas quedan por pagar sin fecha; las existentes se conservan</small></span></label>
        <label><input type="radio" name="bulkPaymentAction" checked={paymentAction === 'SCHEDULED'} onChange={() => setPaymentAction('SCHEDULED')} /><span><strong>Programar pago</strong><small>Asignar una fecha común</small></span></label>
        <label><input type="radio" name="bulkPaymentAction" checked={paymentAction === 'PAID'} onChange={() => setPaymentAction('PAID')} /><span><strong>Marcar como pagadas</strong><small>Requiere confirmación final</small></span></label>
      </fieldset>
      {paymentAction === 'SCHEDULED' ? <label>Fecha prevista de pago<input name="scheduledDate" type="date" required defaultValue={today()} /></label> : null}
      {paymentAction === 'PAID' ? <div className="purchase-form-grid"><label>Fecha de pago<input name="paymentDate" type="date" required defaultValue={today()} /></label><label>Medio<select name="paymentMethod" defaultValue="TRANSFER"><option value="TRANSFER">Transferencia</option><option value="CARD">Tarjeta</option><option value="CASH">Efectivo</option><option value="CHECK">Cheque</option><option value="OTHER">Otro</option></select></label><label className="purchase-grid-wide">Referencia opcional<input name="paymentReference" /></label></div> : null}
    </ErpFormPanel>
    {pendingPayload ? <ErpConfirmDialog
      title="Confirmar pagos de varias compras"
      description={<><p>Vas a registrar como pagadas {editableDocuments.length} compras por ${formatAmount(editableTotal)}. {protectedDocuments.length ? `${protectedDocuments.length} conservarán su pago actual.` : ''}</p>{review.error ? <p className="form-error" role="alert">{review.error.message}</p> : null}</>}
      confirmLabel={`Marcar ${editableDocuments.length} como ${editableDocuments.length === 1 ? 'pagada' : 'pagadas'}`}
      pending={review.isPending}
      onCancel={() => setPendingPayload(null)}
      onConfirm={() => review.mutate(pendingPayload)}
    /> : null}
  </div>
}

function RuleManager({ token }: { token: string }) {
  const queryClient = useQueryClient()
  const rulesQuery = useQuery({
    queryKey: ['expense-rules'],
    queryFn: () => apiRequest<ExpenseRule[]>(token, '/expense-rules'),
  })
  const createRule = useMutation({
    mutationFn: (payload: Record<string, unknown>) => apiRequest<ExpenseRule>(token, '/expense-rules', {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey('web-expense-rule') },
      body: JSON.stringify(payload),
    }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['expense-rules'] }),
  })

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    createRule.mutate({
      name: String(form.get('name')),
      descriptionPattern: String(form.get('descriptionPattern')),
      accountLast4: String(form.get('accountLast4') || '') || null,
      category: String(form.get('category')),
      supplierName: String(form.get('supplierName') || '') || null,
      taxClassification: 'DEDUCTIBLE_PENDING_REVIEW',
      active: true,
    })
  }

  return (
    <div className="purchase-rule-layout">
      <ErpPanel title="Reglas activas" count={rulesQuery.data?.length ?? 0}>
        {(rulesQuery.data ?? []).length ? <ul className="purchase-rule-list">{rulesQuery.data?.map((rule) => <li key={rule.id}><strong>{rule.name}</strong><span>Si contiene “{rule.descriptionPattern}” → {rule.category}</span><small>{rule.supplierName ?? 'Proveedor por confirmar'} · siempre pide confirmación</small></li>)}</ul> : <ErpEmptyState title="Sin reglas" description="Crea una regla para reconocer débitos frecuentes como gasolina o comisiones." />}
      </ErpPanel>
      <ErpPanel title="Nueva regla">
        <form className="purchase-rule-form" onSubmit={submit}>
          <label>Nombre<input name="name" required minLength={2} /></label>
          <label>Texto que debe contener<input name="descriptionPattern" required minLength={2} placeholder="GASOLINERA" /></label>
          <label>Categoría<input name="category" required defaultValue="Combustible" /></label>
          <label>Proveedor sugerido<input name="supplierName" /></label>
          <label>Últimos 4 de cuenta, opcional<input name="accountLast4" pattern="[0-9]{4}" /></label>
          {createRule.error ? <p className="form-error" role="alert">{createRule.error.message}</p> : null}
          <ErpButton variant="primary" type="submit" disabled={createRule.isPending}>{createRule.isPending ? 'Guardando…' : 'Guardar'}</ErpButton>
        </form>
      </ErpPanel>
    </div>
  )
}

interface BankReconciliationProps {
  token: string
  payables: Payable[]
  onCreateExpense: (draft: ExpenseDraft) => void
}

interface DebitAllocationDraft {
  transactionId: string
  payableId: string
  amount: string
}

function ManualAllocationEditor({ item, payables, onAdd }: {
  item: BankStatementImport['debitSuggestions'][number]
  payables: Payable[]
  onAdd: (allocation: DebitAllocationDraft) => void
}) {
  const candidates = payables.filter((payable) => payable.status === 'OPEN' || payable.status === 'PARTIAL')
  const [payableId, setPayableId] = useState(candidates[0]?.id ?? '')
  const [amount, setAmount] = useState(item.amount)
  if (!candidates.length) return <span className="fine-print">No hay CxP abierta</span>
  const effectivePayableId = payableId || candidates[0]!.id
  return <div className="purchase-allocation-editor"><select aria-label={`CxP para ${item.reference}`} value={effectivePayableId} onChange={(event) => setPayableId(event.target.value)}>{candidates.map((payable) => <option key={payable.id} value={payable.id}>{payable.supplierName ?? payable.description} · saldo ${formatAmount(payable.openAmount)}</option>)}</select><input aria-label={`Monto para ${item.reference}`} type="number" min="0.01" max={item.amount} step="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} /><ErpButton variant="secondary" onClick={() => onAdd({ transactionId: item.transactionId, payableId: effectivePayableId, amount })}>Agregar cruce</ErpButton></div>
}

function BankReconciliation({ token, payables, onCreateExpense }: BankReconciliationProps) {
  const queryClient = useQueryClient()
  const [period, setPeriod] = useState(today().slice(0, 7))
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<BankStatementImport | null>(null)
  const [manualAllocations, setManualAllocations] = useState<DebitAllocationDraft[]>([])

  function formData(apply: boolean): FormData {
    if (!file) throw new Error('Selecciona el TXT del banco.')
    const data = new FormData()
    data.append('file', file)
    data.append('period', period)
    data.append('apply', String(apply))
    if (manualAllocations.length) data.append('debitAllocations', JSON.stringify(manualAllocations))
    return data
  }

  const review = useMutation({
    mutationFn: () => apiRequest<BankStatementImport>(token, '/finance/bank-statements', { method: 'POST', body: formData(false) }),
    onSuccess: setPreview,
  })
  const applyMatches = useMutation({
    mutationFn: () => apiRequest<BankStatementImport>(token, '/finance/bank-statements', {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey('web-finance-bank') },
      body: formData(true),
    }),
    onSuccess: (result) => {
      setPreview(result)
      void queryClient.invalidateQueries({ queryKey: ['payables'] })
      void queryClient.invalidateQueries({ queryKey: ['receivables'] })
    },
  })

  return (
    <ErpPanel title="Conciliación bancaria">
      <form className="purchase-bank-form" onSubmit={(event) => { event.preventDefault(); review.mutate() }}>
        <p className="fine-print">Una sola carga cruza créditos con CxC y débitos con CxP. El extracto prueba el movimiento de dinero, no su efecto fiscal.</p>
        <label>Período<input type="month" required value={period} onChange={(event) => { setPeriod(event.target.value); setPreview(null) }} /></label>
        <label>Extracto Banco Bolivariano<input type="file" accept=".txt,text/plain" required onChange={(event) => { setFile(event.target.files?.[0] ?? null); setPreview(null) }} /></label>
        {review.error ? <p className="form-error" role="alert">{review.error.message}</p> : null}
        <ErpButton variant="primary" type="submit" disabled={review.isPending}>{review.isPending ? 'Revisando…' : 'Revisar movimientos'}</ErpButton>
      </form>
      {preview ? (
        <div className="purchase-bank-results" aria-live="polite">
          <p><strong>{preview.accountMasked}</strong> · {preview.creditRows} créditos · {preview.debitRows} débitos</p>
          <div className="purchase-bank-columns">
            <section aria-labelledby="bank-credit-title"><h3 id="bank-credit-title">Cobros encontrados</h3>{preview.matches.length ? <ul>{preview.matches.map((match) => <li key={match.transactionId}><span>{match.paymentDate} · Factura {match.invoiceSequential}</span><strong>${formatAmount(match.amount)}</strong><small>{match.detail}</small></li>)}</ul> : <p className="fine-print">No hay créditos con cruce único.</p>}</section>
            <section aria-labelledby="bank-debit-title"><h3 id="bank-debit-title">Pagos encontrados</h3>{preview.debitMatches.length ? <ul>{preview.debitMatches.map((match) => <li key={`${match.transactionId}-${match.payableId}`}><span>{match.paymentDate} · {match.supplierName ?? match.description}</span><strong>${formatAmount(match.allocatedAmount)}</strong><small>{match.detail}</small></li>)}</ul> : <p className="fine-print">No hay débitos con cruce único.</p>}</section>
          </div>
          {preview.debitSuggestions.length ? <section aria-labelledby="bank-suggestions-title"><h3 id="bank-suggestions-title">Débitos por revisar</h3><p className="fine-print">Puedes preparar un gasto o repartir el débito entre una o varias CxP. Revisa el reparto antes de confirmar.</p><div className="table-wrap" tabIndex={0}><table className="erp-responsive-table"><thead><tr><th>Fecha</th><th>Descripción</th><th>Valor</th><th>Regla</th><th>Acción</th></tr></thead><tbody>{preview.debitSuggestions.map((item) => <tr key={item.transactionId}><td>{item.paymentDate}</td><td>{item.description}<small>{item.detail}</small></td><td>${formatAmount(item.amount)}</td><td>{item.ruleName ?? 'Sin regla'}</td><td><div className="purchase-suggestion-actions">{item.classification === 'EXPENSE_CANDIDATE' || item.classification === 'BANK_FEE' || item.classification === 'BANK_TAX' || item.classification === 'UNCLASSIFIED' ? <ErpButton variant="secondary" onClick={() => onCreateExpense({ supplierName: item.suggestedSupplierName ?? '', description: item.description, category: item.suggestedCategory ?? (item.classification === 'BANK_FEE' ? 'Comisiones bancarias' : item.classification === 'BANK_TAX' ? 'Impuestos bancarios' : 'Sin clasificar'), issueDate: item.paymentDate, total: item.amount })}>Crear gasto</ErpButton> : <span className="fine-print">Clasificar manualmente</span>}<ManualAllocationEditor item={item} payables={payables} onAdd={(allocation) => setManualAllocations((current) => [...current, allocation])} /></div></td></tr>)}</tbody></table></div></section> : null}
          {manualAllocations.length ? <section className="purchase-allocation-summary" aria-labelledby="allocation-title"><h3 id="allocation-title">Repartos preparados</h3><ul>{manualAllocations.map((allocation, index) => { const payable = payables.find((item) => item.id === allocation.payableId); return <li key={`${allocation.transactionId}-${allocation.payableId}-${index}`}><span>{payable?.supplierName ?? payable?.description ?? 'CxP'} · ${formatAmount(allocation.amount)}</span><ErpButton variant="ghost" onClick={() => setManualAllocations((current) => current.filter((_, itemIndex) => itemIndex !== index))}>Quitar</ErpButton></li> })}</ul><ErpButton variant="secondary" disabled={review.isPending} onClick={() => review.mutate()}>Revisar reparto</ErpButton></section> : null}
          {applyMatches.error ? <p className="form-error" role="alert">{applyMatches.error.message}</p> : null}
          <ErpButton variant="primary" disabled={applyMatches.isPending || preview.matchedCount + preview.manualCorrectionCount + preview.payableMatchedCount === 0} onClick={() => applyMatches.mutate()}>{applyMatches.isPending ? 'Aplicando…' : `Confirmar ${preview.matchedCount + preview.manualCorrectionCount + preview.payableMatchedCount} cruces`}</ErpButton>
        </div>
      ) : null}
    </ErpPanel>
  )
}

function statusBadge(payable: Payable) {
  const labels = { OPEN: 'Por pagar', PARTIAL: 'Pago parcial', SETTLED: 'Pagada', VOIDED: 'Anulada' }
  const tones = { OPEN: 'warning', PARTIAL: 'warning', SETTLED: 'success', VOIDED: 'danger' } as const
  return <ErpStatusBadge tone={tones[payable.status]}>{labels[payable.status]}</ErpStatusBadge>
}

function PayableClassificationEditor({ token, payable, onSaved }: {
  token: string
  payable: Payable
  onSaved: () => void
}) {
  const [valueIds, setValueIds] = useState((payable.analyticAssignments ?? []).map((item) => item.valueId))
  const [taxClassification, setTaxClassification] = useState<
    'DEDUCTIBLE_CONFIRMED' | 'NON_DEDUCTIBLE'
  >(payable.taxClassification === 'NON_DEDUCTIBLE' ? 'NON_DEDUCTIBLE' : 'DEDUCTIBLE_CONFIRMED')
  const [internalClassification, setInternalClassification] = useState<
    '' | 'REAL' | 'DECLARATION_ONLY'
  >(payable.internalClassification === 'PENDING_REVIEW' ? '' : payable.internalClassification)
  const [reason, setReason] = useState('')
  const fiscalUseChanged = taxClassification !== payable.taxClassification
  const save = useMutation({
    mutationFn: () => apiRequest<Payable>(token, `/payables/${payable.id}/classification`, {
      method: 'PUT',
      headers: { 'Idempotency-Key': idempotencyKey('web-payable-classification') },
      body: JSON.stringify({
        taxClassification,
        internalClassification,
        reason: fiscalUseChanged ? reason : null,
        analyticValueIds: valueIds,
      }),
    }),
    onSuccess: onSaved,
  })

  return <form className="purchase-tag-editor" onSubmit={(event) => { event.preventDefault(); save.mutate() }}>
    <fieldset className="purchase-review-options">
      <legend>Uso fiscal</legend>
      <p className="fine-print">La clasificación define qué entra al cálculo anual; no cambia el XML recibido.</p>
      <label><input type="radio" name={`taxClassification-${payable.id}`} checked={taxClassification === 'DEDUCTIBLE_CONFIRMED'} onChange={() => setTaxClassification('DEDUCTIBLE_CONFIRMED')} /><span><strong>Para declaración · deducible</strong><small>Entra al cálculo tributario con su respaldo fiscal</small></span></label>
      <label><input type="radio" name={`taxClassification-${payable.id}`} checked={taxClassification === 'NON_DEDUCTIBLE'} onChange={() => setTaxClassification('NON_DEDUCTIBLE')} /><span><strong>No deducible</strong><small>Se declara cuando corresponda, pero no reduce el resultado fiscal</small></span></label>
    </fieldset>
    {fiscalUseChanged ? <label>Motivo del cambio<input value={reason} onChange={(event) => setReason(event.target.value)} required minLength={3} maxLength={300} placeholder="Ej. Se confirmó que corresponde al servicio contratado" /></label> : null}
    <fieldset className="purchase-review-options">
      <legend>Control interno</legend>
      <p className="fine-print">Esta marca no cambia IVA, ATS ni renta. Sirve para costos y proyectos internos.</p>
      <label><input type="radio" name={`internalClassification-${payable.id}`} checked={internalClassification === 'REAL'} onChange={() => setInternalClassification('REAL')} /><span><strong>Gasto real del negocio</strong><small>Cuenta en el control interno y puede asignarse a un proyecto</small></span></label>
      <label><input type="radio" name={`internalClassification-${payable.id}`} checked={internalClassification === 'DECLARATION_ONLY'} onChange={() => setInternalClassification('DECLARATION_ONLY')} /><span><strong>Solo tributario</strong><small>Se conserva para el SRI, pero no cuenta como costo interno</small></span></label>
    </fieldset>
    <AnalyticClassificationPicker token={token} valueIds={valueIds} onChange={setValueIds} />
    {save.error ? <p className="form-error" role="alert">{save.error.message}</p> : null}
    <p className="fine-print">Si el periodo ya fue declarado, IAERP pedirá corregir primero esa declaración.</p>
    <ErpButton variant="primary" type="submit" disabled={save.isPending || !internalClassification || (fiscalUseChanged && reason.trim().length < 3)}>{save.isPending ? 'Guardando…' : 'Guardar clasificación'}</ErpButton>
  </form>
}

function PayableBulkClassificationEditor({ token, payables, requestKey, onSaved, onCancel }: {
  token: string
  payables: Payable[]
  requestKey: string
  onSaved: (result: BulkClassificationResult) => void
  onCancel: () => void
}) {
  const [taxClassification, setTaxClassification] = useState<'' | 'DEDUCTIBLE_CONFIRMED' | 'NON_DEDUCTIBLE'>('')
  const [internalClassification, setInternalClassification] = useState<'' | 'REAL' | 'DECLARATION_ONLY'>('')
  const [analyticChange, setAnalyticChange] = useState<'KEEP_EXISTING' | 'REPLACE'>('KEEP_EXISTING')
  const [valueIds, setValueIds] = useState<string[]>([])
  const [reason, setReason] = useState('')
  const startRef = useRef<HTMLDivElement>(null)
  const total = payables.reduce((sum, payable) => sum + Number(payable.total), 0)
  const hasChanges = Boolean(taxClassification || internalClassification || analyticChange === 'REPLACE')
  useEffect(() => startRef.current?.focus(), [])
  const save = useMutation({
    mutationFn: () => apiRequest<BulkClassificationResult>(token, '/payables/classifications/bulk', {
      method: 'PUT',
      headers: { 'Idempotency-Key': requestKey },
      body: JSON.stringify({
        payableIds: payables.map((payable) => payable.id),
        taxClassification: taxClassification || null,
        internalClassification: internalClassification || null,
        reason: taxClassification ? reason : null,
        analyticChange,
        analyticValueIds: analyticChange === 'REPLACE' ? valueIds : [],
      }),
    }),
    onSuccess: onSaved,
  })

  return <div className="purchase-review-focus" ref={startRef} tabIndex={-1} role="region" aria-label={`Edición masiva de ${payables.length} ${payables.length === 1 ? 'compra' : 'compras'}`}>
    <ErpFormPanel
      eyebrow="Edición masiva"
      title={`${payables.length} ${payables.length === 1 ? 'compra seleccionada' : 'compras seleccionadas'}`}
      submitLabel={`Guardar cambios en ${payables.length}`}
      pending={save.isPending}
      submitDisabled={!hasChanges || Boolean(taxClassification && reason.trim().length < 3)}
      error={save.error?.message}
      onSubmit={(event) => { event.preventDefault(); save.mutate() }}
      onCancel={onCancel}
    >
      <dl className="purchase-sri-summary purchase-bulk-summary">
        <div><dt>Compras</dt><dd>{payables.length}</dd></div>
        <div><dt>Total seleccionado</dt><dd>${formatAmount(total)}</dd></div>
      </dl>
      <p className="fine-print">Elige solo lo que quieres cambiar. Los campos en “No cambiar” conservan el valor de cada compra.</p>
      <label>Uso tributario ante el SRI<select value={taxClassification} onChange={(event) => setTaxClassification(event.target.value as typeof taxClassification)}><option value="">No cambiar (recomendado)</option><option value="DEDUCTIBLE_CONFIRMED">Para declaración · deducible</option><option value="NON_DEDUCTIBLE">No deducible</option></select></label>
      {taxClassification ? <label>Motivo del cambio<input value={reason} onChange={(event) => setReason(event.target.value)} required minLength={3} maxLength={300} placeholder="Ej. Se revisó el uso de estas compras" /></label> : null}
      <label>Control interno<select value={internalClassification} onChange={(event) => setInternalClassification(event.target.value as typeof internalClassification)}><option value="">No cambiar</option><option value="REAL">Gasto real del negocio</option><option value="DECLARATION_ONLY">Solo tributario</option></select><small>Esta marca sí puede corregirse aunque el mes ya esté declarado.</small></label>
      <fieldset className="purchase-review-options">
        <legend>Tags</legend>
        <label><input type="radio" name="bulkPayableTags" checked={analyticChange === 'KEEP_EXISTING'} onChange={() => setAnalyticChange('KEEP_EXISTING')} /><span><strong>No cambiar</strong><small>Cada compra conserva sus tags actuales</small></span></label>
        <label><input type="radio" name="bulkPayableTags" checked={analyticChange === 'REPLACE'} onChange={() => setAnalyticChange('REPLACE')} /><span><strong>Reemplazar</strong><small>Aplica los mismos tags; sin selección los limpia</small></span></label>
      </fieldset>
      {analyticChange === 'REPLACE' ? <AnalyticClassificationPicker token={token} valueIds={valueIds} onChange={setValueIds} /> : null}
      <p className="fine-print">IAERP no cambiará el uso tributario de compras que pertenezcan a un periodo ya declarado; las mostrará como fallidas y guardará las demás.</p>
    </ErpFormPanel>
  </div>
}

function PayableDetail({ token, payable, onClose }: { token: string; payable: Payable; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [reversingMovementId, setReversingMovementId] = useState<string | null>(null)
  const movementsQuery = useQuery({
    queryKey: ['payables', payable.id, 'movements'],
    queryFn: () => apiRequest<PayableMovement[]>(token, `/payables/${payable.id}/movements`),
  })
  const payment = useMutation({
    mutationFn: (payload: Record<string, unknown>) => apiRequest<Payable>(token, `/payables/${payable.id}/payments`, {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey('web-payable-payment') },
      body: JSON.stringify(payload),
    }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['payables'] })
      void queryClient.invalidateQueries({ queryKey: ['payables', payable.id, 'movements'] })
    },
  })
  const adjustment = useMutation({
    mutationFn: (payload: Record<string, unknown>) => apiRequest<Payable>(token, `/payables/${payable.id}/adjustments`, {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey('web-payable-adjustment') },
      body: JSON.stringify(payload),
    }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['payables'] })
      void queryClient.invalidateQueries({ queryKey: ['payables', payable.id, 'movements'] })
    },
  })
  const reversal = useMutation({
    mutationFn: ({ movementId, payload }: { movementId: string; payload: Record<string, unknown> }) => apiRequest<Payable>(token, `/payables/${payable.id}/movements/${movementId}/reversal`, {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey('web-payable-reversal') },
      body: JSON.stringify(payload),
    }),
    onSuccess: () => {
      setReversingMovementId(null)
      void queryClient.invalidateQueries({ queryKey: ['payables'] })
      void queryClient.invalidateQueries({ queryKey: ['payables', payable.id, 'movements'] })
    },
  })

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    payment.mutate({
      amount: String(form.get('amount')),
      paymentDate: String(form.get('paymentDate')),
      method: String(form.get('method')),
      reference: String(form.get('reference') || '') || null,
    })
  }

  function submitAdjustment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    adjustment.mutate({
      movementType: String(form.get('movementType')),
      amount: String(form.get('amount')),
      effectiveDate: String(form.get('effectiveDate')),
      reference: String(form.get('reference')),
    })
  }

  function submitReversal(event: FormEvent<HTMLFormElement>, movementId: string) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    reversal.mutate({ movementId, payload: { reason: String(form.get('reason')), effectiveDate: String(form.get('effectiveDate')) } })
  }

  const reversedMovementIds = new Set((movementsQuery.data ?? []).filter((movement) => movement.movementType === 'REVERSAL').map((movement) => movement.reversedMovementId).filter(Boolean))

  return (
    <div className="purchase-detail-layout">
      <div className="purchase-detail-stack">
        {payable.status === 'OPEN' || payable.status === 'PARTIAL' ? <><ErpPanel title="Registrar abono"><form className="purchase-rule-form" onSubmit={submit}><p className="fine-print">Saldo actual: ${formatAmount(payable.openAmount)}. El banco podrá enlazar este pago como evidencia sin duplicarlo.</p><label>Monto<input name="amount" type="number" min="0.01" max={payable.openAmount} step="0.01" required defaultValue={payable.openAmount} /></label><label>Fecha<input name="paymentDate" type="date" required defaultValue={today()} /></label><label>Medio<select name="method" defaultValue="TRANSFER"><option value="TRANSFER">Transferencia</option><option value="CARD">Tarjeta</option><option value="CASH">Efectivo</option><option value="CHECK">Cheque</option><option value="OTHER">Otro</option></select></label><label>Referencia<input name="reference" /></label>{payment.error ? <p className="form-error" role="alert">{payment.error.message}</p> : null}<div className="purchase-detail-actions"><ErpButton variant="primary" type="submit" disabled={payment.isPending}>{payment.isPending ? 'Guardando…' : 'Registrar pago'}</ErpButton><ErpButton variant="ghost" onClick={onClose}>Cerrar</ErpButton></div></form></ErpPanel><ErpPanel title="Aplicar ajuste"><form className="purchase-rule-form" onSubmit={submitAdjustment}><p className="fine-print">Una retención o nota de crédito reduce el saldo y queda separada del dinero pagado.</p><label>Tipo<select name="movementType" defaultValue="RETENTION"><option value="RETENTION">Retención</option><option value="CREDIT_NOTE">Nota de crédito</option></select></label><label>Monto<input name="amount" type="number" min="0.01" max={payable.openAmount} step="0.01" required /></label><label>Fecha efectiva<input name="effectiveDate" type="date" required defaultValue={today()} /></label><label>Documento o motivo<input name="reference" required minLength={3} /></label>{adjustment.error ? <p className="form-error" role="alert">{adjustment.error.message}</p> : null}<ErpButton variant="primary" type="submit" disabled={adjustment.isPending}>{adjustment.isPending ? 'Aplicando…' : 'Aplicar ajuste'}</ErpButton></form></ErpPanel></> : <ErpPanel title="Detalle"><p>Esta cuenta está {payable.status === 'SETTLED' ? 'pagada' : 'anulada'}.</p><ErpButton variant="ghost" onClick={onClose}>Cerrar</ErpButton></ErpPanel>}
      </div>
      <ErpPanel title="Historial" count={movementsQuery.data?.length ?? 0}>
        {movementsQuery.isPending ? <p aria-busy="true">Cargando historial…</p> : null}
        {(movementsQuery.data ?? []).length ? <ul className="purchase-movement-list">{movementsQuery.data?.map((movement) => <li key={movement.id}><span>{movement.effectiveDate} · {movement.movementType}</span><strong>${formatAmount(movement.amount)}</strong><small>{movement.supportReference ?? movement.method ?? 'Sin referencia'}</small>{movement.movementType !== 'REVERSAL' && !reversedMovementIds.has(movement.id) ? <ErpButton variant="ghost" onClick={() => setReversingMovementId(movement.id)}>Revertir</ErpButton> : null}{reversingMovementId === movement.id ? <form className="purchase-reversal-form" onSubmit={(event) => submitReversal(event, movement.id)}><label>Motivo<input name="reason" required minLength={3} /></label><label>Fecha<input name="effectiveDate" type="date" required defaultValue={today()} /></label>{reversal.error ? <p className="form-error" role="alert">{reversal.error.message}</p> : null}<div className="purchase-detail-actions"><ErpButton variant="primary" type="submit" disabled={reversal.isPending}>Confirmar reverso</ErpButton><ErpButton variant="ghost" onClick={() => setReversingMovementId(null)}>Cancelar</ErpButton></div></form> : null}</li>)}</ul> : !movementsQuery.isPending ? <ErpEmptyState title="Sin movimientos" description="Aún no hay pagos, retenciones, notas de crédito ni reversos." /> : null}
      </ErpPanel>
    </div>
  )
}

export function PurchasesPage({
  token,
  partyFilterId,
}: {
  token: string
  /** Llega con valor al abrir Compras desde la ficha de un proveedor. */
  partyFilterId?: string
}) {
  const queryClient = useQueryClient()
  // Antes había seis pestañas y tres de ellas eran solo un filtro de estado
  // del mismo listado. Quedan tres destinos reales y el estado se elige dentro.
  const [view, setView] = useState<'SRI' | 'LIST' | 'BANK'>('LIST')
  const [statusFilter, setStatusFilter] = useState<'ALL' | 'OPEN' | 'SETTLED'>('ALL')
  const [taxFilter, setTaxFilter] = useState<'ALL' | 'DECLARABLE' | 'NON_DEDUCTIBLE' | 'PENDING'>('ALL')
  const [internalFilter, setInternalFilter] = useState<'ALL' | 'REAL' | 'DECLARATION_ONLY' | 'PENDING'>('ALL')
  const [query, setQuery] = useState('')
  const [isCreating, setIsCreating] = useState(false)
  const [draft, setDraft] = useState<ExpenseDraft | undefined>()
  const [selectedPayableId, setSelectedPayableId] = useState<string | null>(null)
  const [editingTagsFor, setEditingTagsFor] = useState<string | null>(null)
  const [reviewingFiscalId, setReviewingFiscalId] = useState<string | null>(null)
  const [selectedFiscalIds, setSelectedFiscalIds] = useState<string[]>([])
  const [selectedPayableIds, setSelectedPayableIds] = useState<string[]>([])
  const [bulkReviewOpen, setBulkReviewOpen] = useState(false)
  const [bulkClassificationOpen, setBulkClassificationOpen] = useState(false)
  const [restoreReviewFocusId, setRestoreReviewFocusId] = useState<string | null>(null)
  const [reviewNotice, setReviewNotice] = useState('')
  const reviewStatusRef = useRef<HTMLParagraphElement>(null)
  const selectAllFiscalRef = useRef<HTMLInputElement>(null)
  const selectAllPayableRef = useRef<HTMLInputElement>(null)
  const bulkRequestKeyRef = useRef(idempotencyKey('web-sri-purchase-bulk-review'))
  const bulkClassificationKeyRef = useRef(idempotencyKey('web-payable-bulk-classification'))
  useEffect(() => {
    if (reviewNotice) reviewStatusRef.current?.focus()
  }, [reviewNotice])
  useEffect(() => {
    if (!reviewingFiscalId && restoreReviewFocusId) {
      document.querySelector<HTMLButtonElement>(`[data-sri-review-id="${restoreReviewFocusId}"]`)?.focus()
      setRestoreReviewFocusId(null)
    }
  }, [restoreReviewFocusId, reviewingFiscalId])
  const [groupByClassificationId, setGroupByClassificationId] = useState('')
  const deferredQuery = useDeferredValue(query.trim().toLocaleLowerCase())
  // El filtro se resuelve en el servidor para no depender de una lista que
  // podría venir acotada.
  const payablesQuery = useQuery({
    queryKey: ['payables', partyFilterId ?? 'todos'],
    queryFn: () => apiRequest<Payable[]>(token, partyFilterId ? `/payables?partyId=${partyFilterId}` : '/payables'),
  })
  const fiscalQuery = useQuery({ queryKey: ['tax', 'purchases'], queryFn: () => apiRequest<PurchaseDocument[]>(token, '/tax/purchases') })
  const classificationsQuery = useQuery({ queryKey: ['analytic-classifications'], queryFn: () => apiRequest<AnalyticClassification[]>(token, '/analytic-classifications') })
  const payables = (payablesQuery.data ?? []).filter((item) => {
    const statusMatches = statusFilter === 'ALL' || (statusFilter === 'OPEN' && ['OPEN', 'PARTIAL'].includes(item.status)) || (statusFilter === 'SETTLED' && item.status === 'SETTLED')
    const taxMatches = taxFilter === 'ALL'
      || (taxFilter === 'DECLARABLE' && item.taxClassification === 'DEDUCTIBLE_CONFIRMED')
      || (taxFilter === 'NON_DEDUCTIBLE' && item.taxClassification === 'NON_DEDUCTIBLE')
      || (taxFilter === 'PENDING' && item.taxClassification === 'DEDUCTIBLE_PENDING_REVIEW')
    const internalMatches = internalFilter === 'ALL'
      || item.internalClassification === internalFilter
    const haystack = `${item.supplierName ?? ''} ${item.description} ${item.documentNumber ?? ''} ${item.category}`.toLocaleLowerCase()
    return statusMatches && taxMatches && internalMatches && (!deferredQuery || haystack.includes(deferredQuery))
  })
  const linkedFiscalIds = new Set((payablesQuery.data ?? []).map((item) => item.fiscalDocumentId).filter(Boolean))
  const fiscalById = new Map((fiscalQuery.data ?? []).map((item) => [item.id, item]))
  const payableByFiscalId = new Map<string, Payable>((payablesQuery.data ?? []).filter((item) => item.fiscalDocumentId).map((item) => [item.fiscalDocumentId as string, item]))
  const pendingFiscal = (fiscalQuery.data ?? []).filter((item) => {
    if (!linkedFiscalIds.has(item.id)) return true
    return payableByFiscalId.get(item.id)?.taxClassification === 'DEDUCTIBLE_PENDING_REVIEW'
  })
  const selectablePendingFiscal = pendingFiscal.slice(0, 100)
  const reviewingFiscal = pendingFiscal.find((item) => item.id === reviewingFiscalId)
  const selectedFiscalDocuments = pendingFiscal.filter((item) => selectedFiscalIds.includes(item.id))
  const selectedFiscalTotal = selectedFiscalDocuments.reduce((sum, item) => sum + Number(item.total), 0)
  useEffect(() => {
    if (selectAllFiscalRef.current) {
      selectAllFiscalRef.current.indeterminate = selectedFiscalDocuments.length > 0 && selectedFiscalDocuments.length < selectablePendingFiscal.length
    }
  }, [selectablePendingFiscal.length, selectedFiscalDocuments.length])
  const selectablePayables = payables.slice(0, 100)
  const selectedPayables = (payablesQuery.data ?? []).filter((item) => selectedPayableIds.includes(item.id))
  const selectedPayableTotal = selectedPayables.reduce((sum, item) => sum + Number(item.total), 0)
  useEffect(() => {
    if (selectAllPayableRef.current) {
      const visibleSelectedCount = selectablePayables.filter((item) => selectedPayableIds.includes(item.id)).length
      selectAllPayableRef.current.indeterminate = visibleSelectedCount > 0 && visibleSelectedCount < selectablePayables.length
    }
  }, [selectablePayables, selectedPayableIds])
  const selectedPayable = (payablesQuery.data ?? []).find((item) => item.id === selectedPayableId)
  const selectedClassification = (classificationsQuery.data ?? []).find((item) => item.id === groupByClassificationId)
  const payableGroups = groupByClassificationId
    ? Array.from(payables.reduce((groups, payable) => {
      const assignment = (payable.analyticAssignments ?? []).find((item) => item.classificationId === groupByClassificationId)
      const key = assignment ? assignment.path.map((part) => part.name).join(' / ') : 'Sin clasificar'
      groups.set(key, [...(groups.get(key) ?? []), payable])
      return groups
    }, new Map<string, Payable[]>()).entries())
    // Sin agrupación por tag, se agrupa por mes: una lista corrida de compras
    // de varios meses obliga a leer fecha por fecha para ubicarse.
    : Array.from(payables.reduce((groups, payable) => {
      const key = payable.issueDate.slice(0, 7)
      groups.set(key, [...(groups.get(key) ?? []), payable])
      return groups
    }, new Map<string, Payable[]>()).entries())
      .sort(([izquierda], [derecha]) => derecha.localeCompare(izquierda))
      .map(([mes, items]) => [
        new Date(`${mes}-01T12:00:00`).toLocaleDateString('es-EC', { month: 'long', year: 'numeric' }),
        items,
      ] as [string, Payable[]])

  if (isCreating) return <PurchaseForm token={token} draft={draft} onCancel={() => { setIsCreating(false); setDraft(undefined) }} onSaved={() => { setIsCreating(false); setDraft(undefined); void queryClient.invalidateQueries({ queryKey: ['payables'] }) }} />

  function clearFiscalSelection() {
    setSelectedFiscalIds([])
    setBulkReviewOpen(false)
    bulkRequestKeyRef.current = idempotencyKey('web-sri-purchase-bulk-review')
  }

  function toggleFiscalSelection(documentId: string) {
    setSelectedFiscalIds((current) => current.includes(documentId)
      ? current.filter((id) => id !== documentId)
      : current.length < 100 ? [...current, documentId] : current)
  }

  function clearPayableSelection() {
    setSelectedPayableIds([])
    setBulkClassificationOpen(false)
    bulkClassificationKeyRef.current = idempotencyKey('web-payable-bulk-classification')
  }

  function togglePayableSelection(payableId: string) {
    setSelectedPayableIds((current) => current.includes(payableId)
      ? current.filter((id) => id !== payableId)
      : current.length < 100 ? [...current, payableId] : current)
  }

  function handleBulkResult(result: BulkReviewResult) {
    const failedIds = result.items.filter((item) => item.status === 'FAILED').map((item) => item.documentId)
    const resultParts = [
      result.reviewedCount ? `${result.reviewedCount} ${result.reviewedCount === 1 ? 'compra revisada' : 'compras revisadas'}` : '',
      result.protectedCount ? `${result.protectedCount} ${result.protectedCount === 1 ? 'conservó' : 'conservaron'} pago y tags` : '',
      result.skippedCount ? `${result.skippedCount} ya ${result.skippedCount === 1 ? 'estaba revisada' : 'estaban revisadas'}` : '',
      failedIds.length ? `${failedIds.length} no ${failedIds.length === 1 ? 'pudo' : 'pudieron'} guardarse` : '',
    ].filter(Boolean)
    setBulkReviewOpen(false)
    setSelectedFiscalIds(failedIds)
    setReviewNotice(`${resultParts.join(' · ')}.`)
    if (!failedIds.length) bulkRequestKeyRef.current = idempotencyKey('web-sri-purchase-bulk-review')
    void queryClient.invalidateQueries({ queryKey: ['payables'] })
  }

  function handleBulkClassificationResult(result: BulkClassificationResult) {
    const failedIds = result.items.filter((item) => item.status === 'FAILED').map((item) => item.payableId)
    const failedReasons = Array.from(result.items.reduce((groups, item) => {
      if (item.status === 'FAILED') groups.set(item.detail, (groups.get(item.detail) ?? 0) + 1)
      return groups
    }, new Map<string, number>()).entries()).map(([detail, count]) => `${count} ${count === 1 ? 'compra' : 'compras'}: ${detail}`)
    const fiscalProtectedCount = result.fiscalProtectedCount ?? 0
    setBulkClassificationOpen(false)
    setSelectedPayableIds(failedIds)
    setReviewNotice([
      result.updatedCount ? `${result.updatedCount} ${result.updatedCount === 1 ? 'compra actualizada' : 'compras actualizadas'}` : '',
      fiscalProtectedCount ? `${fiscalProtectedCount} ${fiscalProtectedCount === 1 ? 'conservó' : 'conservaron'} el uso tributario porque el periodo ya está declarado` : '',
      ...failedReasons,
    ].filter(Boolean).join(' · ') + '.')
    // El siguiente intento ya es otro lote cuando conservamos solo los fallidos.
    // La clave actual queda reservada al request que acaba de responder.
    bulkClassificationKeyRef.current = idempotencyKey('web-payable-bulk-classification')
    void queryClient.invalidateQueries({ queryKey: ['payables'] })
    void queryClient.invalidateQueries({ queryKey: ['tax', 'dashboard'] })
  }

  return (
    <>
      <ErpPageHeader eyebrow="Compras y gastos" title="Compras" subtitle="Conserva lo declarado al SRI y marca aparte qué gastos son reales para tu control por proyectos." actions={<ErpButton variant="secondary" onClick={() => setIsCreating(true)}>Nueva compra manual</ErpButton>} />
      {view === 'SRI' && selectedFiscalDocuments.length ? <ErpToolbar ariaLabel="Acciones para compras SRI seleccionadas">
        <p className="purchase-bulk-selection-status" role="status"><strong>{selectedFiscalDocuments.length} {selectedFiscalDocuments.length === 1 ? 'seleccionada' : 'seleccionadas'}</strong><span>Total ${formatAmount(selectedFiscalTotal)}</span></p>
        <ErpButton variant="ghost" onClick={clearFiscalSelection}>Cancelar selección</ErpButton>
        <ErpButton data-sri-bulk-review variant="primary" onClick={() => setBulkReviewOpen(true)}>Revisar selección</ErpButton>
      </ErpToolbar> : view === 'LIST' && selectedPayables.length ? <ErpToolbar ariaLabel="Acciones para compras seleccionadas">
        <p className="purchase-bulk-selection-status" role="status"><strong>{selectedPayables.length} {selectedPayables.length === 1 ? 'seleccionada' : 'seleccionadas'}</strong><span>Total ${formatAmount(selectedPayableTotal)}</span></p>
        <ErpButton variant="ghost" onClick={clearPayableSelection}>Cancelar selección</ErpButton>
        <ErpButton data-payable-bulk-edit variant="primary" onClick={() => { setEditingTagsFor(null); setBulkClassificationOpen(true) }}>Editar selección</ErpButton>
      </ErpToolbar> : <ErpToolbar ariaLabel="Vistas de compras">
        <ErpTabs
          ariaLabel="Secciones de compras"
          value={view}
          onChange={(destino) => { setView(destino); setReviewingFiscalId(null); clearFiscalSelection(); clearPayableSelection(); setReviewNotice('') }}
          tabs={[
            { value: 'SRI', label: `Pendientes SRI (${pendingFiscal.length})` },
            { value: 'LIST', label: 'Compras' },
            { value: 'BANK', label: 'Banco' },
          ]}
        />
        {view === 'LIST' ? <label className="search-field"><span>Estado</span><select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as typeof statusFilter)}><option value="ALL">Todas</option><option value="OPEN">Por pagar</option><option value="SETTLED">Pagadas</option></select></label> : null}
        {view === 'LIST' ? <label className="search-field"><span>Uso fiscal</span><select value={taxFilter} onChange={(event) => setTaxFilter(event.target.value as typeof taxFilter)}><option value="ALL">Todos</option><option value="DECLARABLE">Para declaración</option><option value="NON_DEDUCTIBLE">No deducibles</option><option value="PENDING">Pendientes de revisar</option></select></label> : null}
        {view === 'LIST' ? <label className="search-field"><span>Control interno</span><select value={internalFilter} onChange={(event) => setInternalFilter(event.target.value as typeof internalFilter)}><option value="ALL">Todos</option><option value="REAL">Gastos reales</option><option value="DECLARATION_ONLY">Solo tributarios</option><option value="PENDING">Pendientes de revisar</option></select></label> : null}
        {view === 'LIST' ? <label className="search-field"><span>Buscar compra</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Proveedor, concepto o número" /></label> : null}
        {view === 'LIST' && (classificationsQuery.data ?? []).length ? <label className="search-field"><span>Agrupar por tag</span><select value={groupByClassificationId} onChange={(event) => setGroupByClassificationId(event.target.value)}><option value="">Sin agrupación</option>{classificationsQuery.data?.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label> : null}
      </ErpToolbar>}
      {reviewNotice ? <p className="purchase-review-status" role="status" tabIndex={-1} ref={reviewStatusRef}>{reviewNotice}</p> : null}
      {view === 'SRI' ? bulkReviewOpen ? (
        <SriBulkReview
          token={token}
          documents={selectedFiscalDocuments}
          payablesByFiscalId={payableByFiscalId}
          requestKey={bulkRequestKeyRef.current}
          onResult={handleBulkResult}
          onCancel={() => {
            setBulkReviewOpen(false)
            requestAnimationFrame(() => document.querySelector<HTMLButtonElement>('[data-sri-bulk-review]')?.focus())
          }}
        />
      ) : reviewingFiscal ? <SriPurchaseReview token={token} document={reviewingFiscal} payable={payableByFiscalId.get(reviewingFiscal.id)} onCancel={() => { setRestoreReviewFocusId(reviewingFiscal.id); setReviewingFiscalId(null) }} onSaved={() => { setReviewingFiscalId(null); setReviewNotice('Compra SRI revisada y guardada.'); void queryClient.invalidateQueries({ queryKey: ['payables'] }) }} /> : (
        <ErpPanel title="Pendientes de revisar desde el SRI" count={pendingFiscal.length}>
          <p className="fine-print">Selecciona varias compras para aplicar la misma revisión o abre una para tratarla por separado.</p>
          {pendingFiscal.length > 100 ? <p className="fine-print">Puedes procesar hasta 100 comprobantes por lote.</p> : null}
          {fiscalQuery.isPending ? <p aria-busy="true">Cargando comprobantes SRI…</p> : null}
          {fiscalQuery.error ? <p className="form-error" role="alert">{fiscalQuery.error.message}</p> : null}
          {pendingFiscal.length ? <><div className="purchase-sri-select-all"><label className="purchase-sri-checkbox"><input ref={selectAllFiscalRef} type="checkbox" checked={selectedFiscalDocuments.length > 0 && selectedFiscalDocuments.length === selectablePendingFiscal.length} onChange={(event) => setSelectedFiscalIds(event.target.checked ? selectablePendingFiscal.map((item) => item.id) : [])} aria-label={`Seleccionar los ${selectablePendingFiscal.length} comprobantes visibles`} /></label><span>Seleccionar visibles</span></div><div className="table-wrap" tabIndex={0} aria-label="Comprobantes SRI pendientes de revisar">
            <table className="erp-responsive-table purchase-table purchase-sri-table">
              <thead><tr>
                <th className="purchase-sri-select-cell" scope="col"><span className="sr-only">Selección</span></th>
                <th scope="col">Documento</th><th scope="col">Proveedor</th><th scope="col">Fecha</th><th scope="col">Total</th><th scope="col">Evidencia</th><th scope="col">Acción</th>
              </tr></thead>
              <tbody>{pendingFiscal.map((item) => {
                const selected = selectedFiscalIds.includes(item.id)
                const selectable = selected || selectedFiscalIds.length < 100
                return <tr key={item.id} aria-selected={selected}>
                  <td className="purchase-sri-select-cell"><label className="purchase-sri-checkbox"><input type="checkbox" checked={selected} disabled={!selectable} onChange={() => toggleFiscalSelection(item.id)} aria-label={`Seleccionar factura ${item.documentNumber ?? 'sin número'} de ${item.supplierName ?? 'proveedor sin nombre'}`} /></label></td>
                  <td className="purchase-sri-document-cell">{item.documentNumber ?? 'Sin número'}</td>
                  <td className="purchase-sri-supplier-cell">{item.supplierName ?? 'Sin proveedor'}</td>
                  <td className="purchase-sri-date-cell">{item.issueDate}</td>
                  <td className="purchase-sri-total-cell">${formatAmount(item.total)}</td>
                  <td className="purchase-sri-evidence-cell"><ErpStatusBadge tone={item.isPreliminary ? 'warning' : 'success'}>{item.isPreliminary ? 'Preliminar' : 'XML confirmado'}</ErpStatusBadge></td>
                  <td className="purchase-sri-action-cell"><ErpButton className="purchase-sri-review-button" data-sri-review-id={item.id} variant="secondary" onClick={() => { clearFiscalSelection(); setReviewNotice(''); setReviewingFiscalId(item.id) }}>Revisar</ErpButton></td>
                </tr>
              })}</tbody>
            </table>
          </div></> : !fiscalQuery.isPending ? <ErpEmptyState title="Todo revisado" description="No quedan comprobantes del SRI pendientes de clasificar." /> : null}
        </ErpPanel>
      ) : null}
      {view === 'BANK' ? <><BankReconciliation token={token} payables={payablesQuery.data ?? []} onCreateExpense={(expenseDraft) => { setDraft(expenseDraft); setIsCreating(true) }} /><RuleManager token={token} /></> : null}
      
      {view === 'LIST' ? bulkClassificationOpen ? (
        <PayableBulkClassificationEditor
          token={token}
          payables={selectedPayables}
          requestKey={bulkClassificationKeyRef.current}
          onSaved={handleBulkClassificationResult}
          onCancel={() => {
            setBulkClassificationOpen(false)
            requestAnimationFrame(() => document.querySelector<HTMLButtonElement>('[data-payable-bulk-edit]')?.focus())
          }}
        />
      ) : (
        <ErpPanel title={selectedClassification ? `Compras por ${selectedClassification.name}` : 'Cuentas por pagar'} count={payables.length}>
          {payablesQuery.isPending ? <p aria-busy="true">Cargando compras…</p> : null}
          {payablesQuery.error ? <p className="form-error" role="alert">{payablesQuery.error.message}</p> : null}
          {payables.length ? <><div className="purchase-sri-select-all"><label className="purchase-sri-checkbox"><input ref={selectAllPayableRef} type="checkbox" checked={selectablePayables.length > 0 && selectablePayables.every((item) => selectedPayableIds.includes(item.id))} onChange={(event) => setSelectedPayableIds(event.target.checked ? selectablePayables.map((item) => item.id) : [])} aria-label={`Seleccionar las ${selectablePayables.length} compras visibles`} /></label><span>Seleccionar visibles para editar en lote</span></div><div className="table-wrap" tabIndex={0} aria-label="Listado de compras y cuentas por pagar"><table className="erp-responsive-table purchase-table purchase-list-table"><thead><tr><th className="purchase-sri-select-cell" scope="col"><span className="sr-only">Selección</span></th><th>Compra</th><th>Proveedor</th><th>Fecha</th><th>Total</th><th>Saldo</th><th>Desglose IVA</th><th>Estado</th><th>Tributario</th><th>Interno</th><th>Clasificaciones</th><th>Acciones</th></tr></thead>{payableGroups.map(([group, items]) => <tbody key={group}><tr><th colSpan={12} scope="colgroup" className="purchase-group-heading">{group} · {items.length} compra{items.length === 1 ? '' : 's'} · ${formatAmount(items.reduce((total, item) => total + Number(item.total), 0))}</th></tr>{items.map((item) => { const fiscal = item.fiscalDocumentId ? fiscalById.get(item.fiscalDocumentId) : undefined; const assignments = item.analyticAssignments ?? []; const editing = editingTagsFor === item.id; const selected = selectedPayableIds.includes(item.id); const selectable = selected || selectedPayableIds.length < 100; const fiscalLabel = item.taxClassification === 'DEDUCTIBLE_CONFIRMED' ? 'Para declaración' : item.taxClassification === 'NON_DEDUCTIBLE' ? 'No deducible' : 'Pendiente de revisar'; const internalLabel = item.internalClassification === 'REAL' ? 'Gasto real' : item.internalClassification === 'DECLARATION_ONLY' ? 'Solo tributario' : 'Pendiente de revisar'; return <Fragment key={item.id}><tr aria-selected={selected}><td className="purchase-sri-select-cell"><label className="purchase-sri-checkbox"><input type="checkbox" checked={selected} disabled={!selectable} onChange={() => togglePayableSelection(item.id)} aria-label={`Seleccionar compra ${item.documentNumber ?? item.description}`} /></label></td><td><strong>{item.description}</strong><small>{item.category} · {item.documentNumber ?? 'Sin factura'}</small></td><td>{item.supplierName ?? 'Sin proveedor'}</td><td>{item.issueDate}<small>{item.dueDate ? `Vence ${item.dueDate}` : 'Sin fecha acordada'}</small></td><td>${formatAmount(item.total)}</td><td>${formatAmount(item.openAmount)}</td><td>{fiscal?.taxes.length ? <ul className="purchase-tax-breakdown">{fiscal.taxes.map((tax, index) => <li key={`${tax.sriTaxCode}-${index}`}><span>{tax.taxBracket === 'GRAVADO' ? 'Gravado' : tax.taxBracket} {formatAmount(tax.rate)}%</span><strong>${formatAmount(tax.taxAmount)}</strong><small>Base ${formatAmount(tax.baseAmount)}</small></li>)}</ul> : 'Sin desglose confirmado'}</td><td>{statusBadge(item)}</td><td><ErpStatusBadge tone={item.taxClassification === 'DEDUCTIBLE_CONFIRMED' ? 'success' : 'warning'}>{fiscalLabel}</ErpStatusBadge></td><td><ErpStatusBadge tone={item.internalClassification === 'REAL' ? 'success' : 'warning'}>{internalLabel}</ErpStatusBadge></td><td>{assignments.length ? assignments.map((assignment) => <small key={assignment.classificationId}>{assignment.classificationName}: {assignment.path.map((part) => part.name).join(' / ')}</small>) : '—'}</td><td><ErpButton variant="secondary" onClick={() => setEditingTagsFor(editing ? null : item.id)}>{editing ? 'Cerrar edición' : 'Editar clasificación'}</ErpButton><ErpButton variant="ghost" onClick={() => setSelectedPayableId(item.id)}>{item.status === 'OPEN' || item.status === 'PARTIAL' ? 'Pagar' : 'Historial'}</ErpButton></td></tr>{editing ? <tr><td colSpan={12}><PayableClassificationEditor token={token} payable={item} onSaved={() => { setEditingTagsFor(null); setReviewNotice('Clasificación de la compra actualizada.'); void queryClient.invalidateQueries({ queryKey: ['payables'] }); void queryClient.invalidateQueries({ queryKey: ['tax', 'dashboard'] }) }} /></td></tr> : null}</Fragment> })}</tbody>)}</table></div></> : !payablesQuery.isPending ? <ErpEmptyState title="No hay compras en esta vista" description="Cambia los filtros o registra una nueva compra." /> : null}
        </ErpPanel>
      ) : null}
      {selectedPayable && view === 'LIST' ? <PayableDetail token={token} payable={selectedPayable} onClose={() => setSelectedPayableId(null)} /> : null}
    </>
  )
}
