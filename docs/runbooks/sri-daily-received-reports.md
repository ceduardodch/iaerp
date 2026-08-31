# Descarga diaria de comprobantes recibidos del SRI

## Objetivo

Ejecutar en el Mac del operador la consulta mensual del portal SRI, subir los
reportes con datos a IAERP y pedir al SRI los XML autorizados. El
navegador y su sesión quedan en el Mac; IAERP no guarda la clave ni las cookies
del portal.

## Periodos y tipos

- Zona fiscal: `America/Guayaquil`.
- Cada día se calcula la fecha de ayer y se descarga de nuevo, con el día en
  `Todos`, el mes completo al que pertenece ayer. Así se recupera cualquier
  fecha que no corrió porque el Mac estuvo apagado o el portal falló.
- El día 1 se consulta solo el mes anterior, no dos meses. Por ejemplo, el 1 de
  septiembre se vuelve a descargar agosto completo porque los comprobantes del
  31 de agosto aparecen al día siguiente. El 2 de septiembre ya se descarga
  septiembre completo.
- Tipos: factura, liquidación de compra, nota de crédito, nota de débito y
  comprobante de retención.
- Si un tipo no tiene filas, no se descarga ni se crea evidencia vacía.

## Flujo

1. Ejecutar `node scripts/sri_received_reports_to_iaerp.mjs`. El navegador
   visible entra por `SRI en Línea` y abre comprobantes electrónicos recibidos;
   no usa el módulo legado `facturacion-internet` ni un scraper remoto.
2. El ejecutor lee RUC y clave desde el servicio `IAERP SRI Portal` del Llavero
   de macOS y los escribe en la pantalla oficial sin imprimirlos. No guardar la
   contraseña en IAERP, `.env` ni el repositorio. Si el SRI exige CAPTCHA o
   MFA, parar y pedir atención humana.
3. Calcular la fecha de ayer y seleccionar su año y mes, con el día en `Todos`.
4. Consultar los cinco tipos, uno por uno, solo para ese mes.
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

## Programación local

La tarea corre solo en este Mac a las 08:00, usa una cuenta IAERP de servicio
con `tax:write` y guarda ambos accesos en el Llavero de macOS. La corrida real
del 31 de agosto de 2026 importó tres reportes con filas y encoló la recuperación
XML sin intervención. Si el SRI agrega CAPTCHA, MFA o cambia el formulario, la
tarea queda en atención.
