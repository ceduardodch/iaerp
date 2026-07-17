# Sprint 2 - Facturacion electronica y SRI

## Estado

Done (2026-07-04). Las ocho fases (E4-01..E4-09, E7-03, E9) estan implementadas
y verificadas; QA Reliability dio GO tras validar el ciclo SRI simulado
completo en vivo con worker real (borrador -> emision -> firma XAdES ->
XML/RIDE en MinIO -> transmision -> autorizacion), idempotencia sin duplicar
transmisiones, descarga con checksum, nota de credito parcial autorizada y
exceso rechazado con 422. El detalle de evidencia y los tres bugs de
integracion corregidos durante el cierre estan en `docs/STATUS.md`. Pendiente
externo: commit autorizado y (opcional) un job de CI que ejecute el ciclo SRI
en vivo.

## Objetivo

Entregar en `release` un ciclo completo de factura y nota de credito -borrador,
calculo fiscal, secuencial atomico, firma XAdES-BES, XML, RIDE PDF,
almacenamiento privado, recepcion/autorizacion/reconciliacion/reintentos y
tools MCP equivalentes- contra un **simulador SRI propio** (no existe ambiente
de pruebas SRI real con credenciales en este entorno), sin duplicados de
secuencial ni de clave de acceso.

## Historias

| Orden | IDs | Entrega | Owner experto |
| --- | --- | --- | --- |
| 1 | E4-09 | Vector fiscal versionado con casos de prueba SRI | Ecuador SRI |
| 2 | E4-01, E4-02 | Borrador de factura, lineas, calculo y secuencial atomico | Backend Platform + Ecuador SRI |
| 3 | E4-03, E4-06 | Firma XAdES-BES, XML, RIDE PDF y almacenamiento MinIO | Ecuador SRI + Backend Platform |
| 4 | E4-04, E4-05, E4-08 | Simulador SRI, transmision, reconciliacion y reintentos | Ecuador SRI + Backend Platform + QA |
| 5 | E4-07 | Nota de credito con limite contra factura autorizada | Ecuador SRI + Backend Platform |
| 6 | E7-03 | Tools MCP invoices.\* y credit_notes.\* con politica e idempotencia | MCP AI Security |
| 7 | E9-01 a E9-07 | Dataset sprint-02-v1, factories, integracion y E2E | QA Reliability |
| 8 | — | UI de facturacion (lista, borrador, emision, detalle) | Frontend A11y + Product ERP |

## Decisiones de diseno

Numeradas segun el orden en que deben resolverse; el detalle extendido de cada
una esta en la seccion "Secuencia tecnica" y en el resumen entregado al
coordinador.

1. **Modelo de datos**: `SalesDocument` (cabecera comun factura/nota de
   credito) + `SalesDocumentLine` + `SalesDocumentLineTax` (impuesto por linea,
   permite mezclar tarifas) + `DocumentRelation` (nota de credito -> factura) +
   `Sequence` (siguiente valor por tenant/establecimiento/punto/tipo) +
   `SRITransmission` (cada intento con request/response/estado) +
   `DocumentArtifact` (XML firmado y RIDE, con checksum, tipo y version) +
   modulo `fiscal_policy.py` versionado en codigo (no tabla) con vectores de
   prueba, segun ADR 0008 ya aceptado.
2. **Secuencial atomico**: fila `Sequence` con `SELECT ... FOR UPDATE` dentro de
   la misma transaccion que crea el `SalesDocument`, mismo patron de lock que
   `execute_idempotent` ya usa sobre `Tenant`. Constraint unico
   `(tenant_id, document_type, establishment_id, emission_point_id, sequential)`
   como defensa adicional. En SQLite (unitarias) el mismo codigo funciona
   porque SQLite serializa escritores; la prueba de concurrencia real corre
   solo contra PostgreSQL (integracion), igual que hoy con Alembic.
