# ADR 0008: Calculo fiscal y redondeo versionado

- Estado: Proposed
- Fecha: 2026-07-02

## Contexto

Definir `Decimal` y precision de base de datos no determina el orden de
descuentos, base imponible, IVA, cuantizacion por linea ni reconciliacion entre
XML, PDF y total. Una diferencia minima puede producir rechazo SRI o saldos
inconsistentes.

## Decision propuesta

Crear un `FiscalCalculationPolicy` inmutable y versionado por vigencia. La misma
version calcula backend, XML, PDF, migracion y pruebas. El frontend solo muestra
el resultado.

Antes de aceptar este ADR, el Ecuador SRI Expert debe documentar con fuente
oficial:

- orden de cantidad, precio y descuento;
- base imponible por tarifa;
- precision intermedia;
- cuantizacion/redondeo por linea y por total;
- tratamiento de notas de credito;
- vectores de prueba por tarifa vigente.

## Consecuencias

- Sprint 1 puede avanzar porque no emite documentos.
- Sprint 2 queda bloqueado hasta aceptar este ADR.
- Cambiar una regla crea una version con fecha de vigencia; no reescribe
  documentos historicos.
