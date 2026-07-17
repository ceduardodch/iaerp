# Migracion skyfranquicias — Fase 0: empresas B2B -> tenants

Plan incremental. Se migra solo lo que el owner indique; esta fase cubre
unicamente las empresas/franquicias B2B como `tenants`. Se apoya en el pipeline
y criterios de `docs/07-data-migration.md` (vinculante).

## Decisiones de esta fase (2026-07-09)

- Fuente: conexion directa de solo lectura a la BD de skyfranquicias. No se
  modifica el origen; se toma un snapshot consistente.
- Alcance: cada empresa/franquicia B2B valida -> un `Tenant` de IAERP, por RUC
  unico (`profiles -> tenants` del mapeo). Conflictos por RUC se detienen para
  revision manual (no se fusiona automaticamente).
- Sin usuarios/login: no se crean `users`, `memberships`, ni identidades en
  Keycloak en esta fase. Eso es una fase posterior.
- Sin datos transaccionales: no se migran clientes, productos, facturas,
  cobros ni obligaciones todavia.

## Que NO entra en Fase 0

Usuarios/login, clientes (parties), productos, facturas, cobros, obligaciones,
certificados, y todo modulo de franquicia/farmacia/nomina. Cada uno sera su
propia fase seleccionada por el owner.

## Pipeline (subconjunto de docs/07-data-migration.md)

`extract -> stage -> validate -> transform -> load -> reconcile`

1. **Extract**: cuenta de solo lectura, snapshot con timestamp. Se lee la(s)
   tabla(s) de empresas B2B (nombre y columnas por confirmar con el owner).
2. **Stage**: copia efimera en tabla de staging del migrador, con
   `migration_run_id`. No se toca el destino aun.
3. **Validate** (por registro, sin escribir destino):
   - RUC presente y valido (13 digitos, formato SRI, digito verificador).
   - Nombre/razon social presente.
   - RUC unico dentro del lote; colision con un tenant ya existente en IAERP
     se marca como conflicto (se detiene ese registro, no el lote entero).
   - Se produce un registro de error por cada fila invalida, con el motivo.
4. **Transform** (determinista y versionado): mapear columnas de origen a los
   campos de `Tenant` (ruc, name, organization_id). `organization_id` se
   deriva de forma estable (p. ej. un UUID v5 desde el RUC) para que las
   corridas repetidas produzcan el mismo valor.
5. **Load** (idempotente): upsert de `Tenant` por RUC con
   `migration_run_id` + clave de negocio del origen; una segunda corrida no
   duplica. Cada tenant creado queda etiquetado con la corrida que lo creo.
6. **Reconcile**: reporte con conteos (leidos, validos, insertados, omitidos,
   fallidos), lista de RUC duplicados y conflictos, y diff contra el snapshot.

## Idempotencia y rollback

- Toda corrida usa un `migration_run_id`. `dry-run` obligatorio antes de la
  corrida real: valida y produce el reporte sin escribir el destino.
- Si una corrida falla antes de aprobarse, se eliminan solo los tenants de esa
  corrida (por `migration_run_id`), o se restaura el backup del destino.
- Tras aprobar, las correcciones son nuevas migraciones compensatorias, nunca
  edicion manual.

## Criterios de aceptacion (Fase 0)

- Cero RUC duplicados entre los tenants resultantes.
- Conteos explicados al 100%, incluidas las omisiones y conflictos.
- Una segunda corrida idempotente no crea tenants nuevos ni modifica los
  existentes (salvo cambios reales en la fuente dentro del delta).
- El origen permanece en solo lectura; la migracion no lo modifica.
- Reporte de conciliacion firmado antes de considerar la fase cerrada.

## Lo que falta para ejecutar (input del owner)

1. **Conexion de solo lectura**: motor (MySQL/PostgreSQL/otro), host/puerto,
   base y credenciales de solo lectura. Se configuran por variable de entorno
   (`SKYFRANQUICIAS_SOURCE_URL`), nunca en Git. La BD debe ser alcanzable
   desde donde corre el migrador.
2. **Esquema de origen**: nombre de la tabla de empresas/franquicias B2B y las
   columnas relevantes (identificador, RUC, razon social, estado activo,
   `updated_at` para el delta). Con eso se escribe el extract/transform
   concreto.
3. **Regla de "B2B"**: como distinguir en la fuente una empresa B2B de otras
   (una columna `type`/`segment`, una tabla aparte, un flag), para no traer
   registros fuera de alcance.

## Trabajo tecnico previsto en IAERP (cuando haya inputs)

- Modulo migrador `backend/app/migration/` con el pipeline reusable
  (extract/stage/validate/transform/load/reconcile), tabla de control de
  corridas (`migration_run`) y modo `dry-run`.
- Adaptador de fuente para la conexion de solo lectura (driver segun el motor).
- Transform Fase 0 (empresas -> tenants) con sus vectores de prueba a partir
  de un dataset sintetico que imite la forma del origen (sin datos reales).
- Reporte de conciliacion (JSON + resumen legible) y pruebas del migrador
  (validacion de RUC, idempotencia, deteccion de duplicados/conflictos).
