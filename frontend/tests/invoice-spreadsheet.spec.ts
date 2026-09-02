import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

import { pickCombobox } from './combobox'
import { mockDashboardEndpoints } from './dashboard-mocks'
import { navigateToSection } from './navigation'

const product = {
  id: '16161616-1616-4616-8616-161616161616',
  name: 'Servicio de prueba',
  unitPrice: '10.000000',
  taxCategoryId: '99999999-9999-4999-8999-999999999999',
}

async function mockApi(page: Page) {
  const parties = [{
    id: '14141414-1414-4414-8414-141414141414',
    name: 'Cliente de prueba',
    identificationType: 'CEDULA',
    identificationNumber: '1712345678',
    roles: ['CUSTOMER'],
  }]
  const products = [product]
  const establishments = [{
    id: 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
    code: '001',
    name: 'Matriz',
    address: 'Pifo',
    active: true,
  }]
  const emissionPoints = [{
    id: '12121212-1212-4212-8212-121212121212',
    establishmentId: establishments[0].id,
    code: '001',
    active: true,
  }]
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
      scopes: ['context:read', 'parties:read', 'parties:write', 'products:read', 'products:write', 'organization:read', 'organization:write', 'invoices:read', 'invoices:write'],
      automationWritesEnabled: false,
      defaultPaymentTermsDays: 0,
    },
  }))
  await page.route('**/api/v1/parties', async (route) => {
    if (route.request().method() === 'POST') {
      const payload = route.request().postDataJSON()
      const created = { id: '24242424-2424-4424-8424-242424242424', ...payload }
      parties.push(created)
      await route.fulfill({ status: 201, json: created })
      return
    }
    await route.fulfill({ json: parties })
  })
  await page.route('**/api/v1/products', async (route) => {
    if (route.request().method() === 'POST') {
      const payload = route.request().postDataJSON()
      const created = { id: '26262626-2626-4626-8626-262626262626', ...payload }
      products.push(created)
      await route.fulfill({ status: 201, json: created })
      return
    }
    await route.fulfill({ json: products })
  })
  await page.route('**/api/v1/tax-categories', (route) => route.fulfill({
    json: [{
      id: product.taxCategoryId,
      sriCode: '4',
      name: 'IVA 15%',
      rate: '15.000000',
      active: true,
    }],
  }))
  await page.route('**/api/v1/establishments', async (route) => {
    if (route.request().method() === 'POST') {
      const payload = route.request().postDataJSON()
      const created = {
        id: 'abababab-abab-4bab-8bab-abababababab',
        ...payload,
        active: true,
      }
      establishments.push(created)
      await route.fulfill({ status: 201, json: created })
      return
    }
    await route.fulfill({ json: establishments })
  })
  await page.route('**/api/v1/establishments/*', async (route) => {
    const payload = route.request().postDataJSON()
    establishments[0] = { ...establishments[0], ...payload }
    await route.fulfill({ json: establishments[0] })
  })
  await page.route('**/api/v1/emission-points', async (route) => {
    if (route.request().method() === 'POST') {
      const payload = route.request().postDataJSON()
      const created = { id: 'cdcdcdcd-cdcd-4dcd-8dcd-cdcdcdcdcdcd', ...payload, active: true }
      emissionPoints.push(created)
      await route.fulfill({ status: 201, json: created })
      return
    }
    await route.fulfill({ json: emissionPoints })
  })
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
  await navigateToSection(page, 'Facturas')
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
  await pickCombobox(page, 'Producto 1', product.name)
  await page.getByLabel('Cantidad 1').fill('2')

  const firstRow = page.locator('.invoice-spreadsheet tbody tr').first()
  await expect(firstRow.locator('td').nth(6)).toContainText('$23,00', { timeout: 15_000 })
  await expect(page.locator('.invoice-spreadsheet tfoot')).toContainText('$23,00', { timeout: 15_000 })
})

