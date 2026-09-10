import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { logout, navigateToSection } from './navigation'

const tenantNorte = '11111111-1111-4111-8111-111111111111'
const tenantSur = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const ownerEmail = 'owner@iaerp.local'

async function login(page: Page, tenantId: string) {
  await page.goto('/')
  await page.getByLabel('Correo').fill(ownerEmail)
  await page.getByLabel('ID de empresa').fill(tenantId)
  await page.getByRole('button', { name: 'Continuar' }).click()
}

async function issueToken(
  request: APIRequestContext,
  tenantId: string,
  scopes: string[],
) {
  const response = await request.post('/api/v1/dev/token', {
    data: { email: ownerEmail, tenantId, scopes },
  })
  expect(response.ok()).toBeTruthy()
  return (await response.json()) as { accessToken: string }
}

test.describe.configure({ mode: 'serial' })

test('login and tenant switch preserve isolation', async ({ page }) => {
  const suffix = crypto.randomUUID().slice(0, 8)
  const contactName = `Cliente E2E Norte ${suffix}`
  const identification = BigInt(`0x${suffix}`).toString().padStart(10, '0').slice(-10)

  await login(page, tenantNorte)
  await expect(
    page.getByRole('heading', { name: 'IAERP Demo Norte' }),
  ).toBeVisible()

  await navigateToSection(page, 'Contactos')
  await page.getByRole('button', { name: 'Nuevo contacto' }).click()
  await page.getByLabel('Nombre o razón social').fill(contactName)
  await page.getByLabel('Número').fill(identification)
  await page.getByRole('button', { name: 'Guardar' }).click()
  await expect(page.getByText(contactName, { exact: true })).toBeVisible()

  const editedName = `${contactName} Editado`
  await page.getByRole('button', { name: `Editar ${contactName}` }).click()
  await expect(page.getByRole('heading', { name: 'Editar contacto' })).toBeVisible()
  await page.getByLabel('Nombre o razón social').fill(editedName)
  await page.getByRole('button', { name: 'Guardar' }).click()
  await expect(page.getByText(editedName, { exact: true })).toBeVisible()

  await logout(page)
  await login(page, tenantSur)
  await expect(
    page.getByRole('heading', { name: 'IAERP Demo Sur' }),
  ).toBeVisible()
  await navigateToSection(page, 'Contactos')
  await expect(page.getByText(editedName)).toHaveCount(0)
})

test('creates a product through the real API and refreshes the catalog', async ({
  page,
}) => {
  const suffix = crypto.randomUUID().slice(0, 8)
  // Un servicio contratado por concurso público se nombra con el objeto, la
  // entidad y el número de proceso; el caso real que falló medía 268
  // caracteres y no cabía en la columna de 200.
  const productName = `CONTRATO DE ENCARGO DE TRATAMIENTO DE DATOS PERSONALES RELATIVO A LA RENOVACION DE UN SERVICIO GESTIONADO DESTINADO A LA PROTECCION DE LA INFRAESTRUCTURA DE UNA ENTIDAD DEMO E2E ${suffix} No.000-CM-2026 DEL (1 JULIO 2026 AL 31 JULIO 2026)`
  expect(productName.length).toBeGreaterThan(200)

  await login(page, tenantNorte)
  await navigateToSection(page, 'Catálogos')
  await page.getByRole('button', { name: 'Nuevo producto' }).click()
  // El tope real es el de `ProductCreate` (300 para nombre, 80 para código), y
  // 300 es a su vez el de `detalle/descripcion` en el esquema SRI. El
  // formulario lo frena aquí en vez de dejar que el 422 de Pydantic llegue
  // crudo a la pantalla ("name: String should have at most 200 characters").
  const nameField = page.getByLabel('Nombre')
  await nameField.fill('x'.repeat(360))
  await expect(nameField).toHaveValue('x'.repeat(300))
  const codeField = page.getByLabel('Código interno')
  await codeField.fill('C'.repeat(120))
  await expect(codeField).toHaveValue('C'.repeat(80))
  await nameField.fill(productName)
  await codeField.fill(`E2E-${suffix}`)
  await page.getByLabel('Precio unitario').fill('12.345678')
  await page.getByRole('button', { name: 'Guardar' }).click()

  const productCard = page
    .getByRole('article')
    .filter({ has: page.getByRole('heading', { name: productName }) })
  await expect(productCard).toBeVisible()
  await expect(productCard.getByText('$12,35')).toBeVisible()

  await page.getByRole('button', { name: `Editar ${productName}` }).click()
  await expect(page.getByRole('heading', { name: 'Editar producto' })).toBeVisible()
  await page.getByLabel('Precio unitario').fill('14.500000')
  await page.getByRole('button', { name: 'Guardar' }).click()
  await expect(productCard.getByText('$14,50')).toBeVisible()
})

test('restricted token shows an accessible authorization error', async ({
  page,
  request,
}) => {
  const token = await issueToken(request, tenantNorte, ['context:read'])
  await page.goto('/')
  await page.evaluate(
    ({ accessToken }) => {
      sessionStorage.setItem(
        'iaerp.auth.v1',
        JSON.stringify({
          token: accessToken,
          displayName: 'restricted-user',
        }),
      )
    },
    token,
  )
  await page.reload()

  await expect(
    page.getByRole('heading', { name: 'No pudimos abrir el espacio' }),
  ).toBeVisible()
  await expect(page.getByRole('alert')).toContainText('Missing scopes')
})
