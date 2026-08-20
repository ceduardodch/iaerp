import { useEffect, useMemo, useRef, type KeyboardEvent } from 'react'

import type { InvoicePreview, Product, TaxCategory } from '../api'
import { formatAmount } from '../utils/format'
import { ErpButton } from './erp'
import { ErpCombobox, type ErpComboboxOption } from './erp/ErpCombobox'

export type InvoiceSpreadsheetLine = {
  key: string
  productId: string
  description: string
  quantity: string
  unitPrice: string
  discount: string
  taxCode: string
}

type InvoiceSpreadsheetProps = {
  lines: InvoiceSpreadsheetLine[]
  products: Product[]
  taxes: TaxCategory[]
  preview?: InvoicePreview
  previewPending: boolean
  onProductChange: (key: string, productId: string) => void
  onUpdateLine: (key: string, patch: Partial<InvoiceSpreadsheetLine>) => void
  onAddLine: () => void
  onRemoveLine: (key: string) => void
  onCreateProduct?: () => void
}

function formatPercent(value: string | number): string {
  return `${formatAmount(value)} %`
}

function formatCurrency(value: string | undefined): string {
  return value === undefined ? '—' : `$${formatAmount(value)}`
}

/**
 * Deja pasar solo lo que puede formar un decimal: dígitos, un punto y una coma
 * que se normaliza a punto.
 *
 * Antes estas celdas eran `<input type="number">` y el precio se perdía al
 * escribir: el navegador considera inválido un valor a medias (por ejemplo
 * "12." o "12,5") y devuelve cadena vacía en `value`, así que el importe
 * desaparecía mientras se tecleaba. Además pintaba flechas de subir/bajar que
 * con `step="0.000001"` movían el precio en millonésimas y la rueda del mouse
 * lo cambiaba sin querer al hacer scroll sobre la tabla.
 */
function sanitizeDecimal(raw: string): string | null {
  const normalized = raw.replace(',', '.')
  if (normalized === '') return ''
  return /^\d*\.?\d*$/.test(normalized) ? normalized : null
}

