# Observabilidad y bucle de autorresolución — pendientes

Lista ordenada. **Una corrida toma solo el primer pendiente sin marcar**, lo
termina completo y lo marca. Ver las reglas al final.

## Objetivo

Hoy, cuando a un usuario le falla algo, nadie se entera. El fallo queda en la
tabla `dead_letters` y solo se ve con SQL manual. La meta es cerrar el círculo:

1. **Ver** el error (persistido, expuesto en API y en pantalla).
2. **Enterarse** del error (tracking externo).
3. **Resolverlo solo** cuando sea recuperable; escalarlo cuando no lo sea.

## Lo que YA existe (verificado, no reconstruir)

| Pieza | Dónde |
|---|---|
| Correlation ID por request | `app/main.py:59`, expuesto al cliente en `X-Correlation-Id` |
| Fallos persistidos | `dead_letters`, `outbox_events.dead_lettered_at`, `inbox_events` (`app/models/platform.py`) |
| Auditoría | `append_audit` en `services/unit_of_work.py`, tabla `operations` |
| Idempotencia | `execute_idempotent`, `idempotency_records` |
| Guardrails de agente | `AutomationSettings` (`writes_enabled` False por defecto, `daily_amount_limit`) y `AutomationRateWindow` (`services/automation_rate.py`) |
| Scope `operations:read` | Ya en `ALL_DEV_SCOPES` (`api/router.py:135`) |
| Health checks | `/health/{live,ready,startup}`, `workers/health.py` |

**No existe:** Sentry/OTel/Prometheus (solo mencionados como intención en
`docs/04-architecture.md:42` y `docs/10-operations.md`), ningún endpoint ni
pantalla que exponga los fallos, handler global de excepciones (solo
`IntegrityError`), captura de errores de frontend.

## Regla fiscal que gobierna todo esto

`app/workers/sri_transmission.py` ya distingue lo que importa:

- Un **rechazo fiscal** (`RETURNED` → `REJECTED`) es **terminal y no se
  reintenta**. Nunca llega a `dead_letters`.
- Un **fallo técnico** (timeout, excepción no fiscal) reprograma con backoff y
  solo crea `DeadLetter` al agotar `OUTBOX_MAX_ATTEMPTS`.
- La reconciliación (paso 2 del docstring) **nunca reenvía** un documento que ya
  esté `RECEIVED`/`PENDING_AUTHORIZATION`/`AUTHORIZED`: solo consulta
  autorización.

Esa reconciliación es lo que hace seguro reintentar. Sin ella, no hay reintento
automático. De ahí sale la política del pendiente 4, que es la pieza de
seguridad de todo el bucle.

## Pendientes

### Fase 1 — Ver los errores

- [x] 1. `GET /ops/failures` (scope `operations:read`): lista paginada de
      `dead_letters`, con filtro por estado y fecha. Solo lectura,
      tenant-scoped. Schema en `schemas/platform.py`.
      **`dead_letters` es la fuente canónica y completa: NO unir con
      `outbox_events`.** Verificado en el código: el dispatcher
      (`workers/outbox.py::_mark_failed`) marca `dead_lettered_at` *y* crea la
      fila de `DeadLetter`, mientras que el consumidor SRI
      (`workers/sri_transmission.py::_followup_or_dead_letter`) solo crea la
      fila. Unir ambas tablas duplicaría todos los fallos del dispatcher; el
      `UniqueConstraint(source_type, source_id)` ya garantiza una fila por fallo.
- [x] 2. Handler global de excepciones en `main.py` + logs JSON estructurados
      (timestamp, level, correlation_id, tenant pseudonimizado, actor, evento).
      Hoy un 500 que no sea `IntegrityError` se pierde en el traceback de
      uvicorn sin correlation ID.
- [x] 3. Servicio de política `services/ops_failures.py`:
      `classify_failure()` decide `AUTO_RETRY` / `NEEDS_HUMAN` con **lista
      blanca explícita por `event_type`** (default deny). Su prueba
      `backend/tests/test_ops_failure_policy.py` es intocable (ver reglas).
- [x] 4. `POST /ops/failures/{id}/retry` (scope `operations:write`, nuevo) con
      `execute_idempotent`: reintento **manual** disparado por un humano.
      Registrar el scope en `ALL_DEV_SCOPES`, `SERVICE_ACCOUNT_ALLOWED_SCOPES`,
      `infra/keycloak/iaerp-realm.json` y `configure-staging.sh` (el pendiente
      de nómina que se olvidó de esto rompió con 422; no repetirlo).
