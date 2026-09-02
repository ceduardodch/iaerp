# Módulo de avisos (notificaciones operativas) — plan de trabajo

> Documento de **relevo**: quien retome este módulo lee esto antes de tocar
> código. Coordinación general: [`COORDINACION_IA.md`](../COORDINACION_IA.md).
> Estado del proyecto: [`docs/STATUS.md`](STATUS.md).

**Última actualización:** 2026-09-02 (F1 completada)
**Estado:** ✅ F0 y F1 completas. El módulo programa y entrega el aviso de
declaración de IVA con `StubEmailSender` (sin red). Falta P0.3 del usuario
(dominio Brevo, API key, calendario de feriados) para arrancar F2.

## Qué es

Un módulo que **le avisa a la empresa lo que tiene que hacer**, con calendario
propio y parametrizable por cuenta: facturar a un cliente el día que toca,
declarar antes de la fecha límite, pagar el IESS, cerrar el mes sabiendo cuánto
IVA se generó, y ver ingresos/egresos en los primeros días del mes.

Es **distinto** de la cobranza que ya existe (`CollectionReminder`), que le
escribe **al cliente**. Este módulo le escribe **al equipo interno**. La
distinción no es cosmética: define destinatarios, plantillas, transporte y
regla de opt-out diferentes.

### Lo que este módulo NO hace

Vinculante, en línea con el [ADR 0012](adrs/0012-tax-module-scope.md):

- **No declara, no paga, no presenta ni envía nada al SRI ni al IESS.** Avisa
  para que una persona lo haga.
- **No emite facturas.** El aviso "toca facturar a ACME" no crea la factura.
- **No inventa cifras.** Si el IVA del período viene de evidencia incompleta,
  el correo lo dice y no muestra un número que parezca definitivo.
- **No reemplaza los recordatorios de cobranza al cliente** (Gmail + WhatsApp
  ya existentes en `workers/collections.py`).

---

## Qué se reutiliza (no rehacer)

El repo ya tiene resuelto casi todo el andamiaje. El módulo se monta encima:

| Pieza existente | Qué aporta | Dónde |
|---|---|---|
| Outbox + inbox + Celery | Entrega at-least-once con reintentos (`max_retries=8`, backoff) y aislamiento por `consumer_name` | `workers/outbox.py`, `workers/tasks.py` |
| Patrón de scheduler en bucle | 3 schedulers ya corren en el dispatcher; el nuevo es un cuarto `TaskGroup.create_task` | `workers/dispatcher.py:48` |
| Patrón "programar → PROCESSING → outbox" | `dispatch_due_reminders_once` con `with_for_update(skip_locked=True)` y reintentos por `attempts`. **Copiar este patrón tal cual** | `workers/collections.py:87` |
| Plantillas con marcadores | `{{empresa}}`, `{{cliente}}`… renderizadas por tenant | `services/collection_email.py` |
| Protocolo `Notifier` + `StubNotifier` | Contrato de envío con implementación sin red para dev/CI | `integrations/notifications/` |
| Motor de IVA | `compute_iva` con trazabilidad por cifra | `services/tax/iva.py:112` |
| Pendientes tributarios | `TaxTask` ya se genera sola por período | `services/tax/tasks.py` |
| Nómina con IESS | `PayrollEntry.aporte_iess`, períodos DRAFT/APPROVED | `models/payroll.py:145` |
| Secretos por referencia | `TenantTaxProfile.vault_ref` — nunca la clave en BD | `models/tax.py:73` |

---

## F0 — Prerequisitos bloqueantes (antes de escribir código)

### P0.1 · ✅ Fecha límite del SRI por noveno dígito

**Hecho.** Antes, `TaxPeriod.due_date` era `nullable` y solo se llenaba si
alguien la escribía a mano; no había lógica que la calculara, así que un aviso
"declara hasta tal fecha" no tenía de dónde sacar la fecha.

Lo que quedó implementado:

- **`services/tax/due_dates.py`** — tabla del noveno dígito (días 10 a 28), mes
  de declaración (el siguiente al período) y corrimiento a día hábil.
- **`services/tax/periods.py`** — `get_or_create_period` calcula la fecha
  cuando no se le pasa una. Una fecha explícita **nunca** se pisa: quien la
  escribe conoce una prórroga o un régimen que la regla general no cubre.
- **Migración `d2e3f4a5b6c7`** — rellena los períodos de IVA existentes que
  quedaron sin fecha. Idempotente, no toca fechas escritas a mano, salta RUC
  ilegibles y su downgrade conserva los datos.
