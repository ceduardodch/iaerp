import { Fragment, useDeferredValue, useState, type FormEvent } from 'react'
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
  ErpToolbar,
} from '../erp'
import { AnalyticClassificationPicker } from '../analytics/AnalyticClassificationPicker'
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
  const save = useMutation({
    mutationFn: () => apiRequest<Payable>(token, `/payables/${payable.id}/analytic-assignments`, {
      method: 'PUT',
      headers: { 'Idempotency-Key': idempotencyKey('web-payable-analytics') },
      body: JSON.stringify({ valueIds }),
    }),
    onSuccess: onSaved,
  })

  return <div className="purchase-tag-editor">
    <AnalyticClassificationPicker token={token} valueIds={valueIds} onChange={setValueIds} />
    {save.error ? <p className="form-error" role="alert">{save.error.message}</p> : null}
    <ErpButton variant="primary" onClick={() => save.mutate()} disabled={save.isPending}>{save.isPending ? 'Guardando…' : 'Guardar tags'}</ErpButton>
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

export function PurchasesPage({ token }: { token: string }) {
  const queryClient = useQueryClient()
  const [view, setView] = useState<'ALL' | 'OPEN' | 'SETTLED' | 'BANK' | 'RULES'>('ALL')
  const [query, setQuery] = useState('')
  const [isCreating, setIsCreating] = useState(false)
  const [draft, setDraft] = useState<ExpenseDraft | undefined>()
  const [selectedPayableId, setSelectedPayableId] = useState<string | null>(null)
  const [editingTagsFor, setEditingTagsFor] = useState<string | null>(null)
  const [groupByClassificationId, setGroupByClassificationId] = useState('')
  const deferredQuery = useDeferredValue(query.trim().toLocaleLowerCase())
  const payablesQuery = useQuery({ queryKey: ['payables'], queryFn: () => apiRequest<Payable[]>(token, '/payables') })
  const fiscalQuery = useQuery({ queryKey: ['tax', 'purchases'], queryFn: () => apiRequest<PurchaseDocument[]>(token, '/tax/purchases') })
  const classificationsQuery = useQuery({ queryKey: ['analytic-classifications'], queryFn: () => apiRequest<AnalyticClassification[]>(token, '/analytic-classifications') })
  const payables = (payablesQuery.data ?? []).filter((item) => {
    const statusMatches = view === 'ALL' || (view === 'OPEN' && ['OPEN', 'PARTIAL'].includes(item.status)) || (view === 'SETTLED' && item.status === 'SETTLED')
    const haystack = `${item.supplierName ?? ''} ${item.description} ${item.documentNumber ?? ''} ${item.category}`.toLocaleLowerCase()
    return statusMatches && (!deferredQuery || haystack.includes(deferredQuery))
  })
  const linkedFiscalIds = new Set((payablesQuery.data ?? []).map((item) => item.fiscalDocumentId).filter(Boolean))
  const fiscalById = new Map((fiscalQuery.data ?? []).map((item) => [item.id, item]))
  const unlinkedFiscal = (fiscalQuery.data ?? []).filter((item) => !linkedFiscalIds.has(item.id))
  const selectedPayable = (payablesQuery.data ?? []).find((item) => item.id === selectedPayableId)
  const selectedClassification = (classificationsQuery.data ?? []).find((item) => item.id === groupByClassificationId)
  const payableGroups = groupByClassificationId
    ? Array.from(payables.reduce((groups, payable) => {
      const assignment = (payable.analyticAssignments ?? []).find((item) => item.classificationId === groupByClassificationId)
      const key = assignment ? assignment.path.map((part) => part.name).join(' / ') : 'Sin clasificar'
      groups.set(key, [...(groups.get(key) ?? []), payable])
      return groups
    }, new Map<string, Payable[]>()).entries())
    : [['Todas las compras', payables] as [string, Payable[]]]

  if (isCreating) return <PurchaseForm token={token} draft={draft} onCancel={() => { setIsCreating(false); setDraft(undefined) }} onSaved={() => { setIsCreating(false); setDraft(undefined); void queryClient.invalidateQueries({ queryKey: ['payables'] }) }} />

  return (
    <>
      <ErpPageHeader eyebrow="Compras y gastos" title="Compras" subtitle="Registra gastos directos o por pagar, conserva el soporte fiscal y cruza sus pagos con el banco." actions={<ErpButton variant="primary" onClick={() => setIsCreating(true)}>Nueva compra</ErpButton>} />
      <ErpToolbar ariaLabel="Vistas de compras">
        {([['ALL', 'Todas'], ['OPEN', 'Por pagar'], ['SETTLED', 'Pagadas'], ['BANK', 'Conciliación bancaria'], ['RULES', 'Reglas']] as const).map(([value, label]) => <ErpButton key={value} variant={view === value ? 'primary' : 'ghost'} onClick={() => setView(value)}>{label}</ErpButton>)}
        {!['BANK', 'RULES'].includes(view) ? <label className="search-field"><span>Buscar compra</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Proveedor, concepto o número" /></label> : null}
        {!['BANK', 'RULES'].includes(view) && (classificationsQuery.data ?? []).length ? <label className="search-field"><span>Agrupar por tag</span><select value={groupByClassificationId} onChange={(event) => setGroupByClassificationId(event.target.value)}><option value="">Sin agrupación</option>{classificationsQuery.data?.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label> : null}
      </ErpToolbar>
      {view === 'BANK' ? <BankReconciliation token={token} payables={payablesQuery.data ?? []} onCreateExpense={(expenseDraft) => { setDraft(expenseDraft); setIsCreating(true) }} /> : null}
      {view === 'RULES' ? <RuleManager token={token} /> : null}
      {!['BANK', 'RULES'].includes(view) ? (
        <ErpPanel title={selectedClassification ? `Compras por ${selectedClassification.name}` : 'Cuentas por pagar'} count={payables.length}>
          {payablesQuery.isPending ? <p aria-busy="true">Cargando compras…</p> : null}
          {payablesQuery.error ? <p className="form-error" role="alert">{payablesQuery.error.message}</p> : null}
          {payables.length ? <div className="table-wrap" tabIndex={0} aria-label="Listado de compras y cuentas por pagar"><table className="erp-responsive-table purchase-table"><thead><tr><th>Compra</th><th>Proveedor</th><th>Fecha</th><th>Total</th><th>Saldo</th><th>Desglose IVA</th><th>Estado</th><th>Fiscal</th><th>Clasificaciones</th><th>Acciones</th></tr></thead>{payableGroups.map(([group, items]) => <tbody key={group}>{groupByClassificationId ? <tr><th colSpan={10} scope="colgroup">{group} · {items.length} compras</th></tr> : null}{items.map((item) => { const fiscal = item.fiscalDocumentId ? fiscalById.get(item.fiscalDocumentId) : undefined; const assignments = item.analyticAssignments ?? []; const editing = editingTagsFor === item.id; return <Fragment key={item.id}><tr><td><strong>{item.description}</strong><small>{item.category} · {item.documentNumber ?? 'Sin factura'}</small></td><td>{item.supplierName ?? 'Sin proveedor'}</td><td>{item.issueDate}<small>Vence {item.dueDate}</small></td><td>${formatAmount(item.total)}</td><td>${formatAmount(item.openAmount)}</td><td>{fiscal?.taxes.length ? <ul className="purchase-tax-breakdown">{fiscal.taxes.map((tax, index) => <li key={`${tax.sriTaxCode}-${index}`}><span>{tax.taxBracket === 'GRAVADO' ? 'Gravado' : tax.taxBracket} {formatAmount(tax.rate)}%</span><strong>${formatAmount(tax.taxAmount)}</strong><small>Base ${formatAmount(tax.baseAmount)}</small></li>)}</ul> : 'Sin desglose confirmado'}</td><td>{statusBadge(item)}</td><td><ErpStatusBadge tone={item.evidenceStatus === 'FISCAL_XML' ? 'success' : 'warning'}>{item.evidenceStatus === 'FISCAL_XML' ? 'XML confirmado' : item.taxClassification === 'NON_DEDUCTIBLE' ? 'No deducible' : 'Deducible · revisar'}</ErpStatusBadge></td><td>{assignments.length ? assignments.map((assignment) => <small key={assignment.classificationId}>{assignment.classificationName}: {assignment.path.map((part) => part.name).join(' / ')}</small>) : '—'}</td><td><ErpButton variant="secondary" onClick={() => setEditingTagsFor(editing ? null : item.id)}>{editing ? 'Cerrar tags' : 'Clasificar'}</ErpButton><ErpButton variant="ghost" onClick={() => setSelectedPayableId(item.id)}>{item.status === 'OPEN' || item.status === 'PARTIAL' ? 'Pagar' : 'Historial'}</ErpButton></td></tr>{editing ? <tr><td colSpan={10}><PayableClassificationEditor token={token} payable={item} onSaved={() => { setEditingTagsFor(null); void queryClient.invalidateQueries({ queryKey: ['payables'] }) }} /></td></tr> : null}</Fragment> })}</tbody>)}</table></div> : !payablesQuery.isPending ? <ErpEmptyState title="No hay compras en esta vista" description="Usa Nueva compra para registrar gasolina, servicios o una factura por pagar." /> : null}
        </ErpPanel>
      ) : null}
      {selectedPayable && !['BANK', 'RULES'].includes(view) ? <PayableDetail token={token} payable={selectedPayable} onClose={() => setSelectedPayableId(null)} /> : null}
      {view === 'ALL' && unlinkedFiscal.length ? <ErpPanel title="Documentos fiscales anteriores pendientes de enlazar" count={unlinkedFiscal.length}><p className="fine-print">Estos comprobantes ya existían en Tributario antes de CxP. Siguen visibles y no se duplican como gasto.</p><div className="table-wrap" tabIndex={0}><table className="erp-responsive-table purchase-table"><thead><tr><th>Documento</th><th>Proveedor</th><th>Fecha</th><th>Total</th><th>Evidencia</th></tr></thead><tbody>{unlinkedFiscal.map((item) => <tr key={item.id}><td>{item.documentNumber ?? 'Sin número'}</td><td>{item.supplierName ?? 'Sin proveedor'}</td><td>{item.issueDate}</td><td>${formatAmount(item.total)}</td><td><ErpStatusBadge tone={item.isPreliminary ? 'warning' : 'success'}>{item.isPreliminary ? 'Preliminar' : 'XML confirmado'}</ErpStatusBadge></td></tr>)}</tbody></table></div></ErpPanel> : null}
    </>
  )
}
