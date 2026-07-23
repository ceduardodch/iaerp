import { expect, test, type Page } from '@playwright/test'

// Sprint 6 (HU-17): el formulario de nueva factura muestra si la condición de
// pago aplicada proviene del override del cliente o del default de la empresa.

const customerWithOverride = {
  id: '14141414-1414-4414-8414-141414141414',
  name: 'Cliente con override',
  identificationType: 'CEDULA',
  identificationNumber: '1712345678',
  roles: ['CUSTOMER'],
  paymentTermsDays: 30,
}

const customerDefault = {
  id: '15151515-1515-4515-8515-151515151515',
  name: 'Cliente sin override',
  identificationType: 'CEDULA',
  identificationNumber: '1798765432',
  roles: ['CUSTOMER'],
  paymentTermsDays: null,
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
      scopes: ['context:read', 'parties:read', 'products:read', 'invoices:read', 'invoices:write'],
      automationWritesEnabled: false,
      defaultPaymentTermsDays: 0,
    },
  }))
  // El primer cliente de la lista (index 0) es el seleccionado por defecto: se
  // pone el que NO tiene override para verificar el badge "empresa" inicial.
  await page.route('**/api/v1/parties', (route) => route.fulfill({
    json: [customerDefault, customerWithOverride],
  }))
  await page.route('**/api/v1/products', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/v1/tax-categories', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/v1/establishments', (route) => route.fulfill({
    json: [{
      id: 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
      code: '001',
      name: 'Matriz',
      address: 'Dirección sintética',
      active: true,
    }],
  }))
  await page.route('**/api/v1/emission-points', (route) => route.fulfill({
    json: [{
      id: '12121212-1212-4212-8212-121212121212',
      establishmentId: 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
      code: '001',
      active: true,
    }],
  }))
  await page.route('**/api/v1/invoices', (route) => route.fulfill({ json: [] }))
}

async function openInvoiceForm(page: Page) {
  await page.goto('/')
  await page.getByRole('button', { name: 'Continuar' }).click()
  await page.getByRole('button', { name: 'Facturas' }).click()
  await page.getByRole('button', { name: 'Nueva factura' }).first().click()
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => sessionStorage.clear())
  await mockApi(page)
  await openInvoiceForm(page)
})

test('badge muestra "empresa" cuando el cliente no tiene override', async ({ page }) => {
  const badge = page.locator('.payment-terms-source')
  await expect(badge).toHaveAttribute('data-terms-source', 'company')
  await expect(badge).toContainText('predeterminada de la empresa')
})

test('badge cambia a "cliente" al elegir un cliente con override', async ({ page }) => {
  await page.getByLabel('Cliente').selectOption(customerWithOverride.id)

  const badge = page.locator('.payment-terms-source')
  await expect(badge).toHaveAttribute('data-terms-source', 'customer')
  await expect(badge).toContainText('configurada para este cliente')
})
