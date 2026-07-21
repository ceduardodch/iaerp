import { expect, test, type Page } from '@playwright/test'

const product = {
  id: '16161616-1616-4616-8616-161616161616',
  name: 'Servicio de prueba',
  unitPrice: '10.000000',
  taxCategoryId: '99999999-9999-4999-8999-999999999999',
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
  await page.route('**/api/v1/parties', (route) => route.fulfill({
    json: [{
      id: '14141414-1414-4414-8414-141414141414',
      name: 'Cliente de prueba',
      identificationType: 'CEDULA',
      identificationNumber: '1712345678',
      roles: ['CUSTOMER'],
    }],
  }))
  await page.route('**/api/v1/products', (route) => route.fulfill({ json: [product] }))
  await page.route('**/api/v1/tax-categories', (route) => route.fulfill({
    json: [{
      id: product.taxCategoryId,
      sriCode: '4',
      name: 'IVA 15%',
      rate: '15.000000',
      active: true,
    }],
  }))
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
  await page.route('**/api/v1/invoices/preview', (route) => route.fulfill({
    json: {
      lines: [{
        description: product.name,
        quantity: '2.000000',
        unitPrice: product.unitPrice,
        discount: '0.00',
        baseAmount: '20.00',
        taxCode: '4',
        taxRate: '15.000000',
        taxAmount: '3.00',
        total: '23.00',
      }],
      subtotal: '20.00',
      taxTotal: '3.00',
      total: '23.00',
    },
  }))
  await page.route('**/api/v1/invoices', (route) => route.fulfill({ json: [] }))
}

async function openInvoiceForm(page: Page) {
  await page.goto('/')
  await page.getByRole('button', { name: 'Continuar' }).click()
  await page.getByRole('button', { name: '04 Facturas' }).click()
  await page.getByRole('button', { name: 'Nueva factura' }).first().click()
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => sessionStorage.clear())
  await mockApi(page)
  await openInvoiceForm(page)
})

test('shows the editable invoice spreadsheet with its complete header', async ({ page }) => {
  const table = page.locator('.invoice-spreadsheet')
  await expect(table).toBeVisible()
  await expect(table.getByRole('columnheader')).toHaveText([
    'Producto',
    'Descripción',
    'Cantidad',
    'P. Unit.',
    'Desc.',
    'Base',
    'IVA',
    'Total',
    'Acción',
  ])
})

test('adds an invoice line', async ({ page }) => {
  const rows = page.locator('.invoice-spreadsheet tbody tr')
  await expect(rows).toHaveCount(1)

  await page.getByRole('button', { name: 'Agregar línea' }).click()
  await expect(rows).toHaveCount(2)
})

test('removes an invoice line when more than one exists', async ({ page }) => {
  const rows = page.locator('.invoice-spreadsheet tbody tr')
  await page.getByRole('button', { name: 'Agregar línea' }).click()
  await expect(rows).toHaveCount(2)

  await page.getByRole('button', { name: 'Quitar línea 2' }).click()
  await expect(rows).toHaveCount(1)
})

test('shows backend-calculated totals after editing quantity', async ({ page }) => {
  await page.getByLabel('Producto 1').selectOption(product.id)
  await page.getByLabel('Cantidad 1').fill('2')

  const firstRow = page.locator('.invoice-spreadsheet tbody tr').first()
  await expect(firstRow.locator('td').nth(7)).toContainText('$23,00', { timeout: 15_000 })
  await expect(page.locator('.invoice-spreadsheet tfoot')).toContainText('$23,00', { timeout: 15_000 })
})

test('marks a zero quantity as invalid', async ({ page }) => {
  const quantity = page.getByLabel('Cantidad 1')
  await quantity.fill('0')

  await expect(quantity).toHaveAttribute('aria-invalid', 'true')
  await expect(quantity).toHaveClass(/cell-invalid/)
})
