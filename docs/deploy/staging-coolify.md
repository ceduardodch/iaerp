# Despliegue de staging en Coolify (server .12) para pruebas online

Objetivo: publicar una version ONLINE para probar el ciclo de facturacion con
login real (Keycloak/OIDC) y el simulador SRI, sin exponer nada inseguro.
NO es produccion: usa el simulador SRI, no emite ante el SRI real.

Dominios de SERVER.12:

- App y API: `https://iaerp.b2b.com.ec`
- Identidad: `https://auth.iaerp.b2b.com.ec`
- Documentos privados: `https://files.iaerp.b2b.com.ec`

## Postura de seguridad (obligatoria)

`APP_ENV=staging` fuerza en el backend (ver `app/core/config.py`):

- `AUTH_MODE=oidc` obligatorio -> `/api/v1/dev/token` responde 404, no hay
  emision de tokens sin autenticacion.
- Postgres obligatorio (no SQLite).
- `SRI_SIMULATOR_ENABLED=true` permitido SOLO en staging (en release/production
  esta prohibido). El simulador `/sri-sim` queda montado para poder autorizar
  facturas de prueba.

Si alguien intenta arrancar staging con `AUTH_MODE=dev` o SQLite, la app se
niega a iniciar. Esto es intencional.

## Rama y flujo

- Coolify en .12 esta conectado al repo y lee `compose.coolify.yaml` desde
  `release` (rama de validacion/preproduccion, AGENTS.md).
- `main` queda reservada para produccion real (SRI real), que NO es esto.
- El auto-deploy directo de Coolify esta desactivado. Un push a `release`
  ejecuta CI completo y el job `deploy-staging` llama a Coolify solamente si
  todas las validaciones terminaron correctamente.

## Servicios a desplegar

Los mismos del `compose.yaml`: `postgres`, `redis`, `minio`, `keycloak`,
`api`, `worker`, `scheduler`, `web`. En Coolify se definen como un stack (o el
compose adaptado) con los healthchecks ya presentes.

## Variables de entorno (se configuran en Coolify, NUNCA en Git)

Reemplaza `staging.tu-dominio` por el host publico real de .12.

Backend (`api`, y las relevantes en `worker`/`scheduler`):

```
APP_ENV=staging
AUTH_MODE=oidc
DATABASE_URL=postgresql+asyncpg://iaerp:<PG_PASSWORD>@postgres:5432/iaerp
REDIS_URL=redis://redis:6379/0

# OIDC / Keycloak (host PUBLICO alcanzable por el navegador para el issuer)
OIDC_ISSUER_URL=https://auth.staging.tu-dominio/realms/iaerp
OIDC_JWKS_URL=http://keycloak:8080/realms/iaerp/protocol/openid-connect/certs
OIDC_API_AUDIENCE=iaerp-api
OIDC_MCP_AUDIENCE=https://api.staging.tu-dominio/mcp
MCP_SERVER_URL=https://api.staging.tu-dominio/mcp
OIDC_ADMIN_URL=http://keycloak:8080
OIDC_ADMIN_REALM=iaerp
OIDC_ADMIN_CLIENT_ID=iaerp-provisioner
OIDC_ADMIN_CLIENT_SECRET=<PROVISIONER_SECRET>

# Simulador SRI (permitido en staging)
SRI_SIMULATOR_ENABLED=true

# Firma XAdES: certificado de PRUEBA (staging lo autogenera si falta).
# Debe apuntar a un volumen persistente y escribible por el usuario del
# contenedor.
IAERP_SIGNING_CERT_PATH=/home/iaerp/certs/test-signing.p12
IAERP_SIGNING_CERT_PASSWORD=<CERT_PASSWORD>

# MinIO (bucket privado). MINIO_PUBLIC_ENDPOINT DEBE ser el host publico
# alcanzable por el navegador para descargar XML/RIDE via URL prefirmada.
MINIO_ENDPOINT=minio:9000
MINIO_PUBLIC_ENDPOINT=files.staging.tu-dominio
MINIO_ACCESS_KEY=<MINIO_KEY>
MINIO_SECRET_KEY=<MINIO_SECRET>
MINIO_SECURE=true

# CORS: solo el dominio del frontend de staging
CORS_ORIGINS=https://staging.tu-dominio
```

Frontend (`web`, build args):

```
VITE_AUTH_MODE=oidc
VITE_KEYCLOAK_URL=https://auth.staging.tu-dominio
VITE_API_URL=https://api.staging.tu-dominio/api/v1
```

Keycloak (`keycloak`):

```
KC_BOOTSTRAP_ADMIN_USERNAME=<KC_ADMIN>
KC_BOOTSTRAP_ADMIN_PASSWORD=<KC_ADMIN_PASSWORD>
KC_DB=postgres
KC_DB_URL=jdbc:postgresql://postgres:5432/keycloak
KC_DB_USERNAME=keycloak
KC_DB_PASSWORD=<KC_DB_PASSWORD>
KC_HOSTNAME=auth.staging.tu-dominio
KC_HEALTH_ENABLED=true
```

Todos los `<...>` son SECRETOS: se generan una vez, se guardan en el gestor de
secretos de Coolify, y no se escriben en el repo.

## Keycloak: realm e usuarios

- El realm `iaerp` se importa desde `infra/keycloak/iaerp-realm.json`. Ese realm
  trae usuarios demo con password conocido (`owner` / `DemoPass123!`, etc.)
  utiles para la PRUEBA. Antes de dar acceso a terceros, cambia esas claves o
  crea usuarios propios.
- El issuer publico (`OIDC_ISSUER_URL`, `KC_HOSTNAME`) debe coincidir con el
  dominio real, o el login OIDC fallara por mismatch de issuer.

## Checklist antes de abrir el acceso

- [ ] `GET https://api.staging.tu-dominio/api/v1/dev/token` devuelve 404
      (confirma que no hay emision de tokens sin auth).
- [ ] Login OIDC real funciona (redirige a Keycloak y vuelve autenticado).
- [ ] Crear factura -> Emitir -> pasa a AUTORIZADA via simulador.
- [ ] Descarga de XML/RIDE por URL prefirmada funciona desde el navegador
      (requiere `MINIO_PUBLIC_ENDPOINT` correcto y TLS).
- [ ] `GET .../sri-sim/...` existe (simulador montado) pero NO expone datos de
      otros tenants.
- [ ] Un GET anonimo al bucket MinIO devuelve 403.
- [ ] TLS activo en todos los hosts publicos (api, web, auth, files).

## Que NO hace staging

- No emite ante el SRI real (no hay certificado acreditado ni endpoints
  oficiales; usa el simulador).
- No es el destino de la migracion de datos reales de skyfranquicias (eso se
  planifica aparte, ver `docs/migration/`).
