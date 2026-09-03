import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  apiRequest,
  idempotencyKey,
  type ChannelAccountRead,
  type ChannelAccountUpdate,
  type ChannelTestResult,
  type NotificationAudienceKind,
  type NotificationBillingFrequency,
  type NotificationBillingScheduleInput,
  type NotificationBillingScheduleRead,
  type NotificationDeliveryStatus,
  type NotificationEventDetailRead,
  type NotificationEventRead,
  type NotificationEventStatus,
  type NotificationRuleRead,
  type NotificationRuleUpdate,
  type NotificationScheduleKind,
  type NotificationTemplatePreviewResult,
  type NotificationTemplateRead,
  type NotificationTemplateUpdate,
  type Party,
} from '../../api'
import {
  ErpActionCell,
  ErpButton,
  ErpDataTable,
  ErpEmptyState,
  ErpFormPanel,
  ErpPageHeader,
  ErpPanel,
  ErpStatusBadge,
  ErpTabs,
  ErpToolbar,
} from '../erp'
import { ErpCombobox } from '../erp/ErpCombobox'
import './NotificationsPage.css'

const amountFormatter = new Intl.NumberFormat('es-EC', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

function formatAmount(value: string | number): string {
  const amount = Number(value)
  return Number.isFinite(amount) ? amountFormatter.format(amount) : '0,00'
}

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString('es-EC', {
    timeZone: 'America/Guayaquil',
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

function parseCsv(value: string): string[] {
  return value.split(',').map((item) => item.trim()).filter(Boolean)
}

/**
 * Mismos marcadores que `PLACEHOLDERS` en
 * `backend/app/services/notifications/catalog.py`. Catálogo fijo de solo
 * lectura para la UI, no viene de la API.
 */
const TEMPLATE_PLACEHOLDERS = [
  '{{empresa}}', '{{periodo}}', '{{fecha_limite}}', '{{dias_restantes}}', '{{estado}}', '{{pendientes}}',
  '{{aviso_feriados}}', '{{cliente}}', '{{dia}}', '{{monto_referencia}}', '{{nota}}', '{{aporte_personal}}',
  '{{empleados}}', '{{aviso_patronal}}', '{{ingresos}}', '{{egresos}}', '{{resultado}}', '{{documentos}}',
  '{{iva_generado}}', '{{credito_tributario}}', '{{saldo}}', '{{aviso_preliminar}}',
]

const SCHEDULE_KIND_OPTIONS: Array<{ value: NotificationScheduleKind; label: string }> = [
  { value: 'DAY_OF_MONTH', label: 'Días fijos del mes' },
  { value: 'OFFSET_TO_DUE', label: 'Desplazamiento respecto a un vencimiento' },
  { value: 'LAST_BUSINESS_DAY', label: 'Último día hábil del mes' },
  { value: 'WEEKDAY', label: 'Día de la semana' },
]

// PARTY existe en el esquema pero `services/notifications/delivery.py` todavía
// no resuelve destinatarios para ese modo: ofrecerlo confundiría más de lo que ayuda.
const AUDIENCE_KIND_OPTIONS: Array<{ value: NotificationAudienceKind; label: string }> = [
  { value: 'TENANT_USERS', label: 'Todo el equipo' },
  { value: 'EXPLICIT_EMAILS', label: 'Correos específicos' },
]

function summarizeSchedule(rule: NotificationRuleRead): string {
  switch (rule.scheduleKind) {
    case 'DAY_OF_MONTH':
      return rule.daysOfMonth ? `Días ${rule.daysOfMonth} del mes` : 'Días del mes (sin configurar)'
    case 'OFFSET_TO_DUE':
      return rule.offsetsDays ? `${rule.offsetsDays} días respecto al vencimiento` : 'Sin desplazamientos configurados'
    case 'LAST_BUSINESS_DAY':
      return 'Último día hábil del mes'
    case 'WEEKDAY':
      return rule.daysOfMonth ? `Día(s) ${rule.daysOfMonth} de la semana` : 'Día de la semana (sin configurar)'
    default:
      return '—'
  }
}

/** Reemplazo completo con todo igual salvo `enabled`: evita abrir el formulario para un cambio rápido. */
function toggledRulePayload(rule: NotificationRuleRead): NotificationRuleUpdate {
  return {
    enabled: !rule.enabled,
    scheduleKind: rule.scheduleKind,
    daysOfMonth: rule.daysOfMonth ?? null,
    offsetsDays: rule.offsetsDays ?? null,
    sendHour: rule.sendHour,
    channels: rule.channels,
    audienceKind: rule.audienceKind,
    audienceRoles: rule.audienceRoles,
    audienceEmails: rule.audienceEmails,
    requireAck: rule.requireAck,
  }
}

function RuleEnabledToggle({ token, rule, onChanged }: {
  token: string
  rule: NotificationRuleRead
  onChanged: () => void
}) {
  const toggle = useMutation({
    mutationFn: () => apiRequest<NotificationRuleRead>(token, `/notifications/rules/${rule.id}`, {
      method: 'PUT',
      headers: { 'Idempotency-Key': idempotencyKey('web-notifications-rule-update') },
      body: JSON.stringify(toggledRulePayload(rule)),
    }),
    onSuccess: onChanged,
  })

  return (
    <div className="notif-switch">
      <label>
        <input
          type="checkbox"
          role="switch"
          checked={rule.enabled}
          disabled={toggle.isPending}
          onChange={() => toggle.mutate()}
          aria-label={`${rule.enabled ? 'Apagar' : 'Encender'} ${rule.name}`}
        />
        {rule.enabled ? 'Encendida' : 'Apagada'}
      </label>
      {toggle.error ? <small className="form-error" role="alert">{toggle.error.message}</small> : null}
    </div>
  )
}

function RuleForm({ token, rule, onCancel, onSaved }: {
  token: string
  rule: NotificationRuleRead
  onCancel: () => void
  onSaved: () => void
}) {
  const [enabled, setEnabled] = useState(rule.enabled)
  const [scheduleKind, setScheduleKind] = useState<NotificationScheduleKind>(rule.scheduleKind)
  // Ambos campos se conservan aunque solo uno se muestre: CLIENTE_FACTURAR usa
  // schedule_kind=DAY_OF_MONTH pero guarda su recordatorio en offsets_days, así
  // que ocultar un campo no debe mandarlo en null y borrar lo que ya tenía.
  const [daysOfMonth, setDaysOfMonth] = useState(rule.daysOfMonth ?? '')
  const [offsetsDays, setOffsetsDays] = useState(rule.offsetsDays ?? '')
  const [sendHour, setSendHour] = useState(rule.sendHour)
  const [audienceKind, setAudienceKind] = useState<NotificationAudienceKind>(
    rule.audienceKind === 'PARTY' ? 'TENANT_USERS' : rule.audienceKind,
  )
  const [audienceRoles, setAudienceRoles] = useState(rule.audienceRoles.join(', '))
  const [audienceEmails, setAudienceEmails] = useState<string[]>(
    rule.audienceEmails.length ? rule.audienceEmails : [''],
  )
  const [requireAck, setRequireAck] = useState(rule.requireAck)

  const save = useMutation({
    mutationFn: () => apiRequest<NotificationRuleRead>(token, `/notifications/rules/${rule.id}`, {
      method: 'PUT',
      headers: { 'Idempotency-Key': idempotencyKey('web-notifications-rule-update') },
      body: JSON.stringify({
        enabled,
        scheduleKind,
        daysOfMonth: daysOfMonth.trim() || null,
        offsetsDays: offsetsDays.trim() || null,
        sendHour: Number(sendHour),
        channels: rule.channels || 'EMAIL',
        audienceKind,
        audienceRoles: audienceKind === 'TENANT_USERS' ? parseCsv(audienceRoles) : [],
        audienceEmails: audienceKind === 'EXPLICIT_EMAILS'
          ? audienceEmails.map((email) => email.trim()).filter(Boolean)
          : [],
        requireAck,
      } satisfies NotificationRuleUpdate),
    }),
    onSuccess: onSaved,
  })

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    save.mutate()
  }

  return (
    <ErpFormPanel
      eyebrow="Avisos"
      title={`Configurar «${rule.name}»`}
      pending={save.isPending}
      error={save.error?.message}
      onSubmit={submit}
      onCancel={onCancel}
    >
      <div className="notif-form-grid">
        <label>
          Cuándo enviar
          <select value={scheduleKind} onChange={(event) => setScheduleKind(event.target.value as NotificationScheduleKind)}>
            {SCHEDULE_KIND_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </label>
        {scheduleKind === 'DAY_OF_MONTH' || scheduleKind === 'WEEKDAY' ? (
          <label>
            {scheduleKind === 'WEEKDAY' ? 'Días de la semana (separados por coma)' : 'Días del mes (separados por coma, ej. 1,10)'}
            <input value={daysOfMonth} onChange={(event) => setDaysOfMonth(event.target.value)} placeholder="1,10" />
          </label>
        ) : null}
        {scheduleKind === 'OFFSET_TO_DUE' ? (
          <label>
            Desplazamiento en días (separados por coma, admite signo, ej. -7,-3,-1)
            <input value={offsetsDays} onChange={(event) => setOffsetsDays(event.target.value)} placeholder="-7,-3,-1" />
          </label>
        ) : null}
        <label>
          Hora de envío (0-23)
          <input
            type="number"
            min={0}
            max={23}
            required
            value={sendHour}
            onChange={(event) => setSendHour(Number(event.target.value))}
          />
        </label>
        <label>
          Destinatarios
          <select value={audienceKind} onChange={(event) => setAudienceKind(event.target.value as NotificationAudienceKind)}>
            {AUDIENCE_KIND_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </label>
        {audienceKind === 'TENANT_USERS' ? (
          <label>
            Roles (separados por coma, ej. owner, admin)
            <input value={audienceRoles} onChange={(event) => setAudienceRoles(event.target.value)} placeholder="owner, admin" />
          </label>
        ) : null}
      </div>
      {scheduleKind === 'LAST_BUSINESS_DAY' ? (
        <p className="fine-print">Se calcula solo: el último día hábil del mes.</p>
      ) : null}
      {audienceKind === 'EXPLICIT_EMAILS' ? (
        <fieldset className="notif-email-list">
          <legend>Correos destinatarios</legend>
          {audienceEmails.map((email, index) => (
            <div className="notif-email-row" key={index}>
              <input
                type="email"
                required
                value={email}
                aria-label={`Correo ${index + 1}`}
                onChange={(event) => setAudienceEmails((current) => (
                  current.map((value, position) => (position === index ? event.target.value : value))
                ))}
              />
              <ErpButton
                variant="ghost"
                onClick={() => setAudienceEmails((current) => current.filter((_, position) => position !== index))}
                disabled={audienceEmails.length === 1}
              >
                Quitar
              </ErpButton>
            </div>
          ))}
          <ErpButton variant="ghost" onClick={() => setAudienceEmails((current) => [...current, ''])}>
            Añadir correo
          </ErpButton>
        </fieldset>
      ) : null}
      <fieldset className="notif-checks">
        <legend>Comportamiento</legend>
        <label>
          <input type="checkbox" checked={requireAck} onChange={(event) => setRequireAck(event.target.checked)} />
          Requiere acuse humano
        </label>
        <p className="fine-print">Si se marca, un acuse humano silencia los recordatorios restantes del mismo asunto.</p>
        <label>
          <input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />
          Regla encendida
        </label>
        {enabled && !rule.enabled ? (
          <p className="form-warning">A partir de ahora este aviso puede enviarse de verdad.</p>
        ) : null}
      </fieldset>
    </ErpFormPanel>
  )
}

function RulesTab({ token, rules, isPending, error }: {
  token: string
  rules: NotificationRuleRead[]
  isPending: boolean
  error?: string
}) {
  const queryClient = useQueryClient()
  const [configuringRule, setConfiguringRule] = useState<NotificationRuleRead | null>(null)

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ['notification-rules'] })
  }

  if (configuringRule) {
    return (
      <RuleForm
        token={token}
        rule={configuringRule}
        onCancel={() => setConfiguringRule(null)}
        onSaved={() => { setConfiguringRule(null); refresh() }}
      />
    )
  }

  return (
    <ErpPanel title="Reglas de avisos" count={rules.length}>
      {isPending ? <p aria-busy="true">Cargando reglas…</p> : null}
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      <ErpDataTable
        ariaLabel="Reglas de avisos internos"
        rows={rules}
        rowKey={(rule) => rule.id}
        emptyState={<ErpEmptyState title="Sin reglas" description="Las reglas del catálogo aparecen aquí automáticamente." />}
        columns={[
          { header: 'Aviso', cell: (rule) => rule.name },
          { header: 'Estado', cell: (rule) => <RuleEnabledToggle token={token} rule={rule} onChanged={refresh} /> },
          { header: 'Envía', cell: (rule) => summarizeSchedule(rule) },
          { header: 'Hora', cell: (rule) => `${String(rule.sendHour).padStart(2, '0')}:00` },
          {
            header: 'Acciones',
            cell: (rule) => (
              <ErpActionCell>
                <ErpButton variant="ghost" onClick={() => setConfiguringRule(rule)}>Configurar</ErpButton>
              </ErpActionCell>
            ),
          },
        ]}
      />
    </ErpPanel>
  )
}

function TemplatesTab({ token, rules }: { token: string; rules: NotificationRuleRead[] }) {
  const queryClient = useQueryClient()
  const [ruleType, setRuleType] = useState('')
  const activeRuleType = ruleType || rules[0]?.ruleType || ''
  const templateQuery = useQuery({
    queryKey: ['notification-templates', activeRuleType],
    queryFn: () => apiRequest<NotificationTemplateRead>(token, `/notifications/templates/${activeRuleType}`),
    enabled: Boolean(activeRuleType),
  })
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [preview, setPreview] = useState<NotificationTemplatePreviewResult | null>(null)
  const bodyRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (templateQuery.data) {
      setSubject(templateQuery.data.subject)
      setBody(templateQuery.data.body)
      setPreview(null)
    }
  }, [templateQuery.data])

  const save = useMutation({
    mutationFn: () => apiRequest<NotificationTemplateRead>(token, `/notifications/templates/${activeRuleType}`, {
      method: 'PUT',
      headers: { 'Idempotency-Key': idempotencyKey('web-notifications-template-update') },
      body: JSON.stringify({ subject, body } satisfies NotificationTemplateUpdate),
    }),
    onSuccess: (template) => queryClient.setQueryData(['notification-templates', activeRuleType], template),
  })

  const restore = useMutation({
    mutationFn: () => apiRequest<NotificationTemplateRead>(token, `/notifications/templates/${activeRuleType}`, {
      method: 'DELETE',
    }),
    onSuccess: (template) => queryClient.setQueryData(['notification-templates', activeRuleType], template),
  })

  const previewMutation = useMutation({
    mutationFn: () => apiRequest<NotificationTemplatePreviewResult>(
      token,
      `/notifications/templates/${activeRuleType}/preview`,
      { method: 'POST', body: JSON.stringify({ subject, body } satisfies NotificationTemplateUpdate) },
    ),
    onSuccess: setPreview,
  })

  function insertPlaceholder(placeholder: string) {
    const element = bodyRef.current
    if (!element) {
      setBody((current) => `${current}${placeholder}`)
      return
    }
    const start = element.selectionStart ?? element.value.length
    const end = element.selectionEnd ?? element.value.length
    const next = `${body.slice(0, start)}${placeholder}${body.slice(end)}`
    setBody(next)
    requestAnimationFrame(() => {
      element.focus()
      element.selectionStart = start + placeholder.length
      element.selectionEnd = start + placeholder.length
    })
  }

  const template = templateQuery.data

  return (
    <ErpPanel
      title="Plantilla del aviso"
      actions={template ? (
        <ErpStatusBadge tone={template.isCustom ? 'success' : 'neutral'}>
          {template.isCustom ? 'Personalizada' : 'Predeterminada'}
        </ErpStatusBadge>
      ) : undefined}
    >
      <label>
        Tipo de aviso
        <select value={activeRuleType} onChange={(event) => setRuleType(event.target.value)} disabled={!rules.length}>
          {rules.map((rule) => <option key={rule.ruleType} value={rule.ruleType}>{rule.name}</option>)}
        </select>
      </label>
      {!rules.length ? <p aria-busy="true">Cargando catálogo de avisos…</p> : null}
      {templateQuery.isPending ? <p aria-busy="true">Cargando plantilla…</p> : null}
      {templateQuery.error ? <p className="form-error" role="alert">{templateQuery.error.message}</p> : null}
      {template ? (
        <>
          <label>
            Asunto
            <input value={subject} maxLength={300} required onChange={(event) => setSubject(event.target.value)} />
          </label>
          <label>
            Cuerpo
            <textarea
              ref={bodyRef}
              value={body}
              maxLength={5000}
              required
              rows={10}
              onChange={(event) => setBody(event.target.value)}
            />
          </label>
          <div className="notif-placeholders">
            <p className="fine-print">Marcadores disponibles (clic para insertar en el cuerpo):</p>
            <div className="notif-placeholder-list">
              {TEMPLATE_PLACEHOLDERS.map((placeholder) => (
                <button
                  key={placeholder}
                  type="button"
                  className="notif-placeholder-chip"
                  onClick={() => insertPlaceholder(placeholder)}
                >
                  {placeholder}
                </button>
              ))}
            </div>
          </div>
          {save.error ? <p className="form-error" role="alert">{save.error.message}</p> : null}
          {previewMutation.error ? <p className="form-error" role="alert">{previewMutation.error.message}</p> : null}
          {restore.error ? <p className="form-error" role="alert">{restore.error.message}</p> : null}
          <div className="erp-form-actions">
            {template.isCustom ? (
              <ErpButton variant="ghost" disabled={restore.isPending} onClick={() => restore.mutate()}>
                {restore.isPending ? 'Restaurando…' : 'Restaurar plantilla original'}
              </ErpButton>
            ) : null}
            <ErpButton variant="secondary" disabled={previewMutation.isPending} onClick={() => previewMutation.mutate()}>
              {previewMutation.isPending ? 'Generando…' : 'Vista previa'}
            </ErpButton>
            <ErpButton variant="primary" disabled={save.isPending} onClick={() => save.mutate()}>
              {save.isPending ? 'Guardando…' : 'Guardar'}
            </ErpButton>
          </div>
          {preview ? (
            <div className="notif-preview-box">
              <p className="section-number">Vista previa</p>
              <strong>{preview.subject}</strong>
              <pre>{preview.bodyText}</pre>
            </div>
          ) : null}
        </>
      ) : null}
    </ErpPanel>
  )
}