3. **Clave de acceso SRI**: 49 digitos, modulo 11 con las reglas oficiales
   (fecha, tipo, RUC, ambiente, serie, secuencial, codigo numerico, tipo de
   emision, digito verificador). Unicidad global via `UniqueConstraint` en
   `sales_documents.access_key`. Regla E4-05: antes de reintentar una emision,
   el worker consulta `SRITransmission` por `access_key`; si ya existe una
   transmision `RECEIVED`, `PENDING_AUTHORIZATION` o `AUTHORIZED`, se reconcilia
   (se consulta autorizacion) y nunca se retransmite el mismo XML.
4. **Firma XAdES-BES**: `signxml` (ya requiere `lxml` + `cryptography`, y
   `cryptography` ya esta disponible transitivamente via `pyjwt[crypto]`).
   Se anade `signxml` y `lxml` explicitos a `pyproject.toml`. Certificado de
   prueba: script `backend/scripts/generate_test_certificate.py` genera un
   `.p12` autofirmado efimero en tiempo de test/dev, cifrado con una passphrase
   de entorno, nunca versionado (`*.p12`, `*.pfx` en `.gitignore`). El
   fingerprint (SHA-256 del certificado) se audita en `AuditEvent` al firmar.
5. **RIDE PDF**: `reportlab`. Es la opcion mas liviana (sin binarios nativos
   como los que exige WeasyPrint -Pango/Cairo-, que complican Docker/Coolify) y
   ya es el estandar de facto en integraciones SRI ecuatorianas existentes.
   Genera el PDF con layout tabular simple a partir de los mismos datos que el
   XML, evitando divergencia entre RIDE y XML.
6. **Almacenamiento MinIO**: bucket privado `iaerp-documents` (ya provisto en
   Sprint 1). Layout de objetos:
   `{tenant_id}/sales-documents/{document_id}/{artifact_type}-v{version}.{ext}`
   (`artifact_type` en `xml-signed`, `ride-pdf`). Checksum SHA-256 calculado
   antes de subir y verificado al descargar; se guarda en `DocumentArtifact`.
   Sin URLs publicas: toda descarga pasa por un endpoint autenticado que emite
   una URL prefirmada de corta duracion (reutiliza el patron de storage privado
   del ADR 0005).
7. **Simulador SRI**: modulo `backend/app/integrations/sri/` con un
   `Protocol` (`SRIClient`) que define `send_reception(xml) -> ReceptionResult`
   y `check_authorization(access_key) -> AuthorizationResult`. Dos
   implementaciones: `SimulatorSRIClient` (activo salvo que se configure un
   cliente real) y un placeholder `SoapSRIClient` sin implementar (documentado,
   no funcional, para Sprint futuro con credenciales reales). El simulador se
   monta como router FastAPI `/sri-sim` **solo si `SRI_SIMULATOR_ENABLED=true`**
   (por defecto true en dev/test, false si no se declara, nunca activable en
   `main`/produccion); expone endpoints REST simplificados (no SOAP real, para
   no acoplar el contrato a un detalle de transporte que cambiara con el
   cliente real) para simular: `RECEIVED`, `RETURNED` (RECHAZADA con motivo),
   `AUTHORIZED`, `NOT_AUTHORIZED`, `TIMEOUT` (no responde, fuerza reintento) y
   `DUPLICATE_RESPONSE` (reenvia la misma respuesta autorizada para probar que
   la reconciliacion no reemite). El estado a simular se configura por
   `access_key` via fixture/seed, no por azar, para reproducibilidad.
8. **Flujo asincrono**: `invoices.issue` valida estado y calculo, firma el XML
   de forma sincrona (operacion local, sin red), persiste el `SalesDocument` en
   `SIGNED` y escribe un `OutboxEvent` (`invoice.signed`) en la misma
   transaccion, reutilizando `execute_idempotent`. Un nuevo consumidor
   `sri_transmission` (worker Celery, mismo patron que `dispatcher.py`/
   `consume_once`) toma el evento, llama a `SRIClient.send_reception`, y segun
   respuesta pasa a `RECEIVED`/`REJECTED`; si es `RECEIVED`, agenda una
   consulta de autorizacion con backoff exponencial (reutiliza
   `_retry_delay` de `outbox.py`) hasta `AUTHORIZED`/`NOT_AUTHORIZED` o
   `dead_letters` tras agotar intentos. El estado es consultable via
   `GET /invoices/{id}` y `invoices.get` (MCP), que exponen el ultimo
   `SRITransmission`.
