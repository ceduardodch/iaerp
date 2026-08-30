import { expect, test, type Page } from '@playwright/test'

import { mockDashboardEndpoints } from './dashboard-mocks'
import { navigateToSection } from './navigation'

/**
 * E2E dedicado al panel de Incidencias (`GET`/`POST /ops/failures*`, pendiente 8
 * de docs/OBSERVABILIDAD_PENDIENTES.md), con un backend simulado EN MEMORIA
 * (patrón de payroll.spec.ts): a diferencia de los tests de action-queue.spec.ts,
 * que devuelven una lista estática y una respuesta de reintento fija, aquí el
 * mock aplica de verdad el filtro `status=OPEN` y muta el estado al reintentar
 * -- igual que `app/services/ops_failures.py::retry_failure` -- para probar que
 * el frontend confía en la verdad del backend entre pantallazos (incluida una
 * recarga completa) y no solo en el estado local de React.
 */

const context = {
  tenantId: '11111111-1111-4111-8111-111111111111',
  ruc: '1799999999001',
  name: 'IAERP Demo',
  roles: ['owner'],
  scopes: ['context:read', 'receivables:read', 'leads:read', 'operations:read', 'operations:write'],
  automationWritesEnabled: false,
  defaultPaymentTermsDays: 30,
}

type Failure = {
  id: string
  sourceType: string
  sourceId: string
  eventType: string
  error: string
  attempts: number
  status: 'OPEN' | 'RESOLVED'
  classification: 'AUTO_RETRY' | 'NEEDS_HUMAN'
  correlationId: string | null
  aggregateType: string | null
  aggregateId: string | null
  createdAt: string
  resolvedAt: string | null
}

function baseFailure(overrides: Partial<Failure> = {}): Failure {
  return {
    id: 'cccccccc-3333-4333-8333-333333333333',
    sourceType: 'OUTBOX',
    sourceId: 'source-1',
    eventType: 'invoice.signed',
    error: 'Timeout consultando al SRI',
    attempts: 5,
    status: 'OPEN',
    classification: 'AUTO_RETRY',
    correlationId: 'corr-auto-retry',
    aggregateType: 'sales_document',
    aggregateId: 'doc-1',
    createdAt: '2026-08-28T09:00:00Z',
    resolvedAt: null,
    ...overrides,
  }
}

/**
 * Backend de `/ops/failures` simulado en memoria. El GET respeta el filtro
 * `status` como `list_failures()`; el retry replica las mismas reglas que
 * `retry_failure()`: 404 si no existe, 409 si ya no está `OPEN`, 422 si el
 * payload no trae `aggregate_type`/`aggregate_id`, y si no, marca `RESOLVED`.
 * `failRetriesUntilAttempt` simula un fallo técnico transitorio (503) en los
 * primeros N intentos de un mismo id antes de dejarlo tener éxito.
 */
async function mockOpsFailures(
  page: Page,
  { failures = [] as Failure[], failRetriesUntilAttempt = 0 } = {},
) {
  const retryAttempts = new Map<string, number>()

  await page.route('**/api/v1/dev/token', (route) => route.fulfill({ json: { accessToken: 'test-token' } }))
  await mockDashboardEndpoints(page)
  await page.route('**/api/v1/context', (route) => route.fulfill({ json: context }))
  for (const path of ['parties', 'products', 'tax-categories', 'establishments', 'emission-points']) {
    await page.route(`**/api/v1/${path}`, (route) => route.fulfill({ json: [] }))
  }
  await page.route('**/api/v1/crm/integrations', (route) =>
    route.fulfill({
      json: {
        googleConnected: false,
        googleEmail: null,
        googleLastSyncAt: null,
        googleConfigurationAvailable: false,
        whatsappConnected: true,
        whatsappPhone: '+593999999999',
        whatsappMetaConnected: true,
        whatsappEvolutionConnected: false,
        whatsappEvolutionPhone: null,
        evolutionConfigurationAvailable: false,
        whatsappCrmProvider: 'META',
        whatsappCollectionsProvider: 'META',
      },
    }),
  )
  await page.route('**/api/v1/crm/action-queue**', (route) =>
    route.fulfill({ json: { collections: [], prospecting: [] } }),
  )

  await page.route('**/api/v1/ops/failures**', async (route) => {
    if (route.request().method() !== 'GET') {
      await route.fallback()
      return
    }
    const url = new URL(route.request().url())
    const status = url.searchParams.get('status')
    const filtered = status ? failures.filter((failure) => failure.status === status) : failures
    await route.fulfill({ json: filtered })
  })

  await page.route('**/api/v1/ops/failures/*/retry', async (route) => {
    const url = new URL(route.request().url())
    const id = url.pathname.split('/').slice(-2)[0] as string
    const failure = failures.find((candidate) => candidate.id === id)
    if (!failure) {
      await route.fulfill({ status: 404, json: { detail: 'Ops failure not found' } })
      return
    }
    if (failure.status !== 'OPEN') {
      await route.fulfill({ status: 409, json: { detail: 'Ops failure is not open; it was already resolved' } })
      return
    }
    if (!failure.aggregateType || !failure.aggregateId) {
      await route.fulfill({
        status: 422,
        json: { detail: 'Ops failure payload is missing aggregate_type/aggregate_id; cannot retry' },
      })
      return
    }
    const attemptNumber = (retryAttempts.get(id) ?? 0) + 1
    retryAttempts.set(id, attemptNumber)
    if (attemptNumber <= failRetriesUntilAttempt) {
      await route.fulfill({ status: 503, json: { detail: 'Fallo temporal del servidor' } })
      return
    }
    failure.status = 'RESOLVED'
    failure.resolvedAt = '2026-08-30T10:00:00Z'
    await route.fulfill({ json: failure })
  })

  return { failures }
}

