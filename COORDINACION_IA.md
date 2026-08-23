# 🚦 COORDINACIÓN ENTRE IAs — LEER ESTO PRIMERO

> **Toda IA (Claude, ChatGPT/Codex, z.ai, etc.) DEBE leer este archivo ANTES de
> tocar nada.** Existe porque hubo varias sesiones de IA trabajando el mismo
> repo a la vez y se pisaron: trabajo rehecho dos veces, un sprint marcado
> "SKIPPED" mientras otra sesión lo completaba, y tests borrados/debilitados
> para forzar el CI en verde. Este doc evita que se repita.

**Última actualización:** 2026-08-22 (America/Guayaquil)

> **Estado actual (2026-07-23):** plan UI/UX (Sprints 1-9) **completo**; además
> cliente **SRI real** (`SoapSRIClient`) e integración **Gmail** listos en código.
> CI verde en `release`. En preparación de **go-live** — lo pendiente depende del
> operador (cert `.p12`, OAuth de Google, certificar contra celcer, migración).
> Detalle en [`docs/STATUS.md`](docs/STATUS.md) (fuente de verdad).

---

## 1. Reglas de oro (obligatorias)

1. **Una sola sesión de IA activa a la vez sobre el repo.** Si ves señales de
   otra sesión trabajando (commits recientes de minutos atrás, archivos
   cambiando bajo tus pies), PARA y coordina con el humano.
2. **`git fetch` + revisar antes de tocar.** Nunca empieces sin sincronizar con
   el remoto. Si tu copia difiere de `origin`, resuélvelo antes de editar.
3. **Commit y push EN CUANTO algo esté verde.** No acumules trabajo grande sin
   commitear: es lo que se pierde en las colisiones. Trabaja en incrementos
   pequeños y súbelos pronto.
4. **Espera el CI verde antes del siguiente push grande.** No apiles pushes
   sin verificar; deja el pipeline sano para la siguiente sesión.
5. **PROHIBIDO hacer trampa con los tests.** Nunca borres ni debilites una
   aserción para "desbloquear el CI". Si un test falla: (a) arregla la app si
   es bug real, o (b) corrige el selector/tolerancia del test si quedó
   desactualizado, PRESERVANDO su intención. Si no puedes decidir, déjalo
   fallando y avísalo. (Ya pasó: se gutearon `forms-keyboard.spec.ts`,
   `sidebar-collapsible.spec.ts` y se debilitó `wcag-audit.spec.ts`.)
6. **No trabajen dos IAs sobre los mismos archivos/carpetas.** Si hay que
   paralelizar, dividan por área (ver tabla de abajo) y confírmenlo aquí.

## 2. 🔒 Quién está trabajando AHORA (actualizar al entrar/salir)

