"""Provision one Keycloak organization/user pair into IAERP without free-form SQL."""

import argparse
import asyncio
import uuid

from app.db.session import SessionFactory
from app.services.tenant_provisioning import TenantOwnerProvision, provision_tenant_owner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--organization-id", required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--ruc", required=True)
    parser.add_argument("--tenant-name", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--actor-id", required=True)
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    request = TenantOwnerProvision(
        organization_id=args.organization_id,
        external_subject=args.subject,
        ruc=args.ruc,
        tenant_name=args.tenant_name,
        email=args.email,
        display_name=args.display_name,
    )
    async with SessionFactory.begin() as session:
        tenant = await provision_tenant_owner(
            session,
            request=request,
            actor_id=args.actor_id,
            correlation_id=str(uuid.uuid4()),
        )
    print(f"Provisioned tenant {tenant.id} for organization {args.organization_id}")


if __name__ == "__main__":
    asyncio.run(main())
