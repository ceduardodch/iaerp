# Modelo de dominio

## Contextos

IAERP se implementa como monolito modular. Cada contexto conserva sus reglas y
publica casos de uso; ningun modulo consulta tablas privadas de otro modulo.

| Contexto | Responsabilidad |
| --- | --- |
| Identity | Usuario, sesion, membresia, rol y service account |
| Organization | Tenant/RUC, configuracion fiscal, establecimiento y punto |
| Parties | Contacto con roles customer y/o supplier |
| Catalog | Producto/servicio, codigo, precio e impuestos |
| Billing | Factura, nota de credito, lineas, secuencial y ciclo SRI |
| Receivables | Vencimientos, cobros, retenciones y aplicaciones |
| Payables | Obligaciones, vencimientos, pagos y aplicaciones |
| Documents | Metadatos, hash, version y ubicacion de objetos |
| Communications | Email, WhatsApp, plantilla, entrega y trazabilidad |
| Automation | Politica, agente, tool call, idempotencia y kill switch |
| Audit | Evento append-only y correlacion |

## Entidades principales

### Identidad y organizacion

- `User`: identidad humana externa asociada al subject OIDC.
- `Tenant`: una razon social y un RUC; contiene configuracion y plan.
- `Membership`: relacion usuario-tenant con roles.
- `ServiceAccount`: identidad de agente con scopes y expiracion.
- `Establishment`: codigo SRI de tres digitos y direccion.
- `EmissionPoint`: codigo SRI de tres digitos y secuencias por tipo documental.
- `FiscalCredential`: referencia cifrada al certificado, vigencia y fingerprint.

### Datos maestros

- `Party`: persona o empresa con identificacion, nombre y roles.
- `PartyContact`: emails, telefonos y direcciones versionables.
- `Product`: bien o servicio, codigo, descripcion, precio y estado.
- `TaxCategory`: tarifa/codigo SRI vigente y fechas de aplicacion.
- `Tag`: nombre, color y estado dentro del tenant.
- `TagAssignment`: relacion controlada entre tag y entidad soportada.

### Facturacion

- `SalesDocument`: cabecera comun de factura y nota de credito.
- `SalesDocumentLine`: cantidad, precio, descuento, impuestos y total.
- `DocumentRelation`: nota de credito relacionada con factura.
- `SRITransmission`: cada intento, respuesta, estado y correlacion.
- `Sequence`: siguiente valor por tenant, tipo, establecimiento y punto.

Estados de factura:

`DRAFT -> READY -> SIGNED -> RECEIVED -> AUTHORIZED`

Estados alternos:

- `REJECTED`: rechazo definitivo con mensajes.
- `PENDING_AUTHORIZATION`: recibido, aun sin autorizacion.
- `FAILED`: error tecnico recuperable.
- `VOIDED`: solo cuando el proceso fiscal aplicable lo permita.

Una factura autorizada no se edita. Una nota de credito siempre referencia un
documento autorizado y no puede exceder su saldo acreditable.

### Cuentas por cobrar

- `Receivable`: saldo exigible, moneda y origen.
- `ReceivableInstallment`: fecha, monto y estado de cada vencimiento.
- `CustomerPayment`: ingreso registrado con referencia y medio.
- `ReceivableAllocation`: aplicacion de pago, retencion o descuento.
- `CollectionReminder`: destinatario, canal, plantilla y resultado.

`saldo = monto original - pagos aplicados - retenciones - descuentos - creditos`

Nunca se guarda un saldo como unica fuente de verdad. Se calcula desde movimientos
y se puede materializar para lectura con reconciliacion.

### Cuentas por pagar

- `Payable`: obligacion con proveedor y documento de respaldo.
- `PayableInstallment`: vencimientos.
- `SupplierPayment`: pago registrado, sin ejecutar transferencia.
- `PayableAllocation`: aplicacion de pago, retencion o ajuste.
- `PaymentSchedule`: fecha planificada, prioridad y estado.
- `ExtractionRun`: resultado estructurado y confianza de XML/PDF.

## Tipos y precision

- Identificadores: UUID.
- Totales monetarios: `NUMERIC(18,2)`.
- Cantidades y precios unitarios: `NUMERIC(18,6)`.
- Porcentajes: `NUMERIC(9,6)`.
- Fechas fiscales: `date`.
- Eventos: `timestamptz` en UTC, presentados en `America/Guayaquil`.
- Moneda inicial: `USD`, conservada explicitamente en documentos.

## Invariantes

1. Toda entidad de negocio tiene `tenant_id`.
2. RUC es unico entre tenants activos.
3. Clave de acceso SRI es unica cuando no es nula.
4. Secuencial es unico por tenant, tipo, establecimiento y punto de emision.
5. Una aplicacion no puede superar el saldo disponible del pago ni del documento.
6. Un documento financiero contabilizado no se elimina fisicamente.
7. Un agente no puede ampliar sus propios scopes o politicas.
8. La idempotency key es unica por tenant, actor, operacion y ventana definida.
9. Los hashes de archivos se validan al cargar y descargar.
10. Una accion de otro tenant se responde como no encontrada, evitando filtracion.

## Eventos de dominio iniciales

- `invoice.created`, `invoice.ready`, `invoice.signed`
- `invoice.received_by_sri`, `invoice.authorized`, `invoice.rejected`
- `credit_note.authorized`
- `receivable.created`, `payment.recorded`, `receivable.settled`
- `payable.created`, `payable.due_soon`, `supplier_payment.recorded`
- `reminder.requested`, `reminder.delivered`, `reminder.failed`
- `automation.blocked`, `automation.executed`, `automation.kill_switch_changed`

Los eventos que produzcan efectos externos se copian a outbox en la misma
transaccion de negocio.