const EVENT_STATUS_OPTIONS: Array<{ value: NotificationEventStatus; label: string }> = [
  { value: 'PENDING', label: 'Pendiente' },
  { value: 'PROCESSING', label: 'Procesando' },
  { value: 'SENT', label: 'Enviado' },
  { value: 'STUBBED', label: 'Simulado' },
  { value: 'SKIPPED', label: 'Omitido' },
  { value: 'FAILED', label: 'Fallido' },
  { value: 'CANCELLED', label: 'Cancelado' },
]

function eventStatusLabel(status: NotificationEventStatus | string): string {
  return EVENT_STATUS_OPTIONS.find((option) => option.value === status)?.label ?? status
}

function eventStatusTone(status: NotificationEventStatus | string): 'neutral' | 'success' | 'warning' | 'danger' {
  if (status === 'SENT' || status === 'STUBBED') return 'success'
  if (status === 'PENDING' || status === 'PROCESSING') return 'warning'
  if (status === 'FAILED') return 'danger'
  return 'neutral'
}

const DELIVERY_STATUS_LABELS: Record<NotificationDeliveryStatus, string> = {
  PENDING: 'Pendiente',
  STUBBED: 'Simulado',
  SENT: 'Enviado',
  FAILED: 'Fallido',
  BOUNCED: 'Rebotado',
  COMPLAINED: 'Marcado como spam',
}

