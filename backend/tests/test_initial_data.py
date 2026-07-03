from sqlalchemy import func, select

from app.db.base import Base
from app.db.session import SessionFactory, engine
from app.initial_data import (
    DEMO_TENANT_ID,
    DEMO_USER_ID,
    NO_MEMBERSHIP_USER_ID,
    SECOND_TENANT_ID,
    SEED_VERSION,
    TENANT_A_SERVICE_ACCOUNT_ID,
    TENANT_B_SERVICE_ACCOUNT_ID,
    seed,
)
from app.models.masters import Establishment, Party, Product, Tag, TaxCategory
from app.models.platform import Membership, ServiceAccount, Tenant, User


async def test_seed_is_repeatable_and_preserves_foreign_keys():
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)

    await seed()
    await seed()

    async with SessionFactory() as session:
        assert SEED_VERSION == "sprint-01-v1"
        assert await session.scalar(select(func.count()).select_from(Tenant)) == 2
        assert await session.scalar(select(func.count()).select_from(User)) == 4
        assert await session.scalar(select(func.count()).select_from(Membership)) == 4
        assert await session.scalar(select(func.count()).select_from(ServiceAccount)) == 2
        assert await session.scalar(select(func.count()).select_from(TaxCategory)) == 2
        assert await session.scalar(select(func.count()).select_from(Establishment)) == 2
        assert await session.scalar(select(func.count()).select_from(Tag)) == 2
        assert await session.scalar(select(func.count()).select_from(Party)) == 2
        assert await session.scalar(select(func.count()).select_from(Product)) == 2

        owner_memberships = (
            await session.scalars(select(Membership).where(Membership.user_id == DEMO_USER_ID))
        ).all()
        assert {row.tenant_id for row in owner_memberships} == {
            DEMO_TENANT_ID,
            SECOND_TENANT_ID,
        }
        assert (
            await session.scalar(
                select(func.count())
                .select_from(Membership)
                .where(Membership.user_id == NO_MEMBERSHIP_USER_ID)
            )
            == 0
        )

        account_a = await session.get(ServiceAccount, TENANT_A_SERVICE_ACCOUNT_ID)
        account_b = await session.get(ServiceAccount, TENANT_B_SERVICE_ACCOUNT_ID)
        assert account_a is not None and account_a.client_id == "iaerp-agent-norte"
        assert account_b is not None and account_b.client_id == "iaerp-agent-sur"

        products = (await session.scalars(select(Product).order_by(Product.code))).all()
        assert [product.code for product in products] == ["NORTE-001", "SUR-001"]


async def test_seed_adopts_existing_rows_by_business_key():
    async with SessionFactory() as session:
        original_tax_ids = set(await session.scalars(select(TaxCategory.id)))

    await seed()
    await seed()

    async with SessionFactory() as session:
        tax_ids = set(await session.scalars(select(TaxCategory.id)))
        assert tax_ids == original_tax_ids
        assert await session.scalar(select(func.count()).select_from(Tenant)) == 2
        assert await session.scalar(select(func.count()).select_from(Product)) == 2
