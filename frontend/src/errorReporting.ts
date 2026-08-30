import * as Sentry from '@sentry/browser'

import { getLastCorrelationId } from './api'

export type FrontendErrorSource = 'window.onerror' | 'unhandledrejection' | 'error-boundary'

export type FrontendErrorReport = {
  source: FrontendErrorSource
  message: string
  stack?: string
  componentStack?: string
  correlationId: string | null
}

// Pendiente 9 de docs/OBSERVABILIDAD_PENDIENTES.md: espejo de
// `IAERP_ERROR_DSN` en backend. Vacío (default) = desactivado, sin cambiar
// el comportamiento. `VITE_` es el prefijo que Vite expone al bundle del
// navegador (ver `VITE_API_URL` en api.ts).
const errorDsn = import.meta.env.VITE_ERROR_DSN
// No hay una fuente de versión de app compartida con el backend (que fija
// `APP_VERSION` en `app/main.py`); se deja un release fijo, igual de simple.
const FRONTEND_RELEASE = 'iaerp-frontend@0.0.0'

let sentryInitialized = false

function ensureSentryInitialized(): void {
  if (sentryInitialized || !errorDsn) return
  Sentry.init({ dsn: errorDsn, environment: import.meta.env.MODE, release: FRONTEND_RELEASE })
  sentryInitialized = true
}

/**
 * Punto único de captura de errores de frontend (pendiente 7 de
 * `docs/OBSERVABILIDAD_PENDIENTES.md`). Adjunta el correlation ID de la
 * última request al backend para poder cruzarlo con los logs estructurados
 * y el evento de Sentry/GlitchTip del handler global (`app/main.py`).
 *
 * No se etiqueta con el tenant: a diferencia del backend, el frontend nunca
 * decodifica el JWT (es opaco, solo se usa vía `getToken()`), así que no hay
 * un valor de tenant confiable para taguear sin agregar esa decodificación
 * solo para esto. El correlation_id ya permite cruzar este evento con el del
 * backend, que sí lleva el tenant pseudonimizado.
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

  if (!errorDsn) return
  ensureSentryInitialized()
  Sentry.withScope((scope) => {
    scope.setTag('source', source)
    if (report.correlationId) scope.setTag('correlation_id', report.correlationId)
    if (componentStack) scope.setContext('react', { componentStack })
    Sentry.captureException(error)
  })
}
