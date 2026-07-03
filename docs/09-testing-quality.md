# Pruebas y calidad

Este documento es la unica fuente canonica de Definition of Done. Otros archivos
deben enlazarla y no copiar una version parcial.

## Piramide

- Unitarias: calculos, estados, politicas, secuencias y parsers.
- Integracion: PostgreSQL, Redis, MinIO, Keycloak y outbox.
- Contrato: OpenAPI, MCP schemas, SRI, email y WhatsApp.
- End-to-end: flujos financieros en web y agente.
- No funcionales: aislamiento, seguridad, carga, resiliencia y restauracion.

## Datos de prueba

Las pruebas deben usar datos sinteticos, deterministas y versionados. No se
copiaran bases productivas, XML reales, certificados, correos, telefonos ni
documentos con datos personales.

Se mantendran tres capas de datos:

- Builders y factories unitarias: crean entidades minimas en memoria y permiten
  declarar solo las diferencias relevantes para cada escenario.
- Seeds de integracion: levantan dos tenants ficticios, usuarios multi-tenant,
  establecimientos, puntos de emision, parties, productos, impuestos, tags y
  estados financieros conocidos.
- Fixtures de contrato/E2E: XML, respuestas SRI, PDF, emails y mensajes
  sanitizados, con checksums y resultados esperados.

El dataset base debe incluir:

- tenant A y tenant B con RUC ficticios validos y datos que permitan detectar
  fugas entre tenants;
- owner, operador, consulta y service account con scopes distintos;
- un usuario perteneciente a ambos tenants y otro sin membresia;
- establecimientos y puntos con secuencias independientes;
- parties duplicables y no duplicables por tipo/identificacion;
- productos gravados, tarifa cero, descuentos y cantidades decimales;
- facturas autorizada, pendiente, rechazada y con autorizacion tardia;
- cuentas por cobrar/pagar vigentes, vencidas, parciales y saldadas;
- documentos maliciosos para prompt injection y archivos invalidos.

Cada seed sera idempotente y tendra una version. Las pruebas deben crear y
destruir su propio estado o ejecutarse dentro de transacciones aisladas; no
dependeran del orden ni de datos creados manualmente.

## Niveles obligatorios por cambio

| Tipo de cambio | Unitarias | Integracion | Contrato | E2E |
| --- | --- | --- | --- | --- |
| Regla de dominio/calculo | Obligatoria | Si persiste o publica | Si cambia interfaz | Flujo critico |
| Repository/migracion | Casos de borde | Obligatoria con PostgreSQL real | No aplica | Segun flujo |
| Endpoint REST | Casos de uso | Obligatoria con auth y DB | OpenAPI obligatoria | Flujo principal |
| Tool MCP | Casos de uso/politica | Obligatoria con OAuth y DB | Schema MCP obligatorio | Escrituras criticas |
| Worker/outbox | Reintentos/estados | Obligatoria con Redis y DB | Evento obligatorio | Flujo asincrono critico |
| UI | Estado y validacion | API mock/real segun capa | Tipos generados | Flujo principal y a11y |
| Adaptador externo | Parseo y errores | Sandbox o simulador | Fixture versionada | Smoke controlado |

Las pruebas unitarias no deben requerir red, Docker ni reloj real. Las pruebas
de integracion deben usar los mismos motores y versiones mayores que produccion;
SQLite no sustituye PostgreSQL para restricciones, concurrencia o migraciones.

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

La CI separara suites rapidas y completas:

- En cada PR: lint, tipos, unitarias, integracion, contratos, migraciones y build.
- En `release`: lo anterior mas E2E, accesibilidad y smoke del stack completo.
- Antes de promover a `main`: regresion funcional, seguridad y evidencia de los
  criterios del sprint; Coolify sigue siendo el unico responsable del deploy.

Los reportes JUnit, cobertura, trazas y capturas de fallos se conservaran como
artefactos de CI sin incluir secretos ni datos personales.

## Cobertura

No se usara una cifra global como unico objetivo. Reglas de dinero, autorizacion,
idempotencia, SRI y aislamiento requieren cobertura de ramas y casos negativos.
Codigo generado y adaptadores triviales se evalua por contrato.

Como umbral inicial, el codigo de dominio y casos de uso nuevos debe mantener al
menos 80% de lineas y 75% de ramas. Este umbral no reemplaza los escenarios
obligatorios ni permite excluir codigo critico para mejorar la cifra.

## Definition of Done

- Criterios de aceptacion automatizados.
- Datos de prueba sinteticos, deterministas y documentados.
- Pruebas unitarias para reglas y casos de uso modificados.
- Pruebas de integracion para persistencia, autenticacion, colas y adaptadores.
- Prueba E2E para todo flujo de negocio nuevo o modificado.
- Casos negativos y de reintento incluidos.
- Contratos y migraciones actualizados.
- Sin findings criticos o altos sin decision documentada.
- Logs, metricas y alertas para el flujo.
- Revision de seguridad para herramientas de escritura.
- Demostracion en `release`.