- [x] 5. Tipos `OpsFailure` en `frontend/src/api.ts`, espejo camelCase del
      schema.
- [x] 6. Panel "Incidencias" en la bandeja de acción
      (`components/action-queue/`): lista los fallos abiertos, muestra causa y
      correlation ID, y permite reintentar los `AUTO_RETRY`. Los `NEEDS_HUMAN`
      se muestran con su motivo y sin botón de reintento.
- [x] 7. Captura de errores de frontend: `window.onerror` y
      `unhandledrejection` en `main.tsx`, más el `componentDidCatch` de
      `ErrorBoundary.tsx` (hoy solo hace `console.error`). Reportar con el
      correlation ID de la última request.
- [x] 8. E2E `frontend/tests/ops-failures.spec.ts` con backend mockeado en
      memoria (patrón de `payroll.spec.ts`).

### Fase 2 — Enterarse

- [x] 9. Integración con Sentry o GlitchTip **gateada por variable de entorno**:
      `IAERP_ERROR_DSN` vacío = desactivado, que es el default. Tags:
      correlation_id, tenant, versión. Backend y frontend. Sin DSN configurado
      el código no debe cambiar de comportamiento ni fallar.

### Fase 3 — Bucle operativo (AUTORIZADA por el humano el 2026-08-31)

El humano autorizó explícitamente esta fase. **Sigue siendo inerte al
publicarse**: `_require_automation_writes` (`mcp/server.py:240`) falla cerrado
si el tenant no tiene fila de `AutomationSettings` o si `writes_enabled` es
`False`, que es el default. Nada se activa hasta que una persona lo encienda por
tenant, igual que `IAERP_ERROR_DSN`. Construir esto NO enciende nada.

Patrón obligatorio para las tools, ya probado en `receivables.record_payment`:
`_tool_context(scope, tool_name)` (que aplica `_consume_tool_rate`) →
`_require_automation_writes` → `execute_idempotent`.

Toda tool nueva debe registrarse también en `contracts/mcp-tools.yaml`: el job
`YAML contracts` del CI valida la paridad contra `mcp/server.py` y se pone rojo
si falta.

- [ ] 10. Tool MCP `ops.list_failures` (solo lectura, `operations:read`),
      reutilizando `ops_failures.list_failures` sin duplicar la consulta.
      Devuelve la `classification` para que el agente sepa qué puede tocar.
- [ ] 11. Tool MCP `ops.retry_failure` (`operations:write`). **Diferencia
      central con `POST /ops/failures/{id}/retry`:** el endpoint REST NO pasa por
      `classify_failure()` a propósito, porque ahí un humano ya ejerció su
      juicio (ver el docstring de `retry_failure`). La tool del agente SÍ debe
      pasar, y rechazar todo lo que no sea `AUTO_RETRY`. Tres pruebas
      obligatorias: rechaza un `NEEDS_HUMAN`, rechaza con
      `writes_enabled=False`, y la auditoría queda distinguible de la humana
      (actor de cuenta de servicio, no de usuario).
- [ ] 12. Reintento automático **determinista en el worker**, no vía LLM: un
      paso en `workers/dispatcher.py` que reintenta los `DeadLetter`
      `AUTO_RETRY` del tenant cuando `writes_enabled` está activo, reutilizando
      la misma mecánica de `retry_failure` (encolar un `OutboxEvent` fresco).
      Para una lista blanca de un solo `event_type` esto es más simple, barato y
      predecible que pedirle a un modelo que apriete un botón; el valor del
      agente está en diagnosticar y explicar los `NEEDS_HUMAN`, que es lo que
      habilitan los pendientes 10 y 11. Debe respetar el mismo kill switch.
- [ ] 13. Runbook en `docs/10-operations.md`: cómo encender esto de verdad
      (poner `writes_enabled=True` en el tenant, emitir la cuenta de servicio
      con `operations:read`/`operations:write`, y cómo apagarlo en caliente).
      Sin esto, se publica algo que nadie sabe activar ni detener.

## Reglas de cada corrida

1. Tomar **solo el primer pendiente sin marcar**. No adelantar los siguientes.
2. Escribir su prueba primero y **verificarla revirtiendo el arreglo**: si no
   falla al revertir, la prueba no sirve.
3. Correr `cd backend && uv run ruff check . && uv run mypy app` y las pruebas
   del área. En frontend además `npx tsc --noEmit`, `npm run lint` y
   `npm run build`.
4. Commitear, empujar y **esperar el CI**. Si queda rojo, revertir el push con
   un commit de reversión y anotar el motivo aquí.