- **29 pruebas** en `tests/test_tax_due_dates.py` (los 10 dígitos, diciembre →
  enero, sábado/domingo, feriados, RUC inválidos, integración por servicio) más
  una verificación del backfill en `scripts/validate_migrations.py`, que corre
  contra PostgreSQL real en CI.

**Límites deliberados** — el módulo devuelve `None` en vez de estimar:

| Caso | Estado | Qué falta |
|---|---|---|
| IVA mensual | ✅ Confirmado | — |
| ATS, RENTA, RDEP, ADI | ⛔ Sin fecha | El usuario debe confirmar cada calendario |
| Feriados | ⚠️ Parcial | Sábados y domingos sí se corren siempre. Los feriados se reciben desde afuera y hoy nadie los carga, así que el resultado se marca con `holidays_checked=False`. Cargar el calendario oficial es P0.3 |
| Régimen semestral | ⛔ No contemplado | `TenantTaxProfile.tax_regime` se guarda pero no se usa en ninguna lógica |

Esto no es una omisión: un aviso que la gente va a obedecer no puede llevar una
fecha estimada. Sin dato confirmado, no hay fecha.

### P0.2 · ✅ Decisión tomada: opción A

**Brevo transporta solo los avisos internos.** La cobranza y el envío de
facturas al cliente siguen por Gmail.

El motivo: hoy el correo de cobranza vive en un hilo de Gmail real
(`send_google_email_with_thread`) y las respuestas del cliente se sincronizan a
la bandeja (`sync_google_inbox`). Mandarlo por Brevo rompería ese hilo. Brevo
es excelente para correo transaccional saliente, que es justamente lo que son
los avisos internos. Si alguna vez se quiere mover la cobranza, se hace con un
ADR propio.

### P0.3 · ⏳ Insumos del usuario (no se pueden generar desde el código)

- Cuenta Brevo + **dominio verificado** (SPF, DKIM, DMARC). Sin esto, los
  correos caen en spam y el módulo parece roto cuando no lo está.
- API key de Brevo por cuenta → va al gestor de secretos, **nunca a la BD**.
- **Calendario de feriados** del año en curso, para completar el corrimiento a
  día hábil (ver la tabla de límites en P0.1). Se pide como fechas concretas
  porque la observancia de los feriados ecuatorianos cambia por decreto.
- **Calendario del IESS** (fecha límite del aporte por dígito, si aplica).
- Calendarios de ATS, RENTA y RDEP, si se quieren avisos de esas obligaciones.
- Confirmación de la lista de avisos del catálogo y sus fechas por defecto.

---

## Diseño acordado

### Principio: separar tres cosas

Hoy en cobranza están mezcladas. Aquí van separadas desde el inicio:

1. **Regla** — *cuándo* avisar (parametrizable por cuenta).
2. **Plantilla** — *qué dice* (editable por cuenta, con marcadores).
3. **Transporte** — *por dónde sale* (Brevo / Gmail / stub, por cuenta).

Esto es lo que hace el módulo "parametrizable" de verdad: cambiar el día de un
aviso no debe requerir tocar código ni redeploy.

### Modelos (`backend/app/models/notifications.py`, todos tenant-scoped)

| Modelo | Para qué |
|---|---|
| `NotificationChannelAccount` | Proveedor por cuenta: `provider` (BREVO/GMAIL/STUB), `api_key_vault_ref`, `sender_email`, `sender_name`, `status`, `verified_at`, `last_error`. **La clave nunca en BD ni en logs.** |
| `NotificationRule` | La parametrización: `rule_type`, `name`, `enabled`, `schedule_kind`, `days_of_month`, `offsets_days`, `send_hour`, `channels`, `template_id`, `audience_kind`, `audience_roles`, `audience_emails`, `params` (JSON), `require_ack`. Se permiten **varias reglas del mismo tipo** — así "más de un correo que se lance" es configuración, no código. |
| `NotificationTemplate` | Asunto + cuerpo por cuenta y `rule_type`. Default en código, override por cuenta. Mismo mecanismo de marcadores que `collection_email.py`. |
| `NotificationEvent` | La ocurrencia programada: `rule_id`, `dedupe_key` (**unique por tenant**), `scheduled_at` (UTC), `status`, `attempts`, `payload` (snapshot de las cifras calculadas), `ack_at`/`ack_by`. |
| `NotificationDelivery` | Un envío por destinatario: `recipient`, `provider`, `provider_message_id`, `status`, `error_message`, `sent_at`. Permite trazar quién recibió qué y procesar bajas individuales. |
| `PartyBillingSchedule` | **Dato que hoy no existe**: `party_id`, `contract_id` (nullable), `day_of_month`, `frequency`, `amount_hint`, `product_hint`, `active`, `last_invoiced_period`. |

