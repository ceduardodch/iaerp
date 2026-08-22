import { expect, type Page } from '@playwright/test'

const sectionGroups: Record<string, string> = {
  'Bandeja de acción': 'Comercial',
  CRM: 'Comercial',
  Contactos: 'Comercial',
  Contratos: 'Comercial',
  Facturas: 'Operaciones',
  Cartera: 'Operaciones',
  Compras: 'Operaciones',
  Tributario: 'Operaciones',
  Catálogos: 'Administración',
  Empresa: 'Administración',
  Nómina: 'Administración',
}

/** Navega por la cabecera agrupada en desktop o por el panel lateral en móvil. */
export async function navigateToSection(page: Page, section: string): Promise<void> {
  const mobileMenu = page.getByRole('button', { name: 'Menú', exact: true })
  const navigation = page.getByRole('navigation', { name: 'Navegación principal' })
  await expect(mobileMenu.or(navigation)).toBeVisible()

  if (await mobileMenu.isVisible()) {
    await mobileMenu.click()
    await page.getByRole('navigation', { name: 'Navegación principal móvil' })
      .getByRole('button', { name: section, exact: true })
      .click()
    return
  }

  if (section === 'Resumen') {
    await navigation.getByRole('button', { name: section, exact: true }).click()
    return
  }

  const group = sectionGroups[section]
  if (!group) throw new Error(`La sección ${section} no tiene grupo de navegación`)
  const destination = navigation.getByRole('button', { name: section, exact: true })
  if (!(await destination.isVisible())) {
    await navigation.getByRole('button', { name: group, exact: true }).click()
  }
  await destination.click()
}

/** Cierra la sesión desde la cabecera desktop o desde el panel móvil. */
export async function logout(page: Page): Promise<void> {
  const mobileMenu = page.getByRole('button', { name: 'Menú', exact: true })

  if (await mobileMenu.isVisible()) {
    await mobileMenu.click()
    await page
      .getByRole('dialog', { name: 'Menú principal' })
      .getByRole('button', { name: 'Cerrar sesión' })
      .click()
    return
  }

  await page.getByRole('button', { name: 'Cerrar sesión' }).click()
}
