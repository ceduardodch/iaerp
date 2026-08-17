import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { mockDashboardEndpoints } from './dashboard-mocks'
import { navigateToSection } from './navigation'

const context = {
  tenantId: '11111111-1111-4111-8111-111111111111',
  ruc: '1799999999001',
  name: 'IAERP Demo',
  roles: ['owner'],
  scopes: [
    'context:read',
    'parties:read',
    'products:read',
    'receivables:read',
    'receivables:write',
    'receivables:notify',
  ],
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

const overdueReceivable = {
  id: '51515151-5151-4515-8515-515151515151',
  partyId: customer.id,
  status: 'OVERDUE',
  originalAmount: '150.00',
  openAmount: '150.00',
  currency: 'USD',
  // Fecha fija muy en el pasado: el bucket "90+" no debe depender del reloj real de CI.
  dueDate: '2020-01-01',
  aging: { bucket: '90+' as const, daysOverdue: 2400 },
  collectionEnabled: false,
}

const partialReceivable = {
  id: '61616161-6161-4616-8616-616161616161',
  partyId: customer.id,
  status: 'PARTIAL',
  originalAmount: '300.00',
  openAmount: '120.00',
  currency: 'USD',
  dueDate: '2026-08-15',
  aging: { bucket: 'CURRENT' as const, daysOverdue: 0 },
  collectionEnabled: true,
}

const settledReceivable = {
  id: '71717171-7171-4717-8717-717171717171',
  partyId: customer.id,
  status: 'SETTLED',
  originalAmount: '80.00',
  openAmount: '0.00',
  currency: 'USD',
  // La fecha histórica se conserva, pero una cuenta sin saldo no tiene aging pendiente.
  dueDate: '2020-01-01',
  aging: null,
  collectionEnabled: false,
}

const updatedAfterPayment = {
  ...overdueReceivable,
  status: 'PARTIAL',
  openAmount: '50.00',
}

async function mockApi(page: Page) {
  let currentReceivables = [overdueReceivable, partialReceivable, settledReceivable]
  let collectionHistory = [{
    id: '82828282-8282-4828-8828-828282828282', kind: 'REMINDER' as const, occurredAt: '2026-07-05T12:00:00Z',
    channel: 'WHATSAPP', outcome: 'SENT', note: null, recipient: '+593999999999', deliveryStatus: 'READ', deliveredAt: '2026-07-05T12:01:00Z', readAt: '2026-07-05T12:02:00Z',
  }]
  await page.route('**/api/v1/dev/token', (route) =>
    route.fulfill({ json: { accessToken: 'test-token' } }),
  )
  await page.route('**/api/v1/context', (route) => route.fulfill({ json: context }))
  await page.route('**/api/v1/parties', (route) => route.fulfill({ json: [customer] }))
  await page.route('**/api/v1/products', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/v1/tax-categories', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/v1/establishments', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/v1/emission-points', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/v1/receivables**', (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    if (route.request().url().includes('/collection-history')) {
      return route.fulfill({ json: collectionHistory })
    }
    return route.fulfill({
      json: currentReceivables,
    })
  })
  await page.route('**/api/v1/receivables/collections', (route) =>
    route.fulfill({
      json: {
        fromDate: null,
        toDate: null,
        cashAmount: '400.00',
        cashCount: 2,
        retentionAmount: '100.00',
        retentionCount: 1,
        creditAmount: '0.00',
        creditCount: 0,
        settledAmount: '500.00',
        retentionShare: '20.00',
      },
    }),
  )
  await page.route('**/api/v1/receivables/collection-policy', (route) =>
    route.fulfill({
      json: {
        enabled: true,
        offsetsDays: [-3, 0, 3, 7, 15],
        channels: ['EMAIL'],
        sendHour: 9,
        emailTemplateId: 'payment_reminder',
        whatsappTemplateId: 'payment_reminder',
        emailSubject: 'Recordatorio de pago - {{empresa}}',
        emailBody: 'Estimado/a {{cliente}}, podemos acordar un plan de pagos.',
        paymentInstructions: 'BANCO SINTETICO\nCUENTA CORRIENTE\n0000000000',
        updatedAt: '2026-07-05T12:00:00Z',
      },
    }),
  )
  await mockDashboardEndpoints(page)
  await page.route(`**/api/v1/receivables/${overdueReceivable.id}/payments`, (route) => {
    if (route.request().method() === 'POST') {
      currentReceivables = currentReceivables.map((item) =>
        item.id === updatedAfterPayment.id ? updatedAfterPayment : item,
      )
      return route.fulfill({ status: 201, json: updatedAfterPayment })
    }
    return route.fallback()
  })
  await page.route(`**/api/v1/receivables/${overdueReceivable.id}/collection-policy`, (route) => {
    if (route.request().method() === 'PUT') {
      currentReceivables = currentReceivables.map((item) =>
        item.id === overdueReceivable.id ? { ...item, collectionEnabled: true } : item,
      )
      return route.fulfill({ json: { ...overdueReceivable, collectionEnabled: true } })
    }
    return route.fallback()
  })
  await page.route(`**/api/v1/receivables/${overdueReceivable.id}/reminders`, (route) => {
    if (route.request().method() === 'POST') {
      return route.fulfill({
        status: 202,
        json: {
          operationId: '81818181-8181-4818-8818-818181818181',
          status: 'ACCEPTED',
          correlationId: 'corr-reminder-1',
          createdAt: '2026-07-05T12:00:00Z',
          expiresAt: '2026-07-05T13:00:00Z',
        },
      })
    }
    return route.fallback()
  })
  await page.route(`**/api/v1/receivables/${overdueReceivable.id}/contacts`, (route) =>
    {
      const contact = { id: '83838383-8383-4838-8838-838383838383', kind: 'CONTACT' as const, occurredAt: '2026-07-05T12:03:00Z', channel: 'CALL', outcome: 'CONTACTED', note: 'Cliente confirma revisión.', recipient: null, deliveryStatus: null, deliveredAt: null, readAt: null }
      collectionHistory = [contact, ...collectionHistory]
      return route.fulfill({ status: 201, json: contact })
    },
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

async function loginAndOpenReceivables(page: Page) {
  await page.goto('/')
  await page.getByRole('button', { name: 'Continuar' }).click()
  await expect(page.getByRole('heading', { name: 'IAERP Demo' })).toBeVisible()
  await navigateToSection(page, 'Cartera')
  await expect(page.getByRole('heading', { name: 'Cartera', exact: true })).toBeVisible()
}

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.addInitScript(() => sessionStorage.clear())
  await mockApi(page)
})

test('receivables list passes WCAG 2.1 AA automated checks', async ({ page }) => {
  await loginAndOpenReceivables(page)
  await expect(page.getByText(customer.name).first()).toBeVisible()
  await expectNoA11yViolations(page)
})

test('receivables defaults to pending accounts and keeps their aging visible', async ({ page }) => {
  await loginAndOpenReceivables(page)
  await expect(page.getByText('VENCIDA', { exact: true })).toBeVisible()
  await expect(page.getByText('PARCIAL', { exact: true })).toBeVisible()
  await expect(page.getByText('SALDADA', { exact: true })).toHaveCount(0)
  await expect(page.getByText('Más de 90 días', { exact: true })).toBeVisible()
})

test('settled receivable is available only when explicitly requested', async ({ page }) => {
  await loginAndOpenReceivables(page)
  await page.getByLabel('Filtrar por estado').selectOption('SETTLED')
  const settledRow = page.getByRole('row', {
    name: /\$80,00/,
  })
  await expect(settledRow.getByRole('cell').nth(6)).toHaveText('—')
  await expect(settledRow).not.toContainText('Más de 90 días')
  await expect(settledRow.getByRole('button', { name: /Registrar cobro/ })).toBeDisabled()
  await expect(settledRow.getByRole('button', { name: /correo de cobro/i })).toBeDisabled()
})

test('register payment full-page view is keyboard reachable, labelled and passes axe', async ({ page }) => {
  await loginAndOpenReceivables(page)

  const paymentButton = page.getByRole('button', { name: `Registrar cobro para ${customer.name}` }).first()
  await paymentButton.focus()
  await page.keyboard.press('Enter')

  await expect(page.getByRole('heading', { name: 'Registrar cobro', level: 1 })).toBeVisible()
  await expect(page.getByLabel('Monto en efectivo')).toBeVisible()
  await expect(page.getByLabel('Fecha de cobro')).toBeVisible()
  await expect(page.getByLabel('Método')).toBeVisible()
  await expectNoA11yViolations(page)

  await page.getByRole('button', { name: 'Agregar retención' }).click()
  await expect(page.getByLabel('Tipo de retención 1')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Quitar retención 1' })).toBeVisible()

  await page.getByRole('button', { name: 'Agregar descuento' }).click()
  await expect(page.getByLabel('Monto de descuento 1')).toBeVisible()
  await expectNoA11yViolations(page)

  await page.getByRole('button', { name: 'Cancelar' }).click()
  await expect(page.getByRole('heading', { name: 'Registrar cobro' })).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'Cartera', exact: true })).toBeVisible()
})

