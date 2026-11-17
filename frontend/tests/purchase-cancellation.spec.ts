import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { navigateToSection } from './navigation'

const documentId = '22222222-2222-4222-8222-222222222222'
const payableId = '33333333-3333-4333-8333-333333333333'
const evidenceId = '44444444-4444-4444-8444-444444444444'
const purchase = {
  id: documentId, docType: 'FACTURA', issueDate: '2026-08-04', documentNumber: '001-001-000000009',
  supplierName: 'Proveedor sintético', supplierIdentification: '1799999999001', subtotal: '100.00',
  taxTotal: '15.00', total: '115.00', paymentMethods: ['20'], isPreliminary: false, taxes: [],
}
const payable = {
  id: payableId, fiscalDocumentId: documentId, supplierName: purchase.supplierName,
  description: 'Compra sintética', category: 'Servicios', documentType: 'INVOICE',
  documentNumber: purchase.documentNumber, issueDate: purchase.issueDate, dueDate: '2026-08-30',
  total: '115.00', openAmount: '115.00', currency: 'USD', status: 'OPEN',
  taxClassification: 'DEDUCTIBLE_PENDING_REVIEW', internalClassification: 'PENDING_REVIEW',
  evidenceStatus: 'FISCAL_XML', analyticAssignments: [],
}

