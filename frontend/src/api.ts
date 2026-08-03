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
  expectedIvaWithholdingRate?: string | null
  expectedIncomeWithholdingRate?: string | null
  withholdingProfileValidFrom?: string | null
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
  validFrom: string
  validTo?: string | null
  active: boolean
}

export type TaxCategoryInput = {
  sriCode: string
  name: string
  rate: string
  validFrom: string
}

export type CommercialContract = {
  id: string
  partyId: string
  contractNumber: string
  title: string
  serviceType: 'FIXED_MONTHLY' | 'AWS_MONTHLY' | 'MILESTONE' | 'ONE_OFF' | 'ACCESSORY'
  sourceLeadId: string | null
  parentContractId: string | null
  reportRequired: boolean
  collectionEnabled: boolean
  status: 'DRAFT' | 'PENDING_SIGNATURE' | 'SIGNED' | 'ACTIVE' | 'EXPIRED' | 'SUPERSEDED' | 'CANCELLED'
  currentVersionId: string | null
}

export type ContractVersion = {
  id: string
  contractId: string
  versionNumber: number
  status: CommercialContract['status']
  validFrom: string
  validTo: string | null
  paymentTermsDays: number
  renewalNoticeDays: number | null
  pricingRules: Array<Record<string, unknown>>
  amendsVersionId: string | null
  signedAt: string | null
  sentAt: string | null
  sentArtifactSha256: string | null
  gmailThreadId: string | null
  replyDetectedAt: string | null
  signedArtifactSha256: string | null
  signaturePrecheckStatus: 'SIGNATURE_FOUND' | 'SIGNATURE_NOT_FOUND' | 'CHECK_FAILED' | null
  signaturePrecheckDetails: Record<string, unknown> | null
  firmaecConfirmedAt: string | null
}

export type ContractEmailSync = {
  messagesChecked: number
  replyDetected: boolean
  signedPdfReceived: boolean
  duplicateIgnored: boolean
}

export type AwsConsumptionCut = {
  id: string
  partyId: string
  periodStart: string
  periodEnd: string
  source: 'AWS_COST_EXPLORER' | 'CSV_UPLOAD' | 'XLSX_UPLOAD'
  status: 'IMPORTED' | 'RECONCILED' | 'REVIEWED' | 'REJECTED' | 'BILLED'
  totalCost: string
  currency: 'USD'
  evidenceSha256: string | null
}

export type BillingProposal = {
  id: string
  partyId: string
  issueDate: string
  totalAmount: string
  contractVersionId: string | null
  awsConsumptionCutId: string | null
  salesDocumentId: string | null
  exceptionReason: string | null
  commercialSnapshot: Record<string, unknown>
  periodStart: string | null
  periodEnd: string | null
  pricingRuleIndex: number
  billingType: CommercialContract['serviceType']
  reportRequired: boolean
  collectionEnabled: boolean
  reportSha256: string | null
  reportFileName: string | null
  reportApprovedAt: string | null
  status: 'DRAFT' | 'READY_FOR_REVIEW' | 'CONVERTED' | 'CANCELLED'
}

