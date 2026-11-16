# ADR 0019 — Clasificación de facturas recibidas por proveedor

- Estado: Proposed
- Fecha: 2026-11-16

## Contexto

Compras calcula el uso fiscal y el control interno por separado. Las reglas
existentes del banco solo sugieren gastos según el texto de un débito.

## Decisión

- Un administrador puede guardar una regla activa o inactiva por RUC de
  proveedor y empresa. La regla elige deducible o no deducible para el
  estimado de renta.
- El worker aplica la regla al recuperar y validar el XML de una factura
  recibida que estaba pendiente. Comprueba la política de escrituras
  automáticas, la clasificación actual y los períodos declarados de la
  factura y de sus notas de crédito vinculadas.
- La decisión y su auditoría comparten la transacción de recuperación. La
  auditoría conserva el ID de la regla, el documento, el actor y la decisión.
- El tablero reutiliza el caso de uso de edición masiva para clasificar con
  arrastre o con botones. Etiquetas y control interno pueden guardarse por
  separado de la decisión fiscal.

El detalle y los criterios se encuentran en
[OpenSpec](../../openspec/changes/compras-sri-reglas-mcp/tasks.md).
