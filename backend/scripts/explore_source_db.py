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
from sqlalchemy.engine import URL, make_url
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


def build_url() -> str:
    """Arma la URL desde el entorno, aceptando dos formatos.

    Si existe ``PROSPECT_SOURCE_URL`` se usa tal cual. Si no, se arma con las
    variables sueltas (HOST, PORT, USER, PASSWORD, DATABASE), que es como las
    entrega un archivo de credenciales típico.

    Se usa ``URL.create`` en vez de concatenar texto a propósito: una
    contraseña con ``@``, ``/`` o ``#`` rompe una URL construida a mano, y el
    error se ve como "credenciales inválidas" en vez de como lo que es.
    """
    direct = os.environ.get("PROSPECT_SOURCE_URL")
    if direct:
        return direct

    host = os.environ.get("HOST")
    user = os.environ.get("USER_DB") or os.environ.get("USER")
    password = os.environ.get("PASSWORD")
    database = os.environ.get("DATABASE")
    if not all((host, user, password, database)):
        sys.exit(
            "Faltan datos de conexión.\n"
            "Carga el archivo de credenciales antes de correr el script:\n"
            "  set -a && source ../base_maestra-local-readonly.env && set +a"
        )

    port_raw = os.environ.get("PORT") or "5432"
    return URL.create(
        drivername="postgresql+asyncpg",
        username=user,
        password=password,
        host=host,
        port=int(port_raw),
        database=database,
    ).render_as_string(hide_password=False)


def connect_args() -> dict[str, object]:
    """TLS según SSL_MODE. asyncpg lo recibe como parámetro de conexión."""
    mode = (os.environ.get("SSL_MODE") or "").strip().lower()
    if mode in {"require", "verify-ca", "verify-full", "prefer", "allow"}:
        return {"ssl": mode}
    if mode in {"disable", "false", "off"}:
        return {"ssl": False}
    return {}


def target_schema() -> str | None:
    """Esquema a inspeccionar. Sin él se lee el de por defecto (public)."""
    value = (os.environ.get("SCHEMA") or "").strip()
    return value or None


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


async def _column_names(
    conn: AsyncConnection, table_name: str, schema: str | None
) -> list[str]:
    columns = await conn.run_sync(
        lambda sync: inspect(sync).get_columns(table_name, schema=schema)  # noqa: B023
    )
    return [str(column["name"]) for column in columns]


async def inventory(url_string: str) -> None:
    schema = target_schema()
    engine = create_async_engine(url_string, pool_pre_ping=True, connect_args=connect_args())
    try:
        async with engine.connect() as conn:
            await _statement_timeout(conn, url_string)
            tables = await conn.run_sync(
                lambda sync: inspect(sync).get_table_names(schema=schema)
            )

            print(f"\nConexión: {_redact(url_string)}" + (f"  esquema: {schema}" if schema else ""))
            print(f"Tablas encontradas: {len(tables)}\n")
            print(f"{'TABLA':<40} {'FILAS':>12}  COLUMNAS")
            print("-" * 72)

            for name in sorted(tables):
                try:
                    total = await conn.scalar(
                        select(func.count()).select_from(sa_table(name, schema=schema))
                    )
                except Exception:
                    total = None
                columns = await _column_names(conn, name, schema)
                shown = ", ".join(columns[:6]) + ("…" if len(columns) > 6 else "")
                print(f"{name:<40} {total if total is not None else '?':>12}  {shown}")

            print(
                "\nSiguiente paso: elige una tabla y perfílala con"
                "\n  uv run --frozen python scripts/explore_source_db.py --table NOMBRE"
            )
    finally:
        await engine.dispose()


async def profile_table(url_string: str, table_name: str) -> None:
    schema = target_schema()
    engine = create_async_engine(url_string, pool_pre_ping=True, connect_args=connect_args())
    try:
        async with engine.connect() as conn:
            await _statement_timeout(conn, url_string)
            known = await conn.run_sync(
                lambda sync: inspect(sync).get_table_names(schema=schema)
            )
            if table_name not in known:
                sys.exit(
                    f"La tabla '{table_name}' no existe en el esquema.\n"
                    "Corre el inventario primero para ver los nombres disponibles."
                )
            columns = await conn.run_sync(
                lambda sync: inspect(sync).get_columns(table_name, schema=schema)  # noqa: B023
            )

            quote = conn.dialect.identifier_preparer.quote
            qualified = f"{quote(schema)}.{quote(table_name)}" if schema else quote(table_name)
            source = sa_table(table_name, schema=schema)
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
                        text(f"SELECT COUNT({qcol}) FROM {qualified}")  # nosec B608
                    ) or 0
                    distinct = await conn.scalar(
                        text(f"SELECT COUNT(DISTINCT {qcol}) FROM {qualified}")  # nosec B608
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
                        text(
                            f"SELECT DISTINCT {qcol} FROM {qualified} "  # nosec B608
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

    url_string = build_url()

    if args.table:
        asyncio.run(profile_table(url_string, args.table))
    else:
        asyncio.run(inventory(url_string))


if __name__ == "__main__":
    main()
