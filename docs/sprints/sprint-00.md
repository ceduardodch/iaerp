# Sprint 0 - Definicion, riesgos y contratos

## Estado

Approved.

Aprobado por el owner el 2 de julio de 2026.

## Duracion y objetivo

Duracion prevista: dos semanas.

Dejar IAERP decision-complete para iniciar Sprint 1 sin inventar alcance,
arquitectura, seguridad o contratos durante la implementacion.

## Entregables

- [x] Repositorio independiente y politica de ramas documentada.
- [x] Vision de producto y criterios de exito.
- [x] TAM/SAM/SOM con fuentes e hipotesis.
- [x] Alcance, restricciones y exclusiones.
- [x] Modelo de dominio e invariantes.
- [x] Arquitectura y topologia Coolify.
- [x] Catalogo MCP y reglas de autonomia.
- [x] Threat model y controles.
- [x] Plan de migracion selectiva.
- [x] Roadmap y backlog priorizado.
- [x] Estrategia de pruebas y operaciones.
- [x] ADR iniciales.
- [x] Contratos preliminares OpenAPI/MCP.
- [x] Revision y aprobacion del owner.

## Riesgos a resolver antes de Sprint 1

| Riesgo | Tratamiento | Responsable |
| --- | --- | --- |
| Keycloak aumenta operacion | PoC local de login, client credentials y MCP | Backend/DevOps |
| MCP SDK v2 en transicion | Fijar v1 `<2` y revisar al iniciar Sprint 1 | Backend |
| Autonomia financiera | Politicas, kill switch, idempotencia y auditoria primero | Producto/Backend |
| Datos entre tenants | Repository tenant-scoped y pruebas negativas | Backend/QA |
| Costos IA/WhatsApp | Medicion por tenant y limites de plan | Producto |
| Certificados heredados | No copiar Git; recarga/traslado cifrado | Owner/DevOps |
| TAM demasiado amplio | Entrevistas y segmentacion SRI reproducible | Producto |

Estado al cierre:

- Riesgos aceptados como trabajo de Sprint 1, no declarados resueltos.
- Keycloak/MCP queda bloqueado por el PoC del ADR 0009.
- Aislamiento requiere FK compuestas, contexto inmutable y decision RLS.
- SDK MCP permanece fijado por hash/version y se revisa antes de instalar.

## Criterios de aceptacion

- No hay terminos ambiguos entre tenant, RUC, establecimiento y punto.
- El alcance MVP y sus exclusiones estan aprobados.
- Cada tool de escritura exige scope, politica e idempotencia.
- Arquitectura tiene fuente de verdad para migraciones, archivos y jobs.
- Backlog permite planificar Sprint 1 sin decisiones de producto pendientes.
- No existen secretos, certificados o datos productivos en el repositorio.

## Decision de cierre

Sprint 1 queda habilitado para preparacion. La implementacion de identidad/MCP
permanece bloqueada hasta resolver el PoC del ADR 0009. Backend, frontend e
infraestructura deben respetar los ADR aceptados y sus cambios requieren un
nuevo ADR.