5. Marcar la casilla y anotar en la Bitácora qué se hizo, con el hash del commit.
6. **Nunca modificar ni debilitar `backend/tests/test_ops_failure_policy.py`.**
   Codifica qué se puede reintentar solo y qué no. Debilitarlo permitiría que un
   agente reintente automáticamente algo con efecto fiscal ya producido. Si una
   de esas pruebas falla, el error está en el código nuevo.
7. **Nunca** ampliar la lista blanca de `classify_failure()` a un `event_type`
   nuevo sin que exista reconciliación idempotente demostrada en su handler.
   Ante la duda: `NEEDS_HUMAN`.
8. Si el CI falla o una prueba no pasa **dos corridas seguidas** sobre el mismo
   pendiente: apagar la tarea programada `observabilidad-loop`, escribir el
   motivo abajo y detenerse.

## Fuera de alcance

Métricas y trazas distribuidas (Prometheus, OpenTelemetry), alertas por
WhatsApp/email, y cualquier auto-arreglo de código en producción. El bucle de
ingeniería (error → PR) se decide aparte y **nunca** despliega solo.

## Bitácora

- Pendiente 1 (`GET /ops/failures`), commit `4bb8c4b`, **publicado solo en
  `release`** (CI run `33252196358` verde: Backend 15m31s, Security y YAML
  contracts OK; el job de despliegue no corre en `release`, que es justo lo
  buscado). Falta autorización humana para promover a `main`.
  `services/ops_failures.py` consulta solo `dead_letters` y no une
  `outbox_events`: el dispatcher escribe en las dos tablas, así que el join
  duplicaría todos sus fallos. Se verificó en rojo agregando el join —
  `test_dead_lettered_outbox_event_appears_once` falla mostrando la fila
  repetida — y se restauró reescribiendo, sin `git checkout`. El
  `correlation_id` y los `aggregate_*` se aplanan desde el `payload` que
  escriben los workers, con lectura defensiva (`_payload_text`) porque su forma
  varía por `event_type` y una clave ausente no debe tumbar el listado entero.
  7 pruebas nuevas + 18 del área verdes, ruff y mypy limpios.
- 2026-08-29: lista creada tras auditar el repo. Confirmado que no hay ninguna
  herramienta de observabilidad instalada (solo intención en docs) y que los
  guardrails de agente (`AutomationSettings`, `AutomationRateWindow`,
  idempotencia, auditoría) ya existen y son reutilizables tal cual.
- Pendiente 2 (handler global de excepciones), commit `439ca63`, **publicado
  solo en `release`** (CI run `33285077255` verde: Backend 15m11s, Security y
  OIDC OK; el job de despliegue a Coolify quedó `skipped`, que es justo lo
  buscado en esta rama). Falta autorización humana para promover a `main`.
  El handler se registra con `@app.exception_handler(Exception)`, lo que en
  Starlette lo instala en `ServerErrorMiddleware` (no en `ExceptionMiddleware`):
  por eso solo intercepta excepciones que ningún otro handler capturó —
  `HTTPException` y `IntegrityError` siguen su camino normal — y no compite con
  el handler de `IntegrityError` ya existente. El `tenant_id`/`actor_id` se
  guardan en `request.state` desde `get_auth_context`
  (`app/core/auth.py::get_auth_context`) porque los exception handlers de
  FastAPI solo reciben `(request, exc)` y no pueden usar `Depends`; el tenant
  se loguea pseudonimizado con `sha256(...)[:12]`, nunca el UUID crudo. Se
  verificó en rojo quitando el handler nuevo: las dos pruebas de
  `test_unhandled_exception_handler.py` fallan (una con `JSONDecodeError` al
  parsear el body plano de Starlette, otra sin ningún registro `app.main` en
  `caplog`), y se restauró reescribiendo el bloque, sin `git checkout`. 2
  pruebas nuevas + 27 del área (`test_ops_failures_api.py`,
  `test_billing_api.py`) verdes, ruff y mypy limpios. La suite completa tiene
  2 fallos preexistentes y ajenos a este cambio (confirmado corriéndolos en
  `08f8d63` antes de tocar nada): `test_health` por Redis apagado (esperado) y
  `test_payroll_employees_service.py::test_create_employee_rejects_duplicate_identification_within_tenant`
  por un `IntegrityError` crudo que el servicio de nómina no atrapa — no es
  parte de este pendiente.
