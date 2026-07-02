# Contratos preliminares

Estos archivos son especificacion de Sprint 0, no una implementacion ejecutable.

- `openapi.yaml`: superficie REST inicial y schemas comunes.
- `mcp-tools.yaml`: catalogo de tools, scopes, efectos e idempotencia.

## Convenciones

- OAuth/OIDC es obligatorio.
- El tenant activo proviene del token; no aparece como argumento confiable.
- Montos viajan como strings decimales.
- Toda escritura exige header/campo `idempotencyKey`.
- Errores incluyen `code`, `message` y `correlationId`.
- IDs son UUID.

Al iniciar Sprint 1, estos contratos se convierten en tests. Cualquier cambio
incompatible debe actualizar el ADR/alcance y versionar el contrato.
