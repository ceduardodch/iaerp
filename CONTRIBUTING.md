# Contribucion

## Flujo

1. Trabajar en `release`, salvo autorizacion explicita para usar `develop`.
2. Mantener cambios pequenos y ligados a una historia del backlog.
3. Ejecutar lint, pruebas, migraciones de prueba y build antes de entregar.
4. Actualizar contratos y documentacion cuando cambie comportamiento publico.
5. Promover `release` a `main` mediante PR aprobado.

No se crean ramas adicionales ni se hace push, merge o PR sin autorizacion.

## Definition of Done

- Criterios de aceptacion comprobados.
- Aislamiento de tenant verificado.
- Pruebas unitarias, integracion y contrato relevantes en verde.
- Migraciones con upgrade y downgrade probados.
- Escrituras idempotentes y auditadas.
- Sin secretos o datos personales en codigo, fixtures, logs o artefactos.
- Documentacion y contratos actualizados.
- Observabilidad minima: logs estructurados, metricas y correlacion.
