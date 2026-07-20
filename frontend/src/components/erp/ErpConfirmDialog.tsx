import type { ReactNode } from 'react'
import { ErpModal } from './ErpModal'
import { ErpButton } from './index'

/**
 * Confirmación reutilizable para operaciones destructivas o financieras
 * (mover leads en bloque, marcar ganado/perdido masivamente, etc.).
 */
export function ErpConfirmDialog({
  title,
  description,
  confirmLabel = 'Confirmar',
  cancelLabel = 'Cancelar',
  danger = false,
  pending = false,
  onConfirm,
  onCancel,
}: {
  title: ReactNode
  description: ReactNode
  confirmLabel?: string
  cancelLabel?: string
  danger?: boolean
  pending?: boolean
  onConfirm: () => void
  onCancel: () => void
}) {
  return (
    <ErpModal title={title} onClose={onCancel} size="sm">
      <div className="erp-confirm-body">{description}</div>
      <div className="erp-form-actions erp-confirm-actions">
        <ErpButton variant="secondary" onClick={onCancel} disabled={pending}>
          {cancelLabel}
        </ErpButton>
        <ErpButton variant={danger ? 'danger' : 'primary'} onClick={onConfirm} disabled={pending}>
          {pending ? 'Aplicando…' : confirmLabel}
        </ErpButton>
      </div>
    </ErpModal>
  )
}
