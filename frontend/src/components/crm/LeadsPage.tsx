import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useDeferredValue, useState, type FormEvent } from 'react'

import { apiRequest, idempotencyKey, type Lead, type LeadCreate, type LeadStatus } from '../api'
import { useAuth } from '../auth'
import {
  ErpActionCell,
  ErpButton,
  ErpEmptyState,
  ErpFormPanel,
  ErpPageHeader,
  ErpPanel,
  ErpStatusBadge,
  ErpToolbar,
} from '../components/erp'

const LEAD_STATUS_LABELS: Record<LeadStatus, string> = {
  NEW: 'Nuevo',
  CONTACTED: 'Contactado',
  QUALIFIED: 'Calificado',
  PROPOSAL: 'Propuesta',
  NEGOTIATION: 'Negociación',
  WON: 'Ganado',
  LOST: 'Perdido',
}

const LEAD_STATUS_TONES: Record<LeadStatus, 'neutral' | 'success' | 'warning' | 'danger'> = {
  NEW: 'neutral',
  CONTACTED: 'neutral',
  QUALIFIED: 'warning',
  PROPOSAL: 'warning',
  NEGOTIATION: 'warning',
  WON: 'success',
  LOST: 'danger',
}

function LeadStatusBadge({ status }: { status: LeadStatus }) {
  return (
    <ErpStatusBadge tone={LEAD_STATUS_TONES[status]}>
      {LEAD_STATUS_LABELS[status]}
    </ErpStatusBadge>
  )
}

function HotnessBadge({ hotness }: { hotness: 'COLD' | 'WARM' | 'HOT' }) {
  const tones: Record<'COLD' | 'WARM' | 'HOT', 'neutral' | 'success' | 'warning' | 'danger'> = {
    COLD: 'neutral',
    WARM: 'warning',
    HOT: 'danger',
  }
  const labels: Record<'COLD' | 'WARM' | 'HOT', string> = {
    COLD: 'Frío',
    WARM: 'Tibio',
    HOT: 'Caliente',
  }
  return (
    <ErpStatusBadge tone={tones[hotness]}>
      {labels[hotness]}
    </ErpStatusBadge>
  )
}

export function LeadsPage() {
  const { token } = useAuth()
  const queryClient = useQueryClient()
  const [statusFilter, setStatusFilter] = useState<LeadStatus | ''>('')
  const [editor, setEditor] = useState<Lead | null | undefined>(undefined)

  const { data: leads = [], isLoading } = useQuery({
    queryKey: ['crm-leads', statusFilter],
    queryFn: () =>
      apiRequest<Lead[]>(
        token,
        statusFilter ? `/crm/leads?status=${statusFilter}` : '/crm/leads',
      ),
  })

  const createLead = useMutation({
    mutationFn: (data: LeadCreate) =>
      apiRequest<Lead>(token, '/crm/leads', {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey('crm-lead') },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      setEditor(undefined)
      return queryClient.invalidateQueries({ queryKey: ['crm-leads'] })
    },
  })

  function submitLead(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const data = new FormData(form)
    createLead.mutate({
      partyId: String(data.get('partyId')),
      status: (data.get('status') as LeadStatus) || 'NEW',
      source: data.get('source') as string | null,
      score: parseInt(String(data.get('score') || '0'), 10),
      hotness: (data.get('hotness') as 'COLD' | 'WARM' | 'HOT') || 'COLD',
    })
  }

  return (
    <>
      <ErpPageHeader
        eyebrow="Gestión de prospectos"
        title="Leads"
        subtitle="Pipeline de ventas y seguimiento de prospectos."
        actions={
          <ErpButton variant="primary" onClick={() => setEditor(null)}>
            Nuevo lead
          </ErpButton>
        }
      />

      <ErpToolbar>
        <label className="search-field">
          <span>Filtrar por estado</span>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as LeadStatus | '')}
          >
            <option value="">Todos los estados</option>
            <option value="NEW">Nuevos</option>
            <option value="CONTACTED">Contactados</option>
            <option value="QUALIFIED">Calificados</option>
            <option value="PROPOSAL">Con propuesta</option>
            <option value="NEGOTIATION">En negociación</option>
            <option value="WON">Ganados</option>
            <option value="LOST">Perdidos</option>
          </select>
        </label>
      </ErpToolbar>

      <section className={`split-layout ${editor === undefined ? 'erp-list-only' : ''}`}>
        <ErpPanel title="Prospectos" count={leads.length}>
          {isLoading ? (
            <p>Cargando leads...</p>
          ) : leads.length === 0 ? (
            <ErpEmptyState
              title="No hay leads"
              description="Crea el primer prospecto para comenzar tu pipeline de ventas."
              action={
                <ErpButton variant="primary" onClick={() => setEditor(null)}>
                  Nuevo lead
                </ErpButton>
              }
            />
          ) : (
            <div className="table-wrap">
              <table className="erp-responsive-table">
                <thead>
                  <tr>
                    <th>Party ID</th>
                    <th>Estado</th>
                    <th>Source</th>
                    <th>Puntuación</th>
                    <th>Temperatura</th>
                    <th>Valor estimado</th>
                    <th>Cierre esperado</th>
                    <th>Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {leads.map((lead) => (
                    <tr key={lead.id}>
                      <td>
                        <strong>{lead.partyId}</strong>
                      </td>
                      <td>
                        <LeadStatusBadge status={lead.status} />
                      </td>
                      <td>{lead.source || '-'}</td>
                      <td>{lead.score}/100</td>
                      <td>
                        <HotnessBadge hotness={lead.hotness} />
                      </td>
                      <td>{lead.estimatedValue || '-'}</td>
                      <td>{lead.expectedCloseDate || '-'}</td>
                      <td>
                        <ErpActionCell>
                          <ErpButton
                            variant="ghost"
                            onClick={() => setEditor(lead)}
                          >
                            Ver detalle
                          </ErpButton>
                        </ErpActionCell>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </ErpPanel>

        {editor !== undefined ? (
          <ErpFormPanel
            key={editor?.id ?? 'new-lead'}
            eyebrow={editor ? 'Detalle' : 'Nuevo registro'}
            title={editor ? 'Detalle del lead' : 'Nuevo lead'}
            pending={createLead.isPending}
            error={createLead.error?.message}
            onSubmit={submitLead}
            onCancel={() => setEditor(undefined)}
          >
            <label>
              Party ID
              <input
                name="partyId"
                defaultValue={editor?.partyId}
                required
              />
            </label>
            <label>
              Estado
              <select
                name="status"
                defaultValue={editor?.status ?? 'NEW'}
              >
                <option value="NEW">Nuevo</option>
                <option value="CONTACTED">Contactado</option>
                <option value="QUALIFIED">Calificado</option>
                <option value="PROPOSAL">Propuesta</option>
                <option value="NEGOTIATION">Negociación</option>
                <option value="WON">Ganado</option>
                <option value="LOST">Perdido</option>
              </select>
            </label>
            <label>
              Source
              <input
                name="source"
                defaultValue={editor?.source ?? ''}
              />
            </label>
            <label>
              Puntuación (0-100)
              <input
                name="score"
                type="number"
                min="0"
                max="100"
                defaultValue={editor?.score ?? 0}
              />
            </label>
            <label>
              Temperatura
              <select
                name="hotness"
                defaultValue={editor?.hotness ?? 'COLD'}
              >
                <option value="COLD">Frío</option>
                <option value="WARM">Tibio</option>
                <option value="HOT">Caliente</option>
              </select>
            </label>
          </ErpFormPanel>
        ) : null}
      </section>
    </>
  )
}