- Pendiente 3 (`classify_failure()`), commit `e94b7ce`, **publicado solo en
  `release`** (CI run `33285961789` verde: Backend 15m53s, Security OK; el
  despliegue a Coolify quedó `skipped`, esperado en esta rama). Falta
  autorización humana para promover a `main`. La lista blanca solo tiene
  `invoice.signed`: es el único handler (`workers/sri_transmission.py::
  handle_invoice_signed`) que demuestra reconciliación idempotente antes de
  reintentar — nunca retransmite una clave con `SRITransmission` en
  `RECEIVED`/`PENDING_AUTHORIZATION`/`AUTHORIZED`, solo reconsulta
  autorización, y ese es el mismo camino que ya usa su propio backoff
  automático antes de agotar `OUTBOX_MAX_ATTEMPTS`. Se revisó cada otro
  `event_type` real del sistema (`invoice.authorized`,
  `credit_note.authorized`, `collection.reminder.due`, los cuatro de
  `campaign.*`, `tax.xml_recovery.requested`) y ninguno tiene ese chequeo en
  su handler, así que quedan `NEEDS_HUMAN` por default-deny. Se verificó en
  rojo vaciando la lista blanca — `test_invoice_signed_is_auto_retry` falla
  mostrando `NEEDS_HUMAN` — y se restauró reescribiendo, sin `git checkout`.
  3 pruebas nuevas + 7 de `test_ops_failures_api.py` + 2 de
  `test_unhandled_exception_handler.py` verdes, ruff y mypy limpios. No se
  tocó el endpoint ni el schema: eso es pendiente 4 en adelante.