export type ContractArtifactDownload = {
  downloadUrl: string
  expiresInSeconds: number
  fileName: string
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
  | 'NOT_AUTHORIZED'
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
  collectionStatus?: AccountItemStatus | null
  installments?: Array<{ dueDate: string; amount: string }>
  retentionTotal: string
  collectionEnabled: boolean
  commercialSnapshot?: Record<string, unknown> | null
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
  collectionEnabled?: boolean
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

export type InvoiceEmailResult = {
  messageId: string
  recipient: string
  attachmentNames: string[]
}

export type InvoiceEmailPreview = {
  recipient?: string | null
  subject: string
  message: string
  attachmentNames: string[]
  dueDate: string
  paymentTermsDays: number
}

export type InvoiceEmailTemplate = {
  subject: string
  body: string
  availableVariables: string[]
}

export type FiscalSettings = {
  sriEnvironment: '1' | '2'
  electronicInvoicingProviderName: string
  electronicInvoicingProviderRuc: string
  certificateConfigured: boolean
  rideLogoConfigured: boolean
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
  invoiceSequential?: string | null
  status: AccountItemStatus
  originalAmount: string
  openAmount: string
  currency: string
  dueDate?: string | null
}

export type ReceivableMovement = {
  id: string
  receivableId: string
  installmentId: string
  movementType: 'PAYMENT' | 'RETENTION' | 'DISCOUNT' | 'CREDIT_NOTE' | 'REVERSAL'
  amount: string
  supportReference?: string | null
  reversedMovementId?: string | null
  actorId: string
  effectiveDate?: string | null
  createdAt: string
}

export type PaymentMethod = 'TRANSFER' | 'CHECK' | 'CASH' | 'CARD' | 'OTHER'

export type RetentionInput = {
  kind: 'RETENTION_IVA' | 'RETENTION_RENTA' | 'OTHER'
  amount: string
  reason: string
  documentReference: string
}

export type RetentionXmlPreview = {
  authorizationNumber: string
  supportingDocument: string
  retentions: Array<{
    kind: RetentionInput['kind']
    amount: string
    baseAmount: string
    rate: string
    sriRetentionCode: string
  }>
}

export type RetentionBatch = {
  items: Array<{
    fileName: string
    receivableId?: string | null
    authorizationNumber?: string | null
    supportingDocument?: string | null
    invoiceSequential?: string | null
    issueDate?: string | null
    total: string
    status: 'MATCHED' | 'REVIEW_REQUIRED'
    detail: string
  }>
}

export type BankStatementImport = {
  period: string
  fileName: string
  sourceSha256: string
  totalRows: number
  creditRows: number
  outsidePeriodCreditCount: number
  matchedCount: number
  unmatchedCreditCount: number
  ignoredDebitCount: number
  alreadyImportedCount: number
  manualCorrectionCount: number
  matches: Array<{
    transactionId: string
    paymentDate: string
    reference: string
    description: string
    amount: string
    receivableId: string
    invoiceSequential: string
    originalAmount: string
    retentionTotal: string
    replacesManualPayment: boolean
    status: 'MATCHED' | 'REGISTERED'
    detail: string
  }>
  manualCorrections: Array<{
    transactionId: string
    paymentDate: string
    reference: string
    amount: string
    targetReceivableId: string
    targetInvoiceSequential: string
    manualReceivableId: string
    manualInvoiceSequential: string
    manualMovementId: string
    status: 'CORRECTION_REQUIRED' | 'CORRECTED'
    detail: string
  }>
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

export type ReceivableDueDateUpdate = {
  dueDate: string
  reason: string
}

export type ReminderInput = {
  channel: 'EMAIL' | 'WHATSAPP'
  /**
   * Etiqueta del envío en el historial, no la fuente del texto: el cuerpo sale
   * de la plantilla del tenant (`CollectionPolicy`). Opcional, igual que en el
   * backend, que cae a "payment_reminder" si no llega.
   */
  templateId?: string | null
  message?: string | null
  scheduledAt?: string | null
}

/**
 * Desglose del cobro (`GET /receivables/collections`).
 *
 * `cashAmount` es dinero que entró; `retentionAmount` es valor que el cliente
 * retuvo y que se recupera ante el SRI, no en caja. `creditAmount` agrupa notas
 * de crédito y descuentos: bajan la deuda sin cobro.
 */
export type CollectionsBreakdown = {
  fromDate: string | null
  toDate: string | null
  cashAmount: string
  cashCount: number
  retentionAmount: string
  retentionCount: number
  creditAmount: string
  creditCount: number
  settledAmount: string
  retentionShare: string
}

export type CollectionPolicy = {
  enabled: boolean
  offsetsDays: number[]
  channels: Array<'EMAIL' | 'WHATSAPP'>
  sendHour: number
  emailTemplateId: string
  whatsappTemplateId: string
  emailSubject: string
  emailBody: string
  paymentInstructions: string
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
  whatsappMetaConnected: boolean
  whatsappEvolutionConnected: boolean
  whatsappEvolutionPhone?: string | null
  evolutionConfigurationAvailable: boolean
  whatsappCrmProvider: 'META' | 'EVOLUTION'
  whatsappCollectionsProvider: 'META' | 'EVOLUTION'
}

export type EvolutionWhatsAppIntegration = {
  connected: boolean
  displayPhoneNumber?: string | null
  webhookUrl: string
  qrCode?: string | null
  qrExpiresInSeconds?: number | null
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
      body?.detail ??
        body?.message ??
        `No se pudo completar la solicitud (HTTP ${response.status})`,
      response.status,
    )
  }
  return response.json() as Promise<T>
}

