# Guía de Desarrollo — IAERP

Cómo levantar, probar y contribuir al proyecto localmente.

> Complementa: [`USER_GUIDE.md`](USER_GUIDE.md), [`ADMIN_GUIDE.md`](ADMIN_GUIDE.md),
> y la raíz [`AGENTS.md`](../AGENTS.md) / [`COORDINACION_IA.md`](../COORDINACION_IA.md)
> (reglas para sesiones de IA).

## 1. Stack

- **Backend:** FastAPI + SQLAlchemy 2.0 async + PostgreSQL 17 + Alembic. Gestor
  de paquetes **uv**. Workers Celery + Redis. Almacenamiento MinIO (S3).
- **Frontend:** React 19 + TypeScript (estricto, `noUncheckedIndexedAccess`) +
  Vite (Rolldown) + TanStack Query. Tests E2E con Playwright, lint con oxlint.
- **Auth:** Keycloak (OIDC) en producción; modo `dev` local.

## 2. Levantar el stack completo

```bash
docker compose up -d
```

Servicios y puertos:

| Servicio | URL / Puerto | Notas |
|----------|--------------|-------|
| API | http://localhost:8000 | OpenAPI en `/docs` |
| Frontend | http://localhost:8088 | |
| Keycloak | http://localhost:8080 | Identidad OIDC |
| MinIO | http://localhost:9001 | Consola S3 |
| PostgreSQL | localhost:55432 | (contenedor: 5432) |
| Redis | localhost:6379 | |

El contenedor `api` corre migraciones (`alembic upgrade head`) y siembra datos
(`python -m app.initial_data`) antes de arrancar `uvicorn`.

### Usuario demo (modo dev)
- **Email:** `owner@iaerp.local`
- **Tenant ID:** `11111111-1111-4111-8111-111111111111`
- **Password:** ninguna en modo dev

## 3. Desarrollo del frontend

```bash
cd frontend
npm install
npm run dev        # servidor Vite (proxya /api y /mcp a :8000)
npm run build      # tsc -b + vite build (cero errores TS)
npm run lint       # oxlint
npm run test:e2e   # Playwright (levanta su propio dev server)
```

Correr un solo spec o proyecto:
```bash
npx playwright test invoice-spreadsheet.spec.ts            # un archivo
npx playwright test --project=chromium                     # solo escritorio
npx playwright test --project=mobile                       # viewport 375px
```

- Los proyectos Playwright son **chromium** (escritorio) y **mobile** (375×667).
  Los tests de layout específico de escritorio hacen `test.skip` en `mobile` con
  razón explícita.
- **Specs mockeados** (usan `page.route`, no requieren backend):
  `invoice-spreadsheet`, `invoice-payment-terms`, `invoices-a11y`. Corren local
  sin levantar la API — útiles para verificación rápida.

## 4. Desarrollo del backend

```bash
cd backend
uv run --frozen ruff check .          # lint
uv run --frozen mypy app              # tipos
uv run --frozen pytest -q             # tests (requieren postgres de test)
uv run --frozen alembic upgrade head  # migraciones
uv run --frozen alembic check         # validar schema vs modelos
```

**Zona horaria en tests:** para fechas fiscales usa
`app.core.timezones.today_in_fiscal_timezone()` (America/Guayaquil), NO
`date.today()`: en CI (UTC) esto último causa flakes entre 00:00–05:00 UTC.

## 5. Convenciones

- **Backend:** modelos con mixins (`UUIDPrimaryKeyMixin`, `TimestampMixin`,
  `TenantEntityMixin`); servicios async con `session` + `context`; escrituras con
  `execute_idempotent`; autorización con `require_scopes()`. Toda query incluye
  `tenant_id`.
- **Frontend:** componentes `Erp*` para consistencia visual; data fetching con
  TanStack Query; tipos sincronizados con los schemas del backend; acceso a la
  API con `apiRequest<T>(token, path, init)`.
- **Bundle:** la sección CRM se carga con `React.lazy` (arrastra dnd-kit +
  framer-motion); las dependencias estables van a un chunk `vendor` para caching.

## 6. CI (`.github/workflows/ci.yml`)

Jobs: **Backend** (ruff + mypy + pytest), **Frontend** (lint + build + Playwright
contra API real), **OIDC/full stack**, **PostgreSQL migrations**, **Security**,
**YAML contracts**, **Coolify deployment config**.

**Regla de oro:** nunca borres ni debilites una aserción para "desbloquear el
CI". Si un test falla: arregla la app (bug real) o corrige el selector/tolerancia
del test preservando su intención.

## 7. Ramas y despliegue

- **`release`:** rama de trabajo integrada (preprod). Todo el desarrollo llega
  aquí primero; se espera CI verde antes de acumular más.
- **`main`:** producción. Coolify despliega SRI real desde `main`. Solo se
  promueve vía PR `release → main` con CI verde.

Antes de pushear: `git fetch` y confirma la rama. Ver reglas completas de
coordinación entre sesiones de IA en [`COORDINACION_IA.md`](../COORDINACION_IA.md).

## 8. Troubleshooting

- **Lock files:** `uv.lock` y `package-lock.json` están committeados; úsalos.
- **`docker compose ps`** para verificar el estado de los servicios.
- **Frontend E2E rojo con backend requerido:** verifica que la API responda en
  `http://127.0.0.1:8000/health/ready`.
