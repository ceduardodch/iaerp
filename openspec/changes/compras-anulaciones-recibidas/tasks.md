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