export function idempotencyKey(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`
}

// Módulo tributario (ADR 0012)
export type TaxPeriod = {
  id: string
  year: number
  month: number
  obligationType: 'IVA' | 'ATS' | 'RDEP' | 'RENTA' | 'ADI'
  status:
    | 'PENDIENTE_DESCARGA'
    | 'EVIDENCIA_INCOMPLETA'
    | 'LISTO_REVISAR'
    | 'LISTO_DECLARAR'
    | 'DECLARADO'
  dueDate?: string | null
  notes?: string | null
}

export type TaxEvidence = {
  id: string
  taxPeriodId?: string | null
  filename: string
  fileType: 'XML' | 'TXT' | 'PDF' | 'ZIP' | 'OTHER'
  sha256: string
  sizeBytes: number
  origin: string
  uploadedAt: string
  processingNotes?: string | null
  duplicate: boolean
}

export type TaxIngestResult = {
  created: number
  updated: number
  skipped: number
  preliminary: number
  notes: string[]
}

export type TaxFiscalDocument = {
  id: string
  direction: 'EMITIDO' | 'RECIBIDO'
  docType: string
  accessKey?: string | null
  issueDate: string
  counterpartyIdentification?: string | null
  counterpartyName?: string | null
  subtotal: string
  taxTotal: string
  total: string
  paymentMethods?: string[]
  isPreliminary: boolean
}

export type TaxFormField = {
  fieldCode: string
  label: string
  sourceKey: string
  /** true = el usuario copia el valor al formulario; false = el SRI lo autocalcula. */
  isPaste: boolean
  /** Formateado como `1234.56`. */
  value: string
  documentCount: number
  /** true si el código aún debe confirmarse contra el formulario vigente. */
  needsReview: boolean
}

export type TaxIvaSummary = {
  periodId: string
  year: number
  month: number
  status: string
  documentCount: number
  isPreliminary: boolean
  preliminaryReasons: string[]
  amounts: Record<string, string>
  fields: TaxFormField[]
}

export type TaxAnnex = {
  id: string
  taxPeriodId: string
  annexType: 'ATS' | 'RDEP' | 'ADI'
  status: 'GENERADO' | 'VALIDADO' | 'RECHAZADO' | 'ENTREGADO'
  version: number
  xmlSha256?: string | null
  downloadUrl?: string | null
}

export type TaxOwnDocumentsResult = {
  created: number
  updated: number
  /** Comprobantes propios que no se pudieron importar; el motivo va en `notes`. */
  skipped: number
  notes: string[]
}

export type TaxBulkItem = {
  filename: string
  /** Nombre del ZIP del que salió, si vino dentro de uno. */
  sourceArchive?: string | null
  status: 'OK' | 'DUPLICADO' | 'ERROR'
  docType?: string | null
  direction?: 'EMITIDO' | 'RECIBIDO' | null
  accessKey?: string | null
  issueDate?: string | null
  /** Periodo destino, calculado con la fecha real de emisión. */
  periodYear?: number | null
  periodMonth?: number | null
  counterpartyIdentification?: string | null
  counterpartyName?: string | null
  total?: string | null
  isRetention: boolean
  error?: string | null
}

export type TaxBulkResult = {
  items: TaxBulkItem[]
  created: number
  updated: number
  duplicates: number
  errors: number
  /** Comprobantes por periodo destino: {"2025-11": 4} */
  periods: Record<string, number>
  notes: string[]
  retentionCount: number
  retentionsApplied: number
}

export type TaxDossierRetention = {
  accessKey?: string | null
  issueDate: string
  issuerName?: string | null
  ivaAmount: string
  incomeTaxAmount: string
}

export type TaxDossierMovement = {
  movementType: 'PAYMENT' | 'RETENTION' | 'DISCOUNT' | 'CREDIT_NOTE' | 'REVERSAL'
  amount: string
  occurredAt: string
  reference?: string | null
  /** Presente cuando el cobro vino de la conciliación del extracto bancario. */
  bankReference?: string | null
}

/** Historia del comprobante: retenciones, cobros y saldo. */
export type TaxDocumentDossier = {
  documentId: string
  docType: string
  direction: 'EMITIDO' | 'RECIBIDO'
  accessKey?: string | null
  issueDate: string
  counterpartyName?: string | null
  total: string
  paymentMethods: string[]
  retentions: TaxDossierRetention[]
  movements: TaxDossierMovement[]
  receivableId?: string | null
  receivableStatus?: string | null
  retainedIva: string
  retainedIncomeTax: string
  collectedAmount: string
  outstandingAmount: string
  /** total − retención IVA − retención renta */
  expectedNet: string
  netDifference: string
  notes: string[]
}
