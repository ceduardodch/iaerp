# ADR 0006: Outbox, Celery y Redis

- Estado: Accepted
- Fecha: 2026-07-02

## Contexto

SRI, comunicaciones, extraccion e IA pueden tardar o fallar. Ejecutarlos dentro
de la peticion crea timeouts y efectos perdidos.

## Decision

Guardar eventos outbox en la transaccion de negocio y procesarlos con Celery y
Redis. Cada job es idempotente, registra intentos y termina en dead letter cuando
agota reintentos.

El dispatcher reclama lotes PostgreSQL con `FOR UPDATE SKIP LOCKED`, asigna un
lease recuperable y publica un `event_id` estable. Solo marca publicado despues
de confirmacion del broker. Cada consumidor mantiene inbox/deduplicacion por
`event_id`, usa confirmacion tardia y puede repetir sin duplicar efectos.

Dead letters permanecen en PostgreSQL con payload redacted, error, intentos y
accion operativa. Redis/Celery transporta; no es fuente de verdad.

## Consecuencias

- No se pierde el vinculo entre cambio y efecto externo.
- Redis no es fuente de verdad.
- Se requiere dispatcher, scheduler y operacion de colas.
- Publicacion y consumo son al menos una vez; idempotencia produce el efecto
  observable de exactamente una vez.
