import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { DndContext, PointerSensor, useDraggable, useDroppable, useSensor, useSensors } from '@dnd-kit/core'
import { CSS } from '@dnd-kit/utilities'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { GripVertical } from 'lucide-react'

import { apiRequest, idempotencyKey, type Payable, type PurchaseDocument } from '../../api'
import { AnalyticClassificationPicker } from '../analytics/AnalyticClassificationPicker'
import { ErpButton, ErpPanel, ErpStatusBadge } from '../erp'
import { ErpModal } from '../erp/ErpModal'

type Classification = Payable['taxClassification']
type Rule = {
  id: string
  supplierRuc: string
  taxClassification: Exclude<Classification, 'DEDUCTIBLE_PENDING_REVIEW'>
  active: boolean
}
type Change = {
  ids: string[]
  classification?: Classification
  internalClassification?: Exclude<Payable['internalClassification'], 'PENDING_REVIEW'>
  valueIds?: string[]
  initialValueIds?: string[]
  reason?: string
  key: string
}

const lanes = [
  { id: 'DEDUCTIBLE_PENDING_REVIEW', label: 'Por revisar', action: 'Dejar por revisar' },
  { id: 'DEDUCTIBLE_CONFIRMED', label: 'Deducibles', action: 'Marcar deducible' },
  { id: 'NON_DEDUCTIBLE', label: 'No deducibles', action: 'Marcar no deducible' },
] as const

const formatter = new Intl.NumberFormat('es-EC', { style: 'currency', currency: 'USD' })
const pageSize = 24

function Lane({ id, label, count, children }: {
  id: Classification
  label: string
  count: number
  children: ReactNode
}) {
  const { isOver, setNodeRef } = useDroppable({ id })
  return <section ref={setNodeRef} aria-label={label} className={`purchase-board-lane${isOver ? ' is-over' : ''}`}>
    <h3>{label} <span>{count}</span></h3>
    {children}
  </section>
}

function Card({ item, selected, selectionDisabled, canEdit, onSelect, onMove, onTags }: {
  item: Payable
  selected: boolean
  selectionDisabled: boolean
  canEdit: boolean
  onSelect: () => void
  onMove: (target: Classification) => void
  onTags: () => void
}) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: item.id,
    disabled: !canEdit,
  })
  const title = item.documentNumber ?? item.description
  return <article
    ref={setNodeRef}
    aria-label={title}
    className={`purchase-board-card${isDragging ? ' is-dragging' : ''}`}
    style={{ transform: CSS.Translate.toString(transform) }}
  >
    <div className="purchase-board-card-title">
      {canEdit ? <>
        <input type="checkbox" checked={selected} disabled={selectionDisabled} onChange={onSelect} aria-label={`Seleccionar compra ${title}`} />
        <button type="button" className="purchase-board-grip" {...attributes} {...listeners} tabIndex={-1} aria-label={`Arrastrar compra ${title}`}><GripVertical size={18} aria-hidden="true" /></button>
      </> : null}
      <strong>{item.supplierName ?? item.description}</strong>
    </div>
    <p>{title} · {item.issueDate}</p>
    <p><strong>{formatter.format(Number(item.total))}</strong> · {item.evidenceStatus === 'FISCAL_XML' ? 'XML confirmado' : 'Sin XML confirmado'}</p>
    <p>{item.internalClassification === 'REAL' ? 'Gasto real' : item.internalClassification === 'DECLARATION_ONLY' ? 'Solo tributario' : 'Control interno pendiente'}</p>
    {item.analyticAssignments?.length ? <ul className="purchase-board-tags">
      {item.analyticAssignments.map((assignment) => <li key={assignment.valueId}>
        {assignment.path.map((part) => part.name).join(' / ')}
      </li>)}
    </ul> : null}
    {canEdit ? <div className="purchase-board-actions">
      {lanes.filter((lane) => lane.id !== item.taxClassification).map((lane) =>
        <ErpButton key={lane.id} variant="ghost" onClick={() => onMove(lane.id)}>{lane.action}</ErpButton>
      )}
      <ErpButton variant="ghost" onClick={onTags}>Etiquetas y control</ErpButton>
    </div> : null}
  </article>
}

