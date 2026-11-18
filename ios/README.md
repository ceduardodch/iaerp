# IAERP para iPhone

Cliente SwiftUI en [IAERP.xcodeproj](IAERP/IAERP.xcodeproj), esquema `IAERP`.
Fuente del proyecto: [project.yml](IAERP/project.yml), XcodeGen 2.45+.
[Backlog](../docs/backlog/ios-backlog.md) · [ADR 0022](../docs/adrs/0022-native-ios-client.md).

## Conexión IAERP — 0.4.1 (5), en validación

Carlos autorizó conectar la app a IAERP e instalarla en su iPhone. La pantalla
de acceso trae la API, issuer, cliente público y host de documentos de IAERP;
el usuario indica el alias de su empresa y se identifica con su cuenta.
No guarda contraseñas. La conexión nunca sustituye errores reales por datos demo.

La política nativa del servidor cruza scopes con la membresía vigente de cada
empresa. Sólo owner/admin/billing pueden crear borradores; el cliente iOS no
puede emitir, anular ni enviar comprobantes aunque solicite esos scopes.
La [PR #107](https://github.com/ceduardodch/iaerp/pull/107) está publicada como
`2bcd013`, CI/Coolify correctos y cuatro huellas de backend verificadas.
`iaerp-ios` está habilitado. El acceso code/PKCE abre el formulario de login;
PKCE ausente y callback ajeno se rechazan. Eso no acredita un login autenticado
desde el teléfono. La app sigue en [PR #108 de borrador](https://github.com/ceduardodch/iaerp/pull/108).

Un guardado incierto conserva clave y solicitud en Keychain, ligados a usuario,
organización y tenant. Tras reiniciar consulta el resultado y recupera el mismo
borrador. No permite crear otro mientras quede pendiente. Después de un intento sólo concilia por lectura: un resultado desconocido
requiere revisión y nunca autoriza otro POST por el reloj del teléfono.
«Continuar guardado» puede enviar por primera vez; «Consultar guardado» sólo lee.
Cerrar el formulario conserva el pendiente.
[ADR 0024](../docs/adrs/0024-ios-production-connection-policy.md) y
[ADR 0025](../docs/adrs/0025-ios-durable-draft-recovery.md).

Pruebas locales: **80 SwiftPM, 42 AppHost y 19 UI correctas**, sin fallos ni
omisiones. Incluyen tres terminaciones reales del proceso y auditoría stock con
texto máximo, sin filtros. Persisten tres avisos de dimensión en runtime.
Build arm64 iPhoneOS 0.4.1 (5) sin firma correcto. La CI iOS anterior se canceló
por tiempo y mostró dos fallos de UI en iOS 27.2; último candidato remoto pendiente.
[Evidencia del corte](validation/2026-11-18-live-connection.md).

Teléfono físico emparejado por cable, iOS 26.0.1 compatible con el mínimo 26.
El titular actualizó la sesión de Apple. La firma ahora falla por límite de
iPhones registrados del Personal Team; Carlos confirma que sólo tiene esa cuenta. Instalación
y primer login siguen pendientes. Face ID y VoiceOver requieren revisión física.

## Cuentas guardadas — base 0.3.0 (3)

El selector recuerda varios usuarios y empresas en Keychain, sin contraseñas.
Muestra nombre, usuario y empresa; cada elección pide Face ID o código del
iPhone y después valida la sesión con el servidor. Cambiar cuenta conserva
las guardadas y borra el contexto/documentos previos. Al pasar a segundo plano
se bloquea el acceso real; al volver se elige y desbloquea otra vez.

**Añadir cuenta** abre el proveedor de acceso para la primera identificación.
Las opciones de una cuenta permiten **Volver a iniciar sesión** o **Quitar de
este iPhone**, con confirmación identificada. **Cerrar sesión** elimina sólo la
activa e intenta cerrarla también en el proveedor. Si el servidor revoca la
sesión, hace falta identificarse otra vez. Sin autenticación del dispositivo
disponible o con cancelación no se abre una cuenta guardada.

[ADR 0023](../docs/adrs/0023-ios-saved-accounts.md). **77 SwiftPM y 25 AppHost
correctas; tres UI de cuentas correctas, incluida auditoría de texto máximo**.
Build iPhoneOS arm64 sin firma correcto. [Evidencia y capturas](validation/2026-11-18-cuentas.md).
La prueba de Face ID, firma e instalación en el iPhone siguen pendientes. La política del servidor y la recuperación durable se ampliaron en 0.4.0;
el corte actual anterior detalla las verificaciones pendientes. No se instalaron
dependencias o runtimes nuevos para este incremento.

## Versión en preparación

Tres secciones: **Clientes, Facturas y Cuenta**. Incluye búsqueda y ficha de
cliente; selección de productos; preview; guardado idempotente de un borrador;
listado/ficha con estados SRI y cobro separados; RIDE/XML y compartir por acción
humana. AppAuth y el cliente REST están preparados para una conexión revisada.
No existe acción de emitir al SRI en esta versión.
El corte anterior 0.2.0 compila para iPhone y pasa 58 pruebas SwiftPM, 17 de app y
13 de 14 recorridos UI. La auditoría del formulario con texto máximo sigue
fallando por contraste; está registrada en IOS-017 y no se marca aprobada.
El plazo inicial toma cliente, empresa o contado; permite ajustarlo y guarda
la cuota con el total exacto del preview y fecha de Guayaquil. Los campos
numéricos tienen «Listo» para cerrar el teclado.

La app abre en una bienvenida: **Probar demo** usa sólo fixtures y memoria;
**Entrar a mi empresa** solicita configuración pública y abre el navegador de
acceso. Las direcciones públicas de IAERP vienen preparadas; no hay campos para pegar tokens.
El selector de **Cuentas guardadas** recupera el perfil elegido de Keychain,
tras comprobar al usuario del dispositivo, y vuelve a validar `/context`.
La contraseña se escribe sólo en la página del proveedor de acceso.

La demo tiene dos empresas, roles, cinco estados de factura y documentos
ficticios. Permite preparar ejemplos con los dos productos del catálogo,
cantidades 1, 2 o 3, precios originales y descuento cero. Sus previews vienen
de una tabla fija; no copia cálculos fiscales del servidor. Los borradores de
prueba se borran al salir o cambiar empresa. Un error de conexión real nunca
activa datos demo como sustituto.

## Estructura

- `Sources/IAERPClient`: DTO, Decimal exacto, REST, documentos y fixture de demo.
- `Sources/IAERPIdentity`: configuración, AppAuth, Keychain y ciclo de sesión.
- `App/Workspace`: pantallas y estado aislado en MainActor; `ERPComponents.swift`
  comparte búsqueda, badges y filas. La demo inicial queda como regresión.
- `Tests`: Swift Testing de lógica/contratos con proveedores controlados.
- `AppTests`: formulario, carreras, cambios de sesión y limpieza en iOS.
- `UITests`: recorridos y auditoría nativa con todos los tipos, sin exclusiones.
- `configuration`: cliente público de Keycloak preparado para revisión.

AppAuth iOS 3.0.0 está fijado por revisión en `Package.resolved`. Es la única
biblioteca externa; no se usa CocoaPods. El único registro durable de negocio es la solicitud mínima de un guardado
pendiente, según ADR 0025; no hay catálogo ni documentos offline. Tokens/perfil quedan en Keychain `WhenUnlockedThisDeviceOnly`;
archivos compartibles se protegen, excluyen de backup y purgan al iniciar,
salir y cambiar de sesión, incluso tras un cierre inesperado.
Compartir conserva el nombre del documento y evita sobrescribir otra descarga.
Un fallo de borrado de Keychain se informa; no se promete eliminar credenciales
si el sistema rechaza esa operación.

## Comprobar desde la raíz

Entorno local: macOS 26.6.2, Xcode 27.2 (27B52), SDK 27.2. Se reutilizó el runtime
existente iOS 26.5 (23F77), con un solo dispositivo `IAERP iPhone 14`, ID
`9E0D1622-65DF-40B0-86B8-C9D81F560A29`. No se descargó otro runtime.

```sh
xcodegen generate --spec ios/IAERP/project.yml
plutil -lint ios/IAERP/IAERP.xcodeproj/project.pbxproj
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer swift test --package-path ios/IAERP
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer \
  IAERP_SIMULATOR_ID=9E0D1622-65DF-40B0-86B8-C9D81F560A29 \
  bash ios/scripts/test-ios.sh
```

El script no instala herramientas ni descarga simuladores. Si el ID no existe,
consultar `xcrun simctl list devices available` y elegir uno disponible.
`IAERP_DERIVED_DATA_PATH` elige la caché de compilación y `IAERP_RESULT_PATH` el
resultado `.xcresult`; por defecto quedan en `/tmp`. Se evita DerivedData dentro
de Documentos: los frameworks SPM añadían un RPATH absoluto allí y el cargador
se quedaba detenido antes de arrancar. La misma app avanzó al compilar en `/tmp`.
El `xcode-select` global permanece en Command Line Tools.

Las dos suites no se sustituyen: SwiftPM prueba modelos/adaptadores y Xcode
prueba la app dentro de iOS. [Evidencia inicial](validation/2026-11-17.md) y
[corte del incremento](validation/2026-11-17-incremento.md).
El workflow [iOS](../.github/workflows/ios.yml) usa `xcode-27` con Xcode 27.2 y un
iPhone 17/iOS 27.2 ya instalado en el runner, sin descargar otro. Está preparado;
no se hizo push ni se ejecutó en GitHub. No publica builds ni toca Coolify.
[Imagen oficial del runner](https://github.com/actions/runner-images/blob/main/images/macos/xcode-27-arm64-Readme.md).

## Conexión real e instalación

La [configuración](configuration/README.md) describe los endpoints y la puerta
para habilitar el cliente público. Los tests sintéticos no acreditan el primer
login real, los documentos reales ni el guardado contra producción.

Para instalar, conectar/desbloquear el iPhone y completar las pantallas de
confianza o Developer Mode si Apple las solicita. Xcode toma el Team del titular
mediante configuración local; no se versionan credenciales ni perfiles.
Bundle ID: `ec.com.b2b.iaerp.demo`. IOS-004 sigue parcial hasta abrir la app
firmada en el teléfono. TestFlight requiere una entrega y autorización aparte.

## Revisar la demo en el teléfono

1. Probar demo → buscar Costa o Álamo → abrir la ficha del cliente.
2. Crear un borrador con Servicio de ejemplo, cantidad 1 y plazo 30 días.
   Revisar el total ficticio USD 115, guardar y reabrir su plan de pago.
3. Abrir una factura autorizada de ejemplo y ver RIDE/XML; el contenido avisa
   que es ficticio y no tiene validez fiscal.
4. Cuenta → Mi empresa → cambiar empresa; comprobar sus clientes distintos.
5. Cerrar sesión, probar texto grande/modo oscuro y revisar VoiceOver.

Sólo se mantienen herramientas y cachés necesarias. Se reutiliza el runtime
26.5 y un simulador propio; no se instalaron más herramientas o dependencias.
El acceso productivo quedó configurado y se comprobaron política, callbacks y
PKCE sin credenciales ni documentos reales. No hubo login nativo autenticado,
creación real de borrador ni emisión fiscal desde estas pruebas.

Apple publica un límite de tres dispositivos en Personal Team y caducidad de
siete días. No conocemos la fecha de liberación del cupo de esta cuenta.
[Condiciones del equipo gratuito](https://developer.apple.com/help/account/basics/about-your-developer-account/).
