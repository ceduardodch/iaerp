import { ErpButton } from '../erp'

/**
 * Hint accesible de atajos de teclado del kanban (Sprint 2). El botón "?"
 * alterna un panel con la lista; Esc también lo cierra (ver
 * `useKanbanShortcuts`).
 */
export function ShortcutsHint({
  open,
  onToggle,
}: {
  open: boolean
  onToggle: () => void
}) {
  return (
    <div className="shortcuts-hint">
      <ErpButton
        variant="ghost"
        onClick={onToggle}
        aria-expanded={open}
        aria-controls="kanban-shortcuts-panel"
        aria-label="Atajos de teclado"
      >
        ?
      </ErpButton>
      {open ? (
        <section
          id="kanban-shortcuts-panel"
          className="shortcuts-panel"
          role="region"
          aria-label="Atajos de teclado del pipeline"
        >
          <h3>Atajos de teclado</h3>
          <dl>
            <div>
              <dt>← →</dt>
              <dd>Mover el foco entre columnas</dd>
            </div>
            <div>
              <dt>↑ ↓</dt>
              <dd>Mover el foco dentro de la columna</dd>
            </div>
            <div>
              <dt>Enter</dt>
              <dd>Abrir la oportunidad enfocada</dd>
            </div>
            <div>
              <dt>Esc</dt>
              <dd>Cerrar este panel, el detalle o limpiar la selección</dd>
            </div>
            <div>
              <dt>Shift + click</dt>
              <dd>Seleccionar un rango dentro de la columna</dd>
            </div>
          </dl>
        </section>
      ) : null}
    </div>
  )
}
