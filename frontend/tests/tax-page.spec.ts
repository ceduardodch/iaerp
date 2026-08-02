import { expect, test, type Page } from '@playwright/test'

// Sección tributaria (ADR 0012): valores listos para copiar, distinción entre
// campos "para pegar" y "solo control", y aviso explícito cuando los datos son
// preliminares. La API va mockeada: la pantalla no calcula nada por su cuenta.

const PERIOD_ID = '33333333-3333-4333-8333-333333333333'

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
  await page.route('**/api/v1/dev/token', (route) =>
    route.fulfill({ json: { accessToken: 'test-token' } }),
  )
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

test('marca los comprobantes preliminares en la tabla de documentos', async ({ page }) => {
  const retentionRow = page.getByRole('row', { name: /RETENCION/ })
  await expect(retentionRow).toContainText('Preliminar')

  const invoiceRow = page.getByRole('row', { name: /PROVEEDOR DEMO/ })
  await expect(invoiceRow).toContainText('Confirmado')
})

test('genera el ATS y ofrece su descarga privada', async ({ page }) => {
  await page.getByRole('button', { name: 'Generar ATS' }).click()
  await expect(page.getByRole('status')).toContainText('ATS v1 generado')
  await expect(page.getByRole('link', { name: 'Descargar ZIP' })).toHaveAttribute(
    'href',
    'https://private.example/AT112025.zip',
  )
})
