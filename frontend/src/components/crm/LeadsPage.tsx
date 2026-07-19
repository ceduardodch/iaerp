import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'

import {
  apiRequest,
  idempotencyKey,
  type Lead,
  type LeadCreate,
  type LeadWithPartyCreate,
  type Party,
  type Product,
} from '../../api'
import { ErpButton, ErpEmptyState, ErpFormPanel, ErpPageHeader, ErpToolbar } from '../erp'
import { CrmKanban } from './CrmKanban'
import { LeadCard } from './LeadCard'
import { LeadDetailPanel } from './LeadDetailPanel'
import { useKanban } from '../../hooks/useKanban'

type View = { kind: 'board' } | { kind: 'new' } | { kind: 'detail'; lead: Lead }

export function LeadsPage({
  token,
  parties,
  products,
}: {
  token: string
  parties: Party[]
  products: Product[]
}) {
  const queryClient = useQueryClient()
  const [view, setView] = useState<View>({ kind: 'board' })
  const [contactMode, setContactMode] = useState<'existing' | 'new'>('existing')

  // Hook custom para gestión del Kanban con drag & drop
  const {
    filteredLeads,
    draggedLeadId,
    leadsQuery,
    selectLead,
    setSearchQuery,
    kanbanProviders,
  } = useKanban({ token })

  const createLead = useMutation({
    mutationFn: ({ path, data }: { path: string; data: LeadCreate | LeadWithPartyCreate }) =>
      apiRequest<Lead>(token, path, {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey('crm-lead') },
        body: JSON.stringify(data),
      }),
    onSuccess: (lead) => {
      void queryClient.invalidateQueries({ queryKey: ['crm-leads'] })
      void queryClient.invalidateQueries({ queryKey: ['parties'] })
      setView({ kind: 'detail', lead })
    },
  })

  function submitLead(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    const common = {
      title: String(data.get('title')),
      productId: String(data.get('productId') || '') || null,
      source: String(data.get('source') || '') || null,
      score: Number(data.get('score') || 0),
      hotness: (data.get('hotness') || 'COLD') as 'COLD' | 'WARM' | 'HOT',
      estimatedValue: String(data.get('estimatedValue') || '') || null,
      expectedCloseDate: String(data.get('expectedCloseDate') || '') || null,
    }
    if (contactMode === 'existing') {
      createLead.mutate({
        path: '/crm/leads',
        data: { ...common, partyId: String(data.get('partyId')) },
      })
      return
    }
    createLead.mutate({
      path: '/crm/leads/with-party',
      data: {
        ...common,
        partyName: String(data.get('partyName')),
        partyIdentificationType: data.get('identificationType') as LeadWithPartyCreate['partyIdentificationType'],
        partyIdentificationNumber: String(data.get('identificationNumber')),
        partyEmail: String(data.get('email') || '') || null,
        partyPhone: String(data.get('phone') || '') || null,
        partyAddress: String(data.get('address') || '') || null,
      },
    })
  }

  if (view.kind === 'new') {
    return (
      <>
        <ErpPageHeader eyebrow="Gestión comercial" title="Nueva oportunidad" subtitle="Registra el negocio y su contacto sin usar identificadores técnicos." />
        <ErpFormPanel title="Datos de la oportunidad" eyebrow="Nuevo lead" pending={createLead.isPending} error={createLead.error?.message} onSubmit={submitLead} onCancel={() => setView({ kind: 'board' })}>
          <label>Título de la oportunidad<input name="title" placeholder="Venta de servicios AWS" required /></label>
          <label>Producto o servicio<select name="productId"><option value="">Sin producto definido</option>{products.map((product) => <option key={product.id} value={product.id}>{product.name}</option>)}</select></label>
          <div className="segmented-control" role="group" aria-label="Origen del contacto">
            <button type="button" className={contactMode === 'existing' ? 'active' : ''} onClick={() => setContactMode('existing')}>Contacto existente</button>
            <button type="button" className={contactMode === 'new' ? 'active' : ''} onClick={() => setContactMode('new')}>Contacto nuevo</button>
          </div>
          {contactMode === 'existing' ? (
            <label>Contacto<select name="partyId" required><option value="">Seleccionar…</option>{parties.map((party) => <option key={party.id} value={party.id}>{party.name} · {party.identificationNumber}</option>)}</select></label>
          ) : (
            <div className="lead-contact-fields">
              <label>Nombre o razón social<input name="partyName" required /></label>
              <div className="field-row"><label>Identificación<select name="identificationType"><option value="RUC">RUC</option><option value="CEDULA">Cédula</option><option value="PASSPORT">Pasaporte</option><option value="FINAL_CONSUMER">Consumidor final</option></select></label><label>Número<input name="identificationNumber" required /></label></div>
              <div className="field-row"><label>Correo<input name="email" type="email" /></label><label>Teléfono<input name="phone" /></label></div>
              <label>Dirección<input name="address" /></label>
            </div>
          )}
          <div className="field-row"><label>Origen<input name="source" placeholder="Referido, web, evento…" /></label><label>Valor estimado<input name="estimatedValue" type="number" min="0" step="0.01" /></label></div>
          <div className="field-row"><label>Temperatura<select name="hotness"><option value="COLD">Frío</option><option value="WARM">Tibio</option><option value="HOT">Caliente</option></select></label><label>Puntuación<input name="score" type="number" min="0" max="100" defaultValue="0" /></label></div>
          <label>Cierre esperado<input name="expectedCloseDate" type="date" /></label>
        </ErpFormPanel>
      </>
    )
  }

  if (view.kind === 'detail') {
    return <LeadDetailPanel lead={view.lead} token={token} products={products} onClose={() => setView({ kind: 'board' })} onUpdated={(lead) => { queryClient.setQueryData<Lead[]>(['crm-leads'], (current) => current?.map((item) => item.id === lead.id ? lead : item)); setView((current) => current.kind === 'detail' ? { kind: 'detail', lead } : current) }} />
  }

  const KanbanWithProviders = kanbanProviders

  return (
    <>
      <ErpPageHeader eyebrow="Gestión comercial" title="Pipeline" subtitle="Oportunidades ordenadas por etapa, valor y próxima acción." actions={<ErpButton variant="primary" onClick={() => setView({ kind: 'new' })}>Nueva oportunidad</ErpButton>} />
      <ErpToolbar><label className="search-field"><span>Buscar</span><input value="" onChange={(event) => setSearchQuery(event.target.value)} placeholder="Oportunidad, contacto o producto" /></label></ErpToolbar>
      {leadsQuery.isPending ? <p>Cargando pipeline…</p> : filteredLeads.length === 0 ? <ErpEmptyState title="No hay oportunidades" description="Crea el primer lead para comenzar el pipeline." action={<ErpButton variant="primary" onClick={() => setView({ kind: 'new' })}>Nueva oportunidad</ErpButton>} /> : (
        <KanbanWithProviders>
          <CrmKanban
            leads={filteredLeads}
            draggedLeadId={draggedLeadId}
            renderLeadCard={(lead, index) => (
              <LeadCard
                key={lead.id}
                lead={lead}
                index={index}
                onClick={() => selectLead(lead.id)}
                isDragging={draggedLeadId === lead.id}
              />
            )}
          />
        </KanbanWithProviders>
      )}
    </>
  )
}
