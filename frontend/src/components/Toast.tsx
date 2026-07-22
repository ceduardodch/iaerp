import {
  createContext,
  useCallback,
  useContext,
  useRef,
  useState,
  type PropsWithChildren,
} from 'react'

/**
 * Notificaciones toast (Sprint 8): feedback ligero y accesible para acciones del
 * usuario (éxito/error/info), sin dependencias externas. Se renderizan en una
 * región aria-live para que los lectores de pantalla las anuncien.
 */

export type ToastVariant = 'success' | 'error' | 'info'

type ToastItem = {
  id: string
  message: string
  variant: ToastVariant
}

type ToastContextValue = {
  notify: (message: string, variant?: ToastVariant) => void
}

const ToastContext = createContext<ToastContextValue | null>(null)

const AUTO_DISMISS_MS = 4500

export function ToastProvider({ children }: PropsWithChildren) {
  const [toasts, setToasts] = useState<ToastItem[]>([])
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>())

  const dismiss = useCallback((id: string) => {
    setToasts((current) => current.filter((toast) => toast.id !== id))
    const timer = timers.current.get(id)
    if (timer) {
      clearTimeout(timer)
      timers.current.delete(id)
    }
  }, [])

  const notify = useCallback(
    (message: string, variant: ToastVariant = 'info') => {
      const id = crypto.randomUUID()
      setToasts((current) => [...current, { id, message, variant }])
      timers.current.set(
        id,
        setTimeout(() => dismiss(id), AUTO_DISMISS_MS),
      )
    },
    [dismiss],
  )

  return (
    <ToastContext.Provider value={{ notify }}>
      {children}
      <div className="toast-container" role="region" aria-label="Notificaciones" aria-live="polite">
        {toasts.map((toast) => (
          <div key={toast.id} className={`toast toast-${toast.variant}`} role="status">
            <span className="toast-message">{toast.message}</span>
            <button
              type="button"
              className="toast-close"
              aria-label="Cerrar notificación"
              onClick={() => dismiss(toast.id)}
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext)
  if (!context) {
    throw new Error('useToast debe usarse dentro de <ToastProvider>')
  }
  return context
}
