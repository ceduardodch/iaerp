# IAERP para iPhone: backlog y avance

- Fecha: 2026-11-18, America/Guayaquil.
- Estado: **0.4.1 en validación; conexión productiva e instalación física en curso**.
- Objetivo: instalar IAERP en el iPhone de Carlos y sumar funciones por entregas pequeñas.
- Decisión de arquitectura: [ADR 0022, Accepted](../adrs/0022-native-ios-client.md).
- Calidad: [Definition of Done vigente](../09-testing-quality.md).

## Dirección aprobada

App nativa en **Swift y SwiftUI**, con el backend actual como fuente de verdad.
Primero, instalar, entrar y consultar clientes. Después, preparar facturas,
guardar borradores y probar su emisión antes de sumar otros módulos.
Cada parte termina con una demostración y revisión de Carlos antes de abrir la siguiente.
No se propone copiar todo el ERP en la primera versión.

Carlos indicó «Empecemos» después de revisar la propuesta. Esto autoriza la
dirección SwiftUI y preparar el primer incremento local mientras se completa
el entorno de IOS-001. No autoriza producción ni elimina las pruebas de cierre.

## Continuación autorizada

Carlos pide el 2026-11-17 seguir avanzando hasta conectar el teléfono en unas
2 horas. Autoriza preparar las Partes 1–3 en código/simulador sin esperar la
instalación física de IOS-004. Prioridad: acceso, clientes, borrador de factura,
consulta y documentos. Las pruebas/revisiones y el cierre físico siguen
pendientes donde corresponda; esta autorización no habilita producción,
emisión SRI real, push ni distribución. No equivale a promesa de paridad web.

## Conexión autorizada — 0.4.1

Carlos pide conectar a IAERP, hacer lo necesario y avisar cuando pueda instalar
para probar. Después conecta el teléfono y autoriza continuar. Esto amplía la
preparación local a configuración nativa y publicación de controles de servidor
por release → PR → main → CI/Coolify. No autoriza emisión fiscal de prueba en SRI
producción ni cambios ajenos a esta conexión.

| Historia | Estado del corte actual |
| --- | --- |
| IOS-004 | Teléfono emparejado por cable, iOS 26.0.1 compatible. Firma bloqueada por cupo de Personal Team; Apple ID activo y sin otra cuenta. No instalada. |
| IOS-005/006/007 | Endpoints de IAERP preparados. PR #107 publicada/verificada (`2bcd013`); `iaerp-ios` habilitado con PKCE/callbacks comprobados. Login nativo físico pendiente. |
| IOS-009/010 | Registro durable Keychain y reconciliación implementados según ADR 0025. 42 AppHost correctas; un intento incierto sin lookup positivo nunca reenvía. UI termina/reabre el proceso en tres puntos con un único borrador. Guardado real y auditoría del servidor por comprobar. |
| IOS-017 | Auditorías previas de cuentas/consultas correctas; formulario con texto máximo en validación. VoiceOver/horizontal físicos pendientes. |
| IOS-020/026 | Múltiples perfiles guardados y bloqueo local implementados; prueba Face ID/código en el teléfono pendiente. |
| IOS-021 | Workflow macOS preparado, sin ejecutar aún la CI iOS remota. Backend PR #107 tiene CI propia en curso. |

**80 SwiftPM y 42 AppHost correctas**. Las fuentes locales resuelven los dos P1
anteriores de permisos y recuperación, con el acceso habilitado tras verificar el backend publicado. Una operación
incierta sin resultado exige conciliación; no depende del reloj local. No hay emisión fiscal en la interfaz móvil.
[Evidencia actual](../../ios/validation/2026-11-18-live-connection.md).
Los apartados de avance anteriores que siguen conservan sus resultados históricos.

## Cuentas guardadas — prioridad pedida el 18 de noviembre

Carlos solicita guardar **varios usuarios**, elegir uno y entrar sin repetir
claves mientras su sesión siga vigente. Se adelanta IOS-020 y se añade IOS-026,
con [ADR 0023](../adrs/0023-ios-saved-accounts.md). No cambia las puertas del
piloto real ni exige instalar herramientas nuevas.

