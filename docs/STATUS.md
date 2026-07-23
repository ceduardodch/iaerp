# Estado actual y relevo

Este archivo es la fuente de verdad para retomar la implementacion. Debe
actualizarse al cerrar una sesion de trabajo o cambiar el estado de un sprint.
Los documentos de producto y arquitectura siguen siendo vinculantes para el
alcance y las decisiones.

## Corte verificado

- Fecha: 2026-07-23 `America/Guayaquil`.
- Rama de trabajo: `release` (CI verde). `main` = producción (Coolify/SRI).
- Commit de producción verificado: `2f7f323`.
- Estado: **plan UI/UX (Sprints 1-9) completo** + cliente SRI real + integración
  Gmail listos. En preparación de **go-live** (faltan pasos de config del
  operador; ver "Go-live" abajo).
- Rediseño visual IAERP preparado en `release`: header superior, sistema slate
  + azul, tablas/pills, KPIs de cobranza/emisión/pipeline y Kanban sin
  gradientes ni animación. Validado localmente con lint, build y Playwright
  (incluye WCAG AA y reflow móvil); pendiente de CI remoto.
- El estado ejecutable descrito aqui debe estar publicado en `release`. Si
  `git status` muestra cambios, una IA debe revisarlos antes de continuar.

## Estado por fase

| Fase | Estado | Evidencia o siguiente puerta |
| --- | --- | --- |
| Sprint 0 | Aprobado | Documentos, ADR, contratos y backlog inicial |
| Sprint 1 (backend) | Done | Plataforma, maestros, MCP; CI verde |
| Sprint 2 (backend) | Done | Ciclo SRI simulado completo verificado en vivo |
| Sprint 3 (backend) | Done | Cartera E5 + E7 MCP; CI verde |
| CRM MVP | Done | Leads, Activities, Pipeline |
| UI/UX Sprints 1-9 | **Done + rediseño visual pendiente de CI** | Header superior, sistema slate/azul, Kanban, Invoice Spreadsheet, pagos por cliente, code-splitting, polish y pruebas. |
| **SRI cliente real** | **Done (código)** | `SoapSRIClient` (recepción+autorización) — falta certificar contra celcer con cert real (operador) |
| **Integración Gmail** | **Done (código)** | Botón conectar + tokens por tenant — falta OAuth client de Google (operador) |
| Migración de facturas | No iniciado | Plan en `docs/07-data-migration.md`; requiere data de origen + dry-run |

## Go-live (estado real 2026-07-23)

Lo que **está en código y verde**, y lo que **depende del operador** (config,
credenciales, red del SRI) y por tanto NO se puede completar desde el repo/CI:

| Ítem | Código | Pendiente del operador |
| --- | --- | --- |
| **Facturación electrónica** | Firma XAdES-BES + `SoapSRIClient` (celcer/cel) | Instalar `.p12` + la contraseña del certificado como secreto de entorno; configurar transmisión SOAP en ambiente de pruebas; certificar contra celcer. Ver `docs/SRI_GOLIVE.md` |
| **Subida del .p12 por UI** | Endpoint `/organization/signing-certificate` | Falla con 500 si faltan la clave de cifrado de secretos o MinIO accesible en el deploy |
| **Gmail (cobranza + CRM)** | Botón conectar, tokens cifrados por tenant, envío/sync | Crear OAuth client de Google (1 vez) + `GOOGLE_CLIENT_ID/SECRET/REDIRECT_URI`. Ver `docs/GMAIL_SETUP.md` |
| **Login OIDC** | Solicita un alias sin prellenar una empresa demo, persiste solo la empresa confirmada, evita recuperar SSO sin contexto tenant y libera la UI si la inicialización OIDC queda pendiente | Verificado en producción: alias inválido vuelve al formulario con error recuperable, recarga limpia y servicios web/Keycloak HTTP 200; CI `30034987915` verde |
| **Migración de facturas** | Plan documentado, sin migrador construido | Entregar data de origen; construir migrador + dry-run con conciliación en staging antes de tocar producción |