function deliveryStatusLabel(status: NotificationDeliveryStatus | string): string {
  return DELIVERY_STATUS_LABELS[status as NotificationDeliveryStatus] ?? status
}

function deliveryStatusTone(status: NotificationDeliveryStatus | string): 'neutral' | 'success' | 'warning' | 'danger' {
  if (status === 'SENT' || status === 'STUBBED') return 'success'
  if (status === 'PENDING') return 'warning'
  if (status === 'FAILED' || status === 'BOUNCED' || status === 'COMPLAINED') return 'danger'
  return 'neutral'
}

function EventActionsCell({ token, event, onChanged, onViewDetail }: {
  token: string
  event: NotificationEventRead
  onChanged: () => void
  onViewDetail: (eventId: string) => void
}) {
  const ack = useMutation({
    mutationFn: () => apiRequest<NotificationEventRead>(token, `/notifications/events/${event.id}/ack`, {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey('web-notifications-event-ack') },
    }),
    onSuccess: onChanged,
  })
  const resend = useMutation({
    mutationFn: () => apiRequest<NotificationEventRead>(token, `/notifications/events/${event.id}/resend`, {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey('web-notifications-event-resend') },
    }),
    onSuccess: onChanged,
  })

  return (
    <ErpActionCell>
      <ErpButton variant="ghost" onClick={() => onViewDetail(event.id)}>Ver detalle</ErpButton>
      {!event.ackAt ? (
        <ErpButton variant="ghost" disabled={ack.isPending} onClick={() => ack.mutate()}>
          {ack.isPending ? 'Confirmando…' : 'Dar acuse'}
        </ErpButton>
      ) : null}
      {event.status === 'FAILED' ? (
        <ErpButton variant="ghost" disabled={resend.isPending} onClick={() => resend.mutate()}>
          {resend.isPending ? 'Reintentando…' : 'Reintentar'}
        </ErpButton>
      ) : null}
      {ack.error ? <small className="form-error" role="alert">{ack.error.message}</small> : null}
      {resend.error ? <small className="form-error" role="alert">{resend.error.message}</small> : null}
    </ErpActionCell>
  )
}