| Historia | Criterios de aceptación | Estado |
| --- | --- | --- |
| IOS-026 / P1 | Guardar varias identidades usuario+empresa en Keychain; elegir por UUID estable; nombre/usuario/empresa distinguibles, incluso con nombres iguales. Alta interactiva; cambiar conserva perfiles, limpia contexto y documentos; quitar sólo elimina el elegido y pide confirmación identificada. Migrar sesión v1 sin pérdida o resurrección. Automatizar dos usuarios en una empresa, dos empresas, A/B/A, borrado individual, refresh tardío y errores transitorios. | Preparada localmente: 77 SwiftPM +25 AppHost correctas y tres UI de cuentas correctas; ver evidencia del 18 de noviembre. Acceso real/instalación pendientes. |
| IOS-020 / adelantada P1 | Face ID/código nuevo en cada selección; cancelar o política no disponible no permite acceso; éxito tardío de A no abre B. Al volver de segundo plano se elige/desbloquea de nuevo; inactividad del sistema de autenticación no crea un bucle. Token/membresía se validan con el servidor. Prueba física pendiente. | Controles probados con barreras y auditoría local correcta. Face ID/código y VoiceOver en teléfono pendientes. |

La primera identificación se hace en el proveedor OIDC. No se guardan claves ni
se promete acceso indefinido: revocación o vencimiento de la sesión exigen entrar
otra vez. «Cambiar cuenta» conserva acceso; «Cerrar sesión» lo elimina para la
activa; «Quitar de este iPhone» olvida sólo el perfil elegido.

[Evidencia y capturas](../../ios/validation/2026-11-18-cuentas.md). P2 posterior:
mostrar proveedor en la confirmación Quitar y distinguir realms del mismo host
si coinciden las demás etiquetas. Los UUID/configuraciones ya están separados.

## Avance de Parte 0

| Historia | Estado real |
| --- | --- |
| IOS-001 | Entorno Mac listo: Xcode 27.2 (27B52), SDK 27.2 y runtime existente iOS 26.5; build real correcto. Un simulador propio, sin descarga adicional. Unos 23 GiB libres al cierre. Falta versión exacta y detección del teléfono físico. |
| IOS-002 | Dirección y primer incremento aprobados con «Empecemos»; mínimo iOS 26 provisional hasta comprobar teléfono. |
| IOS-003 | Tres skills instalados y hashes verificados. |
| IOS-004 | Parcial: demo de clientes compila, abre y pasa pruebas en simulador iPhone 14. Carlos respondió «Lo conectaré después»; faltan firma e instalación física. |
| IOS-017 | Tres XCUITest correctos, incluida auditoría de listado/ficha con texto máximo sin exclusiones; inspección visual claro/oscuro correcta. VoiceOver manual, horizontal y teléfono pendientes. |
| IOS-021 | Proyecto reproducible y pruebas locales correctas; workflow macOS aún sin implementar. |

## Avance posterior — Partes 1–3

Versión local **0.2.0 (2)**, preparada mientras Carlos difiere conectar el
teléfono. Este corte amplía el de Parte 0; sus cierres físicos siguen pendientes.
Validación final Tests-39: 58 SwiftPM y 17 AppHost correctas, **13/14 UI**.
La auditoría del formulario con texto máximo falla por contraste y sigue
abierta en IOS-017; no se considera una entrega de calidad cerrada.

