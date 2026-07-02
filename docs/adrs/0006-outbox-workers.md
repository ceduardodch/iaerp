# ADR 0006: Outbox, Celery y Redis

- Estado: Proposed
- Fecha: 2026-07-02

## Contexto

SRI, comunicaciones, extraccion e IA pueden tardar o fallar. Ejecutarlos dentro
de la peticion crea timeouts y efectos perdidos.

## Decision

Guardar eventos outbox en la transaccion de negocio y procesarlos con Celery y
Redis. Cada job es idempotente, registra intentos y termina en dead letter cuando
agota reintentos.

## Consecuencias

- No se pierde el vinculo entre cambio y efecto externo.
- Redis no es fuente de verdad.
- Se requiere dispatcher, scheduler y operacion de colas.
