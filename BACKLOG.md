# Backlog IAERP - Alcance y Planificación

**Fecha:** 2026-07-19
**Versión:** 1.0
**Estado:** Activo

## 🎯 Visión General

Transformar IAERP en un ERP moderno con interfaces dinámicas, manteniendo la robustez fiscal ecuatoriana y la arquitectura técnica existente.

**Horizonte:** 12 semanas
**Enfoque:** Mejoras UI/UX + Modernización de interfaces
**Stack:** React 19 + TypeScript + FastAPI + PostgreSQL

---

## 📊 Resumen del Alcance

### Módulo CRM Mejoras (Sprints 1-2)
- **Pipeline Kanban arrastrable** - Drag & drop 60fps con @dnd-kit
- **Cards modernos** - Avatars, badges, gradientes, animaciones
- **Auto-scroll** - Scroll inteligente durante drag operations
- **Responsivo** - Mobile-first con breakpoints adaptativos

### UX Modernización (Sprints 3-6)
- **Menú colapsible** - Sidebar 250px → 64px con transiciones suaves
- **Invoice Spreadsheet** - Detalle tipo hoja de cálculo editable
- **Forms Profesionales** - Layout vertical "one sprint" 
- **Pagos por Cliente** - Override de condiciones a nivel customer

### Stack Technical Upgrade (Sprint 7-8)
- **Librerías modernas** - React Hook Form, Framer Motion, Zustand
- **Performance** - Optimización de renderizado y memoización
- **Accessibility** - WCAG AA compliance con ARIA labels

### Polish & Deploy (Sprints 9-12)
- **Testing E2E** - Cobertura completa con Playwright
- **Animaciones** - Micro-interacciones y transiciones
- **Deploy** - Producción con monitoreo

---

## 🗓️ Backlog por Sprint

### Sprint 1: CRM Kanban Foundation (Semana 1)

**Objetivo:** Pipeline visual arrastrable para gestión de leads

#### Historias de Usuario:
- [ ] **HU-1:** Como vendedor, quiero ver mis leads en columnas kanban para tener visión del pipeline
- [ ] **HU-2:** Como vendedor, quiero arrastrar leads entre columnas para cambiar estado rápidamente
- [ ] **HU-3:** Como manager, quiero ver métricas visuales del pipeline (total por columna, value total)

#### Criterios de Aceptación:
- [ ] Pipeline kanban con 7 columnas (NEW → CONTACTED → QUALIFIED → PROPOSAL → NEGOTIATION → WON/LOST)
- [ ] Drag & drop funcional con @dnd-kit/core
- [ ] Auto-scroll vertical durante drag operations
- [ ] Cards con avatar, nombre, puntuación, temperatura
- [ ] Badges con gradientes según estado (COLD→blue, WARM→orange, HOT→red)
- [ ] Filtros por owner y timeframe
- [ ] Responsive mobile (1 columna) → desktop (7 columnas)

#### Tareas Técnicas:
- [ ] **TASK-1.1:** Instalar dependencias @dnd-kit/core, @dnd-kit/sortable, @dnd-kit/utilities
- [ ] **TASK-1.2:** Crear componente `CrmKanban.tsx` con layout grid CSS
- [ ] **TASK-1.3:** Implementar `useKanban` hook con Zustand para state management
- [ ] **TASK-1.4:** Crear componente `LeadCard.tsx` con avatars y badges
- [ ] **TASK-1.5:** Implementar drag handlers con `DndContext` + `SortableContext`
- [ ] **TASK-1.6:** Backend: `PUT /crm/leads/{id}/status` (ya existe)
- [ ] **TASK-1.7:** Frontend: Integration con `/crm/leads` API
- [ ] **TASK-1.8:** Animaciones spring con `framer-motion`
- [ ] **TASK-1.9:** Testing E2E con Playwright (drag scenarios)
- [ ] **TASK-1.10:** Deploy a staging y QA con usuario

**Estimación:** 5-7 días
**Dependencies:** Ninguna (stack actual suficiente)
**Risk:** Medium (drag & drop complexity)

---

### Sprint 2: CRM Kanban Advanced (Semana 2)

