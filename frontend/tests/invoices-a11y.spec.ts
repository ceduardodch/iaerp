import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

import { pickCombobox } from './combobox'
import { mockDashboardEndpoints } from './dashboard-mocks'
import { navigateToSection } from './navigation'

const context = {
  tenantId: '11111111-1111-4111-8111-111111111111',
  ruc: '1799999999001',
  name: 'IAERP Demo',
  roles: ['owner'],
  scopes: ['context:read', 'parties:read', 'products:read', 'invoices:read', 'invoices:write'],
  automationWritesEnabled: false,
  defaultPaymentTermsDays: 0,
}

const customer = {
  id: '14141414-1414-4414-8414-141414141414',
  name: 'Cliente Sintetico Norte',
  identificationType: 'CEDULA',
  identificationNumber: '1712345678',
  roles: ['CUSTOMER'],
}

const product = {
  id: '16161616-1616-4616-8616-161616161616',
  name: 'Servicio Norte',
  code: 'NORTE-001',
  unitPrice: '10.250000',
  taxCategoryId: '99999999-9999-4999-8999-999999999999',
}

const establishment = {
  id: 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
  code: '001',
  name: 'Matriz Norte',
  address: 'Direccion sintetica norte',
  active: true,
}

const emissionPoint = {
  id: '12121212-1212-4212-8212-121212121212',
  establishmentId: establishment.id,
  code: '001',
  active: true,
}

const draftInvoice = {
  id: '21212121-2121-4212-8212-212121212121',
  type: 'INVOICE',
  status: 'DRAFT',
  sequential: '001001000000001',
  issueDate: '2026-07-04',
  accessKey: null,
  subtotal: '19.50',
  tax: '2.93',
  total: '22.43',
  currency: 'USD',
  partyId: customer.id,
  establishmentId: establishment.id,
  emissionPointId: emissionPoint.id,
  reason: null,
  lines: [
    {
      id: 'a1a1a1a1-a1a1-4a1a-8a1a-a1a1a1a1a1a1',
      lineNumber: 1,
      productId: product.id,
      description: product.name,
      quantity: '2',
      unitPrice: '10.250000',
      discount: '1.00',
      baseAmount: '19.50',
      taxCode: '4',
      taxRate: '15.000000',
      taxAmount: '2.93',
    },
  ],
  sriTransmission: null,
}

const authorizedInvoice = {
  ...draftInvoice,
  id: '31313131-3131-4313-8313-313131313131',
  sequential: '001001000000002',
  status: 'AUTHORIZED',
  accessKey: '1'.repeat(49),
  sriTransmission: {
    status: 'AUTHORIZED',
    message: 'Comprobante autorizado',
    authorizationNumber: '9'.repeat(37),
    lastAttemptAt: '2026-07-04T12:00:00Z',
  },
}

const rejectedInvoice = {
  ...draftInvoice,
  id: '41414141-4141-4414-8414-414141414141',
  sequential: '001001000000003',
  status: 'REJECTED',
  sriTransmission: {
    status: 'REJECTED',
    message: 'RUC del cliente no encontrado',
    authorizationNumber: null,
    lastAttemptAt: '2026-07-04T12:05:00Z',
  },
}

const historicalInvoice = {
  ...draftInvoice,
  id: '61616161-6161-4616-8616-616161616160',
  sequential: '000000123',
  issueDate: '2026-05-11',
  status: 'HISTORICAL_ISSUED',
  accessKey: '1'.repeat(49),
  authorizationNumber: '1'.repeat(49),
  reason: 'Factura historica respaldada por RIDE PDF; XML no disponible.',
  sriTransmission: null,
}

const duplicatedInvoice = {
  ...rejectedInvoice,
  id: '51515151-5151-4515-8515-515151515151',
  sequential: '001001000000004',
  status: 'DRAFT',
  accessKey: null,
  sriTransmission: null,
}

const commercialContract = {
  id: '61616161-6161-4616-8616-616161616161',
  partyId: customer.id,
  contractNumber: 'CT-2026-001',
  title: 'Servicios administrados AWS',
  serviceType: 'AWS_MONTHLY',
  sourceLeadId: null,
  parentContractId: null,
  reportRequired: true,
  collectionEnabled: true,
  status: 'DRAFT',
  currentVersionId: null,
}

