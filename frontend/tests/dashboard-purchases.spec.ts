import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { navigateToSection } from './navigation'

const dashboard = {
  trend: [
    { year: 2026, month: 6, total: '800.00', invoiceCount: 2, creditNoteCount: 0 },
    { year: 2026, month: 7, total: '2300.00', invoiceCount: 4, creditNoteCount: 1 },
    { year: 2026, month: 8, total: '590.26', invoiceCount: 1, creditNoteCount: 0 },
  ],
  currentMonth: {
    year: 2026,
    month: 8,
    authorizedSalesTotal: '590.26',
    authorizedSalesCount: 1,
    evidencedSalesTotal: '590.26',
    evidencedSalesCount: 1,
    purchasesTotal: '115.00',
    purchaseCount: 1,
    ivaGenerated: '76.99',
    ivaCredit: '15.00',
    retainedIva: '0.00',
    ivaPayable: '61.99',
    ivaCreditBalance: '0.00',
    isPreliminary: true,
    preliminaryReasons: ['El crédito de IVA debe validarse con el campo 564 y su respaldo contable.'],
    needsAccountingReview: true,
  },
}

const aging = [
  { bucket: 'CURRENT', total: '1200.00', installmentCount: 3 },
  { bucket: '1-15', total: '400.00', installmentCount: 1 },
  { bucket: '16-30', total: '250.00', installmentCount: 1 },
  { bucket: '31-60', total: '0.00', installmentCount: 0 },
  { bucket: '61-90', total: '0.00', installmentCount: 0 },
  { bucket: '90+', total: '900.00', installmentCount: 2 },
]

const collectionMonths = [
  { year: 2026, month: 6, cashAmount: '500.00', retentionAmount: '50.00', settledAmount: '550.00' },
  { year: 2026, month: 7, cashAmount: '700.00', retentionAmount: '100.00', settledAmount: '800.00' },
  { year: 2026, month: 8, cashAmount: '880.00', retentionAmount: '120.00', settledAmount: '1000.00' },
]

const purchases = [
  {
    id: '11111111-2222-4333-8444-555555555555',
    docType: 'FACTURA',
    accessKey: '0108202601123456789000120010010000001231234567819',
    issueDate: '2026-08-01',
    documentNumber: '001-001-000000123',
    supplierIdentification: '1234567890001',
    supplierName: 'PROVEEDOR DEMO CIA. LTDA.',
    subtotal: '100.00',
    taxTotal: '15.00',
    total: '115.00',
    paymentMethods: ['20'],
    isPreliminary: false,
    taxes: [
      { sriTaxCode: '4', taxBracket: 'GRAVADO', rate: '15.00', baseAmount: '100.00', taxAmount: '15.00' },
    ],
  },
  {
    id: '22222222-3333-4444-8555-666666666666',
    docType: 'FACTURA',
    accessKey: '0208202601123456789000120010010000001241234567819',
    issueDate: '2026-08-02',
    documentNumber: '001-001-000000124',
    supplierIdentification: '1799999999001',
    supplierName: 'SERVICIOS CLOUD ECUADOR',
    subtotal: '200.00',
    taxTotal: '30.00',
    total: '230.00',
    paymentMethods: ['20'],
    isPreliminary: false,
    taxes: [
      { sriTaxCode: '4', taxBracket: 'GRAVADO', rate: '15.00', baseAmount: '200.00', taxAmount: '30.00' },
    ],
  },
]

