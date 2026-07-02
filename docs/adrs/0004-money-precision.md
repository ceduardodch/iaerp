# ADR 0004: Precision monetaria

- Estado: Proposed
- Fecha: 2026-07-02

## Contexto

Los `float` producen errores de redondeo incompatibles con impuestos, saldos y
conciliacion.

## Decision

Usar Python `Decimal`, PostgreSQL `NUMERIC(18,2)` para totales,
`NUMERIC(18,6)` para precios/cantidades y serializacion decimal sin perdida.
Cada documento define moneda y politica de redondeo.

## Consecuencias

- Calculos reproducibles y conciliables.
- Frontend no debe convertir montos a float para operaciones.
- Las migraciones recalculan y reportan diferencias.