const contractVersion = {
  id: '71717171-7171-4717-8717-717171717171',
  contractId: commercialContract.id,
  versionNumber: 1,
  status: 'DRAFT',
  validFrom: '2026-08-01',
  validTo: '2027-07-31',
  paymentTermsDays: 30,
  renewalNoticeDays: null,
  pricingRules: [],
  amendsVersionId: null,
  signedAt: null,
  sentAt: null,
  sentArtifactSha256: null,
  gmailThreadId: null,
  replyDetectedAt: null,
  signedArtifactSha256: null,
  signaturePrecheckStatus: null,
  signaturePrecheckDetails: null,
  firmaecConfirmedAt: null,
}

async function mockApi(page: Page) {
  await page.route('**/api/v1/dev/token', (route) =>
    route.fulfill({ json: { accessToken: 'test-token' } }),
  )
  await mockDashboardEndpoints(page)
  await page.route('**/api/v1/context', (route) => route.fulfill({ json: context }))
  await page.route('**/api/v1/parties', (route) => route.fulfill({ json: [customer] }))
  await page.route('**/api/v1/crm/leads**', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/v1/commercial/billing-proposals**', (route) =>
    route.fulfill({ json: [] }),
  )
  await page.route('**/api/v1/commercial/aws-consumption-cuts**', (route) =>
    route.fulfill({ json: [] }),
  )
  await page.route('**/api/v1/commercial/contracts**', (route) => {
    if (route.request().url().endsWith('/versions')) return route.fulfill({ json: [contractVersion] })
    return route.fulfill({ json: [commercialContract] })
  })
  await page.route('**/api/v1/products', (route) => route.fulfill({ json: [product] }))
  await page.route('**/api/v1/tax-categories', (route) =>
    route.fulfill({
      json: [
        {
          id: product.taxCategoryId,
          sriCode: '4',
          name: 'IVA 15%',
          rate: '15.000000',
          active: true,
        },
      ],
    }),
  )
  await page.route('**/api/v1/establishments', (route) => route.fulfill({ json: [establishment] }))
  await page.route('**/api/v1/emission-points', (route) => route.fulfill({ json: [emissionPoint] }))
  await page.route('**/api/v1/invoices/preview', (route) =>
    route.fulfill({
      json: {
        lines: draftInvoice.lines.map((line) => ({ ...line, total: '22.43' })),
        taxSubtotals: [
          { taxCode: '4', taxRate: '15.000000', baseAmount: '19.50', taxAmount: '2.93' },
        ],
        subtotal: '19.50',
        taxTotal: '2.93',
        total: '22.43',
      },
    }),
  )
  await page.route('**/api/v1/invoices/historical-pdf', (route) =>
    route.fulfill({ status: 201, json: historicalInvoice }),
  )
  await page.route('**/api/v1/invoices', (route) => {
    if (route.request().method() === 'POST') {
      return route.fulfill({ status: 201, json: draftInvoice })
    }
    return route.fulfill({ json: [draftInvoice, authorizedInvoice, rejectedInvoice] })
  })
  await page.route(`**/api/v1/invoices/${draftInvoice.id}`, (route) =>
    route.fulfill({ json: draftInvoice }),
  )
  await page.route(`**/api/v1/invoices/${authorizedInvoice.id}`, (route) =>
    route.fulfill({ json: authorizedInvoice }),
  )
  await page.route(`**/api/v1/invoices/${rejectedInvoice.id}`, (route) =>
    route.fulfill({ json: rejectedInvoice }),
  )
  await page.route(`**/api/v1/invoices/${duplicatedInvoice.id}`, (route) =>
    route.fulfill({ json: duplicatedInvoice }),
  )
  await page.route(`**/api/v1/invoices/${historicalInvoice.id}`, (route) =>
    route.fulfill({ json: historicalInvoice }),
  )
  await page.route(`**/api/v1/invoices/${authorizedInvoice.id}/email-preview`, (route) =>
    route.fulfill({
      json: {
        recipient: customer.email,
        senderAddress: 'contabilidad@b2b.com.ec',
        senderName: 'Contabilidad B2B',
        subject: 'Factura 001-001-000000002 · IAERP Demo',
        message: 'Hola Cliente Demo.\n\nFecha límite de pago: 2026-08-04\nPlazo acordado: 31 días.',
        attachmentNames: ['FACTURA-001-001-000000002.xml', 'FACTURA-001-001-000000002.pdf'],
        dueDate: '2026-08-04',
        paymentTermsDays: 31,
      },
    }),
  )
  await page.route('**/api/v1/invoices/*/duplicate', (route) =>
    route.fulfill({ status: 201, json: duplicatedInvoice }),
  )
  await page.route('**/api/v1/invoices/*/artifacts', (route) => {
    if (route.request().url().includes(historicalInvoice.id)) {
      return route.fulfill({
        json: [
          {
            id: 'd1d1d1d1-d1d1-4d1d-8d1d-d1d1d1d1d1d1',
            artifactType: 'ride-pdf',
            sha256: 'c'.repeat(64),
            version: 1,
            createdAt: '2026-08-03T12:00:00Z',
          },
        ],
      })
    }
    if (route.request().url().includes(authorizedInvoice.id)) {
      return route.fulfill({
        json: [
          {
            id: 'b1b1b1b1-b1b1-4b1b-8b1b-b1b1b1b1b1b1',
            artifactType: 'xml-signed',
            sha256: 'a'.repeat(64),
            version: 1,
            createdAt: '2026-07-04T12:00:00Z',
          },
          {
            id: 'c1c1c1c1-c1c1-4c1c-8c1c-c1c1c1c1c1c1',
            artifactType: 'ride-pdf',
            sha256: 'b'.repeat(64),
            version: 1,
            createdAt: '2026-07-04T12:00:00Z',
          },
        ],
      })
    }
    return route.fulfill({ json: [] })
  })
  await page.route(/\/api\/v1\/invoices\/[^/]+\/artifacts\/[^/]+\/download\?inline=true$/, (route) =>
    route.fulfill({
      json: {
        downloadUrl: 'https://documents.example.test/ride.pdf?disposition=inline',
        expiresInSeconds: 300,
        fileName: 'FACTURA-001001000000002.pdf',
      },
    }),
  )
}

