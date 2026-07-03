# ADR 0002: Keycloak para identidad OAuth/OIDC

- Estado: Accepted
- Fecha: 2026-07-02

## Contexto

La web, APIs, service accounts y MCP externo necesitan OAuth 2.1, OIDC, rotacion
y revocacion. Construir un authorization server propio aumenta riesgo.

## Decision

Usar Keycloak como Authorization Server. Web usa Authorization Code + PKCE;
service accounts usan Client Credentials. API y MCP validan tokens como Resource
Servers.

## Consecuencias

- Se evita implementar criptografia y flujos OAuth propios.
- Keycloak agrega operacion, backups y hardening.
- Membresias y reglas de negocio permanecen en IAERP.
