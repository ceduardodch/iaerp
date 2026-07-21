# IAERP - Claude AI Assistant Configuration

> ⚠️ **ANTES DE TOCAR NADA, LEE [`COORDINACION_IA.md`](COORDINACION_IA.md)** —
> coordinación entre IAs (quién está activo, estado real de sprints, ramas,
> regla de no mutear tests). Obligatorio leerlo primero.

**Proyecto:** IAERP - ERP Ecuatoriano con facturación electrónica SRI
**Stack:** FastAPI + SQLAlchemy + PostgreSQL + React 19 + TypeScript
**Arquitectura:** Monolito modular multi-tenant

## Contexto del Proyecto

IAERP es un ERP ecuatoriano especializado en facturación electrónica SRI con integración MCP (Model Context Protocol). El sistema incluye:

- **Facturación electrónica** con validaciones SRI tiempo real
- **Cartera (receivables)** con aging y cobranza
- **CRM de prospectos** con pipeline de ventas
- **Integración MCP** para agentes AI
- **Multi-tenancy** con aislamiento completo de datos

## Estructura del Proyecto

```
iaerp/
├── backend/              # FastAPI + SQLAlchemy
│   ├── app/
│   │   ├── api/        # Endpoints REST
│   │   ├── core/       # Auth, config, timezones
│   │   ├── db/         # Session, base class
│   │   ├── models/     # SQLAlchemy models
│   │   ├── schemas/    # Pydantic schemas
│   │   ├── services/   # Business logic
│   │   ├── workers/    # Celery tasks
│   │   └── integrations/ # SRI, Gmail, notifications
│   ├── migrations/     # Alembic migrations
│   └── tests/          # Backend tests
├── frontend/           # React 19 + TypeScript
│   ├── src/
│   │   ├── components/ # React components
│   │   ├── api.ts      # API client + types
│   │   └── App.tsx     # Main application
│   └── tests/          # Playwright E2E tests
├── compose.yaml        # Docker compose local
└── docs/               # Documentación
```

## Stack Tecnológico

### Backend
- **Framework:** FastAPI + SQLAlchemy 2.0 async
- **Database:** PostgreSQL 17 + Alembic migrations
- **Workers:** Celery + Redis
- **Storage:** MinIO (S3-compatible)
- **Auth:** Keycloak OAuth 2.1 + OIDC

### Frontend
- **Framework:** React 19 + TypeScript
- **Build:** Vite
- **Testing:** Playwright (E2E)
- **State:** TanStack Query (React Query)
- **Styling:** Tailwind CSS con variables CSS personalizadas

## Patrones Arquitectónicos

### Backend
- **Tenant-scoped:** Todas las queries incluyen `tenant_id`
- **Idempotency:** Headers `Idempotency-Key` en operaciones de escritura
- **Audit:** Sistema de auditoría con `append_audit`
- **Workers:** Procesamiento asíncrono con outbox pattern
- **Scopes:** Autorización granular por recurso

### Frontend
- **Components:** `ErpPageHeader`, `ErpPanel`, `ErpFormPanel` (patrón consistente)
- **Data fetching:** TanStack Query con invalidación automática
- **Forms:** FormData + API client con idempotency
- **Types:** TypeScript sincronizado con backend schemas

## Módulos Implementados

### ✅ Sprint 1-3 Completados
- **Plataforma:** Tenants, users, memberships, service accounts
- **Maestros:** Parties, products, establishments, emission points
- **Facturación:** Invoices, credit notes, SRI transmission
- **Cartera:** Receivables, aging, payments, collections
- **CRM:** Leads, activities, pipeline básico
- **MCP:** Tools para invoices, receivables, prompts anti-injection

### 🚧 En Progreso
- **UI/UX Improvements:** Plan de 12 semanas para modernizar interfaces
- **Integración Gmail:** OAuth 2.0 + sincronización (placeholder implementado)

## Desarrollo Local

### Levantar stack completo:
```bash
docker compose up -d
```

### Servicios:
- **API:** http://localhost:8000 (OpenAPI: /docs)
- **Frontend:** http://localhost:8088
- **Keycloak:** http://localhost:8080
- **MinIO:** http://localhost:9001

### Usuario demo (local):
- **Email:** owner@iaerp.local
- **Tenant ID:** 11111111-1111-4111-8111-111111111111
- **Password:** (none en modo dev)

### Testing:
```bash
# Backend
cd backend
uv run pytest tests/ -v

# Frontend
cd frontend
npm run test:e2e
```

## Convenciones de Código

### Backend
- **Models:** SQLAlchemy con `UUIDPrimaryKeyMixin`, `TimestampMixin`, `TenantEntityMixin`
- **Services:** Async con inyección de `session` y `context`
- **API:** `execute_idempotent` para operaciones de escritura
- **Auth:** `require_scopes()` con scopes granulares

