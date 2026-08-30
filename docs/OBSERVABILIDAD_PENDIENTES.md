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
- [ ] 6. Panel "Incidencias" en la bandeja de acción
      (`components/action-queue/`): lista los fallos abiertos, muestra causa y
      correlation ID, y permite reintentar los `AUTO_RETRY`. Los `NEEDS_HUMAN`
      se muestran con su motivo y sin botón de reintento.
- [ ] 7. Captura de errores de frontend: `window.onerror` y
      `unhandledrejection` en `main.tsx`, más el `componentDidCatch` de
      `ErrorBoundary.tsx` (hoy solo hace `console.error`). Reportar con el
      correlation ID de la última request.
- [ ] 8. E2E `frontend/tests/ops-failures.spec.ts` con backend mockeado en
      memoria (patrón de `payroll.spec.ts`).

### Fase 2 — Enterarse

- [ ] 9. Integración con Sentry o GlitchTip **gateada por variable de entorno**:
      `IAERP_ERROR_DSN` vacío = desactivado, que es el default. Tags:
      correlation_id, tenant, versión. Backend y frontend. Sin DSN configurado
      el código no debe cambiar de comportamiento ni fallar.

### 🔒 Fase 3 — Bucle operativo (REQUIERE AUTORIZACIÓN HUMANA)

**La corrida que llegue aquí NO implementa: escribe en la Bitácora que la Fase 1
y 2 están cerradas, apaga la tarea programada y termina.** A partir de este
punto un agente adquiere capacidad de escritura sobre datos de producción, y esa
decisión es del humano, no del bucle.

- [ ] 10. Tool MCP `ops.list_failures` (solo lectura, `operations:read`).
- [ ] 11. Tool MCP `ops.retry_failure`: solo acepta fallos que
      `classify_failure()` marque `AUTO_RETRY`, pasa por `AutomationSettings`
      (`writes_enabled`), `consume_automation_rate` e idempotencia, y queda
      auditada como acción de agente distinguible de una humana.
- [ ] 12. Disparo por evento al crearse un `DeadLetter` (no por reloj).

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