| Historia | Preparado en código y pruebas locales | Pendiente para cerrar |
| --- | --- | --- |
| IOS-005 | AppAuth 3.0.0, PKCE, perfil/tokens en Keychain, restauración explícita, refresh compartido y logout con aviso de fallos. | Login/cancelación/renovación/revocación contra Keycloak/API de pruebas; aprobación del piloto. |
| IOS-006 | Dos empresas sintéticas, limpieza de memoria/archivos, rechazo de respuestas y refresh de una sesión anterior. | Mismo usuario con roles distintos por empresa y cambio real mediante nueva autorización. |
| IOS-007 | REST tipado, Decimal exacto, sesiones efímeras, 401 una vez en lecturas, sin reintentos automáticos del POST. | Contrato contra API/base de pruebas y política por membresía. |
| IOS-008 | Búsqueda y ficha de clientes; filtro CUSTOMER, vacío/error, límite visible de 100; privacidad de ventana. | Contrato con datos sintéticos del servidor y prueba física. |
| IOS-009/010 | Selección de maestros, preview, borrador idempotente, plazo cliente/empresa/contado y cuota exacta. Regresión de commit perdido → 403 → recuperación sin duplicado. | Guardado real en entorno de pruebas, permisos y auditoría del servidor. |
| IOS-011 | Sin acción de emitir en la app. | Emisión SRI sandbox completa; no forma parte del borrador local entregado. |
| IOS-012/014 | Búsqueda/filtros y ficha de factura; número completo, estados SRI/cobro separados, cinco estados sintéticos. | Período y completitud real del contrato; autorización tardía del servidor. |
| IOS-013 | PDFKit, XML como texto, compartir por gesto; HTTPS/allowlist/SHA256/límite de descarga y temporales protegidos con nombre del comprobante. | URL vencida/acceso ajeno contra servidor y comprobación física del selector/compartir. |
| IOS-017 | Auditoría sin exclusiones y revisión UI/UX independiente; raíces y fichas probadas. | Resolver el fallo final de contraste del formulario con texto máximo; VoiceOver manual, horizontal y dispositivo. Historia abierta. |
| IOS-021 | Workflow macOS preparado con Xcode/SDK fijos, script local y retención de resultados sintéticos. | Ejecución remota autorizada; no se hizo push ni se gastó runner. |

**Bloqueo P1 para acceso real:** la configuración versionada concede
`invoices:write` sin cruzarlo con roles de la membresía. La plantilla iOS está
`enabled: false`. No habilitar el cliente hasta acordar/aplicar la política por
tenant y pasar pruebas de POST directo con consulta/facturador en dos empresas,
incluido un mismo usuario con roles distintos, revocación y reducción de permisos.
No basta ocultar `Nuevo`, mover el scope a opcional o usar un rol global.
Esto describe el código/configuración versionados; no acredita el estado del
realm productivo. [Preparación del piloto](../../ios/configuration/README.md).

**Bloqueo P1 de IOS-010 para escritura real:** `pendingInput`/`pendingKey` están
en memoria. Recuperación dentro del mismo proceso probada; terminar la app tras
el commit pierde esa identidad. Antes del piloto, decidir el registro durable
según ADR 0022 y probar recuperación de clave/payload originales ligados a
usuario/tenant/perfil, revalidación de permisos, reconciliación y vigencia de la
idempotencia. Terminar antes del envío, después del commit y después de recibir
respuesta debe dejar un único borrador; otro usuario/tenant no puede recuperarlo.
No habilitar escrituras reales mientras esto y la política de permisos sigan
pendientes. La demo local y sus borradores en memoria mantienen su alcance.

Orden de cierre: permisos e integración de pruebas → instalación/firma en el
iPhone → revisión de Carlos → emisión sandbox si se mantiene esa prioridad.
Compras, cartera, cobros, avisos y caché offline conservan su orden
posterior; no se añadieron sin una prioridad confirmada.

Evidencia: cinco pruebas Swift Testing/ocho casos correctos; build iOS correcto;
XCUITest final **3 correctos, 0 fallos, 0 omisiones** en iPhone 14/iOS 26.5.
Producto/seguridad revisaron el plan; QA y UI revisaron entrega y evidencia,
sin P0/P1 pendientes para el alcance local. Se corrigieron problemas reales de
icono, aislamiento XCTest y accesibilidad sin omitir controles.
[Corte de evidencia](../../ios/validation/2026-11-17.md) y
[guía reproducible](../../ios/README.md).

Carlos confirmó **iPhone 14 actualizado** y prioridad **crear facturas y consultar
clientes**. Falta confirmar el número exacto de iOS y si tiene cuenta Apple
Developer de pago. El orden queda Clientes → Nueva factura → Facturas/documentos;
Resumen, Compras y Cartera se revisan después. No hay fechas ni presupuesto aprobados.

## Base inicial verificada — 17 de noviembre

- Checkout `release`, revisión `82d1c56`, igual a su upstream al consultar remoto.
- Web React/TypeScript y backend FastAPI; al iniciar no existía cliente iOS.
  Ahora existe la demo sintética probada en `ios/IAERP`.
- Keycloak, un tenant por token y cambio de empresa mediante nueva autorización
  ya están definidos en [ADR 0009](../adrs/0009-tenant-token-mcp-oauth.md).
