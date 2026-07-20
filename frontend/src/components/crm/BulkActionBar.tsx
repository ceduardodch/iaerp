import { useState } from 'react'

import type { LeadStatus } from '../../api'
import { ErpButton } from '../erp'
import { PIPELINE } from './CrmKanban'
import type { BulkMoveResult, UseKanbanReturn } from '../../hooks/useKanban'

/**
 * Barra flotante de acciones en lote (Sprint 2).
 *
 * Aparece cuando hay leads seleccionados. "Mover a" ofrece todas las etapas;
 * la validación es por lead (misma convención del pipeline): los inválidos se
 * omiten y se reportan en el resumen ("3 movidos, 2 omitidos").
 */
export function BulkActionBar({
  selectedLeadIds,
  mutation,
  onClear,
}: {
  selectedLeadIds: Set<string>
  mutation: UseKanbanReturn['bulkMoveMutation']
  onClear: () => void
}) {
  const [target, setTarget] = useState<LeadStatus>('CONTACTED')
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null)
  const [summary, setSummary] = useState<string | null>(null)

  if (selectedLeadIds.size === 0 && !summary) return null

  function describe(results: BulkMoveResult[]): string {
    const moved = results.filter((item) => item.outcome === 'moved').length
    const skipped = results.filter((item) => item.outcome === 'skipped')
    const failed = results.filter((item) => item.outcome === 'error')
    const parts = [`${moved} movido${moved === 1 ? '' : 's'}`]
    if (skipped.length > 0) {
      parts.push(`${skipped.length} omitido${skipped.length === 1 ? '' : 's'} por transición inválida`)
    }
    if (failed.length > 0) {
      parts.push(`${failed.length} con error`)
    }
    return parts.join(', ')
  }

  function run() {
    setSummary(null)
    mutation.mutate(
      {
        leadIds: [...selectedLeadIds],
        targetStatus: target,
        onProgress: (done, total) => setProgress({ done, total }),
      },
      {
        onSettled: () => setProgress(null),
        onSuccess: (results) => {
          setSummary(describe(results))
          onClear()
        },
      }
    )
  }

  return (
    <aside className="bulk-action-bar" role="region" aria-label="Acciones en lote">
      {selectedLeadIds.size > 0 ? (
        <>
          <strong>{selectedLeadIds.size} seleccionado{selectedLeadIds.size === 1 ? '' : 's'}</strong>
          <label>
            Mover a
            <select
              value={target}
              onChange={(event) => setTarget(event.target.value as LeadStatus)}
            >
              {PIPELINE.map((stage) => (
                <option key={stage.id} value={stage.id}>
                  {stage.label}
                </option>
              ))}
            </select>
          </label>
          <ErpButton variant="primary" onClick={run} disabled={mutation.isPending}>
            {progress ? `Moviendo ${progress.done}/${progress.total}…` : 'Mover'}
          </ErpButton>
          <ErpButton variant="ghost" onClick={onClear} disabled={mutation.isPending}>
            Deseleccionar
          </ErpButton>
        </>
      ) : null}
      {summary ? (
        <p className="bulk-summary" role="status">
          {summary}{' '}
          <button type="button" className="bulk-summary-close" onClick={() => setSummary(null)}>
            Cerrar
          </button>
        </p>
      ) : null}
    </aside>
  )
}
