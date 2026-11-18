# iOS 0.2.0: consultas y borradores locales

Corte del 17 de noviembre de 2026, America/Guayaquil. Continúa la
[Parte 0](2026-11-17.md) por pedido de Carlos de avanzar mientras conecta el
teléfono después. No acredita una instalación física ni habilitación real.

## Alcance preparado

- SwiftUI: bienvenida, Clientes, Facturas y Cuenta; fichas y empresa.
- OIDC/AppAuth, perfil y tokens en Keychain, restauración explícita,
  refresh compartido y salida con aviso de fallos.
- REST tipado, Decimal exacto y respuestas tardías aisladas por sesión.
- Cliente/producto, preview, plazo cliente → empresa → contado, vencimiento
  de Guayaquil y guardado idempotente de borrador dentro del mismo proceso.
- Facturas con estados SRI y cobro separados; PDFKit, XML como texto y compartir
  por acción humana. Temporales protegidos, excluidos de backup y purgados.
- Dos empresas sintéticas y acceso de consulta; cinco estados documentales.

La demo usa cantidades 1, 2 o 3, precios originales y descuento cero. Sus
previews son tablas fijas de datos ficticios; no reemplazan cálculos fiscales
del servidor. Los borradores demo desaparecen al salir/cambiar de empresa.
No existe una acción de emitir al SRI.

## Entorno y dependencias

Xcode 27.2 (27B52), SDK 27.2, Swift 6 con concurrencia completa y UI MainActor.
Mínimo iOS 26 provisional. Un único simulador propio iPhone 14/iOS 26.5
(23F77), ID `9E0D1622-65DF-40B0-86B8-C9D81F560A29`.
Se reutilizó el runtime existente; no se descargó otro.

AppAuth iOS 3.0.0 es la única dependencia externa. Revisión fijada:
`a972daac82d449d58ab119e91c68153e29ddac33`. Licencia y atribución incluidas.
Sin CocoaPods ni base de negocio local. Perfil/tokens usan Keychain
`WhenUnlockedThisDeviceOnly`; un fallo de borrado se informa y no se presenta
como credenciales eliminadas.

## Pruebas y compilación

El corte final **Tests-39 no está completamente verde**: **58 pruebas SwiftPM**
y **17 pruebas de app** correctas; **13 de 14 recorridos UI correctos**, sin
omisiones. Xcode resume 30/31 pruebas nativas agrupadas correctas. Falla
`testInvoiceFormAndDetailAccessibilityAtLargestTextSize` por **Contrast failed**
al auditar los totales con texto máximo. **IOS-017 sigue abierto**; requiere
resolver el hallazgo y comprobar el dispositivo. No se atribuye a un defecto
concreto del SDK sin demostrarlo.

La ejecución anterior Tests-28 pasó íntegra (31 pruebas nativas agrupadas,
59 casos efectivos), pero no sustituye la validación del árbol actual. Los
intentos posteriores y sus fallos se conservan como tales. El helper exige
frame completo y gestos cortos desde el margen; QA confirmó que refuerza la
intención conforme a COORDINACION_IA §5(b). No hay handlers ni exclusiones en
las auditorías de Workspace.

| Control | Evidencia |
| --- | --- |
| Modelos, REST y contratos sintéticos | 21 pruebas; Decimal JSON desde texto, dos empresas, errores, 401 limitado, POST sin repetición automática, clave/payload estables, descargas/host/SHA256. |
| Identidad | 32 pruebas; URLs/callback/issuer/audience/organización, cancelación, restauración, refresh concurrente/tardío y logout. |
| Demo inicial | Cinco pruebas, ocho casos; búsqueda y aislamiento del fixture. |
| AppHost | 17 pruebas; plazo y cuota exacta, calendario Guayaquil, preview obsoleto, respuestas fuera de orden, commit perdido → 403 → recuperación, logout y documentos. |
| UI | 14 recorridos implementados; 13 correctos y una auditoría pendiente: crear/guardar/reabrir, cancelar, búsqueda, consulta, dos empresas/logout, PDF/XML, configuración inválida, modo oscuro y accesibilidad. |
| Auditoría nativa | Todos los tipos, sin exclusiones. Raíces, Cliente, Empresa y selectores probados; el recorrido de formulario/totales/factura con texto máximo sigue abierto por contraste. |
| Build iPhoneOS | Build Debug arm64 correcto, sin firma, bundle 0.2.0 (2), mínimo iOS 26. No prueba instalación. |
| CI remota | Workflow preparado; no ejecutado, sin push ni gasto de runner. |

Pruebas de integración usan transportes/proveedores controlados y datos
sintéticos. No sustituyen Keycloak/API/base/SRI reales.

## Privacidad con documento abierto

Se abrió un RIDE ficticio y se entró al selector real de apps. La jerarquía
confirma `AppSwitcherContentView` y la tarjeta de IAERP; la captura muestra
fondo opaco y sólo «IAERP», sin el documento. QA y seguridad inspeccionaron
esa captura; UI/UX revisó las pantallas y el formulario.