- Pendiente 4 (`POST /ops/failures/{id}/retry`), commits `bc51ecb` (endpoint)
  y `c82c3a3` (baseline de secretos), **publicado solo en `release`** (CI
  disparado a mano con `gh workflow run` porque el push normal solo compara
  contra el commit anterior y se saltaba `Backend`/`Frontend` al no tocar esas
  rutas en el segundo commit; run `33287751676` verde: Backend, Frontend,
  OIDC, migraciones, YAML contracts y Security checks OK, despliegue a
  Coolify `skipped`, que es justo lo buscado en esta rama). Falta autorización
  humana para promover a `main`.
  Decisión de diseño explícita: a diferencia del agente de la Fase 3
  (`ops.retry_failure`, pendiente 11, gateado por `classify_failure() ==
  AUTO_RETRY`), este endpoint humano NO repite ese gate — acepta reintentar
  cualquier fallo `OPEN` del tenant, porque quien lo dispara ya ejerció su
  propio juicio al pedirlo explícitamente por el scope nuevo
  `operations:write`. El pendiente lo describe así ("reintento manual
  disparado por un humano") sin mencionar `classify_failure()`, a diferencia
  del texto del pendiente 11 que sí lo exige para el agente; se documenta acá
  por si un futuro pendiente decide que hace falta más fricción.
  El reintento nunca reabre el `OutboxEvent` original: encola uno nuevo (id
  fresco) con el mismo `event_type`/`aggregate_type`/`aggregate_id`/
  `correlation_id` que trae el `payload` del `DeadLetter`, igual que
  `workers/sri_transmission.py::_enqueue_followup` — reabrir el original no
  sirve porque su `InboxEvent` puede seguir `COMPLETED` y `consume_once` lo
  deduplicaría. Si el `payload` no trae `aggregate_type`/`aggregate_id`
  (dato viejo o malformado), responde 422 en vez de violar el `NOT NULL` de
  `OutboxEvent`. Reintentar un fallo que ya no está `OPEN` responde 409.
  Registrado `operations:write` en las cuatro ubicaciones (`ALL_DEV_SCOPES`
  en `api/router.py`, `SERVICE_ACCOUNT_ALLOWED_SCOPES` en
  `schemas/platform.py`, `infra/keycloak/iaerp-realm.json` y
  `configure-staging.sh`) para no repetir el 422 que ya rompió nómina.
  Se verificó en rojo comentando el cambio de `status`/`resolved_at` en
  `retry_failure()`: `test_retry_failure_reopens_and_enqueues_fresh_outbox_event`
  y `test_retry_failure_twice_returns_409` fallan mostrando `OPEN` en vez de
  `RESOLVED`, y se restauró reescribiendo, sin `git checkout`. 6 pruebas
  nuevas + 7 de listado en `test_ops_failures_api.py`, más
  `test_ops_failure_policy.py` (intocable) y `test_unhandled_exception_handler.py`
  verdes; suite completa 582 pasan/36 skip, mismos 2 fallos preexistentes y
  ajenos (`test_health` por Redis apagado, duplicado de identificación en
  nómina); ruff y mypy limpios.
- Pendiente 5 (tipos `OpsFailure` en `frontend/src/api.ts`), commit `b911ade`,
  **publicado solo en `release`** (CI run `33289490530` verde: Frontend 6m41s,
  Security OK; Backend/OIDC/migraciones/contratos YAML quedaron `skipped` por
  no tocar esas rutas, y el despliegue a Coolify también `skipped`, esperado
  en esta rama). Falta autorización humana para promover a `main`.
  Es un cambio puramente de tipos, sin lógica: `OpsFailure`/`OpsFailureStatus`
  espejan `OpsFailureRead` (`app/schemas/platform.py`) campo a campo en
  camelCase, mismo patrón sin wrapper propio que `Payable` y
  `PayrollEmployee` (commit `1958de7`, que tampoco llevó test dedicado por la
  misma razón: no hay comportamiento que ejercitar hasta que el pendiente 6
  consuma el tipo desde el panel de Incidencias). Verificado con
  `npx tsc --noEmit`, `npm run lint` y `npm run build` limpios; los tres
  warnings de lint que aparecen en el run (`useKanban.ts`, `CrmKanban.tsx`,
  `Toast.tsx`) son preexistentes y ajenos a este archivo.
- Pendiente 6 (panel "Incidencias" en `ActionQueuePage.tsx`), commit
  `505b62a`, **publicado solo en `release`** (CI run `33292062927` verde:
  Backend, Frontend y Security checks OK; despliegue a Coolify `skipped`,
  esperado en esta rama). Falta autorización humana para promover a `main`.
  Antes de tocar el frontend agregué un campo `classification` a
  `OpsFailureRead` (`app/schemas/platform.py` + `_to_read` en
  `app/services/ops_failures.py`), calculado con `classify_failure()`: sin
  esto el panel habría tenido que reimplementar la lista blanca de
  `event_type` en TypeScript, duplicando una decisión que ya vive en el
  backend y que puede desincronizarse. El endpoint de reintento manual
  (pendiente 4) sigue sin exigir esta clasificación -- es solo una guía de
  UI para el humano, documentado explícitamente en el docstring del schema
  para que no se confunda con un gate de seguridad.
  El panel nuevo (`IncidentRow` + sección "Incidencias" en
  `ActionQueuePage.tsx`) consulta `GET /ops/failures?status=OPEN` solo si
  `scopes` incluye `operations:read` (prop nueva que `App.tsx` pasa desde
  `contextQuery.data.scopes`, igual que ya hacía `InvoicesPage`); el botón
  "Reintentar" solo aparece si además el fallo es `AUTO_RETRY` y el usuario
  tiene `operations:write`. Los `NEEDS_HUMAN` muestran la insignia "Requiere
  revisión manual" sin botón. Al reintentar, la fila se oculta localmente y
  se invalida la query -- no se reabre optimísticamente porque el backend ya
  marca el `DeadLetter` original como `RESOLVED`.
  Se verificó en rojo dos veces: (1) quitando `classification` del schema
  -- `test_list_failures_returns_dead_letters` y la nueva
  `test_list_failures_exposes_needs_human_for_unknown_event_types` fallan
  con `ValidationError: classification Field required`; (2) forzando
  `canReadFailures`/`canRetryFailures`/`canRetry` a `true` en el componente
  -- los E2E `sin el scope operations:read no se muestra el panel de
  Incidencias` y `solo ofrece reintentar la incidencia AUTO_RETRY` fallan
  mostrando el panel/botón que no debían. Ambas veces se restauró
  reescribiendo, sin `git checkout`.
  Backend: 2 pruebas nuevas + 19 del área (`test_ops_failures_api.py`,
  `test_ops_failure_policy.py`, `test_unhandled_exception_handler.py`)
  verdes, ruff y mypy limpios; suite completa 583 pasan/36 skip, mismos 2
  fallos preexistentes y ajenos (`test_health` por Redis apagado, duplicado
  de identificación en nómina). Frontend: 5 E2E nuevos + 6 existentes de
  `action-queue.spec.ts` verdes (11/11), `tsc --noEmit`, `oxlint` (mismos 3
  warnings preexistentes) y `npm run build` limpios.
- Pendiente 7 (captura de errores de frontend), commits `628ce9f` (captura)
  y `caca137` (fix del E2E en CI), **publicado solo en `release`** (CI run
  `33296811532` verde: Frontend 7m22s, Security OK; Backend/OIDC/
  migraciones/YAML/Coolify quedaron `skipped` por no tocar esas rutas,
  esperado en esta rama). Falta autorización humana para promover a `main`.
  Punto único de reporte en `src/errorReporting.ts`, llamado desde tres
  sitios: `window.addEventListener('error'|'unhandledrejection')` en
  `main.tsx` y `componentDidCatch` en `ErrorBoundary.tsx` (que antes solo
  hacía `console.error`). El correlation ID sale de
  `api.ts::getLastCorrelationId()`, una variable de módulo que `apiRequest`
  actualiza desde el header `X-Correlation-Id` de cada respuesta del
  pendiente 2 (`app/main.py`) — no se limpia si la respuesta no trae el
  header, para no perder el último conocido en llamadas intermedias sin
  ese dato. Sin `IAERP_ERROR_DSN` (pendiente 9) el destino sigue siendo la
  consola, en JSON estructurado listo para un envío futuro a Sentry.
  E2E nuevo (`frontend-error-capture.spec.ts`, 3 pruebas × 2 proyectos)
  verificado en rojo revirtiendo cada uno de los tres puntos de captura
  antes de confirmar. El caso de `ErrorBoundary` no fuerza un throw
  artificial: aborta la petición de red del chunk JS de Nómina
  (`page.route` sobre `resourceType() === 'script'`), reproduciendo un
  fallo real de carga diferida (`React.lazy`) que React resuelve a través
  del `ErrorBoundary` que envuelve su `Suspense` en `App.tsx` — mismo
  mecanismo que un fallo de red o un deploy con chunks obsoletos en
  producción.
  El primer push (`628ce9f`) quedó rojo en CI (run `33296364260`): local
  no hay backend real corriendo, así que los mocks de `page.route` bastan;
  en CI sí hay un backend real detrás del proxy de Vite, y alguna llamada
  del arranque del tablero que mis mocks no cubrían explícitamente escapó a
  ese backend, que siempre pone su propio `X-Correlation-Id` — pisó el
  correlation ID fijo que el test esperaba. Fix (`caca137`): ruta catch-all
  `**/api/v1/**` registrada primero (menor prioridad en Playwright, las
  rutas específicas siguen ganando para sus paths) que responde con el
  mismo correlation ID conocido para cualquier endpoint no mockeado
  explícitamente, sin dejar que nada llegue a la red real. Confirmado
  verde en el segundo push sin tocar el código de producción, solo el test.
  `tsc --noEmit`, `oxlint` (mismos 3 warnings preexistentes) y
  `npm run build` limpios; 45 E2E de specs mockeados sin backend real
  (`crm-kanban`, `action-queue`, `payroll`, `sidebar-collapsible`, el nuevo)
  verdes en local sin regresiones.
- Pendiente 8 (E2E `frontend/tests/ops-failures.spec.ts`), commit `6b5abf7`,
  **publicado solo en `release`** (CI run `33298642264` verde: Frontend
  7m49s, Security OK; Backend/OIDC/migraciones/YAML/Coolify quedaron
  `skipped` por no tocar esas rutas, esperado en esta rama). Falta
  autorización humana para promover a `main`. Sin cambio de aplicación: es un
  archivo de test nuevo, así que la verificación en rojo se hizo rompiendo a
  propósito el código real que cada prueba ejercita (y restaurándolo después
  reescribiendo, sin `git checkout`), no revirtiendo un "arreglo" propio.
  A diferencia de las 8 pruebas de Incidencias que ya viven en
  `action-queue.spec.ts` (pendiente 6) -- que usan una lista estática y una
  respuesta de reintento fija por `page.route` -- este archivo monta un
  backend en memoria que aplica de verdad el filtro `status` de
  `GET /ops/failures` y muta el `DeadLetter` al reintentar (404/409/422 y
  éxito), replicando las reglas de `app/services/ops_failures.py::
  retry_failure`. Los 4 casos nuevos y lo que cada uno verificó en rojo:
  (1) el filtro por `status=OPEN` -- se rompió quitando el query param en
  `ActionQueuePage.tsx`, la incidencia `RESOLVED` se colaba en la lista;
  (2) que el reintento persiste en el backend y sobrevive a una recarga
  completa de página (no solo un `Set` local en React) -- se rompió
  cambiando la `mutationFn` de `IncidentRow` por un éxito falso sin llamar a
  `apiRequest`, y tras `page.reload()` la incidencia reaparecía porque el
  backend simulado nunca se enteró; (3) que un 422 por payload incompleto
  (`aggregate_type`/`aggregate_id` ausentes, mismo caso que documentó el
  pendiente 4) se explica en un `role="alert"` y no hace desaparecer la fila;
  (4) que un fallo técnico transitorio (503) dos veces seguidas no bloquea
  la incidencia: el botón se reactiva solo porque `retry.isPending` vuelve a
  `false` al fallar la mutación, y un segundo click sí tiene éxito. (3) y (4)
  se rompieron juntas quitando el bloque `retry.error ? <p role="alert">...`
  de `IncidentRow`. La navegación tras `page.reload()` necesitó volver a
  llamar `navigateToSection(page, 'Bandeja de acción')`: la sección activa
  vive en estado de React, no en la URL, aunque el token en `sessionStorage`
  sí sobrevive la recarga sin pasar por "Continuar" de nuevo.
  `tsc --noEmit`, `oxlint` (mismos 3 warnings preexistentes) y `npm run build`
  limpios; 49 E2E de specs mockeados sin backend real (`crm-kanban`,
  `action-queue`, `payroll`, `sidebar-collapsible`,
  `frontend-error-capture`, el nuevo `ops-failures`) verdes en local en
  `chromium`, sin regresiones.
  Con esto se cierra la Fase 1 completa
  (docs/OBSERVABILIDAD_PENDIENTES.md). Sigue el pendiente 9 (Fase 2, Sentry/
  GlitchTip gateado por `IAERP_ERROR_DSN`); la Fase 3 sigue esperando
  autorización humana explícita antes de tocarla.
- Pendiente 9 (Sentry/GlitchTip gateado por `IAERP_ERROR_DSN`), commit
  `3883783`, **publicado solo en `release`** (CI run `33301101716` verde:
  Security 1m16s, Frontend 8m52s, Backend 15m32s, OIDC y full stack 2m53s;
  despliegue a Coolify `skipped`, esperado en esta rama). Falta autorización
  humana para promover a `main`.
  `app/core/observability.py` es el único punto que importa `sentry_sdk`:
  `init_error_tracking()` no llama a `sentry_sdk.init` si `IAERP_ERROR_DSN`
  está vacío (default), y `capture_exception()` es no-op mientras ese init
  no haya corrido -- ninguna de las dos cambia de comportamiento sin DSN.
  Se conecta desde `unhandled_exception_handler` (`app/main.py`, pendiente 2)
  reusando el mismo `correlation_id`/`tenant_hash`/`actor` que ya arma para
  el log JSON, así el evento de Sentry y la línea de log se pueden cruzar
  por correlation_id. En frontend, `src/errorReporting.ts` hace lo mismo con
  `@sentry/browser`, gateado por `VITE_ERROR_DSN` (prefijo que Vite expone al
  bundle, igual que `VITE_API_URL`); decisión documentada en el código: no
  tagea tenant porque el frontend nunca decodifica el JWT (es opaco, solo se
  usa vía `getToken()`) y agregar esa decodificación solo para un tag de
  Sentry no valía la complejidad -- el `correlation_id` ya permite cruzar el
  evento del frontend con el del backend, que sí lleva el tenant
  pseudonimizado.
  Verificado en rojo dos veces: (1) backend, comentando la llamada a
  `capture_exception()` en `unhandled_exception_handler` --
  `test_unhandled_exception_reports_to_error_tracking` (nueva, en
  `test_unhandled_exception_handler.py`) falla con `captured == []`; (2)
  frontend, reemplazando temporalmente el gate `VITE_ERROR_DSN` por un DSN
  fijo en `errorReporting.ts` -- el nuevo E2E `sin VITE_ERROR_DSN no sale
  ninguna llamada a un backend de error tracking externo` falla mostrando 3
  requests reales a `ingest.sentry.io` (el envelope que el SDK intenta
  mandar), confirmando que el gate es lo único que lo bloquea y que la
  integración sí dispara tráfico real cuando está activa. Ambas veces se
  restauró reescribiendo, sin `git checkout`.
  No hay framework de pruebas unitarias en frontend (solo Playwright E2E,
  ver `playwright.config.ts`), así que la cobertura de la lógica de gateo en
  sí (no solo la ausencia de red) vive en el backend
  (`backend/tests/test_observability.py`, 5 pruebas nuevas con
  `sentry_sdk.init`/`new_scope`/`capture_exception` mockeados). Mismo tipo de
  decisión de alcance que ya documentó el pendiente 5 para no forzar
  herramientas nuevas por una sola pieza sin lógica de negocio propia.
  Backend: 5 pruebas nuevas de `test_observability.py` + 1 nueva de
  `test_unhandled_exception_handler.py` (3/3 de ese archivo) verdes; suite
  completa 589 pasan/36 skip, mismos 2 fallos preexistentes y ajenos
  (`test_health` por Redis apagado, duplicado de identificación en nómina);
  ruff y mypy limpios. Frontend: 1 E2E nuevo + 3 existentes de
  `frontend-error-capture.spec.ts` (4/4) verdes, más 46 E2E de los otros
  specs mockeados sin regresiones; `tsc --noEmit`, `oxlint` (mismos 3
  warnings preexistentes) y `npm run build` limpios.
  Con esto se cierra la Fase 2 completa. La Fase 3 (pendientes 10-12, tools
  MCP de reintento automático) sigue esperando autorización humana explícita
  antes de tocarla: le da a un agente capacidad de escritura sobre datos de
  producción.
- 2026-08-31: pendiente 10 (`ops.list_failures`) implementado y verificado en
  local, **sin commitear ni pushear**: a mitad de la corrida detecté que otra
  sesión de IA está trabajando en vivo sobre el mismo working tree, tocando
  exactamente los mismos archivos compartidos que necesito para registrar la
  tool nueva (`backend/app/mcp/server.py`, `backend/app/mcp/
  tool_fingerprints.py`, `contracts/mcp-tools.yaml`) para una tool distinta
  (`tax.process_received_reports`, con sus propios `app/api/tax.py`,
  `app/services/tax/received_reports.py`, `tests/test_mcp_tax.py`,
  `tests/test_tax_received_reports.py` y `docs/runbooks/` sin commitear).
  Confirmé la colisión con `stat -f "%Sm"` en esos archivos: ediciones de los
  últimos ~7 minutos, mientras `git status` al arrancar esta corrida daba
  árbol limpio. Regla 1 de `COORDINACION_IA.md` ("si ves señales de otra
  sesión trabajando, PARA y coordina con el humano") aplica literalmente. Como
  esta corrida es automática y sin humano presente para coordinar en el
  momento, no hice ningún `git add`/`commit`/`push` ni toqué los archivos de
  la otra sesión (`git checkout`/`restore`/`stash` habría arriesgado su
  trabajo en curso) y me detuve sin marcar la casilla 10.
  Lo que sí quedó completo y verificado en el working tree (útil para quien
  retome esto): tool `ops.list_failures` (solo lectura, scope
  `operations:read` ya registrado en las cuatro ubicaciones desde el
  pendiente 4) en `mcp/server.py`, reutilizando `ops_failures.list_failures`
  sin duplicar la consulta y devolviendo `classification` por fallo; huella
  SHA-256 nueva en `tool_fingerprints.py`; entrada + `$defs.opsFailure` en
  `contracts/mcp-tools.yaml` (`scripts/validate_contracts.py` pasa); test
  nuevo `backend/tests/test_mcp_ops_failures.py` (6 pruebas: catálogo por
  scope, aislamiento de tenant, equivalencia con `GET /ops/failures` incluida
  la `classification`, filtro por `status`, no bloqueado por el kill switch
  de automatización porque es solo lectura, y error exacto de scope
  faltante), verificado en rojo forzando `status=None` en la tool (el test de
  filtro por `status` falla mostrando ambos fallos) y restaurado reescribiendo
  sin `git checkout`. `ruff check .` y `uv run mypy app` limpios. Suite
  completa corrida en orden natural de archivos (`pytest tests/`, que es como
  corre CI): 48/48 verdes en los archivos de MCP + ops; en la corrida de la
  suite completa aparecieron fallos adicionales de nómina/salud que
  desaparecen corriendo esos archivos solos, así que son de aislamiento entre
  tests preexistente y no de este cambio (no investigado a fondo porque no es
  el alcance de este pendiente).
  Dejo la tarea programada **encendida**: esto no es un pendiente que falló
  dos corridas seguidas, es una colisión externa con otra sesión que
  presumiblemente termina y libera los archivos. La próxima corrida debe: (1)
  `git status` primero como siempre: si sigue viendo cambios sin commitear
  ajenos a nómina/pagos/CRM en `mcp/server.py` y compañía, asumir que la otra
  sesión sigue activa y volver a pausarse; (2) si el árbol está limpio o solo
  tiene los cuatro archivos de la tool de tax ya commiteados por su propia
  sesión, reaplicar el mismo diseño descrito arriba para `ops.list_failures`
  (no hay nada que rehacer en diseño, solo en mecánica de commit) y seguir el
  flujo normal de publicación en `release`.
