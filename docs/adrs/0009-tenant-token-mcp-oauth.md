# ADR 0009: Tenant activo y compatibilidad OAuth MCP

- Estado: Accepted
- Fecha: 2026-07-02 (propuesto), 2026-07-03 (aceptado con el PoC completo)

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

## Resultado del PoC (2026-07-03, Keycloak 26.6.4)

Los siete puntos quedaron demostrados y automatizados contra el stack local:

1. Organization seleccionada en el token: `scripts/keycloak_poc.py` y
   `backend/tests/test_tenant_switch_poc.py`.
2. Audience exacta y no intercambiable entre API y MCP: la API rechaza tokens
   con audience MCP y el MCP rechaza tokens con audience API
   (`test_tenant_switch_poc.py::test_api_and_mcp_audiences_are_not_interchangeable`).
3. Authorization Code + PKCE para web con cambio de tenant por nueva
   autorizacion: `frontend/tests/oidc.spec.ts`.
4. Client credentials por tenant, lifespan <= 300 s y ciclo de vida completo:
   `backend/tests/test_service_account_poc.py` y
   `backend/scripts/validate_oidc_runtime.py`.
5. Protected Resource Metadata y flujo real desde MCP Inspector:
   `docs/evidence/sprint-01-mcp-inspector.md`.
6. RFC 8707: Keycloak NO es estricto; acepta un `resource` ajeno (HTTP 200).
   Se adopta el perfil `fixed-audience-with-resource-server-validation`:
   audience fija por mapper y validacion estricta de audience/resource en API
   y MCP. Un token nunca se acepta por el `resource` declarado por el cliente.
7. Revocacion con token aun vigente: tanto de service account (rechazo
   inmediato en MCP y bloqueo de nueva emision) como de membresia de usuario
   (`test_tenant_switch_poc.py::test_revoked_membership_blocks_still_valid_token`).

Ademas: un usuario sin membresia en la organizacion solicitada recibe de
Keycloak un token sin claim `organization` (el scope se omite en silencio);
la validacion estricta de IAERP es la que bloquea el acceso. Esto confirma que
la base IAERP debe seguir siendo la fuente de verdad de permisos en cada
request.

## Fuentes

- https://www.keycloak.org/docs/latest/server_admin/
- https://www.keycloak.org/securing-apps/token-exchange
- https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization

## Consecuencias

- Keycloak queda confirmado como authorization server; no se requiere ADR
  sustituto ni gateway OAuth adicional.
- Tokens antiguos nunca sustituyen la validacion de membresia activa.
- No se confia en un `tenant_id` enviado por cliente o modelo.
- La validacion estricta de audience/resource en API y MCP es obligatoria y
  permanente porque Keycloak no aplica RFC 8707 de forma estricta.
