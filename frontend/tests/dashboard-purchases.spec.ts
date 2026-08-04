import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

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
]

async function mockApi(page: Page) {
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
    await page.route(`**/api/v1/${path}`, (route) => route.fulfill({ json: [] }))
  }
  await page.route('**/api/v1/receivables/aging', (route) => route.fulfill({
    json: { asOf: '2026-08-15', buckets: aging, byParty: [] },
  }))
  await page.route('**/api/v1/receivables/collections/monthly**', (route) => route.fulfill({
    json: { months: collectionMonths },
  }))
  await page.route('**/api/v1/tax/dashboard', (route) => route.fulfill({ json: dashboard }))
  await page.route('**/api/v1/tax/purchases', (route) => route.fulfill({ json: purchases }))
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

test('Compras agrupa XML por mes y muestra el desglose de IVA', async ({ page }) => {
  await page.getByRole('button', { name: 'Compras' }).click()

  await expect(page.getByRole('heading', { name: 'Compras', exact: true })).toBeVisible()
  await expect(page.getByText('agosto de 2026')).toBeVisible()
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
