# ADR 0021: Anulación local de facturas recibidas

- Estado: Accepted
- Fecha: 2026-11-17
- Decisión humana: registrar en Compras las facturas anuladas después de su importación.

## Contexto

Un documento recibido puede seguir en Compras tras su anulación. El XML autorizado y un reporte histórico no prueban su vigencia actual. La anulación directa ante el SRI y la nota de crédito tienen efectos distintos y no deben descontarse dos veces.

## Decisión

Registrar una anulación ya efectuada ante el SRI mediante un caso de uso de dominio único, sólo cuando también se canceló la operación comercial y dejó de existir el saldo original. El estado SRI por sí solo no acredita esa decisión económica. La acción humana exige permiso, tenant autenticado, fecha efectiva, motivo, respaldo, clave de idempotencia y `economicOutcome=OPERATION_CANCELLED` sin valor por defecto. La interfaz pide una confirmación separada de la cancelación de la compra y la extinción de ese saldo; la auditoría conserva ambas decisiones. Guarda auditoría y conserva documento, XML, importe y movimientos históricos. No envía solicitudes de anulación al SRI.

La compra anulada deja de sumar deuda y reportes fiscales abiertos. La reimportación no la reactiva. La interfaz mantiene el historial y separa el estado del documento del estado de pago.

Una compra que sigue vigente, espera una factura sustituta o sólo tiene un cambio documental requiere conciliar el estado fiscal y la obligación comercial por separado; este primer flujo rechaza esos casos sin alterar la compra ni la deuda. No sustituye el registro de una factura de reemplazo.

Cuando hay un período declarado, pagos, retenciones o notas de crédito aplicadas, se rechaza la aplicación automática con un motivo concreto. El operador debe conciliar los movimientos y revisar el ajuste fiscal antes de registrar la anulación. No se inventan reembolsos ni saldos a favor y no se reescriben declaraciones cerradas.

Una ausencia en el listado de recibidos no prueba anulación. El primer alcance registra una confirmación humana respaldada; no anuncia verificación automática ante el SRI.

## Consecuencias

- La acción sirve a documentos sin movimientos ni cierre fiscal afectado.
- El respaldo y el historial permanecen consultables por el tenant.
- Las notas de crédito mantienen su flujo y descuentos existentes.
- La automatización futura de verificación debe reutilizar el mismo caso de uso y respetar política, idempotencia y auditoría.

## Fuentes

Resoluciones oficiales [NAC-DGERCGC25-00000014](https://www.sri.gob.ec/o/sri-portlet-biblioteca-alfresco-internet/descargar?id=137046a6-787c-47fb-a2d7-176595d292dc&nombre=NAC-DGERCGC25-00000014.pdf) y [NAC-DGERCGC25-00000017](https://www.sri.gob.ec/o/sri-portlet-biblioteca-alfresco-internet/descargar?id=e98fc8a6-299e-4ea9-8de7-2f6c70dbb4f5&nombre=NAC-DGERCGC25-00000017.pdf). El registro local no decide si todavía existe plazo para anular ante el SRI.