### Frontend
- **Components:** PascalCase para componentes, camelCase para archivos
- **Types:** Sincronizados con backend schemas (Lead vs LeadCreate)
- **API:** `apiRequest<T>(token, path, init)` con manejo de errores
- **UI:** Patrones `Erp*` para consistencia visual

## Convenciones de Git

### Branch strategy:
- **main:** Rama estable, solo merge desde release
- **release:** Desarrollo integrado, listo para producción
- **feature/**: Branches temporales para features grandes

### Commit messages:
- Formato convencional: `feat(scope): description`
- CRM example: `feat(crm): implementar MVP de CRM de prospectos`
- Incluir `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>`

## Prioridades del Producto

### Roadmap General:
1. **Estabilidad:** Sprints 1-3 (completados ✅)
2. **Usabilidad:** UI/UX improvements (plan creado)
3. **Integraciones:** Gmail Workspace, Calendar
4. **Expansion:** Más módulos de ERP

### Current Focus:
- **CRM Enhancement:** Pipeline kanban arrastrable
- **Invoice UX:** Detalle tipo hoja de cálculo
- **Modernización:** Forms profesionales y sidebar colapsible

## Recursos de Desarrollo

### Documentación clave:
- **STATUS.md:** Fuente de verdad del estado del proyecto
- **Sprints docs:** `docs/sprints/sprint-*.md`
- **ADRs:** Decisiones arquitectónicas en `docs/adrs/`

### Testing:
- **CI:** `.github/workflows/ci.yml` con tests completos
- **E2E:** Playwright specs en `frontend/tests/`
- **Backend:** Pytest en `backend/tests/`

### Troubleshooting:
- **Lock files:** `uv.lock` y `package-lock.json` committeados
- **Migrations:** `alembic check` para validar schema
- **Docker:** `docker compose ps` para verificar servicios

## Configuración de Agentes IA

### MCP Server:
- **Host:** localhost:8000
- **Tools:** invoices, receivables, parties, products
- **Auth:** Service accounts con scopes limitados

### Scopes disponibles:
- `leads:read`, `leads:write` - CRM operations
- `communications:read`, `communications:write` - Gmail integration
- `invoices:*` - Facturación completa
- `receivables:*` - Cartera y cobranza

## Próximos Pasos

1. **Revisar QUICK_START.md** - Guía rápida de 20 segundos para retomar trabajo
2. **Revisar ISSUE_TRACKING.md** - Tareas 1x1 del sprint actual
3. **Ver SPRINT_STATUS.md** - Status detallado y decisiones técnicas
4. **Revisar BACKLOG.md** - Alcance completo si hay dudas
5. **Seleccionar próxima tarea** - Del backlog priorizado
6. **Trabajar 1x1** - Una tarea a la vez con cierre claro
7. **Actualizar sprint status** - Documentar progreso al cerrar

## 📁 Sistema de Documentación (Work 1x1)

**Documentos principales:**
- **QUICK_START.md** - Guía rápida 20 segundos para retomar trabajo
- **CLAUDE.md** - Este archivo (setup completo del proyecto)
- **BACKLOG.md** - Alcance detallado (12 semanas, 9 sprints)
- **SPRINT_STATUS.md** - Status de sprints y decisiones técnicas
- **ISSUE_TRACKING.md** - Tareas 1x1 para no perder contexto entre sesiones
- **docs/STATUS.md** - Fuente de verdad del proyecto

**Cómo usar el sistema:**
1. **Al iniciar sesión:** "Revisar QUICK_START.md" (20 segundos)
2. **Para continuar:** "Revisar ISSUE_TRACKING.md y continuar con TASK-X.Y"
3. **Si dudas técnicas:** Revisar SPRINT_STATUS.md (Decision Log)
4. **Si se acaban tokens:** Todo documentado, next session → retomar
5. **Al cerrar sesión:** Actualizar ISSUE_TRACKING.md con próxima tarea pendiente

**Beneficios del sistema:**
- ✅ **Continuidad:** Sin perder contexto entre sesiones
- ✅ **Tokens:** Optimiza uso, todo documentado para retomar
- ✅ **Trazabilidad:** Decisiones técnicas y riesgos documentados
- ✅ **Colaboración:** Work 1x1 sin interferir con otros cambios
- ✅ **Progreso:** Medible por tareas completadas vs totales

## Contacto y Soporte

- **Repo:** https://github.com/ceduardodch/iaerp
- **Issues:** GitHub issues para bugs y features
- **Documentación:** `docs/` directory para decisiones arquitectónicas

---

**Última actualización:** 2026-07-19
**Sprint activo:** UI/UX Improvements Plan
**Estado:** En desarrollo activo