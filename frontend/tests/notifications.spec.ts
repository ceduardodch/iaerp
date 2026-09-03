import { expect, test, type Page } from '@playwright/test'

import { mockDashboardEndpoints } from './dashboard-mocks'
import { navigateToSection } from './navigation'

// Avisos internos: reglas, plantillas, bitácora, calendario de facturación y
// canal Brevo. La API va mockeada con estado en memoria (como
// analytic-classifications.spec.ts y payroll.spec.ts) para poder encadenar
// encender → configurar y fallido → reintentar en el mismo test.

type Rule = {
  id: string
  ruleType: string
  name: string
  enabled: boolean
  scheduleKind: string
  daysOfMonth: string | null
  offsetsDays: string | null
  sendHour: number
  channels: string
  audienceKind: string
  audienceRoles: string[]
  audienceEmails: string[]
  requireAck: boolean
  updatedAt: string
}

type Template = {
  ruleType: string
  subject: string
  body: string
  isCustom: boolean
}

type Delivery = {
  id: string
  recipient: string
  channel: string
  provider: string
  status: string
  errorMessage: string | null
  sentAt: string | null
}

type NotificationEvent = {
  id: string
  ruleId: string | null
  ruleType: string
  status: string
  scheduledAt: string
  attempts: number
  errorMessage: string | null
  sentAt: string | null
  ackAt: string | null
  ackBy: string | null
  periodLabel: string | null
  payload: Record<string, unknown>
  deliveries: Delivery[]
}

type BillingSchedule = {
  id: string
  partyId: string
  partyName: string
  contractId: string | null
  dayOfMonth: number
  frequency: string
  anchorMonth: number | null
  amountHint: string | null
  notes: string | null
  active: boolean
}

const PARTY_ID = '22222222-2222-4222-8222-222222222221'

function baseRule(overrides: Partial<Rule> = {}): Rule {
  return {
    id: 'rule-iva-declaracion',
    ruleType: 'IVA_DECLARACION',
    name: 'Recordatorio de declaracion de IVA',
    enabled: false,
    scheduleKind: 'OFFSET_TO_DUE',
    daysOfMonth: null,
    offsetsDays: '-7,-3,-1',
    sendHour: 8,
    channels: 'EMAIL',
    audienceKind: 'TENANT_USERS',
    audienceRoles: [],
    audienceEmails: [],
    requireAck: true,
    updatedAt: '2026-08-01T00:00:00Z',
    ...overrides,
  }
}

function baseTemplate(overrides: Partial<Template> = {}): Template {
  return {
    ruleType: 'IVA_DECLARACION',
    subject: 'Declaracion de IVA {{periodo}} vence el {{fecha_limite}}',
    body: 'La declaracion de IVA del periodo {{periodo}} de {{empresa}} vence el {{fecha_limite}}.',
    isCustom: false,
    ...overrides,
  }
}

function baseDelivery(overrides: Partial<Delivery> = {}): Delivery {
  return {
    id: 'delivery-1',
    recipient: 'owner@iaerp.local',
    channel: 'EMAIL',
    provider: 'STUB',
    status: 'SENT',
    errorMessage: null,
    sentAt: '2026-08-20T13:00:00Z',
    ...overrides,
  }
}

function baseEvent(overrides: Partial<NotificationEvent> = {}): NotificationEvent {
  return {
    id: 'event-1',
    ruleId: 'rule-iva-declaracion',
    ruleType: 'IVA_DECLARACION',
    status: 'SENT',
    scheduledAt: '2026-08-21T13:00:00Z',
    attempts: 1,
    errorMessage: null,
    sentAt: '2026-08-21T13:00:05Z',
    ackAt: null,
    ackBy: null,
    periodLabel: '08/2026',
    payload: { period_label: '08/2026' },
    deliveries: [baseDelivery()],
    ...overrides,
  }
}

function eventSummary(event: NotificationEvent): Omit<NotificationEvent, 'payload' | 'deliveries'> {
  return {
    id: event.id,
    ruleId: event.ruleId,
    ruleType: event.ruleType,
    status: event.status,
    scheduledAt: event.scheduledAt,
    attempts: event.attempts,
    errorMessage: event.errorMessage,
    sentAt: event.sentAt,
    ackAt: event.ackAt,
    ackBy: event.ackBy,
    periodLabel: event.periodLabel,
  }
}

