"""Complete monthly reads and the read-only dashboard, using synthetic tenant data."""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.db.session import SessionFactory
from app.models.billing import SalesDocument
from app.models.masters import EmissionPoint
from app.models.receivables import Movement, Receivable
from app.services import receivables
from tests.test_billing_api import TENANT_A, TENANT_B, auth, token_for
from tests.test_ios_permissions import claims, membership, oidc_signer
from tests.test_receivables_collections_breakdown import _seed_movements
from tests.test_receivables_service import (
    _create_authorized_invoice_stub,
    _create_party,
    _create_receivable,
)


async def test_invoice_filters_totals_and_paging_share_the_whole_dataset(client):
    async with SessionFactory() as session, session.begin():
        party = await _create_party(session, tenant_id=TENANT_A, suffix="first")
        seed = await _create_authorized_invoice_stub(
            session, tenant_id=TENANT_A, party_id=party.id, total=Decimal("1.10")
        )
        seed.issue_date = date(2025, 7, 4)
        seed.sequential = "000500000"
        point = EmissionPoint(
            tenant_id=TENANT_A, establishment_id=seed.establishment_id, code="002"
        )
        session.add(point)
        await session.flush()
        rows = []
        for index in range(106):
            invoice = SalesDocument(
                tenant_id=TENANT_A,
                establishment_id=seed.establishment_id,
                emission_point_id=point.id if index == 101 else seed.emission_point_id,
                party_id=party.id,
                document_type="CREDIT_NOTE" if index == 103 else "INVOICE",
                sequential=f"{0 if index == 101 else index:09}",
                issue_date=date(2026, 7, 1 if index < 60 else 31),
                status="AUTHORIZED" if index == 102 else "DRAFT",
                currency="USD",
                subtotal=Decimal("1.10"),
                tax_total=Decimal("0.00"),
                total=Decimal("1.10"),
                fiscal_policy_version="synthetic",
                archived_at=datetime.now(UTC) if index >= 104 else None,
            )
            rows.append(invoice)
        session.add_all(rows)
        await session.flush()
        match_id = str(rows[101].id)
        await _create_receivable(
            session,
            tenant_id=TENANT_A,
            party_id=party.id,
            sales_document_id=rows[102].id,
            original_amount=Decimal("1.10"),
            installment_amounts=[Decimal("1.10")],
            due_date=date(2026, 8, 1),
        )
        seed_key = seed.access_key
        other_party = await _create_party(session, tenant_id=TENANT_B, suffix="other")
        await _create_authorized_invoice_stub(
            session, tenant_id=TENANT_B, party_id=other_party.id, total=Decimal("99.99")
        )
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["invoices:read"])
    url = "/api/v1/invoices/months"
    months = await client.get(url, headers=auth(token))
    assert months.status_code == 200, months.text
    assert months.json() == [
        {"month": "2026-07", "count": 103, "total": "113.30", "currency": "USD"},
        {"month": "2025-07", "count": 1, "total": "1.10", "currency": "USD"},
    ]
    params = {"limit": 50}
    found = []
    while True:
        page = await client.get(f"{url}/2026-07", headers=auth(token), params=params)
        assert page.status_code == 200, page.text
        data = page.json()
        found += data["items"]
        if data["nextCursor"] is None:
            break
        assert len(data["items"]) == 50
        params["cursor"] = data["nextCursor"]
    assert len({r["id"] for r in found}) == len(found) == 103
    assert [(r["issueDate"], r["id"]) for r in found] == sorted(
        [(r["issueDate"], r["id"]) for r in found], reverse=True
    )
    assert all(r["customerName"] == "Cliente first" for r in found)
    assert {r["collectionStatus"] for r in found} == {None, "OPEN"}
    number = "900-002-000000000"
    result = await client.get(f"{url}/2026-07", params={"q": number}, headers=auth(token))
    assert [(r["id"], r["number"]) for r in result.json()["items"]] == [(match_id, number)]
    groups = await client.get(url, params={"q": number}, headers=auth(token))
    assert groups.json() == [{"month": "2026-07", "count": 1, "total": "1.10", "currency": "USD"}]
    for filters, expected in [
        ({"q": seed_key}, ["2025-07"]),
        ({"status": "AUTHORIZED"}, ["2026-07", "2025-07"]),
        ({"partyId": str(uuid.uuid4())}, []),
    ]:
        result = await client.get(url, params=filters, headers=auth(token))
        assert [g["month"] for g in result.json()] == expected
    for path, filters in [("2026-13", {}), ("2026-07", {"cursor": "bad"}), ("0000-01", {})]:
        assert (
            await client.get(f"{url}/{path}", params=filters, headers=auth(token))
        ).status_code == 422


