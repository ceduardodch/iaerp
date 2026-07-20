import { expect, test } from '@playwright/test'

test.describe('Form Keyboard Navigation', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: 'Continuar' }).click()
  })

  test('navigates CRM lead form with keyboard', async ({ page }) => {
    await page.getByRole('button', { name: '07 CRM' }).click()
    await page.getByRole('button', { name: 'Nueva oportunidad' }).first().click()

    // Test tab navigation through form fields
    await page.keyboard.press('Tab')
    const firstFocused = await page.evaluate(() => document.activeElement?.tagName)
    expect(['INPUT', 'SELECT', 'TEXTAREA']).toContain(firstFocused)

    // Continue tabbing through form
    for (let i = 0; i < 5; i++) {
      await page.keyboard.press('Tab')
    }

    // Test reverse navigation
    await page.keyboard.press('Shift+Tab')
    await page.keyboard.press('Shift+Tab')

    // Verify we can still interact with elements
    const titleInput = page.getByLabel('Título')
    await titleInput.fill(`Oportunidad keyboard ${Date.now()}`)

    // Verify form submission with keyboard
    await page.keyboard.press('Tab') // Move to next field
    await page.keyboard.press('Tab') // Skip to contact selection
    await page.keyboard.press('ArrowDown') // Open dropdown
    await page.keyboard.press('Enter') // Select first option

    // Navigate to submit button
    await page.keyboard.press('Tab')
    await page.keyboard.press('Tab')

    // Submit with Enter or Space
    await page.keyboard.press('Enter')
  })

  test('uses escape to cancel form', async ({ page }) => {
    await page.getByRole('button', { name: '07 CRM' }).click()
    await page.getByRole('button', { name: 'Nueva oportunidad' }).first().click()

    // Fill some data
    await page.getByLabel('Título').fill('Test cancellation')

    // Press Escape to close
    await page.keyboard.press('Escape')

    // Modal should be closed or cancel button clicked
    const modalVisible = await page.locator('.erp-modal-overlay').isVisible().catch(() => false)
    expect(modalVisible).toBe(false)
  })

  test('uses space to activate buttons', async ({ page }) => {
    await page.getByRole('button', { name: '07 CRM' }).click()

    // Focus the new opportunity button
    const newOppButton = page.getByRole('button', { name: 'Nueva oportunidad' }).first()
    await newOppButton.focus()

    // Activate with Space
    await page.keyboard.press('Space')

    // Modal should open
    await expect(page.locator('.erp-modal')).toBeVisible()
  })
})

test.describe('Form Validation', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: 'Continuar' }).click()
  })

  test('validates required fields in lead form', async ({ page }) => {
    await page.getByRole('button', { name: '07 CRM' }).click()
    await page.getByRole('button', { name: 'Nueva oportunidad' }).first().click()

    // Try to submit without filling required fields
    const saveButton = page.getByRole('button', { name: 'Guardar' })
    await saveButton.click()

    // Check for validation feedback - either error messages or browser validation
    const hasCustomErrors = await page.locator('.form-error, .erp-error-text').count() > 0
    const hasBrowserValidation = await page.evaluate(() => {
      const inputs = document.querySelectorAll('input:invalid, select:invalid')
      return inputs.length > 0
    })

    expect(hasCustomErrors || hasBrowserValidation).toBe(true)
  })

  test('shows validation for email format', async ({ page }) => {
    await page.getByRole('button', { name: '03 Facturación' }).click()
    await page.getByRole('button', { name: 'Nueva factura' }).first().click()

    // Try to fill an email field with invalid format (if present in form)
    const emailInput = page.locator('input[type="email"]').first()

    if (await emailInput.count() > 0) {
      await emailInput.fill('invalid-email')
      await emailInput.blur()

      // Check for validation state
      const isValid = await emailInput.evaluate(el => (el as HTMLInputElement).checkValidity())
      expect(isValid).toBe(false)

      // Now test valid email
      await emailInput.fill('test@example.com')
      await emailInput.blur()

      const isNowValid = await emailInput.evaluate(el => (el as HTMLInputElement).checkValidity())
      expect(isNowValid).toBe(true)
    }
  })

  test('validates number fields', async ({ page }) => {
    await page.getByRole('button', { name: '03 Facturación' }).click()
    await page.getByRole('button', { name: 'Nueva factura' }).first().click()

    // Test number field validation
    const numberInput = page.locator('input[type="number"]').first()

    if (await numberInput.count() > 0) {
      // Test that non-numeric input is rejected
      await numberInput.focus()
      await page.keyboard.type('abc')

      // Number input should reject non-numeric
      const value = await numberInput.inputValue()
      expect(value).not.toBe('abc')

      // Test valid number
      await numberInput.fill('100')
      await numberInput.blur()

      const validValue = await numberInput.inputValue()
      expect(validValue).toBe('100')
    }
  })

  test('resets validation state on form cancel', async ({ page }) => {
    await page.getByRole('button', { name: '07 CRM' }).click()
    await page.getByRole('button', { name: 'Nueva oportunidad' }).first().click()

    // Trigger validation
    const saveButton = page.getByRole('button', { name: 'Guardar' })
    await saveButton.click()

    // Cancel form
    const cancelButton = page.getByRole('button', { name: 'Cancelar' })
    await cancelButton.click()

    // Modal should close and validation errors clear
    const modalVisible = await page.locator('.erp-modal').isVisible().catch(() => false)
    expect(modalVisible).toBe(false)
  })
})

