import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'

import { apiRequest, idempotencyKey, type Lead, type LeadActivity, type LeadActivityCreate } from '../../api'
import { ErpButton, ErpEmptyState, ErpFormPanel, ErpStatusBadge, ErpToolbar } from '../erp'

const ACTIVITY_TYPE_LABELS: Record<LeadActivity['activityType'], string> = {
  CALL: 'Llamada',
  EMAIL: 'Email',
  MEETING: 'Reunión',
  NOTE: 'Nota',
  TASK: 'Tarea',
}

const OUTCOME_LABELS: Record<LeadActivity['outcome'], string> = {
  POSITIVE: 'Positivo',
  NEUTRAL: 'Neutral',
  NEGATIVE: 'Negativo',
  PENDING: 'Pendiente',
}

const OUTCOME_TONES: Record<LeadActivity['outcome'], 'neutral' | 'success' | 'warning' | 'danger'> = {
  POSITIVE: 'success',
  NEUTRAL: 'neutral',
  NEGATIVE: 'danger',
  PENDING: 'warning',
}

interface LeadDetailPanelProps {
  lead: Lead | null
  token: string
  onClose: () => void
}

export function LeadDetailPanel({ lead, token, onClose }: LeadDetailPanelProps) {
  const queryClient = useQueryClient()
  const [showActivityForm, setShowActivityForm] = useState(false)

  const { data: activities = [], isLoading: isLoadingActivities } = useQuery({
    queryKey: ['crm-activities', lead?.id],
    queryFn: () => apiRequest<LeadActivity[]>(token, `/crm/leads/${lead?.id}/activities`),
    enabled: !!lead,
  })

  const createActivity = useMutation({
    mutationFn: (data: LeadActivityCreate) =>
      apiRequest<LeadActivity>(token, `/crm/leads/${lead?.id}/activities`, {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey('crm-activity') },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      setShowActivityForm(false)
      return queryClient.invalidateQueries({ queryKey: ['crm-activities', lead?.id] })
    },
  })

  function submitActivity(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!lead) return

    const form = event.currentTarget
    const data = new FormData(form)
    createActivity.mutate({
      leadId: lead.id,
      activityType: data.get('activityType') as LeadActivityCreate['activityType'],
      subject: String(data.get('subject')),
      description: data.get('description') as string | null,
      outcome: (data.get('outcome') as LeadActivityCreate['outcome']) || 'PENDING',
      reminderDate: data.get('reminderDate') as string | null,
      reminderCompleted: false,
    })
  }

  if (!lead) {
    return (
      <aside className="form-panel erp-form-panel">
        <p className="section-number">Detalle</p>
        <h2>Selecciona un lead</h2>
        <p className="erp-page-subtitle">Elige un lead de la lista para ver su detalle y actividades.</p>
        <div className="erp-form-actions">
          <ErpButton variant="secondary" onClick={onClose}>
            Cerrar
          </ErpButton>
        </div>
      </aside>
    )
  }

  return (
    <aside className="form-panel erp-form-panel crm-lead-detail">
      <p className="section-number">Detalle</p>
      <h2>Lead {lead.partyId.slice(0, 8)}...</h2>

      <div className="crm-lead-info">
        <span className="tag">Estado: {lead.status}</span>
        <span className="tag">Puntuación: {lead.score}/100</span>
        <span className="tag">Temperatura: {lead.hotness}</span>
        {lead.estimatedValue ? (
          <span className="tag">Valor: ${lead.estimatedValue}</span>
        ) : null}
        {lead.expectedCloseDate ? (
          <span className="tag">Cierre: {lead.expectedCloseDate}</span>
        ) : null}
      </div>

      <ErpToolbar>
        <div className="erp-toolbar-group">
          <h3>Actividades</h3>
          <ErpButton
            variant="primary"
            onClick={() => setShowActivityForm(!showActivityForm)}
          >
            {showActivityForm ? 'Cancelar' : 'Nueva actividad'}
          </ErpButton>
        </div>
      </ErpToolbar>

      {showActivityForm ? (
        <ErpFormPanel
          eyebrow="Nueva actividad"
          title="Registrar actividad"
          submitLabel="Registrar"
          pendingLabel="Registrando..."
          pending={createActivity.isPending}
          error={createActivity.error?.message}
          onSubmit={submitActivity}
          onCancel={() => setShowActivityForm(false)}
        >
          <label>
            Tipo de actividad
            <select name="activityType" required>
              <option value="CALL">Llamada</option>
              <option value="EMAIL">Email</option>
              <option value="MEETING">Reunión</option>
              <option value="NOTE">Nota</option>
              <option value="TASK">Tarea</option>
            </select>
          </label>
          <label>
            Asunto
            <input name="subject" required />
          </label>
          <label>
            Descripción
            <textarea name="description" rows={3} />
          </label>
          <label>
            Resultado
            <select name="outcome">
              <option value="PENDING">Pendiente</option>
              <option value="POSITIVE">Positivo</option>
              <option value="NEUTRAL">Neutral</option>
              <option value="NEGATIVE">Negativo</option>
            </select>
          </label>
          <label>
            Recordatorio (opcional)
            <input
              name="reminderDate"
              type="datetime-local"
            />
          </label>
        </ErpFormPanel>
      ) : null}

      <section className="crm-activities">
        {isLoadingActivities ? (
          <p>Cargando actividades...</p>
        ) : activities.length === 0 ? (
          <ErpEmptyState
            title="No hay actividades"
            description="Este lead no tiene actividades registradas aún."
          />
        ) : (
          <div className="timeline">
            {activities.map((activity) => (
              <div key={activity.id} className="timeline-item">
                <small className="timeline-date">
                  {new Date(activity.createdAt).toLocaleString('es-EC')}
                </small>
                <div className="timeline-content">
                  <span className="tag">{ACTIVITY_TYPE_LABELS[activity.activityType]}</span>
                  <strong>{activity.subject}</strong>
                  <ErpStatusBadge tone={OUTCOME_TONES[activity.outcome]}>
                    {OUTCOME_LABELS[activity.outcome]}
                  </ErpStatusBadge>
                  {activity.description ? (
                    <p className="timeline-description">{activity.description}</p>
                  ) : null}
                  {activity.reminderDate && !activity.reminderCompleted ? (
                    <span className="reminder-chip">
                      ⏰ Recordatorio: {new Date(activity.reminderDate).toLocaleString('es-EC')}
                    </span>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <div className="erp-form-actions">
        <ErpButton variant="secondary" onClick={onClose}>
          Cerrar
        </ErpButton>
      </div>
    </aside>
  )
}
