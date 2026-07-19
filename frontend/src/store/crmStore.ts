import { create } from 'zustand'
import type { Lead, LeadStatus } from '../api'

/**
 * Estado del store CRM
 */
interface CrmState {
  /** Lista de leads en el pipeline */
  leads: Lead[]
  /** Lead actualmente siendo arrastrado */
  draggedLeadId: string | null
  /** ID del lead actualmente seleccionado/abierto */
  selectedLeadId: string | null
  /** Filtro de búsqueda actual */
  searchQuery: string
  /** Filtro de owner actual */
  ownerFilter: string | null
  /** Filtro de timeframe actual */
  timeframeFilter: 'all' | 'today' | 'week' | 'month'
}

/**
 * Acciones del store CRM
 */
interface CrmActions {
  /** Actualizar la lista de leads */
  setLeads: (leads: Lead[]) => void
  /** Iniciar drag de un lead */
  startDrag: (leadId: string) => void
  /** Finalizar drag (limpiar estado) */
  endDrag: () => void
  /** Seleccionar un lead para ver detalle */
  selectLead: (leadId: string | null) => void
  /** Actualizar un lead específico (después de API update) */
  updateLead: (leadId: string, updates: Partial<Lead>) => void
  /** Mover un lead a una nueva etapa */
  moveLead: (leadId: string, newStatus: LeadStatus) => void
  /** Actualizar filtro de búsqueda */
  setSearchQuery: (query: string) => void
  /** Actualizar filtro de owner */
  setOwnerFilter: (ownerId: string | null) => void
  /** Actualizar filtro de timeframe */
  setTimeframeFilter: (filter: 'all' | 'today' | 'week' | 'month') => void
  /** Limpiar todos los filtros */
  clearFilters: () => void
}

/**
 * Store Zustand para estado del CRM
 *
 * Centraliza el estado de:
 * - Leads del pipeline
 * - Operaciones de drag & drop
 * - Filtros de búsqueda y selección
 * - Lead seleccionado para detalle
 */
export const useCrmStore = create<CrmState & CrmActions>((set) => ({
  // Estado inicial
  leads: [],
  draggedLeadId: null,
  selectedLeadId: null,
  searchQuery: '',
  ownerFilter: null,
  timeframeFilter: 'all',

  // Acciones
  setLeads: (leads) => set({ leads }),

  startDrag: (leadId) => set({ draggedLeadId: leadId }),

  endDrag: () => set({ draggedLeadId: null }),

  selectLead: (leadId) => set({ selectedLeadId: leadId }),

  updateLead: (leadId, updates) =>
    set((state) => ({
      leads: state.leads.map((lead) =>
        lead.id === leadId ? { ...lead, ...updates } : lead
      ),
    })),

  moveLead: (leadId, newStatus) =>
    set((state) => ({
      leads: state.leads.map((lead) =>
        lead.id === leadId ? { ...lead, status: newStatus } : lead
      ),
    })),

  setSearchQuery: (query) => set({ searchQuery: query }),

  setOwnerFilter: (ownerId) => set({ ownerFilter: ownerId }),

  setTimeframeFilter: (filter) => set({ timeframeFilter: filter }),

  clearFilters: () =>
    set({
      searchQuery: '',
      ownerFilter: null,
      timeframeFilter: 'all',
    }),
}))

/**
 * Selectores derivados útiles
 */

/** Leads filtrados por búsqueda, owner y timeframe */
export const selectFilteredLeads = (state: CrmState & CrmActions) => {
  let filtered = state.leads

  // Filtro de búsqueda
  if (state.searchQuery) {
    const normalizedQuery = state.searchQuery.trim().toLocaleLowerCase('es')
    filtered = filtered.filter(
      (lead) =>
        lead.title.toLocaleLowerCase('es').includes(normalizedQuery) ||
        lead.party.name.toLocaleLowerCase('es').includes(normalizedQuery) ||
        lead.product?.name?.toLocaleLowerCase('es').includes(normalizedQuery)
    )
  }

  // Filtro de owner
  if (state.ownerFilter) {
    filtered = filtered.filter((lead) => lead.owner?.id === state.ownerFilter)
  }

  // Filtro de timeframe (por fecha de creación)
  if (state.timeframeFilter !== 'all') {
    const now = new Date()
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
    const weekAgo = new Date(today.getTime() - 7 * 24 * 60 * 60 * 1000)
    const monthAgo = new Date(today.getTime() - 30 * 24 * 60 * 60 * 1000)

    filtered = filtered.filter((lead) => {
      const createdAt = new Date(lead.createdAt)
      switch (state.timeframeFilter) {
        case 'today':
          return createdAt >= today
        case 'week':
          return createdAt >= weekAgo
        case 'month':
          return createdAt >= monthAgo
        default:
          return true
      }
    })
  }

  return filtered
}

/** Lead actualmente seleccionado */
export const selectSelectedLead = (state: CrmState & CrmActions) => {
  return state.leads.find((lead) => lead.id === state.selectedLeadId) ?? null
}

/** Leads agrupados por etapa del pipeline */
export const selectLeadsByStage = (state: CrmState & CrmActions) => {
  const grouped = new Map<LeadStatus, Lead[]>()
  const stages: LeadStatus[] = [
    'NEW',
    'CONTACTED',
    'QUALIFIED',
    'PROPOSAL',
    'NEGOTIATION',
    'WON',
    'LOST',
  ]

  for (const stage of stages) {
    grouped.set(
      stage,
      state.leads.filter((lead) => lead.status === stage)
    )
  }

  return grouped
}
