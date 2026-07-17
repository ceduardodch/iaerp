# Sprint 3 - Cuentas por cobrar

## Estado

In progress (corte 2026-07-05). Diseno completo y aprobado para iniciar
implementacion; ningun codigo de este sprint esta escrito todavia. El trabajo
sin commitear de Sprint 2 en `release` (facturacion y SRI) sigue integro y no
debe descartarse: es la base sobre la que corre este sprint.

## Objetivo

Entregar en `release` el ciclo completo de cartera de clientes -receivable
trazable a su factura de origen, vencimientos que suman el monto original,
cobros parciales con retenciones y descuentos auditados, aplicacion de nota de
credito, aging reproducible por fecha local, reverso auditado de un
movimiento y recordatorios como interfaz reemplazable (P1, stub local sin
envio real)- de forma que **la cartera coincide siempre con los documentos de
Billing y sus movimientos**: ningun saldo se edita a mano, todo saldo se
deriva de `Receivable` + `ReceivableAllocation`/`CreditAllocation` y es
reconciliable contra `SalesDocument`.

## Historias

| Orden | IDs | Entrega | Owner experto |
| --- | --- | --- | --- |
| 1 | E5-01, E5-02 | Receivable creado desde factura autorizada + vencimientos que suman el monto original | Backend Platform |
| 2 | E5-03, E5-04 | Cobro parcial con saldo exacto, retenciones y descuentos auditados, sin sobreaplicar | Backend Platform |
| 3 | E5-08 | Aplicar nota de credito autorizada contra cartera o saldo a favor | Backend Platform + Ecuador SRI |
| 4 | E5-05 | Aging por rangos reproducibles en fecha local `America/Guayaquil` | Backend Platform |
| 5 | E5-09 | Reverso de movimiento como compensacion auditada, sin editar el original | Backend Platform |
| 6 | E5-06, E5-07 (P1) | Interfaz `Notifier` con `StubNotifier` local; recordatorio registrado sin envio real | Backend Platform |
| 7 | E7-04 | Tools MCP `receivables.list`/`record_payment`/`send_reminder` sobre los mismos casos de uso | MCP AI Security |
| 8 | E9-01 a E9-07 | Dataset `sprint-03-v1`, pruebas de saldo/aging, integracion de movimientos y E2E de cobro | QA Reliability |
| 9 | — | UI de cartera (lista con aging, drawer de cobro, aplicar NC, reverso) | Frontend A11y + Product ERP |

## Decisiones de diseno

Numeradas en el orden en que el prompt de coordinacion las plantea.

1. **Modelo de datos**. `Receivable` (cabecera: `sales_document_id` origen,
   `party_id`, `original_amount`, `currency`, `status`
   `OPEN`/`PARTIALLY_PAID`/`PAID`/`VOID`, `1:1` con la factura que lo origina).
   `ReceivableInstallment` (vencimiento: `due_date`, `amount`, `paid_amount`
   derivado, `sequence`; la suma de `amount` de las cuotas de un receivable
   siempre es igual a `original_amount`, verificado al crear). `Movement`
   (tabla unica de aplicaciones, no una tabla por tipo): `movement_type` en
   `PAYMENT`, `RETENTION`, `DISCOUNT`, `CREDIT_NOTE`, `REVERSAL`; `amount`
   siempre `>= 0` (nunca signo negativo en la columna: el efecto sobre el
   saldo lo determina `movement_type`, `REVERSAL` resta lo que su
   `reversed_movement_id` habia sumado); `installment_id` (a que cuota
   aplica, nunca al receivable en bloque, para que el saldo por cuota sea
   siempre reconstruible); `support_reference` (texto libre: numero de
   retencion, motivo de descuento, id de nota de credito); `reversed_movement_id`
   nulo salvo en `REVERSAL`. `CustomerCredit` (saldo a favor cuando una NC
   excede el saldo abierto de la factura: `party_id`, `origin_credit_note_id`,
   `amount`, `remaining_amount`). Dinero siempre `Numeric(18, 2)`/`Decimal`,
   igual que `SalesDocument` (ADR 0004). Todo modelo nuevo usa
   `TenantEntityMixin` + `UUIDPrimaryKeyMixin` + `TimestampMixin`, igual que
   `billing.py`.
