"""Carga la lista objetivo al CRM con el trabajo ya repartido por día.

El pipeline no debería vivir en una hoja suelta: el trabajo del día tiene que
estar EN el sistema. Este script toma las empresas candidatas del registro
societario público y crea un lead por cada una, con una tarea inicial cuya
``reminderDate`` está escalonada — 3 por día hábil.

Así, cada mañana el CRM ya sabe qué toca: no hace falta que nadie lo recuerde
ni que alguien lo dicte.

Reglas:

- **Solo `stg.cia`**, el registro societario público (RUC, razón social, CIIU,
  empleados, contacto institucional). NUNCA ``master.clientes`` ni ninguna tabla
  que una empresa y persona por cédula.
- **Previo por defecto.** Sin ``--apply`` no escribe nada en el CRM: imprime lo
  que haría. Cargar 131 leads a producción sin verlos antes no se deshace fácil.
- **Idempotente por RUC.** Si el lead ya existe no lo duplica, porque este
  script se va a correr más de una vez.

Uso:

    # Ver qué se cargaría (no escribe)
    uv run --frozen python scripts/load_prospects_to_crm.py

    # Cargar de verdad
    uv run --frozen python scripts/load_prospects_to_crm.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

# Empresas vigentes de tecnología con equipo real y dominio propio: el segmento
# más caliente para servicios AWS (ver docs/PLAN_PRIMER_CLIENTE_AWS.md).
QUERY = """
SELECT ruc, nombre_compania, correo_electronico, telefono,
       provincia, canton, ciiu_codigo_n6,
       NULLIF(regexp_replace(COALESCE(empleados,''),'[^0-9]','','g'),'')::bigint AS empleados
FROM stg.cia
WHERE fecha_cancelacion = '0000-00-00'
  AND ciiu_codigo_n6 ~ '^(J62|J63)'
  AND NULLIF(regexp_replace(COALESCE(empleados,''),'[^0-9]','','g'),'')::bigint >= 10
  AND COALESCE(correo_electronico,'') <> ''
  AND lower(split_part(correo_electronico,'@',2)) NOT IN
      ('gmail.com','hotmail.com','yahoo.com','outlook.com','hotmail.es','yahoo.es','live.com','icloud.com')
