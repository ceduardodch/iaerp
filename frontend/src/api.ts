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

export type AnalyticClassification = {
  id: string
  code: string
  name: string
  maxDepth: number
  active: boolean
}

export type AnalyticClassificationValue = {
  id: string
  classificationId: string
  parentId?: string | null
  code: string
  name: string
  color?: string | null
  active: boolean
}

export type AnalyticAssignment = {
  classificationId: string
  classificationCode: string
  classificationName: string
  valueId: string
  path: Array<{ code: string; name: string }>
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
  | 'HISTORICAL_ISSUED'
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
  authorizationNumber?: string | null
  authorizedAt?: string | null
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
  analyticAssignments: AnalyticAssignment[]
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
  analyticValueIds?: string[]
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
  senderAddress?: string | null
  senderName?: string | null
  attachmentNames: string[]
}

export type InvoiceEmailPreview = {
  recipient?: string | null
  senderAddress?: string | null
  senderName?: string | null
  subject: string
  message: string
  attachmentNames: string[]
  dueDate: string
  paymentTermsDays: number
}

export type InvoiceEmailTemplate = {
  subject: string
  body: string
  fromAddress?: string | null
  fromName?: string | null
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
  issueDate?: string | null
  daysSinceInvoice?: number | null
  dueDate?: string | null
  aging?: { bucket: AgingBucket; daysOverdue: number } | null
  collectionEnabled: boolean
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
  accountMasked: string
  totalRows: number
  creditRows: number
  debitRows: number
  outsidePeriodCreditCount: number
  outsidePeriodDebitCount: number
  matchedCount: number
  unmatchedCreditCount: number
  ignoredDebitCount: number
  payableMatchedCount: number
  unmatchedDebitCount: number
  ruleSuggestionCount: number
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
  debitMatches: Array<{
    transactionId: string
    paymentDate: string
    reference: string
    description: string
    amount: string
    payableId: string
    supplierName?: string | null
    documentNumber?: string | null
    payableTotal: string
    allocatedAmount: string
    linksExistingPayment: boolean
    status: 'MATCHED' | 'REGISTERED' | 'EVIDENCE_LINKED'
    detail: string
  }>
  debitSuggestions: Array<{
    transactionId: string
    paymentDate: string
    reference: string
    description: string
    amount: string
    classification: 'UNCLASSIFIED' | 'EXPENSE_CANDIDATE' | 'BANK_FEE' | 'BANK_TAX' | 'INTERNAL_TRANSFER' | 'CARD_SETTLEMENT'
    ruleId?: string | null
    ruleName?: string | null
    suggestedCategory?: string | null
    suggestedSupplierName?: string | null
    suggestedTaxClassification?: string | null
    detail: string
  }>
}

export type PayableStatus = 'OPEN' | 'PARTIAL' | 'SETTLED' | 'VOIDED'

export type Payable = {
  id: string
  supplierId?: string | null
  supplierName?: string | null
  fiscalDocumentId?: string | null
  description: string
  category: string
  documentType: 'INVOICE' | 'LIQUIDATION' | 'DEBIT_NOTE' | 'OTHER'
  documentNumber?: string | null
  issueDate: string
  dueDate: string
  total: string
  openAmount: string
  currency: 'USD'
  status: PayableStatus
  taxClassification: 'DEDUCTIBLE_PENDING_REVIEW' | 'DEDUCTIBLE_CONFIRMED' | 'NON_DEDUCTIBLE'
  internalClassification: 'PENDING_REVIEW' | 'REAL' | 'DECLARATION_ONLY'
  evidenceStatus: 'NONE' | 'ATTACHED' | 'PRELIMINARY' | 'FISCAL_XML'
  supportReference?: string | null
  analyticAssignments: AnalyticAssignment[]
}