- El MVP original prioriza web. ADR 0022 acepta la ampliación nativa por partes.
- Mac: macOS 26.6.2, Apple Silicon, Xcode 27.2 (27B52), Swift 6.4 y SDK 27.2.
  `xcode-select` sigue en Command Line Tools; se usa `DEVELOPER_DIR` para Xcode.
  Build y arranque en simulador iOS 26.5 verificados; teléfono físico pendiente.
- Hay cambios locales previos de avisos y scripts SRI; quedan fuera de esta propuesta.
- El grafo del proyecto orientó la búsqueda; se contrastaron rutas y auth con
  código actual. La consulta fue parcial por límite de salida, no una auditoría completa.

## Tecnología propuesta

| Área | Elección | Motivo y límite |
| --- | --- | --- |
| IDE y SDK | Xcode estable más reciente compatible con Mac e iPhone | Xcode 27.2 (27B52) instalado y probado con SDK 27.2; runtime existente iOS 26.5. No requiere beta. |
| iOS mínimo | iOS 26 | Teléfono conectado con iOS 26.0.1, compatible. APIs posteriores se condicionan con disponibilidad y alternativa compatible. |
| Interfaz | SwiftUI, NavigationStack, TabView, SF Symbols | Navegación nativa, español, modo oscuro y Dynamic Type. Aspecto de sistema con Liquid Glass donde corresponda; importes y contenido conservan legibilidad. |
| Estado y red | Observation, async/await y URLSession | Estado visual aislado en MainActor; cancelación y protección frente a respuestas de la empresa anterior. Ajustes de concurrencia explícitos al crear el proyecto. |
| Identidad | OIDC Authorization Code + PKCE S256 | Cliente público iOS propio y sesión de autenticación del sistema; evaluar AppAuth-iOS en el PoC. Sin secreto de cliente dentro de la app. |
| Sesión | Keychain; bloqueo local con LocalAuthentication en una entrega posterior | El bloqueo local no sustituye el token ni los permisos del servidor. No guardar la clave de Keycloak o del SRI. |
| Contrato | REST existente y modelos Swift tipados | Decimal desde texto decimal exacto, nunca pasando por Double. Totales y estados fiscales proceden del servidor. |
| Datos locales | Memoria en primeras entregas | API con sesión efímera, caché de disco deshabilitada y sin cookies propias. Keychain sólo para tokens; temporales documentales controlados. Sin escrituras offline. SwiftData requiere aprobar caché persistente posterior. |
| Pruebas | Swift Testing + XCTest/XCUITest | Swift Testing para unidades e integración; XCUITest para recorridos y accesibilidad nativa. CI macOS propuesta, pendiente de presupuesto del runner. |
| Distribución | Xcode al principio; TestFlight después | Instalar en el teléfono no exige publicar en App Store. Firma y distribución se configuran con la cuenta del titular. |

Usar APIs actuales no obliga a sumar IA en el dispositivo, widgets, cámara o
dependencias sin un caso concreto. El proyecto local fija Swift 6, comprobación
completa de concurrencia y aislamiento MainActor para UI; el paquete puro usa
valores Sendable. Compilación y pruebas con Xcode real verifican esos ajustes;
XCTest usa métodos MainActor sobre un target nonisolated.

## Entregas y orden

Prioridad P0 = necesaria para el primer uso seguro; P1 = completa el alcance
elegido; P2 = opcional. Tamaño S/M/L expresa complejidad relativa, no días.
Las historias futuras mantienen su alcance propuesto; el avance real está en
los dos cortes anteriores. Las dependencias son acumulativas dentro de cada parte.

| Parte | Resultado para Carlos | Salida verificable |
| --- | --- | --- |
| 0 | Decidir alcance y preparar instalación | Entorno compatible y app de prueba instalada con datos sintéticos. |
| 1 | Entrar y consultar clientes | Login, empresa, cierre de sesión y clientes desde el iPhone. |
| 2 | Crear una factura | Cliente/producto, vista previa y borrador; emisión sólo en sandbox durante pruebas. Primera entrega funcional prioritaria. |
| 3 | Consultar facturas y documentos | Buscar factura, ver estado y abrir su RIDE. |
| 4 | Consultar compras y cartera, si se priorizan | Revisar deuda, vencimientos y respaldo por empresa; no bloquea la primera entrega de facturación. |
| 5 | Registrar acciones elegidas | Clasificación o cobro/pago con permisos, confirmación e idempotencia. Elegir un flujo antes de desarrollarlo. |
| 6 | Usar y actualizar la beta | TestFlight, pruebas en dispositivo y canal de soporte; funciones extra se priorizan aparte. |