test('registering a payment shows the backend-computed balance, never client math', async ({ page }) => {
  await loginAndOpenReceivables(page)

  await page
    .getByRole('button', { name: `Registrar cobro para ${customer.name}` })
    .first()
    .click()
  await page.getByLabel('Monto en efectivo').fill('100.00')
  await page.getByRole('button', { name: 'Guardar' }).click()

  await expect(page.getByRole('heading', { name: 'Cartera', exact: true })).toBeVisible()
  const updatedRow = page.getByRole('row', { name: /\$50,00/ })
  await expect(updatedRow).toBeVisible()
  await expectNoA11yViolations(page)
})

test('send collection email view is keyboard reachable, labelled and passes axe', async ({ page }) => {
  await loginAndOpenReceivables(page)

  const reminderButton = page
    .getByRole('button', { name: `Enviar correo de cobro a ${customer.name}` })
    .first()
  await reminderButton.focus()
  await page.keyboard.press('Enter')

  await expect(page.getByRole('heading', { name: 'Enviar correo de cobro', level: 1 })).toBeVisible()
  await expect(page.getByLabel('Canal')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Enviar ahora', exact: true })).toBeDisabled()
  await expect(page.getByText('Esta factura no permite mensajes de cobranza.')).toBeVisible()
  await expectNoA11yViolations(page)

  const enableCollection = page.getByRole('button', { name: 'Permitir cobranza para esta factura' })
  await enableCollection.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByText('Cobranza permitida. Ya puedes enviar o programar el correo.')).toBeVisible()
  await expect(page.getByLabel('Canal')).toBeFocused()
  await expect(page.getByRole('button', { name: 'Enviar ahora', exact: true })).toBeEnabled()

  await page.getByLabel('Programar para').fill('2026-08-20T09:00')
  await expect(page.getByText('Los correos programados usan la plantilla general configurada arriba.')).toBeVisible()
  await expect(page.getByLabel('Mensaje personalizado')).toHaveCount(0)
  await page.getByLabel('Programar para').fill('')
  await expect(page.getByLabel('Mensaje personalizado')).toBeVisible()

  // Ya no se pide escribir un id de plantilla: se muestra la configurada, con
  // sus datos bancarios, y se envía directo.
  const preview = page.getByRole('region', { name: 'Plantilla que se enviará' })
  await expect(preview).toContainText('Recordatorio de pago - {{empresa}}')
  await expect(preview).toContainText('plan de pagos')
  await expect(preview).toContainText('BANCO SINTETICO')

  await page.getByRole('button', { name: 'Enviar ahora', exact: true }).click()

  await expect(page.getByRole('heading', { name: 'Enviar correo de cobro' })).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'Cartera', exact: true })).toBeVisible()
})

