import { useDeferredValue, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { apiRequest, type PurchaseDocument } from '../../api'
import {
  ErpEmptyState,
  ErpPageHeader,
  ErpPanel,
  ErpStatusBadge,
  ErpToolbar,
} from '../erp'
import './PurchasesPage.css'

const amountFormatter = new Intl.NumberFormat('es-EC', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

function formatAmount(value: string | number): string {
  const amount = Number(value)
  return Number.isFinite(amount) ? amountFormatter.format(amount) : '0,00'
}

function monthLabel(month: string): string {
  return new Date(`${month}-01T12:00:00`).toLocaleDateString('es-EC', {
    month: 'long',
    year: 'numeric',
  })
}

function documentTypeLabel(type: PurchaseDocument['docType']): string {
  return {
    FACTURA: 'Factura',
    NOTA_CREDITO: 'Nota de crédito',
    NOTA_DEBITO: 'Nota de débito',
    LIQUIDACION: 'Liquidación',
  }[type]
}

function taxBracketLabel(bracket: PurchaseDocument['taxes'][number]['taxBracket']): string {
  return {
    GRAVADO: 'Gravado',
    TARIFA_CERO: 'Tarifa 0%',
    EXENTO: 'Exento',
    NO_OBJETO: 'No objeto',
  }[bracket]
}

function signedTotal(document: PurchaseDocument): number {
  return (document.docType === 'NOTA_CREDITO' ? -1 : 1) * Number(document.total)
}

export function PurchasesPage({ token }: { token: string }) {
  const [query, setQuery] = useState('')
  const [year, setYear] = useState('')
  const deferredQuery = useDeferredValue(query.trim().toLocaleLowerCase())
  const purchasesQuery = useQuery({
    queryKey: ['tax', 'purchases'],
    queryFn: () => apiRequest<PurchaseDocument[]>(token, '/tax/purchases'),
  })
  const purchases = purchasesQuery.data ?? []
  const years = [...new Set(purchases.map((purchase) => purchase.issueDate.slice(0, 4)))].sort().reverse()
  const filtered = purchases.filter((purchase) => {
    const matchesYear = !year || purchase.issueDate.startsWith(year)
    const haystack = `${purchase.supplierName ?? ''} ${purchase.supplierIdentification ?? ''} ${purchase.documentNumber ?? ''} ${purchase.accessKey ?? ''}`.toLocaleLowerCase()
    return matchesYear && (!deferredQuery || haystack.includes(deferredQuery))
  })
  const grouped = Object.entries(
    filtered.reduce<Record<string, PurchaseDocument[]>>((groups, purchase) => {
      const month = purchase.issueDate.slice(0, 7)
      ;(groups[month] ??= []).push(purchase)
      return groups
    }, {}),
  ).sort(([left], [right]) => right.localeCompare(left))

  return (
    <>
      <ErpPageHeader
        eyebrow="Documentos recibidos"
        title="Compras"
        subtitle="Consulta mes a mes las compras creadas desde XML o TXT del SRI. Esta pantalla no permite crear valores manuales."
      />
      <ErpToolbar ariaLabel="Filtros de compras">
        <label className="search-field">
          <span>Buscar compra</span>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Proveedor, número o clave SRI"
          />
        </label>
        <label>
          Año
          <select value={year} onChange={(event) => setYear(event.target.value)}>
            <option value="">Todos</option>
            {years.map((value) => <option key={value}>{value}</option>)}
          </select>
        </label>
        <ErpStatusBadge>{filtered.length} comprobantes</ErpStatusBadge>
      </ErpToolbar>
      {purchasesQuery.isPending ? <p aria-busy="true">Cargando compras…</p> : null}
      {purchasesQuery.error ? (
        <p className="form-error" role="alert">{purchasesQuery.error.message}</p>
      ) : null}
      {!purchasesQuery.isPending && !purchasesQuery.error ? (
        <ErpPanel title="Compras recibidas" count={filtered.length}>
          {grouped.length ? (
            <div className="invoice-month-list" aria-label="Compras agrupadas por mes">
              {grouped.map(([month, monthPurchases], index) => {
                const monthTotal = monthPurchases.reduce(
                  (total, purchase) => total + signedTotal(purchase),
                  0,
                )
                const monthTax = monthPurchases.reduce(
                  (total, purchase) => total + (purchase.docType === 'NOTA_CREDITO' ? -1 : 1) * Number(purchase.taxTotal),
                  0,
                )
                return (
                  <details key={month} className="invoice-month-accordion" open={index === 0}>
                    <summary>
                      <span className="invoice-month-title">{monthLabel(month)}</span>
                      <span className="invoice-month-summary">
                        {monthPurchases.length} documento{monthPurchases.length === 1 ? '' : 's'} · Total ${formatAmount(monthTotal)} · IVA ${formatAmount(monthTax)}
                      </span>
                    </summary>
                    <div className="table-wrap" tabIndex={0} aria-label={`Compras de ${monthLabel(month)}`}>
                      <table className="erp-responsive-table purchase-table">
                        <thead>
                          <tr>
                            <th>Documento</th>
                            <th>Proveedor</th>
                            <th>Fecha</th>
                            <th>Subtotal</th>
                            <th>Desglose IVA</th>
                            <th>Total</th>
                            <th>Evidencia</th>
                          </tr>
                        </thead>
                        <tbody>
                          {monthPurchases.map((purchase) => (
                            <tr key={purchase.id}>
                              <td>
                                <strong>{purchase.documentNumber ?? 'Sin número visible'}</strong>
                                <small>{documentTypeLabel(purchase.docType)}</small>
                              </td>
                              <td>
                                {purchase.supplierName ?? 'Proveedor sin nombre'}
                                <small>{purchase.supplierIdentification ?? 'Sin identificación'}</small>
                              </td>
                              <td>{purchase.issueDate}</td>
                              <td>${formatAmount(purchase.subtotal)}</td>
                              <td>
                                {purchase.taxes.length ? (
                                  <ul className="purchase-tax-breakdown">
                                    {purchase.taxes.map((tax, taxIndex) => (
                                      <li key={`${tax.sriTaxCode}-${tax.rate}-${taxIndex}`}>
                                        <span>{taxBracketLabel(tax.taxBracket)} {formatAmount(tax.rate)}%</span>
                                        <strong>${formatAmount(tax.taxAmount)}</strong>
                                        <small>Base ${formatAmount(tax.baseAmount)}</small>
                                      </li>
                                    ))}
                                  </ul>
                                ) : 'Sin desglose confirmado'}
                              </td>
                              <td><strong>${formatAmount(purchase.total)}</strong></td>
                              <td>
                                <ErpStatusBadge tone={purchase.isPreliminary ? 'warning' : 'success'}>
                                  {purchase.isPreliminary ? 'Preliminar' : 'XML confirmado'}
                                </ErpStatusBadge>
                                <small className="purchase-id">ID {purchase.id}</small>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </details>
                )
              })}
            </div>
          ) : (
            <ErpEmptyState
              title="No hay compras para mostrar"
              description="Carga los XML en Tributario; las compras aparecerán aquí según su fecha real de emisión."
            />
          )}
        </ErpPanel>
      ) : null}
    </>
  )
}
