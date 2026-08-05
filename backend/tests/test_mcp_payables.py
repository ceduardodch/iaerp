"""Contrato MCP de CxP: catálogo, casos de uso e igualdad con REST."""

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