/** Backend de avisos simulado en memoria; cada test arranca desde su propio estado. */
async function mockNotifications(page: Page, {
  rules = [baseRule()] as Rule[],
  templates = [] as Template[],
  events = [] as NotificationEvent[],
  schedules = [] as BillingSchedule[],
} = {}) {
  const captured: { ruleUpdate: Record<string, unknown> | null } = { ruleUpdate: null }

  await page.route('**/api/v1/dev/token', (route) => route.fulfill({ json: { accessToken: 'test-token' } }))
  await mockDashboardEndpoints(page)
  await page.route('**/api/v1/context', (route) => route.fulfill({
    json: {
      tenantId: '11111111-1111-4111-8111-111111111111',
      ruc: '1799999999001',
      name: 'IAERP Demo',
      roles: ['owner'],
      scopes: ['context:read', 'notifications:read', 'notifications:write'],
      automationWritesEnabled: false,
      defaultPaymentTermsDays: 0,
    },
  }))
  for (const path of ['products', 'tax-categories', 'establishments', 'emission-points', 'invoices', 'receivables']) {
    await page.route(`**/api/v1/${path}`, (route) => route.fulfill({ json: [] }))
  }
  // Calendario de facturación necesita un cliente real para el combobox.
  await page.route('**/api/v1/parties', (route) => route.fulfill({
    json: [{
      id: PARTY_ID,
      name: 'ACME S.A.',
      identificationType: 'RUC',
      identificationNumber: '1790000000001',
      roles: ['CUSTOMER'],
    }],
  }))

  await page.route('**/api/v1/notifications/rules', (route) => route.fulfill({ json: rules }))
  await page.route('**/api/v1/notifications/rules/*', async (route) => {
    if (route.request().method() !== 'PUT') { await route.fallback(); return }
    const id = new URL(route.request().url()).pathname.split('/').pop() as string
    const rule = rules.find((candidate) => candidate.id === id)
    if (!rule) { await route.fulfill({ status: 404, json: { detail: 'No encontrado' } }); return }
    const body = route.request().postDataJSON() as Record<string, unknown>
    captured.ruleUpdate = body
    Object.assign(rule, body)
    await route.fulfill({ json: rule })
  })

  await page.route('**/api/v1/notifications/templates/*', async (route) => {
    const ruleType = new URL(route.request().url()).pathname.split('/').pop() as string
    const method = route.request().method()
    const existing = templates.find((candidate) => candidate.ruleType === ruleType)
    if (method === 'GET') {
      await route.fulfill({ json: existing ?? baseTemplate({ ruleType, isCustom: false }) })
      return
    }
    if (method === 'PUT') {
      const body = route.request().postDataJSON() as { subject: string; body: string }
      const updated: Template = { ruleType, subject: body.subject, body: body.body, isCustom: true }
      const index = templates.findIndex((candidate) => candidate.ruleType === ruleType)
      if (index >= 0) templates[index] = updated
      else templates.push(updated)
      await route.fulfill({ json: updated })
      return
    }
    if (method === 'DELETE') {
      const restored = baseTemplate({ ruleType, isCustom: false })
      const index = templates.findIndex((candidate) => candidate.ruleType === ruleType)
      if (index >= 0) templates[index] = restored
      await route.fulfill({ json: restored })
      return
    }
    await route.fallback()
  })
  await page.route('**/api/v1/notifications/templates/*/preview', async (route) => {
    const body = route.request().postDataJSON() as { subject: string; body: string }
    const render = (text: string) => text
      .replaceAll('{{periodo}}', '08/2026')
      .replaceAll('{{fecha_limite}}', '2026-09-28')
      .replaceAll('{{empresa}}', 'IAERP Demo')
    await route.fulfill({
      json: { subject: render(body.subject), bodyText: render(body.body), bodyHtml: `<p>${render(body.body)}</p>` },
    })
  })

  await page.route('**/api/v1/notifications/events*', async (route) => {
    if (route.request().method() !== 'GET') { await route.fallback(); return }
    await route.fulfill({ json: events.map(eventSummary) })
  })
  await page.route('**/api/v1/notifications/events/*', async (route) => {
    if (route.request().method() !== 'GET') { await route.fallback(); return }
    const id = new URL(route.request().url()).pathname.split('/').pop() as string
    const event = events.find((candidate) => candidate.id === id)
    if (!event) { await route.fulfill({ status: 404, json: { detail: 'No encontrado' } }); return }
    await route.fulfill({ json: event })
  })
  await page.route('**/api/v1/notifications/events/*/ack', async (route) => {
    const id = new URL(route.request().url()).pathname.split('/').slice(-2)[0] as string
    const event = events.find((candidate) => candidate.id === id)
    if (!event) { await route.fulfill({ status: 404, json: { detail: 'No encontrado' } }); return }
    if (!event.ackAt) { event.ackAt = '2026-08-22T09:00:00Z'; event.ackBy = 'owner@iaerp.local' }
    await route.fulfill({ json: eventSummary(event) })
  })
  await page.route('**/api/v1/notifications/events/*/resend', async (route) => {
    const id = new URL(route.request().url()).pathname.split('/').slice(-2)[0] as string
    const event = events.find((candidate) => candidate.id === id)
    if (!event) { await route.fulfill({ status: 404, json: { detail: 'No encontrado' } }); return }
    event.status = 'SENT'
    event.errorMessage = null
    event.sentAt = '2026-08-22T09:05:00Z'
    event.deliveries = event.deliveries.map((delivery) => ({
      ...delivery,
      status: 'SENT',
      errorMessage: null,
      sentAt: '2026-08-22T09:05:00Z',
    }))
    await route.fulfill({ json: eventSummary(event) })
  })

  await page.route('**/api/v1/notifications/billing-schedules*', async (route) => {
    if (route.request().method() === 'POST') {
      const body = route.request().postDataJSON() as Record<string, unknown>
      if (body.frequency !== 'MONTHLY' && !body.anchorMonth) {
        // Shape exacta verificada corriendo `NotificationBillingScheduleCreate`
        // real contra el mismo payload (FastAPI/Pydantic v2: RequestValidationError).
        await route.fulfill({
          status: 422,
          json: {
            detail: [{
              type: 'value_error',
              loc: ['body'],
              msg: 'Value error, Un ciclo no mensual necesita anchor_month para saber desde qué mes se cuenta',
            }],
          },
        })
        return
      }
      const created: BillingSchedule = {
        id: `schedule-${schedules.length + 1}`,
        partyId: String(body.partyId),
        partyName: 'ACME S.A.',
        contractId: null,
        dayOfMonth: Number(body.dayOfMonth),
        frequency: String(body.frequency),
        anchorMonth: body.anchorMonth == null ? null : Number(body.anchorMonth),
        amountHint: body.amountHint == null ? null : String(body.amountHint),
        notes: body.notes == null ? null : String(body.notes),
        active: true,
      }
      schedules.push(created)
      await route.fulfill({ status: 201, json: created })
      return
    }
    await route.fulfill({ json: schedules })
  })

  await page.route('**/api/v1/notifications/channel-account', (route) => route.fulfill({
    json: {
      provider: 'STUB',
      platformKeyConfigured: false,
      senderEmail: null,
      senderName: 'IAERP',
      replyTo: null,
      ready: false,
      blockingReason: 'Falta configurar la clave de Brevo',
    },
  }))

  return { rules, templates, events, schedules, captured }
}

