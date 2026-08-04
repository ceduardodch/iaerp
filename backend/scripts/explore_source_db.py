"""Explora una BD de origen en SOLO LECTURA, sin sacar datos personales.

Para decidir un cruce hay que conocer el esquema: qué tablas hay, qué columnas,
cuántas filas y qué tan completo viene cada campo. Eso se puede saber sin mirar
un solo dato de una persona real.

Cómo protege los datos:

- **Nunca imprime la cadena de conexión** (lleva la contraseña dentro).
- **Columnas que parecen personales** (correo, teléfono, nombre, dirección,
  identificación, clave) reportan solo completitud y cantidad de valores
  distintos. Sus valores NO se muestran jamás.
- Del resto muestra ejemplos solo si tienen pocos valores distintos, que es
  donde el ejemplo enseña algo (un estado, un tipo) y no expone a nadie.
- Solo emite ``SELECT`` y reflexión de esquema. No escribe.

Uso:

    # 1. Inventario: qué tablas hay y de qué tamaño
    uv run --frozen python scripts/explore_source_db.py

    # 2. Perfil de una tabla concreta
    uv run --frozen python scripts/explore_source_db.py --table empresas
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys

from sqlalchemy import func, inspect, select, text
from sqlalchemy import table as sa_table
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

# Columnas cuyo CONTENIDO no se muestra nunca. Se detectan por nombre porque es
# lo único que se conoce antes de leer. Ante la duda, se oculta: el costo de
# ocultar de más es no ver un ejemplo; el de mostrar de menos es filtrar datos
# de una persona a la terminal y a los logs.
SENSITIVE = re.compile(
    r"mail|correo|phone|telef|celul|movil|nombre|name|apellid|lastname|"
    # En una persona natural la razon social ES el nombre de la persona.
    r"razon|contribuyente|titular|representante|"
    r"direcc|address|domicil|cedul|ruc|identific|dni|pasaport|"
    r"password|clave|secret|token|key|hash|tarjeta|cuenta|iban",
    re.IGNORECASE,
)

MAX_DISTINCT_TO_SHOW = 12


def _redact(url_string: str) -> str:
    """Describe la conexión sin revelar credenciales."""
    url = make_url(url_string)
    return f"{url.drivername} → {url.host or 'local'}/{url.database or '?'}"


async def _statement_timeout(conn: AsyncConnection, url_string: str) -> None:
    """Evita que un COUNT sobre una tabla enorme cuelgue la sesión."""
    if "postgresql" in url_string:
        await conn.execute(text("SET statement_timeout = '30s'"))
        # Refuerzo de solo lectura a nivel de sesión: aunque el script solo
        # emite SELECT, el motor rechaza cualquier escritura por accidente.
        await conn.execute(text("SET default_transaction_read_only = on"))


async def _column_names(conn: AsyncConnection, table_name: str) -> list[str]:
    columns = await conn.run_sync(
        lambda sync: inspect(sync).get_columns(table_name)  # noqa: B023
    )
    return [str(column["name"]) for column in columns]


async def inventory(url_string: str) -> None:
    engine = create_async_engine(url_string, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            await _statement_timeout(conn, url_string)
            tables = await conn.run_sync(lambda sync: inspect(sync).get_table_names())

            print(f"\nConexión: {_redact(url_string)}")
            print(f"Tablas encontradas: {len(tables)}\n")
            print(f"{'TABLA':<40} {'FILAS':>12}  COLUMNAS")
            print("-" * 72)

            for name in sorted(tables):
                try:
                    total = await conn.scalar(select(func.count()).select_from(sa_table(name)))
                except Exception:
                    total = None
                columns = await _column_names(conn, name)
                shown = ", ".join(columns[:6]) + ("…" if len(columns) > 6 else "")
                print(f"{name:<40} {total if total is not None else '?':>12}  {shown}")

            print(
                "\nSiguiente paso: elige una tabla y perfílala con"
                "\n  uv run --frozen python scripts/explore_source_db.py --table NOMBRE"
            )
    finally:
        await engine.dispose()


async def profile_table(url_string: str, table_name: str) -> None:
    engine = create_async_engine(url_string, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            await _statement_timeout(conn, url_string)
            known = await conn.run_sync(lambda sync: inspect(sync).get_table_names())
            if table_name not in known:
                sys.exit(
                    f"La tabla '{table_name}' no existe en el esquema.\n"
                    "Corre el inventario primero para ver los nombres disponibles."
                )
            columns = await conn.run_sync(
                lambda sync: inspect(sync).get_columns(table_name)  # noqa: B023
            )

            quote = conn.dialect.identifier_preparer.quote
            qualified = quote(table_name)
            source = sa_table(table_name)
            total = await conn.scalar(select(func.count()).select_from(source)) or 0
            print(f"\nTabla: {table_name}   ({total} filas)")
            print("=" * 78)
            print(f"{'COLUMNA':<26} {'TIPO':<16} {'LLENO':>7} {'DISTINTOS':>10}  EJEMPLOS")
            print("-" * 78)

            for column in columns:
                name = str(column["name"])
                qcol = quote(name)
                try:
                    filled = await conn.scalar(
                        text(f"SELECT COUNT({qcol}) FROM {qualified}")  # noqa: S608
                    ) or 0
                    distinct = await conn.scalar(
                        text(f"SELECT COUNT(DISTINCT {qcol}) FROM {qualified}")  # noqa: S608
                    ) or 0
                except Exception:
                    filled, distinct = 0, 0

                share = f"{filled / total * 100:.0f}%" if total else "—"
                samples = ""

                if SENSITIVE.search(name):
                    # Dato personal: se reporta que existe y qué tan completo
                    # está, nunca lo que contiene.
                    samples = "· oculto (dato personal) ·"
                elif 0 < distinct <= MAX_DISTINCT_TO_SHOW:
                    rows = await conn.execute(
                        text(  # noqa: S608
                            f"SELECT DISTINCT {qcol} FROM {qualified} "
                            f"WHERE {qcol} IS NOT NULL LIMIT {MAX_DISTINCT_TO_SHOW}"
                        )
                    )
                    values = [str(r[0])[:18] for r in rows]
                    samples = ", ".join(values)

                print(
                    f"{name[:25]:<26} {str(column['type'])[:15]:<16} "
                    f"{share:>7} {distinct:>10}  {samples[:30]}"
                )

            print(
                "\nLas columnas marcadas como dato personal existen y se pueden usar,"
                "\npero su contenido no se imprime para no dejarlo en la terminal."
            )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", help="Perfilar una tabla concreta")
    args = parser.parse_args()

    url_string = os.environ.get("PROSPECT_SOURCE_URL")
    if not url_string:
        sys.exit(
            "Falta PROSPECT_SOURCE_URL.\n"
            "Ponla en backend/.env (ya ignorado por git) con un usuario de SOLO LECTURA."
        )

    if args.table:
        asyncio.run(profile_table(url_string, args.table))
    else:
        asyncio.run(inventory(url_string))


if __name__ == "__main__":
    main()
