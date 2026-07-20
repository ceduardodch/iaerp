import { useMemo, type ReactNode } from 'react'
import { useDroppable } from '@dnd-kit/core'
import { motion } from 'framer-motion'
import type { Lead, LeadStatus } from '../../api'

export const PIPELINE: Array<{ id: LeadStatus; label: string; color: string }> = [
  { id: 'NEW', label: 'Nuevo', color: '#3b82f6' },          // blue
  { id: 'CONTACTED', label: 'Contactado', color: '#8b5cf6' }, // purple
  { id: 'QUALIFIED', label: 'Calificado', color: '#06b6d4' }, // cyan
  { id: 'PROPOSAL', label: 'Propuesta', color: '#f59e0b' },   // amber
  { id: 'NEGOTIATION', label: 'Negociación', color: '#ec4899' }, // pink
  { id: 'WON', label: 'Ganado', color: '#10b981' },       // green
  { id: 'LOST', label: 'Perdido', color: '#6b7280' },      // gray
]

const ACTIVE_STAGES = new Set<LeadStatus>([
  'NEW', 'CONTACTED', 'QUALIFIED', 'PROPOSAL', 'NEGOTIATION',
])

/**
 * Props del componente CrmKanban
 */
interface CrmKanbanProps {
  /** Lista de leads a mostrar */
  leads: Lead[]
  /** Renderizado de cada tarjeta de lead */
  renderLeadCard: (lead: Lead, index: number) => ReactNode
  /** Lead actualmente siendo arrastrado */
  draggedLeadId: string | null
  /** Abre el quick-add precargado con la etapa de la columna (solo etapas activas) */
  onQuickAdd?: (stage: LeadStatus) => void
  /** Determina si un lead está seleccionado (checkbox "seleccionar todos") */
  isLeadSelected?: (leadId: string) => boolean
  /** Alterna la selección de todos los leads visibles de una columna */
  onToggleColumnSelection?: (columnLeadIds: string[]) => void
}

/**
 * Componente principal del Kanban CRM
 *
 * Layout de 7 columnas responsive:
 * - Desktop: 7 columnas visibles horizontalmente
 * - Tablet: 3-4 columnas con scroll horizontal
 * - Mobile: 1 columna con toggle entre etapas
 *
 * Integrado con @dnd-kit para drag & drop nativo
 */
export function CrmKanban({
  leads,
  renderLeadCard,
  draggedLeadId,
  onQuickAdd,
  isLeadSelected,
  onToggleColumnSelection,
}: CrmKanbanProps) {
  // Agrupar leads por etapa para optimizar renderizado
  const leadsByStage = useMemo(() => {
    const grouped = new Map<LeadStatus, Lead[]>()
    for (const stage of PIPELINE) {
      grouped.set(stage.id, leads.filter((lead) => lead.status === stage.id))
    }
    return grouped
  }, [leads])

  return (
    <section className="crm-kanban" aria-label="Pipeline de ventas">
      {PIPELINE.map((stage) => {
        const stageLeads = leadsByStage.get(stage.id) ?? []
        const totalValue = stageLeads.reduce(
          (sum, lead) => sum + Number(lead.estimatedValue ?? 0),
          0
        )
        const isActive = ACTIVE_STAGES.has(stage.id)
        const hasDraggedLead = draggedLeadId
          ? stageLeads.some((lead) => lead.id === draggedLeadId)
          : false

        return (
          <motion.div
            key={stage.id}
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{
              type: 'spring',
              stiffness: 200,
              damping: 20,
              delay: PIPELINE.indexOf(stage) * 0.1,
            }}
          >
            <KanbanColumn
              stage={stage.id}
              label={stage.label}
              leadCount={stageLeads.length}
              totalValue={totalValue}
              isActive={isActive}
              hasDraggedLead={hasDraggedLead}
              onQuickAdd={isActive ? onQuickAdd : undefined}
              columnSelected={
                stageLeads.length > 0 &&
                !!isLeadSelected &&
                stageLeads.every((lead) => isLeadSelected(lead.id))
              }
              onToggleColumnSelection={
                onToggleColumnSelection && stageLeads.length > 0
                  ? () => onToggleColumnSelection(stageLeads.map((lead) => lead.id))
                  : undefined
              }
            >
              {stageLeads.map((lead, index) => renderLeadCard(lead, index))}
            </KanbanColumn>
          </motion.div>
        )
      })}
    </section>
  )
}

/**
 * Columna individual del Kanban
 * Integrada con useDroppable para recibir drops
 */
interface KanbanColumnProps {
  stage: LeadStatus
  label: string
  leadCount: number
  totalValue: number
  isActive: boolean
  hasDraggedLead: boolean
  /** Abre el quick-add para esta etapa (solo columnas activas) */
  onQuickAdd?: (stage: LeadStatus) => void
  /** ¿Todos los leads visibles de la columna están seleccionados? */
  columnSelected?: boolean
  /** Alterna la selección de toda la columna */
  onToggleColumnSelection?: () => void
  children: ReactNode
}

function KanbanColumn({
  stage,
  label,
  leadCount,
  totalValue,
  isActive,
  hasDraggedLead,
  onQuickAdd,
  columnSelected = false,
  onToggleColumnSelection,
  children,
}: KanbanColumnProps) {
  const { setNodeRef, isOver } = useDroppable({
    id: stage,
    disabled: !isActive,
  })

  // Placeholder para drag & drop (se renderiza cuando se arrastra sobre esta columna)
  const showDropIndicator = isActive && (isOver || hasDraggedLead)

  return (
    <section
      ref={setNodeRef}
      className={`kanban-column kanban-${stage.toLowerCase()} ${
        showDropIndicator ? 'kanban-column-drag-over' : ''
      }`}
      data-stage={stage}
      data-active={isActive}
      data-droppable={isActive}
    >
      <header className="kanban-column-header">
        <div className="kanban-column-title">
          {onToggleColumnSelection ? (
            <input
              type="checkbox"
              className="kanban-column-select"
              checked={columnSelected}
              onChange={onToggleColumnSelection}
              aria-label={`Seleccionar todos los leads de ${label}`}
            />
          ) : null}
          <h2>{label}</h2>
          <span className="kanban-column-count">{leadCount}</span>
        </div>
        <div className="kanban-column-actions">
          <small className="kanban-column-total">
            ${totalValue.toLocaleString('es-EC', { minimumFractionDigits: 2 })}
          </small>
          {onQuickAdd ? (
            <button
              type="button"
              className="kanban-quick-add"
              onClick={() => onQuickAdd(stage)}
              aria-label={`Crear lead en ${label}`}
            >
              +
            </button>
          ) : null}
        </div>
      </header>

      <div className="kanban-stack">{children}</div>

      {showDropIndicator && (
        <motion.div
          className="kanban-drop-indicator"
          aria-hidden="true"
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.9 }}
          transition={{
            type: 'spring',
            stiffness: 400,
            damping: 15,
          }}
        >
          Soltar para mover a {label}
        </motion.div>
      )}
    </section>
  )
}