function EventDetailPanel({ token, eventId, onClose }: { token: string; eventId: string; onClose: () => void }) {
  const detailQuery = useQuery({
    queryKey: ['notification-events', 'detail', eventId],
    queryFn: () => apiRequest<NotificationEventDetailRead>(token, `/notifications/events/${eventId}`),
  })
  const detail = detailQuery.data

  return (
    <ErpPanel title="Detalle del aviso" actions={<ErpButton variant="ghost" onClick={onClose}>Cerrar</ErpButton>}>
      {detailQuery.isPending ? <p aria-busy="true">Cargando detalle…</p> : null}
      {detailQuery.error ? <p className="form-error" role="alert">{detailQuery.error.message}</p> : null}
      {detail ? (
        <>
          <ErpDataTable
            ariaLabel="Entregas del aviso"
            rows={detail.deliveries}
            rowKey={(delivery) => delivery.id}
            emptyState={<ErpEmptyState title="Sin entregas" description="Este aviso todavía no generó entregas individuales." />}
            columns={[
              { header: 'Destinatario', cell: (delivery) => delivery.recipient },
              { header: 'Canal', cell: (delivery) => delivery.channel },
              {
                header: 'Estado',
                cell: (delivery) => (
                  <ErpStatusBadge tone={deliveryStatusTone(delivery.status)}>
                    {deliveryStatusLabel(delivery.status)}
                  </ErpStatusBadge>
                ),
              },
              { header: 'Enviado', cell: (delivery) => delivery.sentAt ? formatDateTime(delivery.sentAt) : '—' },
              { header: 'Error', cell: (delivery) => delivery.errorMessage ?? '—' },
            ]}
          />
          <details className="notif-payload-details">
            <summary>Ver datos crudos (payload)</summary>
            <pre>{JSON.stringify(detail.payload, null, 2)}</pre>
          </details>
        </>
      ) : null}
    </ErpPanel>
  )
}

