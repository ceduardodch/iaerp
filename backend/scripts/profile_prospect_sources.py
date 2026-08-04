"""Perfila las fuentes de prospección SIN volcar datos personales.

Antes de cruzar dos bases hay que saber qué tiene cada una. Este script mira
ambas con la MISMA lente para que sean comparables, que es lo que hace posible
el cruce después.

Dos reglas que el script cumple siempre:

1. **No imprime datos personales.** Ni nombres, ni correos, ni teléfonos, ni
   RUCs completos. Solo agregados y conteos. Un perfilado que vuelca la base en
   pantalla deja los datos en logs y en el historial de la terminal.
2. **Solo lectura.** No escribe en ninguna de las dos fuentes.

Lo que se aprende del RUC sin llamar a nadie: los dos primeros dígitos son la
provincia y el tercero dice si es persona natural, sector público o sociedad.
Eso ya da una segmentación real de la cartera actual, que es la semilla del
perfil de cliente ideal.

Uso:

    # Perfilar los clientes propios del servicio de comprobantes
    FRACTALSOFT_API_URL=... FRACTALSOFT_ADMIN_KEY=... \\
        uv run --frozen python scripts/profile_prospect_sources.py --tenants

    # Perfilar un CSV exportado (Superintendencia, base comercial, lo que sea)
    uv run --frozen python scripts/profile_prospect_sources.py \\
        --csv ruta/al/archivo.csv --ruc-column RUC
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import Counter
from collections.abc import Iterable

import httpx

# Códigos de provincia del RUC (dos primeros dígitos). 30 es "exterior".
PROVINCES = {
    "01": "Azuay", "02": "Bolívar", "03": "Cañar", "04": "Carchi",
    "05": "Cotopaxi", "06": "Chimborazo", "07": "El Oro", "08": "Esmeraldas",
    "09": "Guayas", "10": "Imbabura", "11": "Loja", "12": "Los Ríos",
    "13": "Manabí", "14": "Morona Santiago", "15": "Napo", "16": "Pastaza",
    "17": "Pichincha", "18": "Tungurahua", "19": "Zamora Chinchipe",
    "20": "Galápagos", "21": "Sucumbíos", "22": "Orellana",
    "23": "Santo Domingo", "24": "Santa Elena", "30": "Exterior",
}


def normalize_ruc(raw: object) -> str | None:
    """Deja solo dígitos y valida longitud.

    Normalizar ANTES de comparar no es cosmético: el mismo RUC escrito con
    guiones en una base y sin ellos en la otra simplemente no cruza.
    """
    digits = "".join(char for char in str(raw or "") if char.isdigit())
    return digits if len(digits) == 13 else None


def entity_kind(ruc: str) -> str:
    """Tipo de contribuyente según el tercer dígito del RUC."""
    third = ruc[2]
    if third == "9":
        return "Sociedad privada"
    if third == "6":
        return "Sector público"
    if third in "012345":
        return "Persona natural"
    return "Desconocido"


def province(ruc: str) -> str:
    return PROVINCES.get(ruc[:2], f"Código {ruc[:2]}")


def _bar(count: int, total: int, width: int = 28) -> str:
    filled = round((count / total) * width) if total else 0
    return "█" * filled + "·" * (width - filled)


def report(title: str, rucs: Iterable[str | None], total_rows: int) -> None:
    valid = [ruc for ruc in rucs if ruc]
    invalid = total_rows - len(valid)

    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")
    print(f"Filas leídas:        {total_rows}")
    print(f"RUC válido:          {len(valid)}")
    if invalid:
        # Un RUC ilegible no es un detalle: es una fila que jamás va a cruzar.
        print(f"RUC inválido/ausente: {invalid}  ← nunca cruzarán, hay que revisarlas")

    unique = set(valid)
    if len(unique) != len(valid):
        print(f"Duplicados:          {len(valid) - len(unique)}")

    if not valid:
        return

    for label, counter in (
        ("Tipo de contribuyente", Counter(entity_kind(r) for r in unique)),
        ("Provincia", Counter(province(r) for r in unique)),
    ):
        print(f"\n{label}:")
        for key, count in counter.most_common(12):
            share = count / len(unique) * 100
            print(f"  {key:22} {count:6}  {_bar(count, len(unique))} {share:5.1f}%")


def profile_tenants() -> list[str | None]:
    """Lee los clientes propios del servicio de comprobantes.

    Solo ``GET /admin/tenants``: la cartera propia. No toca comprobantes, que
    son datos de los clientes y tienen otro propósito.
    """
    base_url = os.environ.get("FRACTALSOFT_API_URL", "https://api.fractalsoft.io")
    api_key = os.environ.get("FRACTALSOFT_ADMIN_KEY")
    if not api_key:
        sys.exit(
            "Falta FRACTALSOFT_ADMIN_KEY en el entorno.\n"
            "Ponla en backend/.env (ya está en .gitignore), nunca en el código."
        )

    with httpx.Client(timeout=30) as client:
        response = client.get(f"{base_url}/admin/tenants", headers={"X-API-Key": api_key})
    if response.status_code == 401:
        sys.exit("La clave no fue aceptada (401). Revisa el valor, no lo pegues aquí.")
    response.raise_for_status()

    payload = response.json()
    rows = payload if isinstance(payload, list) else payload.get("items", [])

    active = sum(1 for row in rows if row.get("active"))
    print(f"\nClientes del servicio: {len(rows)} ({active} activos)")
    # Se muestran los NOMBRES de campo disponibles, nunca sus valores.
    if rows:
        print(f"Campos disponibles:    {', '.join(sorted(rows[0].keys()))}")

    return [normalize_ruc(row.get("ruc")) for row in rows]


def profile_csv(path: str, ruc_column: str) -> tuple[list[str | None], int]:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames and ruc_column not in reader.fieldnames:
            sys.exit(
                f"La columna '{ruc_column}' no existe. Columnas: {', '.join(reader.fieldnames)}"
            )
        rows = [normalize_ruc(row.get(ruc_column)) for row in reader]
    return rows, len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenants", action="store_true", help="Perfilar los clientes propios")
    parser.add_argument("--csv", help="Ruta a un CSV exportado para perfilar")
    parser.add_argument("--ruc-column", default="RUC", help="Columna del RUC en el CSV")
    args = parser.parse_args()

    if not args.tenants and not args.csv:
        parser.error("Indica --tenants, --csv, o ambos para comparar las dos fuentes")

    tenant_rucs: list[str | None] = []
    csv_rucs: list[str | None] = []

    if args.tenants:
        tenant_rucs = profile_tenants()
        report(
            "FUENTE A — Clientes propios (servicio de comprobantes)",
            tenant_rucs,
            len(tenant_rucs),
        )

    if args.csv:
        csv_rucs, total = profile_csv(args.csv, args.ruc_column)
        report(f"FUENTE B — {args.csv}", csv_rucs, total)

    # El cruce: cuántos de mis clientes reales aparecen en la base grande. Ese
    # solapamiento es lo que permite describir el perfil de cliente ideal con
    # los campos ricos del registro (actividad, tamaño) en vez de a ojo.
    if tenant_rucs and csv_rucs:
        a = {ruc for ruc in tenant_rucs if ruc}
        b = {ruc for ruc in csv_rucs if ruc}
        overlap = a & b
        print(f"\n{'=' * 60}\nCRUCE POR RUC\n{'=' * 60}")
        print(f"Clientes propios encontrados en la base grande: {len(overlap)} de {len(a)}")
        if a:
            print(f"Cobertura: {len(overlap) / len(a) * 100:.1f}%")
        if len(overlap) < len(a):
            print(
                f"\n{len(a) - len(overlap)} cliente(s) NO están en la base grande.\n"
                "Puede ser que la base esté desactualizada o que sean personas\n"
                "naturales que el registro de sociedades no incluye."
            )


if __name__ == "__main__":
    main()
