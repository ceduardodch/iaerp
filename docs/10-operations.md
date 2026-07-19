# Operaciones

## Ambientes

- Local: datos sinteticos y servicios en contenedores.
- Release: integraciones sandbox/test y datos no productivos.
- Produccion: Coolify desde `main`, SRI produccion y secretos separados.

No se reutilizan bases, buckets, clients OAuth ni credenciales entre ambientes.

## Salud

- `/health/live`: proceso responde.
- `/health/ready`: dependencias indispensables disponibles.
- `/health/startup`: migraciones y configuracion validas.
- MCP publica salud separada sin exponer tools ni metadatos sensibles.

## Observabilidad

- Logs JSON con timestamp, level, service, tenant pseudonimizado, actor,
  correlation ID y event.
- Metricas: latencia, errores, cola, retries, SRI, email/WhatsApp, tool calls,
  bloqueo de politicas y costo IA.
- Trazas entre REST/MCP, caso de uso, outbox, worker y proveedor externo.
- Alertas por errores sostenidos, cola estancada, autorizaciones pendientes,
  fallos de backup y consumo anomalo.

## Backup y restauracion

- PostgreSQL: backup diario y WAL/PITR cuando la infraestructura lo permita.
- MinIO: versionado y replicacion/backup independiente.
- Keycloak: export/configuracion y base respaldada.
- Redis no es fuente de verdad.
- La firma PKCS#12 vive en el bucket privado bajo el prefijo del tenant. Su
  contraseña se cifra con `IAERP_SECRETS_ENCRYPTION_KEY`; rotar esa clave
  exige descifrar y volver a cifrar los secretos antes del cambio.
- RPO objetivo inicial: 24 horas; RTO objetivo: 4 horas.
- Restauracion trimestral en ambiente aislado con evidencia.

Los objetivos se revisan antes de produccion segun criticidad y costo.

## Runbooks

Se prepararan procedimientos para:

- SRI caido o respuesta pendiente.
- Cola detenida o dead-letter creciente.
- Email/WhatsApp rechazado.
- Certificado vencido o comprometido.
- Clave de acceso autorizada pero estado local pendiente.
- Sospecha de fuga entre tenants.
- Agente ejecutando acciones anormales.
- Restauracion y rollback de despliegue/migracion.

## Incidentes

1. Contener: kill switch, revocar tokens o aislar integracion.
2. Preservar evidencia y correlation IDs.
3. Determinar tenants y documentos afectados.
4. Recuperar servicio sin retransmitir efectos desconocidos.
5. Comunicar segun severidad y obligaciones.
6. Crear postmortem con acciones y fechas.

## Despliegue

- CI valida `release` sin desplegarla. Coolify no hace auto-deploy al recibir
  pushes directos; el unico despliegue automatico se solicita desde el job
  protegido de GitHub Actions.
- `main` es la fuente de produccion y dispara el despliegue Coolify una vez que
  todos los jobs de CI terminan correctamente.
- El Environment de GitHub que contiene el token conserva temporalmente el
  nombre historico `staging`; es solo el scope del secreto y no el destino.
- Migraciones se ejecutan como job controlado antes de habilitar nueva version.
- Solo se permite un head Alembic y un job de migracion con lock.
- El rol de migracion es distinto del rol de runtime.
- CI prueba upgrade desde base vacia y desde la version productiva anterior.
- Downgrades destructivos no se ejecutan automaticamente; requieren backup,
  restauracion ensayada y plan compensatorio.
- Cambios incompatibles usan estrategia expand/migrate/contract.
- Rollback de app no revierte automaticamente una migracion destructiva.

## Retencion

Antes del piloto se definiran tiempos legales para comprobantes, auditoria,
mensajes, documentos de proveedor y trazas de IA. La configuracion nunca podra
eliminar evidencia fiscal obligatoria.
