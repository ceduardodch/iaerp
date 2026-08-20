import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import {
  apiRequest,
  idempotencyKey,
  type ActionQueueCollectionCandidate,
  type ActionQueueProspectingCandidate,
  type ActionQueueRead,
  type IntegrationStatus,
  type LeadActivity,
  type LeadMessageCreate,
  type Operation,
  type ReminderInput,
} from '../../api'
import { ErpButton, ErpEmptyState, ErpPageHeader, ErpPanel } from '../erp'
import './ActionQueuePage.css'

const amountFormatter = new Intl.NumberFormat('es-EC', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

function formatAmount(value: string | number): string {
  const amount = Number(value)
  return Number.isFinite(amount) ? amountFormatter.format(amount) : '0,00'
}

function formatDate(value: string): string {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString('es-EC')
}

/**
 * `IntegrationStatus` trae un flag de conexión por proveedor (Meta/Evolution)
 * y por separado a qué proveedor está enrutado cada canal
 * (`whatsappCrmProvider` para prospección, `whatsappCollectionsProvider`
 * para cobranza). Un tenant puede tener Evolution conectado para cobranza
 * pero Meta para CRM (o viceversa), así que la lectura "¿puedo enviar?" no es
 * un solo booleano global: depende de qué proveedor enruta cada lista.
 */
function isChannelReady(status: IntegrationStatus | undefined, provider: 'META' | 'EVOLUTION' | undefined): boolean {
  if (!status || !provider) return false
  return provider === 'META' ? status.whatsappMetaConnected : status.whatsappEvolutionConnected
}

function WhatsAppDisconnectedNotice({ onGoToSettings }: { onGoToSettings?: () => void }) {
  return (
    <p className="form-warning" role="status">
      WhatsApp no está conectado para este canal. Conéctalo en{' '}
      <strong>Empresa → Canales e integraciones</strong> para poder enviar estos mensajes.
      {onGoToSettings ? (
        <>
          {' '}
          <ErpButton variant="secondary" onClick={onGoToSettings}>
            Ir a Configuración
          </ErpButton>
        </>
      ) : null}
    </p>
  )
}

function CollectionRow({
  token,
  candidate,
  whatsappReady,
  onSent,
}: {
  token: string
  candidate: ActionQueueCollectionCandidate
  whatsappReady: boolean
  onSent: (receivableId: string) => void
}) {
  const [message, setMessage] = useState(candidate.suggestedMessage)

  const sendReminder = useMutation({
    mutationFn: () =>
      apiRequest<Operation>(token, `/receivables/${candidate.receivableId}/reminders`, {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey('web-action-queue-reminder') },
        body: JSON.stringify({
          channel: 'WHATSAPP',
          templateId: null,
          message,
          scheduledAt: null,
          // Este candidato ya pasó el filtro de cooldown del backend, pero si
          // tuvo un recordatorio ANTES de esa ventana puede seguir "SENT" en
          // la base: sin motivo de reenvío el endpoint responde 409.
          resendReason: candidate.lastReminderAt
            ? 'Nuevo recordatorio desde la bandeja de acción'
            : null,
        } satisfies ReminderInput),
      }),
    onSuccess: () => onSent(candidate.receivableId),
  })

  return (
    <li className="action-queue-row">
      <div className="action-queue-row-info">
        <strong>{candidate.partyName}</strong>
        <span className="fine-print">{candidate.phone}</span>
        <span className="action-queue-row-meta">
          ${formatAmount(candidate.openAmount)} pendiente · {candidate.daysOverdue} día(s) de atraso
        </span>
      </div>
      <label className="action-queue-row-message">
        Mensaje de WhatsApp
        <textarea
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          rows={3}
          maxLength={2000}
        />
      </label>
      <div className="action-queue-row-actions">
        <ErpButton
          variant="primary"
          disabled={!whatsappReady || sendReminder.isPending || !message.trim()}
          onClick={() => sendReminder.mutate()}
        >
          {sendReminder.isPending ? 'Enviando…' : 'Enviar'}
        </ErpButton>
        {sendReminder.error ? (
          <p className="form-error" role="alert">
            {sendReminder.error.message}
          </p>
        ) : null}
      </div>
    </li>
  )
}

function ProspectingRow({
  token,
  candidate,
  whatsappReady,
  onSent,
}: {
  token: string
  candidate: ActionQueueProspectingCandidate
  whatsappReady: boolean
  onSent: (leadId: string) => void
}) {
  const [message, setMessage] = useState(candidate.suggestedMessage)

  const sendMessage = useMutation({
    mutationFn: () =>
      apiRequest<LeadActivity>(token, `/crm/leads/${candidate.leadId}/messages`, {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey('web-action-queue-message') },
        body: JSON.stringify({
          channel: 'WHATSAPP',
          subject: null,
          message,
          templateId: null,
          followUpDays: 4,
        } satisfies LeadMessageCreate),
      }),
    onSuccess: () => onSent(candidate.leadId),
  })

  return (
    <li className="action-queue-row">
      <div className="action-queue-row-info">
        <strong>{candidate.partyName}</strong>
        <span className="fine-print">{candidate.phone}</span>
        <span className="action-queue-row-meta">Lead creado el {formatDate(candidate.createdAt)}</span>
      </div>
      <label className="action-queue-row-message">
        Mensaje de WhatsApp
        <textarea
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          rows={3}
          maxLength={2000}
        />
      </label>
      <div className="action-queue-row-actions">
        <ErpButton
          variant="primary"
          disabled={!whatsappReady || sendMessage.isPending || !message.trim()}
          onClick={() => sendMessage.mutate()}
        >
          {sendMessage.isPending ? 'Enviando…' : 'Enviar'}
        </ErpButton>
        {sendMessage.error ? (
          <p className="form-error" role="alert">
            {sendMessage.error.message}
          </p>
        ) : null}
      </div>
    </li>
  )
}