async def test_monthly_amounts_and_pages_respect_currency(client):
    async with SessionFactory() as session, session.begin():
        party = await _create_party(session, tenant_id=TENANT_A, suffix="currency")
        for currency, amount in [("USD", "2.01"), ("EUR", "6.10")]:
            doc = await _create_authorized_invoice_stub(
                session, tenant_id=TENANT_A, party_id=party.id, total=Decimal(amount)
            )
            doc.currency = currency
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["invoices:read"])
    base = "/api/v1/invoices/months"
    groups = (await client.get(base, headers=auth(token))).json()
    assert [(g["currency"], g["count"], g["total"]) for g in groups] == [
        ("EUR", 1, "6.10"),
        ("USD", 1, "2.01"),
    ]
    for group in groups:
        page = await client.get(
            f"{base}/{group['month']}", headers=auth(token), params={"currency": group["currency"]}
        )
        assert page.status_code == 200
        items = page.json()["items"]
        assert [(r["currency"], r["total"]) for r in items] == [(group["currency"], group["total"])]


async def test_overview_matches_web_for_partial_overdue_and_reversed_payments(client, monkeypatch):
    today = date(2026, 9, 3)
    monkeypatch.setattr(receivables, "today_in_fiscal_timezone", lambda: today)
    movements = await _seed_movements(
        suffix="r1",
        entries=[
            ("PAYMENT", Decimal("87.25"), today),
            ("RETENTION", Decimal("12.75"), today),
            ("DISCOUNT", Decimal("0.50"), today),
            ("PAYMENT", Decimal("200.00"), today),
            ("PAYMENT", Decimal("20.00"), date(2026, 8, 31)),
        ],
    )
    async with SessionFactory() as session, session.begin():
        original = movements[3]
        session.add(
            Movement(
                tenant_id=TENANT_A,
                receivable_id=original.receivable_id,
                installment_id=original.installment_id,
                movement_type="REVERSAL",
                amount=original.amount,
                effective_date=today,
                reversed_movement_id=original.id,
                actor_id="synthetic",
            )
        )
        party = await _create_party(session, tenant_id=TENANT_A, suffix="current")
        document = await _create_authorized_invoice_stub(
            session, tenant_id=TENANT_A, party_id=party.id, total=Decimal("15.00")
        )
        await _create_receivable(
            session,
            tenant_id=TENANT_A,
            party_id=party.id,
            sales_document_id=document.id,
            original_amount=Decimal("15.00"),
            installment_amounts=[Decimal("15.00")],
            due_date=today,
        )
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["receivables:read"])
    overview = await client.get("/api/v1/receivables/overview", headers=auth(token))
    assert overview.status_code == 200, overview.text
    data = overview.json()
    assert data == {
        "outstanding": "894.50",
        "overdue": "879.50",
        "collectedThisMonth": "100.00",
        "asOf": str(today),
        "currency": "USD",
    }
    web = (await client.get("/api/v1/receivables", headers=auth(token))).json()
    assert Decimal(data["outstanding"]) == sum(Decimal(r["openAmount"]) for r in web)
    assert Decimal(data["overdue"]) == sum(
        Decimal(r["openAmount"]) for r in web if r["status"] == "OVERDUE"
    )
    history = (
        await client.get("/api/v1/receivables/collections/monthly", headers=auth(token))
    ).json()
    assert data["collectedThisMonth"] == history["months"][-1]["settledAmount"]
    b = await token_for(client, "b@iaerp.local", TENANT_B, ["receivables:read"])
    empty = (await client.get("/api/v1/receivables/overview", headers=auth(b))).json()
    assert {empty[k] for k in ("outstanding", "overdue", "collectedThisMonth")} == {"0.00"}


async def test_overview_with_foreign_currency_does_not_label_mixed_totals_usd(client):
    movements = await _seed_movements(
        suffix="fx", entries=[("PAYMENT", Decimal("10"), date(2026, 8, 1))]
    )
    async with SessionFactory() as session, session.begin():
        account = await session.get(Receivable, movements[0].receivable_id)
        account.currency = "EUR"
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["receivables:read"])
    response = await client.get("/api/v1/receivables/overview", headers=auth(token))
    assert response.status_code == 409
    assert "outstanding" not in response.json()


@pytest.mark.parametrize(
    "role,may_read",
    [
        ("owner", True),
        ("admin", True),
        ("collections", True),
        ("auditor", True),
        ("billing", False),
        ("viewer", False),
        ("unknown", False),
    ],
)
async def test_mobile_overview_needs_signed_scope_and_permitted_membership(
    client,
    monkeypatch,
    role,
    may_read,
):
    sign = oidc_signer(monkeypatch)
    await membership(TENANT_A, [role])
    for scope, expected in [("invoices:read", 403), ("receivables:read", 200 if may_read else 403)]:
        headers = auth(sign(claims(scope=scope)))
        result = await client.get("/api/v1/receivables/overview", headers=headers)
        assert result.status_code == expected, result.text
    for path in ["receivables", "receivables/aging", "receivables/collections/monthly"]:
        assert (await client.get(f"/api/v1/{path}", headers=headers)).status_code == 403
