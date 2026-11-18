# Conexión a IAERP y recuperación de borradores — 18 de noviembre de 2026

## Corte de esta evidencia

Carlos pide dejar las conexiones a IAERP listas y avisar cuando pueda instalar
y probar en su iPhone. Este corte registra preparación, pruebas locales y
dependencias aún abiertas. **No declara completada la conexión nativa ni lista
la instalación firmada.** El resultado de una prueba individual tampoco cambia
el estado fallido del bundle que la contiene.

Decisiones: [ADR 0024: conexión y permisos](../../docs/adrs/0024-ios-production-connection-policy.md)
y [ADR 0025: recuperación durable](../../docs/adrs/0025-ios-durable-draft-recovery.md).
Se mantienen la arquitectura nativa y las cuentas guardadas de ADR 0022/0023.

## Conexión y control del acceso

La app tiene precargados estos datos públicos:

| Uso | Valor |
| --- | --- |
| API | `https://iaerp.b2b.com.ec/api/v1` |
| Issuer OIDC | `https://iaerp-auth.b2b.com.ec/realms/iaerp` |
| Cliente nativo | `iaerp-ios` |
| Host de documentos | `iaerp-files.b2b.com.ec` |
| Callback exacto | `ec.com.b2b.iaerp:/oauth2redirect` |

Fuente: `App/Identity/IAERPConnection.swift`. La empresa se elige al entrar; el
tenant y los permisos proceden de la identidad autenticada y de la membresía
del servidor. No hay contraseñas, secretos de cliente ni tokens incluidos en
esta configuración pública.

El cliente `iaerp-ios` fue creado en el servicio de acceso real, **deshabilitado**.
La representación sanitizada observada queda en
`/tmp/iaerp-ios-live-native-disabled.json`: `enabled: false`, callback exacto y
scope `profile`. No confundir registrar el cliente con habilitarlo, autenticar
al usuario, probar la API o instalar la app.

La política backend del cliente nativo limita los scopes al piloto y los cruza
con la membresía activa del tenant en cada request. `invoices:write` se mantiene
sólo para los roles `owner`, `admin` o `billing`; etiquetas ambiguas no conceden
escritura. Claims de cliente contradictorios o audiencia MCP no dan acceso móvil.
La política nueva se aplica al cliente iOS y conserva las reglas de web y de
cuentas de servicio.

Además, las únicas mutaciones admitidas para el piloto son POST de borrador y
POST de preview. El scope heredado de escritura no habilita llamadas directas
para emitir, enviar, anular, archivar o duplicar comprobantes. Las rutas siguen
invocando los mismos casos de uso de IAERP.

El lookup `GET /invoices/draft-requests/{idempotency_key}` devuelve únicamente el
ID de una creación completada del mismo actor y tenant, ligada a un documento
INVOICE existente. Ausente, ajena o no completada responde 404. La clave textual
conserva su caso; no se ofrece un acceso genérico a la tabla ni al payload.

Este backend y su contrato se versionaron en **`eec4b09`**, PR **#107**.
`6b1e832` cambia un hash de fixture sintético para el escáner; su control de
seguridad pasa. La PR #107 pasó el CI completo: 918 pruebas backend correctas (30 omisiones
previas), migraciones, contrato, seguridad, web y OIDC. Se integró en main como
`2bcd013`; CI/Coolify `44314403923` está en curso. El cliente permanece
deshabilitado hasta comprobar el despliegue efectivo de la política.

## Recuperación durable

El journal guarda en Keychain `WhenUnlockedThisDeviceOnly`, sin sincronización,
el UUID de idempotencia y el payload original **antes** del POST. No guarda
credenciales, documentos descargados ni una caché general de negocio.

La identidad financiera incluye issuer, sujeto, organización, tenant y API
canónica. Cambiar UUID de perfil, alias, cliente OIDC o host de archivos no oculta
el pendiente ni permite otra clave. La configuración original completa sigue
siendo obligatoria para reenviar; una configuración modificada sólo puede
conciliar por lookup/GET con la identidad actual revalidada.

Cada recuperación comprueba contexto, membresía, identidad y generación después
de suspender. Lookup/GET requieren consulta; sólo un nuevo POST exige además
escritura vigente. Una respuesta válida persiste su ID antes del GET final.
Se validan los campos de la factura sin recalcular impuestos, se acepta la cuota
por defecto si no se enviaron cuotas y no se exige DRAFT cuando el documento
ya avanzó legítimamente.

El contador de intentos también se persiste antes de la red. Un primer 400/422
definitivo permite corregir; después de incertidumbre, 400/401/403/409 y errores
de red conservan el UUID y payload. Con el TTL declarado de 24 horas, fuera de
23 horas o con el reloj retrocedido no se reenvía sin evidencia autoritativa.
Cancelar, salir, cambiar cuenta o terminar el proceso no descarta la operación.
Nuevo permanece bloqueado hasta confirmar el pendiente; no hay borrado arbitrario.

## Resultados observados

| Validación | Resultado y alcance |
| --- | --- |
| SwiftPM | **80 funciones correctas**: 51 identidad, 24 cliente y 5 demo. `/tmp/iaerp-ios-live-swift-2.log`. |
| AppHost | **41 funciones correctas** en `/tmp/iaerp-ios-live-form-3.log`, incluido acceso nativo a Keychain. El bundle general terminó fallido por la auditoría UI del formulario. |
| Terminación real del proceso | Un test con **tres escenarios correctos**, 40,232 s, en `/tmp/iaerp-ios-live-process-1.xcresult`; log homónimo. El bundle general terminó fallido por el otro test, el formulario. |
| Auditoría de formulario | Sigue abierta en este corte. `form-3` falló; root está ejecutando `form-4`. No se anticipa su resultado. |
| Firma e instalación física | Pendientes del build firmado y de la ejecución en el teléfono. |