export type PayableMovement = {
  id: string
  payableId: string
  installmentId: string
  movementType: 'PAYMENT' | 'RETENTION' | 'CREDIT_NOTE' | 'REVERSAL'
  amount: string
  effectiveDate: string
  method?: 'TRANSFER' | 'CHECK' | 'CASH' | 'CARD' | 'OTHER' | null
  supportReference?: string | null
  reversedMovementId?: string | null
  actorId: string
  createdAt: string
}

export type ExpenseRule = {
  id: string
  name: string
  descriptionPattern: string
  accountLast4?: string | null
  amountMin?: string | null
  amountMax?: string | null
  category: string
  supplierName?: string | null
  taxClassification: Payable['taxClassification']
  active: boolean
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
  resendReason?: string | null
}

export type CollectionContactInput = {
  channel: 'CALL' | 'EMAIL' | 'WHATSAPP' | 'NOTE'
  outcome: 'PENDING' | 'CONTACTED' | 'PROMISE_TO_PAY' | 'NO_RESPONSE' | 'WRONG_CONTACT'
  note?: string | null
  occurredAt?: string | null
}

export type CollectionHistoryEntry = {
  id: string
  kind: 'REMINDER' | 'CONTACT'
  occurredAt: string
  channel: string
  outcome: string
  note: string | null
  recipient: string | null
  deliveryStatus: string | null
  deliveredAt: string | null
  readAt: string | null
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

/** Tramos de antigüedad de cartera, en orden: el orden es parte del dato. */
export type AgingBucket = 'CURRENT' | '1-15' | '16-30' | '31-60' | '61-90' | '90+'

export type AgingSummary = {
  asOf: string
  buckets: Array<{ bucket: AgingBucket; total: string; installmentCount: number }>
  byParty: Array<{ partyId: string; bucket: AgingBucket; total: string; installmentCount: number }>
}

/**
 * Serie mensual de cobro (`GET /receivables/collections/monthly`).
 *
 * Siempre trae todos los meses del rango, con cero donde no hubo cobro: una
 * serie con huecos dibujaría una tendencia falsa.
 */
export type MonthlyCollection = {
  year: number
  month: number
  cashAmount: string
  retentionAmount: string
  settledAmount: string
}

export type CollectionsHistory = {
  months: MonthlyCollection[]
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
  sourceExternalId?: string | null
  campaignId?: string | null
  campaignName?: string | null
  adId?: string | null
  utmSource?: string | null
  utmMedium?: string | null
  utmCampaign?: string | null
  utmContent?: string | null
  consentCapturedAt?: string | null
  consentTextVersion?: string | null
  campaignVariantId?: string | null
  qualificationStatus: 'UNREVIEWED' | 'QUALIFIED' | 'DISQUALIFIED'
  qualifiedAt?: string | null
  qualifiedBy?: string | null
  companyName?: string | null
  jobTitle?: string | null
  usesAws?: boolean | null
  decisionAuthority?: boolean | null
  qualificationReason?: string | null
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
  partyIdentificationNumber?: string | null
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

/**
 * Envío real por Gmail/WhatsApp. A diferencia de `LeadActivityCreate` —que
 * solo deja constancia en el historial— esto sí despacha el mensaje.
 * `followUpDays` agenda el recordatorio; el servidor calcula la fecha.
 */
export type LeadMessageCreate = {
  channel: 'EMAIL' | 'WHATSAPP'
  subject?: string | null
  message: string
  templateId?: string | null
  followUpDays?: number | null
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

/**
 * Bandeja de acción (`GET /crm/action-queue`): candidatos a WhatsApp de
 * cobranza vencida + prospección de leads nuevos, agregados en un solo
 * lugar. Es de solo lectura -- el envío real sigue pasando por
 * `POST /receivables/{id}/reminders` y `POST /crm/leads/{id}/messages`.
 */
export type ActionQueueCollectionCandidate = {
  receivableId: string
  partyId: string
  partyName: string
  phone: string
  openAmount: string
  daysOverdue: number
  lastReminderAt?: string | null
  suggestedMessage: string
}

export type ActionQueueProspectingCandidate = {
  leadId: string
  partyId: string
  partyName: string
  phone: string
  createdAt: string
  lastActivityAt?: string | null
  suggestedMessage: string
}

export type ActionQueueRead = {
  collections: ActionQueueCollectionCandidate[]
  prospecting: ActionQueueProspectingCandidate[]
}

/**
 * Fallo operativo terminal (`GET /ops/failures`, `POST
 * /ops/failures/{id}/retry`), espejo camelCase de
 * `app/schemas/platform.py::OpsFailureRead`. `correlationId` y
 * `aggregate*` vienen aplanados desde el `payload` del worker que lo
 * originó y pueden faltar en datos viejos o malformados.
 *
 * `classification` es el resultado de `classify_failure()` en el backend
 * (lista blanca por `event_type`, default deny): el panel de Incidencias lo
 * usa para decidir si ofrece el botón de reintento, sin duplicar esa lista
 * blanca aquí.
 */
export type OpsFailureStatus = 'OPEN' | 'RESOLVED'
export type OpsFailureClassification = 'AUTO_RETRY' | 'NEEDS_HUMAN'

export type OpsFailure = {
  id: string
  sourceType: string
  sourceId: string
  eventType: string
  error: string
  attempts: number
  status: OpsFailureStatus
  classification: OpsFailureClassification
  correlationId?: string | null
  aggregateType?: string | null
  aggregateId?: string | null
  createdAt: string
  resolvedAt?: string | null
}

export type EvolutionWhatsAppIntegration = {
  connected: boolean
  displayPhoneNumber?: string | null
  webhookUrl: string
  qrCode?: string | null
  qrExpiresInSeconds?: number | null
}

export type MetaAdsIntegration = {
  connected: boolean
  adAccountId?: string | null
  pageId?: string | null
  instagramActorId?: string | null
  defaultLeadFormId?: string | null
  accountCurrency?: string | null
  accountTimezone?: string | null
  webhookUrl: string
}

export type SocialCampaign = {
  id: string
  tenantId: string
  provider: 'META'
  name: string
  status: 'DRAFT' | 'PREPARING' | 'PREPARED' | 'ACTIVATING' | 'ACTIVE' | 'PAUSING' | 'PAUSED' | 'ERROR'
  dailyBudget: string
  currency?: string | null
  ageMin: number
  ageMax: number
  countries: string[]
  primaryText: string
  headline: string
  description?: string | null
  leadFormId?: string | null
  creativeSha256?: string | null
  externalCampaignId?: string | null
  externalAdsetId?: string | null
  externalCreativeId?: string | null
  externalAdId?: string | null
  approvedAt?: string | null
  activatedAt?: string | null
  pausedAt?: string | null
  lastError?: string | null
  createdAt: string
  updatedAt: string
}

export type SocialCampaignPolicy = {
  activationEnabled: boolean
  dailyBudgetLimit: string
  activeDailyBudget: string
}

export type SocialCampaignVariant = {
  id: string
  campaignId: string
  tenantId: string
  key: string
  name: string
  angle?: string | null
  position: number
  primaryText: string
  headline: string
  description?: string | null
  creativeSha256?: string | null
  externalCreativeId?: string | null
  externalAdId?: string | null
  createdAt: string
  updatedAt: string
}

export type SocialCampaignVariantDecision = {
  variant: SocialCampaignVariant
  currency?: string | null
  spend: string
  impressions: number
  clicks: number
  leads: number
  qualifiedLeads: number
  ctr?: string | null
  cpl?: string | null
  costPerQualifiedLead?: string | null
}

export type SocialCampaignInsights = {
  campaignId: string
  syncedDays: Array<{
    variantId: string
    metricDate: string
    externalAdId: string
    currency: string
    spend: string
    impressions: number
    clicks: number
    leads: number
  }>
  variants: SocialCampaignVariantDecision[]
}

export type OrganizationProfile = {
  tenantId: string
  name: string
  ruc: string
  defaultPaymentTermsDays: number
}

export type PayrollEmployee = {
  id: string
  fullName: string
  identificationNumber: string
  position?: string | null
  sueldoMensual: string
  fechaIngreso: string
  fechaSalida?: string | null
  active: boolean
  decimoTerceroMensualizado: boolean
  decimoCuartoMensualizado: boolean
  fondosReservaMensualizados: boolean
}

export type PayrollEmployeeInput = {
  fullName: string
  identificationNumber: string
  position?: string | null
  sueldoMensual: string
  fechaIngreso: string
  decimoTerceroMensualizado: boolean
  decimoCuartoMensualizado: boolean
  fondosReservaMensualizados: boolean
}

export type PayrollEmployeeTerminateInput = {
  fechaSalida: string
}

export type PayrollPeriodStatus = 'DRAFT' | 'APPROVED'

export type PayrollPeriod = {
  id: string
  anio: number
  mes: number
  status: PayrollPeriodStatus
}

export type PayrollPeriodDraftInput = {
  anio: number
  mes: number
}

export type PayrollEntry = {
  id: string
  periodId: string
  employeeId: string
  diasTrabajados: number
  imponible: string
  decimoTercero: string
  decimoCuarto: string
  fondosReserva: string
  totalIngresos: string
  aporteIess: string
  totalDescuentos: string
  liquido: string
  sbuAplicado: string
  tasaIessAplicada: string
  tasaFondosAplicada: string
}

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

function apiErrorMessage(body: unknown, status: number): string {
  if (!body || typeof body !== 'object') {
    return `No se pudo completar la solicitud (HTTP ${status})`
  }
  const errorBody = body as { detail?: unknown; message?: unknown }
  if (typeof errorBody.detail === 'string') return errorBody.detail
  if (typeof errorBody.message === 'string') return errorBody.message
  if (Array.isArray(errorBody.detail)) {
    const messages = errorBody.detail.flatMap((item) => {
      if (!item || typeof item !== 'object') return []
      const validation = item as { loc?: unknown; msg?: unknown }
      if (typeof validation.msg !== 'string') return []
      const location = Array.isArray(validation.loc) ? validation.loc.at(-1) : null
      return [typeof location === 'string' ? `${location}: ${validation.msg}` : validation.msg]
    })
    if (messages.length) return messages.join('. ')
  }
  return `No se pudo completar la solicitud (HTTP ${status})`
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
    const body = await response.json().catch(() => null) as unknown
    throw new ApiError(apiErrorMessage(body, response.status), response.status)
  }
  return response.json() as Promise<T>
}

export function idempotencyKey(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`
}

/** Tamaño de página; el backend acota en `LIST_LEADS_MAX_LIMIT` (200). */
const LEADS_PAGE_SIZE = 200
/** Techo de seguridad: un backend que devolviera páginas llenas para siempre
 *  colgaría la pantalla. Con 3 vueltas ya se cubren 600 leads. */
const LEADS_MAX_PAGES = 3

/**
 * Trae todos los leads recorriendo las páginas hasta agotarlas.
 *
 * `GET /crm/leads` devolvía como mucho 100 y quien lo consumía pedía una sola
 * vez, así que el tablero ocultaba el pipeline a partir de ahí y el dashboard
 * calculaba sus indicadores sobre una lista truncada, sin ningún aviso.
 */
export async function fetchAllLeads(token: string, query = ''): Promise<Lead[]> {
  const leads: Lead[] = []
  for (let page = 0; page < LEADS_MAX_PAGES; page += 1) {
    const params = new URLSearchParams(query)
    params.set('limit', String(LEADS_PAGE_SIZE))
    params.set('offset', String(page * LEADS_PAGE_SIZE))
    const batch = await apiRequest<Lead[]>(token, `/crm/leads?${params}`)
    leads.push(...batch)
    if (batch.length < LEADS_PAGE_SIZE) break
  }
  return leads
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

export type TaxXmlRecoveryJob = {
  id: string
  taxPeriodId: string
  status: 'QUEUED' | 'RUNNING' | 'COMPLETED'
  totalCount: number
  processedCount: number
  recoveredCount: number
  unavailableCount: number
  failedCount: number
  items: Array<{ documentId: string; status: 'PENDING' | 'RECOVERED' | 'UNAVAILABLE' | 'FAILED' }>
  startedAt?: string | null
  completedAt?: string | null
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
  analyticAssignments: AnalyticAssignment[]
}

export type PurchaseTaxLine = {
  sriTaxCode: string
  taxBracket: 'GRAVADO' | 'TARIFA_CERO' | 'EXENTO' | 'NO_OBJETO'
  rate: string
  baseAmount: string
  taxAmount: string
}

export type PurchaseDocument = {
  id: string
  docType: 'FACTURA' | 'NOTA_CREDITO' | 'NOTA_DEBITO' | 'LIQUIDACION'
  accessKey?: string | null
  issueDate: string
  documentNumber?: string | null
  supplierIdentification?: string | null
  supplierName?: string | null
  subtotal: string
  taxTotal: string
  total: string
  paymentMethods: string[]
  isPreliminary: boolean
  taxes: PurchaseTaxLine[]
}

export type MonthlySalesTrend = {
  year: number
  month: number
  total: string
  invoiceCount: number
  creditNoteCount: number
}

export type CurrentMonthTax = {
  year: number
  month: number
  authorizedSalesTotal: string
  authorizedSalesCount: number
  evidencedSalesTotal: string
  evidencedSalesCount: number
  purchasesTotal: string
  purchaseCount: number
  ivaGenerated: string
  ivaCredit: string
  retainedIva: string
  ivaPayable: string
  ivaCreditBalance: string
  isPreliminary: boolean
  preliminaryReasons: string[]
  needsAccountingReview: boolean
}

export type DashboardTax = {
  trend: MonthlySalesTrend[]
  currentMonth: CurrentMonthTax
  annual: AnnualFiscalTax
}

export type AnnualFiscalMonth = {
  month: number
  status: string
  isDeclared: boolean
  salesBase: string
  deductiblePurchasesBase: string
  incomeTaxWithheld: string
}

export type AnnualFiscalTax = {
  year: number
  salesBase: string
  deductiblePurchasesBase: string
  nonDeductiblePurchasesBase: string
  pendingReviewPurchasesBase: string
  internalRealExpensesTotal: string
  internalRealExpenseCount: number
  internalDeclarationOnlyExpensesTotal: string
  internalDeclarationOnlyExpenseCount: number
  internalPendingExpensesTotal: string
  internalPendingExpenseCount: number
  resultBeforeAdjustments: string
  incomeTaxWithheld: string
  ivaWithheld: string
  declaredSalesBase: string
  declaredDeductiblePurchasesBase: string
  declaredResultBeforeAdjustments: string
  declaredIncomeTaxWithheld: string
  declaredMonthCount: number
  lastDeclaredMonth?: number | null
  estimatedIncomeTaxRate: string | null
  declaredEstimatedIncomeTax: string | null
  projectedEstimatedIncomeTax: string | null
  declaredEstimatedBalance: string | null
  projectedEstimatedBalance: string | null
  estimateReason: string
  pendingReviewDocumentCount: number
  preliminaryDocumentCount: number
  refundStatus: 'REVIEW_AT_ANNUAL_CLOSE' | 'NO_RECORDED_CREDIT'
  refundMessage: string
  limitations: string[]
  months: AnnualFiscalMonth[]
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
  pendingPurchaseCount: number
  pendingPurchaseSubtotal: string
  pendingPurchaseTaxTotal: string
  pendingPurchaseTotal: string
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