async function mockApi(page: Page) {
  let bankApplied = false
  let sriReviewed = false
  await page.route('**/api/v1/dev/token', (route) => route.fulfill({ json: { accessToken: 'test-token' } }))
  await page.route('**/api/v1/context', (route) => route.fulfill({
    json: {
      tenantId: '11111111-1111-4111-8111-111111111111',
      ruc: '1799999999001',
      name: 'IAERP Demo',
      roles: ['owner'],
      scopes: ['context:read', 'tax:read'],
      automationWritesEnabled: false,
      defaultPaymentTermsDays: 0,
    },
  }))
  for (const path of ['parties', 'products', 'tax-categories', 'establishments', 'emission-points', 'invoices', 'receivables', 'crm/leads']) {
    await page.route(`**/api/v1/${path}**`, (route) => route.fulfill({ json: [] }))
  }
  await page.route('**/api/v1/receivables/aging', (route) => route.fulfill({
    json: { asOf: '2026-08-15', buckets: aging, byParty: [] },
  }))
  await page.route('**/api/v1/receivables/collections/monthly**', (route) => route.fulfill({
    json: { months: collectionMonths },
  }))
  await page.route('**/api/v1/tax/dashboard', (route) => route.fulfill({ json: dashboard }))
  await page.route('**/api/v1/tax/purchases', (route) => route.fulfill({ json: purchases }))
  await page.route('**/api/v1/analytic-classifications', (route) => route.fulfill({ json: [{
    id: '33333333-4444-4555-8666-777777777777',
    code: 'PROYECTO',
    name: 'Proyecto',
    maxDepth: 1,
    active: true,
  }] }))
  await page.route('**/api/v1/analytic-classifications/*/values', (route) => route.fulfill({ json: [{
    id: '44444444-5555-4666-8777-888888888888',
    classificationId: '33333333-4444-4555-8666-777777777777',
    parentId: null,
    code: 'IAERP',
    name: 'IAERP',
    color: '#1769AA',
    active: true,
  }] }))
  const basePayable = {
    id: '99999999-2222-4333-8444-555555555555',
    supplierId: null,
    supplierName: 'PROVEEDOR DEMO CIA. LTDA.',
    fiscalDocumentId: purchases[0].id,
    description: 'Compra 001-001-000000123',
    category: 'Sin clasificar',
    documentType: 'INVOICE',
    documentNumber: '001-001-000000123',
    issueDate: '2026-08-01',
    dueDate: '2026-08-01',
    total: '115.00',
    openAmount: bankApplied ? '0.00' : '115.00',
    currency: 'USD',
    status: bankApplied ? 'SETTLED' : 'OPEN',
    taxClassification: 'DEDUCTIBLE_CONFIRMED',
    evidenceStatus: 'FISCAL_XML',
    supportReference: purchases[0].accessKey,
    analyticAssignments: [],
  }
  const reviewedPayable = {
    ...basePayable,
    id: 'aaaaaaaa-2222-4333-8444-555555555555',
    supplierName: purchases[1].supplierName,
    fiscalDocumentId: purchases[1].id,
    description: 'Compra 001-001-000000124',
    documentNumber: purchases[1].documentNumber,
    issueDate: purchases[1].issueDate,
    dueDate: '2026-08-02',
    total: '230.00',
    openAmount: '0.00',
    status: 'SETTLED',
    taxClassification: 'DEDUCTIBLE_CONFIRMED',
    supportReference: purchases[1].accessKey,
    analyticAssignments: [{
      classificationId: '33333333-4444-4555-8666-777777777777',
      classificationCode: 'PROYECTO',
      classificationName: 'Proyecto',
      valueId: '44444444-5555-4666-8777-888888888888',
      path: [{ code: 'IAERP', name: 'IAERP' }],
    }],
  }
  await page.route('**/api/v1/payables', (route) => {
    const currentBasePayable = {
      ...basePayable,
      openAmount: bankApplied ? '0.00' : '115.00',
      status: bankApplied ? 'SETTLED' : 'OPEN',
    }
    return route.fulfill({ json: sriReviewed ? [currentBasePayable, reviewedPayable] : [currentBasePayable] })
  })
  await page.route('**/api/v1/payables/from-document/review', async (route) => {
    sriReviewed = true
    await route.fulfill({ status: 201, json: reviewedPayable })
  })
  await page.route('**/api/v1/payables/*/movements', (route) => route.fulfill({ json: bankApplied ? [{
    id: '77777777-2222-4333-8444-555555555555',
    payableId: '99999999-2222-4333-8444-555555555555',
    installmentId: '88888888-2222-4333-8444-555555555555',
    movementType: 'PAYMENT',
    amount: '115.00',
    effectiveDate: '2026-08-05',
    method: 'TRANSFER',
    supportReference: 'BANK:DEBITO-001',
    reversedMovementId: null,
    actorId: 'user:test',
    createdAt: '2026-08-05T12:00:00Z',
  }] : [] }))
  await page.route('**/api/v1/finance/bank-statements', async (route) => {
    const isApply = Boolean(route.request().headers()['idempotency-key'])
    bankApplied ||= isApply
    await route.fulfill({ json: {
      period: '2026-08', fileName: 'estado.txt', sourceSha256: 'a'.repeat(64), accountMasked: '****1234',
      totalRows: 1, creditRows: 0, debitRows: 1, outsidePeriodCreditCount: 0, outsidePeriodDebitCount: 0,
      matchedCount: 0, unmatchedCreditCount: 0, ignoredDebitCount: 0, payableMatchedCount: 1,
      unmatchedDebitCount: 0, ruleSuggestionCount: 0, alreadyImportedCount: 0, manualCorrectionCount: 0,
      matches: [], manualCorrections: [], debitSuggestions: [],
      debitMatches: [{
        transactionId: 'b'.repeat(64), paymentDate: '2026-08-05', reference: 'DEBITO-001',
        description: 'TRANSFERENCIA PROVEEDOR DEMO', amount: '115.00',
        payableId: '99999999-2222-4333-8444-555555555555', supplierName: 'PROVEEDOR DEMO CIA. LTDA.',
        documentNumber: '001-001-000000123', payableTotal: '115.00', allocatedAmount: '115.00',
        linksExistingPayment: false, status: isApply ? 'REGISTERED' : 'MATCHED',
        detail: isApply ? 'Pago registrado con evidencia bancaria' : 'Coincidencia única y exacta',
      }],
    } })
  })
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => sessionStorage.clear())
  await mockApi(page)
  await page.goto('/')
  await page.getByRole('button', { name: 'Continuar' }).click()
})

