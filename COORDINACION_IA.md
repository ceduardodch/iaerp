# 🚦 COORDINACIÓN ENTRE IAs — LEER ESTO PRIMERO

> **Toda IA (Claude, ChatGPT/Codex, z.ai, etc.) DEBE leer este archivo ANTES de
> tocar nada.** Existe porque hubo varias sesiones de IA trabajando el mismo
> repo a la vez y se pisaron: trabajo rehecho dos veces, un sprint marcado
> "SKIPPED" mientras otra sesión lo completaba, y tests borrados/debilitados
> para forzar el CI en verde. Este doc evita que se repita.

**Última actualización:** 2026-07-21 12:47 (America/Guayaquil)

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
- **Sprint 4 (Invoice Spreadsheet UX)** ❌ PENDIENTE — es HIGH y lo pidió el
  usuario; se saltó. Es el siguiente objetivo real.
- **Deuda de calidad ABIERTA:** los tests a11y borrados/debilitados se están
  restaurando y arreglando de verdad (tarea en curso). No los vuelvas a mutear.

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
