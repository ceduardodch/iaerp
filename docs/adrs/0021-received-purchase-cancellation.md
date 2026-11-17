# ADR 0021: Anulación local de facturas recibidas

- Estado: Accepted
- Fecha: 2026-11-17
- Decisión humana: registrar en Compras las facturas anuladas después de su importación.

## Contexto

Un documento recibido puede seguir en Compras tras su anulación. El XML autorizado y un reporte histórico no prueban su vigencia actual. La anulación directa ante el SRI y la nota de crédito tienen efectos distintos y no deben descontarse dos veces.

## Decisión

Registrar una anulación ya efectuada ante el SRI mediante un caso de uso de dominio único. La acción humana exige permiso, tenant autenticado, fecha efectiva, motivo, respaldo y clave de idempotencia. Guarda auditoría y conserva documento, XML, importe y movimientos históricos. No envía solicitudes de anulación al SRI.

La compra anulada deja de sumar deuda y reportes fiscales abiertos. La reimportación no la reactiva. La interfaz mantiene el historial y separa el estado del documento del estado de pago.

Cuando hay un período declarado, pagos, retenciones o notas de crédito aplicadas, se rechaza la aplicación automática con un motivo concreto. El operador debe conciliar los movimientos y revisar el ajuste fiscal antes de registrar la anulación. No se inventan reembolsos ni saldos a favor y no se reescriben declaraciones cerradas.

Una ausencia en el listado de recibidos no prueba anulación. El primer alcance registra una confirmación humana respaldada; no anuncia verificación automática ante el SRI.

## Consecuencias

- La acción sirve a documentos sin movimientos ni cierre fiscal afectado.
- El respaldo y el historial permanecen consultables por el tenant.
- Las notas de crédito mantienen su flujo y descuentos existentes.
- La automatización futura de verificación debe reutilizar el mismo caso de uso y respetar política, idempotencia y auditoría.

## Fuentes

Resoluciones oficiales [NAC-DGERCGC25-00000014](https://www.sri.gob.ec/o/sri-portlet-biblioteca-alfresco-internet/descargar?id=137046a6-787c-47fb-a2d7-176595d292dc&nombre=NAC-DGERCGC25-00000014.pdf) y [NAC-DGERCGC25-00000017](https://www.sri.gob.ec/o/sri-portlet-biblioteca-alfresco-internet/descargar?id=e98fc8a6-299e-4ea9-8de7-2f6c70dbb4f5&nombre=NAC-DGERCGC25-00000017.pdf). El registro local no decide si todavía existe plazo para anular ante el SRI.
