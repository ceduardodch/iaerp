# Contribucion

## Flujo

1. Trabajar en `release`, salvo autorizacion explicita para usar `develop`.
2. Mantener cambios pequenos y ligados a una historia del backlog.
3. Ejecutar lint, pruebas, migraciones de prueba y build antes de entregar.
4. Actualizar contratos y documentacion cuando cambie comportamiento publico.
5. Promover `release` a `main` mediante PR aprobado.

No se crean ramas adicionales ni se hace push, merge o PR sin autorizacion.

## Definition of Done

La fuente canonica es `docs/09-testing-quality.md`. Este archivo no mantiene una
segunda lista para evitar criterios divergentes. Ningun cambio se considera Done
si omite aislamiento, casos negativos, contratos/migraciones, seguridad,
observabilidad, documentacion o demostracion en `release` segun esa fuente.
