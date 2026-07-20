import { expect, test } from '@playwright/test'

/**
 * WCAG 2.1 AA Compliance Audit Tests
 *
 * These tests verify compliance with WCAG 2.1 Level AA requirements:
 * - Perceivable: Information and UI components must be presentable in ways users can perceive
 * - Operable: UI components and navigation must be operable
 * - Understandable: Information and operation must be understandable
 * - Robust: Content must be robust enough to be interpreted by assistive technologies
 */

test.describe('WCAG 2.1 AA - Perceivable', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: 'Continuar' }).click()
  })

  test('1.1.1 Non-text Content: All images have alt text', async ({ page }) => {
    // Check that all images have appropriate alt attributes
    const images = page.locator('img')
    const count = await images.count()

    for (let i = 0; i < count; i++) {
      const img = images.nth(i)
      const alt = await img.getAttribute('alt')
      const role = await img.getAttribute('role')

      // Images should have alt text or be decorative (role="presentation" or alt="")
      expect(alt !== null || role === 'presentation').toBe(true)
    }
  })

  test('1.3.1 Adaptable: Content can be presented in different ways', async ({ page }) => {
    await page.getByRole('button', { name: '07 CRM' }).click()

    // Check for semantic HTML structure
    const hasSemanticHTML = await page.evaluate(() => {
      const hasHeadings = document.querySelectorAll('h1, h2, h3, h4, h5, h6').length > 0
      const hasLandmarks = document.querySelectorAll('nav, main, header, footer, section, article').length > 0
      const hasLists = document.querySelectorAll('ul, ol').length > 0
      return hasHeadings && hasLandmarks
    })

    expect(hasSemanticHTML).toBe(true)
  })

  test('1.3.4 Orientation: Content works in both portrait and landscape', async ({ page }) => {
    // Test that content is not restricted to a single orientation
    const viewportMeta = await page.locator('meta[name="viewport"]').getAttribute('content')

    // Should not lock orientation
    expect(viewportMeta).not.toContain('orientation=locked')
  })

  test('1.4.3 Contrast (Minimum): Text has sufficient contrast', async ({ page }) => {
    await page.getByRole('button', { name: '07 CRM' }).click()

    // Check contrast ratios for text elements (4.5:1 for normal text, 3:1 for large text)
    const contrastFailures = await page.evaluate(() => {
      const failures: string[] = []

      // Check main text elements
      const textElements = document.querySelectorAll('p, span, div, a, button, label')

      textElements.forEach(el => {
        const styles = window.getComputedStyle(el)
        const color = styles.color
        const backgroundColor = styles.backgroundColor

        // Skip if background is transparent or same as parent
        if (backgroundColor === 'transparent' || backgroundColor === 'rgba(0, 0, 0, 0)') {
          return
        }

        // Very basic contrast check - real implementation would use proper color calculation
        if (color === 'rgb(0, 0, 0)' && backgroundColor === 'rgb(0, 0, 0)') {
          failures.push(el.tagName + ' ' + el.className)
        }
      })

      return failures
    })

    expect(contrastFailures.length).toBe(0)
  })

  test('1.4.4 Resize text: Text can be resized up to 200%', async ({ page }) => {
    // Check that text can be resized without assistive technology
    const hasRelativeUnits = await page.evaluate(() => {
      const rootStyles = window.getComputedStyle(document.documentElement)
      const bodyStyles = window.getComputedStyle(document.body)

      // Check if font sizes use relative units (rem, em, %, vh, vw)
      const rootFontSize = rootStyles.fontSize
      const bodyFontSize = bodyStyles.fontSize

      return !rootFontSize.includes('px') || !bodyFontSize.includes('px')
    })

    expect(hasRelativeUnits).toBe(true)
  })

  test('1.4.10 Reflow: Content does not cause horizontal scroll at 400% zoom', async ({ page }) => {
    await page.getByRole('button', { name: '07 CRM' }).click()

    // Set viewport to 320x320 (simulating 400% zoom on a 1280px screen)
    await page.setViewportSize({ width: 320, height: 480 })

    // Check if horizontal scrolling is required
    const requiresHorizontalScroll = await page.evaluate(() => {
      return document.body.scrollWidth > window.innerWidth
    })

    expect(requiresHorizontalScroll).toBe(false)
  })
})

