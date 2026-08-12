import { useQueries, useQuery } from '@tanstack/react-query'

import {
  apiRequest,
  type AnalyticClassification,
  type AnalyticClassificationValue,
} from '../../api'

export function AnalyticClassificationPicker({
  token,
  valueIds,
  onChange,
}: {
  token: string
  valueIds: string[]
  onChange: (valueIds: string[]) => void
}) {
  const classifications = useQuery({
    queryKey: ['analytic-classifications'],
    queryFn: () => apiRequest<AnalyticClassification[]>(token, '/analytic-classifications'),
  })
  const values = useQueries({
    queries: (classifications.data ?? []).map((classification) => ({
      queryKey: ['analytic-classifications', classification.id, 'values'],
      queryFn: () => apiRequest<AnalyticClassificationValue[]>(
        token,
        `/analytic-classifications/${classification.id}/values`,
      ),
    })),
  })

  if (classifications.isPending) return null
  if (classifications.error) return <p className="form-error" role="alert">No se pudieron cargar las clasificaciones: {classifications.error.message}</p>
  if (!classifications.data?.length) {
    return (
      <fieldset>
        <legend>Clasificaciones analíticas</legend>
        <p className="fine-print">Aún no hay valores configurados. Créelos en Empresa → Clasificaciones para poder elegirlos aquí.</p>
      </fieldset>
    )
  }

  return (
    <fieldset>
      <legend>Clasificaciones analíticas</legend>
      <p className="fine-print">Opcionales. Selecciona un valor ya configurado; no se crea texto libre desde el documento.</p>
      {classifications.data.map((classification, index) => {
        const options = values[index]?.data ?? []
        const selected = valueIds.find((id) => options.some((option) => option.id === id)) ?? ''
        return (
          <label key={classification.id}>
            {classification.name}
            <select
              value={selected}
              onChange={(event) => {
                const withoutClassification = valueIds.filter(
                  (id) => !options.some((option) => option.id === id),
                )
                onChange(event.target.value ? [...withoutClassification, event.target.value] : withoutClassification)
              }}
            >
              <option value="">Sin clasificar</option>
              {options.map((option) => {
                const parent = option.parentId ? options.find((item) => item.id === option.parentId) : undefined
                return <option key={option.id} value={option.id}>{parent ? `${parent.name} / ${option.name}` : option.name}</option>
              })}
            </select>
          </label>
        )
      })}
    </fieldset>
  )
}
