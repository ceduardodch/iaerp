# Nómina — pendientes

Lista ordenada del módulo de nómina. **Una corrida toma solo el primer pendiente
sin marcar**, lo termina completo y lo marca. Ver las reglas al final.

## Cifras legales vigentes (2026)

No investigar de nuevo: están verificadas contra fuente oficial.

| Concepto | Valor | Regla |
|---|---|---|
| SBU | $482,00 | Acuerdo Ministerial MDT-2025-195, desde el 1-ene-2026 |
| SBU 2025 | $470,00 | Para periodos del año anterior |
| Aporte personal IESS | 9,45% | Sobre la remuneración imponible |
| Fondos de reserva | 8,33% | **Solo desde el mes 13** de servicio |
| Décimo tercero | imponible ÷ 12 | Mensualizado, o acumulado hasta el 24-dic |
| Décimo cuarto | SBU ÷ 12 | Mensualizado, o acumulado hasta el 15-ago (Sierra/Amazonía) o 15-mar (Costa/Insular) |

**Los décimos y los fondos de reserva NO entran a la base del aporte IESS.**

## Pendientes

- [x] Parámetros por año (SBU y tasas) y pruebas de reglas legales
- [x] Cálculo puro del rol en `services/payroll/calculations.py`
- [x] Modelos `payroll_employees`, `payroll_periods`, `payroll_entries` y migración
- [ ] Servicio de empleados: alta, edición y baja
- [ ] Servicio de periodos: generar borrador idempotente y aprobar
- [ ] Endpoints `/payroll/*` con `execute_idempotent` y scopes `payroll:read` / `payroll:write`
- [ ] Registrar los scopes en `KNOWN_SCOPES`, `iaerp-realm.json` y `configure-staging.sh`
- [ ] `run_payroll_scheduler()` en el `TaskGroup` de `workers/dispatcher.py`
- [ ] Tipos y cliente en `frontend/src/api.ts`
- [ ] Pantalla `PayrollPage.tsx` con pestañas Empleados y Roles
- [ ] Sección `payroll` en `Sidebar.tsx`, `App.tsx` y `tests/navigation.ts`
- [ ] E2E `frontend/tests/payroll.spec.ts`

## Reglas de cada corrida

1. Tomar **solo el primer pendiente sin marcar**. No adelantar los siguientes.
2. Escribir su prueba primero y **verificarla revirtiendo el arreglo**: si no
   falla al revertir, la prueba no sirve.
3. Correr `uv run ruff check .`, `uv run mypy app` y las pruebas del área. En
   frontend además `npx tsc --noEmit`, `npm run lint` y `npm run build`.
4. Commitear en `main`, empujar y **esperar el CI**. Si el CI queda rojo,
   revertir el push y anotar el motivo aquí.
5. Marcar la casilla y anotar en una línea qué se hizo, con el hash del commit.
6. **Nunca modificar ni borrar `backend/tests/test_payroll_legal.py`.** Codifica
   las reglas legales; debilitarlo permitiría publicar un cálculo equivocado en
   verde. Si una de esas pruebas falla, el error está en el código nuevo.
7. Si el CI falla o una prueba no pasa **dos corridas seguidas**: apagar la
   tarea programada `nomina-loop`, escribir el motivo abajo y detenerse.

## Bitácora

- Parámetros y pruebas legales: SBU por año en `services/payroll/parameters.py`,
  con prueba que falla si el año en curso no está registrado.
- Cálculo puro del rol, con las cinco reglas legales cubiertas.
- Modelos y migración: `payroll_employees`, `payroll_periods` (único por
  tenant/año/mes) y `payroll_entries` (mapeo directo de `RolCalculado`,
  único por tenant/periodo/empleado) en commit `176c4d4`, con fix de
  detect-secrets en `2e76127`. Esta corrida solo verificó (migración aplica
  contra Postgres real, 19 pruebas verdes, ruff y mypy limpios) y marcó la
  casilla que había quedado sin actualizar. CI de esta corrida (commit
  `db0a7b0`, run 32580761487) quedó verde — primera confirmación real del
  fix de detect-secrets, cuyo propio run se había cancelado antes por un
  push posterior.
