from sqlalchemy import func, select

from app.db.base import Base
from app.db.session import SessionFactory, engine
from app.initial_data import DEMO_TENANT_ID, seed
from app.models.masters import TaxCategory
from app.models.platform import Tenant


async def test_seed_is_repeatable_and_preserves_foreign_keys():
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)

    await seed()
    await seed()

    async with SessionFactory() as session:
        assert await session.get(Tenant, DEMO_TENANT_ID) is not None
        assert (
            await session.scalar(
                select(func.count())
                .select_from(TaxCategory)
                .where(TaxCategory.tenant_id == DEMO_TENANT_ID)
            )
            == 1
        )
