"""Contrato MCP de CxP: catálogo, casos de uso e igualdad con REST."""

from app.schemas.payables import PayableCreate
from tests.test_billing_api import TENANT_A, auth, token_for
from tests.test_mcp_receivables import (
    _enable_automation_writes,
    mcp_lifespan,
    mcp_session,
)


async def test_mcp_payable_create_and_payment_are_visible_through_rest(client) -> None:
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["payables:read", "payables:write", "automation:write"],
    )
    await _enable_automation_writes(client, token, "mcp-payables-enable-0001")

    async with mcp_lifespan():
        async with mcp_session(token) as session:
            tools = {tool.name for tool in (await session.list_tools()).tools}
            assert {
                "payables.list",
                "payables.create",
                "payables.schedule_payment",
                "payables.record_payment",
            }.issubset(tools)
            created = await session.call_tool(
                "payables.create",
                {
                    "payable": {
                        "supplierName": "Proveedor MCP",
                        "description": "Servicio operativo",
                        "category": "Servicios",
                        "issueDate": "2026-01-12",
                        "dueDate": "2026-01-31",
                        "total": "75.00",
                        "paymentTiming": "PAY_LATER",
                    },
                    "idempotencyKey": "mcp-payable-create-0001",
                },
            )
            assert created.isError is False, created.content
            payable_id = created.structuredContent["id"]
            assert created.structuredContent["foreignDigitalService"] is False

            imported = {
                "description": "Servicio digital de ejemplo",
                "issueDate": "2026-01-12",
                "total": "36.00",
                "foreignDigitalService": True,
            }
            imported_key = "mcp-import-service-example"
            overseas = await session.call_tool(
                "payables.create", {"payable": imported, "idempotencyKey": imported_key}
            )
            assert not overseas.isError, overseas.content
            assert overseas.structuredContent["foreignDigitalService"] is True
            replay = await client.post(
                "/api/v1/payables", headers=auth(token, imported_key), json=imported
            )
            assert replay.status_code == 201 and replay.json() == overseas.structuredContent
            conflict = await client.post(
                "/api/v1/payables",
                headers=auth(token, imported_key),
                json={**imported, "foreignDigitalService": False},
            )
            assert conflict.status_code == 409

            paid = await session.call_tool(
                "payables.record_payment",
                {
                    "payableId": payable_id,
                    "payment": {
                        "amount": "25.00",
                        "paymentDate": "2026-01-20",
                        "method": "TRANSFER",
                        "reference": "MCP-PAGO-001",
                    },
                    "idempotencyKey": "mcp-payable-payment-0001",
                },
            )
            assert paid.isError is False, paid.content
            assert paid.structuredContent["openAmount"] == "50.00"

        rest = await client.get(
            f"/api/v1/payables/{payable_id}", headers=auth(token)
        )
        assert rest.status_code == 200, rest.text
        assert rest.json()["status"] == "PARTIAL"
        assert rest.json()["openAmount"] == "50.00"


def test_manual_create_reuses_the_payload_stored_before_import_classification():
    legacy = {"description": "Ejemplo", "issueDate": "2026-01-12", "total": "15.00"}
    manual = PayableCreate.model_validate(legacy)
    old_payload = manual.model_dump(mode="json")
    del old_payload["foreignDigitalService"]
    assert manual.idempotency_payload() == old_payload
    explicit_local = PayableCreate.model_validate({**legacy, "foreignDigitalService": False})
    assert explicit_local.idempotency_payload() == old_payload
