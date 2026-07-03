# Sprint 1 - Plataforma, identidad y maestros

## Estado

In progress.

Corte del 3 de julio de 2026:

- Plataforma local, maestros REST/MCP, aislamiento base, auditoria,
  idempotencia, outbox/inbox/dead letter, Keycloak y UI implementados.
- Backend mantenido pasa Ruff, mypy y 8 pruebas.
- Frontend pasa lint, build y 6 pruebas Playwright de accesibilidad.
- ADR 0009 sigue propuesto: organization/audience estan comprobados, pero faltan
  client credentials, revocacion, MCP Inspector y cierre de la matriz OAuth.
- El detalle operativo y los pendientes se mantienen en `docs/STATUS.md`.

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
| 10 | E9-01 a E9-07 | Datos sinteticos y automatizacion de pruebas | QA Reliability |

## Secuencia tecnica

1. Crear skeleton backend/frontend e infraestructura local.
2. Configurar PostgreSQL/Alembic y modelos de identidad/tenant.
3. Ejecutar y aprobar el PoC ADR 0009; integrar Keycloak solo despues.
4. Implementar contexto autenticado y repositories tenant-scoped.
5. Crear auditoria, idempotencia, politicas y kill switch.
6. Implementar maestros con REST.
7. Exponer `context.get`, `parties.search` y `products.search` por MCP.
8. Agregar UI minima y pruebas de aislamiento/accesibilidad.

## Plan de pruebas y datos

El seed `sprint-01-v1` debe crear dos tenants ficticios, un usuario multi-tenant,
un usuario exclusivo por tenant, un usuario sin membresia, cuatro roles, una
service account por tenant y maestros distinguibles entre ambos tenants.

Pruebas unitarias:

- validacion de RUC, codigos fiscales y valores Decimal;
- resolucion de membresias, permisos, politicas y kill switch;
- idempotencia, estados de outbox y filtros tenant-scoped;
- validacion y serializacion de comandos REST/MCP.

Pruebas de integracion:

- migracion Alembic desde cero y downgrade/upgrade;
- login OIDC, cambio autorizado de tenant y revocacion de service account;
- CRUD de maestros con PostgreSQL y auditoria real;
- publicacion, reintento y dead letter del outbox con Redis;
- equivalencia de permisos y resultados entre REST y MCP;
- intentos de acceso cruzado por ID, busqueda y worker.

Pruebas E2E:

- login, seleccion de tenant, consulta y alta de un maestro;
- cambio al segundo tenant sin mostrar datos del primero;
- acceso denegado visible y accesible para un rol sin permiso;
- recorrido por teclado, axe-core y viewport movil.

La evidencia minima es reporte JUnit, cobertura, log sanitizado del stack y
traza/captura de cada fallo E2E.

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
- Dataset `sprint-01-v1` se recrea desde cero de forma idempotente.
- Suites unitarias e integracion pasan sin depender del orden de ejecucion.
- Los cuatro recorridos E2E pasan en escritorio y viewport movil.
- CI publica evidencia de pruebas sin secretos ni datos personales.

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
