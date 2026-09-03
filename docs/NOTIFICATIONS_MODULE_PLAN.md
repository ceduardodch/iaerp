# Módulo de avisos (notificaciones operativas) — plan de trabajo

> Documento de **relevo**: quien retome este módulo lee esto antes de tocar
> código. Coordinación general: [`COORDINACION_IA.md`](../COORDINACION_IA.md).
> Estado del proyecto: [`docs/STATUS.md`](STATUS.md).

**Última actualización:** 2026-09-03 (F4 completada — módulo funcionalmente completo)
**Estado:** ✅ F0, F1, F2, F3 y F4 completas. El módulo se configura entero
desde la web: reglas, plantillas, bitácora, calendario de facturación y canal
Brevo. El envío real se activa solo cuando existan `BREVO_API_KEY` y
`BREVO_SENDER_EMAIL`; sin ellas sigue en stub. Todas las reglas siguen
apagadas por defecto hasta que una persona las encienda.

> ✅ **Keycloak de producción ya tiene los scopes.** `notifications:read` y
> `notifications:write` se crearon a mano el 2026-09-03 y quedaron como
> *Default* en `iaerp-web` (verificado contra el discovery del realm). No
> queda acción pendiente de este tipo.
> Ya pasó con `tax:*` y dejó la sección rota en producción.

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

### P0.2b · ✅ Una sola cuenta Brevo, la de IAERP

Decidido el 2026-09-02 (revisa una decisión anterior del mismo día, que ponía
una cuenta por tenant). **IAERP tiene una única cuenta de Brevo.** Cada empresa
configura desde la web solo su identidad de remitente, nunca una clave.

Consecuencias para F2:

- **La API key es un secreto de plataforma, no de tenant**: vive en la
  configuración del servidor (env/vault), igual que las demás credenciales de
  infraestructura. Nunca llega por HTTP ni se guarda por tenant.
- `notification_channel_accounts` se queda como está y **no necesita columna
  para la clave**. Lo que guarda por tenant es identidad de envío:
  `sender_email`, `sender_name` y (a agregar) `reply_to`.
- No hay que cifrar nada con Fernet ni construir pantalla de API key. F2 se
  reduce a: cliente Brevo, resolución del remitente por tenant, bitácora de
  entregas y webhook de rebotes.

**El punto que decide si esto funciona: qué dominio va en el `From`.** Brevo
solo deja enviar desde dominios autenticados en la cuenta, así que hay dos
caminos y conviene elegir a conciencia:

| Estrategia | Qué implica |
|---|---|
| **Dominio propio de IAERP (recomendada)** | El `From` es `avisos@<dominio-iaerp>` con el nombre de la empresa como display, y el `Reply-To` apunta al correo del tenant. **Cero trabajo de DNS por cliente**: se verifica un dominio una vez y sirve para todos. |
| Dominio de cada cliente | El `From` es `avisos@sucliente.com`. Exige que cada cliente agregue registros DKIM/SPF a **su** DNS apuntando a la cuenta Brevo de IAERP. Se ve más propio, pero cada alta se bloquea hasta que alguien toque el DNS del cliente. |

La recomendada es la primera: con una sola cuenta, la gracia es justamente no
depender del DNS ajeno para dar de alta a una empresa. La segunda queda
disponible por tenant para quien la pida y pueda tocar su DNS.

El motivo: hoy el correo de cobranza vive en un hilo de Gmail real
(`send_google_email_with_thread`) y las respuestas del cliente se sincronizan a
la bandeja (`sync_google_inbox`). Mandarlo por Brevo rompería ese hilo. Brevo
es excelente para correo transaccional saliente, que es justamente lo que son
los avisos internos. Si alguna vez se quiere mover la cobranza, se hace con un
ADR propio.

### Estado real del remitente (verificado 2026-09-03)

Remitente elegido: **`notificaciones@b2b.com.ec`**. Se descartó un buzón
personal (`carlos.diaz@…`) porque con una sola cuenta ese `From` lo ven todos
los clientes, y las respuestas y rebotes de todos caerían en una bandeja
personal. El `Reply-To` sí es por empresa (`NotificationChannelAccount.reply_to`).

| Registro DNS de `b2b.com.ec` | Estado |
|---|---|
| SPF con `include:spf.brevo.com` | ✅ Añadido al registro existente (no uno nuevo) |
| Consultas DNS del SPF | ✅ 6 de 10 — sin riesgo de `permerror` |
| DKIM Brevo | ✅ `brevo1._domainkey` y `brevo2._domainkey` → `*.dkim.brevo.com` |
| Subdominio de marca | ✅ `notificaciones.b2b.com.ec` → `brand.brevosend.com` |
| DMARC | ✅ Publicado, `p=none` |

El dominio figura como **Authenticated** y **Branded** en el panel de Brevo, así
que los correos firman con DKIM alineado a `b2b.com.ec` y DMARC pasa: la
entregabilidad no es un problema pendiente.

