export function formatAmount(value: string | number): string {
  const amount = Number(value)
  return Number.isFinite(amount) ? amount.toLocaleString('es-EC', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }) : '0,00'
}