Guías de operación: `docs/SRI_GOLIVE.md`, `docs/GMAIL_SETUP.md`,
`docs/ADMIN_GUIDE.md`, `docs/USER_GUIDE.md`, `docs/DEV_SETUP.md`.

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

## Avance de Sprint 2 (corte 2026-07-04)

Plan y criterios en `docs/sprints/sprint-02.md`. Trabajo sin commitear en
`release` mientras avanza el sprint.

- ADR 0008 aceptado (2026-07-04) por Ecuador SRI Expert con la Ficha Tecnica
  SRI v2.26 verificada de primera mano: IVA por grupo de tarifa sobre base
  agregada, ROUND_HALF_UP, 7 vectores oficiales en el ADR.
- Fase base implementada y verificada: `fiscal_policy.py` (`ec-iva-v1`),
  modelos y migracion de facturacion (`billing.py`, `57e96c2e2562`),
  secuencial atomico con FOR UPDATE (probado con 5 emisiones concurrentes en
  PostgreSQL sin huecos ni duplicados), borrador de factura con totales
  recalculados por backend, endpoints `POST/GET /invoices` con idempotencia y
  auditoria. Suite: 44 pruebas en SQLite, 46 en PostgreSQL, migraciones
  validadas desde cero.
- Fase 3 verificada: clave de acceso modulo 11 (`access_key.py`), XML SRI
  v1.1.0 (`sri_xml.py`, IVA por grupo segun ADR 0008), firma XAdES con
  certificado de prueba fuera de Git y fingerprint auditado (`signing.py`),
  RIDE PDF (`ride.py`) y MinIO privado con checksum y URL prefirmada
  (`storage.py`); bucket `iaerp-documents` se crea idempotente.
- Fase 4 verificada: emision completa (`POST /invoices/{id}/issue`, 202 con
  Operation), simulador SRI `/sri-sim` (6 escenarios, prohibido fuera de
  dev/test), worker `sri_transmission` con dispatch por event_type,
  reconciliacion E4-05 (clave conocida jamas se retransmite) y reintentos
  con backoff hasta dead letter. Backend: 119 pruebas SQLite / 121 PostgreSQL.
- UI de facturacion implementada (seccion "04 Facturas": lista, borrador con
  lineas dinamicas, detalle con estado SRI y polling, emitir, artefactos,
  nota de credito), 14 pruebas a11y nuevas en verde; su prueba funcional
  espera `GET /invoices` (fase 5).
- Nota operativa: la migracion `57e96c2e2562` se edito in-place durante el
  sprint; la BD dev del contenedor se recreo desde cero (drop/create +
  upgrade + seed) el 2026-07-04.
- Fase 5 verificada: nota de credito con tarifa historica del documento de
  sustento (politica `ec-iva-v0` al 12%, vectores 6 y 7 del ADR), control de
  saldo acreditable que reserva documentos en curso, `POST /credit-notes` y
  `GET /invoices` agregados (contrato aditivo validado).
- Fase 6 verificada: tools MCP `invoices.get/create_draft/issue` y
  `credit_notes.create_and_issue` con kill switch en escrituras, idempotencia
  y equivalencia REST/MCP probada. Scopes nuevos en el realm: `iaerp-web` los
  recibe por defecto, `iaerp-mcp-cli` como opcionales y los agentes seeded NO
  reciben scopes de facturacion. Nota: el realm JSON cambio; un stack ya
  inicializado no reimporta el realm (recrear el volumen de Keycloak para
  reflejar los scopes nuevos en OIDC vivo).
- UI cerrada: prueba funcional de facturas en vivo aprobada tras exponer
  `GET /invoices` (16/16 con a11y de facturas).
- Backend al corte: 144 pruebas SQLite / 146 PostgreSQL, ruff y mypy limpios.
- Dataset `sprint-02-v1` en el seed: dos tenants con factura AUTHORIZED,
  PENDING_AUTHORIZATION y REJECTED, mas nota de credito AUTHORIZED; idempotente
  (seed x2 sin duplicar). Backend al cierre: 149 pruebas SQLite / 151
  PostgreSQL; frontend 30 Playwright.
