import { expect, test, type Page } from '@playwright/test'

import { mockDashboardEndpoints } from './dashboard-mocks'
import { navigateToSection } from './navigation'

const tenantId = '11111111-1111-4111-8111-111111111111'

async function mockShell(page: Page) {
  await page.route('**/api/v1/dev/token', (route) => route.fulfill({ json: { accessToken: 'test-token' } }))
  await mockDashboardEndpoints(page)
  await page.route('**/api/v1/context', (route) => route.fulfill({
    json: {
      tenantId,
      ruc: '1799999999001',
      name: 'IAERP Demo',
      roles: ['owner'],
      scopes: ['analytics:read', 'analytics:write'],
      automationWritesEnabled: false,
    },
  }))
  for (const path of ['parties', 'products', 'tax-categories', 'establishments', 'emission-points']) {
    await page.route(`**/api/v1/${path}`, (route) => route.fulfill({ json: [] }))
  }
}

async function openClassifications(page: Page) {
  await page.goto('/')
  await page.getByLabel('Correo').fill('owner@iaerp.local')
  await page.getByLabel('ID de empresa').fill(tenantId)
  await page.getByRole('button', { name: 'Continuar' }).click()
  await navigateToSection(page, 'Empresa')
  await page.getByRole('button', { name: 'Clasificaciones' }).click()
  await expect(page.getByRole('heading', { name: 'Clasificaciones analíticas' })).toBeVisible()
}

function classificationForm(page: Page) {
  return page.locator('form').filter({
    has: page.getByRole('button', { name: 'Crear clasificación' }),
  })
}

test('explica un código repetido sin enviar otra alta', async ({ page }) => {
  let postCount = 0
  await mockShell(page)
  await page.route(/\/api\/v1\/analytic-classifications(?:\?.*)?$/, async (route) => {
    if (route.request().method() === 'POST') {
      postCount += 1
      await route.fulfill({ status: 409, json: { detail: 'No debía enviarse' } })
      return
    }
    await route.fulfill({
      json: [{ id: '11111111-1111-4111-8111-111111111119', code: 'A001', name: 'AWS Cloud', maxDepth: 1, active: true }],
    })
  })
  await page.route('**/api/v1/analytic-classifications/*/values', (route) => route.fulfill({ json: [] }))

  await openClassifications(page)
  const form = classificationForm(page)
  await form.getByLabel('Nombre').fill('AWS_CLOUD')
  await form.getByLabel('Código').fill('A001')
  await form.getByRole('button', { name: 'Crear clasificación' }).click()

  await expect(page.getByRole('alert')).toHaveText('Ya existe una clasificación con el código A001.')
  expect(postCount).toBe(0)
})

test('muestra el detalle de validación y no object Object', async ({ page }) => {
  await mockShell(page)
  await page.route(/\/api\/v1\/analytic-classifications(?:\?.*)?$/, async (route) => {
    if (route.request().method() === 'POST') {
      await route.fulfill({
        status: 422,
        json: { detail: [{ loc: ['body', 'code'], msg: 'El código no es válido', type: 'string_pattern_mismatch' }] },
      })
      return
    }
    await route.fulfill({ json: [] })
  })

  await openClassifications(page)
  const form = classificationForm(page)
  await form.getByLabel('Nombre').fill('AWS Cloud')
  await form.getByLabel('Código').fill('AWS_CLOUD')
  await form.getByRole('button', { name: 'Crear clasificación' }).click()

  await expect(page.getByRole('alert')).toHaveText('code: El código no es válido')
  await expect(page.getByText('[object Object]')).toHaveCount(0)
})