9. **Tools MCP**: se implementan las cuatro tools ya declaradas en
   `contracts/mcp-tools.yaml` (`invoices.get`, `invoices.create_draft`,
   `invoices.issue`, `credit_notes.create_and_issue`), sin renombrar. Mismo
   patron que `parties.create`/`products.create`: `_tool_context` con scope
   requerido, `_require_automation_writes` para las de efecto `write`/
   `external-write`, `execute_idempotent` para borrador/emision, y auditoria
   automatica dentro de ese helper. `invoices.issue` y
   `credit_notes.create_and_issue` devuelven `Operation` (202, asincrono);
   `invoices.create_draft` devuelve `SalesDocument` directo (201, sincrono).
10. **Contratos**: `openapi.yaml` ya tiene los schemas y endpoints de
    invoices/credit-notes (lineas 508-660, 1269-1420); se completan campos que
    faltan para el diseno (`documentType` en `SalesDocument` para
    distinguir INVOICE/CREDIT_NOTE ya existe via `type`; se agregan
    `establishmentCode`, `emissionPointCode` de solo lectura y el bloque
    `sriTransmission` con `status`/`message`/`lastAttemptAt`). `mcp-tools.yaml`
    no cambia de forma, solo se verifica que el `outputSchema` de
    `invoices.get` refleje el campo nuevo. Ningun endpoint ni tool existente
    se elimina o cambia de firma.

## Secuencia tecnica

1. Ecuador SRI Expert documenta y versiona el vector fiscal (orden de calculo,
   base imponible, redondeo, notas de credito) con fuente oficial; se acepta
   ADR 0008 antes de tocar codigo de calculo (bloqueante, ya senalado en el
   ADR).
2. Backend Platform crea modelos (`billing.py`), migracion Alembic y el modulo
   `fiscal_policy.py` con la version inicial y sus vectores de prueba.
3. Backend Platform implementa reserva de secuencial atomica y el caso de uso
   de borrador (`services/billing.py`), recalculando totales en backend
   (frontend nunca envia totales).
4. Ecuador SRI + Backend Platform implementan clave de acceso (modulo 11),
   firma XAdES-BES con `signxml`, generacion de XML SRI y RIDE con
   `reportlab`, y subida a MinIO con checksum.
5. Backend Platform implementa el simulador SRI (`/sri-sim`, gated por
   variable de entorno), el `SRIClient` Protocol, el consumidor Celery de
   transmision/autorizacion con reintentos y dead letter, y la reconciliacion
   por clave de acceso (E4-05).
6. Ecuador SRI + Backend Platform implementan nota de credito: validacion de
   relacion con factura autorizada, limite acreditable y reutilizacion del
   mismo pipeline de firma/transmision.
7. MCP AI Security expone `invoices.get`, `invoices.create_draft`,
   `invoices.issue`, `credit_notes.create_and_issue` sobre los mismos casos de
   uso que REST.
8. Frontend A11y + Product ERP construyen lista -> drawer de facturas
   (borrador, emision, detalle con estado SRI y descarga de artefactos)
   reutilizando `frontend/src/components/erp/`.
9. QA Reliability construye el dataset `sprint-02-v1`, factories, pruebas de
   concurrencia, contrato y E2E; emite recomendacion go/no-go.

## Plan de pruebas y datos

El dataset `sprint-02-v1` extiende `sprint-01-v1` (no lo reemplaza) agregando,
para cada uno de los dos tenants ya existentes:

