import { useEffect, useRef, type KeyboardEvent } from 'react'

import type { InvoicePreview, Product, TaxCategory } from '../api'
import { formatAmount } from '../utils/format'
import { ErpButton } from './erp'

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
}

function formatPercent(value: string | number): string {
  return `${formatAmount(value)} %`
}

function formatCurrency(value: string | undefined): string {
  return value === undefined ? '—' : `$${formatAmount(value)}`
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
}: InvoiceSpreadsheetProps) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const pendingFocusRow = useRef<number | null>(null)

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

  return (
    <div className="invoice-spreadsheet-section">
      <div className="invoice-spreadsheet-wrap" ref={wrapRef}>
        <table className="invoice-spreadsheet" aria-label="Líneas de factura">
          <thead>
            <tr>
              <th scope="col">Producto</th>
              <th scope="col">Descripción</th>
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
                    <select
                      aria-label={`Producto ${index + 1}`}
                      value={line.productId}
                      onChange={(event) => onProductChange(line.key, event.target.value)}
                      onKeyDown={(event) => handleKeyDown(event, index, 0)}
                      data-row={index}
                      data-col={0}
                      required
                    >
                      <option value="" disabled>Seleccionar…</option>
                      {products.map((product) => {
                        const tax = taxes.find((item) => item.id === product.taxCategoryId)
                        return (
                          <option key={product.id} value={product.id}>
                            {product.name}{tax ? ` · IVA ${formatPercent(tax.rate)}` : ''}
                          </option>
                        )
                      })}
                    </select>
                  </td>
                  <td>
                    <input
                      aria-label={`Descripción ${index + 1}`}
                      type="text"
                      value={line.description}
                      onChange={(event) => onUpdateLine(line.key, { description: event.target.value })}
                      onKeyDown={(event) => handleKeyDown(event, index, 1)}
                      data-row={index}
                      data-col={1}
                      required
                    />
                  </td>
                  <td>
                    <input
                      aria-label={`Cantidad ${index + 1}`}
                      className={quantityInvalid ? 'cell-invalid' : undefined}
                      aria-invalid={quantityInvalid ? 'true' : undefined}
                      type="number"
                      min="0.000001"
                      step="0.000001"
                      value={line.quantity}
                      onChange={(event) => onUpdateLine(line.key, { quantity: event.target.value })}
                      onKeyDown={(event) => handleKeyDown(event, index, 2)}
                      data-row={index}
                      data-col={2}
                      required
                    />
                  </td>
                  <td>
                    <input
                      aria-label={`Precio unitario ${index + 1}`}
                      className={unitPriceInvalid ? 'cell-invalid' : undefined}
                      aria-invalid={unitPriceInvalid ? 'true' : undefined}
                      type="number"
                      min="0"
                      step="0.000001"
                      value={line.unitPrice}
                      onChange={(event) => onUpdateLine(line.key, { unitPrice: event.target.value })}
                      onKeyDown={(event) => handleKeyDown(event, index, 3)}
                      data-row={index}
                      data-col={3}
                      required
                    />
                  </td>
                  <td>
                    <input
                      aria-label={`Descuento ${index + 1}`}
                      type="number"
                      min="0"
                      step="0.01"
                      value={line.discount}
                      onChange={(event) => onUpdateLine(line.key, { discount: event.target.value })}
                      onKeyDown={(event) => handleKeyDown(event, index, 4)}
                      data-row={index}
                      data-col={4}
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
                        onClick={() => onRemoveLine(line.key)}
                      >
                        Quitar
                      </ErpButton>
                    ) : null}
                  </td>
                </tr>
              )
            })}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row" colSpan={5}>
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
      <ErpButton variant="secondary" onClick={onAddLine}>
        Agregar línea
      </ErpButton>
    </div>
  )
}