`schedule_kind` admite: `DAY_OF_MONTH` (ej. "1,10"), `OFFSET_TO_DUE` (ej.
"-7,-3,-1,0" respecto a una fecha límite), `LAST_BUSINESS_DAY`, `WEEKDAY`.

**`dedupe_key` es la pieza crítica.** Ejemplo:
`iva_declaracion:2026-09:offset-3`. Garantiza que el scheduler corriendo cada
minuto no dispare el mismo correo dos veces, incluso tras un reinicio. Es
exactamente el rol que cumple `correlation_id` en `collections.py:122`.

### El calendario de facturación (`PartyBillingSchedule`)

Hoy **no hay ningún campo de "día de facturación"** en el repo:
`CommercialContract.service_type` sí tiene `FIXED_MONTHLY`, pero no dice qué día
(`models/legal_commercial.py:62`). Sin este modelo, el aviso "a ACME se le
factura el 1 y a Beta el 10" no tiene de dónde salir.

Va en tabla propia y no como campo del contrato porque hay clientes recurrentes
sin contrato formal cargado, y porque un contrato puede tener más de un ciclo.

Lo valioso: el aviso **se cierra solo**. Si ya existe una factura emitida a ese
cliente en ese período, el evento pasa a `SKIPPED` en vez de molestar. Un aviso
que no sabe cuándo callarse se ignora en dos semanas.

### Catálogo de avisos

| Tipo | Disparo por defecto | Fuente | Se salta si… |
|---|---|---|---|
| `CLIENTE_FACTURAR` | Día de `PartyBillingSchedule`, + recordatorio a los 2 días | `party_billing_schedules` × `sales_documents` | Ya hay factura al cliente en el período |
| `IVA_DECLARACION` | Offsets −7, −3, −1, 0 sobre `TaxPeriod.due_date` | `tax_periods` + `tax_tasks` abiertas | `status == 'DECLARADO'` |
| `IVA_PREVIEW_MENSUAL` | Último día hábil del mes, 17:00 | `services/tax/iva.compute_iva` | — (informativo, siempre marcado **preliminar**) |
| `RESUMEN_MENSUAL` | Días 3 y 5 del mes siguiente | Ventas + compras + cartera + CxP | — |
| `IESS_APORTE` | Offsets −5, −2, −1 sobre el 15 | `payroll_entries.aporte_iess` del mes anterior | Acuse humano registrado (`require_ack`) |
| `NOMINA_ROL` | Día 25 | `payroll_periods` en DRAFT | Período ya `APPROVED` |
| `CARTERA_VENCIDA` | Lunes 08:00 | Aging existente | No hay saldo vencido |
| `CXP_PROXIMO_PAGO` | Offsets −3, −1 | `supplier_payment_schedules.scheduled_date` | Pago ya registrado |
| `RENOVACION_CONTRATO` | `renewal_notice_days` antes de `valid_to` | `commercial_contract_versions` | Ya hay versión nueva |
| `SRI_RECHAZO` | Inmediato (por evento, no calendario) | `sri_transmissions` REJECTED | — |
| `EVIDENCIA_INCOMPLETA` | Días 5 y 15 | `tax_tasks` BAJAR_COMPROBANTES / COMPLETAR_EVIDENCIA | No hay tareas abiertas |

Los tres últimos son extras que caen solos porque los datos ya existen; el
usuario pidió "lo que se te ocurra".

### Barandas de contenido (esto define la credibilidad del módulo)

- **IVA preliminar es preliminar.** Si `compute_iva` reporta documentos
  preliminares o sin desglose, el correo dice "cifra incompleta — faltan N
  comprobantes" en lugar del número. Es la misma regla que ya aplica Tributario
  ("bloquea cifras parciales", `docs/STATUS.md`).
- **Cada cifra dice de dónde sale.** Nº de documentos y período, siempre.
- **Ningún aviso afirma que algo se declaró o pagó.** Solo que toca hacerlo.
- **Los avisos leen `TaxTask`, no crean una segunda verdad.** El scheduler
  tributario ya genera pendientes; duplicar esa lógica produce dos estados que
  se contradicen.

### Transporte Brevo (`integrations/notifications/brevo.py`)

