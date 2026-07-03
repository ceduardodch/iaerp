# Arquitectura

## Enfoque

Se usara un monolito modular. Es la opcion adecuada para un equipo de 2-3
personas: conserva transacciones consistentes entre facturacion y cartera, evita
operacion prematura de microservicios y permite extraer componentes cuando exista
evidencia de escala o aislamiento.

## Componentes

```text
Browser / External Agent
          |
       Keycloak
          |
   Nginx / Coolify ingress
      |            |
 React web      FastAPI ASGI
                  |     |
                REST   /mcp
                  \     /
             Application cases
                    |
        Domain modules + policy engine
          |          |          |
     PostgreSQL    Redis       MinIO
          |
        Outbox -> Worker/Scheduler -> SRI, Email, WhatsApp, OpenAI
```

## Backend

- Python 3.12.
- FastAPI para REST y health endpoints.
- SQLAlchemy 2 con sesiones asincronas.
- Alembic como unico mecanismo de migracion.
- Pydantic v2 para comandos, respuestas y contratos.
- SDK oficial MCP estable `>=1.27,<2`, revisando la version antes de iniciar
  implementacion.
- Worker Celery y Redis para tareas externas.
- OpenTelemetry para trazas; logs JSON con correlation ID.

Estructura prevista:

```text
backend/
  app/
    modules/
      identity/
      organization/
      parties/
      catalog/
      billing/
      receivables/
      payables/
      documents/
      communications/
      automation/
      audit/
    adapters/
      rest/
      mcp/
      sri/
      storage/
      messaging/
      ai/
    infrastructure/
    main.py
  migrations/
  tests/
```

Los endpoints no contienen reglas de negocio. REST, MCP y jobs construyen un
contexto autenticado y llaman comandos/consultas de aplicacion.

## Frontend

- React y TypeScript estricto.
- Vite para build.
- TanStack Query para estado remoto.
- React Hook Form y Zod para formularios.
- Rutas y permisos derivados del tenant activo y claims.
- Pantallas por modulo, con un selector de tenant fuera del contexto de datos.

La primera experiencia es web responsive. No se planifica aplicacion movil
nativa en el MVP.

## Identidad

Keycloak actua como Authorization Server OAuth 2.1/OIDC. La API y MCP son
Resource Servers.

- Authorization Code + PKCE para web.
- Client Credentials para service accounts controladas.
- Tokens cortos; refresh token rotado.
- El token contiene una sola Keycloak Organization seleccionada; su id se mapea
  al tenant.
- `tenant_id`, roles y scopes se validan tambien contra membresia activa en la
  base en cada request.
- Cambiar de tenant requiere nueva autorizacion OIDC; el modelo no envia tenant
  arbitrario.
- La compatibilidad RFC 8707 para MCP se resuelve en el PoC del ADR 0009.

## Persistencia

- PostgreSQL con una base y esquema inicial.
- Todas las tablas de negocio incluyen `tenant_id` e indices compuestos.
- Relaciones de negocio usan claves y foreign keys compuestas `(tenant_id, id)`
  para impedir referencias cruzadas incluso ante un bug de aplicacion.
- Repository layer y `AsyncSession` reciben un contexto de tenant inmutable.
- Row Level Security se decide y prueba antes de cerrar la migracion inicial; si
  se difiere, el ADR debe documentar controles compensatorios.
- Backups y restauraciones se prueban; tener backup sin restauracion no cuenta.

## Archivos y secretos

- MinIO almacena objetos privados, versionados y con checksum.
- PostgreSQL guarda metadatos, hash, tipo y owner; no blobs grandes.
- Certificados se cifran con envelope encryption y claves fuera de la base.
- Descargas usan URL firmada corta o streaming autorizado.
- Los contenedores no persisten archivos de negocio en filesystem local.

## Asincronia e idempotencia

- La transaccion de negocio inserta evento outbox.
- Una sola Unit of Work persiste idempotencia, request hash, mutacion, auditoria,
  outbox y respuesta antes de un unico commit.
- Repositories no hacen commit y no ejecutan efectos externos.
- Un dispatcher publica a Celery.
- Workers registran intento, resultado y siguiente reintento.
- Efectos externos usan idempotency key estable.
- SRI se consulta por clave antes de retransmitir un documento conocido.
- Dead-letter queue visible para operacion.
- Dispatcher usa lease recuperable y `FOR UPDATE SKIP LOCKED`; consumidores
  deduplican por `event_id` estable.

## Despliegue

Coolify administra servicios separados:

- `web`
- `api`
- `worker`
- `scheduler`
- `keycloak`
- `postgres`
- `redis`
- `minio`

Produccion se construye solo desde `main`. GitHub Actions ejecuta CI, nunca
deploy. Ambientes iniciales: local, release/preproduccion y produccion.

## Criterios para separar servicios

Un modulo se extrae solo si existe al menos una condicion:

- escala independiente demostrada;
- frontera de seguridad que no se resuelve en proceso;
- disponibilidad diferente;
- equipo propietario independiente;
- limitacion tecnica medida.

La preferencia inicial es mantener modulos y contratos claros dentro del monolito.