> 📌 **Nota para quien verifique el DNS a mano:** Brevo publica el DKIM como
> **CNAMEs numerados** (`brevo1._domainkey`, `brevo2._domainkey`), no como un
> TXT en `brevo._domainkey` ni en `mail._domainkey`. Consultar esos selectores
> da vacío y hace creer que falta la autenticación cuando está completa.
> El registro `brevo-code` solo interviene en la verificación inicial del
> dominio; una vez autenticado, su ausencia no significa nada.

### P0.3 · ⏳ Insumos del usuario (no se pueden generar desde el código)

- **Una** cuenta Brevo de IAERP, con **un dominio verificado** (SPF, DKIM,
  DMARC). Sin esto los correos caen en spam y el módulo parece roto cuando no
  lo está. Con la estrategia recomendada se verifica una sola vez, no por
  cliente.
- API key de esa cuenta → configuración del servidor, **nunca a la BD** ni por
  HTTP.
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

### Frontend (`frontend/src/components/notifications/`) — ✅ implementado

`NotificationsPage.tsx` con **cinco** pestañas, patrón `Erp*`, carga lazy con
`ErrorBoundary` + `Suspense` (igual que Nómina en `App.tsx`):

1. **Reglas** — lista por tipo con interruptor, calendario y destinatarios.
2. **Plantillas** — editor con marcadores, vista previa y restaurar default.
3. **Bitácora** — eventos con estado, detalle de entregas, acuse y reintento.
4. **Calendario de facturación** — CRUD de `PartyBillingSchedule` por cliente.
5. **Canal (Brevo)** — estado, remitente y envío de prueba.

Entrada "Avisos" en el grupo Administración del `Sidebar.tsx`.

**Desviación deliberada del diseño original:** el boceto inicial preveía 3
pestañas, con el calendario de facturación en la ficha del cliente y Brevo
como tarjeta en Empresa. Se cambió porque **no existe una vista de "ficha del
cliente"** en el código — `PartiesPage` vive inline dentro de `App.tsx` (4800+
líneas) sin una ruta de detalle por contacto. Construir esa vista habría sido
un cambio mucho más grande y riesgoso que lo que pedía F4. Las cinco pestañas
dentro de `NotificationsPage` logran la misma capacidad (ver/editar el
calendario por cliente, configurar Brevo) sin tocar ese archivo.

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

## Estado de F3 (implementado)

Cuatro avisos más, sobre el mismo planificador. 17 pruebas en
`tests/test_notifications_catalog.py`.

| Aviso | Cuándo | Se calla cuando |
|---|---|---|
| `CLIENTE_FACTURAR` | Día del `PartyBillingSchedule`, más recordatorio a los 2 días | Ya hay factura emitida al cliente en el período |
| `IESS_APORTE` | −5, −2, −1 sobre el 15 del mes siguiente al rol | Hay acuse humano para ese período |
| `RESUMEN_MENSUAL` | Días 3 y 5, sobre el mes cerrado | Informativo, no se calla |
| `IVA_PREVIEW_MENSUAL` | Último día hábil, 17:00 | Informativo, no se calla |

Barandas de contenido que cada uno lleva:

- **IESS:** el rol solo tiene el aporte **personal** (9,45%); el patronal
  (11,15%) no se calcula en ninguna parte de IAERP. El correo lo dice
  explícitamente, porque leer esa cifra como el total de la planilla lleva a
  pagar de menos.
- **Avance de IVA:** si `compute_iva` reporta evidencia incompleta, el correo
  dice "cifras INCOMPLETAS" y lista los motivos, en vez de mostrar un número
  que parezca declarable.
- **Resumen mensual:** avisa cuántas compras están preliminares, porque el
  egreso puede subir cuando se complete su respaldo.
- **Facturar a cliente:** el `amount_hint` se presenta como referencia del
  calendario, nunca como el valor a facturar.

Detalles del calendario que estaban en el aire y quedaron resueltos: un ciclo
configurado el 31 se recorta al último día real del mes (quien puso 31 espera
un aviso a fin de mes, también en abril), y un ciclo no mensual exige
`anchor_month` — sin ancla el aviso caería en el mes equivocado, así que la
base lo impide con un `CHECK` en vez de adivinar.

## Estado de F2 (implementado)

29 pruebas en `tests/test_notifications_channel.py`, ninguna abre red: el
cliente se ejercita contra un transporte `httpx` simulado.

| Pieza | Dónde |
|---|---|
| Cliente Brevo | `integrations/notifications/brevo.py` |
| Proveedor y remitente por tenant | `services/notifications/channels.py` |
| Rebotes y quejas | `services/notifications/webhooks.py` |
| Estado, remitente, prueba y webhook | `api/notifications.py` |
| `reply_to` del tenant | migración `a5b6c7d8e9f0` |

### Variables de entorno (Coolify, nunca en Git)

