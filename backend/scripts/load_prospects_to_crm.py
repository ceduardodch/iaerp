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
import csv
import os
import sys
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

_EMP = "NULLIF(regexp_replace(COALESCE(empleados,''),'[^0-9]','','g'),'')::bigint"
_CORREO_PROPIO = (
    "COALESCE(correo_electronico,'') <> '' AND "
    "lower(split_part(correo_electronico,'@',2)) NOT IN "
    "('gmail.com','hotmail.com','yahoo.com','outlook.com',"
    "'hotmail.es','yahoo.es','live.com','icloud.com')"
)

# Dos negocios distintos, validados con los clientes actuales:
#
#   isv        Empresa de software que revende a clientes finales y no quiere
#              operar infraestructura. Es el perfil de Trantotech e Infinit.
#              Ingreso recurrente atado a su gasto en AWS.
#
#   educacion  Institución con superficie pública expuesta y bajo ataque. Es el
#              perfil de la Universidad Andina (WAF gestionado + pentesting).
#              Ticket mayor, pero depende de que estén doliéndose ahora.
#
# El ORDEN importa tanto como el filtro: la primera versión ordenaba por
# empleados descendente y ponía de primero a la empresa de 2.275 personas, que
# es el PEOR prospecto — a ese tamaño ya tienen equipo de nube propio y hasta
# pueden ser partners de AWS, o sea competencia. Se prioriza el punto dulce.
SEGMENTS: dict[str, dict[str, str]] = {
    "isv": {
        "where": f"ciiu_codigo_n6 ~ '^(J62|J63)' AND {_EMP} >= 10 AND {_CORREO_PROPIO}",
        # 1 = punto dulce (gasto real en AWS, sin nadie que lo optimice)
        # 2 = chicas   3 = grandes, revisar antes si son competencia
        "priority": f"CASE WHEN {_EMP} BETWEEN 30 AND 99 THEN 1 "
        f"WHEN {_EMP} < 30 THEN 2 ELSE 3 END",
    },
    "educacion": {
        "where": f"ciiu_codigo_n6 ~ '^P85' AND {_EMP} >= 25 AND {_CORREO_PROPIO}",
        "priority": "1",
    },
}

QUERY = """
SELECT ruc, nombre_compania, correo_electronico, telefono,
       provincia, canton, ciiu_codigo_n6,
       {emp} AS empleados,
       {priority} AS prioridad
FROM stg.cia
WHERE fecha_cancelacion = '0000-00-00' AND {where}
ORDER BY prioridad, {emp} DESC NULLS LAST
"""

CONTACTS_PER_DAY = 3

# Guion del primer contacto por segmento. El de ISV sale textual de cómo ya
# funciona con Trantotech e Infinit; no es una hipótesis de marketing.
PITCH = {
    "isv": (
        "Operamos el AWS de empresas de software que venden a sus clientes: "
        "ustedes construyen, nosotros corremos la infraestructura con guardias "
        "y control de costo.\n\n"
        "Pregunta de calificación: ¿cuánto pagan de AWS al mes? "
        "(referencia: Infinit $600, Trantotech $1.800)"
    ),
    # Los números salen del caso de éxito real de la UASB, no de un folleto.
    # El gancho es la ÚLTIMA pregunta: no la saben responder, y por eso piden
    # la reunión.
    "educacion": (
        "APERTURA:\n"
        "«110.000 ataques en un mes contra una universidad ecuatoriana, todos "
        "bloqueados antes de llegar al servidor. ¿Sabes cuántos está recibiendo "
        "la tuya?»\n\n"
        "RESPALDO: caso UASB — 110.000 ataques bloqueados en 30 días, 0 "
        "incidentes en producción, 40% menos superficie con geo-blocking. "
        "Testimonio de Juan Carlos Paladines, Coordinador de Infraestructura.\n\n"
        "PEDIR: una conversación sobre qué están viendo hoy en sus sistemas "
        "públicos. NO ofrecer pentesting en el primer contacto — eso viene "
        "después, cuando ya hay confianza.\n\n"
        "OJO: usar la versión PÚBLICA del caso, sin el subdominio ni la marca "
        "del firewall del cliente, y con la autorización escrita de la UASB."
    ),
}

# A este tamaño ya tienen equipo de nube propio y pueden ser partners de AWS.
# Se cargan igual, pero marcados: contactarlos como prospecto quema el nombre.
REVISAR_COMPETENCIA = (
    "VERIFICAR EN AWS PARTNER FINDER ANTES DE CONTACTAR. "
    "A este tamaño puede ser partner de AWS (competencia) o tener equipo "
    "propio. Si es partner, tratarlo como par para co-selling, no como "
    "prospecto."
)


