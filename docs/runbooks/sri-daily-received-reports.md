# Descarga diaria de comprobantes recibidos del SRI

Para volver a configurar accesos, cuentas IAERP o perfiles de Chrome, seguir
[`sri-multicompany-recovery.md`](sri-multicompany-recovery.md).

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

1. Ejecutar `node scripts/sri_received_reports_to_iaerp.mjs --all` para todas
   las empresas o `--company=btob` para una sola. El navegador
   visible entra por `SRI en Línea` y abre comprobantes electrónicos recibidos;
   no usa el módulo legado `facturacion-internet` ni un scraper remoto.
2. El ejecutor lee RUC y clave desde un servicio distinto del Llavero de macOS
   por empresa y los escribe en la pantalla oficial sin imprimirlos. También
   usa una cuenta IAERP de servicio y un perfil de navegador separados por
   empresa. No guardar la contraseña en IAERP, `.env` ni el repositorio. Si el
   SRI exige CAPTCHA o MFA, parar y pedir atención humana.
3. Calcular la fecha de ayer y seleccionar su año y mes, con el día en `Todos`.
4. Consultar los cinco tipos, uno por uno, solo para ese mes.
5. Descargar cada reporte que tenga filas.
6. Validar localmente que el receptor de todas las filas de todos los TXT
   coincide con el RUC esperado. Para persona natural se acepta su cédula base
   solo si el RUC es válido y termina en `001`. El lote completo se valida antes
   de la primera subida, así una sesión persistente de otra empresa no guarda
   evidencia cruzada.
7. Antes de subir, llamar el preflight REST autenticado y confirmar que el RUC
   del portal coincide con el tenant fijado por la cuenta IAERP. Un cruce corta
   el flujo sin crear evidencia.
8. Subir cada TXT a `POST /api/v1/tax/evidence` con origen `PORTAL_SRI` y una
   clave idempotente distinta por archivo.
9. Llamar `POST /api/v1/tax/received-reports/process` por REST con los IDs devueltos,
   `reportYear`, `reportMonth` y una clave idempotente estable para ese tenant,
   mes y fecha de ejecución.
10. Mostrar solo conteos por tipo, creados, actualizados, omitidos, preliminares
   y estado del trabajo de recuperación. No registrar RUC, claves de acceso,
   nombres, importes ni el contenido de los TXT.

## Controles

- La API obtiene el tenant del token y exige `tax:write`; REST y MCP llaman el
  mismo caso de uso de procesamiento.
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

La tarea corre solo en este Mac a las 08:00 con `--all`. DATA-CLIP, BTOB SAS y
LEXCODE AUDIT S.A.S. usan cuentas IAERP con `tax:write`, servicios de Llavero y
perfiles de navegador distintos. La corrida real del 31 de agosto de 2026
terminó para las tres empresas: DATA-CLIP listó 468 comprobantes en tres
reportes, BTOB SAS listó 18 en dos reportes y LEXCODE listó cuatro facturas en
un reporte. IAERP encoló la recuperación XML en cada tenant. Una segunda corrida
de LEXCODE conservó las mismas cuatro compras de agosto sin duplicarlas. Si una
empresa falla, la tarea continúa con la otra, termina con error para pedir
atención y no mezcla tenants. Si el SRI agrega CAPTCHA, MFA o cambia el
formulario, la empresa queda en atención.