2. **Reglas de saldo**. El saldo nunca se guarda como columna de verdad en
   `Receivable`/`ReceivableInstallment` (coherente con
   `docs/03-domain-model.md`: "Nunca se guarda un saldo como unica fuente de
   verdad"); se calcula en cada operacion como
   `amount - sum(movements no-REVERSAL activos) + sum(REVERSAL que los
   deshacen)` y se valida ANTES de insertar un movimiento nuevo dentro de la
   misma transaccion: `sum(aplicaciones) <= saldo de la cuota` (nunca
   sobreaplicar) y el resultado nunca es negativo (422 si se excede, mismo
   patron de mensaje que `create_credit_note` en `services/billing.py`
   informa "available"/"requested"). Concurrencia: `SELECT ... FOR UPDATE`
   sobre la fila `Receivable` (no la cuota individual, para serializar todas
   las aplicaciones de un mismo receivable y evitar que dos cobros
   concurrentes sobreapliquen cuotas distintas de la misma cabecera) dentro de
   la transaccion que inserta el `Movement`, mismo patron que
   `_reserve_sequential` usa sobre `Sequence` y que `execute_idempotent` usa
   sobre `Tenant`. Un `CHECK` de base de datos (`amount >= 0`) en `Movement`
   y en `ReceivableInstallment.paid_amount` (columna derivada, ver decision 3)
   es la defensa adicional, igual que el `UniqueConstraint` adicional al lock
   en `SalesDocument`/`Sequence`.
3. **Vista de saldo: calculada on-demand, no materializada**. Una funcion de
   servicio (`services/receivables.py::compute_installment_balance`) suma los
   movimientos activos de una cuota bajo el mismo lock del punto 2; no existe
   columna `open_amount` persistida en `ReceivableInstallment` que pueda
   desincronizarse (la razon explicita del invariante de dominio). El listado
   `GET /receivables` (`AccountItem`) SI expone `openAmount` calculado en la
   consulta (agregacion SQL, no columna), evitando el N+1 de traer todas las
   cuotas/movimientos al API layer. Se acepta el costo de recalcular en cada
   lectura porque el volumen esperado por tenant (cientos de cuotas, no
   millones) no lo justifica; si el aging se vuelve lento se evalua un ADR de
   materializacion con reconciliacion, no antes.
4. **Aging**. Buckets fijos y deterministas: `CURRENT` (no vencido),
   `1-15`, `16-30`, `31-60`, `61-90`, `90+` dias de mora, calculados como
   `fecha_de_corte_local - due_date` en dias, con `fecha_de_corte_local`
   siempre `date.today()` en `America/Guayaquil` (mismo `ZoneInfo` que
   `services/billing.py::_today_in_fiscal_timezone`, extraido a
   `app/core/timezones.py` para no duplicar el `ZoneInfo("America/Guayaquil")`
   entre Billing y Receivables). El bucket se calcula por **cuota**, no por
   receivable completo (una factura con 3 cuotas puede tener una vencida y
   dos vigentes a la vez); `OVERDUE` en `AccountItem.status` es el estado
   derivado (invariante 13 del dominio: "no es una transicion persistida"),
   nunca se persiste como columna de `Receivable`. Reproducible porque el
   calculo es una funcion pura de `(due_date, saldo, fecha_de_corte)`: la
   misma cuota con la misma fecha de corte siempre cae en el mismo bucket, en
   cualquier entorno. Vista calculada on-demand (mismo razonamiento que
   decision 3): `GET /receivables?dueBefore=...` y una consulta interna de
   aging agregan sobre cuotas abiertas sin materializar.
5. **Integracion con facturacion: automatico via evento `invoice.authorized`,
   no endpoint explicito**. Se agrega un evento de dominio nuevo
   `invoice.authorized` que `workers/sri_transmission.py` escribe a
   `OutboxEvent` en la MISMA transaccion en que marca el `SalesDocument` como
   `AUTHORIZED` (hoy esa transicion ocurre sin publicar un evento; es un
   cambio aditivo minimo al handler existente, no una reescritura). Un
   consumidor nuevo `workers/receivables.py::handle_invoice_authorized`
   (mismo patron inbox/dedupe por `event_id` que
   `workers/sri_transmission.py`) crea el `Receivable` + sus
   `ReceivableInstallment` a partir de `SalesDocument.total` y las
   `InstallmentInput` ya guardadas en `InvoiceInput.installments`
   (`app/schemas/billing.py`, hoy aceptadas y descartadas segun su propio
   docstring: "esta fase no crea Receivable... corresponde a una fase
   posterior"). Si `installments` tenia una sola cuota igual al total (caso
   por defecto cuando el usuario no definio plan de pago), se genera un
   receivable de una cuota con `due_date = issue_date` (pago de contado). Se
   elige el flujo asincrono por outbox en vez de un endpoint explicito porque
   (a) es coherente con el resto de efectos derivados de `AUTHORIZED` (ADR
   0006), (b) evita que el cliente HTTP tenga que orquestar "emitir factura y
   luego crear receivable" como dos llamadas separadas con riesgo de olvidar
   la segunda, y (c) una nota de credito NUNCA genera receivable propio (solo
   aplica contra el de la factura, decision 6), asi que el unico disparador
   valido es la autorizacion de una `INVOICE`, que ya es un evento de
   dominio. Las cuotas de la factura (`InstallmentInput`) y los vencimientos
   del receivable (`ReceivableInstallment`) son la misma cosa vista desde dos
   lados del ciclo de vida: la factura declara el plan de pago propuesto en
   el borrador (antes de saber si el SRI autoriza), el receivable materializa
   ese plan como cartera exigible solo cuando el documento es firme
   (`AUTHORIZED`). No existe endpoint `POST /receivables`: la unica forma de
   crear un receivable es este evento (el contrato ya publicado en Sprint 0
   nunca declaro un POST de creacion manual, solo lectura/cobro/recordatorio,
   lo que confirma esta decision retroactivamente).
6. **Aplicar nota de credito (E5-08)**. `workers/sri_transmission.py` publica
   tambien `credit_note.authorized` cuando una `CREDIT_NOTE` llega a
   `AUTHORIZED` (mismo cambio aditivo que en decision 5). Un handler
   `handle_credit_note_authorized` resuelve la factura relacionada via
   `DocumentRelation` (ya existe, Sprint 2), localiza su `Receivable` y
   aplica el `total` de la NC como un `Movement` tipo `CREDIT_NOTE` bajo el
   mismo lock/regla de saldo de la decision 2, distribuido contra las cuotas
   abiertas en orden de vencimiento (mas antigua primero). Si el `total` de
   la NC excede el saldo abierto del receivable, el excedente crea/incrementa
   un `CustomerCredit` del mismo `party_id` (nunca deja `open_amount`
   negativo, coherente con el invariante de dominio "el excedente... se
   convierte en CustomerCredit; nunca produce cartera negativa"). Idempotente
   por `access_key` de la NC: un `Movement` tipo `CREDIT_NOTE` guarda la
   `access_key` en `support_reference` con `UniqueConstraint
   (tenant_id, movement_type, support_reference)` cuando `movement_type =
   CREDIT_NOTE`, para que un reintento del evento (inbox ya dedupe por
   `event_id`, esta es la segunda barrera igual que el `UniqueConstraint` de
   `SalesDocument.access_key`) nunca aplique la misma NC dos veces.
7. **Reverso (E5-09)**. `POST /receivables/{receivableId}/movements/{movementId}/reversal`
   (nuevo, aditivo) crea un `Movement` tipo `REVERSAL` con
   `reversed_movement_id` apuntando al original; el original nunca se edita
   ni se borra (invariante 6 del dominio: "documento financiero contabilizado
   no se elimina fisicamente"). El efecto en saldo es aditivo por
   construccion: como el saldo se calcula sumando movimientos activos
   (decision 2/3), un `REVERSAL` simplemente deshace el efecto de su
   `movement_type` original (revertir un `PAYMENT` libera saldo en la cuota;
   revertir un `CREDIT_NOTE` reabre saldo en el receivable y, si genero
   `CustomerCredit`, lo reduce en la misma transaccion). Reglas: no se puede
   revertir un `REVERSAL` (evita cadenas infinitas; un error de reverso se
   corrige con un movimiento nuevo del tipo correcto, no revirtiendo el
   reverso), y un movimiento ya revertido no admite un segundo reverso
   (`UniqueConstraint (tenant_id, reversed_movement_id)`). Auditado con
   `append_audit` (`action="movement.reversed"`, `details` incluye
   `original_movement_id` y motivo obligatorio).
8. **Recordatorios (P1, interfaz reemplazable)**. `Protocol Notifier` en
   `app/integrations/notifications/protocol.py` con un solo metodo
   `send(reminder: ReminderRequest) -> ReminderResult`, mismo patron que
   `SRIClient` (Sprint 2). Implementacion activa por defecto:
   `StubNotifier` (`app/integrations/notifications/stub.py`): no abre
   conexion de red, solo registra `CollectionReminder` con
   `channel`/`template_id`/`recipient`/`status="STUBBED"` y lo devuelve; sirve
   para poblar la UI y probar el flujo completo sin credenciales.
   `EmailNotifier`/`WhatsAppNotifier` quedan como clases sin implementar
   (`NotImplementedError`, documentadas, igual que `SoapSRIClient` en Sprint
   2) para un sprint futuro con credenciales reales. `CollectionReminder`
   incluye `consent_opt_out: bool` en `Party`/`PartyContact` (campo nuevo,
   sin logica de captura real todavia: el endpoint respeta el flag si esta en
   `true` devolviendo 422, pero no hay UI de gestion de consentimiento en
   este sprint). Marcado explicitamente P1/parcial en criterios de aceptacion
   y en "No incluido".
9. **Tools MCP E7-04**. `contracts/mcp-tools.yaml` ya declara
   `receivables.list` (`receivables:read`, `effect: read`),
   `receivables.record_payment` (`receivables:write`, `effect: write`) y
   `receivables.send_reminder` (`receivables:notify`, `effect: external-write`)
   desde Sprint 0; este sprint las IMPLEMENTA sin renombrar ni cambiar forma,
   reutilizando `_tool_context`/`_require_automation_writes`/
   `execute_idempotent` exactamente como `invoices.*` en `mcp/server.py`.
   `receivables.list` es de solo lectura (no pasa por el kill switch, igual
   que `invoices.get`). `receivables.record_payment` y
   `receivables.send_reminder` requieren `_require_automation_writes` +
   idempotencia; ninguna permite saldo negativo ni bypassa el scope (la
   validacion de saldo vive en `services/receivables.py`, la misma funcion
   que usa el endpoint REST, nunca duplicada en la tool). El reverso (E5-09)
   NO se expone como tool MCP en este sprint (no esta en el catalogo
   declarado y revertir es una operacion sensible que se prefiere mantener
   solo en REST/UI humana hasta que haya una politica de automatizacion
   especifica para deshacer cobros); se documenta en "No incluido".
10. **Contratos**. Aditivo sobre lo ya declarado en Sprint 0/2:
    `openapi.yaml` ya tiene `GET /receivables`, `POST
    /receivables/{receivableId}/payments`, `POST
    /receivables/{receivableId}/reminders` y los schemas `AccountItem`,
    `PaymentInput`, `RetentionInput`, `DiscountInput`, `ReminderInput`,
    `InstallmentInput` completos y suficientes para este diseno; no se
    renombra ni se cambia ninguno. Se agregan solo: el path nuevo `POST
    /receivables/{receivableId}/movements/{movementId}/reversal` (decision 7,
    respuesta `AccountItem`), el campo de solo lectura
    `aging: {bucket: string, daysOverdue: integer}` en `AccountItem` (nuevo,
    opcional, no rompe consumidores existentes), y un schema
    `MovementRead`/endpoint `GET /receivables/{receivableId}/movements` para
    que la UI liste el historial de aplicaciones (necesario para el drawer,
    no declarado en Sprint 0 porque no existia el concepto de `Movement`
    todavia). `contracts/mcp-tools.yaml` no cambia de forma; solo se verifica
    que `AccountItem` referenciado en `outputSchema` de las tres tools ya
    declaradas siga siendo compatible tras el campo `aging` agregado.

## Secuencia tecnica

1. Backend Platform crea modelos (`models/receivables.py`: `Receivable`,
   `ReceivableInstallment`, `Movement`, `CustomerCredit`), migracion Alembic y
   `app/core/timezones.py` (extrae `ZoneInfo("America/Guayaquil")` compartido
   con `services/billing.py`).
2. Backend Platform agrega el evento `invoice.authorized` en
   `workers/sri_transmission.py` (cambio aditivo al handler existente que ya
   marca `AUTHORIZED`) y el consumidor `workers/receivables.py` que crea
   `Receivable`/`ReceivableInstallment` desde `InvoiceInput.installments`
   (E5-01, E5-02).
3. Backend Platform implementa `services/receivables.py`: calculo de saldo
   on-demand bajo lock (decision 2/3), registrar cobro con retenciones y
   descuentos como `Movement`s en una sola transaccion (E5-03, E5-04), y el
   endpoint `POST /receivables/{receivableId}/payments`.
4. Backend Platform + Ecuador SRI implementan `credit_note.authorized` y
   `handle_credit_note_authorized` (E5-08): aplicacion contra cuotas abiertas
   en orden de vencimiento y creacion de `CustomerCredit` cuando excede.
5. Backend Platform implementa aging (E5-05) como funcion pura reutilizada por
   `GET /receivables` y por la UI, y el reverso (E5-09) con su endpoint nuevo.
6. Backend Platform implementa `Notifier`/`StubNotifier` (P1) y el endpoint
   `POST /receivables/{receivableId}/reminders`.
7. MCP AI Security implementa `receivables.list`, `receivables.record_payment`
   y `receivables.send_reminder` sobre los mismos casos de uso de
   `services/receivables.py` (E7-04).
8. Frontend A11y + Product ERP construyen lista de cartera con aging ->
   drawer de cobro (retenciones/descuentos) -> aplicar NC visible como
   historial -> accion de reverso, reutilizando `components/erp/`.
9. QA Reliability construye el dataset `sprint-03-v1`, pruebas de
   saldo/aging/concurrencia, integracion de movimientos y E2E de cobro;
   emite recomendacion go/no-go.

## Plan de pruebas y datos

El dataset `sprint-03-v1` extiende `sprint-02-v1` (no lo reemplaza), agregando
para cada uno de los dos tenants ya existentes:

- un `Receivable` `OPEN` con 3 `ReceivableInstallment` (cuotas que suman
  exactamente el `total` de una factura `AUTHORIZED` nueva del seed, con al
  menos una cuota ya vencida a la fecha de corte y dos vigentes, para probar
  aging mixto dentro del mismo receivable);
- un `Receivable` `PARTIALLY_PAID` con un `Movement` `PAYMENT` parcial, un
  `Movement` `RETENTION` y un `Movement` `DISCOUNT` sobre la misma cuota,
  saldo resultante exacto documentado en el fixture;
- un `Receivable` `PAID` totalmente cobrado, incluyendo un `Movement`
  `REVERSAL` de un `PAYMENT` anterior seguido del `PAYMENT` correcto (para
  probar que el reverso no deja rastro de saldo negativo ni duplica);
- una nota de credito `AUTHORIZED` (reutilizando el patron de
  `sprint-02-v1`) aplicada contra un receivable con saldo suficiente
  (`Movement` `CREDIT_NOTE` sin excedente);
- una nota de credito `AUTHORIZED` cuyo `total` excede el saldo abierto del
  receivable relacionado, generando un `CustomerCredit` con
  `remaining_amount` documentado;
- un intento de cobro que se sobreaplica sobre una cuota puntual (caso
  negativo, debe rechazarse con 422 y saldo intacto);
- un `CollectionReminder` `STUBBED` (E5-06/E5-07 parcial) para verificar que
  el stub registra sin red y sin credenciales;
- vectores de aging: cuotas con `due_date` colocado exactamente en el limite
  de cada bucket (`CURRENT`, `1-15`, `16-30`, `31-60`, `61-90`, `90+`) contra
  una fecha de corte fija del fixture (no `date.today()` real), con el bucket
  esperado documentado.

Pruebas unitarias:

- `services/receivables.py`: calculo de saldo de una cuota con combinaciones
  de `PAYMENT`/`RETENTION`/`DISCOUNT`/`CREDIT_NOTE`/`REVERSAL`, incluyendo el
  limite exacto (saldo llega a 0.00) y el caso que se pasa por 0.01 (debe
  rechazarse);
- que la suma de `ReceivableInstallment.amount` de un receivable nunca
  difiere del `original_amount` (falla la creacion si no cuadra, protegiendo
  contra un evento `invoice.authorized` con `installments` mal sumadas);
- aging: los 6 buckets contra los vectores de fecha limite del dataset,
  determinismo con fecha de corte inyectada (no reloj real);
- reverso: revertir un `PAYMENT` libera exactamente el monto revertido;
  revertir un `REVERSAL` se rechaza; revertir un movimiento ya revertido se
  rechaza;
- aplicacion de nota de credito: dentro de saldo, en el limite exacto, y con
  excedente que genera `CustomerCredit` con el monto correcto;
- `StubNotifier`: registra `CollectionReminder` sin abrir socket (se verifica
  con un doble que falla el test si se intenta abrir red), y respeta
  `consent_opt_out=true` devolviendo el rechazo esperado.

Pruebas de integracion (PostgreSQL real):

- concurrencia real: dos cobros simultaneos sobre el mismo receivable/cuota
  nunca permiten que la suma de sus montos supere el saldo (lock `FOR UPDATE`
  probado con tareas concurrentes reales, mismo patron que el secuencial de
  Sprint 2);
- ciclo completo evento-driven: factura `AUTHORIZED` (worker real) produce
  `Receivable`+cuotas automaticamente sin llamada explicita del cliente;
- nota de credito `AUTHORIZED` (worker real) aplica contra el receivable
  relacionado sin intervencion manual, incluyendo el caso de excedente;
- reintento del evento `credit_note.authorized` (simulando reentrega del
  outbox) nunca aplica la misma NC dos veces (`UniqueConstraint` de
  `support_reference`);
- repetir `idempotencyKey` en `receivables.record_payment`
  (REST o MCP) no crea un segundo `Movement`.

Pruebas de contrato:

- OpenAPI valida contra los endpoints ya declarados de cartera mas el path
  nuevo de reverso y el campo `aging` aditivo en `AccountItem`;
- esquema MCP de las tres tools ya declaradas valida sin romper su forma
  publicada en Sprint 0.

Pruebas E2E (Playwright, escritorio y viewport movil):

- ver la lista de cartera con aging visible tras autorizar una factura del
  seed, sin crear el receivable manualmente;
- registrar un cobro parcial con una retencion, ver el saldo actualizado y el
  historial de movimientos;
- aplicar una nota de credito del seed y ver el saldo de la factura
  relacionada bajar (o el saldo a favor aparecer si excede);
- revertir un cobro y ver el saldo restaurado con el movimiento original
  visible e intacto;
- recorrido por teclado, axe-core y reflow a 320 CSS px/200% zoom en las
  pantallas nuevas (lista de cartera, drawer de cobro, historial de
  movimientos).

## Criterios de aceptacion

- Todo `Receivable` referencia una factura `AUTHORIZED` existente
  (`sales_document_id` trazable) y su `original_amount` coincide exactamente
  con el `total` de esa factura.
- La suma de `ReceivableInstallment.amount` de un receivable es siempre igual
  a su `original_amount`, verificado al crearse desde el evento
  `invoice.authorized`.
- Ningun cobro, retencion, descuento o nota de credito puede hacer que la
  suma de aplicaciones de una cuota supere su monto (sin sobreaplicar) ni que
  el saldo resultante sea negativo; probado en el limite exacto y un
  centavo por encima.
- Bajo concurrencia real contra PostgreSQL, dos aplicaciones simultaneas sobre
  el mismo receivable nunca sobreaplican (prueba con tareas concurrentes
  reales, no solo aserciones aisladas).
- Aging es reproducible: la misma cuota con la misma fecha de corte local
  (`America/Guayaquil`) siempre produce el mismo bucket, sin depender del
  reloj real de la maquina que ejecuta la prueba.
- Aplicar una nota de credito autorizada nunca deja saldo negativo en la
  factura relacionada; el excedente siempre se refleja como
  `CustomerCredit`, nunca se descarta ni se trunca silenciosamente.
- Revertir un movimiento crea un `Movement` `REVERSAL` nuevo que referencia
  el original sin editarlo ni borrarlo; el original sigue siendo consultable
  con su valor original intacto.
- Repetir la misma `idempotencyKey` en `receivables.record_payment` (REST o
  MCP) devuelve el mismo resultado sin crear un segundo movimiento.
- Las tres tools MCP de cartera respetan scope, kill switch e idempotencia
  igual que las de facturacion; un token sin scope no las lista ni ejecuta;
  ninguna permite saldo negativo.
- El `StubNotifier` nunca abre una conexion de red ni requiere credenciales;
  un recordatorio queda registrado con plantilla, destinatario y estado
  `STUBBED`, y respeta `consent_opt_out`.
- OpenAPI y catalogo MCP siguen validos y sin romper los contratos ya
  publicados en Sprint 0/1/2 (`receivables.*` conserva su forma original,
  solo se agrega el path de reverso y el campo `aging`).
- UI de cartera pasa axe-core, recorrido por teclado, foco visible/restaurado,
  contraste AA y reflow a 320 CSS px y 200% zoom.
- Dataset `sprint-03-v1` se recrea desde cero de forma idempotente y coexiste
  con `sprint-01-v1`/`sprint-02-v1` sin romper sus pruebas.
- Las suites unitarias, de integracion y de contrato pasan sin depender del
  orden de ejecucion ni de red/reloj real (salvo la integracion marcada
  contra PostgreSQL/Redis reales).
- Los recorridos E2E de cobro, aplicacion de nota de credito y reverso pasan
  en escritorio y viewport movil.
- **La cartera coincide con documentos y movimientos**: para cada receivable
  del dataset, `original_amount` = `SalesDocument.total` de origen, y
  `open_amount` calculado = `original_amount - suma de movimientos activos`,
  verificado en una prueba de reconciliacion explicita que recorre todo el
  dataset.
- CI publica evidencia (JUnit, cobertura, trazas, capturas) sin secretos,
  certificados ni datos personales.

## Revisiones obligatorias

- Backend Platform revisa transacciones, migraciones, lock de concurrencia y
  el worker de eventos `invoice.authorized`/`credit_note.authorized`.
- Ecuador SRI revisa que la aplicacion de nota de credito respete el saldo
  acreditable ya validado en Sprint 2 y no lo contradiga.
- MCP AI Security revisa scopes, politica de automatizacion e idempotencia de
  las tres tools de cartera, y confirma que el reverso no quede expuesto por
  MCP sin politica explicita.
- Product ERP revisa que la lista de cartera y el drawer de cobro sigan el
  flujo lista -> drawer y no dupliquen componentes de `components/erp/`.
- Frontend A11y revisa las pantallas nuevas.
- QA Reliability emite recomendacion go/no-go independiente, igual que en
  Sprint 1 y 2.

## No incluido

Cuentas por pagar (Payables, obligaciones a proveedores) - Sprint 4. Agente
interno, adaptador OpenAI y dashboard financiero - Sprint 5. Envio real de
recordatorio por email o WhatsApp con credenciales, proveedor externo,
tracking de apertura/entrega real y gestion de consentimiento con UI propia -
queda como interfaz `Notifier`/`StubNotifier` reemplazable, sin integracion
real (E5-06/E5-07 permanecen P1/parcial). Reverso de movimiento como tool MCP
(solo REST/UI humana en este sprint). Materializacion de saldo o aging en
tabla propia (se evalua con ADR solo si el calculo on-demand demuestra ser un
cuello de botella real). Retenciones/descuentos con integracion tributaria
real (SRI Renta/IVA): en este sprint son montos auditados con soporte y
motivo, sin generar comprobante de retencion electronico.
