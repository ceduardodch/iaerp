import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  useDeferredValue,
  useState,
  type FormEvent,
} from 'react'
import {
  apiRequest,
  idempotencyKey,
  type EmissionPoint,
  type Establishment,
  type InvoiceLineInput,
  type InvoicePreview,
  type Party,
  type Product,
  type SalesDocument,
  type TaxCategory,
} from '../../api'
import { FormGrid, FormProgress, FormSection } from './index'
import { formatAmount } from '../../utils/format'

type DraftLine = {
  key: string
  productId: string
  description: string
  quantity: string
  unitPrice: string
  discount: string
  taxCode: string
}

type NewInvoiceFormProps = {
  token: string
  customers: Party[]
  products: Product[]
  taxes: TaxCategory[]
  establishments: Establishment[]
  emissionPoints: EmissionPoint[]
  defaultPaymentTermsDays: number
  onCreated: (invoiceId: string) => void
  onCancel: () => void
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

export function NewInvoiceFormVertical({
  token,
  customers,
  products,
  taxes,
  establishments,
  emissionPoints,
  defaultPaymentTermsDays,
  onCreated,
  onCancel,
}: NewInvoiceFormProps) {
  const queryClient = useQueryClient()
  const [currentStep] = useState<1 | 2 | 3>(1)
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

  const availableEmissionPoints = emissionPoints.filter(
    (point) => point.establishmentId === establishmentId,
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
    enabled: currentStep === 3 && lines.every((line) => Boolean(
      line.description && line.taxCode && Number(line.quantity) > 0 && Number(line.unitPrice) >= 0,
    )),
  })

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
      onCreated(invoice.id)
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

  const steps: Array<{ title: string; status: 'completed' | 'current' | 'pending' }> = [
    { title: 'Cliente', status: currentStep === 1 ? 'current' : currentStep > 1 ? 'completed' : 'pending' },
    { title: 'Fecha y pago', status: currentStep === 2 ? 'current' : currentStep > 2 ? 'completed' : 'pending' },
    { title: 'Líneas', status: currentStep === 3 ? 'current' : 'pending' },
  ]

  return (
    <>
      <FormProgress steps={steps} />
      <form onSubmit={submit}>
        <FormSection
          title="Cliente"
          description="Selecciona el cliente para esta factura"
          defaultExpanded={currentStep === 1}
        >
          <label>
            Cliente
            <select
              value={customerId}
              onChange={(event) => {
                const nextId = event.target.value
                setCustomerId(nextId)
                setPaymentTermsDays(customers.find((customer) => customer.id === nextId)?.paymentTermsDays ?? defaultPaymentTermsDays)
              }}
              required
            >
              {customers.map((customer) => (
                <option key={customer.id} value={customer.id}>{customer.name}</option>
              ))}
            </select>
          </label>
        </FormSection>

        <FormSection
          title="Fecha y condiciones de pago"
          description="Configura la emisión y términos de pago"
          defaultExpanded={currentStep === 2}
        >
          <FormGrid columns={2}>
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
            <label>
              Fecha de emisión
              <input type="date" value={issueDate} onChange={(event) => setIssueDate(event.target.value)} required />
            </label>
            <label>
              Condición de pago
              <select value={String(paymentTermsDays)} onChange={(event) => setPaymentTermsDays(Number(event.target.value))}>
                <option value="0">Contado</option>
                <option value="15">15 días</option>
                <option value="30">30 días</option>
                <option value="45">45 días</option>
                <option value="60">60 días</option>
                <option value="90">90 días</option>
              </select>
            </label>
            <label style={{ gridColumn: '1 / -1' }}>
              Vencimiento
              <input value={addDays(issueDate, paymentTermsDays)} readOnly />
            </label>
          </FormGrid>
        </FormSection>

        <FormSection
          title="Líneas de factura"
          description="Agrega productos y servicios con sus impuestos"
          defaultExpanded={currentStep === 3}
        >
          <fieldset className="invoice-lines">
            <legend>Líneas</legend>
            {lines.map((line, index) => (
              <div className="invoice-line-row" key={line.key}>
                <label>
                  {`Producto ${index + 1}`}
                  <select
                    value={line.productId}
                    onChange={(event) => onProductChange(line.key, event.target.value)}
                    required
                  >
                    <option value="" disabled>Seleccionar…</option>
                    {products.map((product) => {
                      const tax = taxes.find((item) => item.id === product.taxCategoryId)
                      return <option key={product.id} value={product.id}>{product.name}{tax ? ` · IVA ${formatAmount(tax.rate)}%` : ''}</option>
                    })}
                  </select>
                </label>
                <FormGrid columns={3}>
                  <label>
                    Cantidad
                    <input
                      type="number"
                      min="0.000001"
                      step="0.000001"
                      value={line.quantity}
                      onChange={(event) => updateLine(line.key, { quantity: event.target.value })}
                      required
                    />
                  </label>
                  <label>
                    Precio unitario
                    <input
                      type="number"
                      min="0"
                      step="0.000001"
                      value={line.unitPrice}
                      onChange={(event) => updateLine(line.key, { unitPrice: event.target.value })}
                      required
                    />
                  </label>
                  <label>
                    Descuento
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={line.discount}
                      onChange={(event) => updateLine(line.key, { discount: event.target.value })}
                    />
                  </label>
                </FormGrid>
                {lines.length > 1 ? (
                  <button
                    type="button"
                    className="erp-button erp-button-ghost"
                    onClick={() => setLines((current) => current.filter((item) => item.key !== line.key))}
                  >
                    Quitar línea
                  </button>
                ) : null}
              </div>
            ))}
            <button
              type="button"
              className="erp-button erp-button-secondary"
              onClick={() => setLines((current) => [...current, emptyDraftLine()])}
            >
              + Agregar línea
            </button>
          </fieldset>
        </FormSection>

        <section className="invoice-live-preview" aria-live="polite">
          <p className="section-number">Cálculo en vivo</p>
          {previewQuery.isPending ? <small>Validando con el servidor…</small> : null}
          {previewQuery.error ? <p className="form-error">{previewQuery.error.message}</p> : null}
          {previewQuery.data ? (
            <dl className="invoice-totals">
              <div><dt>Subtotal</dt><dd>{formatAmount(previewQuery.data.subtotal)}</dd></div>
              <div><dt>IVA total</dt><dd>{formatAmount(previewQuery.data.taxTotal)}</dd></div>
              <div className="invoice-grand-total"><dt>Total</dt><dd>{formatAmount(previewQuery.data.total)}</dd></div>
            </dl>
          ) : <p className="fine-print">Completa la primera línea para calcular los valores.</p>}
        </section>

        <div className="erp-form-actions">
          <button type="button" className="erp-button erp-button-secondary" onClick={onCancel}>Cancelar</button>
          <button type="submit" className="erp-button erp-button-primary" disabled={createDraft.isPending}>
            {createDraft.isPending ? 'Creando…' : 'Crear factura'}
          </button>
        </div>
      </form>
    </>
  )
}