function EventsTab({ token, rules }: { token: string; rules: NotificationRuleRead[] }) {
  const queryClient = useQueryClient()
  const [status, setStatus] = useState('')
  const [ruleType, setRuleType] = useState('')
  const [limit, setLimit] = useState('50')
  const [detailId, setDetailId] = useState<string | null>(null)

  const params = new URLSearchParams()
  if (status) params.set('status', status)
  if (ruleType) params.set('ruleType', ruleType)
  params.set('limit', limit)

  const eventsQuery = useQuery({
    queryKey: ['notification-events', status, ruleType, limit],
    queryFn: () => apiRequest<NotificationEventRead[]>(token, `/notifications/events?${params.toString()}`),
  })
  const events = eventsQuery.data ?? []

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ['notification-events'] })
  }

  return (
    <>
      <ErpToolbar ariaLabel="Filtros de la bitácora de avisos">
        <label>
          Estado
          <select value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="">Todos</option>
            {EVENT_STATUS_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </label>
        <label>
          Tipo de aviso
          <select value={ruleType} onChange={(event) => setRuleType(event.target.value)}>
            <option value="">Todos</option>
            {rules.map((rule) => <option key={rule.ruleType} value={rule.ruleType}>{rule.name}</option>)}
          </select>
        </label>
        <label>
          Mostrar
          <select value={limit} onChange={(event) => setLimit(event.target.value)}>
            <option value="50">50</option>
            <option value="100">100</option>
            <option value="200">200</option>
          </select>
        </label>
      </ErpToolbar>
      <ErpPanel title="Bitácora de avisos" count={events.length}>
        {eventsQuery.isPending ? <p aria-busy="true">Cargando bitácora…</p> : null}
        {eventsQuery.error ? <p className="form-error" role="alert">{eventsQuery.error.message}</p> : null}
        <ErpDataTable
          ariaLabel="Bitácora de avisos internos"
          rows={events}
          rowKey={(event) => event.id}
          emptyState={<ErpEmptyState title="Sin avisos" description="Todavía no hay avisos programados con estos filtros." />}
          columns={[
            { header: 'Aviso', cell: (event) => rules.find((rule) => rule.ruleType === event.ruleType)?.name ?? event.ruleType },
            { header: 'Período', cell: (event) => event.periodLabel ?? '—' },
            {
              header: 'Estado',
              cell: (event) => (
                <ErpStatusBadge tone={eventStatusTone(event.status)}>{eventStatusLabel(event.status)}</ErpStatusBadge>
              ),
            },
            { header: 'Programado para', cell: (event) => formatDateTime(event.scheduledAt) },
            { header: 'Intentos', cell: (event) => event.attempts },
            {
              header: 'Acciones',
              cell: (event) => (
                <EventActionsCell token={token} event={event} onChanged={refresh} onViewDetail={setDetailId} />
              ),
            },
          ]}
        />
      </ErpPanel>
      {detailId ? <EventDetailPanel token={token} eventId={detailId} onClose={() => setDetailId(null)} /> : null}
    </>
  )
}

