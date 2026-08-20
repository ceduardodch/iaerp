"""Carga diaria de leads ISV al CRM, únicamente vía crm_agent_cli.py.

Cada corrida toma las siguientes N empresas de ``listas/isv.csv`` que
todavía no tienen lead en el CRM (dedupe por razón social) y llama a
``crm_agent_cli.py create-lead`` por cada una. Nunca llama a la API del
CRM directamente ni maneja ``PROSPECT_CRM_CLIENT_SECRET``; eso vive solo
dentro de ``crm_agent_cli.py``.

Excluye empresas de 100+ empleados (según `stg.cia`) y las que ya estén
en ``listas/isv_excluir.csv``: a ese tamaño pueden ser partners de AWS
(competencia) y el plan pide verificarlo antes de contactar.

Uso:

    # Ver los siguientes 3 sin escribir nada
    uv run python scripts/auto_cargar_leads_isv.py --dry-run

    # Crear los siguientes 3 leads
    uv run python scripts/auto_cargar_leads_isv.py --limit 3

    # Listar candidatos en JSON, para que un agente los filtre (p.ej. con
    # Apollo) antes de decidir cuáles crear
    uv run python scripts/auto_cargar_leads_isv.py --list 6

    # Crear un candidato puntual ya filtrado
    uv run python scripts/auto_cargar_leads_isv.py --create-ruc 1790598616001

    # Excluir permanentemente uno que resultó ser competencia
    uv run python scripts/auto_cargar_leads_isv.py --exclude 1790394182001 \
        --reason "Apollo: consultora TI, managed services"
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
LISTAS_DIR = Path(__file__).resolve().parents[2] / "listas"
CSV_PATH = LISTAS_DIR / "isv.csv"
EXCLUDE_PATH = LISTAS_DIR / "isv_excluir.csv"
CLI = ["uv", "run", "python", "scripts/crm_agent_cli.py"]
TITLE = "Revisión de costo y seguridad AWS"


def existing_names() -> set[str]:
    result = subprocess.run(
        [*CLI, "leads", "--limit", "200"],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.exit(f"No se pudo leer el CRM: {result.stderr.strip()}")
    leads = json.loads(result.stdout)
    return {
        lead["party"]["name"].strip().lower()
        for lead in leads
        if lead.get("party") and lead["party"].get("name")
    }


def excluded_rucs() -> set[str]:
    if not EXCLUDE_PATH.exists():
        return set()
    with EXCLUDE_PATH.open(encoding="utf-8", newline="") as handle:
        return {
            (row.get("ruc") or "").strip()
            for row in csv.DictReader(handle)
            if (row.get("ruc") or "").strip()
        }


def all_rows() -> list[dict[str, object]]:
    with CSV_PATH.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    parsed: list[dict[str, object]] = []
    for row in rows:
        ruc = (row.get("ruc") or "").strip()
        name = (row.get("empresa") or "").strip()
        email = (row.get("correo") or "").strip()
        phone = (row.get("telefono") or "").strip()
        try:
            empleados = int((row.get("empleados") or "").strip())
        except ValueError:
            continue
        if not ruc or not name or not (email or phone):
            continue
        if empleados < 10 or empleados >= 100:
            continue
        priority = 1 if 30 <= empleados <= 99 else 2
        parsed.append(
            {
                "ruc": ruc,
                "name": name,
                "email": email,
                "phone": phone,
                "empleados": empleados,
                "priority": priority,
            }
        )
    parsed.sort(key=lambda r: (r["priority"], -r["empleados"]))
    return parsed


def candidates() -> list[dict[str, object]]:
    excluded = excluded_rucs()
    taken = existing_names()
    return [
        row
        for row in all_rows()
        if row["ruc"] not in excluded and str(row["name"]).lower() not in taken
    ]


def create_one(row: dict[str, object]) -> None:
    key = f"isv-lead-{row['ruc']}"
    cmd = [
        *CLI,
        "create-lead",
        "--name", str(row["name"]),
        "--identification-type", "RUC",
        "--identification-number", str(row["ruc"]),
        "--title", TITLE,
        "--idempotency-key", key,
    ]
    if row["email"]:
        cmd += ["--email", str(row["email"])]
    if row["phone"]:
        cmd += ["--phone", str(row["phone"])]

    result = subprocess.run(cmd, cwd=BACKEND_DIR, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"FALLÓ {row['name']}: {result.stderr.strip()}")
        return
    lead = json.loads(result.stdout)
    print(f"Creado: {row['name']} -> lead {lead['id']}")


def cmd_list(limit: int) -> None:
    print(json.dumps(candidates()[:limit], ensure_ascii=False, indent=2))


def cmd_create_ruc(ruc: str) -> None:
    match = next((row for row in candidates() if row["ruc"] == ruc), None)
    if match is None:
        sys.exit(f"{ruc} no está pendiente (ya tiene lead, está excluido, o no cumple el filtro).")
    create_one(match)


def cmd_exclude(ruc: str, reason: str) -> None:
    row = next((r for r in all_rows() if r["ruc"] == ruc), None)
    name = row["name"] if row else ""
    if ruc in excluded_rucs():
        print(f"{ruc} ya estaba excluido.")
        return
    is_new = not EXCLUDE_PATH.exists()
    with EXCLUDE_PATH.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        if is_new:
            writer.writerow(["ruc", "empresa", "motivo", "fecha"])
        writer.writerow([ruc, name, reason, date.today().isoformat()])
    print(f"Excluido permanentemente: {name or ruc} ({reason})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=3, help="Crear hasta N leads")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--list", type=int, metavar="N", help="Listar N candidatos en JSON, sin crear nada"
    )
    parser.add_argument("--create-ruc", metavar="RUC", help="Crear un candidato puntual por RUC")
    parser.add_argument("--exclude", metavar="RUC", help="Excluir permanentemente un RUC")
    parser.add_argument("--reason", default="", help="Motivo de --exclude")
    args = parser.parse_args()

    if args.exclude:
        if not args.reason:
            sys.exit("--exclude requiere --reason")
        cmd_exclude(args.exclude, args.reason)
        return

    if args.create_ruc:
        cmd_create_ruc(args.create_ruc)
        return

    if args.list is not None:
        cmd_list(args.list)
        return

    batch = candidates()[: args.limit]
    if not batch:
        print("No quedan candidatos sin cargar en el rango 10-99 empleados.")
        return

    for row in batch:
        if args.dry_run:
            key = f"isv-lead-{row['ruc']}"
            print(f"[dry-run] crearía lead: {row['name']} (RUC {row['ruc']}, key {key})")
            continue
        create_one(row)


if __name__ == "__main__":
    main()