### Parte 0 — Alcance y primera instalación

| ID | Pri / tamaño | Historia | Dependencias | Criterios y evidencia |
| --- | --- | --- | --- | --- |
| IOS-001 | P0 / S | Como dueño, confirmar dispositivo y entorno | — | iPhone 14 actualizado confirmado; registrar versión exacta de iOS, Xcode/macOS/SDK compatibles, espacio y modo de instalación. Prueba de compilación y detección de dispositivo; no actualizar macOS por defecto. |
| IOS-002 | P0 / S | Como dueño, revisar alcance y navegación | IOS-001 | Prioridad confirmada: clientes y crear facturas. Revisar Clientes, Facturas, Nueva factura y Cuenta; mínimo iOS y módulos posteriores pendientes. ADR de dirección/alcance aceptado por humano antes del código; habilitar acceso autenticado tiene su propia puerta tras el PoC. |
| IOS-003 | P0 / S | Como desarrollador, usar skills revisados | Hecha localmente | `swiftui-expert-skill`, `swift-concurrency` y `swift-testing-expert` instalados en el perfil Codex, con origen/ref/hash en `skills-lock.json`. No instala Xcode ni modifica permisos. |
| IOS-004 | P0 / M | Como dueño, abrir la primera app en mi iPhone | IOS-001, IOS-002 | Proyecto en `ios/IAERP`, bundle ID y firma propios; pantalla inicial sintética y test de arranque. Compila en simulador y abre en dispositivo. Documentar vencimiento de firma y reinstalación. |

### Parte 1 — Acceso y clientes

| ID | Pri / tamaño | Historia | Dependencias | Criterios y evidencia |
| --- | --- | --- | --- | --- |
| IOS-005 | P0 / L | Como usuario, iniciar y cerrar sesión | IOS-004, IOS-021 | PoC Keycloak de pruebas: cliente público iOS, PKCE, state/nonce, issuer/audience y callback exactos. Probar login cancelado, expiración, token de audience incorrecta, revocación y refresh concurrente. Logout borra Keychain/estado local e intenta revocar refresh/cerrar sesión OIDC; distinguir fallo remoto y SSO del navegador. Sin tokens en logs. |
| IOS-006 | P0 / M | Como usuario, elegir empresa sin mezclar datos | IOS-005 | Cada token lleva una organización; backend confirma membresía. Cambio cancela solicitudes y limpia memoria/temporales antes de mostrar otra empresa. Tests con dos tenants, dos roles, respuesta de A y refresh tardíos al estar en B; no restaurar sesión vieja. |
| IOS-007 | P0 / M | Como usuario, entender carga, errores y conexión | IOS-005 | Cliente REST tipado con URLSession efímera, URLCache deshabilitada y política sin cookies de API. 401 renueva una vez, 403 informa permiso, 429 respeta espera y 5xx permite reintentar lectura. Tests de contrato, no persistencia, cancelación y errores; escrituras sólo reintentan según idempotencia. |
| IOS-008 | P0 / M | Como facturador, consultar clientes y abrir su ficha | IOS-006, IOS-007 | Buscar clientes existentes y ver datos fiscales autorizados de `/parties`, sin mostrar proveedores como clientes por error. Scopes, búsqueda y completitud fijados en contrato; vacío/error/sin permiso cubiertos. Antes de mostrar datos, ocultar snapshot del selector de apps. XCUITest de buscar→ficha→volver y privacidad desde esta parte. |

Salida: Carlos puede abrir la app instalada, entrar, consultar clientes y salir.
La evidencia manual del teléfono complementa las pruebas automatizadas.

### Parte 2 — Crear la primera factura

