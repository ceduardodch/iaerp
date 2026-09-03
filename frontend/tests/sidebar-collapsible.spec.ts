import { expect, test, type Page } from '@playwright/test'

import { mockDashboardEndpoints } from './dashboard-mocks'

const navigationGroups = [
  { label: 'Comercial', items: ['CRM', 'Contactos', 'Contratos'] },
  { label: 'Operaciones', items: ['Facturas', 'Cartera', 'Compras', 'Tributario'] },
  { label: 'Administración', items: ['Catálogos', 'Empresa', 'Nómina', 'Avisos'] },
]
const navigationLabels = ['Resumen', ...navigationGroups.flatMap((group) => group.items)]

async function mockApi(page: Page) {
  await page.route('**/api/v1/dev/token', (route) => route.fulfill({ json: { accessToken: 'test-token' } }))
  await mockDashboardEndpoints(page)
  await page.route('**/api/v1/context', (route) => route.fulfill({
    json: {
      tenantId: '11111111-1111-4111-8111-111111111111',
      ruc: '1799999999001',
      name: 'IAERP Demo',
      roles: ['owner'],
      scopes: [],
      automationWritesEnabled: false,
    },
  }))
  for (const path of ['parties', 'products', 'tax-categories', 'establishments', 'emission-points']) {
    await page.route(`**/api/v1/${path}`, (route) => route.fulfill({ json: [] }))
  }
}

async function login(page: Page) {
  await page.goto('/')
  await page.getByRole('button', { name: 'Continuar' }).click()
  await expect(page.getByRole('heading', { name: 'IAERP Demo' })).toBeVisible()
}

test.describe('Navegación principal', () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 })
    await mockApi(page)
    await login(page)
  })

  test('agrupa todos los módulos y mantiene visible la sesión en escritorio', async ({ page }) => {
    const header = page.locator('.app-header')
    const navigation = header.getByRole('navigation', { name: 'Navegación principal' })
    await expect(header.getByText('IAERP', { exact: true })).toBeVisible()
    await expect(navigation.getByRole('button', { name: 'Resumen', exact: true })).toBeVisible()

    for (const group of navigationGroups) {
      const trigger = navigation.getByRole('button', { name: group.label, exact: true })
      await expect(trigger).toBeVisible()
      await trigger.click()
      await expect(trigger).toHaveAttribute('aria-expanded', 'true')
      for (const label of group.items) {
        await expect(navigation.getByRole('button', { name: label, exact: true })).toBeVisible()
      }
    }

    await expect(header.getByText('IAERP Demo · RUC 1799999999001')).toBeVisible()
    await expect(header.getByRole('button', { name: 'Cerrar sesión' })).toBeVisible()
  })

  test('señala el módulo actual y lleva el foco al contenido al navegar', async ({ page }) => {
    const navigation = page.getByRole('navigation', { name: 'Navegación principal' })
    const overview = navigation.getByRole('button', { name: 'Resumen', exact: true })
    await expect(overview).toHaveAttribute('aria-current', 'page')

    await navigation.getByRole('button', { name: 'Administración', exact: true }).click()
    await navigation.getByRole('button', { name: 'Catálogos', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Productos y servicios' })).toBeVisible()
    await expect(page.getByRole('main')).toBeFocused()
    await expect(overview).not.toHaveAttribute('aria-current')
  })

  test('permite abrir grupos y navegar solo con teclado', async ({ page }) => {
    const navigation = page.getByRole('navigation', { name: 'Navegación principal' })
    const commercial = navigation.getByRole('button', { name: 'Comercial', exact: true })
    await commercial.focus()
    await page.keyboard.press('Enter')
    await expect(commercial).toHaveAttribute('aria-expanded', 'true')

    const contacts = navigation.getByRole('button', { name: 'Contactos', exact: true })
    await contacts.focus()
    await page.keyboard.press('Enter')
    await expect(page.getByRole('heading', { name: 'Contactos', exact: true })).toBeVisible()
    await expect(page.getByRole('main')).toBeFocused()
  })

  test('cierra un grupo con Escape', async ({ page }) => {
    const operations = page.getByRole('button', { name: 'Operaciones', exact: true })
    await operations.click()
    await expect(operations).toHaveAttribute('aria-expanded', 'true')
    const invoices = page.getByRole('navigation', { name: 'Navegación principal' })
      .getByRole('button', { name: 'Facturas', exact: true })
    await invoices.focus()
    await page.keyboard.press('Escape')
    await expect(operations).toHaveAttribute('aria-expanded', 'false')
    await expect(operations).toBeFocused()
  })

  test('no usa el menú lateral heredado', async ({ page }) => {
    await expect(page.locator('.sidebar')).toHaveCount(0)
    await expect(page.locator('.app-shell')).not.toHaveClass(/sidebar-collapsed/)
  })
})

test.describe('Navegación móvil', () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 })
    await mockApi(page)
    await login(page)
  })

  test('reemplaza la fila horizontal por una barra compacta y un menú completo', async ({ page }) => {
    const header = page.locator('.app-header')
    await expect(header.locator('.app-current-section')).toHaveText('Resumen')
    const menuButton = header.getByRole('button', { name: 'Menú', exact: true })
    await expect(menuButton).toBeVisible()
    await expect(menuButton).toHaveCSS('min-height', '44px')
    await expect(header.getByRole('navigation', { name: 'Navegación principal' })).toBeHidden()

    await menuButton.click()
    const dialog = page.getByRole('dialog', { name: 'Menú principal' })
    await expect(dialog).toBeVisible()
    const mobileNavigation = dialog.getByRole('navigation', { name: 'Navegación principal móvil' })
    for (const label of navigationLabels) {
      const destination = mobileNavigation.getByRole('button', { name: label, exact: true })
      await destination.scrollIntoViewIfNeeded()
      await expect(destination).toBeInViewport()
      expect((await destination.boundingBox())?.height).toBeGreaterThanOrEqual(44)
    }
  })

  test('cierra con Escape y devuelve el foco al botón Menú', async ({ page }) => {
    const menuButton = page.getByRole('button', { name: 'Menú', exact: true })
    await menuButton.click()
    await expect(page.getByRole('dialog', { name: 'Menú principal' })).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog', { name: 'Menú principal' })).toHaveCount(0)
    await expect(menuButton).toBeFocused()
  })

  test('navega, cierra el panel y deja el foco en el contenido', async ({ page }) => {
    await page.getByRole('button', { name: 'Menú', exact: true }).click()
    await page.getByRole('navigation', { name: 'Navegación principal móvil' })
      .getByRole('button', { name: 'Catálogos', exact: true })
      .click()

    await expect(page.getByRole('dialog', { name: 'Menú principal' })).toHaveCount(0)
    await expect(page.getByRole('heading', { name: 'Productos y servicios' })).toBeVisible()
    await expect(page.locator('.app-current-section')).toHaveText('Catálogos')
    await expect(page.getByRole('main')).toBeFocused()
  })

  test('no crea desbordamiento horizontal a 320 px', async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 700 })
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(overflow).toBeLessThanOrEqual(1)
  })

  test('usa grupos a 1024 px y el panel compacto a 768 px', async ({ page }) => {
    await page.setViewportSize({ width: 1024, height: 700 })
    await expect(page.getByRole('navigation', { name: 'Navegación principal' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Menú', exact: true })).toBeHidden()
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1)

    await page.setViewportSize({ width: 768, height: 700 })
    await expect(page.getByRole('navigation', { name: 'Navegación principal' })).toBeHidden()
    await expect(page.getByRole('button', { name: 'Menú', exact: true })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1)
  })
})
