import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/mcp': 'http://127.0.0.1:8000',
    },
  },
  build: {
    rollupOptions: {
      output: {
        // Separa las dependencias estables (react, react-query) del código de la
        // app, que cambia con cada release. Así el chunk de vendor se cachea a
        // largo plazo y los usuarios solo re-descargan el código de app al
        // actualizar. dnd-kit/framer-motion NO se incluyen: ya viven aislados en
        // el chunk lazy `crm`. Se usa el form función por compatibilidad con
        // Rolldown (el form objeto no está tipado en esta versión).
        manualChunks(id) {
          if (
            id.includes('node_modules/react/') ||
            id.includes('node_modules/react-dom/') ||
            id.includes('node_modules/scheduler/') ||
            id.includes('node_modules/@tanstack/')
          ) {
            return 'vendor'
          }
          return undefined
        },
      },
    },
  },
})
