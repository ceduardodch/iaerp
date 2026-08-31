"""Contrato MCP del flujo diario de reportes recibidos del SRI."""

import pytest

from app.services import storage
from app.services.tax import evidence as evidence_service
from tests.test_billing_api import TENANT_A, token_for
from tests.test_mcp_receivables import (
    _enable_automation_writes,
    mcp_lifespan,
    mcp_session,
)
from tests.test_tax_received_reports import (
    REPORT_MONTH,
    REPORT_YEAR,
    _report,
    _upload,
)


@pytest.fixture
def stored_objects(monkeypatch) -> dict[str, bytes]:
    objects: dict[str, bytes] = {}

    async def upload(*, object_key: str, data: bytes, **_kwargs) -> None:
        objects[object_key] = data

    async def download(*, object_key: str) -> bytes:
        return objects[object_key]

    monkeypatch.setattr(evidence_service.storage, "upload_private_object", upload)
    monkeypatch.setattr(storage, "download_artifact", download)
    return objects


async def test_mcp_tax_catalog_is_filtered_by_scope(client) -> None:
    without_tax = await token_for(client, "a@iaerp.local", TENANT_A, ["context:read"])
    with_tax = await token_for(client, "a@iaerp.local", TENANT_A, ["tax:write"])

    async with mcp_lifespan():
        async with mcp_session(without_tax) as session:
            tools = await session.list_tools()
            assert "tax.process_received_reports" not in {tool.name for tool in tools.tools}

        async with mcp_session(with_tax) as session:
            tools = await session.list_tools()
            assert "tax.process_received_reports" in {tool.name for tool in tools.tools}


async def test_mcp_tax_process_requires_kill_switch_and_reuses_rest_case(
    client,
    stored_objects,
) -> None:
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["tax:write", "automation:write"],
    )
    evidence_id = await _upload(client, token, "facturas.txt", _report())
    arguments = {
        "evidenceIds": [evidence_id],
        "reportYear": REPORT_YEAR,
        "reportMonth": REPORT_MONTH,
        "idempotencyKey": "mcp-tax-reports-20260830",
    }

    async with mcp_lifespan():
        async with mcp_session(token) as session:
            blocked = await session.call_tool("tax.process_received_reports", arguments)
            assert blocked.isError is True
            assert "Automation writes are disabled" in blocked.content[0].text

        await _enable_automation_writes(client, token, "mcp-tax-enable-0001")

        async with mcp_session(token) as session:
            processed = await session.call_tool("tax.process_received_reports", arguments)
            replay = await session.call_tool("tax.process_received_reports", arguments)

    assert processed.isError is False
    assert replay.isError is False
    assert replay.structuredContent == processed.structuredContent
    body = processed.structuredContent
    assert body["reportYear"] == REPORT_YEAR
    assert body["reportMonth"] == REPORT_MONTH
    assert body["evidenceCount"] == 1
    assert body["listedRows"] == 1
    assert body["recoveryJob"]["status"] == "QUEUED"


async def test_mcp_tax_rejects_report_from_another_month(client, stored_objects) -> None:
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["tax:write", "automation:write"],
    )
    evidence_id = await _upload(client, token, "facturas.txt", _report())
    await _enable_automation_writes(client, token, "mcp-tax-enable-date")

    async with mcp_lifespan(), mcp_session(token) as session:
        result = await session.call_tool(
            "tax.process_received_reports",
            {
                "evidenceIds": [evidence_id],
                "reportYear": 2026,
                "reportMonth": 7,
                "idempotencyKey": "mcp-tax-wrong-date-0001",
            },
        )

    assert result.isError is True
    assert "Every report row must match reportYear and reportMonth" in result.content[0].text


async def test_mcp_tax_contract_is_closed_and_rejects_tenant_override(client) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["tax:write"])

    async with mcp_lifespan(), mcp_session(token) as session:
        tools = await session.list_tools()
        tool = next(item for item in tools.tools if item.name == "tax.process_received_reports")
        result = await session.call_tool(
            tool.name,
            {
                "evidenceIds": ["00000000-0000-0000-0000-000000000001"],
                "reportYear": REPORT_YEAR,
                "reportMonth": REPORT_MONTH,
                "idempotencyKey": "mcp-tax-extra-field-0001",
                "tenantId": str(TENANT_A),
            },
        )

    assert tool.inputSchema["additionalProperties"] is False
    assert tool.outputSchema["additionalProperties"] is False
    recovery_schema = tool.outputSchema["$defs"]["TaxXmlRecoveryJobRead"]
    item_schema = tool.outputSchema["$defs"]["TaxXmlRecoveryItemRead"]
    assert recovery_schema["additionalProperties"] is False
    assert item_schema["additionalProperties"] is False
    assert "documentId" in item_schema["properties"]
    assert "fiscal_document_id" not in item_schema["properties"]
    assert result.isError is True
    assert "Extra inputs are not permitted" in result.content[0].text
