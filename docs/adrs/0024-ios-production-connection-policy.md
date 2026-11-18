# ADR 0024: Conexión iOS y permisos efectivos del piloto

- Estado: Accepted
- Fecha: 2026-11-18
- Solicitud humana: Carlos pide «Deja todas las conexiones a iaerp haz lo q
  necesites» y avisar cuando pueda instalar y probar, tras aclarar que el destino
  es su IAERP productivo. Se preparan las conexiones y controles necesarios.
- No autoriza emisión SRI real como prueba, reset de usuarios/realm, rotación
  global de secretos ni cambios de permisos de los clientes web o agentes.

## Decisión

Precargar en el cliente nativo la API `https://iaerp.b2b.com.ec/api/v1`, issuer
`https://iaerp-auth.b2b.com.ec/realms/iaerp`, cliente `iaerp-ios` y host privado
de archivos `iaerp-files.b2b.com.ec`. Son datos públicos; la empresa y la identidad
se eligen mediante autenticación y el tenant se resuelve en el servidor.

Registrar un cliente público iOS independiente: PKCE S256 obligatorio, code flow,
callback/login y postlogout exacto `ec.com.b2b.iaerp:/oauth2redirect`. Sin secreto,
password grant, implicit, service account o scope offline. Mantener refresh
normal; la revocación/vencimiento requiere nueva identificación.

El realm actual no contenía `profile`. Crear ese scope estándar sólo si falta,
con `preferred_username` y `name` en ID token/UserInfo, sin esos datos en el access
token. Adjuntarlo sólo al nuevo cliente; no añadirlo a defaults del realm ni
modificar otras aplicaciones. Las etiquetas no deciden permisos.

Para tokens firmados cuyo `azp` o `client_id` identifica `iaerp-ios`, rechazar
claims de cliente contradictorios, exigir audiencia API y excluir audiencia MCP.
Resolver usuario/membresía activa del tenant en cada request y calcular:

`scopes efectivos = scopes emitidos ∩ allowlist móvil ∩ política de membresía`.

El piloto permite los scopes de consulta necesarios: context, memberships,
organization, parties, products e invoices. `invoices:write` se conserva sólo
para roles de membresía `owner`, `admin` o `billing`, ya declarados en el dominio.
No inferir escritura para roles ambiguos. Las políticas web/service accounts no
se cambian con esta entrega.

La API heredada comparte `invoices:write` con emitir, enviar, anular, archivar y
duplicar. Por eso el cliente nativo sólo puede mutar mediante **POST /invoices**
y **POST /invoices/preview**; las otras mutaciones fallan antes del caso de uso,
auditoría o outbox. Tener permiso de borrador no permite emitir ante SRI por
llamada directa. Las lecturas siguen exigiendo su scope y aislamiento de tenant.
Las rutas autorizadas invocan los mismos casos de uso existentes.

Añadir una lectura específica `GET /invoices/draft-requests/{idempotency_key}`,
con `invoices:read`. Devuelve sólo `invoiceId` de una operación completada del
mismo actor/tenant y de creación de borrador, con documento existente del mismo
tenant. Clave UUID textual exacta: no normalizar mayúsculas. Ausente/ajena/no
completada responde 404; no se devuelve el payload ni un acceso genérico a tablas.
Un registro retenido tras su TTL puede confirmar la operación por lectura.

## Activación y pruebas

Preparar inicialmente el cliente deshabilitado. Habilitarlo sólo después de
publicar y verificar que la API ejecuta esta política; CI/local por sí solos no
prueban ese estado. Conservar representación final sanitizada de cliente,
defaults/optional scopes y callbacks, sin secretos o registros de usuarios.

Probar JWT RS256 verificado, dos roles y dos tenants con el mismo sujeto,
downgrade/revocación, scopes ajenos podados, colisión de service account,
audiencias/claims inválidos y POST fiscales denegados antes del UOW. No emitir
en producción para demostrar la denegación. Verificar además contrato real y
login PKCE en el dispositivo; registrar firma/instalación por separado.

Backend Platform y MCP AI Security revisaron la política. La recuperación de
escrituras se decide por separado en ADR 0025. No se promete conexión completa
por haber leído discovery, registrado un cliente o compilado el iPhoneOS.
