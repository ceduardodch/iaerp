import { expect, test, type Page } from '@playwright/test'
import { mockDashboardEndpoints } from './dashboard-mocks'
import { navigateToSection } from './navigation'

/**
 * E2E de la Bandeja de acción (`GET /crm/action-queue`): revisión agregada de
 * cobranza vencida + prospección de leads en un solo lugar. Todo mockeado con
 * page.route, sin backend real -- el envío sigue pasando por los endpoints
 * que ya existían (`/receivables/{id}/reminders` y `/crm/leads/{id}/messages`).
 */

const context = {
  tenantId: '11111111-1111-4111-8111-111111111111',
  ruc: '1799999999001',
  name: 'IAERP Demo',
  roles: ['owner'],
  scopes: ['context:read', 'receivables:read', 'leads:read'],
  automationWritesEnabled: false,
  defaultPaymentTermsDays: 30,
}

const integrationsConnected = {
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
  whatsappCrmProvider: 'META' as const,
  whatsappCollectionsProvider: 'META' as const,
}

const collectionCandidate = {
  receivableId: 'aaaaaaaa-1111-4111-8111-111111111111',
  partyId: 'party-collection-1',
  partyName: 'Distribuidora Norte',
  phone: '+593987654321',
  openAmount: '450.75',
  daysOverdue: 18,
  lastReminderAt: null,
  suggestedMessage: 'Hola Distribuidora Norte, le recordamos que mantiene un saldo pendiente de USD 450.75 con 18 día(s) de atraso.',
}

const prospectingCandidate = {
  leadId: 'bbbbbbbb-2222-4222-8222-222222222222',
  partyId: 'party-lead-1',
  partyName: 'Hotel Sur',
  phone: '+593912345678',
  createdAt: '2026-08-10T09:00:00Z',
  lastActivityAt: null,
  suggestedMessage: 'Hola Hotel Sur, gracias por tu interés en "Facturación Hotel Sur". ¿Tienes unos minutos esta semana?',
}

async function mockApi(
  page: Page,
  options?: { collections?: unknown[]; prospecting?: unknown[]; integrations?: Record<string, unknown> },
) {
  await page.route('**/api/v1/dev/token', (route) =>
    route.fulfill({ json: { accessToken: 'test-token' } }),
  )
  await mockDashboardEndpoints(page)
  await page.route('**/api/v1/context', (route) => route.fulfill({ json: context }))
  for (const path of ['parties', 'products', 'tax-categories', 'establishments', 'emission-points']) {
    await page.route(`**/api/v1/${path}`, (route) => route.fulfill({ json: [] }))
  }
  await page.route('**/api/v1/crm/integrations', (route) =>
    route.fulfill({ json: options?.integrations ?? integrationsConnected }),
  )
  await page.route('**/api/v1/crm/action-queue**', (route) =>
    route.fulfill({
      json: {
        collections: options?.collections ?? [collectionCandidate],
        prospecting: options?.prospecting ?? [prospectingCandidate],
      },
    }),
  )
}

async function openActionQueue(page: Page) {
  await page.goto('/')
  await page.getByRole('button', { name: 'Continuar' }).click()
  await navigateToSection(page, 'Bandeja de acción')
  await expect(page.getByRole('heading', { name: 'Bandeja de acción' })).toBeVisible()
}

test('carga la bandeja y muestra cobranza y prospección pendientes', async ({ page }) => {
  await mockApi(page)
  await openActionQueue(page)

  await expect(page.getByRole('heading', { name: 'Cobranza pendiente' })).toBeVisible()
  await expect(page.getByText('Distribuidora Norte', { exact: true })).toBeVisible()
  await expect(page.getByText('$450,75 pendiente · 18 día(s) de atraso')).toBeVisible()

  await expect(page.getByRole('heading', { name: 'Prospección pendiente' })).toBeVisible()
  await expect(page.getByText('Hotel Sur', { exact: true })).toBeVisible()
})