function RuleEditor({ token, tenantId, rules, documents, automationEnabled, onClose }: {
  token: string
  tenantId: string
  rules: Rule[]
  documents: PurchaseDocument[]
  automationEnabled: boolean
  onClose: () => void
}) {
  const [ruc, setRuc] = useState('')
  const [classification, setClassification] = useState<Rule['taxClassification']>('DEDUCTIBLE_CONFIRMED')
  const [active, setActive] = useState(true)
  const [confirmed, setConfirmed] = useState(false)
  const queryClient = useQueryClient()
  const save = useMutation({
    mutationFn: ({ supplierRuc, taxClassification, enabled }: {
      supplierRuc: string
      taxClassification: Rule['taxClassification']
      enabled: boolean
    }) => apiRequest<Rule>(token, `/purchase-tax-rules/${supplierRuc}`, {
      method: 'PUT',
      headers: { 'Idempotency-Key': idempotencyKey('web-purchase-tax-rule') },
      body: JSON.stringify({ taxClassification, active: enabled }),
    }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['purchase-tax-rules', tenantId] })
      onClose()
    },
  })
  const suppliers = new Map<string, string>()
  for (const document of documents) {
    if (document.supplierIdentification && document.supplierName) {
      suppliers.set(document.supplierIdentification, document.supplierName)
    }
  }

  function chooseSupplier(supplierRuc: string) {
    const existing = rules.find((rule) => rule.supplierRuc === supplierRuc)
    setRuc(supplierRuc)
    setClassification(existing?.taxClassification ?? 'DEDUCTIBLE_CONFIRMED')
    setActive(existing?.active ?? true)
    setConfirmed(false)
  }

  return <ErpModal title="Reglas por proveedor" size="md" onClose={() => { if (!save.isPending) onClose() }}>
    {!automationEnabled ? <p className="fine-print">Las escrituras automáticas están desactivadas. IAERP comprueba este permiso al recuperar cada XML.</p> : null}
    {rules.length ? <ul className="purchase-board-rule-list">
      {rules.map((rule) => <li key={rule.id}>
        <ErpButton variant="ghost" onClick={() => chooseSupplier(rule.supplierRuc)}>{suppliers.get(rule.supplierRuc) ?? rule.supplierRuc}</ErpButton>
        <ErpStatusBadge tone={rule.active ? 'success' : 'neutral'}>{rule.active ? 'Activa' : 'Inactiva'}</ErpStatusBadge>
      </li>)}
    </ul> : null}
    <form className="purchase-rule-form" onSubmit={(event) => {
      event.preventDefault()
      if ((!active || confirmed) && !save.isPending) save.mutate({ supplierRuc: ruc, taxClassification: classification, enabled: active })
    }}>
      <label>RUC del proveedor
        <input value={ruc} onChange={(event) => chooseSupplier(event.target.value)} inputMode="numeric" list="purchase-rule-suppliers" pattern="[0-9]{13}" required />
      </label>
      <datalist id="purchase-rule-suppliers">
        {Array.from(suppliers, ([supplierRuc, name]) => <option key={supplierRuc} value={supplierRuc}>{name}</option>)}
      </datalist>
      <label>Clasificación para renta
        <select value={classification} onChange={(event) => {
          setClassification(event.target.value as Rule['taxClassification'])
          setConfirmed(false)
        }}>
          <option value="DEDUCTIBLE_CONFIRMED">Deducible</option>
          <option value="NON_DEDUCTIBLE">No deducible</option>
        </select>
      </label>
      <label className="purchase-board-check"><input type="checkbox" checked={active} onChange={(event) => setActive(event.target.checked)} /> Activar regla</label>
      {active ? <label className="purchase-board-check">
        <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} required />
        Confirmo que esta clasificación se puede aplicar a las próximas facturas con XML recuperado de este proveedor.
      </label> : null}
      {save.error ? <p className="form-error" role="alert">{save.error.message}</p> : null}
      <div className="erp-form-actions">
        <ErpButton variant="secondary" onClick={onClose} disabled={save.isPending}>Cancelar</ErpButton>
        <ErpButton variant="primary" type="submit" disabled={save.isPending || (active && !confirmed)}>Guardar</ErpButton>
      </div>
    </form>
  </ErpModal>
}

