# Estado actual y relevo

Este archivo es la fuente de verdad para retomar la implementacion. Debe
actualizarse al cerrar una sesion de trabajo o cambiar el estado de un sprint.
Los documentos de producto y arquitectura siguen siendo vinculantes para el
alcance y las decisiones.

## Corte verificado

- Fecha: 2026-07-03 17:51 `America/Guayaquil`.
- Rama de trabajo: `release`.
- Commit del corte: consultar `git log -1 --oneline`; este archivo forma parte
  del mismo corte y no mantiene un hash autorreferencial.
- Sprint activo: Sprint 1, en progreso.
- El estado ejecutable descrito aqui debe estar publicado en `release`. Si
  `git status` muestra cambios, una IA debe revisarlos antes de continuar.

## Estado por fase

| Fase | Estado | Evidencia o siguiente puerta |
| --- | --- | --- |
| Sprint 0 | Aprobado | Documentos, ADR, contratos y backlog inicial |
| Sprint 1 | Done | CI verde run 28705977016; criterios con evidencia |
| Sprint 2 | En progreso | Facturacion, nota de credito y SRI |
| Sprint 3 | No iniciado | Cuentas por cobrar |
| Sprint 4 | No iniciado | Cuentas por pagar |
| Sprint 5 | No iniciado | Agente, dashboard y migracion piloto |
| Sprint 6 | No iniciado | Estabilizacion y produccion |

## Implementado en Sprint 1

- Stack local con PostgreSQL 17, Redis 7.4, MinIO, Keycloak 26.6.4, API,
  worker, scheduler y web.
- FastAPI, SQLAlchemy 2 y Alembic con modelos de tenant, usuario, membresia,
  service account, auditoria, idempotencia, outbox, inbox y dead letter.
- Maestros REST tenant-scoped: establecimientos, puntos de emision, categorias
  tributarias, tags, clientes/proveedores y productos.
- Scopes, validacion de membresia activa, politicas de automatizacion y kill
  switch.
- MCP Streamable HTTP con `context.get`, `parties.search`, `parties.create`,
  `products.search` y `products.create`.
- Frontend React/Vite con login de desarrollo y flujo OIDC con Keycloak.
- Seed local repetible, realm de Keycloak importable y Dockerfiles de API/web.
- Pruebas de aislamiento, scopes, idempotencia, auditoria, outbox/inbox/dead
  letter, MCP y accesibilidad.
- PoC automatizado de service accounts contra el stack real
  (`backend/tests/test_service_account_poc.py`): client credentials con claims
  y lifespan <= 300 s, alta/revocacion via API con provisioning en Keycloak,
  rechazo inmediato de un token todavia vigente tras revocar, bloqueo de nueva
  emision con el cliente deshabilitado y rechazo de tokens expirados. Se ejecuta
  con `IAERP_POC=1 uv run pytest tests/test_service_account_poc.py` y el stack
  levantado con `AUTH_MODE=oidc`; sin esa variable la suite se omite.
- Cambio de tenant OIDC multi-tenant probado de extremo a extremo. A nivel API
  (`backend/tests/test_tenant_switch_poc.py`, misma puerta `IAERP_POC=1`):
  `owner` obtiene contexto Norte (roles owner/admin) o Sur (viewer) segun la
  `organization:<alias>` autorizada, un token con `organization:*` (dos
  organizaciones) se rechaza con 403 y un usuario sin membresia en la
  organizacion recibe token sin claim `organization` que la API rechaza con
  403. A nivel UI (`frontend/tests/oidc.spec.ts`, puerta `E2E_OIDC=1` con
  `E2E_USE_RUNNING_APP=1 PLAYWRIGHT_BASE_URL=http://localhost:8088`): login
  PKCE en Norte, datos de Norte visibles, logout, login en Sur y verificacion
  de que los datos de Norte no aparecen; aprobado en escritorio y movil.
- MCP validado con el Inspector oficial en modo CLI contra el stack real:
  Protected Resource Metadata, 401 con `resource_metadata`, catalogo de tools
  filtrado por scopes por tenant y aislamiento de datos. Evidencia sanitizada
  en `docs/evidence/sprint-01-mcp-inspector.md`.
- Dataset `sprint-01-v1` verificado: el seed (`app/initial_data.py`) crea dos
  tenants, usuario multi-tenant, usuarios exclusivos, usuario sin membresia,
  cinco roles, una service account por tenant y maestros distinguibles; se
  ejecuto dos veces seguidas contra PostgreSQL sin errores (idempotente).
- E2E funcionales (`frontend/tests/functional.spec.ts`) aprobados con la API
  en modo dev: alta/edicion de contacto y producto contra la API real,
  aislamiento al cambiar de tenant y error de autorizacion accesible para un
  token restringido. Junto con `a11y.spec.ts` y `oidc.spec.ts` cubren los
  cuatro recorridos E2E del plan en escritorio y movil (12 pruebas).
- Suite de migraciones Alembic validada contra PostgreSQL 17
  (`backend/scripts/validate_migrations.py`): creacion desde cero, downgrade a
  base sin tablas remanentes, upgrade nuevamente y `alembic check` sin drift.
  Se ejecuta local con `DATABASE_URL=...iaerp_migrations` y en el job
  `migrations` del CI.
- CI configurado en `.github/workflows/ci.yml` sin deploy: jobs de backend
  (Ruff, mypy, pytest con PostgreSQL/Redis y reporte JUnit), migraciones,
  contratos (OpenAPI y referencias MCP), frontend (lint, build, Playwright con
  API real), stack OIDC completo (keycloak_poc, validate_oidc_runtime, suites
  PoC de service account y cambio de tenant, PKCE E2E) y seguridad
  (detect-secrets, pip-audit, bandit, npm audit). Todos los pasos reproducibles
  en local fueron ejecutados y aprobados el 2026-07-03; el backend tambien pasa
  contra PostgreSQL (16 pruebas con la de concurrencia incluida).
