# Evidencia: validacion MCP con Inspector real (Sprint 1)

- Fecha: 2026-07-03 `America/Guayaquil`.
- Cliente: `@modelcontextprotocol/inspector` en modo CLI (`npx --yes
  @modelcontextprotocol/inspector --cli`).
- Servidor: `http://localhost:8000/mcp` (stack local de Compose con
  `AUTH_MODE=oidc`, Keycloak 26.6.4).
- Todos los datos mostrados son sinteticos del seed `sprint-01-v1`. Los access
  tokens se redactan como `<token>`.

## Protected Resource Metadata

```bash
curl -s http://localhost:8000/.well-known/oauth-protected-resource/mcp
```

```json
{
  "resource": "http://localhost:8000/mcp",
  "authorization_servers": ["http://localhost:8080/realms/iaerp"],
  "scopes_supported": [],
  "bearer_methods_supported": ["header"]
}
```

## Request sin token: 401 con puntero al PRM

```text
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer error="invalid_token",
  error_description="Authentication required",
  resource_metadata="http://localhost:8000/.well-known/oauth-protected-resource/mcp"
```

## Emision de tokens (client credentials por tenant)

```bash
curl -s -X POST \
  http://localhost:8080/realms/iaerp/protocol/openid-connect/token \
  -d 'grant_type=client_credentials&client_id=iaerp-agent-norte&client_secret=<secret>'
```

## Catalogo de tools filtrado por scopes de la service account

```bash
npx --yes @modelcontextprotocol/inspector --cli http://localhost:8000/mcp \
  --transport http --header "Authorization: Bearer <token>" --method tools/list
```

- `iaerp-agent-norte` (scopes `context:read parties:read products:read`):
  `["context.get", "parties.search", "products.search"]`
- `iaerp-agent-sur` (scopes `context:read parties:read`):
  `["context.get", "parties.search"]`
- Ninguna tool de escritura (`parties.create`, `products.create`) aparece sin
  el scope correspondiente.

## `context.get` resuelve el tenant de cada agente

```bash
npx --yes @modelcontextprotocol/inspector --cli http://localhost:8000/mcp \
  --transport http --header "Authorization: Bearer <token>" \
  --method tools/call --tool-name context.get
```

Con el token de `iaerp-agent-norte`:

```json
{
  "tenantId": "11111111-1111-4111-8111-111111111111",
  "ruc": "1791234502001",
  "name": "IAERP Demo Norte",
  "roles": ["agent"],
  "scopes": ["context:read", "parties:read", "products:read"],
  "automationWritesEnabled": false
}
```

Con el token de `iaerp-agent-sur`:

```json
{
  "tenantId": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  "ruc": "1795432104001",
  "name": "IAERP Demo Sur",
  "roles": ["agent"],
  "scopes": ["context:read", "parties:read"],
  "automationWritesEnabled": false
}
```

## `parties.search` devuelve solo datos del tenant del token

```bash
npx --yes @modelcontextprotocol/inspector --cli http://localhost:8000/mcp \
  --transport http --header "Authorization: Bearer <token>" \
  --method tools/call --tool-name parties.search --tool-arg query=Sintetico
```

Con el token de `iaerp-agent-norte` la respuesta contiene unicamente
`Cliente Sintetico Norte`; el `Proveedor Sintetico Sur` del otro tenant no
aparece.

## Conclusiones

- El flujo MCP OAuth completo funciona con un cliente real: descubrimiento via
  PRM, `WWW-Authenticate` con `resource_metadata` en 401, bearer token por
  header y validacion estricta de audience en el servidor.
- El catalogo y las respuestas quedan limitados al tenant y scopes de la
  service account, sin fuga entre tenants.
- Reproducible con el stack local: `AUTH_MODE=oidc docker compose up -d --wait`
  y los comandos anteriores.
