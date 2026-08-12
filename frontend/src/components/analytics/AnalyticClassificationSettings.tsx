import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'

import {
  apiRequest,
  idempotencyKey,
  type AnalyticClassification,
  type AnalyticClassificationValue,
} from '../../api'
import { ErpButton, ErpEmptyState, ErpPanel } from '../erp'

export function AnalyticClassificationSettings({ token }: { token: string }) {
  const queryClient = useQueryClient()
  const [selectedId, setSelectedId] = useState('')
  const [classificationFormError, setClassificationFormError] = useState('')
  const classifications = useQuery({
    queryKey: ['analytic-classifications'],
    queryFn: () => apiRequest<AnalyticClassification[]>(token, '/analytic-classifications'),
  })
  const values = useQueries({
    queries: (classifications.data ?? []).map((item) => ({
      queryKey: ['analytic-classifications', item.id, 'values'],
      queryFn: () => apiRequest<AnalyticClassificationValue[]>(token, `/analytic-classifications/${item.id}/values`),
    })),
  })
  const createClassification = useMutation({
    mutationFn: (body: object) => apiRequest<AnalyticClassification>(token, '/analytic-classifications', {
      method: 'POST', headers: { 'Idempotency-Key': idempotencyKey('web-analytic-classification') }, body: JSON.stringify(body),
    }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['analytic-classifications'] }),
  })
  const createValue = useMutation({
    mutationFn: ({ classificationId, body }: { classificationId: string; body: object }) => apiRequest<AnalyticClassificationValue>(token, `/analytic-classifications/${classificationId}/values`, {
      method: 'POST', headers: { 'Idempotency-Key': idempotencyKey('web-analytic-value') }, body: JSON.stringify(body),
    }),
    onSuccess: (_, variables) => void queryClient.invalidateQueries({ queryKey: ['analytic-classifications', variables.classificationId, 'values'] }),
  })
  const selected = (classifications.data ?? []).find((item) => item.id === selectedId) ?? classifications.data?.[0]
  const selectedValues = selected ? values[(classifications.data ?? []).findIndex((item) => item.id === selected.id)]?.data ?? [] : []

  function submitClassification(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const code = String(form.get('code')).trim().toUpperCase().replace(/[^A-Z0-9_]/g, '_')
    if (!/^[A-Z][A-Z0-9_]{1,39}$/.test(code)) {
      setClassificationFormError('El código debe empezar con una letra y usar solo letras, números o guion bajo.')
      return
    }
    if (classifications.data?.some((item) => item.code === code)) {
      setClassificationFormError(`Ya existe una clasificación con el código ${code}.`)
      return
    }
    setClassificationFormError('')
    createClassification.mutate({
      code,
      name: String(form.get('name')).trim(),
      maxDepth: Number(form.get('maxDepth')),
    })
  }
  function submitValue(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!selected) return
    const form = new FormData(event.currentTarget)
    createValue.mutate({
      classificationId: selected.id,
      body: {
        code: String(form.get('code')).trim().toUpperCase().replace(/[^A-Z0-9_-]/g, '_'),
        name: String(form.get('name')).trim(),
        parentId: String(form.get('parentId') || '') || null,
      },
    })
  }

  return <>
    <ErpPanel title="Clasificaciones analíticas">
      <p className="fine-print">Define aquí franquicias, sucursales, proyectos, centros de costo u otros catálogos. Cada tenant decide sus propios niveles; ningún nivel es obligatorio en los documentos.</p>
      <form className="company-profile-editor" onSubmit={submitClassification}>
        <label>Nombre<input name="name" required minLength={2} placeholder="Ej. Franquicia" /></label>
        <label>Código<input name="code" required minLength={2} maxLength={40} pattern="[A-Za-z][A-Za-z0-9_]{1,39}" title="Empieza con una letra y usa solo letras, números o guion bajo" placeholder="FRANQUICIA" /></label>
        <label>Niveles máximos<select name="maxDepth" defaultValue="1"><option value="1">1 nivel</option><option value="2">2 niveles</option><option value="3">3 niveles</option></select></label>
        {classificationFormError || createClassification.error ? <p className="form-error" role="alert">{classificationFormError || createClassification.error?.message}</p> : null}
        <ErpButton variant="primary" type="submit" disabled={createClassification.isPending}>{createClassification.isPending ? 'Guardando…' : 'Crear clasificación'}</ErpButton>
      </form>
    </ErpPanel>
    <ErpPanel title="Valores controlados" count={classifications.data?.length ?? 0}>
      {classifications.isPending ? <p>Cargando…</p> : null}
      {classifications.error ? <p className="form-error" role="alert">{classifications.error.message}</p> : null}
      {!classifications.isPending && !classifications.error && !classifications.data?.length ? <ErpEmptyState title="Sin clasificaciones" description="Crea primero un catálogo para usarlo en Facturas y Compras." /> : null}
      {classifications.data?.length ? <>
        <label>Clasificación<select value={selected?.id ?? ''} onChange={(event) => setSelectedId(event.target.value)}>{classifications.data.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.maxDepth} nivel(es)</option>)}</select></label>
        <ul className="establishment-list">{selectedValues.map((item) => <li key={item.id}><span>{item.code}</span><div><strong>{item.name}</strong><small>{item.parentId ? 'Subnivel configurado' : 'Nivel principal'}</small></div></li>)}</ul>
        <form className="company-profile-editor" onSubmit={submitValue}>
          <label>Nombre<input name="name" required minLength={2} /></label>
          <label>Código<input name="code" required minLength={1} /></label>
          <label>Depende de<select name="parentId"><option value="">Sin padre: primer nivel</option>{selectedValues.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          {createValue.error ? <p className="form-error" role="alert">{createValue.error.message}</p> : null}
          <ErpButton variant="secondary" type="submit" disabled={createValue.isPending}>{createValue.isPending ? 'Guardando…' : 'Agregar valor'}</ErpButton>
        </form>
      </> : null}
    </ErpPanel>
  </>
}
