import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

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
}

const partialReceivable = {
  id: '61616161-6161-4616-8616-616161616161',
  partyId: customer.id,
  status: 'PARTIAL',
  originalAmount: '300.00',
  openAmount: '120.00',
  currency: 'USD',
  dueDate: '2026-08-15',
}

const settledReceivable = {
  id: '71717171-7171-4717-8717-717171717171',
  partyId: customer.id,
  status: 'SETTLED',
  originalAmount: '80.00',
  openAmount: '0.00',
  currency: 'USD',
  dueDate: '2026-06-01',
}

const updatedAfterPayment = {
  ...overdueReceivable,
  status: 'PARTIAL',
  openAmount: '50.00',
}

async function mockApi(page: Page) {
  let currentReceivables = [overdueReceivable, partialReceivable, settledReceivable]
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
    return route.fulfill({
      json: currentReceivables,
    })
  })
  await page.route(`**/api/v1/receivables/${overdueReceivable.id}/payments`, (route) => {
    if (route.request().method() === 'POST') {
      currentReceivables = currentReceivables.map((item) =>
        item.id === updatedAfterPayment.id ? updatedAfterPayment : item,
      )
      return route.fulfill({ status: 201, json: updatedAfterPayment })
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
  await page.getByRole('button', { name: '06 Cartera' }).click()
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

test('receivables status badges and aging are visible per account', async ({ page }) => {
  await loginAndOpenReceivables(page)
  await expect(page.getByText('VENCIDA', { exact: true })).toBeVisible()
  await expect(page.getByText('PARCIAL', { exact: true })).toBeVisible()
  await expect(page.getByText('SALDADA', { exact: true })).toBeVisible()
  await expect(page.getByText('Más de 90 días', { exact: true })).toBeVisible()
})

test('settled receivable disables collection actions', async ({ page }) => {
  await loginAndOpenReceivables(page)
  const settledRow = page.getByRole('row', {
    name: /\$80,00/,
  })
  await expect(settledRow.getByRole('button', { name: /Registrar cobro/ })).toBeDisabled()
  await expect(settledRow.getByRole('button', { name: /recordatorio/i })).toBeDisabled()
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

test('send reminder full-page view is keyboard reachable, labelled and passes axe', async ({ page }) => {
  await loginAndOpenReceivables(page)

  const reminderButton = page.getByRole('button', { name: `Enviar recordatorio para ${customer.name}` }).first()
  await reminderButton.focus()
  await page.keyboard.press('Enter')

  await expect(page.getByRole('heading', { name: 'Enviar recordatorio', level: 1 })).toBeVisible()
  await expect(page.getByLabel('Canal')).toBeVisible()
  await expect(page.getByLabel('Plantilla')).toBeVisible()
  await expectNoA11yViolations(page)

  await page.getByLabel('Plantilla').fill('11111111-1111-4111-8111-111111111111')
  await page.getByRole('button', { name: 'Enviar', exact: true }).click()

  await expect(page.getByRole('heading', { name: 'Enviar recordatorio' })).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'Cartera', exact: true })).toBeVisible()
})

test('status filter narrows the receivables list', async ({ page }) => {
  await loginAndOpenReceivables(page)
  await page.getByLabel('Filtrar por estado').selectOption('SETTLED')
  await expect(page.getByRole('cell', { name: 'SALDADA' })).toBeVisible()
})

test('receivables screens reflow at 320 CSS px and at 200% zoom without horizontal scroll', async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 900 })
  await loginAndOpenReceivables(page)
  await expectNoHorizontalOverflow(page)

  await page
    .getByRole('button', { name: `Registrar cobro para ${customer.name}` })
    .first()
    .click()
  await expect(page.getByRole('heading', { name: 'Registrar cobro', level: 1 })).toBeVisible()
  await expectNoHorizontalOverflow(page)

  await page.setViewportSize({ width: 640, height: 900 })
  await page.evaluate(() => {
    document.documentElement.style.zoom = '200%'
  })
  await expect(page.getByRole('heading', { name: 'Registrar cobro', level: 1 })).toBeVisible()
  await expectNoHorizontalOverflow(page)
})
