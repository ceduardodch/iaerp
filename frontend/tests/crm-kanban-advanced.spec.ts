import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

/**
 * E2E del Sprint 2 - CRM Kanban Advanced (mocks page.route, sin backend):
 * quick-add por columna, modal de detalle sin perder contexto, bulk
 * operations, filtros avanzados, búsqueda por email, atajos de teclado y
 * accesibilidad (axe) en kanban y modal.
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
    estimatedValue: '100.00',
    expectedCloseDate: '2026-08-15',
    createdAt: '2026-07-19T10:00:00Z',
    updatedAt: '2026-07-19T10:00:00Z',
    tenantId: context.tenantId,
    ...overrides,
  }
}

const LEADS = [
  lead({ id: 'l1', title: 'ERP para Andes Café', score: 90, hotness: 'HOT', expectedCloseDate: '2026-07-25' }),
  lead({ id: 'l2', title: 'Facturación Hotel Sur', score: 40, hotness: 'WARM' }),
  lead({ id: 'l3', title: 'Kit contable', score: 15, hotness: 'COLD', party: { id: 'p3', name: 'Distribuidora Norte', email: 'ventas@norte.ec' } }),
  lead({ id: 'l4', title: 'Migración nube', status: 'CONTACTED', score: 70, hotness: 'WARM' }),
  lead({ id: 'l5', title: 'Sitio institucional', status: 'NEGOTIATION', score: 85, hotness: 'HOT' }),
]

async function mockApi(page: Page, options?: { leads?: unknown[] }) {
  const leads = options?.leads ?? LEADS
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
  await page.route('**/api/v1/crm/leads', (route) => {
    if (route.request().method() === 'POST') {
      return route.fulfill({ json: lead({ id: 'created-generic' }) })
    }
    return route.fulfill({ json: leads })
  })
}

async function openCrm(page: Page) {
  await page.goto('/')
  await page.getByRole('button', { name: 'Continuar' }).click()
  await page.getByRole('button', { name: /CRM/ }).click()
  await expect(page.getByRole('heading', { name: 'Pipeline' })).toBeVisible()
}

async function expectNoA11yViolations(page: Page) {
  // Espera a que terminen las animaciones de entrada de framer-motion: axe
  // calcula el contraste con la opacidad ACTUAL, y las columnas entran con
  // fade-in escalonado (falsos positivos de contraste si se corre antes).
  await page.waitForFunction(() =>
    [...document.querySelectorAll<HTMLElement>('.crm-kanban > div, .kanban-card')].every(
      (el) => getComputedStyle(el).opacity === '1'
    )
  )
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze()
  expect(results.violations).toEqual([])
}

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.addInitScript(() => sessionStorage.clear())
  await mockApi(page)
})

test('quick-add crea un lead desde la columna y aparece en el kanban', async ({ page }) => {
  await page.route('**/api/v1/crm/leads/with-party', (route) =>
    route.fulfill({
      json: lead({ id: 'nuevo1', title: 'Oportunidad Quick', party: { id: 'pq', name: 'Cliente Quick', email: 'q@demo.ec' } }),
    })
  )
  await openCrm(page)

  await page.getByRole('button', { name: 'Crear lead en Nuevo' }).click()
  await expect(page.getByRole('dialog', { name: 'Nueva oportunidad en Nuevo' })).toBeVisible()
  await page.getByLabel('Título de la oportunidad').fill('Oportunidad Quick')
  await page.getByLabel('Nombre o razón social').fill('Cliente Quick')
  await page.getByLabel('Número').fill('1713209771')
  await page.getByRole('button', { name: 'Crear lead', exact: true }).click()

  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByText('Oportunidad Quick', { exact: true })).toBeVisible()
})

test('las columnas WON y LOST no ofrecen quick-add', async ({ page }) => {
  await openCrm(page)
  await expect(page.getByRole('button', { name: 'Crear lead en Nuevo' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Crear lead en Ganado' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Crear lead en Perdido' })).toHaveCount(0)
})

