import { useMutation, useQueryClient } from '@tanstack/react-query'
import { type FormEvent } from 'react'
import {
  apiRequest,
  idempotencyKey,
  type Party,
} from '../../api'
import { FormGrid, FormProgress, FormSection } from './index'

type PartyFormProps = {
  token: string
  party?: Party
  onCreated?: () => void
  onUpdated?: () => void
  onCancel: () => void
}

export function PartyFormVertical({
  token,
  party,
  onCreated,
  onUpdated,
  onCancel,
}: PartyFormProps) {
  const queryClient = useQueryClient()
  const isEditing = Boolean(party)

  const createParty = useMutation({
    mutationFn: (data: {
      id?: string
      name: FormDataEntryValue | null
      identificationType: FormDataEntryValue | null
      identificationNumber: FormDataEntryValue | null
      role: FormDataEntryValue | null
      email: FormDataEntryValue | null
      phone: FormDataEntryValue | null
      address: FormDataEntryValue | null
      paymentTermsDays: FormDataEntryValue | null
    }) =>
      apiRequest<Party>(token, data.id ? `/parties/${data.id}` : '/parties', {
        method: data.id ? 'PUT' : 'POST',
        headers: { 'Idempotency-Key': idempotencyKey('web-party') },
        body: JSON.stringify({
          name: data.name,
          identificationType: data.identificationType,
          identificationNumber: data.identificationNumber,
          roles: [data.role],
          email: data.email || null,
          phone: data.phone || null,
          address: data.address || null,
          paymentTermsDays: data.paymentTermsDays === '' ? null : Number(data.paymentTermsDays),
        }),
      }),
    onSuccess: () => {
      if (isEditing && onUpdated) {
        onUpdated()
      } else if (!isEditing && onCreated) {
        onCreated()
      }
      return queryClient.invalidateQueries({ queryKey: ['parties'] })
    },
  })

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const data = new FormData(form)
    createParty.mutate({
      id: party?.id,
      name: data.get('name'),
      identificationType: data.get('identificationType'),
      identificationNumber: data.get('identificationNumber'),
      role: data.get('role'),
      email: data.get('email'),
      phone: data.get('phone'),
      address: data.get('address'),
      paymentTermsDays: data.get('paymentTermsDays'),
    })
  }

  const steps: Array<{ title: string; status: 'completed' | 'current' | 'pending' }> = [
    { title: 'Información básica', status: 'current' },
    { title: 'Datos tributarios', status: 'pending' },
    { title: 'Contacto', status: 'pending' },
  ]

  return (
    <>
      <FormProgress steps={steps} />
      <form onSubmit={submit}>
        <FormSection
          title="Información básica"
          description="Nombre y rol del contacto"
          defaultExpanded={true}
        >
          <label>
            Nombre o razón social
            <input name="name" defaultValue={party?.name} required />
          </label>
          <label>
            Rol
            <select name="role" defaultValue={party?.roles[0] ?? 'CUSTOMER'} required>
              <option value="CUSTOMER">Cliente</option>
              <option value="SUPPLIER">Proveedor</option>
            </select>
          </label>
        </FormSection>

        <FormSection
          title="Datos tributarios"
          description="Identificación fiscal"
          defaultExpanded={true}
        >
          <FormGrid columns={2}>
            <label>
              Tipo
              <select name="identificationType" defaultValue={party?.identificationType ?? 'RUC'} required>
                <option>RUC</option>
                <option>CEDULA</option>
                <option>PASSPORT</option>
                <option>FINAL_CONSUMER</option>
              </select>
            </label>
            <label>
              Número
              <input name="identificationNumber" defaultValue={party?.identificationNumber} required />
            </label>
          </FormGrid>
          <label style={{ gridColumn: '1 / -1' }}>
            Condición de pago predeterminada
            <select name="paymentTermsDays" defaultValue={party?.paymentTermsDays ?? ''}>
              <option value="">Usar valor de la empresa</option>
              <option value="0">Contado</option>
              <option value="15">15 días</option>
              <option value="30">30 días</option>
              <option value="45">45 días</option>
              <option value="60">60 días</option>
              <option value="90">90 días</option>
            </select>
          </label>
        </FormSection>

        <FormSection
          title="Contacto"
          description="Información de comunicación"
          defaultExpanded={true}
        >
          <FormGrid columns={2}>
            <label>
              Correo
              <input name="email" type="email" defaultValue={party?.email ?? ''} />
            </label>
            <label>
              Teléfono
              <input name="phone" type="tel" defaultValue={party?.phone ?? ''} />
            </label>
          </FormGrid>
          <label>
            Dirección
            <textarea name="address" rows={3} defaultValue={party?.address ?? ''} />
          </label>
        </FormSection>

        <div className="erp-form-actions">
          <button type="button" className="erp-button erp-button-secondary" onClick={onCancel}>
            Cancelar
          </button>
          <button type="submit" className="erp-button erp-button-primary" disabled={createParty.isPending}>
            {createParty.isPending ? 'Guardando…' : isEditing ? 'Actualizar' : 'Crear'}
          </button>
        </div>
      </form>
    </>
  )
}
