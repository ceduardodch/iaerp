# Conexión iOS a IAERP

Corte 2026-11-18: Carlos autorizó conectar e instalar la app. El cliente público
`iaerp-ios` está creado en Keycloak y permanece **deshabilitado** mientras se
valida/publica la política del servidor en la PR #107.

| Campo | Valor preparado en la app |
| --- | --- |
| API | `https://iaerp.b2b.com.ec/api/v1` |
| Issuer | `https://iaerp-auth.b2b.com.ec/realms/iaerp` |
| Client ID | `iaerp-ios` |
| Callback exacto | `ec.com.b2b.iaerp:/oauth2redirect` |
| Documentos | `iaerp-files.b2b.com.ec` |
| Empresa | Alias de una organización de la cuenta autenticada |

`keycloak-ios-client.json` fija Authorization Code y PKCE S256; sin secreto,
password grant, implicit flow, service account ni offline_access. El scope
`profile` mínimo sólo aporta nombre y usuario en ID token/UserInfo, no añade
roles. No se cambian scopes por defecto del realm ni los demás clientes.

`configure-native-client.py` se ejecuta dentro del entorno existente de la API
con sus credenciales de administración; nunca las imprime ni las copia al Mac.
La preparación deja el cliente deshabilitado. Antes de `--enable` hay que pasar
CI, publicar por main/CI/Coolify y comprobar la política servida. El script exige
los SHA256 esperados de las cuatro fuentes del backend y los compara en `/app`;
no basta una comprobación de salud o una ruta pública. Concilia sólo asociaciones
del cliente iOS y lo habilita al final, tras comprobar su configuración.

## Permisos y recuperación

El backend reconoce el cliente nativo por claims firmados y exige audience de
API. Resuelve usuario, tenant y membresía vigentes en cada petición. Lecturas
quedan limitadas a scopes nativos; `invoices:write` exige owner/admin/billing
en esa empresa. Las únicas mutaciones nativas permitidas son preview y creación
de borrador. Emisión, anulación, envío y demás escrituras se rechazan antes de
abrir la operación de negocio. Web y agentes conservan sus políticas existentes.
[ADR 0024](../../docs/adrs/0024-ios-production-connection-policy.md).

Antes del POST, iOS guarda clave/payload en Keychain DeviceOnly. Un reinicio
consulta `/invoices/draft-requests/{idempotency_key}` para el mismo usuario,
tenant y operación. Si hace falta reintenta la solicitud original, con permisos
vigentes y dentro de 23 horas, frente a una retención mínima de servidor de 24.
Después sólo concilia: la ausencia de una clave caducada no autoriza otra factura.
[ADR 0025](../../docs/adrs/0025-ios-durable-draft-recovery.md).

## Prueba física pendiente

Verificar login PKCE y cancelación; seleccionar cuentas guardadas con Face ID o
código; consultar clientes/facturas de la empresa correcta y abrir documentos.
Para probar Guardar, elegir una operación revisada: crea un borrador real y no
lo emite al SRI. Los tests sintéticos no sustituyen esa prueba autenticada.
No existe acción de emisión fiscal en esta versión.

[Evidencia actual](../validation/2026-11-18-live-connection.md).
