import { expect, test, type Page } from '@playwright/test'

/**
 * E2E del Sprint 1 - CRM Kanban Foundation, con mocks `page.route` (sin
 * backend ni servidor externo: corre igual en local y en CI contra el dev
 * server de Vite). Cubre columnas, cards, badges, contadores, búsqueda y
 * responsive. La versión anterior apuntaba hardcodeado a localhost:8088 y
 * fallaba en CI, donde ese servidor no existe.
 */

const context = {
  tenantId: '11111111-1111-4111-8111-111111111111',
  ruc: '1799999999001',
  name: 'IAERP Demo',
  roles: ['owner'],
  scopes: ['context:read', 'leads:read', 'leads:write'],
  automationWritesEnabled: false,
}

function lead(overrides: Record<string, unknown>) {
  const id = String(overrides.id)
  return {
    id,
    partyId: `party-${id}`,
    title: `Lead ${id}`,
    productId: null,
    party: { id: `party-${id}`, name: `Contacto ${id}`, email: `${id}@demo.ec` },
    product: null,
    owner: { id: 'user-1', displayName: 'User A', email: 'a@iaerp.local' },
    status: 'NEW',
    source: null,
    ownerUserId: 'user-1',
    score: 50,
    hotness: 'COLD',
    estimatedValue: '150.00',
    expectedCloseDate: '2026-08-15',
    createdAt: '2026-07-19T10:00:00Z',
    updatedAt: '2026-07-19T10:00:00Z',
    tenantId: context.tenantId,
    ...overrides,
  }
}

const LEADS = [
  lead({ id: 'k1', title: 'ERP para Andes Café', hotness: 'HOT', score: 90 }),
  lead({ id: 'k2', title: 'Facturación Hotel Sur', hotness: 'WARM', status: 'CONTACTED' }),
  lead({ id: 'k3', title: 'Kit contable', hotness: 'COLD', status: 'NEGOTIATION' }),
]

async function mockApi(page: Page) {
  await page.route('**/api/v1/dev/token', (route) =>
    route.fulfill({ json: { accessToken: 'test-token' } })
  )
  await page.route('**/api/v1/context', (route) => route.fulfill({ json: context }))
  for (const path of ['parties', 'products', 'tax-categories', 'establishments', 'emission-points', 'receivables', 'invoices']) {
    await page.route(`**/api/v1/${path}`, (route) => route.fulfill({ json: [] }))
  }
  await page.route('**/api/v1/crm/integrations/status', (route) =>
    route.fulfill({ json: { googleConnected: false, googleEmail: null } })
  )
  await page.route('**/api/v1/crm/leads', (route) => route.fulfill({ json: LEADS }))
}

async function openCrm(page: Page) {
  await page.goto('/')
  await page.getByRole('button', { name: 'Continuar' }).click()
  await page.getByRole('button', { name: /CRM/ }).click()
  await expect(page.getByRole('heading', { name: 'Pipeline' })).toBeVisible()
  await page.waitForSelector('.crm-kanban')
}

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.addInitScript(() => sessionStorage.clear())
  await mockApi(page)
})

test.describe('CRM Kanban Pipeline', () => {
  test('debería mostrar las 7 columnas del pipeline', async ({ page }) => {
    await openCrm(page)
    await expect(page.locator('.kanban-column')).toHaveCount(7)
    const labels = ['Nuevo', 'Contactado', 'Calificado', 'Propuesta', 'Negociación', 'Ganado', 'Perdido']
    for (const [index, label] of labels.entries()) {
      await expect(page.locator('.kanban-column h2').nth(index)).toContainText(label)
    }
  })

  test('debería mostrar leads en sus columnas con la información esperada', async ({ page }) => {
    await openCrm(page)
    await expect(page.locator('.kanban-card')).toHaveCount(3)

    const firstCard = page.locator('[data-lead-id="k1"]')
    await expect(firstCard.locator('strong')).toContainText('ERP para Andes Café')
    await expect(firstCard.locator('.lead-card-badge')).toContainText('Caliente')
    await expect(firstCard.locator('.lead-card-score')).toContainText('90')

    await expect(
      page.locator('.kanban-column[data-stage="CONTACTED"] .kanban-card')
    ).toHaveCount(1)
    await expect(
      page.locator('.kanban-column[data-stage="NEGOTIATION"] .kanban-card')
    ).toHaveCount(1)
  })

  test('debería permitir búsqueda de leads y filtrar el tablero', async ({ page }) => {
    await openCrm(page)
    const searchInput = page.getByLabel('Buscar')
    await searchInput.fill('andes')
    await expect(searchInput).toHaveValue('andes')
    await expect(page.locator('.kanban-card')).toHaveCount(1)
    await expect(page.getByText('ERP para Andes Café')).toBeVisible()
  })

  test('debería mostrar contadores y totales monetarios por columna', async ({ page }) => {
    await openCrm(page)
    await expect(page.locator('.kanban-column-count')).toHaveCount(7)
    await expect(page.locator('.kanban-column-total')).toHaveCount(7)
    await expect(
      page.locator('.kanban-column[data-stage="NEW"] .kanban-column-total')
    ).toContainText('150')
  })

  test('debería ser responsive en mobile', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 })
    await openCrm(page)
    await expect(page.locator('.crm-kanban')).toBeVisible()
    await expect(page.locator('.kanban-column').first()).toBeVisible()
  })
})

test.describe('Lead Cards', () => {
  test('debería mostrar badges de hotness', async ({ page }) => {
    await openCrm(page)
    await expect(page.locator('[data-lead-id="k1"] .lead-card-badge')).toContainText('Caliente')
    await expect(page.locator('[data-lead-id="k2"] .lead-card-badge')).toContainText('Tibio')
    await expect(page.locator('[data-lead-id="k3"] .lead-card-badge')).toContainText('Frío')
  })

  test('debería mostrar valor estimado en el footer de la card', async ({ page }) => {
    await openCrm(page)
    await expect(page.locator('[data-lead-id="k1"]').locator('footer b')).toContainText('150')
  })
})

test.describe('Drag & Drop', () => {
  test('las columnas activas son droppables y las terminales no', async ({ page }) => {
    await openCrm(page)
    await expect(page.locator('.kanban-column[data-stage="NEW"]')).toHaveAttribute(
      'data-droppable',
      'true'
    )
    await expect(page.locator('.kanban-column[data-stage="WON"]')).toHaveAttribute(
      'data-droppable',
      'false'
    )
  })
})

test.describe('Performance', () => {
  test('no debería tener errores de consola al cargar el kanban', async ({ page }) => {
    const errors: string[] = []
    page.on('console', (message) => {
      if (message.type() === 'error') errors.push(message.text())
    })
    await openCrm(page)
    expect(errors).toEqual([])
  })
})
