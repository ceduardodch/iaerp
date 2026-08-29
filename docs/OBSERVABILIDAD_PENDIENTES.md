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

- [ ] 1. `GET /ops/failures` (scope `operations:read`): lista paginada de
      `dead_letters`, con filtro por estado y fecha. Solo lectura,
      tenant-scoped. Schema en `schemas/platform.py`.
      **`dead_letters` es la fuente canónica y completa: NO unir con
      `outbox_events`.** Verificado en el código: el dispatcher
      (`workers/outbox.py::_mark_failed`) marca `dead_lettered_at` *y* crea la
      fila de `DeadLetter`, mientras que el consumidor SRI
      (`workers/sri_transmission.py::_followup_or_dead_letter`) solo crea la
      fila. Unir ambas tablas duplicaría todos los fallos del dispatcher; el
      `UniqueConstraint(source_type, source_id)` ya garantiza una fila por fallo.
- [ ] 2. Handler global de excepciones en `main.py` + logs JSON estructurados
      (timestamp, level, correlation_id, tenant pseudonimizado, actor, evento).
      Hoy un 500 que no sea `IntegrityError` se pierde en el traceback de
      uvicorn sin correlation ID.
- [ ] 3. Servicio de política `services/ops_failures.py`:
      `classify_failure()` decide `AUTO_RETRY` / `NEEDS_HUMAN` con **lista
      blanca explícita por `event_type`** (default deny). Su prueba
      `backend/tests/test_ops_failure_policy.py` es intocable (ver reglas).
- [ ] 4. `POST /ops/failures/{id}/retry` (scope `operations:write`, nuevo) con
      `execute_idempotent`: reintento **manual** disparado por un humano.
      Registrar el scope en `ALL_DEV_SCOPES`, `SERVICE_ACCOUNT_ALLOWED_SCOPES`,
      `infra/keycloak/iaerp-realm.json` y `configure-staging.sh` (el pendiente
      de nómina que se olvidó de esto rompió con 422; no repetirlo).
- [ ] 5. Tipos `OpsFailure` en `frontend/src/api.ts`, espejo camelCase del
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

- 2026-08-29: lista creada tras auditar el repo. Confirmado que no hay ninguna
  herramienta de observabilidad instalada (solo intención en docs) y que los
  guardrails de agente (`AutomationSettings`, `AutomationRateWindow`,
  idempotencia, auditoría) ya existen y son reutilizables tal cual.