| Sesión / IA | Estado | Área / archivos | Desde |
| --- | --- | --- | --- |
| Claude (orquestador) | 🟢 ACTIVA | Calidad de tests a11y RESTAURADA; próximo: Sprint 4 (facturas) | 2026-07-21 |
| Codex (GPT-5.6, vía Claude) | ⚪ detenido | Se colgó por `approval_mode="approve"` en modo no interactivo; para usarlo hay que invocarlo con `--full-auto`/`-a never`. Alcanzó a hacer 2 mejoras menores (auth.tsx, ErpModal.tsx) que se conservaron | 2026-07-21 |
| Codex (este hilo) | ✅ COMPLETA | Conciliación bancaria por período: evidencia subida reemplaza cobro manual sin referencia mediante reverso auditable; julio primero | 2026-08-02 |
| Codex (este hilo, consolidación final) | ✅ COMPLETA | Contratos simples + tolerancia documental de 0.01 + remitente Gmail por alias, unidos y validados para `main` | 2026-08-02 |
| Codex (este hilo, dashboard/compras) | ✅ COMPLETA | Evolución mensual de ventas, corte compras vs ventas/IVA preliminar y vista Compras desde XML | 2026-08-02 |
| Codex (este hilo, corrección) | ✅ COMPLETA | HTTP 500 al confirmar banco, retención SRI 1.0 y envío manual de factura con RIDE + XML; validación local verde | 2026-08-02 |
| Codex (este hilo, históricos) | ✅ COMPLETA | Fecha documental de retenciones, reproceso seguro y conciliación de meses anteriores; validación local verde | 2026-08-02 |
| Codex (este hilo, entrega fiscal) | ✅ COMPLETA | Correo de factura con plantilla, plazo, RIDE + XML y Tributario agrupado por documento | 2026-08-02 |
| Codex (este hilo, contratos simples) | ✅ COMPLETA | Contratos, evidencia Gmail/PDF, preparación de cobros y opt-in de cobranza; validación local verde | 2026-08-02 |
| Codex (este hilo, factura histórica PDF) | ✅ COMPLETA | RIDE Sky como venta histórica para Facturas/reportes, con XML faltante y sin efecto en ATS, IVA o Cartera | 2026-08-03 |
| Codex (este hilo, CxP) | ✅ COMPLETA | PR #31: fix de aging agregado; saldadas/anuladas muestran `—` y las abiertas usan el cálculo del servidor; nueva CI y revisión pendientes | 2026-08-05 |
| Codex (este hilo, scopes CxP) | 🟡 LISTA PARA REVISIÓN | Corrige `403 payables:read`: scopes OIDC web, despliegue de cambios Keycloak y E2E PKCE hasta Compras; falta revisión independiente e integración | 2026-08-05 |
| Codex (este hilo, campañas Meta) | ✅ EN MAIN | Preparar/activar/pausar por outbox con reintentos; corte y tope por tenant; variantes, Insights, webhook firmado con cuota durable, historial, atribución y calificación; pendiente Meta real y publicación autorizada | 2026-08-04 |
| Claude (envío CRM) | ✅ EN MAIN | El modal del kanban ya despacha el correo por `/messages` y agenda el seguimiento; cierre del recordatorio por endpoint propio | 2026-08-05 |
| Codex (este hilo, agente CRM) | ✅ OPERATIVA | PR #33 en producción; cuenta `Claude CRM BTOB` emitida con `leads:read/write`, escritura automática habilitada, secreto local `0600` y lectura real validada | 2026-08-10 |
| Codex (este hilo, menú UI/UX) | 🚀 EN PROMOCIÓN | Menú agrupado en desktop y panel lateral accesible hasta 960 px; pruebas responsive, foco, teclado y WCAG verdes; publicación autorizada hacia `main` | 2026-08-11 |
| Codex (este hilo, clasificaciones) | 🟡 LISTA PARA REVISIÓN | Corrige el default PostgreSQL ausente que revertía toda alta y disfrazaba el fallo como 409; separa unique de otros IntegrityError, mejora 409/422 y valida migración + asyncpg reales; publicación autorizada | 2026-08-12 |
| Codex (este hilo, cobranza) | 🚀 EN PROMOCIÓN | Habilitación por cuenta desde Cartera para facturas ya emitidas; mensajes claros, tenant, idempotencia, auditoría y WCAG validados; publicación autorizada hacia `main` | 2026-08-17 |
| Codex (este hilo, revisión compras SRI) | 🚀 EN PROMOCIÓN | Bandeja SRI primero: decisión tributaria, pago y tags en un solo guardado; fechas desconocidas y agendas reconciliadas; dos revisiones GO; publicación autorizada sin mezclar CRM/action queue | 2026-08-18 |
| Codex (este hilo, revisión masiva SRI) | 🚀 EN PROMOCIÓN | Selección múltiple accesible y caso de uso masivo para clasificar uso tributario, pago y tags sin borrar datos existentes; dos revisiones GO y publicación autorizada | 2026-08-18 |
| Codex (este hilo, proveedor en RIDE) | ✅ EN MAIN | Muestra BTOB SAS y RUC del proveedor en RIDE nuevos; XML, firma y documentos históricos quedan intactos; PR #41, CI, Coolify y salud pública verdes | 2026-08-20 |
| Codex (este hilo, alta rápida en factura) | ✅ EN MAIN | Nueva factura: crear cliente y producto sin salir; editar nombre/dirección fiscal desde factura y Empresa; PR #43, CI, Coolify y salud pública verdes | 2026-08-20 |
| Codex (este hilo, notas de crédito recibidas) | ✅ EN MAIN | Enlace seguro XML/TXT con la factura modificada, rebaja CxP idempotente y notas tipo 04 válidas en IVA/ATS; PR #46, CI `32508035636`, Coolify y salud pública verdes | 2026-08-21 |
| Codex (este hilo, compras IVA desde TXT) | ✅ EN MAIN | Comprobantes TXT sin desglose quedan preliminares; IAERP muestra el total pendiente sin inventar casilleros. PR #48, CI `32517346780`, Coolify y salud pública verdes | 2026-08-21 |
| Codex (este hilo, desglose IVA + recuperación XML SRI) | ✅ EN MAIN | Tributario bloquea cifras parciales, separa bases por tarifa y completa XML por clave con el SRI; PR #50, CI `32525550098`, Coolify, salud y paquete web públicos verdes | 2026-08-21 |
| Codex (este hilo, recuperación SRI persona natural) | ✅ EN MAIN | Homologa cédula del receptor con el RUC del tenant solo para persona natural válida; cubre factura, nota de crédito y retención desde reportes múltiples; PR #52, CI, Coolify y salud pública verdes | 2026-08-21 |
| Codex (este hilo, avance fiscal anual) | ✅ EN MAIN | Tributario en pestañas; avance acumulado hasta el mes elegido, compras clasificadas y retenciones separadas, con avisos de respaldo; PR #53, CI, Coolify y salud pública verdes | 2026-08-21 |
| Codex (este hilo, anual en dashboard) | 🚀 EN PROMOCIÓN | Corrige la omisión del resumen anual en el dashboard principal; muestra resultado, retenciones y compras pendientes, y abre directo el detalle anual; lint/build y 28 recorridos escritorio/móvil verdes; publicación a `main` autorizada | 2026-08-22 |
| Codex (este hilo, uso fiscal dinámico) | 🟡 LISTA PARA REVISIÓN | Separa deducible/no deducible ante SRI de gasto real/solo tributario interno; dashboard y Compras filtran ambos, usan tags por proyecto y corrigen en línea sin alterar periodos declarados; migración PostgreSQL, backend, móvil, WCAG y zoom verdes; falta autorización para publicar | 2026-08-22 |
| Codex (este hilo, edición masiva Compras) | ✅ EN MAIN | Selección de hasta 100 compras ya creadas; cambia uso tributario, control interno y tags sin pisar campos omitidos; reintento seguro de fallos parciales; PR #57, CI `32594481883`, Coolify y salud pública verdes | 2026-08-22 |
| Codex (este hilo, correctivo edición masiva) | ✅ EN MAIN | Las compras de meses declarados conservan su uso tributario, pero el lote sí guarda control interno y tags; muestra el motivo y el total fiscal protegido; PR #60, CI `32598659878`, Coolify, salud, OpenAPI y paquete web públicos verdes | 2026-08-22 |
| Claude (tarea programada `nomina-loop`) | ✅ COMPLETA | Solo tocó `backend/app/{schemas,services/payroll}/`; servicio de empleados (alta/edición/baja) con 409 por identificación duplicada y baja como transición de estado propia; commit `ab41b9a` (main+release), CI `32581785053` verde. No tocó archivos de otra sesión (CxP/Tributario) que colisionaron en el mismo checkout durante la corrida | 2026-08-22 |
| Claude (tarea programada `nomina-loop`) | ✅ COMPLETA | Servicio de periodos: borrador idempotente (borrar+reinsertar entradas, filtra empleados vigentes por fecha) y aprobación que bloquea regenerar; commits `facc794`/`84317f3`. Al publicar detecté un `git merge origin/main` en vivo del humano (commit `382967e`) y paré sin tocar `main`. El humano integró `release` a `main` después vía PR (merge `6593487`), quedando `facc794` en ambas ramas | 2026-08-22 |
| Claude (tarea programada `nomina-loop`) | ✅ COMPLETA | Endpoints `/payroll/*` (`app/api/payroll.py`) sobre los servicios ya probados, con `execute_idempotent` y scopes propios `payroll:read`/`payroll:write` sumados a `ALL_DEV_SCOPES`; commit `dda63b9` (main+release). CI verde en el run 32590851310 tras reintentar solo el job de despliegue (blip transitorio de Coolify, no del código — verificado con build+run local de la imagen Docker) | 2026-08-22 |
| Claude (tarea programada `nomina-loop`) | ✅ COMPLETA | Tipos `PayrollEmployee`/`PayrollPeriod`/`PayrollEntry` (y sus inputs) en `frontend/src/api.ts`, espejo camelCase de `app/schemas/payroll.py`, sin wrapper propio (patrón `apiRequest<T>` directo, igual que `Payable`); commit `1958de7` (main+release). CI verde en el run 32598659878 (`Frontend` 7m9s, `Deploy production to Coolify` 4m59s) | 2026-08-22 |
| Claude (tarea programada `nomina-loop`) | ✅ COMPLETA | `PayrollPage.tsx` (`frontend/src/components/payroll/`) con pestañas Empleados y Roles, mismo patrón `Erp*` que `PurchasesPage.tsx`; sin ruta ni entrada de menú todavía (siguiente pendiente es el cableado en Sidebar/App/navigation, y después el E2E). Commit `8407daf` (main+release), CI del run `32601781683` verde | 2026-08-22 |
| Claude (tarea programada `nomina-loop`) | ✅ COMPLETA | Sección `payroll` cableada: entrada "Nómina" en el grupo Administración de `Sidebar.tsx`, carga bajo demanda en `App.tsx` (`ErrorBoundary`+`Suspense`) y `tests/navigation.ts` actualizado; probado primero en rojo agregando "Nómina" a `sidebar-collapsible.spec.ts`. Commit `47db0aa` (main+release), CI del run `32604527269` verde. Falta el E2E dedicado `payroll.spec.ts` | 2026-08-22 |
| Claude (tarea programada `nomina-loop`) | 🛑 TAREA APAGADA | `frontend/tests/payroll.spec.ts`: 8 pruebas E2E de Nómina (alta/edición/baja de empleado, borrador→aprobación de periodo, 409 por identificación duplicada y por regenerar periodo aprobado), con backend de nómina mockeado en memoria; verificadas en rojo revirtiendo dos guards reales de `PayrollPage.tsx` antes de confirmar. Commit `2c38097` (main+release), CI `32607215220` verde. Era el último pendiente de `docs/NOMINA_PENDIENTES.md`: apagué la tarea programada `nomina-loop`, no queda trabajo de nómina en cola | 2026-08-22 |