/**
 * Bandeja de acción (Comercial → Bandeja de acción): un solo lugar para
 * revisar y aprobar los recordatorios de cobranza vencida y los mensajes de
 * primer contacto que el sistema sugiere, en vez de entrar factura por
 * factura o lead por lead. Solo agrega candidatos (`GET /crm/action-queue`);
 * el envío real sigue pasando por los dos endpoints que ya existían.
 */
export function ActionQueuePage({
  token,
  onGoToSettings,
}: {
  token: string
  onGoToSettings?: () => void
}) {
  const queryClient = useQueryClient()
  const [sentReceivableIds, setSentReceivableIds] = useState<Set<string>>(new Set())
  const [sentLeadIds, setSentLeadIds] = useState<Set<string>>(new Set())

  const queueQuery = useQuery({
    queryKey: ['crm', 'action-queue'],
    queryFn: () => apiRequest<ActionQueueRead>(token, '/crm/action-queue'),
  })
  const integrationsQuery = useQuery({
    queryKey: ['crm', 'integrations'],
    queryFn: () => apiRequest<IntegrationStatus>(token, '/crm/integrations'),
  })

  function markReceivableSent(receivableId: string) {
    setSentReceivableIds((current) => new Set(current).add(receivableId))
    void queryClient.invalidateQueries({ queryKey: ['crm', 'action-queue'] })
  }

  function markLeadSent(leadId: string) {
    setSentLeadIds((current) => new Set(current).add(leadId))
    void queryClient.invalidateQueries({ queryKey: ['crm', 'action-queue'] })
  }

  const collections = (queueQuery.data?.collections ?? []).filter(
    (candidate) => !sentReceivableIds.has(candidate.receivableId),
  )
  const prospecting = (queueQuery.data?.prospecting ?? []).filter(
    (candidate) => !sentLeadIds.has(candidate.leadId),
  )

  const collectionsReady = isChannelReady(integrationsQuery.data, integrationsQuery.data?.whatsappCollectionsProvider)
  const prospectingReady = isChannelReady(integrationsQuery.data, integrationsQuery.data?.whatsappCrmProvider)

  const nothingPending =
    !queueQuery.isLoading && !queueQuery.error && collections.length === 0 && prospecting.length === 0

  return (
    <>
      <ErpPageHeader
        eyebrow="Comercial"
        title="Bandeja de acción"
        subtitle="Revisa y aprueba en un solo lugar los recordatorios de cobranza vencida y los mensajes de primer contacto sugeridos antes de enviarlos por WhatsApp."
      />

      {queueQuery.error ? (
        <p className="form-error" role="alert">
          No se pudo cargar la bandeja: {queueQuery.error.message}
        </p>
      ) : null}

      {nothingPending ? (
        <ErpEmptyState
          title="No hay pendientes hoy"
          description="No hay recordatorios de cobranza ni mensajes de prospección sugeridos por ahora. Vuelve a revisar más tarde."
        />
      ) : (
        <>
          <ErpPanel title="Cobranza pendiente" count={collections.length}>
            {integrationsQuery.data && !collectionsReady ? (
              <WhatsAppDisconnectedNotice onGoToSettings={onGoToSettings} />
            ) : null}
            {queueQuery.isLoading ? <p className="fine-print">Cargando…</p> : null}
            {!queueQuery.isLoading && collections.length === 0 ? (
              <ErpEmptyState
                title="Sin cobranza pendiente"
                description="No hay facturas vencidas con recordatorio sugerido en este momento."
              />
            ) : (
              <ul className="action-queue-list">
                {collections.map((candidate) => (
                  <CollectionRow
                    key={candidate.receivableId}
                    token={token}
                    candidate={candidate}
                    whatsappReady={collectionsReady}
                    onSent={markReceivableSent}
                  />
                ))}
              </ul>
            )}
          </ErpPanel>

          <ErpPanel title="Prospección pendiente" count={prospecting.length}>
            {integrationsQuery.data && !prospectingReady ? (
              <WhatsAppDisconnectedNotice onGoToSettings={onGoToSettings} />
            ) : null}
            {queueQuery.isLoading ? <p className="fine-print">Cargando…</p> : null}
            {!queueQuery.isLoading && prospecting.length === 0 ? (
              <ErpEmptyState
                title="Sin prospección pendiente"
                description="No hay leads nuevos con mensaje de primer contacto sugerido en este momento."
              />
            ) : (
              <ul className="action-queue-list">
                {prospecting.map((candidate) => (
                  <ProspectingRow
                    key={candidate.leadId}
                    token={token}
                    candidate={candidate}
                    whatsappReady={prospectingReady}
                    onSent={markLeadSent}
                  />
                ))}
              </ul>
            )}
          </ErpPanel>
        </>
      )}
    </>
  )
}
