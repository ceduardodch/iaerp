# Conexión iOS a IAERP

Corte 2026-11-18: Carlos autorizó conectar e instalar la app. El cliente público
`iaerp-ios` está **habilitado** tras publicar la PR #107 y verificar la política
en la API (`2bcd013`, CI/Coolify `44314403923`). Sus cuatro huellas coinciden con
las fuentes revisadas. La plantilla sigue `enabled: false` para que importar
una copia sin la puerta del script no abra acceso por defecto.

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
los SHA256 esperados de las fuentes de control de acceso del backend y los compara en `/app`;
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
tenant y operación. Sólo un contador cero permite el primer envío original,
con permisos vigentes. Después de un intento incierto sólo consulta y concilia:
un 404 no autoriza otro POST, aunque el reloj del teléfono indique menos de
23 horas. El contador cero conserva una ventana de vigencia del primer envío;
la retención del servidor no se infiere de un reloj local.
[ADR 0025](../../docs/adrs/0025-ios-durable-draft-recovery.md).

## Prueba física pendiente

Verificar login PKCE y cancelación; seleccionar cuentas guardadas con Face ID o
código; consultar clientes/facturas de la empresa correcta y abrir documentos.
Para probar Guardar, elegir una operación revisada: crea un borrador real y no
lo emite al SRI. Los tests sintéticos no sustituyen esa prueba autenticada.
No existe acción de emisión fiscal en esta versión.

[Evidencia actual](../validation/2026-11-18-live-connection.md).

La versión 0.5.0 añade `receivables:read` al cliente nativo para el resumen de Inicio. El backend comprueba rol, empresa y ruta en cada petición. Una sesión que aún tenga el token anterior puede requerir renovarlo o volver a entrar para obtener el permiso. [ADR 0026](../../docs/adrs/0026-ios-receivables-overview.md).

La versión 0.6.0 añade `customers:create` y `products:create` al cliente iOS. La API fija el rol CUSTOMER en el alta de clientes, exige una categoría fiscal vigente en el alta de productos y verifica la membresía para ambas operaciones. El simulador y su buzón requieren permisos independientes que este cliente de producción no solicita.

La versión 0.7.0 usa los permisos `invoices:issue` e `invoices:email` para el flujo aprobado por el usuario. Se asignan al cliente OIDC público después de verificar el servidor publicado. La API limita los permisos a la membresía activa de facturación, administración o titular de la empresa. Los tokens emitidos antes del cambio pueden requerir que el usuario vuelva a iniciar sesión.