test('dashboard muestra evolución y corte mensual documentado', async ({ page }) => {
  await expect(page.getByRole('heading', { name: 'Evolución de ventas emitidas' })).toBeVisible()
  // El valor de cada mes vive en la tabla equivalente del gráfico, que es como
  // lo lee un lector de pantalla: la línea solo rotula el extremo.
  await expect(
    page.getByRole('table', { name: /Ventas emitidas netas por mes/ }),
  ).toContainText('2.300,00')
  await expect(page.getByRole('heading', { name: 'Ventas y compras del mes' })).toBeVisible()
  await expect(page.getByRole('heading', { name: /IVA estimado/ })).toBeVisible()
  await expect(page.getByText('$61,99')).toBeVisible()
  await expect(page.getByText('a pagar')).toBeVisible()
  await expect(page.getByRole('alert')).toContainText('campo 564')
})

test('la sección de caja separa el dinero de las retenciones', async ({ page }) => {
  await expect(page.getByRole('heading', { name: 'Caja y cobranza' })).toBeVisible()

  // La antigüedad usa rampa ordinal: el orden de los tramos es parte del dato.
  await expect(page.getByRole('table', { name: /antigüedad/i })).toContainText('$900,00')

  // Una retención no es caja: se muestra aparte del dinero recibido.
  await expect(page.getByText('Se fue en retenciones')).toBeVisible()
  await expect(page.getByText('$120,00 recuperables ante el SRI, no en caja.')).toBeVisible()

  // 1.000 este mes contra 800 el anterior = +25 %, calculado del servidor.
  await expect(page.getByText(/25,00 % vs. mes anterior/)).toBeVisible()
})

test('el tablero completo pasa la auditoría de accesibilidad', async ({ page }) => {
  await expect(page.getByRole('heading', { name: 'Caja y cobranza' })).toBeVisible()
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze()
  expect(results.violations).toEqual([])
})

