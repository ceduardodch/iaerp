import { Component, type ErrorInfo, type ReactNode } from 'react'

type ErrorBoundaryProps = {
  children: ReactNode
  /** Etiqueta opcional del área protegida, para el mensaje de fallback. */
  label?: string
}

type ErrorBoundaryState = {
  error: Error | null
}

/**
 * Límite de error (Sprint 8): captura errores de renderizado en el árbol hijo y
 * muestra un fallback accesible en vez de dejar la pantalla en blanco. Los error
 * boundaries deben ser componentes de clase (no hay equivalente con hooks).
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  override state: ErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error }
  }

  override componentDidCatch(error: Error, info: ErrorInfo) {
    // Deja rastro en consola para diagnóstico; en producción esto podría
    // enviarse a un servicio de observabilidad.
    console.error('ErrorBoundary capturó un error:', error, info.componentStack)
  }

  handleReset = () => {
    this.setState({ error: null })
  }

  override render() {
    if (this.state.error) {
      return (
        <div className="error-boundary" role="alert">
          <div className="error-boundary-card">
            <p className="error-boundary-eyebrow">Algo salió mal</p>
            <h2>No pudimos mostrar {this.props.label ?? 'esta sección'}</h2>
            <p className="error-boundary-detail">
              Ocurrió un error inesperado. Puedes reintentar; si persiste, recarga la página.
            </p>
            <div className="error-boundary-actions">
              <button type="button" className="erp-button erp-button-secondary" onClick={this.handleReset}>
                Reintentar
              </button>
              <button
                type="button"
                className="erp-button erp-button-primary"
                onClick={() => window.location.reload()}
              >
                Recargar página
              </button>
            </div>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}