def repair(value: str | None) -> str:
    """Repara el mojibake de la carga original.

    El texto se guardó como UTF-8 leído como Latin-1 (``DISEÃâO`` por
    ``DISEÑO``). Revertirlo es volver a codificar en Latin-1 y decodificar como
    UTF-8.

    Se intenta hasta dos veces porque hay filas con doble codificación
    (``COMPAÃ'IA``): una sola pasada las deja a medias. Y se prueba también
    ``cp1252``, que es donde caen los bytes 0x80-0x9F que Latin-1 no puede
    decodificar — sin eso, nombres con comillas o guiones tipográficos se
    quedaban rotos.
    """
    if not value:
        return ""
    text = value.strip()
    for _ in range(2):
        if "Ã" not in text and "Â" not in text:
            break
        for encoding in ("latin-1", "cp1252"):
            try:
                fixed = text.encode(encoding).decode("utf-8")
            except (UnicodeDecodeError, UnicodeEncodeError):
                continue
            if fixed != text:
                text = fixed
                break
        else:
            break
    return text.strip()


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


async def fetch_targets(segment: str) -> list[dict[str, object]]:
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
            spec = SEGMENTS[segment]
            rows = await conn.execute(
                text(QUERY.format(emp=_EMP, where=spec["where"], priority=spec["priority"]))
            )
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
    parser.add_argument(
        "--segment",
        choices=sorted(SEGMENTS),
        default="isv",
        help="isv = empresas de software (perfil Trantotech/Infinit); "
        "educacion = instituciones educativas (perfil U. Andina)",
    )
    parser.add_argument("--apply", action="store_true", help="Escribir en el CRM")
    parser.add_argument(
        "--export",
        metavar="RUTA.csv",
        help="Escribir la lista a un CSV para trabajarla a mano (no toca el CRM)",
    )
    parser.add_argument("--limit", type=int, help="Cargar solo las primeras N")
    args = parser.parse_args()

    base_url = os.environ.get("PROSPECT_CRM_URL")
    token = os.environ.get("PROSPECT_CRM_TOKEN")
    if args.apply and not (base_url and token):
        sys.exit(
            "Para --apply hacen falta PROSPECT_CRM_URL y PROSPECT_CRM_TOKEN en backend/.env.\n"
            "Crea una cuenta de servicio con scopes leads:read y leads:write."
        )

    targets = await fetch_targets(args.segment)
    if args.limit:
        targets = targets[: args.limit]

    start = datetime.now(UTC).replace(hour=13, minute=0, second=0, microsecond=0)
    schedule = business_days(start + timedelta(days=1), len(targets))

    print(f"\nSegmento: {args.segment}   Empresas objetivo: {len(targets)}")
    dias = len({d.date() for d in schedule})
    print(f"A {CONTACTS_PER_DAY} por día hábil = {dias} días de trabajo\n")

    if args.export:
        # El correo del registro es INSTITUCIONAL (info@, gerencia@), no el de
        # una persona. Se exporta tal cual para poder escribir hoy, pero la
        # respuesta esperada es menor que la de un contacto con nombre.
        with open(args.export, "w", newline="", encoding="utf-8-sig") as handle:  # noqa: ASYNC230
            writer = csv.writer(handle)
            writer.writerow(
                ["contactar", "empresa", "correo", "telefono", "empleados",
                 "provincia", "ruc", "ciiu", "nota"]
            )
            for row, when in zip(targets, schedule, strict=True):
                writer.writerow([
                    when.date(),
                    repair(str(row["nombre_compania"])),
                    row["correo_electronico"],
                    row["telefono"] or "",
                    row["empleados"] or "",
                    repair(str(row["provincia"])),
                    row["ruc"],
                    row["ciiu_codigo_n6"],
                    "revisar si es competencia" if row["prioridad"] == 3 else "",
                ])
        print(f"Exportadas {len(targets)} empresas a {args.export}")
        return

    if not args.apply:
        print(f"{'EMPRESA':<42}{'EMPL':>6}  {'PROVINCIA':<13}{'CONTACTAR':<12}NOTA")
        print("-" * 100)
        for row, when in list(zip(targets, schedule, strict=True))[:15]:
            name = repair(str(row["nombre_compania"]))[:40]
            nota = "revisar si es competencia" if row["prioridad"] == 3 else ""
            print(
                f"{name:<42}{row['empleados'] or 0:>6}  "
                f"{repair(str(row['provincia']))[:11]:<13}{str(when.date()):<12}{nota}"
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
                        "title": (
                            f"Brazo de AWS — {name}"
                            if args.segment == "isv"
                            else f"Seguridad gestionada — {name}"
                        ),
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
                        "subject": (
                            "REVISAR si es competencia antes de contactar"
                            if row["prioridad"] == 3
                            else "Primer contacto"
                        ),
                        "description": (
                            f"{row['empleados'] or '?'} empleados · {row['provincia']} · "
                            f"CIIU {row['ciiu_codigo_n6']}\n\n"
                            + (REVISAR_COMPETENCIA + "\n\n" if row["prioridad"] == 3 else "")
                            + PITCH[args.segment]
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
