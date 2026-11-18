"""Actor/tenant-bound reconciliation of a native app's uncertain draft write."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.db.session import SessionFactory
from app.models.platform import IdempotencyRecord, Membership
from tests.test_billing_api import _invoice_payload, _setup_billing_masters, token_for
from tests.test_ios_permissions import TENANT_A, TENANT_B, USER_A, claims, membership, oidc_signer

USER_B = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
KEY = "ABCDEF12-1234-4567-89AB-CDEF01234567"


@pytest_asyncio.fixture
async def completed_draft(client, monkeypatch):
    setup = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters = await _setup_billing_masters(client, setup, key_prefix="ios-lookup")
    sign = oidc_signer(monkeypatch)
    headers = {"Authorization": f"Bearer {sign(claims())}", "Idempotency-Key": KEY}
    payload = _invoice_payload(masters)
    created = await client.post("/api/v1/invoices", headers=headers, json=payload)
    assert created.status_code == 201, created.text
    return {"headers": headers, "invoice": created.json(), "sign": sign, "payload": payload}


async def test_ios_completed_draft_lookup_keeps_original_uppercase_key(client, completed_draft):
    found = await client.get(
        f"/api/v1/invoices/draft-requests/{KEY}", headers=completed_draft["headers"]
    )
    assert found.status_code == 200
    assert found.json() == {"invoiceId": completed_draft["invoice"]["id"]}
    # Idempotency keys are opaque, not case-insensitive UUID identities.
    lower = await client.get(
        f"/api/v1/invoices/draft-requests/{KEY.lower()}", headers=completed_draft["headers"]
    )
    assert lower.status_code == 404


async def test_ios_distinct_case_variant_requests_reconcile_to_their_own_documents(
    client, completed_draft
):
    lower = await client.post(
        "/api/v1/invoices",
        headers={**completed_draft["headers"], "Idempotency-Key": KEY.lower()},
        json=completed_draft["payload"],
    )
    assert lower.status_code == 201
    assert lower.json()["id"] != completed_draft["invoice"]["id"]
    for key, expected in [
        (KEY, completed_draft["invoice"]["id"]),
        (KEY.lower(), lower.json()["id"]),
    ]:
        found = await client.get(
            f"/api/v1/invoices/draft-requests/{key}", headers=completed_draft["headers"]
        )
        assert found.json() == {"invoiceId": expected}


async def test_ios_draft_lookup_does_not_reveal_other_actor_or_tenant(client, completed_draft):
    sign = completed_draft["sign"]
    async with SessionFactory() as session, session.begin():
        session.add(Membership(tenant_id=TENANT_A, user_id=USER_B, roles=["viewer"]))
    await membership(TENANT_B, ["viewer"])
    absent = await client.get(
        f"/api/v1/invoices/draft-requests/{uuid.uuid4()}", headers=completed_draft["headers"]
    )
    for payload in [claims(sub="user-b"), claims("tenant-b")]:
        foreign = await client.get(
            f"/api/v1/invoices/draft-requests/{KEY}?tenant_id={TENANT_A}&actor_id={USER_A}",
            headers={"Authorization": f"Bearer {sign(payload)}"},
        )
        assert foreign.status_code == 404
        assert foreign.json() == absent.json() == {"detail": "Completed draft request not found"}


async def test_ios_reader_can_reconcile_an_existing_draft_after_membership_downgrade(
    client, completed_draft
):
    await membership(TENANT_A, ["viewer"])
    found = await client.get(
        f"/api/v1/invoices/draft-requests/{KEY}", headers=completed_draft["headers"]
    )
    assert found.status_code == 200
    assert found.json() == {"invoiceId": completed_draft["invoice"]["id"]}
    replay = await client.post(
        "/api/v1/invoices", headers=completed_draft["headers"], json=completed_draft["payload"]
    )
    assert replay.status_code == 403


async def test_ios_retained_expired_evidence_can_reconcile_without_replaying(
    client, completed_draft
):
    async with SessionFactory() as session, session.begin():
        record = await session.scalar(
            select(IdempotencyRecord).where(IdempotencyRecord.idempotency_key == KEY)
        )
        assert record is not None
        record.expires_at = datetime.now(UTC) - timedelta(days=1)
    found = await client.get(
        f"/api/v1/invoices/draft-requests/{KEY}", headers=completed_draft["headers"]
    )
    assert found.status_code == 200
    assert found.json() == {"invoiceId": completed_draft["invoice"]["id"]}


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "PROCESSING"},
        {"response_body": None},
        {"response_body": {"id": "not-an-id"}},
        {"response_body": {"id": str(uuid.UUID(int=0))}},
        {"operation": "invoices.issue"},
    ],
)
async def test_ios_incomplete_or_invalid_evidence_does_not_resolve_a_draft(
    client, completed_draft, changes
):
    async with SessionFactory() as session, session.begin():
        record = await session.scalar(
            select(IdempotencyRecord).where(IdempotencyRecord.idempotency_key == KEY)
        )
        assert record is not None
        for attribute, value in changes.items():
            setattr(record, attribute, value)
    result = await client.get(
        f"/api/v1/invoices/draft-requests/{KEY}", headers=completed_draft["headers"]
    )
    assert result.status_code == 404
    assert result.json() == {"detail": "Completed draft request not found"}


async def test_ios_completed_evidence_cannot_reference_an_invoice_in_another_tenant(
    client, completed_draft
):
    await membership(TENANT_B, ["viewer"])
    async with SessionFactory() as session, session.begin():
        session.add(
            IdempotencyRecord(
                tenant_id=TENANT_B,
                actor_id=str(USER_A),
                operation="invoices.create_draft",
                idempotency_key=KEY,
                request_hash="synthetic",
                status="COMPLETED",
                response_status=201,
                response_body={"id": completed_draft["invoice"]["id"]},
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
    result = await client.get(
        f"/api/v1/invoices/draft-requests/{KEY}",
        headers={"Authorization": f"Bearer {completed_draft['sign'](claims('tenant-b'))}"},
    )
    assert result.status_code == 404


@pytest.mark.parametrize("key", ["not-a-uuid", "A" * 129, "{abcdef12-1234-4567-89ab-cdef01234567}"])
async def test_ios_draft_lookup_rejects_invalid_or_oversized_keys(client, completed_draft, key):
    response = await client.get(
        f"/api/v1/invoices/draft-requests/{key}", headers=completed_draft["headers"]
    )
    assert response.status_code == 422