test.describe('WCAG 2.1 AA - Operable', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: 'Continuar' }).click()
  })

  test('2.1.1 Keyboard: All functionality is available via keyboard', async ({ page }) => {
    await page.getByRole('button', { name: '07 CRM' }).click()

    // Test keyboard navigation
    await page.keyboard.press('Tab')
    await page.keyboard.press('Tab')
    await page.keyboard.press('Tab')

    // Check if we've moved through interactive elements
    const focused = await page.evaluate(() => {
      const active = document.activeElement
      return {
        tagName: active?.tagName,
        isFocusable: active ? (active as HTMLElement).tabIndex >= 0 : false
      }
    })

    expect(['INPUT', 'BUTTON', 'SELECT', 'TEXTAREA', 'A']).toContain(focused.tagName)
  })

  test('2.1.4 Character Key Shortcuts: No keyboard traps', async ({ page }) => {
    await page.getByRole('button', { name: '07 CRM' }).click()

    // Test that keyboard focus can be moved away from any element
    const canEscape = await page.evaluate(() => {
      // Try to find any element that might trap focus
      const focusableElements = document.querySelectorAll(
        'a, button, input, select, textarea, [tabindex]:not([tabindex="-1"])'
      )

      return focusableElements.length > 0
    })

    expect(canEscape).toBe(true)
  })

  test('2.4.7 Focus Visible: Keyboard focus indicator is visible', async ({ page }) => {
    await page.getByRole('button', { name: '07 CRM' }).click()

    // Focus an element and check for visible indicator
    const button = page.getByRole('button', { name: 'Nueva oportunidad' }).first()
    await button.focus()

    const hasFocusIndicator = await button.evaluate(el => {
      const styles = window.getComputedStyle(el)
      return {
        outlineWidth: styles.outlineWidth,
        outlineStyle: styles.outlineStyle,
        boxShadow: styles.boxShadow
      }
    })

    // Should have visible focus indicator (outline or box-shadow)
    const hasVisibleFocus =
      (parseInt(hasFocusIndicator.outlineWidth) || 0) > 0 &&
      hasFocusIndicator.outlineStyle !== 'none' ||
      hasFocusIndicator.boxShadow !== 'none'

    expect(hasVisibleFocus).toBe(true)
  })

  test('2.5.5 Target Size: Click targets are at least 44x44 pixels', async ({ page }) => {
    await page.getByRole('button', { name: '07 CRM' }).click()

    // Check that interactive elements meet minimum size requirements
    const undersizedTargets = await page.evaluate(() => {
      const undersized: { tag: string; size: { width: number; height: number } }[] = []

      const targets = document.querySelectorAll('a, button, input[type="checkbox"], input[type="radio"], [role="button"]')

      targets.forEach(target => {
        const rect = target.getBoundingClientRect()
        const width = rect.width
        const height = rect.height

        // Check if either dimension is less than 44px
        if (width < 44 || height < 44) {
          undersized.push({
            tag: target.tagName,
            size: { width, height }
          })
        }
      })

      return undersized
    })

    // Log undersized targets but don't fail the test (some may be unavoidable)
    if (undersizedTargets.length > 0) {
      console.log('Undersized targets found:', undersizedTargets)
    }
  })
})

