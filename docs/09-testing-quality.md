# Pruebas y calidad

Este documento es la unica fuente canonica de Definition of Done. Otros archivos
deben enlazarla y no copiar una version parcial.

## Piramide

- Unitarias: calculos, estados, politicas, secuencias y parsers.
- Integracion: PostgreSQL, Redis, MinIO, Keycloak y outbox.
- Contrato: OpenAPI, MCP schemas, SRI, email y WhatsApp.
- End-to-end: flujos financieros en web y agente.
- No funcionales: aislamiento, seguridad, carga, resiliencia y restauracion.

## Escenarios obligatorios

### Multi-tenant

- Usuario con dos membresias solo ve el tenant activo.
- Usuario sin membresia recibe 404 y no confirma existencia.
- Worker conserva tenant al procesar outbox.
- Service account no puede cambiar tenant ni scopes.

### Facturacion

- Dos emisiones concurrentes obtienen secuenciales distintos.
- Repetir idempotency key no crea otra factura.
- Clave existente consulta SRI antes de retransmitir.
- Autorizacion tardia actualiza el documento sin duplicarlo.
- Nota de credito referencia factura autorizada y respeta limite.
- Nota de credito sobre factura cobrada crea saldo a favor, no cartera negativa.
- PDF/XML corresponden a los datos persistidos.

### Dinero

- Redondeo y precision en cantidad, precio, descuento, IVA y total.
- Pago parcial y varias aplicaciones.
- Retencion y descuento no producen saldo negativo.
- Reversion conserva trazabilidad.
- Reversion de pago, retencion o descuento crea movimiento compensatorio; no
  edita ni elimina el original.
- Aging usa fecha de vencimiento y zona correcta.
- `OVERDUE` se deriva correctamente al cruzar medianoche local.

### IA/MCP

- Token sin scope no lista ni ejecuta tool.
- Kill switch bloquea escrituras y mantiene consultas.
- Idempotencia funciona entre reintentos del agente.
- Documento con instrucciones maliciosas solo produce datos extraidos.
- Respuesta fuera de esquema se rechaza.
- Limites diarios y por monto bloquean operacion.

### Migracion

- Repetir corrida no duplica.
- Conteos y montos reconcilian.
- Claves duplicadas detienen el tenant afectado.
- Registro pendiente con clave no se reemite.

## CI

GitHub Actions solo ejecutara:

- lint y formato en modo check;
- type checking;
- pruebas unitarias e integracion;
- validacion de migraciones;
- build de backend/frontend;
- OpenAPI y MCP contract tests;
- secret scan, dependency scan y SAST.

No existiran jobs de deploy.

## Cobertura

No se usara una cifra global como unico objetivo. Reglas de dinero, autorizacion,
idempotencia, SRI y aislamiento requieren cobertura de ramas y casos negativos.
Codigo generado y adaptadores triviales se evalua por contrato.

## Definition of Done

- Criterios de aceptacion automatizados.
- Casos negativos y de reintento incluidos.
- Contratos y migraciones actualizados.
- Sin findings criticos o altos sin decision documentada.
- Logs, metricas y alertas para el flujo.
- Revision de seguridad para herramientas de escritura.
- Demostracion en `release`.
