# ADR 0011: expediente legal-comercial versionado y evidencia AWS

- Estado: Proposed
- Fecha: 2026-07-29

## Contexto

IAERP ya relaciona clientes, facturas, cuotas y cartera, pero no conserva el
instrumento comercial que explica por que se factura ni la evidencia de consumo
AWS. Los clientes pueden tener un cargo fijo mensual, consumo variable o ambos.

## Decision

Se incorpora un contexto `legal_commercial` tenant-scoped, separado de Billing
y del SRI. Sus contratos tienen versiones inmutables después de firmarse y cada
archivo se guarda privado con SHA-256, tipo, autor, fecha y control de descarga.

Una versión contiene vigencia, firmantes, condiciones de pago, renovación,
servicios y reglas de cobro `FIXED_MONTHLY`, `AWS_COST_PLUS_MARGIN` o ambas. Un
corte de consumo AWS normalizado proviene de un conector de solo lectura o de
una carga CSV/XLSX; requiere conciliación y revisión antes de usarse.

Una propuesta de facturación une versión contractual, corte y regla de precio,
y guarda un snapshot comercial al crear el borrador de factura. La ausencia de
contrato activo no bloquea facturar: exige advertencia, motivo y auditoría. La
factura autorizada conserva su régimen fiscal y no se modifica por el contrato.

La IA solo extrae un esquema cerrado con evidencia por página/fragmento y
confianza. REST y MCP exponen consultas tenant-scoped; no hay tools MCP de
escritura ni firma/e-mail automáticos en la primera versión.

## Consecuencias

- Se requiere migración, API, UI, artefactos privados, auditoría y pruebas de
  aislamiento, integridad, conciliación y prompt injection.
- La firma electrónica con proveedor y la asesoría/validación jurídica humana
  permanecen fuera de alcance.
- El alcance MVP se amplía de manera controlada; este ADR debe pasar a
  `Accepted` antes de implementar persistencia o endpoints.
