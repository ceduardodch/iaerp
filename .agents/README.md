# Agentes expertos de IAERP

Los expertos son perfiles de responsabilidad. No sustituyen permisos, revisiones
ni aprobacion humana.

## Registro

| Agente | Perfil | Skills principales |
| --- | --- | --- |
| Product ERP Expert | `experts/product-erp.md` | ERP Domain Knowledge |
| Backend Platform Expert | `experts/backend-platform.md` | fba |
| Ecuador SRI Expert | `experts/ecuador-sri.md` | Reglas locales del repositorio |
| MCP AI Security Expert | `experts/mcp-ai-security.md` | mcp-patterns, seguridad |
| Frontend A11y Expert | `experts/frontend-a11y.md` | a11y-playwright-testing, React |
| QA Reliability Expert | `experts/qa-reliability.md` | pruebas, contratos, operaciones |

## Reglas

- El orquestador asigna una responsabilidad y archivos concretos.
- Los agentes informan supuestos, riesgos y validaciones realizadas.
- Revisores trabajan en solo lectura salvo que reciban ownership explicito.
- Dos agentes no editan el mismo archivo en paralelo.
- Hallazgos se clasifican P0, P1 o P2 y referencian archivo/contrato.
- Un experto no puede relajar un ADR aceptado; debe proponer uno nuevo.
- Produccion, secretos, SRI produccion, push, merge y PR requieren autorizacion
  humana explicita.

## Skills instaladas

Las skills viven en `skills/` y su origen/hash en `../skills-lock.json`.

- `fba`: patrones FastAPI por capas. Se usa como referencia, sin adoptar su
  framework base ni sus respuestas propietarias.
- `mcp-patterns`: OAuth, Streamable HTTP, seguridad y pruebas MCP.
- `ERP Domain Knowledge`: procesos AR/AP y terminologia ERP.
- `a11y-playwright-testing`: WCAG 2.1 AA, axe-core y teclado.

Los ADR y reglas de IAERP tienen prioridad cuando una skill recomienda una
arquitectura diferente.

## Revision de cadena de suministro

Revision inicial: 2 de julio de 2026.

| Skill | Evaluacion del instalador | Decision |
| --- | --- | --- |
| fba | Gen Safe, Socket 0 alertas, Snyk Low | Aceptada como referencia |
| mcp-patterns | Gen Safe, Socket 0 alertas, Snyk Medium | Aceptada con revision manual |
| ERP Domain Knowledge | Sin scripts; contenido documental | Aceptada como referencia |
| a11y-playwright-testing | Gen Safe, Socket 0 alertas, Snyk Low | Aceptada |

La revision local confirma que las cuatro skills contienen solo Markdown/JSON y
ningun archivo ejecutable. Una actualizacion cambia el hash y exige nueva
revision antes de usarla.
