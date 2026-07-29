"""Load only eligible authorized Sky Franquicia invoices into IAERP."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from app.db.session import SessionFactory
from app.services.sky_franquicia_migration import load_authorized_invoices


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--ruc", required=True)
    parser.add_argument(
        "--source-url-env",
        default="SKYFRANQUICIAS_SOURCE_URL",
        help="Environment variable that holds the read-only source URL.",
    )
    return parser.parse_args()


async def _main() -> int:
    arguments = _arguments()
    source_url = os.environ.get(arguments.source_url_env)
    if not source_url:
        raise RuntimeError(f"Missing source URL environment variable {arguments.source_url_env}")
    async with SessionFactory() as session:
        report = await load_authorized_invoices(
            session=session,
            source_url=source_url,
            ruc=arguments.ruc,
            tenant_id=arguments.tenant_id,
        )
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(_main()))
    except Exception as error:
        print(f"Authorized invoice migration failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
