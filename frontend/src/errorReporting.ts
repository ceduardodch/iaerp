import { getLastCorrelationId } from './api'

export type FrontendErrorSource = 'window.onerror' | 'unhandledrejection' | 'error-boundary'

export type FrontendErrorReport = {
  source: FrontendErrorSource
  message: string
  stack?: string
  componentStack?: string
  correlationId: string | null
}

/**
 * Punto único de captura de errores de frontend (pendiente 7 de
 * `docs/OBSERVABILIDAD_PENDIENTES.md`). Adjunta el correlation ID de la
 * última request al backend para poder cruzarlo con los logs estructurados
 * del handler global (`app/main.py`). Sin `IAERP_ERROR_DSN` configurado
 * (pendiente 9, aún no implementado) el único destino es la consola,
 * estructurada para que un envío a Sentry/GlitchTip después solo tenga que
 * leer este mismo objeto.
 */
export function reportFrontendError(error: Error, source: FrontendErrorSource, componentStack?: string): void {
  const report: FrontendErrorReport = {
    source,
    message: error.message,
    stack: error.stack,
    componentStack,
    correlationId: getLastCorrelationId(),
  }
  console.error('[frontend-error]', JSON.stringify(report))
}