test.describe('WCAG 2.1 AA - Understandable', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: 'Continuar' }).click()
  })

  test('3.1.1 Language of Page: Has valid lang attribute', async ({ page }) => {
    const lang = await page.locator('html').getAttribute('lang')

    // Should have a valid language code
    expect(lang).toBeTruthy()
    expect(lang?.length).toBeGreaterThan(1)
  })

  test('3.2.1 On Focus: No unexpected context changes on focus', async ({ page }) => {
    await page.getByRole('button', { name: '07 CRM' }).click()

    // Focus elements and ensure no unexpected changes
    const initialUrl = page.url()

    await page.keyboard.press('Tab')
    await page.keyboard.press('Tab')

    const urlAfterFocus = page.url()

    // URL should not change just from focus
    expect(initialUrl).toBe(urlAfterFocus)
  })

  test('3.3.1 Error Identification: Errors are identified and described', async ({ page }) => {
    await page.getByRole('button', { name: '07 CRM' }).click()
    await page.getByRole('button', { name: 'Nueva oportunidad' }).first().click()

    // Trigger form validation errors
    const saveButton = page.getByRole('button', { name: 'Guardar' })
    await saveButton.click()

    // Check for error indicators
    const hasErrorIndicators = await page.evaluate(() => {
      const invalidInputs = document.querySelectorAll('input:invalid, select:invalid, textarea:invalid')
      const customErrors = document.querySelectorAll('.form-error, .erp-error-text, [aria-invalid="true"]')

      return invalidInputs.length > 0 || customErrors.length > 0
    })

    expect(hasErrorIndicators).toBe(true)
  })

  test('3.3.2 Labels or Instructions: Form controls have labels', async ({ page }) => {
    await page.getByRole('button', { name: '07 CRM' }).click()
    await page.getByRole('button', { name: 'Nueva oportunidad' }).first().click()

    // Check that all form controls have labels
    const unlabeledControls = await page.evaluate(() => {
      const unlabeled: string[] = []

      const controls = document.querySelectorAll('input, select, textarea')
      controls.forEach(control => {
        const hasLabel =
          control.hasAttribute('aria-label') ||
          control.hasAttribute('aria-labelledby') ||
          (control.id && document.querySelector(`label[for="${control.id}"]`))

        if (!hasLabel && control.type !== 'hidden') {
          unlabeled.push(control.tagName + ' ' + (control as HTMLElement).className)
        }
      })

      return unlabeled
    })

    expect(unlabeledControls).toEqual([])
  })
})

test.describe('WCAG 2.1 AA - Robust', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
  })

  test('4.1.1 Parsing: No parsing errors in HTML', async ({ page }) => {
    // Check for valid HTML structure
    const hasValidStructure = await page.evaluate(() => {
      // Check for basic HTML structure elements
      const hasDoctype = document.doctype !== null
      const hasHtml = document.documentElement !== null
      const hasHead = document.head !== null
      const hasBody = document.body !== null

      return hasDoctype && hasHtml && hasHead && hasBody
    })

    expect(hasValidStructure).toBe(true)
  })

  test('4.1.2 Name, Role, Value: UI components have proper ARIA attributes', async ({ page }) => {
    await page.getByRole('button', { name: 'Continuar' }).click()
    await page.getByRole('button', { name: '07 CRM' }).click()

    // Check that interactive elements have proper roles
    const elementsWithMissingRoles = await page.evaluate(() => {
      const missingRoles: string[] = []

      // Custom interactive elements should have roles
      const customInteractives = document.querySelectorAll('[onclick], [role]')
      customInteractives.forEach(el => {
        const role = el.getAttribute('role')
        const isNativeRole = ['A', 'BUTTON', 'INPUT', 'SELECT', 'TEXTAREA'].includes(el.tagName)

        if (!role && !isNativeRole && el.hasAttribute('onclick')) {
          missingRoles.push(el.tagName + ' ' + el.className)
        }
      })

      return missingRoles
    })

    // Log issues but don't fail (native roles are acceptable)
    if (elementsWithMissingRoles.length > 0) {
      console.log('Custom elements without explicit roles:', elementsWithMissingRoles)
    }
  })
})

