import { expect, test, type Page } from '@playwright/test'

test.skip(
  process.env.E2E_OIDC !== '1',
  'OIDC E2E requires the Compose stack in AUTH_MODE=oidc',
)

async function login(page: Page, alias: string, expectedTenant: string) {
  await page.getByLabel('Alias de empresa').fill(alias)
  await page.getByRole('button', { name: 'Continuar con Keycloak' }).click()

  await page.getByLabel('Username or email').fill('owner')
  await page.getByRole('button', { name: 'Sign In' }).click()
  await page.getByRole('textbox', { name: 'Password' }).fill('DemoPass123!')
  await page.getByRole('button', { name: 'Sign In' }).click()

  await expect(page).toHaveURL('http://localhost:8088/')
  await expect(page.getByRole('heading', { name: expectedTenant })).toBeVisible()
}

test('PKCE login changes tenant only through a new organization authorization', async ({
  page,
}) => {
  await page.goto('/')
  await login(page, 'iaerp-norte', 'IAERP Demo Norte')

  await page.getByRole('button', { name: '02 Contactos' }).click()
  await expect(
    page.getByText('Cliente Sintetico Norte', { exact: true }),
  ).toBeVisible()
  await page.getByRole('button', { name: 'Cerrar sesión' }).click()

  await expect(page.getByRole('heading', { name: 'Elegir empresa' })).toBeVisible()
  await login(page, 'iaerp-sur', 'IAERP Demo Sur')
  await page.getByRole('button', { name: '02 Contactos' }).click()
  await expect(
    page.getByText('Cliente Sintetico Norte', { exact: true }),
  ).toHaveCount(0)
  await expect(
    page.getByText('Proveedor Sintetico Sur', { exact: true }),
  ).toBeVisible()
})
