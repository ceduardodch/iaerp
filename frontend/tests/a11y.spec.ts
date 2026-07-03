import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

const context = {
  tenantId: '11111111-1111-4111-8111-111111111111',
  ruc: '1799999999001',
  name: 'IAERP Demo',
  roles: ['owner'],
  scopes: ['context:read', 'parties:read', 'products:read'],
  automationWritesEnabled: false,
}

async function mockApi(page: Page) {
  await page.route('**/api/v1/dev/token', (route) =>
    route.fulfill({ json: { accessToken: 'test-token' } }),
  )
  await page.route('**/api/v1/context', (route) =>
    route.fulfill({ json: context }),
  )
  await page.route('**/api/v1/parties', (route) =>
    route.fulfill({ json: [] }),
  )
  await page.route('**/api/v1/products', (route) =>
    route.fulfill({ json: [] }),
  )
  await page.route('**/api/v1/tax-categories', (route) =>
    route.fulfill({
      json: [
        {
          id: '22222222-2222-4222-8222-222222222222',
          sriCode: '4',
          name: 'IVA 15%',
          rate: '15.000000',
          active: true,
        },
      ],
    }),
  )
  await page.route('**/api/v1/establishments', (route) =>
    route.fulfill({ json: [] }),
  )
}

async function expectNoA11yViolations(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze()
  expect(results.violations).toEqual([])
}

async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => {
    const root = document.scrollingElement ?? document.documentElement
    return root.scrollWidth - root.clientWidth
  })
  expect(overflow).toBeLessThanOrEqual(1)
}

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.addInitScript(() => sessionStorage.clear())
  await mockApi(page)
})

test('login and dashboard pass WCAG 2.1 AA automated checks', async ({
  page,
}) => {
  await page.goto('/')
  await expectNoA11yViolations(page)

  await page.getByRole('button', { name: 'Continuar' }).click()
  await expect(page.getByRole('heading', { name: 'IAERP Demo' })).toBeVisible()
  await expectNoA11yViolations(page)
})

test('dashboard exposes a working keyboard skip link', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Continuar' }).click()
  await expect(page.getByRole('heading', { name: 'IAERP Demo' })).toBeVisible()

  await page.keyboard.press('Tab')
  const skipLink = page.getByRole('link', { name: 'Saltar al contenido' })
  await expect(skipLink).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('main')).toBeFocused()
})

test('primary sections are keyboard reachable and labelled', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Continuar' }).click()

  const contacts = page.getByRole('button', { name: '02 Contactos' })
  await contacts.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { name: 'Contactos', exact: true })).toBeVisible()
  await expect(page.getByLabel('Buscar contacto')).toBeVisible()
})

test('layout reflows at 320 CSS px and at 200% zoom without horizontal scroll', async ({
  page,
}) => {
  // WCAG 1.4.10 (reflow): contenido usable a 320 CSS px sin scroll horizontal.
  await page.setViewportSize({ width: 320, height: 900 })
  await page.goto('/')
  await expectNoHorizontalOverflow(page)

  await page.getByRole('button', { name: 'Continuar' }).click()
  await expect(page.getByRole('heading', { name: 'IAERP Demo' })).toBeVisible()
  await expectNoHorizontalOverflow(page)
  await expectNoA11yViolations(page)

  await page.getByRole('button', { name: '02 Contactos' }).click()
  await expect(page.getByRole('heading', { name: 'Contactos', exact: true })).toBeVisible()
  await expectNoHorizontalOverflow(page)

  // WCAG 1.4.4 (resize text): 200% de zoom en un viewport de 640 px equivale
  // a 320 CSS px efectivos y no debe introducir scroll horizontal.
  await page.setViewportSize({ width: 640, height: 900 })
  await page.evaluate(() => {
    document.documentElement.style.zoom = '200%'
  })
  await expect(page.getByRole('heading', { name: 'Contactos', exact: true })).toBeVisible()
  await expectNoHorizontalOverflow(page)
})
