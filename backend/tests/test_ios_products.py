"""Native catalog entry uses the tenant's fiscal calendar and the same product as the web."""

import asyncio
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.auth import settings
from app.core.timezones import today_in_fiscal_timezone
from app.db.session import SessionFactory, engine
from app.models.masters import Product, TaxCategory
from app.models.platform import AuditEvent
from tests.test_billing_api import auth
from tests.test_ios_permissions import TENANT_A, TENANT_B, USER_A, claims, membership, oidc_signer

LOOKUP = "/api/v1/catalog-products/lookup"
CREATE = "/api/v1/catalog-products"
CODE = "S_%1"
BASE = {"code": CODE, "name": "Servicio de prueba", "unitPrice": "0.050001"}


@pytest.fixture
def mobile(monkeypatch):
    signer = oidc_signer(monkeypatch)

    def token(*, org="tenant-a", scope="products:read products:create", **overrides):
        return signer(claims(org, scope=scope, **overrides))

    return token


async def payload(tenant=TENANT_A):
    async with SessionFactory() as session:
        tax = await session.scalar(select(TaxCategory.id).where(TaxCategory.tenant_id == tenant))
    return {**BASE, "taxCategoryId": str(tax)}


async def test_create_recover_same_product_and_audit_actor(client, mobile, monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    data = await payload()
    headers = auth(mobile(), str(uuid.uuid4()))
    fetch = auth(mobile())
    assert (await client.post(LOOKUP, headers=fetch, json={"code": CODE})).status_code == 404
    first = await client.post(CREATE, headers=headers, json=data)
    assert first.status_code == 201, first.text
    product = first.json()
    assert product["taxCategoryId"] == data["taxCategoryId"]
    assert Decimal(product["unitPrice"]) == Decimal(data["unitPrice"])
    assert (product["name"], product["code"]) == (data["name"], CODE)
    assert (await client.post(CREATE, headers=headers, json=data)).json() == product
    assert (
        await client.post(CREATE, headers=headers, json={**data, "name": "Otro"})
    ).status_code == 409
    assert (
        await client.post(CREATE, headers=auth(mobile(), str(uuid.uuid4())), json=data)
    ).status_code == 409
    assert (await client.post(LOOKUP, headers=fetch, json={"code": f" {CODE} "})).json() == product
    await membership(TENANT_B, ["billing"])
    other = auth(mobile(org="tenant-b"), str(uuid.uuid4()))
    assert (await client.post(LOOKUP, headers=other, json={"code": CODE})).status_code == 404
    second = await client.post(CREATE, headers=other, json=await payload(TENANT_B))
    assert second.status_code == 201 and second.json()["id"] != product["id"]
    async with SessionFactory() as session:
        events = list(
            await session.scalars(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == TENANT_A, AuditEvent.action == "product.created"
                )
            )
        )
        assert len(events) == 1 and events[0].actor_id == str(USER_A)
        assert events[0].entity_id == product["id"]
        actual = await session.get(Product, uuid.UUID(product["id"]))
        assert actual.active and actual.unit_price == Decimal("0.050001")
    await membership(TENANT_A, ["viewer"])
    assert (await client.post(CREATE, headers=headers, json=data)).status_code == 403
    assert (await client.post(LOOKUP, headers=fetch, json={"code": CODE})).status_code == 403