- API transaccional: `POST https://api.brevo.com/v3/smtp/email`, header
  `api-key`. **Un request por destinatario** → un `NotificationDelivery` por
  persona, con su `provider_message_id`. Más caro en requests, pero permite
  trazar rebotes y bajas individuales.
- Clave por cuenta vía `api_key_vault_ref`. Nunca en BD, nunca en logs, nunca
  en el payload del outbox.
- En dev y CI: `StubEmailSender` activo por defecto (**cero red en tests**,
  regla ya vigente del repo).
- Webhook `POST /webhooks/brevo` para `delivered` / `bounce` / `spam` →
  actualiza `NotificationDelivery`. Firma validada; existe el precedente de
  `valid_meta_signature` en `crm_integrations.py:841`.
- Reintentos: los del outbox + Celery. No inventar un mecanismo propio.

### Dónde corre

Un `run_notification_scheduler()` más en `workers/dispatcher.py:48`, junto a
los tres que ya viven ahí, y un handler `notification.due` registrado en
`_HANDLERS_BY_EVENT_TYPE` (`workers/tasks.py:75`). **No hace falta Celery
beat**: el patrón del repo es bucle asíncrono + outbox, y funciona.

Todo se programa en `America/Guayaquil` y se persiste en UTC, igual que
`collections.py:60`. Día 31 en meses de 30 → último día del mes (explícito y
probado).

### API (`backend/app/api/notifications.py`, prefijo `/notifications`)

Scopes nuevos `notifications:read` / `notifications:write`.

```
GET  /notifications/rules                    PUT  /notifications/rules/{id}
GET  /notifications/templates/{rule_type}    PUT  /notifications/templates/{rule_type}
POST /notifications/templates/{rule_type}/preview
GET  /notifications/events?status=           POST /notifications/events/{id}/ack
POST /notifications/events/{id}/resend
GET  /notifications/channel-account          PUT  /notifications/channel-account
POST /notifications/channel-account/test
GET|POST|PUT /billing-schedules
POST /webhooks/brevo                         (público, firmado)
```

Escrituras con `execute_idempotent` y `append_audit`, como el resto del repo.

