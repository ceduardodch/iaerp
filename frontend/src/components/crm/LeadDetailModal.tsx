import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'

import {
  apiRequest,
  idempotencyKey,
  type Lead,
  type LeadActivity,
  type LeadActivityCreate,
} from '../../api'
import { ErpButton } from '../erp'
import { ErpModal } from '../erp/ErpModal'

const ACTIVITY_LABELS: Record<LeadActivity['activityType'], string> = {
  CALL: 'Llamada',
  EMAIL: 'Correo',
  WHATSAPP: 'WhatsApp',
  MEETING: 'Reunión',
  NOTE: 'Nota',
  TASK: 'Tarea',
}

/**
 * Modal de detalle de lead (Sprint 2, HU-5): se abre al hacer click en una
 * card SIN navegar — el kanban queda intacto detrás (scroll, filtros y
 * selección se preservan). Muestra el negocio y su contacto, permite editar
 * puntuación/temperatura/valor, y gestiona el timeline de actividades.
 */
export function LeadDetailModal({
  lead,
  token,
  onClose,
  onUpdated,
}: {
  lead: Lead
  token: string
  onClose: () => void
  onUpdated: (lead: Lead) => void
}) {
  const queryClient = useQueryClient()
  const [editError, setEditError] = useState<string | null>(null)

  const activitiesQuery = useQuery({
    queryKey: ['crm-lead-activities', lead.id],
    queryFn: () => apiRequest<LeadActivity[]>(token, `/crm/leads/${lead.id}/activities`),
  })

  const updateLead = useMutation({
    mutationFn: (updates: Partial<{ score: number; hotness: Lead['hotness']; estimatedValue: string | null }>) =>
      apiRequest<Lead>(token, `/crm/leads/${lead.id}`, {
        method: 'PUT',
        headers: { 'Idempotency-Key': idempotencyKey('crm-lead-edit') },
        body: JSON.stringify(updates),
      }),
    onSuccess: (updated) => {
      setEditError(null)
      onUpdated(updated)
      void queryClient.invalidateQueries({ queryKey: ['crm-leads'] })
    },
    onError: (cause) =>
      setEditError(cause instanceof Error ? cause.message : 'No se pudo actualizar'),
  })

  const createActivity = useMutation({
    mutationFn: (data: LeadActivityCreate) =>
      apiRequest<LeadActivity>(token, `/crm/leads/${lead.id}/activities`, {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey('crm-activity') },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['crm-lead-activities', lead.id] })
    },
  })

  function submitActivity(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const data = new FormData(form)
    createActivity.mutate(
      {
        leadId: lead.id,
        activityType: data.get('activityType') as LeadActivityCreate['activityType'],
        subject: String(data.get('subject')),
        description: String(data.get('description') || '') || null,
        outcome: 'PENDING',
      },
      { onSuccess: () => form.reset() }
    )
  }

  return (
    <ErpModal title={lead.title} onClose={onClose} size="lg">
      <div className="lead-detail-modal">
        <section aria-label="Datos del contacto" className="lead-detail-contact">
          <h3>{lead.party.name}</h3>
          <dl>
            <div>
              <dt>Correo</dt>
              <dd>{lead.party.email ?? '—'}</dd>
            </div>
            <div>
              <dt>Teléfono</dt>
              <dd>{lead.party.phone ?? '—'}</dd>
            </div>
            <div>
              <dt>Responsable</dt>
              <dd>{lead.owner?.displayName ?? 'Sin responsable'}</dd>
            </div>
            <div>
              <dt>Producto</dt>
              <dd>{lead.product?.name ?? '—'}</dd>
            </div>
          </dl>
        </section>

        <section aria-label="Calificación" className="lead-detail-edit">
          <div className="field-row">
            <label>
              Puntuación
              <input
                type="number"
                min={0}
                max={100}
                defaultValue={lead.score}
                onBlur={(event) => {
                  const score = Number(event.target.value)
                  if (score !== lead.score) updateLead.mutate({ score })
                }}
              />
            </label>
            <label>
              Temperatura
              <select
                defaultValue={lead.hotness}
                onChange={(event) =>
                  updateLead.mutate({ hotness: event.target.value as Lead['hotness'] })
                }
              >
                <option value="COLD">Frío</option>
                <option value="WARM">Tibio</option>
                <option value="HOT">Caliente</option>
              </select>
            </label>
            <label>
              Valor estimado
              <input
                type="number"
                min={0}
                step="0.01"
                defaultValue={lead.estimatedValue ?? ''}
                onBlur={(event) => {
                  const value = event.target.value || null
                  if (value !== (lead.estimatedValue ?? null)) {
                    updateLead.mutate({ estimatedValue: value })
                  }
                }}
              />
            </label>
          </div>
          {editError ? (
            <p className="form-error" role="alert">
              {editError}
            </p>
          ) : null}
        </section>

        <section aria-label="Actividades" className="lead-detail-activities">
          <h3>Actividades</h3>
          <form className="activity-form" onSubmit={submitActivity}>
            <div className="field-row">
              <label>
                Tipo
                <select name="activityType" defaultValue="NOTE">
                  {Object.entries(ACTIVITY_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Asunto
                <input name="subject" required placeholder="Llamada de seguimiento" />
              </label>
            </div>
            <label>
              Detalle
              <textarea name="description" rows={2} />
            </label>
            <ErpButton variant="secondary" type="submit" disabled={createActivity.isPending}>
              {createActivity.isPending ? 'Guardando…' : 'Registrar actividad'}
            </ErpButton>
            {createActivity.error ? (
              <p className="form-error" role="alert">
                {createActivity.error.message}
              </p>
            ) : null}
          </form>

          {activitiesQuery.isPending ? (
            <p>Cargando actividades…</p>
          ) : (activitiesQuery.data ?? []).length === 0 ? (
            <p className="lead-detail-empty">Sin actividades registradas todavía.</p>
          ) : (
            <ol className="activity-timeline">
              {(activitiesQuery.data ?? []).map((activity) => (
                <li key={activity.id}>
                  <span className="activity-type">{ACTIVITY_LABELS[activity.activityType]}</span>
                  <strong>{activity.subject}</strong>
                  {activity.description ? <p>{activity.description}</p> : null}
                  <time dateTime={activity.createdAt}>
                    {new Date(activity.createdAt).toLocaleString('es-EC')}
                  </time>
                </li>
              ))}
            </ol>
          )}
        </section>
      </div>
    </ErpModal>
  )
}