**Objetivo:** Funcionalidades avanzadas del kanban

#### Historias de Usuario:
- [ ] **HU-4:** Como vendedor, quiero crear leads desde el kanban con quick-add
- [ ] **HU-5:** Como vendedor, quiero ver detalles del lead en modal sin perder contexto
- [ ] **HU-6:** Como vendedor, quiero filtrar por hotness y score

#### Criterios de Aceptación:
- [ ] Quick-add form para crear leads desde kanban (modal lateral)
- [ ] Click en card abre modal con detalles (sin navegar away)
- [ ] Bulk operations: seleccionar múltiples leads y moverlos
- [ ] Filtros avanzados: score range, hotness, date range
- [ ] Search por nombre/email de party
- [ ] Keyboard shortcuts (← → para navegar, Enter para seleccionar)

#### Tareas Técnicas:
- [ ] **TASK-2.1:** Modal `LeadQuickAdd.tsx` con form compacto
- [ ] **TASK-2.2:** Modal `LeadDetail.tsx` con tabs (Details, Activities, Notes)
- [ ] **TASK-2.3:** Bulk select con checkboxes en cards
- [ ] **TASK-2.4:** Backend: `PUT /crm/leads/bulk-status` (nuevo endpoint)
- [ ] **TASK-2.5:** Filtros avanzados UI con ErpToolbar mejorado
- [ ] **TASK-2.6:** Search debounced (300ms) con TanStack Query
- [ ] **TASK-2.7:** Keyboard navigation con `react-hotkeys-hook`
- [ ] **TASK-2.8:** Performance: virtual list para >100 leads con `react-window`
- [ ] **TASK-2.9:** E2E testing de bulk operations
- [ ] **TASK-2.10:** Deploy y validación con stakeholder

**Estimación:** 5-7 días
**Dependencies:** Sprint 1 completado
**Risk:** Low (extends foundation)

---

### Sprint 3: Sidebar Colapsible (Semana 3)

**Objetivo:** Menú lateral colapsible para ganar espacio en pantalla

#### Historias de Usuario:
- [ ] **HU-7:** Como usuario, quiero esconder el menú para tener más espacio de trabajo
- [ ] **HU-8:** Como usuario, quiero acceso rápido a secciones frecuentes con iconos
- [ ] **HU-9:** Como usuario, quiero que el menú recuerde mi preferencia
- [ ] **HU-10:** Como usuario, quiero ver claramente dónde estoy en la navegación (actualmente no se visualiza bien)
- [ ] **HU-11:** Como usuario, quiero que los títulos de página no sean tan grandes y difíciles de leer

#### Criterios de Aceptación:
- [ ] Sidebar colapsible: 250px (expanded) → 64px (collapsed)
- [ ] Toggle button visible en header o sidebar itself
- [ ] Icon-only mode cuando está colapsado con tooltips
- [ ] Transición suave de 300ms con cubic-bezier
- [ ] Estado preservado en localStorage
- [ ] Responsive: en mobile se colapsa por defecto
- [ ] ARIA labels para accessibility

#### Tareas Técnicas:
- [ ] **TASK-3.1:** Mejorar visibilidad de navegación activa (badge/highlight más visible)
- [ ] **TASK-3.2:** Reducir tamaño de títulos h1 (clamp ajustado a tamaños más razonables)
- [ ] **TASK-3.3:** Crear componente `Sidebar.tsx` con state local + localStorage sync
- [ ] **TASK-3.4:** Iconos para cada sección (usando SVG strings o lucide-react)
- [ ] **TASK-3.5:** Tooltips con `@radix-ui/react-tooltip` o custom
- [ ] **TASK-3.6:** CSS transitions con `transform: translateX()` y `opacity`
- [ ] **TASK-3.7:** Update `App.tsx` layout para sidebar + main content
- [ ] **TASK-3.6:** Breakpoint mobile: <768px sidebar colapsado por defecto
- [ ] **TASK-3.7:** Testing E2E: expandir/colapsar, navegación mobile
- [ ] **TASK-3.8:** Accessibility audit con axe-core
- [ ] **TASK-3.9:** Deploy y validación cross-browser
- [ ] **TASK-3.10:** Performance audit (Lighthouse score)

