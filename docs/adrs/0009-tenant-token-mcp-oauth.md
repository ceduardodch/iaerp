# ADR 0009: Tenant activo y compatibilidad OAuth MCP

- Estado: Proposed
- Fecha: 2026-07-02

## Contexto

Un usuario puede pertenecer a varios tenants, pero cada access token debe quedar
ligado a uno. Keycloak Organizations soporta el scope dinamico
`organization:<alias>` y puede incluir el organization id en el token. Keycloak
tambien puede agregar audiences mediante client scope mapper.

MCP OAuth requiere Protected Resource Metadata, audience/resource binding y
validacion estricta. La documentacion oficial revisada no confirma soporte
completo de Keycloak para el parametro RFC 8707 `resource` en el flujo requerido.

## Decision propuesta

- Keycloak autentica y representa cada tenant como Organization.
- La aplicacion solicita una sola `organization:<alias>`; nunca
  `organization:*` para operaciones.
- El token contiene `iss`, `aud`, `azp`, `sub` o `client_id`, `organization.id`,
  `scope`, `exp` y `jti`.
- IAERP mapea `organization.id` a `tenant_id` y valida en base la membresia activa
  en cada request. La base IAERP es fuente de verdad de permisos de negocio.
- Revocar una membresia bloquea acceso inmediatamente aunque el token no expire.
- Access tokens duran como maximo cinco minutos.
- Service accounts se vinculan a un unico tenant y no cambian contexto.
- Web cambia tenant mediante nueva autorizacion OIDC con el alias elegido.
- API y MCP usan audiences separadas y no aceptan tokens destinados al otro.

## PoC bloqueante

Antes de aceptar este ADR se debe demostrar con Keycloak:

1. Organization seleccionada en access token.
2. Audience exacta para API y MCP.
3. Authorization Code + PKCE para web.
4. Client Credentials para service account de un tenant.
5. Protected Resource Metadata y flujo real desde MCP Inspector.
6. Comportamiento del parametro RFC 8707 `resource`.
7. Revocacion de membresia con token aun vigente.

Si Keycloak no cumple el flujo MCP sin extensiones inseguras, se presentara un
ADR sustituto para un authorization server compatible o un gateway OAuth
limitado. No se implementara un authorization server casero.

## Fuentes

- https://www.keycloak.org/docs/latest/server_admin/
- https://www.keycloak.org/securing-apps/token-exchange
- https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization

## Consecuencias

- Sprint 1 no implementa auth definitiva hasta cerrar el PoC.
- Tokens antiguos nunca sustituyen la validacion de membresia activa.
- No se confia en un `tenant_id` enviado por cliente o modelo.
