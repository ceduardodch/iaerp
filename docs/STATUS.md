# Estado actual y relevo

Este archivo es la fuente de verdad para retomar la implementacion. Debe
actualizarse al cerrar una sesion de trabajo o cambiar el estado de un sprint.
Los documentos de producto y arquitectura siguen siendo vinculantes para el
alcance y las decisiones.

## Corte verificado

- Fecha: 2026-07-03 09:13 `America/Guayaquil`.
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
| Sprint 1 | En progreso | Plataforma ejecutable; faltan cierres indicados abajo |
| Sprint 2 | No iniciado | Facturacion, nota de credito y SRI |
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
- Backend: mypy estricto aprobado sobre 28 archivos.
- Backend: 8 pruebas aprobadas.
- Frontend: lint y build aprobados.
- Frontend: 6 pruebas Playwright aprobadas en escritorio y movil.
- `http://localhost:8000/health/ready`: HTTP 200.
- `http://localhost:8088`: HTTP 200.
- Discovery OIDC de Keycloak: HTTP 200.
- Los ocho servicios de Compose estan ejecutandose; los servicios con
  healthcheck reportan `healthy`.

El PoC de Keycloak confirma organization unica, audience fija y discovery. No
confirma soporte RFC 8707 estricto: Keycloak acepta un `resource` ajeno. IAERP
debe mantener validacion estricta de audience/resource en API y MCP.

## Pendiente para cerrar Sprint 1

- Completar y automatizar el PoC de service account: client credentials,
  expiracion, revocacion y rechazo inmediato con token vigente.
- Probar el cambio de tenant OIDC con un usuario multi-tenant de extremo a
  extremo.
- Validar MCP con un cliente/Inspector real y guardar evidencia sanitizada.
- Implementar el dataset versionado `sprint-01-v1` descrito en el plan de
  pruebas y ampliar E2E desde accesibilidad hacia flujos funcionales.
- Ejecutar Alembic contra PostgreSQL desde cero, downgrade/upgrade y
  `alembic check` como suite automatizada.
- Agregar CI solo para lint, tipos, pruebas, migraciones, contratos y build. No
  agregar deploy; Coolify desplegara exclusivamente desde `main`.
- Corregir la advertencia del worker Celery sobre usuario/grupo del contenedor y
  agregar healthchecks para worker, scheduler y web.
- Revisar y aceptar o sustituir ADR 0009 cuando se complete la matriz OAuth.

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

1. Convertir el PoC OAuth pendiente en pruebas automatizadas.
2. Implementar `sprint-01-v1` con dos tenants y roles diferenciados.
3. Automatizar migraciones PostgreSQL y E2E funcionales.
4. Cerrar la deuda de lint/healthchecks y configurar CI.
5. Ejecutar la revision independiente de QA y actualizar Sprint 1 a `Done` solo
   si todos sus criterios de aceptacion tienen evidencia.

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