**Estimación:** 3-5 días
**Dependencies:** Ninguna (componente independiente)
**Risk:** Low (componente UI self-contained)

---

### Sprint 4: Invoice Spreadsheet UX (Semana 4-5)

**Objetivo:** Detalle de factura tipo hoja de cálculo editable (estilo Odoo)

#### Historias de Usuario:
- [ ] **HU-10:** Como usuario, quiero ver líneas de factura en formato editable
- [ ] **HU-11:** Como usuario, quiero editar cantidades/precios directamente y ver totales recalcular
- [ ] **HU-12:** Como usuario, quiero agregar/quitar líneas rápidamente

#### Criterios de Aceptación:
- [ ] Vista tipo hoja de cálculo con grid editable
- [ ] Celdas editables inline: quantity, unit_price, discount, tax_code
- [ ] Cálculos en tiempo real (<100ms): line_total, tax, grand_total
- [ ] Auto-save progressive (debounce 2s después de último cambio)
- [ ] Indicadores de estado: "unsaved changes", "saving...", "saved"
- [ ] Validaciones inline: quantity >0, price ≥0
- [ ] Agregar línea: botón "+" inline o "Add line" button
- [ ] Eliminar línea: icono de trash con confirmación
- [ ] Responsive: 1 columna en mobile, 3-4 en desktop

#### Tareas Técnicas:
- [ ] **TASK-4.1:** Investigar Odoo 19 invoice detail UX (screenshot analysis)
- [ ] **TASK-4.2:** Elegir grid library: `@ag-grid/react` vs `react-spreadsheet-grid` vs custom
- [ ] **TASK-4.3:** Crear componente `InvoiceSpreadsheet.tsx` con celdas editables
- [ ] **TASK-4.4:** Implementar cálculos en backend: `POST /invoices/{id}/recalculate`
- [ ] **TASK-4.5:** Frontend: debounced auto-save con `useDebounce` hook
- [ ] **TASK-4.6:** Loading states y error handling
- [ ] **TASK-4.7:** Keyboard navigation (↑ ↓ ← →, Enter, Escape)
- [ ] **TASK-4.8:** Validaciones visuales (bordes rojos, tooltips de error)
- [ ] **TASK-4.9:** E2E testing: edición, cálculos, auto-save
- [ ] **TASK-4.10:** Backend: tests de precisión fiscal (rounding, tax calculation)
- [ ] **TASK-4.11:** Performance audit con grandes invoices (50+ líneas)
- [ ] **TASK-4.12:** Deploy y validación con usuario final

**Estimación:** 7-10 días
**Dependencies:** Ninguna (feature independiente)
**Risk:** Medium-high (cálculos fiscales complejos)

---

### Sprint 5: Forms Verticales "One Sprint" (Semana 6-7)

**Objetivo:** Layout profesional vertical para todos los forms del sistema

#### Historias de Usuario:
- [ ] **HU-13:** Como usuario, quiero forms ordenados verticalmente no todo hacia abajo
- [ ] **HU-14:** Como usuario, quiero secciones colapsables para forms largos
- [ ] **HU-15:** Como usuario, quiero ver progreso del form (step indicator)

#### Criterios de Aceptación:
- [ ] Layout multi-columna: máximo 3 columnas en desktop
- [ ] Fieldsets para agrupación lógica: "Información básica", "Datos fiscales", etc.
- [ ] Secciones colapsables con acordeón
- [ ] Progress indicator: steps del form con "Step 1 of 3"
- [ ] Mobile-first: 1 columna siempre en mobile
- [ ] Spacing consistente: gaps de 8px, 16px, 24px
- [ ] Labels above inputs (estándar) vs labels to left (solo desktop)

