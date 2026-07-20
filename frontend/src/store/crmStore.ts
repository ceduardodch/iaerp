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
  /** Selección múltiple para bulk operations */
  selectedLeadIds: Set<string>
  /** Filtro de búsqueda actual */
  searchQuery: string
  /** Filtro de owner actual */
  ownerFilter: string | null
  /** Filtro de timeframe actual */
  timeframeFilter: 'all' | 'today' | 'week' | 'month'
  /** Filtros avanzados (Sprint 2): score, temperatura y cierre esperado */
  scoreMin: number
  scoreMax: number
  hotnessFilter: Set<'COLD' | 'WARM' | 'HOT'>
  closeDateFrom: string | null
  closeDateTo: string | null
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
  /** Insertar un lead optimista (quick-add) antes de la respuesta del API */
  addLeadOptimistic: (lead: Lead) => void
  /** Reemplazar el lead optimista por el real devuelto por el API */
  replaceLeadId: (tempId: string, lead: Lead) => void
  /** Quitar un lead (rollback de creación optimista fallida) */
  removeLead: (leadId: string) => void
  /** Alternar selección múltiple de un lead individual */
  toggleLeadSelection: (leadId: string) => void
  /** Seleccionar el rango contiguo dentro de una misma columna (Shift+click) */
  selectLeadRange: (columnLeadIds: string[], clickedId: string) => void
  /** Alternar selección de todos los leads visibles de una columna */
  toggleColumnSelection: (columnLeadIds: string[]) => void
  /** Limpiar la selección múltiple */
  clearSelection: () => void
  /** Actualizar filtro de búsqueda */
  setSearchQuery: (query: string) => void
  /** Actualizar filtro de owner */
  setOwnerFilter: (ownerId: string | null) => void
  /** Actualizar filtro de timeframe */
  setTimeframeFilter: (filter: 'all' | 'today' | 'week' | 'month') => void
  /** Actualizar rango de score */
  setScoreFilter: (min: number, max: number) => void
  /** Actualizar filtro de temperatura */
  setHotnessFilter: (hotness: Set<'COLD' | 'WARM' | 'HOT'>) => void
  /** Actualizar rango de fecha de cierre esperado */
  setDateRangeFilter: (from: string | null, to: string | null) => void
  /** Limpiar solo los filtros avanzados */
  clearAdvancedFilters: () => void
  /** Limpiar todos los filtros */
  clearFilters: () => void
}

const ADVANCED_FILTER_DEFAULTS = {
  scoreMin: 0,
  scoreMax: 100,
  hotnessFilter: new Set<'COLD' | 'WARM' | 'HOT'>(),
  closeDateFrom: null as string | null,
  closeDateTo: null as string | null,
}

/**
 * Store Zustand para estado del CRM
 *
 * Centraliza leads, drag & drop, selección (simple y múltiple) y filtros
 * (búsqueda, owner, timeframe y avanzados del Sprint 2).
 */