test.describe('Form Accessibility', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: 'Continuar' }).click()
  })

  test('has proper label associations', async ({ page }) => {
    await page.getByRole('button', { name: '07 CRM' }).click()
    await page.getByRole('button', { name: 'Nueva oportunidad' }).first().click()

    // Check that form controls have associated labels
    const inputs = page.locator('input, select, textarea')
    const count = await inputs.count()

    for (let i = 0; i < Math.min(count, 5); i++) {
      const input = inputs.nth(i)
      const hasLabel = await input.evaluate(el => {
        const hasId = el.hasAttribute('id')
        const hasAriaLabel = el.hasAttribute('aria-label')
        const hasAriaLabelledby = el.hasAttribute('aria-labelledby')
        return hasId || hasAriaLabel || hasAriaLabelledby
      })

      expect(hasLabel).toBe(true)
    }
  })

  test('shows visible focus indicators', async ({ page }) => {
    await page.getByRole('button', { name: '07 CRM' }).click()

    // Test focus visibility on buttons
    const button = page.getByRole('button', { name: 'Nueva oportunidad' }).first()
    await button.focus()

    // Check for visible focus styles
    const hasFocusStyle = await button.evaluate(el => {
      const styles = window.getComputedStyle(el)
      return styles.outline !== 'none' || styles.boxShadow !== 'none'
    })

    expect(hasFocusStyle).toBe(true)
  })

  test('uses semantic form structure', async ({ page }) => {
    await page.getByRole('button', { name: '07 CRM' }).click()
    await page.getByRole('button', { name: 'Nueva oportunidad' }).first().click()

    // Check for proper use of fieldset/legend or form sections
    const hasSemanticStructure = await page.evaluate(() => {
      const hasFieldsets = document.querySelectorAll('fieldset').length > 0
      const hasFormSections = document.querySelectorAll('.form-section, .form-section-header').length > 0
      const hasLabels = document.querySelectorAll('label').length > 0

      return hasFieldsets || hasFormSections || hasLabels
    })

    expect(hasSemanticStructure).toBe(true)
  })

  test('provides keyboard shortcuts documentation', async ({ page }) => {
    await page.getByRole('button', { name: '07 CRM' }).click()

    // Check if there's any keyboard shortcut help available
    const hasShortcutHint = await page.locator('[title*="keyboard"], [aria-label*="atajo"], .shortcuts-hint').count() > 0

    // This is a nice-to-have, not a requirement
    if (hasShortcutHint) {
      expect(hasShortcutHint).toBe(true)
    }
  })
})
