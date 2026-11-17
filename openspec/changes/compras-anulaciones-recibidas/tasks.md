## 1. Dominio y respaldo

- [x] 1.1 Definir el estado de anulación y su respaldo sin borrar el original.
- [x] 1.2 Crear caso de uso, API y auditoría con permiso, tenant e idempotencia.
- [x] 1.3 Proteger períodos declarados, pagos, retenciones y notas de crédito.
- [x] 1.4 Excluir anuladas de deuda vigente y reportes abiertos.

## 2. Interfaz y calidad

- [x] 2.1 Añadir acción de registro, confirmación y estado visible en Compras.
- [x] 2.2 Cubrir aceptación con pruebas de integración, contrato, interfaz y accesibilidad.
- [x] 2.3 Revisar dominio fiscal, seguridad y plataforma con expertos independientes.
- [ ] 2.4 Publicar por release → PR → main y verificar el entorno publicado.

## Evidencia

Solicitud del usuario del 17 de noviembre de 2026. La captura identifica una compra que el usuario informa anulada; no constituye por sí misma respaldo del estado SRI. No se cambiará esa compra por una inferencia de la imagen.

Validación local: 28 pruebas dirigidas PostgreSQL 15, 10 E2E nuevos y 36 regresiones Compras/dashboard; accesibilidad y geometría escritorio/móvil. Migración upgrade, downgrade y upgrade en PostgreSQL 15. Ruff y mypy correctos. Revisiones independientes fiscal y seguridad GO. Suite general verificada: 867 correctas, 30 omisiones previas; la prueba de salud pasó después de iniciar Redis local (868 en total). Publicación pendiente.
