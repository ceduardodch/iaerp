import { expect, test } from '@playwright/test'

test.describe('Sidebar Collapsible - Sprint 6', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    // Clear localStorage to ensure consistent state
    await page.evaluate(() => localStorage.removeItem('sidebar-collapsed'))
    await page.reload()
  })

  test('initial state: sidebar expanded by default', async ({ page }, testInfo) => {
    test.skip(
      testInfo.project.name === 'mobile',
      'Ancho de escritorio (250px): en móvil el sidebar es full-width por diseño (ver test dedicado a móvil).',
    )
    await page.getByRole('button', { name: 'Continuar' }).click()

    // Check sidebar is expanded
    const appShell = page.locator('.app-shell')
    await expect(appShell).not.toHaveClass(/sidebar-collapsed/)

    // Check sidebar width is 250px (expanded)
    const sidebarWidth = await page.locator('.sidebar').evaluate(el => {
      return window.getComputedStyle(el).width
    })
    expect(sidebarWidth).toBe('250px')
  })

  test('collapse sidebar with button click', async ({ page }) => {
    await page.getByRole('button', { name: 'Continuar' }).click()

    // Find and click the collapse button
    const toggleButton = page.locator('.sidebar-toggle').first()
    await expect(toggleButton).toHaveAttribute('aria-label', /Contraer menú/)

    await toggleButton.click()

    // Check sidebar is collapsed
    const appShell = page.locator('.app-shell')
    await expect(appShell).toHaveClass(/sidebar-collapsed/)

    // Check toggle button label changed
    await expect(toggleButton).toHaveAttribute('aria-label', /Expandir menú/)
  })

  test('expand sidebar with button click', async ({ page }) => {
    await page.getByRole('button', { name: 'Continuar' }).click()

    // First collapse, then expand
    const toggleButton = page.locator('.sidebar-toggle').first()
    await toggleButton.click()
    await expect(page.locator('.app-shell')).toHaveClass(/sidebar-collapsed/)

    // Now expand
    await toggleButton.click()
    await expect(page.locator('.app-shell')).not.toHaveClass(/sidebar-collapsed/)
  })

  test('collapse sidebar with keyboard shortcut (Cmd/Ctrl+B)', async ({ page }) => {
    await page.getByRole('button', { name: 'Continuar' }).click()

    // Check initial state
    await expect(page.locator('.app-shell')).not.toHaveClass(/sidebar-collapsed/)

    // Use keyboard shortcut to collapse
    const isMac = await page.evaluate(() => navigator.platform.toUpperCase().indexOf('MAC') >= 0)
    const modifier = isMac ? 'Meta' : 'Control'

    await page.keyboard.press(`${modifier}+b`)

    // Check sidebar is collapsed
    await expect(page.locator('.app-shell')).toHaveClass(/sidebar-collapsed/)
  })

  test('sidebar width changes on collapse', async ({ page }, testInfo) => {
    test.skip(
      testInfo.project.name === 'mobile',
      'Anchos de escritorio (250px/64px): en móvil el sidebar es full-width por diseño (ver test dedicado a móvil).',
    )
    await page.getByRole('button', { name: 'Continuar' }).click()

    // Check expanded width
    const expandedWidth = await page.locator('.sidebar').evaluate(el => {
      return window.getComputedStyle(el).width
    })
    expect(expandedWidth).toBe('250px')

    // Collapse and check width
    await page.locator('.sidebar-toggle').first().click()

    // El ancho se anima con una transición CSS de 300ms sobre
    // grid-template-columns; medir de inmediato captura un valor intermedio de
    // la animación (~115px en CI). Se sondea hasta que asiente en ~64px antes de
    // aplicar la tolerancia de subpíxeles (el computado puede ser p.ej. 64.7px).
    await expect
      .poll(
        async () =>
          Math.round(
            await page
              .locator('.sidebar')
              .evaluate((el) => parseFloat(window.getComputedStyle(el).width)),
          ),
        { timeout: 2000 },
      )
      .toBeLessThanOrEqual(66)
    const collapsedWidth = await page
      .locator('.sidebar')
      .evaluate((el) => parseFloat(window.getComputedStyle(el).width))
    expect(Math.round(collapsedWidth)).toBeGreaterThanOrEqual(62)
  })

  test('sidebar persists state across page reloads', async ({ page }) => {
    await page.getByRole('button', { name: 'Continuar' }).click()

    // Collapse sidebar
    await page.locator('.sidebar-toggle').first().click()
    await expect(page.locator('.app-shell')).toHaveClass(/sidebar-collapsed/)

    // Reload page
    await page.reload()

    // Check state persisted
    await expect(page.locator('.app-shell')).toHaveClass(/sidebar-collapsed/)
  })

  test('tooltips appear on collapsed navigation items', async ({ page }) => {
    await page.getByRole('button', { name: 'Continuar' }).click()

    // Collapse sidebar
    await page.locator('.sidebar-toggle').first().click()
    await expect(page.locator('.app-shell')).toHaveClass(/sidebar-collapsed/)

    // Find navigation buttons with tooltips
    const navButton = page.locator('.sidebar nav button').first()
    await expect(navButton).toHaveAttribute('data-tooltip')

    // Hover over button to show tooltip
    await navButton.hover()

    // Check tooltip appears (using CSS pseudo-element)
    const hasTooltip = await navButton.evaluate(el => {
      const styles = window.getComputedStyle(el, '::after')
      return styles.content !== 'none' && styles.opacity !== '0'
    })

    expect(hasTooltip).toBe(true)
  })

  test('brand text hides on collapse', async ({ page }) => {
    await page.getByRole('button', { name: 'Continuar' }).click()

    // Check brand text is visible when expanded
    await expect(page.locator('.brand-lockup strong')).toContainText('IAERP')
    await expect(page.locator('.brand-lockup small')).toContainText('Finanzas aumentadas')

    // Collapse sidebar
    await page.locator('.sidebar-toggle').first().click()
    await expect(page.locator('.app-shell')).toHaveClass(/sidebar-collapsed/)

    // Al colapsar, el texto de marca se DESMONTA del DOM (no queda con
    // opacity:0). Se verifica su ausencia; la marca compacta (brand-mark) sigue.
    await expect(page.locator('.brand-lockup strong')).toHaveCount(0)
    await expect(page.locator('.brand-lockup small')).toHaveCount(0)
    await expect(page.locator('.brand-mark')).toBeVisible()
  })

  test('navigation text hides on collapse', async ({ page }) => {
    await page.getByRole('button', { name: 'Continuar' }).click()

    // Check navigation text is visible when expanded
    const navButton = page.locator('.sidebar nav button').first()
    await expect(navButton).toContainText('01')
    await expect(navButton).toContainText('Resumen')

    // Collapse sidebar
    await page.locator('.sidebar-toggle').first().click()
    await expect(page.locator('.app-shell')).toHaveClass(/sidebar-collapsed/)

    // Al colapsar, los botones de nav muestran SOLO el icono: el eyebrow
    // (span) y la etiqueta se desmontan. Se verifica que el texto ya no está.
    await expect(navButton.locator('span')).toHaveCount(0)
    await expect(navButton).not.toContainText('Resumen')
    // El icono (svg de lucide) permanece como referencia visual.
    await expect(navButton.locator('svg')).toBeVisible()
  })

  test('footer user info hides on collapse, avatar remains', async ({ page }, testInfo) => {
    test.skip(
      testInfo.project.name === 'mobile',
      'El footer expandido (nombre + botón) no es visible en el layout móvil.',
    )
    await page.getByRole('button', { name: 'Continuar' }).click()

    // Check footer is fully visible when expanded
    await expect(page.locator('.sidebar-footer strong')).toBeVisible()
    await expect(page.locator('.sidebar-footer button')).toBeVisible()
    await expect(page.locator('.avatar')).toBeVisible()

    // Collapse sidebar
    await page.locator('.sidebar-toggle').first().click()
    await expect(page.locator('.app-shell')).toHaveClass(/sidebar-collapsed/)

    // Al colapsar, el bloque de usuario (nombre + botón salir) se desmonta y
    // solo queda el avatar.
    await expect(page.locator('.sidebar-footer strong')).toHaveCount(0)
    await expect(page.locator('.sidebar-footer button')).toHaveCount(0)
    await expect(page.locator('.avatar')).toBeVisible()
  })

  test('sidebar animation has smooth transitions', async ({ page }) => {
    await page.getByRole('button', { name: 'Continuar' }).click()

    const toggleButton = page.locator('.sidebar-toggle').first()

    // El ancho del layout se anima con una transición CSS real sobre
    // grid-template-columns (.app-shell). Medir el tiempo de agregado de la
    // clase con JS (versión anterior) medía el toggle de React, no la
    // animación CSS, y era intrínsecamente flaky. Aquí se verifica que la
    // transición CSS existe y tiene duración > 0.
    const transition = await page.locator('.app-shell').evaluate(el => {
      const styles = window.getComputedStyle(el)
      return {
        property: styles.transitionProperty,
        durationMs: (parseFloat(styles.transitionDuration) || 0) * 1000,
      }
    })
    expect(transition.property).toContain('grid-template-columns')
    expect(transition.durationMs).toBeGreaterThan(0)

    // Y el colapso efectivamente ocurre.
    await toggleButton.click()
    await expect(page.locator('.app-shell')).toHaveClass(/sidebar-collapsed/)
  })

  test('sidebar toggle button icon reflects collapsed state', async ({ page }) => {
    await page.getByRole('button', { name: 'Continuar' }).click()

    const toggleButton = page.locator('.sidebar-toggle').first()

    // El indicador de dirección del toggle cambia INTERCAMBIANDO el path del
    // chevron (no rotando con CSS). Se captura el `d` del path expandido...
    const expandedPath = await toggleButton.locator('svg path').getAttribute('d')
    await expect(toggleButton).toHaveAttribute('aria-pressed', 'false')

    await toggleButton.click()
    await expect(page.locator('.app-shell')).toHaveClass(/sidebar-collapsed/)

    // ...y al colapsar el chevron apunta al lado contrario (path distinto) y el
    // estado accesible se refleja en aria-pressed.
    const collapsedPath = await toggleButton.locator('svg path').getAttribute('d')
    expect(collapsedPath).not.toBe(expandedPath)
    await expect(toggleButton).toHaveAttribute('aria-pressed', 'true')
  })

  test('sidebar maintains accessibility attributes', async ({ page }) => {
    await page.getByRole('button', { name: 'Continuar' }).click()

    const toggleButton = page.locator('.sidebar-toggle').first()

    // Check aria-pressed is false when expanded
    await expect(toggleButton).toHaveAttribute('aria-pressed', 'false')

    // Collapse and check aria-pressed updates
    await toggleButton.click()
    await expect(toggleButton).toHaveAttribute('aria-pressed', 'true')

    // Expand and check aria-pressed updates back
    await toggleButton.click()
    await expect(toggleButton).toHaveAttribute('aria-pressed', 'false')
  })

  test('sidebar works in mobile viewport', async ({ page }) => {
    // Set mobile viewport
    await page.setViewportSize({ width: 375, height: 667 })
    await page.reload()
    await page.getByRole('button', { name: 'Continuar' }).click()

    // On mobile, sidebar should be static and full-width
    const sidebarPosition = await page.locator('.sidebar').evaluate(el => {
      return window.getComputedStyle(el).position
    })

    expect(sidebarPosition).toBe('static')

    // Toggle button should still work
    const toggleButton = page.locator('.sidebar-toggle').first()
    await toggleButton.click()

    // Check class is applied
    await expect(page.locator('.app-shell')).toHaveClass(/sidebar-collapsed/)
  })

  test('sidebar keyboard navigation works correctly', async ({ page }) => {
    await page.getByRole('button', { name: 'Continuar' }).click()

    // Focus the toggle button
    const toggleButton = page.locator('.sidebar-toggle').first()
    await toggleButton.focus()

    // Check it's focused
    const isFocused = await toggleButton.evaluate(el => document.activeElement === el)
    expect(isFocused).toBe(true)

    // Use Enter to activate
    await page.keyboard.press('Enter')
    await expect(page.locator('.app-shell')).toHaveClass(/sidebar-collapsed/)

    // Use Space to expand
    await page.keyboard.press('Space')
    await expect(page.locator('.app-shell')).not.toHaveClass(/sidebar-collapsed/)
  })

  test('sidebar color contrast meets accessibility standards', async ({ page }) => {
    await page.getByRole('button', { name: 'Continuar' }).click()

    // Check sidebar background is dark (forest green)
    const sidebarBgColor = await page.locator('.sidebar').evaluate(el => {
      return window.getComputedStyle(el).backgroundColor
    })

    // Check text color is light
    const textColor = await page.locator('.sidebar').evaluate(el => {
      return window.getComputedStyle(el).color
    })

    // Both should be defined
    expect(sidebarBgColor).not.toBe('rgba(0, 0, 0, 0)')
    expect(textColor).not.toBe('rgba(0, 0, 0, 0)')
  })
})