test('Compras une CxP con el XML y muestra el desglose de IVA', async ({ page }) => {
  await navigateToSection(page, 'Compras')

  await expect(page.getByRole('heading', { name: 'Compras', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Cuentas por pagar' })).toBeVisible()
  const row = page.getByRole('row', { name: /001-001-000000123/ })
  await expect(row).toContainText('PROVEEDOR DEMO')
  await expect(row).toContainText('Gravado 15,00%')
  await expect(row).toContainText('Base $100,00')
  await expect(row).toContainText('XML confirmado')
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze()
  expect(results.violations).toEqual([])
})

test('Compras revisa un comprobante SRI con pago y tag en un solo guardado', async ({ page }) => {
  await navigateToSection(page, 'Compras')
  await page.getByRole('button', { name: 'Pendientes SRI (1)' }).click()
  const row = page.getByRole('row', { name: /001-001-000000124/ })
  await expect(row).toContainText('SERVICIOS CLOUD ECUADOR')
  await row.getByRole('button', { name: 'Revisar' }).click()
  await expect(page.getByLabel('Revisión SRI de SERVICIOS CLOUD ECUADOR')).toBeFocused()
  await page.getByRole('button', { name: 'Cancelar' }).click()
  await expect(row.getByRole('button', { name: 'Revisar' })).toBeFocused()
  await row.getByRole('button', { name: 'Revisar' }).click()
  await expect(page.getByLabel('Revisión SRI de SERVICIOS CLOUD ECUADOR')).toBeFocused()

  await page.getByRole('radio', { name: /Gasto del negocio/ }).check()
  await page.getByRole('radio', { name: /Ya pagado/ }).check()
  await page.getByLabel('Fecha de pago').fill('2026-08-08')
  await page.getByLabel('Proyecto').selectOption('44444444-5555-4666-8777-888888888888')
  const requestPromise = page.waitForRequest((request) => request.url().endsWith('/payables/from-document/review'))
  await page.getByRole('button', { name: 'Guardar revisión' }).click()
  const request = await requestPromise
  expect(request.postDataJSON()).toMatchObject({
    documentId: purchases[1].id,
    taxClassification: 'DEDUCTIBLE_CONFIRMED',
    paymentState: 'PAID',
    paymentDate: '2026-08-08',
    analyticValueIds: ['44444444-5555-4666-8777-888888888888'],
  })
  await expect(page.getByRole('status')).toHaveText('Compra SRI revisada y guardada.')
  await expect(page.getByRole('status')).toBeFocused()
  await expect(page.getByRole('heading', { name: 'Todo revisado' })).toBeVisible()

  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze()
  expect(results.violations).toEqual([])
})

test('Compras conserva pago y tags al clasificar una CxP que ya tuvo movimientos', async ({ page }) => {
  let reviewed = false
  const partial = {
    id: 'aaaaaaaa-2222-4333-8444-555555555555',
    supplierId: null,
    supplierName: purchases[1].supplierName,
    fiscalDocumentId: purchases[1].id,
    description: 'Compra 001-001-000000124',
    category: 'Servicios cloud',
    documentType: 'INVOICE',
    documentNumber: purchases[1].documentNumber,
    issueDate: purchases[1].issueDate,
    dueDate: null,
    total: '230.00',
    openAmount: '100.00',
    currency: 'USD',
    status: 'PARTIAL',
    taxClassification: reviewed ? 'NON_DEDUCTIBLE' : 'DEDUCTIBLE_PENDING_REVIEW',
    evidenceStatus: 'FISCAL_XML',
    supportReference: purchases[1].accessKey,
    analyticAssignments: [{
      classificationId: '33333333-4444-4555-8666-777777777777',
      classificationCode: 'PROYECTO',
      classificationName: 'Proyecto',
      valueId: '44444444-5555-4666-8777-888888888888',
      path: [{ code: 'IAERP', name: 'IAERP' }],
    }],
  }
  await page.route('**/api/v1/payables', (route) => route.fulfill({ json: [{
    ...partial,
    id: '99999999-2222-4333-8444-555555555555',
    fiscalDocumentId: purchases[0].id,
    taxClassification: 'DEDUCTIBLE_CONFIRMED',
  }, { ...partial, taxClassification: reviewed ? 'NON_DEDUCTIBLE' : 'DEDUCTIBLE_PENDING_REVIEW' }] }))
  let reviewBody: Record<string, unknown> | undefined
  await page.route('**/api/v1/payables/from-document/review', async (route) => {
    reviewBody = route.request().postDataJSON() as Record<string, unknown>
    reviewed = true
    await route.fulfill({ status: 201, json: { ...partial, taxClassification: 'NON_DEDUCTIBLE' } })
  })

  await navigateToSection(page, 'Compras')
  await page.getByRole('button', { name: 'Pendientes SRI (1)' }).click()
  await page.getByRole('button', { name: 'Revisar' }).click()
  await expect(page.getByRole('group', { name: 'Pago ya registrado' })).toContainText('saldo $100,00')
  await expect(page.getByRole('group', { name: 'Tags conservados' })).toContainText('Proyecto: IAERP')
  await page.getByRole('radio', { name: /Solo registro tributario/ }).check()
  await page.getByRole('button', { name: 'Guardar revisión' }).click()
  expect(reviewBody).toMatchObject({
    paymentState: 'KEEP_EXISTING',
    taxClassification: 'NON_DEDUCTIBLE',
    analyticValueIds: ['44444444-5555-4666-8777-888888888888'],
  })
  await expect(page.getByRole('status')).toBeFocused()
})

test('Compras programa pago y reintenta con la misma clave idempotente', async ({ page }) => {
  const keys: string[] = []
  let attempts = 0
  await page.route('**/api/v1/payables/from-document/review', async (route) => {
    attempts += 1
    keys.push(route.request().headers()['idempotency-key'])
    if (attempts === 1) {
      await route.fulfill({ status: 500, json: { detail: 'Error temporal' } })
      return
    }
    await route.fulfill({ status: 201, json: {} })
  })

  await navigateToSection(page, 'Compras')
  await page.getByRole('button', { name: 'Pendientes SRI (1)' }).click()
  await page.getByRole('button', { name: 'Revisar' }).click()
  await page.getByRole('radio', { name: /Gasto del negocio/ }).check()
  await page.getByRole('radio', { name: /Pago previsto/ }).check()
  await page.getByLabel('Fecha prevista de pago').fill('2026-08-31')
  await page.getByRole('button', { name: 'Guardar revisión' }).click()
  await expect(page.getByRole('alert')).toContainText('Error temporal')
  await page.getByRole('button', { name: 'Guardar revisión' }).click()
  await expect(page.getByRole('status')).toBeVisible()
  expect(keys).toHaveLength(2)
  expect(keys[0]).toBe(keys[1])
})

test('Compras carga, confirma y muestra en historial un pago del mismo extracto', async ({ page }) => {
  await navigateToSection(page, 'Compras')
  await page.getByRole('button', { name: 'Conciliación bancaria' }).click()
  await page.getByLabel('Extracto Banco Bolivariano').setInputFiles({
    name: 'estado.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('extracto sintetico'),
  })
  await page.getByRole('button', { name: 'Revisar movimientos' }).click()
  await expect(page.getByRole('heading', { name: 'Pagos encontrados' })).toBeVisible()
  await expect(page.getByText('Coincidencia única y exacta')).toBeVisible()
  await page.getByRole('button', { name: 'Confirmar 1 cruces' }).click()
  await expect(page.getByText('Pago registrado con evidencia bancaria')).toBeVisible()

  await page.getByRole('button', { name: 'Todas' }).click()
  await page.getByRole('button', { name: 'Historial' }).click()
  await expect(page.getByRole('heading', { name: 'Historial' })).toBeVisible()
  await expect(page.getByText('BANK:DEBITO-001')).toBeVisible()
})

test('Compras permite preparar un reparto manual antes de confirmar', async ({ page }) => {
  await page.route('**/api/v1/finance/bank-statements', async (route) => {
    const hasAllocation = route.request().postData()?.includes('debitAllocations') ?? false
    await route.fulfill({ json: {
      period: '2026-08', fileName: 'estado.txt', sourceSha256: 'c'.repeat(64), accountMasked: '****1234',
      totalRows: 1, creditRows: 0, debitRows: 1, outsidePeriodCreditCount: 0, outsidePeriodDebitCount: 0,
      matchedCount: 0, unmatchedCreditCount: 0, ignoredDebitCount: 0,
      payableMatchedCount: hasAllocation ? 1 : 0, unmatchedDebitCount: hasAllocation ? 0 : 1,
      ruleSuggestionCount: 0, alreadyImportedCount: 0, manualCorrectionCount: 0,
      matches: [], manualCorrections: [],
      debitMatches: hasAllocation ? [{
        transactionId: 'd'.repeat(64), paymentDate: '2026-08-06', reference: 'LOTE-002',
        description: 'PAGO AGRUPADO', amount: '50.00', payableId: '99999999-2222-4333-8444-555555555555',
        supplierName: 'PROVEEDOR DEMO CIA. LTDA.', documentNumber: '001-001-000000123', payableTotal: '115.00',
        allocatedAmount: '50.00', linksExistingPayment: false, status: 'MATCHED', detail: 'Reparto manual listo para confirmar',
      }] : [],
      debitSuggestions: hasAllocation ? [] : [{
        transactionId: 'd'.repeat(64), paymentDate: '2026-08-06', reference: 'LOTE-002',
        description: 'PAGO AGRUPADO', amount: '50.00', classification: 'UNCLASSIFIED', detail: 'Sin cruce; requiere revisión',
      }],
    } })
  })

  await navigateToSection(page, 'Compras')
  await page.getByRole('button', { name: 'Conciliación bancaria' }).click()
  await page.getByLabel('Extracto Banco Bolivariano').setInputFiles({ name: 'estado.txt', mimeType: 'text/plain', buffer: Buffer.from('extracto sintetico') })
  await page.getByRole('button', { name: 'Revisar movimientos' }).click()
  await expect(page.getByRole('heading', { name: 'Débitos por revisar' })).toBeVisible()
  await page.getByLabel('Monto para LOTE-002').fill('50.00')
  await page.getByRole('button', { name: 'Agregar cruce' }).click()
  await expect(page.getByRole('heading', { name: 'Repartos preparados' })).toBeVisible()
  await page.getByRole('button', { name: 'Revisar reparto' }).click()
  await expect(page.getByText('Reparto manual listo para confirmar')).toBeVisible()
})