#### Tareas Técnicas:
- [ ] **TASK-5.1:** Crear `FormSection.tsx` component colapsable
- [ ] **TASK-5.2:** Crear `FormProgress.tsx` con steps indicator
- [ ] **TASK-5.3:** Crear `FormGrid.tsx` con responsive columns (1-2-3)
- [ ] **TASK-5.4:** Investigar "one sprint" layout patterns ( screenshots)
- [ ] **TASK-5.5:** Refactor `InvoiceCreate` form con nuevo layout
- [ ] **TASK-5.6:** Refactor `PartyCreate` form con nuevo layout
- [ ] **TASK-5.7:** Refactor `LeadWithPartyCreate` form con nuevo layout
- [ ] **TASK-5.8:** System fonts stack con `system-ui` para native feel
- [ ] **TASK-5.9:** Focus states y border colors consistentes
- [ ] **TASK-5.10:** Error states y help text styling
- [ ] **TASK-5.11:** E2E testing: keyboard navigation, validation
- [ ] **TASK-5.12:** Accessibility audit (WCAG AA)

**Estimación:** 5-7 días
**Dependencies:** Ninguna (refactor de forms existentes)
**Risk:** Low (mejora visual, sin cambios de lógica)

---

### Sprint 6: Pagos por Cliente (Semana 8)

**Objetivo:** Condiciones de pago configurables por cliente (override de empresa)

#### Historias de Usuario:
- [ ] **HU-16:** Como administrador, quiero configurar condiciones de pago por cliente
- [ ] **HU-17:** Como usuario, quiero ver qué condiciones aplica (company default vs customer override)
- [ ] **HU-18:** Como administrador, quiero ver historial de cambios en condiciones

#### Criterios de Aceptación:
- [ ] Model `CustomerPaymentTerms` con relación a `Party`
- [ ] UI en configuración: Payment terms por customer
- [ ] Override logic: customer terms > company terms
- [ ] Indicador visual: "Using company terms" vs "Using customer terms"
- [ ] Historial: auditoría de cambios de términos
- [ ] Default fallback: company terms si no hay customer override

#### Tareas Técnicas:
- [ ] **TASK-6.1:** Backend: Model `CustomerPaymentTerms` (tenant_id, party_id, terms)
- [ ] **TASK-6.2:** Backend: Migration `add_customer_payment_terms`
- [ ] **TASK-6.3:** Backend: Service `payment_terms.get_effective_terms(party_id)`
- [ ] **TASK-6.4:** Backend: API `GET/POST /customers/{id}/payment-terms`
- [ ] **TASK-6.5:** Frontend: Config UI en settings section
- [ ] **TASK-6.6:** Frontend: Badge en invoice create mostrando términos aplicables
- [ ] **TASK-6.7:** Testing: override logic, defaults, edge cases
- [ ] **TASK-6.8:** Documentation: guía de configuración
- [ ] **TASK-6.9:** Data migration strategy (existentes customers)
- [ ] **TASK-6.10:** Deploy y validación

**Estimación:** 5-7 días
**Dependencies:** Ninguna (feature independiente de lógica de negocio)
**Risk:** Medium (cambio de lógica de negocio, requiere migración)

---

### Sprint 7: Stack Modernization (Semana 9)

**Objetivo:** Actualizar librerías React y patrones de performance

#### Historias de Usuario:
- [ ] **HU-19:** Como sistema, quiero usar librerías modernas para mejor performance
- [ ] **HU-20:** Como desarrollador, quiero patterns actualizados para maintainability

#### Criterios de Aceptación:
- [ ] `react-hook-form` vs controlled components (3x más rápido)
- [ ] `zustand` vs context para state global (menos re-renders)
- [ ] `framer-motion` vs CSS transitions (60fps animaciones)
- [ ] `@radix-ui` + `shadcn/ui` para componentes accesibles
- [ ] Memoización con `React.memo` y `useMemo` donde aplica
- [ ] Code splitting con `React.lazy` + `Suspense`
- [ ] Bundle size analysis: <200KB gzipped