test('marks a zero quantity as invalid', async ({ page }) => {
  const quantity = page.getByLabel('Cantidad 1')
  await quantity.fill('0')

  await expect(quantity).toHaveAttribute('aria-invalid', 'true')
  await expect(quantity).toHaveClass(/cell-invalid/)
})

test('creates and selects a customer without leaving the invoice', async ({ page }) => {
  await page.getByRole('button', { name: 'Crear cliente' }).click()
  const dialog = page.getByRole('dialog', { name: 'Crear cliente' })
  await dialog.getByLabel('Nombre o razón social').fill('Cliente rápido')
  await dialog.getByLabel('Número').fill('1799999999002')
  await dialog.getByRole('button', { name: 'Crear y seleccionar' }).click()

  await expect(dialog).toBeHidden()
  await expect(page.getByLabel('Cliente')).toHaveValue('Cliente rápido')
  await expect(page.getByRole('status')).toContainText('Cliente rápido creado y seleccionado')
})

test('keeps keyboard focus and accessibility in the quick customer modal', async ({ page }) => {
  const trigger = page.getByRole('button', { name: 'Crear cliente' })
  await trigger.focus()
  await trigger.press('Enter')
  const dialog = page.getByRole('dialog', { name: 'Crear cliente' })
  await expect(dialog.getByLabel('Nombre o razón social')).toBeFocused()
  const results = await new AxeBuilder({ page }).include('.erp-modal').analyze()
  expect(results.violations).toEqual([])
  if ((page.viewportSize()?.width ?? 1000) <= 760) {
    for (const button of await dialog.getByRole('button').all()) {
      const box = await button.boundingBox()
      expect(box?.height).toBeGreaterThanOrEqual(44)
      expect(box?.width).toBeGreaterThanOrEqual(44)
    }
  }
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(trigger).toBeFocused()
})

test('creates and adds a product without losing the invoice draft', async ({ page }) => {
  await page.getByLabel('Cantidad 1').fill('3')
  await page.getByLabel('Descuento 1').fill('1.25')
  const issueDate = await page.getByLabel('Fecha de emisión').inputValue()
  await page.getByRole('button', { name: 'Crear producto o servicio' }).click()
  const dialog = page.getByRole('dialog', { name: 'Crear producto o servicio' })
  await dialog.getByLabel('Nombre').fill('Servicio rápido')
  await dialog.getByLabel('Precio unitario').fill('25')
  const results = await new AxeBuilder({ page }).include('.erp-modal').analyze()
  expect(results.violations).toEqual([])
  await dialog.getByRole('button', { name: 'Crear y agregar' }).click()

  await expect(dialog).toBeHidden()
  await expect(page.getByLabel('Producto 1')).toHaveValue('Servicio rápido')
  await expect(page.getByLabel('Precio unitario 1')).toHaveValue('25')
  await expect(page.getByLabel('Cantidad 1')).toHaveValue('3')
  await expect(page.getByLabel('Descuento 1')).toHaveValue('1.25')
  await expect(page.getByLabel('Fecha de emisión')).toHaveValue(issueDate)
})

test('does not close a quick modal while the create request is pending', async ({ page }) => {
  await page.route('**/api/v1/parties', async (route) => {
    if (route.request().method() !== 'POST') {
      await route.fallback()
      return
    }
    await new Promise((resolve) => setTimeout(resolve, 500))
    const payload = route.request().postDataJSON()
    await route.fulfill({
      status: 201,
      json: { id: '34343434-3434-4434-8434-343434343434', ...payload },
    })
  })
  await page.getByRole('button', { name: 'Crear cliente' }).click()
  const dialog = page.getByRole('dialog', { name: 'Crear cliente' })
  await dialog.getByLabel('Nombre o razón social').fill('Cliente pendiente')
  await dialog.getByLabel('Número').fill('1799999999003')
  await dialog.getByRole('button', { name: 'Crear y seleccionar' }).click()

  await expect(dialog.getByRole('button', { name: 'Cerrar ventana' })).toBeDisabled()
  await page.keyboard.press('Escape')
  await expect(dialog).toBeVisible()
  await expect(dialog).toBeHidden()
  await expect(page.getByLabel('Cliente')).toHaveValue('Cliente pendiente')
})

