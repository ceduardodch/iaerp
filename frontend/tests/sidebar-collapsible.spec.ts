import { expect, test } from '@playwright/test'

const navigationLabels = ['Resumen', 'Contactos', 'Productos', 'Facturas', 'Empresa', 'Cartera', 'CRM']

test.describe('Navegación principal', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: 'Continuar' }).click()
  })

  test('muestra la marca, todas las secciones y la sesión activa', async ({ page }) => {
    const header = page.locator('.app-header')
    await expect(header).toBeVisible()
    await expect(header.getByText('IAERP', { exact: true })).toBeVisible()
    await expect(header.getByRole('navigation', { name: 'Navegación principal' })).toBeVisible()

    for (const label of navigationLabels) {
      await expect(header.getByRole('button', { name: label, exact: true })).toBeVisible()
    }

    await expect(header.getByRole('button', { name: 'Cerrar sesión' })).toBeVisible()
  })

  test('identifica la sección actual y actualiza la vista al navegar', async ({ page }) => {
    const navigation = page.getByRole('navigation', { name: 'Navegación principal' })
    const overview = navigation.getByRole('button', { name: 'Resumen', exact: true })
    await expect(overview).toHaveAttribute('aria-current', 'page')

    const products = navigation.getByRole('button', { name: 'Productos', exact: true })
    await products.click()
    await expect(products).toHaveAttribute('aria-current', 'page')
    await expect(overview).not.toHaveAttribute('aria-current')
    await expect(page.getByRole('heading', { name: 'Productos' })).toBeVisible()
  })

  test('permite navegar con teclado y conserva un foco visible', async ({ page }) => {
    const contacts = page.getByRole('navigation', { name: 'Navegación principal' })
      .getByRole('button', { name: 'Contactos', exact: true })
    await contacts.focus()
    await expect(contacts).toBeFocused()
    await page.keyboard.press('Enter')
    await expect(contacts).toHaveAttribute('aria-current', 'page')
    await expect(page.getByRole('heading', { name: 'Contactos' })).toBeVisible()
  })

  test('mantiene las etiquetas de navegación visibles sin tooltips ocultos', async ({ page }) => {
    const navigation = page.getByRole('navigation', { name: 'Navegación principal' })
    for (const label of navigationLabels) {
      const button = navigation.getByRole('button', { name: label, exact: true })
      await expect(button).toBeVisible()
      await expect(button).not.toHaveAttribute('data-tooltip')
    }
    await expect(page.locator('.sidebar-toggle')).toHaveCount(0)
  })

  test('se adapta a móvil sin ocultar las acciones principales', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 })
    const header = page.locator('.app-header')
    await expect(header).toBeVisible()
    await expect(header.getByRole('button', { name: 'Resumen', exact: true })).toBeVisible()
    await expect(header.getByRole('button', { name: 'Cerrar sesión' })).toBeVisible()
  })

  test('no usa el menú lateral ni sus atajos heredados', async ({ page }) => {
    await expect(page.locator('.sidebar')).toHaveCount(0)
    await expect(page.locator('.app-shell')).not.toHaveClass(/sidebar-collapsed/)
    await page.keyboard.press('Control+b')
    await expect(page.locator('.app-shell')).not.toHaveClass(/sidebar-collapsed/)
  })
})