async function openIncidents(page: Page) {
  await page.goto('/')
  await page.getByRole('button', { name: 'Continuar' }).click()
  await navigateToSection(page, 'Bandeja de acción')
  await expect(page.getByRole('heading', { name: 'Incidencias', exact: true })).toBeVisible()
}

test('el listado respeta el filtro por estado: una incidencia ya resuelta no aparece entre las abiertas', async ({ page }) => {
  await mockOpsFailures(page, {
    failures: [
      baseFailure(),
      baseFailure({
        id: 'dddddddd-4444-4444-8444-444444444444',
        eventType: 'collection.reminder.due',
        classification: 'NEEDS_HUMAN',
        status: 'RESOLVED',
        resolvedAt: '2026-08-20T09:00:00Z',
      }),
    ],
  })
  await openIncidents(page)

  await expect(page.getByText('invoice.signed', { exact: true })).toBeVisible()
  await expect(page.getByText('collection.reminder.due', { exact: true })).toHaveCount(0)
})

test('reintentar persiste en el backend: tras recargar la página, la incidencia ya no vuelve a aparecer', async ({ page }) => {
  await mockOpsFailures(page, { failures: [baseFailure()] })
  await openIncidents(page)

  const row = page.locator('.action-queue-row', { hasText: 'invoice.signed' })
  await row.getByRole('button', { name: 'Reintentar' }).click()
  await expect(row).toHaveCount(0)

  // La sección activa vive en estado de React, no en la URL: tras recargar
  // hay que volver a navegar a "Bandeja de acción", pero la sesión (token en
  // sessionStorage) sí sobrevive, así que no hace falta pasar por "Continuar".
  await page.reload()
  await navigateToSection(page, 'Bandeja de acción')
  await expect(page.getByRole('heading', { name: 'Incidencias', exact: true })).toBeVisible()
  await expect(page.getByText('invoice.signed', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'Sin incidencias abiertas' })).toBeVisible()
})

test('si el backend rechaza el reintento por payload incompleto, explica el error y conserva la incidencia', async ({ page }) => {
  await mockOpsFailures(page, {
    failures: [baseFailure({ aggregateType: null, aggregateId: null })],
  })
  await openIncidents(page)

  const row = page.locator('.action-queue-row', { hasText: 'invoice.signed' })
  await row.getByRole('button', { name: 'Reintentar' }).click()

  await expect(row.getByRole('alert')).toContainText('aggregate_type/aggregate_id')
  await expect(row).toBeVisible()
})

test('un fallo técnico transitorio no bloquea la incidencia: se puede reintentar de nuevo hasta que el backend acepta', async ({ page }) => {
  await mockOpsFailures(page, { failures: [baseFailure()], failRetriesUntilAttempt: 1 })
  await openIncidents(page)

  const row = page.locator('.action-queue-row', { hasText: 'invoice.signed' })
  const retryButton = row.getByRole('button', { name: 'Reintentar' })

  await retryButton.click()
  await expect(row.getByRole('alert')).toContainText('Fallo temporal del servidor')
  await expect(row).toBeVisible()

  await expect(retryButton).toBeEnabled()
  await retryButton.click()
  await expect(row).toHaveCount(0)
})