async function expectNoA11yViolations(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze()
  expect(results.violations).toEqual([])
}

async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => {
    const root = document.scrollingElement ?? document.documentElement
    return root.scrollWidth - root.clientWidth
  })
  expect(overflow).toBeLessThanOrEqual(1)
}

async function loginAndOpenInvoices(page: Page) {
  await page.goto('/')
  await page.getByRole('button', { name: 'Continuar' }).click()
  await expect(page.getByRole('heading', { name: 'IAERP Demo' })).toBeVisible()
  await navigateToSection(page, 'Facturas')
  await expect(page.getByRole('heading', { name: 'Facturas', exact: true })).toBeVisible()
  // Espera a que la LISTA cargue (el mock devuelve 3 facturas). Sin esto, entre
  // que aparece el encabezado y resuelve la query de facturas se muestra el
  // empty-state, cuyo botón "Nueva factura" colisiona (strict mode) con el del
  // encabezado. Es un race latente que el code-split (timing distinto) destapó.
  await expect(
    page.getByRole('row', { name: new RegExp(draftInvoice.sequential) }),
  ).toBeVisible()
}

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.addInitScript(() => sessionStorage.clear())
  await mockApi(page)
})

test('invoice list passes WCAG 2.1 AA automated checks', async ({ page }) => {
  await loginAndOpenInvoices(page)
  await expect(page.getByRole('cell', { name: draftInvoice.sequential, exact: true })).toBeVisible()
  await expectNoA11yViolations(page)
})