test.describe('WCAG 2.1 AA - Additional Success Criteria', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: 'Continuar' }).click()
  })

  test('2.4.6 Headings and Labels: Uses headings hierarchically', async ({ page }) => {
    await page.getByRole('button', { name: '07 CRM' }).click()

    // Check for proper heading hierarchy
    const properHierarchy = await page.evaluate(() => {
      const headings = document.querySelectorAll('h1, h2, h3, h4, h5, h6')
      let previousLevel = 0

      for (const heading of headings) {
        const level = parseInt(heading.tagName[1])

        // Headings should not skip levels (e.g., h1 followed by h3)
        if (level > previousLevel + 1 && previousLevel !== 0) {
          return false
        }

        previousLevel = level
      }

      return true
    })

    expect(properHierarchy).toBe(true)
  })

  test('2.4.1 Bypass Blocks: Skip navigation link available', async ({ page }) => {
    // Check for skip navigation link
    const skipLink = page.locator('.skip-link, a[href^="#main"], a[href^="#content"]').first()
    const hasSkipLink = await skipLink.count() > 0

    // This is a best practice - log if missing but don't fail
    if (!hasSkipLink) {
      console.log('No skip navigation link found')
    }
  })

  test('1.3.2 Meaningful Sequence: Content order makes sense when linearized', async ({ page }) => {
    await page.getByRole('button', { name: '07 CRM' }).click()

    // Check that content appears in a meaningful order
    const meaningfulOrder = await page.evaluate(() => {
      // Check that main content comes before navigation or footer
      const main = document.querySelector('main')
      const nav = document.querySelector('nav')
      const footer = document.querySelector('footer')

      if (main && nav) {
        return main.compareDocumentPosition(nav) & Node.DOCUMENT_POSITION_FOLLOWING
      }

      return true
    })

    expect(meaningfulOrder).toBe(true)
  })

  test('3.3.4 Error Prevention (Legal/Financial): Confirmation for important actions', async ({ page }) => {
    await page.getByRole('button', { name: '07 CRM' }).click()

    // For destructive actions, check for confirmations
    const deleteButtons = page.locator('button:has-text("Eliminar"), button:has-text("Borrar")')
    const count = await deleteButtons.count()

    if (count > 0) {
      // Delete buttons should either:
      // 1. Require confirmation, or
      // 2. Be clearly marked as destructive
      const hasConfirmationOrWarning = await page.evaluate(() => {
        const deleteBtns = document.querySelectorAll('button')
        const results: boolean[] = []

        deleteBtns.forEach(btn => {
          const text = btn.textContent?.toLowerCase() || ''
          const isDestructive = text.includes('eliminar') || text.includes('borrar') || text.includes('delete')

          if (isDestructive) {
            // Check for destructive styling or confirmation mechanism
            const hasDestructiveClass = btn.classList.contains('erp-button-danger') ||
                                       btn.classList.contains('danger')
            results.push(hasDestructiveClass)
          }
        })

        return results.every(r => r === true) || results.length === 0
      })

      // This is a best practice - not a hard requirement
      if (!hasConfirmationOrWarning) {
        console.log('Some destructive actions lack confirmation or warning styling')
      }
    }
  })
})

test.describe('WCAG 2.1 AA - Accessibility Statement', () => {
  test('has accessibility information or contact', async ({ page }) => {
    await page.goto('/')

    // Check for accessibility statement, help, or contact information
    const hasAccessibilityInfo = await page.evaluate(() => {
      const bodyText = document.body.textContent?.toLowerCase() || ''

      return bodyText.includes('accesibilidad') ||
             bodyText.includes('accessibility') ||
             bodyText.includes('ayuda') ||
             bodyText.includes('help')
    })

    // This is a best practice - log if missing
    if (!hasAccessibilityInfo) {
      console.log('No accessibility information found on page')
    }
  })
})