| ID | Pri / tamaño | Historia | Dependencias | Criterios y evidencia |
| --- | --- | --- | --- | --- |
| IOS-009 | P0 / M | Como facturador, elegir cliente/producto y revisar importes | IOS-008 | Buscar maestros existentes con permisos. Cantidad/precio usan Decimal; preview del backend es autoridad. Tests de identificaciones, tarifas y precios sintéticos. Alta de maestros queda para una historia posterior si se necesita. |
| IOS-010 | P0 / L | Como facturador, guardar una factura en borrador | IOS-009 | Preview, validación y alta reutilizan casos de uso actuales. `Guardar` y `Cancelar` mantienen su significado; guardado no emite. Misma clave al reintentar la misma operación, doble toque no duplica. Tests de desconexión después del commit y conflicto; cliente e importe quedan bien al reabrir. |
| IOS-011 | P1 / L | Como facturador, emitir en ambiente de pruebas | IOS-010 | Confirmación explícita de empresa/ambiente/importe; seguir operación asíncrona y consultar clave antes de reenviar. Pruebas sandbox de pendiente, rechazo, timeout y autorización tardía sin duplicar. Certificado permanece en backend. Producción exige autorización humana aparte. |

Salida prioritaria: Carlos consulta un cliente, prepara líneas y guarda un
borrador desde el iPhone. Emitir y recibir autorización se demuestra en sandbox;
no se presenta ese ensayo como emisión productiva. Si un borrador guardado no
admite edición en la API actual, definir ese incremento antes de ofrecerla.

### Parte 3 — Facturas y RIDE

| ID | Pri / tamaño | Historia | Dependencias | Criterios y evidencia |
| --- | --- | --- | --- | --- |
| IOS-012 | P1 / M | Como usuario, buscar y abrir facturas | IOS-010 | Lista y ficha por período/estado; número, cliente, importe, estado SRI y cobro separados. Pruebas de vacío, sin permiso, listado completo y errores; confirmar filtros/límites reales del contrato. |
| IOS-013 | P1 / M | Como usuario, abrir RIDE/XML y compartir el documento elegido | IOS-012 | Descarga autenticada con permiso, vista PDF y hoja de compartir por acción humana. Nombre/contenido corresponden a la factura. Archivos temporales protegidos, excluidos de backup y purgados al cerrar/cambiar sesión; probar acceso ajeno, URL vencida y limpieza. Un archivo ya compartido queda bajo control de su destinatario. |
| IOS-014 | P1 / S | Como usuario, ver documentos pendientes con claridad | IOS-012 | Distinguir pendiente, rechazada, autorizada e histórica sin XML. La consulta no emite ni reenvía. Pruebas de todos esos estados y de autorización tardía. |

### Parte 4 — Compras y cartera, después de facturación

| ID | Pri / tamaño | Historia | Dependencias | Criterios y evidencia |
| --- | --- | --- | --- | --- |
| IOS-015 | P2 / M | Como usuario, consultar compras y su respaldo | IOS-008; priorización humana | Listado/ficha con proveedor, fecha, total, estado fiscal y pago separados. Documento preliminar o sin XML se señala. Pruebas de NC, compra anulada y permisos, sin cambiar reglas fiscales. |
| IOS-016 | P2 / M | Como dueño, consultar cartera y vencimientos | IOS-008; priorización humana | CxC/CxP, neto pendiente y movimientos del servidor. Fixtures con pagos/cobros parciales y revertidos, retenciones, NC, saldadas y medianoche Guayaquil. Ejemplo: 100 menos retención 10 y cobro 40 deja 50; revertir cobro deja 90 y conserva historia. |
| IOS-017 | P0 / M transversal | Como usuario, usar cada entrega con accesibilidad | Empieza en IOS-004; se amplía por pantalla | VoiceOver y tamaños grandes permiten completar cada flujo; objetivos táctiles de al menos 44 pt. Modo claro/oscuro, Reduce Motion/Transparency, errores y datos extensos cubiertos. XCUITest y auditoría nativa desde la primera pantalla; revisión manual en teléfono. No esperar a Parte 4 para aplicarlo. |

IOS-017 e IOS-021 son trabajo transversal desde Parte 0, situado aquí para
mantener identificadores únicos. Son condiciones de cierre de cada entrega,
no tareas que se dejan para el final.

### Parte 5 — Elegir y añadir una escritura a la vez