async function setup(page: Page, { protectedMessage = '', canWrite = true, linked = true } = {}) {
  let cancelled = false
  let cancellation: Record<string, unknown> | null = null
  let uploadCount = 0
  const requests: Array<{ body: Record<string, unknown>; key?: string }> = []
  await page.route('**/api/v1/**', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/v1/dev/token', (route) => route.fulfill({ json: { accessToken: 'synthetic-token' } }))
  await page.route('**/api/v1/context', (route) => route.fulfill({ json: {
    tenantId: '11111111-1111-4111-8111-111111111111', name: 'Empresa sintética', roles: ['owner'],
    scopes: ['context:read', 'payables:read', ...(canWrite ? ['payables:write', 'tax:write'] : [])],
    automationWritesEnabled: false,
  } }))
  await page.route('**/api/v1/payables', (route) => route.fulfill({ json: linked ? [{
    ...payable, status: cancelled ? 'VOIDED' : 'OPEN', paymentStatus: 'OPEN',
    openAmount: cancelled ? '0.00' : '115.00',
  }] : [] }))
  await page.route('**/api/v1/tax/purchases', (route) => route.fulfill({ json: [{
    ...purchase, lifecycleStatus: cancelled ? 'CANCELLED' : 'ACTIVE', cancellation,
  }] }))
  await page.route('**/api/v1/tax/evidence', async (route) => {
    uploadCount += 1
    expect(route.request().headers()['content-type']).toContain('multipart/form-data')
    expect(route.request().postData()).toContain('SRI_CANCELLATION')
    await route.fulfill({ status: 201, json: { id: evidenceId } })
  })
  await page.route(`**/api/v1/tax/purchases/${documentId}/cancellation`, async (route) => {
    const body = route.request().postDataJSON()
    requests.push({ body, key: route.request().headers()['idempotency-key'] })
    if (protectedMessage) {
      await route.fulfill({ status: 409, json: { detail: protectedMessage } })
      return
    }
    cancelled = true
    cancellation = { ...body, actorId: 'synthetic-user', recordedAt: '2026-11-17T18:00:00Z' }
    await route.fulfill({ json: { ...purchase, lifecycleStatus: 'CANCELLED', cancellation } })
  })
  await page.route(`**/api/v1/tax/evidence/${evidenceId}/download`, (route) => route.fulfill({ json: { url: 'https://example.invalid/synthetic-evidence.pdf' } }))
  await page.addInitScript(() => sessionStorage.clear())
  await page.goto('/')
  await page.getByRole('button', { name: 'Continuar' }).click()
  await navigateToSection(page, 'Compras')
  return { requests, uploads: () => uploadCount }
}

async function openDialog(page: Page) {
  await page.getByRole('button', { name: 'Pagar', exact: true }).click()
  await page.getByRole('button', { name: 'Registrar anulación', exact: true }).click()
  return page.getByRole('dialog', { name: 'Registrar anulación de compra' })
}

async function completeForm(page: Page) {
  const dialog = page.getByRole('dialog', { name: 'Registrar anulación de compra' })
  await dialog.getByLabel('Fecha de anulación en el SRI').fill('2026-08-05')
  await dialog.getByLabel('Motivo de la anulación').fill('Constancia de anulación verificada')
  await dialog.getByLabel('Respaldo de la anulación', { exact: true }).setInputFiles({
    name: 'constancia-sintetica.txt', mimeType: 'text/plain', buffer: Buffer.from('Fixture sintético de anulación; sin datos reales.'),
  })
  await dialog.getByLabel('Confirmo que la factura consta ANULADA en el SRI').check()
  return dialog
}

test('registra anulación respaldada, conserva historial y excluye de pendientes y clasificación', async ({ page }) => {
  const state = await setup(page)
  await openDialog(page)
  const dialog = await completeForm(page)
  await dialog.getByRole('button', { name: 'Guardar', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(state.requests).toHaveLength(1)
  expect(state.requests[0].body).toEqual({ effectiveDate: '2026-08-05', reason: 'Constancia de anulación verificada', evidenceId, sriStatus: 'ANULADO' })
  expect(state.requests[0].key).toBeTruthy()
  expect(state.uploads()).toBe(1)
  await expect(page.getByRole('status').filter({ hasText: 'Anulación registrada' })).toBeVisible()
  const row = page.getByRole('row').filter({ hasText: 'Compra sintética' })
  await expect(row.getByText('Anulada', { exact: true })).toBeVisible()
  await expect(row.getByRole('checkbox')).toBeDisabled()
  await expect(row.getByRole('button', { name: 'Editar clasificación' })).toBeDisabled()
  await expect(page.getByRole('link', { name: 'Ver respaldo de la anulación' })).toHaveAttribute('href', 'https://example.invalid/synthetic-evidence.pdf')
  await page.getByRole('combobox', { name: 'Estado', exact: true }).selectOption('VOIDED')
  await expect(row).toBeVisible()
  await expect(page.getByRole('columnheader').filter({ hasText: '0,00 vigentes' })).toBeVisible()
  await page.getByRole('tab', { name: /Pendientes SRI/ }).click()
  await expect(page.getByRole('heading', { name: 'Todo revisado' })).toBeVisible()
  await page.getByRole('tab', { name: 'Clasificar', exact: true }).click()
  await expect(page.getByRole('article', { name: purchase.documentNumber })).toHaveCount(0)
})

test('requiere respaldo y confirmación, respeta teclado y pasa axe en el diálogo', async ({ page }, testInfo) => {
  const state = await setup(page)
  const dialog = await openDialog(page)
  await expect(dialog.getByLabel('Fecha de anulación en el SRI')).toBeFocused()
  await expect(dialog.getByRole('button', { name: 'Guardar', exact: true })).toBeDisabled()
  await dialog.getByRole('button', { name: 'Cancelar', exact: true }).focus()
  await page.keyboard.press('Tab')
  await expect(dialog.getByRole('button', { name: 'Cerrar ventana' })).toBeFocused()
  expect((await new AxeBuilder({ page }).include('[role="dialog"]').withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()).violations).toEqual([])
  const confirmation = dialog.getByLabel('Confirmo que la factura consta ANULADA en el SRI')
  await confirmation.scrollIntoViewIfNeeded()
  const confirmationBounds = await confirmation.locator('..').boundingBox()
  const confirmationTextBounds = await confirmation.locator('..').locator('span').boundingBox()
  expect(confirmationTextBounds!.height).toBeLessThanOrEqual(confirmationBounds!.height)
  expect(confirmationTextBounds!.x + confirmationTextBounds!.width).toBeLessThanOrEqual(confirmationBounds!.x + confirmationBounds!.width + 1)
  await page.screenshot({ path: `/tmp/iaerp-cancellation-${testInfo.project.name}.png` })
  const geometry = await dialog.boundingBox()
  expect(geometry!.width).toBeLessThanOrEqual(page.viewportSize()!.width)
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Registrar anulación', exact: true })).toBeFocused()
  expect(state.requests).toHaveLength(0)
  expect(state.uploads()).toBe(0)
})

test('explica el bloqueo contable y reintenta sin duplicar respaldo ni cambiar la clave', async ({ page }) => {
  const message = 'El período está declarado. Revisa el ajuste con contabilidad antes de registrar la anulación.'
  const state = await setup(page, { protectedMessage: message })
  await openDialog(page)
  const dialog = await completeForm(page)
  await dialog.getByRole('button', { name: 'Guardar', exact: true }).click()
  await expect(dialog.getByRole('alert')).toHaveText(message)
  await dialog.getByRole('button', { name: 'Guardar', exact: true }).click()
  await expect.poll(() => state.requests.length).toBe(2)
  expect(state.requests[0].key).toBe(state.requests[1].key)
  expect(state.uploads()).toBe(1)
  await expect(page.getByRole('row').filter({ hasText: 'Compra sintética' }).getByText('Por pagar', { exact: true })).toBeVisible()
})

test('permite registrar desde pendientes SRI sin cuenta por pagar y respeta permisos', async ({ page }) => {
  await setup(page, { linked: false })
  await page.getByRole('tab', { name: /Pendientes SRI/ }).click()
  await page.getByRole('button', { name: 'Registrar anulación' }).click()
  await expect(page.getByRole('dialog', { name: 'Registrar anulación de compra' })).toBeVisible()
  await page.keyboard.press('Escape')
  await setup(page, { canWrite: false })
  await page.getByRole('button', { name: 'Pagar', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Registrar anulación' })).toHaveCount(0)
})


test('conserva respaldo e historial de una anulación SRI sin cuenta por pagar', async ({ page }) => {
  const state = await setup(page, { linked: false })
  await page.getByRole('tab', { name: /Pendientes SRI/ }).click()
  await page.getByRole('button', { name: 'Registrar anulación' }).click()
  const dialog = await completeForm(page)
  await dialog.getByRole('button', { name: 'Guardar', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'Todo revisado' })).toBeVisible()
  await page.getByRole('tab', { name: 'Compras', exact: true }).click()
  await page.getByRole('combobox', { name: 'Estado', exact: true }).selectOption('VOIDED')
  await expect(page.getByRole('heading', { name: 'Anuladas sin cuenta por pagar' })).toBeVisible()
  await expect(page.getByText('Constancia de anulación verificada', { exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Ver respaldo de la anulación' })).toBeVisible()
  expect(state.requests).toHaveLength(1)
})
