import asyncio
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.db.session import SessionFactory
from app.models.masters import TaxCategory
from app.models.platform import AutomationSettings, Membership, Tenant, User

DEMO_TENANT_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
DEMO_USER_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")


async def seed() -> None:
    async with SessionFactory() as session, session.begin():
        tenant = await session.get(Tenant, DEMO_TENANT_ID)
        if tenant is None:
            tenant = Tenant(
                id=DEMO_TENANT_ID,
                ruc="1799999999001",
                name="IAERP Demo",
                organization_id="33333333-3333-4333-8333-333333333333",
            )
            session.add(tenant)

        user = await session.get(User, DEMO_USER_ID)
        if user is None:
            user = User(
                id=DEMO_USER_ID,
                external_subject=str(DEMO_USER_ID),
                email="owner@iaerp.local",
                display_name="IAERP Owner",
            )
            session.add(user)

        # These rows are referenced below but the models intentionally avoid
        # ORM relationships, so establish their FK targets before dependents.
        await session.flush()

        membership = await session.scalar(
            select(Membership).where(
                Membership.tenant_id == DEMO_TENANT_ID,
                Membership.user_id == DEMO_USER_ID,
            )
        )
        if membership is None:
            session.add(
                Membership(
                    tenant_id=DEMO_TENANT_ID,
                    user_id=DEMO_USER_ID,
                    roles=["owner", "admin"],
                )
            )

        if await session.get(AutomationSettings, DEMO_TENANT_ID) is None:
            session.add(
                AutomationSettings(
                    tenant_id=DEMO_TENANT_ID,
                    writes_enabled=False,
                    daily_amount_limit=Decimal("0.00"),
                )
            )

        tax = await session.scalar(
            select(TaxCategory).where(
                TaxCategory.tenant_id == DEMO_TENANT_ID,
                TaxCategory.sri_code == "4",
            )
        )
        if tax is None:
            session.add(
                TaxCategory(
                    tenant_id=DEMO_TENANT_ID,
                    sri_code="4",
                    name="IVA 15%",
                    rate=Decimal("15.000000"),
                    valid_from=date(2024, 4, 1),
                )
            )


if __name__ == "__main__":
    asyncio.run(seed())