> ⚠️ **Acción manual en Keycloak de producción.** Los scopes nuevos hay que
> crearlos en el realm a mano: la instancia no se reimporta. Ya pasó con
> `tax:read`/`tax:write` y dejó la sección rota en producción — el
> procedimiento exacto está en [`TAX_MODULE_PLAN.md`](TAX_MODULE_PLAN.md#-accion-requerida-en-keycloak-de-produccion).

### Frontend (`frontend/src/components/notifications/`)

`NotificationsPage.tsx` con tres pestañas, patrón `Erp*`, carga lazy con
`ErrorBoundary` + `Suspense` (igual que Nómina en `App.tsx`):

1. **Reglas** — lista por tipo con interruptor, días, hora y destinatarios.
2. **Plantillas** — editor con marcadores y vista previa con datos reales.
3. **Bitácora** — eventos con estado, destinatarios, acuse y reenvío.

Entrada "Avisos" en el grupo Administración del `Sidebar.tsx`. El calendario de
facturación vive dentro de la ficha del cliente, no aquí. La conexión Brevo va
como tarjeta en **Empresa**, junto a las demás integraciones.

---

## Estado de F1 (implementado)

| Pieza | Dónde |
|---|---|
| Modelos (5 tablas) | `models/notifications.py`, migración `e3f4a5b6c7d8` |
| Catálogo y defaults | `services/notifications/catalog.py` |
| Aritmética de calendario | `services/notifications/scheduling.py` |
| Planificador idempotente | `services/notifications/planner.py` |
| Destinatarios, plantillas y entrega | `services/notifications/delivery.py` |
| Transporte | `integrations/notifications/email_sender.py` |
| Despacho por outbox | `workers/notifications.py`, cableado en `dispatcher.py` y `tasks.py` |
| Pruebas | `tests/test_notifications_foundation.py` (21) |

Decisiones que conviene no revertir sin pensarlo:

- **Las reglas nacen apagadas.** Nada sale hasta que una persona lo enciende.
- **`uq_notification_events_tenant_dedupe_key` es la garantía real**, no el
  `SELECT` previo del planificador: verificado quitando esa primera capa y
  comprobando que el aviso sigue sin duplicarse.
- **El stub reporta `STUBBED`, nunca `SENT`.** Una bitácora de pruebas no puede
  ser indistinguible de la de producción. Por eso `STUBBED` existe también como
  estado de `NotificationEvent`.
- **La condición de "ya no corresponde" se revisa dos veces**, al programar y al
  entregar: entre ambos momentos pasan días y avisar de una declaración ya
  presentada es lo que enseña a la gente a ignorar los avisos.
- **El correo advierte que los feriados no están verificados** mientras nadie
  cargue el calendario, en vez de mostrar una fecha que aparente estar confirmada.

Lo que F1 **no** trae, por diseño: API REST y pantalla (F4), y los otros diez
avisos del catálogo (F3 y F5). El esquema ya los admite sin migración nueva.

## Fases

Cada fase cierra con CI verde y commit propio (regla 3 de `COORDINACION_IA.md`).

| # | Fase | Entregable | Cierra cuando |
|---|---|---|---|
| **F0** | Prerequisitos | ✅ `due_dates.py` + migración; ✅ decisión de alcance Brevo (opción A); ⏳ dominio verificado y calendario de feriados | Un período de IVA muestra su fecha límite correcta según el noveno dígito ✅ |
| **F1** | Fundación | ✅ Modelos + migración `e3f4a5b6c7d8` + planificador + `StubEmailSender` + `IVA_DECLARACION` completo | ✅ El planificador corre tres veces el mismo día y genera **un** evento |
| **F2** | Transporte | `brevo.py` + `NotificationDelivery` + webhook + envío de prueba | Un correo real llega a la bandeja del usuario y el webhook marca `delivered` |
| **F3** | Catálogo | `PartyBillingSchedule` + `CLIENTE_FACTURAR`, `IESS_APORTE`, `RESUMEN_MENSUAL`, `IVA_PREVIEW_MENSUAL` | Cada aviso se salta solo cuando su condición ya se cumplió |
| **F4** | Parametrización | `NotificationsPage.tsx` (3 pestañas) + calendario en la ficha del cliente | Cambiar el día de un aviso desde la UI cambia el envío, sin redeploy |
| **F5** | Cierre | Resto del catálogo + acuse + digest agrupado por día | Un día con 4 avisos manda 1 correo, no 4 |

**F1 es la fase que decide el módulo.** Si el scheduler genérico + `dedupe_key`
quedan bien, agregar el aviso número 11 es media hora. Si quedan mal, cada
aviso nuevo trae su propio bug de duplicados.

## Verificación por fase

- **Backend:** `uv run pytest tests/test_notifications*.py -v`, sin red.
  Obligatorias: (a) el scheduler es idempotente en corridas repetidas; (b) cada
  regla respeta su condición de "se salta si…"; (c) fin de mes con día 31; (d)
  aislamiento multi-tenant en destinatarios y `dedupe_key`.
- **Frontend:** E2E Playwright `notifications.spec.ts` + WCAG, como el resto.
- **Integración:** envío de prueba a la propia cuenta antes de habilitar
  cualquier regla en producción.

## Riesgos

| Riesgo | Mitigación |
|---|---|
| **Fatiga de correo** — 11 tipos × varios offsets = ruido, y el usuario los filtra | Digest agrupado por día (F5); `require_ack` solo en IESS y declaración; todo apagado por defecto y se enciende de a uno |
| **Un aviso con una cifra equivocada** destruye la confianza en el módulo entero | Barandas de contenido: preliminar se marca como preliminar, cada cifra dice su origen |
| Doble verdad con `TaxTask` | Los avisos leen, no crean pendientes |
| Correo a spam | Dominio verificado (P0.3) antes de cualquier regla activa |
| Fuga de la API key de Brevo | Solo `vault_ref`; nunca en BD, logs ni payload del outbox |
| Scopes ausentes en Keycloak de producción | Documentado arriba; se aplica a mano antes de promover |

## Decisiones pendientes del usuario

1. ~~**Alcance de Brevo**~~ — ✅ resuelto: opción A, solo avisos internos.
2. **Calendario de feriados** del año, y el del IESS (P0.3).
3. **Destinatarios por defecto**: ¿todos los usuarios con rol `owner`, o una
   lista explícita de correos por cuenta? (recomendación: por rol, con lista
   explícita como override).
4. **Confirmar el catálogo**: qué avisos entran en F3 y cuáles pueden esperar.

---

## Reglas de trabajo

- Fases pequeñas, commit y push en cuanto algo esté verde.
- No debilitar ni borrar pruebas para forzar CI verde (regla 5 de
  `COORDINACION_IA.md`).
- Actualizar este documento y `docs/STATUS.md` al cerrar cada fase.
