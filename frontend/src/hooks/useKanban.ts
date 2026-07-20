import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, createElement, useEffect } from 'react'
import {
  DndContext,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import {
  SortableContext,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { useShallow } from 'zustand/react/shallow'
import type { Lead, LeadStatus, LeadWithPartyCreate } from '../api'
import { apiRequest, idempotencyKey } from '../api'
import {
  selectActiveFilterCount,
  selectFilteredLeads,
  selectSelectedLead,
  useCrmStore,
} from '../store/crmStore'
import { isQuickAddSingleHop, isValidLeadTransition } from '../store/crmTransitions'

export type BulkMoveOutcome = 'moved' | 'skipped' | 'error'
export type BulkMoveResult = {
  leadId: string
  title: string
  outcome: BulkMoveOutcome
  message?: string
}

function buildOptimisticLead(
  tempId: string,
  status: LeadStatus,
  data: LeadWithPartyCreate
): Lead {
  const now = new Date().toISOString()
  return {
    id: tempId,
    partyId: tempId,
    title: data.title,
    productId: data.productId ?? null,
    party: {
      id: tempId,
      name: data.partyName,
      email: data.partyEmail ?? undefined,
      phone: data.partyPhone ?? undefined,
      address: data.partyAddress ?? undefined,
    },
    product: null,
    owner: null,
    status,
    source: data.source ?? null,
    ownerUserId: null,
    score: data.score ?? 0,
    hotness: data.hotness ?? 'COLD',
    estimatedValue: data.estimatedValue ?? null,
    expectedCloseDate: data.expectedCloseDate ?? null,
    createdAt: now,
    updatedAt: now,
    tenantId: '',
  }
}

/**
 * Hook custom para gestión del Kanban CRM con drag & drop
 *
 * Proporciona:
 * - Estado centralizado con Zustand
 * - Handlers para drag & drop con @dnd-kit
 * - Integración con TanStack Query para API calls
 * - Filtros (básicos y avanzados), selección múltiple y quick-add
 */
export function useKanban({ token }: { token: string }) {
  const queryClient = useQueryClient()
  const {
    leads,
    draggedLeadId,
    searchQuery,
    ownerFilter,
    timeframeFilter,
    scoreMin,
    scoreMax,
    hotnessFilter,
    closeDateFrom,
    closeDateTo,
    selectedLeadIds,
    setLeads,
    startDrag,
    endDrag,
    selectLead,
    updateLead,
    moveLead: moveLeadOptimistic,
    addLeadOptimistic,
    replaceLeadId,
    removeLead,
    toggleLeadSelection,
    selectLeadRange,
    toggleColumnSelection,
    clearSelection,
    setSearchQuery,
    setOwnerFilter,
    setTimeframeFilter,
    setScoreFilter,
    setHotnessFilter,
    setDateRangeFilter,
    clearAdvancedFilters,
    clearFilters,
  } = useCrmStore()

  // Query para obtener leads del servidor
  const leadsQuery = useQuery({
    queryKey: ['crm-leads'],
    queryFn: () => apiRequest<Lead[]>(token, '/crm/leads'),
  })

  // Sincronizar leads del query con el store cuando cambian
  useEffect(() => {
    if (leadsQuery.data) {
      setLeads(leadsQuery.data)
    }
  }, [leadsQuery.data, setLeads])

  // Mutación para mover lead entre etapas
  const moveLeadMutation = useMutation({
    mutationFn: ({
      leadId,
      newStatus,
    }: {
      leadId: string
      newStatus: LeadStatus
    }) =>
      apiRequest<Lead>(token, `/crm/leads/${leadId}/status`, {
        method: 'PUT',
        headers: {
          'Idempotency-Key': idempotencyKey('crm-stage'),
        },
        body: JSON.stringify({ newStatus }),
      }),
    onMutate: async ({ leadId, newStatus }) => {
      // Actualización optimista: actualizar estado local inmediatamente
      moveLeadOptimistic(leadId, newStatus)

      // Cancelar queries en progreso para evitar conflictos
      await queryClient.cancelQueries({ queryKey: ['crm-leads'] })

      // Guardar estado previo para rollback
      const previousLeads = queryClient.getQueryData<Lead[]>(['crm-leads'])

      return { previousLeads }
    },
    onError: (_error, _variables, context) => {
      // Rollback en caso de error
      if (context?.previousLeads) {
        queryClient.setQueryData(['crm-leads'], context.previousLeads)
        setLeads(context.previousLeads)
      }
    },
    onSuccess: (updatedLead) => {
      // Actualizar estado con valor del servidor (source of truth)
      updateLead(updatedLead.id, updatedLead)
    },
  })

  // Handler para cuando termina el drag & drop. Conserva la convención del
  // Sprint 1: solo se puede soltar en etapas activas (WON/LOST se alcanzan
  // desde bulk-move o el detalle, con validación de transición estricta).
  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event

      if (!over) {
        endDrag()
        return
      }

      const leadId = active.id as string
      const newStatus = over.id as LeadStatus

      const lead = leads.find((l) => l.id === leadId)
      if (!lead || lead.status === newStatus) {
        endDrag()
        return
      }

      const activeStages: LeadStatus[] = [
        'NEW',
        'CONTACTED',
        'QUALIFIED',
        'PROPOSAL',
        'NEGOTIATION',
      ]

      if (!activeStages.includes(newStatus)) {
        endDrag()
        return
      }

      moveLeadMutation.mutate({ leadId, newStatus })
      endDrag()
    },
    [leads, endDrag, moveLeadMutation]
  )

  /**
   * Quick-add (Sprint 2): crea un lead con party nuevo (el backend siempre lo
   * crea en NEW) y, si la columna destino es alcanzable en UN salto válido
   * desde NEW (hoy: solo CONTACTED), encadena el PUT de status. No se simulan
   * saltos múltiples: para etapas posteriores el lead queda en NEW y se
   * informa al usuario.
   */
  const createLeadWithPartyMutation = useMutation({
    mutationFn: async ({
      targetStatus,
      data,
      tempId,
    }: {
      targetStatus: LeadStatus
      data: LeadWithPartyCreate
      tempId: string
    }) => {
      const created = await apiRequest<Lead>(token, '/crm/leads/with-party', {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey('crm-quick-add') },
        body: JSON.stringify(data),
      })
      replaceLeadId(tempId, created)
      void queryClient.invalidateQueries({ queryKey: ['crm-leads'] })
      void queryClient.invalidateQueries({ queryKey: ['parties'] })

      if (targetStatus === 'NEW' || !isQuickAddSingleHop(targetStatus)) {
        return { lead: created, stayedInNew: targetStatus !== 'NEW' }
      }

      try {
        const moved = await apiRequest<Lead>(token, `/crm/leads/${created.id}/status`, {
          method: 'PUT',
          headers: { 'Idempotency-Key': idempotencyKey('crm-quick-add-move') },
          body: JSON.stringify({ newStatus: targetStatus }),
        })
        updateLead(moved.id, moved)
        return { lead: moved, stayedInNew: false }
      } catch {
        return { lead: created, stayedInNew: true }
      }
    },
    onMutate: async ({ targetStatus, data, tempId }) => {
      await queryClient.cancelQueries({ queryKey: ['crm-leads'] })
      const placeholderStatus: LeadStatus =
        targetStatus === 'NEW' || isQuickAddSingleHop(targetStatus) ? targetStatus : 'NEW'
      addLeadOptimistic(buildOptimisticLead(tempId, placeholderStatus, data))
    },
    onError: (_error, variables) => {
      removeLead(variables.tempId)
    },
  })

  /**
   * Bulk move (Sprint 2): mueve varios leads a `targetStatus` de forma
   * secuencial. Los leads cuya transición no es válida según la convención
   * del pipeline no se envían a la API: se reportan como "omitidos".
   */
  const bulkMoveMutation = useMutation({
    mutationFn: async ({
      leadIds,
      targetStatus,
      onProgress,
    }: {
      leadIds: string[]
      targetStatus: LeadStatus
      onProgress?: (done: number, total: number) => void
    }) => {
      const results: BulkMoveResult[] = []
      for (let index = 0; index < leadIds.length; index += 1) {
        const leadId = leadIds[index]
        const lead = leads.find((item) => item.id === leadId)

        if (!lead) {
          results.push({ leadId, title: leadId, outcome: 'error', message: 'Lead no encontrado' })
          onProgress?.(index + 1, leadIds.length)
          continue
        }

        if (!isValidLeadTransition(lead.status, targetStatus)) {
          results.push({ leadId, title: lead.title, outcome: 'skipped' })
          onProgress?.(index + 1, leadIds.length)
          continue
        }

        try {
          const updated = await apiRequest<Lead>(token, `/crm/leads/${leadId}/status`, {
            method: 'PUT',
            headers: { 'Idempotency-Key': idempotencyKey('crm-bulk-move') },
            body: JSON.stringify({ newStatus: targetStatus }),
          })
          updateLead(updated.id, updated)
          results.push({ leadId, title: lead.title, outcome: 'moved' })
        } catch (error) {
          results.push({
            leadId,
            title: lead.title,
            outcome: 'error',
            message: error instanceof Error ? error.message : 'Error desconocido',
          })
        }

        onProgress?.(index + 1, leadIds.length)
      }
      void queryClient.invalidateQueries({ queryKey: ['crm-leads'] })
      return results
    },
  })

  // Selectores derivados. `useShallow` es obligatorio en Zustand v5 para
  // selectores que devuelven un array/objeto NUEVO en cada llamada (p.ej.
  // `.filter()`): sin él, `useSyncExternalStore` ve una referencia distinta
  // en cada render y entra en render-loop ("getSnapshot should be cached").
  const filteredLeads = useCrmStore(useShallow(selectFilteredLeads))
  const selectedLead = useCrmStore(useShallow(selectSelectedLead))
  const activeFilterCount = useCrmStore(selectActiveFilterCount)

  // Sensores de @dnd-kit con umbral de distancia: sin `activationConstraint`
  // cualquier movimiento del puntero durante el mousedown inicia un drag y se
  // come el "click" de los botones dentro de la card. 8px distingue un click
  // de un drag real.
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } })
  )

  // Context providers para @dnd-kit
  const kanbanProviders = useCallback(
    ({ children }: { children: React.ReactNode }) =>
      createElement(
        DndContext,
        { onDragEnd: handleDragEnd, sensors },
        createElement(SortableContext, {
          items: filteredLeads.map((lead) => lead.id),
          strategy: verticalListSortingStrategy,
          children,
        })
      ),
    [filteredLeads, handleDragEnd, sensors]
  )

  return {
    // Estado
    leads,
    filteredLeads,
    selectedLead,
    draggedLeadId,
    searchQuery,
    ownerFilter,
    timeframeFilter,
    scoreMin,
    scoreMax,
    hotnessFilter,
    closeDateFrom,
    closeDateTo,
    activeFilterCount,
    selectedLeadIds,

    // Queries y Mutations
    leadsQuery,
    moveLeadMutation,
    createLeadWithPartyMutation,
    bulkMoveMutation,

    // Acciones
    selectLead,
    setSearchQuery,
    setOwnerFilter,
    setTimeframeFilter,
    setScoreFilter,
    setHotnessFilter,
    setDateRangeFilter,
    clearAdvancedFilters,
    clearFilters,
    toggleLeadSelection,
    selectLeadRange,
    toggleColumnSelection,
    clearSelection,

    // Drag & Drop
    handleDragStart: startDrag,
    handleDragEnd,
    kanbanProviders,
  }
}

/**
 * Tipos para TypeScript
 */
export type UseKanbanReturn = ReturnType<typeof useKanban>