test('collection history shows verified delivery and records a manual contact', async ({ page }) => {
  await loginAndOpenReceivables(page)
  await page.getByRole('button', { name: `Ver historia de cobranza de ${customer.name}` }).first().click()

  await expect(page.getByRole('heading', { name: 'Historia de cobranza', level: 1 })).toBeVisible()
  await expect(page.getByText('Enviado · Leído', { exact: true })).toBeVisible()
  await expect(page.getByLabel('Canal')).toBeVisible()
  await expect(page.getByLabel('Resultado')).toBeVisible()
  await page.getByRole('textbox', { name: 'Nota' }).fill('Cliente confirma revisión.')
  await expectNoA11yViolations(page)
  await page.getByRole('button', { name: 'Guardar', exact: true }).click()
  await expect(page.getByText('Cliente confirma revisión.')).toBeVisible()
})

test('collections strip separates cash from retentions', async ({ page }) => {
  await loginAndOpenReceivables(page)

  // Una retención baja el saldo pero no es caja: debe verse aparte del dinero.
  const strip = page.getByRole('region', { name: 'Desglose del cobro' })
  await expect(strip).toContainText('Cobrado en dinero')
  await expect(strip).toContainText('$400,00')
  await expect(strip).toContainText('Retenciones')
  await expect(strip).toContainText('$100,00')
  await expect(strip).toContainText('20,00 % del cobro fue retención')
})

test('status filter narrows the receivables list', async ({ page }) => {
  await loginAndOpenReceivables(page)
  await page.getByLabel('Filtrar por estado').selectOption('SETTLED')
  await expect(page.getByRole('cell', { name: 'SALDADA' })).toBeVisible()
})