export function PurchaseClassificationBoard({ token, tenantId, items, documents, canEdit, canManageRules, automationEnabled }: {
  token: string
  tenantId: string
  items: Payable[]
  documents: PurchaseDocument[]
  canEdit: boolean
  canManageRules: boolean
  automationEnabled: boolean
}) {
  const queryClient = useQueryClient()
  const [selected, setSelected] = useState<string[]>([])
  const [limits, setLimits] = useState<Partial<Record<Classification, number>>>({})
  const [change, setChange] = useState<Change | null>(null)
  const [notice, setNotice] = useState('')
  const noticeRef = useRef<HTMLParagraphElement>(null)
  const [editingRules, setEditingRules] = useState(false)
  useEffect(() => { if (notice) noticeRef.current?.focus() }, [notice])
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }))
  const rulesQuery = useQuery({
    queryKey: ['purchase-tax-rules', tenantId],
    queryFn: () => apiRequest<Rule[]>(token, '/purchase-tax-rules'),
    enabled: canManageRules && editingRules,
  })
  const update = useMutation({
    mutationFn: (change: Change) => apiRequest<{
      updatedCount: number
      items: Array<{ status: string; fiscalUseProtected: boolean; detail: string }>
    }>(token, '/payables/classifications/bulk', {
      method: 'PUT',
      headers: { 'Idempotency-Key': change.key },
      body: JSON.stringify({
        payableIds: change.ids,
        taxClassification: change.classification,
        internalClassification: change.internalClassification,
        reason: change.reason?.trim(),
        analyticChange: change.valueIds ? 'REPLACE' : 'KEEP_EXISTING',
        analyticValueIds: change.valueIds,
      }),
    }),
    onSuccess: async (result) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['payables'] }),
        queryClient.invalidateQueries({ queryKey: ['tax', 'dashboard'] }),
      ])
      setSelected([])
      setChange(null)
      const failures = result.items.filter((item) => item.status === 'FAILED' || item.fiscalUseProtected)
      const details = [...new Set(failures.map((item) => item.detail))].join(' · ')
      const saved = result.updatedCount - result.items.filter((item) => item.fiscalUseProtected).length
      const summary = saved === 1 ? '1 compra guardada.' : `${saved} compras guardadas.`
      setNotice(details ? `${summary} ${details}` : summary)
    },
  })
  const available = items.filter((item) => item.status !== 'VOIDED')
  const visibleSelection = selected.filter((id) => available.some((item) => item.id === id))

  function openChange(ids: string[], fields: Pick<Change, 'classification' | 'initialValueIds'>) {
    if (!ids.length || update.isPending) return
    update.reset()
    setNotice('')
    setChange({ ids, ...fields, key: idempotencyKey('web-purchase-board') })
  }

  function startMove(ids: string[], classification: Classification) {
    const moving = ids.filter((id) => available.some((item) =>
      item.id === id && item.taxClassification !== classification
    ))
    openChange(moving, { classification })
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!change || update.isPending) return
    if (change.classification && (change.reason ?? '').trim().length < 3) return
    if (!change.classification && !change.valueIds && !change.internalClassification) return
    update.mutate(change)
  }

  const target = lanes.find((lane) => lane.id === change?.classification)
  return <ErpPanel title="Clasificación de compras" actions={canManageRules ? <ErpButton variant="secondary" onClick={() => setEditingRules(true)}>Reglas por proveedor</ErpButton> : undefined}>
    {notice ? <p ref={noticeRef} tabIndex={-1} role="status" className="purchase-review-status">{notice}</p> : null}
    {visibleSelection.length ? <div className="purchase-board-actions" aria-label="Acciones para compras seleccionadas">
      <strong>{visibleSelection.length} seleccionadas</strong>
      {lanes.map((lane) => <ErpButton key={lane.id} variant="secondary" onClick={() => startMove(visibleSelection, lane.id)}>{lane.action}</ErpButton>)}
      <ErpButton variant="secondary" onClick={() => openChange(visibleSelection, {})}>Etiquetas y control</ErpButton>
      <ErpButton variant="ghost" onClick={() => setSelected([])}>Cancelar selección</ErpButton>
    </div> : null}
    <DndContext sensors={sensors} onDragEnd={({ active, over }) => {
      const lane = lanes.find((candidate) => candidate.id === over?.id)
      if (!lane || !canEdit || typeof active.id !== 'string') return
      startMove(visibleSelection.includes(active.id) ? visibleSelection : [active.id], lane.id)
    }}>
      <div className="purchase-board">
        {lanes.map((lane) => {
          const cards = available.filter((item) => item.taxClassification === lane.id)
          const limit = limits[lane.id] ?? pageSize
          return <Lane key={lane.id} id={lane.id} label={lane.label} count={cards.length}>
            {cards.slice(0, limit).map((item) => <Card
              key={item.id}
              item={item}
              canEdit={canEdit}
              selected={visibleSelection.includes(item.id)}
              selectionDisabled={visibleSelection.length >= 100 && !visibleSelection.includes(item.id)}
              onSelect={() => setSelected((ids) => visibleSelection.includes(item.id)
                ? ids.filter((id) => id !== item.id)
                : [...visibleSelection, item.id])}
              onMove={(destination) => startMove([item.id], destination)}
              onTags={() => openChange([item.id], { initialValueIds: (item.analyticAssignments ?? []).map((assignment) => assignment.valueId) })}
            />)}
            {cards.length > limit ? <ErpButton variant="ghost" onClick={() => setLimits({ ...limits, [lane.id]: limit + pageSize })}>Ver más</ErpButton> : null}
          </Lane>
        })}
      </div>
    </DndContext>
    {change ? <ErpModal title={target ? target.action : 'Etiquetas y control'} size="sm" onClose={() => { if (!update.isPending) setChange(null) }}>
      <form className="purchase-rule-form" onSubmit={submit}>
        {target ? <>
          <p>{change.ids.length === 1 ? 'Vas a cambiar la clasificación de una compra.' : `Vas a cambiar la clasificación de ${change.ids.length} compras.`}</p>
          <label>Motivo<input value={change.reason ?? ''} onChange={(event) => setChange({ ...change, reason: event.target.value, key: idempotencyKey('web-purchase-board') })} required minLength={3} maxLength={300} /></label>
        </> : <>
          {change.ids.length > 1 ? <p>Si eliges etiquetas, se reemplazarán en las {change.ids.length} compras seleccionadas.</p> : null}
          <label>Control interno
            <select value={change.internalClassification ?? ''} onChange={(event) => setChange({
              ...change,
              internalClassification: (event.target.value || undefined) as Change['internalClassification'],
              key: idempotencyKey('web-purchase-board'),
            })}>
              <option value="">Conservar control actual</option>
              <option value="REAL">Gasto real</option>
              <option value="DECLARATION_ONLY">Solo tributario</option>
            </select>
          </label>
          <AnalyticClassificationPicker token={token} valueIds={change.valueIds ?? change.initialValueIds ?? []} onChange={(valueIds) => setChange({ ...change, valueIds, key: idempotencyKey('web-purchase-board') })} />
        </>}
        {update.error ? <p role="alert" className="form-error">{update.error.message}</p> : null}
        <div className="erp-form-actions">
          <ErpButton variant="secondary" onClick={() => setChange(null)} disabled={update.isPending}>Cancelar</ErpButton>
          <ErpButton variant="primary" type="submit" disabled={update.isPending || (target ? (change.reason ?? '').trim().length < 3 : !change.valueIds && !change.internalClassification)}>Guardar</ErpButton>
        </div>
      </form>
    </ErpModal> : null}
    {editingRules ? rulesQuery.data ? <RuleEditor token={token} tenantId={tenantId} rules={rulesQuery.data} documents={documents} automationEnabled={automationEnabled} onClose={() => setEditingRules(false)} /> :
      <ErpModal title="Reglas por proveedor" size="sm" onClose={() => setEditingRules(false)}>
        {rulesQuery.error ? <p className="form-error" role="alert">{rulesQuery.error.message}</p> : <p role="status">Cargando reglas…</p>}
      </ErpModal> : null}
  </ErpPanel>
}
