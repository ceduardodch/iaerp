# Sprint Status Tracking - IAERP UI/UX Improvements

**Fecha inicio:** 2026-07-19
**Fecha actualización:** 2026-07-21
**Horizonte:** 12 semanas
**Estado general:** ✅ Sprints 1-9 completados (5 parcial; 7 con alcance ajustado).
Post-plan: **cliente SRI real** (`SoapSRIClient`) + **integración Gmail** listos en
código, en preparación de **go-live** (faltan pasos de config del operador). CI
verde en `release`. Fuente de verdad operativa: [`docs/STATUS.md`](docs/STATUS.md).

> ⚠️ Este progreso se sincronizó con la realidad por commits (antes estaba
> desactualizado en 22%). La fuente viva de coordinación es
> [`COORDINACION_IA.md`](COORDINACION_IA.md).

---

## 📊 Progreso General

``[███████████████████████████████░░] ~94% (8.5/9 sprints)

Sprint 1: ████████████████████████████████ 100% CRM Kanban Foundation ✅
Sprint 2: ████████████████████████████████ 100% CRM Kanban Advanced ✅ (NO fue "skipped": sí se hizo)
Sprint 3: ████████████████████████████████ 100% Sidebar Colapsible + UX ✅
Sprint 4: ████████████████████████████████ 100% Invoice Spreadsheet UX ✅
Sprint 5: ████████████████░░░░░░░░░░░░░░░░ ~50% Forms Verticales ⚠️ (forms accesibles vigentes y validados por wcag-audit; los componentes *Vertical duplicados sin cablear fueron eliminados)
Sprint 6: ████████████████████████████████ 100% Pagos por Cliente ✅ (modelo ya existía; se añadió el indicador HU-17)
Sprint 7: ████████████████████████████████ 100% Stack Modernization ✅ (code-splitting CRM + vendor chunk; reescrituras react-hook-form/radix descartadas por riesgo/valor)
Sprint 8: ████████████████████████████████ 100% Polish & Animations ✅ (ErrorBoundary, skeletons, toasts, transición de sección)
Sprint 9: ████████████████████████████████ 100% Testing & Documentation ✅ (cobertura E2E ampliada + guías USER/ADMIN/DEV)
```

---

## 🎯 Sprint 1: CRM Kanban Foundation

**Periodo:** Semana 1 (5-7 días estimados)
**Estado:** ✅ COMPLETADO - Todas las tareas implementadas
**Prioridad:** HIGH (Usuario quiere CRM visual primero)
**Risk Score:** Low (todos los riesgos resueltos)
**Progress:** 100% (10/10 tareas completadas) ✅

### Historias de Usuario (3)
- [ ] **HU-1:** Ver leads en columnas kanban para visión del pipeline
- [ ] **HU-2:** Arrastrar leads entre columnas para cambiar estado rápidamente
- [ ] **HU-3:** Ver métricas visuales del pipeline (total por columna, value total)

### Criterios de Aceptación (10)
- [ ] Pipeline kanban con 7 columnas (NEW → CONTACTED → QUALIFIED → PROPOSAL → NEGOTIATION → WON/LOST)
- [ ] Drag & drop funcional con @dnd-kit/core
- [ ] Auto-scroll vertical durante drag operations
- [ ] Cards con avatar, nombre, puntuación, temperatura
- [ ] Badges con gradientes según estado (COLD→blue, WARM→orange, HOT→red)
- [ ] Filtros por owner y timeframe
- [ ] Responsive mobile (1 columna) → desktop (7 columnas)

### Tareas Técnicas (10)
- [x] **TASK-1.1:** Instalar dependencias @dnd-kit/core, @dnd-kit/sortable, @dnd-kit/utilities ✅
- [x] **TASK-1.2:** Crear componente `CrmKanban.tsx` con layout grid CSS ✅
- [x] **TASK-1.3:** Implementar `useKanban` hook con Zustand para state management ✅
- [x] **TASK-1.4:** Crear componente `LeadCard.tsx` con avatars y badges ✅
- [x] **TASK-1.5:** Implementar drag handlers con `DndContext` + `SortableContext` ✅
- [x] **TASK-1.6:** Verificar backend API `PUT /crm/leads/{id}/status` ✅
- [x] **TASK-1.7:** Frontend: Integration con `/crm/leads` API ✅
- [x] **TASK-1.8:** Animaciones spring con `framer-motion` ✅
- [x] **TASK-1.9:** Testing E2E con Playwright (drag scenarios) ✅
- [x] **TASK-1.10:** Deploy a staging y QA con usuario ✅
- [ ] **TASK-1.6:** Backend: Verificar `PUT /crm/leads/{id}/status` (ya existe)
- [ ] **TASK-1.7:** Frontend: Integration con `/crm/leads` API
- [ ] **TASK-1.8:** Animaciones spring con `framer-motion`
- [ ] **TASK-1.9:** Testing E2E con Playwright (drag scenarios)
- [ ] **TASK-1.10:** Deploy a staging y QA con usuario

### Dependencies
- **Blockers:** Ninguna
- **Requiere:** Skills de testing instaladas, CRM base funcionando

### Technical Decisions
- **Librería DnD:** @dnd-kit/core (elección sobre react-beautiful-dnd)
- **State Management:** Zustand (más ligero que Redux para componente único)
- **Animations:** Framer Motion (60fps spring physics)

### Code Files to Create/Modify
- [ ] `frontend/src/components/crm/CrmKanban.tsx` (nuevo)
- [ ] `frontend/src/components/crm/LeadCard.tsx` (nuevo)
- [ ] `frontend/src/hooks/useKanban.ts` (nuevo)
- [ ] `frontend/src/store/crmStore.ts` (nuevo, Zustand)
- [ ] `frontend/src/App.tsx` (modificar para incluir CrmKanban)
- [ ] `frontend/package.json` (añadir dependencias)

### Testing Strategy
- **E2E Scenarios:**
  - Drag lead from NEW → CONTACTED
  - Drag multiple leads between columns
  - Filter by owner and verify filtering
  - Mobile responsive (1 column layout)
- **Performance:** Validate 60fps durante drag operations

---

## 🎯 Sprint 2: CRM Kanban Advanced

**Periodo:** Semana 2 (5-7 días estimados)
**Estado:** ✅ COMPLETADO (2026-07-20) — implementado por la sesión que cerró el
sprint por instrucción del usuario; si otra sesión ve "SKIPPED" en su copia,
esta versión (con evidencia) es la vigente. Detalle de tareas en
ISSUE_TRACKING.md (TASK-2.0 a TASK-2.8).
**Prioridad:** MEDIUM
**Risk Score:** Low (extends foundation)

### Historias de Usuario (3)
- [x] **HU-4:** Crear leads desde kanban con quick-add ✅
- [x] **HU-5:** Ver detalles del lead en modal sin perder contexto ✅
- [x] **HU-6:** Filtrar por hotness y score ✅

### Criterios de Aceptación
- [x] Quick-add form desde kanban ("+" solo en columnas activas; optimista con rollback) ✅
- [x] Click en card abre modal con detalles (ErpModal accesible; Esc/overlay cierra; el kanban conserva scroll/filtros/selección) ✅
- [x] Bulk operations: selección individual, Shift+rango por columna y "seleccionar todos"; mover con validación por lead y resumen de omitidos ✅
- [x] Filtros avanzados: score range, hotness (multi) y date range ✅
- [x] Search por nombre/email de party ✅
- [x] Keyboard shortcuts (←→↑↓ navegan, Enter abre, Esc cierra/deselecciona) + panel "?" ✅

### Evidencia (2026-07-20)
- `frontend/tests/crm-kanban-advanced.spec.ts`: 16/16 (8 escenarios × desktop/mobile), mocks + axe AA.
- Suites completas verdes tras el sprint: 64 Playwright, 244 backend, lint y build limpios.
- Fixes incluidos: bug 500 al registrar actividades (backend + test), render-loop latente Zustand v5 (useShallow), drag sensor 8px (clicks ya no se pierden), contraste AA del kanban.

### Dependencies
- **Requiere:** Sprint 1 completado

---

## 🎯 Sprint 3: Sidebar Colapsible + UX Improvements

**Periodo:** Semana 3 (3-5 días estimados)
**Estado:** ✅ COMPLETADO - Todas las tareas implementadas
**Prioridad:** HIGH (Usuario reportó problemas de navegación y títulos grandes)
**Risk Score:** Low (mejoras visuales self-contained)
**Progress:** 100% (7/7 tareas completadas) ✅

### Historias de Usuario (5)
- [ ] **HU-7:** Esconder menú para ganar espacio de trabajo
- [ ] **HU-8:** Acceso rápido a secciones frecuentes con iconos
- [ ] **HU-9:** Que el menú recuerde mi preferencia
- [ ] **HU-10:** Ver claramente dónde estoy en la navegación (actualmente no se visualiza bien)
- [ ] **HU-11:** Que los títulos de página no sean tan grandes y difíciles de leer

### Criterios de Aceptación (14)
- [x] Sidebar colapsible: 250px (expanded) → 64px (collapsed)
- [x] Toggle button visible en header o sidebar itself
- [x] Icon-only mode cuando está colapsado con tooltips
- [x] Transición suave de 300ms con cubic-bezier
- [x] Estado preservado en localStorage
- [ ] Responsive: en mobile se colapsa por defecto
- [x] ARIA labels para accessibility
- [x] Navegación activa más visible (highlight o badge mejorado)
- [x] Títulos h1 reducidos de tamaño actual (muy grande) a tamaño razonable
- [x] Títulos con clamp ajustado para mejor legibilidad
- [x] Indicador visual claro de ubicación actual
- [ ] Consistencia visual en toda la aplicación

### Tareas Técnicas (7)
- [x] **TASK-3.1:** Mejorar visibilidad de navegación activa (badge/highlight más visible)
- [x] **TASK-3.2:** Reducir tamaño de títulos h1 (clamp ajustado a tamaños más razonables)
- [x] **TASK-3.3:** Crear componente `Sidebar.tsx` con state local + localStorage sync
- [x] **TASK-3.4:** Iconos para cada sección (usando SVG strings o lucide-react)
- [x] **TASK-3.5:** Tooltips con CSS custom (sin dependencias adicionales)
- [x] **TASK-3.6:** CSS transitions con `transform: translateX()` y `opacity`
- [x] **TASK-3.7:** Update `App.tsx` layout para sidebar + main content

### Dependencies
- **Blockers:** Ninguna (feature independiente)

---

## 🎯 Sprint 4: Invoice Spreadsheet UX

**Periodo:** Semana 4-5 (7-10 días estimados)
**Estado:** 📋 Planeado - No iniciado
**Prioridad:** HIGH (Usuario lo mencionó específicamente)
**Risk Score:** Medium-high (cálculos fiscales complejos)

### Dependencies
- **Blockers:** Ninguna (feature independiente)

---

## 🎯 Sprint 5: Forms Verticales "One Sprint"

**Periodo:** Semana 6-7 (5-7 días estimados)
**Estado:** 📋 Planeado - No iniciado
**Prioridad:** MEDIUM
**Risk Score:** Low (mejora visual, sin cambios de lógica)

### Dependencies
- **Blockers:** Ninguna (refactor de forms existentes)

---

## 🎯 Sprint 6: Pagos por Cliente

**Periodo:** Semana 8 (5-7 días estimados)
**Estado:** 📋 Planeado - No iniciado
**Prioridad:** MEDIUM (lógica de negocio)
**Risk Score:** Medium (cambio de lógica de negocio)

### Dependencies
- **Blockers:** Ninguna (feature independiente)

---

## 🎯 Sprint 7: Stack Modernization

**Periodo:** Semana 9 (7-10 días estimados)
**Estado:** 📋 Planeado - No iniciado
**Prioridad:** LOW-MEDIUM (upgrade técnico)
**Risk Score:** Medium (refactor significativo de patterns)

### Dependencies
- **Requiere:** Sprints anteriores para maximizar benefit

---

## 🎯 Sprint 8: Polish & Animations

**Periodo:** Semana 10-11 (5-7 días estimados)
**Estado:** 📋 Planeado - No iniciado
**Prioridad:** LOW
**Risk Score:** Low (mejoras visuales)

### Dependencies
- **Requiere:** Sprint 7 (stack moderno)

---

## 🎯 Sprint 9: Testing & Documentation

**Periodo:** Semana 12 (5-7 días estimados)
**Estado:** 📋 Planeado - No iniciado
**Prioridad:** HIGH (calidad y confianza)
**Risk Score:** Low (testing y documentación)

### Dependencies
- **Requiere:** Todos los sprints anteriores

---

## 📈 Timeline Visual

```
Week 1-2:  [████] Sprint 1: CRM Kanban Foundation
Week 3:   [░░░░░] Sprint 2: CRM Kanban Advanced  
Week 4:   [░░░░░] Sprint 3: Sidebar Colapsible
Week 5-6:  [░░░░░] Sprint 4: Invoice Spreadsheet UX
Week 7:   [░░░░░] Sprint 5: Forms Verticales
Week 8:   [░░░░░] Sprint 6: Pagos por Cliente
Week 9:   [░░░░░] Sprint 7: Stack Modernization
Week 10:  [░░░░░] Sprint 8: Polish & Animations
Week 11:  [░░░░░] Sprint 8: Polish & Animations (cont)
Week 12:  [░░░░░] Sprint 9: Testing & Documentation
```

---

## 🚦 Decision Log

### Decision 1: Librería Drag & Drop
**Fecha:** 2026-07-19
**Decisión:** Usar @dnd-kit/core sobre react-beautiful-dnd
**Razón:** @dnd-kit es más moderno, mejor performance, accesibilidad nativa
**Alternativas consideradas:** react-beautiful-dnd, dnd-kit, react-dnd

### Decision 2: State Management para Kanban
**Fecha:** 2026-07-19
**Decisión:** Zustand sobre Redux/Context
**Razón:** Más ligero, ideal para component-level state
**Alternativas consideradas:** Redux Toolkit, React Context, Jotai

### Decision 3: Priority Order
**Fecha:** 2026-07-19
**Decisión:** CRM Kanban → Invoice UX → Forms → Sidebar → Others
**Razón:** CRM es high-value para usuario, Invoice UX es high-complexity
**Alternativas consideradas:** Sidebar primero (mais fácil), Forms primero (menos riesgo)

---

## 💡 Lessons Learned (por llenar después de cada sprint)

### Sprint 1 Lessons:
_ pendiente de completar sprint_

### Sprint 2 Lessons:
_ pendiente de completar sprint_

---

## 🔄 Session Context

**Última sesión:** 2026-07-19
**Estado actual:** Planning completado, backlog estructurado
**Próxima acción:** Iniciar Sprint 1 - CRM Kanban Foundation
**Tokens usados:** ~30% de sesión actual

**Para retomar en próxima sesión:**
1. Revisar este documento (SPRINT_STATUS.md)
2. Ver qué tareas están pendientes en Sprint 1
3. Continuar desde donde se quedó
4. Actualizar CLAUDE.md si hay cambios significativos

**Comando para quick resume:**
"Revisar SPRINT_STATUS.md y BACKLOG.md para continuar con Sprint 1"

---

## 📞 Emergency Contacts

**Si el proyecto está bloqueado:**
- **Tech Lead:** [Contactar para decisiones técnicas]
- **Product Owner:** [Contactar para prioridades]
- **Architecture:** Revisar ADRs en `/docs/adrs/`

**Documentación de emergencia:**
- `STATUS.md` - Estado actual del proyecto
- `BACKLOG.md` - Alcance y tareas detalladas
- `CLAUDE.md` - Configuración del proyecto

---

**Última actualización:** 2026-07-19 15:30
**Sprint activo:** Sprint 1 - CRM Kanban Foundation (planeado, no iniciado)
**Próximo hito:** TASK-1.1 (Instalar dependencias @dnd-kit)