test('bank statement preview registers only the confirmed exact invoice match', async ({
  page,
}) => {
  let requestCount = 0
  await page.route('**/api/v1/finance/bank-statements', (route) => {
    requestCount += 1
    const registered = requestCount > 1
    return route.fulfill({
      json: {
        period: '2026-07',
        fileName: 'estado.txt',
        sourceSha256: 'a'.repeat(64),
        accountMasked: '****8731',
        totalRows: 3,
        creditRows: 2,
        debitRows: 1,
        outsidePeriodCreditCount: 0,
        outsidePeriodDebitCount: 0,
        matchedCount: 1,
        unmatchedCreditCount: 1,
        ignoredDebitCount: 1,
        payableMatchedCount: 0,
        unmatchedDebitCount: 1,
        ruleSuggestionCount: 0,
        alreadyImportedCount: 0,
        manualCorrectionCount: 0,
        matches: [{
          transactionId: 'b'.repeat(64),
          paymentDate: '2026-07-14',
          reference: '22525496-2451',
          description: 'TRANSFERENCIA RECIBIDA',
          amount: '136.50',
          receivableId: overdueReceivable.id,
          invoiceSequential: '000000961',
          originalAmount: '150.00',
          retentionTotal: '13.50',
          replacesManualPayment: false,
          status: registered ? 'REGISTERED' : 'MATCHED',
          detail: registered ? 'Cobro registrado' : 'Lista para registrar',
        }],
        manualCorrections: [],
        debitMatches: [],
        debitSuggestions: [],
      },
    })
  })
  await loginAndOpenReceivables(page)
  await page.getByRole('button', { name: 'Cargar estado bancario' }).click()
  await expect(page.getByRole('heading', { name: 'Conciliar banco', level: 1 })).toBeVisible()
  await page.getByLabel('Estado de cuenta bancario').setInputFiles({
    name: 'estado.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('estado bancario sintetico'),
  })
  await page.getByRole('button', { name: 'Revisar movimientos' }).click()
  await expect(page.getByRole('cell', { name: '000000961' })).toBeVisible()
  await expect(page.getByText('1 cobro · 0 pagos · 0 gastos sugeridos')).toBeVisible()
  await expectNoA11yViolations(page)

  await page.getByRole('button', { name: 'Confirmar 1 cambio' }).click()
  await expect(page.getByText('Cobro registrado')).toBeVisible()
  await expect(page.getByText(/Solo los cobros indicados como registrados/)).toBeVisible()
  expect(requestCount).toBe(2)
})

test('historical retention preview shows the XML issue date before correction', async ({
  page,
}) => {
  await page.route('**/api/v1/receivables/retention-batch', (route) =>
    route.fulfill({
      json: {
        items: [{
          fileName: 'retencion-junio.xml',
          receivableId: overdueReceivable.id,
          authorizationNumber: '6'.repeat(49),
          supportingDocument: '001001000000951',
          invoiceSequential: '000000951',
          issueDate: '2025-06-15',
          total: '13.50',
          status: 'MATCHED',
          detail: 'Corregirá la fecha desde el XML',
        }],
      },
    }),
  )
  await loginAndOpenReceivables(page)
  await page.getByRole('button', { name: 'Cargar retenciones XML' }).click()
  await page.getByLabel('XML de comprobantes de retención').setInputFiles({
    name: 'retencion-junio.xml',
    mimeType: 'application/xml',
    buffer: Buffer.from('<retencion/>'),
  })
  await page.getByRole('button', { name: 'Revisar XML' }).click()

  const row = page.getByRole('row', { name: /retencion-junio\.xml/ })
  await expect(row).toContainText('2025-06-15')
  await expect(row).toContainText('Corregirá la fecha desde el XML')
  await expect(page.getByRole('button', { name: 'Registrar 1 retención' })).toBeVisible()
  await expectNoA11yViolations(page)
})

test('receivables screens reflow at 320 CSS px and at 200% zoom without horizontal scroll', async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 900 })
  await loginAndOpenReceivables(page)
  await expectNoHorizontalOverflow(page)

  const registerPaymentButton = page
    .getByRole('button', { name: `Registrar cobro para ${customer.name}` })
    .first()
  await expect(registerPaymentButton).toBeInViewport()
  await registerPaymentButton.click()
  await expect(page.getByRole('heading', { name: 'Registrar cobro', level: 1 })).toBeVisible()
  await expectNoHorizontalOverflow(page)

  await page.setViewportSize({ width: 640, height: 900 })
  await page.evaluate(() => {
    document.documentElement.style.zoom = '200%'
  })
  await expect(page.getByRole('heading', { name: 'Registrar cobro', level: 1 })).toBeVisible()
  await expectNoHorizontalOverflow(page)
})