export function InvoiceSpreadsheet({
  lines,
  products,
  taxes,
  preview,
  previewPending,
  onProductChange,
  onUpdateLine,
  onAddLine,
  onRemoveLine,
  onCreateProduct,
}: InvoiceSpreadsheetProps) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const pendingFocusRow = useRef<number | null>(null)

  const productOptions = useMemo<ErpComboboxOption[]>(
    () =>
      products.map((product) => {
        const tax = taxes.find((item) => item.id === product.taxCategoryId)
        return {
          value: product.id,
          label: product.name,
          hint: tax ? `IVA ${formatPercent(tax.rate)}` : undefined,
        }
      }),
    [products, taxes],
  )

  useEffect(() => {
    const row = pendingFocusRow.current
    if (row === null || row >= lines.length) return

    wrapRef.current
      ?.querySelector<HTMLElement>(`[data-row="${row}"][data-col="0"]`)
      ?.focus()
    pendingFocusRow.current = null
  }, [lines.length])

  function handleKeyDown(
    event: KeyboardEvent<HTMLInputElement | HTMLSelectElement>,
    row: number,
    column: number,
  ) {
    if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
      const nextRow = event.key === 'ArrowUp' ? row - 1 : row + 1
      const nextCell = wrapRef.current?.querySelector<HTMLElement>(
        `[data-row="${nextRow}"][data-col="${column}"]`,
      )
      if (nextCell) {
        event.preventDefault()
        nextCell.focus()
      }
      return
    }

    if (event.key === 'Enter' && row === lines.length - 1) {
      event.preventDefault()
      pendingFocusRow.current = lines.length
      onAddLine()
    }
  }

  function updateDecimal(key: string, field: 'quantity' | 'unitPrice' | 'discount', raw: string) {
    const value = sanitizeDecimal(raw)
    // Una tecla que no forma un decimal se ignora en vez de borrar la celda.
    if (value === null) return
    onUpdateLine(key, { [field]: value })
  }

  return (
    <div className="invoice-spreadsheet-section">
      <div className="invoice-spreadsheet-wrap" ref={wrapRef}>
        <table className="invoice-spreadsheet" aria-label="Líneas de factura">
          <thead>
            <tr>
              <th scope="col">Producto</th>
              <th scope="col">Cantidad</th>
              <th scope="col">P. Unit.</th>
              <th scope="col">Desc.</th>
              <th scope="col">Base</th>
              <th scope="col">IVA</th>
              <th scope="col">Total</th>
              <th scope="col"><span className="sr-only">Acción</span></th>
            </tr>
          </thead>
          <tbody>
            {lines.map((line, index) => {
              const calculatedLine = preview?.lines[index]
              const quantityInvalid = Number(line.quantity) <= 0
              const unitPriceInvalid = Number(line.unitPrice) < 0

              return (
                <tr key={line.key}>
                  <td>
                    <ErpCombobox
                      ariaLabel={`Producto ${index + 1}`}
                      options={productOptions}
                      value={line.productId}
                      onChange={(productId) => onProductChange(line.key, productId)}
                      onKeyDown={(event) => handleKeyDown(event, index, 0)}
                      placeholder="Buscar producto…"
                      dataRow={index}
                      dataCol={0}
                      required
                    />
                  </td>
                  <td>
                    <input
                      aria-label={`Cantidad ${index + 1}`}
                      className={quantityInvalid ? 'cell-invalid' : undefined}
                      aria-invalid={quantityInvalid ? 'true' : undefined}
                      type="text"
                      inputMode="decimal"
                      value={line.quantity}
                      onChange={(event) => updateDecimal(line.key, 'quantity', event.target.value)}
                      onKeyDown={(event) => handleKeyDown(event, index, 1)}
                      data-row={index}
                      data-col={1}
                      required
                    />
                  </td>
                  <td>
                    <input
                      aria-label={`Precio unitario ${index + 1}`}
                      className={unitPriceInvalid ? 'cell-invalid' : undefined}
                      aria-invalid={unitPriceInvalid ? 'true' : undefined}
                      type="text"
                      inputMode="decimal"
                      value={line.unitPrice}
                      onChange={(event) => updateDecimal(line.key, 'unitPrice', event.target.value)}
                      onKeyDown={(event) => handleKeyDown(event, index, 2)}
                      data-row={index}
                      data-col={2}
                      required
                    />
                  </td>
                  <td>
                    <input
                      aria-label={`Descuento ${index + 1}`}
                      type="text"
                      inputMode="decimal"
                      value={line.discount}
                      onChange={(event) => updateDecimal(line.key, 'discount', event.target.value)}
                      onKeyDown={(event) => handleKeyDown(event, index, 3)}
                      data-row={index}
                      data-col={3}
                    />
                  </td>
                  <td className="invoice-spreadsheet-amount">{formatCurrency(calculatedLine?.baseAmount)}</td>
                  <td className="invoice-spreadsheet-amount">{formatCurrency(calculatedLine?.taxAmount)}</td>
                  <td className="invoice-spreadsheet-amount">{formatCurrency(calculatedLine?.total)}</td>
                  <td className="invoice-spreadsheet-action">
                    {lines.length > 1 ? (
                      <ErpButton
                        variant="ghost"
                        aria-label={`Quitar línea ${index + 1}`}
                        title="Quitar línea"
                        className="erp-icon-button"
                        onClick={() => onRemoveLine(line.key)}
                      >
                        <span aria-hidden="true">✕</span>
                      </ErpButton>
                    ) : null}
                  </td>
                </tr>
              )
            })}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row" colSpan={4}>
                Totales
                <span className="invoice-spreadsheet-pending" aria-live="polite">
                  {previewPending ? 'Calculando…' : ''}
                </span>
              </th>
              <td><span>Subtotal</span>{formatCurrency(preview?.subtotal)}</td>
              <td><span>IVA total</span>{formatCurrency(preview?.taxTotal)}</td>
              <td><span>Total</span>{formatCurrency(preview?.total)}</td>
              <td />
            </tr>
          </tfoot>
        </table>
      </div>
      <div className="invoice-spreadsheet-actions">
        <ErpButton variant="secondary" onClick={onAddLine}>
          Agregar línea
        </ErpButton>
        {onCreateProduct ? (
          <ErpButton variant="secondary" onClick={onCreateProduct}>
            Crear producto o servicio
          </ErpButton>
        ) : null}
      </div>
    </div>
  )
}
