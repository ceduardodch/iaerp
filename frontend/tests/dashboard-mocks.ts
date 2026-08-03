import type { Page } from '@playwright/test'

/**
 * Mockea lo que consulta el tablero al arrancar la app.
 *
 * La sesión siempre entra por el Resumen, así que CUALQUIER spec que haga login
 * dispara estas consultas aunque el test vaya a otra pantalla. Sin mock salen a
 * la API real con el token falso, devuelven 401 y ensucian la consola — lo que
 * rompe el spec que exige cero errores de consola al cargar el kanban.
 *
 * Los mocks por ruta exacta (`**\/api/v1/receivables`) NO cubren estas dos, que
 * cuelgan de subrutas. Por eso viven en un helper compartido: la próxima
 * consulta que agregue el tablero se añade aquí una vez y no en nueve specs.
 */
export async function mockDashboardEndpoints(page: Page): Promise<void> {
  await page.route('**/api/v1/receivables/aging**', (route) =>
    route.fulfill({
      json: {
        asOf: '2026-08-01',
        buckets: [
          { bucket: 'CURRENT', total: '0.00', installmentCount: 0 },
          { bucket: '1-15', total: '0.00', installmentCount: 0 },
          { bucket: '16-30', total: '0.00', installmentCount: 0 },
          { bucket: '31-60', total: '0.00', installmentCount: 0 },
          { bucket: '61-90', total: '0.00', installmentCount: 0 },
          { bucket: '90+', total: '0.00', installmentCount: 0 },
        ],
        byParty: [],
      },
    }),
  )
  await page.route('**/api/v1/receivables/collections/monthly**', (route) =>
    route.fulfill({
      json: {
        months: [
          { year: 2026, month: 7, cashAmount: '0.00', retentionAmount: '0.00', settledAmount: '0.00' },
          { year: 2026, month: 8, cashAmount: '0.00', retentionAmount: '0.00', settledAmount: '0.00' },
        ],
      },
    }),
  )
}