const BILLING_FREQUENCY_OPTIONS: Array<{ value: NotificationBillingFrequency; label: string }> = [
  { value: 'MONTHLY', label: 'Mensual' },
  { value: 'BIMONTHLY', label: 'Bimestral' },
  { value: 'QUARTERLY', label: 'Trimestral' },
  { value: 'ANNUAL', label: 'Anual' },
]

function billingFrequencyLabel(frequency: NotificationBillingFrequency | string): string {
  return BILLING_FREQUENCY_OPTIONS.find((option) => option.value === frequency)?.label ?? frequency
}

function BillingScheduleForm({ token, parties, schedule, onCancel, onSaved }: {
  token: string
  parties: Party[]
  schedule?: NotificationBillingScheduleRead
  onCancel: () => void
  onSaved: () => void
}) {
  const [partyId, setPartyId] = useState(schedule?.partyId ?? '')
  const [dayOfMonth, setDayOfMonth] = useState(schedule?.dayOfMonth ?? 1)
  const [frequency, setFrequency] = useState<NotificationBillingFrequency>(schedule?.frequency ?? 'MONTHLY')
  const [anchorMonth, setAnchorMonth] = useState(schedule?.anchorMonth ? String(schedule.anchorMonth) : '')
  const [amountHint, setAmountHint] = useState(schedule?.amountHint ?? '')
  const [notes, setNotes] = useState(schedule?.notes ?? '')
  const [active, setActive] = useState(schedule?.active ?? true)

  const partyOptions = useMemo(
    () => parties.map((party) => ({ value: party.id, label: party.name, hint: party.identificationNumber })),
    [parties],
  )

  // El PUT acepta reasignar `partyId` (`NotificationBillingScheduleUpdate` lo
  // hereda de `Create` y `update_billing_schedule` lo aplica sin restricción,
  // verificado en `services/legal_commercial.py`), así que el combobox queda
  // editable también al editar.
  const save = useMutation({
    mutationFn: () => {
      const payload: NotificationBillingScheduleInput = {
        partyId,
        dayOfMonth: Number(dayOfMonth),
        frequency,
        anchorMonth: frequency === 'MONTHLY' ? null : (anchorMonth.trim() ? Number(anchorMonth) : null),
        amountHint: amountHint.trim() || null,
        notes: notes.trim() || null,
        ...(schedule ? { active } : {}),
      }
      return schedule
        ? apiRequest<NotificationBillingScheduleRead>(token, `/notifications/billing-schedules/${schedule.id}`, {
          method: 'PUT',
          headers: { 'Idempotency-Key': idempotencyKey('web-notifications-billing-schedule-update') },
          body: JSON.stringify(payload),
        })
        : apiRequest<NotificationBillingScheduleRead>(token, '/notifications/billing-schedules', {
          method: 'POST',
          headers: { 'Idempotency-Key': idempotencyKey('web-notifications-billing-schedule-create') },
          body: JSON.stringify(payload),
        })
    },
    onSuccess: onSaved,
  })

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    save.mutate()
  }

  return (
    <ErpFormPanel
      eyebrow="Avisos"
      title={schedule ? `Editar calendario de ${schedule.partyName}` : 'Nuevo calendario de facturación'}
      pending={save.isPending}
      error={save.error?.message}
      onSubmit={submit}
      onCancel={onCancel}
    >
      <div className="notif-form-grid">
        <label>
          Cliente
          <ErpCombobox
            options={partyOptions}
            value={partyId}
            onChange={setPartyId}
            ariaLabel="Cliente del calendario de facturación"
            required
          />
        </label>
        <label>
          Día del mes
          <input
            type="number"
            min={1}
            max={31}
            required
            value={dayOfMonth}
            onChange={(event) => setDayOfMonth(Number(event.target.value))}
          />
        </label>
        <label>
          Frecuencia
          <select value={frequency} onChange={(event) => setFrequency(event.target.value as NotificationBillingFrequency)}>
            {BILLING_FREQUENCY_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </label>
        {frequency !== 'MONTHLY' ? (
          <label>
            Mes ancla
            {/* Sin `required`: es una regla cruzada con `frequency` que ya aplica el
                backend (422 con detalle legible); duplicarla aquí solo taparía ese mensaje. */}
            <input
              type="number"
              min={1}
              max={12}
              value={anchorMonth}
              onChange={(event) => setAnchorMonth(event.target.value)}
            />
            <small className="fine-print">Necesario para que el aviso sepa desde qué mes contar.</small>
          </label>
        ) : null}
        <label>
          Monto de referencia
          <input type="number" min={0} step="0.01" value={amountHint} onChange={(event) => setAmountHint(event.target.value)} />
          <small className="fine-print">Solo es una referencia para el aviso, no un valor que se facture.</small>
        </label>
        <label>
          Notas
          <input value={notes} maxLength={500} onChange={(event) => setNotes(event.target.value)} />
        </label>
      </div>
      {schedule ? (
        <label className="notif-inline-check">
          <input type="checkbox" checked={active} onChange={(event) => setActive(event.target.checked)} />
          Activo
        </label>
      ) : null}
    </ErpFormPanel>
  )
}