#### Tareas Técnicas:
- [ ] **TASK-7.1:** Install `react-hook-form` + `@hookform/resolvers`
- [ ] **TASK-7.2:** Install `zustand/vanilla` para state management
- [ ] **TASK-7.3:** Install `framer-motion` para animaciones
- [ ] **TASK-7.4:** Install `@radix-ui/*` components (dialog, dropdown, etc.)
- [ ] **TASK-7.5:** Refactor forms a `react-hook-form` (invoice, party, lead)
- [ ] **TASK-7.6:** Implement `useCRMStore` con Zustand para kanban
- [ ] **TASK-7.7:** Animaciones spring con Framer Motion
- [ ] **TASK-7.8:** `React.memo` para cards y listas grandes
- [ ] **TASK-7.9:** `React.lazy` para routes (invoices, receivables, crm)
- [ ] **TASK-7.10:** Bundle analysis con `rollup-plugin-visualizer`
- [ ] **TASK-7.11:** Performance audit baseline vs post-optimization
- [ ] **TASK-7.12:** E2E testing: no regressions en funcionalidad

**Estimación:** 7-10 días
**Dependencies:** Ninguna (upgrade técnico)
**Risk:** Medium (refactor significativo de patterns)

---

### Sprint 8: Polish & Animations (Semana 10-11)

**Objetivo:** Micro-interacciones, animaciones y detalles visuales

#### Historias de Usuario:
- [ ] **HU-21:** Como usuario, quiero feedback visual en todas mis acciones
- [ ] **HU-22:** Como usuario, quiero transiciones suaves entre páginas
- [ ] **HU-23:** Como usuario, quiero loading states claros

#### Criterios de Aceptación:
- [ ] Loading skeletons en lugar de spinners
- [ ] Button states: hover, active, disabled, loading
- [ ] Toast notifications para acciones (success/error)
- [ ] Page transitions: fade + slide con Framer Motion
- [ ] Hover effects elevados: box-shadow transform
- [ ] Focus visible states para accessibility
- [ ] Empty states ilustrados (no solo texto)
- [ ] Error boundaries con graceful fallbacks

#### Tareas Técnicas:
- [ ] **TASK-8.1:** Crear `LoadingSkeleton.tsx` component
- [ ] **TASK-8.2:** Crear `ToastProvider.tsx` con `sonner` o custom
- [ ] **TASK-8.3:** Implementar `AnimatePresence` de Framer Motion en routes
- [ ] **TASK-8.4:** Hover states en botones con `whileHover` scale
- [ ] **TASK-8.5:** Focus rings visibles en todos los inputs
- [ ] **TASK-8.6:** Empty states con ilustraciones SVG o icons
- [ ] **TASK-8.7:** Error boundary con `react-error-boundary`
- [ ] **TASK-8.8:** Micro-interactions: checkbox, radio, toggle animations
- [ ] **TASK-8.9:** Page transition: `/overview` → `/parties` con slide
- [ ] **TASK-8.10:** Performance: asegurar 60fps en animaciones
- [ ] **TASK-8.11:** E2E testing: no regressions visuales
- [ ] **TASK-8.12:** Accessibility audit: keyboard navigation

**Estimación:** 5-7 días
**Dependencies:** Sprint 7 (stack moderno)
**Risk:** Low (mejoras visuales, sin cambios de funcionalidad)

---

### Sprint 9: Testing & Documentation (Semana 12)

**Objetivo:** Cobertura completa de testing y documentación

#### Historias de Usuario:
- [ ] **HU-24:** Como equipo, quiero tests E2E completos para confidence
- [ ] **HU-25:** Como desarrollador, quiero docs claras para onboarding

#### Criterios de Aceptación:
- [ ] E2E coverage: 100% de user flows críticos
- [ ] Component tests: componentes complejos (kanban, spreadsheet)
- [ ] API tests: endpoints nuevos (bulk-status, payment-terms)
- [ ] Documentación: user guide, admin guide, dev setup
- [ ] Accessibility: WCAG AA compliance verificado