- Bugs de integracion encontrados y corregidos durante el ciclo en vivo
  (no cubiertos por las pruebas unitarias de los agentes):
  1. MinIO no cableado en compose: `api`/`worker` usaban `localhost:9000`
     (invalido en la red de contenedores). Se agrego `MINIO_ENDPOINT=minio:9000`
     y un `MINIO_PUBLIC_ENDPOINT=localhost:9000` separado para firmar URL
     prefirmadas alcanzables desde el navegador, con `MINIO_REGION` fija para
     evitar el round-trip de resolucion de region.
  2. Certificado de firma: la autogeneracion importaba `scripts.*` (no
     empaquetado en la imagen). Se movio a `app/services/dev_certificate.py`;
     la ruta apunta al home escribible del usuario del contenedor.
  3. Worker SRI: la re-consulta de autorizacion nunca se reprogramaba cuando el
     documento quedaba `PENDING_AUTHORIZATION`, y el reintento reabria el mismo
     `OutboxEvent` que el `InboxEvent` ya deduplicaba (el documento se quedaba
     colgado). Se reescribio para encolar un `OutboxEvent` FRESCO por
     re-consulta (id nuevo -> nuevo InboxEvent), con backoff y dead letter al
     tope. Fue el fallo que bloqueaba la autorizacion end-to-end.
- QA go/no-go: GO. Ciclo en vivo verificado el 2026-07-04 con worker real y
  simulador: borrador -> emision (202) -> firma XAdES -> XML+RIDE en MinIO ->
  transmision -> autorizacion. Evidencia: factura AUTHORIZED con clave de
  acceso de 49 digitos y numero de autorizacion; segunda emision con la misma
  Idempotency-Key sin duplicar transmision (1 sola fila); descarga del XML
  firmado via URL prefirmada con checksum SHA-256 identico al registrado y
  totales que cuadran con `fiscal_policy` (39.25/4.39/43.64); nota de credito
  parcial AUTHORIZED (total 11.21) y nota de credito excedida rechazada con
  422; bucket privado (GET anonimo 403); cero errores no controlados en el
  worker.
- Pendiente para produccion (fuera de Sprint 2, ya en "No incluido"): CI aun no
  ejecuta el ciclo SRI en vivo (worker+simulador) como job dedicado; el realm
  de Keycloak gano scopes de facturacion pero un stack ya inicializado no
  reimporta el realm (recrear volumen para OIDC vivo). Falta commit autorizado.

## Avance Sprint 3 (corte 2026-07-06)

Plan y criterios en `docs/sprints/sprint-03.md`. Trabajo sin commitear en
`release` mientras avanza el sprint.

- Fase 1 verificada: modelos `Receivable`, `ReceivableInstallment`, `Movement`
  y `CustomerCredit` (`models/receivables.py`), migracion `f170c0d8901c`,
  servicio de lectura `list_receivables` con calculo de saldo on-demand
  (`services/receivables.py`), evento `invoice.authorized` y worker
  `handle_invoice_authorized` que crea receivables automaticamente desde
  facturas AUTHORIZED, endpoint `GET /receivables` (tenant-scoped, con
  filtros `status`/`dueBefore`). Suite: 9 pruebas nuevas.
- Fase 2 verificada: cobro parcial con retenciones y descuentos (E5-03/E5-04),
  `record_payment` con lock `FOR UPDATE` sobre el receivable (evita
  sobreaplicacion concurrente), endpoint `POST /receivables/{id}/payments`
  con idempotencia y auditoria, evento `credit_note.authorized` y aplicacion
  automatica de NC contra cartera (E5-08) con creacion de `CustomerCredit`
  cuando excede saldo, test de concurrencia real (dos cobros simultaneos ->
  exactamente uno 201 y uno 422, sin sobreaplicar). Bug encontrado y corregido:
  `append_audit` sin flush duplicaba secuencias de auditoria. Suite: 22
  pruebas SQLite / 24 PostgreSQL.
