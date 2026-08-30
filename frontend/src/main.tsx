import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import './index.css'
import App from './App.tsx'
import { AuthProvider } from './auth.tsx'
import { ErrorBoundary } from './components/ErrorBoundary.tsx'
import { ToastProvider } from './components/Toast.tsx'
import { reportFrontendError } from './errorReporting.ts'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 10_000 } },
})

// Pendiente 7 de docs/OBSERVABILIDAD_PENDIENTES.md: sin esto, un error fuera
// del árbol de React (script global, promesa sin catch) no deja ningún
// rastro con correlation ID.
window.addEventListener('error', (event) => {
  const error = event.error instanceof Error ? event.error : new Error(event.message)
  reportFrontendError(error, 'window.onerror')
})

window.addEventListener('unhandledrejection', (event) => {
  const reason = event.reason
  const error = reason instanceof Error ? reason : new Error(String(reason))
  reportFrontendError(error, 'unhandledrejection')
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary label="la aplicación">
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <AuthProvider>
            <App />
          </AuthProvider>
        </ToastProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>,
)
