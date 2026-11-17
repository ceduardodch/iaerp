# Descarga SRI en el servidor b2b

El servicio `sri-importer` se publica por Coolify desde `main`. Mantiene un
navegador abierto por empresa y conserva sus perfiles en el volumen
`iaerp-sri-importer-data`. Consulta el mes de ayer a las 08:00 de
`America/Guayaquil`. Si reinicia después de esa hora, recupera la corrida
pendiente y mantiene la idempotencia de la importación.

Las cuatro cuentas técnicas están en
`/home/b2b/services/iaerp-sri-importer/accounts.json`, propietario 1000 y
permisos 0600. El archivo entra al contenedor en modo lectura. Los accesos al
SRI siguen cifrados en la configuración de cada empresa de IAERP.

## Acceso al navegador

El escritorio se publica solo en `127.0.0.1:18229` del servidor y en una red
Docker dedicada. Para abrirlo desde el Mac:

```bash
ssh -N -L 18229:127.0.0.1:18229 b2b-server
```

Abrir `http://127.0.0.1:18229/vnc.html`. El escritorio exige la clave privada
que el servicio genera en `/data/vnc-password` (0600); el administrador puede
consultarla desde la terminal privada de Coolify. No guardarla en URLs,
logs ni capturas. Esta segunda protección se mantiene aunque Coolify añada
el servicio a su red compartida. Cada ventana corresponde a un perfil
separado. La primera sesión o un acceso caducado puede exigir que el operador
complete el login o un CAPTCHA en el SRI.

## Prueba y operación

Desde la terminal del servicio en Coolify:

```bash
node infra/sri-importer/request.mjs btob CHECK_ACCESS
node infra/sri-importer/request.mjs btob DOWNLOAD
node infra/sri-importer/request.mjs all IMPORT
```

`CHECK_ACCESS` toma el acceso guardado en IAERP para iniciar sesión.
`DOWNLOAD` verifica los reportes y sus receptores sin subirlos.
`IMPORT` procesa el lote con las protecciones existentes de IAERP.

Si el SRI pide CAPTCHA durante una consulta, el servicio muestra la ventana
correspondiente y espera hasta diez minutos. El operador resuelve el desafío y
pulsa Consultar. El servicio consume ese resultado y continúa.

El resumen está en `/data/status.json` dentro del servicio. Los errores y los
conteos aparecen en los logs de Coolify. Cada empresa que falle queda en
atención y la corrida continúa con las demás. La cuenta ANA KARINA requiere
guardar su acceso SRI en Empresa, según la verificación del 17 de noviembre.

La automatización del Mac permanece pausada para evitar corridas duplicadas.