test('click en card abre modal de detalle sin perder filtros ni contexto', async ({ page }) => {
  // Mock stateful: el POST agrega al timeline y el refetch la devuelve.
  const activities: Array<Record<string, unknown>> = [
    { id: 'a1', leadId: 'l1', activityType: 'CALL', subject: 'Primera llamada', outcome: 'POSITIVE', reminderCompleted: false, actorId: 'user-1', createdAt: '2026-07-19T15:00:00Z', updatedAt: '2026-07-19T15:00:00Z', tenantId: context.tenantId },
  ]
  await page.route('**/api/v1/crm/leads/l1/activities', (route) => {
    if (route.request().method() === 'POST') {
      const body = route.request().postDataJSON() as { subject: string; activityType: string }
      const created = { id: `a${activities.length + 1}`, leadId: 'l1', activityType: body.activityType, subject: body.subject, outcome: 'PENDING', reminderCompleted: false, actorId: 'user-1', createdAt: '2026-07-20T09:00:00Z', updatedAt: '2026-07-20T09:00:00Z', tenantId: context.tenantId }
      activities.unshift(created)
      return route.fulfill({ json: created })
    }
    return route.fulfill({ json: activities })
  })
  await openCrm(page)

  // Fija un filtro de búsqueda antes de abrir el modal
  await page.getByLabel('Buscar').fill('andes')
  await expect(page.getByText('ERP para Andes Café')).toBeVisible()

  await page.getByRole('button', { name: 'Ver detalles de ERP para Andes Café' }).click()
  const modal = page.getByRole('dialog', { name: 'ERP para Andes Café' })
  await expect(modal).toBeVisible()
  await expect(modal.getByText('l1@demo.ec')).toBeVisible()
  await expect(modal.getByText('Primera llamada')).toBeVisible()
  await expectNoA11yViolations(page)

  // Registrar actividad desde el modal
  await modal.getByLabel('Asunto').fill('Nueva nota')
  await modal.getByRole('button', { name: 'Registrar actividad' }).click()
  await expect(modal.getByText('Nueva nota', { exact: true })).toBeVisible()

  // Esc cierra y el contexto (filtro) sigue intacto
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByLabel('Buscar')).toHaveValue('andes')
})

test('bulk: selección múltiple y mover con resumen de omitidos', async ({ page }) => {
  let statusCalls = 0
  await page.route('**/api/v1/crm/leads/*/status', (route) => {
    statusCalls += 1
    const url = route.request().url()
    const id = url.split('/crm/leads/')[1].split('/')[0]
    return route.fulfill({ json: lead({ id, status: 'CONTACTED' }) })
  })
  await openCrm(page)

  // Selecciona los 3 leads de la columna Nuevo con el checkbox de columna
  await page.getByLabel('Seleccionar todos los leads de Nuevo').check()
  // Y también uno en NEGOTIATION (transición NEW->CONTACTED válida solo para los 3 primeros)
  await page.getByLabel('Seleccionar Sitio institucional').check()

  const bar = page.getByRole('region', { name: 'Acciones en lote' })
  await expect(bar.getByText('4 seleccionados')).toBeVisible()
  await bar.getByLabel('Mover a').selectOption('CONTACTED')
  await bar.getByRole('button', { name: 'Mover', exact: true }).click()

  await expect(bar.getByRole('status')).toContainText('3 movidos, 1 omitido por transición inválida')
  expect(statusCalls).toBe(3)
})

test('filtros avanzados: score, temperatura y fechas', async ({ page }) => {
  await openCrm(page)
  await page.getByRole('button', { name: 'Filtros' }).click()

  // Score >= 60 deja l1 (90), l4 (70), l5 (85)
  await page.getByLabel('Mínimo').fill('60')
  await expect(page.getByText('Kit contable')).toHaveCount(0)
  await expect(page.getByText('ERP para Andes Café')).toBeVisible()

  // Temperatura HOT deja l1 y l5
  await page.getByRole('checkbox', { name: 'Caliente' }).check()
  await expect(page.getByText('Facturación Hotel Sur')).toHaveCount(0)
  await expect(page.getByText('Sitio institucional')).toBeVisible()

  // Rango de cierre esperado hasta julio deja solo l1 (2026-07-25)
  await page.getByLabel('Hasta').fill('2026-07-31')
  await expect(page.getByText('Sitio institucional')).toHaveCount(0)
  await expect(page.getByText('ERP para Andes Café')).toBeVisible()

  // Limpiar restaura
  await page.getByRole('button', { name: 'Limpiar filtros avanzados' }).click()
  await expect(page.getByText('Kit contable')).toBeVisible()
})

test('búsqueda por email del contacto', async ({ page }) => {
  await openCrm(page)
  await page.getByLabel('Buscar').fill('ventas@norte.ec')
  await expect(page.getByText('Kit contable')).toBeVisible()
  await expect(page.getByText('ERP para Andes Café')).toHaveCount(0)
})

test('atajos de teclado: flechas navegan y Enter abre el detalle', async ({ page }) => {
  await page.route('**/api/v1/crm/leads/*/activities', (route) => route.fulfill({ json: [] }))
  await openCrm(page)

  // El hint es accesible
  await page.getByRole('button', { name: 'Atajos de teclado' }).click()
  await expect(page.getByRole('region', { name: 'Atajos de teclado del pipeline' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('region', { name: 'Atajos de teclado del pipeline' })).toHaveCount(0)

  // Primera flecha enfoca la primera card; flecha abajo baja; Enter abre
  await page.keyboard.press('ArrowRight')
  await expect(page.getByRole('button', { name: 'Ver detalles de ERP para Andes Café' })).toBeFocused()
  await page.keyboard.press('ArrowDown')
  await expect(page.getByRole('button', { name: 'Ver detalles de Facturación Hotel Sur' })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('dialog', { name: 'Facturación Hotel Sur' })).toBeVisible()
})

test('kanban pasa verificación de accesibilidad AA', async ({ page }) => {
  await openCrm(page)
  await expectNoA11yViolations(page)
})