async function openNotifications(page: Page) {
  await page.addInitScript(() => sessionStorage.clear())
  await page.goto('/')
  await page.getByRole('button', { name: 'Continuar' }).click()
  await navigateToSection(page, 'Avisos')
  await expect(page.getByRole('heading', { name: 'Avisos', exact: true })).toBeVisible()
}

test('enciende una regla desde la lista y manda el PUT con el resto de la parametrización intacta', async ({ page }) => {
  const { captured } = await mockNotifications(page, {
    rules: [baseRule({ id: 'rule-iva-declaracion', enabled: false })],
  })
  await openNotifications(page)

  const row = page.getByRole('row', { name: /Recordatorio de declaracion de IVA/ })
  await expect(row).toContainText('Apagada')
  await row.getByRole('switch').click()

  await expect(row).toContainText('Encendida')
  expect(captured.ruleUpdate).toMatchObject({
    enabled: true,
    scheduleKind: 'OFFSET_TO_DUE',
    offsetsDays: '-7,-3,-1',
    sendHour: 8,
    requireAck: true,
  })
})

test('edita una plantilla y la vista previa muestra el texto ya renderizado', async ({ page }) => {
  await mockNotifications(page, {
    rules: [baseRule()],
    templates: [baseTemplate()],
  })
  await openNotifications(page)
  await page.getByRole('tab', { name: 'Plantillas' }).click()
  await expect(page.getByRole('heading', { name: 'Plantilla del aviso' })).toBeVisible()

  await page.getByLabel('Cuerpo').fill('Aviso de prueba para {{periodo}}, vence {{fecha_limite}}.')
  await page.getByRole('button', { name: 'Vista previa' }).click()

  await expect(page.getByText('Aviso de prueba para 08/2026, vence 2026-09-28.')).toBeVisible()
})

