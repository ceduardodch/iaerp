import { useState, type FormEvent } from 'react'

import type { Lead, LeadStatus, LeadWithPartyCreate, Product } from '../../api'
import { ErpButton } from '../erp'
import type { UseKanbanReturn } from '../../hooks/useKanban'

/**
 * Form compacto para crear un lead desde una columna del kanban (Sprint 2).
 *
 * Campos mínimos: título, contacto (nombre + identificación) y opcionales de
 * negocio. El backend crea siempre en NEW; el hook encadena un salto a la
 * columna destino solo si es una transición directa válida (ver
 * `crmTransitions.isQuickAddSingleHop`); si no, el lead queda en NEW y
 * `onCreated` recibe `stayedInNew: true` para avisar al usuario.
 */
export function QuickAddLeadForm({
  targetStatus,
  mutation,
  products,
  onCancel,
  onCreated,
}: {
  targetStatus: LeadStatus
  mutation: UseKanbanReturn['createLeadWithPartyMutation']
  products: Product[]
  onCancel: () => void
  onCreated: (result: { lead: Lead; stayedInNew: boolean }) => void
}) {
  const [error, setError] = useState<string | null>(null)

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    const form = new FormData(event.currentTarget)
    const data: LeadWithPartyCreate = {
      title: String(form.get('title')),
      partyName: String(form.get('partyName')),
      partyIdentificationType: form.get(
        'identificationType'
      ) as LeadWithPartyCreate['partyIdentificationType'],
      partyIdentificationNumber: String(form.get('identificationNumber')),
      partyEmail: String(form.get('email') || '') || null,
      partyPhone: String(form.get('phone') || '') || null,
      productId: String(form.get('productId') || '') || null,
      source: String(form.get('source') || '') || null,
      hotness: (form.get('hotness') || 'COLD') as 'COLD' | 'WARM' | 'HOT',
      estimatedValue: String(form.get('estimatedValue') || '') || null,
    }
    const tempId = `temp-${crypto.randomUUID()}`
    mutation.mutate(
      { targetStatus, data, tempId },
      {
        onSuccess: (result) => onCreated(result),
        onError: (cause) =>
          setError(cause instanceof Error ? cause.message : 'No se pudo crear el lead'),
      }
    )
  }

  return (
    <form className="quick-add-form" onSubmit={submit}>
      <label>
        Título de la oportunidad
        <input name="title" placeholder="Venta de servicios AWS" required autoFocus />
      </label>
      <label>
        Nombre o razón social
        <input name="partyName" required />
      </label>
      <div className="field-row">
        <label>
          Identificación
          <select name="identificationType" defaultValue="CEDULA">
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
      </div>
      <div className="field-row">
        <label>
          Correo
          <input name="email" type="email" />
        </label>
        <label>
          Teléfono
          <input name="phone" />
        </label>
      </div>
      <div className="field-row">
        <label>
          Producto
          <select name="productId">
            <option value="">Sin producto definido</option>
            {products.map((product) => (
              <option key={product.id} value={product.id}>
                {product.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Temperatura
          <select name="hotness" defaultValue="COLD">
            <option value="COLD">Frío</option>
            <option value="WARM">Tibio</option>
            <option value="HOT">Caliente</option>
          </select>
        </label>
      </div>
      <div className="field-row">
        <label>
          Origen
          <input name="source" placeholder="Referido, web, evento…" />
        </label>
        <label>
          Valor estimado
          <input name="estimatedValue" type="number" min="0" step="0.01" />
        </label>
      </div>
      {error ? (
        <p className="form-error" role="alert">
          {error}
        </p>
      ) : null}
      <div className="quick-add-actions">
        <ErpButton variant="ghost" type="button" onClick={onCancel}>
          Cancelar
        </ErpButton>
        <ErpButton variant="primary" type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? 'Creando…' : 'Crear lead'}
        </ErpButton>
      </div>
    </form>
  )
}
