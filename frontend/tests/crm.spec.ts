import { expect, test } from '@playwright/test'

test('creates an opportunity and advances it through the accessible CRM flow', async ({ page }) => {
  const title = `Venta AWS E2E ${Date.now()}`

  await page.goto('/')
  await page.getByRole('button', { name: 'Continuar' }).click()
  await page.getByRole('button', { name: 'CRM' }).click()
  await expect(page.getByRole('heading', { name: 'Pipeline' })).toBeVisible()

  await page.getByRole('button', { name: 'Nueva oportunidad' }).first().click()
  await page.getByLabel('Título').fill(title)
  await page.getByRole('combobox', { name: 'Contacto', exact: true }).selectOption({ index: 1 })
  await page.getByLabel('Valor estimado').fill('2500.50')
  await page.getByRole('textbox', { name: 'Origen', exact: true }).fill('Playwright')
  await page.getByRole('button', { name: 'Guardar' }).click()

  await expect(page.getByRole('heading', { name: title })).toBeVisible()
  await expect(page.getByText('Sin responsable')).toHaveCount(0)
  await page.getByRole('button', { name: 'Contactado', exact: true }).click()
  await expect(page.getByText('Contactado', { exact: true }).first()).toBeVisible()

  await page.getByRole('button', { name: 'Volver al pipeline' }).click()
  await expect(page.getByRole('heading', { name: 'Pipeline' })).toBeVisible()
  await expect(page.getByText(title)).toBeVisible()
})