function BillingSchedulesTab({ token, parties }: { token: string; parties: Party[] }) {
  const queryClient = useQueryClient()
  const [partyFilterId, setPartyFilterId] = useState('')
  const [editingSchedule, setEditingSchedule] = useState<NotificationBillingScheduleRead | null>(null)
  const [isCreating, setIsCreating] = useState(false)

  const params = new URLSearchParams()
  if (partyFilterId) params.set('partyId', partyFilterId)
  const query = params.toString()

  const schedulesQuery = useQuery({
    queryKey: ['notification-billing-schedules', partyFilterId],
    queryFn: () => apiRequest<NotificationBillingScheduleRead[]>(
      token,
      `/notifications/billing-schedules${query ? `?${query}` : ''}`,
    ),
  })
  const schedules = schedulesQuery.data ?? []

  const partyFilterOptions = useMemo(() => [
    { value: '', label: 'Todos los clientes' },
    ...parties.map((party) => ({ value: party.id, label: party.name, hint: party.identificationNumber })),
  ], [parties])

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ['notification-billing-schedules'] })
  }

  if (isCreating || editingSchedule) {
    return (
      <BillingScheduleForm
        token={token}
        parties={parties}
        schedule={editingSchedule ?? undefined}
        onCancel={() => { setIsCreating(false); setEditingSchedule(null) }}
        onSaved={() => { setIsCreating(false); setEditingSchedule(null); refresh() }}
      />
    )
  }

  return (
    <>
      <ErpToolbar ariaLabel="Filtro del calendario de facturación">
        <ErpCombobox
          options={partyFilterOptions}
          value={partyFilterId}
          onChange={setPartyFilterId}
          ariaLabel="Filtrar calendario por cliente"
          placeholder="Todos los clientes"
        />
      </ErpToolbar>
      <ErpPanel
        title="Calendario de facturación"
        count={schedules.length}
        actions={<ErpButton variant="secondary" onClick={() => setIsCreating(true)}>Nuevo calendario</ErpButton>}
      >
        {schedulesQuery.isPending ? <p aria-busy="true">Cargando calendario…</p> : null}
        {schedulesQuery.error ? <p className="form-error" role="alert">{schedulesQuery.error.message}</p> : null}
        <ErpDataTable
          ariaLabel="Calendario de facturación por cliente"
          rows={schedules}
          rowKey={(schedule) => schedule.id}
          emptyState={(
            <ErpEmptyState
              title="Sin calendarios"
              description="Da de alta el primer calendario para que el aviso de facturación sepa cuándo avisar."
              action={<ErpButton variant="primary" onClick={() => setIsCreating(true)}>Nuevo calendario</ErpButton>}
            />
          )}
          columns={[
            { header: 'Cliente', cell: (schedule) => schedule.partyName },
            { header: 'Día', cell: (schedule) => schedule.dayOfMonth },
            { header: 'Frecuencia', cell: (schedule) => billingFrequencyLabel(schedule.frequency) },
            { header: 'Mes ancla', cell: (schedule) => schedule.anchorMonth ?? '—' },
            { header: 'Monto de referencia', cell: (schedule) => schedule.amountHint ? `$${formatAmount(schedule.amountHint)}` : '—' },
            { header: 'Notas', cell: (schedule) => schedule.notes ?? '—' },
            {
              header: 'Activo',
              cell: (schedule) => (
                <ErpStatusBadge tone={schedule.active ? 'success' : 'neutral'}>
                  {schedule.active ? 'Activo' : 'Inactivo'}
                </ErpStatusBadge>
              ),
            },
            {
              header: 'Acciones',
              cell: (schedule) => (
                <ErpActionCell>
                  <ErpButton variant="ghost" onClick={() => setEditingSchedule(schedule)}>Editar</ErpButton>
                </ErpActionCell>
              ),
            },
          ]}
        />
      </ErpPanel>
    </>
  )
}