test('lista la bitácora con un aviso enviado y uno fallido, y reintenta el fallido', async ({ page }) => {
  const sentEvent = baseEvent({ id: 'event-sent', status: 'SENT', periodLabel: '08/2026' })
  const failedEvent = baseEvent({
    id: 'event-failed',
    status: 'FAILED',
    periodLabel: '07/2026',
    sentAt: null,
    errorMessage: 'Error del proveedor',
    deliveries: [baseDelivery({ id: 'delivery-failed', status: 'FAILED', errorMessage: 'Error del proveedor', sentAt: null })],
  })
  await mockNotifications(page, {
    rules: [baseRule()],
    events: [sentEvent, failedEvent],
  })
  await openNotifications(page)
  await page.getByRole('tab', { name: 'Bitácora' }).click()

  const sentRow = page.getByRole('row', { name: /08\/2026/ })
  await expect(sentRow).toContainText('Enviado')
  await expect(sentRow.getByRole('button', { name: 'Reintentar' })).toHaveCount(0)

  const failedRow = page.getByRole('row', { name: /07\/2026/ })
  await expect(failedRow).toContainText('Fallido')
  await failedRow.getByRole('button', { name: 'Reintentar' }).click()

  await expect(failedRow).toContainText('Enviado')
  await expect(failedRow.getByRole('button', { name: 'Reintentar' })).toHaveCount(0)
})

test('crea un calendario no mensual sin mes ancla y muestra el 422 del backend como error legible', async ({ page }) => {
  await mockNotifications(page, { rules: [baseRule()] })
  await openNotifications(page)
  await page.getByRole('tab', { name: 'Calendario de facturación' }).click()

  await page.getByRole('button', { name: 'Nuevo calendario' }).first().click()
  await expect(page.getByRole('heading', { name: 'Nuevo calendario de facturación' })).toBeVisible()

  await page.getByRole('combobox', { name: 'Cliente del calendario de facturación' }).fill('ACME')
  await page.getByRole('option', { name: /ACME/ }).click()
  await page.getByLabel('Día del mes').fill('15')
  await page.getByLabel('Frecuencia').selectOption('BIMONTHLY')
  await expect(page.getByLabel('Mes ancla')).toBeVisible()

  await page.getByRole('button', { name: 'Guardar' }).click()

  await expect(page.getByRole('alert')).toContainText(
    'Un ciclo no mensual necesita anchor_month para saber desde qué mes se cuenta',
  )
  // Sigue en el formulario: un 422 no debe dejar la pantalla en un estado ambiguo.
  await expect(page.getByRole('heading', { name: 'Nuevo calendario de facturación' })).toBeVisible()
})

test('navega la pestaña de Reglas por teclado con foco visible y roles ARIA correctos', async ({ page }) => {
  await mockNotifications(page, { rules: [baseRule()] })
  await openNotifications(page)

  const tablist = page.getByRole('tablist', { name: 'Secciones de avisos' })
  await expect(tablist).toBeVisible()
  const rulesTab = page.getByRole('tab', { name: 'Reglas' })
  await expect(rulesTab).toHaveAttribute('aria-selected', 'true')

  await rulesTab.focus()
  await page.keyboard.press('ArrowRight')
  const templatesTab = page.getByRole('tab', { name: 'Plantillas' })
  await expect(templatesTab).toHaveAttribute('aria-selected', 'true')
  await expect(templatesTab).toBeFocused()

  await page.keyboard.press('ArrowLeft')
  await expect(rulesTab).toBeFocused()
  await expect(rulesTab).toHaveAttribute('aria-selected', 'true')

  await page.getByRole('button', { name: 'Configurar' }).click()
  await expect(page.getByRole('heading', { name: /Configurar/ })).toBeVisible()

  await page.keyboard.press('Tab')
  const focusedTag = await page.evaluate(() => document.activeElement?.tagName)
  expect(['INPUT', 'SELECT', 'TEXTAREA']).toContain(focusedTag)
})
