# Roadmap

Sprints de dos semanas, equipo de 2-3 personas. Cada sprint entrega una porcion
vertical demostrable en `release`.

## Sprint 0 - Definicion y contratos

- Repositorio, gobernanza y documentacion.
- TAM/SAM/SOM, alcance, dominio y threat model.
- ADR y contratos preliminares REST/MCP.
- Backlog priorizado y Definition of Done.

Salida: documentos aprobados y riesgos criticos con responsable.

## Sprint 1 - Plataforma y maestros

- Keycloak, tenant, membresias, roles y service accounts.
- Auditoria, idempotencia, politicas y kill switch.
- Establecimientos, puntos, parties, productos, impuestos y tags.
- PostgreSQL/Alembic, Redis, MinIO y CI.
- Primeras tools MCP de contexto y busqueda.
- Dataset sintetico multi-tenant y pruebas unitarias, integracion REST/MCP/worker
  y E2E de login, cambio de tenant y maestros.

Salida: dos tenants demuestran aislamiento en REST y MCP.

## Sprint 2 - Facturacion

- Factura y nota de credito.
- Secuencia atomica, calculos, firma, XML, PDF y almacenamiento.
- Recepcion, autorizacion, reconciliacion y reintentos SRI.
- Tools MCP de borrador, emision y consulta.
- Vectores fiscales versionados, simulador SRI y pruebas unitarias de calculo,
  integracion concurrente y E2E de factura/nota de credito.

Salida: ciclo completo en ambiente de pruebas SRI sin duplicados.

## Sprint 3 - Cuentas por cobrar

- Receivables, cuotas, pagos, retenciones, descuentos y aplicaciones.
- Aging, saldos y alertas.
- Email y WhatsApp con plantillas y tracking.
- Tools de cartera, cobro y recordatorio.
- Dataset de cartera con vencimientos y aplicaciones parciales; pruebas
  unitarias de saldo/aging, integracion de movimientos y E2E de cobro.

Salida: cartera coincide con documentos y movimientos.

## Sprint 4 - Cuentas por pagar

- Obligaciones, vencimientos, programacion y pagos parciales.
- Carga XML/PDF, antivirus, extraccion y validacion.
- Tools de consulta, creacion, programacion y pago.
- Fixtures XML/PDF sanitizadas; pruebas unitarias de extraccion/duplicados,
  integracion documental y E2E de obligacion/pago.

Salida: documento de proveedor se convierte en obligacion trazable.

## Sprint 5 - Automatizacion y migracion piloto

- Agente interno y adaptador OpenAI.
- Presupuestos, limites y observabilidad de tool calls.
- Dashboard financiero y flujo proyectado.
- Migrador selectivo y piloto de un RUC.
- Dataset de ataques y migracion anonimizada; pruebas de politicas, prompt
  injection, consistencia REST/MCP y reconciliacion repetible.

Salida: flujo autonomo controlado, auditable y reconciliado.

## Sprint 6 - Estabilizacion y produccion

- Rendimiento, seguridad, DAST y pruebas de carga.
- Backup/restauracion, runbooks y alertas.
- UAT, capacitacion, cutover y rollback.
- Regresion integral, pruebas de carga, seguridad, resiliencia y restauracion
  con evidencia y umbrales aprobados.

Salida: checklist de produccion aprobado y despliegue desde `main` por Coolify.

## Puertas

- No inicia Sprint 1 sin aprobar Sprint 0.
- Ningun sprint cierra sin unitarias e integracion de sus historias y E2E de sus
  flujos principales usando datos sinteticos reproducibles.
- No se habilita SRI produccion sin pruebas de duplicado/reconciliacion.
- No se habilita IA autonoma sin threat model y kill switch probado.
- No se migra produccion sin reporte y restauracion ensayada.