- al menos dos productos con tarifa gravada y uno con tarifa cero, usados en
  lineas con cantidades decimales y descuentos por linea;
- una factura `AUTHORIZED` completa (con XML/RIDE de fixture, checksums
  validos);
- una factura `PENDING_AUTHORIZATION` (recibida, sin autorizar) para probar
  reconciliacion;
- una factura `REJECTED` con mensaje SRI de fixture;
- una factura con autorizacion tardia (creada `RECEIVED`, autorizada en una
  corrida posterior del simulador) para probar actualizacion sin duplicar;
- una nota de credito autorizada referenciando la factura autorizada, con
  monto menor al total acreditable;
- un intento de nota de credito que excede el saldo acreditable (caso
  negativo);
- vectores fiscales del ADR 0008: casos con IVA 15%/12% historico, tarifa 0%,
  descuentos por linea y por documento, y redondeo en el limite (p. ej.
  `0.005`) con el resultado esperado documentado.

Pruebas unitarias:

- `fiscal_policy.py`: subtotal, base imponible por tarifa, redondeo por linea y
  por total, contra los vectores oficiales del ADR 0008;
- calculo de clave de acceso (modulo 11) con vectores conocidos, incluyendo un
  digito verificador esperado;
- estados validos del `SalesDocument` (transiciones permitidas y prohibidas,
  p. ej. no se edita `AUTHORIZED`);
- limite acreditable de nota de credito (dentro de saldo, en el limite exacto,
  y excedido);
- parseo y clasificacion de respuestas del simulador (`RECEIVED`, `RETURNED`,
  `AUTHORIZED`, `NOT_AUTHORIZED`, `TIMEOUT`, `DUPLICATE_RESPONSE`).

Pruebas de integracion (PostgreSQL real):

- reserva de secuencial bajo concurrencia real: N tareas concurrentes emitiendo
  facturas en el mismo establecimiento/punto obtienen secuenciales
  consecutivos sin huecos y sin duplicados (se acepta un hueco solo si una
  transaccion revierte por error, documentado como caso aceptado);
- repetir `idempotencyKey` en `invoices.issue` no crea una segunda transmision
  ni un segundo evento outbox;
- ciclo completo borrador -> emision -> firma -> outbox -> worker ->
  simulador -> autorizacion contra el stack real (Redis + PostgreSQL);
- reconciliacion: una clave con transmision `RECEIVED` no se retransmite ante
  un timeout simulado, solo se reconsulta;
- reintentos con backoff hasta dead letter cuando el simulador fuerza fallo
  persistente;
- checksum de artefactos se verifica al subir y al descargar desde MinIO.

Pruebas de contrato:

- OpenAPI valida contra los endpoints de facturacion existentes y los campos
  nuevos de `SalesDocument`;
- esquema MCP de las cuatro tools valida contra `contracts/mcp-tools.yaml` sin
  romper `invoices.get`/`invoices.create_draft`/`invoices.issue`/
  `credit_notes.create_and_issue` ya declaradas.

Pruebas E2E (Playwright, escritorio y viewport movil):

- crear borrador de factura, ver totales recalculados por backend, emitir y
  ver el estado SRI avanzar hasta autorizado (con el simulador respondiendo
  `AUTHORIZED` de forma determinista via fixture);
- emitir una factura cuyo simulador responde `NOT_AUTHORIZED` y verificar
  mensaje visible y accesible;
- crear nota de credito sobre la factura autorizada del seed y verificar
  actualizacion de saldo acreditable;
- recorrido por teclado, axe-core y reflow a 320 CSS px/200% zoom en las
  pantallas nuevas (lista, drawer de borrador, detalle con estado SRI).

La evidencia minima sigue el mismo formato de Sprint 1: JUnit, cobertura, log
sanitizado del stack y traza/captura de cada fallo E2E.

## Criterios de aceptacion

- El vector fiscal de `fiscal_policy.py` reproduce exactamente los casos
  oficiales documentados por Ecuador SRI Expert (ADR 0008 aceptado con
  evidencia, no solo "Proposed").
