# IAERP

ERP SaaS para pymes ecuatorianas, enfocado en automatizacion mediante IA y
Model Context Protocol (MCP).

## Estado

Sprint 0 fue aprobado el 2 de julio de 2026. Sprint 1 esta en progreso con una
plataforma local ejecutable, REST/MCP tenant-scoped, Keycloak, maestros, outbox
y frontend base.

El detalle verificable para retomar el trabajo esta en
[Estado actual y relevo](docs/STATUS.md). Ese documento distingue lo
implementado, lo probado y lo pendiente.

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

1. [Vision de producto](docs/00-product-vision.md)
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
- `release`: validacion y rama de trabajo por defecto.
- `main`: produccion; Coolify despliega exclusivamente desde esta rama.

GitHub Actions se usara solo para CI. No se desplegara desde GitHub Actions.
