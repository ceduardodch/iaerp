import { expect, test, type Page } from '@playwright/test'
import { mockDashboardEndpoints } from './dashboard-mocks'

// Sección tributaria (ADR 0012): valores listos para copiar, distinción entre
// campos "para pegar" y "solo control", y aviso explícito cuando los datos son
// preliminares. La API va mockeada: la pantalla no calcula nada por su cuenta.

const PERIOD_ID = '33333333-3333-4333-8333-333333333333'
const HISTORICAL_ID = '88888888-8888-4888-8888-888888888888'

const summary = {
  periodId: PERIOD_ID,
  year: 2025,
  month: 11,
  status: 'LISTO_REVISAR',
  documentCount: 3,
  isPreliminary: true,
  preliminaryReasons: [
    '1 comprobante(s) sin detalle confirmado: carga su XML autorizado antes de declarar.',
  ],
  amounts: {
    ventasBrutas: '1836.00',
    ivaGenerado: '275.40',
    comprasGravadasBase: '13.13',
    comprasTarifaCeroBase: '276.30',
    ivaCreditoTributario: '1.97',
    retencionesIvaRecibidas: '32.80',
    retencionesRentaRecibidas: '8.59',
    saldoAPagar: '240.63',
    creditoAFavor: '0.00',
  },
  fields: [
    {
      fieldCode: '401',
      label: 'Ventas locales gravadas con tarifa distinta de 0%',
      sourceKey: 'ventasGravadasBase',
      isPaste: true,
      value: '1836.00',
      documentCount: 1,
      needsReview: false,
    },
    {
      fieldCode: '609',
      label: 'Retenciones de IVA que le efectuaron',
      sourceKey: 'retencionesIvaRecibidas',
      isPaste: true,
      value: '32.80',
      documentCount: 1,
      needsReview: false,
    },
    {
      fieldCode: '507',
      label: 'Total de adquisiciones y pagos (confirmar contra el formulario vigente)',
      sourceKey: 'comprasTotalesBase',
      isPaste: false,
      value: '289.43',
      documentCount: 2,
      needsReview: true,
    },
  ],
}