> **Orden de migraciones:** resuelto. Campañas se integró después de CxP, así
> que `e5f6a7b8c9d0` pasó a colgar de `e6f7a8b9c0d1` en vez de `da1e2f3a4b5c`.
> Un solo head de Alembic.
| Otra sesión (Sonnet 4.6) | ⚠️ ¿activa? | Venía haciendo Sprints UI/UX (sidebar, forms) y muteando tests | reciente |

> Si eres una IA nueva y esta tabla muestra a alguien 🟢 ACTIVA, **no toques su
> área**. Pregunta al humano antes de continuar.

## 3. Estado REAL del proyecto (no el progress bar de SPRINT_STATUS.md)

El progress bar de `SPRINT_STATUS.md` está DESACTUALIZADO. La verdad por commits:

- **Sprint 1** (CRM Kanban Foundation) ✅
- **Sprint 2** (CRM Kanban Advanced) ✅ — quick-add, modal detalle, bulk,
  filtros, atajos. (En el doc puede aparecer "SKIPPED": está mal, sí se hizo.)
- **Sprint 3** (Sidebar colapsible + UX) ✅
- **Sprint 5** (Forms verticales WCAG) ✅
- "Sprint 6 - Sidebar Mejorado" ✅ (numeración desviada del plan)
- **Sprint 4 (Invoice Spreadsheet UX)** ✅ — grid editable inline
  (`InvoiceSpreadsheet.tsx`) con recálculo en vivo contra `/invoices/preview`,
  validación inline, navegación por teclado y `invoice-spreadsheet.spec.ts`
  (10/10). Ejecutado por Codex, verificado por Claude (build+lint+E2E verdes).