test('historical PDF is clearly separated from fiscal delivery and ATS', async ({ page }) => {
  await loginAndOpenInvoices(page)
  await page.getByRole('button', { name: 'Cargar histórica' }).click()
  await expect(page.getByRole('heading', { name: 'Factura histórica' })).toBeVisible()
  await page.getByLabel('RIDE PDF de SkyFranquicias').setInputFiles({
    name: 'factura-historica.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4\n%%EOF'),
  })
  await page.getByRole('button', { name: 'Crear venta histórica' }).click()

  await expect(page.getByRole('heading', { name: 'Factura 000000123' })).toBeVisible()
  await expect(page.getByText('HISTÓRICA · XML FALTANTE', { exact: true })).toBeVisible()
  await expect(page.getByText(/El XML no está disponible y el documento no entra al ATS/)).toBeVisible()
  await expect(page.getByText('Documento histórico: no se retransmite al SRI.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Preparar correo' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Nota de crédito' })).toHaveCount(0)
  await expectNoA11yViolations(page)
})

test('invoice status badges are visible and labelled per document', async ({ page }) => {
  await loginAndOpenInvoices(page)
  await expect(page.getByText('BORRADOR', { exact: true })).toBeVisible()
  await expect(page.getByText('AUTORIZADA', { exact: true })).toBeVisible()
  await expect(page.getByText('RECHAZADA', { exact: true })).toBeVisible()
})

test('new invoice full-page view is keyboard reachable, labelled and passes axe', async ({ page }) => {
  await loginAndOpenInvoices(page)

  const newInvoiceButton = page.getByRole('button', { name: 'Nueva factura' })
  await newInvoiceButton.focus()
  await page.keyboard.press('Enter')

  await expect(page.getByRole('heading', { name: 'Nueva factura', level: 1 })).toBeVisible()
  await expect(page.getByLabel('Cliente')).toBeVisible()
  await expect(page.getByLabel('Establecimiento')).toBeVisible()
  await expect(page.getByLabel('Punto de emisión')).toBeVisible()
  await expect(page.getByLabel('Fecha de emisión')).toBeVisible()
  await expect(page.getByLabel('Producto 1')).toBeVisible()
  await expectNoA11yViolations(page)

  await page.getByRole('button', { name: 'Agregar línea' }).click()
  await expect(page.getByLabel('Producto 2')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Quitar línea 2' })).toBeVisible()

  await page.getByRole('button', { name: 'Cancelar' }).click()
  await expect(page.getByRole('heading', { name: 'Nueva factura' })).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'Facturas', exact: true })).toBeVisible()
})

test('creating a draft shows backend totals and opens detail with SRI status', async ({ page }) => {
  await loginAndOpenInvoices(page)

  await page.getByRole('button', { name: 'Nueva factura' }).click()
  await pickCombobox(page, 'Producto 1', product.name)
  await page.getByRole('button', { name: 'Guardar' }).click()

  // Toast de éxito (Sprint 8) al crear la factura.
  await expect(page.locator('.toast-success')).toContainText(
    `Factura ${draftInvoice.sequential} creada`,
  )

  const detail = page.getByLabel(`Factura ${draftInvoice.sequential}`, { exact: true })
  await expect(page.getByRole('heading', { name: `Factura ${draftInvoice.sequential}` })).toBeVisible()
  await expect(detail.getByTestId('invoice-total')).toContainText('$22,43')
  await expect(detail.getByText('Sin intentos de transmisión todavía.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Emitir' })).toBeEnabled()
  await expect(page.getByRole('button', { name: 'Nota de crédito' })).toHaveCount(0)
  await expectNoA11yViolations(page)
})

