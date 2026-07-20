import { useState } from 'react'

import { ErpButton, ErpToolbar } from '../erp'

type Hotness = 'COLD' | 'WARM' | 'HOT'

const HOTNESS_LABELS: Record<Hotness, string> = {
  COLD: 'Frío',
  WARM: 'Tibio',
  HOT: 'Caliente',
}

/**
 * Toolbar de filtros del kanban (Sprint 2): búsqueda por texto (título,
 * contacto por nombre/email, producto) siempre visible, y panel de filtros
 * avanzados plegable (rango de score, temperatura y rango de cierre esperado).
 * El filtrado es client-side sobre los leads cargados (≤100), en el store.
 */
export function KanbanFilters({
  searchQuery,
  onSearchChange,
  scoreMin,
  scoreMax,
  onScoreChange,
  hotnessFilter,
  onHotnessChange,
  closeDateFrom,
  closeDateTo,
  onDateRangeChange,
  activeFilterCount,
  onClearAdvanced,
}: {
  searchQuery: string
  onSearchChange: (query: string) => void
  scoreMin: number
  scoreMax: number
  onScoreChange: (min: number, max: number) => void
  hotnessFilter: Set<Hotness>
  onHotnessChange: (hotness: Set<Hotness>) => void
  closeDateFrom: string | null
  closeDateTo: string | null
  onDateRangeChange: (from: string | null, to: string | null) => void
  activeFilterCount: number
  onClearAdvanced: () => void
}) {
  const [open, setOpen] = useState(false)

  function toggleHotness(value: Hotness) {
    const next = new Set(hotnessFilter)
    if (next.has(value)) {
      next.delete(value)
    } else {
      next.add(value)
    }
    onHotnessChange(next)
  }

  return (
    <div className="kanban-filters">
      <ErpToolbar>
        <label className="search-field">
          <span>Buscar</span>
          <input
            value={searchQuery}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder="Oportunidad, contacto, email o producto"
          />
        </label>
        <ErpButton
          variant="ghost"
          onClick={() => setOpen((current) => !current)}
          aria-expanded={open}
          aria-controls="kanban-advanced-filters"
        >
          Filtros{activeFilterCount > 0 ? ` (${activeFilterCount})` : ''}
        </ErpButton>
      </ErpToolbar>

      {open ? (
        <section
          id="kanban-advanced-filters"
          className="kanban-advanced-filters"
          aria-label="Filtros avanzados"
        >
          <fieldset>
            <legend>Puntuación</legend>
            <div className="field-row">
              <label>
                Mínimo
                <input
                  type="number"
                  min={0}
                  max={100}
                  value={scoreMin}
                  onChange={(event) =>
                    onScoreChange(Math.min(Number(event.target.value), scoreMax), scoreMax)
                  }
                />
              </label>
              <label>
                Máximo
                <input
                  type="number"
                  min={0}
                  max={100}
                  value={scoreMax}
                  onChange={(event) =>
                    onScoreChange(scoreMin, Math.max(Number(event.target.value), scoreMin))
                  }
                />
              </label>
            </div>
          </fieldset>

          <fieldset>
            <legend>Temperatura</legend>
            <div className="hotness-options" role="group">
              {(Object.keys(HOTNESS_LABELS) as Hotness[]).map((value) => (
                <label key={value} className="hotness-option">
                  <input
                    type="checkbox"
                    checked={hotnessFilter.has(value)}
                    onChange={() => toggleHotness(value)}
                  />
                  {HOTNESS_LABELS[value]}
                </label>
              ))}
            </div>
          </fieldset>

          <fieldset>
            <legend>Cierre esperado</legend>
            <div className="field-row">
              <label>
                Desde
                <input
                  type="date"
                  value={closeDateFrom ?? ''}
                  onChange={(event) =>
                    onDateRangeChange(event.target.value || null, closeDateTo)
                  }
                />
              </label>
              <label>
                Hasta
                <input
                  type="date"
                  value={closeDateTo ?? ''}
                  onChange={(event) =>
                    onDateRangeChange(closeDateFrom, event.target.value || null)
                  }
                />
              </label>
            </div>
          </fieldset>

          <ErpButton variant="ghost" onClick={onClearAdvanced} disabled={activeFilterCount === 0}>
            Limpiar filtros avanzados
          </ErpButton>
        </section>
      ) : null}
    </div>
  )
}
