"""Native policy through actual membership queries, JWT verification and REST.

All signing keys/tenants/users are synthetic. No Keycloak, SRI or production
service is contacted: only the JWKS network lookup is replaced with a local
public key; PyJWT still verifies RS256, issuer, audience and expiration.
"""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from sqlalchemy import func, select

from app.core import auth as authentication
from app.core.ios_permissions import IOS_READ_SCOPES
from app.db.session import SessionFactory
from app.models.billing import SalesDocument
from app.models.platform import AuditEvent, IdempotencyRecord, Membership, ServiceAccount
from tests.test_billing_api import _invoice_payload, _setup_billing_masters, token_for

TENANT_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
TENANT_B = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
USER_A = uuid.UUID("22222222-2222-4222-8222-222222222222")
OVERBROAD_SCOPES = " ".join(
    sorted(IOS_READ_SCOPES | {"invoices:write", "invoices:issue", "service-accounts:write"})
)


def claims(organization: str = "tenant-a", **overrides: object) -> dict[str, object]:
    now = datetime.now(UTC)
    payload: dict[str, object] = {
        "iss": authentication.settings.OIDC_ISSUER_URL,
        "aud": authentication.settings.OIDC_API_AUDIENCE,
        "azp": "iaerp-ios",
        "sub": "user-a",
        "scope": OVERBROAD_SCOPES,
        "organization": {organization: {"id": organization}},
        "roles": ["owner", "admin", "billing"],  # Untrusted for business permissions.
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    payload.update(overrides)
    return payload


async def membership(tenant: uuid.UUID, roles: list[str], *, active: bool = True) -> None:
    async with SessionFactory() as session, session.begin():
        value = await session.scalar(
            select(Membership).where(Membership.tenant_id == tenant, Membership.user_id == USER_A)
        )
        if value is None:
            session.add(Membership(tenant_id=tenant, user_id=USER_A, roles=roles, active=active))
        else:
            value.roles = roles
            value.active = active


def oidc_signer(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(authentication.settings, "AUTH_MODE", "oidc")
    monkeypatch.setattr(
        authentication.settings, "OIDC_ISSUER_URL", "https://identity.example.invalid"
    )

    class LocalJWKS:
        def __init__(self, _url):
            pass

        def get_signing_key_from_jwt(self, _token):
            return SimpleNamespace(key=key.public_key())

    monkeypatch.setattr(authentication, "PyJWKClient", LocalJWKS)
    return lambda payload: jwt.encode(payload, key, algorithm="RS256")


@pytest.mark.parametrize(
    "roles,can_write",
    [
        (["owner"], True),
        (["admin"], True),
        (["billing"], True),
        (["viewer"], False),
        (["auditor"], False),
        (["accountant"], False),
        (["operator"], False),
        (["collections"], False),
        (["payables"], False),
        (["unknown"], False),
        ([], False),
    ],
)
async def test_ios_scopes_are_limited_by_current_membership(monkeypatch, roles, can_write):
    monkeypatch.setattr(authentication.settings, "AUTH_MODE", "oidc")
    await membership(TENANT_A, roles)
    async with SessionFactory() as session:
        context = await authentication.resolve_auth_context(claims(), session)
    assert context.roles == frozenset(roles)
    assert context.scopes == IOS_READ_SCOPES | ({"invoices:write"} if can_write else set())
    assert context.client_id == "iaerp-ios"


async def test_ios_same_subject_keeps_writer_and_reader_tenants_separate(monkeypatch):
    monkeypatch.setattr(authentication.settings, "AUTH_MODE", "oidc")
    await membership(TENANT_A, ["billing"])
    await membership(TENANT_B, ["viewer"])
    for organization, tenant, writer in [
        ("tenant-a", TENANT_A, True),
        ("tenant-b", TENANT_B, False),
    ]:
        async with SessionFactory() as session:
            context = await authentication.resolve_auth_context(claims(organization), session)
        assert context.actor_id == str(USER_A)
        assert context.tenant_id == tenant
        assert ("invoices:write" in context.scopes) == writer


async def test_ios_role_never_adds_scopes_missing_from_the_token(monkeypatch):
    monkeypatch.setattr(authentication.settings, "AUTH_MODE", "oidc")
    async with SessionFactory() as session:
        context = await authentication.resolve_auth_context(claims(scope="context:read"), session)
    assert context.scopes == {"context:read"}


@pytest.mark.parametrize(
    "overrides",
    [
        {"azp": "iaerp-ios", "client_id": "iaerp-web"},
        {"azp": "iaerp-web", "client_id": "iaerp-ios"},
        {"azp": 42, "client_id": "iaerp-ios"},
        {"aud": authentication.settings.OIDC_MCP_AUDIENCE},
        {
            "aud": [
                authentication.settings.OIDC_API_AUDIENCE,
                authentication.settings.OIDC_MCP_AUDIENCE,
            ]
        },
        {"aud": "unrelated-api"},
    ],
)
async def test_ios_cannot_escape_policy_through_client_claims_or_mcp(monkeypatch, overrides):
    monkeypatch.setattr(authentication.settings, "AUTH_MODE", "oidc")
    async with SessionFactory() as session:
        with pytest.raises(HTTPException) as error:
            await authentication.resolve_auth_context(claims(**overrides), session)
    assert error.value.status_code == 403


@pytest.mark.parametrize(
    "identity", [{"azp": None, "client_id": "iaerp-ios"}, {"client_id": "iaerp-ios"}]
)
async def test_ios_policy_recognizes_either_consistent_signed_client_claim(monkeypatch, identity):
    monkeypatch.setattr(authentication.settings, "AUTH_MODE", "oidc")
    await membership(TENANT_A, ["viewer"])
    async with SessionFactory() as session:
        context = await authentication.resolve_auth_context(claims(**identity), session)
    assert "invoices:write" not in context.scopes


async def test_ios_human_cannot_be_reclassified_as_a_service_account(monkeypatch):
    monkeypatch.setattr(authentication.settings, "AUTH_MODE", "oidc")
    await membership(TENANT_A, ["viewer"])
    async with SessionFactory() as session, session.begin():
        session.add(
            ServiceAccount(
                tenant_id=TENANT_B,
                client_id="iaerp-ios",
                name="Synthetic collision",
                secret_hash="synthetic-unused",
                scopes=["invoices:write"],
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
    async with SessionFactory() as session:
        context = await authentication.resolve_auth_context(claims(), session)
    assert context.actor_type == "USER"
    assert context.tenant_id == TENANT_A
    assert "invoices:write" not in context.scopes


async def test_ios_membership_downgrade_and_revocation_apply_to_the_same_valid_jwt(
    client, monkeypatch
):
    sign = oidc_signer(monkeypatch)
    token = sign(claims())
    headers = {"Authorization": f"Bearer {token}"}
    initial = await client.get("/api/v1/context", headers=headers)
    assert initial.status_code == 200
    assert "invoices:write" in initial.json()["scopes"]

    await membership(TENANT_A, ["viewer"])
    downgraded = await client.get("/api/v1/context", headers=headers)
    assert downgraded.status_code == 200
    assert downgraded.json()["roles"] == ["viewer"]
    assert "invoices:write" not in downgraded.json()["scopes"]

    await membership(TENANT_A, ["owner"], active=False)
    revoked = await client.get("/api/v1/context", headers=headers)
    assert revoked.status_code == 404
    assert revoked.json()["detail"] == "Membership not found"


async def test_ios_draft_writer_can_create_one_audited_draft_but_reader_post_is_denied(
    client, monkeypatch
):
    setup = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters = await _setup_billing_masters(client, setup, key_prefix="ios-native")
    await membership(TENANT_A, ["billing"])
    await membership(TENANT_B, ["viewer"])
    sign = oidc_signer(monkeypatch)
    writer = sign(claims())
    payload = _invoice_payload(masters)
    headers = {"Authorization": f"Bearer {writer}", "Idempotency-Key": "ios-native-draft-0001"}
    created = await client.post("/api/v1/invoices", headers=headers, json=payload)
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "DRAFT"
    assert created.json()["total"] == "115.00"
    repeat = await client.post("/api/v1/invoices", headers=headers, json=payload)
    assert repeat.status_code == 201
    assert repeat.json()["id"] == created.json()["id"]

    reader = sign(claims("tenant-b"))
    denied = await client.post(
        "/api/v1/invoices",
        headers={"Authorization": f"Bearer {reader}", "Idempotency-Key": "ios-reader-denied-0001"},
        json=payload,
    )
    assert denied.status_code == 403
    assert "invoices:write" in denied.json()["detail"]
    foreign = await client.get(
        f"/api/v1/invoices/{created.json()['id']}",
        headers={"Authorization": f"Bearer {reader}"},
    )
    assert foreign.status_code == 404
    async with SessionFactory() as session:
        assert await session.scalar(select(func.count()).select_from(SalesDocument)) == 1
        drafts = await session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action == "invoice.draft_created")
        )
        assert drafts == 1


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("POST", "issue", None),
        ("POST", "email", {"recipient": "synthetic@example.invalid"}),
        ("POST", "void", {"reason": "Synthetic void"}),
        ("POST", "archive", {"reason": "Synthetic archive"}),
        ("POST", "duplicate", None),
        ("PUT", "collection-policy", {"enabled": True}),
        ("PUT", "analytic-assignments", {"analyticValueIds": []}),
    ],
)
async def test_ios_direct_mutations_other_than_draft_never_enter_a_unit_of_work(
    client, monkeypatch, method, path, body
):
    import app.api.router as api

    async def forbidden_unit_of_work(*args, **kwargs):
        pytest.fail("Native policy must reject before any business mutation/callback")

    monkeypatch.setattr(api, "execute_idempotent", forbidden_unit_of_work)
    token = oidc_signer(monkeypatch)(claims())
    response = await client.request(
        method,
        f"/api/v1/invoices/cccccccc-cccc-4ccc-8ccc-cccccccccccc/{path}",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "ios-forbidden-operation"},
        json=body,
    )
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "Native iOS access permits invoice drafts and preview only"
    async with SessionFactory() as session:
        assert await session.scalar(select(func.count()).select_from(IdempotencyRecord)) == 0
        assert await session.scalar(select(func.count()).select_from(AuditEvent)) == 0


async def test_ios_preview_remains_read_only_for_reader(client, monkeypatch):
    await membership(TENANT_A, ["viewer"])
    token = oidc_signer(monkeypatch)(claims())
    response = await client.post(
        "/api/v1/invoices/preview",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "issueDate": "2026-07-04",
            "lines": [
                {
                    "description": "Synthetic",
                    "quantity": "1",
                    "unitPrice": "100.00",
                    "taxCode": "4",
                },
            ],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["total"] == "115.00"
    async with SessionFactory() as session:
        assert await session.scalar(select(func.count()).select_from(SalesDocument)) == 0


async def test_existing_web_scope_policy_is_unchanged(monkeypatch):
    monkeypatch.setattr(authentication.settings, "AUTH_MODE", "oidc")
    await membership(TENANT_A, ["viewer"])
    async with SessionFactory() as session:
        context = await authentication.resolve_auth_context(claims(azp="iaerp-web"), session)
    assert context.scopes == frozenset(OVERBROAD_SCOPES.split())