async function mockApi(page: Page) {
  let historicalApproved = false
  await page.route('**/api/v1/dev/token', (route) =>
    route.fulfill({ json: { accessToken: 'test-token' } }),
  )
  await mockDashboardEndpoints(page)
  await page.route('**/api/v1/context', (route) => route.fulfill({
    json: {
      tenantId: '11111111-1111-4111-8111-111111111111',
      ruc: '1799999999001',
      name: 'IAERP Demo',
      roles: ['owner'],
      scopes: ['context:read', 'tax:read', 'tax:write'],
      automationWritesEnabled: false,
      defaultPaymentTermsDays: 0,
    },
  }))
  for (const path of ['parties', 'products', 'tax-categories', 'establishments', 'emission-points', 'invoices']) {
    await page.route(`**/api/v1/${path}`, (route) => route.fulfill({ json: [] }))
  }
  await page.route('**/api/v1/tax/periods', (route) => route.fulfill({
    json: [
      { id: PERIOD_ID, year: 2025, month: 11, obligationType: 'IVA', status: 'LISTO_REVISAR' },
      { id: '44444444-4444-4444-8444-444444444444', year: 2024, month: 12, obligationType: 'IVA', status: 'DECLARADO' },
    ],
  }))
  await page.route(`**/api/v1/tax/periods/${PERIOD_ID}/iva`, (route) =>
    route.fulfill({ json: summary }),
  )
  await page.route(`**/api/v1/tax/periods/${PERIOD_ID}/documents`, (route) => route.fulfill({
    json: [
      {
        id: '55555555-5555-4555-8555-555555555555',
        direction: 'RECIBIDO',
        docType: 'FACTURA',
        accessKey: '3011202501099999999900120010100000079561234567818',
        issueDate: '2025-11-30',
        counterpartyName: 'PROVEEDOR DEMO CIA LTDA',
        subtotal: '276.30',
        taxTotal: '0.00',
        total: '276.30',
        paymentMethods: ['20'],
        isPreliminary: false,
      },
      {
        id: '66666666-6666-4666-8666-666666666666',
        direction: 'RECIBIDO',
        docType: 'RETENCION',
        issueDate: '2025-12-20',
        counterpartyName: 'CLIENTE AGENTE DEMO',
        subtotal: '0.00',
        taxTotal: '0.00',
        total: '0.00',
        isPreliminary: true,
      },
    ],
  }))
  await page.route(
    `**/api/v1/tax/periods/${PERIOD_ID}/historical-tax-candidates`,
    (route) => route.fulfill({
      json: [{
        id: HISTORICAL_ID,
        documentNumber: '706768646',
        accessKey: '1105202601179311319200120010017067686461391703815',
        issueDate: '2026-05-11',
        customerName: 'UNIVERSIDAD DEMO',
        subtotal: '1836.00',
        taxTotal: '275.40',
        total: '2111.40',
        approved: historicalApproved,
        xmlOriginalMissing: true,
      }],
    }),
  )
  await page.route(
    `**/api/v1/tax/periods/${PERIOD_ID}/historical-tax-candidates/${HISTORICAL_ID}/approve`,
    async (route) => {
      historicalApproved = true
      await route.fulfill({
        json: {
          id: '99999999-9999-4999-8999-999999999999',
          direction: 'EMITIDO',
          docType: 'FACTURA',
          issueDate: '2026-05-11',
          counterpartyName: 'UNIVERSIDAD DEMO',
          subtotal: '1836.00',
          taxTotal: '275.40',
          total: '2111.40',
          paymentMethods: ['20'],
          isPreliminary: false,
        },
      })
    },
  )
  await page.route(`**/api/v1/tax/periods/${PERIOD_ID}/ats`, (route) => route.fulfill({
    json: {
      id: '77777777-7777-4777-8777-777777777777',
      taxPeriodId: PERIOD_ID,
      annexType: 'ATS',
      status: 'GENERADO',
      version: 1,
      downloadUrl: 'https://private.example/AT112025.zip',
    },
  }))
  await page.route(`**/api/v1/tax/periods/${PERIOD_ID}/status`, async (route) => {
    const request = route.request().postDataJSON() as { targetStatus: string }
    await route.fulfill({
      json: {
        id: PERIOD_ID,
        year: 2025,
        month: 11,
        obligationType: 'IVA',
        status: request.targetStatus,
      },
    })
  })
  await page.route('**/api/v1/tax/annexes/77777777-7777-4777-8777-777777777777/issues', (route) => route.fulfill({ json: [] }))
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => sessionStorage.clear())
  await mockApi(page)
  await page.goto('/')
  await page.getByRole('button', { name: 'Continuar' }).click()
  await page.getByRole('button', { name: 'Tributario' }).click()
  await expect(page.getByRole('heading', { name: 'Tributario' })).toBeVisible()
})

test('muestra los periodos agrupados por año', async ({ page }) => {
  await expect(page.getByText('2025', { exact: true })).toBeVisible()
  await expect(page.getByText('2024', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: /Noviembre/ })).toBeVisible()
})

test('muestra los valores listos para copiar con dos decimales', async ({ page }) => {
  const row = page.getByRole('row', { name: /401/ })
  await expect(row).toContainText('1836.00')
  // Punto decimal, sin separador de miles.
  await expect(row).not.toContainText('1,836')

  await expect(page.getByRole('row', { name: /609/ })).toContainText('32.80')
})

