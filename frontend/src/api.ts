export type TenantContext = {
  tenantId: string
  ruc: string
  name: string
  roles: string[]
  scopes: string[]
  automationWritesEnabled: boolean
  defaultPaymentTermsDays: number
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
  paymentTermsDays?: number | null
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
  installments?: Array<{ dueDate: string; amount: string }>
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
  fileName: string
}

export type FiscalSettings = {
  sriEnvironment: '1' | '2'
  certificateConfigured: boolean
  certificateFingerprintSha256?: string | null
  certificateSubject?: string | null
  certificateValidFrom?: string | null
  certificateValidTo?: string | null
  certificateUploadedAt?: string | null
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
  message?: string | null
  scheduledAt?: string | null
}

export type CollectionPolicy = {
  enabled: boolean
  offsetsDays: number[]
  channels: Array<'EMAIL' | 'WHATSAPP'>
  sendHour: number
  emailTemplateId: string
  whatsappTemplateId: string
  updatedAt: string
}

export type InvoicePreview = {
  lines: Array<{
    description: string
    quantity: string
    unitPrice: string
    discount: string
    baseAmount: string
    taxCode: string
    taxRate: string
    taxAmount: string
    total: string
  }>
  subtotal: string
  taxTotal: string
  total: string
}

// CRM Types

export type LeadStatus = 'NEW' | 'CONTACTED' | 'QUALIFIED' | 'PROPOSAL' | 'NEGOTIATION' | 'WON' | 'LOST'

export type Lead = {
  id: string
  partyId: string
  title: string
  productId?: string | null
  party: Pick<Party, 'id' | 'name' | 'email' | 'phone' | 'address'>
  product?: Pick<Product, 'id' | 'name' | 'code'> | null
  owner?: { id: string; displayName: string; email: string } | null
  status: LeadStatus
  source?: string | null
  ownerUserId?: string | null
  score: number
  hotness: 'COLD' | 'WARM' | 'HOT'
  estimatedValue?: string | null
  expectedCloseDate?: string | null
  createdAt: string
  updatedAt: string
  tenantId: string
}

export type LeadCreate = {
  partyId: string
  title: string
  productId?: string | null
  status?: LeadStatus
  source?: string | null
  ownerUserId?: string | null
  score?: number
  hotness?: 'COLD' | 'WARM' | 'HOT'
  estimatedValue?: string | null
  expectedCloseDate?: string | null
}

export type LeadUpdate = {
  title?: string | null
  productId?: string | null
  status?: LeadStatus | null
  source?: string | null
  ownerUserId?: string | null
  score?: number | null
  hotness?: 'COLD' | 'WARM' | 'HOT' | null
  estimatedValue?: string | null
  expectedCloseDate?: string | null
}

export type LeadWithPartyCreate = {
  partyName: string
  partyIdentificationType: 'RUC' | 'CEDULA' | 'PASSPORT' | 'FINAL_CONSUMER'
  partyIdentificationNumber: string
  partyEmail?: string | null
  partyPhone?: string | null
  partyAddress?: string | null
  title: string
  productId?: string | null
  status?: LeadStatus
  source?: string | null
  score?: number
  hotness?: 'COLD' | 'WARM' | 'HOT'
  estimatedValue?: string | null
  expectedCloseDate?: string | null
}

export type LeadActivity = {
  id: string
  leadId: string
  activityType: 'CALL' | 'EMAIL' | 'WHATSAPP' | 'MEETING' | 'NOTE' | 'TASK'
  subject: string
  description?: string | null
  outcome: 'POSITIVE' | 'NEUTRAL' | 'NEGATIVE' | 'PENDING'
  reminderDate?: string | null
  reminderCompleted: boolean
  actorId: string
  sourceEmailId?: string | null
  sourceEmailThreadId?: string | null
  createdAt: string
  updatedAt: string
  tenantId: string
}

export type LeadActivityCreate = {
  leadId: string
  activityType: 'CALL' | 'EMAIL' | 'MEETING' | 'NOTE' | 'TASK'
  subject: string
  description?: string | null
  outcome?: 'POSITIVE' | 'NEUTRAL' | 'NEGATIVE' | 'PENDING'
  reminderDate?: string | null
  reminderCompleted?: boolean
}

export type LeadStatusUpdate = {
  newStatus: LeadStatus
  reason?: string | null
}

export type GmailSyncResult = {
  messagesProcessed: number
  activitiesCreated: number
  leadsMatched: number
  errors: string[]
  lastSyncAt: string
}

export type IntegrationStatus = {
  googleConnected: boolean
  googleEmail?: string | null
  googleLastSyncAt?: string | null
  googleConfigurationAvailable: boolean
  whatsappConnected: boolean
  whatsappPhone?: string | null
}

export type OrganizationProfile = {
  tenantId: string
  name: string
  ruc: string
  defaultPaymentTermsDays: number
}

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

const apiUrl = import.meta.env.VITE_API_URL ?? '/api/v1'

type TokenProvider = (forceRefresh?: boolean) => Promise<string>

let tokenProvider: TokenProvider | null = null

export function configureApiTokenProvider(provider: TokenProvider | null) {
  tokenProvider = provider
}

export async function apiRequest<T>(
  token: string,
  path: string,
  init?: RequestInit,
): Promise<T> {
  async function send(forceRefresh = false) {
    const accessToken = tokenProvider ? await tokenProvider(forceRefresh) : token
    const headers = new Headers(init?.headers)
    headers.set('Authorization', `Bearer ${accessToken}`)
    if (!(init?.body instanceof FormData) && !headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json')
    }
    return fetch(`${apiUrl}${path}`, { ...init, headers })
  }

  let response = await send()
  if (response.status === 401 && tokenProvider) {
    response = await send(true)
  }

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