El test comprueba la tarjeta y su uniformidad interior, fuera de los márgenes
y la banda del rótulo central. Un control negativo desactivó temporalmente el
escudo: falló exactamente en la aserción prevista, **4679 píxeles distintos
frente a 0**. La fuente original se restauró byte por byte en `finally` antes
de la suite completa. No queda un bypass en la app.

Esta evidencia cubre el PDF y el simulador probados; no demuestra todos los
contenidos/apariencias ni el teléfono físico.

## Correcciones verificadas

Se corrigieron el plazo que se reiniciaba al volver del selector, el teclado
numérico sin cierre claro y la conservación de una operación incierta tras
un 403. El preview tardío ya libera su estado sin publicar totales viejos.

La auditoría encontró contraste en búsquedas, footers, acciones deshabilitadas
y contenido bajo materiales de barras. Se usan búsqueda/conteos compartidos,
fuentes semánticas y colores adaptativos. Formulario y acciones tienen áreas
separadas; las fichas usan barras opacas, ocultan las pestañas y recuperan la
navegación al volver. No se limitaron fuentes ni se excluyeron hallazgos.

Se observó ejecución de un test anterior tras reinstalaciones incrementales.
El script retira sólo el runner de pruebas de esta app antes de ejecutar.
Los frameworks SPM del simulador se compilan en `/tmp`: en Documentos el
cargador se detenía antes de arrancar. No se cambió el `xcode-select` global.

Los intentos fallidos/interrumpidos se conservan en logs y no se cuentan como
aprobados. El SDK emite avisos de UIKit/XCTest durante algunos recorridos;
no se ocultaron. El resultado del auditor y los fallos de pruebas se registran
por separado de esos avisos.

## Puertas que siguen abiertas

**QA local:** resolver la auditoría automática del formulario a texto máximo
y repetir el recorrido físico. El build y la demo para revisión no equivalen
a una entrega de calidad cerrada.

1. **P1: permisos por empresa.** El realm/backend versionados conceden el scope
   de escritura sin cruzarlo con roles de membresía. La plantilla de cliente
   queda `enabled: false`. Probar dos roles y dos tenants, incluido el mismo
   usuario con permisos distintos, POST directo, revocación y reducción de permisos.
   No se verificó ni modificó la política desplegada.
2. **P1: recuperación tras terminar el proceso.** Clave/payload pendientes viven
   en memoria. Antes de escrituras reales, decidir el registro durable conforme
   al ADR y probar recuperación/reconciliación que deje un único documento.
3. PoC real de acceso/contratos/documentos y emisión SRI sandbox aparte. No se
   importó el cliente ni se inició sesión. Sólo se consultó discovery OIDC público
   para verificar issuer, endpoints HTTPS y PKCE S256.
4. Versión exacta del teléfono, Team, firma, confianza/Developer Mode e instalación.
   CoreDevice sólo detectó el simulador al consultar. VoiceOver manual y revisión
   horizontal/física pendientes.
5. TestFlight, publicación y módulos posteriores requieren su propia revisión.

[Backlog y criterios](../../docs/backlog/ios-backlog.md) ·
[Preparación del piloto](../configuration/README.md) ·
[ADR 0022](../../docs/adrs/0022-native-ios-client.md).

## Artefactos y reproducción

[Script y guía](../README.md). Resultados temporales fuera de Git, sujetos a
caducidad de `/tmp`:

- `/tmp/iaerp-workspace-validation/tests-39.log` y `Tests-39.xcresult`: corte final.
- `summary-39.json`: 30/31 agrupadas, un fallo de contraste y cero omisiones.
- `tests-28.log`: antecedente verde de un corte previo; no es el cierre actual.
- `privacy-negative.log`: fallo esperado del control negativo.
- `iphoneos-final-build.log`: compilación arm64 sin firma.

[SHA256 de las entradas de código/proyecto](2026-11-17-source-sha256.txt)
identifica el árbol local, que aún no tiene commit. Se comprueba desde la raíz
con `shasum -a 256 -c ios/validation/2026-11-17-source-sha256.txt`.

Capturas sintéticas del corte final: [Clientes](screenshots/2026-11-17/clientes.png),
[RIDE demo](screenshots/2026-11-17/ride-demo.png),
[selector protegido](screenshots/2026-11-17/privacidad.png) y
[formulario con auditoría pendiente](screenshots/2026-11-17/formulario-auditoria-pendiente.png).

Se limpiaron bundles/exports de intentos anteriores y cachés de compilación
que ya no se usaban. Quedaron unos 20,1 GiB libres; caché activa 452 MiB,
SwiftPM 190 MiB y resultados/logs 97 MiB. Se conserva el resultado final, logs y pocas capturas sintéticas;
no se instalan runtimes ni herramientas extra para este cierre.

Sin producción, commit, push, PR, merge, distribución ni cambios de backend/web.
Los cambios previos de avisos y scripts SRI quedan fuera.
