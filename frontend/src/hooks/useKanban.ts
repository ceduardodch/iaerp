import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, createElement, useEffect } from 'react'
import { DndContext, type DragEndEvent } from '@dnd-kit/core'
import {
  SortableContext,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import type { Lead, LeadStatus } from '../api'
import { apiRequest, idempotencyKey } from '../api'
import {
  selectFilteredLeads,
  selectLeadsByStage,
  selectSelectedLead,
  useCrmStore,
} from '../store/crmStore'

/**
 * Hook custom para gestión del Kanban CRM con drag & drop
 *
 * Proporciona:
 * - Estado centralizado con Zustand
 * - Handlers para drag & drop con @dnd-kit
 * - Integración con TanStack Query para API calls
 * - Filtros y selección de leads
 */
export function useKanban({ token }: { token: string }) {
  const queryClient = useQueryClient()
  const {
    leads,
    draggedLeadId,
    searchQuery,
    ownerFilter,
    timeframeFilter,
    setLeads,
    startDrag,
    endDrag,
    selectLead,
    updateLead,
    moveLead: moveLeadOptimistic,
    setSearchQuery,
    setOwnerFilter,
    setTimeframeFilter,
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
      }
    },
    onSuccess: (updatedLead) => {
      // Actualizar estado con valor del servidor (source of truth)
      updateLead(updatedLead.id, updatedLead)
    },
  })

  // Handler para cuando termina el drag & drop
  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event

      if (!over) {
        endDrag()
        return
      }

      const leadId = active.id as string
      const newStatus = over.id as LeadStatus

      // Verificar que sea un movimiento válido
      const lead = leads.find((l) => l.id === leadId)
      if (!lead || lead.status === newStatus) {
        endDrag()
        return
      }

      // Validar etapas activas (no se puede mover a WON/LOST desde otras etapas)
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

      // Ejecutar mutación para mover lead
      moveLeadMutation.mutate({ leadId, newStatus })
      endDrag()
    },
    [leads, endDrag, moveLeadMutation]
  )

  // Selectores derivados
  const filteredLeads = useCrmStore(selectFilteredLeads)
  const leadsByStage = useCrmStore(selectLeadsByStage)
  const selectedLead = useCrmStore(selectSelectedLead)

  // Context providers para @dnd-kit
  const kanbanProviders = useCallback(
    ({ children }: { children: React.ReactNode }) =>
      createElement(
        DndContext,
        { onDragEnd: handleDragEnd },
        createElement(SortableContext, {
          items: filteredLeads.map((lead) => lead.id),
          strategy: verticalListSortingStrategy,
          children,
        })
      ),
    [filteredLeads, handleDragEnd]
  )

  return {
    // Estado
    leads,
    filteredLeads,
    leadsByStage,
    selectedLead,
    draggedLeadId,
    searchQuery,
    ownerFilter,
    timeframeFilter,

    // Queries y Mutations
    leadsQuery,
    moveLeadMutation,

    // Acciones
    selectLead,
    setSearchQuery,
    setOwnerFilter,
    setTimeframeFilter,
    clearFilters,

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
