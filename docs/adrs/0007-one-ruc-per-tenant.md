# ADR 0007: Un RUC por tenant

- Estado: Accepted
- Fecha: 2026-07-02

## Contexto

El producto debe ser multiempresa, pero mezclar varios emisores en un tenant
complica permisos, secuencias, certificados y limites comerciales.

## Decision

Un tenant corresponde exactamente a un RUC. Un usuario puede pertenecer a
varios tenants y seleccionar un contexto autorizado.

## Consecuencias

- Aislamiento y facturacion por suscripcion mas simples.
- Establecimientos y puntos pertenecen al tenant.
- Grupos empresariales se manejan con varias membresias, no con varios RUC en
  una misma cuenta.
