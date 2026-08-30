import { expect, test, type Page } from '@playwright/test'
import { mockDashboardEndpoints } from './dashboard-mocks'
import { navigateToSection } from './navigation'

/**
 * Pendiente 7 de docs/OBSERVABILIDAD_PENDIENTES.md: hoy un error fuera del
 * árbol de React (script global, promesa sin catch) o un fallo de render no
 * dejan ningún rastro con correlation ID. Verifica que `window.onerror`,
 * `unhandledrejection` y `ErrorBoundary.componentDidCatch` reporten con el
 * correlation ID de la última respuesta del backend (`src/errorReporting.ts`).
 */

const KNOWN_CORRELATION_ID = 'corr-frontend-error-test'

async function mockApp(page: Page) {
  // Red de seguridad: cualquier ruta de API que no esté mockeada abajo debe
  // seguir devolviendo el correlation ID conocido en vez de escapar al
  // backend real (que en CI sí está arriba y respondería con un UUID propio,
  // pisando el que este test necesita para su aserción).
  await page.route('**/api/v1/**', (route) =>
    route.fulfill({ headers: { 'X-Correlation-Id': KNOWN_CORRELATION_ID }, json: {} }),
  )
  await page.route('**/api/v1/dev/token', (route) => route.fulfill({ json: { accessToken: 'test-token' } }))
  await mockDashboardEndpoints(page)
  await page.route('**/api/v1/context', (route) =>
    route.fulfill({
      headers: { 'X-Correlation-Id': KNOWN_CORRELATION_ID },
      json: {
        tenantId: '11111111-1111-4111-8111-111111111111',
        ruc: '1799999999001',
        name: 'IAERP Demo',
        roles: ['owner'],
        scopes: ['context:read'],
        automationWritesEnabled: false,
        defaultPaymentTermsDays: 30,
      },
    }),
  )
  for (const path of ['parties', 'products', 'tax-categories', 'establishments', 'emission-points', 'invoices', 'receivables']) {
    await page.route(`**/api/v1/${path}`, (route) => route.fulfill({ json: [] }))
  }
}

async function login(page: Page) {
  await page.goto('/')
  await page.getByRole('button', { name: 'Continuar' }).click()
  const mobileMenu = page.getByRole('button', { name: 'Menú', exact: true })
  const navigation = page.getByRole('navigation', { name: 'Navegación principal' })
  await expect(mobileMenu.or(navigation)).toBeVisible()
}

function collectFrontendErrorReports(page: Page): string[] {
  const reports: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error' && message.text().includes('[frontend-error]')) {
      reports.push(message.text())
    }
  })
  return reports
}

test('reporta con el correlation ID un error no capturado de script (window.onerror)', async ({ page }) => {
  await mockApp(page)
  const reports = collectFrontendErrorReports(page)
  await login(page)

  await page.evaluate(() => {
    window.setTimeout(() => {
      throw new Error('Boom onerror')
    }, 0)
  })

  await expect.poll(() => reports.length).toBeGreaterThan(0)
  expect(reports[0]).toContain('"source":"window.onerror"')
  expect(reports[0]).toContain('"message":"Boom onerror"')
  expect(reports[0]).toContain(`"correlationId":"${KNOWN_CORRELATION_ID}"`)
})

test('reporta con el correlation ID una promesa rechazada sin manejar (unhandledrejection)', async ({ page }) => {
  await mockApp(page)
  const reports = collectFrontendErrorReports(page)
  await login(page)

  await page.evaluate(() => {
    Promise.reject(new Error('Boom rejection'))
  })

  await expect.poll(() => reports.length).toBeGreaterThan(0)
  expect(reports[0]).toContain('"source":"unhandledrejection"')
  expect(reports[0]).toContain('"message":"Boom rejection"')
  expect(reports[0]).toContain(`"correlationId":"${KNOWN_CORRELATION_ID}"`)
})

test('reporta con el correlation ID un fallo de render capturado por el ErrorBoundary', async ({ page }) => {
  await mockApp(page)
  const reports = collectFrontendErrorReports(page)

  // Simula un fallo real (chunk servido a medias, red inestable): la carga
  // diferida de Nómina falla y React resuelve el `lazy()` rechazado a través
  // del ErrorBoundary que envuelve su Suspense en App.tsx.
  await page.route('**/*', async (route) => {
    const request = route.request()
    if (request.resourceType() === 'script' && request.url().toLowerCase().includes('payroll')) {
      await route.abort('failed')
      return
    }
    await route.fallback()
  })

  await login(page)
  await navigateToSection(page, 'Nómina')

  await expect(page.getByText('No pudimos mostrar Nómina')).toBeVisible()
  await expect.poll(() => reports.length).toBeGreaterThan(0)
  expect(reports[0]).toContain('"source":"error-boundary"')
  expect(reports[0]).toContain(`"correlationId":"${KNOWN_CORRELATION_ID}"`)
})