function ChannelTab({ token }: { token: string }) {
  const queryClient = useQueryClient()
  const channelQuery = useQuery({
    queryKey: ['notification-channel-account'],
    queryFn: () => apiRequest<ChannelAccountRead>(token, '/notifications/channel-account'),
  })
  const channel = channelQuery.data
  const [senderName, setSenderName] = useState('')
  const [senderEmail, setSenderEmail] = useState('')
  const [replyTo, setReplyTo] = useState('')

  useEffect(() => {
    if (channel) {
      setSenderName(channel.senderName ?? '')
      setSenderEmail(channel.senderEmail ?? '')
      setReplyTo(channel.replyTo ?? '')
    }
  }, [channel])

  const save = useMutation({
    mutationFn: () => apiRequest<ChannelAccountRead>(token, '/notifications/channel-account', {
      method: 'PUT',
      headers: { 'Idempotency-Key': idempotencyKey('web-notifications-channel-account-update') },
      body: JSON.stringify({
        senderName: senderName.trim() || null,
        senderEmail: senderEmail.trim() || null,
        replyTo: replyTo.trim() || null,
      } satisfies ChannelAccountUpdate),
    }),
    onSuccess: (updated) => queryClient.setQueryData(['notification-channel-account'], updated),
  })

  const [testRecipient, setTestRecipient] = useState('')
  const test = useMutation({
    mutationFn: () => apiRequest<ChannelTestResult>(token, '/notifications/channel-account/test', {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey('web-notifications-channel-account-test') },
      body: JSON.stringify({ recipient: testRecipient }),
    }),
  })

  function submitSender(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    save.mutate()
  }

  function submitTest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    test.mutate()
  }

  return (
    <>
      <ErpPanel title="Estado del canal">
        {channelQuery.isPending ? <p aria-busy="true">Cargando estado del canal…</p> : null}
        {channelQuery.error ? <p className="form-error" role="alert">{channelQuery.error.message}</p> : null}
        {channel ? (
          <div className="notif-channel-status">
            <ErpStatusBadge tone={channel.ready ? 'success' : 'danger'}>
              {channel.ready ? 'Listo para enviar' : 'No listo'}
            </ErpStatusBadge>
            <span>Proveedor: {channel.provider}</span>
            <span>
              Remitente actual: {channel.senderName}
              {channel.senderEmail ? ` <${channel.senderEmail}>` : ' (sin correo propio, usa el de la plataforma)'}
            </span>
            {channel.blockingReason ? <p className="form-warning">{channel.blockingReason}</p> : null}
          </div>
        ) : null}
      </ErpPanel>
      <ErpPanel title="Remitente de esta empresa">
        <form className="notif-form-grid" onSubmit={submitSender}>
          <label>
            Nombre del remitente
            <input value={senderName} maxLength={200} onChange={(event) => setSenderName(event.target.value)} />
          </label>
          <label>
            Correo del remitente
            <input type="email" value={senderEmail} onChange={(event) => setSenderEmail(event.target.value)} />
            <small className="fine-print">
              Solo funciona si el dominio está autenticado en la cuenta Brevo de IAERP; si no, deja este campo vacío
              para usar el remitente de la plataforma.
            </small>
          </label>
          <label>
            Responder a
            <input type="email" value={replyTo} onChange={(event) => setReplyTo(event.target.value)} />
          </label>
          {save.error ? <p className="form-error" role="alert">{save.error.message}</p> : null}
          <ErpButton variant="primary" type="submit" disabled={save.isPending}>
            {save.isPending ? 'Guardando…' : 'Guardar remitente'}
          </ErpButton>
        </form>
      </ErpPanel>
      <ErpPanel title="Enviar correo de prueba">
        <p className="fine-print">Prueba la cadena completa sin encender ninguna regla.</p>
        {channel && !channel.ready ? (
          <p className="form-warning">No se puede enviar la prueba: {channel.blockingReason ?? 'el canal todavía no está listo.'}</p>
        ) : null}
        <form className="notif-form-grid" onSubmit={submitTest}>
          <label>
            Correo de prueba
            <input
              type="email"
              required
              value={testRecipient}
              disabled={!channel?.ready}
              onChange={(event) => setTestRecipient(event.target.value)}
            />
          </label>
          <ErpButton variant="secondary" type="submit" disabled={!channel?.ready || test.isPending}>
            {test.isPending ? 'Enviando…' : 'Enviar prueba'}
          </ErpButton>
        </form>
        {test.error ? <p className="form-error" role="alert">{test.error.message}</p> : null}
        {test.data ? (
          <p
            className={test.data.status === 'FAILED' ? 'form-error' : 'form-success'}
            role={test.data.status === 'FAILED' ? 'alert' : undefined}
          >
            {test.data.status === 'SENT' ? 'Correo enviado.' : null}
            {test.data.status === 'STUBBED' ? 'Simulado (sin credenciales reales configuradas).' : null}
            {test.data.status === 'FAILED' ? `Falló: ${test.data.errorMessage ?? 'motivo desconocido'}` : null}
            {test.data.providerMessageId ? ` (ID ${test.data.providerMessageId})` : null}
          </p>
        ) : null}
      </ErpPanel>
    </>
  )
}

export function NotificationsPage({ token, parties }: { token: string; parties: Party[] }) {
  const [tab, setTab] = useState<'RULES' | 'TEMPLATES' | 'EVENTS' | 'BILLING' | 'CHANNEL'>('RULES')
  const rulesQuery = useQuery({
    queryKey: ['notification-rules'],
    queryFn: () => apiRequest<NotificationRuleRead[]>(token, '/notifications/rules'),
  })
  const rules = rulesQuery.data ?? []

  return (
    <>
      <ErpPageHeader
        eyebrow="Avisos"
        title="Avisos"
        subtitle="Notificaciones internas: quién avisa, cuándo y por dónde. Ningún aviso sale hasta que se enciende su regla."
      />
      <ErpToolbar ariaLabel="Secciones de avisos">
        <ErpTabs
          ariaLabel="Secciones de avisos"
          value={tab}
          onChange={setTab}
          tabs={[
            { value: 'RULES', label: 'Reglas' },
            { value: 'TEMPLATES', label: 'Plantillas' },
            { value: 'EVENTS', label: 'Bitácora' },
            { value: 'BILLING', label: 'Calendario de facturación' },
            { value: 'CHANNEL', label: 'Canal' },
          ]}
        />
      </ErpToolbar>
      {tab === 'RULES' ? (
        <RulesTab token={token} rules={rules} isPending={rulesQuery.isPending} error={rulesQuery.error?.message} />
      ) : null}
      {tab === 'TEMPLATES' ? <TemplatesTab token={token} rules={rules} /> : null}
      {tab === 'EVENTS' ? <EventsTab token={token} rules={rules} /> : null}
      {tab === 'BILLING' ? <BillingSchedulesTab token={token} parties={parties} /> : null}
      {tab === 'CHANNEL' ? <ChannelTab token={token} /> : null}
    </>
  )
}
