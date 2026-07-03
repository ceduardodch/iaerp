# Modelo operativo de agentes expertos

## Objetivo

Usar agentes especializados para aumentar profundidad sin entregarles autoridad
ilimitada. Los agentes trabajan sobre contratos, ADR y ownership explicito.

## Flujo

1. El orquestador selecciona historia y criterios de aceptacion.
2. Product ERP y el experto de dominio confirman invariantes.
3. Un implementador recibe archivos o modulo exclusivo.
4. Expertos de seguridad/fiscal revisan cuando aplique.
5. QA Reliability valida de forma independiente.
6. Un humano autoriza push, PR, produccion y acciones externas sensibles.

## Matriz de revision

| Cambio | Revisores obligatorios |
| --- | --- |
| Tenancy, auth, roles | Backend Platform + MCP AI Security + QA |
| Factura/nota de credito/SRI | Ecuador SRI + Backend + QA |
| AR/AP y saldos | Product ERP + Backend + QA |
| Tool MCP de lectura | MCP AI Security + QA |
| Tool MCP de escritura | Product ERP + MCP AI Security + QA |
| UI financiera | Frontend A11y + Product ERP + QA |
| Migracion | Product ERP + Ecuador SRI + Backend + QA |
| Operacion/backup | Backend Platform + QA |

## Independencia

- Implementador y revisor no deben ser el mismo agente.
- El revisor entrega findings; no altera el codigo revisado sin reasignacion.
- P0: riesgo de dinero, documento fiscal, seguridad o perdida de datos; bloquea.
- P1: comportamiento importante incorrecto o sin prueba; bloquea release.
- P2: mejora mantenible que puede planificarse.

## Autoridad humana reservada

- Aprobar ADR o cambio de alcance.
- Dar acceso a secretos o produccion.
- Emitir/anular en SRI produccion durante pruebas.
- Hacer push, abrir/mergear PR o desplegar.
- Aceptar riesgo P0/P1.

## Skills

Las skills son referencias de trabajo, no autoridad. Se fijan por hash en
`skills-lock.json`, se revisan antes de actualizar y nunca pueden contradecir
un ADR aceptado. La lista se mantiene pequena para reducir instrucciones
conflictivas y riesgo de cadena de suministro.
