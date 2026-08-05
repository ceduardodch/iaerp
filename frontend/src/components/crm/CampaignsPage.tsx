import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'

import {
  apiRequest,
  idempotencyKey,
  type SocialCampaign,
  type SocialCampaignInsights,
  type SocialCampaignPolicy,
  type SocialCampaignVariant,
} from '../../api'
import {
  ErpButton,
  ErpEmptyState,
  ErpFormPanel,
  ErpPageHeader,
  ErpPanel,
  ErpStatusBadge,
} from '../erp'
import { ErpConfirmDialog } from '../erp/ErpConfirmDialog'

const STATUS_LABEL: Record<SocialCampaign['status'], string> = {
  DRAFT: 'Borrador',
  PREPARING: 'Preparando',
  PREPARED: 'Lista y pausada',
  ACTIVATING: 'Activando',
  ACTIVE: 'Activa',
  PAUSING: 'Pausando',
  PAUSED: 'Pausada',
  ERROR: 'Revisar',
}

function statusTone(status: SocialCampaign['status']) {
  if (status === 'ACTIVE') return 'success' as const
  if (status === 'ERROR') return 'danger' as const
  if (status === 'PREPARING' || status === 'PREPARED' || status === 'ACTIVATING' || status === 'PAUSING' || status === 'PAUSED') return 'warning' as const
  return 'neutral' as const
}

function money(value: string | null | undefined, currency: string | null | undefined) {
  if (value === null || value === undefined) return '—'
  return `${currency ?? ''} ${Number(value).toFixed(2)}`.trim()
}