test('shows where Pifo comes from and updates the emission address in place', async ({ page }) => {
  const address = page.locator('.invoice-establishment-address')
  await expect(address).toContainText('Dirección del establecimiento:')
  await expect(address).toContainText('Pifo')
  await page.getByRole('button', { name: 'Editar dirección' }).click()
  const dialog = page.getByRole('dialog', { name: 'Editar establecimiento 001' })
  await dialog.getByLabel('Dirección del establecimiento').fill('Av. Nueva matriz 123, Quito')
  const results = await new AxeBuilder({ page }).include('.erp-modal').analyze()
  expect(results.violations).toEqual([])
  await dialog.getByRole('button', { name: 'Guardar dirección' }).click()

  await expect(dialog).toBeHidden()
  await expect(page.getByText('Av. Nueva matriz 123, Quito')).toBeVisible()
})

test('creates an establishment from Empresa with its fiscal code and address', async ({ page }) => {
  await navigateToSection(page, 'Empresa')
  await page.getByRole('button', { name: 'Nuevo establecimiento' }).click()
  const dialog = page.getByRole('dialog', { name: 'Nuevo establecimiento' })
  await dialog.getByLabel('Código fiscal').fill('002')
  await dialog.getByLabel('Nombre').fill('Sucursal Norte')
  await dialog.getByLabel('Dirección del establecimiento').fill('Av. Eloy Alfaro 123, Quito')
  const results = await new AxeBuilder({ page }).include('.erp-modal').analyze()
  expect(results.violations).toEqual([])
  await dialog.getByRole('button', { name: 'Crear establecimiento' }).click()

  await expect(dialog).toBeHidden()
  await expect(page.getByText('Sucursal Norte')).toBeVisible()
  await expect(page.getByText('Av. Eloy Alfaro 123, Quito')).toBeVisible()
})

test('creates an emission point from Empresa for its establishment', async ({ page }) => {
  await navigateToSection(page, 'Empresa')
  await page.getByRole('button', { name: 'Nuevo punto de emisión' }).click()
  const dialog = page.getByRole('dialog', { name: 'Nuevo punto de emisión' })
  await dialog.getByLabel('Establecimiento').selectOption({ label: '001 · Matriz' })
  await dialog.getByLabel('Código del punto').fill('002')
  const results = await new AxeBuilder({ page }).include('.erp-modal').analyze()
  expect(results.violations).toEqual([])
  await dialog.getByRole('button', { name: 'Crear punto de emisión' }).click()

  await expect(dialog).toBeHidden()
  await expect(page.getByRole('heading', { name: 'Puntos de emisión' })).toBeVisible()
  await expect(page.getByRole('listitem').filter({ hasText: '002001 · Matriz' })).toBeVisible()
  await expect(page.getByRole('status')).toContainText('Punto de emisión creado')
})

test('hides establishment editing from a read-only organization user', async ({ page }) => {
  await page.route('**/api/v1/context', (route) => route.fulfill({
    json: {
      tenantId: '11111111-1111-4111-8111-111111111111',
      ruc: '1799999999001',
      name: 'IAERP Demo',
      roles: ['reader'],
      scopes: ['context:read', 'organization:read', 'invoices:read'],
      automationWritesEnabled: false,
      defaultPaymentTermsDays: 0,
    },
  }))
  await page.reload()
  await page.getByRole('button', { name: 'Continuar' }).click()
  await navigateToSection(page, 'Empresa')

  await expect(page.getByRole('heading', { name: 'Empresa', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Editar dirección' })).toHaveCount(0)
})
