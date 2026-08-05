import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { mockDashboardEndpoints } from './dashboard-mocks'

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
    qualificationStatus: 'UNREVIEWED',
    companyName: null,
    jobTitle: null,
    usesAws: null,
    decisionAuthority: null,
    qualificationReason: null,
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
  lead({ id: 'k1', title: 'ERP para Andes Café', hotness: 'HOT', score: 90, source: 'META_LEAD_AD', campaignId: 'meta-001', campaignName: 'Demo ERP Ecuador', utmCampaign: 'demo_erp_ec' }),
  lead({ id: 'k2', title: 'Facturación Hotel Sur', hotness: 'WARM', status: 'CONTACTED' }),
  lead({ id: 'k3', title: 'Kit contable', hotness: 'COLD', status: 'NEGOTIATION' }),
]

async function mockApi(page: Page) {
  let campaigns: Record<string, unknown>[] = []
  let variants: Record<string, unknown>[] = []
  let leads = LEADS.map((item) => ({ ...item }))
  await page.route('**/api/v1/dev/token', (route) =>
    route.fulfill({ json: { accessToken: 'test-token' } })
  )
  await mockDashboardEndpoints(page)
  await page.route('**/api/v1/context', (route) => route.fulfill({ json: context }))
  for (const path of ['parties', 'products', 'tax-categories', 'establishments', 'emission-points', 'receivables', 'invoices']) {
    await page.route(`**/api/v1/${path}`, (route) => route.fulfill({ json: [] }))
  }
  await page.route('**/api/v1/receivables/aging', (route) =>
    route.fulfill({ json: { asOf: '2026-08-02', buckets: [], byParty: [] } })
  )
  await page.route('**/api/v1/receivables/collections/monthly**', (route) =>
    route.fulfill({ json: { months: [] } })
  )
  await page.route('**/api/v1/crm/integrations/status', (route) =>
    route.fulfill({ json: { googleConnected: false, googleEmail: null } })
  )
  await page.route('**/api/v1/crm/campaigns**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    const action = path.split('/').at(-1)
    if (request.method() === 'GET' && path.endsWith('/policy')) {
      return route.fulfill({
        json: {
          activationEnabled: true,
          dailyBudgetLimit: '10.00',
          activeDailyBudget: campaigns.some((item) => item.status === 'ACTIVE') ? '5.00' : '0.00',
        },
      })
    }
    if (request.method() === 'GET' && path.endsWith('/variants')) {
      return route.fulfill({ json: variants })
    }
    const insights = {
      campaignId: 'campaign-ui-1', syncedDays: [],
      variants: variants.map((variant, index) => ({
        variant, currency: 'USD', spend: index === 0 ? '4.00' : '6.00',
        impressions: index === 0 ? 1000 : 1200, clicks: index === 0 ? 20 : 12,
        leads: index === 0 ? 2 : 1, qualifiedLeads: index === 0 ? 1 : 0,
        ctr: index === 0 ? '2.00' : '1.00', cpl: index === 0 ? '2.00' : '6.00',
        costPerQualifiedLead: index === 0 ? '4.00' : null,
      })),
    }
    if (request.method() === 'GET' && path.endsWith('/insights')) {
      return route.fulfill({ json: insights })
    }
    if (request.method() === 'GET') {
      if (campaigns.some((item) => item.status === 'PAUSING')) {
        campaigns = campaigns.map((item) => ({
          ...item,
          status: 'PAUSED',
          pausedAt: '2026-08-04T10:10:00Z',
        }))
      }
      if (campaigns.some((item) => item.status === 'PREPARING')) {
        campaigns = campaigns.map((item) => ({
          ...item,
          status: 'PREPARED',
          currency: 'USD',
          externalCampaignId: 'meta-campaign-1',
          externalAdsetId: 'meta-adset-1',
        }))
        variants = variants.map((item, index) => ({
          ...item,
          externalCreativeId: `meta-creative-${index + 1}`,
          externalAdId: `meta-ad-${index + 1}`,
        }))
      }
      if (campaigns.some((item) => item.status === 'ACTIVATING')) {
        campaigns = campaigns.map((item) => ({
          ...item,
          status: 'ACTIVE',
          activatedAt: '2026-08-04T10:05:00Z',
        }))
      }
      return route.fulfill({ json: campaigns })
    }
    if (path.endsWith('/crm/campaigns')) {
      const input = request.postDataJSON()
      const campaign = {
        id: 'campaign-ui-1', tenantId: context.tenantId, provider: 'META', status: 'DRAFT',
        currency: null, creativeSha256: null, externalCampaignId: null,
        externalAdsetId: null, externalCreativeId: null, externalAdId: null,
        approvedAt: null, activatedAt: null, pausedAt: null, lastError: null,
        createdAt: '2026-08-04T10:00:00Z', updatedAt: '2026-08-04T10:00:00Z',
        ...input,
      }
      campaigns = [campaign]
      return route.fulfill({ status: 201, json: campaign })
    }
    const current = campaigns[0] ?? {}
    if (request.method() === 'POST' && path.endsWith('/variants')) {
      const input = request.postDataJSON()
      const variant = { id: `variant-${variants.length + 1}`, campaignId: 'campaign-ui-1', tenantId: context.tenantId, position: variants.length + 1, creativeSha256: null, externalCreativeId: null, externalAdId: null, createdAt: '2026-08-04T10:00:00Z', updatedAt: '2026-08-04T10:00:00Z', ...input }
      variants = [...variants, variant]
      return route.fulfill({ status: 201, json: variant })
    }
    if (action === 'creative' && path.includes('/variants/')) {
      const variantId = path.split('/').at(-2)
      const updated = { ...variants.find((item) => item.id === variantId), creativeSha256: `sha-${variantId}` }
      variants = variants.map((item) => item.id === variantId ? updated : item)
      return route.fulfill({ json: updated })
    }
    if (action === 'creative') {
      const updated = { ...current, creativeSha256: 'sha256-image' }
      campaigns = [updated]
      variants = [{ id: 'variant-1', campaignId: 'campaign-ui-1', tenantId: context.tenantId, key: 'principal', name: 'Principal', angle: null, position: 1, primaryText: current.primaryText, headline: current.headline, description: current.description, creativeSha256: 'sha256-image', externalCreativeId: null, externalAdId: null, createdAt: '2026-08-04T10:00:00Z', updatedAt: '2026-08-04T10:00:00Z' }]
      return route.fulfill({ json: updated })
    }
    if (action === 'prepare') {
      const updated = { ...current, status: 'PREPARING' }
      campaigns = [updated]
      return route.fulfill({ json: updated })
    }
    if (action === 'activate') {
      const updated = { ...current, status: 'ACTIVATING', approvedAt: '2026-08-04T10:05:00Z', activatedAt: null }
      campaigns = [updated]
      return route.fulfill({ json: updated })
    }
    if (action === 'pause') {
      const updated = { ...current, status: 'PAUSING' }
      campaigns = [updated]
      return route.fulfill({ json: updated })
    }
    if (action === 'sync') return route.fulfill({ json: insights })
    return route.abort()
  })
  await page.route('**/api/v1/crm/leads', (route) => route.fulfill({ json: leads }))
  await page.route('**/api/v1/crm/leads/*/activities', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/v1/crm/leads/*/qualification', (route) => {
    const input = route.request().postDataJSON()
    const updated = { ...leads[0], qualificationStatus: input.status, companyName: input.companyName, jobTitle: input.jobTitle, usesAws: input.usesAws, decisionAuthority: input.decisionAuthority, qualificationReason: input.reason }
    leads = [updated, ...leads.slice(1)]
    return route.fulfill({ json: updated })
  })
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

  test('muestra el resumen de los leads atribuidos a campañas', async ({ page }) => {
    await openCrm(page)
    const summary = page.locator('.campaign-summary-panel')
    await expect(summary).toContainText('Demo ERP Ecuador')
    await expect(summary).toContainText('META_LEAD_AD')
    await expect(summary).toContainText('1')
  })

  test('crea, prepara pausada y activa una campaña con confirmación', async ({ page }) => {
    await openCrm(page)
    await page.getByRole('button', { name: 'Campañas' }).click()
    await expect(page.getByRole('heading', { name: 'Campañas', exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Nueva campaña' }).first().click()
    await page.getByLabel('Nombre').fill('Demo IAERP Meta')
    await page.getByLabel('Texto de la variante principal').fill('Solicita una demo de IAERP.')
    await page.getByLabel('Titular principal').fill('Ordena tu empresa')
    await page.getByRole('button', { name: 'Guardar borrador' }).click()
    await expect(page.getByRole('heading', { name: 'Demo IAERP Meta' })).toBeVisible()
    await page.getByLabel('Imagen principal JPG o PNG').setInputFiles({
      name: 'campaign.png',
      mimeType: 'image/png',
      buffer: Buffer.from('89504e470d0a1a0a', 'hex'),
    })
    await page.getByRole('button', { name: 'Crear variante principal' }).click()
    await page.getByRole('button', { name: 'Añadir variante' }).click()
    const variantForm = page.locator('.campaign-variant-form')
    await variantForm.getByLabel('Clave').fill('costo')
    await variantForm.getByLabel('Nombre').fill('Ángulo costo')
    await variantForm.getByLabel('Ángulo').fill('Costo')
    await variantForm.getByLabel('Texto principal').fill('Reduce el costo de operar AWS.')
    await variantForm.getByLabel('Titular').fill('Controla tu costo AWS')
    await variantForm.getByRole('button', { name: 'Guardar variante' }).click()
    const costVariant = page.locator('.campaign-variant-card').filter({ hasText: 'Ángulo costo' })
    await costVariant.getByLabel('Imagen').setInputFiles({
      name: 'cost.png', mimeType: 'image/png', buffer: Buffer.from('89504e470d0a1a0a', 'hex'),
    })
    await costVariant.getByRole('button', { name: 'Cargar' }).click()
    await page.getByRole('button', { name: 'Preparar todas en Meta (pausadas)' }).click()
    await expect(page.getByText('Lista y pausada')).toBeVisible()
    await page.getByRole('button', { name: 'Activar campaña' }).click()
    await expect(page.getByText('Meta activará')).toBeVisible()
    await page.getByRole('button', { name: 'Sí, activar campaña' }).click()
    await expect(page.getByText('Activa', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Actualizar métricas' }).click()
    const table = page.locator('.campaign-insights-table')
    await expect(table).toContainText('Principal')
    await expect(table).toContainText('Ángulo costo')
    await expect(table).toContainText('2.00%')
    await expect(table).toContainText('USD 4.00')
  })

  test('debería ser responsive en mobile', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 })
    await openCrm(page)
    await expect(page.locator('.crm-kanban')).toBeVisible()
    await expect(page.locator('.kanban-column').first()).toBeVisible()
  })

  test('califica un lead de Meta con evidencia comercial', async ({ page }) => {
    await openCrm(page)
    await page.locator('[data-lead-id="k1"]').click()
    await expect(page.getByRole('heading', { name: 'Calificación comercial' })).toBeVisible()
    const qualification = page.getByRole('region', { name: 'Calificación comercial' })
    await qualification.getByLabel('Empresa').fill('Andes Café')
    await qualification.getByLabel('Cargo').fill('CTO')
    await qualification.getByLabel('¿Usa AWS?').selectOption('true')
    await qualification.getByLabel('¿Decide o llega al decisor?').selectOption('true')
    await qualification.getByLabel('Motivo').fill('Usa AWS y decide sobre la cuenta.')
    await qualification.getByRole('button', { name: 'Guardar calificación' }).click()
    await expect(qualification.getByText('Calificado', { exact: true })).toBeVisible()
  })

  test('campañas y calificación pasan WCAG 2.1 AA', async ({ page }) => {
    await openCrm(page)
    const campaignsTrigger = page.getByRole('button', { name: 'Campañas' })
    await campaignsTrigger.focus()
    await expect(campaignsTrigger).toBeFocused()
    await page.keyboard.press('Enter')
    await expect(page.getByRole('heading', { name: 'Campañas', exact: true })).toBeVisible()
    const campaignsAudit = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      .analyze()
    expect(campaignsAudit.violations).toEqual([])

    await page.getByRole('button', { name: 'Volver al pipeline' }).click()
    await page.locator('[data-lead-id="k1"]').click()
    const qualificationAudit = await new AxeBuilder({ page })
      .include('.erp-modal')
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      .analyze()
    expect(qualificationAudit.violations).toEqual([])
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
