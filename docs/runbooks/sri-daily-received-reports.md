# Descarga diaria de comprobantes recibidos del SRI

## Objetivo

Ejecutar en el Mac del operador la consulta del portal SRI para el día anterior,
subir los reportes con datos a IAERP y pedir al SRI los XML autorizados. El
navegador y su sesión quedan en el Mac; IAERP no guarda la clave ni las cookies
del portal.

## Fecha y tipos

- Zona fiscal: `America/Guayaquil`.
- Fecha de consulta: ayer, nunca hoy.
- Tipos: factura, liquidación de compra, nota de crédito, nota de débito y
  comprobante de retención.
- Si un tipo no tiene filas, no se descarga ni se crea evidencia vacía.

## Flujo

1. Abrir en Chrome la consulta de comprobantes electrónicos recibidos.
2. Si la sesión venció, parar y pedir al operador que inicie sesión. No guardar
   la contraseña en IAERP ni en el repositorio.
3. Seleccionar año, mes y día de ayer.
4. Consultar los cinco tipos, uno por uno.
5. Descargar cada reporte que tenga filas.
6. Subir cada TXT a `POST /api/v1/tax/evidence` con origen `PORTAL_SRI` y una
   clave idempotente distinta por archivo.
7. Llamar `tax.process_received_reports` por MCP con los IDs devueltos, la fecha
   consultada y una clave idempotente estable para ese tenant y día.
8. Mostrar solo conteos por tipo, creados, actualizados, omitidos, preliminares
   y estado del trabajo de recuperación. No registrar RUC, claves de acceso,
   nombres, importes ni el contenido de los TXT.

## Controles

- El MCP obtiene el tenant del token y exige `tax:write`.
- La escritura exige que el tenant tenga habilitada su política de
  automatización.
- Se aceptan de uno a cinco TXT distintos.
- Todas las filas deben tener la fecha consultada. Una fila de otro día cancela
  el lote completo.
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