- Worker Celery saneado: el contenedor corre como usuario `iaerp` (sin
  advertencia de superusuario), worker/scheduler/web tienen healthcheck y
  reportan `healthy`, y se corrigio en `app/workers/tasks.py` un bug de
  event loop (asyncio.run por task ataba el pool asyncpg a un loop cerrado y
  producia fallos intermitentes "attached to a different loop"); tras el fix,
  cero errores en logs con trafico real de outbox.
- ADR 0009 aceptado el 2026-07-03: los siete puntos del PoC bloqueante quedaron
  demostrados y automatizados, incluida la revocacion de membresia con token
  vigente y el rechazo cruzado de audiences API/MCP
  (`backend/tests/test_tenant_switch_poc.py`, 5 pruebas en vivo). Perfil
  adoptado: `fixed-audience-with-resource-server-validation`.
- Revision independiente de arquitectura sobre los cambios OAuth/worker:
  aprobada con observaciones; se aplicaron el hook `worker_process_shutdown`
  (cierre del loop y dispose del engine) y la aclaracion de unicidad de
  `client_id` en `auth.py`. Observacion abierta: si el job `oidc` de CI muestra
  flakiness por el `sleep(3)` del test de expiracion, subir el margen o usar
  retry acotado.

## Validacion del corte

Comandos ejecutados el 2026-07-03:

```bash
cd backend
uv run ruff check .
uv run mypy app
uv run pytest -q

cd ../frontend
npm run lint
npm run build
npm run test:e2e
```

Resultados:

- Backend y migraciones: Ruff aprobado.
- Backend: mypy estricto aprobado sobre 31 archivos.
- Backend: 15 pruebas aprobadas en SQLite y 16 contra PostgreSQL (incluye la
  de concurrencia). Las 8 del PoC en vivo pasan con `IAERP_POC=1` y el stack
  OIDC arriba (3 de service account + 5 de cambio de tenant/audiences).
- Se corrigio en `app/core/auth.py` la comparacion de `expires_at` de service
  accounts: SQLite devuelve datetimes sin zona y rompia la validacion de
  expiracion en pruebas.
- Frontend: lint y build aprobados.
- Frontend: 14 pruebas Playwright aprobadas en escritorio y movil (a11y con
  reflow a 320 CSS px y 200% zoom, y funcionales con API dev), mas el recorrido
  OIDC PKCE con el stack completo en ambos viewports (`npm run test:e2e:oidc`).
- `http://localhost:8000/health/ready`: HTTP 200.
- `http://localhost:8088`: HTTP 200.
- Discovery OIDC de Keycloak: HTTP 200.
- Los ocho servicios de Compose estan ejecutandose; los servicios con
  healthcheck reportan `healthy`.

El PoC de Keycloak confirma organization unica, audience fija y discovery. No
confirma soporte RFC 8707 estricto: Keycloak acepta un `resource` ajeno. IAERP
debe mantener validacion estricta de audience/resource en API y MCP.

## Pendiente para cerrar Sprint 1

- Los ocho pendientes tecnicos del corte anterior quedaron cerrados el
  2026-07-03 (ver "Implementado en Sprint 1" y la matriz del ADR 0009).
- QA Reliability ejecuto la revision independiente el 2026-07-03: NO-GO
  condicional con dos brechas, ambas atendidas en la misma sesion: (a) se
  agrego la prueba de reflow a 320 CSS px y 200% zoom en `a11y.spec.ts`
  (aprobada en escritorio y movil) y (b) `test:e2e:oidc` ahora corre en ambos
  viewports. La condicion final quedo cumplida el 2026-07-04 con el push
  autorizado a `release` y el primer run verde del CI (run 28705977016, seis
  jobs incluidos OIDC full stack y seguridad, artefactos publicados):
  https://github.com/ceduardodch/iaerp/actions/runs/28705977016
  Sprint 1 queda marcado como Done.
- Observaciones menores del QA sin bloquear: los specs de a11y usan API
  mockeada; `pytest-randomly` valido la independencia de orden pero no esta en
  la configuracion permanente del proyecto.

## Ejecucion local

```bash
docker compose up -d
docker compose ps
```

Accesos locales:

- Aplicacion: `http://localhost:8088`
- API/OpenAPI: `http://localhost:8000/docs`
- Keycloak: `http://localhost:8080`
- MinIO: `http://localhost:9001`

Usuario demo OIDC, solo local:

- Usuario: `owner`
- Clave: `DemoPass123!`

El modo de desarrollo de Vite puede usar `owner@iaerp.local` y el tenant
`11111111-1111-4111-8111-111111111111` sin password. No habilitar
`AUTH_MODE=dev` en ambientes compartidos o productivos.

## Siguiente trabajo recomendado

1. Ejecutar la revision independiente de QA y actualizar Sprint 1 a `Done` solo
   si todos sus criterios de aceptacion tienen evidencia.
2. Con autorizacion humana, commitear el estado de esta sesion en `release`
   para que el corte publicado coincida con este archivo.
3. Iniciar la planificacion de Sprint 2 (facturacion, nota de credito y SRI).

## Regla de relevo

Una IA nueva debe leer, en este orden:

1. `AGENTS.md`.
2. Este archivo.
3. `docs/sprints/sprint-01.md`.
4. `docs/09-testing-quality.md`.
5. Los ADR relacionados con el cambio que vaya a realizar.

Antes de modificar codigo debe ejecutar `git status`, comprobar los servicios y
no descartar cambios existentes. No debe crear ramas, hacer push, merge ni abrir
PR sin autorizacion explicita.