| ID | Pri / tamaño | Historia | Dependencias | Criterios y evidencia |
| --- | --- | --- | --- | --- |
| IOS-018 | P2 / L | Como operador, clasificar una compra | IOS-015; selección humana | Cambiar uso tributario/control/tags mediante el caso de uso existente. Scopes, idempotencia y auditoría; período declarado conserva sus protecciones. Tests positivo, parcial, repetido, sin permiso y otro tenant. |
| IOS-019 | P2 / L | Como operador, registrar un cobro o pago | IOS-016; selección humana | Neto consultado de nuevo, método/fecha reales y confirmación. No iniciar transferencia bancaria. Tests de parcial, retención, reverso, concurrencia, sobrepago, reintento tras timeout y doble toque. Elegir CxC o CxP para el primer incremento. |
| IOS-020 | P1 / M, adelantada | Como usuario, bloquear el acceso local a la app | IOS-006, IOS-026 | Adelantada por petición del 18 de noviembre; ver criterios y avance al inicio. Biometría/código nuevo por selección, bloqueo en segundo plano y validación del servidor. Prueba física pendiente. |

### Parte 6 — Beta y mejoras opcionales

| ID | Pri / tamaño | Historia | Dependencias | Criterios y evidencia |
| --- | --- | --- | --- | --- |
| IOS-021 | P1 / M | Como desarrollador, validar cada entrega en CI macOS | IOS-004; requisito de cierre de cada parte posterior | Fijar Xcode/SDK y simulador, compilar, ejecutar Swift Testing/XCUITest y conservar resultados sin datos reales. No subir builds ni desplegar backend automáticamente; no debilitar la CI existente. |
| IOS-022 | P1 / M | Como dueño, instalar actualizaciones por TestFlight | IOS-008, IOS-021; cuenta de pago y autorización de subida | Beta parcial posible desde Parte 1, sólo con funciones entregadas y probadas; beta de facturación añade IOS-010/011 según alcance. Bundle ID/firma del titular, privacidad y export compliance revisados; instalar/actualizar build real y documentar caducidad. Pruebas de preferencias, logout y accesibilidad del alcance; subida no prueba instalación. |
| IOS-023 | P2 / L | Como usuario, recibir avisos de vencimiento | IOS-022; alcance aprobado | Evaluar APNs, backend y consentimiento; texto de bloqueo sin importes/datos sensibles por defecto. Deep link revalida sesión/tenant y nunca ejecuta una escritura. Tests de duplicados, token inválido y permiso denegado. |
| IOS-024 | P2 / L | Como usuario, consultar datos recientes sin red | IOS-012; ADR de caché aprobado | Caché local protegida y aislada por usuario/tenant, fecha de consulta y caducidad visibles; borrado en logout/revocación al reconectar. Sin escrituras ni promesa de saldo actual offline. Tests de TTL, cambio de empresa, reinstalación y reconexión. |
| IOS-025 | P2 / M | Como usuario, sumar captura, widgets o atajos útiles | Partes previas; elegir un solo caso | Definir valor antes de desarrollar. Cámara/importación no presume validez fiscal; widgets ocultan datos sensibles; atajos no evitan permisos ni confirmaciones. Cada función tendrá criterios y pruebas propios antes de entrar al sprint. |

## Reutilización y brechas por validar

Rutas relativas a `/api/v1`; existencia revisada en código, **no compatibilidad
iOS ni servicio productivo verificados**. IOS-007 debe fijar scopes, schemas,
filtros, límites, decimales, errores y completitud de cada lista.

| Capacidad | Fuente existente | Trabajo iOS / brecha |
| --- | --- | --- |
| Contexto y empresas | `backend/app/api/router.py`: `/context`, `/memberships`; `frontend/src/auth.tsx` | Nuevo cliente OIDC público y callback. Validar cómo presentar las membresías antes de cambiar de contexto. |
| Resumen | Web `App.tsx`: consultas `/invoices`, `/receivables`, `/tax/dashboard`; `backend/app/api/tax.py` | No se verificó un resumen único móvil. Evitar sumar listas parciales; propuesta de endpoint agregado sólo si hace falta. |
| Facturas/maestros | `backend/app/api/router.py`: `/invoices`, `/parties`, `/products`, `/invoices/preview` | Vistas nativas, contratos y manejo de red. |
| Documentos | `backend/app/api/router.py`: artefactos y download de factura; `backend/app/api/tax.py`: evidencia | Descarga y limpieza segura; compartir exige gesto humano. |
| Cartera/compras | `backend/app/api/router.py`: `/receivables`; `backend/app/api/payables.py`: `/payables` | Validar relación de compra/evidencia/deuda y scopes; no asumir que compra y CxP son lo mismo. |
| Escrituras | Casos de uso, `execute_idempotent`, auditoría y workers actuales | Reutilizar REST; sin SQL, reglas fiscales o firma en el teléfono. |

