import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { motion } from 'framer-motion'
import type { Lead } from '../../api'

/**
 * Props del componente LeadCard
 */
interface LeadCardProps {
  /** Lead a mostrar */
  lead: Lead
  /** Índice para animación escalonada */
  index: number
  /** Callback al hacer click en la card */
  onClick: () => void
  /** Indica si el lead está siendo arrastrado */
  isDragging?: boolean
  /** Selección múltiple (Sprint 2): ¿esta card está seleccionada? */
  selected?: boolean
  /** Alternar selección; `shiftKey` activa el rango contiguo en la columna */
  onToggleSelect?: (shiftKey: boolean) => void
}

/**
 * Gradient colors según hotness del lead
 */
const HOTNESS_COLORS = {
  COLD: {
    gradient: 'linear-gradient(135deg, #3b82f6 0%, #2563eb 100%)',
    bg: 'blue',
    text: 'Frío',
  },
  WARM: {
    gradient: 'linear-gradient(135deg, #f59e0b 0%, #d97706 100%)',
    bg: 'orange',
    text: 'Tibio',
  },
  HOT: {
    gradient: 'linear-gradient(135deg, #ef4444 0%, #dc2626 100%)',
    bg: 'red',
    text: 'Caliente',
  },
}

/**
 * Colores de badge según etapa del pipeline
 */
const STAGE_COLORS = {
  NEW: '#3b82f6',
  CONTACTED: '#8b5cf6',
  QUALIFIED: '#06b6d4',
  PROPOSAL: '#f59e0b',
  NEGOTIATION: '#ec4899',
  WON: '#10b981',
  LOST: '#6b7280',
}

/**
 * Tarjeta individual de lead para el Kanban
 *
 * Características:
 * - Draggable con @dnd-kit
 * - Avatar del owner con iniciales
 * - Badges con gradient según hotness
 * - Indicador visual de etapa con color
 * - Animaciones escalonadas por índice
 * - Responsive design
 */
export function LeadCard({
  lead,
  index,
  onClick,
  isDragging,
  selected = false,
  onToggleSelect,
}: LeadCardProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging: isSortableDragging,
  } = useSortable({ id: lead.id })

  const hotnessInfo = HOTNESS_COLORS[lead.hotness]
  const stageColor = STAGE_COLORS[lead.status]
  const ownerInitials = lead.owner
    ? lead.owner.displayName
        .split(' ')
        .map((name) => name[0])
        .join('')
        .toUpperCase()
        .slice(0, 2)
    : 'NA'

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    '--card-index': index,
    '--stage-color': stageColor,
  } as React.CSSProperties

  const isActive = ['NEW', 'CONTACTED', 'QUALIFIED', 'PROPOSAL', 'NEGOTIATION'].includes(
    lead.status
  )

  return (
    <motion.article
      ref={setNodeRef}
      className={`kanban-card ${isDragging || isSortableDragging ? 'is-dragging' : ''} ${
        selected ? 'is-selected' : ''
      }`}
      style={style}
      data-lead-id={lead.id}
      data-active={isActive}
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.95 }}
      transition={{
        type: 'spring',
        stiffness: 300,
        damping: 20,
        delay: index * 0.05,
      }}
      whileHover={{ scale: 1.02, boxShadow: '0 8px 22px rgba(23, 52, 45, 0.15)' }}
      whileTap={{ scale: 0.98 }}
    >
      {/* Checkbox de selección múltiple: fuera del botón draggable para no
          disparar drag ni abrir el detalle al marcarlo. */}
      {onToggleSelect ? (
        <label className="lead-card-select">
          <input
            type="checkbox"
            checked={selected}
            aria-label={`Seleccionar ${lead.title}`}
            onClick={(event) => event.stopPropagation()}
            onChange={(event) =>
              onToggleSelect((event.nativeEvent as MouseEvent).shiftKey ?? false)
            }
          />
        </label>
      ) : null}
      <button
        type="button"
        onClick={onClick}
        disabled={!isActive}
        className="lead-card-button"
        {...(isActive ? listeners : undefined)}
        {...attributes}
        aria-label={`Ver detalles de ${lead.title}`}
      >
        <div className="lead-card-header">
          {/* Badge de hotness con gradient */}
          <div
            className="lead-card-badge"
            style={{
              background: hotnessInfo.gradient,
            }}
            aria-label={`Temperatura: ${hotnessInfo.text}`}
          >
            <span>{hotnessInfo.text}</span>
          </div>

          {/* Score numérico */}
          <div className="lead-card-score" aria-label={`Puntuación: ${lead.score}`}>
            {lead.score}
          </div>
        </div>

        {/* Contenido principal */}
        <div className="lead-card-content">
          {/* Kicker: producto o source */}
          <span className="kanban-card-kicker">
            {lead.product?.name ?? lead.source ?? 'Oportunidad'}
          </span>

          {/* Título de la oportunidad */}
          <strong>{lead.title}</strong>

          {/* Nombre del contacto/party */}
          <span>{lead.party.name}</span>

          {/* Footer: avatar + valor estimado */}
          <footer>
            <div className="lead-card-avatar">
              <div
                className="avatar-circle"
                style={{
                  background: hotnessInfo.gradient,
                }}
                aria-label={`Responsable: ${lead.owner?.displayName ?? 'Sin responsable'}`}
              >
                {ownerInitials}
              </div>
              <small>{lead.owner?.displayName ?? 'Sin responsable'}</small>
            </div>

            <b>
              ${Number(lead.estimatedValue ?? 0).toLocaleString('es-EC', {
                minimumFractionDigits: 2,
              })}
            </b>
          </footer>
        </div>
      </button>
    </motion.article>
  )
}

/**
 * Versión simplificada para listas sin drag & drop
 */
export function LeadCardCompact({
  lead,
  onClick,
}: {
  lead: Lead
  onClick: () => void
}) {
  const hotnessInfo = HOTNESS_COLORS[lead.hotness]

  return (
    <article className="lead-card-compact">
      <button type="button" onClick={onClick} className="lead-card-compact-button">
        <div
          className="lead-card-compact-badge"
          style={{
            background: hotnessInfo.gradient,
          }}
        >
          <span>{hotnessInfo.text}</span>
        </div>

        <div className="lead-card-compact-content">
          <strong>{lead.title}</strong>
          <span>{lead.party.name}</span>
        </div>

        <b>
          ${Number(lead.estimatedValue ?? 0).toLocaleString('es-EC', {
            minimumFractionDigits: 2,
          })}
        </b>
      </button>
    </article>
  )
}