ORDER BY empleados DESC NULLS LAST
"""

CONTACTS_PER_DAY = 3


def repair(value: str | None) -> str:
    """Repara el mojibake de la carga original.

    El texto se guardó como UTF-8 leído como Latin-1 (``DISEÃâO`` por
    ``DISEÑO``). Afecta al 4,7% de los nombres. Revertirlo es volver a
    codificar en Latin-1 y decodificar como UTF-8; si no aplica, se deja igual.
    """
    if not value:
        return ""
    if "Ã" not in value and "Â" not in value:
        return value.strip()
    try:
        return value.encode("latin-1").decode("utf-8").strip()
    except (UnicodeDecodeError, UnicodeEncodeError):
        return value.strip()


def business_days(start: datetime, count: int) -> list[datetime]:
    """Reparte ``count`` contactos a razón de 3 por día hábil.

    Se saltan sábados y domingos: una tarea que vence el domingo no se hace el
    domingo, se acumula y ensucia la lista del lunes.
    """
    dates: list[datetime] = []
    day = start
    while len(dates) < count:
        if day.weekday() < 5:
            for _ in range(CONTACTS_PER_DAY):
                if len(dates) < count:
                    dates.append(day)
        day += timedelta(days=1)
    return dates


async def fetch_targets() -> list[dict[str, object]]:
    url = URL.create(
        drivername="postgresql+asyncpg",
        username=os.environ["USER"],
        password=os.environ["PASSWORD"],
        host=os.environ["HOST"],
        port=int(os.environ.get("PORT", "5432")),
        database=os.environ["DATABASE"],
    )
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SET statement_timeout = '120s'"))
            rows = await conn.execute(text(QUERY))
            return [dict(row._mapping) for row in rows]
    finally:
        await engine.dispose()


async def existing_rucs(client: httpx.AsyncClient) -> set[str]:
    """RUCs que ya están en el CRM, para no duplicar en una segunda corrida."""
    response = await client.get("/api/v1/crm/leads")
    response.raise_for_status()
    found: set[str] = set()
    for lead in response.json():
        party = lead.get("party") or {}
        number = party.get("identificationNumber")
        if number:
            found.add(str(number))
    return found


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Escribir en el CRM")
    parser.add_argument("--limit", type=int, help="Cargar solo las primeras N")
    args = parser.parse_args()

    base_url = os.environ.get("PROSPECT_CRM_URL")
    token = os.environ.get("PROSPECT_CRM_TOKEN")
    if args.apply and not (base_url and token):
        sys.exit(
            "Para --apply hacen falta PROSPECT_CRM_URL y PROSPECT_CRM_TOKEN en backend/.env.\n"
            "Crea una cuenta de servicio con scopes leads:read y leads:write."
        )

    targets = await fetch_targets()
    if args.limit:
        targets = targets[: args.limit]

    start = datetime.now(UTC).replace(hour=13, minute=0, second=0, microsecond=0)
    schedule = business_days(start + timedelta(days=1), len(targets))

    print(f"\nEmpresas objetivo: {len(targets)}")
    dias = len({d.date() for d in schedule})
    print(f"A {CONTACTS_PER_DAY} por día hábil = {dias} días de trabajo\n")

    if not args.apply:
        print(f"{'EMPRESA':<44}{'EMPL':>6}  {'PROVINCIA':<14}CONTACTAR")
        print("-" * 92)
        for row, when in list(zip(targets, schedule, strict=True))[:15]:
            name = repair(str(row["nombre_compania"]))[:42]
            print(
                f"{name:<44}{row['empleados'] or 0:>6}  "
                f"{repair(str(row['provincia']))[:12]:<14}{when.date()}"
            )
        if len(targets) > 15:
            print(f"... y {len(targets) - 15} más")
        print("\nPREVIO — no se escribió nada. Agrega --apply para cargar.")
        return

    assert base_url and token  # garantizado por la validación de arriba
    async with httpx.AsyncClient(
        base_url=base_url, headers={"Authorization": f"Bearer {token}"}, timeout=30
    ) as client:
        already = await existing_rucs(client)
        created = skipped = failed = 0

        for row, when in zip(targets, schedule, strict=True):
            ruc = str(row["ruc"]).strip()
            if ruc in already:
                skipped += 1
                continue
            name = repair(str(row["nombre_compania"]))
            try:
                lead = await client.post(
                    "/api/v1/crm/leads/with-party",
                    json={
                        "partyName": name,
                        "partyIdentificationType": "RUC",
                        "partyIdentificationNumber": ruc,
                        "partyEmail": str(row["correo_electronico"] or "") or None,
                        "partyPhone": str(row["telefono"] or "") or None,
                        "title": f"Revisión AWS — {name}",
                        "source": "REGISTRO_SOCIETARIO",
                        "hotness": "COLD",
                    },
                )
                lead.raise_for_status()
                lead_id = lead.json()["id"]

                # La tarea con fecha es lo que hace que el CRM sepa qué toca hoy.
                # Un lead sin próximo paso con fecha es un lead que se pierde.
                await client.post(
                    f"/api/v1/crm/leads/{lead_id}/activities",
                    json={
                        "leadId": lead_id,
                        "activityType": "TASK",
                        "subject": "Primer contacto: ofrecer revisión de costo AWS",
                        "description": (
                            f"{row['empleados'] or '?'} empleados · {row['provincia']} · "
                            f"CIIU {row['ciiu_codigo_n6']}\n\n"
                            "Pedir la factura de AWS del último mes (NO acceso a la cuenta)."
                        ),
                        "outcome": "PENDING",
                        "reminderDate": when.isoformat(),
                    },
                )
                created += 1
            except httpx.HTTPError as exc:
                failed += 1
                print(f"  falló {ruc}: {exc}")

        print(f"\nCreados: {created}   Ya existían: {skipped}   Fallaron: {failed}")


if __name__ == "__main__":
    asyncio.run(main())