async def test_exact_code_recovery_after_first_page_and_inactive_collision(client, mobile):
    data = await payload()
    async with SessionFactory() as session, session.begin():
        for i in range(106):
            session.add(
                Product(
                    tenant_id=TENANT_A,
                    name=f"A-{i:03}",
                    code=f"S-{i:03}",
                    unit_price=Decimal(0),
                    tax_category_id=uuid.UUID(data["taxCategoryId"]),
                )
            )
    headers = auth(mobile(), str(uuid.uuid4()))
    first = await client.post(CREATE, headers=headers, json={**data, "unitPrice": "0"})
    assert first.status_code == 201
    for partial in (CODE.lower(), "S", "S-1", "%"):
        assert (
            await client.post(LOOKUP, headers=headers, json={"code": partial})
        ).status_code == 404
    exact = await client.post(LOOKUP, headers=headers, json={"code": CODE})
    assert exact.status_code == 200 and exact.json()["id"] == first.json()["id"]
    async with SessionFactory() as session, session.begin():
        obj = await session.get(Product, uuid.UUID(first.json()["id"]))
        obj.active = False
    assert (await client.post(LOOKUP, headers=headers, json={"code": CODE})).status_code == 409
    assert (
        await client.post(CREATE, headers=auth(mobile(), str(uuid.uuid4())), json=data)
    ).status_code == 409
    async with SessionFactory() as session:
        obj = await session.get(Product, uuid.UUID(first.json()["id"]))
        assert not obj.active and obj.unit_price == 0


async def test_native_product_permissions_input_and_fiscal_dates(client, mobile):
    data = await payload()
    headers = auth(mobile(), str(uuid.uuid4()))
    for token in (
        mobile(scope="products:read"),
        mobile(scope="products:create"),
        mobile(azp="iaerp-web"),
    ):
        limited = auth(token, str(uuid.uuid4()))
        assert (await client.post(CREATE, headers=limited, json=data)).status_code == 403
        assert (await client.post(LOOKUP, headers=limited, json={"code": CODE})).status_code == 403
    assert (await client.post("/api/v1/products", headers=headers, json=data)).status_code == 403
    assert (
        await client.put(f"/api/v1/products/{uuid.uuid4()}", headers=headers, json=data)
    ).status_code == 403
    for changes in (
        {"active": True},
        {"tenantId": str(TENANT_B)},
        {"code": " "},
        {"name": " "},
        {"name": "a" * 301},
        {"code": None},
        {"code": "a" * 81},
        {"unitPrice": "-1"},
        {"unitPrice": "0.1234567"},
        {"unitPrice": "1000000000000"},
        {"taxCategoryId": "X"},
    ):
        assert (
            await client.post(CREATE, headers=headers, json={**data, **changes})
        ).status_code == 422
    assert (await client.post(CREATE, headers=auth(mobile()), json=data)).status_code == 422
    assert (
        await client.post(CREATE, headers=headers, json=await payload(TENANT_B))
    ).status_code == 404
    today = today_in_fiscal_timezone()
    for start, end, active, expect in (
        (today, None, False, 404),
        (today + timedelta(days=1), None, True, 422),
        (today - timedelta(days=3), today - timedelta(days=1), True, 422),
    ):
        async with SessionFactory() as session, session.begin():
            category = await session.get(TaxCategory, uuid.UUID(data["taxCategoryId"]))
            category.valid_from, category.valid_to, category.active = start, end, active
        assert (await client.post(CREATE, headers=headers, json=data)).status_code == expect
    async with SessionFactory() as session, session.begin():
        assert await session.scalar(select(func.count()).select_from(Product)) == 0
        assert await session.scalar(select(func.count()).select_from(AuditEvent)) == 0
        category = await session.get(TaxCategory, uuid.UUID(data["taxCategoryId"]))
        category.valid_from = category.valid_to = today
    assert (await client.post(CREATE, headers=headers, json=data)).status_code == 201


async def test_overlapping_catalog_creates_keep_one_product(client, mobile):
    data = await payload()

    async def create():
        return await client.post(CREATE, headers=auth(mobile(), str(uuid.uuid4())), json=data)

    if engine.dialect.name == "postgresql":
        first, second = await asyncio.gather(create(), create())
    else:
        first, second = await create(), await create()
    assert sorted((first.status_code, second.status_code)) == [201, 409]
    async with SessionFactory() as session:
        assert await session.scalar(select(func.count()).select_from(Product)) == 1