- Bajo concurrencia real contra PostgreSQL, N emisiones simultaneas en el
  mismo establecimiento/punto producen secuenciales unicos y sin duplicados;
  la prueba se ejecuta con evidencia reproducible (no solo aserciones
  aisladas).
- La clave de acceso SRI es unica globalmente (constraint de base de datos) y
  su digito verificador pasa el modulo 11 en todos los vectores de prueba.
- Una clave de acceso con transmision `RECEIVED`/`PENDING_AUTHORIZATION`/
  `AUTHORIZED` nunca genera un segundo XML transmitido ante timeout o
  reintento; solo se reconsulta (prueba explicita con el escenario
  `DUPLICATE_RESPONSE`/`TIMEOUT` del simulador).
- Repetir la misma `idempotencyKey` en `invoices.issue` o
  `credit_notes.create_and_issue` (REST o MCP) devuelve el mismo resultado sin
  crear una segunda transmision ni un segundo evento outbox.
- Una factura `AUTHORIZED` es inmutable; solo una nota de credito relacionada
  puede compensarla, y la suma de notas de credito nunca supera el total
  acreditable de la factura.
- XML firmado y RIDE PDF de un mismo documento comparten los mismos totales,
  clave de acceso y checksum verificable; ambos se descargan solo via URL
  prefirmada autenticada, nunca publica.
- El certificado de prueba nunca se versiona (`.gitignore` verificado) y su
  fingerprint queda auditado en `AuditEvent` en cada firma.
- El worker de transmision SRI reintenta con backoff y produce `dead_letters`
  al agotar intentos, sin perder el vinculo con el `SalesDocument` de origen.
- Las cuatro tools MCP de facturacion respetan scope, kill switch, politica de
  automatizacion e idempotencia igual que `parties.create`/`products.create`;
  un token sin scope no las lista ni ejecuta.
- OpenAPI y catalogo MCP siguen validos y sin romper los contratos ya
  publicados en Sprint 1 (`context.get`, `parties.*`, `products.*`).
- UI de facturacion pasa axe-core, recorrido por teclado, foco visible/
  restaurado, contraste AA y reflow a 320 CSS px/200% zoom.
- Dataset `sprint-02-v1` se recrea desde cero de forma idempotente y coexiste
  con `sprint-01-v1` sin romper sus pruebas.
- Las suites unitarias, de integracion y de contrato pasan sin depender del
  orden de ejecucion ni de red/reloj real (salvo la integracion marcada como
  tal contra PostgreSQL/Redis/MinIO reales).
- Los recorridos E2E de factura y nota de credito pasan en escritorio y
  viewport movil.
- CI publica evidencia (JUnit, cobertura, trazas, capturas) sin secretos,
  certificados ni datos personales.

## Revisiones obligatorias

- Ecuador SRI revisa vector fiscal, clave de acceso, XML, estados SRI y
  reconciliacion antes de aceptar el diseno de calculo (ADR 0008) y antes de
  cerrar el sprint.
- Backend Platform revisa transacciones, migraciones, secuencial atomico y el
  worker de transmision/reintentos.
- MCP AI Security revisa scopes, politica de automatizacion e idempotencia de
  las tools nuevas.
- Product ERP revisa que el borrador y el drawer de factura sigan el flujo
  lista -> drawer y no dupliquen componentes de `components/erp/`.
- Frontend A11y revisa las pantallas nuevas.
- QA Reliability emite recomendacion go/no-go independiente, igual que en
  Sprint 1.

## No incluido

SRI produccion (credenciales y certificado reales, endpoints oficiales),
retenciones electronicas, guias de remision, notas de debito, liquidaciones de
compra, cuentas por cobrar (Receivables, cobros, aging, recordatorios) y
cuentas por pagar (Payables). Esas capacidades comienzan en Sprint 3 o
posteriores segun `docs/08-roadmap.md`.
