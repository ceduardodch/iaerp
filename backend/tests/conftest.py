import os
import uuid
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal

import pytest_asyncio

os.environ["APP_ENV"] = "test"
os.environ["AUTH_MODE"] = "dev"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_iaerp.db"
os.environ["DEV_JWT_SECRET"] = "test-secret-that-is-longer-than-thirty-two-characters"

from app.db.base import Base  # noqa: E402
from app.db.session import SessionFactory, engine  # noqa: E402
from app.models.masters import TaxCategory  # noqa: E402
from app.models.platform import AutomationSettings, Membership, Tenant, User  # noqa: E402

TENANT_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
TENANT_B = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
USER_A = uuid.UUID("22222222-2222-4222-8222-222222222222")
USER_B = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


@pytest_asyncio.fixture(autouse=True)
async def database() -> AsyncIterator[None]:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)

    async with SessionFactory() as session, session.begin():
        session.add_all(
            [
                Tenant(
                    id=TENANT_A,
                    ruc="1799999999001",
                    name="Tenant A",
                    organization_id="tenant-a",
                ),
                Tenant(
                    id=TENANT_B,
                    ruc="1799999999002",
                    name="Tenant B",
                    organization_id="tenant-b",
                ),
                User(
                    id=USER_A,
                    external_subject="user-a",
                    email="a@iaerp.local",
                    display_name="User A",
                ),
                User(
                    id=USER_B,
                    external_subject="user-b",
                    email="b@iaerp.local",
                    display_name="User B",
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                Membership(
                    tenant_id=TENANT_A,
                    user_id=USER_A,
                    roles=["owner"],
                ),
                Membership(
                    tenant_id=TENANT_B,
                    user_id=USER_B,
                    roles=["owner"],
                ),
                AutomationSettings(
                    tenant_id=TENANT_A,
                    writes_enabled=False,
                    daily_amount_limit=Decimal("0.00"),
                ),
                AutomationSettings(
                    tenant_id=TENANT_B,
                    writes_enabled=False,
                    daily_amount_limit=Decimal("0.00"),
                ),
                TaxCategory(
                    tenant_id=TENANT_A,
                    sri_code="4",
                    name="IVA 15%",
                    rate=Decimal("15.000000"),
                    valid_from=date(2024, 4, 1),
                ),
                TaxCategory(
                    tenant_id=TENANT_B,
                    sri_code="4",
                    name="IVA 15%",
                    rate=Decimal("15.000000"),
                    valid_from=date(2024, 4, 1),
                ),
            ]
        )
    yield


@pytest_asyncio.fixture
async def client():
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as async_client:
        yield async_client