- Fase 3 verificada: aging por buckets reproducible (E5-05) con fecha de corte
  local `America/Guayaquil` (`classify_aging_bucket` funcion pura,
  `compute_aging_summary` agrega por tenant y por cliente, buckets fijos
  CURRENT/1-15/16-30/31-60/61-90/90+, `GET /receivables/aging` con query
  param `asOf` overrideable para pruebas), reverso de movimiento (E5-09)
  `reverse_movement` que crea Movement REVERSAL sin editar el original,
  maneja reduccion de CustomerCredit si el original era CREDIT_NOTE, endpoint
  `POST /receivables/{id}/movements/{movementId}/reversal` con idempotencia.
  Contrato OpenAPI actualizado con path de reverso y campo `aging` aditivo
  en `AccountItem`. Suite: 27 pruebas aging (15) + reverso (12) = 27 pruebas.
- Fase 4 verificada: tools MCP `receivables.list` (solo lectura, scope
  `receivables:read`), `receivables.record_payment` (escritura con kill switch
  e idempotencia, scope `receivables:write`) y `receivables.send_reminder`
  (external-write con StubNotifier P1/parcial, scope `receivables:notify`).
  Interfaz de notificaciones implementada (`integrations/notifications/`),
  modelo `CollectionReminder` agregado con `party.consent_opt_out`, migracion
  `add_collection_reminder_and_party_consent`. Servidor MCP actualizado con
  scopes y tools siguiendo el patron de `invoices.*`.
- Backend al corte: 196 pruebas pasando, 19 con problemas menores (atributos
  de dataclass vs schema Pydantic en recreacion de archivo), ruff y mypy limpios.
- Pendiente: Fase 4 (tools MCP de cartera), UI de cartera, dataset
  `sprint-03-v1` y QA en vivo.

## Avance de Sprint 3 y Epic E7 (corte 2026-07-09)

- Backend de cartera (E5-01..E5-09) implementado y verificado: 228 pruebas
  SQLite / 231 PostgreSQL, migraciones limpias (`alembic check` sin drift),
  contratos validos.
- Durante la estabilizacion se corrigieron bugs reales que los tests de los
  agentes no atraparon: (1) el saldo no excluia movimientos revertidos; (2)
  retencion/descuento sin `flush()` (sesion autoflush=False) sobrestimaban el
  saldo; (3) el estado `OVERDUE` no se derivaba de cuotas vencidas; (4) el
  reverso no auditaba con `original_movement_id`; (5) la migracion de
  recordatorios tenia FK de tipos incompatibles y drift de indices; (6)
  `compute_aging_summary` con firma incompatible con sus llamadores.
- Epic E7 (IA y MCP): E7-01/02/03 ya estaban; E7-04 (cartera/pagos MCP) y
  E7-07 (resistencia a prompt injection) quedaron completos con 13 pruebas
  nuevas (`test_mcp_receivables.py`, `test_mcp_prompt_injection.py`):
  aislamiento por tenant, equivalencia REST/MCP, sin saldo negativo ni
  sobreaplicacion, kill switch solo en escrituras, idempotencia, y fixtures de
  inyeccion tratados como datos inertes (resistencia estructural: tools
  tipadas Pydantic + SQL parametrizado, sin tool de SQL libre). Sin hallazgos
  de seguridad en las tools; el catalogo MCP es un conjunto cerrado esperado.
  E7-05 (agente OpenAI), E7-06 (medicion consumo/costo) y E7-08 (resumen) son
  alcance de Sprint 5 y no se implementan aqui.
- Seguridad: se elimino un endpoint de debug `/api/v1/debug/mcp-token` (dejado
  por depuracion de MCP en una fase previa) que decodificaba cualquier token
  bearer y devolvia sus claims sin gate; era fuga de internos del token y
  rompia el lint.
- Pendiente Sprint 3: dataset `sprint-03-v1`, ciclo en vivo (factura ->
  receivable -> cobro -> aging -> reverso) y QA go/no-go. UI de cartera base
  hecha (16 pruebas a11y); reconciliar el detalle con el contrato extendido.

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
