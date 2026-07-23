import { expect, test, type Page } from '@playwright/test'

const tenantNorte = '11111111-1111-4111-8111-111111111111'
const ownerEmail = 'owner@iaerp.local'

async function login(page: Page, tenantId: string) {
  await page.goto('/')
  await page.getByLabel('Correo').fill(ownerEmail)
  await page.getByLabel('ID de empresa').fill(tenantId)
  await page.getByRole('button', { name: 'Continuar' }).click()
}

type SalesDocument = {
  id: string
  sequential: string
  status: string
  subtotal: string
  tax: string
  total: string
}

function formatAmount(value: string) {
  return new Intl.NumberFormat('es-EC', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Number(value))
}

test.describe.configure({ mode: 'serial' })

test('creates an invoice draft with two lines and a discount; UI shows exactly the backend totals', async ({
  page,
}) => {
  const suffix = crypto.randomUUID().slice(0, 8)
  const productName = `Producto Factura E2E ${suffix}`

  await login(page, tenantNorte)
  await expect(page.getByRole('heading', { name: 'IAERP Demo Norte' })).toBeVisible()

  // Producto propio de este test para no depender de datos sintéticos compartidos.
  await page.getByRole('button', { name: 'Productos' }).click()
  await page.getByRole('button', { name: 'Nuevo producto' }).click()
  await page.getByLabel('Nombre').fill(productName)
  await page.getByLabel('Código interno').fill(`FACT-E2E-${suffix}`)
  await page.getByLabel('Precio unitario').fill('10.250000')
  await page.getByRole('button', { name: 'Guardar' }).click()
  await expect(page.getByRole('heading', { name: productName })).toBeVisible()

  await page.getByRole('button', { name: 'Facturas' }).click()
  await expect(page.getByRole('heading', { name: 'Facturas', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Nueva factura' }).first().click()

  await page.getByLabel('Cliente').selectOption({ label: 'Cliente Sintetico Norte' })
  const firstProductId = await page
    .getByLabel('Producto 1')
    .locator('option', { hasText: productName })
    .getAttribute('value')
  await page.getByLabel('Producto 1').selectOption(firstProductId ?? '')
  await page.getByLabel('Cantidad').fill('2')
  await page.getByLabel('Descuento').fill('1.50')

  await page.getByRole('button', { name: 'Agregar línea' }).click()
  const secondProductId = await page
    .getByLabel('Producto 2')
    .locator('option', { hasText: /^Servicio Norte · IVA 15,00 %$/ })
    .getAttribute('value')
  await page.getByLabel('Producto 2').selectOption(secondProductId ?? '')
  await page.getByLabel('Cantidad').nth(1).fill('1')

  const draftResponse = page.waitForResponse(
    (response) => response.url().endsWith('/api/v1/invoices') && response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: 'Guardar' }).click()
  const response = await draftResponse
  expect(response.ok()).toBeTruthy()
  const invoice = (await response.json()) as SalesDocument

  // Los totales que exhibe la UI deben ser exactamente los que devolvio el
  // backend en la respuesta de creacion del borrador: la UI nunca calcula
  // impuestos ni totales, solo los muestra (regla del sprint).
  const detail = page.getByLabel(`Factura ${invoice.sequential}`, { exact: true })
  await expect(page.getByRole('heading', { name: `Factura ${invoice.sequential}` })).toBeVisible()
  await expect(detail.getByTestId('invoice-subtotal')).toContainText(`$${formatAmount(invoice.subtotal)}`)
  await expect(detail.getByTestId('invoice-tax')).toContainText(`$${formatAmount(invoice.tax)}`)
  await expect(detail.getByTestId('invoice-total')).toContainText(`$${formatAmount(invoice.total)}`)
  await expect(detail.getByText('BORRADOR', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: 'Volver al listado' }).click()
  await expect(page.getByRole('cell', { name: invoice.sequential, exact: true })).toBeVisible()
  await expect(
    page.getByRole('row', { name: new RegExp(invoice.sequential) }).getByText(`$${formatAmount(invoice.total)}`),
  ).toBeVisible()

  await page
    .getByRole('row', { name: new RegExp(invoice.sequential) })
    .getByRole('button', { name: 'Ver' })
    .click()
  await expect(page.getByRole('heading', { name: `Factura ${invoice.sequential}` })).toBeVisible()
  await expect(page.getByText('Sin intentos de transmisión todavía.')).toBeVisible()
})
