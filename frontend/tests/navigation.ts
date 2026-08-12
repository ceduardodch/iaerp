import type { Page } from '@playwright/test'

const sectionGroups: Record<string, string> = {
  CRM: 'Comercial',
  Contactos: 'Comercial',
  Contratos: 'Comercial',
  Facturas: 'Operaciones',
  Cartera: 'Operaciones',
  Compras: 'Operaciones',
  Tributario: 'Operaciones',
  Catálogos: 'Administración',
  Empresa: 'Administración',
}

/** Navega por la cabecera agrupada en desktop o por el panel lateral en móvil. */
export async function navigateToSection(page: Page, section: string): Promise<void> {
  if (section === 'Resumen') {
    await page.getByRole('navigation', { name: 'Navegación principal' })
      .getByRole('button', { name: section, exact: true })
      .click()
    return
  }

  const mobileMenu = page.getByRole('button', { name: 'Menú', exact: true })
  if (await mobileMenu.isVisible()) {
    await mobileMenu.click()
    await page.getByRole('navigation', { name: 'Navegación principal móvil' })
      .getByRole('button', { name: section, exact: true })
      .click()
    return
  }

  const group = sectionGroups[section]
  if (!group) throw new Error(`La sección ${section} no tiene grupo de navegación`)
  const navigation = page.getByRole('navigation', { name: 'Navegación principal' })
  const destination = navigation.getByRole('button', { name: section, exact: true })
  if (!(await destination.isVisible())) {
    await navigation.getByRole('button', { name: group, exact: true }).click()
  }
  await destination.click()
}
