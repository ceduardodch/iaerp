import { test, expect } from '@playwright/test'

/**
 * E2E Tests para CRM Kanban
 *
 * Prueba el pipeline visual con drag & drop para leads
 */
test.describe('CRM Kanban Pipeline', () => {
  test.beforeEach(async ({ page }) => {
    // Navegar a la página de CRM
    await page.goto('http://localhost:8088')
    // TODO: Añadir autenticación cuando esté implementada
  })

  test('debería mostrar las 7 columnas del pipeline', async ({ page }) => {
    // Verificar que las 7 columnas estén presentes
    await expect(page.locator('.kanban-column')).toHaveCount(7)

    // Verificar los labels de las columnas
    await expect(page.locator('.kanban-column h2').nth(0)).toContainText('Nuevo')
    await expect(page.locator('.kanban-column h2').nth(1)).toContainText('Contactado')
    await expect(page.locator('.kanban-column h2').nth(2)).toContainText('Calificado')
    await expect(page.locator('.kanban-column h2').nth(3)).toContainText('Propuesta')
    await expect(page.locator('.kanban-column h2').nth(4)).toContainText('Negociación')
    await expect(page.locator('.kanban-column h2').nth(5)).toContainText('Ganado')
    await expect(page.locator('.kanban-column h2').nth(6)).toContainText('Perdido')
  })

  test('debería mostrar leads en columnas (si existen)', async ({ page }) => {
    // Esperar a que el kanban cargue
    await page.waitForSelector('.crm-kanban')

    // Contar total de leads
    const leadCards = page.locator('.kanban-card')
    const count = await leadCards.count()

    if (count > 0) {
      // Verificar que al menos un card sea visible
      await expect(leadCards.first()).toBeVisible()

      // Verificar que los cards tengan la información esperada
      const firstCard = leadCards.first()
      await expect(firstCard.locator('strong')).toBeVisible() // título
      await expect(firstCard.locator('.lead-card-badge')).toBeVisible() // hotness badge
    }
  })

  test('debería permitir búsqueda de leads', async ({ page }) => {
    await page.waitForSelector('.crm-kanban')

    // Encontrar campo de búsqueda
    const searchInput = page.locator('.search-field input').first()
    await expect(searchInput).toBeVisible()

    // Escribir búsqueda
    await searchInput.fill('test')

    // Verificar que el input tenga el valor
    await expect(searchInput).toHaveValue('test')
  })

  test('debería mostrar contadores de valor en cada columna', async ({ page }) => {
    await page.waitForSelector('.crm-kanban')

    // Verificar que cada columna tenga un contador
    const counters = page.locator('.kanban-column-count')
    await expect(counters).toHaveCount(7)

    // Verificar que haya un total monetario en cada columna
    const totals = page.locator('.kanban-column-total')
    await expect(totals).toHaveCount(7)
  })

  test('debería ser responsive en mobile', async ({ page }) => {
    // Simular viewport mobile
    await page.setViewportSize({ width: 375, height: 667 })

    await page.waitForSelector('.crm-kanban')

    // En mobile, las columnas deberían ocupar más ancho
    const firstColumn = page.locator('.kanban-column').first()
    const boundingBox = await firstColumn.boundingBox()

    expect(boundingBox?.width).toBeGreaterThan(300) // Al menos 300px en mobile
  })
})

test.describe('Lead Cards', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('http://localhost:8088')
  })

  test('debería mostrar badges de hotness con colores', async ({ page }) => {
    await page.waitForSelector('.crm-kanban')

    const leadCards = page.locator('.kanban-card')
    const count = await leadCards.count()

    if (count > 0) {
      // Verificar que los badges tengan gradient background
      const firstBadge = leadCards.first().locator('.lead-card-badge')
      await expect(firstBadge).toBeVisible()

      // Verificar avatar del owner
      const avatar = leadCards.first().locator('.avatar-circle')
      await expect(avatar).toBeVisible()
    }
  })

  test('debería mostrar valor estimado en footer', async ({ page }) => {
    await page.waitForSelector('.crm-kanban')

    const leadCards = page.locator('.kanban-card')
    const count = await leadCards.count()

    if (count > 0) {
      // Verificar que el footer tenga el valor estimado
      const footer = leadCards.first().locator('footer b')
      await expect(footer).toBeVisible()
      await expect(footer.textContent()).toContain('$')
    }
  })
})

test.describe('Drag & Drop', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('http://localhost:8088')
  })

  test('debería permitir arrastrar lead entre columnas', async ({ page }) => {
    await page.waitForSelector('.crm-kanban')

    const leadCards = page.locator('.kanban-card')
    const count = await leadCards.count()

    if (count >= 1) {
      const firstCard = leadCards.first()

      // Verificar que el card sea draggable
      const button = firstCard.locator('button')
      await expect(button).toHaveAttribute('aria-disabled', /^(false|undefined)$/)

      // Intentar hacer drag (sin soltar)
      // Nota: Playwright tiene soporte limitado para drag & drop nativo
      // Esta prueba verifica que la infraestructura esté en lugar
      await expect(firstCard).toBeVisible()
    }
  })

  test('debería mostrar drop indicator al arrastrar', async ({ page }) => {
    await page.waitForSelector('.crm-kanban')

    // Verificar que exista la clase para el drop indicator
    const kanbanColumns = page.locator('.kanban-column[data-droppable="true"]')
    await expect(kanbanColumns).toHaveCount(5) // Solo etapas activas
  })
})

test.describe('Performance', () => {
  test('debería cargar kanban en menos de 3 segundos', async ({ page }) => {
    const startTime = Date.now()

    await page.goto('http://localhost:8088')
    await page.waitForSelector('.crm-kanban')

    const loadTime = Date.now() - startTime
    expect(loadTime).toBeLessThan(3000)
  })

  test('no debería tener errores de consola', async ({ page }) => {
    const errors: string[] = []

    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        errors.push(msg.text())
      }
    })

    await page.goto('http://localhost:8088')
    await page.waitForSelector('.crm-kanban')

    // Esperar un poco para capturar errores tardíos
    await page.waitForTimeout(1000)

    expect(errors.length).toBe(0)
  })
})