test('separa los campos para pegar de los que el SRI autocalcula', async ({ page }) => {
  // 401 y 609 son para copiar: tienen botón.
  await expect(page.getByRole('button', { name: 'Copiar campo 401' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Copiar campo 609' })).toBeVisible()
  // 507 es solo control: aparece en la tabla de control, sin botón de copiar.
  await expect(page.getByRole('button', { name: 'Copiar campo 507' })).toHaveCount(0)
  await expect(page.getByText('Solo control (el SRI los calcula)')).toBeVisible()
})

test('advierte cuando los datos son preliminares', async ({ page }) => {
  const warning = page.getByRole('alert')
  await expect(warning).toContainText('Datos preliminares')
  await expect(warning).toContainText('carga su XML autorizado antes de declarar')
})

test('separa la retención de renta del IVA mensual', async ({ page }) => {
  const summaryPanel = page.getByText('Retenciones de renta (no entran al IVA)')
  await expect(summaryPanel).toBeVisible()
  await expect(page.getByRole('definition').filter({ hasText: '8.59' })).toBeVisible()
})

test('separa cada comprobante y muestra su ID IAERP', async ({ page }) => {
  await expect(page.getByText('Compras recibidas', { exact: true })).toBeVisible()
  await expect(page.getByText('Retenciones recibidas', { exact: true })).toBeVisible()
  await page.locator('details').filter({ hasText: 'Compras recibidas' }).locator('summary').click()
  await page.locator('details').filter({ hasText: 'Retenciones recibidas' }).locator('summary').click()
  const retentionCard = page.locator('article').filter({ hasText: 'Retención' })
  await expect(retentionCard).toContainText('Preliminar')

  const invoiceCard = page.locator('article').filter({ hasText: 'PROVEEDOR DEMO' })
  await expect(invoiceCard).toContainText('Confirmado')
  await expect(invoiceCard).toContainText('Transferencia')
  await expect(invoiceCard).toContainText('ID IAERP')
  await expect(invoiceCard).toContainText('55555555-5555-4555-8555-555555555555')
  await expect(invoiceCard).toContainText('Clave SRI')
  await expect(invoiceCard.getByRole('button', { name: /Copiar ID IAERP/ })).toBeVisible()
})

test('genera el ATS y ofrece su descarga privada', async ({ page }) => {
  await page.getByRole('button', { name: 'Generar ATS' }).click()
  await expect(page.getByRole('status')).toContainText('ATS v1 generado')
  await expect(page.getByRole('link', { name: 'Descargar ZIP' })).toHaveAttribute(
    'href',
    'https://private.example/AT112025.zip',
  )
})

test('aprueba un RIDE histórico solo para IVA y ATS con respaldo bancario', async ({ page }) => {
  const panel = page
    .getByRole('heading', { name: 'Excepciones ATS · XML original faltante' })
    .locator('xpath=ancestor::section[1]')
  await expect(panel).toContainText('706768646')
  await expect(panel).toContainText('1836.00')
  const approve = page.getByRole('button', { name: 'Aprobar excepción IVA/ATS' })
  await expect(approve).toBeDisabled()
  await page.getByLabel('Respaldo de transferencia bancaria').fill(
    'Estado bancario mayo 2026, transferencia neta respaldada',
  )
  page.once('dialog', (dialog) => dialog.accept())
  await approve.click()
  await expect(page.getByText('Aprobada para ATS')).toBeVisible()
})

test('exige confirmación antes de dejar el periodo listo para declarar', async ({ page }) => {
  let confirmation = ''
  page.on('dialog', async (dialog) => {
    confirmation = dialog.message()
    await dialog.accept()
  })
  await page.getByRole('button', { name: 'Marcar listo para declarar' }).click()
  await expect.poll(() => confirmation).toContain('revisaste la evidencia')
})

// Carga en bloque: revisar primero, confirmar después. La pantalla no decide
// nada por su cuenta: muestra lo que el servidor clasificó.
const bulkPreview = {
  items: [
    {
      filename: 'Factura (1).xml',
      status: 'OK',
      docType: 'FACTURA',
      direction: 'RECIBIDO',
      accessKey: '3011202501099999999900120010100000079561234567818',
      issueDate: '2025-11-30',
      periodYear: 2025,
      periodMonth: 11,
      counterpartyName: 'PROVEEDOR DEMO CIA LTDA',
      total: '276.30',
      isRetention: false,
    },
    {
      filename: 'Retención (1).xml',
      status: 'OK',
      docType: 'RETENCION',
      direction: 'RECIBIDO',
      issueDate: '2025-11-10',
      periodYear: 2025,
      periodMonth: 11,
      counterpartyName: 'CLIENTE AGENTE DEMO',
      total: '41.39',
      isRetention: true,
    },
    {
      filename: 'roto.xml',
      status: 'ERROR',
      isRetention: false,
      error: 'Invalid SRI XML',
    },
  ],
  created: 0,
  updated: 0,
  duplicates: 0,
  errors: 1,
  periods: { '2025-11': 2 },
  notes: [],
  retentionCount: 1,
  retentionsApplied: 0,
}

async function selectBulkFiles(page: Page) {
  await page.setInputFiles('input[type="file"]', [
    { name: 'Factura (1).xml', mimeType: 'application/xml', buffer: Buffer.from('<a/>') },
    { name: 'Retención (1).xml', mimeType: 'application/xml', buffer: Buffer.from('<b/>') },
  ])
}

test('revisa el lote antes de guardar y clasifica cada archivo', async ({ page }) => {
  await page.route('**/api/v1/tax/evidence/bulk', (route) =>
    route.fulfill({ json: bulkPreview }),
  )

  await selectBulkFiles(page)
  await page.getByRole('button', { name: 'Revisar carga' }).click()

  await expect(page.getByText('Previo: esto es lo que se cargará')).toBeVisible()
  // Cada archivo muestra qué es y a qué periodo va.
  const invoiceRow = page.getByRole('row', { name: /Factura \(1\)\.xml/ })
  await expect(invoiceRow).toContainText('FACTURA')
  await expect(invoiceRow).toContainText('Recibido')
  await expect(invoiceRow).toContainText('Noviembre 2025')
  // El archivo ilegible se reporta sin abortar el resto.
  await expect(page.getByRole('row', { name: /roto\.xml/ })).toContainText('Invalid SRI XML')
  // Todavía no se guardó nada: sigue ofreciendo confirmar.
  await expect(page.getByRole('button', { name: 'Confirmar carga' })).toBeVisible()
})

test('ofrece aplicar las retenciones a cartera solo si hay retenciones', async ({ page }) => {
  await page.route('**/api/v1/tax/evidence/bulk', (route) =>
    route.fulfill({ json: bulkPreview }),
  )

  await selectBulkFiles(page)
  await page.getByRole('button', { name: 'Revisar carga' }).click()

  const checkbox = page.getByRole('checkbox', { name: /Aplicar 1 retención/ })
  await expect(checkbox).toBeVisible()
  // Por defecto NO se aplica: la cartera solo se toca si se confirma.
  await expect(checkbox).not.toBeChecked()
})

test('confirmar la carga informa lo registrado', async ({ page }) => {
  let applied = false
  await page.route('**/api/v1/tax/evidence/bulk', async (route) => {
    const body = route.request().postData() ?? ''
    if (body.includes('name="apply"') && body.includes('true')) {
      applied = true
      return route.fulfill({
        json: { ...bulkPreview, created: 2, retentionsApplied: 1 },
      })
    }
    return route.fulfill({ json: bulkPreview })
  })

  await selectBulkFiles(page)
  await page.getByRole('button', { name: 'Revisar carga' }).click()
  await page.getByRole('button', { name: 'Confirmar carga' }).click()

  await expect.poll(() => applied).toBe(true)
  await expect(page.getByText('Carga confirmada')).toBeVisible()
  await expect(page.getByText(/Registrados: 2 nuevo/)).toBeVisible()
})

// Expediente: la historia del comprobante en la propia tabla de documentos.
test('despliega la historia del comprobante con retención y cobro', async ({ page }) => {
  await page.route('**/api/v1/tax/documents/*/dossier', (route) => route.fulfill({
    json: {
      documentId: '55555555-5555-4555-8555-555555555555',
      docType: 'FACTURA',
      direction: 'EMITIDO',
      accessKey: '1511202501179999999900120010010000000451234567819',
      issueDate: '2025-11-15',
      counterpartyName: 'CLIENTE DEMO S.A.',
      total: '359.24',
      paymentMethods: ['20'],
      retentions: [
        {
          accessKey: '1011202507066666666600120010010000023643121521411',
          issueDate: '2025-11-20',
          issuerName: 'CLIENTE AGENTE DEMO',
          ivaAmount: '32.80',
          incomeTaxAmount: '8.59',
        },
      ],
      movements: [
        {
          movementType: 'PAYMENT',
          amount: '317.85',
          occurredAt: '2025-11-25T10:00:00Z',
          reference: 'BANCO 998877 | TRX-1',
          bankReference: '998877 | TRX-1',
        },
      ],
      receivableId: '88888888-8888-4888-8888-888888888888',
      receivableStatus: 'SETTLED',
      retainedIva: '32.80',
      retainedIncomeTax: '8.59',
      collectedAmount: '317.85',
      outstandingAmount: '0.00',
      expectedNet: '317.85',
      netDifference: '0.00',
      notes: [],
    },
  }))

  await page.getByRole('button', { name: /Ver historia del comprobante/ }).first().click()

  const dossier = page.locator('.tax-dossier')
  await expect(dossier).toBeVisible()
  // La retención se ve con IVA y renta separadas.
  await expect(dossier).toContainText('IVA $32.80')
  await expect(dossier).toContainText('Renta $8.59')
  // El cobro muestra su referencia bancaria.
  await expect(dossier).toContainText('Cobro')
  await expect(dossier).toContainText('Banco · 998877')
  // total − retenciones = neto esperado.
  await expect(dossier).toContainText('Neto esperado')
  await expect(dossier).toContainText('$317.85')
})