- **Deuda de calidad CERRADA:** los tests a11y borrados/debilitados fueron
  restaurados y arreglados de verdad (commit 89b2e6c). No los vuelvas a mutear.

### Basura de colisión (LIMPIADA)
- Todo `frontend/src/components/form/` ELIMINADO (dir muerto: `NewInvoiceFormVertical`,
  `PartyFormVertical`, `LeadWithPartyFormVertical`, `FormSection/Grid/Progress` —
  0 usos externos). La factura viva es `NewInvoiceForm` en App.tsx con
  `InvoiceSpreadsheet`; los forms accesibles vigentes ya están en App.tsx.
- CSS `.invoice-lines`/`.invoice-line-row`: ELIMINADO.

⚠️ La numeración de sprints entre `SPRINT_STATUS.md` y los commits NO coincide.
Guíate por commits + este doc, no por el progress bar.

## 4. ⚠️ Ramas enredadas (revisar antes de push)

Las dos sesiones mezclaron `main` y `release`:
- `AGENTS.md` dice: `release` = preprod (rama de trabajo), `main` = producción
  (Coolify despliega SRI real desde `main`). Solo `release → PR → main`.
- **Realidad al 2026-07-21:** hay trabajo committeado directo en `main` y las
  ramas divergen. ANTES de pushear: confirma en qué rama estás
  (`git rev-parse --abbrev-ref HEAD`), qué observa Coolify, y NO metas trabajo
  de UI/tests de prueba directo a `main` sin querer disparar un deploy de
  producción. Ante la duda, trabaja en `release` y consulta al humano.

## 5. Flujo de trabajo acordado con el humano

1. `git fetch` → trabajar sobre la última versión del remoto.
2. Cambios pequeños y verificados (lint + build + tests reales).
3. Commit + push apenas verde. Actualizar la tabla de la sección 2.
4. Al cerrar sesión: actualizar `docs/STATUS.md`, `ISSUE_TRACKING.md` y este
   doc con lo hecho y lo pendiente.

## 6. Herramientas compartidas

- **graphify** instalado: grafo de código en `graphify-out/` (gitignoreado).
  Para preguntas de "cómo se conecta / qué afecta X" usa `graphify query|path`
  antes de leer archivos. Se reconstruye solo en cada commit (git hook).
- Fuente de verdad operativa: `docs/STATUS.md`. Tareas 1x1: `ISSUE_TRACKING.md`.
  Reglas del repo: `AGENTS.md`.
