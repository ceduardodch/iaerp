"""Scoped customer creation and exact recovery in the iOS billing flow."""

import asyncio
import uuid

import pytest
from sqlalchemy import func, select

from app.core.auth import settings
from app.core.ios_permissions import IOS_CUSTOMER_CREATE
from app.db.session import SessionFactory, engine
from app.models.masters import Party
from app.models.platform import AuditEvent
from tests.test_billing_api import auth
from tests.test_ios_permissions import TENANT_A, TENANT_B, USER_A, claims, membership, oidc_signer

LOOKUP = "/api/v1/customers/lookup"
CREATE = "/api/v1/customers"
IDENTITY = {"identificationType": "RUC", "identificationNumber": "9999999999001"}
PAYLOAD = {**IDENTITY, "name": "Cliente de prueba", "email": "prueba@example.org"}


@pytest.fixture
def mobile(monkeypatch):
    signer = oidc_signer(monkeypatch)

    def token(*, org="tenant-a", scope=f"parties:read {IOS_CUSTOMER_CREATE}", **claims_override):
        return signer(claims(org, scope=scope, **claims_override))

    return token


async def test_customer_quick_create_is_scoped_and_idempotent(client, mobile, monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    read = auth(mobile())
    write = auth(mobile(), str(uuid.uuid4()))
    assert (await client.post(LOOKUP, headers=read, json=IDENTITY)).status_code == 404
    first = await client.post(CREATE, headers=write, json=PAYLOAD)
    assert first.status_code == 201, first.text
    data = first.json()
    assert (data["roles"], data["name"], data["email"]) == (
        ["CUSTOMER"],
        PAYLOAD["name"],
        PAYLOAD["email"],
    )
    assert (await client.post(CREATE, headers=write, json=PAYLOAD)).json() == data
    assert (
        await client.post(CREATE, headers=write, json={**PAYLOAD, "name": "Distinto"})
    ).status_code == 409
    assert (
        await client.post(CREATE, headers=auth(mobile(), str(uuid.uuid4())), json=PAYLOAD)
    ).status_code == 409
    assert (await client.post(LOOKUP, headers=read, json=IDENTITY)).json() == data
    await membership(TENANT_B, ["billing"])
    other = auth(mobile(org="tenant-b"), str(uuid.uuid4()))
    assert (await client.post(LOOKUP, headers=other, json=IDENTITY)).status_code == 404
    separate = await client.post(CREATE, headers=other, json={**PAYLOAD, "name": "Otra empresa"})
    assert separate.status_code == 201 and separate.json()["id"] != data["id"]
    async with SessionFactory() as session:
        events = list(
            await session.scalars(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == TENANT_A, AuditEvent.action == "party.created"
                )
            )
        )
        assert len(events) == 1 and events[0].actor_id == str(USER_A)
        assert events[0].entity_id == data["id"] and "identificationNumber" not in events[0].details
    # Even replaying a successful key checks the user's current membership and scopes.
    await membership(TENANT_A, ["viewer"])
    assert (await client.post(CREATE, headers=write, json=PAYLOAD)).status_code == 403
    assert (await client.post(LOOKUP, headers=read, json=IDENTITY)).status_code == 403


async def test_exact_customer_lookup_beyond_page_and_collision(client, mobile):
    async with SessionFactory() as session, session.begin():
        for i in range(108):
            session.add(
                Party(
                    tenant_id=TENANT_A,
                    name=f"A-{i:03}",
                    identification_type="PASSPORT",
                    identification_number=f"TEST-{i:03}",
                    roles=["CUSTOMER"],
                )
            )
        session.add(
            Party(
                tenant_id=TENANT_A,
                name="Último",
                identification_type="RUC",
                identification_number=IDENTITY["identificationNumber"],
                roles=["CUSTOMER", "SUPPLIER"],
            )
        )
    result = await client.post(LOOKUP, headers=auth(mobile()), json=IDENTITY)
    assert result.status_code == 200 and result.json()["name"] == "Último"
    async with SessionFactory() as session, session.begin():
        party = await session.get(Party, uuid.UUID(result.json()["id"]))
        party.roles = ["SUPPLIER"]
    assert (await client.post(LOOKUP, headers=auth(mobile()), json=IDENTITY)).status_code == 409
    assert (
        await client.post(CREATE, headers=auth(mobile(), str(uuid.uuid4())), json=PAYLOAD)
    ).status_code == 409
    async with SessionFactory() as session, session.begin():
        party = await session.get(Party, uuid.UUID(result.json()["id"]))
        assert party.name == "Último" and party.roles == ["SUPPLIER"]
        party.roles = ["CUSTOMER"]
        party.active = False
    assert (await client.post(LOOKUP, headers=auth(mobile()), json=IDENTITY)).status_code == 409


async def test_customer_shape_permissions_and_validation(client, mobile):
    for token in (
        mobile(scope="parties:read"),
        mobile(scope="customers:create"),
        mobile(azp="iaerp-web"),
    ):
        headers = auth(token, str(uuid.uuid4()))
        assert (await client.post(CREATE, headers=headers, json=PAYLOAD)).status_code == 403
        assert (await client.post(LOOKUP, headers=headers, json=IDENTITY)).status_code == 403
    headers = auth(mobile(), str(uuid.uuid4()))
    assert (
        await client.post(
            "/api/v1/parties", headers=headers, json={**PAYLOAD, "roles": ["CUSTOMER"]}
        )
    ).status_code == 403
    for changes in (
        {"roles": ["SUPPLIER"]},
        {"tenantId": str(TENANT_B)},
        {"name": " "},
        {"email": "invalid"},
        {"identificationNumber": "12"},
        {"identificationNumber": "１２３４５６７８９０１２３"},
        {"identificationType": "PASSPORT", "identificationNumber": "A"},
        {"identificationType": "CEDULA", "identificationNumber": "123456789"},
    ):
        assert (
            await client.post(CREATE, headers=headers, json={**PAYLOAD, **changes})
        ).status_code == 422
    assert (await client.post(CREATE, headers=auth(mobile()), json=PAYLOAD)).status_code == 422
    assert (
        await client.post(LOOKUP, headers=headers, json={**IDENTITY, "tenantId": str(TENANT_B)})
    ).status_code == 422
    async with SessionFactory() as session:
        assert await session.scalar(select(func.count()).select_from(Party)) == 0


async def test_competing_native_customer_creates_do_not_duplicate(client, mobile):
    async def submit():
        return await client.post(CREATE, headers=auth(mobile(), str(uuid.uuid4())), json=PAYLOAD)

    if engine.dialect.name == "postgresql":
        first, second = await asyncio.gather(submit(), submit())
    else:
        first, second = await submit(), await submit()
    assert sorted((first.status_code, second.status_code)) == [201, 409]
    async with SessionFactory() as session:
        assert await session.scalar(select(func.count()).select_from(Party)) == 1
