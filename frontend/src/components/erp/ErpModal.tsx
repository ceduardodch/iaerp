import { useEffect, useId, useRef, type PropsWithChildren, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'

let openModalCount = 0

/** Marca el contenido de fondo como inert mientras haya un modal abierto (accesibilidad AA). */
function useInertBackground(active: boolean) {
  useEffect(() => {
    if (!active) return
    const root = document.getElementById('root')
    openModalCount += 1
    root?.setAttribute('inert', '')
    return () => {
      openModalCount = Math.max(0, openModalCount - 1)
      if (openModalCount === 0) {
        root?.removeAttribute('inert')
      }
    }
  }, [active])
}

/**
 * Modal accesible centrado, reutilizable en todo el CRM (detalle de lead,
 * quick-add, confirmaciones, hint de atajos).
 *
 * - Overlay a pantalla completa con `createPortal` a `document.body`
 *   (necesario porque `#main-content` tiene `overflow: hidden`).
 * - `role="dialog" aria-modal="true"`, foco atrapado (Tab/Shift+Tab cicla
 *   dentro del modal), Esc cierra, click en el overlay cierra.
 * - Restaura el foco al elemento que abrió el modal al cerrarse.
 * - Marca el fondo `inert` mientras el modal está abierto.
 */
export function ErpModal({
  title,
  onClose,
  children,
  size = 'md',
  closeLabel = 'Cerrar ventana',
  describedById,
}: PropsWithChildren<{
  title: ReactNode
  onClose: () => void
  size?: 'sm' | 'md' | 'lg'
  closeLabel?: string
  describedById?: string
}>) {
  const titleId = useId()
  const dialogRef = useRef<HTMLDivElement>(null)
  const previouslyFocused = useRef<HTMLElement | null>(null)

  useInertBackground(true)

  useEffect(() => {
    previouslyFocused.current = document.activeElement as HTMLElement | null
    const dialog = dialogRef.current
    const focusable = dialog?.querySelector<HTMLElement>(FOCUSABLE_SELECTOR)
    ;(focusable ?? dialog)?.focus()

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onClose()
        return
      }
      if (event.key !== 'Tab' || !dialog) return

      const focusableEls = Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
        (el) => el.offsetParent !== null,
      )
      if (focusableEls.length === 0) return

      const first = focusableEls[0]
      const last = focusableEls[focusableEls.length - 1]
      const active = document.activeElement

      if (event.shiftKey && active === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && active === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown, true)
    return () => {
      document.removeEventListener('keydown', handleKeyDown, true)
      previouslyFocused.current?.focus?.()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return createPortal(
    <div
      className="erp-modal-overlay"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div
        ref={dialogRef}
        className={`erp-modal erp-modal-${size}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={describedById}
        tabIndex={-1}
      >
        <header className="erp-modal-header">
          <h2 id={titleId}>{title}</h2>
          <button type="button" className="erp-modal-close" onClick={onClose} aria-label={closeLabel}>
            ×
          </button>
        </header>
        <div className="erp-modal-body">{children}</div>
      </div>
    </div>,
    document.body,
  )
}
