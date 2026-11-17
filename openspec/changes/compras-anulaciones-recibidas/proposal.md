## Why

Una factura recibida puede anularse después de importarla. La compra aún aparece por pagar y puede seguir afectando los reportes. El usuario pidió registrar estas anulaciones sin perder el historial.

## What Changes

- Registrar la anulación ya efectuada ante el SRI con fecha, motivo y respaldo, sólo si también se canceló la compra y se extinguió ese saldo.
- Exigir y auditar una confirmación económica separada, sin asumir que el estado SRI extingue la deuda. Compras vigentes y refacturación requieren otro tratamiento.
- Conservar el documento original y mostrar su estado en Compras.
- Excluir las anuladas de deuda vigente y cálculos fiscales abiertos.
- Proteger períodos declarados y movimientos aplicados; exigir su revisión previa.
- Mantener el flujo de notas de crédito separado de la anulación directa.

## Capabilities

### New Capabilities

- `compras-anulaciones`: registro auditable de anulaciones de facturas recibidas.

### Modified Capabilities

## Impact

Compras, cuentas por pagar, reportes tributarios, permisos y auditoría. No emite solicitudes de anulación ante el SRI ni modifica documentos productivos por el contenido de una captura.