La prueba de Keychain falló inicialmente con un host del simulador sin el acceso
necesario. Se corrigieron firma ad hoc y entitlements específicos del simulador;
la prueba se mantuvo y pasó. No se omitió ni se sustituyó por una implementación
en memoria para declarar persistencia nativa.

Las pruebas del journal cubren antes del POST, commit con respuesta perdida,
respuesta antes de confirmación, fallo de persistencia, permisos y membresía
revocados, cambio de identidad, TTL, configuración pública modificada, dos
instancias y conciliación de lectura tras downgrade. Las pruebas unitarias que
recrean objetos se distinguen de la prueba siguiente, que sí termina el proceso.

### Tres terminaciones reales del proceso

`InvoiceRecoveryProcessUITests.testActualTerminationRecoversOneDraftAtEachCommitBoundary`
lanza una superficie diagnóstica exclusiva de Debug del simulador. Usa Keychain
real para el journal y otro servicio Keychain aislado por UUID para el ledger
del **backend sintético**. No construye AuthenticationController, no reemplaza
su control de desbloqueo y no llama a redes reales.

1. **Antes del POST:** la operación ya está persistida y el test termina la app.
2. **Después del commit, sin respuesta:** el ledger sintético ya contiene la
   factura y la respuesta queda suspendida; el test termina la app.
3. **Después de la respuesta:** el journal ya conservó el ID confirmado y el GET
   queda suspendido; el test termina la app.

En cada escenario XCUITest comprueba `notRunning`, relanza, verifica otro PID y
la misma clave previa, pulsa Recuperar y exige exactamente un registro en el
ledger, coincidencia de clave y journal vacío. Retira sólo los servicios Keychain
del UUID de esa prueba. Esto acredita la frontera de proceso y almacenamiento
local; **no acredita el login, commit ni la idempotencia del servidor productivo**.

## Puerta automatizada para activar el cliente

`ios/scripts/configure-native-client.py` exige en `--enable` los SHA256 exactos
de auth, ios_permissions, draft_requests y router bajo `/app`. Comprueba antes
de OAuth y otra vez antes de habilitar; concilia el cliente deshabilitado,
verifica flags/scopes/mappers, habilita al final y vuelve a leer. Una confirmación
final fallida intenta cerrar el cliente y distingue si no puede confirmar ese
cierre. No hay validación basada en `assert` que desaparezca con Python `-O`.

Ocho pruebas persistidas en `ios/scripts/tests/test_configure_native_client.py`
pasan con `backend/.venv/bin/python -B -O -m unittest discover -s ios/scripts/tests -v`.
Usan MockTransport, no credenciales ni llamadas reales. El workflow iOS incluye
un job Ubuntu para esta puerta, con httpx 0.28.1, ya usado por el backend.

Form-4 confirma la geometría de Total/revisión/nota, pero la auditoría nativa
falla por contraste: parte del IVA anterior queda bajo la barra. La revisión
visual detecta que el scroll queda al 99 %. Form-5 comprueba el final real del
scroll, aprovechando el margen de 32 pt, sin filtrar ni omitir hallazgos.
Form-5/6 fallaron por Text clipped sin elemento identificable; Form-7 con
un contenedor GeometryReader no cambió el viewport ni el resultado y se revirtió.
Una comprobación FullScreenCover (Form-8) falló ya en la primera auditoría y se
revirtió. La suite completa local vuelve a ejecutarse con el último diseño
revisado; el fallo sigue abierto. El handler diagnóstico siempre devuelve false
y no excluye hallazgos. Una CI iOS en PR de borrador comparará el runtime 27.2
ya instalado en GitHub, sin descargarlo al Mac.

## Teléfono y límites del cierre

El iPhone está emparejado y conectado por cable, con **iOS 26.0.1**. La sesión
caducada de Apple fue renovada por su titular. El intento de firma posterior ya autentica con Apple, pero falla con
«Your development team has reached the maximum number of registered iPhone
devices». Xcode muestra sólo Personal Team y cuatro dispositivos provisionados.
Se pidió al titular otro equipo/cuenta disponible. No hay app instalada por
estar conectado ni por haber actualizado la sesión.

Pendientes que root debe cerrar y anotar en el corte final:

- CI/merge/despliegue y verificación efectiva de la política backend; sólo entonces
  habilitar el cliente nativo y conservar su representación sanitizada final.
- Resultado final de la auditoría del formulario, sin excluir hallazgos ni limitar
  el tamaño de letra para aprobarla.
- Build firmado, instalación y ejecución en el iPhone; Face ID/código, VoiceOver
  y cambio de cuentas en el dispositivo.
- Login OIDC nativo real, contexto/membresía/roles, lectura de clientes y facturas,
  archivos y recuperación contra el servidor, según el alcance del piloto.

Hasta este corte **no hubo login OIDC nativo real, escritura de negocio desde la
app ni emisión fiscal real**. La creación del cliente deshabilitado es un cambio
de configuración del acceso; no equivale a esas operaciones. No se afirma
«listo para instalar y probar» mientras la firma, la política publicada y los
controles pendientes anteriores no estén verificados.