function CampaignCard({
  token,
  campaign,
  onUpdated,
  onActivate,
  activationAllowed,
}: {
  token: string
  campaign: SocialCampaign
  onUpdated: (campaign: SocialCampaign) => void
  onActivate: (campaign: SocialCampaign) => void
  activationAllowed: boolean
}) {
  const queryClient = useQueryClient()
  const [addingVariant, setAddingVariant] = useState(false)
  const variantsKey = ['crm-campaign-variants', campaign.id]
  const insightsKey = ['crm-campaign-insights', campaign.id]
  const variantsQuery = useQuery({
    queryKey: variantsKey,
    queryFn: () => apiRequest<SocialCampaignVariant[]>(token, `/crm/campaigns/${campaign.id}/variants`),
  })
  const insightsQuery = useQuery({
    queryKey: insightsKey,
    queryFn: () => apiRequest<SocialCampaignInsights>(token, `/crm/campaigns/${campaign.id}/insights`),
  })
  const addVariant = useMutation({
    mutationFn: (data: object) => apiRequest<SocialCampaignVariant>(token, `/crm/campaigns/${campaign.id}/variants`, {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey('crm-campaign-variant') },
      body: JSON.stringify(data),
    }),
    onSuccess: (variant) => {
      queryClient.setQueryData<SocialCampaignVariant[]>(variantsKey, (current) => [...(current ?? []), variant])
      setAddingVariant(false)
    },
  })
  const uploadPrincipal = useMutation({
    mutationFn: (formData: FormData) => apiRequest<SocialCampaign>(token, `/crm/campaigns/${campaign.id}/creative`, {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey('crm-campaign-principal-image') },
      body: formData,
    }),
    onSuccess: (updated) => {
      onUpdated(updated)
      void queryClient.invalidateQueries({ queryKey: variantsKey })
    },
  })
  const uploadVariant = useMutation({
    mutationFn: ({ variantId, formData }: { variantId: string; formData: FormData }) =>
      apiRequest<SocialCampaignVariant>(token, `/crm/campaigns/${campaign.id}/variants/${variantId}/creative`, {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey('crm-campaign-variant-image') },
        body: formData,
      }),
    onSuccess: (updated) => {
      queryClient.setQueryData<SocialCampaignVariant[]>(variantsKey, (current) =>
        current?.map((item) => item.id === updated.id ? updated : item),
      )
    },
  })
  const campaignAction = useMutation({
    mutationFn: (action: 'prepare' | 'pause') => apiRequest<SocialCampaign>(token, `/crm/campaigns/${campaign.id}/${action}`, {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey(`crm-campaign-${action}`) },
    }),
    onSuccess: (updated) => {
      onUpdated(updated)
      void queryClient.invalidateQueries({ queryKey: variantsKey })
    },
  })
  const syncInsights = useMutation({
    mutationFn: () => apiRequest<SocialCampaignInsights>(token, `/crm/campaigns/${campaign.id}/insights/sync`, {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey('crm-campaign-insights') },
      body: JSON.stringify({ days: 3 }),
    }),
    onSuccess: (insights) => queryClient.setQueryData(insightsKey, insights),
  })

  function submitVariant(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    addVariant.mutate({
      key: String(data.get('key')).toLowerCase(),
      name: data.get('name'),
      angle: data.get('angle') || null,
      primaryText: data.get('primaryText'),
      headline: data.get('headline'),
      description: data.get('description') || null,
    })
  }

  const variants = variantsQuery.data ?? []
  const allImagesReady = variants.length > 0 && variants.every((item) => item.creativeSha256)
  const canEdit = ['DRAFT', 'ERROR'].includes(campaign.status)
  return (
    <ErpPanel
      title={campaign.name}
      actions={<ErpStatusBadge tone={statusTone(campaign.status)}>{STATUS_LABEL[campaign.status]}</ErpStatusBadge>}
      className="campaign-card"
    >
      <div className="campaign-card-grid">
        <dl>
          <div><dt>Presupuesto</dt><dd>{campaign.currency ?? 'Moneda por confirmar'} {Number(campaign.dailyBudget).toFixed(2)} al día</dd></div>
          <div><dt>Público</dt><dd>{campaign.countries.join(', ')} · {campaign.ageMin} a {campaign.ageMax} años</dd></div>
          <div><dt>Variantes</dt><dd>{variants.length}</dd></div>
        </dl>
        <p>Las variantes comparten campaña, público y presupuesto. Meta reparte el tráfico entre sus anuncios.</p>
      </div>
      {campaign.lastError ? <p className="form-error" role="alert">{campaign.lastError}</p> : null}
      {variantsQuery.error ? <p className="form-error">{variantsQuery.error.message}</p> : null}

      <section className="campaign-variants" aria-label={`Variantes de ${campaign.name}`}>
        <div className="campaign-section-heading">
          <h3>Variantes creativas</h3>
          {canEdit ? <ErpButton onClick={() => setAddingVariant((current) => !current)}>Añadir variante</ErpButton> : null}
        </div>
        {variants.length === 0 && canEdit ? (
          <form className="campaign-inline-form" onSubmit={(event) => {
            event.preventDefault()
            uploadPrincipal.mutate(new FormData(event.currentTarget))
          }}>
            <p>La primera imagen crea la variante principal con el texto del borrador.</p>
            <label>Imagen principal JPG o PNG<input name="creative" type="file" accept="image/jpeg,image/png" required /></label>
            <ErpButton type="submit" disabled={uploadPrincipal.isPending}>Crear variante principal</ErpButton>
          </form>
        ) : null}
        {addingVariant ? (
          <form className="campaign-variant-form" onSubmit={submitVariant}>
            <div className="field-row">
              <label>Clave<input name="key" placeholder="riesgo" pattern="[a-z0-9][a-z0-9_-]*" required /></label>
              <label>Nombre<input name="name" placeholder="Ángulo riesgo" required /></label>
              <label>Ángulo<input name="angle" placeholder="Riesgo, costo…" /></label>
            </div>
            <label>Texto principal<textarea name="primaryText" rows={3} required /></label>
            <div className="field-row">
              <label>Titular<input name="headline" required /></label>
              <label>Descripción<input name="description" /></label>
            </div>
            {addVariant.error ? <p className="form-error">{addVariant.error.message}</p> : null}
            <div className="campaign-actions">
              <ErpButton onClick={() => setAddingVariant(false)}>Cancelar</ErpButton>
              <ErpButton variant="primary" type="submit" disabled={addVariant.isPending}>Guardar variante</ErpButton>
            </div>
          </form>
        ) : null}
        <div className="campaign-variant-list">
          {variants.map((variant) => (
            <article key={variant.id} className="campaign-variant-card">
              <div><strong>{variant.name}</strong><small>{variant.angle || variant.key}</small></div>
              <p>{variant.primaryText}</p>
              <span>{variant.creativeSha256 ? 'Imagen lista' : 'Falta imagen'}</span>
              {canEdit ? (
                <form onSubmit={(event) => {
                  event.preventDefault()
                  uploadVariant.mutate({ variantId: variant.id, formData: new FormData(event.currentTarget) })
                }}>
                  <label>Imagen<input name="creative" type="file" accept="image/jpeg,image/png" required /></label>
                  <ErpButton type="submit" disabled={uploadVariant.isPending}>{variant.creativeSha256 ? 'Reemplazar' : 'Cargar'}</ErpButton>
                </form>
              ) : null}
            </article>
          ))}
        </div>
      </section>

      <div className="campaign-actions">
        {allImagesReady && canEdit ? (
          <ErpButton variant="primary" disabled={campaignAction.isPending} onClick={() => campaignAction.mutate('prepare')}>Preparar todas en Meta (pausadas)</ErpButton>
        ) : null}
        {['PREPARED', 'PAUSED'].includes(campaign.status) ? <ErpButton variant="success" disabled={!activationAllowed} onClick={() => onActivate(campaign)}>Activar campaña</ErpButton> : null}
        {campaign.externalCampaignId && ['ACTIVATING', 'ACTIVE', 'ERROR'].includes(campaign.status) ? <ErpButton variant="danger" disabled={campaignAction.isPending} onClick={() => campaignAction.mutate('pause')}>Pausar campaña</ErpButton> : null}
        {['PREPARED', 'ACTIVE', 'PAUSED'].includes(campaign.status) ? <ErpButton disabled={syncInsights.isPending} onClick={() => syncInsights.mutate()}>{syncInsights.isPending ? 'Sincronizando…' : 'Actualizar métricas'}</ErpButton> : null}
      </div>
      {campaignAction.error ? <p className="form-error">{campaignAction.error.message}</p> : null}
      {syncInsights.error ? <p className="form-error">{syncInsights.error.message}</p> : null}

      {insightsQuery.data?.variants.length ? (
        <div className="campaign-insights-table-wrap">
          <table className="campaign-insights-table">
            <thead><tr><th>Variante</th><th>Gasto</th><th>Impresiones</th><th>CTR</th><th>Leads</th><th>CPL</th><th>Calificados</th><th>Costo/calificado</th></tr></thead>
            <tbody>
              {insightsQuery.data.variants.map((item) => (
                <tr key={item.variant.id}>
                  <td><strong>{item.variant.name}</strong><small>{item.variant.angle}</small></td>
                  <td>{money(item.spend, item.currency)}</td>
                  <td>{item.impressions.toLocaleString('es-EC')}</td>
                  <td>{item.ctr ? `${item.ctr}%` : '—'}</td>
                  <td>{item.leads}</td>
                  <td>{money(item.cpl, item.currency)}</td>
                  <td>{item.qualifiedLeads}</td>
                  <td>{money(item.costPerQualifiedLead, item.currency)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <p className="fine-print">Aún no hay métricas guardadas. Meta Insights se consulta por día y anuncio.</p>}
    </ErpPanel>
  )
}

export function CampaignsPage({ token, onBack }: { token: string; onBack: () => void }) {
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)
  const [activationTarget, setActivationTarget] = useState<SocialCampaign | null>(null)
  const campaignsQuery = useQuery({
    queryKey: ['crm-campaigns'],
    queryFn: () => apiRequest<SocialCampaign[]>(token, '/crm/campaigns'),
    refetchInterval: (query) => query.state.data?.some((item) => ['PREPARING', 'ACTIVATING', 'PAUSING'].includes(item.status)) ? 2000 : false,
  })
  const policyQuery = useQuery({
    queryKey: ['crm', 'campaign-policy'],
    queryFn: () => apiRequest<SocialCampaignPolicy>(token, '/crm/campaigns/policy'),
  })
  const updateCampaign = (campaign: SocialCampaign) => {
    queryClient.setQueryData<SocialCampaign[]>(['crm-campaigns'], (current) => current?.map((item) => item.id === campaign.id ? campaign : item))
  }
  const createCampaign = useMutation({
    mutationFn: (data: object) => apiRequest<SocialCampaign>(token, '/crm/campaigns', {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey('crm-campaign-create') },
      body: JSON.stringify(data),
    }),
    onSuccess: (campaign) => {
      queryClient.setQueryData<SocialCampaign[]>(['crm-campaigns'], (current) => [campaign, ...(current ?? [])])
      setCreating(false)
    },
  })
  const activateCampaign = useMutation({
    mutationFn: (campaignId: string) => apiRequest<SocialCampaign>(token, `/crm/campaigns/${campaignId}/activate`, {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey('crm-campaign-activate') },
      body: JSON.stringify({ confirmed: true }),
    }),
    onSuccess: (campaign) => {
      updateCampaign(campaign)
      setActivationTarget(null)
    },
  })

  function submitCampaign(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    createCampaign.mutate({
      name: data.get('name'), dailyBudget: data.get('dailyBudget'),
      ageMin: Number(data.get('ageMin')), ageMax: Number(data.get('ageMax')),
      countries: [String(data.get('country') || 'EC').toUpperCase()],
      primaryText: data.get('primaryText'), headline: data.get('headline'),
      description: data.get('description') || null, leadFormId: data.get('leadFormId') || null,
    })
  }

  if (creating) return (
    <>
      <ErpPageHeader eyebrow="CRM · Redes" title="Nueva campaña" subtitle="Define el público y la primera variante. El borrador no crea gasto." />
      <ErpFormPanel eyebrow="Campaña Meta" title="Público, presupuesto y variante principal" submitLabel="Guardar borrador" pending={createCampaign.isPending} error={createCampaign.error?.message} onSubmit={submitCampaign} onCancel={() => setCreating(false)}>
        <label>Nombre<input name="name" required /></label>
        <div className="field-row"><label>Presupuesto diario (moneda de la cuenta)<input name="dailyBudget" type="number" min="1" max="10000" step="0.01" defaultValue="5.00" required /></label><label>País<input name="country" defaultValue="EC" pattern="[A-Za-z]{2}" required /></label></div>
        <div className="field-row"><label>Edad mínima<input name="ageMin" type="number" min="18" max="65" defaultValue="25" required /></label><label>Edad máxima<input name="ageMax" type="number" min="18" max="65" defaultValue="65" required /></label></div>
        <label>Texto de la variante principal<textarea name="primaryText" rows={4} maxLength={5000} required /></label>
        <label>Titular principal<input name="headline" maxLength={200} required /></label>
        <label>Descripción<input name="description" maxLength={500} /></label>
        <label>Formulario instantáneo Meta<input name="leadFormId" placeholder="Opcional: usa el formulario por defecto" /></label>
      </ErpFormPanel>
    </>
  )

  const campaigns = campaignsQuery.data ?? []
  return (
    <>
      <ErpPageHeader eyebrow="CRM · Redes" title="Campañas" subtitle="Compara variantes, controla el gasto y recibe los formularios como leads." actions={<><ErpButton onClick={onBack}>Volver al pipeline</ErpButton><ErpButton variant="primary" onClick={() => setCreating(true)}>Nueva campaña</ErpButton></>} />
      <p className="environment-warning campaign-spend-warning">Preparar crea todos los anuncios en pausa. Activar inicia el gasto compartido del presupuesto diario.</p>
      {policyQuery.data && !policyQuery.data.activationEnabled ? <p className="fine-print" role="status">La activación está bloqueada en Empresa → Canales e integraciones. Un propietario debe definir el tope diario.</p> : null}
      {campaignsQuery.isPending ? <p>Cargando campañas…</p> : null}
      {campaignsQuery.error ? <p className="form-error">{campaignsQuery.error.message}</p> : null}
      {!campaignsQuery.isPending && campaigns.length === 0 ? <ErpEmptyState title="No hay campañas" description="Crea un borrador y sus variantes antes de preparar Meta." action={<ErpButton variant="primary" onClick={() => setCreating(true)}>Nueva campaña</ErpButton>} /> : (
        <div className="campaign-list">{campaigns.map((campaign) => <CampaignCard key={campaign.id} token={token} campaign={campaign} onUpdated={updateCampaign} onActivate={setActivationTarget} activationAllowed={policyQuery.data?.activationEnabled === true} />)}</div>
      )}
      {activationTarget ? <ErpConfirmDialog title="Activar campaña y comenzar gasto" description={<>Meta activará <strong>{activationTarget.name}</strong> con un límite diario de <strong>{activationTarget.currency ?? 'moneda de cuenta'} {Number(activationTarget.dailyBudget).toFixed(2)}</strong> compartido entre sus variantes. IAERP registrará quién aprobó la acción.</>} confirmLabel="Sí, activar campaña" pending={activateCampaign.isPending} onCancel={() => setActivationTarget(null)} onConfirm={() => activateCampaign.mutate(activationTarget.id)} /> : null}
    </>
  )
}
