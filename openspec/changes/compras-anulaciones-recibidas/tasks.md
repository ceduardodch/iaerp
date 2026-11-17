## 1. Dominio y respaldo

- [x] 1.1 Definir el estado de anulación y su respaldo sin borrar el original.
- [x] 1.2 Crear caso de uso, API y auditoría con permiso, tenant e idempotencia.
- [x] 1.3 Proteger períodos declarados, pagos, retenciones y notas de crédito.
- [x] 1.4 Excluir anuladas de deuda vigente y reportes abiertos.

## 2. Interfaz y calidad

- [x] 2.1 Añadir acción de registro, confirmación y estado visible en Compras.
- [x] 2.2 Cubrir aceptación con pruebas de integración, contrato, interfaz y accesibilidad.
- [x] 2.3 Revisar dominio fiscal, seguridad y plataforma con expertos independientes.
- [x] 2.4 Publicar por release → PR → main y verificar el entorno publicado.

## Evidencia

Solicitud del usuario del 17 de noviembre de 2026. La captura identifica una compra que el usuario informa anulada; no constituye por sí misma respaldo del estado SRI. No se cambiará esa compra por una inferencia de la imagen.

Validación local: 28 pruebas dirigidas PostgreSQL 15, 10 E2E nuevos y 36 regresiones Compras/dashboard; accesibilidad y geometría escritorio/móvil. Migración upgrade, downgrade y upgrade en PostgreSQL 15. Ruff y mypy correctos. Revisiones independientes fiscal y seguridad GO. Suite general verificada: 867 correctas, 30 omisiones previas; la prueba de salud pasó después de iniciar Redis local (868 en total). Publicación pendiente.

## Revisión ERP antes de publicar

PR #101 quedó integrado en `7b09469`, pero la corrida main `44157431870` se
canceló antes del despliegue por un P1 de revisión ERP: una factura anulada no
prueba por sí sola que se extinguieron la operación, deuda y gasto reales.
El ajuste exige `economicOutcome=OPERATION_CANCELLED`, una confirmación
separada en pantalla y su auditoría. Ausencia, compra vigente y reemplazo se
rechazan sin cambios. 31 pruebas dirigidas PostgreSQL pasan tras el ajuste.
La producción sigue en `1444bdd`; la factura del ejemplo sigue intacta.

P1 cerrado tras revisión ERP independiente y seguridad/contrato: doble confirmación, petición obligatoria y respuesta coherente. POST y GET reales devuelven la decisión económica. 31 PostgreSQL y 14 E2E correctos; Ruff, mypy, build, teclado, axe y geometría móvil pasan. Publicación aún pendiente.

Publicación verificada de la función: PR #101/#102 en `b586aeb`,
CI/Coolify `44161725575` correctos; contrato obligatorio, API, paquete web,
migración y MCP autenticado verificados. 871 backend y 412 E2E correctos
(30/4 omisiones previas). La función sólo admite operación cancelada y saldo
extinguido; no se aplicó a la factura real. El arreglo del reinicio SRI sigue
las tareas del cambio `compras-sri-reglas-mcp`.

## Aplicación al caso indicado

El usuario confirmó que también se canceló la compra. La decisión económica
ya está aclarada y corresponde a OPERATION_CANCELLED. Falta adjuntar el
respaldo SRI y registrar la acción desde una sesión humana autorizada; no se
ha modificado la compra productiva del ejemplo.

## Publicación verificada

PR #101/#102, revisión `fb0537e`, [CI/Coolify](https://github.com/ceduardodch/iaerp/actions/runs/44169331013) correctos. API, contrato obligatorio de decisión económica, paquete web, migración, perfiles SRI y MCP autenticado verificados. 871 backend y 412 E2E correctos (30/4 omisiones previas). Alcance publicado sólo para operación cancelada; factura real no modificada y registro real pendiente de respaldo SRI; el usuario ya confirmó la compra cancelada.

- [x] 3.1 Confirmar que también se canceló la compra: confirmado por el usuario.
- [ ] 3.2 Adjuntar el respaldo del estado SRI y su fecha efectiva.
- [ ] 3.3 Revisar cierres y movimientos, registrar desde la sesión humana autorizada si procede y comprobar el resultado.

## 4. Acceso directo desde la fila

- [x] 4.1 Mostrar `Anular` bajo el número de la compra, sin entrar en `Pagar`.
- [x] 4.2 Reutilizar permisos, modal, respaldo y protecciones; conservar borrador al cancelar y cerrar edición al guardar.
- [x] 4.3 Automatizar escritorio/móvil, teclado, foco, permisos y regresiones: 18 E2E dirigidos y 36 regresiones Compras/dashboard pasan; build/lint correctos. Revisión frontend/a11y independiente GO, incluido objetivo táctil de 44×44 px.
- [ ] 4.4 Revisión independiente y publicación por release → PR → main con verificación del paquete servido.

Validación PR #105: release `44176683958` pasó 416 E2E; el PR detectó
una carrera en una aserción de revisión móvil existente. Se espera la petición
asíncrona con `expect.poll` conservando los cuatro campos y la aserción de foco.
20 repeticiones dirigidas (10 por tamaño) pasan; se repite CI completo.
