import type { BankStatementImport } from '../../api'
import { ErpDataTable } from '../erp'

const amountFormatter = new Intl.NumberFormat('es-EC', {
  style: 'currency',
  currency: 'USD',
})

export function BankCreditReviews({ statement }: { statement: BankStatementImport }) {
  const rows = statement.creditReviews ?? []
  const outsideCount = statement.outsidePeriodCreditCount

  return (
    <>
      {outsideCount > 0 ? (
        <p className="fine-print">
          Abonos de otros meses en este TXT: {outsideCount}. Selecciona el mes del abono para revisarlo.
        </p>
      ) : null}
      {rows.length > 0 ? (
        <ErpDataTable
          ariaLabel="Estado de los demás abonos"
          rows={rows}
          rowKey={(item) => item.transactionId}
          columns={[
            { header: 'Fecha', cell: (item) => item.paymentDate },
            { header: 'Referencia bancaria', cell: (item) => item.reference },
            { header: 'Abono', cell: (item) => amountFormatter.format(Number(item.amount)) },
            { header: 'Resultado', cell: (item) => item.detail },
          ]}
        />
      ) : null}
    </>
  )
}
