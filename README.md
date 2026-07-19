# IAERP

ERP SaaS para pymes ecuatorianas, enfocado en automatizacion mediante IA y
Model Context Protocol (MCP).

## Estado

**Última actualización:** 2026-07-19

**Sprints Completados:**
- ✅ Sprint 0: Aprobación (2026-07-02)
- ✅ Sprint 1: Plataforma base (2026-07-03)
- ✅ Sprint 2: Facturación SRI (2026-07-04)
- ✅ Sprint 3: Cartera + MCP (2026-07-06)
- ✅ CRM MVP: Prospectos y pipeline básico (2026-07-19)

**Sprints Actuales:**
- 🔄 UI/UX Improvements: Plan 12 semanas para modernizar interfaces
- 📋 Sprint 1: CRM Kanban Foundation (pipeline visual arrastrable)

**El detalle verificable para retomar el trabajo está en:**
- [Estado actual y relevo](docs/STATUS.md) - Fuente de verdad del proyecto
- [Quick Start](QUICK_START.md) - Guía rápida 20 segundos
- [Issue Tracking](ISSUE_TRACKING.md) - Tareas 1x1 del sprint actual

## Alcance inicial

- Facturacion electronica: facturas y notas de credito.
- Cuentas por cobrar: vencimientos, cobros, retenciones y recordatorios.
- Cuentas por pagar: obligaciones, documentos, programacion y pagos registrados.
- Datos maestros: contactos, productos, establecimientos, puntos de emision y
  etiquetas.
- API REST y servidor MCP remoto con los mismos casos de uso.

El MVP no incluye contabilidad general, conciliacion bancaria, transferencias,
nomina ni modulos propios de franquicias.

## Documentacion

### Guías Rápidas:
1. **[QUICK_START.md](QUICK_START.md)** - 🚀 Guía 20 segundos para retomar trabajo
2. **[CLAUDE.md](CLAUDE.md)** - 🤖 Configuración del proyecto para agentes AI
3. **[docs/STATUS.md](docs/STATUS.md)** - 🏠 Fuente de verdad del proyecto

### Planificación y Alcance:
4. **[BACKLOG.md](BACKLOG.md)** - 📋 Alcance completo (12 semanas de UI/UX improvements)
5. **[SPRINT_STATUS.md](SPRINT_STATUS.md)** - 📊 Status detallado de sprints y decisiones técnicas
6. **[ISSUE_TRACKING.md](ISSUE_TRACKING.md)** - ✅ Tareas 1x1 (trabajo sesión por sesión)

### Documentos de Producto:
7. [Vision de producto](docs/00-product-vision.md)
2. [TAM, SAM y SOM](docs/01-tam-sam-som.md)
3. [Alcance y restricciones](docs/02-scope-and-restrictions.md)
4. [Modelo de dominio](docs/03-domain-model.md)
5. [Arquitectura](docs/04-architecture.md)
6. [IA y MCP](docs/05-ai-mcp.md)
7. [Seguridad y amenazas](docs/06-security-threat-model.md)
8. [Migracion](docs/07-data-migration.md)
9. [Roadmap](docs/08-roadmap.md)
10. [Pruebas y calidad](docs/09-testing-quality.md)
11. [Operaciones](docs/10-operations.md)
12. [Backlog](docs/backlog/product-backlog.md)
13. [Sprint 0](docs/sprints/sprint-00.md)
14. [Contratos REST y MCP](contracts/README.md)
15. [Modelo operativo de agentes](docs/11-agent-operating-model.md)
16. [Estado actual y relevo](docs/STATUS.md)
17. [Sistema de interfaz ERP](docs/12-frontend-design-system.md)

Las decisiones tecnicas vinculantes se registran en [ADR](docs/adrs/).
Los perfiles expertos y skills locales se registran en [.agents](.agents/README.md).

## Tecnologia objetivo

- Backend: Python, FastAPI, SQLAlchemy 2, Alembic y PostgreSQL.
- Frontend: React, TypeScript y Vite.
- Identidad: Keycloak mediante OAuth 2.1 y OpenID Connect.
- Procesamiento: Redis y workers.
- Archivos: MinIO compatible con S3.
- IA: adaptador de modelos con OpenAI como primer proveedor.
- MCP: SDK oficial de Python, Streamable HTTP y resultados estructurados.

## Entrega

- `develop`: desarrollo continuo.
- `release`: validacion y rama de trabajo por defecto; CI verde despliega el
  staging `https://iaerp.b2b.com.ec` mediante Coolify.
- `main`: produccion; Coolify despliega exclusivamente desde esta rama.

GitHub Actions actua como puerta de CI/CD: no ejecuta contenedores en el host,
sino que solicita el despliegue a Coolify una vez superadas las validaciones.
