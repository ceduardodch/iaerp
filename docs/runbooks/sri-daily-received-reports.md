# Descarga diaria de comprobantes recibidos del SRI

## Objetivo

Ejecutar en el Mac del operador la consulta mensual del portal SRI, subir los
reportes con datos a IAERP y pedir al SRI los XML autorizados. El
navegador y su sesión quedan en el Mac; IAERP no guarda la clave ni las cookies
del portal.

## Periodos y tipos

- Zona fiscal: `America/Guayaquil`.
- Cada día se descarga de nuevo el mes actual completo para recuperar cualquier
  fecha que no corrió porque el Mac estuvo apagado o el portal falló.
- El día 1 también se descarga el mes anterior completo, porque los
  comprobantes del último día pueden aparecer con retraso.
- Tipos: factura, liquidación de compra, nota de crédito, nota de débito y
  comprobante de retención.
- Si un tipo no tiene filas, no se descarga ni se crea evidencia vacía.

## Flujo

1. Abrir en Chrome la consulta de comprobantes electrónicos recibidos.
2. Si la sesión venció, parar y pedir al operador que inicie sesión. No guardar
   la contraseña en IAERP ni en el repositorio.
3. Seleccionar año y mes, con el día en `Todos`.
4. Consultar los cinco tipos, uno por uno, para el mes actual. El día 1 repetir
   los pasos 3 a 7 para el mes anterior.
5. Descargar cada reporte que tenga filas.
6. Subir cada TXT a `POST /api/v1/tax/evidence` con origen `PORTAL_SRI` y una
   clave idempotente distinta por archivo.
7. Llamar `tax.process_received_reports` por MCP con los IDs devueltos,
   `reportYear`, `reportMonth` y una clave idempotente estable para ese tenant,
   mes y fecha de ejecución.
8. Mostrar solo conteos por tipo, creados, actualizados, omitidos, preliminares
   y estado del trabajo de recuperación. No registrar RUC, claves de acceso,
   nombres, importes ni el contenido de los TXT.

## Controles

- El MCP obtiene el tenant del token y exige `tax:write`.
- La escritura exige que el tenant tenga habilitada su política de
  automatización.
- Se aceptan de uno a cinco TXT distintos.
- Todas las filas deben pertenecer al año y mes consultados. Una fila de otro
  mes cancela el lote completo; esto evita importar resultados viejos que el
  portal haya dejado en pantalla.
- La evidencia se deduplica por hash dentro del tenant. Los comprobantes se
  crean o actualizan por la combinación única `tenant_id + access_key`; un XML
  autorizado existente nunca se degrada con datos preliminares del TXT.
- Repetir la misma clave idempotente devuelve el mismo resultado y no duplica
  evidencia, documentos ni trabajos.
- Los XML se recuperan después del commit mediante outbox; una caída del SRI no
  borra la evidencia ya guardada.
- Si aparece CAPTCHA, bloqueo, error de autenticación o cambio del portal, parar
  y avisar. No intentar saltarlo.

## Programación pendiente

Antes de activar la tarea diaria hay que acordar la hora. La tarea debe correr
solo en este Mac, usar una cuenta IAERP de servicio con scopes mínimos y guardar
su secreto en el Llavero de macOS. El portal SRI seguirá usando la sesión de
Chrome; si vence, la tarea queda en atención hasta que el operador vuelva a
iniciar sesión.