test('authorized invoice detail shows SRI transmission, artifacts and credit note action', async ({
  page,
}) => {
  await loginAndOpenInvoices(page)
  await page
    .getByRole('row', { name: new RegExp(authorizedInvoice.sequential) })
    .getByRole('button', { name: 'Ver' })
    .click()

  const detail = page.getByLabel(`Factura ${authorizedInvoice.sequential}`, { exact: true })
  await expect(page.getByRole('heading', { name: `Factura ${authorizedInvoice.sequential}` })).toBeVisible()
  await expect(detail.getByLabel('Estado SRI').getByText('AUTORIZADA', { exact: true })).toBeVisible()
  await expect(detail.getByText('Comprobante autorizado')).toBeVisible()
  await expect(detail.getByText(authorizedInvoice.sriTransmission.authorizationNumber)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Descargar XML firmado' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Descargar RIDE PDF' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Preparar correo' })).toBeVisible()
  await page.getByRole('button', { name: 'Preparar correo' }).click()
  const emailDialog = page.getByRole('dialog', { name: 'Enviar factura por correo' })
  await expect(emailDialog).toContainText('Contabilidad B2B · contabilidad@b2b.com.ec')
  await expect(emailDialog).toContainText('Fecha límite de pago')
  await expect(emailDialog).toContainText('31 días')
  await expect(emailDialog).toContainText('FACTURA-001-001-000000002.xml')
  await page.keyboard.press('Escape')
  await expect(page.getByRole('button', { name: 'Volver al listado' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Emitir' })).toBeDisabled()

  const creditNoteButton = page.getByRole('button', { name: 'Nota de crédito' })
  await creditNoteButton.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { name: 'Nueva nota de crédito', level: 1 })).toBeVisible()
  await expectNoA11yViolations(page)
})

test('RIDE opens in the in-app PDF viewer and returns focus when it closes', async ({ page }) => {
  await loginAndOpenInvoices(page)
  await page
    .getByRole('row', { name: new RegExp(authorizedInvoice.sequential) })
    .getByRole('button', { name: 'Ver' })
    .click()

  const viewRide = page.getByRole('button', { name: 'Ver RIDE' })
  await viewRide.click()
  const dialog = page.getByRole('dialog', { name: 'RIDE autorizado' })
  await expect(dialog).toBeVisible()
  await expect(dialog.locator('iframe[title="FACTURA-001001000000002.pdf"]')).toHaveAttribute(
    'src',
    /disposition=inline/,
  )
  await expect(dialog.getByRole('button', { name: 'Abrir en otra pestaña' })).toBeVisible()

  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(viewRide).toBeFocused()
})

test('rejected invoice shows an accessible SRI message', async ({ page }) => {
  await loginAndOpenInvoices(page)
  await page
    .getByRole('row', { name: new RegExp(rejectedInvoice.sequential) })
    .getByRole('button', { name: 'Ver' })
    .click()

  const detail = page.getByLabel(`Factura ${rejectedInvoice.sequential}`, { exact: true })
  await expect(detail.getByLabel('Estado SRI').getByText('RECHAZADA', { exact: true })).toBeVisible()
  await expect(detail.getByText('RUC del cliente no encontrado')).toBeVisible()
})

test('duplicate creates a separate draft from a rejected invoice', async ({ page }) => {
  await loginAndOpenInvoices(page)
  await page
    .getByRole('row', { name: new RegExp(rejectedInvoice.sequential) })
    .getByRole('button', { name: 'Ver' })
    .click()

  await page.getByRole('button', { name: 'Duplicar' }).click()
  await expect(page.getByRole('heading', { name: `Factura ${duplicatedInvoice.sequential}` })).toBeVisible()
  await expect(page.getByText('BORRADOR', { exact: true })).toBeVisible()
  await expect(page.getByText('RUC del cliente no encontrado')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Emitir' })).toBeEnabled()
})

test('contracts are reachable from navigation and customer details', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Continuar' }).click()
  await navigateToSection(page, 'Contratos')
  await expect(page.getByRole('heading', { name: 'Contratos', exact: true })).toBeVisible()
  await expect(page.getByText('CT-2026-001', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Abrir' }).click()
  await expect(page.getByRole('heading', { name: 'Servicios administrados AWS' })).toBeVisible()
  await expect(page.getByLabel('PDF terminado')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Cortes AWS' })).toBeVisible()
  await expectNoA11yViolations(page)
})

test('invoices screens reflow at 320 CSS px and at 200% zoom without horizontal scroll', async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 900 })
  await loginAndOpenInvoices(page)
  await expectNoHorizontalOverflow(page)

  await page.getByRole('button', { name: 'Nueva factura' }).click()
  await expect(page.getByRole('heading', { name: 'Nueva factura', level: 1 })).toBeVisible()
  await expectNoHorizontalOverflow(page)

  await page.setViewportSize({ width: 640, height: 900 })
  await page.evaluate(() => {
    document.documentElement.style.zoom = '200%'
  })
  await expect(page.getByRole('heading', { name: 'Nueva factura', level: 1 })).toBeVisible()
  await expectNoHorizontalOverflow(page)
})