## Instalación en el iPhone

1. **Primera prueba con Xcode:** cuenta Apple, teléfono vinculado y Developer
   Mode cuando Apple lo requiera. Personal Team gratuito permite pruebas, pero
   el perfil expira a los 7 días y requiere renovar/reinstalar. No es entrega permanente.
2. **Beta con TestFlight:** requiere Apple Developer Program y App Store Connect;
   cada build se prueba hasta 90 días. Configurar grupo interno o externo según
   titularidad y rol; revisión beta cuando Apple la requiera. No exige publicar
   la app para todo el público.
3. **Distribución duradera:** App Store u otro canal permitido se decide aparte,
   tras revisar uso personal/empresa, costes y reglas de Apple. No se paga una
   membresía ni se publica nada en esta sesión.

## Puertas de revisión

- Antes del código: resolver IOS-001/002 y aceptar la dirección/alcance de ADR
  0022 con revisión de Product ERP. Esto permite crear la app sintética y el PoC
  de pruebas, no habilita acceso productivo. Tras IOS-005, Backend Platform,
  MCP AI Security y QA revisan el PoC antes de abrir el acceso autenticado del piloto.
- Antes de una pantalla nativa: aprobar equivalencias del sistema ERP. React
  `Erp*` no se puede importar en SwiftUI: conservar jerarquía, textos y acciones;
  documentar componentes nativos compartidos y cualquier cambio de posición.
- Antes de escrituras: pruebas de permisos, aislamiento, duplicados, auditoría y
  fallos de red; Product ERP/Backend/QA y Ecuador SRI donde haya efecto fiscal.
- En cada parte: criterios automatizados con datos sintéticos, evidencia de
  build, accesibilidad desde la primera pantalla y demo en teléfono; Carlos
  revisa antes de abrir la parte siguiente. IOS-017/021 se amplían en cada parte.
- Push, PR, merge, configuración productiva de Keycloak, emisión real y subida
  a TestFlight conservan autorización humana propia. Coolify sigue a cargo del
  backend; distribución iOS será un flujo separado propuesto en ADR 0022.

## Próximo trabajo

Cuando Carlos conecte el iPhone, confirmar versión, confianza/Developer Mode y
cuenta/Team; firmar, instalar y revisar la demo para cerrar **IOS-004**.
El build y las pruebas de simulador ya están correctos. El login y clientes
reales entran en la siguiente parte, tras su revisión de esta entrega.

## Revisión de esta propuesta

Product ERP y seguridad/plataforma revisaron el documento de forma independiente.
Se corrigieron las puertas ADR/PoC, el orden de TestFlight y las protecciones
de red y privacidad desde el primer acceso. Sin hallazgos P0/P1 documentales
pendientes al cierre. Enlaces locales, 25 IDs únicos, dependencias sin ciclos y
hashes de los tres skills comprobados. Carlos aceptó después la dirección con
«Empecemos». La validación posterior acredita el simulador; no acredita
instalación en el teléfono físico.

## Fuentes oficiales consultadas

- [Apple: Xcode, SDK y requisitos](https://developer.apple.com/xcode/system-requirements/).
- [Apple: SwiftUI](https://developer.apple.com/swiftui/) y
  [adopción de Liquid Glass](https://developer.apple.com/documentation/technologyoverviews/adopting-liquid-glass).
- [Apple: sesión de autenticación](https://developer.apple.com/documentation/authenticationservices/aswebauthenticationsession).
- [Apple: Swift Testing](https://developer.apple.com/documentation/testing).
- [Apple: red efímera](https://developer.apple.com/documentation/foundation/urlsessionconfiguration/ephemeral)
  y [privacidad al ir a segundo plano](https://developer.apple.com/documentation/uikit/preparing-your-ui-to-run-in-the-background).
- [Apple: cuenta y límites de Personal Team](https://developer.apple.com/help/account/basics/about-your-developer-account/).
- [Apple: TestFlight](https://developer.apple.com/help/app-store-connect/test-a-beta-version/testflight-overview/).

Las versiones y condiciones se deben volver a comprobar al preparar la primera
build. Los skills ayudan a escribir y revisar código; no sustituyen estas fuentes.
