export type TenantContext = {
  tenantId: string
  ruc: string
  name: string
  roles: string[]
  scopes: string[]
  automationWritesEnabled: boolean
}

export type Party = {
  id: string
  name: string
  identificationType: 'RUC' | 'CEDULA' | 'PASSPORT' | 'FINAL_CONSUMER'
  identificationNumber: string
  roles: Array<'CUSTOMER' | 'SUPPLIER'>
  email?: string
  phone?: string
  address?: string
}

export type Product = {
  id: string
  name: string
  code?: string
  unitPrice: string
  taxCategoryId: string
}

export type TaxCategory = {
  id: string
  sriCode: string
  name: string
  rate: string
  active: boolean
}

export type Establishment = {
  id: string
  code: string
  name: string
  address: string
  active: boolean
}

export type EmissionPoint = {
  id: string
  establishmentId: string
  code: string
  active: boolean
}

export type SalesDocumentStatus =
  | 'DRAFT'
  | 'READY'
  | 'SIGNED'
  | 'RECEIVED'
  | 'PENDING_AUTHORIZATION'
  | 'AUTHORIZED'
  | 'REJECTED'
  | 'FAILED'
  | 'VOIDED'

export type SalesDocumentLine = {
  id: string
  lineNumber: number
  productId: string | null
  description: string
  quantity: string
  unitPrice: string
  discount: string
  baseAmount: string
  taxCode: string
  taxRate: string
  taxAmount: string
}

export type SriTransmission = {
  status: string
  message?: string | null
  authorizationNumber?: string | null
  lastAttemptAt?: string | null
}

export type SalesDocument = {
  id: string
  type: 'INVOICE' | 'CREDIT_NOTE'
  status: SalesDocumentStatus
  sequential: string
  issueDate: string
  accessKey: string | null
  subtotal: string
  tax: string
  total: string
  currency: string
  partyId: string
  establishmentId: string
  emissionPointId: string
  establishmentCode?: string
  emissionPointCode?: string
  reason: string | null
  lines: SalesDocumentLine[]
  sriTransmission?: SriTransmission | null
}

export type InvoiceLineInput = {
  productId?: string | null
  description: string
  quantity: string
  unitPrice: string
  discount?: string
  taxCode: string
}

export type InvoiceInput = {
  customerId: string
  establishmentId: string
  emissionPointId: string
  issueDate: string
  installments: Array<{ dueDate: string; amount: string }>
  lines: InvoiceLineInput[]
}

export type CreditNoteInput = {
  invoiceId: string
  reason: string
  lines: InvoiceLineInput[]
}

export type Operation = {
  operationId: string
  status: 'ACCEPTED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'BLOCKED'
  correlationId: string
  createdAt: string
  expiresAt: string
  result?: Record<string, unknown> | null
}

export type DocumentArtifact = {
  id: string
  artifactType: 'xml-signed' | 'ride-pdf'
  sha256: string
  version: number
  createdAt: string
}

export type ArtifactDownload = {
  downloadUrl: string
  expiresInSeconds: number
}

export type AccountItemStatus = 'OPEN' | 'PARTIAL' | 'OVERDUE' | 'SETTLED' | 'VOIDED'

export type AccountItem = {
  id: string
  partyId: string
  status: AccountItemStatus
  originalAmount: string
  openAmount: string
  currency: string
  dueDate?: string | null
}

export type PaymentMethod = 'TRANSFER' | 'CHECK' | 'CASH' | 'CARD' | 'OTHER'

export type RetentionInput = {
  kind: 'RETENTION_IVA' | 'RETENTION_RENTA' | 'OTHER'
  amount: string
  reason: string
  documentReference?: string | null
}

export type DiscountInput = {
  amount: string
  reason: string
}

export type PaymentInput = {
  cashAmount: string
  paymentDate: string
  method?: PaymentMethod | null
  reference?: string | null
  retentions: RetentionInput[]
  discounts: DiscountInput[]
}

export type ReminderInput = {
  channel: 'EMAIL' | 'WHATSAPP'
  templateId: string
}

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

const apiUrl = import.meta.env.VITE_API_URL ?? '/api/v1'

export async function apiRequest<T>(
  token: string,
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(`${apiUrl}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  })

  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as
      | { detail?: string; message?: string }
      | null
    throw new ApiError(
      body?.detail ?? body?.message ?? 'No se pudo completar la solicitud',
      response.status,
    )
  }
  return response.json() as Promise<T>
}

export function idempotencyKey(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`
}
