"""HTTP de ``/payroll/*``: scopes, idempotencia y flujo completo.

Los casos de negocio (409/422/404, prorrateo, filtros por tenant) ya están
cubiertos en ``test_payroll_employees_service.py`` y
``test_payroll_periods_service.py``; aquí solo se verifica la capa HTTP:
que las rutas existan, exijan el scope correcto y que las escrituras sean
idempotentes vía ``Idempotency-Key``.
"""

from decimal import Decimal

from app.db.session import SessionFactory
from app.models.payroll import PayrollEmployee
from tests.test_billing_api import TENANT_A, auth, token_for


def _employee_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "fullName": "Ana Torres",
        "identificationNumber": "1712345678",
        "sueldoMensual": "1000.00",
        "fechaIngreso": "2020-01-01",
    }
    payload.update(overrides)
    return payload


async def test_create_employee_requires_write_scope(client) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["payroll:read"])
    response = await client.post(
        "/api/v1/payroll/employees",
        headers=auth(token, "payroll-emp-scope-0001"),
        json=_employee_payload(),
    )
    assert response.status_code == 403, response.text


async def test_list_employees_requires_read_scope(client) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["payroll:write"])
    response = await client.get("/api/v1/payroll/employees", headers=auth(token))
    assert response.status_code == 403, response.text


async def test_create_employee_returns_201_and_is_listed(client) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["payroll:read", "payroll:write"])
    create = await client.post(
        "/api/v1/payroll/employees",
        headers=auth(token, "payroll-emp-create-0001"),
        json=_employee_payload(),
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["fullName"] == "Ana Torres"
    assert body["active"] is True

    listing = await client.get("/api/v1/payroll/employees", headers=auth(token))
    assert listing.status_code == 200, listing.text
    assert [item["id"] for item in listing.json()] == [body["id"]]


async def test_create_employee_idempotency_key_replay_does_not_duplicate(client) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["payroll:read", "payroll:write"])
    payload = _employee_payload(identificationNumber="1798765432")

    first = await client.post(
        "/api/v1/payroll/employees",
        headers=auth(token, "payroll-emp-idem-0001"),
        json=payload,
    )
    assert first.status_code == 201, first.text

    second = await client.post(
        "/api/v1/payroll/employees",
        headers=auth(token, "payroll-emp-idem-0001"),
        json=payload,
    )
    assert second.status_code == 201, second.text
    assert first.json() == second.json()

    async with SessionFactory() as session:
        from sqlalchemy import select

        rows = list(
            (
                await session.scalars(
                    select(PayrollEmployee).where(
                        PayrollEmployee.tenant_id == TENANT_A,
                        PayrollEmployee.identification_number == "1798765432",
                    )
                )
            ).all()
        )
    assert len(rows) == 1


async def test_create_employee_duplicate_identification_returns_409_via_api(client) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["payroll:read", "payroll:write"])
    payload = _employee_payload(identificationNumber="1755555555")

    first = await client.post(
        "/api/v1/payroll/employees",
        headers=auth(token, "payroll-emp-dup-0001"),
        json=payload,
    )
    assert first.status_code == 201, first.text

    second = await client.post(
        "/api/v1/payroll/employees",
        headers=auth(token, "payroll-emp-dup-0002"),
        json=payload,
    )
    assert second.status_code == 409, second.text


async def test_update_employee_via_api(client) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["payroll:read", "payroll:write"])
    create = await client.post(
        "/api/v1/payroll/employees",
        headers=auth(token, "payroll-emp-upd-0001"),
        json=_employee_payload(identificationNumber="1711111111"),
    )
    employee_id = create.json()["id"]

    update = await client.put(
        f"/api/v1/payroll/employees/{employee_id}",
        headers=auth(token, "payroll-emp-upd-0002"),
        json=_employee_payload(identificationNumber="1711111111", sueldoMensual="1500.00"),
    )
    assert update.status_code == 200, update.text
    assert update.json()["sueldoMensual"] == "1500.00"


async def test_terminate_employee_via_api(client) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["payroll:read", "payroll:write"])
    create = await client.post(
        "/api/v1/payroll/employees",
        headers=auth(token, "payroll-emp-term-0001"),
        json=_employee_payload(identificationNumber="1722222222"),
    )
    employee_id = create.json()["id"]

    terminate = await client.post(
        f"/api/v1/payroll/employees/{employee_id}/terminate",
        headers=auth(token, "payroll-emp-term-0002"),
        json={"fechaSalida": "2026-06-15"},
    )
    assert terminate.status_code == 200, terminate.text
    assert terminate.json()["active"] is False

    listing = await client.get("/api/v1/payroll/employees", headers=auth(token))
    assert employee_id not in [item["id"] for item in listing.json()]


async def test_generate_draft_period_requires_write_scope(client) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["payroll:read"])
    response = await client.post(
        "/api/v1/payroll/periods/draft",
        headers=auth(token, "payroll-period-scope-0001"),
        json={"anio": 2026, "mes": 6},
    )
    assert response.status_code == 403, response.text


async def test_generate_draft_period_and_list_entries(client) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["payroll:read", "payroll:write"])
    await client.post(
        "/api/v1/payroll/employees",
        headers=auth(token, "payroll-period-emp-0001"),
        json=_employee_payload(identificationNumber="1733333333"),
    )

    draft = await client.post(
        "/api/v1/payroll/periods/draft",
        headers=auth(token, "payroll-period-draft-0001"),
        json={"anio": 2026, "mes": 6},
    )
    assert draft.status_code == 200, draft.text
    period_body = draft.json()
    assert period_body["status"] == "DRAFT"

    periods_listing = await client.get("/api/v1/payroll/periods", headers=auth(token))
    assert periods_listing.status_code == 200, periods_listing.text
    assert period_body["id"] in [item["id"] for item in periods_listing.json()]

    entries = await client.get(
        f"/api/v1/payroll/periods/{period_body['id']}/entries", headers=auth(token)
    )
    assert entries.status_code == 200, entries.text
    assert len(entries.json()) == 1
    assert Decimal(entries.json()[0]["liquido"]) == Decimal("1112.30")


async def test_draft_period_regeneration_after_approval_returns_409_via_api(client) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["payroll:read", "payroll:write"])
    await client.post(
        "/api/v1/payroll/employees",
        headers=auth(token, "payroll-period-appr-emp-0001"),
        json=_employee_payload(identificationNumber="1744444444"),
    )
    draft = await client.post(
        "/api/v1/payroll/periods/draft",
        headers=auth(token, "payroll-period-appr-draft-0001"),
        json={"anio": 2026, "mes": 7},
    )
    period_id = draft.json()["id"]

    approve = await client.post(
        f"/api/v1/payroll/periods/{period_id}/approve",
        headers=auth(token, "payroll-period-appr-approve-0001"),
        json={},
    )
    assert approve.status_code == 200, approve.text
    assert approve.json()["status"] == "APPROVED"

    regenerate = await client.post(
        "/api/v1/payroll/periods/draft",
        headers=auth(token, "payroll-period-appr-draft-0002"),
        json={"anio": 2026, "mes": 7},
    )
    assert regenerate.status_code == 409, regenerate.text
