import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import {
  apiRequest,
  idempotencyKey,
  type LeadCreate,
  type LeadWithPartyCreate,
  type Party,
  type Product,
} from '../../api'
import { FormGrid, FormProgress, FormSection } from './index'

type LeadFormProps = {
  token: string
  parties: Party[]
  products: Product[]
  onCreated?: (lead: any) => void
  onCancel: () => void
}

export function LeadWithPartyFormVertical({
  token,
  parties,
  products,
  onCreated,
  onCancel,
}: LeadFormProps) {
  const queryClient = useQueryClient()
  const [contactMode, setContactMode] = useState<'existing' | 'new'>('existing')

  const createLead = useMutation({
    mutationFn: ({ path, data }: { path: string; data: LeadCreate | LeadWithPartyCreate }) =>
      apiRequest(token, path, {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey('crm-lead') },
        body: JSON.stringify(data),
      }),
    onSuccess: (lead) => {
      void queryClient.invalidateQueries({ queryKey: ['crm-leads'] })
      void queryClient.invalidateQueries({ queryKey: ['parties'] })
      if (onCreated && lead) onCreated(lead)
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

  const steps: Array<{ title: string; status: 'completed' | 'current' | 'pending' }> = [
    { title: 'Oportunidad', status: 'current' },
    { title: 'Contacto', status: 'pending' },
    { title: 'Detalles', status: 'pending' },
  ]

  return (
    <>
      <FormProgress steps={steps} />
      <form onSubmit={submitLead}>
        <FormSection
          title="Datos de la oportunidad"
          description="Información del lead y su valor"
          defaultExpanded={true}
        >
          <label>
            Título de la oportunidad
            <input name="title" placeholder="Venta de servicios AWS" required />
          </label>
          <FormGrid columns={2}>
            <label>
              Producto o servicio
              <select name="productId">
                <option value="">Sin producto definido</option>
                {products.map((product) => (
                  <option key={product.id} value={product.id}>{product.name}</option>
                ))}
              </select>
            </label>
            <label>
              Valor estimado
              <input name="estimatedValue" type="number" min="0" step="0.01" />
            </label>
          </FormGrid>
        </FormSection>

        <FormSection
          title="Contacto"
          description="Cliente asociado a la oportunidad"
          defaultExpanded={true}
        >
          <div className="segmented-control" role="group" aria-label="Origen del contacto">
            <button
              type="button"
              className={contactMode === 'existing' ? 'active' : ''}
              onClick={() => setContactMode('existing')}
            >
              Contacto existente
            </button>
            <button
              type="button"
              className={contactMode === 'new' ? 'active' : ''}
              onClick={() => setContactMode('new')}
            >
              Contacto nuevo
            </button>
          </div>

          {contactMode === 'existing' ? (
            <label>
              Contacto
              <select name="partyId" required>
                <option value="">Seleccionar…</option>
                {parties.map((party) => (
                  <option key={party.id} value={party.id}>{party.name} · {party.identificationNumber}</option>
                ))}
              </select>
            </label>
          ) : (
            <div className="lead-contact-fields">
              <label>
                Nombre o razón social
                <input name="partyName" required />
              </label>
              <FormGrid columns={2}>
                <label>
                  Identificación
                  <select name="identificationType">
                    <option value="RUC">RUC</option>
                    <option value="CEDULA">Cédula</option>
                    <option value="PASSPORT">Pasaporte</option>
                    <option value="FINAL_CONSUMER">Consumidor final</option>
                  </select>
                </label>
                <label>
                  Número
                  <input name="identificationNumber" required />
                </label>
              </FormGrid>
              <FormGrid columns={2}>
                <label>
                  Correo
                  <input name="email" type="email" />
                </label>
                <label>
                  Teléfono
                  <input name="phone" />
                </label>
              </FormGrid>
              <label>
                Dirección
                <input name="address" />
              </label>
            </div>
          )}
        </FormSection>

        <FormSection
          title="Detalles adicionales"
          description="Clasificación y timeline del lead"
          defaultExpanded={true}
        >
          <FormGrid columns={3}>
            <label>
              Origen
              <input name="source" placeholder="Referido, web, evento…" />
            </label>
            <label>
              Valor estimado
              <input name="estimatedValue" type="number" min="0" step="0.01" />
            </label>
            <label>
              Cierre esperado
              <input name="expectedCloseDate" type="date" />
            </label>
          </FormGrid>
          <FormGrid columns={2}>
            <label>
              Temperatura
              <select name="hotness">
                <option value="COLD">Frío</option>
                <option value="WARM">Tibio</option>
                <option value="HOT">Caliente</option>
              </select>
            </label>
            <label>
              Puntuación
              <input name="score" type="number" min="0" max="100" defaultValue="0" />
            </label>
          </FormGrid>
        </FormSection>

        <div className="erp-form-actions">
          <button type="button" className="erp-button erp-button-secondary" onClick={onCancel}>
            Cancelar
          </button>
          <button type="submit" className="erp-button erp-button-primary" disabled={createLead.isPending}>
            {createLead.isPending ? 'Creando…' : 'Crear oportunidad'}
          </button>
        </div>
      </form>
    </>
  )
}