export const useCrmStore = create<CrmState & CrmActions>((set) => ({
  // Estado inicial
  leads: [],
  draggedLeadId: null,
  selectedLeadId: null,
  selectedLeadIds: new Set(),
  searchQuery: '',
  ownerFilter: null,
  timeframeFilter: 'all',
  ...ADVANCED_FILTER_DEFAULTS,

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

  addLeadOptimistic: (lead) => set((state) => ({ leads: [lead, ...state.leads] })),

  replaceLeadId: (tempId, lead) =>
    set((state) => ({
      leads: state.leads.map((item) => (item.id === tempId ? lead : item)),
    })),

  removeLead: (leadId) =>
    set((state) => ({
      leads: state.leads.filter((lead) => lead.id !== leadId),
    })),

  toggleLeadSelection: (leadId) =>
    set((state) => {
      const next = new Set(state.selectedLeadIds)
      if (next.has(leadId)) {
        next.delete(leadId)
      } else {
        next.add(leadId)
      }
      return { selectedLeadIds: next }
    }),

  selectLeadRange: (columnLeadIds, clickedId) =>
    set((state) => {
      // Rango contiguo dentro de la columna: desde el último seleccionado de
      // esa columna hasta el clickeado; si no hay ancla, selecciona solo el
      // clickeado.
      const next = new Set(state.selectedLeadIds)
      const clickedIndex = columnLeadIds.indexOf(clickedId)
      if (clickedIndex === -1) return { selectedLeadIds: next }
      const anchorIndex = columnLeadIds.findLastIndex(
        (id) => id !== clickedId && next.has(id)
      )
      if (anchorIndex === -1) {
        next.add(clickedId)
        return { selectedLeadIds: next }
      }
      const [from, to] =
        anchorIndex < clickedIndex ? [anchorIndex, clickedIndex] : [clickedIndex, anchorIndex]
      for (const id of columnLeadIds.slice(from, to + 1)) {
        next.add(id)
      }
      return { selectedLeadIds: next }
    }),

  toggleColumnSelection: (columnLeadIds) =>
    set((state) => {
      const next = new Set(state.selectedLeadIds)
      const allSelected =
        columnLeadIds.length > 0 && columnLeadIds.every((id) => next.has(id))
      for (const id of columnLeadIds) {
        if (allSelected) {
          next.delete(id)
        } else {
          next.add(id)
        }
      }
      return { selectedLeadIds: next }
    }),

  clearSelection: () => set({ selectedLeadIds: new Set() }),

  setSearchQuery: (query) => set({ searchQuery: query }),

  setOwnerFilter: (ownerId) => set({ ownerFilter: ownerId }),

  setTimeframeFilter: (filter) => set({ timeframeFilter: filter }),

  setScoreFilter: (min, max) => set({ scoreMin: min, scoreMax: max }),

  setHotnessFilter: (hotness) => set({ hotnessFilter: hotness }),

  setDateRangeFilter: (from, to) => set({ closeDateFrom: from, closeDateTo: to }),

  clearAdvancedFilters: () =>
    set({ ...ADVANCED_FILTER_DEFAULTS, hotnessFilter: new Set() }),

  clearFilters: () =>
    set({
      searchQuery: '',
      ownerFilter: null,
      timeframeFilter: 'all',
      ...ADVANCED_FILTER_DEFAULTS,
      hotnessFilter: new Set(),
    }),
}))

/**
 * Selectores derivados útiles
 *
 * OJO Zustand v5: los selectores que devuelven un array/objeto NUEVO en cada
 * llamada (`.filter()`, `new Map()`) deben consumirse con `useShallow` en los
 * componentes, o `useSyncExternalStore` entra en render-loop ("getSnapshot
 * should be cached"). Ver `useKanban.ts`.
 */

/** Leads filtrados por búsqueda, owner, timeframe y filtros avanzados */
export const selectFilteredLeads = (state: CrmState & CrmActions) => {
  let filtered = state.leads

  // Filtro de búsqueda: título, contacto (nombre y email) y producto
  if (state.searchQuery) {
    const normalizedQuery = state.searchQuery.trim().toLocaleLowerCase('es')
    filtered = filtered.filter(
      (lead) =>
        lead.title.toLocaleLowerCase('es').includes(normalizedQuery) ||
        lead.party.name.toLocaleLowerCase('es').includes(normalizedQuery) ||
        (lead.party.email ?? '').toLocaleLowerCase('es').includes(normalizedQuery) ||
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

  // Filtros avanzados (Sprint 2)
  if (state.scoreMin > 0 || state.scoreMax < 100) {
    filtered = filtered.filter(
      (lead) => lead.score >= state.scoreMin && lead.score <= state.scoreMax
    )
  }
  if (state.hotnessFilter.size > 0) {
    filtered = filtered.filter((lead) => state.hotnessFilter.has(lead.hotness))
  }
  if (state.closeDateFrom) {
    filtered = filtered.filter(
      (lead) => lead.expectedCloseDate != null && lead.expectedCloseDate >= state.closeDateFrom!
    )
  }
  if (state.closeDateTo) {
    filtered = filtered.filter(
      (lead) => lead.expectedCloseDate != null && lead.expectedCloseDate <= state.closeDateTo!
    )
  }

  return filtered
}

/** Lead actualmente seleccionado */
export const selectSelectedLead = (state: CrmState & CrmActions) => {
  return state.leads.find((lead) => lead.id === state.selectedLeadId) ?? null
}

/** Cantidad de filtros avanzados activos (para el badge del panel de filtros) */
export const selectActiveFilterCount = (state: CrmState & CrmActions) => {
  let count = 0
  if (state.scoreMin > 0 || state.scoreMax < 100) count += 1
  if (state.hotnessFilter.size > 0) count += 1
  if (state.closeDateFrom || state.closeDateTo) count += 1
  return count
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
