import { expect, type Page } from '@playwright/test'

/**
 * Elige una opción en un `ErpCombobox`.
 *
 * Cliente y producto dejaron de ser `<select>` nativos (listas de cientos de
 * registros son inservibles sin buscador), así que `selectOption` ya no aplica:
 * hay que abrir la lista y hacer clic en la opción. El texto se escribe para
 * filtrar, igual que lo haría una persona.
 */
export async function pickCombobox(
  page: Page,
  fieldLabel: string,
  optionLabel: string,
): Promise<void> {
  const input = page.getByRole('combobox', { name: fieldLabel, exact: true })
  await input.click()
  await input.fill(optionLabel)
  // Sin `exact`: el nombre accesible de la opción incluye su pista (RUC del
  // cliente, IVA del producto) además de la etiqueta.
  await page.getByRole('option', { name: optionLabel }).first().click()
  // El campo muestra la etiqueta elegida, no la búsqueda a medias.
  await expect(input).toHaveValue(optionLabel)
}
