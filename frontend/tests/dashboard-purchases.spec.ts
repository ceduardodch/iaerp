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
  await expect(page.getByRole('heading', { name: 'Evolución de ventas' })).toBeVisible()
  await expect(page.getByLabel('Ventas autorizadas netas por mes')).toContainText('2.300,00')
  await expect(page.getByRole('heading', { name: /Compras vs. ventas/ })).toBeVisible()
  await expect(page.getByText('IVA estimado a pagar')).toBeVisible()
  await expect(page.getByText('$61,99')).toBeVisible()
  await expect(page.getByRole('alert')).toContainText('campo 564')
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
