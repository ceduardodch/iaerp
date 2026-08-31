# Recuperación de la automatización SRI multiempresa

## Cuándo usar este runbook

Usar este procedimiento si cambia una clave del SRI, vence o se revoca una
cuenta IAERP, se daña un perfil de Chrome, cambia el Mac o la tarea diaria deja
de entrar. No guardar RUC, contraseñas, `client_id`, `client_secret`, cookies ni
reportes fiscales en Git, `.env`, tickets, capturas o chats.

La fuente de verdad de las empresas está en
`scripts/sri_received_companies.mjs`. Cada empresa debe tener cuatro secretos y
un perfil de navegador propios. El token de la cuenta IAERP fija el tenant; el
script nunca toma el tenant desde el RUC escrito en el portal.

## Mapa de configuración

| Empresa | Servicio del Llavero | Cuenta | Valor guardado |
| --- | --- | --- | --- |
| DATA-CLIP | `IAERP SRI Portal` | `ruc` | Usuario RUC del portal |
| DATA-CLIP | `IAERP SRI Portal` | `password` | Clave del portal |
| DATA-CLIP | `IAERP SRI Daily Import` | `client_id` | ID de la cuenta IAERP |
| DATA-CLIP | `IAERP SRI Daily Import` | `client_secret` | Secreto de la cuenta IAERP |
| BTOB SAS | `IAERP SRI Portal BTOB` | `ruc` | Usuario RUC del portal |
| BTOB SAS | `IAERP SRI Portal BTOB` | `password` | Clave del portal |
| BTOB SAS | `IAERP SRI Daily Import BTOB` | `client_id` | ID de la cuenta IAERP |
| BTOB SAS | `IAERP SRI Daily Import BTOB` | `client_secret` | Secreto de la cuenta IAERP |

Perfiles persistentes, fuera del repositorio:

- DATA-CLIP: `~/Library/Application Support/IAERP/sri-browser-profile`
- BTOB SAS: `~/Library/Application Support/IAERP/sri-browser-profile-btob`

La tarea local `SRI recibidos a IAERP` ejecuta todos los días a las 08:00:

```bash
node scripts/sri_received_reports_to_iaerp.mjs --all
```

## Cambiar RUC o clave del SRI

1. Pausar `SRI recibidos a IAERP` desde Automations en Codex.
2. Abrir **Acceso a Llaveros** en el Mac.
3. Buscar el servicio exacto de la empresa en la tabla anterior.
4. Editar la entrada `ruc` o `password`. El campo secreto de la entrada `ruc`
   contiene el RUC usado como usuario; no crear una cuenta llamada `username`.
5. Guardar y cerrar Acceso a Llaveros.
6. Probar solo esa empresa con el comando de la sección de validación.
7. Reactivar la tarea únicamente después de una prueba correcta.

Se puede confirmar que una entrada existe sin mostrar su valor:

```bash
/usr/bin/security find-generic-password -s "IAERP SRI Portal BTOB" -a ruc >/dev/null && echo "RUC configurado"
/usr/bin/security find-generic-password -s "IAERP SRI Portal BTOB" -a password >/dev/null && echo "Clave configurada"
```

Cambiar el nombre del servicio o de la cuenta exige actualizar también
`scripts/sri_received_companies.mjs` y sus pruebas.

## Reemitir una cuenta IAERP

1. Entrar a IAERP con un usuario que pueda administrar cuentas de servicio.
2. Cambiar a la organización correcta y confirmar su nombre antes de crear la
   cuenta. Nunca crear la cuenta mientras está activo el otro tenant.
3. Crear una cuenta con nombre claro, vencimiento definido y solo el scope
   `tax:write`.
4. Confirmar que las escrituras automáticas están habilitadas para ese tenant.
5. Guardar el `client_id` y el `client_secret` que IAERP muestra una sola vez en
   las dos entradas del Llavero indicadas en la tabla. No imprimirlos para
   probarlos.
6. Revocar la cuenta anterior después de que la nueva pase la prueba individual.

Si no existe una pantalla administrativa para emitirla, usar el endpoint
autenticado `POST /api/v1/service-accounts` con un usuario del tenant que tenga
`service-accounts:write`. El cuerpo debe contener `name`, `scopes:
["tax:write"]` y `expiresAt`; la petición exige `Idempotency-Key`. No usar el
administrador de Keycloak para saltarse IAERP: IAERP debe registrar, limitar y
auditar la cuenta.

## Recuperar un perfil de navegador

Primero cerrar la ventana de Chrome abierta por el ejecutor. Si el perfil quedó
bloqueado o corrupto, renombrar su carpeta exacta a una copia de respaldo desde
Finder; no borrar toda la carpeta `IAERP`. La siguiente corrida crea un perfil
nuevo. El script escribe RUC y clave desde el Llavero, así que una sesión previa
del portal no es requisito.

Mantener un perfil distinto por empresa. Reusar el mismo perfil permite que
Chrome restaure el acceso de la otra empresa. El ejecutor borra, fija y verifica
los campos RUC y clave justo antes de enviar el formulario para evitar ese
cruce.

## Validación antes de reactivar

Desde la raíz del proyecto:

```bash
node --check scripts/sri_received_reports_to_iaerp.mjs
node --test scripts/tests/sri_received_companies.test.mjs
node scripts/sri_received_reports_to_iaerp.mjs --company=data-clip
node scripts/sri_received_reports_to_iaerp.mjs --company=btob
node scripts/sri_received_reports_to_iaerp.mjs --all
```

Las pruebas reales son idempotentes: IAERP deduplica evidencia por tenant y
hash, y comprobantes por tenant y clave de acceso. Aun así, revisar el resumen
seguro de cada empresa: periodo, reportes, filas, tipos, creados, actualizados,
omitidos, preliminares y estado de recuperación. Nunca comparar mostrando los
documentos o secretos en consola.

## Diagnóstico rápido

| Error | Acción |
| --- | --- |
| `KEYCHAIN_CONFIGURATION_MISSING_*` | Revisar servicio y cuenta exactos en el Llavero. |
| `SRI_CREDENTIAL_FIELD_MISMATCH` | Cerrar Chrome, revisar el perfil de esa empresa y repetir. |
| `SRI_AUTHENTICATION_REJECTED` | Probar RUC y clave manualmente; luego corregir solo esa entrada del Llavero. |
| `SRI_CAPTCHA_REQUIRED` | Detener esa empresa y completar la revisión humana; no intentar saltarla. |
| `SRI_MFA_REQUIRED` | Completar o redefinir el segundo factor con el dueño de la cuenta. |
| `STAGE_iaerp-token` | Revisar vigencia, revocación y Llavero de la cuenta IAERP. |
| `STAGE_iaerp-evidence-*` | Confirmar API, scope `tax:write` y política de automatización del tenant. |
| `STAGE_iaerp-process` | Revisar el lote y los eventos de IAERP sin volver a cargarlo a otro tenant. |

Si falla una empresa con `--all`, la otra continúa y el proceso termina con
error para pedir atención. Corregir y probar primero con `--company`; no cambiar
las credenciales de ambas empresas a la vez.