test('edita el mensaje sugerido y envía el recordatorio de cobranza; la fila desaparece', async ({ page }) => {
  await mockApi(page)
  let requestBody: Record<string, unknown> | undefined
  await page.route(`**/api/v1/receivables/${collectionCandidate.receivableId}/reminders`, (route) => {
    requestBody = route.request().postDataJSON()
    return route.fulfill({
      status: 202,
      json: {
        operationId: 'op-1',
        status: 'ACCEPTED',
        correlationId: 'corr-1',
        createdAt: '2026-08-17T12:00:00Z',
        expiresAt: '2026-08-17T13:00:00Z',
      },
    })
  })

  await openActionQueue(page)

  const row = page.locator('.action-queue-row', { hasText: 'Distribuidora Norte' })
  const textarea = row.getByRole('textbox', { name: 'Mensaje de WhatsApp' })
  await textarea.fill('Mensaje personalizado de cobranza para Distribuidora Norte.')
  await row.getByRole('button', { name: 'Enviar' }).click()

  await expect(row).toHaveCount(0)
  await expect(page.getByText('Distribuidora Norte')).toHaveCount(0)

  expect(requestBody).toMatchObject({
    channel: 'WHATSAPP',
    message: 'Mensaje personalizado de cobranza para Distribuidora Norte.',
  })
})

test('edita el mensaje sugerido y envía el mensaje de prospección; la fila desaparece', async ({ page }) => {
  await mockApi(page)
  let requestBody: Record<string, unknown> | undefined
  await page.route(`**/api/v1/crm/leads/${prospectingCandidate.leadId}/messages`, (route) => {
    requestBody = route.request().postDataJSON()
    return route.fulfill({
      json: {
        id: 'activity-1',
        leadId: prospectingCandidate.leadId,
        activityType: 'WHATSAPP',
        subject: 'Mensaje enviado',
        description: null,
        outcome: 'PENDING',
        reminderDate: null,
        reminderCompleted: false,
        actorId: 'user-1',
        createdAt: '2026-08-17T12:00:00Z',
        updatedAt: '2026-08-17T12:00:00Z',
        tenantId: context.tenantId,
      },
    })
  })

  await openActionQueue(page)

  const row = page.locator('.action-queue-row', { hasText: 'Hotel Sur' })
  const textarea = row.getByRole('textbox', { name: 'Mensaje de WhatsApp' })
  await textarea.fill('Mensaje personalizado de bienvenida para Hotel Sur.')
  await row.getByRole('button', { name: 'Enviar' }).click()

  await expect(row).toHaveCount(0)
  await expect(page.getByText('Hotel Sur')).toHaveCount(0)

  expect(requestBody).toMatchObject({
    channel: 'WHATSAPP',
    message: 'Mensaje personalizado de bienvenida para Hotel Sur.',
  })
})

test('muestra un error inline si el envío falla y conserva la fila', async ({ page }) => {
  await mockApi(page)
  await page.route(`**/api/v1/receivables/${collectionCandidate.receivableId}/reminders`, (route) =>
    route.fulfill({ status: 422, json: { detail: 'Party has no contact for WHATSAPP' } }),
  )

  await openActionQueue(page)

  const row = page.locator('.action-queue-row', { hasText: 'Distribuidora Norte' })
  await row.getByRole('button', { name: 'Enviar' }).click()

  await expect(row.getByRole('alert')).toBeVisible()
  await expect(row).toBeVisible()
})

test('muestra estado vacío cuando no hay pendientes', async ({ page }) => {
  await mockApi(page, { collections: [], prospecting: [] })
  await openActionQueue(page)

  await expect(page.getByRole('heading', { name: 'No hay pendientes hoy' })).toBeVisible()
})

test('avisa cuando WhatsApp no está conectado en vez de dejar los botones sin explicación', async ({ page }) => {
  await mockApi(page, {
    integrations: { ...integrationsConnected, whatsappConnected: false, whatsappMetaConnected: false },
  })
  await openActionQueue(page)

  await expect(page.getByText('WhatsApp no está conectado para este canal.').first()).toBeVisible()
  const row = page.locator('.action-queue-row', { hasText: 'Distribuidora Norte' })
  await expect(row.getByRole('button', { name: 'Enviar' })).toBeDisabled()

  await page.getByRole('button', { name: 'Ir a Configuración' }).first().click()
  await expect(page.getByRole('heading', { name: 'Empresa', exact: true })).toBeVisible()
})
