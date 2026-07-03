# Sprint 1 - Plataforma, identidad y maestros

## Estado

Ready, blocked by ADR 0009 PoC.

## Objetivo

Entregar una base ejecutable en `release` donde dos tenants puedan autenticarse,
gestionar maestros y usar consultas REST/MCP sin fuga de datos.

## Historias

| Orden | IDs | Entrega | Owner experto |
| --- | --- | --- | --- |
| 1 | E1-01, E1-02 | Keycloak, login y tenant/RUC | Backend Platform |
| 2 | E1-03, E1-04, E1-05 | Membresias, roles y service accounts | Backend + MCP Security |
| 3 | E2-01, E2-02 | Auditoria e idempotencia | Backend Platform |
| 4 | E2-03 | Outbox, dispatcher e inbox de worker | Backend Platform + QA |
| 5 | E2-04, E2-05 | Politicas y kill switch | MCP AI Security |
| 6 | E3-01, E3-02 | Empresa, establecimientos y puntos | Ecuador SRI + Backend |
| 7 | E3-03, E3-04, E3-05 | Parties, productos, impuestos y tags | Product ERP + Backend |
| 8 | E7-01, E7-02 | MCP OAuth, contexto y busquedas | MCP AI Security |
| 9 | E1-06 | Matriz de aislamiento REST/MCP/worker | QA Reliability |

## Secuencia tecnica

1. Crear skeleton backend/frontend e infraestructura local.
2. Configurar PostgreSQL/Alembic y modelos de identidad/tenant.
3. Ejecutar y aprobar el PoC ADR 0009; integrar Keycloak solo despues.
4. Implementar contexto autenticado y repositories tenant-scoped.
5. Crear auditoria, idempotencia, politicas y kill switch.
6. Implementar maestros con REST.
7. Exponer `context.get`, `parties.search` y `products.search` por MCP.
8. Agregar UI minima y pruebas de aislamiento/accesibilidad.

## Criterios de aceptacion

- Dos tenants con RUC distintos y usuarios/membresias controlados.
- Un usuario multi-tenant cambia contexto solo mediante flujo autorizado.
- Requests sin tenant valido no alcanzan repositories.
- Usuario del tenant A no descubre IDs ni datos del tenant B.
- Service account solo ve tools/scopes asignados.
- Kill switch bloquea escrituras automatizadas y no consultas.
- Cada escritura produce auditoria e idempotency record.
- Alembic crea y revierte el esquema desde cero.
- OpenAPI y catalogo MCP siguen validos.
- UI base pasa axe-core y flujo por teclado.
- UI tiene foco visible/restaurado, errores anunciados, contraste AA y reflow a
  320 CSS px/200% zoom.
- Outbox preserva tenant y supera crash entre claim, publicacion y confirmacion.

## Revisiones obligatorias

- Backend Platform revisa transacciones y migraciones.
- MCP AI Security revisa OAuth, audience, scopes y tool schemas.
- Product ERP revisa maestros e impuestos.
- Ecuador SRI revisa establecimiento/punto y configuracion fiscal.
- Frontend A11y revisa UI.
- QA Reliability emite recomendacion go/no-go independiente.

## No incluido

Emision SRI, XML/PDF, facturas, cartera y obligaciones. Esas capacidades
comienzan en Sprint 2 o posteriores.