#### Tareas Técnicas:
- [ ] **TASK-9.1:** E2E specs: kanban drag & drop, bulk operations
- [ ] **TASK-9.2:** E2E specs: invoice spreadsheet editing
- [ ] **TASK-9.3:** E2E specs: forms verticales, keyboard nav
- [ ] **TASK-9.4:** Component tests: `CrmKanban.tsx`, `InvoiceSpreadsheet.tsx`
- [ ] **TASK-9.5:** API tests: `test_crm_api.py`, `test_payment_terms.py`
- [ ] **TASK-9.6:** Integration tests: end-to-end invoice → spreadsheet
- [ ] **TASK-9.7:** Docs: `USER_GUIDE.md` con screenshots
- [ ] **TASK-9.8:** Docs: `ADMIN_GUIDE.md` para configuración
- [ ] **TASK-9.9:** Docs: `DEV_SETUP.md` actualizado
- [ ] **TASK-9.10:** Accessibility audit con axe DevTools
- [ ] **TASK-9.11:** Performance budget: Lighthouse score >90
- [ ] **TASK-9.12:** Deploy a producción y monitoring

**Estimación:** 5-7 días
**Dependencies:** Todos los sprints anteriores
**Risk:** Low (testing y documentación)

---

## 📈 Métricas de Éxito

### Technical Metrics
- **Performance:** <100ms Time to Interactive
- **Bundle Size:** <200KB gzipped total
- **Lighthouse:** >90 score en todas las categorías
- **Accessibility:** WCAG AA compliant

### Business Metrics
- **Productivity:** +40% en tiempo de完成任务
- **Errores:** -60% en validaciones incorrectas
- **Satisfacción:** +80% en feedback de usuarios
- **Adopción:** +50% en uso de CRM vs spreadsheet

### Development Metrics
- **Velocity:** 5-7 días por sprint (realista)
- **Quality:** 0 critical bugs en producción
- **Coverage:** >80% E2E coverage de flujos críticos

---

## 🚨 Riesgos y Mitigaciones

### Riesgo 1: Drag & Drop Performance
**Probabilidad:** Medium | **Impacto:** High
**Mitigación:** Prototipar @dnd-kit en Sprint 1, validar 60fps antes de full commitment

### Riesgo 2: Cálculos Fiscales Incorrectos
**Probabilidad:** Medium | **Impacto:** Critical
**Mitigación:** Testing exhaustivo de rounding, validation con SRI test environment

### Riesgo 3: Regresiones en UI Refactor
**Probabilidad:** Low | **Impacto:** Medium
**Mitigación:** E2E testing antes/after, screenshot comparisons

### Riesgo 4: Scope Creep
**Probabilidad:** High | **Impacto:** Medium
**Mitigación:** Backlog priorizado, 1 feature a la vez, stakeholder approval

---

## 🔄 Cierre de Sprint

### Checklist por Sprint:
- [ ] **Funcionalidad:** Todas las HUs completadas con criterios de aceptación
- [ ] **Testing:** E2E specs pasando, API tests cubriendo nuevos endpoints
- [ ] **Documentation:** Actualización de STATUS.md, CLAUDE.md
- [ ] **Deploy:** Push a release con tag de versión
- [ ] **Demo:** Walkthrough con stakeholder de funcionalidades
- [ ] **Retro:** Lessons learned registradas en memoria del agente

### Formato de Status Update:

```markdown
## Sprint X: [Nombre] - [Status]
**Fecha:** YYYY-MM-DD
**Duración:** X días
**Outcome:** ✅ Success / ⚠️ Partial / ❌ Blocked

### Completado:
- [x] HU-X: [Descripción] - [Detalles]
- [x] Tareas técnicas: [Resumen]

### Bloqueado:
- [ ] HU-Y: [Razón del bloqueo]

### Próximos Pasos:
1. [Próxima acción]
2. [Próxima acción]

### Lecciones Aprendidas:
- [Lesson learned]
```

---

## 📞 Contacto y Soporte

**Stakeholders:**
- **Product Owner:** [Nombre]
- **Tech Lead:** [Nombre]
- **UX Lead:** [Nombre]

**Comunicación:**
- **Daily:** Standup de 15min en [slack/channel]
- **Weekly:** Sprint review + planning
- **Issues:** GitHub issues con labels `sprint-X`, `priority`

---

**Última actualización:** 2026-07-19
**Próximo Sprint:** Sprint 1 - CRM Kanban Foundation
**Timeline estimado:** 12 semanas (3 meses)