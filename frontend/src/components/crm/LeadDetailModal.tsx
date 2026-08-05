import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'

import {
  apiRequest,
  idempotencyKey,
  type Lead,
  type LeadActivity,
  type LeadActivityCreate,
  type LeadMessageCreate,
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

  /**
   * Envío real por Gmail. El endpoint `/messages` despacha el correo y deja la
   * actividad; `/activities` solo deja la actividad. El modal antes usaba el
   * segundo, así que desde el kanban no había forma de escribirle al lead.
   */
  const sendMessage = useMutation({
    mutationFn: (data: LeadMessageCreate) =>
      apiRequest<LeadActivity>(token, `/crm/leads/${lead.id}/messages`, {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey('crm-message') },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['crm-lead-activities', lead.id] })
      void queryClient.invalidateQueries({ queryKey: ['crm-activities', lead.id] })
    },
  })

  const completeReminder = useMutation({
    mutationFn: ({ activityId, completed }: { activityId: string; completed: boolean }) =>
      apiRequest<LeadActivity>(token, `/crm/leads/${lead.id}/activities/${activityId}/reminder`, {
        method: 'PUT',
        headers: { 'Idempotency-Key': idempotencyKey('crm-reminder') },
        body: JSON.stringify({ completed }),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['crm-lead-activities', lead.id] })
    },
  })

  const qualifyLead = useMutation({
    mutationFn: (data: object) => apiRequest<Lead>(token, `/crm/leads/${lead.id}/qualification`, {
      method: 'PUT',
      headers: { 'Idempotency-Key': idempotencyKey('crm-lead-qualification') },
      body: JSON.stringify(data),
    }),
    onSuccess: (updated) => {
      onUpdated(updated)
      void queryClient.invalidateQueries({ queryKey: ['crm-leads'] })
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
        reminderDate: String(data.get('reminderDate') || '') || null,
      },
      { onSuccess: () => form.reset() }
    )
  }

  function submitMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const data = new FormData(form)
    const followUpDays = Number(data.get('followUpDays') || 0)
    sendMessage.mutate(
      {
        channel: 'EMAIL',
        subject: String(data.get('subject')),
        message: String(data.get('message')),
        followUpDays: followUpDays > 0 ? followUpDays : null,
      },
      { onSuccess: () => form.reset() }
    )
  }

  function submitQualification(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    const booleanValue = (name: string) => {
      const value = String(data.get(name) || '')
      return value === '' ? null : value === 'true'
    }
    qualifyLead.mutate({
      status: data.get('status'),
      companyName: data.get('companyName') || null,
      jobTitle: data.get('jobTitle') || null,
      usesAws: booleanValue('usesAws'),
      decisionAuthority: booleanValue('decisionAuthority'),
      reason: data.get('reason'),
    })
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

        <section aria-label="Enviar correo" className="lead-detail-message">
          <h3>Enviar correo</h3>
          {lead.party.email ? (
            <form className="message-form" onSubmit={submitMessage}>
              <label>
                Asunto
                <input name="subject" required maxLength={200} placeholder="pregunta rápida sobre su AWS" />
              </label>
              <label>
                Mensaje
                <textarea name="message" rows={8} required maxLength={5000} />
              </label>
              <div className="field-row">
                <label>
                  Seguimiento
                  <select name="followUpDays" defaultValue="4">
                    <option value="0">Sin recordatorio</option>
                    <option value="2">En 2 días</option>
                    <option value="4">En 4 días</option>
                    <option value="7">En 1 semana</option>
                    <option value="15">En 15 días</option>
                  </select>
                </label>
                <ErpButton variant="primary" type="submit" disabled={sendMessage.isPending}>
                  {sendMessage.isPending ? 'Enviando…' : `Enviar a ${lead.party.email}`}
                </ErpButton>
              </div>
              <p className="fine-print">
                Sale por Gmail desde la cuenta conectada y queda en el historial.
              </p>
              {sendMessage.error ? (
                <p className="form-error" role="alert">
                  {sendMessage.error.message}
                </p>
              ) : null}
              {sendMessage.isSuccess ? (
                <p className="form-success" role="status">
                  Correo enviado.
                </p>
              ) : null}
            </form>
          ) : (
            <p className="lead-detail-empty">
              Este contacto no tiene correo registrado. Agrégalo en el contacto para poder escribirle.
            </p>
          )}
        </section>

        {lead.campaignId || lead.campaignName || lead.utmCampaign ? (
          <section aria-label="Origen de captación" className="lead-detail-contact">
            <h3>Origen de captación</h3>
            <dl>
              <div><dt>Canal</dt><dd>{lead.source ?? '—'}</dd></div>
              <div><dt>Campaña</dt><dd>{lead.campaignName ?? lead.utmCampaign ?? '—'}</dd></div>
              <div><dt>Anuncio</dt><dd>{lead.adId ?? '—'}</dd></div>
              <div><dt>Consentimiento</dt><dd>{lead.consentCapturedAt ? new Date(lead.consentCapturedAt).toLocaleString('es-EC') : '—'}</dd></div>
            </dl>
          </section>
        ) : null}

        {['META_LEAD_AD', 'LINKEDIN_LEAD_GEN', 'TIKTOK_LEAD_GEN'].includes(lead.source ?? '') ? (
          <section aria-label="Calificación comercial" className="lead-detail-qualification">
            <h3>Calificación comercial</h3>
            <p className={`qualification-state qualification-${lead.qualificationStatus.toLowerCase()}`}>
              {lead.qualificationStatus === 'QUALIFIED' ? 'Calificado' : lead.qualificationStatus === 'DISQUALIFIED' ? 'Descartado' : 'Sin revisar'}
            </p>
            <form onSubmit={submitQualification}>
              <div className="field-row">
                <label>Decisión<select name="status" defaultValue={lead.qualificationStatus === 'DISQUALIFIED' ? 'DISQUALIFIED' : 'QUALIFIED'}><option value="QUALIFIED">Calificar</option><option value="DISQUALIFIED">Descartar</option></select></label>
                <label>Empresa<input name="companyName" defaultValue={lead.companyName ?? ''} /></label>
                <label>Cargo<input name="jobTitle" defaultValue={lead.jobTitle ?? ''} /></label>
              </div>
              <div className="field-row">
                <label>¿Usa AWS?<select name="usesAws" defaultValue={lead.usesAws === null || lead.usesAws === undefined ? '' : String(lead.usesAws)}><option value="">Sin confirmar</option><option value="true">Sí</option><option value="false">No</option></select></label>
                <label>¿Decide o llega al decisor?<select name="decisionAuthority" defaultValue={lead.decisionAuthority === null || lead.decisionAuthority === undefined ? '' : String(lead.decisionAuthority)}><option value="">Sin confirmar</option><option value="true">Sí</option><option value="false">No</option></select></label>
              </div>
              <label>Motivo<textarea name="reason" rows={2} defaultValue={lead.qualificationReason ?? ''} required /></label>
              <p className="fine-print">Para calificar se exige empresa, uso confirmado de AWS y acceso a la decisión.</p>
              {qualifyLead.error ? <p className="form-error" role="alert">{qualifyLead.error.message}</p> : null}
              <ErpButton variant="primary" type="submit" disabled={qualifyLead.isPending}>{qualifyLead.isPending ? 'Guardando…' : 'Guardar calificación'}</ErpButton>
            </form>
          </section>
        ) : null}

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
            <label>
              Recordatorio
              <input name="reminderDate" type="datetime-local" />
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
                  {activity.reminderDate ? (
                    <p
                      className={
                        activity.reminderCompleted
                          ? 'activity-reminder done'
                          : new Date(activity.reminderDate) <= new Date()
                            ? 'activity-reminder overdue'
                            : 'activity-reminder'
                      }
                    >
                      {activity.reminderCompleted
                        ? 'Seguimiento hecho'
                        : `Seguimiento: ${new Date(activity.reminderDate).toLocaleDateString('es-EC')}`}
                      {activity.reminderCompleted ? null : (
                        <button
                          type="button"
                          disabled={completeReminder.isPending}
                          onClick={() =>
                            completeReminder.mutate({ activityId: activity.id, completed: true })
                          }
                        >
                          Marcar hecho
                        </button>
                      )}
                    </p>
                  ) : null}
                </li>
              ))}
            </ol>
          )}
        </section>
      </div>
    </ErpModal>
  )
}
