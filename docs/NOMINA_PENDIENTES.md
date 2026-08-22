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
- [x] Servicio de empleados: alta, edición y baja
- [x] Servicio de periodos: generar borrador idempotente y aprobar
- [x] Endpoints `/payroll/*` con `execute_idempotent` y scopes `payroll:read` / `payroll:write`
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
- Servicio de empleados (alta, edición, baja) en `services/payroll/employees.py`,
  commit `ab41b9a`. `create_employee`/`update_employee` devuelven 409 claro
  ante identificación duplicada por tenant (constraint único, verificado
  contra Postgres real porque sqlite no expone `sqlstate` igual). La baja
  (`deactivate_employee`) es una transición de estado propia: fija
  `fecha_salida` y `active=False`, con 422 si la fecha es anterior al
  ingreso. `list_employees` excluye a los dados de baja. CI del run
  32581785053 quedó verde (Backend 14m4s, resto de jobs OK o gateados sin
  cambios en su área).
- Servicio de periodos (`services/payroll/periods.py`), commit `facc794`.
  `generate_draft_period` filtra empleados vigentes por fecha (no por
  `active`), para que quien sale a mitad de mes siga cobrando su
  proporcional ese mes y desaparezca el siguiente. Cada llamada borra y
  reinserta las entradas del periodo, así que repetirla no duplica filas
  (verificado revirtiendo el borrado: sin él, la segunda llamada rompe el
  único `tenant/periodo/empleado`). `approve_period` cierra el periodo;
  `generate_draft_period` rechaza regenerar uno ya aprobado con 409
  (verificado revirtiendo el guard). 39 pruebas del área verdes contra
  Postgres real (`TEST_DATABASE_URL=iaerp_test`), ruff y mypy limpios.
  Publicado en `origin/release`. Esta corrida detectó un `git merge
  origin/main` en curso del humano en el mismo checkout (commit `382967e`) y
  paró sin tocar `main` para no pisarlo. El humano ya integró `release` a
  `main` vía PR (#55/#56, merge `6593487`), así que `facc794` está en ambas
  ramas — sin acción pendiente de esta IA.
- Endpoints `/payroll/*` (`app/api/payroll.py`), commit `dda63b9`. Reutiliza
  los servicios ya probados sin tocar su lógica; las escrituras (alta/edición/
  baja de empleado, generar borrador, aprobar periodo) pasan por
  `execute_idempotent` igual que `payables.py`. `periods.py` ganó
  `list_periods`/`list_entries` porque no existía forma de leer periodos ni
  roles calculados y los `GET` los necesitan. Sumé `payroll:read`/
  `payroll:write` a `ALL_DEV_SCOPES` en `router.py`: sin eso el token de
  desarrollo no puede emitirlos y toda prueba HTTP falla en 403 al pedir el
  token, no en el endpoint. 10 pruebas nuevas en `test_payroll_api.py`
  (scopes, replay de `Idempotency-Key`, 409 por identificación duplicada y
  por regenerar un periodo aprobado), verificadas en rojo desregistrando el
  router del `main.py` (fallan en 404) antes de confirmarlas en verde. CI del
  run 32590851310 quedó verde tras un reintento: el primer intento falló solo
  en "Deploy production to Coolify" (el job de `Backend` con tests/ruff/mypy
  ya había quedado verde); construí y corrí la imagen Docker local para
  descartar causa en el código (arranca limpio, expone las rutas nuevas) y el
  rerun del job de despliegue quedó verde, confirmando que fue un blip
  transitorio de Coolify y no del cambio.
