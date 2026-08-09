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
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

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
TOKEN_ENDPOINT = "https://iaerp-auth.b2b.com.ec/realms/iaerp/protocol/openid-connect/token"


class ServiceAccountToken:
    """Obtiene y renueva el token de la cuenta de servicio de prospección."""

    def __init__(self, client_id: str, client_secret: str) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token: str | None = None
        self.expires_at = 0.0

    async def get(self, client: httpx.AsyncClient, *, refresh: bool = False) -> str:
        if not refresh and self.access_token and time.monotonic() < self.expires_at:
            return self.access_token
        response = await client.post(
            TOKEN_ENDPOINT,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
        )
        response.raise_for_status()
        payload = response.json()
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise RuntimeError("El proveedor de identidad no devolvió access_token")
        expires_in = payload.get("expires_in")
        if not isinstance(expires_in, int) or expires_in <= 0:
            raise RuntimeError("El proveedor de identidad no devolvió expires_in válido")
        self.access_token = token
        # Se renueva antes de vencer para que una carga larga no quede a mitad de petición.
        self.expires_at = time.monotonic() + max(1, expires_in - 30)
        return token

    async def request(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> httpx.Response:
        async def send(*, refresh: bool) -> httpx.Response:
            token = await self.get(client, refresh=refresh)
            headers = dict(kwargs.get("headers", {}))
            headers["Authorization"] = f"Bearer {token}"
            return await client.request(method, path, **{**kwargs, "headers": headers})

        response = await send(refresh=False)
        return await send(refresh=True) if response.status_code == 401 else response

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

# Texto exacto que el propio export escribe en la columna ``nota``. Se compara
# contra este literal en vez de contra "hay algo escrito": el CSV está pensado
# para editarse a mano, y una anotación como "no contesta" no debe convertir a
# un prospecto normal en sospechoso de competencia.
NOTA_COMPETENCIA = "revisar si es competencia"


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


def assign_schedule(targets: list[dict[str, object]]) -> list[datetime]:
    """Fecha de primer contacto de cada fila.

    Si el CSV trae ``contactar`` se respeta: es el plan que la persona pudo
    haber reordenado a mano y recalcularlo desde mañana lo descartaba en
    silencio. Lo demás se reparte a 3 por día hábil.
    """
    start = datetime.now(UTC).replace(hour=13, minute=0, second=0, microsecond=0)
    computed = business_days(start + timedelta(days=1), len(targets))
    return [
        planned if isinstance((planned := row.get("contactar")), datetime) else fallback
        for row, fallback in zip(targets, computed, strict=True)
    ]


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


def _csv_prioridad(row: dict[str, str]) -> int:
    """Prioridad de una fila del CSV.

    La columna explícita manda. Los CSV exportados antes de que existiera no
    la tienen, así que se cae al marcador exacto que escribe el export; una
    nota escrita a mano no debe marcar competencia.
    """
    declared = (row.get("prioridad") or "").strip()
    if declared.isdigit():
        return int(declared)
    return 3 if (row.get("nota") or "").strip().lower() == NOTA_COMPETENCIA else 1


def _csv_contactar(row: dict[str, str]) -> datetime | None:
    """Fecha planificada de la fila, si el CSV la trae y es legible."""
    raw = (row.get("contactar") or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).replace(tzinfo=UTC, hour=13, minute=0, second=0)
    except ValueError:
        return None


def targets_from_csv(path: str) -> list[dict[str, object]]:
    """Lee una lista ya exportada con ``--export``.

    Evita depender de la base de empresas en cada corrida: esa conexión es de
    red local y macOS la bloquea de forma intermitente, lo que dejaba la rutina
    diaria a merced de un permiso del sistema. El CSV ya viene en el orden de
    prioridad, así que se respeta tal cual.
    """
    with open(path, encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [
        {
            "ruc": (row.get("ruc") or "").strip(),
            "nombre_compania": row.get("empresa") or "",
            "correo_electronico": row.get("correo") or "",
            "telefono": row.get("telefono") or "",
            "empleados": row.get("empleados") or "",
            "provincia": row.get("provincia") or "",
            "ciiu_codigo_n6": row.get("ciiu") or "",
            "prioridad": _csv_prioridad(row),
            "segmento": (row.get("segmento") or "").strip() or None,
            "contactar": _csv_contactar(row),
        }
        for row in rows
        if (row.get("ruc") or "").strip()
    ]


def segment_from_csv(targets: list[dict[str, object]], explicit: str | None) -> str:
    """Resuelve el segmento de una lista leída de CSV.

    El guion de primer contacto depende del segmento: cargar `educacion.csv`
    sin decirlo escribía el discurso de AWS a universidades. Antes esto no
    fallaba porque ``--segment`` caía a ``isv`` en silencio.
    """
    declared = {str(row["segmento"]) for row in targets if row.get("segmento")}
    if len(declared) > 1:
        sys.exit(f"El CSV mezcla segmentos ({', '.join(sorted(declared))}); sepáralos.")
    if declared:
        segmento = declared.pop()
        if segmento not in SEGMENTS:
            sys.exit(f"Segmento desconocido en el CSV: {segmento}")
        if explicit and explicit != segmento:
            sys.exit(f"El CSV dice '{segmento}' y --segment dice '{explicit}'.")
        return segmento
    if not explicit:
        sys.exit(
            "El CSV no tiene columna 'segmento'. Indica --segment "
            f"({'/'.join(sorted(SEGMENTS))}) para saber qué guion escribir."
        )
    return explicit


LEADS_PAGE_SIZE = 200
# Techo de seguridad: si el servidor devolviera páginas llenas indefinidamente,
# la recorrida no debe quedarse girando.
LEADS_MAX_PAGES = 50


async def existing_rucs(client: httpx.AsyncClient, token: ServiceAccountToken) -> set[str]:
    """RUCs que ya están en el CRM, para no duplicar en una segunda corrida.

    Recorre todas las páginas. Con una sola petición el endpoint devolvía como
    mucho 100 leads, así que pasado ese punto la deduplicación dejaba de ver
    los leads más antiguos y la recorrida los reportaba como fallas (la unicidad
    de ``Party`` por RUC hace que el alta responda 409).
    """
    found: set[str] = set()
    for page in range(LEADS_MAX_PAGES):
        response = await token.request(
            client,
            "GET",
            f"/api/v1/crm/leads?limit={LEADS_PAGE_SIZE}&offset={page * LEADS_PAGE_SIZE}",
        )
        response.raise_for_status()
        batch = response.json()
        for lead in batch:
            party = lead.get("party") or {}
            number = party.get("identificationNumber")
            if number:
                found.add(str(number))
        if len(batch) < LEADS_PAGE_SIZE:
            break
    return found


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--segment",
        choices=sorted(SEGMENTS),
        default=None,
        help="isv = empresas de software (perfil Trantotech/Infinit); "
        "educacion = instituciones educativas (perfil U. Andina). "
        "Con --from-csv se toma del CSV si trae la columna 'segmento'.",
    )
    parser.add_argument("--apply", action="store_true", help="Escribir en el CRM")
    parser.add_argument(
        "--export",
        metavar="RUTA.csv",
        help="Escribir la lista a un CSV para trabajarla a mano (no toca el CRM)",
    )
    parser.add_argument("--limit", type=int, help="Cargar solo las primeras N")
    parser.add_argument(
        "--from-csv",
        metavar="RUTA.csv",
        help="Leer una lista ya exportada en vez de consultar la base de empresas",
    )
    args = parser.parse_args()

    base_url = os.environ.get("PROSPECT_CRM_URL")
    client_id = os.environ.get("PROSPECT_CRM_CLIENT_ID")
    client_secret = os.environ.get("PROSPECT_CRM_CLIENT_SECRET")
    if args.apply and not (base_url and client_id and client_secret):
        sys.exit(
            "Para --apply hacen falta PROSPECT_CRM_URL, PROSPECT_CRM_CLIENT_ID y "
            "PROSPECT_CRM_CLIENT_SECRET en backend/.env.\n"
            "Crea una cuenta de servicio con scopes leads:read y leads:write."
        )

    if args.from_csv:
        targets = targets_from_csv(args.from_csv)
        segment = segment_from_csv(targets, args.segment)
    else:
        # El camino de base de datos conserva el valor de siempre.
        segment = args.segment or "isv"
        targets = await fetch_targets(segment)
    if args.limit:
        targets = targets[: args.limit]

    schedule = assign_schedule(targets)

    print(f"\nSegmento: {segment}   Empresas objetivo: {len(targets)}")
    dias = len({d.date() for d in schedule})
    print(f"A {CONTACTS_PER_DAY} por día hábil = {dias} días de trabajo\n")

    if args.export:
        # El correo del registro es INSTITUCIONAL (info@, gerencia@), no el de
        # una persona. Se exporta tal cual para poder escribir hoy, pero la
        # respuesta esperada es menor que la de un contacto con nombre.
        with open(args.export, "w", newline="", encoding="utf-8-sig") as handle:  # noqa: ASYNC230
            writer = csv.writer(handle)
            # `segmento` y `prioridad` van explícitas: deducirlas del texto de
            # la nota al releer el CSV escribía el guion equivocado y marcaba
            # como competencia a cualquiera con una anotación a mano.
            writer.writerow(
                ["contactar", "empresa", "correo", "telefono", "empleados",
                 "provincia", "ruc", "ciiu", "segmento", "prioridad", "nota"]
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
                    segment,
                    row["prioridad"],
                    NOTA_COMPETENCIA if row["prioridad"] == 3 else "",
                ])
        print(f"Exportadas {len(targets)} empresas a {args.export}")
        return

    if not args.apply:
        print(f"{'EMPRESA':<42}{'EMPL':>6}  {'PROVINCIA':<13}{'CONTACTAR':<12}NOTA")
        print("-" * 100)
        for row, when in list(zip(targets, schedule, strict=True))[:15]:
            name = repair(str(row["nombre_compania"]))[:40]
            nota = NOTA_COMPETENCIA if row["prioridad"] == 3 else ""
            print(
                f"{name:<42}{row['empleados'] or 0:>6}  "
                f"{repair(str(row['provincia']))[:11]:<13}{str(when.date()):<12}{nota}"
            )
        if len(targets) > 15:
            print(f"... y {len(targets) - 15} más")
        print("\nPREVIO — no se escribió nada. Agrega --apply para cargar.")
        return

    assert base_url and client_id and client_secret  # garantizado por la validación de arriba
    token = ServiceAccountToken(client_id, client_secret)
    async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:
        already = await existing_rucs(client, token)
        # El calendario se reparte SOBRE LO QUE FALTA. Repartirlo antes y luego
        # saltarse los ya cargados dejaba el turno perdido, así que en una
        # segunda corrida los primeros días quedaban vacíos y se rompía el
        # "3 por día hábil".
        pending = [row for row in targets if str(row["ruc"]).strip() not in already]
        skipped = len(targets) - len(pending)
        schedule = assign_schedule(pending)
        created = failed = 0
        if skipped:
            print(f"{skipped} ya estaban en el CRM; se reparten los {len(pending)} restantes.\n")

        for row, when in zip(pending, schedule, strict=True):
            ruc = str(row["ruc"]).strip()
            name = repair(str(row["nombre_compania"]))
            try:
                lead = await token.request(
                    client,
                    "POST",
                    "/api/v1/crm/leads/with-party",
                    headers={"Idempotency-Key": f"prospect-lead-{uuid.uuid4()}"},
                    json={
                        "partyName": name,
                        "partyIdentificationType": "RUC",
                        "partyIdentificationNumber": ruc,
                        "partyEmail": str(row["correo_electronico"] or "") or None,
                        "partyPhone": str(row["telefono"] or "") or None,
                        "title": (
                            f"Brazo de AWS — {name}"
                            if segment == "isv"
                            else f"Seguridad gestionada — {name}"
                        ),
                        "source": "REGISTRO_SOCIETARIO",
                        "hotness": "COLD",
                    },
                )
                # ``Party`` es único por (tenant, tipo, número), así que el RUC
                # repetido responde 409. Es la red que aguanta aunque la lista
                # de deduplicación venga incompleta: ya existe, no es una falla.
                if lead.status_code == 409:
                    skipped += 1
                    continue
                lead.raise_for_status()
                lead_id = lead.json()["id"]

                # La tarea con fecha es lo que hace que el CRM sepa qué toca hoy.
                # Un lead sin próximo paso con fecha es un lead que se pierde.
                activity = await token.request(
                    client,
                    "POST",
                    f"/api/v1/crm/leads/{lead_id}/activities",
                    headers={"Idempotency-Key": f"prospect-activity-{uuid.uuid4()}"},
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
                            + PITCH[segment]
                        ),
                        "outcome": "PENDING",
                        "reminderDate": when.isoformat(),
                    },
                )
                activity.raise_for_status()
                created += 1
            except httpx.HTTPError as exc:
                failed += 1
                print(f"  falló {ruc}: {exc}")

        print(f"\nCreados: {created}   Ya existían: {skipped}   Fallaron: {failed}")


if __name__ == "__main__":
    asyncio.run(main())