| Variable | Para qué | Sin ella |
|---|---|---|
| `BREVO_API_KEY` | Clave de la cuenta de plataforma | Sigue el stub: registra `STUBBED`, no envía |
| `BREVO_SENDER_EMAIL` | `From` sobre el dominio verificado | El canal reporta `ready=false` con el motivo |
| `BREVO_SENDER_NAME` | Nombre visible por defecto | Usa `IAERP` |
| `BREVO_WEBHOOK_TOKEN` | Secreto en la ruta del webhook | El webhook responde 404 a todo |

Decisiones que conviene no revertir:

- **Un request por destinatario**, no un envío agrupado. Cuesta más llamadas,
  pero es lo único que permite guardar un `provider_message_id` por persona y
  cruzar después un rebote con quien no recibió el aviso.
- **`send` nunca lanza**: devuelve `FAILED`. Un correo mal escrito no puede
  impedir que el resto del equipo reciba el aviso.
- **El error se limpia con la clave concreta del cliente**, además del patrón
  genérico. La primera versión del patrón dejaba pasar
  `api-key': 'xkeysib-...'` porque las comillas cortaban la coincidencia; lo
  descubrió una prueba y por eso ahora se borra el valor exacto y se corta
  desde la palabra clave hasta el fin de línea.
- **Brevo no firma sus webhooks**, así que el secreto va en la ruta, igual que
  el webhook de Evolution. Un token que no coincide responde **404**, no 401:
  un endpoint público no debería confirmarle a nadie que existe.
- **Un `delivered` que llega después de un rebote no lo deshace.** El desenlace
  negativo es el que importa.
- **El estado del canal es consultable** (`GET /notifications/channel-account`)
  y el envío de prueba responde 422 con el motivo si algo falta. Un módulo de
  correo que falla en silencio es indistinguible de uno roto.

### Contrato con Brevo, verificado contra la API publicada (2026-09-03)

Un transporte simulado responde lo que uno le diga, así que valida el manejo de
errores pero **no** si el proveedor entiende el payload. Se contrastó campo por
campo contra la referencia de `POST /v3/smtp/email` y coincide: endpoint,
cabecera `api-key`, `sender {email,name}`, `to [{email}]`, `subject`,
`textContent`, `htmlContent`, `replyTo {email}` y `messageId` en la respuesta
201. Brevo además devuelve `messageIds` en plural y como lista cuando hay
varias versiones; el cliente ya lo contempla.

Eso quedó fijado en `test_payload_matches_the_documented_brevo_contract`, para
que un cambio de contrato lo detecte el CI y no un aviso que no llega.

### Configuración real, verificada en producción (2026-09-03)

`GET /notifications/channel-account` respondió:

```json
{"provider":"BREVO","platformKeyConfigured":true,
 "senderEmail":"notificaciones@b2b.com.ec","ready":true,"blockingReason":null}
```

Eso confirma de una sola vez: la app lee `BREVO_API_KEY` (el nombre en Coolify
coincide), el remitente está puesto, el proveedor ya no es el stub, y los scopes
`notifications:*` funcionan de punta a punta en Keycloak.

### Lo único que falta

**Un correo real llegando a una bandeja real.** Es el criterio de salida de F2 y
sigue sin cumplirse: requiere disparar
`POST /notifications/channel-account/test` con un token de sesión. Lo que queda
por comprobar ahí es que la clave sea válida y que el mensaje se entregue -- el
formato ya está verificado.

Recién después de ese correo se debería encender la primera regla.

## Fases

Cada fase cierra con CI verde y commit propio (regla 3 de `COORDINACION_IA.md`).

| # | Fase | Entregable | Cierra cuando |
|---|---|---|---|
| **F0** | Prerequisitos | ✅ `due_dates.py` + migración; ✅ decisión de alcance Brevo (opción A); ⏳ dominio verificado y calendario de feriados | Un período de IVA muestra su fecha límite correcta según el noveno dígito ✅ |
| **F1** | Fundación | ✅ Modelos + migración `e3f4a5b6c7d8` + planificador + `StubEmailSender` + `IVA_DECLARACION` completo | ✅ El planificador corre tres veces el mismo día y genera **un** evento |
| **F2** | Transporte | ✅ `brevo.py` + `channels.py` + `webhooks.py` + envío de prueba + migración `a5b6c7d8e9f0` | ⏳ Falta la prueba real: un correo llega a la bandeja y el webhook marca `delivered` |
| **F3** | Catálogo | ✅ `PartyBillingSchedule` (migración `f4a5b6c7d8e9`) + `CLIENTE_FACTURAR`, `IESS_APORTE`, `RESUMEN_MENSUAL`, `IVA_PREVIEW_MENSUAL` | ✅ Cada aviso se salta solo cuando su condición ya se cumplió |
| **F4** | Parametrización | ✅ 12 endpoints REST + `NotificationsPage.tsx` (5 pestañas) | ✅ Cambiar el día de un aviso desde la UI cambia el envío, sin redeploy |
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
