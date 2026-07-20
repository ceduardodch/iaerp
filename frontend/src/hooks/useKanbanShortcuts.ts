import { useEffect } from 'react'
import type { Lead } from '../api'
import { PIPELINE } from '../components/crm/CrmKanban'

/**
 * Atajos de teclado del kanban CRM (Sprint 2):
 *
 * - ← → mueven el foco entre columnas (misma fila visual)
 * - ↑ ↓ mueven el foco dentro de una columna
 * - Enter abre la card enfocada: no requiere manejo aquí, el navegador ya
 *   activa el `onClick` del `<button>` nativo enfocado.
 * - Esc: si el panel de atajos está abierto lo cierra; si no, y hay
 *   selección múltiple activa, la limpia. Cerrar el modal de detalle con Esc
 *   lo maneja `ErpModal` directamente (tiene prioridad al estar por encima).
 *
 * La posición "actual" se lee de `document.activeElement` (no de estado
 * React) para no pelear con el foco real del navegador. Cada card es un
 * `<button class="lead-card-button">` dentro de `[data-lead-id]`, así que Tab
 * ya las alcanza de forma nativa; las flechas son una mejora encima de eso.
 */
export function useKanbanShortcuts({
  filteredLeads,
  hintOpen,
  setHintOpen,
  selectedCount,
  clearSelection,
}: {
  filteredLeads: Lead[]
  hintOpen: boolean
  setHintOpen: (open: boolean) => void
  selectedCount: number
  clearSelection: () => void
}) {
  useEffect(() => {
    function columnsWithLeads(): Array<{ stage: string; leads: Lead[] }> {
      return PIPELINE.map((stage) => ({
        stage: stage.id as string,
        leads: filteredLeads.filter((lead) => lead.status === stage.id),
      })).filter((column) => column.leads.length > 0)
    }

    function focusLead(leadId: string) {
      document
        .querySelector<HTMLButtonElement>(`[data-lead-id="${leadId}"] button.lead-card-button`)
        ?.focus()
    }

    function currentPosition(): { columnIndex: number; leadIndex: number } | null {
      const active = document.activeElement
      const card = active?.closest<HTMLElement>('[data-lead-id]')
      if (!card) return null
      const leadId = card.dataset.leadId
      const columns = columnsWithLeads()
      for (let columnIndex = 0; columnIndex < columns.length; columnIndex += 1) {
        const leadIndex = columns[columnIndex].leads.findIndex((lead) => lead.id === leadId)
        if (leadIndex !== -1) return { columnIndex, leadIndex }
      }
      return null
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        if (hintOpen) {
          event.preventDefault()
          setHintOpen(false)
          return
        }
        if (selectedCount > 0) {
          event.preventDefault()
          clearSelection()
        }
        return
      }

      if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) {
        return
      }

      // No interceptar flechas dentro de inputs/selects/textarea (forms).
      const target = event.target as HTMLElement | null
      if (target && ['INPUT', 'SELECT', 'TEXTAREA'].includes(target.tagName)) {
        return
      }

      const columns = columnsWithLeads()
      if (columns.length === 0) return

      const position = currentPosition()
      if (!position) {
        // Sin card enfocada: la primera flecha enfoca la primera card visible.
        event.preventDefault()
        focusLead(columns[0].leads[0].id)
        return
      }

      event.preventDefault()
      const { columnIndex, leadIndex } = position

      if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
        const nextColumnIndex =
          event.key === 'ArrowLeft'
            ? Math.max(0, columnIndex - 1)
            : Math.min(columns.length - 1, columnIndex + 1)
        const nextColumn = columns[nextColumnIndex]
        const nextLead =
          nextColumn.leads[Math.min(leadIndex, nextColumn.leads.length - 1)]
        focusLead(nextLead.id)
        return
      }

      const column = columns[columnIndex]
      const nextLeadIndex =
        event.key === 'ArrowUp'
          ? Math.max(0, leadIndex - 1)
          : Math.min(column.leads.length - 1, leadIndex + 1)
      focusLead(column.leads[nextLeadIndex].id)
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [filteredLeads, hintOpen, setHintOpen, selectedCount, clearSelection])
}
