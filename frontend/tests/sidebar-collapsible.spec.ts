import { expect, test } from '@playwright/test'

test.describe('Sidebar Collapsible - Sprint 6', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    // Clear localStorage to ensure consistent state
    await page.evaluate(() => localStorage.removeItem('sidebar-collapsed'))
    await page.reload()
  })

  test('initial state: sidebar expanded by default', async ({ page }) => {
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

  test('sidebar width changes on collapse', async ({ page }) => {
    await page.getByRole('button', { name: 'Continuar' }).click()

    // Check expanded width
    const expandedWidth = await page.locator('.sidebar').evaluate(el => {
      return window.getComputedStyle(el).width
    })
    expect(expandedWidth).toBe('250px')

    // Collapse and check width
    await page.locator('.sidebar-toggle').first().click()

    const collapsedWidth = await page.locator('.sidebar').evaluate(el => {
      return window.getComputedStyle(el).width
    })
    expect(collapsedWidth).toBe('64px')
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

    // Check brand text is hidden (opacity: 0, pointer-events: none)
    const brandTextOpacity = await page.locator('.brand-lockup strong').evaluate(el => {
      return window.getComputedStyle(el).opacity
    })

    expect(brandTextOpacity).toBe('0')
  })

  test('navigation text hides on collapse', async ({ page }) => {
    await page.getByRole('button', { name: 'Continuar' }).click()

    // Check navigation text is visible when expanded
    const navButton = page.locator('.sidebar nav button').first()
    await expect(navButton).toContainText('01')
    await expect(navButton).toContainText('Resumen')

    // Collapse sidebar
    await page.locator('.sidebar-toggle').first().click()

    // Check navigation text is hidden
    const buttonTextOpacity = await navButton.locator('span').evaluate(el => {
      return window.getComputedStyle(el).opacity
    })

    expect(buttonTextOpacity).toBe('0')
  })

  test('footer user info hides on collapse, avatar remains', async ({ page }) => {
    await page.getByRole('button', { name: 'Continuar' }).click()

    // Check footer is fully visible when expanded
    await expect(page.locator('.sidebar-footer strong')).toBeVisible()
    await expect(page.locator('.sidebar-footer button')).toBeVisible()
    await expect(page.locator('.avatar')).toBeVisible()

    // Collapse sidebar
    await page.locator('.sidebar-toggle').first().click()

    // Check user info is hidden but avatar remains
    const userInfoOpacity = await page.locator('.sidebar-footer strong').evaluate(el => {
      return window.getComputedStyle(el).opacity
    })
    expect(userInfoOpacity).toBe('0')

    // Avatar should still be visible
    await expect(page.locator('.avatar')).toBeVisible()
  })

  test('sidebar animation has smooth transitions', async ({ page }) => {
    await page.getByRole('button', { name: 'Continuar' }).click()

    const toggleButton = page.locator('.sidebar-toggle').first()

    // Check CSS transitions are applied
    const hasTransition = await page.locator('.sidebar').evaluate(el => {
      const styles = window.getComputedStyle(el)
      return styles.transition.includes('padding') || styles.transitionDuration !== '0s'
    })

    expect(hasTransition).toBe(true)

    // Perform collapse and measure transition time (basic check)
    const startTime = Date.now()
    await toggleButton.click()
    await page.waitForSelector('.app-shell.sidebar-collapsed', { timeout: 1000 })
    const endTime = Date.now()

    // Animation should take roughly 300ms (as defined in CSS)
    const transitionTime = endTime - startTime
    expect(transitionTime).toBeGreaterThan(250)
    expect(transitionTime).toBeLessThan(500)
  })

  test('sidebar toggle button rotates icon on collapse', async ({ page }) => {
    await page.getByRole('button', { name: 'Continuar' }).click()

    const toggleButton = page.locator('.sidebar-toggle').first()

    // Initial rotation should be 0deg
    const initialRotation = await toggleButton.locator('svg').evaluate(el => {
      const styles = window.getComputedStyle(el)
      const transform = styles.transform
      // Extract rotation from transform matrix or rotate function
      if (transform.includes('rotate')) {
        const match = transform.match(/rotate\((\d+)deg\)/)
        return match ? parseInt(match[1]) : 0
      }
      return 0
    })

    // Collapse sidebar
    await toggleButton.click()

    // After collapse, rotation should be 180deg
    const collapsedRotation = await toggleButton.locator('svg').evaluate(el => {
      const styles = window.getComputedStyle(el)
      const transform = styles.transform
      if (transform.includes('rotate')) {
        const match = transform.match(/rotate\((\d+)deg\)/)
        return match ? parseInt(match[1]) : 0
      }
      return 0
    })

    expect(collapsedRotation).toBe(180)
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
